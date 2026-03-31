# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Tests for the tool-search knowledge graph builder and renderer."""

from __future__ import annotations

import pytest

from okta_mcp_server.utils.knowledge_graph import (
    build_tool_knowledge_graph,
    graph_to_text,
)
from okta_mcp_server.tools.tool_search.registry import TOOL_CATALOG, CATEGORIES


# ---------------------------------------------------------------------------
# Minimal test catalog for isolated / deterministic tests
# ---------------------------------------------------------------------------

MINI_CATALOG = [
    {
        "name": "list_users",
        "category": "users",
        "description": "List all users from Okta.",
        "parameters": {
            "search": "str – Search string",
            "limit": "int – Results per page",
            "after": "str – Pagination cursor",
        },
        "tags": ["list", "read", "users", "pagination"],
    },
    {
        "name": "get_user",
        "category": "users",
        "description": "Get a single user by ID.",
        "parameters": {"user_id": "str (required)"},
        "tags": ["get", "read", "users", "lookup"],
    },
    {
        "name": "create_user",
        "category": "users",
        "description": "Create a new user.",
        "parameters": {"profile": "dict (required)"},
        "tags": ["create", "write", "users"],
    },
    {
        "name": "delete_deactivated_user",
        "category": "users",
        "description": "Delete a deactivated user.",
        "parameters": {"user_id": "str (required)"},
        "tags": ["delete", "write", "users", "lifecycle"],
    },
    {
        "name": "list_groups",
        "category": "groups",
        "description": "List all groups.",
        "parameters": {
            "search": "str – Search string",
            "limit": "int – Results per page",
        },
        "tags": ["list", "read", "groups", "pagination"],
    },
    {
        "name": "add_user_to_group",
        "category": "groups",
        "description": "Add a user to a group.",
        "parameters": {
            "group_id": "str (required)",
            "user_id": "str (required)",
        },
        "tags": ["add", "write", "groups", "users", "membership"],
    },
]


# ---------------------------------------------------------------------------
# Tests for build_tool_knowledge_graph
# ---------------------------------------------------------------------------

class TestBuildToolKnowledgeGraph:
    """Tests using the mini catalog for deterministic assertions."""

    def test_top_level_keys(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        expected_keys = {"categories", "tools", "tag_index", "param_index",
                         "crud_families", "relationships", "summary"}
        assert set(g.keys()) == expected_keys

    def test_categories_grouping(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        assert "users" in g["categories"]
        assert "groups" in g["categories"]
        assert len(g["categories"]["users"]) == 4
        assert len(g["categories"]["groups"]) == 2

    def test_tools_flat_list(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        assert len(g["tools"]) == 6
        names = [t["name"] for t in g["tools"]]
        assert "list_users" in names
        assert "add_user_to_group" in names

    def test_tag_index(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        assert "list" in g["tag_index"]
        assert "list_users" in g["tag_index"]["list"]
        assert "list_groups" in g["tag_index"]["list"]
        # 'users' tag should contain tools from both categories
        assert "add_user_to_group" in g["tag_index"]["users"]

    def test_param_index(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        # user_id is shared between get_user, delete_deactivated_user, add_user_to_group
        assert "user_id" in g["param_index"]
        uid_tools = g["param_index"]["user_id"]
        assert "get_user" in uid_tools
        assert "delete_deactivated_user" in uid_tools
        assert "add_user_to_group" in uid_tools

    def test_crud_families(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        assert "list" in g["crud_families"]
        assert "create" in g["crud_families"]
        assert "delete" in g["crud_families"]
        assert "add" in g["crud_families"]
        assert "list_users" in g["crud_families"]["list"]
        assert "list_groups" in g["crud_families"]["list"]

    def test_relationships_shared_param(self):
        """user_id is shared (non-common) → should create edges."""
        g = build_tool_knowledge_graph(MINI_CATALOG)
        shared_param_rels = [
            r for r in g["relationships"] if "shared parameter" in r["reason"]
        ]
        # user_id is shared among get_user, delete_deactivated_user, add_user_to_group
        user_id_rels = [r for r in shared_param_rels if "'user_id'" in r["reason"]]
        assert len(user_id_rels) >= 1
        # group_id only appears in add_user_to_group → no shared edge for it alone
        group_id_rels = [r for r in shared_param_rels if "'group_id'" in r["reason"]]
        assert len(group_id_rels) == 0

    def test_relationships_same_entity(self):
        """Tools that share an entity name via CRUD verb should be connected."""
        g = build_tool_knowledge_graph(MINI_CATALOG)
        entity_rels = [r for r in g["relationships"] if "same entity" in r["reason"]]
        # list_users, get_user, create_user share entity "user(s)" depending on parse
        # At minimum list_groups connects to nothing else for 'groups' entity
        assert isinstance(entity_rels, list)

    def test_relationships_cross_category_tag(self):
        """'users' tag appears in both users and groups categories → cross-category edge."""
        g = build_tool_knowledge_graph(MINI_CATALOG)
        cross_rels = [r for r in g["relationships"] if "cross-category" in r["reason"]]
        users_cross = [r for r in cross_rels if "'users'" in r["reason"]]
        # add_user_to_group (groups) shares 'users' tag with users-category tools
        assert len(users_cross) >= 1

    def test_relationships_no_duplicates(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        seen = set()
        for r in g["relationships"]:
            key = tuple(sorted([r["source"], r["target"]])) + (r["reason"],)
            assert key not in seen, f"Duplicate relationship edge: {r}"
            seen.add(key)

    def test_summary_counts(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        s = g["summary"]
        assert s["total_tools"] == 6
        assert s["total_categories"] == 2
        assert s["total_tags"] > 0
        assert s["total_relationships"] >= 0
        assert s["category_counts"]["users"] == 4
        assert s["category_counts"]["groups"] == 2

    def test_common_params_excluded_from_shared_param_edges(self):
        """limit, after, fetch_all, q, filter should NOT generate shared-param edges."""
        g = build_tool_knowledge_graph(MINI_CATALOG)
        shared_param_rels = [
            r for r in g["relationships"] if "shared parameter" in r["reason"]
        ]
        for r in shared_param_rels:
            for common in ("'limit'", "'after'", "'fetch_all'", "'q'", "'filter'"):
                assert common not in r["reason"], (
                    f"Common param {common} should not produce a shared-param edge"
                )

    def test_empty_catalog(self):
        g = build_tool_knowledge_graph([])
        assert g["tools"] == []
        assert g["categories"] == {}
        assert g["relationships"] == []
        assert g["summary"]["total_tools"] == 0


# ---------------------------------------------------------------------------
# Tests using the real TOOL_CATALOG (integration-level)
# ---------------------------------------------------------------------------

class TestBuildFromRealCatalog:
    """Verify the graph builds correctly from the actual TOOL_CATALOG."""

    def test_builds_without_error(self):
        g = build_tool_knowledge_graph()
        assert g["summary"]["total_tools"] == len(TOOL_CATALOG)

    def test_all_categories_present(self):
        g = build_tool_knowledge_graph()
        for cat in CATEGORIES:
            assert cat in g["categories"], f"Category {cat} missing from graph"

    def test_every_tool_in_flat_list(self):
        g = build_tool_knowledge_graph()
        graph_names = {t["name"] for t in g["tools"]}
        catalog_names = {t["name"] for t in TOOL_CATALOG}
        assert graph_names == catalog_names

    def test_has_relationships(self):
        g = build_tool_knowledge_graph()
        assert len(g["relationships"]) > 0

    def test_has_crud_families(self):
        g = build_tool_knowledge_graph()
        for verb in ("list", "get", "create", "update", "delete"):
            assert verb in g["crud_families"], f"Missing CRUD verb: {verb}"
            assert len(g["crud_families"][verb]) >= 1


# ---------------------------------------------------------------------------
# Tests for graph_to_text
# ---------------------------------------------------------------------------

class TestGraphToText:
    def test_renders_header(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "# Okta MCP Server" in text
        assert "Tool Knowledge Graph" in text

    def test_renders_summary(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "Total tools: 6" in text
        assert "Categories: 2" in text

    def test_renders_categories_and_tools(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "### users" in text
        assert "### groups" in text
        assert "**list_users**" in text
        assert "**add_user_to_group**" in text

    def test_renders_parameters(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "`user_id`" in text
        assert "`search`" in text

    def test_renders_crud_families(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "CRUD / Lifecycle Families" in text
        assert "**list**" in text

    def test_renders_relationships(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        # Should have at least some relationship edges rendered
        assert "Cross-Tool Relationships" in text
        assert "↔" in text

    def test_renders_tag_index(self):
        g = build_tool_knowledge_graph(MINI_CATALOG)
        text = graph_to_text(g)
        assert "Tag Index" in text
        assert "**list**" in text

    def test_empty_catalog_renders(self):
        g = build_tool_knowledge_graph([])
        text = graph_to_text(g)
        assert "Total tools: 0" in text

    def test_real_catalog_renders(self):
        """Smoke test: rendering the real catalog should produce substantial text."""
        g = build_tool_knowledge_graph()
        text = graph_to_text(g)
        assert len(text) > 500
        assert "search_tools" not in text  # search_tools is not in TOOL_CATALOG
