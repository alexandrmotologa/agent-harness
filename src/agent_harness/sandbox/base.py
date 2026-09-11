from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class SecurityViolationError(Exception):
    """Raised when code or a tool attempts to escape the sandbox."""


class SandboxResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    files_deleted: list[str] = Field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0

    def format_output(self) -> str:
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[STDERR]\n{self.stderr}")
        if not parts and self.exit_code == 0:
            parts.append("[Command completed with no output]")
        elif not parts:
            parts.append(f"[Command exited with code {self.exit_code}]")
        return "\n".join(parts)


class BaseSandbox(ABC):
    def __init__(self, workspace_dir: Path, timeout_seconds: float = 15.0):
        self.workspace_dir = workspace_dir.resolve()
        self.timeout_seconds = timeout_seconds
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def execute_command(
        self,
        command: str,
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute a shell command within the sandbox boundaries."""

    @abstractmethod
    def read_file(self, relative_path: str) -> str:
        """Read text content from a file inside the workspace."""

    @abstractmethod
    def write_file(self, relative_path: str, content: str) -> None:
        """Write text content to a file inside the workspace."""

    @abstractmethod
    def list_files(self, subpath: str = ".") -> list[str]:
        """List relative file paths inside the workspace."""

    @abstractmethod
    def reset(self) -> None:
        """Reset workspace to a clean state."""
