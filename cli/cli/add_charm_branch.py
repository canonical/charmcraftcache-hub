import argparse
import dataclasses
import json
import os
import pathlib
import re
import subprocess

import requests

from . import charm


class IssueParsingError(ValueError):
    """Unexpected format for issue body"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-body", required=True)
    parser.add_argument("--issue-author", required=True)
    args = parser.parse_args()
    try:
        # Check if issue author in Canonical GitHub organization
        response = requests.get(
            f"https://api.github.com/orgs/canonical/members/{args.issue_author}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": f'Bearer {os.environ["READ_MEMBERS_GITHUB_PAT"]}',
            },
        )
        if response.status_code != 204:
            # Unable to confirm user is in Canonical GitHub organization

            if response.status_code == 404:
                # User is not in Canonical GitHub organization
                raise IssueParsingError(
                    "Unable to authorize GitHub user that created this issue. If you are trying "
                    "to use charmcraftcache for a GitHub repository that is not maintained by "
                    "Canonical, please add a comment to this issue: "
                    "https://github.com/canonical/charmcraftcache/issues/2"
                )

            # Unknown if user is in Canonical GitHub organization; raise uncaught exception
            response.raise_for_status()
            raise Exception(f"Unrecognized {response.status_code=}")
            # This code should never run; added in case `except` clause is accidentally updated to
            # catch `Exception`
            exit(1)

        # Example issue body:
        """### GitHub repository

canonical/mysql-router-k8s-operator

### Git ref (branch, tag, commit sha, etc.)

main

### Relative path to charmcraft.yaml

."""
        match = re.fullmatch(
            r"""### GitHub repository

(?P<organization>[a-zA-Z0-9.\-_]+)/(?P<repo_name>[a-zA-Z0-9.\-_]+)

### Git ref \(branch, tag, commit sha, etc\.\)

(?P<ref>\S+)

### Relative path to charmcraft\.yaml

(?P<path>[^\n]+)""",
            args.issue_body,
        )

        if not match:
            raise IssueParsingError("@carlcsaposs-canonical Error parsing issue body")
        organization = match.group("organization")
        charm_branch = charm.CharmRef(
            github_repository=f'{organization}/{match.group("repo_name")}',
            ref=match.group("ref"),
            relative_path_to_charmcraft_yaml=match.group("path"),
        )
        # Validate organization
        allowed_github_orgs = ("canonical", "juju", "charmed-kubernetes")
        if organization not in allowed_github_orgs:
            raise IssueParsingError(
                "To protect against arbitrary code execution, charmcraftcache-hub is only "
                f'available for these GitHub organizations: {", ".join(allowed_github_orgs)}. '
                "More info: https://github.com/canonical/charmcraftcache/issues/2"
            )
        # Check that repository exists
        try:
            subprocess.run(["gh", "repo", "view", charm_branch.github_repository], check=True)
        except subprocess.CalledProcessError:
            raise IssueParsingError("Repository not found. @carlcsaposs-canonical")
        # Validate ref
        try:
            subprocess.run(
                ["git", "check-ref-format", "--allow-onelevel", charm_branch.ref], check=True
            )
        except subprocess.CalledProcessError:
            raise IssueParsingError("Invalid git ref. @carlcsaposs-canonical")
        # Validate path
        path = pathlib.Path(charm_branch.relative_path_to_charmcraft_yaml)
        if not path.resolve().is_relative_to(pathlib.Path(".").resolve()):
            raise IssueParsingError("Invalid path. @carlcsaposs-canonical")
        if "ccchub" in (
            charm_branch.github_repository,
            charm_branch.ref,
            charm_branch.relative_path_to_charmcraft_yaml,
        ):
            raise IssueParsingError(
                "'ccchub' string is not allowed in repository name, git ref, or relative path to "
                "charmcraft.yaml. @carlcsaposs-canonical"
            )
        with open("charms.json") as file:
            charms = json.load(file)
        charm_ = dataclasses.asdict(charm_branch)
        if charm_ in charms:
            raise IssueParsingError("Git ref already exists in charms.json. @carlcsaposs-canonical")
    except IssueParsingError as exception:
        output = f"success={json.dumps(False)}\nerror={exception.message}"
    else:
        charms.append(charm_)
        with open("charms.json", "w") as file:
            json.dump(charms, file, indent=2)
        output = (
            f"success={json.dumps(True)}\ntitle=Add "
            f"{charm_branch.github_repository}@{charm_branch.ref} at path "
            f"{charm_branch.relative_path_to_charmcraft_yaml}"
        )
    print(output)
    with open(os.environ["GITHUB_OUTPUT"], "a") as file:
        file.write(output)
