# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Tests for the Dynamic Knowledge Graph Orchestrator.

Covers:
  1. KG construction — nodes, edges, no intents
  2. Dynamic queries — tools, callable, reachable, dependencies, path
  3. Execution chain building — LLM-provided sequence gets wired
  4. MCP tools — orchestrator_query_graph, orchestrator_build_plan,
                 orchestrator_execute, orchestrator_context
  5. End-to-end — query graph → build plan → execute → context
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_state():
    """Reset session and KG singleton before each test."""
    reset_session()
    reset_knowledge_graph()
    yield
    reset_session()
    reset_knowledge_graph()


@pytest.fixture
def kg() -> OktaKnowledgeGraph:
    """Return a freshly built knowledge graph."""
    return build_okta_knowledge_graph()


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
        FakeGroup(
            id=f"00g_grp{i+1}",
            profile=FakeGroup.Profile(name=names[i] if i < len(names) else f"Group-{i+1}"),
        )
        for i in range(n)
    ]


def _make_mock_client(
    user: FakeUser | None = None,
    groups: list | None = None,
    apps: list | None = None,
) -> AsyncMock:
    client = AsyncMock()
    if user is None:
        user = FakeUser()
    if groups is None:
        groups = _make_fake_groups()
    if apps is None:
        apps = [FakeAppLink(label="Slack"), FakeAppLink(label="Jira")]

    client.get_user.return_value = (user, MagicMock(), None)
    client.list_user_groups.return_value = (groups, MagicMock(), None)
    client.unassign_user_from_group.return_value = (MagicMock(), None)
    client.deactivate_user.return_value = (MagicMock(), None)
    client.list_app_links.return_value = (apps, MagicMock(), None)
    client.list_users.return_value = ([user], MagicMock(), None)
    client.suspend_user.return_value = (MagicMock(), None)
    client.activate_user.return_value = (MagicMock(), None, None)
    client.revoke_user_sessions.return_value = None
    return client


def _make_ctx():
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
# 1. Knowledge Graph Construction
# ===========================================================================

class TestKGConstruction:
    def test_graph_has_nodes(self, kg):
        assert kg.get_stats()["total_nodes"] >= 11

    def test_graph_has_connections(self, kg):
        assert kg.get_stats()["total_connections"] >= 9

    def test_no_intents_in_graph(self, kg):
        """The dynamic KG has NO predefined intents."""
        assert "total_intents" not in kg.get_stats()

    def test_get_user_node_exists(self, kg):
        node = kg.get_node("get_user")
        assert node is not None
        assert node.entity_type == EntityType.USER
        assert node.operation == OperationType.READ
        assert "user_id" in node.required_params

    def test_node_has_tags(self, kg):
        node = kg.get_node("get_user")
        assert len(node.tags) > 0
        assert "lookup" in node.tags

    def test_deactivate_user_is_destructive(self, kg):
        node = kg.get_node("deactivate_user")
        assert node.is_destructive is True

    def test_remove_user_from_group_has_iteration_binding(self, kg):
        node = kg.get_node("remove_user_from_group")
        assert node.param_bindings.get("group_id") == "user.groups[]"

    def test_enriched_outputs(self, kg):
        node = kg.get_node("get_user")
        assert isinstance(node.outputs, dict)
        assert node.outputs["id"] == "user.id"
        assert node.outputs["status"] == "user.status"

    def test_param_bindings(self, kg):
        node = kg.get_node("deactivate_user")
        assert node.param_bindings == {"user_id": "user.id"}

    def test_virtual_adjacency_downstream(self, kg):
        downstream = kg.get_downstream("get_user")
        assert "deactivate_user" in downstream
        assert "list_user_groups" in downstream

    def test_virtual_adjacency_upstream(self, kg):
        upstream = kg.get_upstream("deactivate_user")
        assert "get_user" in upstream

    def test_to_dict_serialisation(self, kg):
        data = kg.to_dict()
        assert "nodes" in data
        assert "get_user" in data["nodes"]
        # No edges key in the new model
        assert "edges" not in data

    def test_singleton(self):
        kg1 = get_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is kg2

    def test_reset_singleton(self):
        kg1 = get_knowledge_graph()
        reset_knowledge_graph()
        kg2 = get_knowledge_graph()
        assert kg1 is not kg2


# ===========================================================================
# 2. Dynamic Queries
# ===========================================================================

class TestQueryTools:
    def test_filter_by_entity(self, kg):
        tools = kg.query_tools(entity_type="user")
        assert len(tools) >= 5
        assert all(t["entity_type"] == "user" for t in tools)

    def test_filter_by_operation(self, kg):
        reads = kg.query_tools(operation="read")
        assert len(reads) >= 4
        assert all(t["operation"] == "read" for t in reads)

    def test_filter_by_tag(self, kg):
        lookups = kg.query_tools(tag="lookup")
        assert len(lookups) >= 1
        assert any(t["action"] == "get_user" for t in lookups)

    def test_combined_filter(self, kg):
        destructive_user = kg.query_tools(entity_type="user", operation="write")
        assert len(destructive_user) >= 3

    def test_no_results(self, kg):
        tools = kg.query_tools(entity_type="nonexistent")
        assert tools == []


class TestQueryCallable:
    def test_with_user_id(self, kg):
        tools = kg.query_callable_tools(["user_id"])
        actions = [t["action"] for t in tools]
        assert "get_user" in actions
        assert "deactivate_user" in actions
        assert "list_user_groups" in actions

    def test_with_no_params(self, kg):
        tools = kg.query_callable_tools([])
        actions = [t["action"] for t in tools]
        # Tools with no required params should be callable
        assert "list_users" in actions
        assert "get_group" in actions

    def test_with_both_params(self, kg):
        tools = kg.query_callable_tools(["user_id", "group_id"])
        actions = [t["action"] for t in tools]
        assert "remove_user_from_group" in actions
        assert "add_user_to_group" in actions


class TestQueryReachable:
    def test_from_get_user(self, kg):
        result = kg.query_reachable("get_user")
        actions = [n["action"] for n in result["nodes"]]
        assert "get_user" in actions  # includes start
        assert "deactivate_user" in actions
        assert "list_user_groups" in actions
        assert "remove_user_from_group" in actions

    def test_depth_info(self, kg):
        result = kg.query_reachable("get_user")
        start_node = next(n for n in result["nodes"] if n["action"] == "get_user")
        assert start_node["depth"] == 0
        deact = next(n for n in result["nodes"] if n["action"] == "deactivate_user")
        assert deact["depth"] == 1

    def test_has_downstream(self, kg):
        result = kg.query_reachable("get_user")
        assert len(result["nodes"]) >= 3

    def test_unknown_action(self, kg):
        result = kg.query_reachable("nonexistent")
        assert "error" in result

    def test_max_depth(self, kg):
        result = kg.query_reachable("get_user", max_depth=1)
        depths = [n["depth"] for n in result["nodes"]]
        assert max(depths) <= 1


class TestQueryDependencies:
    def test_deactivate_user_deps(self, kg):
        result = kg.query_dependencies("deactivate_user")
        actions = [n["action"] for n in result["nodes"]]
        assert "deactivate_user" in actions
        assert "get_user" in actions

    def test_remove_from_group_deps(self, kg):
        result = kg.query_dependencies("remove_user_from_group")
        actions = [n["action"] for n in result["nodes"]]
        assert "get_user" in actions
        assert "list_user_groups" in actions

    def test_unknown_action(self, kg):
        result = kg.query_dependencies("nonexistent")
        assert "error" in result


class TestQueryPath:
    def test_get_user_to_deactivate(self, kg):
        path = kg.query_path("get_user", "deactivate_user")
        assert path is not None
        assert len(path) == 2  # [get_user, deactivate_user]
        assert path[0] == "get_user"
        assert path[1] == "deactivate_user"

    def test_get_user_to_remove_from_group(self, kg):
        path = kg.query_path("get_user", "remove_user_from_group")
        assert path is not None
        assert path[0] == "get_user"
        assert path[-1] == "remove_user_from_group"

    def test_no_path(self, kg):
        path = kg.query_path("deactivate_user", "get_user")
        assert path is None

    def test_unknown_action(self, kg):
        path = kg.query_path("nonexistent", "get_user")
        assert path is None


# ===========================================================================
# 3. Execution Chain Building
# ===========================================================================

class TestBuildExecutionChain:
    def test_simple_chain(self, kg):
        steps = kg.build_execution_chain(["get_user", "deactivate_user"])
        assert len(steps) == 2
        assert steps[0]["action"] == "get_user"
        assert steps[1]["action"] == "deactivate_user"
        assert steps[1]["params"]["user_id"] == "$step1.id"

    def test_for_each_wiring(self, kg):
        steps = kg.build_execution_chain([
            "get_user", "list_user_groups", "remove_user_from_group",
        ])
        assert steps[2]["for_each"] == "$step2"
        assert steps[2]["params"]["user_id"] == "$step1.id"

    def test_five_step_offboard(self, kg):
        steps = kg.build_execution_chain([
            "get_user", "list_user_groups", "remove_user_from_group",
            "list_user_app_assignments", "deactivate_user",
        ])
        assert len(steps) == 5
        assert steps[1]["params"]["user_id"] == "$step1.id"
        assert steps[2]["for_each"] == "$step2"
        assert steps[3]["params"]["user_id"] == "$step1.id"
        assert steps[4]["params"]["user_id"] == "$step1.id"

    def test_suspend_chain(self, kg):
        steps = kg.build_execution_chain([
            "get_user", "clear_user_sessions", "suspend_user",
        ])
        assert len(steps) == 3
        assert steps[1]["params"]["user_id"] == "$step1.id"
        assert steps[2]["params"]["user_id"] == "$step1.id"

    def test_unknown_action_raises(self, kg):
        with pytest.raises(ValueError, match="Unknown action"):
            kg.build_execution_chain(["get_user", "nonexistent"])

    def test_step_numbering(self, kg):
        steps = kg.build_execution_chain(["get_user", "list_user_groups"])
        assert steps[0]["step"] == 1
        assert steps[1]["step"] == 2

    def test_destructive_flag_preserved(self, kg):
        steps = kg.build_execution_chain(["get_user", "deactivate_user"])
        assert steps[0]["is_destructive"] is False
        assert steps[1]["is_destructive"] is True


# ===========================================================================
# 4. MCP Tool: orchestrator_query_graph
# ===========================================================================

class TestQueryGraphTool:
    @pytest.mark.asyncio
    async def test_query_tools(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="tools", entity_type="user")
        assert "tools" in result
        assert result["count"] >= 5

    @pytest.mark.asyncio
    async def test_query_callable(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="callable", available_params="user_id")
        assert "callable_tools" in result
        assert result["count"] >= 5

    @pytest.mark.asyncio
    async def test_query_reachable(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="reachable", start_action="get_user")
        assert "nodes" in result

    @pytest.mark.asyncio
    async def test_query_dependencies(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="dependencies", action="deactivate_user")
        assert "nodes" in result
        actions = [n["action"] for n in result["nodes"]]
        assert "get_user" in actions

    @pytest.mark.asyncio
    async def test_query_path(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(
            ctx, query_type="path", start_action="get_user", end_action="deactivate_user",
        )
        assert "path" in result
        assert result["length"] == 2

    @pytest.mark.asyncio
    async def test_query_node(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="node", action="get_user")
        assert "node" in result
        assert result["node"]["action"] == "get_user"
        assert "upstream" in result
        assert "downstream" in result

    @pytest.mark.asyncio
    async def test_query_stats(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="stats")
        assert "total_nodes" in result

    @pytest.mark.asyncio
    async def test_query_full(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="full")
        assert "nodes" in result

    @pytest.mark.asyncio
    async def test_unknown_query_type(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="bogus")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_reachable_missing_start(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_query_graph
        ctx = _make_ctx()
        result = await orchestrator_query_graph(ctx, query_type="reachable")
        assert "error" in result


# ===========================================================================
# 5. MCP Tool: orchestrator_build_plan
# ===========================================================================

class TestBuildPlanTool:
    @pytest.mark.asyncio
    async def test_build_offboard_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx,
            actions="get_user,list_user_groups,remove_user_from_group,list_user_app_assignments,deactivate_user",
            target_identifier="john@acme.com",
            workflow_name="offboard",
        )
        assert "plan" in result
        assert result["plan"]["total_steps"] == 5
        assert "wiring" in result

    @pytest.mark.asyncio
    async def test_build_suspend_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx,
            actions="get_user,clear_user_sessions,suspend_user",
            target_identifier="jane@acme.com",
        )
        assert result["plan"]["total_steps"] == 3

    @pytest.mark.asyncio
    async def test_build_with_unknown_action(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx, actions="get_user,bogus_action", target_identifier="x",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_build_empty_actions(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(ctx, actions="", target_identifier="x")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_plan_has_correct_wiring(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx, actions="get_user,deactivate_user", target_identifier="john@acme.com",
        )
        wiring = result["wiring"]
        assert wiring[0]["params"]["user_id"] == "john@acme.com"
        assert wiring[1]["params"]["user_id"] == "$step1.id"

    @pytest.mark.asyncio
    async def test_plan_registers_in_session(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        await orchestrator_build_plan(
            ctx, actions="get_user,deactivate_user", target_identifier="x",
        )
        session = get_session()
        assert len(session.plans) == 1

    @pytest.mark.asyncio
    async def test_destructive_plan_requires_approval(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx, actions="get_user,deactivate_user", target_identifier="x",
        )
        assert result["plan"]["requires_approval"] is True
        assert result["plan"]["status"] == "awaiting_approval"
        assert "Requires approval" in result["hint"]

    @pytest.mark.asyncio
    async def test_non_destructive_plan_no_approval(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_build_plan
        ctx = _make_ctx()
        result = await orchestrator_build_plan(
            ctx, actions="get_user,list_user_groups", target_identifier="x",
        )
        assert result["plan"]["requires_approval"] is False
        assert result["plan"]["status"] == "draft"
        assert "Safe to execute" in result["hint"]


# ===========================================================================
# 6. MCP Tool: orchestrator_execute
# ===========================================================================

class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_execute_plan(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_execute,
        )
        ctx = _make_ctx()
        mock_client = _make_mock_client()

        build_result = await orchestrator_build_plan(
            ctx,
            actions="get_user,list_user_groups,remove_user_from_group,deactivate_user",
            target_identifier="john@acme.com",
        )
        plan_id = build_result["plan"]["plan_id"]

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            exec_result = await orchestrator_execute(ctx, plan_id=plan_id)

        assert "summary" in exec_result
        assert exec_result["summary"]["status"] in ("completed", "partial")

    @pytest.mark.asyncio
    async def test_execute_nonexistent(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_execute
        ctx = _make_ctx()
        result = await orchestrator_execute(ctx, plan_id="plan_nope")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_double_execute_fails(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_execute,
        )
        ctx = _make_ctx()
        mock_client = _make_mock_client()

        build_result = await orchestrator_build_plan(
            ctx, actions="get_user,suspend_user", target_identifier="x",
        )
        plan_id = build_result["plan"]["plan_id"]

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            await orchestrator_execute(ctx, plan_id=plan_id)

        result = await orchestrator_execute(ctx, plan_id=plan_id)
        assert "error" in result
        assert "cannot be executed" in result["error"]


# ===========================================================================
# 7. MCP Tool: orchestrator_context
# ===========================================================================

class TestContextTool:
    @pytest.mark.asyncio
    async def test_empty_session(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import orchestrator_context
        ctx = _make_ctx()
        result = await orchestrator_context(ctx)
        assert "session" in result
        assert "graph_stats" in result
        assert result["session"]["total_api_calls"] == 0

    @pytest.mark.asyncio
    async def test_after_build(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_context,
        )
        ctx = _make_ctx()
        await orchestrator_build_plan(
            ctx, actions="get_user,deactivate_user", target_identifier="x",
        )
        result = await orchestrator_context(ctx)
        assert len(result["active_plans"]) == 1


# ===========================================================================
# 8. End-to-End
# ===========================================================================

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_dynamic_offboard(self):
        """LLM queries graph → discovers tools → builds plan → executes."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_context,
            orchestrator_execute,
            orchestrator_query_graph,
        )

        ctx = _make_ctx()
        mock_client = _make_mock_client()

        # 1. Query: what user tools exist?
        tools_result = await orchestrator_query_graph(ctx, query_type="tools", entity_type="user")
        assert tools_result["count"] >= 5

        # 2. Query: what's reachable from get_user?
        reach_result = await orchestrator_query_graph(ctx, query_type="reachable", start_action="get_user")
        reachable_actions = [n["action"] for n in reach_result["nodes"]]
        assert "deactivate_user" in reachable_actions
        assert "list_user_groups" in reachable_actions

        # 3. Build plan (LLM decides: offboard = lookup → groups → remove → apps → deactivate)
        build_result = await orchestrator_build_plan(
            ctx,
            actions="get_user,list_user_groups,remove_user_from_group,list_user_app_assignments,deactivate_user",
            target_identifier="john@acme.com",
            workflow_name="offboard",
            description="Offboard john",
        )
        assert build_result["plan"]["total_steps"] == 5
        plan_id = build_result["plan"]["plan_id"]

        # 4. Execute
        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            exec_result = await orchestrator_execute(ctx, plan_id=plan_id)

        assert exec_result["summary"]["status"] in ("completed", "partial")
        assert len(exec_result["context"]["actions_taken"]) >= 3

        # 5. Context
        ctx_result = await orchestrator_context(ctx)
        assert ctx_result["session"]["total_api_calls"] >= 3

    @pytest.mark.asyncio
    async def test_full_dynamic_suspend(self):
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_execute,
        )

        ctx = _make_ctx()
        mock_client = _make_mock_client()

        build_result = await orchestrator_build_plan(
            ctx,
            actions="get_user,clear_user_sessions,suspend_user",
            target_identifier="jane@acme.com",
        )
        plan_id = build_result["plan"]["plan_id"]

        with patch(
            "okta_mcp_server.tools.orchestrator.engine.get_okta_client",
            return_value=mock_client,
        ):
            exec_result = await orchestrator_execute(ctx, plan_id=plan_id)

        assert exec_result["summary"]["status"] in ("completed", "partial")

    @pytest.mark.asyncio
    async def test_dependency_driven_discovery(self):
        """LLM asks 'what do I need before deactivate_user?' and builds from that."""
        from okta_mcp_server.tools.orchestrator.orchestrator_kg import (
            orchestrator_build_plan,
            orchestrator_query_graph,
        )

        ctx = _make_ctx()

        # Discover dependencies
        deps = await orchestrator_query_graph(ctx, query_type="dependencies", action="deactivate_user")
        dep_actions = [n["action"] for n in deps["nodes"]]
        assert "get_user" in dep_actions

        # Build minimal plan: prereq → target
        result = await orchestrator_build_plan(
            ctx, actions="get_user,deactivate_user", target_identifier="x",
        )
        assert result["plan"]["total_steps"] == 2
        assert result["wiring"][1]["params"]["user_id"] == "$step1.id"
