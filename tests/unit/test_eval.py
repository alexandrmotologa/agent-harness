import pytest

from agent_harness.eval.models import AssertionType, EvalAssertion, EvalSuite, EvalTestCase
from agent_harness.eval.runner import EvalRunner
from agent_harness.providers.base import LLMResponse, LLMToolCall
from agent_harness.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_eval_runner_suite_execution():
    provider = MockProvider(
        responses=[
            LLMResponse(
                content="Writing data to target.txt",
                tool_calls=[
                    LLMToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "target.txt", "content": "alpha beta gamma"},
                    )
                ],
            ),
            LLMResponse(
                content="Task completed successfully.",
                tool_calls=[
                    LLMToolCall(
                        id="c2",
                        name="finish_task",
                        arguments={"answer": "Generated target.txt with alpha beta gamma"},
                    )
                ],
            ),
        ]
    )

    suite = EvalSuite(
        name="Sanity Suite",
        cases=[
            EvalTestCase(
                id="case_1",
                name="Generate file test",
                goal="Write alpha beta gamma to target.txt",
                assertions=[
                    EvalAssertion(
                        assertion_type=AssertionType.FILE_EXISTS,
                        target="target.txt",
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.FILE_CONTAINS,
                        target="target.txt",
                        expected="alpha beta",
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.MAX_STEPS,
                        expected=5,
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.ANSWER_CONTAINS,
                        expected="target.txt",
                    ),
                ],
            )
        ],
    )

    runner = EvalRunner(provider=provider)
    report = await runner.run_suite(suite)

    assert report.total_cases == 1
    assert report.passed_cases == 1
    assert report.failed_cases == 0
    assert report.results[0].passed


@pytest.mark.asyncio
async def test_eval_new_assertions_and_concurrency():
    provider = MockProvider(
        responses=[
            LLMResponse(
                content="Writing data to code.py",
                tool_calls=[
                    LLMToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "code.py", "content": "print('VERSION=2.4.1')\n"},
                    )
                ],
            ),
            LLMResponse(
                content="Executing code.py",
                tool_calls=[
                    LLMToolCall(
                        id="c2",
                        name="execute_command",
                        arguments={"command": "python -c \"print('VERSION=2.4.1')\""},
                    )
                ],
            ),
            LLMResponse(
                content="Completed.",
                tool_calls=[
                    LLMToolCall(
                        id="c3",
                        name="finish_task",
                        arguments={"answer": "Done. Output matched version pattern."},
                    )
                ],
            ),
        ]
    )

    suite = EvalSuite(
        name="Advanced Assertions Suite",
        cases=[
            EvalTestCase(
                id="case_adv_1",
                name="Regex and exit code verification",
                goal="Check python script output",
                assertions=[
                    EvalAssertion(
                        assertion_type=AssertionType.REGEX_MATCH,
                        target="code.py",
                        expected=r"VERSION=\d+\.\d+\.\d+",
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.EXIT_CODE,
                        expected=0,
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.STDERR_EMPTY,
                    ),
                    EvalAssertion(
                        assertion_type=AssertionType.ANSWER_CONTAINS,
                        expected="version pattern",
                    ),
                ],
            )
        ],
    )

    runner = EvalRunner(provider=provider)
    report = await runner.run_suite(suite, concurrency=2)

    assert report.total_cases == 1
    assert report.passed_cases == 1
    assert report.failed_cases == 0
    assert report.results[0].passed
