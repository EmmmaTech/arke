# SPDX-License-Identifier: MIT

from __future__ import annotations

import typing as t
import urllib.parse as urlparse

__all__ = ("Route",)

HTTP_METHODS = t.Literal["GET", "POST", "PATCH", "PUT", "DELETE"]


class Route:
    """Represents a route to the REST API.
    
    Attributes:
        method: 
            The method to use when requesting.
            Can be one of the following: GET, POST, PATCH, PUT, DELETE
        url:
            The url of the route.
        params:
            Additional parameters that will be formatted into the url.
    """
    def __init__(self, method: HTTP_METHODS, url: str, **params: t.Any):
        """Initalizes a REST API route.
        
        Args:
            method: 
                The method to use when requesting.
                Can be one of the following: GET, POST, PATCH, PUT, DELETE
            url:
                The url of the route.
            **params:
                Additional parameters that will be formatted into the url.
        """
        self.method: HTTP_METHODS = method
        self.url: str = url
        self._orig_params: dict[str, t.Any] = params
        self.params: dict[str, str] = {
            k: urlparse.quote(str(v)) for k, v in self._orig_params.items()
        }

    @property
    def formatted_url(self):
        """The url of this route, formatted with additonal parameters."""
        return self.url.format_map(self.params)

    @property
    def bucket(self):
        """The local bucket representation of this route.
        
        This is used primarily for ratelimiting, when a route doesn't have a 
        Discord bucket hash yet.
        """
        top_level_params = {
            k: v
            for k, v in self.params.items()
            if k in ("guild_id", "channel_id", "webhook_id", "webhook_token")
        }
        formatted_url = self.url

        for k, v in top_level_params.items():
            formatted_url = formatted_url.replace(f"{{{k}}}", v)

        return formatted_url
