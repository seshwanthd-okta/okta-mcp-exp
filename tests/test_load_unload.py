# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Test suite for dynamic tool loading and unloading.

Covers:
- MCP tool registration state after load (tools actually callable)
- MCP tool removal state after unload (tools actually gone)
- Tool counts per category
- Multi-cycle load → unload → reload
- Partial unloads (one category out of many)
- All 5 categories individually
- Notification behaviour (sent only when state changes)
- still_loaded and total_tools_removed accuracy
- Startup tools (search_tools, unload_tools) are never affected
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from okta_mcp_server.server import mcp
from okta_mcp_server.tools.tool_search.registry import (
    CATEGORIES,
    TOOL_CATALOG,
    get_loaded_categories,
    load_categories,
    reset_loaded_categories,
    unload_categories,
)
from okta_mcp_server.tools.tool_search.tool_search import search_tools, unload_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx():
    ctx = MagicMock()
    ctx.session = AsyncMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    return ctx


def _registered_tool_names() -> set[str]:
    """Return the set of tool names currently registered on the MCP instance."""
    return {t.name for t in mcp._tool_manager.list_tools()}


def _catalog_tools_for(category: str) -> list[str]:
    """Return the tool names listed in TOOL_CATALOG for a given category."""
    return [t["name"] for t in TOOL_CATALOG if t["category"] == category]


@pytest.fixture(autouse=True)
def _reset():
    """Clean slate before and after every test."""
    reset_loaded_categories()
    yield
    reset_loaded_categories()


# ---------------------------------------------------------------------------
# 1. MCP Registration After Load
# ---------------------------------------------------------------------------

class TestMCPRegistrationAfterLoad:
    """After load_categories(), the tools must be reachable on the MCP instance."""

    @pytest.mark.parametrize("category", ["users", "groups", "applications", "policies", "system_logs"])
    def test_tools_appear_on_mcp_after_load(self, category):
        expected = set(_catalog_tools_for(category))
        load_categories({category})
        registered = _registered_tool_names()
        missing = expected - registered
        assert not missing, f"Category '{category}': tools not on MCP after load: {missing}"

    @pytest.mark.parametrize("category", ["users", "groups", "applications", "policies", "system_logs"])
    def test_tool_count_matches_catalog(self, category):
        expected_count = len(_catalog_tools_for(category))
        load_categories({category})
        # Count how many of this category's tools are registered
        registered = _registered_tool_names()
        loaded_count = sum(1 for name in _catalog_tools_for(category) if name in registered)
        assert loaded_count == expected_count, (
            f"Category '{category}': expected {expected_count} tools, found {loaded_count} on MCP"
        )

    def test_loading_multiple_categories_registers_all(self):
        load_categories({"users", "system_logs"})
        registered = _registered_tool_names()
        for cat in ("users", "system_logs"):
            for name in _catalog_tools_for(cat):
                assert name in registered, f"Tool '{name}' ({cat}) not on MCP"

    def test_load_all_categories_registers_all_forty(self):
        load_categories(set(CATEGORIES))
        registered = _registered_tool_names()
        for tool in TOOL_CATALOG:
            assert tool["name"] in registered, f"Tool '{tool['name']}' missing from MCP"

    def test_loaded_categories_set_updated(self):
        load_categories({"groups", "policies"})
        loaded = get_loaded_categories()
        assert "groups" in loaded
        assert "policies" in loaded

    def test_startup_tools_always_registered(self):
        """search_tools and unload_tools are registered at startup and never go away."""
        registered = _registered_tool_names()
        assert "search_tools" in registered
        assert "unload_tools" in registered


# ---------------------------------------------------------------------------
# 2. MCP De-registration After Unload
# ---------------------------------------------------------------------------

class TestMCPDeregistrationAfterUnload:
    """After unload_categories(), the tools must be absent from the MCP instance."""

    @pytest.mark.parametrize("category", ["users", "groups", "applications", "policies", "system_logs"])
    def test_tools_gone_from_mcp_after_unload(self, category):
        load_categories({category})
        unload_categories({category})
        registered = _registered_tool_names()
        for name in _catalog_tools_for(category):
            assert name not in registered, f"Tool '{name}' still on MCP after unload of '{category}'"

    def test_unload_does_not_affect_other_categories(self):
        load_categories({"users", "groups"})
        unload_categories({"groups"})
        registered = _registered_tool_names()
        # groups tools gone
        for name in _catalog_tools_for("groups"):
            assert name not in registered
        # users tools still present
        for name in _catalog_tools_for("users"):
            assert name in registered

    def test_unload_updates_loaded_categories_set(self):
        load_categories({"users", "groups"})
        unload_categories({"users"})
        loaded = get_loaded_categories()
        assert "users" not in loaded
        assert "groups" in loaded

    def test_unload_not_loaded_is_noop(self):
        """Unloading a category that was never loaded changes nothing."""
        before = _registered_tool_names()
        result = unload_categories({"policies"})
        after = _registered_tool_names()
        assert result == {}
        assert before == after

    def test_startup_tools_survive_full_unload(self):
        """search_tools and unload_tools must remain even after unloading all categories."""
        load_categories(set(CATEGORIES))
        unload_categories(set(CATEGORIES))
        registered = _registered_tool_names()
        assert "search_tools" in registered
        assert "unload_tools" in registered

    def test_total_tools_removed_count(self):
        load_categories({"users", "system_logs"})
        expected = len(_catalog_tools_for("users")) + len(_catalog_tools_for("system_logs"))
        result = unload_categories({"users", "system_logs"})
        actual = sum(len(names) for names in result.values())
        assert actual == expected

    def test_unload_result_lists_correct_tool_names(self):
        load_categories({"system_logs"})
        result = unload_categories({"system_logs"})
        assert "system_logs" in result
        expected = set(_catalog_tools_for("system_logs"))
        assert expected == set(result["system_logs"])


# ---------------------------------------------------------------------------
# 3. Multi-Cycle Load → Unload → Reload
# ---------------------------------------------------------------------------

class TestMultiCycle:
    """Verify that load → unload → reload cycles work correctly."""

    @pytest.mark.parametrize("category", ["users", "groups", "system_logs"])
    def test_single_category_three_cycles(self, category):
        expected = set(_catalog_tools_for(category))
        for cycle in range(3):
            load_categories({category})
            registered = _registered_tool_names()
            missing = expected - registered
            assert not missing, f"Cycle {cycle}: tools missing after load: {missing}"

            unload_categories({category})
            registered = _registered_tool_names()
            leftover = expected & registered
            assert not leftover, f"Cycle {cycle}: tools still present after unload: {leftover}"

    def test_all_categories_cycle(self):
        """Load all, unload all, reload all — tools must match each time."""
        all_tools = {t["name"] for t in TOOL_CATALOG}

        load_categories(set(CATEGORIES))
        assert all_tools <= _registered_tool_names()

        unload_categories(set(CATEGORIES))
        registered_after_unload = _registered_tool_names()
        assert all_tools.isdisjoint(registered_after_unload)

        load_categories(set(CATEGORIES))
        assert all_tools <= _registered_tool_names()

    @pytest.mark.asyncio
    async def test_search_unload_search_cycle(self):
        """search_tools → unload_tools → search_tools — tools reappear on MCP."""
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        assert "system_logs" in get_loaded_categories()
        assert "get_logs" in _registered_tool_names()

        await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "system_logs" not in get_loaded_categories()
        assert "get_logs" not in _registered_tool_names()

        ctx.session.send_tool_list_changed.reset_mock()
        await search_tools(ctx=ctx, pattern="get_logs")
        assert "system_logs" in get_loaded_categories()
        assert "get_logs" in _registered_tool_names()
        ctx.session.send_tool_list_changed.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. Notification Behaviour
# ---------------------------------------------------------------------------

class TestNotificationBehaviour:
    """tools/list_changed must be sent when state changes, and not otherwise."""

    @pytest.mark.asyncio
    async def test_load_sends_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users")
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_load_already_loaded_no_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users")
        ctx.session.send_tool_list_changed.reset_mock()
        await search_tools(ctx=ctx, pattern="list_users")
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unload_sends_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users")
        ctx.session.send_tool_list_changed.reset_mock()
        await unload_tools(ctx=ctx, categories=["users"])
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unload_not_loaded_no_notification(self):
        ctx = _make_ctx()
        await unload_tools(ctx=ctx, categories=["groups"])
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_match_search_no_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="xyznonexistent123")
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_categories_no_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, list_categories=True)
        ctx.session.send_tool_list_changed.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. still_loaded and total_tools_removed accuracy
# ---------------------------------------------------------------------------

class TestResponseAccuracy:
    """Result fields from unload_tools must accurately reflect server state."""

    @pytest.mark.asyncio
    async def test_still_loaded_reflects_actual_state(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        await search_tools(ctx=ctx, pattern="get_logs")

        result = await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "users" in result["still_loaded"]
        assert "system_logs" not in result["still_loaded"]

    @pytest.mark.asyncio
    async def test_still_loaded_empty_after_full_unload(self):
        ctx = _make_ctx()
        for cat in CATEGORIES:
            await search_tools(ctx=ctx, pattern=f".*", category=cat)

        all_cats = list(CATEGORIES)
        result = await unload_tools(ctx=ctx, categories=all_cats)
        assert result["still_loaded"] == []

    @pytest.mark.asyncio
    async def test_total_tools_removed_is_correct(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        await search_tools(ctx=ctx, pattern="get_logs")

        expected = len(_catalog_tools_for("users")) + len(_catalog_tools_for("system_logs"))
        result = await unload_tools(ctx=ctx, categories=["users", "system_logs"])
        assert result["total_tools_removed"] == expected

    @pytest.mark.asyncio
    async def test_unloaded_dict_contains_all_tool_names(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")

        result = await unload_tools(ctx=ctx, categories=["system_logs"])
        expected = set(_catalog_tools_for("system_logs"))
        assert set(result["unloaded"]["system_logs"]) == expected

    @pytest.mark.asyncio
    async def test_unload_empty_categories_list(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=[])
        assert result["unloaded"] == {}
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_unload_invalid_category_error(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=["does_not_exist"])
        assert "error" in result
        assert "valid_categories" in result

    @pytest.mark.asyncio
    async def test_unload_not_loaded_zero_removed(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=["policies"])
        assert result["total_tools_removed"] == 0
        assert result["unloaded"] == {}


# ---------------------------------------------------------------------------
# 6. Per-Category Tool Count Integrity
# ---------------------------------------------------------------------------

class TestPerCategoryToolCounts:
    """Each category must load exactly the number of tools listed in TOOL_CATALOG."""

    @pytest.mark.parametrize("category", ["users", "groups", "applications", "policies", "system_logs"])
    def test_load_registers_exact_count(self, category):
        catalog_count = len(_catalog_tools_for(category))
        load_categories({category})
        registered = _registered_tool_names()
        loaded_count = sum(1 for name in _catalog_tools_for(category) if name in registered)
        assert loaded_count == catalog_count

    @pytest.mark.parametrize("category", ["users", "groups", "applications", "policies", "system_logs"])
    def test_unload_removes_exact_count(self, category):
        catalog_count = len(_catalog_tools_for(category))
        load_categories({category})
        result = unload_categories({category})
        removed_count = len(result.get(category, []))
        assert removed_count == catalog_count

    def test_total_catalog_is_106(self):
        assert len(TOOL_CATALOG) == 106

    def test_twelve_categories_exist(self):
        assert len(CATEGORIES) == 12

    def test_each_category_has_at_least_one_tool(self):
        for cat in CATEGORIES:
            count = len(_catalog_tools_for(cat))
            assert count >= 1, f"Category '{cat}' has no tools in TOOL_CATALOG"


# ---------------------------------------------------------------------------
# 7. Idempotency and Edge Cases
# ---------------------------------------------------------------------------

class TestIdempotencyAndEdgeCases:
    """Guard against double-loading, double-unloading, and boundary conditions."""

    def test_load_same_category_twice_is_idempotent(self):
        first = load_categories({"users"})
        second = load_categories({"users"})
        assert first == {"users"}
        assert second == set()  # nothing new on second call

    def test_load_then_double_unload_is_safe(self):
        load_categories({"users"})
        unload_categories({"users"})
        # Second unload of an already-unloaded category — must not raise
        result = unload_categories({"users"})
        assert result == {}

    def test_mcp_tool_count_stable_after_reload(self):
        """Same number of tools registered after reload as after first load."""
        load_categories({"groups"})
        count_first = sum(1 for name in _catalog_tools_for("groups") if name in _registered_tool_names())
        unload_categories({"groups"})
        load_categories({"groups"})
        count_second = sum(1 for name in _catalog_tools_for("groups") if name in _registered_tool_names())
        assert count_first == count_second

    def test_unknown_category_to_load_does_nothing(self):
        before = _registered_tool_names()
        result = load_categories({"nonexistent_category"})
        assert result == set()
        assert _registered_tool_names() == before

    def test_reset_clears_all_loaded_categories(self):
        load_categories(set(CATEGORIES))
        assert len(get_loaded_categories()) == 12
        reset_loaded_categories()
        assert get_loaded_categories() == set()

    def test_reset_removes_tools_from_mcp(self):
        load_categories({"users", "groups"})
        reset_loaded_categories()
        registered = _registered_tool_names()
        for tool in TOOL_CATALOG:
            if tool["category"] in ("users", "groups"):
                assert tool["name"] not in registered

    @pytest.mark.asyncio
    async def test_search_pattern_drives_correct_category_load(self):
        """search_tools with a users-specific category filter must load only users."""
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        assert get_loaded_categories() == {"users"}

    @pytest.mark.asyncio
    async def test_unload_mixed_valid_and_invalid_returns_error(self):
        """Any invalid category in the list causes an error — no partial unload."""
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        result = await unload_tools(ctx=ctx, categories=["users", "badcat"])
        assert "error" in result
        # users should still be loaded since the call was rejected
        assert "users" in get_loaded_categories()
