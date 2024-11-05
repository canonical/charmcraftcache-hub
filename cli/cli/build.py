import argparse
import os
import pathlib
import subprocess

from . import charm, checkout


def main():
    """Build charm base"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--relative-path-to-charmcraft-yaml", required=True)
    parser.add_argument("--base-index", required=True)
    args = vars(parser.parse_args())
    base_index = args.pop("base_index")
    charm_ref = charm.CharmRef(**args)
    charm_dir = checkout.checkout(charm_ref, sparse=False)
    # Cache directory used by charmcraft; unrelated to charmcraftcache CLI
    charmcraft_cache_directory = pathlib.Path(
        "~/charmcraftcache-hub-ci/charmcraft-cache"
    ).expanduser()

    charmcraft_cache_directory.mkdir(parents=True)
    env = os.environ
    env["CRAFT_SHARED_CACHE"] = str(charmcraft_cache_directory)
    requirements = pathlib.Path(charm_dir, "requirements.txt")
    if not requirements.exists():
        # Workaround for https://github.com/canonical/charmcraft/issues/1389 on charmcraft 2
        requirements.touch()
    subprocess.run(
        ["charmcraft", "pack", "-v", "--bases-index", base_index],
        cwd=charm_dir,
        check=True,
        env=env,
    )
