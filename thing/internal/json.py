import typing as t

__all__ = ()

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
