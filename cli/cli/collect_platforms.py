import argparse
import dataclasses
import enum
import json
import os
import pathlib

import charmcraftcache._platforms

from . import charm, checkout


class _Architecture(enum.StrEnum):
    X64 = "amd64"
    ARM64 = "arm64"
    S390X = "s390x"


_RUNNERS = {
    _Architecture.X64: "ubuntu-latest",
    _Architecture.ARM64: "ubuntu-24.04-arm",
    # Use PS6 runners while PS7 runners unstable: https://chat.canonical.com/canonical/pl/3wcxtsrzo3ykdxe6rzp5uuus8h
    _Architecture.S390X: "self-hosted-linux-s390x-noble-edge",
}


class ArchitectureNotSupported(KeyError):
    """Architecture currently not supported (since runner not available)"""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Platform:
    name: str
    """Shorthand platform name (e.g. 'ubuntu@22.04:amd64')

    From specification ST124 - Multi-base platforms in craft tools
    (https://docs.google.com/document/d/1QVHxZumruKVZ3yJ2C74qWhvs-ye5I9S6avMBDHs2YcQ/edit)

    Syntaxes other than "shorthand notation" are not supported since build-on and build-for should
    match (otherwise wheels will be incompatible)
    """

    runner: str | list[str]
    """GitHub Actions 'runs-on' value"""

    name_in_artifact: str
    """Shorthand platform name with characters allowed in GitHub Actions artifacts
    
    (e.g. 'ubuntu@22.04_ccchubplatform_amd64')
    """

    @classmethod
    def from_platform(cls, platform: charmcraftcache._platforms.Platform, /):
        try:
            runner = _RUNNERS[platform.architecture]
        except KeyError:
            raise ArchitectureNotSupported
        return cls(
            name=platform,
            runner=runner,
            name_in_artifact=platform.name_in_release,
        )


def main():
    """Collect platforms to build from charmcraft.yaml"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--relative-path-to-charmcraft-yaml", required=True)
    args = parser.parse_args()
    charm_ref = charm.CharmRef(**vars(args))
    charm_dir = checkout.checkout(charm_ref)
    platforms = []
    for platform in charmcraftcache._platforms.get(charm_dir / "charmcraft.yaml"):
        try:
            platform = Platform.from_platform(platform)
        except ArchitectureNotSupported:
            print(
                f"Skipped {repr(platform)} platform since the {repr(platform.architecture)} "
                "architecture is not currently supported by charmcraftcache-hub. Please open an "
                "issue if you'd like this architecture to be supported"
            )
            continue
        platforms.append(dataclasses.asdict(platform))
    output = f"platforms={json.dumps(platforms)}\n"
    print(output)
    with pathlib.Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
        file.write(output)
