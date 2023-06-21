import typing as t

__all__ = ("HTTPException",)

def _flatten_error_dict(d: dict[str, t.Any], *, parent: str = ""):
    ret: dict[str, t.Any] = {}

    for k, v in d.items():
        full_key = f"{parent}/{k}"

        if isinstance(v, list) and k == "_errors":
            ret[parent] = "\n".join([v2["message"] for v2 in v])
        else:
            ret.update(_flatten_error_dict(v, parent=full_key))

    return ret

class HTTPException(Exception):
    def __init__(self, msg: t.Any, status: int, status_msg: str):
        error_msg = f"{status} {status_msg}"

        # TODO: use discord_typings for more precise typing here
        if isinstance(msg, dict):
            error_dict = _flatten_error_dict(msg)

            if len(error_dict) == 1 and "" in error_dict:
                error_msg += f" {error_dict['']}"
            else:
                for k, v in error_dict.items():
                    error_msg += f"\n\nIn {k}:\n{v['message']}"
        elif msg is not None:
            error_msg += f"\n{msg}"

        super().__init__(error_msg)
