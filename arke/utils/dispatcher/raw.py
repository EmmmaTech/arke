# SPDX-License-Identifier: MIT

import asyncio
import logging
import typing as t
from collections import defaultdict

from ...internal.async_utils import gather_optionally

__all__ = ("RawDispatcher",)

_log = logging.getLogger(__name__)

_T = t.TypeVar("_T")
_NoneCoroutine = t.Coroutine[t.Any, t.Any, None]

RawDispatcherListener = t.Callable[[t.Any], _NoneCoroutine]
RawDispatcherEventHandler = t.Callable[[t.Any, _T], _NoneCoroutine]
RawDispatcherWaitForCheck = t.Callable[[t.Any], bool]
RawDispatcherWaitForPair = tuple[RawDispatcherWaitForCheck, asyncio.Future[t.Any]]


# TODO: consider getting rid of this class in favor of the typed dispatcher
class RawDispatcher(t.Generic[_T]):
    """A dispatcher that uses raw event types."""

    def __init__(self, event_type: type[_T], /):
        # TODO: keep?
        self.event_type: type[_T] = event_type

        self._listeners: defaultdict[_T, list[RawDispatcherListener]] = defaultdict(list)
        self._event_handlers: list[RawDispatcherEventHandler[_T]] = []
        self._waiters: defaultdict[_T, list[RawDispatcherWaitForPair]] = defaultdict(list)

    def add_listener(self, listener: RawDispatcherListener, event: _T):
        """Adds a listener under an event.
        
        Args:
            listener:
                The listener to add.
            event:
                The event to add the listener under.
        
        Raises:
            TypeError: The listener is not a coroutine function.
        """
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(f"listener must be a coroutine function, not {type(listener)!r}.")

        self._listeners[event].append(listener)

        _log.debug("Listener %s has been added to %s.", listener.__name__, event)

    def remove_listener(self, listener: RawDispatcherListener, event: _T):
        """Removes a listener from an event.
        
        Args:
            listener:
                The listener to remove.
            event:
                The event to remove the listener from.
        
        Raises:
            TypeError:
                The listener is not a coroutine function or the listener has not been added to the event.
        """
        if not asyncio.iscoroutinefunction(listener):
            raise TypeError(f"listener must be a coroutine function, not {type(listener)!r}.")

        listeners = self._listeners[event]

        if listener not in listeners:
            raise ValueError(f"Listener {listener.__name__} has not been added to {event}.")

        listeners.remove(listener)
        self._listeners[event] = listeners

        _log.debug("Listener %s has been removed from %s.", listener.__name__, event)

    def add_event_handler(self, handler: RawDispatcherEventHandler[_T]):
        """Adds a global event handler to this dispatcher.
        
        Args:
            handler:
                The handler to add.
        
        Raises:
            TypeError: The handler is not a coroutine function.
        """
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"handler must be a coroutine function, not {type(handler)!r}.")

        self._event_handlers.append(handler)

        _log.debug("Event handler %s has been added.", handler.__name__)

    def remove_event_handler(self, handler: RawDispatcherEventHandler[_T]):
        """Removes a global event handler from this dispatcher.
        
        Args:
            handler:
                The handler to remove.
        
        Raises:
            TypeError:
                The handler is not a coroutine function or the handler has not been added to this dispatcher.
        """
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"handler must be a coroutine function, not {type(handler)!r}.")

        if handler not in self._event_handlers:
            raise ValueError(f"Handler {handler.__name__} has not been added.")

        self._event_handlers.append(handler)

        _log.debug("Event handler %s has been removed.", handler.__name__)

    def listen(self, event: _T) -> t.Callable[[RawDispatcherListener], RawDispatcherListener]:
        """A decorator that registers a function as a listener.

        Args:
            event:
                The event to register the function under.

        Returns:
            A wrapper that adds the function as a listener.
        """
        def wrapper(func):
            self.add_listener(func, event)
            return func

        return wrapper

    def handler(self, func: RawDispatcherEventHandler[_T], /):
        """A decorator that registers a function as a global event handler.

        Args:
            func:
                The function to register.

        Returns:
            The registered function.
        """
        self.add_event_handler(func)
        return func

    def wait_for(
        self,
        event: _T,
        *,
        check: RawDispatcherWaitForCheck,
        timeout: t.Optional[float] = 90.0,
    ):
        """Waits for an event to be dispatched.
        
        Args:
            event: The event to wait for.
            check:
                A check that will run when the target event is dispatched.
            timeout:
                How long the event should be waited for.

        Returns:
            The metadata of the event dispatch.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self._waiters[event].append((check, future))

        _log.debug("Waiting for event %s with timeout %f.", event, timeout)

        return asyncio.wait_for(future, timeout)

    def dispatch(self, event: _T, metadata: t.Any):
        """Dispatches an event.
        
        If you want each listener & handler to be waited for, please await the return of this method.
        Otherwise, treat this like a normal sync method.

        Args:
            event: The event to dispatch.
            metadata: The metadata for the dispatched event.

        Returns:
            Either a future with a list of tasks or a completed future.
        """
        listeners = self._listeners.get(event, [])
        handlers = self._event_handlers
        wait_fors = self._waiters.get(event, [])

        if not listeners and not handlers and not wait_fors:
            _log.info("Nothing to dispatch under event %s.", event)
            return

        _log.info(
            "%i listener(s), %i event handler(s), and %i waiter(s) under %s will be dispatched.",
            len(listeners),
            len(handlers),
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

        tasks = []

        for listener in listeners:
            task = loop.create_task(listener(metadata), name=f"arke-dispatcher:{event}->{listener.__name__}")
            tasks.append(task)

        for handler in handlers:
            task = loop.create_task(handler(metadata, event), name=f"arke-dispatcher:{handler.__name__}")
            tasks.append(task)

        return gather_optionally(*tasks)
