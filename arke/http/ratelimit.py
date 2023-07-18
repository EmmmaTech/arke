# SPDX-License-Identifier: MIT

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
    """Represents a Discord ratelimit bucket.
    
    Args:
        lag:
            Amount of lag to compensate for slightly outdated reset values.

    Attributes:
        lag: 
            Amount of lag to compensate for slightly outdated reset values.
        bucket:
            The hash for this bucket from Discord.
        reset_after:
            How long until this bucket resets after being exhausted.
        limit:
            The total amount of requests that can be made under this bucket until exhausted.
        remaining:
            The remaining amount of requests until this bucket is exhausted.
        reset:
            The precise datetime when this bucket will next reset.
        enabled:
            Whether this bucket is enabled.
    """
    def __init__(self, lag: float = 0.2):
        self.lag: float = lag

        self.bucket: str = ""
        self.reset_after: float = 0.0
        self._lock: Lock = Lock()
        self.limit: int = 1
        self.remaining: int = 1
        self.reset: t.Optional[datetime.datetime] = None
        self.enabled: bool = True

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, *_):
        pass

    def update_from(self, response: aiohttp.ClientResponse):
        """Update this bucket from the latest REST API response.
        
        Args:
            response: 
                The REST API response to update from.
        """
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
        """Lock this bucket for a specified amount of time.
        
        Args:
            time: 
                The duration for how long this bucket should be locked for.
        """
        if not self._lock.is_set():
            return

        _log.debug("Bucket %s will be locked for %f seconds.", self.bucket, time)
        self._lock.lock_for(time)

    async def acquire(self, *, auto_lock: bool = True):
        """Waits for the bucket to be available.
        
        Args:
            auto_lock: 
                Whether the bucket should auto-lock if there are no more requests left.
        """
        if self.remaining == 0 and auto_lock:
            _log.debug("Bucket %s will be auto-locked.", self.bucket)
            self.lock_for(self.reset_after)
            # prevent the bucket from being locked again until after we actually make a request
            self.remaining = 1

        await self._lock.wait()
        _log.debug("Bucket %s has been acquired!", self.bucket)
