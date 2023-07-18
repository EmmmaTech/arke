# SPDX-License-Identifier: MIT

__all__ = (
    "__name__", 
    "__copyright__",
    "__author__",
    "__version__", 
    "version_info",
)

__name__ = "arke"
__copyright__ = "2023 EmreTech"
__author__ = "EmreTech"

import typing as t

from ._version import __version__


class VersionInfo(t.NamedTuple):
    major: int
    minor: int
    patch: int
    releaseinfo: t.Literal["alpha", "beta", "candidate", "stable"] = "stable"
    serial: t.Optional[int] = None

    @classmethod
    def from_string(cls, raw: str, /):
        serial = None
        releaseinfo = "stable"
        if "-" in raw:
            version, releaseinfo = raw.split("-")

            if "a" in releaseinfo:
                serial = int(releaseinfo[1:])
                releaseinfo = "alpha"
            elif "b" in releaseinfo:
                serial = int(releaseinfo[1:])
                releaseinfo = "beta"
            else:
                serial = int(releaseinfo[2:])
                releaseinfo = "candidate"
        else:
            version = raw

        major, minor, patch = version.split(".")

        return cls(
            major=int(major),
            minor=int(minor),
            patch=int(patch),
            releaseinfo=releaseinfo,
            serial=serial,
        )


version_info: VersionInfo = VersionInfo.from_string(__version__)

del VersionInfo, t
