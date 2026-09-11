import difflib
from pathlib import Path

from rich.text import Text


def generate_unified_diff(
    before_text: str,
    after_text: str,
    filename: str = "file",
) -> str:
    """Generate git-style unified diff between two text versions."""
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)


def format_colored_diff(diff_text: str) -> Text:
    """Format unified diff text into syntax-highlighted Rich Text for console/TUI."""
    rich_text = Text()
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("---") or line.startswith("+++"):
            rich_text.append(line, style="bold magenta")
        elif line.startswith("@@"):
            rich_text.append(line, style="bold cyan")
        elif line.startswith("+"):
            rich_text.append(line, style="green")
        elif line.startswith("-"):
            rich_text.append(line, style="red")
        else:
            rich_text.append(line, style="dim white")
    return rich_text


def compute_checkpoint_diffs(
    snapshot_storage_dir: Path,
    checkpoint_a_id: str,
    checkpoint_b_id: str,
) -> dict[str, str]:
    """Compute per-file unified diffs between two checkpoint snapshot directories."""
    dir_a = snapshot_storage_dir / checkpoint_a_id
    dir_b = snapshot_storage_dir / checkpoint_b_id

    diffs: dict[str, str] = {}
    if not dir_a.exists() or not dir_b.exists():
        return diffs

    all_files_a = {
        str(p.relative_to(dir_a)).replace("\\", "/")
        for p in dir_a.rglob("*")
        if p.is_file()
    }
    all_files_b = {
        str(p.relative_to(dir_b)).replace("\\", "/")
        for p in dir_b.rglob("*")
        if p.is_file()
    }

    all_files = all_files_a.union(all_files_b)

    for rel_path in sorted(all_files):
        path_a = dir_a / rel_path
        path_b = dir_b / rel_path

        content_a = path_a.read_text(encoding="utf-8", errors="replace") if path_a.exists() else ""
        content_b = path_b.read_text(encoding="utf-8", errors="replace") if path_b.exists() else ""

        if content_a != content_b:
            diff_text = generate_unified_diff(content_a, content_b, filename=rel_path)
            diffs[rel_path] = diff_text

    return diffs
