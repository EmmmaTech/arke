from __future__ import annotations

import aiohttp
import asyncio
import typing as t

from ..internal.json import JSONObject, JSONArray
from .auth import Auth
from .errors import HTTPException
from .ratelimit import Bucket, Lock, BucketMigrated
from .route import Route

__all__ = ("Route", "HTTPClient",)

BASE_API_URL = "https://discord.com/api/v{0}"
API_VERSION = 10

def _get_user_agent():
    return f"DiscordBot (https://github.com/EmreTech/discord-api-wrapper, 1.0 Prototype)"

def _get_base_url():
    return BASE_API_URL.format(API_VERSION)

class HTTPClient:
    def __init__(self, default_auth: Auth, *, bucket_lag: float = 0.2):
        self._http: t.Optional[aiohttp.ClientSession] = None
        self._default_headers: dict[str, str] = {"User-Agent": _get_user_agent(), "Authorization": default_auth.header}
        self._base_url = _get_base_url()
        self._default_bucket_lag = bucket_lag
        # (local bucket, discord bucket) -> Bucket
        self._buckets: dict[tuple[str, t.Optional[str]], Bucket] = {}
        self._global_lock: Lock = Lock()
        self._global_lock.set()

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *_):
        await self.close()

    @property
    def http(self):
        if self._http is None:
            self._http = aiohttp.ClientSession(headers=self._default_headers)

        return self._http
    
    async def close(self):
        if self._http is None:
            return

        await self._http.close()

    def _get_bucket(self, key: tuple[str, t.Optional[str]]):
        bucket = self._buckets.get(key)

        if not bucket:
            bucket = Bucket(self._default_bucket_lag)
            self._buckets[key] = bucket

        return bucket

    async def request(
        self,
        route: Route,
        *, 
        json: t.Optional[JSONObject | JSONArray] = None,
        query: t.Optional[dict[str, str]] = None,
        headers: t.Optional[dict[str, str]] = None,
    ):
        if route.method == "GET" and json:
            raise TypeError("json parameter cannot be mixed with GET method!")

        params: dict[str, t.Any] = {}

        if json:
            params["json"] = json

        if query:
            params["query"] = query

        if headers:
            params["headers"] = headers

        local_bucket = route.bucket
        bucket = self._get_bucket((local_bucket, None))

        MAX_RETRIES = 5

        for try_ in range(MAX_RETRIES):
            try:
                async with self._global_lock:
                    # log debug "The global lock has been acquired."
                    async with bucket:
                        # log debug "The local bucket has been acquired."
                        async with self.http.request(
                            route.method, 
                            self._base_url + route.formatted_url, 
                            **params
                        ) as resp:
                            bucket.update_from(resp)
                            await bucket.acquire()

                            if 300 > resp.status >= 200:
                                if resp.status == 204:
                                    return (None, "")

                                content = await resp.text()
                                return (content, resp.content_type)
                            
                            if resp.status == 429:
                                is_global = bool(resp.headers.get("X-RateLimit-Global", False))
                                retry_after = float(resp.headers["Retry-After"])

                                if is_global:
                                    self._global_lock.lock_for(retry_after)
                                    await self._global_lock.wait()
                                else:
                                    bucket.lock_for(retry_after)
                                    await bucket.acquire(auto_lock=False)

                                continue

                            if 500 > resp.status >= 400:
                                msg = await resp.text()
                                raise HTTPException(msg, resp.status, resp.reason)
 
                            if 600 > resp.status >= 500:
                                if resp.status in (500, 502):
                                    await asyncio.sleep(2 * try_ + 1)
                                    continue
                                raise HTTPException(None, resp.status, resp.reason)

            except BucketMigrated as e:
                # log debug "Our bucket {e.old} has migrated to {e.new}."
                bucket = self._get_bucket((local_bucket, e.new))

        # log error "Tried to make request to {route.formatted_url} with method {route.method} {MAX_RETRIES} times."
        return (None, "")