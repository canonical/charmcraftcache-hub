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
    # No sizes (e.g. "large") currently available for s390x IS-hosted runners
    _Architecture.S390X: ["self-hosted", "s390x", "noble"],
}


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
        return cls(
            name=platform,
            runner=_RUNNERS[platform.architecture],
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
    platforms = (
        Platform.from_platform(platform)
        for platform in charmcraftcache._platforms.get(charm_dir / "charmcraft.yaml")
    )
    platforms = [dataclasses.asdict(platform) for platform in platforms]
    output = f"platforms={json.dumps(platforms)}\n"
    print(output)
    with pathlib.Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
        file.write(output)
