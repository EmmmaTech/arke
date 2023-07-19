# SPDX-License-Identifier: MIT

import importlib
import typing as t

T = t.TypeVar("T")

JSONable = str | int | float | bool | None | t.Sequence["JSONable"] | t.Mapping[str, "JSONable"]
"""A type alias that explictly defines an object that complies with the JSON spec."""

@t.runtime_checkable
class _JSONLoader(t.Protocol):
    def __call__(self, obj: str, /) -> JSONable:
        raise NotImplementedError
    
@t.runtime_checkable
class _JSONDumper(t.Protocol):
    def __call__(self, obj: JSONable, /) -> str:
        raise NotImplementedError

load_json: t.Callable[[str], JSONable]
dump_json: t.Callable[[JSONable], str]

@t.overload
def load_json_serializers(
    module: str,
    *,
    loader: str,
    dumper: str,
):
    pass

@t.overload
def load_json_serializers(
    module: None = None,
    *,
    loader: _JSONLoader,
    dumper: _JSONDumper,
):
    pass

def load_json_serializers(
    module: t.Optional[str] = None, 
    *, 
    loader: str | _JSONLoader,
    dumper: str | _JSONDumper,
):
    """Loads json serializers either from a module or from loader & dumper callables.
    
    Args:
        module: The module to load from, if applicable.
        loader: The name of the loader callable or the loader callable itself.
        loader: The name of the dumper callable or the dumper callable itself.

    Raises:
        ValueError: The wrong parameters were passed in.
    """
    global load_json, dump_json

    if module is not None:
        if not isinstance(loader, str) or not isinstance(dumper, str):
            raise ValueError(
                f"Expected loader and dumper parameters to be callables, not {type(loader)!r} and {type(dumper)!r}."
            )
        
        try:
            loaded_module = importlib.import_module(module)
        except ImportError:
            raise ImportError(
                f"You do not seem to have {module} installed."
                " Please install it before attempting to use it for json serialization."
            )
        
        if not hasattr(loaded_module, loader) or not hasattr(loaded_module, dumper):
            raise ValueError(f"{module} has no attribute {loader} and/or {loader}.")
        
        load_json = getattr(loaded_module, loader)
        dump_json = getattr(loaded_module, dumper)

    elif module is None:
        if isinstance(loader, str) or isinstance(dumper, str):
            raise ValueError(
                f"Expected loader and dumper parameters to be str, not {type(loader)!r} and {type(dumper)!r}."
            )
        
        load_json = loader
        dump_json = dumper
    else:
        raise ValueError(f"Expected module to be str or None, got {type(module)!r}.")

try:
    # fastest option will be loaded by default
    import orjson

    # we can't use the module loading functionality because
    # orjson encodes the string contents in its dumps return
    load_json_serializers(
        loader=orjson.loads,
        dumper=lambda __obj: orjson.dumps(__obj).decode(),
    )

except ImportError:
    # load from the stdlib

    load_json_serializers("json", loader="loads", dumper="dumps")
