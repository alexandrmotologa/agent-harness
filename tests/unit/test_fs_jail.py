import pytest

from agent_harness.sandbox.base import SecurityViolationError
from agent_harness.sandbox.fs_jail import FilesystemJail


def test_path_traversal_detection(temp_workspace):
    jail = FilesystemJail(temp_workspace)

    # Valid relative paths
    safe_path = jail.resolve_safe_path("src/module.py")
    assert safe_path == (temp_workspace / "src" / "module.py").resolve()

    # Disallowed path traversal outside workspace
    with pytest.raises(SecurityViolationError):
        jail.resolve_safe_path("../../etc/passwd")

    with pytest.raises(SecurityViolationError):
        jail.resolve_safe_path("../secret.txt")


def test_snapshot_diff_and_restore(temp_workspace):
    jail = FilesystemJail(temp_workspace)

    # Create initial files
    (temp_workspace / "file1.txt").write_text("hello", encoding="utf-8")
    before_snap = jail.save_snapshot("snap_01")

    # Modify file1, create file2
    (temp_workspace / "file1.txt").write_text("hello modified", encoding="utf-8")
    (temp_workspace / "file2.txt").write_text("new file", encoding="utf-8")

    after_snap = jail.scan_workspace()
    diff = jail.compute_diff(before_snap, after_snap)

    assert "file2.txt" in diff.created
    assert "file1.txt" in diff.modified
    assert not diff.deleted

    # Restore snapshot 01 and verify state rolls back
    jail.restore_snapshot("snap_01")
    assert (temp_workspace / "file1.txt").read_text(encoding="utf-8") == "hello"
    assert not (temp_workspace / "file2.txt").exists()
