import asyncio
import os
import shutil
import time
from pathlib import Path

from .base import BaseSandbox, SandboxResult
from .fs_jail import FilesystemJail

# Sensitive environment variables stripped from child processes
SENSITIVE_ENV_PREFIXES = (
    "AWS_",
    "GITHUB_",
    "OPENAI_",
    "ANTHROPIC_",
    "AZURE_",
    "GOOGLE_",
    "SLACK_",
    "DISCORD_",
)
SENSITIVE_ENV_SUBSTRINGS = (
    "_KEY",
    "_SECRET",
    "_TOKEN",
    "_PASSWORD",
    "_AUTH",
)


def get_scrubbed_env(user_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a sanitized environment dictionary with sensitive secrets stripped."""
    clean_env: dict[str, str] = {}
    for key, val in os.environ.items():
        upper_key = key.upper()
        if any(upper_key.startswith(p) for p in SENSITIVE_ENV_PREFIXES):
            continue
        if any(sub in upper_key for sub in SENSITIVE_ENV_SUBSTRINGS):
            continue
        clean_env[key] = val

    if user_env:
        clean_env.update(user_env)

    return clean_env


class ProcessSandbox(BaseSandbox):
    def __init__(
        self,
        workspace_dir: Path,
        timeout_seconds: float = 15.0,
        snapshot_storage_dir: Path | None = None,
    ):
        super().__init__(workspace_dir=workspace_dir, timeout_seconds=timeout_seconds)
        self.jail = FilesystemJail(
            workspace_dir=self.workspace_dir,
            snapshot_storage_dir=snapshot_storage_dir,
        )

    async def execute_command(
        self,
        command: str,
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """
        Execute command as an isolated child process in the workspace.
        Records filesystem diffs produced by the execution.
        """
        before_snapshot = self.jail.scan_workspace()
        scrubbed_env = get_scrubbed_env(env)

        start_time = time.perf_counter()
        try:
            # Use shell execution on Windows/POSIX with workspace as cwd
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace_dir),
                env=scrubbed_env,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdin_bytes = stdin.encode("utf-8") if stdin else None
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin_bytes),
                    timeout=self.timeout_seconds,
                )
                exit_code = proc.returncode or 0
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                exit_code = 124
                stdout_text = ""
                stderr_text = f"Command timed out after {self.timeout_seconds} seconds"

        except Exception as exc:
            exit_code = 1
            stdout_text = ""
            stderr_text = f"Execution failed: {type(exc).__name__}: {exc}"

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        after_snapshot = self.jail.scan_workspace()
        diff = self.jail.compute_diff(before_snapshot, after_snapshot)

        return SandboxResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_ms=elapsed_ms,
            files_created=diff.created,
            files_modified=diff.modified,
            files_deleted=diff.deleted,
        )

    def read_file(self, relative_path: str) -> str:
        safe_path = self.jail.resolve_safe_path(relative_path)
        if not safe_path.is_file():
            raise FileNotFoundError(f"File '{relative_path}' not found in workspace")
        return safe_path.read_text(encoding="utf-8", errors="replace")

    def write_file(self, relative_path: str, content: str) -> None:
        safe_path = self.jail.resolve_safe_path(relative_path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding="utf-8")

    def list_files(self, subpath: str = ".") -> list[str]:
        safe_subpath = self.jail.resolve_safe_path(subpath)
        if not safe_subpath.exists():
            return []
        files = []
        for root, _, filenames in os.walk(safe_subpath):
            for fname in filenames:
                full_path = Path(root) / fname
                rel_path = str(full_path.relative_to(self.workspace_dir)).replace("\\", "/")
                files.append(rel_path)
        return sorted(files)

    def reset(self) -> None:
        if self.workspace_dir.exists():
            for item in self.workspace_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
