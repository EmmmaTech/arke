# SPDX-License-Identifier: MIT

__name__ = "arke"
__description__ = "Python Discord API Wrapper made from the ground up."

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
