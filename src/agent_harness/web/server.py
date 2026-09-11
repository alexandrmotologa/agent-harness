import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..engine.debugger import TimeTravelDebugger
from ..graph.decision_dag import DecisionDAG
from ..providers.mock import MockProvider
from ..sandbox.process_sandbox import ProcessSandbox


class RewindRequest(BaseModel):
    step_or_node_id: int | str
    new_prompt: str | None = None
    new_branch_name: str | None = None


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

    @app.post("/api/runs/{run_id}/rewind")
    async def rewind_run(run_id: str, req: RewindRequest) -> dict[str, Any]:
        file_path = runs_dir / f"{run_id}.json"
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Run not found")

        data = json.loads(file_path.read_text(encoding="utf-8"))
        dag = DecisionDAG.from_dict(data)

        sandbox = ProcessSandbox(workspace_dir=Path(".harness/workspace").resolve())
        provider = MockProvider(model="mock-agent")
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
                # Echo or broadcast if needed
                for conn in active_connections.get(run_id, []):
                    await conn.send_text(data)
        except WebSocketDisconnect:
            if run_id in active_connections and websocket in active_connections[run_id]:
                active_connections[run_id].remove(websocket)

    return app
