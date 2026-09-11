import pytest

from agent_harness.core.guardrails import (
    BudgetController,
    BudgetExceededError,
    InfiniteLoopDetector,
    InfiniteLoopError,
)


def test_infinite_loop_detection():
    detector = InfiniteLoopDetector(threshold=3)

    detector.record_and_check("read_file", {"path": "main.py"})
    detector.record_and_check("read_file", {"path": "main.py"})

    with pytest.raises(InfiniteLoopError) as exc_info:
        detector.record_and_check("read_file", {"path": "main.py"})

    assert "Infinite loop detected" in str(exc_info.value)
    assert "read_file" in str(exc_info.value)


def test_oscillation_warning():
    detector = InfiniteLoopDetector(threshold=5)

    detector.record_and_check("tool_a", {"x": 1})
    detector.record_and_check("tool_b", {"y": 2})
    detector.record_and_check("tool_a", {"x": 1})
    warning = detector.record_and_check("tool_b", {"y": 2})

    assert warning is not None
    assert "oscillating" in warning.lower()


def test_budget_circuit_breaker():
    controller = BudgetController(max_budget_usd=0.05, model_name="claude-3-7-sonnet")

    # Under budget
    cost1 = controller.record_and_check(prompt_tokens=1000, completion_tokens=500)
    assert cost1 < 0.05

    # Trigger budget limit
    with pytest.raises(BudgetExceededError) as exc_info:
        controller.record_and_check(prompt_tokens=20_000, completion_tokens=10_000)

    assert "Budget limit of $0.05 exceeded" in str(exc_info.value)
