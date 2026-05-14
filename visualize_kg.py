#!/usr/bin/env python3
"""
Visualize the Okta Knowledge Graph — full interactive graph with workflow selector.

Usage:
    python visualize_kg.py                        # full graph + workflow selector (default)
    python visualize_kg.py --query reachable --action get_user
    python visualize_kg.py --query dependencies --action deactivate_user
    python visualize_kg.py --query entity --entity user
    python visualize_kg.py --query path --start get_user --end deactivate_user
    python visualize_kg.py --query workflow --workflow offboard_user
    python visualize_kg.py --query full
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Add src to path so we can import the knowledge graph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pyvis.network import Network

from okta_mcp_server.tools.orchestrator.knowledge_graph import (
    build_okta_knowledge_graph,
    OktaKnowledgeGraph,
    EntityType,
)

# Workflow definitions: ordered actions for each workflow
WORKFLOW_ACTIONS = {
    "offboard_user": {
        "actions": [
            "get_user",
            "list_user_groups",
            "remove_user_from_group",
            "list_user_app_assignments",
            "deactivate_user",
        ],
        "description": "Offboard a user: look up → list groups → remove from all groups → list app assignments → deactivate",
    },
    "suspend_user": {
        "actions": [
            "get_user",
            "clear_user_sessions",
            "suspend_user",
        ],
        "description": "Suspend a user: look up → revoke sessions → suspend account",
    },
    "onboard_user": {
        "actions": [
            "get_user",
            "activate_user",
            "list_user_groups",
        ],
        "description": "Onboard a user: look up → activate account → list group memberships",
    },
}

# Color palette by entity type
ENTITY_COLORS = {
    "user": "#4A90D9",
    "group": "#7B68EE",
    "application": "#E67E22",
    "policy": "#27AE60",
    "policy_rule": "#2ECC71",
    "device_assurance": "#E74C3C",
    "log": "#95A5A6",
    "brand": "#F39C12",
    "custom_domain": "#1ABC9C",
    "email_domain": "#3498DB",
    "theme": "#9B59B6",
    "custom_page": "#E91E63",
    "email_template": "#00BCD4",
}

# Shape by operation type
OPERATION_SHAPES = {
    "read": "dot",
    "write": "diamond",
    "delete": "triangle",
}


def build_pyvis_network(title: str = "Okta Knowledge Graph") -> Network:
    """Create a base pyvis Network with consistent settings."""
    net = Network(
        height="900px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
        heading=title,
    )
    net.barnes_hut(
        gravity=-3000,
        central_gravity=0.3,
        spring_length=150,
        spring_strength=0.05,
        damping=0.09,
    )
    return net


def add_node_to_net(
    net: Network,
    node_data: dict,
    highlight: bool = False,
    step_number: int | None = None,
) -> None:
    """Add a single node to the pyvis network."""
    action = node_data["action"]
    entity = node_data["entity_type"]
    operation = node_data["operation"]
    is_destructive = node_data.get("is_destructive", False)

    color = ENTITY_COLORS.get(entity, "#888888")
    shape = OPERATION_SHAPES.get(operation, "dot")
    size = 30 if highlight else 20

    if is_destructive:
        border_color = "#FF0000"
        border_width = 3
    elif highlight:
        border_color = "#FFD700"
        border_width = 3
    else:
        border_color = color
        border_width = 1

    label = action
    if step_number is not None:
        label = f"Step {step_number}\n{action}"

    title_html = (
        f"<b>{action}</b><br>"
        f"<i>{node_data['description']}</i><br><br>"
        f"Entity: {entity}<br>"
        f"Operation: {operation}<br>"
        f"Required: {', '.join(node_data['required_params']) or 'none'}<br>"
        f"Optional: {', '.join(node_data.get('optional_params', [])) or 'none'}<br>"
        f"Outputs: {', '.join(node_data.get('outputs', []))}<br>"
        f"Tags: {', '.join(node_data.get('tags', []))}<br>"
        f"Destructive: {'⚠️ YES' if is_destructive else 'No'}"
    )

    net.add_node(
        action,
        label=label,
        title=title_html,
        color={"background": color, "border": border_color},
        borderWidth=border_width,
        shape=shape,
        size=size,
        font={"size": 12, "color": "#ffffff"},
    )


def add_edge_to_net(net: Network, edge_data: dict) -> None:
    """Add a single edge to the pyvis network."""
    is_iteration = edge_data.get("is_iteration", False)
    label = f"{edge_data['source_output']} → {edge_data['target_param']}"
    title = edge_data.get("description", "")

    net.add_edge(
        edge_data["source"],
        edge_data["target"],
        label=label,
        title=title,
        color="#FFD700" if is_iteration else "#888888",
        width=3 if is_iteration else 1,
        dashes=is_iteration,
        arrows="to",
        font={"size": 9, "color": "#cccccc", "align": "middle"},
    )


def visualize_workflow(kg: OktaKnowledgeGraph, workflow_name: str) -> str:
    """Visualize a specific workflow as a subgraph."""
    wf = WORKFLOW_ACTIONS.get(workflow_name)
    if not wf:
        print(f"Unknown workflow: {workflow_name}")
        print(f"Available: {', '.join(WORKFLOW_ACTIONS.keys())}")
        sys.exit(1)

    actions = wf["actions"]
    net = build_pyvis_network(f"Workflow: {workflow_name}")
    action_set = set(actions)

    # Add workflow nodes with step numbers
    for i, action in enumerate(actions, 1):
        node = kg.get_node(action)
        if node:
            node_data = kg._serialise_node(node)
            add_node_to_net(net, node_data, highlight=True, step_number=i)

    # Add edges between workflow nodes
    for edge in kg._edges:
        if edge.source in action_set and edge.target in action_set:
            add_edge_to_net(net, kg._serialise_edge(edge))

    # Add legend info
    legend = (
        f"<div style='position:fixed;top:10px;right:10px;background:#2d2d44;"
        f"padding:15px;border-radius:8px;color:white;font-size:13px;"
        f"z-index:999;border:1px solid #444;'>"
        f"<b>Workflow: {workflow_name}</b><br><br>"
        f"<b>Steps:</b><br>"
    )
    for i, action in enumerate(actions, 1):
        node = kg.get_node(action)
        desc = node.description if node else ""
        destructive = " ⚠️" if node and node.is_destructive else ""
        legend += f"{i}. {action}{destructive}<br>"
    legend += (
        f"<br><b>Legend:</b><br>"
        f"● Read &nbsp; ◆ Write &nbsp; ▲ Delete<br>"
        f"<span style='color:#FF0000'>Red border</span> = Destructive<br>"
        f"<span style='color:#FFD700'>Gold dashed</span> = Iteration edge"
        f"</div>"
    )

    out = f"kg_viz_{workflow_name}.html"
    net.save_graph(out)
    # inject legend
    _inject_html(out, legend)
    return out


def visualize_reachable(kg: OktaKnowledgeGraph, start_action: str, max_depth: int = 5) -> str:
    """Visualize all tools reachable from a starting action."""
    result = kg.query_reachable(start_action, max_depth)
    if "error" in result:
        print(result["error"])
        sys.exit(1)

    net = build_pyvis_network(f"Reachable from: {start_action}")

    for node_data in result["nodes"]:
        is_start = node_data["action"] == start_action
        add_node_to_net(net, node_data, highlight=is_start)

    for edge_data in result["edges"]:
        add_edge_to_net(net, edge_data)

    out = f"kg_viz_reachable_{start_action}.html"
    net.save_graph(out)
    _inject_legend(out, f"Reachable from '{start_action}'", result["nodes"])
    return out


def visualize_dependencies(kg: OktaKnowledgeGraph, target_action: str) -> str:
    """Visualize all prerequisite tools for a target action."""
    result = kg.query_dependencies(target_action)
    if "error" in result:
        print(result["error"])
        sys.exit(1)

    net = build_pyvis_network(f"Dependencies for: {target_action}")

    for node_data in result["nodes"]:
        is_target = node_data["action"] == target_action
        add_node_to_net(net, node_data, highlight=is_target)

    for edge_data in result["edges"]:
        add_edge_to_net(net, edge_data)

    out = f"kg_viz_deps_{target_action}.html"
    net.save_graph(out)
    _inject_legend(out, f"Dependencies for '{target_action}'", result["nodes"])
    return out


def visualize_path(kg: OktaKnowledgeGraph, start: str, end: str) -> str:
    """Visualize the shortest path between two actions."""
    path = kg.query_path(start, end)
    if path is None:
        print(f"No path found from '{start}' to '{end}'")
        sys.exit(1)

    net = build_pyvis_network(f"Path: {start} → {end}")

    # Collect all nodes in the path
    nodes_in_path = {start}
    for edge_data in path:
        nodes_in_path.add(edge_data["source"])
        nodes_in_path.add(edge_data["target"])

    for action in nodes_in_path:
        node = kg.get_node(action)
        if node:
            node_data = kg._serialise_node(node)
            is_endpoint = action in (start, end)
            add_node_to_net(net, node_data, highlight=is_endpoint)

    for edge_data in path:
        add_edge_to_net(net, edge_data)

    out = f"kg_viz_path_{start}_to_{end}.html"
    net.save_graph(out)
    return out


def visualize_entity(kg: OktaKnowledgeGraph, entity_type: str) -> str:
    """Visualize all tools for a specific entity type and their connections."""
    tools = kg.query_tools(entity_type=entity_type)
    if not tools:
        print(f"No tools found for entity type: {entity_type}")
        sys.exit(1)

    net = build_pyvis_network(f"Entity: {entity_type}")
    action_set = {t["action"] for t in tools}

    for node_data in tools:
        add_node_to_net(net, node_data, highlight=True)

    # Add edges between these tools
    for edge in kg._edges:
        if edge.source in action_set and edge.target in action_set:
            add_edge_to_net(net, kg._serialise_edge(edge))

    # Also add immediate neighbors (1 hop) for context
    neighbor_actions = set()
    for edge in kg._edges:
        if edge.source in action_set and edge.target not in action_set:
            neighbor_actions.add(edge.target)
        if edge.target in action_set and edge.source not in action_set:
            neighbor_actions.add(edge.source)

    for action in neighbor_actions:
        node = kg.get_node(action)
        if node:
            add_node_to_net(net, kg._serialise_node(node), highlight=False)

    for edge in kg._edges:
        src_in = edge.source in action_set or edge.source in neighbor_actions
        tgt_in = edge.target in action_set or edge.target in neighbor_actions
        if src_in and tgt_in and not (edge.source in action_set and edge.target in action_set):
            add_edge_to_net(net, kg._serialise_edge(edge))

    out = f"kg_viz_entity_{entity_type}.html"
    net.save_graph(out)
    _inject_legend(out, f"Entity: {entity_type}", tools)
    return out


def visualize_full(kg: OktaKnowledgeGraph) -> str:
    """Visualize the entire knowledge graph with interactive workflow selector."""
    graph_data = kg.to_dict()
    net = build_pyvis_network("")  # heading injected via custom HTML

    for _action, node_data in graph_data["nodes"].items():
        add_node_to_net(net, node_data)

    for edge_data in graph_data["edges"]:
        add_edge_to_net(net, edge_data)

    out = "kg_viz_full.html"
    net.save_graph(out)

    # Build metadata for JS-side workflow highlighting
    stats = kg.get_stats()
    workflows_js = json.dumps(WORKFLOW_ACTIONS, indent=2)
    entity_colors_js = json.dumps(ENTITY_COLORS)

    # Collect per-node metadata so JS can restore original colors
    node_meta = {}
    for action, node in graph_data["nodes"].items():
        node_meta[action] = {
            "entity_type": node["entity_type"],
            "operation": node["operation"],
            "is_destructive": node.get("is_destructive", False),
        }
    node_meta_js = json.dumps(node_meta)

    # Collect edge info for workflow edge highlighting
    edge_list = []
    for edge_data in graph_data["edges"]:
        edge_list.append({
            "source": edge_data["source"],
            "target": edge_data["target"],
            "is_iteration": edge_data.get("is_iteration", False),
        })
    edge_list_js = json.dumps(edge_list)

    # --- Build the sidebar + JS control panel ---
    sidebar_html = _build_interactive_sidebar(stats, workflows_js, entity_colors_js, node_meta_js, edge_list_js)
    _inject_html(out, sidebar_html)
    return out


def _build_interactive_sidebar(
    stats: dict,
    workflows_js: str,
    entity_colors_js: str,
    node_meta_js: str,
    edge_list_js: str,
) -> str:
    """Build the full sidebar HTML + JS for workflow/entity/query controls."""

    # Build entity color legend rows
    entity_legend = ""
    for entity, color in ENTITY_COLORS.items():
        entity_legend += (
            f'<label style="display:flex;align-items:center;gap:6px;cursor:pointer;padding:1px 0">'
            f'<input type="checkbox" class="entity-filter" data-entity="{entity}" checked '
            f'style="accent-color:{color}">'
            f'<span style="color:{color};font-size:16px">●</span> {entity}'
            f'</label>'
        )

    # Build workflow option buttons
    workflow_buttons = ""
    for wf_name, wf_data in WORKFLOW_ACTIONS.items():
        label = wf_name.replace("_", " ").title()
        workflow_buttons += (
            f'<button class="wf-btn" data-workflow="{wf_name}" '
            f'title="{wf_data["description"]}">{label}</button>'
        )

    return f'''
<style>
  #sidebar {{
    position: fixed; top: 0; right: 0; width: 300px; height: 100vh;
    background: #1e1e30; color: #e0e0e0; font-family: 'Segoe UI', sans-serif;
    font-size: 13px; z-index: 9999; overflow-y: auto; padding: 16px;
    border-left: 2px solid #444; box-sizing: border-box;
    box-shadow: -4px 0 20px rgba(0,0,0,0.5);
  }}
  #sidebar h2 {{ margin: 0 0 8px 0; font-size: 18px; color: #FFD700; }}
  #sidebar h3 {{ margin: 14px 0 6px 0; font-size: 14px; color: #aaa;
    text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #333;
    padding-bottom: 4px; }}
  .stat {{ color: #888; margin-bottom: 10px; }}
  .wf-btn {{
    display: block; width: 100%; padding: 8px 12px; margin: 4px 0;
    background: #2a2a45; color: #e0e0e0; border: 1px solid #444;
    border-radius: 6px; cursor: pointer; font-size: 13px; text-align: left;
    transition: all 0.2s;
  }}
  .wf-btn:hover {{ background: #3a3a5a; border-color: #666; }}
  .wf-btn.active {{ background: #3d3500; border-color: #FFD700; color: #FFD700;
    font-weight: bold; }}
  #reset-btn {{
    display: block; width: 100%; padding: 8px; margin: 8px 0 0 0;
    background: #444; color: #fff; border: none; border-radius: 6px;
    cursor: pointer; font-size: 13px;
  }}
  #reset-btn:hover {{ background: #555; }}
  .wf-steps {{ background: #252540; border-radius: 6px; padding: 10px;
    margin: 8px 0; font-size: 12px; line-height: 1.7; display: none; }}
  .wf-steps.visible {{ display: block; }}
  .step-item {{ padding: 2px 0; }}
  .step-num {{ color: #FFD700; font-weight: bold; margin-right: 4px; }}
  .destructive {{ color: #FF6B6B; }}
  .shape-legend {{ display: flex; gap: 14px; margin: 4px 0; }}
  .edge-legend {{ margin-top: 4px; font-size: 12px; }}
  #mynetwork {{ width: calc(100% - 300px) !important; }}
</style>

<div id="sidebar">
  <h2>Okta Knowledge Graph</h2>
  <div class="stat">{stats['total_nodes']} nodes &middot; {stats['total_edges']} edges</div>

  <h3>Workflows</h3>
  <div id="workflow-buttons">
    {workflow_buttons}
  </div>
  <button id="reset-btn">Show Full Graph</button>
  <div id="wf-step-panel" class="wf-steps"></div>

  <h3>Filter by Entity</h3>
  <div id="entity-filters">
    {entity_legend}
  </div>

  <h3>Legend</h3>
  <div class="shape-legend">
    <span>● Read</span>
    <span>◆ Write</span>
    <span>▲ Delete</span>
  </div>
  <div class="edge-legend">
    <span style="color:#FF0000">Red border</span> = Destructive<br>
    <span style="color:#FFD700">Gold border</span> = Workflow step<br>
    <span style="color:#FFD700">Gold dashed edge</span> = Iteration
  </div>
</div>

<script>
(function() {{
  const WORKFLOWS = {workflows_js};
  const ENTITY_COLORS = {entity_colors_js};
  const NODE_META = {node_meta_js};
  const EDGE_LIST = {edge_list_js};

  // Wait for vis network to be ready
  function waitForNetwork(cb) {{
    if (typeof network !== 'undefined' && network) {{ cb(); return; }}
    setTimeout(() => waitForNetwork(cb), 100);
  }}

  waitForNetwork(function() {{
    const allNodeIds = network.body.data.nodes.getIds();
    const allEdgeIds = network.body.data.edges.getIds();

    // Save original node states
    const origNodes = {{}};
    allNodeIds.forEach(id => {{
      const n = network.body.data.nodes.get(id);
      origNodes[id] = {{
        color: JSON.parse(JSON.stringify(n.color || {{}})),
        borderWidth: n.borderWidth,
        size: n.size,
        label: n.label,
        hidden: false,
        font: JSON.parse(JSON.stringify(n.font || {{}})),
      }};
    }});

    // Save original edge states
    const origEdges = {{}};
    allEdgeIds.forEach(id => {{
      const e = network.body.data.edges.get(id);
      origEdges[id] = {{
        color: e.color,
        width: e.width,
        dashes: e.dashes,
        hidden: false,
      }};
    }});

    // ---- Reset to full graph ----
    function resetGraph() {{
      allNodeIds.forEach(id => {{
        network.body.data.nodes.update({{ id, ...origNodes[id] }});
      }});
      allEdgeIds.forEach(id => {{
        network.body.data.edges.update({{ id, ...origEdges[id] }});
      }});
      document.querySelectorAll('.wf-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('wf-step-panel').classList.remove('visible');
      document.querySelectorAll('.entity-filter').forEach(cb => {{ cb.checked = true; }});
      network.fit({{ animation: true }});
    }}

    // ---- Highlight a workflow ----
    function highlightWorkflow(wfName) {{
      const wf = WORKFLOWS[wfName];
      if (!wf) return;
      const actions = wf.actions;
      const actionSet = new Set(actions);

      // Dim all nodes
      allNodeIds.forEach(id => {{
        if (actionSet.has(id)) {{
          const stepIdx = actions.indexOf(id);
          const meta = NODE_META[id] || {{}};
          const entColor = ENTITY_COLORS[meta.entity_type] || '#888';
          network.body.data.nodes.update({{
            id,
            label: 'Step ' + (stepIdx + 1) + '\\n' + id,
            color: {{ background: entColor, border: meta.is_destructive ? '#FF0000' : '#FFD700' }},
            borderWidth: 3,
            size: 35,
            hidden: false,
            font: {{ size: 14, color: '#ffffff' }},
          }});
        }} else {{
          network.body.data.nodes.update({{
            id,
            color: {{ background: '#333', border: '#444' }},
            borderWidth: 1,
            size: 12,
            font: {{ size: 8, color: '#666' }},
            hidden: false,
          }});
        }}
      }});

      // Dim all edges, highlight workflow edges
      allEdgeIds.forEach(eid => {{
        const e = network.body.data.edges.get(eid);
        const srcIn = actionSet.has(e.from);
        const tgtIn = actionSet.has(e.to);
        if (srcIn && tgtIn) {{
          // Check if iteration edge
          const edgeInfo = EDGE_LIST.find(el => el.source === e.from && el.target === e.to);
          const isIter = edgeInfo ? edgeInfo.is_iteration : false;
          network.body.data.edges.update({{
            id: eid,
            color: isIter ? '#FFD700' : '#ffffff',
            width: isIter ? 4 : 2,
            dashes: isIter,
            hidden: false,
          }});
        }} else {{
          network.body.data.edges.update({{
            id: eid,
            color: '#222',
            width: 0.5,
            hidden: false,
          }});
        }}
      }});

      // Show step panel
      const panel = document.getElementById('wf-step-panel');
      let html = '<b>' + wfName.replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase()) + '</b><br>';
      html += '<span style="color:#888;font-size:11px">' + wf.description + '</span><br><br>';
      actions.forEach((a, i) => {{
        const meta = NODE_META[a] || {{}};
        const dest = meta.is_destructive ? ' <span class="destructive">⚠️ destructive</span>' : '';
        html += '<div class="step-item"><span class="step-num">' + (i+1) + '.</span> ' + a + dest + '</div>';
      }});
      panel.innerHTML = html;
      panel.classList.add('visible');

      // Focus on workflow nodes
      network.fit({{ nodes: actions, animation: true }});
    }}

    // ---- Entity filter ----
    function applyEntityFilter() {{
      const checked = new Set();
      document.querySelectorAll('.entity-filter:checked').forEach(cb => {{
        checked.add(cb.dataset.entity);
      }});
      allNodeIds.forEach(id => {{
        const meta = NODE_META[id] || {{}};
        const visible = checked.has(meta.entity_type);
        network.body.data.nodes.update({{ id, hidden: !visible }});
      }});
      allEdgeIds.forEach(eid => {{
        const e = network.body.data.edges.get(eid);
        const srcMeta = NODE_META[e.from] || {{}};
        const tgtMeta = NODE_META[e.to] || {{}};
        const visible = checked.has(srcMeta.entity_type) && checked.has(tgtMeta.entity_type);
        network.body.data.edges.update({{ id: eid, hidden: !visible }});
      }});
    }}

    // ---- Wire up buttons ----
    document.querySelectorAll('.wf-btn').forEach(btn => {{
      btn.addEventListener('click', function() {{
        // Reset first
        allNodeIds.forEach(id => {{
          network.body.data.nodes.update({{ id, ...origNodes[id] }});
        }});
        allEdgeIds.forEach(id => {{
          network.body.data.edges.update({{ id, ...origEdges[id] }});
        }});
        // Toggle
        const wf = this.dataset.workflow;
        const wasActive = this.classList.contains('active');
        document.querySelectorAll('.wf-btn').forEach(b => b.classList.remove('active'));
        if (wasActive) {{
          document.getElementById('wf-step-panel').classList.remove('visible');
          network.fit({{ animation: true }});
        }} else {{
          this.classList.add('active');
          highlightWorkflow(wf);
        }}
      }});
    }});

    document.getElementById('reset-btn').addEventListener('click', resetGraph);

    document.querySelectorAll('.entity-filter').forEach(cb => {{
      cb.addEventListener('change', function() {{
        // Clear any active workflow first
        document.querySelectorAll('.wf-btn').forEach(b => b.classList.remove('active'));
        document.getElementById('wf-step-panel').classList.remove('visible');
        // Restore then filter
        allNodeIds.forEach(id => {{
          network.body.data.nodes.update({{ id, ...origNodes[id] }});
        }});
        allEdgeIds.forEach(id => {{
          network.body.data.edges.update({{ id, ...origEdges[id] }});
        }});
        applyEntityFilter();
      }});
    }});
  }});
}})();
</script>
'''


def _inject_legend(filepath: str, title: str, nodes: list[dict]) -> None:
    """Inject an informational legend into the HTML file."""
    entity_counts: dict[str, int] = {}
    for n in nodes:
        et = n["entity_type"]
        entity_counts[et] = entity_counts.get(et, 0) + 1

    legend = (
        f"<div style='position:fixed;top:10px;right:10px;background:#2d2d44;"
        f"padding:15px;border-radius:8px;color:white;font-size:13px;"
        f"z-index:999;border:1px solid #444;max-height:80vh;overflow-y:auto;'>"
        f"<b>{title}</b><br><br>"
        f"Total nodes: {len(nodes)}<br><br>"
        f"<b>By entity:</b><br>"
    )
    for entity, count in sorted(entity_counts.items()):
        color = ENTITY_COLORS.get(entity, "#888")
        legend += f"<span style='color:{color}'>●</span> {entity}: {count}<br>"
    legend += (
        f"<br><b>Shapes:</b><br>"
        f"● Read &nbsp; ◆ Write &nbsp; ▲ Delete<br>"
        f"<span style='color:#FF0000'>Red border</span> = Destructive<br>"
        f"<span style='color:#FFD700'>Gold border</span> = Highlighted<br>"
        f"<span style='color:#FFD700'>Gold dashed edge</span> = Iteration"
        f"</div>"
    )
    _inject_html(filepath, legend)


def _inject_html(filepath: str, html_snippet: str) -> None:
    """Inject HTML snippet before </body> in the generated file."""
    with open(filepath, "r") as f:
        content = f.read()
    content = content.replace("</body>", f"{html_snippet}</body>")
    with open(filepath, "w") as f:
        f.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize the Okta Knowledge Graph")
    parser.add_argument(
        "--query", "-q",
        choices=["workflow", "reachable", "dependencies", "path", "entity", "full"],
        default="full",
        help="Type of query to visualize (default: full)",
    )
    parser.add_argument("--action", "-a", help="Action name (for reachable/dependencies)")
    parser.add_argument("--start", help="Start action (for path query)")
    parser.add_argument("--end", help="End action (for path query)")
    parser.add_argument("--entity", "-e", help="Entity type (for entity query)")
    parser.add_argument("--workflow", "-w", default="offboard_user", help="Workflow name")
    parser.add_argument("--depth", "-d", type=int, default=5, help="Max depth for reachable query")

    args = parser.parse_args()

    print("Building knowledge graph...")
    kg = build_okta_knowledge_graph()
    stats = kg.get_stats()
    print(f"  {stats['total_nodes']} nodes, {stats['total_edges']} edges")

    if args.query == "workflow":
        out = visualize_workflow(kg, args.workflow)
    elif args.query == "reachable":
        if not args.action:
            parser.error("--action is required for 'reachable' query")
        out = visualize_reachable(kg, args.action, args.depth)
    elif args.query == "dependencies":
        if not args.action:
            parser.error("--action is required for 'dependencies' query")
        out = visualize_dependencies(kg, args.action)
    elif args.query == "path":
        if not args.start or not args.end:
            parser.error("--start and --end are required for 'path' query")
        out = visualize_path(kg, args.start, args.end)
    elif args.query == "entity":
        if not args.entity:
            parser.error("--entity is required for 'entity' query")
        out = visualize_entity(kg, args.entity)
    elif args.query == "full":
        out = visualize_full(kg)
    else:
        parser.error(f"Unknown query type: {args.query}")

    print(f"\nVisualization saved to: {out}")
    print(f"Open in browser: file://{os.path.abspath(out)}")


if __name__ == "__main__":
    main()
