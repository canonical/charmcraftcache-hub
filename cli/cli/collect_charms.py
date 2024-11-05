import dataclasses
import json
import os
import pathlib

from . import charm


@dataclasses.dataclass(frozen=True, kw_only=True)
class _CharmRefJob(charm.CharmRef):
    charm_index: int
    job_name: str

    @classmethod
    def from_charm_ref(cls, charm_ref: charm.CharmRef, *, index: int):
        return cls(
            **dataclasses.asdict(charm_ref),
            charm_index=index,
            job_name=(
                f'{charm_ref.github_repository.removeprefix("canonical/")} | {charm_ref.ref} | '
                f"{charm_ref.relative_path_to_charmcraft_yaml}"
            ),
        )


def main():
    """Collect charms to build from charms.json"""
    charm_refs = (
        charm.CharmRef(**charm_) for charm_ in json.loads(pathlib.Path("charms.json").read_text())
    )
    charm_refs = (
        _CharmRefJob.from_charm_ref(charm_ref, index=index)
        for index, charm_ref in enumerate(charm_refs)
    )
    charm_refs = [dataclasses.asdict(charm_ref) for charm_ref in charm_refs]
    output = f"charms={json.dumps(charm_refs)}\n"
    print(output)
    with pathlib.Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
        file.write(output)
