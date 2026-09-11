from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


def estimate_tokens(text: str) -> int:
    """Approximate token count using a 4 characters per token heuristic."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class ContextWindowManager:
    def __init__(self, max_tokens: int = 100_000, reserve_output_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.reserve_output_tokens = reserve_output_tokens
        self.messages: list[Message] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> Message:
        msg = Message(
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_call_id=tool_call_id,
            name=name,
        )
        self.messages.append(msg)
        return msg

    def get_estimated_tokens(self) -> int:
        total = 0
        for msg in self.messages:
            total += estimate_tokens(msg.content)
            for tc in msg.tool_calls:
                total += estimate_tokens(str(tc))
        return total

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

    def prune_if_needed(self) -> int:
        """
        Prunes older tool observations if token threshold is exceeded,
        preserving system instructions and initial user goal.
        """
        current_tokens = self.get_estimated_tokens()
        limit = self.max_tokens - self.reserve_output_tokens
        if current_tokens <= limit or len(self.messages) <= 3:
            return 0

        pruned_count = 0
        # Iterate from earliest messages (after system and initial user goal)
        for i in range(2, len(self.messages) - 1):
            msg = self.messages[i]
            if msg.role == "tool" and len(msg.content) > 500:
                msg.content = msg.content[:200] + "\n...[observation truncated for budget]..."
                pruned_count += 1
                if self.get_estimated_tokens() <= limit:
                    break

        return pruned_count

    def to_dict_list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in self.messages:
            item: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                item["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.name:
                item["name"] = msg.name
            result.append(item)
        return result
