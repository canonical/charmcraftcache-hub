import argparse
import dataclasses
import enum
import json
import os
import pathlib

import yaml

from . import charm, checkout


class _Architecture(str, enum.Enum):
    X64 = "amd64"
    ARM64 = "arm64"


_RUNNERS = {
    _Architecture.X64: "ubuntu-latest",
    _Architecture.ARM64: ["self-hosted", "data-platform", "ubuntu", "ARM64", "4cpu16ram"],
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class Base:
    base_index: int
    """Index of base in charmcraft.yaml 'bases'"""

    runner: str | list[str]
    """GitHub Actions 'runs-on' value"""

    name: str
    """Shorthand base name (e.g. 'ubuntu@22.04:amd64')
    
    From specification ST124 - Multi-base platforms in craft tools
    (https://docs.google.com/document/d/1QVHxZumruKVZ3yJ2C74qWhvs-ye5I9S6avMBDHs2YcQ/edit)
    
    Syntaxes other than "shorthand notation" are not supported since build-on and build-for should
    match (otherwise wheels will be incompatible)
    """

    name_in_artifact: str
    """Shorthand base name with characters allowed in GitHub Actions artifacts
    
    (e.g. 'ubuntu@22.04_ccchubbase_amd64')
    """

    @classmethod
    def from_charmcraft_yaml_base(cls, base: dict, *, base_index: int):
        # https://discourse.charmhub.io/t/charmcraft-bases-provider-support/4713
        build_on = base.get("build-on")
        if build_on:
            assert isinstance(build_on, list) and len(build_on) == 1
            base = build_on[0]
        build_on_architectures = base.get("architectures")
        if build_on_architectures:
            assert len(build_on_architectures) == 1, (
                f"Multiple architectures ({build_on_architectures}) in one (charmcraft.yaml) base "
                "entry not supported. Use one entry per architecture"
            )
            architecture = _Architecture(build_on_architectures[0])
        else:
            # Default to X64
            architecture = _Architecture.X64
        assert base["name"] == "ubuntu"
        return cls(
            base_index=base_index,
            runner=_RUNNERS[architecture],
            name=f'ubuntu@{base["channel"]}:{architecture}',
            name_in_artifact=f'ubuntu@{base["channel"]}_ccchubbase_{architecture}',
        )


def main():
    """Collect bases to build from charmcraft.yaml"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--relative-path-to-charmcraft-yaml", required=True)
    args = parser.parse_args()
    charm_ref = charm.CharmRef(**vars(args))
    charm_dir = checkout.checkout(charm_ref)
    charmcraft_yaml = yaml.safe_load((charm_dir / "charmcraft.yaml").read_text())
    bases = (
        Base.from_charmcraft_yaml_base(base, base_index=index)
        for index, base in enumerate(charmcraft_yaml["bases"])
    )
    bases = [dataclasses.asdict(base) for base in bases]
    output = f"bases={json.dumps(bases)}\n"
    print(output)
    with pathlib.Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
        file.write(output)
