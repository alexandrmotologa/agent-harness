from collections.abc import Callable
from typing import Any

from .base import BaseProvider, LLMResponse, LLMToolCall


class MockProvider(BaseProvider):
    def __init__(
        self,
        model: str = "mock-agent",
        responses: list[LLMResponse] | None = None,
        responder: Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], LLMResponse]
        | None = None,
    ):
        super().__init__(model=model)
        self.responses = list(responses) if responses else []
        self.responder = responder
        self.call_count = 0
        self.received_messages: list[list[dict[str, Any]]] = []

    def queue_response(self, response: LLMResponse) -> None:
        self.responses.append(response)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.received_messages.append(messages)

        if self.responder:
            return self.responder(messages, tools)

        if self.responses:
            return self.responses.pop(0)

        # Default fallback response if no scripted response was queued
        last_msg = messages[-1] if messages else {}
        content = last_msg.get("content", "")

        # If a tool result was returned, provide a final completion
        if last_msg.get("role") == "tool":
            return LLMResponse(
                content=f"Task complete based on observation: {content[:100]}",
                prompt_tokens=50,
                completion_tokens=25,
            )

        # Otherwise, call the first tool if available
        if tools:
            first_tool = tools[0]
            # Handle both Anthropic and OpenAI tool formats
            name = (
                first_tool.get("name")
                or first_tool.get("function", {}).get("name")
                or "unknown_tool"
            )
            return LLMResponse(
                content="I will run the requested tool to solve this task.",
                tool_calls=[
                    LLMToolCall(
                        id=f"call_{self.call_count}",
                        name=name,
                        arguments={"command": "echo 'Hello from AgentHarness Sandbox'"},
                    )
                ],
                prompt_tokens=40,
                completion_tokens=20,
            )

        return LLMResponse(
            content="I am a mock agent. Your task has been processed.",
            prompt_tokens=20,
            completion_tokens=15,
        )
