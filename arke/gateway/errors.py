__all__ = (
    "GatewayException",
    "AuthenticationError",
    "RateLimited",
    "ShardingError",
    "IntentError",
)

class GatewayException(Exception):
    pass

class AuthenticationError(GatewayException):
    pass

class RateLimited(GatewayException):
    pass

class ShardingError(GatewayException):
    pass

class IntentError(GatewayException):
    pass
