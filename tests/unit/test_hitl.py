import pytest

from agent_harness.core.hitl import (
    ActionDecision,
    ApprovalPolicy,
    BaseInterventionHandler,
    InterventionResponse,
)
from agent_harness.core.loop import AutonomousLoop
from agent_harness.graph.decision_dag import NodeType
from agent_harness.providers.base import LLMResponse, LLMToolCall
from agent_harness.providers.mock import MockProvider
from agent_harness.sandbox.process_sandbox import ProcessSandbox


class MockInterventionHandler(BaseInterventionHandler):
    def __init__(self, decision: ActionDecision, modified_args: dict | None = None, reason: str | None = None):
        self.decision = decision
        self.modified_args = modified_args
        self.reason = reason
        self.interceptions = []

    async def handle_intervention(self, tool_name: str, arguments: dict, trigger_reason: str) -> InterventionResponse:
        self.interceptions.append({"tool": tool_name, "args": arguments})
        return InterventionResponse(
            decision=self.decision,
            modified_arguments=self.modified_args,
            denial_reason=self.reason,
        )


def test_approval_policy_triggers():
    policy = ApprovalPolicy(require_commands=True, flagged_command_keywords=["rm", "del"])

    assert policy.should_require_approval("execute_command", {"command": "rm -rf build"})
    assert policy.should_require_approval("execute_command", {"command": "del file.txt"})
    assert not policy.should_require_approval("execute_command", {"command": "echo hello"})
    assert not policy.should_require_approval("read_file", {"path": "test.txt"})


@pytest.mark.asyncio
async def test_hitl_denial_interception(temp_workspace):
    sandbox = ProcessSandbox(workspace_dir=temp_workspace)
    handler = MockInterventionHandler(
        decision=ActionDecision.DENY,
        reason="Security policy: deleting files is forbidden.",
    )

    provider = MockProvider(
        responses=[
            LLMResponse(
                content="Attempting dangerous deletion",
                tool_calls=[LLMToolCall(id="c1", name="execute_command", arguments={"command": "rm file.txt"})],
            ),
            LLMResponse(content="Understood, I will skip deleting the file."),
        ]
    )

    loop = AutonomousLoop(
        goal="Test dangerous action",
        sandbox=sandbox,
        provider=provider,
        hitl_handler=handler,
        approval_policy=ApprovalPolicy(require_all=True),
    )

    result = await loop.run()
    assert result.success
    assert len(handler.interceptions) == 1

    # Verify intervention node was recorded in DAG
    intervention_nodes = [
        n for n in loop.dag.nodes_by_id.values()
        if n.node_type == NodeType.INTERVENTION
    ]
    assert len(intervention_nodes) == 1
    assert "Security policy" in intervention_nodes[0].payload.get("denial_reason", "")
