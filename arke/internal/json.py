# SPDX-License-Identifier: MIT

import typing as t

T = t.TypeVar("T")

# these type aliases are to properly represent the recursion of json
# implementation taken from velum
# (https://github.com/eludris-community/velum/blob/6065fd13ac6c6514534c5f5b2b3c4366973a9a92/velum/internal/data_binding.py#L27-L33)

JSONPrimitiveT = str | int | float | bool | None | T
JSONObjectT = t.Mapping[str, JSONPrimitiveT[T]]
JSONArrayT = t.Sequence[JSONPrimitiveT[T]]

JSONPrimitive = JSONObjectT["JSONPrimitiveT"] | JSONArrayT["JSONPrimitiveT"]
JSONObject = JSONObjectT[JSONPrimitive]
JSONArray = JSONArrayT[JSONPrimitive]

load_json: t.Callable[[str], JSONObject | JSONArray]
dump_json: t.Callable[[JSONObject | JSONArray], str]

try:
    # fastest option will be loaded by default
    import orjson

    load_json = orjson.loads

    def dump_json(__obj: JSONObject | JSONArray, /) -> str:
        return orjson.dumps(__obj).decode()

except ImportError:
    # load from the stdlib
    import json

    load_json = json.loads
    dump_json = json.dumps
