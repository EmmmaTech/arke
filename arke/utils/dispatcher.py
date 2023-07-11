#from __future__ import annotations

import abc
import asyncio
import dataclasses
import logging
import traceback
import typing as t
from collections import defaultdict

from .functools import classproperty

__all__ = (
    "Event", 
    "ExceptionEvent", 
    "Dispatcher",
)

_log = logging.getLogger(__name__)

_EventT = t.TypeVar("_EventT", bound="Event")

GenericDispatcherListener = t.Callable[[_EventT], t.Coroutine[t.Any, t.Any, None]]
DispatcherListener = GenericDispatcherListener["Event"]
GenericDispatcherWaitForCheck = t.Callable[[_EventT], bool]
DispatcherWaitForCheck = GenericDispatcherWaitForCheck["Event"]
DispatcherWaitForPair = tuple[DispatcherWaitForCheck, asyncio.Future["Event"]]

def _empty_completed_future():
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    completed.set_result(None)

    return completed

class Event(abc.ABC):
    __dispatches: tuple[type["Event"], ...]

    def __init_subclass__(cls):
        super().__init_subclass__()

        cls.__dispatches = tuple(base for base in cls.mro() if issubclass(base, Event))

    @classproperty
    @classmethod
    def dispatches(cls):
        return cls.__dispatches

Event._Event__dispatches = ()  # pyright: ignore

@dataclasses.dataclass
class ExceptionEvent(Event, t.Generic[_EventT]):
    _: dataclasses.KW_ONLY
    exception: Exception
    listener: GenericDispatcherListener[_EventT]
    event: _EventT

class Dispatcher:
    def __init__(self):
        self._listeners: defaultdict[type[Event], list[DispatcherListener]] = defaultdict(list)
        self._wait_for_callbacks: defaultdict[type[Event], list[DispatcherWaitForPair]] = defaultdict(list)        

    def add_listener(self, listener: GenericDispatcherListener[_EventT], event: type[_EventT]):
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(f"listener must be a coroutine function, not {type(listener)!r}.")

        listener = t.cast(DispatcherListener, listener)
        self._listeners[event].append(listener)

        _log.debug("Listener %s has been added to %s.", listener.__name__, event.__name__)

    def remove_listener(self, listener: GenericDispatcherListener[_EventT], event: type[_EventT]):
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(f"listener must be a coroutine function, not {type(listener)!r}.")

        listeners = self._listeners[event]

        if listener not in listeners:
            raise ValueError(f"Listener {listener.__name__} has not been added to {event.__name__}.")

        listeners.remove(listener)
        self._listeners[event] = listeners

        _log.debug("Listener %s has been removed from %s.", listener.__name__, event.__name__)

    def listen(self, event: type[_EventT]) -> t.Callable[[GenericDispatcherListener[_EventT]], GenericDispatcherListener[_EventT]]:
        def wrapper(func):
            self.add_listener(func, event)
            return func
        return wrapper

    def wait_for(self, event: type[_EventT], *, check: GenericDispatcherWaitForCheck[_EventT], timeout: t.Optional[float] = 90.0):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        check = t.cast(DispatcherWaitForCheck, check)
        self._wait_for_callbacks[event].append((check, future))

        _log.debug("Waiting for event %s with timeout %f.", event.__name__, timeout)

        return asyncio.wait_for(future, timeout)

    async def _run_listener(self, listener: GenericDispatcherListener[_EventT], event: _EventT):
        try:
            await listener(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if type(event) is ExceptionEvent:
                raise e from None
            else:
                _log.info("Listener %s has raised an exception!", listener.__name__)

                exec_event = ExceptionEvent(exception=e, listener=listener, event=event)
                try:
                    await self.dispatch(exec_event, dispatch_subclassed=False)
                except Exception as e:
                    _log.error(
                        "Dispatching an exception event for listener %s has led to the following error: %s",
                        listener.__name__,
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )

    def dispatch(self, event: Event, *, dispatch_subclassed: bool = True):
        event_type = type(event)

        listeners = self._listeners.get(event_type, [])
        wait_fors = self._wait_for_callbacks.get(event_type, [])

        _log.info(
            "%i listeners and %i wait for futures under %s will be dispatched.", 
            len(listeners),
            len(wait_fors),
            event_type.__name__,
        )

        if dispatch_subclassed:
            _log.info("The following events will also be dispatched: %s", event_type.dispatches)

            for event_sub in event_type.dispatches:
                listeners.extend(self._listeners.get(event_sub, []))
                wait_fors.extend(self._wait_for_callbacks.get(event_sub, []))

        for i, (check, future) in enumerate(wait_fors):
            if future.cancelled():
                wait_fors.pop(i)
                continue

            try:
                result = check(event)
            except Exception as e:
                future.set_exception(e)
                wait_fors.pop(i)
            else:
                if result:
                    future.set_result(event)
                wait_fors.pop(i)

        self._wait_for_callbacks[event_type] = wait_fors

        listener_tasks = []
        for listener in listeners:
            listener_task = asyncio.create_task(self._run_listener(listener, event), name=f"arke-dispatcher:{listener.__name__}")
            listener_tasks.append(listener_task)

        if listener_tasks:
            return asyncio.gather(*listener_tasks)

        return _empty_completed_future()
