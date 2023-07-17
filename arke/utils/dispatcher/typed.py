# SPDX-License-Identifier: MIT

import asyncio
import dataclasses
import logging
import traceback
import typing as t
from collections import defaultdict

import typing_extensions as te

from ...internal.async_utils import gather_optionally

__all__ = ("Event", "ExceptionEvent", "TypedDispatcher",)

_log = logging.getLogger(__name__)

_EventT = t.TypeVar("_EventT", bound="Event")
_NoneCoroutine = t.Coroutine[t.Any, t.Any, None]

GenericTypedDispatcherListener = t.Callable[[_EventT], _NoneCoroutine]
GenericTypedDispatcherWaitForCheck = t.Callable[[_EventT], bool]

TypedDispatcherListener = GenericTypedDispatcherListener["Event"]
TypedDispatcherWaitForCheck = GenericTypedDispatcherWaitForCheck["Event"]
TypedDispatcherWaitForPair = tuple[GenericTypedDispatcherWaitForCheck["Event"], asyncio.Future["Event"]]

class Event:
    """The base event class for the typed dispatcher."""
    __dispatches__: tuple[type["Event"], ...] = ()

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls.__dispatches__ = tuple(base for base in cls.__mro__ if issubclass(base, Event))

    @classmethod
    def dispatches(cls):
        """The event classes this event also dispatches."""
        return cls.__dispatches__
    
    @classmethod
    def from_raw_event(cls: type[te.Self], raw: t.Any) -> te.Self:
        """An abstract method that processes an event from a raw event.
        
        This has been provided for possible setups where a typed dispatcher is translating
        event dispatches from a raw dispatcher.
        """
        raise NotImplementedError


@dataclasses.dataclass(kw_only=True)
class ExceptionEvent(t.Generic[_EventT], Event):
    """The base exception event for failed events."""
    exception: Exception
    failed_event: _EventT 
    failed_listener: GenericTypedDispatcherListener[_EventT]


class TypedDispatcher:
    """A dispatcher that uses a well-defined event class instead of a raw type."""

    def __init__(self):
        self._listeners: defaultdict[type[Event], list[TypedDispatcherListener]] = defaultdict(list)
        self._waiters: defaultdict[type[Event], list[TypedDispatcherWaitForPair]] = defaultdict(list)

    def add_listener(self, listener: GenericTypedDispatcherListener[_EventT], event: type[_EventT]):
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

        if t.TYPE_CHECKING:
            listener = t.cast(TypedDispatcherListener, listener)

        self._listeners[event].append(listener)

        _log.debug("Listener %s has been added to %s.", listener.__name__, event)

    def remove_listener(self, listener: GenericTypedDispatcherListener[_EventT], event: type[_EventT]):
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

    # currently, type var tuples cannot have bounds because the pep decided to not define the specifications.
    # this limits our abilities to ideally type this method so it's fully generic.
    def listen_to(self, *events: Event) -> t.Callable[[TypedDispatcherListener], TypedDispatcherListener]:
        """A decorator that registers a function as a listener to one or more events.

        Args:
            *events:
                Every event to register this function under.

        Returns:
            A wrapper that adds the function as a listener.

        Raises:
            TypeError: The function is not a coroutine function.
        """
        def wrapper(func):
            for event in events:
                self.add_listener(func, type(event))
            return func

        return wrapper

    def wait_for(self, event: type[_EventT], *, check: t.Optional[GenericTypedDispatcherWaitForCheck[_EventT]] = None, timeout: t.Optional[float] = 120):
        """Waits for an event to be dispatched.

        Args:
            event: The event to wait for.
            check:
                A function that checks the dispatched event. This can be used to sort events.
                If set to ``None``, a check that defaults to ``True`` is used instead.
            timeout:
                How long the event should be waited for.
                If set to ``None``, the event will be waited for indefinitely.
        
        Returns:
            The metadata of the event dispatcher or nothing if the event wasn't dispatched.
        """
        if check is None:
            check = lambda _: True

        if t.TYPE_CHECKING:
            check = t.cast(TypedDispatcherWaitForCheck, check)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pair = (check, future)

        self._waiters[event].append(pair)

        _log.info("Waiting for event %s with timeout %s.", event, timeout)

        try:
            return asyncio.wait_for(future, timeout)
        except asyncio.CancelledError:
            self._waiters[event].remove(pair)

    async def _run_listener(self, listener: GenericTypedDispatcherListener[_EventT], event: _EventT):
        try:
            await listener(event)
        except asyncio.CancelledError:
            _log.info("Listener %s for event %s has been cancelled.", listener.__name__, event)
        except Exception as e:
            if isinstance(event, ExceptionEvent):
                _log.error(
                    "An exception occured when running exception event %s!\n%s", 
                    event, 
                    traceback.format_exception(type(e), e, e.__traceback__)
                )
            else:
                exc_event = ExceptionEvent(exception=e, failed_event=event, failed_listener=listener)
                self.dispatch(exc_event)

    def dispatch(self, event: Event):
        """Dispatches an event.

        If there are any subclasses of the event class, then those events will also be dispatched.

        If you want each listener to be waited for, please await the return of this method.
        Otherwise, treat this like a normal sync method.

        Args:
            event: The event to dispatch.

        Returns:
            Either a future with a list of tasks or a completed future.
        """
        event_type = type(event)

        tasks = []
        for dispatch in event_type.dispatches():
            listeners = self._listeners.get(dispatch, [])
            waiters = self._waiters.get(dispatch, [])

            if not listeners and not waiters:
                _log.info("Nothing to dispatch under event %s.", event)

            _log.info(
                "%i listener(s) and %i waiter(s) under event %s will be dispatched.", 
                len(listeners), 
                len(waiters),
                dispatch.__name__,
            )

            for waiter in waiters:
                check, future = waiter
                if not future.done():
                    try:
                        if not check(event):
                            continue
                    except Exception as e:
                        future.set_exception(e)
                    else:
                        waiters.remove(waiter)

            for listener in listeners:
                task = asyncio.create_task(
                    self._run_listener(listener, event), 
                    name=f"arke-dispatcher:{event}->{listener.__name__}"
                )
                tasks.append(task)

        return gather_optionally(*tasks)
