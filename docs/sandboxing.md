# Sandboxing and Containment Guide

AgentHarness provides three isolation backends for tool and script execution. This document explains their security properties, resource boundaries, and configuration parameters.

## Isolation Backends

### 1. WebAssembly Sandbox (`WasmSandbox`)

The WebAssembly sandbox executes compiled modules or interpreted scripts using the `wasmtime` runtime.

- Cold start latency: under 5 milliseconds.
- Host filesystem access: denied completely by default. Only pre-opened virtual directories can be mapped.
- Host network access: completely disabled. WebAssembly code cannot initiate socket connections.
- Memory ceiling: configured per instance (default 128 MB). If the process exceeds this allocation, the WebAssembly engine traps and reports an out of memory error.
- Recommended for: safe evaluation of Python scripts via Pyodide or Rust compiled binaries where network access is forbidden.

### 2. Ephemeral Docker Container (`ContainerSandbox`)

For bash commands, compilation tasks, and multi-file project refactoring, the container sandbox spins up a non-root micro-container.

- Base image: `python:3.12-slim` or custom developer images.
- Privileges: runs as unprivileged UID 1000 with `no-new-privileges` flag enabled.
- Root filesystem: mounted as read-only.
- Temporary storage: an in-memory `tmpfs` mounted at `/tmp` (maximum size 64 MB).
- Workspace storage: the isolated project directory mounted at `/workspace`.
- Resource constraints:
  - CPU quota: 0.5 CPU core limit.
  - Memory limit: 256 MB with swap disabled.
  - Execution timeout: 10 seconds default per command.
  - Network isolation: network mode set to `none` unless the user explicitly enables internet access for package installation tools.

### 3. Native Process Sandbox (`ProcessSandbox`)

When Docker is unavailable on the host developer workstation, AgentHarness falls back to the native process sandbox.

- Working directory jail: execution is strictly contained within a designated temporary workspace.
- Path traversal verification: all file paths referenced in tool calls are checked against the root workspace directory. Any path resolving outside this directory raises a security violation error.
- Process isolation: commands run as isolated child processes with detached process groups. If a command times out, the entire process tree is terminated.
- Environment scrubbing: sensitive environment variables (such as `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, or private SSH keys) are stripped from child processes.

## Filesystem Jail and Copy-On-Write Diffs

Each sandbox operates on top of a `FilesystemJail`:

1. Pre-execution fingerprint: before a tool executes, the jail records file names, sizes, and content SHA-256 hashes inside the workspace.
2. Tool execution: the sandbox runs the requested command inside the workspace.
3. Post-execution diff: the jail recalculates file hashes, detecting:
   - Added files
   - Modified files (producing unified unified diff patches)
   - Deleted files
4. Snapshot generation: file states can be saved as immutable checkpoints, enabling the debugger to roll back changes when an execution branch is rewound.
