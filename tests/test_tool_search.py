# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Tests for the tool_search module — search_tools MCP tool and registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from okta_mcp_server.tools.tool_search.registry import (
    CATEGORIES,
    TOOL_CATALOG,
    TOOL_NAMES,
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
    """Build a lightweight fake Context with an async session mock."""
    ctx = MagicMock()
    ctx.session = AsyncMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _reset_loader():
    """Reset loaded categories before each test so lazy-loading tests are isolated."""
    reset_loaded_categories()
    yield
    reset_loaded_categories()


# ---------------------------------------------------------------------------
# Registry sanity checks
# ---------------------------------------------------------------------------


class TestRegistry:
    """Verify that the static tool catalog is well-formed."""

    def test_catalog_not_empty(self):
        assert len(TOOL_CATALOG) > 0

    def test_every_entry_has_required_keys(self):
        required = {"name", "category", "description", "parameters", "tags"}
        for tool in TOOL_CATALOG:
            missing = required - tool.keys()
            assert not missing, f"Tool '{tool.get('name', '???')}' missing keys: {missing}"

    def test_no_duplicate_names(self):
        names = [t["name"] for t in TOOL_CATALOG]
        assert len(names) == len(set(names)), f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"

    def test_categories_index_matches_catalog(self):
        cats_from_catalog = sorted({t["category"] for t in TOOL_CATALOG})
        assert cats_from_catalog == CATEGORIES

    def test_tool_names_set(self):
        assert TOOL_NAMES == {t["name"] for t in TOOL_CATALOG}

    @pytest.mark.parametrize(
        "expected_category",
        ["users", "groups", "applications", "policies", "system_logs"],
    )
    def test_all_categories_present(self, expected_category):
        assert expected_category in CATEGORIES


# ---------------------------------------------------------------------------
# search_tools — list categories mode
# ---------------------------------------------------------------------------


class TestSearchToolsCategories:
    @pytest.mark.asyncio
    async def test_list_categories_returns_counts(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, list_categories=True)
        assert "categories" in result
        assert "total_tools" in result
        assert result["total_tools"] == len(TOOL_CATALOG)
        for cat in CATEGORIES:
            assert cat in result["categories"]

    @pytest.mark.asyncio
    async def test_list_categories_counts_sum(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, list_categories=True)
        assert sum(result["categories"].values()) == result["total_tools"]


# ---------------------------------------------------------------------------
# search_tools — pattern search
# ---------------------------------------------------------------------------


class TestSearchToolsPattern:
    @pytest.mark.asyncio
    async def test_empty_pattern_returns_all_up_to_limit(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="", limit=100)
        assert result["total_matches"] == len(TOOL_CATALOG)

    @pytest.mark.asyncio
    async def test_simple_keyword_search(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="user", limit=50)
        assert result["total_matches"] > 0
        for tool in result["tools"]:
            searchable = " ".join(
                [tool["name"], tool["description"], " ".join(tool["tags"]), " ".join(tool["parameters"].keys())]
            )
            assert "user" in searchable.lower()

    @pytest.mark.asyncio
    async def test_regex_alternation(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="delete|remove", limit=50)
        assert result["total_matches"] > 0
        names = {t["name"] for t in result["tools"]}
        # Should include delete and remove tools
        assert any("delete" in n for n in names)
        assert any("remove" in n for n in names)

    @pytest.mark.asyncio
    async def test_regex_prefix(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="^list", limit=50)
        names = {t["name"] for t in result["tools"]}
        for name in names:
            assert name.startswith("list")

    @pytest.mark.asyncio
    async def test_invalid_regex_returns_error(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="[invalid")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_matches(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="xyznonexistent")
        assert result["total_matches"] == 0
        assert result["tools"] == []
        assert "hint" in result


# ---------------------------------------------------------------------------
# search_tools — category filter
# ---------------------------------------------------------------------------


class TestSearchToolsCategory:
    @pytest.mark.asyncio
    async def test_filter_by_category(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, category="policies", limit=50)
        assert result["total_matches"] > 0
        for tool in result["tools"]:
            assert tool["category"] == "policies"

    @pytest.mark.asyncio
    async def test_unknown_category(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, category="nonexistent")
        assert result["total_matches"] == 0
        assert "available_categories" in result

    @pytest.mark.asyncio
    async def test_category_plus_pattern(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="list", category="groups", limit=50)
        assert result["total_matches"] > 0
        for tool in result["tools"]:
            assert tool["category"] == "groups"
            assert "list" in tool["name"]


# ---------------------------------------------------------------------------
# search_tools — limit / truncation
# ---------------------------------------------------------------------------


class TestSearchToolsLimit:
    @pytest.mark.asyncio
    async def test_default_limit_truncates(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern=".*", limit=3)
        assert len(result["tools"]) == 3
        assert result["total_matches"] > 3
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_large_limit_returns_all(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern=".*", limit=200)
        assert len(result["tools"]) == result["total_matches"]


# ---------------------------------------------------------------------------
# search_tools — specific tool lookups
# ---------------------------------------------------------------------------


class TestSearchToolsSpecific:
    @pytest.mark.asyncio
    async def test_find_get_logs(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="get_logs")
        assert result["total_matches"] == 1
        assert result["tools"][0]["name"] == "get_logs"
        assert result["tools"][0]["category"] == "system_logs"

    @pytest.mark.asyncio
    async def test_find_add_user_to_group(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="add_user_to_group")
        assert result["total_matches"] == 1
        tool = result["tools"][0]
        assert tool["name"] == "add_user_to_group"
        assert "group_id" in tool["parameters"]
        assert "user_id" in tool["parameters"]

    @pytest.mark.asyncio
    async def test_lifecycle_tools(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="activate|deactivate", limit=50)
        names = {t["name"] for t in result["tools"]}
        assert "activate_application" in names
        assert "deactivate_user" in names
        assert "activate_policy" in names
        assert "deactivate_policy_rule" in names


# ---------------------------------------------------------------------------
# Lazy-loading behavior
# ---------------------------------------------------------------------------


class TestLazyLoading:
    """Verify that search_tools triggers on-demand module loading."""

    def test_no_categories_loaded_initially(self):
        assert get_loaded_categories() == set()

    @pytest.mark.asyncio
    async def test_search_loads_matching_categories(self):
        ctx = _make_ctx()
        # Searching for "list_users" should load the 'users' category
        result = await search_tools(ctx=ctx, pattern="list_users", category="users")
        assert result["total_matches"] >= 1
        assert "users" in get_loaded_categories()

    @pytest.mark.asyncio
    async def test_sends_tool_list_changed_notification(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        # system_logs category should have been loaded, triggering a notification
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_notification_when_already_loaded(self):
        ctx = _make_ctx()
        # First call loads the category
        await search_tools(ctx=ctx, pattern="get_logs")
        ctx.session.send_tool_list_changed.assert_awaited_once()
        ctx.session.send_tool_list_changed.reset_mock()

        # Second call for same category — no new load, no notification
        await search_tools(ctx=ctx, pattern="get_logs")
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_categories_does_not_load_modules(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, list_categories=True)
        assert get_loaded_categories() == set()
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_matches_does_not_load_modules(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="xyznonexistent")
        assert get_loaded_categories() == set()

    def test_load_categories_is_idempotent(self):
        first = load_categories({"users"})
        assert first == {"users"}
        second = load_categories({"users"})
        assert second == set()  # already loaded

    def test_load_unknown_category(self):
        result = load_categories({"nonexistent"})
        assert result == set()
        assert "nonexistent" not in get_loaded_categories()


# ---------------------------------------------------------------------------
# Unloading behavior
# ---------------------------------------------------------------------------


class TestUnloading:
    """Verify that unload_tools removes tools and updates loaded state."""

    @pytest.mark.asyncio
    async def test_unload_removes_tools_from_loaded_set(self):
        """After loading then unloading, the category should no longer be loaded."""
        ctx = _make_ctx()
        # Load users
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        assert "users" in get_loaded_categories()

        # Unload users
        result = await unload_tools(ctx=ctx, categories=["users"])
        assert "users" in result["unloaded"]
        assert "users" not in get_loaded_categories()
        assert "users" not in result["still_loaded"]

    @pytest.mark.asyncio
    async def test_unload_sends_tool_list_changed(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        ctx.session.send_tool_list_changed.reset_mock()

        await unload_tools(ctx=ctx, categories=["system_logs"])
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unload_not_loaded_category_is_noop(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=["users"])
        assert result["unloaded"] == {}
        assert result["total_tools_removed"] == 0
        # No notification should be sent when nothing was unloaded
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unload_invalid_category_returns_error(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=["nonexistent"])
        assert "error" in result
        assert "nonexistent" in result["error"]

    @pytest.mark.asyncio
    async def test_unload_empty_list_returns_hint(self):
        ctx = _make_ctx()
        result = await unload_tools(ctx=ctx, categories=[])
        assert result["unloaded"] == {}
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_unload_returns_removed_tool_names(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        result = await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "system_logs" in result["unloaded"]
        assert "get_logs" in result["unloaded"]["system_logs"]

    @pytest.mark.asyncio
    async def test_unload_then_reload(self):
        """Unloaded categories can be re-loaded via search_tools."""
        ctx = _make_ctx()
        # Load
        await search_tools(ctx=ctx, pattern="get_logs")
        assert "system_logs" in get_loaded_categories()

        # Unload
        await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "system_logs" not in get_loaded_categories()

        # Reload
        ctx.session.send_tool_list_changed.reset_mock()
        await search_tools(ctx=ctx, pattern="get_logs")
        assert "system_logs" in get_loaded_categories()
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unload_selective_keeps_other_categories(self):
        """Unloading one category should not affect others."""
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        await search_tools(ctx=ctx, pattern="get_logs")
        assert "users" in get_loaded_categories()
        assert "system_logs" in get_loaded_categories()

        # Unload only system_logs
        await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "users" in get_loaded_categories()
        assert "system_logs" not in get_loaded_categories()

    @pytest.mark.asyncio
    async def test_unload_multiple_categories_at_once(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="list_users", category="users")
        await search_tools(ctx=ctx, pattern="get_logs")
        result = await unload_tools(ctx=ctx, categories=["users", "system_logs"])
        assert "users" in result["unloaded"]
        assert "system_logs" in result["unloaded"]
        assert get_loaded_categories() == set()

    def test_unload_categories_function_directly(self):
        """Test the registry-level unload_categories function."""
        load_categories({"users"})
        assert "users" in get_loaded_categories()

        unloaded = unload_categories({"users"})
        assert "users" in unloaded
        assert "users" not in get_loaded_categories()

    def test_unload_categories_skip_not_loaded(self):
        unloaded = unload_categories({"policies"})
        assert unloaded == {}
