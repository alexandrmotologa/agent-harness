import asyncio
import json
import sys
from typing import Any

from ..sandbox.base import BaseSandbox


class MCPServer:
    """Exposes an AgentHarness sandbox as a standard MCP server over stdio."""

    def __init__(self, sandbox: BaseSandbox):
        self.sandbox = sandbox

    def get_tools_manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "sandboxed_execute_command",
                "description": "Execute a shell command securely inside the AgentHarness sandbox workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to run"}
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "sandboxed_read_file",
                "description": "Read contents of a file strictly inside the sandbox workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"}
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "sandboxed_write_file",
                "description": "Write text content to a file inside the sandbox workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "content": {"type": "string", "description": "File text content"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "sandboxed_list_files",
                "description": "List files within the sandbox workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Subdirectory to list", "default": "."}
                    },
                },
            },
        ]

    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "sandboxed_execute_command":
            res = await self.sandbox.execute_command(arguments.get("command", ""))
            return res.format_output()
        elif name == "sandboxed_read_file":
            return self.sandbox.read_file(arguments.get("path", ""))
        elif name == "sandboxed_write_file":
            self.sandbox.write_file(arguments.get("path", ""), arguments.get("content", ""))
            return f"Wrote {len(arguments.get('content', ''))} characters."
        elif name == "sandboxed_list_files":
            files = self.sandbox.list_files(arguments.get("directory", "."))
            return json.dumps(files)
        else:
            raise ValueError(f"Unknown tool '{name}'")

    async def run_stdio(self) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except Exception:
                continue

            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "AgentHarness-Sandbox", "version": "0.1.0"},
                    },
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": self.get_tools_manifest()},
                }
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                try:
                    output = await self.handle_tool_call(tool_name, tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": output}],
                            "isError": False,
                        },
                    }
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Error: {exc}"}],
                            "isError": True,
                        },
                    }
            elif method == "notifications/initialized":
                continue
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not found"},
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
