import asyncio
import json
import logging
from typing import Any

from pydantic import create_model

from ..core.tool_registry import ToolDefinition, ToolRegistry

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for communicating with external MCP servers over stdio."""

    def __init__(self, command: list[str]):
        self.command = command
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def connect(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send initialize handshake
        init_res = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AgentHarness", "version": "0.1.0"},
            },
        )
        logger.debug("MCP server initialized: %s", init_res)
        await self._send_notification("notifications/initialized", {})

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP process is not running")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(payload) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

        # Read JSON-RPC response line
        resp_line = await self.process.stdout.readline()
        if not resp_line:
            raise RuntimeError("MCP server closed connection unexpectedly")

        data = json.loads(resp_line.decode("utf-8"))
        if "error" in data:
            raise RuntimeError(f"MCP RPC Error: {data['error']}")
        return data.get("result", {})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(payload) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        content_items = result.get("content", [])
        text_outputs = [
            item["text"] for item in content_items if item.get("type") == "text"
        ]
        return "\n".join(text_outputs) if text_outputs else str(result)

    async def register_into_registry(self, registry: ToolRegistry) -> int:
        """Query MCP server tools and register them into an AgentHarness ToolRegistry."""
        tools = await self.list_tools()
        registered_count = 0

        for t in tools:
            name = t["name"]
            desc = t.get("description", "")
            input_schema = t.get("inputSchema", {})

            # Build a dynamic Pydantic model from schema properties
            fields: dict[str, Any] = {}
            props = input_schema.get("properties", {})
            reqs = input_schema.get("required", [])

            for prop_name, _ in props.items():
                if prop_name in reqs:
                    fields[prop_name] = (Any, ...)
                else:
                    fields[prop_name] = (Any, None)

            args_model = create_model(f"MCP_{name}_Args", **fields)

            # Define invocation closure
            async def make_invoker(tool_name: str):
                async def invoker(**kwargs: Any) -> str:
                    return await self.call_tool(tool_name, kwargs)

                return invoker

            func = await make_invoker(name)
            tool_def = ToolDefinition(
                name=name,
                description=desc,
                func=func,
                args_model=args_model,
            )
            registry.add_tool(tool_def)
            registered_count += 1

        return registered_count

    async def close(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
