import datetime
import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field


class NodeType(StrEnum):
    GOAL = "GOAL"
    THOUGHT = "THOUGHT"
    TOOL_CALL = "TOOL_CALL"
    OBSERVATION = "OBSERVATION"
    INTERVENTION = "INTERVENTION"
    FINAL_ANSWER = "FINAL_ANSWER"
    ERROR = "ERROR"


class DecisionNode(BaseModel):
    id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex[:12]}")
    step_index: int = 0
    branch_id: str = "main"
    parent_ids: list[str] = Field(default_factory=list)
    node_type: NodeType
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )
    checkpoint_id: str | None = None
    token_usage: int = 0
    cost_usd: float = 0.0

    def compute_hash(self, parent_hashes: list[str]) -> str:
        """Compute SHA-256 content address derived from parent hashes and payload."""
        hasher = hashlib.sha256()
        for ph in sorted(parent_hashes):
            hasher.update(ph.encode("utf-8"))
        canonical_content = json.dumps(self.payload, sort_keys=True)
        hasher.update(canonical_content.encode("utf-8"))
        hasher.update(self.node_type.value.encode("utf-8"))
        return hasher.hexdigest()


class DecisionDAG:
    def __init__(self, run_id: str, goal: str):
        self.run_id = run_id
        self.goal = goal
        self.graph = nx.DiGraph()
        self.nodes_by_id: dict[str, DecisionNode] = {}
        self.root_node_id: str | None = None
        self.current_leaf_id: str | None = None
        self.step_counter = 0

        # Create and insert root GOAL node
        root = DecisionNode(
            step_index=0,
            branch_id="main",
            parent_ids=[],
            node_type=NodeType.GOAL,
            title="Goal",
            payload={"goal": goal},
        )
        root.content_hash = root.compute_hash([])
        self.add_node(root)
        self.root_node_id = root.id
        self.current_leaf_id = root.id

    def add_node(self, node: DecisionNode) -> None:
        """Add a decision node and establish edges from all parent nodes."""
        parent_hashes = [
            self.nodes_by_id[pid].content_hash
            for pid in node.parent_ids
            if pid in self.nodes_by_id
        ]
        node.content_hash = node.compute_hash(parent_hashes)

        self.nodes_by_id[node.id] = node
        self.graph.add_node(node.id, data=node.model_dump())

        for parent_id in node.parent_ids:
            if parent_id in self.nodes_by_id:
                self.graph.add_edge(parent_id, node.id)

        self.current_leaf_id = node.id

    def create_child_node(
        self,
        node_type: NodeType,
        title: str,
        payload: dict[str, Any],
        parent_id: str | None = None,
        branch_id: str | None = None,
        checkpoint_id: str | None = None,
        token_usage: int = 0,
        cost_usd: float = 0.0,
    ) -> DecisionNode:
        """Helper to create, link, and add a child decision node."""
        parent = parent_id or self.current_leaf_id
        self.step_counter += 1

        parent_node = self.nodes_by_id.get(parent) if parent else None
        inherited_branch = branch_id or (parent_node.branch_id if parent_node else "main")

        node = DecisionNode(
            step_index=self.step_counter,
            branch_id=inherited_branch,
            parent_ids=[parent] if parent else [],
            node_type=node_type,
            title=title,
            payload=payload,
            checkpoint_id=checkpoint_id,
            token_usage=token_usage,
            cost_usd=cost_usd,
        )
        self.add_node(node)
        return node

    def get_node(self, node_id: str) -> DecisionNode | None:
        return self.nodes_by_id.get(node_id)

    def get_parents(self, node_id: str) -> list[DecisionNode]:
        node = self.get_node(node_id)
        if not node:
            return []
        return [self.nodes_by_id[pid] for pid in node.parent_ids if pid in self.nodes_by_id]

    def get_children(self, node_id: str) -> list[DecisionNode]:
        if node_id not in self.graph:
            return []
        child_ids = list(self.graph.successors(node_id))
        return [self.nodes_by_id[cid] for cid in child_ids if cid in self.nodes_by_id]

    def get_trajectory(self, leaf_node_id: str | None = None) -> list[DecisionNode]:
        """Return the linear chain of decision nodes from root to specified leaf."""
        target_id = leaf_node_id or self.current_leaf_id
        if not target_id or target_id not in self.nodes_by_id:
            return []

        chain = []
        curr: str | None = target_id
        while curr and curr in self.nodes_by_id:
            node = self.nodes_by_id[curr]
            chain.append(node)
            curr = node.parent_ids[0] if node.parent_ids else None

        return list(reversed(chain))

    def list_branches(self) -> list[str]:
        branches = {node.branch_id for node in self.nodes_by_id.values()}
        return sorted(branches)

    def to_cytoscape_elements(self) -> list[dict[str, Any]]:
        """Export graph into Cytoscape.js elements for web visualizer."""
        elements = []
        for node in self.nodes_by_id.values():
            elements.append({
                "data": {
                    "id": node.id,
                    "label": f"#{node.step_index} {node.title or node.node_type.value}",
                    "type": node.node_type.value,
                    "branch": node.branch_id,
                    "checkpoint": node.checkpoint_id,
                    "step": node.step_index,
                    "cost": f"${node.cost_usd:.4f}",
                }
            })

        for u, v in self.graph.edges():
            elements.append({
                "data": {
                    "id": f"edge_{u}_{v}",
                    "source": u,
                    "target": v,
                }
            })
        return elements

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "root_node_id": self.root_node_id,
            "current_leaf_id": self.current_leaf_id,
            "step_counter": self.step_counter,
            "nodes": [node.model_dump() for node in self.nodes_by_id.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionDAG":
        dag = cls(run_id=data["run_id"], goal=data["goal"])
        dag.nodes_by_id.clear()
        dag.graph.clear()
        dag.root_node_id = data.get("root_node_id")
        dag.current_leaf_id = data.get("current_leaf_id")
        dag.step_counter = data.get("step_counter", 0)

        for raw_node in data.get("nodes", []):
            node = DecisionNode.model_validate(raw_node)
            dag.nodes_by_id[node.id] = node
            dag.graph.add_node(node.id, data=node.model_dump())
            for pid in node.parent_ids:
                dag.graph.add_edge(pid, node.id)

        return dag
