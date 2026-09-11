import json
from collections import deque
from typing import Any


class GuardrailViolation(Exception):
    """Raised when an execution guardrail is violated."""


class InfiniteLoopError(GuardrailViolation):
    """Raised when an agent repeats the same action repeatedly."""


class BudgetExceededError(GuardrailViolation):
    """Raised when cumulative token expenditure exceeds financial limit."""


class StepLimitExceededError(GuardrailViolation):
    """Raised when maximum step count is reached."""


MODEL_COST_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    # model: (prompt_cost_per_m, completion_cost_per_m)
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "gpt-4o": (5.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "mock": (0.0, 0.0),
    "ollama": (0.0, 0.0),
}


class InfiniteLoopDetector:
    def __init__(self, threshold: int = 3, history_size: int = 10):
        self.threshold = threshold
        self.history: deque[str] = deque(maxlen=history_size)

    def record_and_check(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """
        Records an action signature and returns a warning string if a loop is detected.
        Raises InfiniteLoopError if the threshold is exceeded.
        """
        try:
            canonical_args = json.dumps(arguments, sort_keys=True)
        except Exception:
            canonical_args = str(arguments)

        signature = f"{tool_name}:{canonical_args}"
        self.history.append(signature)

        count = sum(1 for item in self.history if item == signature)
        if count >= self.threshold:
            raise InfiniteLoopError(
                f"Infinite loop detected: tool '{tool_name}' invoked {count} times "
                f"with identical arguments: {canonical_args}"
            )

        # Check for 2-step oscillation (A -> B -> A -> B)
        if len(self.history) >= 4:
            items = list(self.history)
            if items[-1] == items[-3] and items[-2] == items[-4] and items[-1] != items[-2]:
                return (
                    f"Warning: oscillating tool pattern detected between "
                    f"'{items[-1].split(':')[0]}' and '{items[-2].split(':')[0]}'. "
                    f"Consider a different approach."
                )

        return None


class BudgetController:
    def __init__(self, max_budget_usd: float = 1.0, model_name: str = "claude-3-7-sonnet"):
        self.max_budget_usd = max_budget_usd
        self.model_name = model_name
        self.cumulative_prompt_tokens: int = 0
        self.cumulative_completion_tokens: int = 0

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # Find matching rates or default
        rates = MODEL_COST_PER_MILLION_TOKENS.get(
            self.model_name,
            MODEL_COST_PER_MILLION_TOKENS["claude-3-7-sonnet"],
        )
        prompt_cost = (prompt_tokens / 1_000_000.0) * rates[0]
        completion_cost = (completion_tokens / 1_000_000.0) * rates[1]
        return prompt_cost + completion_cost

    def record_and_check(self, prompt_tokens: int, completion_tokens: int) -> float:
        self.cumulative_prompt_tokens += prompt_tokens
        self.cumulative_completion_tokens += completion_tokens
        total_cost = self.calculate_cost(
            self.cumulative_prompt_tokens,
            self.cumulative_completion_tokens,
        )

        if total_cost > self.max_budget_usd:
            raise BudgetExceededError(
                f"Budget limit of ${self.max_budget_usd:.2f} exceeded: "
                f"current spend is ${total_cost:.4f}"
            )

        return total_cost

    @property
    def total_cost_usd(self) -> float:
        return self.calculate_cost(
            self.cumulative_prompt_tokens,
            self.cumulative_completion_tokens,
        )
