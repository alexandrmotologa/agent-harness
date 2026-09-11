import uuid

from ..config import HarnessConfig
from ..core.loop import AutonomousLoop, RunResult
from ..graph.checkpoint import CheckpointManager
from ..graph.decision_dag import DecisionDAG, DecisionNode, NodeType
from ..graph.diff import BranchComparison, compare_branches
from ..providers.base import BaseProvider
from ..sandbox.base import BaseSandbox


class TimeTravelDebugger:
    def __init__(
        self,
        dag: DecisionDAG,
        sandbox: BaseSandbox,
        provider: BaseProvider,
        config: HarnessConfig | None = None,
    ):
        self.dag = dag
        self.sandbox = sandbox
        self.provider = provider
        self.config = config or HarnessConfig()
        jail = getattr(self.sandbox, "jail", None)
        self.checkpoint_mgr = CheckpointManager(jail) if jail else None

    def find_node(self, step_or_id: int | str) -> DecisionNode | None:
        if isinstance(step_or_id, int):
            for node in self.dag.nodes_by_id.values():
                if node.step_index == step_or_id:
                    return node
            return None
        return self.dag.get_node(step_or_id)

    async def rewind_and_branch(
        self,
        target_step_or_id: int | str,
        new_instruction: str | None = None,
        new_branch_name: str | None = None,
    ) -> tuple[RunResult, BranchComparison | None]:
        """
        Rewinds filesystem to target step checkpoint, forks the conversation DAG,
        injects corrected instructions, and continues execution on the new branch.
        """
        target_node = self.find_node(target_step_or_id)
        if not target_node:
            raise ValueError(f"Target node or step '{target_step_or_id}' not found in DAG")

        # Restore checkpoint if available
        if target_node.checkpoint_id and self.checkpoint_mgr:
            self.checkpoint_mgr.restore_checkpoint(target_node.checkpoint_id)

        branch_name = new_branch_name or f"branch_{uuid.uuid4().hex[:6]}"

        original_leaf_id = self.dag.current_leaf_id

        # Record intervention node in DAG
        intervention_node = self.dag.create_child_node(
            node_type=NodeType.INTERVENTION,
            title=f"Rewind & Branch: {branch_name}",
            payload={
                "target_node_id": target_node.id,
                "target_step": target_node.step_index,
                "new_instruction": new_instruction,
            },
            parent_id=target_node.id,
            branch_id=branch_name,
        )

        # Reconstruct message trajectory up to target node
        history = self.dag.get_trajectory(target_node.id)
        loop = AutonomousLoop(
            goal=self.dag.goal,
            sandbox=self.sandbox,
            provider=self.provider,
            config=self.config,
            existing_dag=self.dag,
            start_node_id=intervention_node.id,
            branch_id=branch_name,
        )

        # Populate context manager with historical conversation
        loop.context_mgr.add_message("system", f"Goal: {self.dag.goal}")
        for n in history:
            if n.node_type == NodeType.THOUGHT:
                loop.context_mgr.add_message("assistant", n.payload.get("thought", ""))
            elif n.node_type == NodeType.OBSERVATION:
                loop.context_mgr.add_message("tool", n.payload.get("output", ""))

        if new_instruction:
            loop.context_mgr.add_message(
                "user",
                f"[Developer Intervention at Step {target_node.step_index}]: {new_instruction}",
            )

        # Execute autonomous loop on new branch
        run_result = await loop.run()
        new_leaf_id = self.dag.current_leaf_id

        comparison = None
        if original_leaf_id and new_leaf_id and original_leaf_id != new_leaf_id:
            comparison = compare_branches(self.dag, original_leaf_id, new_leaf_id)

        return run_result, comparison
