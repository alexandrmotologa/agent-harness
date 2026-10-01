from agent_harness.export.report import (
    generate_html_report,
    generate_jsonl_dataset,
    generate_mermaid_diagram,
    generate_otel_trace,
)
from agent_harness.graph.decision_dag import DecisionDAG, NodeType


def test_html_report_generation(temp_workspace):
    dag = DecisionDAG(run_id="run_export_01", goal="Test HTML export report generation")
    dag.create_child_node(NodeType.THOUGHT, "Plan", {"thought": "Step 1 Plan"})
    dag.create_child_node(NodeType.FINAL_ANSWER, "Done", {"answer": "Completed successfully."})

    report_path = temp_workspace / "report.html"
    res_path = generate_html_report(dag, report_path)

    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "run_export_01" in content
    assert "cytoscape" in content
    assert "Step 1 Plan" in content


def test_mermaid_diagram_generation(temp_workspace):
    dag = DecisionDAG(run_id="run_export_mermaid", goal="Test Mermaid export")
    n1 = dag.create_child_node(NodeType.THOUGHT, "Analyze task", {"thought": "Let's inspect codebase"})
    dag.create_child_node(NodeType.TOOL_CALL, "read_file", {"tool": "read_file", "args": {"path": "main.py"}}, parent_id=n1.id)
    dag.create_child_node(NodeType.FINAL_ANSWER, "Finished", {"answer": "All done."})

    mermaid_path = temp_workspace / "diagram.mmd"
    mermaid_str = generate_mermaid_diagram(dag, mermaid_path)

    assert mermaid_path.exists()
    assert "flowchart TD" in mermaid_str
    assert "Analyze task" in mermaid_str
    assert "classDef" in mermaid_str


def test_otel_trace_generation(temp_workspace):
    dag = DecisionDAG(run_id="run_export_otel", goal="Test OTEL export")
    dag.create_child_node(NodeType.THOUGHT, "Reasoning", {"thought": "Thinking..."})
    dag.create_child_node(NodeType.FINAL_ANSWER, "Done", {"answer": "Finished"})

    otel_path = temp_workspace / "trace.json"
    trace = generate_otel_trace(dag, otel_path)

    assert otel_path.exists()
    assert "resourceSpans" in trace
    spans = trace["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3  # Root + Thought + Final Answer
    assert spans[0]["name"] == "AgentStep: Goal"


def test_jsonl_dataset_generation(temp_workspace):
    dag = DecisionDAG(run_id="run_export_jsonl", goal="Fix bug in calculator")
    dag.create_child_node(NodeType.THOUGHT, "Thought", {"thought": "I should run tests."})
    dag.create_child_node(NodeType.TOOL_CALL, "Run test", {"tool": "execute_command", "args": {"command": "pytest"}})
    dag.create_child_node(NodeType.OBSERVATION, "Output", {"output": "1 passed"})
    dag.create_child_node(NodeType.FINAL_ANSWER, "Done", {"answer": "Fixed!"})

    jsonl_path = temp_workspace / "dataset.jsonl"
    records = generate_jsonl_dataset(dag, jsonl_path)

    assert jsonl_path.exists()
    assert len(records) >= 1
    sample = records[0]
    assert "messages" in sample
    assert sample["messages"][0]["role"] == "system"
    assert sample["messages"][1]["role"] == "user"
    assert sample["messages"][-1]["content"] == "Fixed!"
