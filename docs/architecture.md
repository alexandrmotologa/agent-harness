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
- `node_id`: UUID string.
- `step_index`: monotonically increasing integer within the current branch.
- `parent_ids`: list of parent node identifiers (supports linear runs as well as merged branches).
- `node_type`: enum value (`GOAL`, `THOUGHT`, `TOOL_CALL`, `OBSERVATION`, `INTERVENTION`, `FINAL_ANSWER`).
- `content`: structured payload (e.g., arguments passed to tool, text from model, standard output).
- `content_hash`: cryptographic digest computed as `SHA-256(parent_hashes + canonical_json(content))`.
- `token_usage`: tokens consumed by the prompt and completion leading to this node.
- `timestamp`: UTC ISO-8601 string.
- `checkpoint_id`: reference to the virtual filesystem snapshot captured after this step.

### Content-Addressed Hash Integrity

Because each node hash depends directly on the hash of its parent and its serialized payload, any tampering with historical nodes breaks the chain. This provides verifiable audit trails for regulated and enterprise environments.

## Event Dispatching and Streaming

The coordinator implements an event listener interface. As the agent transitions between states, events are emitted:
- `on_run_started(run_id, goal)`
- `on_thought_generated(step, thought_text)`
- `on_tool_executing(step, tool_name, arguments)`
- `on_tool_executed(step, result, duration_ms)`
- `on_guardrail_triggered(rule_name, details)`
- `on_branch_created(parent_node_id, new_branch_id)`
- `on_run_completed(run_id, final_answer, total_tokens, total_cost)`

These events feed directly into the Textual TUI widgets and the FastAPI WebSocket channel without polling.
