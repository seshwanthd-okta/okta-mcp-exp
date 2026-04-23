# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Orchestrator MCP Tools — legacy predefined-workflow orchestrator.

NOTE: This module provides predefined workflow matching (offboard/suspend/onboard).
For dynamic, goal-driven workflow planning, prefer the CSP solver tools:

    orchestrator_plan_for_goal  — CSP solver: goal in, executable plan out
    orchestrator_execute        — execute an approved plan server-side
    orchestrator_context        — retrieve session state + graph stats

The CSP solver (in orchestrator_kg.py) can automatically determine the
correct sequence of Okta API calls for any registered goal, without
requiring manual workflow definitions.
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.tools.orchestrator.engine import (
    PlanStatus,
    execute_plan,
    get_session,
)
from okta_mcp_server.tools.orchestrator.workflows import (
    WORKFLOW_REGISTRY,
    get_workflow_info,
    match_workflow,
    match_workflow_by_keywords,
)


@mcp.tool()
async def orchestrator_query(
    ctx: Context,
    action: str,
    target_type: str,
    target_identifier: str,
    intent: Optional[str] = None,
) -> dict:
    """Build a multi-step Okta workflow plan from predefined workflows.

    NOTE: For dynamic goal-driven planning, prefer orchestrator_plan_for_goal()
    which uses the CSP constraint solver to automatically determine the correct
    action sequence. This tool only supports a fixed set of predefined workflows.

    Parameters:
        action (str, required): The operation to perform. Currently supported:
            - "offboard" — remove user from all groups and deactivate
            - "suspend"  — revoke all active sessions and suspend the account
            - "onboard"  — activate an account and report group memberships
            Use "list" to see all available workflows.
        target_type (str, required): The entity type. Currently supported: "user".
        target_identifier (str, required): The user's email, login, or Okta ID.
        intent (str, optional): Free-form description of what you want to do.
            Used as fallback if action/target_type don't match a workflow.

    Returns:
        Dict containing:
        - plan: Preview of the execution plan with numbered steps
        - available_workflows: List of all supported workflows (when action="list")
        - hint: Guidance on next steps

    Example:
        # Prefer the CSP solver instead:
        orchestrator_plan_for_goal(goal_name="offboard_user", target_identifier="john@acme.com")

        # Legacy predefined workflow:
        orchestrator_query(action="offboard", target_type="user", target_identifier="john@acme.com")
    """
    logger.info(f"orchestrator_query: action='{action}', target_type='{target_type}', "
                f"target_identifier='{target_identifier}', intent='{intent}'")

    # ── List mode ──
    if action.lower() == "list":
        workflows = get_workflow_info()
        return {
            "available_workflows": workflows,
            "total_workflows": len(workflows),
            "hint": (
                "Prefer orchestrator_plan_for_goal() for dynamic goal-driven planning. "
                "Example: orchestrator_plan_for_goal(goal_name='offboard_user', "
                "target_identifier='john@acme.com'). "
                "Or use orchestrator_query with action and target_type from the list above."
            ),
        }

    # ── Match workflow ──
    workflow_name = match_workflow(action, target_type)

    # Fallback to keyword matching on intent
    if not workflow_name and intent:
        workflow_name = match_workflow_by_keywords(intent)

    if not workflow_name:
        return {
            "error": f"No workflow found for action='{action}', target_type='{target_type}'",
            "available_workflows": get_workflow_info(),
            "hint": (
                "Try orchestrator_plan_for_goal() for automatic workflow planning. "
                "Example: orchestrator_plan_for_goal(goal_name='offboard_user', "
                "target_identifier='john@acme.com'). "
                "Or use action='list' to see predefined workflows."
            ),
        }

    # ── Build plan ──
    entry = WORKFLOW_REGISTRY[workflow_name]
    builder = entry["builder"]

    try:
        plan = builder(user_identifier=target_identifier)
    except Exception as exc:
        logger.error(f"Failed to build plan for '{workflow_name}': {exc}")
        return {"error": f"Failed to build workflow plan: {exc}"}

    plan.status = PlanStatus.AWAITING_APPROVAL
    session = get_session()
    session.plans[plan.plan_id] = plan

    preview = plan.to_preview()
    logger.info(f"Built plan {plan.plan_id} with {len(plan.steps)} steps")

    return {
        "plan": preview,
        "hint": (
            f"Review the plan above. It has {len(plan.steps)} steps "
            f"({len(preview['destructive_steps'])} destructive). "
            f"Call orchestrator_execute(plan_id='{plan.plan_id}') to run it server-side. "
            f"All steps execute internally — no additional tool calls needed."
        ),
    }


@mcp.tool()
async def orchestrator_execute(
    ctx: Context,
    plan_id: str,
    params: Optional[str] = None,
) -> dict:
    """Execute an approved workflow plan server-side.

    The server runs all steps internally against the Okta API — no round-trips
    back to the client.  Inter-step dependencies (user IDs, group lists) are
    resolved automatically.  Returns a consolidated result with all outcomes.

    Parameters:
        plan_id (str, required): The plan ID returned by orchestrator_plan_for_goal or orchestrator_query.
        params (str, optional): Additional params as "key=value,key=value" to inject
            into plan steps at execution time. Each handler picks up the params it
            needs (e.g. name=Everyone for get_group). Existing step params are not
            overwritten.

    Returns:
        Dict containing:
        - summary: Step-by-step execution results (status, duration, errors)
        - context: Resolved entities and key data from the execution
        - hint: What to do next
    """
    logger.info(f"orchestrator_execute: plan_id='{plan_id}', params='{params}'")

    session = get_session()
    plan = session.plans.get(plan_id)

    if not plan:
        return {
            "error": f"Plan '{plan_id}' not found. Call orchestrator_plan_for_goal or orchestrator_query first to create a plan.",
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

    # Merge user-provided params into each step (handlers ignore unknown params)
    if params:
        extra: dict = {}
        for pair in params.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                extra[k.strip()] = v.strip()
        if extra:
            for step in plan.steps:
                for k, v in extra.items():
                    if k not in step.params:
                        step.params[k] = v

    # Get the Okta auth manager from context
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    # Execute all steps server-side
    try:
        plan = await execute_plan(plan, manager)
    except Exception as exc:
        logger.error(f"Plan execution failed: {exc}")
        return {"error": f"Plan execution failed: {exc}"}

    summary = plan.to_summary()
    logger.info(f"Plan {plan_id} completed with status: {plan.status.value}")

    # Build a human-readable context from results
    context = _build_execution_context(plan)

    return {
        "summary": summary,
        "context": context,
        "hint": (
            f"Workflow '{plan.workflow_name}' {plan.status.value}. "
            f"Call orchestrator_context() to see the full session state, "
            f"or orchestrator_plan_for_goal() to plan a new workflow with the CSP solver."
        ),
    }


@mcp.tool()
async def orchestrator_context(ctx: Context) -> dict:
    """Get the current orchestrator session state.

    Returns all entities resolved, plans executed, and operations performed
    in this session.  Use this to answer follow-up questions without
    re-querying the Okta API.

    Returns:
        Dict containing:
        - session: Entities resolved, plans executed, total API calls
        - active_plans: Plans that haven't been executed yet
        - hint: Available actions
    """
    logger.info("orchestrator_context invoked")

    session = get_session()
    active_plans = [
        {"plan_id": p.plan_id, "workflow": p.workflow_name, "status": p.status.value}
        for p in session.plans.values()
        if p.status in (PlanStatus.DRAFT, PlanStatus.AWAITING_APPROVAL)
    ]

    return {
        "session": session.to_dict(),
        "active_plans": active_plans,
        "hint": (
            "Use orchestrator_plan_for_goal() to plan a new workflow with the CSP solver, "
            "or orchestrator_execute(plan_id='...') to run a pending plan."
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_execution_context(plan) -> dict:
    """Extract key information from plan results into a readable context dict."""
    from okta_mcp_server.tools.orchestrator.engine import _serialise

    context: dict = {
        "workflow": plan.workflow_name,
        "status": plan.status.value,
        "actions_taken": [],
    }

    # Step 1 — user lookup
    user_data = plan.results.get(1)
    if user_data:
        user_dict = _serialise(user_data)
        if isinstance(user_dict, dict):
            profile = user_dict.get("profile", {})
            context["user"] = {
                "id": user_dict.get("id"),
                "login": profile.get("login"),
                "email": profile.get("email"),
                "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
                "status": user_dict.get("status"),
            }
            context["actions_taken"].append(
                f"Found user: {profile.get('email', user_dict.get('id'))}"
            )

    # Step 2 — groups
    groups_data = plan.results.get(2)
    if isinstance(groups_data, list):
        group_names = []
        for g in groups_data:
            gs = _serialise(g)
            if isinstance(gs, dict) and "profile" in gs:
                group_names.append(gs["profile"].get("name", gs.get("id", "?")))
            elif hasattr(g, "profile") and hasattr(g.profile, "name"):
                group_names.append(g.profile.name)
        context["groups_found"] = group_names
        context["actions_taken"].append(f"Found {len(group_names)} group memberships")

    # Step 3 — group removals
    removals = plan.results.get(3)
    if isinstance(removals, list):
        context["groups_removed"] = len(removals)
        context["actions_taken"].append(f"Removed from {len(removals)} groups")

    # Step 4 — app assignments
    apps_data = plan.results.get(4)
    if isinstance(apps_data, list):
        app_labels = []
        for a in apps_data:
            a_s = _serialise(a)
            if isinstance(a_s, dict):
                app_labels.append(a_s.get("label", a_s.get("appName", "?")))
            elif hasattr(a, "label"):
                app_labels.append(a.label)
        context["app_assignments"] = app_labels
        context["actions_taken"].append(f"Found {len(app_labels)} app assignments")

    # Step 5 — deactivation
    deactivation = plan.results.get(5)
    if deactivation:
        context["actions_taken"].append("User account deactivated")

    # Build summary
    if context.get("user"):
        name = context["user"].get("name") or context["user"].get("email")
        context["summary"] = (
            f"User '{name}' has been offboarded: "
            f"removed from {context.get('groups_removed', 0)} groups, "
            f"has {len(context.get('app_assignments', []))} app assignments, "
            f"and account deactivated."
        )

    return context
