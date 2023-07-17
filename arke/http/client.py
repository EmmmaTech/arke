# SPDX-License-Identifier: MIT

from __future__ import annotations

import abc
import asyncio
import logging
import typing as t

import aiohttp

from ..__about__ import __version__
from ..internal.json import JSONArray, JSONObject, load_json
from .auth import Auth
from .errors import Forbidden, HTTPException, NotFound, ServerError, Unauthorized
from .ratelimit import Bucket, Lock
from .route import Route

__all__ = (
    "Route",
    "HTTPClient",
    "json_or_text",
)

_log = logging.getLogger(__name__)

BASE_API_URL = "https://discord.com/api/v{0}"
# the discord api docs say to grab the gateway url via the get gateway endpoints
# the url is always the same, so we do not do that here
BASE_GATEWAY_URL = "wss://gateway.discord.gg"
API_VERSION = 10


def _get_user_agent():
    return f"DiscordBot (https://github.com/EmreTech/discord-api-wrapper, {__version__})"


def _get_base_url():
    return BASE_API_URL.format(API_VERSION)


class BasicHTTPClient(abc.ABC):
    """Represents a base HTTP client."""

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
    """Represents an HTTP client that interacts with Discord's REST API."""

    def __init__(self, default_auth: Auth, *, bucket_lag: float = 0.2):
        """Initalizes an HTTP client.
        
        Args:
            default_auth: 
                The default authentication to use for requests.
                This can be overridden per request, if needed.
            bucket_lag:
                Amount of lag to compensate for slightly outdated reset values.
        """

        self._http: t.Optional[aiohttp.ClientSession] = None
        self._default_headers: dict[str, str] = {
            "User-Agent": _get_user_agent(),
            "Authorization": default_auth.header,
        }
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
        """The HTTP session used for requests. Automatically regenerated when needed."""
        if self._http is None:
            self._http = aiohttp.ClientSession()

        return self._http

    async def close(self):
        """Closes the HTTP session. If the HTTP session is not set, nothing will happen."""
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
        """Makes a request with the Discord REST API.
        
        Args:
            route:
                The route that the request should be made to.
            json:
                The json payload provided with this request.
            query:
                The query parameters for the url.
            headers:
                Custom headers for this request only.
            auth:
                Custom authentication for this request only.

        Returns:
            A string, json payload, or nothing depending on what Discord responded with.

        Raises:
            ValueError:
                json parameter is set with GET request method or authentication manually set in custom headers.
        """
        if route.method == "GET" and json:
            raise ValueError("json parameter cannot be mixed with GET method!")

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
                        route.method, self._base_url + route.formatted_url, **params
                    ) as resp:
                        bucket.update_from(resp)

                        if bucket.enabled:
                            if discord_hash != bucket.bucket:
                                discord_hash = bucket.bucket
                                key = f"{discord_hash}:{local_bucket}"
                                self._local_to_discord[local_bucket] = discord_hash

                                _log.debug(
                                    "Our bucket has migrated to %s! The new bucket will be refetched.",
                                    key,
                                )

                                if new_bucket := self._get_bucket(key, autocreate=False):
                                    bucket = new_bucket
                                else:
                                    self._buckets[key] = bucket

                            await bucket.acquire()

                        if 300 > resp.status >= 200:
                            _log.debug(
                                "Successfully made a request to %s with status code %i and in %i "
                                + ("try" if try_ == 1 else "tries")
                                + ".",
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
                                _log.info(
                                    "We have hit a global ratelimit! We will globally lock for %f seconds.",
                                    retry_after,
                                )

                                self._global_lock.lock_for(retry_after)
                                await self._global_lock.wait()
                            else:
                                _log.info(
                                    "Bucket %s has hit a ratelimit! We will lock for %f seconds.",
                                    key,
                                    retry_after,
                                )

                                bucket.lock_for(retry_after)
                                await bucket.acquire(auto_lock=False)

                            continue

                        if 500 > resp.status >= 400:
                            raw_content = await resp.text()
                            content = json_or_text(raw_content, resp.content_type)

                            if t.TYPE_CHECKING:
                                content = t.cast(t.Mapping[str, t.Any], content)

                            if resp.status == 401:
                                raise Unauthorized(content)
                            if resp.status == 403:
                                raise Forbidden(content)
                            if resp.status == 404:
                                raise NotFound(content)

                            raise HTTPException(content, resp.status, resp.reason)

                        if 600 > resp.status >= 500:
                            if resp.status in (500, 502):
                                _log.info(
                                    "We have gotten server error %i! We will retry in %i.",
                                    resp.status,
                                    2 * try_ + 1,
                                )
                                await asyncio.sleep(2 * try_ + 1)
                                continue
                            raise ServerError(None, resp.status, resp.reason)

        _log.error(
            "Tried to make request to %s with method %s %d times.",
            route.formatted_url,
            route.method,
            MAX_RETRIES,
        )

    @t.overload
    async def connect_gateway(
        self,
        *,
        url: None = None,
        encoding: t.Optional[t.Literal["json", "etf"]] = None,
        compress: t.Optional[t.Literal["zlib-stream"]] = None,
    ):
        pass

    @t.overload
    async def connect_gateway(self, *, url: str, encoding: None = None, compress: None = None):
        pass

    async def connect_gateway(
        self,
        *,
        url: t.Optional[str] = None,
        encoding: t.Optional[t.Literal["json", "etf"]] = None,
        compress: t.Optional[t.Literal["zlib-stream"]] = None,
    ):
        """Makes the initial request with the Gateway.
        
        Args:
            url:
                The url to connect with. 
                This cannot be mixed with the `encoding` and `compress` parameters.
            encoding:
                The encoding to use for this connection.
                This cannot be mixed with the `url` parameter.
            compress:
                Whether compression will be enabled for this connection.
                This cannot be mixed with the `url` parameter.

        Returns:
            An aiohttp websocket object connected to the Gateway.
        """
        params: dict[str, t.Any] = {}
        if not url:
            url = BASE_GATEWAY_URL
            params = {"v": API_VERSION}

            if encoding:
                params["encoding"] = encoding

            if compress:
                params["compress"] = compress

        return await self.http.ws_connect(url, params=params)


def json_or_text(content: str | None, content_type: str) -> str | JSONObject | JSONArray | None:
    """Parses content into text or a json payload.
    
    Args:
        content:
            The content to parse.
        content_type:
            The type of the content from the response.
    
    Returns:
        A string, json payload, or nothing depending on what the content type is.
    """
    content_type = content_type.lower()

    if content and content_type != "":
        if content_type == "application/json":
            return load_json(content)
        return content

    return None
