# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Tool Search — discover available Okta MCP tools on-demand.

Instead of requiring the model to know every tool name upfront, this
module exposes a single ``search_tools`` MCP tool that lets the model
search the catalogue by regex pattern, category, or operation type.

Usage by the model:
    1. Call ``search_tools(pattern="user")``  → returns all user-related tools
    2. Call ``search_tools(pattern="delete|remove", category="groups")``
    3. Call ``search_tools(pattern=".*", category="policies")``  → all policy tools
    4. Call ``search_tools(pattern="", list_categories=True)``  → show categories
"""

import re
from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.tools.tool_search.registry import (
    CATEGORIES,
    TOOL_CATALOG,
    get_loaded_categories,
    get_usage_summary,
    increment_turn,
    load_categories,
    unload_categories,
)


@mcp.tool()
async def search_tools(
    ctx: Context,
    pattern: str = "",
    category: Optional[str] = None,
    list_categories: bool = False,
    limit: int = 10,
) -> dict:
    """Search for available Okta MCP tools by regex pattern, category, or tags.

    CALL THIS TOOL FIRST to discover which tools exist before invoking them.
    This prevents calling non-existent tools and provides accurate parameter info.

    Parameters:
        pattern (str, optional): Python regex pattern (case-insensitive) matched against
            tool names, descriptions, and tags. Use '.*' or '' to match everything.
            Examples: 'user', 'delete|remove', 'list.*group', 'policy.*rule'.
        category (str, optional): Filter by category. Valid categories:
            applications, brands, custom_domains, custom_pages, custom_templates,
            device_assurance, email_domains, groups, policies, system_logs, themes, users.
        list_categories (bool, optional): If True, return the list of available
            categories and a tool count summary instead of searching. Default: False.
        limit (int, optional): Maximum number of tools to return. Default: 10.

    Returns:
        Dict containing:
        - tools: List of matching tool descriptors (name, category, description, parameters, tags)
        - total_matches: Total number of matches found
        - categories: (only when list_categories=True) Available categories with counts
        - session_usage: Per-category call counts, recency, and unload recommendations
        - hint: Contextual usage hint
    """
    # Increment turn counter — each search_tools call is a reliable proxy for
    # a new LLM reasoning step, giving usage data time-relative meaning.
    current_turn = increment_turn()
    logger.info(f"Tool search invoked — pattern='{pattern}', category='{category}', list_categories={list_categories}, turn={current_turn}")

    # ── Category listing mode ────────────────────────────────────────────
    if list_categories:
        category_counts = {}
        for tool in TOOL_CATALOG:
            cat = tool["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        logger.info(f"Returning category listing: {category_counts}")
        return {
            "categories": category_counts,
            "total_tools": len(TOOL_CATALOG),
            "session_usage": get_usage_summary(),
            "hint": (
                "Use search_tools(category='<name>') to list all tools in a "
                "category, or search_tools(pattern='<regex>') to search across all tools. "
                "Check session_usage.unload_candidates to see which loaded categories "
                "can safely be unloaded."
            ),
        }

    # ── Build candidate set (optionally filtered by category) ────────────
    candidates = TOOL_CATALOG
    if category:
        cat_lower = category.lower().strip()
        candidates = [t for t in candidates if t["category"] == cat_lower]
        if not candidates:
            logger.warning(f"No tools in category '{category}'")
            return {
                "tools": [],
                "total_matches": 0,
                "available_categories": CATEGORIES,
                "hint": f"Category '{category}' not found. Valid categories: {', '.join(CATEGORIES)}",
            }

    # ── Regex search ─────────────────────────────────────────────────────
    if pattern:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            logger.error(f"Invalid regex pattern '{pattern}': {exc}")
            return {
                "error": f"Invalid regex pattern: {exc}",
                "hint": "Provide a valid Python regex pattern. Examples: 'user', 'delete|remove', 'list.*group'.",
            }

        def _matches(tool: dict) -> bool:
            """Return True if the regex matches name, description, tags, or parameter names."""
            searchable = " ".join(
                [
                    tool["name"],
                    tool["description"],
                    " ".join(tool.get("tags", [])),
                    " ".join(tool.get("parameters", {}).keys()),
                ]
            )
            return regex.search(searchable) is not None

        matches = [t for t in candidates if _matches(t)]
    else:
        matches = list(candidates)

    total = len(matches)
    truncated = matches[:limit]

    # ── Lazy-load tool modules for matched categories ──────────────────
    matched_categories = {t["category"] for t in matches}
    newly_loaded = load_categories(matched_categories)
    if newly_loaded:
        logger.info(f"Dynamically loaded tool categories: {newly_loaded}")
        try:
            await ctx.session.send_tool_list_changed()
            logger.info("Sent tools/list_changed notification to client")
        except Exception as exc:
            logger.warning(f"Could not send tools/list_changed notification: {exc}")

    logger.info(f"Tool search found {total} matches, returning {len(truncated)}")

    usage = get_usage_summary()

    # Always compute per-category counts so the LLM discovers ALL categories
    category_counts = {}
    for tool in TOOL_CATALOG:
        cat = tool["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    result: dict = {
        "tools": truncated,
        "total_matches": total,
        "available_categories": category_counts,
        "session_usage": usage,
    }

    if usage.get("unload_candidates"):
        candidates_list = ", ".join(usage["unload_candidates"])
        result["hint"] = (
            f"session_usage shows unload candidates: [{candidates_list}]. "
            f"Call unload_tools(categories=[...]) to free context before loading more tools."
        )
    elif total > limit:
        cat_names = ", ".join(sorted(category_counts.keys()))
        result["hint"] = (
            f"Showing {limit} of {total} matches. "
            f"There are {len(category_counts)} categories with {len(TOOL_CATALOG)} total tools: [{cat_names}]. "
            f"Use search_tools(category='<name>') to list tools per category, "
            f"or increase the limit parameter to see more results at once."
        )
    elif total == 0:
        result["hint"] = (
            "No tools matched your query. Try a broader pattern or "
            "call search_tools(list_categories=True) to see available categories."
        )

    return result


@mcp.tool()
async def unload_tools(
    ctx: Context,
    categories: list[str],
) -> dict:
    """Unload tool categories that are no longer needed to free up context.

    Call this when you are done using tools from specific categories and want
    to reduce the number of tools in context.  The tools will be unregistered
    from the server and can be re-loaded later via search_tools.

    Use session_usage.recommendation and session_usage.unload_candidates returned
    by search_tools to decide which categories to unload.  Prefer unloading
    categories with recommendation 'safe_to_unload' or 'consider_unloading' that
    have not been called recently and have a 'single_use' conversation_pattern.
    Do NOT unload categories with 'alternating' conversation_pattern — they are
    likely to be needed again soon.

    Parameters:
        categories (list[str], required): Categories to unload.
            Valid categories: applications, brands, custom_domains, custom_pages,
            custom_templates, device_assurance, email_domains, groups, policies,
            system_logs, themes, users.
            Only currently-loaded categories will be affected.

    Returns:
        Dict containing:
        - unloaded: Mapping of category → list of tool names removed
        - still_loaded: Categories that remain loaded
        - session_usage: Updated usage stats after unloading
        - hint: Usage hint
    """
    logger.info(f"unload_tools invoked — categories={categories}")

    if not categories:
        return {
            "unloaded": {},
            "still_loaded": sorted(get_loaded_categories()),
            "hint": "Provide a list of categories to unload.",
        }

    # Validate
    invalid = [c for c in categories if c.lower().strip() not in CATEGORIES]
    if invalid:
        return {
            "error": f"Unknown categories: {invalid}",
            "valid_categories": CATEGORIES,
            "hint": f"Valid categories: {', '.join(CATEGORIES)}",
        }

    requested = {c.lower().strip() for c in categories}
    unloaded = unload_categories(requested)

    if unloaded:
        try:
            await ctx.session.send_tool_list_changed()
            logger.info("Sent tools/list_changed notification after unload")
        except Exception as exc:
            logger.warning(f"Could not send tools/list_changed notification: {exc}")

    total_removed = sum(len(names) for names in unloaded.values())
    logger.info(f"Unloaded {total_removed} tools from {len(unloaded)} categories")

    return {
        "unloaded": {cat: names for cat, names in unloaded.items()},
        "total_tools_removed": total_removed,
        "still_loaded": sorted(get_loaded_categories()),
        "session_usage": get_usage_summary(),
        "hint": (
            "Tools have been unregistered. Call search_tools() to re-load "
            "them when needed again. Check session_usage for remaining categories "
            "and further unload recommendations."
        ),
    }
