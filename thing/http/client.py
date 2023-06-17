from __future__ import annotations

import aiohttp
import urllib.parse as urlparse
import typing as t

from .auth import Auth

__all__ = ("Route", "HTTPClient",)

HTTP_METHODS: t.Literal["GET", "POST", "PATCH", "PUT", "DELETE"]
BASE_API_URL = "https://discord.com/api/v{0}"
API_VERSION = 10

def _get_user_agent():
    return f"DiscordBot (https://github.com/EmreTech/discord-api-wrapper, 1.0 Prototype)"

def _get_base_url():
    return BASE_API_URL.format(API_VERSION)

class Route:
    def __init__(self, method: HTTP_METHODS, url: str, **params: t.Any):
        self.method: HTTP_METHODS = method
        self.url: str = url
        self._orig_params: dict[str, t.Any] = params
        self.params: dict[str, str] = {k: urlparse.quote(str(v)) for k, v in self._orig_params}

    @property
    def formatted_url(self):
        return self.url.format_map(self.params)

class HTTPClient:
    def __init__(self, default_auth: Auth):
        self._http: t.Optional[aiohttp.ClientSession] = None
        self._default_headers: dict[str, str] = {"User-Agent": _get_user_agent(), "Authorization": default_auth.header}
        self._base_url = _get_base_url()

    @property
    def http(self):
        if self._http is None:
            self._http = aiohttp.ClientSession(headers=self._default_headers)

        return self._http
    
    async def close(self):
        if self._http is None:
            return

        await self._http.close()

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *_):
        await self.close()

    async def request(
        self,
        route: Route,
        *, 
        json: t.Optional[t.Any] = None,
        query: t.Optional[dict[str, str]] = None,
        headers: t.Optional[dict[str, str]] = None,
    ):
        params: dict[str, t.Any] = {}

        if json:
            params["json"] = json

        if query:
            params["query"] = query

        if headers:
            params["headers"] = headers

        async with self.http.request(
            route.method, 
            self._base_url + route.formatted_url, 
            **params
        ) as resp:
            content = await resp.text()
            return content, resp.content_type