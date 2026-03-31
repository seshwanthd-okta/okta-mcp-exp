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

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from loguru import logger

from okta_mcp_server.utils.client import get_okta_client


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
        "deactivate_user": _action_deactivate_user,

        # ── Groups ──
        "list_user_groups": _action_list_user_groups,
        "remove_user_from_group": _action_remove_user_from_group,

        # ── Applications ──
        "list_user_app_assignments": _action_list_user_app_assignments,
    }


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
        query["limit"] = params["limit"]

    users, _, err = await client.list_users(**query)
    if err:
        raise RuntimeError(f"Okta API error listing users: {err}")
    return users or []


async def _action_get_user(params: dict, client) -> Any:
    """Get a single user by ID or login."""
    user_id = params.get("user_id") or params.get("login")
    if not user_id:
        raise ValueError("get_user requires 'user_id' or 'login'")

    user, _, err = await client.get_user(user_id)
    if err:
        raise RuntimeError(f"Okta API error getting user {user_id}: {err}")
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

    groups, _, err = await client.list_user_groups(user_id)
    if err:
        raise RuntimeError(f"Okta API error listing groups for user {user_id}: {err}")
    return groups or []


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

    apps, _, err = await client.list_app_links(user_id)
    if err:
        raise RuntimeError(f"Okta API error listing app assignments for user {user_id}: {err}")
    return apps or []


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
