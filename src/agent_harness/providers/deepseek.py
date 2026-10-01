import json
import os
from typing import Any

import httpx

from .base import BaseProvider, LLMResponse, LLMToolCall


class DeepSeekProvider(BaseProvider):
    """DeepSeek LLM provider (deepseek-chat and deepseek-reasoner)."""

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url=base_url,
        )

    def format_tools(self, tool_registry: Any) -> list[dict[str, Any]]:
        if hasattr(tool_registry, "to_openai_tools"):
            return tool_registry.to_openai_tools()
        if isinstance(tool_registry, (list, tuple)):
            return [t.to_openai() if hasattr(t, "to_openai") else t for t in tool_registry]
        return []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("DeepSeek API key is required. Set DEEPSEEK_API_KEY environment variable.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        deepseek_messages = []
        if system:
            deepseek_messages.append({"role": "system", "content": system})

        for msg in messages:
            item: dict[str, Any] = {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            if msg.get("tool_calls"):
                item["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                item["tool_call_id"] = msg["tool_call_id"]
            if msg.get("name"):
                item["name"] = msg["name"]
            deepseek_messages.append(item)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": deepseek_messages,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""

        tool_calls = []
        if "tool_calls" in message and message["tool_calls"]:
            for tc in message["tool_calls"]:
                func = tc["function"]
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except Exception:
                    args = {}
                tool_calls.append(
                    LLMToolCall(
                        id=tc["id"],
                        name=func["name"],
                        arguments=args,
                    )
                )

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )
