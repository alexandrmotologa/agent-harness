import logging
import time
from pathlib import Path

from .base import BaseSandbox, SandboxResult
from .fs_jail import FilesystemJail
from .process_sandbox import ProcessSandbox

logger = logging.getLogger(__name__)


class ContainerSandbox(BaseSandbox):
    def __init__(
        self,
        workspace_dir: Path,
        timeout_seconds: float = 15.0,
        image_name: str = "python:3.12-slim",
        memory_limit_mb: int = 256,
        cpu_quota: float = 0.5,
        allow_network: bool = False,
    ):
        super().__init__(workspace_dir=workspace_dir, timeout_seconds=timeout_seconds)
        self.image_name = image_name
        self.memory_limit_mb = memory_limit_mb
        self.cpu_quota = cpu_quota
        self.allow_network = allow_network
        self.jail = FilesystemJail(self.workspace_dir)

        self._docker_client = None
        self._fallback_sandbox: ProcessSandbox | None = None
        self._initialize_docker()

    def _initialize_docker(self) -> None:
        try:
            import docker
            client = docker.from_env()
            client.ping()
            self._docker_client = client
        except Exception as exc:
            logger.warning(
                "Docker daemon unavailable (%s). Falling back to ProcessSandbox.",
                exc,
            )
            self._fallback_sandbox = ProcessSandbox(
                workspace_dir=self.workspace_dir,
                timeout_seconds=self.timeout_seconds,
            )

    @property
    def is_docker_active(self) -> bool:
        return self._docker_client is not None

    async def execute_command(
        self,
        command: str,
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        if self._fallback_sandbox:
            return await self._fallback_sandbox.execute_command(command, stdin=stdin, env=env)

        start_time = time.perf_counter()
        before_snapshot = self.jail.scan_workspace()

        stdout_text = ""
        stderr_text = ""
        exit_code = 0

        container = None
        try:
            client = self._docker_client
            # Configure non-root container with read-only root and tmpfs
            container = client.containers.create(
                image=self.image_name,
                command=["sh", "-c", command],
                working_dir="/workspace",
                user="1000:1000",
                read_only=True,
                tmpfs={"/tmp": "size=64M,mode=1777"},
                volumes={
                    str(self.workspace_dir): {"bind": "/workspace", "mode": "rw"}
                },
                mem_limit=f"{self.memory_limit_mb}m",
                nano_cpus=int(self.cpu_quota * 1_000_000_000),
                network_mode="bridge" if self.allow_network else "none",
                environment=env or {},
            )

            container.start()
            # Wait for container execution with timeout
            result = container.wait(timeout=int(self.timeout_seconds))
            exit_code = result.get("StatusCode", 0)

            logs = container.logs(stdout=True, stderr=True)
            stdout_text = logs.decode("utf-8", errors="replace")

        except Exception as exc:
            exit_code = 1
            stderr_text = f"Container execution error: {type(exc).__name__}: {exc}"
            if "ReadTimeout" in type(exc).__name__:
                exit_code = 124
                stderr_text = f"Container timed out after {self.timeout_seconds} seconds"

        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

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
        import os
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
        import shutil
        if self.workspace_dir.exists():
            for item in self.workspace_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
