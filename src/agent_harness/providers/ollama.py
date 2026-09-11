from typing import Any

import httpx

from .base import BaseProvider, LLMResponse, LLMToolCall


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
    ):
        super().__init__(model=model, base_url=base_url)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})

        for msg in messages:
            ollama_messages.append({
                "role": msg["role"],
                "content": msg.get("content", ""),
            })

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = []

        if "tool_calls" in message and message["tool_calls"]:
            for idx, tc in enumerate(message["tool_calls"]):
                func = tc.get("function", {})
                tool_calls.append(
                    LLMToolCall(
                        id=f"ollama_{idx}",
                        name=func.get("name", ""),
                        arguments=func.get("arguments", {}),
                    )
                )

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=data.get("done_reason", "stop"),
        )
