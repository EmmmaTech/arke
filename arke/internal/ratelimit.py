import asyncio
import logging
import queue

__all__ = ("Lock", "TimePer")

_log = logging.getLogger(__name__)


class Lock(asyncio.Event):
    def __init__(self):
        super().__init__()
        self.set()

    async def __aenter__(self):
        await self.wait()
        return None

    async def __aexit__(self, *_):
        pass

    def lock_for(self, time: float):
        if not self.is_set():
            return

        loop = asyncio.get_running_loop()

        self.clear()
        loop.call_later(time, self.set)


class TimePer:
    def __init__(self, limit: int, per: float):
        self.limit: int = limit
        self.remaining: int = limit
        self.per: float = per

        self._pending: queue.Queue[asyncio.Future[None]] = queue.Queue(limit)
        self._pending_reset: bool = False

    async def __aenter__(self):
        await self.acquire()
        return None

    async def __aexit__(self, *_):
        pass

    async def acquire(self):
        loop = asyncio.get_running_loop()

        if self.remaining == 0:
            _log.debug("We have run out of remaining requests, waiting to create more.")
            future = loop.create_future()
            self._pending.put_nowait(future)

            try:
                await future
            except asyncio.CancelledError:
                _log.debug("Acquire has cancelled. Cleaning up.")
                self._pending.queue.remove(future)
                return

        self.remaining -= 1
        _log.debug("Request has been made, %d left.", self.remaining)

        if not self._pending_reset:
            self._pending_reset = True
            loop.call_later(self.per, self._reset)

    def _reset(self):
        self._pending_reset = False
        self.remaining = self.limit

        for _ in range(self._pending.qsize()):
            future = self._pending.get_nowait()

            self._pending.task_done()
            future.set_result(None)
