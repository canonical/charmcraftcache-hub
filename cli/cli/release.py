import dataclasses
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import time

import requests
import requests.adapters
import uritemplate
import urllib3
import urllib3.util

from . import charm


class GitHubRateLimitRetry(urllib3.util.Retry):
    """Infinite retry for GitHub REST API rate limit

    https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28#exceeding-the-rate-limit
    """

    def __init__(self, **kwargs):
        # Use setdefault since this class is re-initialized on each retry
        # (using values from last retry)

        # Infinite retry
        assert kwargs.setdefault("total", None) is None
        # Only retry on status code
        # `<=0` since count is decremented & this class is re-initialized with `-1` before retry is
        # stopped
        assert kwargs.setdefault("connect", 0) <= 0
        assert kwargs.setdefault("read", 0) <= 0
        assert kwargs.setdefault("redirect", 0) <= 0
        assert kwargs.setdefault("status", None) is None
        assert kwargs.setdefault("other", 0) <= 0

        allowed_methods = (*urllib3.util.Retry.DEFAULT_ALLOWED_METHODS, "POST", "PATCH")
        assert kwargs.setdefault("allowed_methods", allowed_methods) == allowed_methods
        assert kwargs.setdefault("status_forcelist", (403, 429)) == (403, 429)
        assert kwargs.setdefault("respect_retry_after_header", True) is True
        super().__init__(**kwargs)

    def get_retry_after(self, response: urllib3.BaseHTTPResponse) -> float | None:
        seconds = super().get_retry_after(response)
        if seconds:
            print(f"[ccc-hub] Rate limit exceeded. Sleeping for {int(seconds)} seconds", flush=True)
        return seconds

    def sleep_for_retry(self, response: urllib3.BaseHTTPResponse) -> bool:
        # Sleep until x-ratelimit-reset
        if int(response.headers.get("x-ratelimit-remaining", -1)) == 0 and (
            reset := response.headers.get("x-ratelimit-reset")
        ):
            retry_time = datetime.datetime.fromtimestamp(float(reset), tz=datetime.timezone.utc)
            retry_delta = retry_time - datetime.datetime.now(tz=datetime.timezone.utc)
            seconds = max(retry_delta.total_seconds(), 0)
            print(f"[ccc-hub] Rate limit exceeded. Sleeping for {int(seconds)} seconds", flush=True)
            time.sleep(seconds)
            return True
        # Sleep for/until retry-after
        if super().sleep_for_retry(response):
            return True
        # x-ratelimit-reset and retry-after headers missing
        print(
            "[ccc-hub] Rate limit exceeded. Sleeping for 60 seconds (rate limit headers missing)",
            flush=True,
        )
        time.sleep(60)
        return True


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Charm:
    github_repository: str
    relative_path_to_charmcraft_yaml: str

    @classmethod
    def from_charm_ref(cls, charm_ref: charm.CharmRef, /):
        return cls(
            github_repository=charm_ref.github_repository,
            relative_path_to_charmcraft_yaml=charm_ref.relative_path_to_charmcraft_yaml,
        )


def main():
    charm_refs = [
        charm.CharmRef(**charm_) for charm_ in json.loads(pathlib.Path("charms.json").read_text())
    ]

    # Combine cache for multiple refs on the same charm & same platform
    # `_Charm`: list of indexes in charms.json
    charm_indexes: dict[_Charm, list[int]] = {}
    for index, charm_ref in enumerate(charm_refs):
        charm_indexes.setdefault(_Charm.from_charm_ref(charm_ref), []).append(index)
    platforms = pathlib.Path("~/charmcraftcache-hub-ci/platforms/").expanduser()
    combined_platforms = pathlib.Path("~/charmcraftcache-hub-ci/combined_platforms/").expanduser()
    for charm_, indexes in charm_indexes.items():
        # Lower index (earlier in charms.json list) should override higher index
        # `shutil.copytree` with `dirs_exist_ok=True` provides this behavior if we copy higher
        # indexes before lower indexes
        for index in reversed(indexes):
            # Example `platform`: "charm-0-platform-ubuntu@22.04_ccchubplatform_amd64"
            for platform in platforms.glob(f"charm-{index}-*"):
                # Remove charmcraft base directory (e.g. "charmcraft-buildd-base-v7") when copying
                platform_subdirectories = list(platform.iterdir())
                assert len(platform_subdirectories) == 1
                # Example `platform_subdirectory.name`: "charmcraft-buildd-base-v7"
                platform_subdirectory = platform_subdirectories[0]
                shutil.copytree(
                    platform_subdirectory,
                    combined_platforms
                    / platform.name.replace(f"charm-{index}-", f"charm-{min(indexes)}-"),
                    dirs_exist_ok=True,
                )
                shutil.rmtree(platform)
        print(f"[ccc-hub] Merged {indexes=} for {charm_=}", flush=True)
    # Check directory is empty
    platforms.rmdir()
    print("[ccc-hub] Merged platforms", flush=True)

    release_archives = pathlib.Path("~/charmcraftcache-hub-ci/release_archives/").expanduser()
    for platform in combined_platforms.iterdir():
        platform: pathlib.Path
        # Example: "charm-0-platform-ubuntu@22.04_ccchubplatform_amd64"
        artifact_name = platform.name
        first, charm_index, third, platform_name = artifact_name.split("-")
        assert first == "charm" and third == "platform"
        charm_index = int(charm_index)
        charm_ref = charm_refs[charm_index]
        archive_name = f"{charm_ref.github_repository}_ccchub1_{charm_ref.relative_path_to_charmcraft_yaml}_ccchub2_{platform_name}"
        archive_name = archive_name.replace("/", "_")
        archive_path_without_extension = release_archives / archive_name
        expected_archive_path = release_archives / f"{archive_name}.tar.gz"
        assert not expected_archive_path.exists()
        created_archive_path = shutil.make_archive(
            base_name=str(archive_path_without_extension), format="gztar", root_dir=platform
        )
        created_archive_path = pathlib.Path(created_archive_path)
        assert created_archive_path == expected_archive_path
        print(f"[ccc-hub] Created archive {created_archive_path.name}", flush=True)
    print("[ccc-hub] Created all archives", flush=True)

    release_name = f"build-{int(time.time())}-v5"
    # Create git tag
    subprocess.run(["git", "tag", release_name], check=True)
    subprocess.run(["git", "push", "origin", release_name], check=True)
    print(f"[ccc-hub] Created & pushed git tag {release_name}", flush=True)

    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=GitHubRateLimitRetry()))
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f'Bearer {os.environ["GH_TOKEN"]}',
    }
    # Create draft release
    # (Wait until all release files uploaded before marking as latest, non-draft release)
    response = session.post(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/releases',
        headers=headers,
        json={
            "tag_name": release_name,
            "target_commitish": os.environ["GITHUB_SHA"],
            "name": release_name,
            "draft": True,
            "make_latest": "false",
        },
    )
    response.raise_for_status()
    print("[ccc-hub] Created draft release", flush=True)
    data = response.json()
    upload_url_template = uritemplate.URITemplate(data["upload_url"])
    release_id = data["id"]
    # Upload release files
    for path in release_archives.iterdir():
        with path.open("rb") as file:
            response = session.post(
                upload_url_template.expand(name=path.name),
                headers={**headers, "Content-Type": "application/octet-stream"},
                data=file,
            )
        response.raise_for_status()
        print(f"[ccc-hub] Uploaded {path.name}", flush=True)
    print("[ccc-hub] Uploaded all release files", flush=True)
    # Mark release as latest
    response = session.patch(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/releases/{release_id}',
        headers=headers,
        json={"draft": False, "make_latest": "true"},
    )
    response.raise_for_status()
    print("[ccc-hub] Marked release as latest", flush=True)
