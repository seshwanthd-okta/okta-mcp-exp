# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Tests for the Okta MCP Orchestrator.

Covers:
  1. Workflow registry & matching
  2. Plan building (offboard_user)
  3. Variable resolution ($stepN.field, bare $stepN)
  4. Engine execution (happy path, failures, for_each, skip-on-failure)
  5. MCP tool layer (orchestrator_query, orchestrator_execute, orchestrator_context)
  6. Session context tracking
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from okta_mcp_server.tools.orchestrator.engine import (
    Plan,
    PlanStatus,
    SessionContext,
    Step,
    StepResult,
    StepStatus,
    _extract_field,
    _resolve_value,
    _serialise,
    create_plan,
    execute_plan,
    get_session,
    reset_session,
)
from okta_mcp_server.tools.orchestrator.workflows import (
    WORKFLOW_REGISTRY,
    build_offboard_user,
    get_workflow_info,
    match_workflow,
    match_workflow_by_keywords,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_session():
    """Reset the global session before each test."""
    reset_session()
    yield
    reset_session()


@dataclass
class FakeUser:
    id: str = "00u_test123"

    @dataclass
    class Profile:
        login: str = "john@acme.com"
        email: str = "john@acme.com"
        firstName: str = "John"
        lastName: str = "Doe"

    profile: Profile = None

    def __post_init__(self):
        if self.profile is None:
            self.profile = self.Profile()


@dataclass
class FakeGroup:
    id: str = "00g_grp1"

    @dataclass
    class Profile:
        name: str = "Engineering"

    profile: Profile = None

    def __post_init__(self):
        if self.profile is None:
            self.profile = self.Profile()


@dataclass
class FakeAppLink:
    label: str = "Slack"
    appName: str = "slack"


def _make_fake_groups(n: int = 3) -> list[FakeGroup]:
    names = ["Engineering", "All-Employees", "Slack-Access"]
    return [
        FakeGroup(id=f"00g_grp{i+1}", profile=FakeGroup.Profile(name=names[i] if i < len(names) else f"Group-{i+1}"))
        for i in range(n)
    ]


def _make_mock_client(
    user: FakeUser | None = None,
    groups: list | None = None,
    apps: list | None = None,
) -> AsyncMock:
    """Build a mock Okta SDK client with pre-configured returns."""
    client = AsyncMock()

    if user is None:
        user = FakeUser()
    if groups is None:
        groups = _make_fake_groups()
    if apps is None:
        apps = [FakeAppLink(label="Slack"), FakeAppLink(label="Jira")]

    # get_user(user_id) → (user, response, err)
    client.get_user.return_value = (user, MagicMock(), None)
    # list_user_groups(user_id) → (groups, response, err)
    client.list_user_groups.return_value = (groups, MagicMock(), None)
    # unassign_user_from_group(group_id, user_id) → (response, err)
    client.unassign_user_from_group.return_value = (MagicMock(), None)
    # deactivate_user(user_id) → (response, err)
    client.deactivate_user.return_value = (MagicMock(), None)
    # list_app_links(user_id) → (apps, response, err)
    client.list_app_links.return_value = (apps, MagicMock(), None)
    # list_users → (users, response, err)
    client.list_users.return_value = ([user], MagicMock(), None)

    return client


def _make_ctx():
    """Build a fake MCP Context for the orchestrator tools."""
    auth_manager = MagicMock()
    auth_manager.is_valid_token = AsyncMock(return_value=True)
    auth_manager.org_url = "https://test.okta.com"

    lifespan_ctx = MagicMock()
    lifespan_ctx.okta_auth_manager = auth_manager

    request_ctx = MagicMock()
    request_ctx.lifespan_context = lifespan_ctx

    ctx = MagicMock()
    ctx.request_context = request_ctx
    return ctx


# ===========================================================================
# 1. Workflow Registry & Matching
# ===========================================================================

class TestWorkflowRegistry:
    def test_offboard_user_in_registry(self):
        assert "offboard_user" in WORKFLOW_REGISTRY

    def test_match_workflow_exact(self):
        assert match_workflow("offboard", "user") == "offboard_user"

    def test_match_workflow_case_insensitive(self):
        assert match_workflow("OFFBOARD", "USER") == "offboard_user"

    def test_match_workflow_no_match(self):
        assert match_workflow("restart", "server") is None

    def test_match_by_keywords_offboard(self):
        assert match_workflow_by_keywords("offboard the user") == "offboard_user"

    def test_match_by_keywords_terminate(self):
        assert match_workflow_by_keywords("terminate employee") == "offboard_user"

    def test_match_by_keywords_disable_user(self):
        assert match_workflow_by_keywords("disable this user now") == "offboard_user"

    def test_match_by_keywords_no_match(self):
        assert match_workflow_by_keywords("create a new group") is None

    def test_get_workflow_info(self):
        info = get_workflow_info()
        assert len(info) >= 1
        offboard = next(w for w in info if w["name"] == "offboard_user")
        assert offboard["action"] == "offboard"
        assert offboard["target_type"] == "user"
        assert "user_identifier" in offboard["required_params"]


# ===========================================================================
# 2. Plan Building
# ===========================================================================

class TestPlanBuilding:
    def test_build_offboard_user_creates_plan(self):
        plan = build_offboard_user("john@acme.com")
        assert isinstance(plan, Plan)
        assert plan.workflow_name == "offboard_user"
        assert plan.plan_id.startswith("plan_")
        assert len(plan.steps) == 5

    def test_offboard_plan_step_order(self):
        plan = build_offboard_user("john@acme.com")
        actions = [s.action for s in plan.steps]
        assert actions == [
            "get_user",
            "list_user_groups",
            "remove_user_from_group",
            "list_user_app_assignments",
            "deactivate_user",
        ]

    def test_offboard_plan_destructive_steps(self):
        plan = build_offboard_user("john@acme.com")
        destructive = [s.number for s in plan.steps if s.is_destructive]
        assert destructive == [3, 5]

    def test_offboard_plan_for_each_on_step3(self):
        plan = build_offboard_user("john@acme.com")
        step3 = plan.steps[2]
        assert step3.for_each == "$step2"

    def test_offboard_plan_variable_references(self):
        plan = build_offboard_user("test@example.com")
        # Step 2-5 should reference $step1.id
        for step in plan.steps[1:]:
            assert "$step1.id" in str(step.params.values())

    def test_plan_preview(self):
        plan = build_offboard_user("john@acme.com")
        preview = plan.to_preview()
        assert preview["workflow"] == "offboard_user"
        assert preview["total_steps"] == 5
        assert preview["requires_approval"] is True
        assert 3 in preview["destructive_steps"]
        assert 5 in preview["destructive_steps"]

    def test_plan_registered_in_session(self):
        plan = build_offboard_user("john@acme.com")
        session = get_session()
        assert plan.plan_id in session.plans


# ===========================================================================
# 3. Variable Resolution
# ===========================================================================

class TestVariableResolution:
    def _plan_with_results(self) -> Plan:
        plan = Plan(
            plan_id="test_plan",
            workflow_name="test",
            description="test",
            steps=[],
        )
        plan.results[1] = FakeUser()
        plan.results[2] = _make_fake_groups(2)
        return plan

    def test_resolve_step_field(self):
        plan = self._plan_with_results()
        result = _resolve_value("$step1.id", plan)
        assert result == "00u_test123"

    def test_resolve_nested_field(self):
        plan = self._plan_with_results()
        result = _resolve_value("$step1.profile.email", plan)
        assert result == "john@acme.com"

    def test_resolve_bare_step(self):
        plan = self._plan_with_results()
        result = _resolve_value("$step2", plan)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_resolve_plain_string(self):
        plan = self._plan_with_results()
        result = _resolve_value("hello", plan)
        assert result == "hello"

    def test_resolve_dict_with_refs(self):
        plan = self._plan_with_results()
        result = _resolve_value({"user_id": "$step1.id", "static": "value"}, plan)
        assert result == {"user_id": "00u_test123", "static": "value"}

    def test_resolve_missing_step(self):
        plan = self._plan_with_results()
        result = _resolve_value("$step99.id", plan)
        assert result is None

    def test_extract_field_on_dict(self):
        data = {"profile": {"email": "a@b.com"}}
        assert _extract_field(data, "profile.email") == "a@b.com"

    def test_extract_field_on_list(self):
        data = [FakeGroup(id="g1"), FakeGroup(id="g2")]
        result = _extract_field(data, "id")
        assert result == ["g1", "g2"]

    def test_extract_field_none(self):
        assert _extract_field(None, "anything") is None


# ===========================================================================
# 4. Engine Execution
# ===========================================================================

class TestEngineExecution:
    @pytest.mark.asyncio
    async def test_full_offboard_happy_path(self):
        """Execute the full offboard workflow with mocked Okta client."""
        plan = build_offboard_user("john@acme.com")
        mock_client = _make_mock_client()

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        assert result.status == PlanStatus.COMPLETED
        # All 5 steps should have results
        for step in result.steps:
            assert step.result is not None
            assert step.result.status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_step_results_populated(self):
        plan = build_offboard_user("john@acme.com")
        mock_client = _make_mock_client()

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        # Step 1 — user object
        assert result.results[1] is not None
        assert result.results[1].id == "00u_test123"

        # Step 2 — list of groups
        assert isinstance(result.results[2], list)
        assert len(result.results[2]) == 3

        # Step 3 — for_each results (one per group)
        assert isinstance(result.results[3], list)
        assert len(result.results[3]) == 3

        # Step 4 — app links
        assert isinstance(result.results[4], list)

        # Step 5 — deactivation string
        assert result.results[5] is not None

    @pytest.mark.asyncio
    async def test_for_each_calls_remove_per_group(self):
        groups = _make_fake_groups(3)
        mock_client = _make_mock_client(groups=groups)

        plan = build_offboard_user("john@acme.com")
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await execute_plan(plan, MagicMock())

        # unassign_user_from_group should be called once per group
        assert mock_client.unassign_user_from_group.call_count == 3
        called_group_ids = [
            call.args[0] for call in mock_client.unassign_user_from_group.call_args_list
        ]
        expected_ids = [g.id for g in groups]
        assert sorted(called_group_ids) == sorted(expected_ids)

    @pytest.mark.asyncio
    async def test_api_call_counter(self):
        plan = build_offboard_user("john@acme.com")
        mock_client = _make_mock_client()

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await execute_plan(plan, MagicMock())

        session = get_session()
        # 1 (get_user) + 1 (list_groups) + 3 (remove x3) + 1 (list_apps) + 1 (deactivate) = 7
        assert session.total_api_calls == 7

    @pytest.mark.asyncio
    async def test_step_failure_skips_destructive(self):
        """If a read step fails, subsequent destructive steps are skipped."""
        mock_client = _make_mock_client()
        # Make list_user_groups fail
        mock_client.list_user_groups.return_value = (None, None, "API error: 403")

        plan = build_offboard_user("john@acme.com")
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        assert result.status == PlanStatus.PARTIAL
        # Step 2 failed
        assert result.steps[1].result.status == StepStatus.FAILED
        # Step 3 (destructive for_each) should be skipped
        assert result.steps[2].result.status == StepStatus.SKIPPED
        # Step 5 (destructive deactivate) should be skipped
        assert result.steps[4].result.status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_step_failure_non_destructive_continues(self):
        """Non-destructive steps after a failure still execute."""
        mock_client = _make_mock_client()
        # Make list_user_groups fail
        mock_client.list_user_groups.return_value = (None, None, "API error")

        plan = build_offboard_user("john@acme.com")
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        # Step 4 (list_user_app_assignments) is not destructive — should still run
        assert result.steps[3].result.status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        mock_client = _make_mock_client()
        mock_client.get_user.return_value = (None, None, "User not found")

        plan = build_offboard_user("nonexistent@acme.com")
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        assert result.steps[0].result.status == StepStatus.FAILED
        assert "User not found" in result.steps[0].result.error

    @pytest.mark.asyncio
    async def test_zero_groups(self):
        """User in no groups — for_each produces zero iterations."""
        mock_client = _make_mock_client(groups=[])

        plan = build_offboard_user("john@acme.com")
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            result = await execute_plan(plan, MagicMock())

        assert result.status == PlanStatus.COMPLETED
        # Step 3 for_each with empty list — no iterations, still succeeds
        assert result.steps[2].result.status == StepStatus.SUCCESS
        assert result.results[3] == []

    @pytest.mark.asyncio
    async def test_plan_summary(self):
        plan = build_offboard_user("john@acme.com")
        mock_client = _make_mock_client()

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await execute_plan(plan, MagicMock())

        summary = plan.to_summary()
        assert summary["status"] == "completed"
        assert len(summary["steps"]) == 5
        assert all(s["status"] == "success" for s in summary["steps"])

    @pytest.mark.asyncio
    async def test_operation_recorded_in_session(self):
        plan = build_offboard_user("john@acme.com")
        mock_client = _make_mock_client()

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await execute_plan(plan, MagicMock())

        session = get_session()
        assert len(session.operations) == 1
        assert session.operations[0]["workflow"] == "offboard_user"
        assert session.operations[0]["status"] == "completed"


# ===========================================================================
# 5. MCP Tool Layer
# ===========================================================================

class TestOrchestratorTools:
    @pytest.mark.asyncio
    async def test_query_list_workflows(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_query

        ctx = _make_ctx()
        result = await orchestrator_query(
            ctx=ctx, action="list", target_type="", target_identifier=""
        )
        assert "available_workflows" in result
        assert len(result["available_workflows"]) >= 1

    @pytest.mark.asyncio
    async def test_query_offboard_builds_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_query

        ctx = _make_ctx()
        result = await orchestrator_query(
            ctx=ctx, action="offboard", target_type="user", target_identifier="john@acme.com"
        )
        assert "plan" in result
        assert result["plan"]["workflow"] == "offboard_user"
        assert result["plan"]["total_steps"] == 5
        assert result["plan"]["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_query_unknown_action(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_query

        ctx = _make_ctx()
        result = await orchestrator_query(
            ctx=ctx, action="restart", target_type="server", target_identifier="x"
        )
        assert "error" in result
        assert "available_workflows" in result

    @pytest.mark.asyncio
    async def test_query_intent_fallback(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_query

        ctx = _make_ctx()
        result = await orchestrator_query(
            ctx=ctx, action="unknown", target_type="unknown",
            target_identifier="john@acme.com", intent="terminate this employee"
        )
        assert "plan" in result
        assert result["plan"]["workflow"] == "offboard_user"

    @pytest.mark.asyncio
    async def test_execute_plan_success(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import (
            orchestrator_execute,
            orchestrator_query,
        )

        ctx = _make_ctx()
        mock_client = _make_mock_client()

        # First build a plan
        query_result = await orchestrator_query(
            ctx=ctx, action="offboard", target_type="user", target_identifier="john@acme.com"
        )
        plan_id = query_result["plan"]["plan_id"]

        # Execute it
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            exec_result = await orchestrator_execute(ctx=ctx, plan_id=plan_id)

        assert "summary" in exec_result
        assert exec_result["summary"]["status"] == "completed"
        assert "context" in exec_result
        assert "actions_taken" in exec_result["context"]

    @pytest.mark.asyncio
    async def test_execute_nonexistent_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_execute

        ctx = _make_ctx()
        result = await orchestrator_execute(ctx=ctx, plan_id="plan_doesnotexist")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_already_completed_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import (
            orchestrator_execute,
            orchestrator_query,
        )

        ctx = _make_ctx()
        mock_client = _make_mock_client()

        query_result = await orchestrator_query(
            ctx=ctx, action="offboard", target_type="user", target_identifier="john@acme.com"
        )
        plan_id = query_result["plan"]["plan_id"]

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await orchestrator_execute(ctx=ctx, plan_id=plan_id)
            # Execute again — should fail
            result = await orchestrator_execute(ctx=ctx, plan_id=plan_id)

        assert "error" in result
        assert "cannot be executed" in result["error"]

    @pytest.mark.asyncio
    async def test_context_empty_session(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import orchestrator_context

        ctx = _make_ctx()
        result = await orchestrator_context(ctx=ctx)
        assert "session" in result
        assert result["session"]["total_api_calls"] == 0

    @pytest.mark.asyncio
    async def test_context_after_execution(self):
        from okta_mcp_server.tools.orchestrator.orchestrator import (
            orchestrator_context,
            orchestrator_execute,
            orchestrator_query,
        )

        ctx = _make_ctx()
        mock_client = _make_mock_client()

        query_result = await orchestrator_query(
            ctx=ctx, action="offboard", target_type="user", target_identifier="john@acme.com"
        )
        plan_id = query_result["plan"]["plan_id"]

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await orchestrator_execute(ctx=ctx, plan_id=plan_id)

        result = await orchestrator_context(ctx=ctx)
        assert result["session"]["total_api_calls"] == 7
        assert len(result["session"]["plans_executed"]) == 1
        assert len(result["session"]["operations_performed"]) == 1


# ===========================================================================
# 6. Serialisation & helpers
# ===========================================================================

class TestSerialisation:
    def test_serialise_primitives(self):
        assert _serialise("hello") == "hello"
        assert _serialise(42) == 42
        assert _serialise(True) is True
        assert _serialise(None) is None

    def test_serialise_list(self):
        result = _serialise([1, "a", None])
        assert result == [1, "a", None]

    def test_serialise_dict(self):
        result = _serialise({"key": "value"})
        assert result == {"key": "value"}

    def test_serialise_object_with_dict(self):
        user = FakeUser()
        result = _serialise(user)
        assert isinstance(result, dict)
        assert result["id"] == "00u_test123"

    def test_session_to_dict(self):
        session = SessionContext()
        d = session.to_dict()
        assert "entities_resolved" in d
        assert "plans_executed" in d
        assert "total_api_calls" in d

    def test_session_record_entity(self):
        session = SessionContext()
        session.record_entity("user", "john@acme.com", {"id": "00u123"})
        assert session.get_entity("user", "john@acme.com") == {"id": "00u123"}
        assert session.get_entity("user", "nonexistent") is None
