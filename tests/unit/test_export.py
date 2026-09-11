from agent_harness.export.report import generate_html_report
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
