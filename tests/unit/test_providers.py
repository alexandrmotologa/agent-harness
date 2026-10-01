from pydantic import BaseModel, Field

from agent_harness.core.tool_registry import ToolDefinition
from agent_harness.providers.anthropic import AnthropicProvider
from agent_harness.providers.deepseek import DeepSeekProvider
from agent_harness.providers.gemini import GeminiProvider
from agent_harness.providers.openai import OpenAIProvider


class CalcArgs(BaseModel):
    expr: str = Field(..., description="Expression to evaluate")


def dummy_calc(expr: str) -> str:
    return expr


def test_provider_tool_formatting():
    tool = ToolDefinition(
        name="calculate",
        description="Perform arithmetic",
        func=dummy_calc,
        args_model=CalcArgs,
    )

    # Gemini formatting (OpenAI compatible endpoint)
    gemini = GeminiProvider(api_key="test-key")
    gemini_tools = gemini.format_tools([tool])
    assert gemini_tools[0]["type"] == "function"
    assert gemini_tools[0]["function"]["name"] == "calculate"

    # DeepSeek formatting (OpenAI format)
    deepseek = DeepSeekProvider(api_key="test-key")
    ds_tools = deepseek.format_tools([tool])
    assert ds_tools[0]["type"] == "function"
    assert ds_tools[0]["function"]["name"] == "calculate"

    # OpenAI formatting
    openai = OpenAIProvider(api_key="test-key")
    oai_tools = openai.format_tools([tool])
    assert oai_tools[0]["type"] == "function"
    assert oai_tools[0]["function"]["name"] == "calculate"

    # Anthropic formatting
    anthropic = AnthropicProvider(api_key="test-key")
    ant_tools = anthropic.format_tools([tool])
    assert ant_tools[0]["name"] == "calculate"
    assert "input_schema" in ant_tools[0]
