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

import inspect
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
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
    global _session, _DISPATCHER
    _session = SessionContext()
    _DISPATCHER = None


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$step(\d+)\.(.+)")
_BARE_STEP_PATTERN = re.compile(r"\$step(\d+)$")
_INLINE_VAR_PATTERN = re.compile(r"\$step(\d+)\.([a-zA-Z_][a-zA-Z0-9_.]*)")


def _resolve_value(value: Any, plan: Plan) -> Any:
    """Resolve $stepN.field references in a value.

    Supports three modes:
      1. Exact match:  "$step1.id"           → returns the raw value (object, list, etc.)
      2. Bare step:    "$step1"              → returns entire step result
      3. Inline/template: "target.id eq \"$step1.id\""  → string interpolation
         Multiple refs in one string are supported.
    """
    if isinstance(value, str):
        # First try exact $stepN.field (returns raw typed value, not stringified)
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
        # Finally, try inline interpolation: replace all $stepN.field occurrences
        # within a larger string (e.g. filter expressions)
        if "$step" in value:
            def _replace_inline(match: re.Match) -> str:
                step_num = int(match.group(1))
                field_path = match.group(2)
                resolved = _extract_field(plan.results.get(step_num), field_path)
                if resolved is None:
                    return match.group(0)  # leave unresolved reference as-is
                return str(resolved)
            return _INLINE_VAR_PATTERN.sub(_replace_inline, value)
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
                await _execute_for_each(step, items, resolved_params, client, plan, session, manager)
                continue

        # Execute single step
        start = time.monotonic()
        try:
            result_data = await _execute_step(step.action, resolved_params, client, manager)
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
    manager,
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
            result = await _execute_step(step.action, iteration_params, client, manager)
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
# Engine context — lightweight stand-in for MCP Context
# ---------------------------------------------------------------------------

def _make_engine_ctx(manager, client=None):
    """Create a minimal context object that tool functions can use.

    Tool functions access ``ctx.request_context.lifespan_context.okta_auth_manager``
    to obtain an Okta client.  This helper builds a lightweight namespace that
    satisfies that attribute path so the same functions work when called from
    the orchestrator engine (where there is no real MCP Context).

    When *client* is supplied the resolved client is cached on the manager
    wrapper so that ``get_okta_client()`` returns it immediately instead of
    creating a new one.

    ``supports_elicitation(ctx)`` will return ``False`` for this object, so
    destructive operations auto-confirm via ``auto_confirm_on_fallback``.
    """
    engine_manager = manager
    if client is not None:
        engine_manager = SimpleNamespace(
            _resolved_client=client,
            org_url=getattr(manager, "org_url", None),
        )
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(
                okta_auth_manager=engine_manager,
            ),
        ),
        _engine_mode=True,
    )


# ---------------------------------------------------------------------------
# Action dispatcher — delegates to tool functions directly
# ---------------------------------------------------------------------------

# Each tool module exposes an ENGINE_ACTIONS dict that maps action names to
# the actual tool functions (the same functions registered as MCP tools).
# The orchestrator auto-unpacks params to match each function's signature.

_DISPATCHER: dict | None = None


def _get_dispatcher() -> dict:
    """Build and cache the action → handler mapping from all tool modules."""
    global _DISPATCHER
    if _DISPATCHER is not None:
        return _DISPATCHER

    from okta_mcp_server.tools.users.users import ENGINE_ACTIONS as _USER_ACTIONS
    from okta_mcp_server.tools.groups.groups import ENGINE_ACTIONS as _GROUP_ACTIONS
    from okta_mcp_server.tools.applications.applications import ENGINE_ACTIONS as _APP_ACTIONS
    from okta_mcp_server.tools.policies.policies import ENGINE_ACTIONS as _POLICY_ACTIONS
    from okta_mcp_server.tools.device_assurance.device_assurance import ENGINE_ACTIONS as _DA_ACTIONS
    from okta_mcp_server.tools.system_logs.system_logs import ENGINE_ACTIONS as _LOG_ACTIONS
    from okta_mcp_server.tools.customization.brands.brands import ENGINE_ACTIONS as _BRAND_ACTIONS
    from okta_mcp_server.tools.customization.themes.themes import ENGINE_ACTIONS as _THEME_ACTIONS
    # New tool modules
    from okta_mcp_server.tools.groups.group_owners import ENGINE_ACTIONS as _GROUP_OWNER_ACTIONS
    from okta_mcp_server.tools.groups.group_rules import ENGINE_ACTIONS as _GROUP_RULE_ACTIONS
    from okta_mcp_server.tools.users.user_lifecycle import ENGINE_ACTIONS as _USER_LIFECYCLE_ACTIONS
    from okta_mcp_server.tools.users.user_credentials import ENGINE_ACTIONS as _USER_CREDENTIAL_ACTIONS
    from okta_mcp_server.tools.users.user_factors import ENGINE_ACTIONS as _USER_FACTOR_ACTIONS
    from okta_mcp_server.tools.users.user_grants import ENGINE_ACTIONS as _USER_GRANT_ACTIONS
    from okta_mcp_server.tools.users.user_types import ENGINE_ACTIONS as _USER_TYPE_ACTIONS
    from okta_mcp_server.tools.users.user_extended import ENGINE_ACTIONS as _USER_EXTENDED_ACTIONS
    from okta_mcp_server.tools.devices import ENGINE_ACTIONS as _DEVICE_ACTIONS
    from okta_mcp_server.tools.device_integrations import ENGINE_ACTIONS as _DEVICE_INTEGRATION_ACTIONS
    from okta_mcp_server.tools.device_posture_checks import ENGINE_ACTIONS as _DEVICE_POSTURE_ACTIONS
    from okta_mcp_server.tools.log_streaming import ENGINE_ACTIONS as _LOG_STREAM_ACTIONS
    from okta_mcp_server.tools.profile_mappings import ENGINE_ACTIONS as _PROFILE_MAPPING_ACTIONS
    from okta_mcp_server.tools.policies.policies_extended import ENGINE_ACTIONS as _POLICY_EXT_ACTIONS
    from okta_mcp_server.tools.governance import ENGINE_ACTIONS as _GOV_ACTIONS
    from okta_mcp_server.tools.governance_end_user import ENGINE_ACTIONS as _GOV_EU_ACTIONS

    _DISPATCHER = {}
    _DISPATCHER.update(_USER_ACTIONS)
    _DISPATCHER.update(_GROUP_ACTIONS)
    _DISPATCHER.update(_APP_ACTIONS)
    _DISPATCHER.update(_POLICY_ACTIONS)
    _DISPATCHER.update(_DA_ACTIONS)
    _DISPATCHER.update(_LOG_ACTIONS)
    _DISPATCHER.update(_BRAND_ACTIONS)
    _DISPATCHER.update(_THEME_ACTIONS)
    # New modules
    _DISPATCHER.update(_GROUP_OWNER_ACTIONS)
    _DISPATCHER.update(_GROUP_RULE_ACTIONS)
    _DISPATCHER.update(_USER_LIFECYCLE_ACTIONS)
    _DISPATCHER.update(_USER_CREDENTIAL_ACTIONS)
    _DISPATCHER.update(_USER_FACTOR_ACTIONS)
    _DISPATCHER.update(_USER_GRANT_ACTIONS)
    _DISPATCHER.update(_USER_TYPE_ACTIONS)
    _DISPATCHER.update(_USER_EXTENDED_ACTIONS)
    _DISPATCHER.update(_DEVICE_ACTIONS)
    _DISPATCHER.update(_DEVICE_INTEGRATION_ACTIONS)
    _DISPATCHER.update(_DEVICE_POSTURE_ACTIONS)
    _DISPATCHER.update(_LOG_STREAM_ACTIONS)
    _DISPATCHER.update(_PROFILE_MAPPING_ACTIONS)
    _DISPATCHER.update(_POLICY_EXT_ACTIONS)
    _DISPATCHER.update(_GOV_ACTIONS)
    _DISPATCHER.update(_GOV_EU_ACTIONS)
    return _DISPATCHER


async def _execute_step(action: str, params: dict, client, manager) -> Any:
    """Dispatch an action to the appropriate tool function.

    Uses ``inspect.signature`` to auto-unpack the *params* dict into the
    function's keyword arguments and injects a lightweight engine context
    for the ``ctx`` parameter.
    """

    dispatcher = _get_dispatcher()
    if action not in dispatcher:
        raise ValueError(f"Unknown action: '{action}'. Available: {sorted(dispatcher.keys())}")

    handler = dispatcher[action]
    ctx = _make_engine_ctx(manager, client)

    # Build kwargs from params, matching the function's signature.
    sig = inspect.signature(handler)
    kwargs: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "ctx":
            kwargs["ctx"] = ctx
        elif name in params:
            kwargs[name] = params[name]
        # skip params not present — let the function use its defaults

    result = await handler(**kwargs)

    # -- Normalise the result for engine consumption -------------------------
    # MCP tool functions return wrapped formats (e.g. [user], {"items": [...]},
    # ["Error: ..."]) whereas the engine expects raw objects / lists and uses
    # exceptions for errors.

    if isinstance(result, list) and len(result) == 1:
        item = result[0]
        if isinstance(item, str) and item.startswith(("Error:", "Exception:")):
            raise RuntimeError(item)
        if isinstance(item, dict) and "error" in item:
            raise RuntimeError(item["error"])
        # Unwrap single-item lists (e.g. [user] → user)
        result = item
    elif isinstance(result, dict):
        if "error" in result:
            raise RuntimeError(result["error"])
        if "items" in result:
            result = result["items"]

    return result


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
