# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Orchestrator MCP Tools — CSP Constraint-Solver Orchestrator.

Three tools let the LLM delegate multi-step Okta workflows to a
server-side constraint solver instead of reasoning about the correct
API sequence itself.

Workflow for the LLM:
    1. Call orchestrator_plan_for_goal  — describe WHAT you want (goal),
       the solver figures out HOW (action sequence) and builds an
       executable plan.  Always returns a plan_id.
    2. Call orchestrator_execute        — run the plan the solver built.
    3. Call orchestrator_context        — inspect session state or results.

DO NOT manually determine which Okta API calls to make or in what
order — the CSP solver handles that automatically from the knowledge
graph's preconditions and effects.
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
from okta_mcp_server.tools.orchestrator.planner import (
    list_goals,
    plan_for_goal,
    plan_for_state,
)


# @mcp.tool()  # Temporarily disabled — CSP planner replaces manual KG queries
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


# @mcp.tool()  # Temporarily disabled — CSP planner replaces manual plan building
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

    # Parse extra_params and distribute them to every step so that each handler
    # can pick up the fields it needs (e.g. q= for list_brands, primaryColorHex=
    # for replace_brand_theme).  Handlers simply ignore params they don't use.
    if extra_params:
        extra: dict = {}
        for pair in extra_params.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                extra[k.strip()] = v.strip()
        for step_dict in step_dicts:
            step_dict["params"].update(extra)

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

    Call this AFTER orchestrator_plan_for_goal returns a plan_id.
    The server runs every step internally against the Okta API — no
    round-trips back to the LLM.  Inter-step data flow (e.g. user ID
    from step 1 feeds into step 2) is resolved automatically via the
    knowledge graph's edge metadata.

    Do NOT call this without a plan — call orchestrator_plan_for_goal first.

    Parameters:
        plan_id (str, required): The plan ID returned by orchestrator_plan_for_goal.
            Found in the response under solver_result → plan → plan_id.

    Returns:
        Dict with step-by-step execution results, context, and a summary.

    Example:
        # Step 1 — get a plan:
        result = orchestrator_plan_for_goal(goal_name="offboard_user",
                                           target_identifier="john@acme.com")
        plan_id = result["plan"]["plan_id"]

        # Step 2 — execute it:
        orchestrator_execute(plan_id=plan_id)
    """
    logger.info(f"orchestrator_execute: plan_id='{plan_id}'")

    session = get_session()
    plan = session.plans.get(plan_id)

    if not plan:
        return {
            "error": f"Plan '{plan_id}' not found. Call orchestrator_plan_for_goal first to create a plan.",
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

    Use this to:
    - Check what has already been done in this session.
    - Retrieve results from previously executed plans.
    - See which plans are still pending execution.
    - Answer follow-up questions without calling the Okta API again.

    No parameters — returns everything about the current session.

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
            "To start a new workflow, call orchestrator_plan_for_goal() with a "
            "goal_name (e.g. 'offboard_user') and target_identifier. "
            "To run a pending plan, call orchestrator_execute(plan_id='...')."
        ),
    }


@mcp.tool()
async def orchestrator_plan_for_goal(
    ctx: Context,
    goal_name: Optional[str] = None,
    goal_state: Optional[str] = None,
    initial_state: Optional[str] = None,
    target_identifier: Optional[str] = None,
) -> dict:
    """Plan an Okta workflow using the CSP constraint solver.

    THIS IS THE PRIMARY ENTRY POINT for all Okta operations.  Do NOT try to
    determine the correct API call sequence yourself — describe your goal and
    let the solver find the plan.

    This tool ONLY builds a plan.  To execute it, take the plan_id from the
    response and call orchestrator_execute(plan_id=...).

    How it works:
        1. You provide a goal (what end-state you want).
        2. The solver searches the knowledge graph's 109 annotated tool nodes
           and finds the minimal ordered action sequence that reaches that
           goal state from the current state.
        3. A plan is built and returned with a plan_id.
        4. Call orchestrator_execute(plan_id=...) to run it.

    ── CHOOSING A GOAL ──

    PREFERRED — Use a predefined goal_name (the solver already knows the
    correct goal predicates and initial state assumptions):

        goal_name                        What it does
        ─────────────────────────────    ────────────────────────────────────
        "offboard_user"                  Audit apps → revoke groups → clear sessions → deactivate
        "suspend_user"                   Clear sessions → suspend account
        "onboard_user"                   Create user → add to group → activate
        "audit_user"                     Profile + apps + groups + system logs
        "rotate_user_credentials"        Clear all sessions (force re-auth)
        "setup_brand"                    List brands → get brand → list themes
        "configure_custom_domain"        Create → verify → add certificate
        "configure_email_domain"         Create → verify
        "setup_device_assurance_policy"  Create policy → list policies
        "cleanup_group"                  Look up group → delete

    ALTERNATIVE — Supply an ad-hoc goal_state when none of the above fit.
    DISCOVERY — Call with no arguments to list all registered goals.

    ── STATE PREDICATE REFERENCE (for goal_state / initial_state) ──

    Predicates use the format "entity.property=VALUE" separated by commas.
    The solver matches goal predicates against tool *effects* (what each
    tool produces) and works backward to find the action sequence.

    Value semantics:
        PROVIDED    — the caller/user supplies this input data
        KNOWN       — the system has resolved this (ID, profile, status)
        ENUMERATED  — a list/collection has been fetched
        AUDITED     — user-app assignments have been listed
        RETRIEVED   — log events have been fetched
        CREATED     — entity was just created
        ACTIVE      — entity has been activated
        SUSPENDED   — user account suspended
        DEACTIVATED — entity has been deactivated
        DELETED     — entity has been deleted
        UPDATED     — entity profile/config has been modified
        REVOKED     — sessions cleared or group memberships removed
        GRANTED     — group membership added
        VERIFIED    — domain has been verified
        CONFIGURED  — certificate has been configured
        UPLOADED    — file (logo/favicon/background) has been uploaded
        SENT        — test email has been sent

    Available predicates by entity:

        user.*
            user.id=KNOWN                    (resolved by get_user)
            user.profile=KNOWN|UPDATED       (get_user | update_user)
            user.status=KNOWN|CREATED|ACTIVE|SUSPENDED|DEACTIVATED|DELETED
            user.list=KNOWN                  (list_users)
            user.apps=AUDITED               (list_user_app_assignments)
            user.groups=ENUMERATED           (list_user_groups)
            user.group_membership=GRANTED    (add_user_to_group)
            user.group_memberships=REVOKED   (remove_user_from_group)
            user.sessions=REVOKED            (clear_user_sessions)
            user.schema=KNOWN               (get_user_profile_attributes)

        group.*
            group.id=KNOWN                   (get_group)
            group.profile=KNOWN|UPDATED      (get_group | update_group)
            group.status=CREATED|DELETED     (create_group | delete_group)
            group.list=KNOWN                 (list_groups)
            group.users=ENUMERATED           (list_group_users)
            group.apps=ENUMERATED            (list_group_apps)

        application.*
            application.id=KNOWN             (get_application)
            application.profile=KNOWN|UPDATED
            application.status=KNOWN|CREATED|ACTIVE|DEACTIVATED|DELETED
            application.list=KNOWN           (list_applications)

        policy.*  /  policy_rule.*
            policy.id=KNOWN                  (get_policy)
            policy.profile=KNOWN|UPDATED
            policy.status=KNOWN|CREATED|ACTIVE|DEACTIVATED|DELETED
            policy.list=KNOWN                (list_policies)
            policy.rules=ENUMERATED          (list_policy_rules)
            policy_rule.id=KNOWN             (get_policy_rule)
            policy_rule.profile=KNOWN|UPDATED
            policy_rule.status=KNOWN|CREATED|ACTIVE|DEACTIVATED|DELETED

        brand.*  /  theme.*
            brand.id=KNOWN                   (get_brand)
            brand.profile=KNOWN|UPDATED
            brand.status=CREATED|DELETED
            brand.list=KNOWN                 (list_brands)
            brand.domains=ENUMERATED         (list_brand_domains)
            theme.id=KNOWN                   (get_brand_theme)
            theme.profile=KNOWN|UPDATED
            theme.list=KNOWN                 (list_brand_themes)
            theme.logo=UPLOADED|DELETED
            theme.favicon=UPLOADED|DELETED
            theme.background=UPLOADED|DELETED

        custom_domain.*
            custom_domain.id=KNOWN           (get_custom_domain / create)
            custom_domain.profile=KNOWN|UPDATED
            custom_domain.status=KNOWN|CREATED|VERIFIED|DELETED
            custom_domain.list=KNOWN         (list_custom_domains)
            custom_domain.certificate=CONFIGURED

        custom_page.*
            custom_page.sign_in_page=KNOWN|UPDATED|DELETED
            custom_page.sign_in_page_default=KNOWN
            custom_page.sign_in_page_preview=KNOWN|UPDATED|DELETED
            custom_page.sign_in_page_resources=KNOWN
            custom_page.error_page=KNOWN|UPDATED|DELETED
            custom_page.error_page_default=KNOWN
            custom_page.error_page_preview=KNOWN|UPDATED|DELETED
            custom_page.error_page_resources=KNOWN
            custom_page.sign_out_settings=KNOWN|UPDATED
            custom_page.widget_versions=KNOWN

        email_domain.*
            email_domain.id=KNOWN            (get_email_domain / create)
            email_domain.profile=KNOWN|UPDATED
            email_domain.status=KNOWN|CREATED|VERIFIED|DELETED
            email_domain.list=KNOWN          (list_email_domains)

        email_template.*
            email_template.id=KNOWN          (get_email_template)
            email_template.profile=KNOWN
            email_template.list=KNOWN        (list_email_templates)
            email_template.settings=KNOWN|UPDATED
            email_template.default_content=KNOWN
            email_template.default_content_preview=KNOWN
            email_template.customization_id=KNOWN
            email_template.customization=CREATED|DELETED
            email_template.customization_profile=KNOWN|UPDATED
            email_template.customization_preview=KNOWN
            email_template.customizations=ENUMERATED|DELETED
            email_template.test_email=SENT

        device_assurance.*
            device_assurance.id=KNOWN        (get / create)
            device_assurance.profile=KNOWN|UPDATED
            device_assurance.status=KNOWN|CREATED|DELETED
            device_assurance.list=KNOWN      (list)

        log.*
            log.events=RETRIEVED             (get_logs — no preconditions)

    ── PARAMETERS ──

    Parameters:
        goal_name (str, optional): A predefined goal name from the table above.

        goal_state (str, optional): Ad-hoc goal as comma-separated predicates.
            Each predicate is "entity.property=VALUE" from the reference above.
            The solver finds actions whose effects produce these predicates.
            Examples:
                "user.status=DEACTIVATED"
                "user.status=DEACTIVATED,user.sessions=REVOKED"
                "group.status=DELETED"
                "application.list=KNOWN"
                "log.events=RETRIEVED"
                "brand.list=KNOWN,theme.list=KNOWN"
                "custom_domain.status=VERIFIED,custom_domain.certificate=CONFIGURED"

        initial_state (str, optional): Override initial state assumptions.
            Tells the solver what is already true before planning starts.
            Format: "entity.property=VALUE,..."
            Common initial states:
                "user.identifier=PROVIDED"    — you have a user email/login/ID
                "group.identifier=PROVIDED"   — you have a group name/ID
                "user.id=KNOWN"               — user ID already resolved
            Usually not needed — predefined goals include sensible defaults.

        target_identifier (str, optional): The primary identifier for the target
            entity (e.g. user email, group name, brand ID).
            Required to build an executable plan.

    Returns:
        - If no goal given: list of available goals.
        - If planning succeeds: plan preview with plan_id.
          Always call orchestrator_execute(plan_id=...) to run it.

    ── TYPICAL USAGE ──

        # Step 1: Plan — offboard a user
        orchestrator_plan_for_goal(goal_name="offboard_user", target_identifier="john@acme.com")
        → returns plan with plan_id

        # Step 2: Execute
        orchestrator_execute(plan_id="<plan_id from step 1>")

        # Custom goal: deactivate and clear sessions
        orchestrator_plan_for_goal(
            goal_state="user.status=DEACTIVATED,user.sessions=REVOKED",
            initial_state="user.identifier=PROVIDED",
            target_identifier="jane@acme.com"
        )
        → returns plan with plan_id, then call orchestrator_execute(plan_id=...)

        # Get system logs
        orchestrator_plan_for_goal(goal_state="log.events=RETRIEVED")
        → returns plan with plan_id, then call orchestrator_execute(plan_id=...)

        # Discover available goals
        orchestrator_plan_for_goal()
    """
    # If neither goal_name nor goal_state provided, list available goals
    if not goal_name and not goal_state:
        goals = list_goals()
        return {
            "available_goals": goals,
            "hint": (
                "Choose a goal_name from the list, or provide your own goal_state "
                "as 'key=value,key=value' predicates."
            ),
        }

    # Parse initial_state if provided
    init_state: dict[str, str] | None = None
    if initial_state:
        init_state = {}
        for pair in initial_state.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                init_state[k.strip()] = v.strip()

    logger.info(f"orchestrator_plan_for_goal: goal_name='{goal_name}', "
                f"goal_state='{goal_state}', target='{target_identifier}'")

    kg = get_knowledge_graph()

    if goal_name:
        result = plan_for_goal(goal_name, initial_state=init_state, kg=kg)
    else:
        # Parse ad-hoc goal_state
        parsed_goal: dict[str, str] = {}
        for pair in (goal_state or "").split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                parsed_goal[k.strip()] = v.strip()
        if not parsed_goal:
            return {"error": "Invalid goal_state format. Use 'key=value,key=value'."}
        result = plan_for_state(parsed_goal, initial_state=init_state, kg=kg)

    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "goal": goal_name or "ad_hoc",
            "hint": "The planner could not find a valid action sequence for this goal.",
        }

    response: dict = {
        "success": True,
        "solver_result": result.to_dict(),
    }

    # ── Build an executable plan ──
    if target_identifier and result.actions:
        wf_name = goal_name or "csp_workflow"
        desc = f"CSP-planned workflow: {' → '.join(result.actions)}"

        # Reuse the existing build_plan logic
        try:
            step_dicts = kg.build_execution_chain(result.actions)
        except ValueError as exc:
            response["build_error"] = str(exc)
            return response

        # Inject target identifier and init_state optional params into first step
        first_node = kg.get_node(result.actions[0])
        if first_node:
            for param in first_node.required_params:
                step_dicts[0]["params"][param] = target_identifier
            if init_state:
                for param in (first_node.optional_params or []):
                    if param in init_state:
                        step_dicts[0]["params"][param] = init_state[param]

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

        plan = create_plan(workflow_name=wf_name, description=desc, steps=steps)
        has_destructive = any(s.is_destructive for s in steps)
        plan.status = PlanStatus.AWAITING_APPROVAL if has_destructive else PlanStatus.DRAFT

        session = get_session()
        session.plans[plan.plan_id] = plan

        response["plan"] = plan.to_preview()
        response["wiring"] = step_dicts
        response["hint"] = (
            f"CSP solver found {len(result.actions)}-step plan. "
            f"Call orchestrator_execute(plan_id='{plan.plan_id}') to run it."
        )
    else:
        response["hint"] = (
            f"CSP solver found {len(result.actions)}-step plan: "
            f"{' → '.join(result.actions)}. "
            "Provide target_identifier to build an executable plan."
        )

    return response


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
