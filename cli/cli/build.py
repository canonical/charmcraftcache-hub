import argparse
import dataclasses
import json
import os
import pathlib
import subprocess

import yaml

from . import charm


@dataclasses.dataclass(frozen=True, kw_only=True)
class Charm(charm.Charm):
    @property
    def _repository_directory(self) -> pathlib.Path:
        return pathlib.Path("repos", self.github_repository)

    def checkout_repository(self):
        try:
            self._repository_directory.mkdir(parents=True)
        except FileExistsError:
            commands = [
                ["git", "fetch", "origin", self.ref],
                ["git", "checkout", "FETCH_HEAD"],
            ]
        else:
            commands = [
                ["git", "init"],
                [
                    "git",
                    "sparse-checkout",
                    "set",
                    "--sparse-index",
                    self.relative_path_to_charmcraft_yaml,
                ],
                [
                    "git",
                    "remote",
                    "add",
                    "--fetch",
                    "origin",
                    f"https://github.com/{self.github_repository}.git",
                ],
                ["git", "fetch", "origin", self.ref],
                ["git", "checkout", "FETCH_HEAD"],
            ]
        for command in commands:
            try:
                subprocess.run(
                    command,
                    cwd=self._repository_directory,
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                )
            except subprocess.CalledProcessError as exception:
                if "ERROR: Repository not found." in exception.stderr:
                    print(f"{self.github_repository=} not found")
                elif "couldn't find remote ref" in exception.stderr:
                    print(f"{self.ref=} not found")
                else:
                    raise

    @property
    def directory(self) -> pathlib.Path:
        path = self._repository_directory / self.relative_path_to_charmcraft_yaml
        assert path.is_relative_to(self._repository_directory)
        return path


@dataclasses.dataclass
class UbuntuBase:
    version: str  # e.g. 22.04
    series: str  # e.g. jammy
    python_version: str  # e.g. 3.8


BASES = [
    UbuntuBase("20.04", "focal", "3.8"),
    UbuntuBase("22.04", "jammy", "3.10"),
]


def is_base_in_charmcraft_yaml(base: UbuntuBase, charmcraft_yaml: pathlib.Path) -> bool:
    """Check if base in charmcraft.yaml"""
    bases = yaml.safe_load(charmcraft_yaml.read_text())["bases"]
    # Handle multiple bases formats
    # See https://discourse.charmhub.io/t/charmcraft-bases-provider-support/4713
    versions = [base_.get("build-on", [base_])[0]["channel"] for base_ in bases]
    return base.version in versions


def main():
    pip_cache = pathlib.Path("~/charmcraftcache-hub-ci/build/").expanduser()
    pip_cache.mkdir(parents=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("charms_file")
    args = parser.parse_args()
    with open(args.charms_file, "r") as file:
        charms = [Charm(**charm) for charm in json.load(file)]
    pyenv = str(pathlib.Path("~/.pyenv/bin/pyenv").expanduser())
    release_artifacts = pathlib.Path("~/charmcraftcache-hub-ci/release/").expanduser()
    release_artifacts.mkdir(parents=True)
    for base in BASES:
        subprocess.run([pyenv, "install", base.python_version], check=True)
        env = os.environ
        env["PYENV_VERSION"] = base.python_version
        subprocess.run(
            [pyenv, "exec", "pip", "install", "--upgrade", "pip"],
            check=True,
            env=env,
        )
        for charm_ in charms:
            charm_.checkout_repository()
            if not is_base_in_charmcraft_yaml(
                base, charm_.directory / "charmcraft.yaml"
            ):
                continue
            # Check for charmcraft pack wrapper (tox `build-wrapper` environment)
            tox_environments = subprocess.run(
                ["tox", "list", "--no-desc"],
                capture_output=True,
                cwd=charm_.directory,
                check=True,
                encoding="utf-8",
            ).stdout.split("\n")
            if "build-wrapper" in tox_environments:
                subprocess.run(
                    ["tox", "run", "-e", "build-wrapper"],
                    cwd=charm_.directory,
                    check=True,
                )
                requirements = "requirements-last-build.txt"
            else:
                requirements = "requirements.txt"
            assert (charm_.directory / requirements).exists()
            env = os.environ
            env["PYENV_VERSION"] = base.python_version
            env["XDG_CACHE_HOME"] = str(pip_cache)
            subprocess.run(
                [
                    pyenv,
                    "exec",
                    "pip",
                    "install",
                    "-r",
                    requirements,
                    # Build wheels from source
                    "--no-binary",
                    ":all:",
                    # Cache will still be hit if exact version of wheel available
                    # `--ignore-installed` needed to ignore non-exact versions
                    "--ignore-installed",
                ],
                cwd=charm_.directory,
                check=True,
                env=env,
            )
        # Rename .whl files to include relative path from `~/charmcraftcache-hub-ci/build/` and
        # Ubuntu series
        for wheel in (pip_cache / "pip/wheels/").glob("**/*.whl"):
            # Example:
            # `~/charmcraftcache-hub-ci/build/pip/wheels/a6/bb/99/9eae10e99b02cc1daa8f370d631ae22d9a1378c33d04b598b6/setuptools-68.2.2-py3-none-any.whl`
            # is moved to
            # `~/charmcraftcache-hub-ci/release/setuptools-68.2.2-py3-none-any.whl.charmcraftcachehub.jammy_pip_wheels_a6_bb_99_9eae10e99b02cc1daa8f370d631ae22d9a1378c33d04b598b6.charmcraftcachehub`
            parent = str(wheel.parent.relative_to(pip_cache))
            assert "_" not in parent
            parent = parent.replace("/", "_")
            wheel.rename(
                pathlib.PurePath(
                    release_artifacts,
                    f"{wheel.name}.charmcraftcachehub.{base.series}_{parent}.charmcraftcachehub",
                )
            )
