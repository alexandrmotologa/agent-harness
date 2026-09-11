import shutil
import tempfile
from pathlib import Path

import pytest

from agent_harness.graph.decision_dag import DecisionDAG
from agent_harness.providers.mock import MockProvider
from agent_harness.sandbox.process_sandbox import ProcessSandbox


@pytest.fixture
def temp_workspace():
    tmp_dir = Path(tempfile.mkdtemp(prefix="harness_test_ws_"))
    yield tmp_dir
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def process_sandbox(temp_workspace):
    snapshot_dir = temp_workspace.parent / f"{temp_workspace.name}_snaps"
    sb = ProcessSandbox(workspace_dir=temp_workspace, snapshot_storage_dir=snapshot_dir)
    yield sb
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir, ignore_errors=True)


@pytest.fixture
def mock_provider():
    return MockProvider(model="test-mock")


@pytest.fixture
def sample_dag():
    dag = DecisionDAG(run_id="test_run_01", goal="Test decision graph goal")
    return dag
