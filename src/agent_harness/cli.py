import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import GuardrailConfig, HarnessConfig, ProviderType, SandboxConfig, SandboxType
from .core.loop import AutonomousLoop
from .engine.debugger import TimeTravelDebugger
from .graph.decision_dag import DecisionDAG
from .providers.anthropic import AnthropicProvider
from .providers.mock import MockProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider
from .sandbox.container_sandbox import ContainerSandbox
from .sandbox.process_sandbox import ProcessSandbox
from .sandbox.wasm_sandbox import WasmSandbox

app = typer.Typer(
    name="agent-harness",
    help="AgentHarness: Sandboxed multi-agent runtime and time-travel inspector",
    no_args_is_help=True,
)
console = Console()


def get_sandbox(sandbox_type: str, workspace_dir: Path):
    st = sandbox_type.lower()
    if st == "wasm":
        return WasmSandbox(workspace_dir=workspace_dir)
    elif st == "docker":
        return ContainerSandbox(workspace_dir=workspace_dir)
    return ProcessSandbox(workspace_dir=workspace_dir)


def get_provider(provider_type: str, model_name: str, api_key: str | None = None):
    pt = provider_type.lower()
    if pt == "anthropic":
        return AnthropicProvider(model=model_name, api_key=api_key)
    elif pt == "openai":
        return OpenAIProvider(model=model_name, api_key=api_key)
    elif pt == "ollama":
        return OllamaProvider(model=model_name)
    return MockProvider(model=model_name)


def save_run(run_id: str, dag_data: dict, storage_dir: Path) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{run_id}.json"
    file_path.write_text(json.dumps(dag_data, indent=2), encoding="utf-8")
    return file_path


def load_run(run_id: str, storage_dir: Path) -> DecisionDAG | None:
    file_path = storage_dir / f"{run_id}.json"
    if not file_path.exists():
        # Search for prefix match
        matches = list(storage_dir.glob(f"{run_id}*.json"))
        if matches:
            file_path = matches[0]
        else:
            return None
    data = json.loads(file_path.read_text(encoding="utf-8"))
    return DecisionDAG.from_dict(data)


@app.command()
def run(
    goal: Annotated[str, typer.Argument(help="The objective for the autonomous agent to solve")],
    sandbox: Annotated[str, typer.Option("--sandbox", "-s", help="Sandbox: process, wasm, docker")] = "process",
    provider: Annotated[str, typer.Option("--provider", "-p", help="Provider: mock, anthropic, openai, ollama")] = "mock",
    model: Annotated[str, typer.Option("--model", "-m", help="Model name identifier")] = "claude-3-7-sonnet",
    max_steps: Annotated[int, typer.Option("--max-steps", help="Maximum execution steps")] = 25,
    max_budget: Annotated[float, typer.Option("--max-budget", help="Maximum USD budget")] = 1.0,
    workspace: Annotated[str, typer.Option("--workspace", "-w", help="Workspace path")] = ".harness/workspace",
    interactive: Annotated[bool, typer.Option("--interactive", "-i", help="Enable Human-in-the-Loop approval")] = False,
):
    """Execute an autonomous agent goal inside a secure sandbox."""
    console.print(Panel(f"[bold cyan]Goal:[/bold cyan] {goal}\n[bold]Sandbox:[/bold] {sandbox} | [bold]Provider:[/bold] {provider} | [bold]Interactive:[/bold] {interactive}", title="AgentHarness Run Initializing"))

    ws_path = Path(workspace).resolve()
    storage_path = Path(".harness/runs").resolve()
    sb = get_sandbox(sandbox, ws_path)
    prov = get_provider(provider, model)

    config = HarnessConfig(
        provider=ProviderType(provider.lower()) if provider.lower() in [e.value for e in ProviderType] else ProviderType.MOCK,
        model=model,
        sandbox=SandboxConfig(sandbox_type=SandboxType.PROCESS, workspace_dir=ws_path),
        guardrails=GuardrailConfig(max_steps=max_steps, max_budget_usd=max_budget),
    )

    from .core.hitl import CLIInterventionHandler
    hitl_handler = CLIInterventionHandler() if interactive else None

    def on_event(event_type: str, data: dict):
        if event_type == "step_started":
            console.print(f"[dim]Step {data.get('step')} ({data.get('branch_id')})...[/dim]")
        elif event_type == "thought":
            console.print(Panel(data.get("content", ""), title=f"Thought (Step {data.get('step')})", border_style="blue"))
        elif event_type == "tool_call":
            console.print(f"[yellow]> Calling Tool:[/yellow] [bold]{data.get('tool')}[/bold] with {data.get('arguments')}")
        elif event_type == "observation":
            preview = data.get("output", "")[:200]
            console.print(f"[green]< Observation:[/green] {preview}...")
        elif event_type == "guardrail_warning":
            console.print(f"[bold red]! Guardrail Warning:[/bold red] {data.get('warning')}")

    loop = AutonomousLoop(
        goal=goal,
        sandbox=sb,
        provider=prov,
        config=config,
        event_callback=on_event,
        hitl_handler=hitl_handler,
    )

    result = asyncio.run(loop.run())
    save_run(result.run_id, result.dag, storage_path)

    table = Table(title="AgentHarness Run Summary", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="dim")
    table.add_column("Value")
    table.add_row("Run ID", result.run_id)
    table.add_row("Success", "[green]Yes[/green]" if result.success else "[red]No[/red]")
    table.add_row("Steps Taken", str(result.steps_taken))
    table.add_row("Total Tokens", str(result.total_tokens))
    table.add_row("Cost", f"${result.total_cost_usd:.4f}")
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")
    if result.final_answer:
        table.add_row("Final Answer", result.final_answer)
    if result.error_message:
        table.add_row("Error", f"[red]{result.error_message}[/red]")

    console.print(table)


@app.command()
def inspect(
    run_id: Annotated[str | None, typer.Argument(help="Run ID to inspect (omit to list all)")] = None,
    storage: Annotated[str, typer.Option("--storage", help="Path to runs directory")] = ".harness/runs",
):
    """Inspect past agent runs and view their decision graph trajectories."""
    storage_path = Path(storage).resolve()
    if not storage_path.exists():
        console.print("[yellow]No runs found in storage directory.[/yellow]")
        return

    if not run_id:
        table = Table(title="Available Agent Runs", show_header=True)
        table.add_column("Run ID", style="bold cyan")
        table.add_column("Goal")
        table.add_column("Steps")
        table.add_column("Branches")

        for f in storage_path.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                dag = DecisionDAG.from_dict(data)
                branches = len(dag.list_branches())
                table.add_row(dag.run_id, dag.goal[:50] + "...", str(len(dag.nodes_by_id)), str(branches))
            except Exception:
                continue
        console.print(table)
        return

    dag = load_run(run_id, storage_path)
    if not dag:
        console.print(f"[red]Error: Run '{run_id}' not found in '{storage_path}'.[/red]")
        return

    console.print(Panel(f"[bold cyan]Run ID:[/bold cyan] {dag.run_id}\n[bold]Goal:[/bold] {dag.goal}", title="Decision DAG Details"))
    trajectory = dag.get_trajectory()

    table = Table(title="Trajectory Steps", show_header=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Node ID", style="cyan")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Hash", style="dim")

    for node in trajectory:
        table.add_row(
            str(node.step_index),
            node.id,
            node.node_type.value,
            node.title[:40],
            node.content_hash[:10] + "...",
        )
    console.print(table)


@app.command()
def rewind(
    run_id: Annotated[str, typer.Argument(help="Run ID to rewind")],
    step: Annotated[int, typer.Option("--step", "-s", help="Step index to rewind to")],
    prompt: Annotated[str | None, typer.Option("--prompt", "-p", help="Modified instruction for new branch")] = None,
    storage: Annotated[str, typer.Option("--storage", help="Path to runs directory")] = ".harness/runs",
    workspace: Annotated[str, typer.Option("--workspace", "-w", help="Workspace directory")] = ".harness/workspace",
):
    """Rewind execution to a past step and branch into an alternate trajectory."""
    storage_path = Path(storage).resolve()
    ws_path = Path(workspace).resolve()

    dag = load_run(run_id, storage_path)
    if not dag:
        console.print(f"[red]Run '{run_id}' not found.[/red]")
        return

    sb = ProcessSandbox(workspace_dir=ws_path)
    prov = MockProvider(model="mock-agent")
    debugger = TimeTravelDebugger(dag=dag, sandbox=sb, provider=prov)

    console.print(f"[bold cyan]Rewinding run '{run_id}' to step {step}...[/bold cyan]")
    result, comparison = asyncio.run(debugger.rewind_and_branch(target_step_or_id=step, new_instruction=prompt))

    save_run(dag.run_id, dag.to_dict(), storage_path)
    console.print(f"[green]Branch '{result.branch_id}' completed successfully![/green]")
    if comparison:
        console.print(f"[dim]Token Delta: {comparison.token_delta} | Cost Delta: ${comparison.cost_delta_usd:.4f}[/dim]")


@app.command()
def tui(
    run_id: Annotated[str | None, typer.Argument(help="Optional Run ID to open")] = None,
):
    """Launch the interactive Textual terminal dashboard."""
    from .tui.app import AgentHarnessTUI
    app_tui = AgentHarnessTUI(run_id=run_id)
    app_tui.run()


@app.command()
def serve(
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind")] = 8000,
    host: Annotated[str, typer.Option("--host", "-h", help="Host address to bind")] = "127.0.0.1",
):
    """Start the FastAPI decision graph web visualizer and REST server."""
    import uvicorn

    from .web.server import create_app
    server_app = create_app()
    console.print(f"[bold green]Starting AgentHarness Web Studio on http://{host}:{port}[/bold green]")
    uvicorn.run(server_app, host=host, port=port)


@app.command()
def export(
    run_id: Annotated[str, typer.Argument(help="Run ID to export")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output HTML file path")] = "report.html",
    storage: Annotated[str, typer.Option("--storage", help="Path to runs directory")] = ".harness/runs",
):
    """Export a run as a standalone portable HTML report with embedded Cytoscape.js DAG."""
    storage_path = Path(storage).resolve()
    dag = load_run(run_id, storage_path)
    if not dag:
        console.print(f"[red]Error: Run '{run_id}' not found.[/red]")
        raise typer.Exit(code=1)

    from .export.report import generate_html_report
    out_path = Path(output).resolve()
    generate_html_report(dag, out_path)
    console.print(f"[bold green]Report exported successfully to: [cyan]{out_path}[/cyan][/bold green]")


@app.command(name="eval")
def run_eval(
    suite_file: Annotated[str, typer.Argument(help="Path to YAML or JSON eval suite file")],
    provider: Annotated[str, typer.Option("--provider", "-p", help="Provider: mock, anthropic, openai")] = "mock",
    model: Annotated[str, typer.Option("--model", "-m", help="Model name identifier")] = "claude-3-7-sonnet",
):
    """Run an automated evaluation suite against declarative assertions."""
    path = Path(suite_file).resolve()
    if not path.exists():
        console.print(f"[red]Error: Suite file '{suite_file}' not found.[/red]")
        raise typer.Exit(code=1)

    from .eval.models import EvalSuite
    from .eval.runner import EvalRunner

    data = json.loads(path.read_text(encoding="utf-8"))
    suite = EvalSuite.model_validate(data)
    prov = get_provider(provider, model)
    runner = EvalRunner(provider=prov)

    console.print(f"[bold cyan]Running Eval Suite: {suite.name} ({len(suite.cases)} test cases)...[/bold cyan]")
    report = asyncio.run(runner.run_suite(suite))

    table = Table(title=f"Eval Results: {report.suite_name}", show_header=True)
    table.add_column("Case ID", style="cyan")
    table.add_column("Status")
    table.add_column("Steps")
    table.add_column("Cost")
    table.add_column("Details")

    for r in report.results:
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        checks_summary = "; ".join(c.message for c in r.checks)
        table.add_row(r.case_id, status, str(r.steps_taken), f"${r.cost_usd:.4f}", checks_summary)

    console.print(table)
    console.print(f"[bold]Summary:[/bold] {report.passed_cases}/{report.total_cases} passed in {report.total_duration_seconds:.2f}s (${report.total_cost_usd:.4f})")


@app.command()
def mcp_serve(
    workspace: Annotated[str, typer.Option("--workspace", "-w", help="Workspace path")] = ".harness/workspace",
):
    """Start AgentHarness in MCP server mode over stdio."""
    ws_path = Path(workspace).resolve()
    sb = ProcessSandbox(workspace_dir=ws_path)
    from .mcp.server import MCPServer
    server = MCPServer(sandbox=sb)
    asyncio.run(server.run_stdio())


@app.command()
def diff(
    run_id: Annotated[str, typer.Argument(help="Run ID containing branches")],
    storage: Annotated[str, typer.Option("--storage", help="Path to runs directory")] = ".harness/runs",
):
    """View colored diffs between branches in an agent run."""
    storage_path = Path(storage).resolve()
    dag = load_run(run_id, storage_path)
    if not dag:
        console.print(f"[red]Error: Run '{run_id}' not found.[/red]")
        raise typer.Exit(code=1)

    branches = dag.list_branches()
    console.print(f"[bold]Available Branches in '{run_id}':[/bold] {branches}")
    leaves = [n.id for n in dag.nodes_by_id.values() if dag.graph.out_degree(n.id) == 0]
    if len(leaves) >= 2:
        from .graph.diff import compare_branches
        comparison = compare_branches(dag, leaves[0], leaves[1])
        console.print(Panel(
            f"Comparing {comparison.branch_a.branch_id} vs {comparison.branch_b.branch_id}\n"
            f"Token Delta: {comparison.token_delta} | Cost Delta: ${comparison.cost_delta_usd:.4f}",
            title="Branch Comparison",
        ))
    else:
        console.print("[yellow]Run contains only a single linear branch.[/yellow]")

