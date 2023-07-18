# SPDX-License-Identifier: MIT

import enum

__all__ = ("AuthTypes", "Auth")


class AuthTypes(enum.Enum):
    BOT = "Bot"
    BEARER = "Bearer"

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class Auth:
    """Represents an authentication key used with Discord.
    
    The key is used to properly log into your bot account or use your bearer token.

    Args:
        type: The type of authentication.
        token: The authentication key.

    Attributes:
        type: The type of authentication.
        token: The authentication key.
    """

    type: AuthTypes
    token: str

    def __init__(self, *, type: AuthTypes, token: str):
        self.type = type
        self.token = token

    @property
    def header(self):
        """The formatted key provided to Discord."""
        return f"{self.type} {self.token}"
