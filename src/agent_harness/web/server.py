import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import GuardrailConfig, HarnessConfig, ProviderType, SandboxConfig, SandboxType
from ..core.loop import AutonomousLoop
from ..engine.debugger import TimeTravelDebugger
from ..graph.decision_dag import DecisionDAG
from ..providers.anthropic import AnthropicProvider
from ..providers.deepseek import DeepSeekProvider
from ..providers.gemini import GeminiProvider
from ..providers.mock import MockProvider
from ..providers.ollama import OllamaProvider
from ..providers.openai import OpenAIProvider
from ..sandbox.container_sandbox import ContainerSandbox
from ..sandbox.process_sandbox import ProcessSandbox
from ..sandbox.wasm_sandbox import WasmSandbox


class RewindRequest(BaseModel):
    step_or_node_id: int | str
    new_prompt: str | None = None
    new_branch_name: str | None = None
    provider: str | None = None
    model: str | None = None


class NewRunRequest(BaseModel):
    goal: str
    sandbox: str = "process"
    provider: str = "mock"
    model: str = "claude-3-7-sonnet"
    max_steps: int = 25
    max_budget: float = 1.0


def resolve_sandbox(sandbox_type: str, workspace_dir: Path):
    st = sandbox_type.lower()
    if st == "wasm":
        return WasmSandbox(workspace_dir=workspace_dir)
    elif st == "docker":
        return ContainerSandbox(workspace_dir=workspace_dir)
    return ProcessSandbox(workspace_dir=workspace_dir)


def resolve_provider(provider_type: str, model_name: str):
    pt = provider_type.lower()
    if pt == "anthropic":
        return AnthropicProvider(model=model_name)
    elif pt == "openai":
        return OpenAIProvider(model=model_name)
    elif pt == "gemini":
        return GeminiProvider(model=model_name)
    elif pt == "deepseek":
        return DeepSeekProvider(model=model_name)
    elif pt == "ollama":
        return OllamaProvider(model=model_name)
    return MockProvider(model=model_name)


def create_app(storage_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="AgentHarness Studio", version="0.1.0")
    runs_dir = storage_dir or Path(".harness/runs").resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    active_connections: dict[str, list[WebSocket]] = {}

    async def broadcast_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        conns = active_connections.get(run_id, [])
        if not conns:
            return
        msg = json.dumps({"type": event_type, "data": payload})
        for ws in list(conns):
            try:
                await ws.send_text(msg)
            except Exception:
                pass

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> str:
        index_file = static_dir / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return "<h1>AgentHarness Studio</h1><p>index.html not found.</p>"

    @app.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        runs = []
        for file in runs_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                runs.append({
                    "run_id": data.get("run_id"),
                    "goal": data.get("goal"),
                    "step_count": len(data.get("nodes", [])),
                    "timestamp": file.stat().st_mtime,
                })
            except Exception:
                continue
        return sorted(runs, key=lambda r: r["timestamp"], reverse=True)

    @app.post("/api/runs/new")
    async def create_new_run(req: NewRunRequest) -> dict[str, Any]:
        ws_path = Path(".harness/workspace").resolve()
        sb = resolve_sandbox(req.sandbox, ws_path)
        prov = resolve_provider(req.provider, req.model)

        config = HarnessConfig(
            provider=ProviderType(req.provider.lower()) if req.provider.lower() in [e.value for e in ProviderType] else ProviderType.MOCK,
            model=req.model,
            sandbox=SandboxConfig(sandbox_type=SandboxType.PROCESS, workspace_dir=ws_path),
            guardrails=GuardrailConfig(max_steps=req.max_steps, max_budget_usd=req.max_budget),
        )

        def on_event(event_type: str, data: dict[str, Any]):
            asyncio.create_task(broadcast_event(loop.run_id, event_type, data))

        loop = AutonomousLoop(
            goal=req.goal,
            sandbox=sb,
            provider=prov,
            config=config,
            event_callback=on_event,
        )

        result = await loop.run()
        file_path = runs_dir / f"{result.run_id}.json"
        file_path.write_text(json.dumps(result.dag, indent=2), encoding="utf-8")

        return {
            "run_id": result.run_id,
            "success": result.success,
            "steps_taken": result.steps_taken,
            "final_answer": result.final_answer,
            "total_tokens": result.total_tokens,
            "total_cost_usd": result.total_cost_usd,
        }

    @app.get("/api/runs/{run_id}/dag")
    async def get_run_dag(run_id: str) -> dict[str, Any]:
        file_path = runs_dir / f"{run_id}.json"
        if not file_path.exists():
            matches = list(runs_dir.glob(f"{run_id}*.json"))
            if matches:
                file_path = matches[0]
            else:
                raise HTTPException(status_code=404, detail="Run not found")

        data = json.loads(file_path.read_text(encoding="utf-8"))
        dag = DecisionDAG.from_dict(data)
        return {
            "run_id": dag.run_id,
            "goal": dag.goal,
            "branches": dag.list_branches(),
            "nodes": [n.model_dump() for n in dag.nodes_by_id.values()],
            "cytoscape_elements": dag.to_cytoscape_elements(),
        }

    @app.get("/api/runs/{run_id}/report.html", response_class=HTMLResponse)
    async def get_run_report(run_id: str) -> str:
        file_path = runs_dir / f"{run_id}.json"
        if not file_path.exists():
            matches = list(runs_dir.glob(f"{run_id}*.json"))
            if matches:
                file_path = matches[0]
            else:
                raise HTTPException(status_code=404, detail="Run not found")

        data = json.loads(file_path.read_text(encoding="utf-8"))
        dag = DecisionDAG.from_dict(data)

        import tempfile

        from ..export.report import generate_html_report
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        generate_html_report(dag, tmp_path)
        content = tmp_path.read_text(encoding="utf-8")
        tmp_path.unlink(missing_ok=True)
        return content

    @app.get("/api/runs/{run_id}/diff/{node_a}/{node_b}")
    async def get_nodes_diff(run_id: str, node_a: str, node_b: str) -> dict[str, Any]:
        file_path = runs_dir / f"{run_id}.json"
        if not file_path.exists():
            matches = list(runs_dir.glob(f"{run_id}*.json"))
            if matches:
                file_path = matches[0]
            else:
                raise HTTPException(status_code=404, detail="Run not found")

        data = json.loads(file_path.read_text(encoding="utf-8"))
        dag = DecisionDAG.from_dict(data)
        from ..graph.diff import compare_branches
        comparison = compare_branches(dag, node_a, node_b)
        return comparison.model_dump()

    @app.post("/api/runs/{run_id}/rewind")
    async def rewind_run(run_id: str, req: RewindRequest) -> dict[str, Any]:
        file_path = runs_dir / f"{run_id}.json"
        if not file_path.exists():
            matches = list(runs_dir.glob(f"{run_id}*.json"))
            if matches:
                file_path = matches[0]
            else:
                raise HTTPException(status_code=404, detail="Run not found")

        data = json.loads(file_path.read_text(encoding="utf-8"))
        dag = DecisionDAG.from_dict(data)

        sandbox = ProcessSandbox(workspace_dir=Path(".harness/workspace").resolve())
        provider = resolve_provider(req.provider or "mock", req.model or "mock-agent")
        debugger = TimeTravelDebugger(dag=dag, sandbox=sandbox, provider=provider)

        try:
            result, comparison = await debugger.rewind_and_branch(
                target_step_or_id=req.step_or_node_id,
                new_instruction=req.new_prompt,
                new_branch_name=req.new_branch_name,
            )
            # Persist updated DAG
            file_path.write_text(json.dumps(dag.to_dict(), indent=2), encoding="utf-8")
            return {
                "success": result.success,
                "branch_id": result.branch_id,
                "final_answer": result.final_answer,
                "comparison": comparison.model_dump() if comparison else None,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/ws/{run_id}")
    async def websocket_endpoint(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        if run_id not in active_connections:
            active_connections[run_id] = []
        active_connections[run_id].append(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                for conn in active_connections.get(run_id, []):
                    await conn.send_text(data)
        except WebSocketDisconnect:
            if run_id in active_connections and websocket in active_connections[run_id]:
                active_connections[run_id].remove(websocket)

    return app
