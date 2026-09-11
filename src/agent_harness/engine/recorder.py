import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..providers.base import BaseProvider, LLMResponse, LLMToolCall


class CassetteEntry(BaseModel):
    request_hash: str
    messages_summary: str = ""
    response: dict[str, Any]


class Cassette(BaseModel):
    name: str
    entries: list[CassetteEntry] = Field(default_factory=list)


def compute_request_hash(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> str:
    hasher = hashlib.sha256()
    hasher.update(json.dumps(messages, sort_keys=True).encode("utf-8"))
    if tools:
        hasher.update(json.dumps(tools, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


class ReplayProvider(BaseProvider):
    """
    Provider that records live completions to a cassette file or replays
    recorded completions deterministically without invoking external APIs.
    """

    def __init__(
        self,
        cassette_path: Path,
        mode: str = "replay",  # "record" or "replay"
        fallback_provider: BaseProvider | None = None,
        model: str = "replay-agent",
    ):
        super().__init__(model=model)
        self.cassette_path = cassette_path
        self.mode = mode
        self.fallback_provider = fallback_provider
        self.cassette = self._load_cassette()

    def _load_cassette(self) -> Cassette:
        if self.cassette_path.exists():
            try:
                data = json.loads(self.cassette_path.read_text(encoding="utf-8"))
                return Cassette.model_validate(data)
            except Exception:
                pass
        return Cassette(name=self.cassette_path.stem)

    def _save_cassette(self) -> None:
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
        self.cassette_path.write_text(
            json.dumps(self.cassette.model_dump(), indent=2),
            encoding="utf-8",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        req_hash = compute_request_hash(messages, tools)

        # In replay mode, look up match
        if self.mode == "replay":
            for entry in self.cassette.entries:
                if entry.request_hash == req_hash:
                    resp_dict = entry.response
                    tool_calls = [
                        LLMToolCall.model_validate(tc)
                        for tc in resp_dict.get("tool_calls", [])
                    ]
                    return LLMResponse(
                        content=resp_dict.get("content", ""),
                        tool_calls=tool_calls,
                        prompt_tokens=resp_dict.get("prompt_tokens", 0),
                        completion_tokens=resp_dict.get("completion_tokens", 0),
                        finish_reason=resp_dict.get("finish_reason", "stop"),
                    )
            # If not found in replay, raise or fall back
            if not self.fallback_provider:
                raise ValueError(
                    f"No matching cassette entry for request hash '{req_hash}' in '{self.cassette_path}'"
                )

        # Live record mode or fallback
        if self.fallback_provider:
            live_resp = await self.fallback_provider.chat(messages, tools, system)
            entry = CassetteEntry(
                request_hash=req_hash,
                messages_summary=str(messages[-1]) if messages else "",
                response={
                    "content": live_resp.content,
                    "tool_calls": [tc.model_dump() for tc in live_resp.tool_calls],
                    "prompt_tokens": live_resp.prompt_tokens,
                    "completion_tokens": live_resp.completion_tokens,
                    "finish_reason": live_resp.finish_reason,
                },
            )
            self.cassette.entries.append(entry)
            self._save_cassette()
            return live_resp

        raise ValueError("Cannot chat: no fallback provider configured for recording.")
