from agent_harness.graph.decision_dag import DecisionDAG, NodeType


def test_dag_creation_and_hashing(sample_dag):
    assert sample_dag.root_node_id is not None
    root = sample_dag.get_node(sample_dag.root_node_id)
    assert root.node_type == NodeType.GOAL
    assert root.content_hash != ""

    # Add thought node
    thought = sample_dag.create_child_node(
        node_type=NodeType.THOUGHT,
        title="Formulate strategy",
        payload={"thought": "Step 1: Check existing files"},
    )
    assert thought.parent_ids == [root.id]
    assert thought.content_hash != ""
    assert thought.content_hash != root.content_hash

    # Add tool call node
    tool_call = sample_dag.create_child_node(
        node_type=NodeType.TOOL_CALL,
        title="list_files",
        payload={"tool_name": "list_files", "arguments": {}},
    )
    assert tool_call.parent_ids == [thought.id]


def test_dag_trajectory_extraction(sample_dag):
    sample_dag.create_child_node(NodeType.THOUGHT, "T1", {"t": 1})
    sample_dag.create_child_node(NodeType.TOOL_CALL, "TC1", {"tc": 1})
    n3 = sample_dag.create_child_node(NodeType.OBSERVATION, "O1", {"o": 1})

    trajectory = sample_dag.get_trajectory(n3.id)
    assert len(trajectory) == 4  # Root + 3 steps
    assert [n.node_type for n in trajectory] == [
        NodeType.GOAL,
        NodeType.THOUGHT,
        NodeType.TOOL_CALL,
        NodeType.OBSERVATION,
    ]


def test_dag_serialization(sample_dag):
    sample_dag.create_child_node(NodeType.THOUGHT, "Thought 1", {"thought": "Test"})
    data = sample_dag.to_dict()

    restored = DecisionDAG.from_dict(data)
    assert restored.run_id == sample_dag.run_id
    assert restored.goal == sample_dag.goal
    assert len(restored.nodes_by_id) == len(sample_dag.nodes_by_id)

    cytoscape_elements = restored.to_cytoscape_elements()
    assert len(cytoscape_elements) >= 2
