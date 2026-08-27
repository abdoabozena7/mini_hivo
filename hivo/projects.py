"""Numbered project workspace management for the default ``list`` root."""

from dataclasses import dataclass
from pathlib import Path
import re
import shutil


PROJECT_NAME = re.compile(r"^project-(\d+)$")


@dataclass(frozen=True)
class MigrationResult:
    project: Path
    moved: tuple[Path, ...]


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def projects(self) -> list[Path]:
        if not self.root.exists():
            return []
        numbered = []
        for item in self.root.iterdir():
            match = PROJECT_NAME.fullmatch(item.name)
            if item.is_dir() and match:
                numbered.append((int(match.group(1)), item))
        return [item for _number, item in sorted(numbered)]

    def next_number(self) -> int:
        projects = self.projects()
        if not projects:
            return 1
        return max(int(PROJECT_NAME.fullmatch(item.name).group(1)) for item in projects) + 1

    def peek_next_name(self) -> str:
        return f"project-{self.next_number()}"

    def migrate_legacy_contents(self) -> MigrationResult:
        """Move pre-numbered workspace contents into ``project-1`` once.

        Existing numbered project directories are never moved.  Conflicting
        destination names abort before the conflicting item is changed.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        legacy = [item for item in self.root.iterdir() if not PROJECT_NAME.fullmatch(item.name)]
        project = self.root / "project-1"
        if not legacy:
            return MigrationResult(project=project, moved=())

        project.mkdir(parents=False, exist_ok=True)
        conflicts = [item.name for item in legacy if (project / item.name).exists()]
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise FileExistsError(f"cannot migrate legacy list contents; project-1 conflicts: {names}")

        moved = []
        try:
            for item in legacy:
                destination = project / item.name
                shutil.move(str(item), str(destination))
                moved.append(destination)
        except OSError:
            for destination in reversed(moved):
                original = self.root / destination.name
                if destination.exists() and not original.exists():
                    shutil.move(str(destination), str(original))
            raise
        return MigrationResult(project=project, moved=tuple(moved))

    def create_project(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        number = self.next_number()
        while True:
            project = self.root / f"project-{number}"
            try:
                project.mkdir(parents=False, exist_ok=False)
                return project
            except FileExistsError:
                number += 1
