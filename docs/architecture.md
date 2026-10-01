# Architecture Specification

AgentHarness coordinates the execution of autonomous AI agents while guaranteeing containment, causal traceability, and execution recovery. This document details the component boundaries and data flows.

## System Overview

The runtime consists of four primary subsystems:

1. Autonomous Coordinator: runs the ReAct loop, formats prompts, tracks token expenditure, and checks guardrails.
2. Zero-Trust Sandbox Layer: isolates command execution, script evaluation, and filesystem manipulation.
3. Immutable Decision DAG: logs every state transition using cryptographic hashes and maintains execution checkpoints.
4. Debugging and Inspection Interfaces: provides CLI, terminal TUI, and web dashboards for live inspection, rewind, and branch operations.

```
+-----------------------------------------------------------------------------------+
|                                Autonomous Loop                                    |
|   +-------------------+    +---------------------+    +-----------------------+   |
|   | Provider Adapter  |    |    Tool Registry    |    |  Context and Budget   |   |
|   +-------------------+    +---------------------+    +-----------------------+   |
+-----------------------------------------------------------------------------------+
                                          |
                                          | Tool Call Request
                                          v
+-----------------------------------------------------------------------------------+
|                             Sandbox Execution Layer                               |
|   +-------------------+    +---------------------+    +-----------------------+   |
|   | Wasmtime Sandbox  |    |  Docker Container   |    |  Process Jail (Local) |   |
|   +-------------------+    +---------------------+    +-----------------------+   |
|                                         |                                         |
|                                         v                                         |
|                          Filesystem Jail with COW Diffs                           |
+-----------------------------------------------------------------------------------+
                                          |
                                          | Execution Result and Diffs
                                          v
+-----------------------------------------------------------------------------------+
|                             Immutable Decision DAG                                |
|   +-------------------+    +---------------------+    +-----------------------+   |
|   | Node SHA-256 Hash |    | Filesystem Snapshot |    | Branch Diffs Engine   |   |
|   +-------------------+    +---------------------+    +-----------------------+   |
+-----------------------------------------------------------------------------------+
                                          |
                                          | State and Events
                                          v
+-----------------------------------------------------------------------------------+
|                        Inspection and Control Surfaces                            |
|   +-------------------+    +---------------------+    +-----------------------+   |
|   | Textual TUI App   |    | FastAPI WebSocket   |    | Typer CLI Interface   |   |
|   +-------------------+    +---------------------+    +-----------------------+   |
+-----------------------------------------------------------------------------------+
```

## Immutable Decision DAG

Agent reasoning is not treated as a flat text history. Each step is recorded as a vertex in a Directed Acyclic Graph backed by NetworkX.

### Node Structure

Every node in the graph contains:
- `id`: Unique identifier string (e.g. `node_7baa0ad83878`).
- `step_index`: Monotonically increasing integer within the current branch.
- `branch_id`: Active trajectory branch name (`main`, `branch_rewind_1`, etc.).
- `parent_ids`: List of parent node identifiers (supports linear runs as well as branched and merged trajectories).
- `node_type`: Enum value (`GOAL`, `THOUGHT`, `TOOL_CALL`, `OBSERVATION`, `INTERVENTION`, `FINAL_ANSWER`, `ERROR`).
- `title`: Short human-readable summary of the step.
- `payload`: Structured dictionary (e.g., tool arguments, model thoughts, sandbox outputs, final answers).
- `content_hash`: Cryptographic digest computed as `SHA-256(sorted(parent_hashes) + canonical_json(payload) + node_type)`.
- `token_usage`: Tokens consumed by the prompt and completion leading to this node.
- `cost_usd`: Exact cost in USD calculated from frontier model pricing tables.
- `timestamp`: UTC ISO-8601 string.
- `checkpoint_id`: Reference to the virtual filesystem snapshot captured after this step.

### Content-Addressed Hash Integrity

Because each node hash depends directly on the hash of its parent and its serialized payload, any tampering with historical nodes breaks the chain. This provides verifiable audit trails for regulated, financial, and enterprise environments.

## Multi-Format Observability & Dataset Generation

AgentHarness provides native converters in `agent_harness.export.report`:

1. **Standalone HTML Report:** Zero-dependency, self-contained HTML document embedding Cytoscape.js, Dagre layout engine, cost cards, step diff viewer, and payload inspector.
2. **Mermaid Flowchart (`.mmd`):** Generates declarative `flowchart TD` diagrams with stylized class definitions for thoughts, tool calls, and observations.
3. **OpenTelemetry Trace (`.json`):** Exports each decision step as an OpenTelemetry span (`resourceSpans` with `traceId`, `spanId`, `parentSpanId`, and `attributes`) ready to ingest into Jaeger, Datadog, or Grafana Tempo.
4. **Fine-Tuning & DPO Dataset (`.jsonl`):** Transforms multi-branch decision trees into structured conversation datasets (`{"messages": [{"role": "system", ...}, {"role": "user", ...}, ...]}`) for supervised fine-tuning or preference optimization.

## Model Context Protocol (MCP) Integration

AgentHarness supports bidirectional MCP communication:
- **MCP Client (`agent_harness.mcp.client`):** Connects to external MCP tools running over stdio (e.g. SQLite, GitHub, File system servers) and registers them dynamically into the `ToolRegistry`.
- **MCP Server (`agent_harness.mcp.server`):** Exposes AgentHarness's sandboxed execution capabilities over JSON-RPC 2.0 stdio to any MCP-compatible client.

## Benchmark and Parallel Evaluation Runner

The evaluation engine in `agent_harness.eval.runner` allows continuous integration verification of autonomous agents:
- Runs multi-case evaluation suites concurrently via `asyncio.Semaphore`.
- Executes declarative assertions:
  - `FILE_EXISTS` / `FILE_NOT_EXISTS`
  - `FILE_CONTAINS` / `FILE_NOT_CONTAINS`
  - `REGEX_MATCH`
  - `EXIT_CODE`
  - `STDERR_EMPTY`
  - `TOOL_INVOKED`
  - `ANSWER_CONTAINS`
  - `MAX_STEPS` / `MAX_COST_USD`

## Event Dispatching and Streaming

The coordinator implements an event listener interface. As the agent transitions between states, events are emitted:
- `step_started(step, branch_id)`
- `thought(step, content)`
- `tool_call(step, tool, arguments)`
- `observation(step, output)`
- `guardrail_warning(warning)`
- `run_finished(run_id, success, final_answer)`

These events feed directly into the Textual TUI widgets and the FastAPI WebSocket channel without polling.
