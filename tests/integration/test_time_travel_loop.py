import pytest

from agent_harness.config import HarnessConfig
from agent_harness.core.loop import AutonomousLoop
from agent_harness.engine.debugger import TimeTravelDebugger
from agent_harness.providers.base import LLMResponse, LLMToolCall
from agent_harness.providers.mock import MockProvider
from agent_harness.sandbox.process_sandbox import ProcessSandbox


@pytest.mark.asyncio
async def test_end_to_end_loop_and_rewind_branching(temp_workspace):
    # Setup sandbox
    snapshot_dir = temp_workspace.parent / "test_snaps"
    sandbox = ProcessSandbox(workspace_dir=temp_workspace, snapshot_storage_dir=snapshot_dir)

    # Setup scripted responses for branch 1:
    # Step 1: LLM decides to write a file
    # Step 2: LLM completes task
    provider = MockProvider(
        responses=[
            LLMResponse(
                content="I will write prime numbers to primes.txt",
                tool_calls=[
                    LLMToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={"path": "primes.txt", "content": "2, 3, 5, 7"},
                    )
                ],
                prompt_tokens=100,
                completion_tokens=50,
            ),
            LLMResponse(
                content="Primes have been written. Completing task.",
                tool_calls=[
                    LLMToolCall(
                        id="call_2",
                        name="finish_task",
                        arguments={"answer": "Saved primes [2, 3, 5, 7] to primes.txt"},
                    )
                ],
                prompt_tokens=80,
                completion_tokens=30,
            ),
        ]
    )

    config = HarnessConfig()
    loop = AutonomousLoop(
        goal="Write prime numbers to primes.txt",
        sandbox=sandbox,
        provider=provider,
        config=config,
    )

    result = await loop.run()
    assert result.success
    assert result.steps_taken >= 2
    assert "primes.txt" in sandbox.list_files()
    assert sandbox.read_file("primes.txt") == "2, 3, 5, 7"

    # Now test Time-Travel Rewind & Branching
    # Rewind to step 1 (before finish_task) and inject new instruction
    new_provider = MockProvider(
        responses=[
            LLMResponse(
                content="Rewound: Appending 11 and 13 to primes.txt",
                tool_calls=[
                    LLMToolCall(
                        id="call_branch_1",
                        name="write_file",
                        arguments={"path": "primes.txt", "content": "2, 3, 5, 7, 11, 13"},
                    )
                ],
                prompt_tokens=90,
                completion_tokens=40,
            ),
            LLMResponse(
                content="Finished branched execution.",
                tool_calls=[
                    LLMToolCall(
                        id="call_branch_2",
                        name="finish_task",
                        arguments={"answer": "Saved extended primes to primes.txt"},
                    )
                ],
                prompt_tokens=70,
                completion_tokens=25,
            ),
        ]
    )

    debugger = TimeTravelDebugger(
        dag=loop.dag,
        sandbox=sandbox,
        provider=new_provider,
        config=config,
    )

    branch_result, comparison = await debugger.rewind_and_branch(
        target_step_or_id=1,
        new_instruction="Also include 11 and 13 in primes.txt",
        new_branch_name="branch_primes_extended",
    )

    assert branch_result.success
    assert branch_result.branch_id == "branch_primes_extended"
    assert sandbox.read_file("primes.txt") == "2, 3, 5, 7, 11, 13"

    # Verify DAG has multiple branches recorded
    branches = loop.dag.list_branches()
    assert "main" in branches
    assert "branch_primes_extended" in branches

    # Verify comparison was computed
    assert comparison is not None
    assert comparison.branch_a.branch_id == "main"
    assert comparison.branch_b.branch_id == "branch_primes_extended"
