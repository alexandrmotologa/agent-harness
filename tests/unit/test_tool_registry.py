import pytest

from agent_harness.core.tool_registry import ToolRegistry


def test_tool_registration_and_schema():
    registry = ToolRegistry()

    @registry.register(name="add_numbers", description="Adds two numbers together.")
    def add_numbers(a: int, b: int) -> int:
        return a + b

    tool = registry.get_tool("add_numbers")
    assert tool is not None
    assert tool.name == "add_numbers"
    assert tool.description == "Adds two numbers together."

    schema = tool.get_parameters_schema()
    assert "properties" in schema
    assert "a" in schema["properties"]
    assert "b" in schema["properties"]

    anthropic_def = tool.to_anthropic()
    assert anthropic_def["name"] == "add_numbers"
    assert "input_schema" in anthropic_def

    openai_def = tool.to_openai()
    assert openai_def["type"] == "function"
    assert openai_def["function"]["name"] == "add_numbers"


@pytest.mark.asyncio
async def test_tool_execution_success():
    registry = ToolRegistry()

    @registry.register()
    def multiply(x: float, y: float) -> float:
        return x * y

    result = await registry.execute("multiply", {"x": 3.5, "y": 2.0})
    assert not result.is_error
    assert result.output == "7.0"
    assert result.execution_time_ms >= 0


@pytest.mark.asyncio
async def test_tool_execution_validation_error():
    registry = ToolRegistry()

    @registry.register()
    def greet(name: str, count: int) -> str:
        return name * count

    # Pass invalid argument types
    result = await registry.execute("greet", {"name": "hi", "count": "not_an_int"})
    assert result.is_error
    assert "ValidationError" in result.output


@pytest.mark.asyncio
async def test_missing_tool():
    registry = ToolRegistry()
    result = await registry.execute("non_existent", {})
    assert result.is_error
    assert "not found" in result.output
