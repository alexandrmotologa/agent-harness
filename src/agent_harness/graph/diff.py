from typing import Any

from pydantic import BaseModel, Field

from .decision_dag import DecisionDAG, NodeType


class BranchMetrics(BaseModel):
    branch_id: str
    step_count: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    tools_called: list[str] = Field(default_factory=list)
    final_answer: str | None = None
    leaf_node_id: str


class BranchComparison(BaseModel):
    branch_a: BranchMetrics
    branch_b: BranchMetrics
    common_ancestor_node_id: str | None = None
    divergence_step: int = 0
    token_delta: int = 0
    cost_delta_usd: float = 0.0
    file_diff: dict[str, Any] = Field(default_factory=dict)


def extract_branch_metrics(dag: DecisionDAG, leaf_node_id: str) -> BranchMetrics:
    trajectory = dag.get_trajectory(leaf_node_id)
    if not trajectory:
        return BranchMetrics(branch_id="unknown", leaf_node_id=leaf_node_id)

    branch_id = trajectory[-1].branch_id
    total_tokens = sum(n.token_usage for n in trajectory)
    total_cost = sum(n.cost_usd for n in trajectory)
    tools_called = [
        n.payload.get("tool_name", "")
        for n in trajectory
        if n.node_type == NodeType.TOOL_CALL and "tool_name" in n.payload
    ]

    final_node = next(
        (n for n in reversed(trajectory) if n.node_type == NodeType.FINAL_ANSWER),
        None,
    )
    final_answer = (
        final_node.payload.get("answer") or final_node.payload.get("content")
        if final_node
        else None
    )

    return BranchMetrics(
        branch_id=branch_id,
        step_count=len(trajectory),
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        tools_called=tools_called,
        final_answer=final_answer,
        leaf_node_id=leaf_node_id,
    )


def compare_branches(
    dag: DecisionDAG,
    leaf_a_id: str,
    leaf_b_id: str,
) -> BranchComparison:
    """Compare two trajectory branches in the decision graph."""
    metrics_a = extract_branch_metrics(dag, leaf_a_id)
    metrics_b = extract_branch_metrics(dag, leaf_b_id)

    traj_a = dag.get_trajectory(leaf_a_id)
    traj_b = dag.get_trajectory(leaf_b_id)

    # Find lowest common ancestor
    common_ancestor_id = None
    divergence_step = 0
    for na, nb in zip(traj_a, traj_b, strict=False):
        if na.id == nb.id:
            common_ancestor_id = na.id
            divergence_step = na.step_index
        else:
            break

    return BranchComparison(
        branch_a=metrics_a,
        branch_b=metrics_b,
        common_ancestor_node_id=common_ancestor_id,
        divergence_step=divergence_step,
        token_delta=metrics_b.total_tokens - metrics_a.total_tokens,
        cost_delta_usd=metrics_b.total_cost_usd - metrics_a.total_cost_usd,
    )
