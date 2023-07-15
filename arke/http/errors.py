# SPDX-License-Identifier: MIT

import typing as t

from ..internal.json import JSONObject

__all__ = (
    "HTTPException",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "ServerError",
)


def _flatten_error_dict(d: dict[str, t.Any], *, parent: str = ""):
    ret: dict[str, t.Any] = {}

    for k, v in d.items():
        full_key = f"{parent}/{k}"

        if isinstance(v, list) and k == "_errors":
            ret[parent] = "\n".join([v2["message"] for v2 in v])
        elif isinstance(v, dict):
            ret.update(_flatten_error_dict(v, parent=full_key))

    return ret


class HTTPException(Exception):
    def __init__(
        self,
        original: str | t.Optional[t.Mapping[str, t.Any]],
        status: int,
        status_msg: t.Optional[str],
    ):
        code: int = 0
        text: str

        if isinstance(original, dict):
            code = original.get("code", 0)
            message = original.get("message", "")
            errors = original.get("errors")

            if errors:
                errors = _flatten_error_dict(errors)
                helpful = "\n".join(f"In {k}: {v}" for k, v in errors.items())
                text = f"{helpful}\n\n{message}"
            else:
                text = message
        else:
            if t.TYPE_CHECKING:
                original = t.cast(str | None, original)

            text = original or ""

        fmt = f"{status}"
        if status_msg:
            fmt += f" {status_msg}"
        if code:
            fmt += f" (discord code: {code})"
        if text:
            fmt += f"\n{text}"

        super().__init__(fmt)


class Unauthorized(HTTPException):
    def __init__(self, original: str | t.Optional[t.Mapping[str, t.Any]]):
        super().__init__(original, 401, "Unauthorized")


class Forbidden(HTTPException):
    def __init__(self, original: str | t.Optional[t.Mapping[str, t.Any]]):
        super().__init__(original, 403, "Forbidden")


class NotFound(HTTPException):
    def __init__(self, original: str | t.Optional[t.Mapping[str, t.Any]]):
        super().__init__(original, 404, "Not Found")


class ServerError(HTTPException):
    pass
