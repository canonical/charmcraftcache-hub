import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class CharmRef:
    github_repository: str
    ref: str
    relative_path_to_charmcraft_yaml: str
