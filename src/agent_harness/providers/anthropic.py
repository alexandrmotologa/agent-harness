import os
from typing import Any

import httpx

from .base import BaseProvider, LLMResponse, LLMToolCall


class AnthropicProvider(BaseProvider):
    def __init__(
        self,
        model: str = "claude-3-7-sonnet-20250219",
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
    ):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            base_url=base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("Anthropic API key is required. Set ANTHROPIC_API_KEY environment variable.")

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Filter and format messages for Anthropic API
        anthropic_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                system = msg["content"]
                continue
            if role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", "unknown"),
                        "content": msg["content"],
                    }],
                })
            else:
                anthropic_messages.append({
                    "role": role,
                    "content": msg["content"],
                })

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 4096,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content_parts = []
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input", {}),
                    )
                )

        usage = data.get("usage", {})
        return LLMResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason", "end_turn"),
        )
