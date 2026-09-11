import pytest

from agent_harness.engine.recorder import ReplayProvider
from agent_harness.providers.base import LLMResponse, LLMToolCall
from agent_harness.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_recorder_and_replay_cycle(temp_workspace):
    cassette_file = temp_workspace / "test_cassette.json"

    # Step 1: Record using live MockProvider fallback
    live_mock = MockProvider(
        responses=[
            LLMResponse(
                content="Deterministic recorded response",
                tool_calls=[LLMToolCall(id="c1", name="read_file", arguments={"path": "a.txt"})],
                prompt_tokens=42,
                completion_tokens=18,
            )
        ]
    )

    recorder = ReplayProvider(
        cassette_path=cassette_file,
        mode="record",
        fallback_provider=live_mock,
    )

    messages = [{"role": "user", "content": "What is in a.txt?"}]
    tools = [{"name": "read_file", "description": "Read file", "input_schema": {}}]

    res1 = await recorder.chat(messages, tools)
    assert res1.content == "Deterministic recorded response"
    assert len(res1.tool_calls) == 1
    assert cassette_file.exists()

    # Step 2: Replay mode with no fallback provider
    replayer = ReplayProvider(
        cassette_path=cassette_file,
        mode="replay",
        fallback_provider=None,
    )

    res2 = await replayer.chat(messages, tools)
    assert res2.content == "Deterministic recorded response"
    assert res2.tool_calls[0].name == "read_file"
    assert res2.prompt_tokens == 42
