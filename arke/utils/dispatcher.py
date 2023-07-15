import asyncio
import logging
import typing as t
from collections import defaultdict

__all__ = ("RawDispatcher",)

_log = logging.getLogger(__name__)

_T = t.TypeVar("_T")

BaseDispatcherListener = t.Callable[[t.Any], t.Coroutine[t.Any, t.Any, None]]
BaseDispatcherWaitForCheck = t.Callable[[t.Any], bool]
BaseDispatcherWaitForPair = tuple[BaseDispatcherWaitForCheck, asyncio.Future[t.Any]]


def _completed_future():
    loop = asyncio.get_running_loop()

    future = loop.create_future()
    future.set_result(None)
    return future


class RawDispatcher(t.Generic[_T]):
    def __init__(self, event_type: type[_T], /):
        self.event_type: type[_T] = event_type

        self._listeners: defaultdict[_T, list[BaseDispatcherListener]] = defaultdict(
            list
        )
        self._wait_for_callbacks: defaultdict[
            _T, list[BaseDispatcherWaitForPair]
        ] = defaultdict(list)

    def add_listener(self, listener: BaseDispatcherListener, event: _T):
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(
                f"listener must be a coroutine function, not {type(listener)!r}."
            )

        self._listeners[event].append(listener)

        _log.debug("Listener %s has been added to %s.", listener.__name__, event)

    def remove_listener(self, listener: BaseDispatcherListener, event: _T):
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(
                f"listener must be a coroutine function, not {type(listener)!r}."
            )

        listeners = self._listeners[event]

        if listener not in listeners:
            raise ValueError(
                f"Listener {listener.__name__} has not been added to {event}."
            )

        listeners.remove(listener)
        self._listeners[event] = listeners

        _log.debug("Listener %s has been removed from %s.", listener.__name__, event)

    def listen(
        self, event: _T
    ) -> t.Callable[[BaseDispatcherListener], BaseDispatcherListener]:
        def wrapper(func):
            self.add_listener(func, event)
            return func

        return wrapper

    def wait_for(
        self,
        event: _T,
        *,
        check: BaseDispatcherWaitForCheck,
        timeout: t.Optional[float] = 90.0,
    ):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self._wait_for_callbacks[event].append((check, future))

        _log.debug("Waiting for event %s with timeout %f.", event, timeout)

        return asyncio.wait_for(future, timeout)

    def dispatch(self, event: _T, metadata: t.Any):
        listeners = self._listeners.get(event, [])
        wait_fors = self._wait_for_callbacks.get(event, [])

        _log.info(
            "%i listeners and %i wait for futures under %s will be dispatched.",
            len(listeners),
            len(wait_fors),
            event,
        )

        loop = asyncio.get_running_loop()

        for i, (check, future) in enumerate(wait_fors):
            if future.cancelled():
                wait_fors.pop(i)
                continue

            try:
                result = check(metadata)
            except Exception as e:
                future.set_exception(e)
            else:
                if result:
                    future.set_result(event)

            wait_fors.pop(i)

        self._wait_for_callbacks[event] = wait_fors

        tasks = []
        for listener in listeners:
            task = loop.create_task(
                listener(metadata), name=f"arke-dispatcher:{listener.__name__}"
            )
            tasks.append(task)

        if tasks:
            return asyncio.gather(*tasks)
        else:
            return _completed_future()
