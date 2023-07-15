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
    type: AuthTypes
    token: str

    def __init__(self, *, type: AuthTypes, token: str):
        self.type = type
        self.token = token

    @property
    def header(self):
        return f"{self.type} {self.token}"
