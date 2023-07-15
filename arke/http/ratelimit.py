import datetime
import logging
import typing as t

import aiohttp

from ..internal.ratelimit import Lock

__all__ = (
    "Lock",
    "Bucket",
)

_log = logging.getLogger(__name__)


class Bucket:
    def __init__(self, lag: float = 0.2):
        self.lag: float = lag

        self.bucket: str = ""
        self.reset_after: float = 0.0
        self._lock: Lock = Lock()
        self.limit: int = 1
        self.remaining: int = 1
        self.reset: t.Optional[datetime.datetime] = None
        self.bucket: str = ""
        self.enabled: bool = True

    async def __aenter__(self):
        await self.acquire()
        return None

    async def __aexit__(self, *_):
        pass

    def update_from(self, response: aiohttp.ClientResponse):
        headers = response.headers

        if not self.enabled:
            _log.debug("This bucket will skip an update because it's not enabled.")
            return

        x_bucket: t.Optional[str] = headers.get("X-RateLimit-Bucket")
        if x_bucket is None:
            _log.debug("Ratelimiting is not supported for this bucket.")
            self.enabled = False
            return

        if not self.bucket:
            self.bucket = x_bucket

        # from here on, the route has ratelimits

        if headers.get("X-RateLimit-Global", False):
            _log.debug("This ratelimit is globally applied.")
            return

        x_limit: int = int(headers["X-RateLimit-Limit"])
        if x_limit != self.limit:
            self.limit = x_limit

        x_remaining: int = int(headers.get("X-RateLimit-Remaining", 1))
        if x_remaining < self.remaining or self.remaining == 0:
            self.remaining = x_remaining

        # TODO: consider removing this
        x_reset: datetime.datetime = datetime.datetime.fromtimestamp(
            float(headers["X-RateLimit-Reset"])
        )
        if x_reset != self.reset:
            self.reset = x_reset

        x_reset_after: float = float(headers["X-RateLimit-Reset-After"])
        if x_reset_after > self.reset_after:
            self.reset_after = x_reset_after
            self.reset_after += self.lag

    def lock_for(self, time: float):
        if not self._lock.is_set():
            return

        _log.debug("Bucket %s will be locked for %f seconds.", self.bucket, time)
        self._lock.lock_for(time)

    async def acquire(self, *, auto_lock: bool = True):
        if self.remaining == 0 and auto_lock:
            _log.debug("Bucket %s will be auto-locked.", self.bucket)
            self.lock_for(self.reset_after)
            # prevent the bucket from being locked again until after we actually make a request
            self.remaining = 1

        await self._lock.wait()
        _log.debug("Bucket %s has been acquired!", self.bucket)
