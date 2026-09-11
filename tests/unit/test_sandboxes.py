import pytest

from agent_harness.sandbox.container_sandbox import ContainerSandbox
from agent_harness.sandbox.process_sandbox import ProcessSandbox
from agent_harness.sandbox.wasm_sandbox import WasmSandbox


@pytest.mark.asyncio
async def test_process_sandbox_execution(temp_workspace):
    sb = ProcessSandbox(workspace_dir=temp_workspace)

    # Write and read a file
    sb.write_file("test.py", "print('Executed safely inside sandbox')")
    assert sb.read_file("test.py") == "print('Executed safely inside sandbox')"

    # Execute Python in the workspace
    result = await sb.execute_command("python test.py")
    assert result.is_success
    assert "Executed safely inside sandbox" in result.stdout
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_process_sandbox_diff_capture(temp_workspace):
    sb = ProcessSandbox(workspace_dir=temp_workspace)

    # Command that creates a new file
    result = await sb.execute_command("python -c \"open('output.log', 'w').write('data')\"")
    assert result.is_success
    assert "output.log" in result.files_created
    assert "output.log" in sb.list_files()


@pytest.mark.asyncio
async def test_wasm_sandbox_forbidden_imports(temp_workspace):
    sb = WasmSandbox(workspace_dir=temp_workspace)

    # Attempting to import forbidden os module should fail safety visitor
    result = await sb.execute_command("import os\nprint(os.listdir('.'))")
    assert not result.is_success
    assert "Security violation" in result.stderr
    assert "forbidden" in result.stderr


@pytest.mark.asyncio
async def test_wasm_sandbox_safe_code(temp_workspace):
    sb = WasmSandbox(workspace_dir=temp_workspace)

    # Safe algorithm evaluation
    result = await sb.execute_command("nums = [x * 2 for x in range(5)]\nprint(nums)")
    assert result.is_success
    assert "[0, 2, 4, 6, 8]" in result.stdout


def test_container_sandbox_fallback(temp_workspace):
    sb = ContainerSandbox(workspace_dir=temp_workspace)
    # If Docker daemon is absent, fallback should be initialized
    assert sb._fallback_sandbox is not None or sb.is_docker_active
