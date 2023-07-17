# SPDX-License-Identifier: MIT

import asyncio
import typing as t

__all__ = ("completed_future", "gather_optionally",)

_T = t.TypeVar("_T")

def completed_future(*, result: t.Optional[_T] = None) -> asyncio.Future[t.Optional[_T]]:
    """Returns a completed future.
    
    Args:
        result:
            The result to use for the completed future.

    Returns:
        A completed future.
    """
    loop = asyncio.get_running_loop()

    future: asyncio.Future[t.Optional[_T]] = loop.create_future()
    future.set_result(result)
    return future

@t.overload
def gather_optionally(*aws: t.Awaitable[t.Any], return_exceptions: bool = False, default: t.Optional[t.Any] = None) -> asyncio.Future[t.Any]:
    pass

@t.overload
def gather_optionally(*, return_exceptions: bool = False, default: t.Optional[_T] = None) -> asyncio.Future[t.Optional[_T]]:
    pass

def gather_optionally(*aws: t.Awaitable[t.Any], return_exceptions: bool = False, default: t.Optional[_T] = None) -> asyncio.Future[list[t.Any]] | asyncio.Future[_T | None]:
    """Gather provided awaitables, return a completed future if none are provided.
    
    Args:
        *aws:
            The awaitables to gather.
        return_exceptions:
            Whether exceptions are raised or returned.
        default:
            The result to use for the completed future, if returned.

    Returns:
        Either a future with a list of tasks or a completed future.
    """
    if aws:
        return asyncio.gather(*aws, return_exceptions=return_exceptions)
    else:
        return completed_future(result=default)
