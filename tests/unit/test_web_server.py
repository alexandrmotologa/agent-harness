import json

import pytest
from starlette.testclient import TestClient

from agent_harness.graph.decision_dag import DecisionDAG, NodeType
from agent_harness.web.server import create_app


@pytest.fixture
def web_client(temp_workspace):
    storage_dir = temp_workspace / "web_runs"
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Populate a sample run
    dag = DecisionDAG(run_id="run_web_test", goal="Test web studio API")
    dag.create_child_node(NodeType.THOUGHT, "Analyze", {"thought": "Step 1"})
    (storage_dir / f"{dag.run_id}.json").write_text(
        json.dumps(dag.to_dict()), encoding="utf-8"
    )

    app = create_app(storage_dir=storage_dir)
    return TestClient(app)


def test_web_index(web_client):
    response = web_client.get("/")
    assert response.status_code == 200
    assert "AgentHarness Studio" in response.text


def test_api_list_runs(web_client):
    response = web_client.get("/api/runs")
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) >= 1
    assert runs[0]["run_id"] == "run_web_test"


def test_api_get_dag(web_client):
    response = web_client.get("/api/runs/run_web_test/dag")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run_web_test"
    assert "cytoscape_elements" in data
    assert len(data["cytoscape_elements"]) >= 2
