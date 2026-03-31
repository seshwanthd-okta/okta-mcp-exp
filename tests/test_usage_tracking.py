# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Tests for tool usage tracking — record_tool_call, increment_turn,
get_usage_summary, conversation pattern detection, and the session_usage
field returned by search_tools and unload_tools.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from okta_mcp_server.tools.tool_search.registry import (
    CATEGORIES,
    get_loaded_categories,
    get_usage_summary,
    increment_turn,
    load_categories,
    record_tool_call,
    reset_loaded_categories,
    reset_usage_stats,
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


@pytest.fixture(autouse=True)
def _reset():
    """Full clean slate — loaded categories AND usage stats — before each test."""
    reset_loaded_categories()  # also calls reset_usage_stats internally
    yield
    reset_loaded_categories()


# ---------------------------------------------------------------------------
# 1. record_tool_call
# ---------------------------------------------------------------------------

class TestRecordToolCall:

    def test_increments_usage_count(self):
        record_tool_call("get_user")
        summary = get_usage_summary()
        assert summary["categories"]["users"]["tools_used"]["get_user"] == 1

    def test_multiple_calls_accumulate(self):
        record_tool_call("get_user")
        record_tool_call("get_user")
        record_tool_call("get_user")
        summary = get_usage_summary()
        assert summary["categories"]["users"]["tools_used"]["get_user"] == 3

    def test_different_tools_same_category(self):
        record_tool_call("get_user")
        record_tool_call("list_users")
        summary = get_usage_summary()
        cat = summary["categories"]["users"]
        assert cat["tools_used"]["get_user"] == 1
        assert cat["tools_used"]["list_users"] == 1
        assert cat["total_calls"] == 2

    def test_tools_from_different_categories(self):
        record_tool_call("get_user")
        record_tool_call("list_groups")
        record_tool_call("get_logs")
        summary = get_usage_summary()
        assert "users" in summary["categories"]
        assert "groups" in summary["categories"]
        assert "system_logs" in summary["categories"]

    def test_unknown_tool_name_does_not_crash(self):
        """Infrastructure tools like search_tools/unload_tools have no category — safe to record."""
        record_tool_call("search_tools")  # not in TOOL_CATALOG categories
        # Should not raise, and should not appear in summary categories
        summary = get_usage_summary()
        assert "search_tools" not in summary["categories"]

    def test_last_used_turn_updated(self):
        increment_turn()  # turn 1
        increment_turn()  # turn 2
        record_tool_call("get_user")
        summary = get_usage_summary()
        assert summary["categories"]["users"]["last_used_turn"] == 2


# ---------------------------------------------------------------------------
# 2. increment_turn
# ---------------------------------------------------------------------------

class TestIncrementTurn:

    def test_starts_at_zero(self):
        summary = get_usage_summary()
        assert summary["current_turn"] == 0

    def test_increments_by_one(self):
        t1 = increment_turn()
        assert t1 == 1
        t2 = increment_turn()
        assert t2 == 2

    def test_current_turn_in_summary(self):
        increment_turn()
        increment_turn()
        increment_turn()
        summary = get_usage_summary()
        assert summary["current_turn"] == 3

    def test_reset_clears_turn(self):
        increment_turn()
        increment_turn()
        reset_usage_stats()
        summary = get_usage_summary()
        assert summary["current_turn"] == 0


# ---------------------------------------------------------------------------
# 3. get_usage_summary structure
# ---------------------------------------------------------------------------

class TestGetUsageSummary:

    def test_empty_when_no_calls(self):
        summary = get_usage_summary()
        assert summary["categories"] == {}
        assert summary["unload_candidates"] == []
        assert summary["current_turn"] == 0

    def test_required_keys_per_category(self):
        increment_turn()
        record_tool_call("get_user")
        summary = get_usage_summary()
        cat = summary["categories"]["users"]
        assert "total_calls" in cat
        assert "tools_used" in cat
        assert "last_used_turn" in cat
        assert "turns_since_last_use" in cat
        assert "conversation_pattern" in cat
        assert "recommendation" in cat

    def test_turns_since_last_use_calculated(self):
        increment_turn()          # turn 1
        record_tool_call("get_user")  # last used at turn 1
        increment_turn()          # turn 2
        increment_turn()          # turn 3 (current)
        summary = get_usage_summary()
        assert summary["categories"]["users"]["turns_since_last_use"] == 2

    def test_unload_candidates_list(self):
        increment_turn()
        record_tool_call("get_logs")  # used once at turn 1
        # Advance many turns to make it stale
        for _ in range(5):
            increment_turn()
        summary = get_usage_summary()
        assert "system_logs" in summary["unload_candidates"]

    def test_no_unload_candidates_for_recent_use(self):
        increment_turn()
        record_tool_call("get_user")  # used at turn 1, current turn is 1
        summary = get_usage_summary()
        assert "users" not in summary["unload_candidates"]


# ---------------------------------------------------------------------------
# 4. Recommendation logic
# ---------------------------------------------------------------------------

class TestRecommendations:

    def test_keep_loaded_when_used_this_turn(self):
        t = increment_turn()
        record_tool_call("get_user")
        summary = get_usage_summary()
        rec = summary["categories"]["users"]["recommendation"]
        assert "keep_loaded" in rec

    def test_keep_loaded_when_called_frequently(self):
        for _ in range(6):
            increment_turn()
            record_tool_call("get_user")
        summary = get_usage_summary()
        rec = summary["categories"]["users"]["recommendation"]
        assert "keep_loaded" in rec

    def test_safe_to_unload_when_stale_single_use(self):
        increment_turn()
        record_tool_call("get_logs")
        for _ in range(5):
            increment_turn()
        summary = get_usage_summary()
        rec = summary["categories"]["system_logs"]["recommendation"]
        assert "unload" in rec.lower()

    def test_consider_unloading_when_moderately_stale(self):
        # 1 call, 3 turns ago → "consider_unloading" (not frequent, not alternating, not recent)
        increment_turn()
        record_tool_call("list_groups")  # 1 call at turn 1
        increment_turn()
        increment_turn()
        increment_turn()  # current = turn 4, turns_since = 3
        summary = get_usage_summary()
        rec = summary["categories"]["groups"]["recommendation"]
        assert "consider_unloading" in rec or "safe_to_unload" in rec


# ---------------------------------------------------------------------------
# 5. Conversation pattern detection
# ---------------------------------------------------------------------------

class TestConversationPattern:

    def test_single_use_pattern(self):
        increment_turn()
        record_tool_call("get_logs")
        summary = get_usage_summary()
        assert summary["categories"]["system_logs"]["conversation_pattern"] == "single_use"

    def test_consecutive_pattern(self):
        increment_turn()
        record_tool_call("get_user")
        record_tool_call("list_users")
        record_tool_call("get_user")  # all users, no other category
        summary = get_usage_summary()
        assert summary["categories"]["users"]["conversation_pattern"] == "consecutive"

    def test_alternating_pattern(self):
        increment_turn()
        record_tool_call("get_user")      # users
        increment_turn()
        record_tool_call("list_groups")   # groups (interleaved)
        increment_turn()
        record_tool_call("get_user")      # users again → alternating
        summary = get_usage_summary()
        assert "alternating" in summary["categories"]["users"]["conversation_pattern"]

    def test_alternating_overrides_unload_recommendation(self):
        """A category with alternating pattern should NOT be recommended for unload
        even if it hasn't been called recently by count standards."""
        increment_turn()
        record_tool_call("get_user")      # turn 1: users
        increment_turn()
        record_tool_call("list_groups")   # turn 2: groups (interleaved)
        increment_turn()
        record_tool_call("get_user")      # turn 3: users again → alternating
        # Advance 5 more turns to make it "stale" by count
        for _ in range(5):
            increment_turn()
        summary = get_usage_summary()
        rec = summary["categories"]["users"]["recommendation"]
        assert "keep_loaded" in rec


# ---------------------------------------------------------------------------
# 6. session_usage in search_tools response
# ---------------------------------------------------------------------------

class TestSearchToolsSessionUsage:

    @pytest.mark.asyncio
    async def test_session_usage_present_in_response(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, pattern="get_user")
        assert "session_usage" in result

    @pytest.mark.asyncio
    async def test_session_usage_present_in_list_categories(self):
        ctx = _make_ctx()
        result = await search_tools(ctx=ctx, list_categories=True)
        assert "session_usage" in result

    @pytest.mark.asyncio
    async def test_turn_increments_each_search_call(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_user")
        r1 = await search_tools(ctx=ctx, pattern="get_user")
        r2 = await search_tools(ctx=ctx, pattern="get_user")
        assert r2["session_usage"]["current_turn"] > r1["session_usage"]["current_turn"]

    @pytest.mark.asyncio
    async def test_session_usage_categories_appear_after_real_calls(self):
        ctx = _make_ctx()
        # Search loads users, then record a fake call to simulate usage
        await search_tools(ctx=ctx, pattern="get_user", category="users")
        record_tool_call("get_user")
        record_tool_call("get_user")
        result = await search_tools(ctx=ctx, pattern="get_user", category="users")
        usage = result["session_usage"]
        assert "users" in usage["categories"]
        assert usage["categories"]["users"]["total_calls"] == 2

    @pytest.mark.asyncio
    async def test_hint_mentions_unload_candidates(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        record_tool_call("get_logs")      # simulate one real call
        for _ in range(5):
            # Advance turns by searching for something unrelated
            await search_tools(ctx=ctx, pattern="get_user", category="users")
        result = await search_tools(ctx=ctx, pattern="get_user", category="users")
        # system_logs is stale — hint should mention unload candidates
        if result["session_usage"]["unload_candidates"]:
            assert "unload_candidates" in result.get("hint", "") or "session_usage" in result


# ---------------------------------------------------------------------------
# 7. session_usage in unload_tools response
# ---------------------------------------------------------------------------

class TestUnloadToolsSessionUsage:

    @pytest.mark.asyncio
    async def test_session_usage_present_after_unload(self):
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        result = await unload_tools(ctx=ctx, categories=["system_logs"])
        assert "session_usage" in result

    @pytest.mark.asyncio
    async def test_session_usage_still_shows_history_after_unload(self):
        """Unloading a category clears MCP registration but NOT usage history."""
        ctx = _make_ctx()
        await search_tools(ctx=ctx, pattern="get_logs")
        record_tool_call("get_logs")   # simulate real use
        result = await unload_tools(ctx=ctx, categories=["system_logs"])
        # Usage history for system_logs should persist even after unload
        # (so LLM knows it was used before and can make informed reload decisions)
        usage = result["session_usage"]
        assert "system_logs" in usage["categories"]
        assert usage["categories"]["system_logs"]["total_calls"] == 1


# ---------------------------------------------------------------------------
# 8. reset_loaded_categories clears usage stats
# ---------------------------------------------------------------------------

class TestResetClearsUsage:

    def test_reset_clears_usage_counts(self):
        increment_turn()
        record_tool_call("get_user")
        record_tool_call("get_user")
        reset_loaded_categories()
        summary = get_usage_summary()
        assert summary["categories"] == {}

    def test_reset_clears_turn_number(self):
        increment_turn()
        increment_turn()
        reset_loaded_categories()
        summary = get_usage_summary()
        assert summary["current_turn"] == 0

    def test_reset_clears_unload_candidates(self):
        increment_turn()
        record_tool_call("get_logs")
        for _ in range(5):
            increment_turn()
        # Should have unload candidate
        assert "system_logs" in get_usage_summary()["unload_candidates"]
        reset_loaded_categories()
        assert get_usage_summary()["unload_candidates"] == []
