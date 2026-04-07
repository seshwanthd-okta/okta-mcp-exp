# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Orchestrator MCP Tools — Dynamic Knowledge Graph Queries.

No predefined workflows.  The LLM queries the capability graph to discover
tools, their data-flow connections, and dependency chains, then composes
the workflow itself by passing an ordered action list to be wired and executed.

Tools:
    orchestrator_query_graph  — query the KG for tools by entity/operation/reachability
    orchestrator_build_plan   — LLM provides an action sequence, KG wires the params
    orchestrator_execute      — execute an approved plan server-side
    orchestrator_context      — retrieve session state + graph stats
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.tools.orchestrator.engine import (
    Plan,
    PlanStatus,
    Step,
    create_plan,
    execute_plan,
    get_session,
    _serialise,
)
from okta_mcp_server.tools.orchestrator.knowledge_graph import get_knowledge_graph


@mcp.tool()
async def orchestrator_query_graph(
    ctx: Context,
    query_type: str,
    entity_type: Optional[str] = None,
    operation: Optional[str] = None,
    tag: Optional[str] = None,
    action: Optional[str] = None,
    available_params: Optional[str] = None,
    max_depth: Optional[int] = None,
    start_action: Optional[str] = None,
    end_action: Optional[str] = None,
) -> dict:
    """Query the knowledge graph dynamically to discover tools and connections.

    The graph contains all Okta SDK actions as nodes and data-flow dependencies
    as edges.  Use different query_type values to explore the graph:

    Parameters:
        query_type (str, required): The type of query. One of:
            - "tools"         — filter tools by entity_type, operation, and/or tag
            - "callable"      — given params you have, which tools can you call?
            - "reachable"     — BFS from start_action: what tools can be reached?
            - "dependencies"  — reverse BFS: what must run before this action?
            - "path"          — shortest data-flow path between two actions
            - "node"          — get full details of a single tool node
            - "stats"         — graph statistics
            - "full"          — dump entire graph (nodes + edges)

        entity_type (str, optional): Filter by entity: "user", "group", "application"
        operation (str, optional): Filter by operation: "read", "write", "delete"
        tag (str, optional): Filter by tag: "lookup", "lifecycle", "membership", etc.
        action (str, optional): Tool action name for "node" or "dependencies" queries
        available_params (str, optional): Comma-separated param names for "callable"
        max_depth (int, optional): Max traversal depth for "reachable" (default 10)
        start_action (str, optional): Start node for "reachable" or "path"
        end_action (str, optional): End node for "path"

    Returns:
        Dict with query results — tools, edges, paths, or stats depending on query_type.

    Examples:
        # What user tools exist?
        orchestrator_query_graph(query_type="tools", entity_type="user")

        # I have a user_id — what can I call?
        orchestrator_query_graph(query_type="callable", available_params="user_id")

        # What can I reach from get_user?
        orchestrator_query_graph(query_type="reachable", start_action="get_user")

        # What needs to run before I can call deactivate_user?
        orchestrator_query_graph(query_type="dependencies", action="deactivate_user")

        # Path from get_user to remove_user_from_group?
        orchestrator_query_graph(query_type="path", start_action="get_user", end_action="remove_user_from_group")
    """
    kg = get_knowledge_graph()
    qt = query_type.lower()

    logger.info(f"orchestrator_query_graph: type='{qt}'")

    if qt == "tools":
        tools = kg.query_tools(entity_type=entity_type, operation=operation, tag=tag)
        return {"tools": tools, "count": len(tools)}

    if qt == "callable":
        params = [p.strip() for p in (available_params or "").split(",") if p.strip()]
        tools = kg.query_callable_tools(params)
        return {"callable_tools": tools, "count": len(tools), "given_params": params}

    if qt == "reachable":
        if not start_action:
            return {"error": "reachable query requires start_action"}
        return kg.query_reachable(start_action, max_depth=max_depth or 10)

    if qt == "dependencies":
        target = action or end_action
        if not target:
            return {"error": "dependencies query requires action or end_action"}
        return kg.query_dependencies(target)

    if qt == "path":
        if not start_action or not end_action:
            return {"error": "path query requires start_action and end_action"}
        path = kg.query_path(start_action, end_action)
        if path is None:
            return {"path": None, "message": f"No path from '{start_action}' to '{end_action}'"}
        return {"path": path, "length": len(path)}

    if qt == "node":
        if not action:
            return {"error": "node query requires action"}
        node = kg.get_node(action)
        if not node:
            return {"error": f"Unknown action '{action}'"}
        incoming = [kg._serialise_edge(e) for e in kg.get_incoming_edges(action)]
        outgoing = [kg._serialise_edge(e) for e in kg.get_outgoing_edges(action)]
        return {
            "node": kg._serialise_node(node),
            "incoming_edges": incoming,
            "outgoing_edges": outgoing,
        }

    if qt == "stats":
        return kg.get_stats()

    if qt == "full":
        return kg.to_dict()

    return {"error": f"Unknown query_type '{query_type}'. Use: tools, callable, reachable, dependencies, path, node, stats, full"}


@mcp.tool()
async def orchestrator_build_plan(
    ctx: Context,
    actions: str,
    target_identifier: str,
    workflow_name: Optional[str] = None,
    description: Optional[str] = None,
    extra_params: Optional[str] = None,
) -> dict:
    """Build an execution plan from an ordered list of actions you chose.

    YOU decide the sequence of tools after querying the graph.  The KG
    automatically resolves parameter bindings (e.g. step 1's user ID feeds
    into step 2) based on its edge metadata.  You just provide the ordered
    action names.

    Parameters:
        actions (str, required): Comma-separated ordered action names.
            Example: "get_user,list_user_groups,remove_user_from_group,deactivate_user"
        target_identifier (str, required): The primary identifier (e.g. user email/ID).
        workflow_name (str, optional): A name for this workflow (default: "dynamic_workflow").
        description (str, optional): Human-readable description of what this does.
        extra_params (str, optional): Additional static params as "key=value,key=value".
            These override auto-resolved bindings on the first step.

    Returns:
        Dict with plan preview ready for orchestrator_execute.

    Example:
        orchestrator_build_plan(
            actions="get_user,list_user_groups,remove_user_from_group,deactivate_user",
            target_identifier="john@acme.com",
            workflow_name="offboard",
            description="Offboard john: remove from groups and deactivate"
        )
    """
    kg = get_knowledge_graph()

    action_list = [a.strip() for a in actions.split(",") if a.strip()]
    if not action_list:
        return {"error": "No actions provided. Pass comma-separated action names."}

    logger.info(f"orchestrator_build_plan: actions={action_list}, target='{target_identifier}'")

    # Let the KG resolve wiring (param bindings + for_each) from edges
    try:
        step_dicts = kg.build_execution_chain(action_list)
    except ValueError as exc:
        return {"error": str(exc)}

    # Inject the target identifier into the first step's required params
    first_node = kg.get_node(action_list[0])
    if first_node:
        for param in first_node.required_params:
            step_dicts[0]["params"][param] = target_identifier

    # Parse and apply extra_params
    if extra_params:
        for pair in extra_params.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                step_dicts[0]["params"][k.strip()] = v.strip()

    # Build engine Steps
    steps = [
        Step(
            number=sd["step"],
            action=sd["action"],
            params=sd["params"],
            description=sd["description"],
            is_destructive=sd["is_destructive"],
            for_each=sd.get("for_each"),
        )
        for sd in step_dicts
    ]

    wf_name = workflow_name or "dynamic_workflow"
    desc = description or f"Dynamic workflow: {' → '.join(action_list)}"

    plan = create_plan(workflow_name=wf_name, description=desc, steps=steps)

    has_destructive = any(s.is_destructive for s in steps)
    plan.status = PlanStatus.AWAITING_APPROVAL if has_destructive else PlanStatus.DRAFT

    session = get_session()
    session.plans[plan.plan_id] = plan

    preview = plan.to_preview()
    logger.info(f"Built dynamic plan {plan.plan_id} with {len(steps)} steps")

    if has_destructive:
        hint = (
            f"Plan has {len(steps)} steps "
            f"({len(preview['destructive_steps'])} destructive). "
            f"Requires approval. Call orchestrator_execute(plan_id='{plan.plan_id}') to run it."
        )
    else:
        hint = (
            f"Plan has {len(steps)} steps (no destructive actions). "
            f"Safe to execute. Call orchestrator_execute(plan_id='{plan.plan_id}') to run it."
        )

    return {
        "plan": preview,
        "wiring": step_dicts,
        "hint": hint,
    }


@mcp.tool()
async def orchestrator_execute(
    ctx: Context,
    plan_id: str,
) -> dict:
    """Execute an approved workflow plan server-side.

    The server runs all steps internally against the Okta API — no round-trips
    back to the client. Inter-step dependencies are resolved via the knowledge
    graph's edge metadata.

    Parameters:
        plan_id (str, required): The plan ID returned by orchestrator_build_plan.

    Returns:
        Dict with step-by-step execution results and context.
    """
    logger.info(f"orchestrator_execute: plan_id='{plan_id}'")

    session = get_session()
    plan = session.plans.get(plan_id)

    if not plan:
        return {
            "error": f"Plan '{plan_id}' not found. Call orchestrator_build_plan first.",
            "active_plans": [
                {"plan_id": p.plan_id, "workflow": p.workflow_name, "status": p.status.value}
                for p in session.plans.values()
            ],
        }

    if plan.status not in (PlanStatus.DRAFT, PlanStatus.AWAITING_APPROVAL):
        return {
            "error": f"Plan '{plan_id}' is in state '{plan.status.value}' and cannot be executed.",
            "summary": plan.to_summary(),
        }

    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        plan = await execute_plan(plan, manager)
    except Exception as exc:
        logger.error(f"Plan execution failed: {exc}")
        return {"error": f"Plan execution failed: {exc}"}

    summary = plan.to_summary()
    context = _build_execution_context(plan)
    logger.info(f"Plan {plan_id} completed: {plan.status.value}")

    return {
        "summary": summary,
        "context": context,
        "hint": (
            f"Workflow '{plan.workflow_name}' {plan.status.value}. "
            f"Call orchestrator_context() for full session state."
        ),
    }


@mcp.tool()
async def orchestrator_context(ctx: Context) -> dict:
    """Get the current orchestrator session state and graph stats.

    Returns all entities resolved, plans executed, and operations performed.
    Also includes graph statistics for reference.

    Returns:
        Dict with session data, active plans, and graph capabilities.
    """
    logger.info("orchestrator_context invoked")

    session = get_session()
    kg = get_knowledge_graph()

    active_plans = [
        {"plan_id": p.plan_id, "workflow": p.workflow_name, "status": p.status.value}
        for p in session.plans.values()
        if p.status in (PlanStatus.DRAFT, PlanStatus.AWAITING_APPROVAL)
    ]

    return {
        "session": session.to_dict(),
        "active_plans": active_plans,
        "graph_stats": kg.get_stats(),
        "hint": (
            "Use orchestrator_query_graph() to explore tools, "
            "orchestrator_build_plan() to compose a workflow, "
            "or orchestrator_execute() to run a pending plan."
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_execution_context(plan: Plan) -> dict:
    """Extract key information from plan results into a readable context."""
    context: dict = {
        "workflow": plan.workflow_name,
        "status": plan.status.value,
        "actions_taken": [],
    }

    for step in plan.steps:
        result_data = plan.results.get(step.number)
        if result_data is None:
            continue

        serialised = _serialise(result_data)

        if step.action == "get_user" and isinstance(serialised, dict):
            profile = serialised.get("profile", {})
            context["user"] = {
                "id": serialised.get("id"),
                "login": profile.get("login"),
                "email": profile.get("email"),
                "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
                "status": serialised.get("status"),
            }
            context["actions_taken"].append(
                f"Found user: {profile.get('email', serialised.get('id'))}"
            )

        elif step.action == "list_user_groups" and isinstance(serialised, list):
            group_names = []
            for g in serialised:
                gs = _serialise(g) if not isinstance(g, dict) else g
                if isinstance(gs, dict) and "profile" in gs:
                    group_names.append(gs["profile"].get("name", gs.get("id", "?")))
            context["groups_found"] = group_names
            context["actions_taken"].append(f"Found {len(group_names)} group memberships")

        elif step.action == "remove_user_from_group" and isinstance(serialised, list):
            context["groups_removed"] = len(serialised)
            context["actions_taken"].append(f"Removed from {len(serialised)} groups")

        elif step.action == "list_user_app_assignments" and isinstance(serialised, list):
            app_labels = []
            for a in serialised:
                a_s = _serialise(a) if not isinstance(a, dict) else a
                if isinstance(a_s, dict):
                    app_labels.append(a_s.get("label", a_s.get("appName", "?")))
            context["app_assignments"] = app_labels
            context["actions_taken"].append(f"Found {len(app_labels)} app assignments")

        elif step.action == "deactivate_user":
            context["actions_taken"].append("User account deactivated")

        elif step.action == "suspend_user":
            context["actions_taken"].append("User account suspended")

        elif step.action == "activate_user":
            context["actions_taken"].append("User account activated")

        elif step.action == "clear_user_sessions":
            context["actions_taken"].append("All sessions revoked")

        elif step.action == "add_user_to_group":
            context["actions_taken"].append("User added to target group")

        elif step.action == "get_group" and isinstance(serialised, dict):
            profile = serialised.get("profile", {})
            context["target_group"] = {
                "id": serialised.get("id"),
                "name": profile.get("name"),
            }
            context["actions_taken"].append(f"Found group: {profile.get('name')}")

    return context
