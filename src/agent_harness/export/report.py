import json
from pathlib import Path

from ..graph.decision_dag import DecisionDAG, NodeType


def generate_html_report(dag: DecisionDAG, output_file: Path) -> Path:
    """
    Generate a self-contained, standalone HTML report for an AgentHarness run,
    including embedded Cytoscape.js visual graph, decision trajectory, and payload inspector.
    """
    trajectory = dag.get_trajectory()
    total_tokens = sum(n.token_usage for n in trajectory)
    total_cost = sum(n.cost_usd for n in trajectory)
    final_node = next((n for n in reversed(trajectory) if n.node_type == NodeType.FINAL_ANSWER), None)
    final_answer = final_node.payload.get("answer") if final_node else "N/A"

    elements = dag.to_cytoscape_elements()
    nodes_data = [n.model_dump() for n in dag.nodes_by_id.values()]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentHarness Report — {dag.run_id}</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
  <style>
    :root {{
      --bg: #0b0f19;
      --card: #151d2e;
      --border: #232f48;
      --text: #f1f5f9;
      --muted: #8899ac;
      --cyan: #06b6d4;
      --blue: #3b82f6;
      --yellow: #eab308;
      --green: #10b981;
      --purple: #a855f7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); padding: 24px; }}
    header {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 24px; }}
    h1 {{ font-size: 1.4rem; color: var(--cyan); margin-bottom: 8px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-top: 16px; }}
    .stat-card {{ background: rgba(0,0,0,0.25); border: 1px solid var(--border); padding: 12px; border-radius: 6px; }}
    .stat-label {{ font-size: 0.75rem; text-transform: uppercase; color: var(--muted); }}
    .stat-value {{ font-size: 1.2rem; font-weight: 700; margin-top: 4px; }}
    .main-grid {{ display: grid; grid-template-columns: 1fr 400px; gap: 24px; height: 600px; }}
    #graph-container {{ background: #070a10; border: 1px solid var(--border); border-radius: 8px; height: 100%; }}
    .inspector {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; height: 100%; overflow-y: auto; padding: 20px; }}
    .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; margin-bottom: 12px; }}
    .badge-GOAL {{ background: rgba(6,182,212,0.2); color: var(--cyan); }}
    .badge-THOUGHT {{ background: rgba(59,130,246,0.2); color: var(--blue); }}
    .badge-TOOL_CALL {{ background: rgba(234,179,8,0.2); color: var(--yellow); }}
    .badge-OBSERVATION {{ background: rgba(16,185,129,0.2); color: var(--green); }}
    .badge-FINAL_ANSWER {{ background: rgba(16,185,129,0.3); color: #34d399; }}
    .badge-INTERVENTION {{ background: rgba(168,85,247,0.2); color: var(--purple); }}
    pre {{ background: #070a10; border: 1px solid var(--border); padding: 12px; border-radius: 6px; font-family: monospace; font-size: 0.8rem; overflow-x: auto; margin-top: 8px; }}
    .meta-item {{ margin-bottom: 8px; font-size: 0.85rem; }}
    .meta-item span {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>AgentHarness Standalone Audit Report</h1>
    <p style="color: var(--muted); font-size: 0.95rem;">Goal: {dag.goal}</p>
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">Run ID</div><div class="stat-value" style="font-size: 1rem;">{dag.run_id}</div></div>
      <div class="stat-card"><div class="stat-label">Total Steps</div><div class="stat-value">{len(trajectory)}</div></div>
      <div class="stat-card"><div class="stat-label">Tokens Spent</div><div class="stat-value">{total_tokens}</div></div>
      <div class="stat-card"><div class="stat-label">Total Cost</div><div class="stat-value">${total_cost:.4f}</div></div>
      <div class="stat-card"><div class="stat-label">Branches</div><div class="stat-value">{len(dag.list_branches())}</div></div>
      <div class="stat-card"><div class="stat-label">Final Status</div><div class="stat-value" style="font-size: 0.85rem; color: var(--green);">{final_answer[:40]}</div></div>
    </div>
  </header>

  <div class="main-grid">
    <div id="graph-container"></div>
    <div class="inspector" id="inspector-panel">
      <p style="color: var(--muted);">Click any node in the decision graph to inspect thoughts, tool arguments, and sandbox outputs.</p>
    </div>
  </div>

  <script>
    const elements = {json.dumps(elements)};
    const nodes = {json.dumps(nodes_data)};

    const cy = cytoscape({{
      container: document.getElementById('graph-container'),
      elements: elements,
      style: [
        {{
          selector: 'node',
          style: {{
            'label': 'data(label)',
            'color': '#fff',
            'font-size': '11px',
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'background-color': '#334155',
            'width': 34,
            'height': 34
          }}
        }},
        {{ selector: 'node[type = "GOAL"]', style: {{ 'background-color': '#06b6d4' }} }},
        {{ selector: 'node[type = "THOUGHT"]', style: {{ 'background-color': '#3b82f6' }} }},
        {{ selector: 'node[type = "TOOL_CALL"]', style: {{ 'background-color': '#eab308' }} }},
        {{ selector: 'node[type = "OBSERVATION"]', style: {{ 'background-color': '#10b981' }} }},
        {{ selector: 'node[type = "FINAL_ANSWER"]', style: {{ 'background-color': '#059669', 'width': 42, 'height': 42 }} }},
        {{ selector: 'node[type = "INTERVENTION"]', style: {{ 'background-color': '#a855f7' }} }},
        {{
          selector: 'edge',
          style: {{
            'width': 2,
            'line-color': '#475569',
            'target-arrow-color': '#475569',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier'
          }}
        }}
      ],
      layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 40, rankSep: 70 }}
    }});

    cy.on('tap', 'node', function(evt) {{
      const nId = evt.target.id();
      const node = nodes.find(n => n.id === nId);
      if (!node) return;

      const panel = document.getElementById('inspector-panel');
      panel.innerHTML = `
        <div class="badge badge-${{node.node_type}}">${{node.node_type}}</div>
        <h2 style="font-size: 1.1rem; margin-bottom: 12px;">${{node.title || 'Step Details'}}</h2>
        <div class="meta-item"><span>Step:</span> #${{node.step_index}} (${{node.branch_id}})</div>
        <div class="meta-item"><span>Node ID:</span> ${{node.id}}</div>
        <div class="meta-item"><span>Content Hash:</span> <code>${{node.content_hash.substring(0, 16)}}...</code></div>
        <div class="meta-item"><span>Checkpoint:</span> ${{node.checkpoint_id || 'None'}}</div>
        <div class="meta-item"><span>Tokens:</span> ${{node.token_usage}}</div>
        <div style="margin-top: 14px;">
          <div style="font-size: 0.8rem; color: var(--muted); margin-bottom: 4px;">Payload</div>
          <pre>${{JSON.stringify(node.payload, null, 2)}}</pre>
        </div>
      `;
    }});
  </script>
</body>
</html>
"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html_content, encoding="utf-8")
    return output_file
