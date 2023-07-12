import asyncio
import logging
import typing as t

__all__ = ("TimePer",)

_log = logging.getLogger(__name__)

class TimePer:
    def __init__(self, limit: int, per: float):
        self.limit: int = limit
        self.remaining: int = limit
        self.per: float = per

        self._lock: asyncio.Event = asyncio.Event()
        self._lock.set()
        self._reset_task: t.Optional[asyncio.Task[None]] = None

    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, *_):
        pass

    async def _reset(self):
        while True:
            self._lock.clear()

            await asyncio.sleep(self.per)
            self.remaining = self.limit

            self._lock.set()

    def start(self):
        assert self._reset_task is None, "Ratelimiter has already been started!"
        
        self._reset_task = asyncio.create_task(self._reset())
        _log.debug("Ratelimiter has been started.")

    async def stop(self):
        assert self._reset_task is not None, "Ratelimiter is not running!"

        self._reset_task.cancel()
        self._reset_task = None

    async def acquire(self):
        if self.remaining == 0:
            _log.debug("We have run out of requests, waiting to make more.")
            await self._lock.wait()

        self.remaining -= 1
        _log.debug("Request made, %i requests left.", self.remaining)
