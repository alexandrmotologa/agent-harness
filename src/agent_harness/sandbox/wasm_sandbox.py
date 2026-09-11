import ast
import asyncio
import io
import sys
import time
from pathlib import Path

from .base import BaseSandbox, SandboxResult, SecurityViolationError
from .fs_jail import FilesystemJail

# Disallowed AST nodes and module imports in safe Python evaluation
FORBIDDEN_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "http",
    "urllib",
    "requests",
    "httpx",
    "pathlib",
    "posix",
    "nt",
    "ctypes",
}

FORBIDDEN_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
}


class CodeSafetyVisitor(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module in FORBIDDEN_MODULES:
                raise SecurityViolationError(f"Import of '{alias.name}' is forbidden in WasmSandbox")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_module = node.module.split(".")[0]
            if root_module in FORBIDDEN_MODULES:
                raise SecurityViolationError(f"Import from '{node.module}' is forbidden in WasmSandbox")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_BUILTINS and isinstance(node.ctx, ast.Load):
            raise SecurityViolationError(f"Access to builtin '{node.id}' is forbidden in WasmSandbox")
        self.generic_visit(node)


class WasmSandbox(BaseSandbox):
    def __init__(
        self,
        workspace_dir: Path,
        timeout_seconds: float = 5.0,
        memory_limit_mb: int = 128,
    ):
        super().__init__(workspace_dir=workspace_dir, timeout_seconds=timeout_seconds)
        self.memory_limit_mb = memory_limit_mb
        self.jail = FilesystemJail(self.workspace_dir)
        self._wasmtime_available = self._check_wasmtime()

    def _check_wasmtime(self) -> bool:
        try:
            import wasmtime  # noqa: F401
            return True
        except ImportError:
            return False

    async def execute_command(
        self,
        command: str,
        stdin: str = "",
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """
        Executes code inside the WASM or isolated AST runner.
        If command ends with .wasm, loads and executes WebAssembly module.
        Otherwise treats command as a Python script or expression.
        """
        start_time = time.perf_counter()
        before_snapshot = self.jail.scan_workspace()

        # Check if executing a wasm file
        if command.endswith(".wasm") and (self.workspace_dir / command).is_file():
            return await self._execute_wasm_binary(self.workspace_dir / command, start_time)

        # Execute as isolated Python code block
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        exit_code = 0

        def run_isolated() -> None:
            nonlocal exit_code
            try:
                tree = ast.parse(command)
                CodeSafetyVisitor().visit(tree)

                safe_builtins = {
                    k: v
                    for k, v in __builtins__.items()
                    if k not in FORBIDDEN_BUILTINS
                } if isinstance(__builtins__, dict) else {
                    k: getattr(__builtins__, k)
                    for k in dir(__builtins__)
                    if k not in FORBIDDEN_BUILTINS
                }

                # Provide sandboxed workspace file access
                def safe_read(path: str) -> str:
                    return self.read_file(path)

                def safe_write(path: str, content: str) -> None:
                    self.write_file(path, content)

                sandbox_globals = {
                    "__builtins__": safe_builtins,
                    "read_file": safe_read,
                    "write_file": safe_write,
                    "list_files": self.list_files,
                }

                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = stdout_capture, stderr_capture
                try:
                    compiled = compile(tree, filename="<sandbox>", mode="exec")
                    eval(compiled, sandbox_globals)  # noqa: S307
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr

            except SecurityViolationError as sec_err:
                exit_code = 1
                stderr_capture.write(f"Security violation: {sec_err}\n")
            except Exception as exc:
                exit_code = 1
                stderr_capture.write(f"Runtime error: {type(exc).__name__}: {exc}\n")

        try:
            await asyncio.wait_for(
                asyncio.to_thread(run_isolated),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            exit_code = 124
            stderr_capture.write(f"Execution timed out after {self.timeout_seconds} seconds\n")

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        after_snapshot = self.jail.scan_workspace()
        diff = self.jail.compute_diff(before_snapshot, after_snapshot)

        return SandboxResult(
            stdout=stdout_capture.getvalue(),
            stderr=stderr_capture.getvalue(),
            exit_code=exit_code,
            duration_ms=elapsed_ms,
            files_created=diff.created,
            files_modified=diff.modified,
            files_deleted=diff.deleted,
        )

    async def _execute_wasm_binary(self, wasm_file: Path, start_time: float) -> SandboxResult:
        if not self._wasmtime_available:
            return SandboxResult(
                stdout="",
                stderr="wasmtime package is not installed. Install with 'uv pip install wasmtime'.",
                exit_code=1,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        try:
            import wasmtime

            engine = wasmtime.Engine()
            store = wasmtime.Store(engine)
            module = wasmtime.Module.from_file(engine, str(wasm_file))
            instance = wasmtime.Instance(store, module, [])
            exports = instance.exports(store)

            # Call start or run function if exported
            run_func = exports.get("run") or exports.get("_start") or exports.get("main")
            if run_func:
                result = run_func(store)
                output = f"WASM execution completed. Output: {result}"
            else:
                output = "WASM module instantiated successfully."

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SandboxResult(stdout=output, exit_code=0, duration_ms=elapsed_ms)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SandboxResult(
                stderr=f"WASM execution failed: {type(exc).__name__}: {exc}",
                exit_code=1,
                duration_ms=elapsed_ms,
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
