from __future__ import annotations

import urllib.parse as urlparse
import typing as t

__all__ = ("Route",)

HTTP_METHODS = t.Literal["GET", "POST", "PATCH", "PUT", "DELETE"]

class Route:
    def __init__(self, method: HTTP_METHODS, url: str, **params: t.Any):
        self.method: HTTP_METHODS = method
        self.url: str = url
        self._orig_params: dict[str, t.Any] = params
        self.params: dict[str, str] = {k: urlparse.quote(str(v)) for k, v in self._orig_params.items()}

    @property
    def formatted_url(self):
        return self.url.format_map(self.params)
    
    @property
    def bucket(self):
        top_level_params = {k: v for k, v in self.params.items() if k in ("guild_id", "channel_id", "webhook_id", "webhook_token")}
        formatted_url = self.url

        for k, v in top_level_params.items():
            formatted_url = formatted_url.replace(f"{{{k}}}", v)

        return formatted_url
