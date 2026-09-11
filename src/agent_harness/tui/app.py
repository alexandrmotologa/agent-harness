import json
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, ListItem, ListView, Static

from ..graph.decision_dag import DecisionDAG, DecisionNode, NodeType


class DecisionNodeItem(ListItem):
    def __init__(self, node: DecisionNode):
        super().__init__()
        self.node = node

    def render(self) -> Text:
        color = "white"
        if self.node.node_type == NodeType.GOAL:
            color = "cyan"
        elif self.node.node_type == NodeType.THOUGHT:
            color = "blue"
        elif self.node.node_type == NodeType.TOOL_CALL:
            color = "yellow"
        elif self.node.node_type == NodeType.OBSERVATION:
            color = "green"
        elif self.node.node_type == NodeType.FINAL_ANSWER:
            color = "bright_green"
        elif self.node.node_type == NodeType.ERROR:
            color = "red"

        prefix = f"[{self.node.step_index:02d}] {self.node.node_type.value}: "
        text = Text()
        text.append(prefix, style=f"bold {color}")
        title = self.node.title or str(self.node.payload)[:30]
        text.append(title[:40], style="white")
        return text


class NodeDetailWidget(Static):
    def show_node(self, node: DecisionNode | None) -> None:
        if not node:
            self.update("Select a decision node from the list on the left.")
            return

        lines = [
            f"[bold cyan]Step #{node.step_index}[/bold cyan] ({node.branch_id})",
            f"[bold]Node ID:[/bold] {node.id}",
            f"[bold]Type:[/bold] {node.node_type.value}",
            f"[bold]Content Hash:[/bold] {node.content_hash}",
            f"[bold]Checkpoint ID:[/bold] {node.checkpoint_id or 'None'}",
            f"[bold]Token Usage:[/bold] {node.token_usage} | [bold]Cost:[/bold] ${node.cost_usd:.4f}",
            "",
            "[bold yellow]Payload:[/bold yellow]",
            json.dumps(node.payload, indent=2),
        ]
        self.update("\n".join(lines))


class AgentHarnessTUI(App):
    CSS = """
    Screen {
        background: #111827;
        color: #f3f4f6;
    }
    #main-container {
        height: 1fr;
    }
    #left-panel {
        width: 35%;
        border-right: solid #374151;
        padding: 1;
    }
    #right-panel {
        width: 65%;
        padding: 1;
    }
    #status-bar {
        dock: bottom;
        height: 3;
        background: #1f2937;
        color: #9ca3af;
        padding: 0 1;
    }
    ListView {
        background: #111827;
        border: none;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:hover {
        background: #1f2937;
    }
    ListItem.-selected {
        background: #374151;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_nodes", "Refresh"),
    ]

    def __init__(self, run_id: str | None = None, storage_dir: Path | None = None):
        super().__init__()
        self.run_id = run_id
        self.storage_dir = storage_dir or Path(".harness/runs").resolve()
        self.dag: DecisionDAG | None = None
        self._load_dag()

    def _load_dag(self) -> None:
        if self.run_id:
            target = self.storage_dir / f"{self.run_id}.json"
            if target.exists():
                data = json.loads(target.read_text(encoding="utf-8"))
                self.dag = DecisionDAG.from_dict(data)
                return

        # Try to load latest run in storage
        if self.storage_dir.exists():
            runs = sorted(self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if runs:
                data = json.loads(runs[0].read_text(encoding="utf-8"))
                self.dag = DecisionDAG.from_dict(data)
                return

        # Default sample run
        self.dag = DecisionDAG(run_id="sample_run", goal="Calculate prime numbers and save to primes.txt")
        self.dag.create_child_node(NodeType.THOUGHT, "Analyze goal", {"thought": "I need to write primes algorithm."})
        self.dag.create_child_node(NodeType.TOOL_CALL, "execute_command", {"command": "python -c 'print([2, 3, 5, 7])'"})
        self.dag.create_child_node(NodeType.OBSERVATION, "Output", {"output": "[2, 3, 5, 7]"})
        self.dag.create_child_node(NodeType.FINAL_ANSWER, "Task complete", {"answer": "Computed primes successfully."})

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield Static("[bold cyan]Decision DAG Trajectory[/bold cyan]\n")
                yield ListView(id="node-list")
            with Vertical(id="right-panel"):
                yield Static("[bold magenta]Step Inspector[/bold magenta]\n")
                yield NodeDetailWidget(id="node-detail")
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh_nodes()

    def action_refresh_nodes(self) -> None:
        node_list = self.query_one("#node-list", ListView)
        node_list.clear()

        if self.dag:
            nodes = self.dag.get_trajectory()
            for node in nodes:
                node_list.append(DecisionNodeItem(node))

            total_tokens = sum(n.token_usage for n in nodes)
            total_cost = sum(n.cost_usd for n in nodes)
            status_bar = self.query_one("#status-bar", Static)
            status_bar.update(
                f"Run: [bold white]{self.dag.run_id}[/bold white] | "
                f"Goal: {self.dag.goal[:40]}... | "
                f"Steps: {len(nodes)} | "
                f"Tokens: {total_tokens} | "
                f"Cost: ${total_cost:.4f}"
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, DecisionNodeItem):
            detail = self.query_one("#node-detail", NodeDetailWidget)
            detail.show_node(event.item.node)
