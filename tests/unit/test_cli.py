from typer.testing import CliRunner

from agent_harness.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Sandboxed multi-agent runtime" in result.stdout


def test_cli_run_and_inspect(temp_workspace):
    workspace_dir = temp_workspace / "ws"
    storage_dir = temp_workspace / "runs"

    # Execute a run with custom storage
    run_res = runner.invoke(
        app,
        [
            "run",
            "Calculate 2+2",
            "--provider", "mock",
            "--sandbox", "process",
            "--workspace", str(workspace_dir),
            "--storage", str(storage_dir),
            "--max-steps", "3",
        ],
    )
    assert run_res.exit_code == 0
    assert "AgentHarness Run Summary" in run_res.stdout

    # Inspect runs in custom storage
    inspect_res = runner.invoke(app, ["inspect", "--storage", str(storage_dir)])
    assert inspect_res.exit_code == 0
    assert "Available Agent Runs" in inspect_res.stdout

    # Test report alias
    report_res = runner.invoke(
        app,
        [
            "report",
            "run_",
            "--output", str(temp_workspace / "report.html"),
            "--storage", str(storage_dir),
        ],
    )
    assert report_res.exit_code == 0


def test_cli_replay_help():
    res = runner.invoke(app, ["replay", "--help"])
    assert res.exit_code == 0
    assert "Replay previously recorded" in res.stdout
