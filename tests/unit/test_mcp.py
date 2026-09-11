import pytest

from agent_harness.mcp.server import MCPServer
from agent_harness.sandbox.process_sandbox import ProcessSandbox


@pytest.mark.asyncio
async def test_mcp_server_manifest_and_execution(temp_workspace):
    sandbox = ProcessSandbox(workspace_dir=temp_workspace)
    server = MCPServer(sandbox=sandbox)

    manifest = server.get_tools_manifest()
    assert len(manifest) >= 4
    tool_names = [t["name"] for t in manifest]
    assert "sandboxed_execute_command" in tool_names
    assert "sandboxed_write_file" in tool_names
    assert "sandboxed_read_file" in tool_names
    assert "sandboxed_list_files" in tool_names

    # Test writing a file via MCP tool call
    write_res = await server.handle_tool_call(
        "sandboxed_write_file",
        {"path": "mcp_test.txt", "content": "Hello from MCP protocol"},
    )
    assert "Wrote" in write_res

    # Test reading back
    read_res = await server.handle_tool_call(
        "sandboxed_read_file",
        {"path": "mcp_test.txt"},
    )
    assert read_res == "Hello from MCP protocol"

    # Test command execution
    exec_res = await server.handle_tool_call(
        "sandboxed_execute_command",
        {"command": 'python -c "print(40 + 2)"'},
    )
    assert "42" in exec_res
