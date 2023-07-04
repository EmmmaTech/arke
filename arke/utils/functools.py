import typing as t
import typing_extensions as te

__all__ = ("classproperty",)

_T = t.TypeVar("_T")
_ClsT = t.TypeVar("_ClsT")

class classproperty(t.Generic[_ClsT, _T]):
    def __init__(self, fget: t.Callable[[type[_ClsT]], _T], /) -> None:
        self.fget: classmethod[_ClsT, ..., _T]
        self.getter(fget)

    def getter(self, fget: t.Callable[[type[_ClsT]], _T], /) -> te.Self:
        if not isinstance(fget, classmethod):
            raise ValueError(f"Callable {fget.__name__} is not a classmethod!")

        self.fget = fget
        return self

    def __get__(self, obj: t.Optional[_ClsT], type: type[_ClsT]) -> _T:
        return self.fget.__func__(type)  # pyright: ignore
