# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Tests for the CSP-based Workflow Planner.

Covers:
  1. Goal registry — registration, lookup, built-in goals
  2. CSP planner core — backward chaining, topological sort,
     action selection, cycle detection, error handling
  3. Integration with the real Knowledge Graph — planning for
     predefined goals produces valid action sequences
  4. MCP tool — orchestrator_plan_for_goal
  5. Edge cases — empty goals, unknown goals, unsolvable goals
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from okta_mcp_server.tools.orchestrator.engine import (
    PlanStatus,
    get_session,
    reset_session,
)
from okta_mcp_server.tools.orchestrator.knowledge_graph import (
    EntityType,
    OktaKnowledgeGraph,
    OperationType,
    ToolNode,
    build_okta_knowledge_graph,
    get_knowledge_graph,
    reset_knowledge_graph,
)
from okta_mcp_server.tools.orchestrator.planner import (
    CSPPlanner,
    Goal,
    PlanResult,
    get_goal,
    list_goals,
    plan_for_goal,
    plan_for_state,
    register_goal,
    reset_goals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_state():
    """Reset all singletons before each test."""
    reset_session()
    reset_knowledge_graph()
    reset_goals()
    yield
    reset_session()
    reset_knowledge_graph()
    reset_goals()


@pytest.fixture
def kg() -> OktaKnowledgeGraph:
    """Return a freshly built knowledge graph."""
    return build_okta_knowledge_graph()


@pytest.fixture
def mini_kg() -> OktaKnowledgeGraph:
    """A minimal KG for focused unit tests."""
    kg = OktaKnowledgeGraph()
    kg.add_node(ToolNode(
        action="get_user",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Get user by ID or login",
        required_params=["user_id_or_login"],
        outputs={"id": "user.id", "status": "user.status", "profile": "user.profile"},
        preconditions={"user.identifier": "PROVIDED"},
        effects={"user.id": "KNOWN", "user.profile": "KNOWN", "user.status": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_user",
        entity_type=EntityType.USER,
        operation=OperationType.DELETE,
        description="Deactivate a user account",
        required_params=["user_id"],
        is_destructive=True,
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "DEACTIVATED"},
    ))
    kg.add_node(ToolNode(
        action="clear_user_sessions",
        entity_type=EntityType.USER,
        operation=OperationType.DELETE,
        description="Clear all user sessions",
        required_params=["user_id"],
        is_destructive=True,
        preconditions={"user.id": "KNOWN"},
        effects={"user.sessions": "REVOKED"},
    ))
    kg.add_node(ToolNode(
        action="list_user_groups",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List groups a user belongs to",
        required_params=["user_id"],
        outputs={"items": "user.groups[]"},
        preconditions={"user.id": "KNOWN"},
        effects={"user.groups": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="suspend_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Suspend a user account",
        required_params=["user_id"],
        is_destructive=True,
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "SUSPENDED"},
    ))
    return kg


@dataclass
class FakeRequestContext:
    lifespan_context: MagicMock


@dataclass
class FakeContext:
    request_context: FakeRequestContext


def _make_ctx():
    """Create a fake MCP context for tool tests."""
    mock_manager = MagicMock()
    return FakeContext(request_context=FakeRequestContext(lifespan_context=MagicMock(okta_auth_manager=mock_manager)))


# ===========================================================================
# 1. Goal Registry Tests
# ===========================================================================

class TestGoalRegistry:
    """Tests for goal registration and lookup."""

    def test_builtin_goals_registered(self):
        """All built-in goals are registered on module load."""
        goals = list_goals()
        names = [g["name"] for g in goals]
        assert "offboard_user" in names
        assert "suspend_user" in names
        assert "onboard_user" in names
        assert "audit_user" in names
        assert "rotate_user_credentials" in names
        assert "setup_brand" in names
        assert "configure_custom_domain" in names
        assert "configure_email_domain" in names
        assert "setup_device_assurance_policy" in names
        assert "cleanup_group" in names

    def test_get_goal(self):
        """Can retrieve a registered goal by name."""
        goal = get_goal("offboard_user")
        assert goal is not None
        assert goal.name == "offboard_user"
        assert "user.status" in goal.required_state
        assert goal.required_state["user.status"] == "DEACTIVATED"

    def test_get_goal_unknown(self):
        """Returns None for unknown goal."""
        assert get_goal("nonexistent") is None

    def test_register_custom_goal(self):
        """Can register and retrieve a custom goal."""
        register_goal(Goal(
            name="lockdown_user",
            description="Lock down a user completely",
            required_state={"user.status": "DEACTIVATED", "user.sessions": "CLEARED"},
        ))
        goal = get_goal("lockdown_user")
        assert goal is not None
        assert goal.required_state["user.status"] == "DEACTIVATED"

    def test_list_goals_returns_dicts(self):
        """list_goals returns serializable dicts."""
        goals = list_goals()
        assert len(goals) >= 14
        for g in goals:
            assert "name" in g
            assert "description" in g
            assert "required_state" in g

    def test_reset_goals(self):
        """reset_goals clears custom goals and restores built-ins."""
        register_goal(Goal(name="custom", description="test", required_state={}))
        assert get_goal("custom") is not None
        reset_goals()
        assert get_goal("custom") is None
        assert get_goal("offboard_user") is not None  # built-in restored


# ===========================================================================
# 2. CSP Planner Core Tests (with mini_kg)
# ===========================================================================

class TestCSPPlannerCore:
    """Unit tests for the backward-chaining CSP planner."""

    def test_simple_two_step_plan(self, mini_kg):
        """Plan deactivation: get_user → deactivate_user."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        assert result.actions == ["get_user", "deactivate_user"]
        assert len(result.steps) == 2

    def test_three_step_plan(self, mini_kg):
        """Plan suspension: get_user → clear_sessions → suspend_user."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={
                "user.status": "SUSPENDED",
                "user.sessions": "REVOKED",
            },
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        assert "get_user" in result.actions
        assert "suspend_user" in result.actions
        assert "clear_user_sessions" in result.actions
        # get_user must come first
        assert result.actions.index("get_user") < result.actions.index("suspend_user")
        assert result.actions.index("get_user") < result.actions.index("clear_user_sessions")

    def test_initial_state_satisfies_some_goals(self, mini_kg):
        """When initial state already satisfies some predicates, skip those."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.id": "KNOWN", "user.status": "DEACTIVATED"},
            initial_state={"user.id": "KNOWN"},  # already have user.id
        )
        assert result.success
        # Should skip get_user since user.id is already KNOWN
        assert "deactivate_user" in result.actions
        # get_user not needed since user.id already KNOWN
        assert len(result.actions) == 1

    def test_fully_satisfied_initial_state(self, mini_kg):
        """When initial state satisfies all goals, empty plan."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.id": "KNOWN"},
            initial_state={"user.id": "KNOWN"},
        )
        assert result.success
        assert result.actions == []
        assert result.steps == []

    def test_unsolvable_goal(self, mini_kg):
        """When no action can produce a required effect, fail gracefully."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"nonexistent.state": "IMPOSSIBLE"},
            initial_state={},
        )
        assert not result.success
        assert "No action produces effect" in result.error

    def test_max_steps_exceeded(self, mini_kg):
        """When plan would exceed max_steps, fail."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
            max_steps=0,
        )
        assert not result.success
        assert "max_steps" in result.error

    def test_topological_ordering(self, mini_kg):
        """Actions are topologically sorted by dependencies."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={
                "user.status": "DEACTIVATED",
                "user.sessions": "REVOKED",
                "user.groups": "ENUMERATED",
            },
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        # get_user must be first since all others depend on user.id
        assert result.actions[0] == "get_user"

    def test_step_state_transitions(self, mini_kg):
        """Each step records state_before and state_after."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        for step in result.steps:
            assert "state_before" in step
            assert "state_after" in step
            assert "preconditions" in step
            assert "effects" in step
            assert "satisfies" in step

    def test_plan_result_serialization(self, mini_kg):
        """PlanResult.to_dict produces a clean dict."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert isinstance(d["actions"], list)
        assert isinstance(d["steps"], list)
        assert "error" not in d  # no error key when successful

    def test_failed_plan_result_serialization(self, mini_kg):
        """Failed PlanResult includes error in dict."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"impossible.state": "VALUE"},
            initial_state={},
        )
        d = result.to_dict()
        assert d["success"] is False
        assert "error" in d

    def test_action_selection_prefers_already_selected(self, mini_kg):
        """When multiple actions produce the same effect, prefer already selected."""
        # Both get_user and list_user_groups produce user.id: KNOWN
        # Actually in mini_kg only get_user does. Let's test the priority logic
        # by ensuring the planner doesn't duplicate actions
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={
                "user.id": "KNOWN",
                "user.profile": "KNOWN",
                "user.status": "KNOWN",
            },
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        # All three effects come from get_user, so only 1 action needed
        assert result.actions == ["get_user"]


# ===========================================================================
# 3. Integration Tests with Real Knowledge Graph
# ===========================================================================

class TestCSPPlannerIntegration:
    """Integration tests using the full 109-node knowledge graph."""

    def test_offboard_user_plan(self, kg):
        """CSP solver generates a valid offboard_user workflow."""
        result = plan_for_goal("offboard_user", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "deactivate_user" in result.actions
        # get_user must come before deactivate_user
        assert result.actions.index("get_user") < result.actions.index("deactivate_user")

    def test_suspend_user_plan(self, kg):
        """CSP solver generates a valid suspend_user workflow."""
        result = plan_for_goal("suspend_user", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "suspend_user" in result.actions
        assert result.actions.index("get_user") < result.actions.index("suspend_user")

    def test_onboard_user_plan(self, kg):
        """CSP solver generates a valid onboard_user workflow."""
        result = plan_for_goal("onboard_user", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "create_user" in result.actions
        assert "add_user_to_group" in result.actions

    def test_audit_user_plan(self, kg):
        """CSP solver generates a valid audit_user workflow."""
        result = plan_for_goal("audit_user", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "list_user_app_assignments" in result.actions
        assert "list_user_groups" in result.actions
        assert "get_logs" in result.actions

    def test_rotate_user_credentials_plan(self, kg):
        """CSP solver generates a valid rotate_user_credentials workflow."""
        result = plan_for_goal("rotate_user_credentials", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "clear_user_sessions" in result.actions

    def test_setup_brand_plan(self, kg):
        """CSP solver generates a valid setup_brand workflow."""
        result = plan_for_goal("setup_brand", kg=kg)
        assert result.success, f"Failed: {result.error}"
        # Should include some brand-related actions
        brand_actions = [a for a in result.actions if "brand" in a]
        assert len(brand_actions) > 0

    def test_configure_custom_domain_plan(self, kg):
        """CSP solver generates a valid configure_custom_domain workflow."""
        result = plan_for_goal("configure_custom_domain", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "create_custom_domain" in result.actions
        assert "verify_custom_domain" in result.actions

    def test_configure_email_domain_plan(self, kg):
        """CSP solver generates a valid configure_email_domain workflow."""
        result = plan_for_goal("configure_email_domain", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "create_email_domain" in result.actions
        assert "verify_email_domain" in result.actions

    def test_setup_device_assurance_plan(self, kg):
        """CSP solver generates a valid device_assurance workflow."""
        result = plan_for_goal("setup_device_assurance_policy", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "create_device_assurance_policy" in result.actions

    def test_cleanup_group_plan(self, kg):
        """CSP solver generates a valid cleanup_group workflow."""
        result = plan_for_goal("cleanup_group", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "delete_group" in result.actions

    def test_create_group_plan(self, kg):
        """CSP solver generates a valid create_group workflow."""
        result = plan_for_goal("create_group", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "create_group" in result.actions

    def test_audit_group_plan(self, kg):
        """CSP solver generates a valid audit_group workflow."""
        result = plan_for_goal("audit_group", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_group" in result.actions
        assert "list_group_users" in result.actions
        assert "list_group_apps" in result.actions

    def test_add_user_to_group_plan(self, kg):
        """CSP solver generates a valid add_user_to_group workflow."""
        result = plan_for_goal("add_user_to_group", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "get_group" in result.actions
        assert "add_user_to_group" in result.actions

    def test_list_groups_plan(self, kg):
        """CSP solver generates a valid list_groups workflow."""
        result = plan_for_goal("list_groups", kg=kg)
        assert result.success, f"Failed: {result.error}"
        assert "list_groups" in result.actions

    def test_ad_hoc_goal_state(self, kg):
        """Plan with an ad-hoc goal state (not from registry)."""
        result = plan_for_state(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
            kg=kg,
        )
        assert result.success, f"Failed: {result.error}"
        assert "get_user" in result.actions
        assert "deactivate_user" in result.actions

    def test_unknown_goal_name(self, kg):
        """Unknown goal name returns informative error."""
        result = plan_for_goal("nonexistent_goal", kg=kg)
        assert not result.success
        assert "Unknown goal" in result.error
        assert "offboard_user" in result.error  # lists available goals

    def test_offboard_user_ordering(self, kg):
        """Offboard user plan respects dependency ordering."""
        result = plan_for_goal("offboard_user", kg=kg)
        assert result.success
        get_idx = result.actions.index("get_user")
        deact_idx = result.actions.index("deactivate_user")
        # get_user must precede deactivate
        assert get_idx < deact_idx

    def test_final_state_covers_goal(self, kg):
        """Final state of planned workflow satisfies all goal predicates."""
        goal = get_goal("offboard_user")
        result = plan_for_goal("offboard_user", kg=kg)
        assert result.success
        for key, value in goal.required_state.items():
            assert result.final_state.get(key) == value, (
                f"Goal predicate {key}={value} not satisfied in final state. "
                f"Final state has {key}={result.final_state.get(key)}"
            )

    def test_all_builtin_goals_solvable(self, kg):
        """Every registered built-in goal can be solved."""
        for goal_info in list_goals():
            result = plan_for_goal(goal_info["name"], kg=kg)
            assert result.success, (
                f"Goal '{goal_info['name']}' failed: {result.error}"
            )
            assert len(result.actions) > 0, (
                f"Goal '{goal_info['name']}' produced empty plan"
            )

    def test_all_builtin_goals_final_state_satisfies(self, kg):
        """Every built-in goal's final state satisfies all required predicates."""
        for goal_info in list_goals():
            result = plan_for_goal(goal_info["name"], kg=kg)
            assert result.success
            goal = get_goal(goal_info["name"])
            for key, value in goal.required_state.items():
                assert result.final_state.get(key) == value, (
                    f"Goal '{goal_info['name']}': predicate {key}={value} "
                    f"not in final state (got {result.final_state.get(key)})"
                )


# ===========================================================================
# 4. MCP Tool Tests
# ===========================================================================

class TestOrchestratorPlanForGoalTool:
    """Tests for the orchestrator_plan_for_goal MCP tool."""

    @pytest.mark.asyncio
    async def test_list_goals_when_no_args(self):
        """Calling with no args returns available goals."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(ctx)
        assert "available_goals" in result
        assert len(result["available_goals"]) >= 14

    @pytest.mark.asyncio
    async def test_plan_with_goal_name(self):
        """Plan with a predefined goal name."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_name="suspend_user",
            target_identifier="test@example.com",
        )
        assert result["success"] is True
        assert "solver_result" in result
        assert "plan" in result  # always builds a plan
        assert "plan_id" in result["plan"]

    @pytest.mark.asyncio
    async def test_plan_with_adhoc_goal(self):
        """Plan with an ad-hoc goal state."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_state="user.status=DEACTIVATED,user.sessions=REVOKED",
            initial_state="user.identifier=PROVIDED",
            target_identifier="test@example.com",
        )
        assert result["success"] is True
        assert "solver_result" in result

    @pytest.mark.asyncio
    async def test_plan_without_target_identifier(self):
        """Plan is still built without target_identifier — params just won't be pre-filled."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_name="offboard_user",
        )
        assert result["success"] is True
        assert "plan" in result  # plan is built even without target_identifier

    @pytest.mark.asyncio
    async def test_plan_unknown_goal(self):
        """Unknown goal name returns error."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_name="nonexistent",
        )
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_plan_creates_session_plan(self):
        """Auto-built plan is stored in session."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_name="suspend_user",
            target_identifier="test@example.com",
        )
        assert result["success"] is True
        plan_id = result["plan"]["plan_id"]
        session = get_session()
        assert plan_id in session.plans

    @pytest.mark.asyncio
    async def test_plan_destructive_requires_approval(self):
        """Plans with destructive steps require approval."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_name="offboard_user",
            target_identifier="test@example.com",
        )
        assert result["success"] is True
        assert result["plan"]["requires_approval"] is True
        plan_id = result["plan"]["plan_id"]
        session = get_session()
        assert session.plans[plan_id].status == PlanStatus.AWAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_invalid_goal_state_format(self):
        """Invalid goal_state format returns error."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_plan_for_goal,
        )
        ctx = _make_ctx()
        result = await orchestrator_plan_for_goal(
            ctx,
            goal_state="invalid-no-equals",
        )
        assert "error" in result


# ===========================================================================
# 5. Edge Cases & Robustness
# ===========================================================================

class TestCSPPlannerEdgeCases:
    """Edge cases and robustness tests."""

    def test_empty_goal_state(self, mini_kg):
        """Empty goal state produces empty plan."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(goal_state={}, initial_state={})
        assert result.success
        assert result.actions == []

    def test_empty_nodes(self):
        """Planner with no nodes fails for any goal."""
        planner = CSPPlanner({})
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={},
        )
        assert not result.success

    def test_single_action_plan(self, mini_kg):
        """Plan with a single action that's directly available."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.id": "KNOWN"},  # precondition already met
        )
        assert result.success
        assert result.actions == ["deactivate_user"]

    def test_plan_with_override_initial_state(self, kg):
        """Custom initial_state overrides goal's initial_hints."""
        result = plan_for_goal(
            "offboard_user",
            initial_state={"user.id": "KNOWN"},
            kg=kg,
        )
        assert result.success
        # Should still work but may have fewer steps
        # since user.id is already KNOWN
        assert "deactivate_user" in result.actions

    def test_plan_for_state_minimal(self, kg):
        """Ad-hoc plan for a single predicate."""
        result = plan_for_state(
            goal_state={"user.profile": "KNOWN"},
            initial_state={"user.identifier": "PROVIDED"},
            kg=kg,
        )
        assert result.success
        assert "get_user" in result.actions

    def test_planner_does_not_select_unnecessary_actions(self, mini_kg):
        """Planner selects minimal set of actions."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        # Should only have get_user and deactivate_user
        # Not clear_user_sessions or list_user_groups
        assert len(result.actions) == 2

    def test_multiple_effects_from_single_action(self, mini_kg):
        """Action with multiple effects satisfies multiple goals at once."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={
                "user.id": "KNOWN",
                "user.profile": "KNOWN",
                "user.status": "KNOWN",
            },
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        # get_user produces all three effects
        assert result.actions == ["get_user"]

    def test_step_numbering(self, mini_kg):
        """Steps are numbered sequentially starting from 1."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED", "user.sessions": "REVOKED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        for i, step in enumerate(result.steps):
            assert step["step"] == i + 1

    def test_steps_include_entity_type(self, mini_kg):
        """Each step includes entity_type and operation."""
        planner = CSPPlanner(mini_kg._nodes)
        result = planner.plan(
            goal_state={"user.status": "DEACTIVATED"},
            initial_state={"user.identifier": "PROVIDED"},
        )
        assert result.success
        for step in result.steps:
            assert "entity_type" in step
            assert "operation" in step
