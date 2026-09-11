import hashlib
import os
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .base import SecurityViolationError


class FileDiff(BaseModel):
    created: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)


def hash_file(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class FilesystemJail:
    def __init__(self, workspace_dir: Path, snapshot_storage_dir: Path | None = None):
        self.workspace_dir = workspace_dir.resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir = (
            snapshot_storage_dir.resolve()
            if snapshot_storage_dir
            else self.workspace_dir.parent / "snapshots"
        )
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def resolve_safe_path(self, relative_path: str | Path) -> Path:
        """
        Validates that the target path resides strictly inside the workspace directory.
        Raises SecurityViolationError if path traversal is detected.
        """
        target = (self.workspace_dir / relative_path).resolve()
        try:
            target.relative_to(self.workspace_dir)
        except ValueError as exc:
            raise SecurityViolationError(
                f"Path traversal detected: path '{relative_path}' escapes sandbox workspace '{self.workspace_dir}'"
            ) from exc
        return target

    def scan_workspace(self) -> dict[str, str]:
        """Scan workspace and return mapping of relative file paths to SHA-256 hashes."""
        fingerprints: dict[str, str] = {}
        for root, _, files in os.walk(self.workspace_dir):
            for filename in files:
                full_path = Path(root) / filename
                rel_path = str(full_path.relative_to(self.workspace_dir)).replace("\\", "/")
                try:
                    fingerprints[rel_path] = hash_file(full_path)
                except (OSError, PermissionError):
                    continue
        return fingerprints

    def compute_diff(
        self,
        before: dict[str, str],
        after: dict[str, str],
    ) -> FileDiff:
        """Compute file additions, modifications, and deletions between two snapshots."""
        created = [p for p in after if p not in before]
        deleted = [p for p in before if p not in after]
        modified = [p for p in after if p in before and after[p] != before[p]]
        return FileDiff(
            created=sorted(created),
            modified=sorted(modified),
            deleted=sorted(deleted),
        )

    def save_snapshot(self, snapshot_id: str) -> dict[str, str]:
        """Save a snapshot of the workspace to the snapshot storage vault."""
        target_dir = self.snapshot_dir / snapshot_id
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        current_files = self.scan_workspace()
        for rel_path in current_files:
            source_file = self.workspace_dir / rel_path
            dest_file = target_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest_file)

        return current_files

    def restore_snapshot(self, snapshot_id: str) -> None:
        """Restore the workspace to the exact state saved in snapshot_id."""
        source_dir = self.snapshot_dir / snapshot_id
        if not source_dir.exists():
            raise FileNotFoundError(f"Snapshot '{snapshot_id}' not found in '{self.snapshot_dir}'")

        # Clean current workspace files
        for root, dirs, files in os.walk(self.workspace_dir, topdown=False):
            for f in files:
                try:
                    (Path(root) / f).unlink()
                except OSError:
                    pass
            for d in dirs:
                try:
                    (Path(root) / d).rmdir()
                except OSError:
                    pass

        # Copy snapshot files back
        for root, _, files in os.walk(source_dir):
            for filename in files:
                src_path = Path(root) / filename
                rel_path = src_path.relative_to(source_dir)
                dest_path = self.workspace_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest_path)
