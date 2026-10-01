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

    def format_tools(self, tool_registry: Any) -> list[dict[str, Any]]:
        if hasattr(tool_registry, "to_anthropic_tools"):
            return tool_registry.to_anthropic_tools()
        if isinstance(tool_registry, (list, tuple)):
            return [t.to_anthropic() if hasattr(t, "to_anthropic") else t for t in tool_registry]
        return []

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
            role = msg.get("role")
            if role == "system":
                system = msg.get("content", "")
                continue

            if role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", "unknown"),
                    "content": str(msg.get("content", "")),
                }
                # If the previous message was also a user message containing tool results, merge them
                if anthropic_messages and anthropic_messages[-1]["role"] == "user" and isinstance(anthropic_messages[-1]["content"], list):
                    anthropic_messages[-1]["content"].append(tool_result_block)
                else:
                    anthropic_messages.append({
                        "role": "user",
                        "content": [tool_result_block],
                    })
            elif role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                text_content = msg.get("content", "")
                if text_content:
                    content_blocks.append({"type": "text", "text": text_content})
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "tool_call")
                    func = tc.get("function", {})
                    tc_name = func.get("name") or tc.get("name", "tool")
                    tc_args = func.get("arguments", {}) if func else tc.get("arguments", {})
                    if isinstance(tc_args, str):
                        try:
                            import json
                            tc_args = json.loads(tc_args)
                        except Exception:
                            tc_args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc_id,
                        "name": tc_name,
                        "input": tc_args,
                    })
                anthropic_messages.append({
                    "role": "assistant",
                    "content": content_blocks if content_blocks else text_content,
                })
            else:
                anthropic_messages.append({
                    "role": role,
                    "content": msg.get("content", ""),
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
