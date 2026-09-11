<p align="center">
  <img src="docs/images/logo.png?raw=true" alt="AgentHarness Logo" width="140" style="border-radius: 28px;" />
</p>

<h1 align="center">AgentHarness</h1>

<p align="center">
  <strong>Deterministic Execution Runtime &amp; Time-Travel Debugger for Autonomous AI Agents</strong>
</p>

<p align="center">
  <a href="#key-capabilities">Features</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#web-decision-graph-studio">Web Studio</a> •
  <a href="#standalone-audit-reports">Reports</a> •
  <a href="#documentation">Docs</a>
</p>

AgentHarness is a deterministic execution runtime for autonomous AI agents that execute tools, run code, and invoke shell commands. It confines tool executions inside sandboxes, records reasoning trajectories in an immutable Directed Acyclic Graph (DAG), and provides a time-travel debugger to rewind and branch execution when an agent makes an error.

```
                  +-------------------------------------------------------+
                  |                      AgentHarness                     |
                  +-------------------------------------------------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
                     v                                                 v
       +----------------------------+                    +----------------------------+
       |   Zero-Trust Sandboxes     |                    |   Immutable Decision DAG   |
       |  - Wasmtime micro-sandbox  |                    |  - Cryptographic node SHA  |
       |  - Ephemeral container     |                    |  - Step-by-step diffs      |
       |  - Process path jail       |                    |  - Branching and rewind    |
       +----------------------------+                    +----------------------------+
                     |                                                 |
                     +------------------------+------------------------+
                                              |
                                              v
                              +-------------------------------+
                              |    Inspection Interfaces      |
                              |  - Interactive Terminal TUI   |
                              |  - Real-time Web DAG Studio   |
                              |  - Unified Typer CLI          |
                              +-------------------------------+
```

## Why AgentHarness Exists

Giving an autonomous language model direct access to your host shell or unconstrained file write APIs creates three practical problems:

1. Safety risk: hallucinations and prompt injections can modify system files, access sensitive environment variables, or run destructive terminal commands.
2. The black box loop: when an agent makes an incorrect assumption at step 2 of a 10-step plan, existing frameworks force you to cancel the entire run and start over, consuming time and tokens.
3. Lack of execution auditability: teams need deterministic logs showing the exact command, environment state, and file diff produced at each step.

AgentHarness addresses these issues by isolating all tool executions in sandboxes, preserving every decision in a content-addressed graph, and letting you rewind to any earlier node to alter prompts or injected values.

## Key Capabilities

- Zero-trust execution: tools execute inside a WebAssembly runtime, an ephemeral non-root Docker container, or an isolated local process jail with copy-on-write path restrictions.
- Immutable decision DAG: every thought, tool call, and observation is saved with a SHA-256 cryptographic hash calculated from its parent and payload.
- Time-travel debugging: rewind execution to step N, modify the agent prompt or tool output, and branch into a new execution line without losing previous runs.
- Guardrails and cost circuit breakers: automatic detection of repetitive tool calls with identical parameters, paired with configurable token spend limits.
- Dual inspection interfaces: an interactive terminal UI built with Textual, plus a browser dashboard powered by FastAPI and Cytoscape.js.
- Provider adapters: support for Anthropic Claude, OpenAI, local Ollama models, and an offline mock provider for deterministic tests.

## Installation

AgentHarness requires Python 3.12 or newer. You can install it using `uv` or `pip`:

```bash
# Clone the repository
git clone https://github.com/alexandrmotologa/agent-harness.git
cd agent-harness

# Create virtual environment and install dependencies using uv
uv venv
uv pip install -e .

# Optional: install WebAssembly and Docker extras
uv pip install -e ".[wasm,docker]"
```

## Quickstart

Run a goal using the default local process sandbox and mock provider:

```bash
agent-harness run "Calculate prime numbers up to 50 and write them to primes.txt" --provider mock --sandbox process
```

To use Anthropic Claude or OpenAI models, supply your API key:

```bash
export ANTHROPIC_API_KEY="your-api-key"
agent-harness run "Analyze src/auth.py and write unit tests" --provider anthropic --model claude-3-7-sonnet
```

### Inspecting Runs

List previous agent runs and view their step trajectories:

```bash
agent-harness inspect
agent-harness inspect <run-id> --verbose
```

### Time-Travel Rewind and Branching

If the agent takes the wrong approach at step 3, rewind and supply a corrected instruction:

```bash
agent-harness rewind <run-id> --step 3 --prompt "Use an iterative approach instead of recursion"
```

The runtime restores the filesystem state from step 3 and forks the DAG into a second branch.

### Interactive Terminal TUI

Launch the interactive terminal dashboard to monitor nodes, file diffs, and token spending:

```bash
agent-harness tui <run-id>
```

Keyboard shortcuts:
- `u`: Rewind to selected step
- `b`: Fork selected step into a new branch
- `s`: View sandbox stdout and stderr logs
- `d`: View file diff produced by selected step
- `q`: Quit

### Web Decision Graph Studio

Launch the local web visualizer to inspect DAG trajectories and branch points in your browser:

```bash
agent-harness serve --port 8000
```

Open `http://localhost:8000` to interact with the Cytoscape.js decision graph, inspect tool call arguments, token spend, and trigger time-travel rewinds directly from the browser UI.

<p align="center">
  <img src="docs/images/web_studio_dag.png?raw=true" alt="AgentHarness Web Studio" width="96%" style="border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.4);" />
</p>

### Standalone HTML Audit Reports

Generate self-contained, zero-dependency HTML audit reports with interactive graph exploration, metric cards, and step inspection to share with team members or attach to CI/CD pipelines:

```bash
agent-harness report <run-id> --output report.html
```

<p align="center">
  <img src="docs/images/standalone_report.png?raw=true" alt="AgentHarness Standalone Report" width="96%" style="border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.4);" />
</p>

### Deterministic & Fuzzy Cassette Replay

Replay previously recorded agent trajectories deterministically offline, or enable semantic fuzzy matching to tolerate minor wording variances in prompts:

```bash
# Exact deterministic replay
agent-harness replay path/to/cassette.json

# Replay with fuzzy prompt similarity matching
agent-harness replay path/to/cassette.json --fuzzy --threshold 0.85
```

## Project Structure

```
src/agent_harness/
├── cli.py               # Typer CLI commands
├── config.py            # Runtime configuration and environment parsing
├── core/
│   ├── loop.py          # Autonomous ReAct coordinator
│   ├── tool_registry.py # Pydantic schema validation and format conversion
│   ├── context_window.py# Token counter and window sliding logic
│   └── guardrails.py    # Repetition detector and cost circuit breaker
├── sandbox/
│   ├── base.py          # BaseSandbox interface and execution models
│   ├── fs_jail.py       # Path confinement and copy-on-write diff engine
│   ├── process_sandbox.py # Local restricted process executor
│   ├── wasm_sandbox.py  # WebAssembly sandbox powered by Wasmtime
│   └── container_sandbox.py # Ephemeral Docker micro-container runner
├── graph/
│   ├── decision_dag.py  # NetworkX immutable decision graph
│   ├── checkpoint.py    # Filesystem snapshot manager
│   └── diff.py          # Branch comparison metrics
├── engine/
│   ├── debugger.py      # Rewind, replay, and branching coordinator
│   └── recorder.py      # Deterministic cassette recorder and player
├── providers/           # Model adapters for Anthropic, OpenAI, Ollama, Mock
├── tui/                 # Textual terminal UI
└── web/                 # FastAPI server and Cytoscape DAG interface
```

## Running Tests

Run the test suite using pytest:

```bash
uv run pytest -v
```

Check code style and typing:

```bash
uv run ruff check .
uv run mypy src
```

## Documentation

- [Architecture Guide](docs/architecture.md): design decisions, immutable DAG schema, and state hashing.
- [Sandboxing Guide](docs/sandboxing.md): security boundaries of WebAssembly, Docker containers, and process jails.
- [Time-Travel Debugger](docs/time-travel-debugger.md): state checkpoints, branch diffing, and cassette replay.

## License

MIT License. See [LICENSE](LICENSE) for details.
