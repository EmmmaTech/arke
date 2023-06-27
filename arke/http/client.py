from __future__ import annotations

import abc
import aiohttp
import asyncio
import logging
import typing as t

from ..internal.json import JSONObject, JSONArray, load_json
from .auth import Auth
from .errors import HTTPException, Unauthorized, Forbidden, NotFound, ServerError
from .ratelimit import Bucket, Lock
from .route import Route

__all__ = ("Route", "HTTPClient", "json_or_text",)

_log = logging.getLogger(__name__)

BASE_API_URL = "https://discord.com/api/v{0}"
# the discord api docs say to grab the gateway url via the get gateway endpoints
# the url is always the same, so we do not do that here
BASE_GATEWAY_URL = "wss://gateway.discord.gg"
API_VERSION = 10

def _get_user_agent():
    return f"DiscordBot (https://github.com/EmreTech/discord-api-wrapper, 1.0 Prototype)"

def _get_base_url():
    return BASE_API_URL.format(API_VERSION)

class BasicHTTPClient(abc.ABC):
    async def request(
        self,
        route: Route,
        *, 
        json: t.Optional[JSONObject | JSONArray] = None,
        query: t.Optional[dict[str, str]] = None,
        headers: t.Optional[dict[str, str]] = None,
        auth: t.Optional[Auth] = None,
    ) -> str | JSONObject | JSONArray | None:
        pass

class HTTPClient(BasicHTTPClient):
    def __init__(self, default_auth: Auth, *, bucket_lag: float = 0.2):
        self._http: t.Optional[aiohttp.ClientSession] = None
        self._default_headers: dict[str, str] = {"User-Agent": _get_user_agent(), "Authorization": default_auth.header}
        self._base_url = _get_base_url()
        self._default_bucket_lag = bucket_lag
        self._local_to_discord: dict[str, str] = {}
        self._buckets: dict[str, Bucket] = {}
        self._global_lock: Lock = Lock()
        self._global_lock.set()

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *_):
        await self.close()

    @property
    def http(self):
        if self._http is None:
            self._http = aiohttp.ClientSession()

        return self._http
    
    async def close(self):
        if self._http is None:
            return

        await self._http.close()

    @t.overload
    def _get_bucket(self, key: str, *, autocreate: t.Literal[True] = True) -> Bucket:
        pass

    @t.overload
    def _get_bucket(self, key: str, *, autocreate: t.Literal[False]) -> t.Optional[Bucket]:
        pass

    def _get_bucket(self, key: str, *, autocreate: bool = True):
        bucket = self._buckets.get(key)

        if not bucket and autocreate:
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
        auth: t.Optional[Auth] = None,
    ):
        if route.method == "GET" and json:
            raise TypeError("json parameter cannot be mixed with GET method!")

        if headers and "Authorization" in headers:
            raise ValueError("Use the auth parameter to set authentication for this request.")

        if not headers:
            headers = {}

        headers = {**self._default_headers, **headers}

        if auth:
            headers["Authorization"] = auth.header

        params: dict[str, t.Any] = {"headers": headers}

        if json:
            params["json"] = json

        if query:
            params["params"] = query

        local_bucket = route.bucket
        discord_hash = self._local_to_discord.get(local_bucket)

        key = local_bucket
        if discord_hash:
            key = f"{discord_hash}:{local_bucket}"

        bucket = self._get_bucket(key)

        MAX_RETRIES = 5

        _log.debug("Request with bucket %s will start.", key)
        for try_ in range(MAX_RETRIES):
            async with self._global_lock:
                _log.debug("The global lock has been acquired.")
                async with bucket:
                    _log.debug("The local bucket has been acquired.")
                    async with self.http.request(
                        route.method, 
                        self._base_url + route.formatted_url, 
                        **params
                    ) as resp:
                        bucket.update_from(resp)

                        if bucket.enabled:
                            if discord_hash != bucket.bucket:
                                discord_hash = bucket.bucket
                                key = f"{discord_hash}:{local_bucket}"
                                self._local_to_discord[local_bucket] = discord_hash

                                _log.debug("Our bucket has migrated to %s! The new bucket will be refetched.", key)

                                if (new_bucket := self._get_bucket(key, autocreate=False)):
                                    bucket = new_bucket
                                else:
                                    self._buckets[key] = bucket

                            await bucket.acquire()

                        if 300 > resp.status >= 200:
                            _log.debug(
                                "Successfully made a request to %s with status code %i and in %i "
                                "try" if try_ == 1 else "tries" ".",
                                route.formatted_url, 
                                resp.status,
                                try_ + 1,
                            )

                            if resp.status == 204:
                                return

                            content = await resp.text()
                            return json_or_text(content, resp.content_type)

                        if resp.status == 429:
                            is_global = bool(resp.headers.get("X-RateLimit-Global", False))
                            retry_after = float(resp.headers["Retry-After"])

                            if is_global:
                                _log.info("We have hit a global ratelimit! We will globally lock for %f seconds.", retry_after)

                                self._global_lock.lock_for(retry_after)
                                await self._global_lock.wait()
                            else:
                                _log.info("Bucket %s has hit a ratelimit! We will lock for %f seconds.", key, retry_after)

                                bucket.lock_for(retry_after)
                                await bucket.acquire(auto_lock=False)

                            continue                                

                        if 500 > resp.status >= 400:
                            raw_content = await resp.text()
                            content = json_or_text(raw_content, resp.content_type)

                            if resp.status == 401:
                                raise Unauthorized(content)
                            if resp.status == 403:
                                raise Forbidden(content)
                            if resp.status == 404:
                                raise NotFound(content)

                            raise HTTPException(content, resp.status, resp.reason)

                        if 600 > resp.status >= 500:
                            if resp.status in (500, 502):
                                _log.info("We have gotten server error %i! We will retry in %i.", resp.status, 2 * try_ + 1)
                                await asyncio.sleep(2 * try_ + 1)
                                continue
                            raise ServerError(None, resp.status, resp.reason)

        _log.error("Tried to make request to %s with method %s %d times.", route.formatted_url, route.method, MAX_RETRIES)

    async def connect_gateway(self, *, encoding: t.Optional[t.Literal["json", "etf"]] = None, compress: t.Optional[t.Literal["zlib-stream"]] = None):
        params: dict[str, t.Any] = {"v": API_VERSION}

        if encoding:
            params["encoding"] = encoding

        if compress:
            params["compress"] = compress

        return await self.http.ws_connect(BASE_GATEWAY_URL, params=params)

def json_or_text(content: str | None, content_type: str) -> str | JSONObject | JSONArray | None:
    content_type = content_type.lower()

    if content and content_type != "":
        if content_type == "application/json":
            return load_json(content)
        return content

    return None
