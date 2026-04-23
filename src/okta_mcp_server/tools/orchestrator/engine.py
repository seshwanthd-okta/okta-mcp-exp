# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Orchestrator Workflow Engine — executes multi-step Okta workflows server-side.

The engine takes a plan (list of steps), resolves inter-step variable
references ($stepN.field), executes each step against the Okta API,
and returns a consolidated result.  The LLM client never sees
intermediate steps — it gets one final context object.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from loguru import logger

from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.pagination import paginate_all_results


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    DRAFT = "draft"          # plan created, not yet executed
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL = "partial"      # some steps failed
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    step_number: int
    action: str
    status: StepStatus
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class Step:
    """A single step in a workflow plan."""
    number: int
    action: str                           # Okta SDK method name (e.g. "list_users")
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    is_destructive: bool = False
    for_each: str | None = None           # "$stepN.field" — iterate over previous result
    result: StepResult | None = None


@dataclass
class Plan:
    """A workflow execution plan."""
    plan_id: str
    workflow_name: str
    description: str
    steps: list[Step]
    status: PlanStatus = PlanStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    results: dict[int, Any] = field(default_factory=dict)  # step_number → raw result

    def to_preview(self) -> dict:
        """Return a client-friendly preview of the plan."""
        destructive = [s.number for s in self.steps if s.is_destructive]
        return {
            "plan_id": self.plan_id,
            "workflow": self.workflow_name,
            "description": self.description,
            "steps": [
                {
                    "step": s.number,
                    "action": s.action,
                    "description": s.description,
                    "params": _mask_references(s.params),
                    "destructive": s.is_destructive,
                    **({"for_each": s.for_each} if s.for_each else {}),
                }
                for s in self.steps
            ],
            "total_steps": len(self.steps),
            "destructive_steps": destructive,
            "requires_approval": len(destructive) > 0,
            "status": self.status.value,
        }

    def to_summary(self) -> dict:
        """Return a post-execution summary."""
        step_summaries = []
        for s in self.steps:
            r = s.result
            step_summaries.append({
                "step": s.number,
                "action": s.action,
                "description": s.description,
                "status": r.status.value if r else "not_run",
                "duration_ms": r.duration_ms if r else 0,
                **({"error": r.error} if r and r.error else {}),
            })
        return {
            "plan_id": self.plan_id,
            "workflow": self.workflow_name,
            "status": self.status.value,
            "steps": step_summaries,
            "results": {k: _serialise(v) for k, v in self.results.items()},
        }


# ---------------------------------------------------------------------------
# Session context — persists across calls within a conversation
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    """Tracks entities and operations across the session."""
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    plans: dict[str, Plan] = field(default_factory=dict)
    total_api_calls: int = 0
    operations: list[dict] = field(default_factory=list)

    def record_entity(self, entity_type: str, identifier: str, data: dict) -> None:
        key = f"{entity_type}:{identifier}"
        self.entities[key] = data

    def get_entity(self, entity_type: str, identifier: str) -> dict | None:
        return self.entities.get(f"{entity_type}:{identifier}")

    def to_dict(self) -> dict:
        return {
            "entities_resolved": dict(self.entities),
            "plans_executed": [
                {"plan_id": p.plan_id, "workflow": p.workflow_name, "status": p.status.value}
                for p in self.plans.values()
            ],
            "total_api_calls": self.total_api_calls,
            "operations_performed": self.operations,
        }


# Module-level session (one per server instance / conversation).
_session = SessionContext()


def get_session() -> SessionContext:
    return _session


def reset_session() -> None:
    """Reset session state — used in tests."""
    global _session
    _session = SessionContext()


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$step(\d+)\.(.+)")
_BARE_STEP_PATTERN = re.compile(r"\$step(\d+)$")


def _resolve_value(value: Any, plan: Plan) -> Any:
    """Resolve $stepN.field or bare $stepN references in a value."""
    if isinstance(value, str):
        # First try $stepN.field
        m = _VAR_PATTERN.fullmatch(value)
        if m:
            step_num = int(m.group(1))
            field_path = m.group(2)
            return _extract_field(plan.results.get(step_num), field_path)
        # Then try bare $stepN (returns the entire step result)
        m2 = _BARE_STEP_PATTERN.fullmatch(value)
        if m2:
            step_num = int(m2.group(1))
            return plan.results.get(step_num)
        return value
    if isinstance(value, dict):
        return {k: _resolve_value(v, plan) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, plan) for v in value]
    return value


def _extract_field(data: Any, field_path: str) -> Any:
    """Walk a dotted field path into data. E.g. 'profile.email' on a user object."""
    if data is None:
        return None
    parts = field_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            # If accessing a field on a list, map across all items
            return [_extract_field(item, part) for item in current]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
    return current


def _mask_references(params: dict) -> dict:
    """Replace $step refs with human-readable placeholders for preview."""
    masked = {}
    for k, v in params.items():
        if isinstance(v, str) and v.startswith("$step"):
            masked[k] = f"(from {v})"
        else:
            masked[k] = v
    return masked


def _serialise(obj: Any) -> Any:
    """Best-effort serialisation of Okta SDK objects to dicts."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_serialise(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    # Okta SDK models usually have .as_dict() or __dict__
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if hasattr(obj, "__dict__"):
        return {k: _serialise(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------

async def execute_plan(plan: Plan, manager) -> Plan:
    """Execute all steps in a plan sequentially against the Okta API.

    Args:
        plan: The plan to execute.
        manager: OktaAuthManager instance from the MCP context.

    Returns:
        The plan with results populated.
    """
    import time

    plan.status = PlanStatus.EXECUTING
    session = get_session()
    session.plans[plan.plan_id] = plan
    has_failure = False

    client = await get_okta_client(manager)

    for step in plan.steps:
        if has_failure and step.is_destructive:
            # Don't execute destructive steps after a failure
            step.result = StepResult(
                step_number=step.number,
                action=step.action,
                status=StepStatus.SKIPPED,
                error="Skipped due to earlier failure",
            )
            logger.warning(f"Plan {plan.plan_id}: Skipping destructive step {step.number} due to earlier failure")
            continue

        # Resolve variable references
        resolved_params = _resolve_value(step.params, plan)

        # Handle for_each iteration
        if step.for_each:
            items = _resolve_value(step.for_each, plan)
            if isinstance(items, list):
                await _execute_for_each(step, items, resolved_params, client, plan, session)
                continue

        # Execute single step
        start = time.monotonic()
        try:
            result_data = await _execute_step(step.action, resolved_params, client)
            elapsed = (time.monotonic() - start) * 1000

            step.result = StepResult(
                step_number=step.number,
                action=step.action,
                status=StepStatus.SUCCESS,
                data=result_data,
                duration_ms=round(elapsed, 1),
            )
            plan.results[step.number] = result_data
            session.total_api_calls += 1

            logger.info(f"Plan {plan.plan_id}: Step {step.number} ({step.action}) completed in {elapsed:.1f}ms")

        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            has_failure = True
            step.result = StepResult(
                step_number=step.number,
                action=step.action,
                status=StepStatus.FAILED,
                error=str(exc),
                duration_ms=round(elapsed, 1),
            )
            logger.error(f"Plan {plan.plan_id}: Step {step.number} ({step.action}) failed: {exc}")

    # Set final plan status
    statuses = [s.result.status for s in plan.steps if s.result]
    if all(st == StepStatus.SUCCESS for st in statuses):
        plan.status = PlanStatus.COMPLETED
    elif all(st == StepStatus.FAILED for st in statuses):
        plan.status = PlanStatus.FAILED
    else:
        plan.status = PlanStatus.PARTIAL

    # Record in session
    session.operations.append({
        "plan_id": plan.plan_id,
        "workflow": plan.workflow_name,
        "status": plan.status.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return plan


async def _execute_for_each(
    step: Step,
    items: list,
    base_params: dict,
    client,
    plan: Plan,
    session: SessionContext,
) -> None:
    """Execute a step once per item in a list (e.g. remove user from each group)."""
    import time

    all_results = []
    all_errors = []
    total_start = time.monotonic()

    for item in items:
        # The item itself is injected as the iteration variable
        iteration_params = dict(base_params)
        # If the item is a dict-like, merge its fields; otherwise extract .id
        if isinstance(item, dict):
            iteration_params.update(item)
            # Also set group_id if the dict has 'id' (for group iteration)
            if "id" in item and "group_id" not in iteration_params:
                iteration_params["group_id"] = item["id"]
        elif hasattr(item, "id"):
            # Okta SDK objects — use .id as the iterated entity's ID
            iteration_params["group_id"] = item.id
            iteration_params["_item_id"] = item.id
        else:
            iteration_params["_item"] = item

        try:
            result = await _execute_step(step.action, iteration_params, client)
            all_results.append(result)
            session.total_api_calls += 1
        except Exception as exc:
            all_errors.append(str(exc))
            logger.warning(f"for_each step {step.number}: iteration failed: {exc}")

    elapsed = (time.monotonic() - total_start) * 1000

    if all_errors and not all_results:
        step.result = StepResult(
            step_number=step.number,
            action=step.action,
            status=StepStatus.FAILED,
            data=all_results,
            error=f"{len(all_errors)} iterations failed: {all_errors[0]}",
            duration_ms=round(elapsed, 1),
        )
    else:
        step.result = StepResult(
            step_number=step.number,
            action=step.action,
            status=StepStatus.SUCCESS,
            data=all_results,
            duration_ms=round(elapsed, 1),
        )
    plan.results[step.number] = all_results
    logger.info(
        f"for_each step {step.number}: {len(all_results)} succeeded, {len(all_errors)} failed in {elapsed:.1f}ms"
    )


# ---------------------------------------------------------------------------
# Action dispatcher — maps action names to Okta SDK calls
# ---------------------------------------------------------------------------

# This is the core mapping. Each action corresponds to a specific Okta SDK
# method.  The orchestrator calls these directly — it does NOT go through
# the MCP tool layer (no round-trips, no decorators, no elicitation).

async def _execute_step(action: str, params: dict, client) -> Any:
    """Dispatch an action to the appropriate Okta SDK method."""

    dispatcher = _get_dispatcher()
    if action not in dispatcher:
        raise ValueError(f"Unknown action: '{action}'. Available: {sorted(dispatcher.keys())}")

    handler = dispatcher[action]
    return await handler(params, client)


def _get_dispatcher() -> dict:
    """Return the action → handler mapping. Lazy-built on first call."""
    return {
        # ── Users ──
        "list_users": _action_list_users,
        "get_user": _action_get_user,
        "create_user": _action_create_user,
        "update_user": _action_update_user,
        "deactivate_user": _action_deactivate_user,
        "delete_deactivated_user": _action_delete_deactivated_user,
        "suspend_user": _action_suspend_user,
        "activate_user": _action_activate_user,
        "clear_user_sessions": _action_clear_user_sessions,
        "get_user_profile_attributes": _action_get_user_profile_attributes,

        # ── Groups ──
        "list_groups": _action_list_groups,
        "get_group": _action_get_group,
        "create_group": _action_create_group,
        "update_group": _action_update_group,
        "delete_group": _action_delete_group,
        "list_group_users": _action_list_group_users,
        "list_group_apps": _action_list_group_apps,
        "list_user_groups": _action_list_user_groups,
        "add_user_to_group": _action_add_user_to_group,
        "remove_user_from_group": _action_remove_user_from_group,

        # ── Applications ──
        "list_applications": _action_list_applications,
        "get_application": _action_get_application,
        "create_application": _action_create_application,
        "update_application": _action_update_application,
        "delete_application": _action_delete_application,
        "activate_application": _action_activate_application,
        "deactivate_application": _action_deactivate_application,
        "list_user_app_assignments": _action_list_user_app_assignments,

        # ── Policies ──
        "list_policies": _action_list_policies,
        "get_policy": _action_get_policy,
        "create_policy": _action_create_policy,
        "update_policy": _action_update_policy,
        "delete_policy": _action_delete_policy,
        "activate_policy": _action_activate_policy,
        "deactivate_policy": _action_deactivate_policy,

        # ── Policy Rules ──
        "list_policy_rules": _action_list_policy_rules,
        "get_policy_rule": _action_get_policy_rule,
        "create_policy_rule": _action_create_policy_rule,
        "update_policy_rule": _action_update_policy_rule,
        "delete_policy_rule": _action_delete_policy_rule,
        "activate_policy_rule": _action_activate_policy_rule,
        "deactivate_policy_rule": _action_deactivate_policy_rule,

        # ── Device Assurance ──
        "list_device_assurance_policies": _action_list_device_assurance_policies,
        "get_device_assurance_policy": _action_get_device_assurance_policy,
        "create_device_assurance_policy": _action_create_device_assurance_policy,
        "replace_device_assurance_policy": _action_replace_device_assurance_policy,
        "delete_device_assurance_policy": _action_delete_device_assurance_policy,

        # ── System Logs ──
        "get_logs": _action_get_logs,

        # ── Brands ──
        "list_brands": _action_list_brands,
        "get_brand": _action_get_brand,
        "create_brand": _action_create_brand,
        "replace_brand": _action_replace_brand,
        "delete_brand": _action_delete_brand,
        "list_brand_domains": _action_list_brand_domains,

        # ── Themes ──
        "list_brand_themes": _action_list_brand_themes,
        "get_brand_theme": _action_get_brand_theme,
        "replace_brand_theme": _action_replace_brand_theme,
    }


# ---------------------------------------------------------------------------
# Pagination helper for action handlers
# ---------------------------------------------------------------------------

async def _auto_paginate(items, response) -> list:
    """Auto-paginate through all pages of Okta SDK results.

    If the response indicates more pages, uses ``paginate_all_results``
    to fetch every page so the orchestrator always returns the full
    result set without artificial limits.
    """
    if not items:
        return []
    if response and hasattr(response, "has_next") and response.has_next():
        all_items, info = await paginate_all_results(response, items)
        logger.debug(
            f"Auto-paginated: {info['total_items']} items across "
            f"{info['pages_fetched']} pages"
        )
        return all_items
    return list(items)


# ---------------------------------------------------------------------------
# Action handlers — thin wrappers around Okta SDK
# ---------------------------------------------------------------------------

async def _action_list_users(params: dict, client) -> list:
    """Search/list users. Accepts 'search', 'filter', 'q', 'limit'."""
    query = {}
    if params.get("search"):
        query["search"] = params["search"]
    if params.get("filter"):
        query["filter"] = params["filter"]
    if params.get("q"):
        query["q"] = params["q"]
    if params.get("limit"):
        query["limit"] = int(params["limit"])

    users, resp, err = await client.list_users(**query)
    if err:
        raise RuntimeError(f"Okta API error listing users: {err}")
    return await _auto_paginate(users, resp)


async def _action_get_user(params: dict, client) -> Any:
    """Get a single user by ID, login, or display name.

    Tries a direct ``GET /users/{userId}`` first.  If the SDK returns ``None``
    (e.g. the identifier is a display name rather than an Okta ID or email),
    falls back to ``list_users?q=<identifier>`` and returns the first match.
    """
    user_id = params.get("user_id") or params.get("login")
    if not user_id:
        raise ValueError("get_user requires 'user_id' or 'login'")

    user, _, err = await client.get_user(user_id)

    # Direct lookup may silently return None when the identifier is a display
    # name or partial name that Okta doesn't recognise as an ID/login.
    if err or user is None:
        logger.debug(
            f"Direct lookup for '{user_id}' returned None/error — "
            "falling back to list_users search"
        )
        users, _, search_err = await client.list_users(q=user_id, limit=5)
        if search_err:
            raise RuntimeError(f"Okta API error finding user '{user_id}': {search_err}")
        if not users:
            raise RuntimeError(
                f"No user found matching '{user_id}'. "
                "Try providing the user's email or Okta user ID."
            )
        # If there are multiple matches, pick the one whose display name is
        # closest to the query (exact first-name + last-name match preferred).
        query_lower = user_id.strip().lower()
        for candidate in users:
            profile = getattr(candidate, "profile", None)
            if profile:
                full_name = (
                    f"{getattr(profile, 'firstName', '')} "
                    f"{getattr(profile, 'lastName', '')}".strip().lower()
                )
                if full_name == query_lower:
                    logger.info(f"Resolved '{user_id}' → user id={candidate.id}")
                    return candidate
        # No exact match — return the first result and log a warning
        logger.warning(
            f"No exact display-name match for '{user_id}'; "
            f"using first search result (id={users[0].id})"
        )
        return users[0]

    return user


async def _action_deactivate_user(params: dict, client) -> str:
    """Deactivate a user by ID. No elicitation — orchestrator handles approval."""
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("deactivate_user requires 'user_id'")

    result = await client.deactivate_user(user_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deactivating user {user_id}: {err}")
    return f"User {user_id} deactivated successfully"


async def _action_list_user_groups(params: dict, client) -> list:
    """List all groups a user belongs to."""
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("list_user_groups requires 'user_id'")

    groups, resp, err = await client.list_user_groups(user_id)
    if err:
        raise RuntimeError(f"Okta API error listing groups for user {user_id}: {err}")
    return await _auto_paginate(groups, resp)


async def _action_remove_user_from_group(params: dict, client) -> str:
    """Remove a user from a group."""
    group_id = params.get("group_id")
    user_id = params.get("user_id")
    if not group_id or not user_id:
        raise ValueError("remove_user_from_group requires 'group_id' and 'user_id'")

    result = await client.unassign_user_from_group(group_id, user_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error removing user {user_id} from group {group_id}: {err}")
    return f"User {user_id} removed from group {group_id}"


async def _action_list_user_app_assignments(params: dict, client) -> list:
    """List all application assignments for a user."""
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("list_user_app_assignments requires 'user_id'")

    apps, resp, err = await client.list_app_links(user_id)
    if err:
        raise RuntimeError(f"Okta API error listing app assignments for user {user_id}: {err}")
    return await _auto_paginate(apps, resp)


async def _action_suspend_user(params: dict, client) -> str:
    """Suspend a user by ID. The user can be unsuspended later."""
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("suspend_user requires 'user_id'")

    result = await client.suspend_user(user_id)
    err = result[-1] if isinstance(result, tuple) else None
    if err:
        raise RuntimeError(f"Okta API error suspending user {user_id}: {err}")
    return f"User {user_id} suspended successfully"


async def _action_activate_user(params: dict, client) -> Any:
    """Activate a user account. Optionally send an activation email.

    Params:
        user_id (str): Okta user ID.
        send_email (bool): Whether to send an activation email (default True).
    """
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("activate_user requires 'user_id'")

    send_email = params.get("send_email", True)
    if isinstance(send_email, str):
        send_email = send_email.lower() not in ("false", "0", "no")

    token, _, err = await client.activate_user(user_id, send_email=send_email)
    if err:
        raise RuntimeError(f"Okta API error activating user {user_id}: {err}")
    return {
        "status": "activated",
        "user_id": user_id,
        "activation_token": getattr(token, "activationToken", None) if token else None,
    }


async def _action_clear_user_sessions(params: dict, client) -> str:
    """Revoke all active sessions for a user.

    Params:
        user_id (str): Okta user ID.
        keep_current (bool): Whether to keep the current session (default False).
    """
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("clear_user_sessions requires 'user_id'")

    await client.revoke_user_sessions(user_id, oauth_tokens=True)
    return f"All active sessions revoked for user {user_id}"


async def _action_add_user_to_group(params: dict, client) -> str:
    """Add a user to a group.

    Params:
        user_id (str): Okta user ID.
        group_id (str): Okta group ID.
    """
    group_id = params.get("group_id")
    user_id = params.get("user_id")
    if not group_id or not user_id:
        raise ValueError("add_user_to_group requires 'group_id' and 'user_id'")

    result = await client.assign_user_to_group(group_id, user_id)
    err = result[-1] if isinstance(result, tuple) else None
    if err:
        raise RuntimeError(f"Okta API error adding user {user_id} to group {group_id}: {err}")
    return f"User {user_id} added to group {group_id}"


async def _action_get_group(params: dict, client) -> Any:
    """Get a group by ID or name.

    Params:
        group_id (str): Okta group ID (preferred).
        name (str): Group name (falls back to search if group_id not provided).
    """
    group_id = params.get("group_id")
    if group_id:
        group, _, err = await client.get_group(group_id)
        if err:
            raise RuntimeError(f"Okta API error fetching group {group_id}: {err}")
        return group

    name = params.get("name")
    if not name:
        raise ValueError("get_group requires 'group_id' or 'name'")

    groups, _, err = await client.list_groups(q=name)
    if err:
        raise RuntimeError(f"Okta API error searching for group '{name}': {err}")
    if not groups:
        raise RuntimeError(f"No group found matching '{name}'")
    return groups[0]


# ---------------------------------------------------------------------------
# Additional User action handlers
# ---------------------------------------------------------------------------

async def _action_create_user(params: dict, client) -> Any:
    """Create a new user with the given profile."""
    from okta.models.create_user_request import CreateUserRequest

    profile = params.get("profile")

    # If profile is not a dict, assemble it from individual top-level fields
    if not isinstance(profile, dict):
        profile_fields = ("firstName", "lastName", "email", "login")
        assembled = {k: params[k] for k in profile_fields if k in params}
        if assembled:
            profile = assembled
        elif isinstance(profile, str) and "@" in profile:
            # Derive a minimal profile from an email-like identifier
            local_part = profile.split("@")[0]
            parts = local_part.split(".")
            profile = {
                "login": profile,
                "email": profile,
                "firstName": parts[0].capitalize() if parts else local_part.capitalize(),
                "lastName": parts[1].capitalize() if len(parts) > 1 else "",
            }
        elif not profile:
            raise ValueError("create_user requires 'profile'")

    user_data = CreateUserRequest.from_dict({"profile": profile})
    user, _, err = await client.create_user(user_data)
    if err:
        raise RuntimeError(f"Okta API error creating user: {err}")
    return user


async def _action_update_user(params: dict, client) -> Any:
    """Update an existing user's profile."""
    from okta.models.update_user_request import UpdateUserRequest

    user_id = params.get("user_id")
    profile = params.get("profile")
    if not user_id:
        raise ValueError("update_user requires 'user_id'")
    if not profile:
        raise ValueError("update_user requires 'profile'")

    user_data = UpdateUserRequest.from_dict({"profile": profile})
    user, _, err = await client.update_user(user_id, user_data)
    if err:
        raise RuntimeError(f"Okta API error updating user {user_id}: {err}")
    return user


async def _action_delete_deactivated_user(params: dict, client) -> str:
    """Permanently delete a deactivated user."""
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("delete_deactivated_user requires 'user_id'")

    result = await client.delete_user(user_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting user {user_id}: {err}")
    return f"User {user_id} deleted successfully"


async def _action_get_user_profile_attributes(params: dict, client) -> dict:
    """List all user profile attributes supported by the Okta org."""
    users, _, err = await client.list_users(limit=1)
    if err:
        raise RuntimeError(f"Okta API error fetching profile attributes: {err}")
    if users and len(users) > 0:
        return vars(users[0].profile)
    return {}


# ---------------------------------------------------------------------------
# Additional Group action handlers
# ---------------------------------------------------------------------------

async def _action_list_groups(params: dict, client) -> list:
    """Search/list groups. Accepts 'search', 'filter', 'q', 'limit'."""
    query = {}
    if params.get("search"):
        query["search"] = params["search"]
    if params.get("filter"):
        query["filter"] = params["filter"]
    if params.get("q"):
        query["q"] = params["q"]
    if params.get("limit"):
        query["limit"] = int(params["limit"])

    groups, resp, err = await client.list_groups(**query)
    if err:
        raise RuntimeError(f"Okta API error listing groups: {err}")
    return await _auto_paginate(groups, resp)


async def _action_create_group(params: dict, client) -> Any:
    """Create a new group with the given profile."""
    profile = params.get("profile")
    if not profile:
        raise ValueError("create_group requires 'profile'")

    group, _, err = await client.add_group({"profile": profile})
    if err:
        raise RuntimeError(f"Okta API error creating group: {err}")
    return group


async def _action_update_group(params: dict, client) -> Any:
    """Update a group by ID with a new profile."""
    group_id = params.get("group_id")
    profile = params.get("profile")
    if not group_id:
        raise ValueError("update_group requires 'group_id'")
    if not profile:
        raise ValueError("update_group requires 'profile'")

    group, _, err = await client.replace_group(group_id, {"profile": profile})
    if err:
        raise RuntimeError(f"Okta API error updating group {group_id}: {err}")
    return group


async def _action_delete_group(params: dict, client) -> str:
    """Delete a group by ID."""
    group_id = params.get("group_id")
    if not group_id:
        raise ValueError("delete_group requires 'group_id'")

    result = await client.delete_group(group_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting group {group_id}: {err}")
    return f"Group {group_id} deleted successfully"


async def _action_list_group_users(params: dict, client) -> list:
    """List all users in a group."""
    group_id = params.get("group_id")
    if not group_id:
        raise ValueError("list_group_users requires 'group_id'")

    users, resp, err = await client.list_group_users(group_id)
    if err:
        raise RuntimeError(f"Okta API error listing users for group {group_id}: {err}")
    return await _auto_paginate(users, resp)


async def _action_list_group_apps(params: dict, client) -> list:
    """List all applications assigned to a group."""
    group_id = params.get("group_id")
    if not group_id:
        raise ValueError("list_group_apps requires 'group_id'")

    apps, resp, err = await client.list_assigned_applications_for_group(group_id)
    if err:
        raise RuntimeError(f"Okta API error listing apps for group {group_id}: {err}")
    return await _auto_paginate(apps, resp)


# ---------------------------------------------------------------------------
# Application action handlers
# ---------------------------------------------------------------------------

async def _action_list_applications(params: dict, client) -> list:
    """List applications. Accepts 'q', 'filter', 'limit', 'after', 'expand'."""
    # Bypass SDK pydantic deserialization — some JWK credential models in the SDK
    # declare fields as required StrictStr but the API can return None for them,
    # causing validation errors.  Using raw HTTP avoids this SDK bug.
    method, url, header_params, body, _post_params = (
        client._list_applications_serialize(
            q=params.get("q"),
            after=params.get("after"),
            use_optimization=None,
            always_include_vpn_settings=None,
            limit=int(params["limit"]) if params.get("limit") else None,
            filter=params.get("filter"),
            expand=params.get("expand"),
            include_non_deleted=None,
            _request_auth=None,
            _content_type=None,
            _headers=None,
            _host_index=0,
        )
    )
    request, err = await client._request_executor.create_request(
        method, url, body, header_params, {}, keep_empty_params=False
    )
    if err:
        raise RuntimeError(f"Failed to create list_applications request: {err}")
    response, response_body, err = await client._request_executor.execute(request)
    if err:
        raise RuntimeError(f"Okta API error listing applications: {err}")
    if not response_body:
        return []
    apps = json.loads(response_body) if isinstance(response_body, str) else response_body
    return apps if isinstance(apps, list) else []


async def _action_get_application(params: dict, client) -> Any:
    """Get an application by ID."""
    app_id = params.get("app_id")
    if not app_id:
        raise ValueError("get_application requires 'app_id'")

    query = {}
    if params.get("expand"):
        query["expand"] = params["expand"]

    app, _, err = await client.get_application(app_id, **query)
    if err:
        raise RuntimeError(f"Okta API error getting application {app_id}: {err}")
    return app


async def _action_create_application(params: dict, client) -> Any:
    """Create a new application."""
    import okta.models as okta_models

    app_config = params.get("app_config")
    if not app_config:
        raise ValueError("create_application requires 'app_config'")

    activate = params.get("activate", True)
    sign_on_mode = app_config.get("signOnMode") or app_config.get("sign_on_mode", "")
    mode_map = {
        "BOOKMARK": okta_models.BookmarkApplication,
        "AUTO_LOGIN": okta_models.AutoLoginApplication,
        "BASIC_AUTH": okta_models.BasicAuthApplication,
        "BROWSER_PLUGIN": okta_models.BrowserPluginApplication,
        "OPENID_CONNECT": okta_models.OpenIdConnectApplication,
        "SAML_1_1": okta_models.Saml11Application,
        "SAML_2_0": okta_models.SamlApplication,
        "SECURE_PASSWORD_STORE": okta_models.SecurePasswordStoreApplication,
        "WS_FEDERATION": okta_models.WsFederationApplication,
    }
    model_cls = mode_map.get(str(sign_on_mode).upper(), okta_models.Application)
    app_model = model_cls(**app_config)

    app, _, err = await client.create_application(app_model, activate)
    if err:
        raise RuntimeError(f"Okta API error creating application: {err}")
    return app


async def _action_update_application(params: dict, client) -> Any:
    """Update an application by ID."""
    import okta.models as okta_models

    app_id = params.get("app_id")
    app_config = params.get("app_config")
    if not app_id:
        raise ValueError("update_application requires 'app_id'")
    if not app_config:
        raise ValueError("update_application requires 'app_config'")

    sign_on_mode = app_config.get("signOnMode") or app_config.get("sign_on_mode", "")
    mode_map = {
        "BOOKMARK": okta_models.BookmarkApplication,
        "AUTO_LOGIN": okta_models.AutoLoginApplication,
        "BASIC_AUTH": okta_models.BasicAuthApplication,
        "BROWSER_PLUGIN": okta_models.BrowserPluginApplication,
        "OPENID_CONNECT": okta_models.OpenIdConnectApplication,
        "SAML_1_1": okta_models.Saml11Application,
        "SAML_2_0": okta_models.SamlApplication,
        "SECURE_PASSWORD_STORE": okta_models.SecurePasswordStoreApplication,
        "WS_FEDERATION": okta_models.WsFederationApplication,
    }
    model_cls = mode_map.get(str(sign_on_mode).upper(), okta_models.Application)
    app_model = model_cls(**app_config)

    app, _, err = await client.replace_application(app_id, app_model)
    if err:
        raise RuntimeError(f"Okta API error updating application {app_id}: {err}")
    return app


async def _action_delete_application(params: dict, client) -> str:
    """Delete an application by ID."""
    app_id = params.get("app_id")
    if not app_id:
        raise ValueError("delete_application requires 'app_id'")

    result = await client.delete_application(app_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting application {app_id}: {err}")
    return f"Application {app_id} deleted successfully"


async def _action_activate_application(params: dict, client) -> str:
    """Activate an application."""
    app_id = params.get("app_id")
    if not app_id:
        raise ValueError("activate_application requires 'app_id'")

    result = await client.activate_application(app_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error activating application {app_id}: {err}")
    return f"Application {app_id} activated successfully"


async def _action_deactivate_application(params: dict, client) -> str:
    """Deactivate an application."""
    app_id = params.get("app_id")
    if not app_id:
        raise ValueError("deactivate_application requires 'app_id'")

    result = await client.deactivate_application(app_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deactivating application {app_id}: {err}")
    return f"Application {app_id} deactivated successfully"


# ---------------------------------------------------------------------------
# Policy action handlers
# ---------------------------------------------------------------------------

async def _action_list_policies(params: dict, client) -> list:
    """List policies by type."""
    policy_type = params.get("type")
    if not policy_type:
        raise ValueError("list_policies requires 'type'")

    query = {"type": policy_type}
    if params.get("status"):
        query["status"] = params["status"]
    if params.get("q"):
        query["q"] = params["q"]
    if params.get("limit"):
        query["limit"] = str(int(params["limit"]))

    policies, resp, err = await client.list_policies(**query)
    if err:
        raise RuntimeError(f"Okta API error listing policies: {err}")
    return await _auto_paginate(policies, resp)


async def _action_get_policy(params: dict, client) -> Any:
    """Retrieve a specific policy by ID."""
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("get_policy requires 'policy_id'")

    policy, _, err = await client.get_policy(policy_id)
    if err:
        raise RuntimeError(f"Okta API error getting policy {policy_id}: {err}")
    return policy


async def _action_create_policy(params: dict, client) -> Any:
    """Create a new policy."""
    policy_data = params.get("policy_data")
    if not policy_data:
        raise ValueError("create_policy requires 'policy_data'")

    policy, _, err = await client.create_policy(policy_data)
    if err:
        raise RuntimeError(f"Okta API error creating policy: {err}")
    return policy


async def _action_update_policy(params: dict, client) -> Any:
    """Update an existing policy."""
    policy_id = params.get("policy_id")
    policy_data = params.get("policy_data")
    if not policy_id:
        raise ValueError("update_policy requires 'policy_id'")
    if not policy_data:
        raise ValueError("update_policy requires 'policy_data'")

    policy, _, err = await client.replace_policy(policy_id, policy_data)
    if err:
        raise RuntimeError(f"Okta API error updating policy {policy_id}: {err}")
    return policy


async def _action_delete_policy(params: dict, client) -> str:
    """Delete a policy."""
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("delete_policy requires 'policy_id'")

    result = await client.delete_policy(policy_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting policy {policy_id}: {err}")
    return f"Policy {policy_id} deleted successfully"


async def _action_activate_policy(params: dict, client) -> str:
    """Activate a policy."""
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("activate_policy requires 'policy_id'")

    result = await client.activate_policy(policy_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error activating policy {policy_id}: {err}")
    return f"Policy {policy_id} activated successfully"


async def _action_deactivate_policy(params: dict, client) -> str:
    """Deactivate a policy."""
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("deactivate_policy requires 'policy_id'")

    result = await client.deactivate_policy(policy_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deactivating policy {policy_id}: {err}")
    return f"Policy {policy_id} deactivated successfully"


# ---------------------------------------------------------------------------
# Policy Rule action handlers
# ---------------------------------------------------------------------------

async def _action_list_policy_rules(params: dict, client) -> list:
    """List all rules for a policy."""
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("list_policy_rules requires 'policy_id'")

    rules, resp, err = await client.list_policy_rules(policy_id)
    if err:
        raise RuntimeError(f"Okta API error listing rules for policy {policy_id}: {err}")
    return await _auto_paginate(rules, resp)


async def _action_get_policy_rule(params: dict, client) -> Any:
    """Get a specific policy rule."""
    policy_id = params.get("policy_id")
    rule_id = params.get("rule_id")
    if not policy_id:
        raise ValueError("get_policy_rule requires 'policy_id'")
    if not rule_id:
        raise ValueError("get_policy_rule requires 'rule_id'")

    rule, _, err = await client.get_policy_rule(policy_id, rule_id)
    if err:
        raise RuntimeError(f"Okta API error getting rule {rule_id}: {err}")
    return rule


async def _action_create_policy_rule(params: dict, client) -> Any:
    """Create a new rule for a policy."""
    from okta.models.policy_rule import PolicyRule

    policy_id = params.get("policy_id")
    rule_data = params.get("rule_data")
    if not policy_id:
        raise ValueError("create_policy_rule requires 'policy_id'")
    if not rule_data:
        raise ValueError("create_policy_rule requires 'rule_data'")

    policy_rule = PolicyRule.from_dict(rule_data)
    rule, _, err = await client.create_policy_rule(policy_id, policy_rule)
    if err:
        raise RuntimeError(f"Okta API error creating rule for policy {policy_id}: {err}")
    return rule


async def _action_update_policy_rule(params: dict, client) -> Any:
    """Update an existing policy rule."""
    from okta.models.policy_rule import PolicyRule

    policy_id = params.get("policy_id")
    rule_id = params.get("rule_id")
    rule_data = params.get("rule_data")
    if not policy_id:
        raise ValueError("update_policy_rule requires 'policy_id'")
    if not rule_id:
        raise ValueError("update_policy_rule requires 'rule_id'")
    if not rule_data:
        raise ValueError("update_policy_rule requires 'rule_data'")

    policy_rule = PolicyRule.from_dict(rule_data)
    rule, _, err = await client.replace_policy_rule(policy_id, rule_id, policy_rule)
    if err:
        raise RuntimeError(f"Okta API error updating rule {rule_id}: {err}")
    return rule


async def _action_delete_policy_rule(params: dict, client) -> str:
    """Delete a policy rule."""
    policy_id = params.get("policy_id")
    rule_id = params.get("rule_id")
    if not policy_id:
        raise ValueError("delete_policy_rule requires 'policy_id'")
    if not rule_id:
        raise ValueError("delete_policy_rule requires 'rule_id'")

    result = await client.delete_policy_rule(policy_id, rule_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting rule {rule_id}: {err}")
    return f"Rule {rule_id} deleted successfully"


async def _action_activate_policy_rule(params: dict, client) -> str:
    """Activate a policy rule."""
    policy_id = params.get("policy_id")
    rule_id = params.get("rule_id")
    if not policy_id:
        raise ValueError("activate_policy_rule requires 'policy_id'")
    if not rule_id:
        raise ValueError("activate_policy_rule requires 'rule_id'")

    result = await client.activate_policy_rule(policy_id, rule_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error activating rule {rule_id}: {err}")
    return f"Rule {rule_id} activated successfully"


async def _action_deactivate_policy_rule(params: dict, client) -> str:
    """Deactivate a policy rule."""
    policy_id = params.get("policy_id")
    rule_id = params.get("rule_id")
    if not policy_id:
        raise ValueError("deactivate_policy_rule requires 'policy_id'")
    if not rule_id:
        raise ValueError("deactivate_policy_rule requires 'rule_id'")

    result = await client.deactivate_policy_rule(policy_id, rule_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deactivating rule {rule_id}: {err}")
    return f"Rule {rule_id} deactivated successfully"


# ---------------------------------------------------------------------------
# Device Assurance action handlers
# ---------------------------------------------------------------------------

async def _action_list_device_assurance_policies(params: dict, client) -> list:
    """List all device assurance policies."""
    policies, resp, err = await client.list_device_assurance_policies()
    if err:
        raise RuntimeError(f"Okta API error listing device assurance policies: {err}")
    return await _auto_paginate(policies, resp)


async def _action_get_device_assurance_policy(params: dict, client) -> Any:
    """Get a device assurance policy by ID."""
    device_assurance_id = params.get("device_assurance_id")
    if not device_assurance_id:
        raise ValueError("get_device_assurance_policy requires 'device_assurance_id'")

    policy, _, err = await client.get_device_assurance_policy(device_assurance_id)
    if err:
        raise RuntimeError(f"Okta API error getting device assurance policy {device_assurance_id}: {err}")
    return policy


async def _action_create_device_assurance_policy(params: dict, client) -> Any:
    """Create a new device assurance policy."""
    from okta.models.device_assurance import DeviceAssurance

    policy_data = params.get("policy_data")
    if not policy_data:
        raise ValueError("create_device_assurance_policy requires 'policy_data'")

    policy_model = DeviceAssurance.from_dict(policy_data)
    policy, _, err = await client.create_device_assurance_policy(policy_model)
    if err:
        raise RuntimeError(f"Okta API error creating device assurance policy: {err}")
    return policy


async def _action_replace_device_assurance_policy(params: dict, client) -> Any:
    """Replace an existing device assurance policy."""
    from okta.models.device_assurance import DeviceAssurance

    device_assurance_id = params.get("device_assurance_id")
    policy_data = params.get("policy_data")
    if not device_assurance_id:
        raise ValueError("replace_device_assurance_policy requires 'device_assurance_id'")
    if not policy_data:
        raise ValueError("replace_device_assurance_policy requires 'policy_data'")

    policy_model = DeviceAssurance.from_dict(policy_data)
    policy, _, err = await client.replace_device_assurance_policy(device_assurance_id, policy_model)
    if err:
        raise RuntimeError(f"Okta API error replacing device assurance policy {device_assurance_id}: {err}")
    return policy


async def _action_delete_device_assurance_policy(params: dict, client) -> str:
    """Delete a device assurance policy."""
    device_assurance_id = params.get("device_assurance_id")
    if not device_assurance_id:
        raise ValueError("delete_device_assurance_policy requires 'device_assurance_id'")

    result = await client.delete_device_assurance_policy(device_assurance_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting device assurance policy {device_assurance_id}: {err}")
    return f"Device assurance policy {device_assurance_id} deleted successfully"


# ---------------------------------------------------------------------------
# System Logs action handler
# ---------------------------------------------------------------------------

async def _action_get_logs(params: dict, client) -> list:
    """Retrieve system logs. Accepts 'since', 'until', 'filter', 'q', 'limit'."""
    query = {}
    for key in ("since", "until", "filter", "q", "after"):
        if params.get(key):
            query[key] = params[key]
    if params.get("limit"):
        query["limit"] = int(params["limit"])

    logs, resp, err = await client.list_log_events(**query)
    if err:
        raise RuntimeError(f"Okta API error retrieving system logs: {err}")
    return await _auto_paginate(logs, resp)


# ---------------------------------------------------------------------------
# Brand action handlers
# ---------------------------------------------------------------------------

async def _action_list_brands(params: dict, client) -> Any:
    """List brands. When a name query is given and matches exactly one brand,
    returns that brand object directly so downstream steps can reference its ID.
    """
    query = {}
    name = params.get("name") or params.get("q")
    if name:
        query["q"] = name
    if params.get("limit"):
        query["limit"] = int(params["limit"])

    brands, resp, err = await client.list_brands(**query)
    if err:
        raise RuntimeError(f"Okta API error listing brands: {err}")
    brands = await _auto_paginate(brands, resp)

    if name:
        # Prefer exact case-insensitive name match
        exact = [b for b in brands if getattr(b, "name", "").lower() == name.lower()]
        if exact:
            return exact[0]
        if len(brands) == 1:
            return brands[0]

    return brands


async def _action_get_brand(params: dict, client) -> Any:
    """Get a brand by ID."""
    brand_id = params.get("brand_id")
    if not brand_id:
        raise ValueError("get_brand requires 'brand_id'")

    brand, _, err = await client.get_brand(brand_id)
    if err:
        raise RuntimeError(f"Okta API error getting brand {brand_id}: {err}")
    return brand


async def _action_create_brand(params: dict, client) -> Any:
    """Create a new brand with the given name."""
    from okta.models.create_brand_request import CreateBrandRequest

    name = params.get("name")
    if not name:
        raise ValueError("create_brand requires 'name'")

    create_request = CreateBrandRequest(name=name)
    brand, _, err = await client.create_brand(create_request)
    if err:
        raise RuntimeError(f"Okta API error creating brand '{name}': {err}")
    return brand


async def _action_replace_brand(params: dict, client) -> Any:
    """Replace (update) a brand by ID."""
    from okta.models.brand_request import BrandRequest

    brand_id = params.get("brand_id")
    if not brand_id:
        raise ValueError("replace_brand requires 'brand_id'")

    brand_data = params.get("brand_data") or {}
    name = brand_data.get("name") or params.get("name")
    if not name:
        raise ValueError("replace_brand requires 'name'")

    brand_request = BrandRequest(name=name)
    brand, _, err = await client.replace_brand(brand_id, brand_request)
    if err:
        raise RuntimeError(f"Okta API error replacing brand {brand_id}: {err}")
    return brand


async def _action_delete_brand(params: dict, client) -> str:
    """Delete a brand by ID."""
    brand_id = params.get("brand_id")
    if not brand_id:
        raise ValueError("delete_brand requires 'brand_id'")

    result = await client.delete_brand(brand_id)
    err = result[-1]
    if err:
        raise RuntimeError(f"Okta API error deleting brand {brand_id}: {err}")
    return f"Brand {brand_id} deleted successfully"


async def _action_list_brand_domains(params: dict, client) -> list:
    """List all custom domains associated with a brand."""
    brand_id = params.get("brand_id")
    if not brand_id:
        raise ValueError("list_brand_domains requires 'brand_id'")

    domains, resp, err = await client.list_brand_domains(brand_id)
    if err:
        raise RuntimeError(f"Okta API error listing domains for brand {brand_id}: {err}")
    return await _auto_paginate(domains, resp)


# ---------------------------------------------------------------------------
# Theme action handlers
# ---------------------------------------------------------------------------

async def _action_list_brand_themes(params: dict, client) -> Any:
    """List themes for a brand. Since each brand has exactly one theme,
    returns the single theme object directly so its ID can be referenced.
    """
    brand_id = params.get("brand_id")
    if not brand_id:
        raise ValueError("list_brand_themes requires 'brand_id'")

    themes, resp, err = await client.list_brand_themes(brand_id)
    if err:
        raise RuntimeError(f"Okta API error listing themes for brand {brand_id}: {err}")
    themes = await _auto_paginate(themes, resp)

    # Each org has exactly one theme per brand — return it directly
    if len(themes) == 1:
        return themes[0]
    return themes


async def _action_get_brand_theme(params: dict, client) -> Any:
    """Get a specific theme by brand ID and theme ID."""
    brand_id = params.get("brand_id")
    theme_id = params.get("theme_id")
    if not brand_id:
        raise ValueError("get_brand_theme requires 'brand_id'")
    if not theme_id:
        raise ValueError("get_brand_theme requires 'theme_id'")

    theme, _, err = await client.get_brand_theme(brand_id, theme_id)
    if err:
        raise RuntimeError(f"Okta API error getting theme {theme_id} for brand {brand_id}: {err}")
    return theme


async def _action_replace_brand_theme(params: dict, client) -> Any:
    """Replace a theme's colours and touchpoint variants.

    Accepts a 'theme_data' dict and/or individual colour/variant fields.
    Missing required fields are auto-filled from the current theme so that
    callers only need to specify the fields they want to change.
    """
    from okta.models.update_theme_request import UpdateThemeRequest
    from okta.models.sign_in_page_touch_point_variant import SignInPageTouchPointVariant
    from okta.models.end_user_dashboard_touch_point_variant import EndUserDashboardTouchPointVariant
    from okta.models.error_page_touch_point_variant import ErrorPageTouchPointVariant
    from okta.models.email_template_touch_point_variant import EmailTemplateTouchPointVariant
    from okta.models.loading_page_touch_point_variant import LoadingPageTouchPointVariant

    brand_id = params.get("brand_id")
    theme_id = params.get("theme_id")
    if not brand_id:
        raise ValueError("replace_brand_theme requires 'brand_id'")
    if not theme_id:
        raise ValueError("replace_brand_theme requires 'theme_id'")

    # Merge theme_data dict with individual top-level params
    merged: dict = dict(params.get("theme_data") or {})
    for key in (
        "primaryColorHex", "primary_color_hex",
        "secondaryColorHex", "secondary_color_hex",
        "primaryColorContrastHex", "primary_color_contrast_hex",
        "secondaryColorContrastHex", "secondary_color_contrast_hex",
        "signInPageTouchPointVariant", "sign_in_page_touch_point_variant",
        "endUserDashboardTouchPointVariant", "end_user_dashboard_touch_point_variant",
        "errorPageTouchPointVariant", "error_page_touch_point_variant",
        "emailTemplateTouchPointVariant", "email_template_touch_point_variant",
        "loadingPageTouchPointVariant", "loading_page_touch_point_variant",
    ):
        if params.get(key) is not None:
            merged[key] = params[key]

    def _get(*keys):
        for k in keys:
            v = merged.get(k)
            if v is not None:
                return v
        return None

    primary = _get("primary_color_hex", "primaryColorHex")
    secondary = _get("secondary_color_hex", "secondaryColorHex")
    sign_in = _get("sign_in_page_touch_point_variant", "signInPageTouchPointVariant")
    dashboard = _get("end_user_dashboard_touch_point_variant", "endUserDashboardTouchPointVariant")
    error_page = _get("error_page_touch_point_variant", "errorPageTouchPointVariant")
    email = _get("email_template_touch_point_variant", "emailTemplateTouchPointVariant")
    loading = _get("loading_page_touch_point_variant", "loadingPageTouchPointVariant")
    primary_contrast = _get("primary_color_contrast_hex", "primaryColorContrastHex")
    secondary_contrast = _get("secondary_color_contrast_hex", "secondaryColorContrastHex")

    # Fetch current theme to fill in any missing required fields
    needs_current = not all([primary, secondary, sign_in, dashboard, error_page, email])
    current_theme = None
    if needs_current:
        current_theme, _, err = await client.get_brand_theme(brand_id, theme_id)
        if err:
            raise RuntimeError(f"Okta API error fetching current theme {theme_id}: {err}")

    def _from_current(camel_attr, snake_attr, default=None):
        if current_theme:
            val = getattr(current_theme, camel_attr, None) or getattr(current_theme, snake_attr, None)
            if val is not None:
                return val.value if hasattr(val, "value") else val
        return default

    if not primary:
        primary = _from_current("primaryColorHex", "primary_color_hex", "#1662dd")
    if not secondary:
        secondary = _from_current("secondaryColorHex", "secondary_color_hex", "#ebebed")
    if not sign_in:
        sign_in = _from_current("signInPageTouchPointVariant", "sign_in_page_touch_point_variant", "OKTA_DEFAULT")
    if not dashboard:
        dashboard = _from_current("endUserDashboardTouchPointVariant", "end_user_dashboard_touch_point_variant", "OKTA_DEFAULT")
    if not error_page:
        error_page = _from_current("errorPageTouchPointVariant", "error_page_touch_point_variant", "OKTA_DEFAULT")
    if not email:
        email = _from_current("emailTemplateTouchPointVariant", "email_template_touch_point_variant", "OKTA_DEFAULT")

    request_data = {
        "primary_color_hex": primary,
        "secondary_color_hex": secondary,
        "sign_in_page_touch_point_variant": SignInPageTouchPointVariant(str(sign_in).upper()),
        "end_user_dashboard_touch_point_variant": EndUserDashboardTouchPointVariant(str(dashboard).upper()),
        "error_page_touch_point_variant": ErrorPageTouchPointVariant(str(error_page).upper()),
        "email_template_touch_point_variant": EmailTemplateTouchPointVariant(str(email).upper()),
    }
    if primary_contrast:
        request_data["primary_color_contrast_hex"] = primary_contrast
    if secondary_contrast:
        request_data["secondary_color_contrast_hex"] = secondary_contrast
    if loading:
        request_data["loading_page_touch_point_variant"] = LoadingPageTouchPointVariant(str(loading).upper())

    theme_request = UpdateThemeRequest(**request_data)
    theme, _, err = await client.replace_brand_theme(brand_id, theme_id, theme_request)
    if err:
        raise RuntimeError(f"Okta API error replacing theme {theme_id}: {err}")
    return theme


# ---------------------------------------------------------------------------
# Plan builder helper
# ---------------------------------------------------------------------------

def create_plan(workflow_name: str, description: str, steps: list[Step]) -> Plan:
    """Create a new plan and register it in the session."""
    plan = Plan(
        plan_id=f"plan_{uuid.uuid4().hex[:8]}",
        workflow_name=workflow_name,
        description=description,
        steps=steps,
    )
    session = get_session()
    session.plans[plan.plan_id] = plan
    return plan
