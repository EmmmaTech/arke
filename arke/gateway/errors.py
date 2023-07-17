# SPDX-License-Identifier: MIT

__all__ = (
    "GatewayException",
    "AuthenticationError",
    "RateLimited",
    "ShardingError",
    "IntentError",
)


class GatewayException(Exception):
    """The base exception for all Gateway related errors."""


class AuthenticationError(GatewayException):
    """Authentication has failed with the Gateway. (4004)"""


class RateLimited(GatewayException):
    """The Shard has sent too many requests to the Gateway. (4008)"""


class ShardingError(GatewayException):
    """Invalid shard metadata has been sent to the Gateway, or sharding is not enabled. (4010, 4011)"""


class IntentError(GatewayException):
    """Invalid or disallowed intent(s) have been sent to the Gateway. (4013, 4014)""" # 4013,4014
