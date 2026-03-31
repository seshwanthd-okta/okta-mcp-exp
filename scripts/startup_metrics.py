"""Token cost metrics for the 2-tool startup implementation."""

import json
import tiktoken

from okta_mcp_server.tools.tool_search.registry import TOOL_CATALOG, CATEGORIES

enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def main():
    # 1. search_tools schema
    search_tools_schema = {
        "name": "search_tools",
        "description": (
            "Search for available Okta MCP tools by regex pattern, category, or tags. "
            "CALL THIS TOOL FIRST to discover which tools exist before invoking them. "
            "This prevents calling non-existent tools and provides accurate parameter info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Python regex pattern (case-insensitive) matched against tool names, "
                        "descriptions, and tags. Use .* or empty to match everything. "
                        "Examples: user, delete|remove, list.*group, policy.*rule."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category. Valid categories: applications, groups, policies, system_logs, users.",
                },
                "list_categories": {
                    "type": "boolean",
                    "description": "If True, return the list of available categories and a tool count summary instead of searching. Default: False.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tools to return. Default: 10.",
                },
            },
        },
    }

    # 2. unload_tools schema
    unload_tools_schema = {
        "name": "unload_tools",
        "description": (
            "Unload tool categories that are no longer needed to free up context. "
            "Call this when you are done using tools from specific categories and want "
            "to reduce the number of tools in context. The tools will be unregistered "
            "from the server and can be re-loaded later via search_tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Categories to unload. Valid categories: applications, groups, "
                        "policies, system_logs, users. Only currently-loaded categories will be affected."
                    ),
                },
            },
            "required": ["categories"],
        },
    }

    # 3. All 40 tools
    total_all = 0
    cat_tokens = {}
    for tool in TOOL_CATALOG:
        schema = {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    pname: {"type": "string", "description": pdesc}
                    for pname, pdesc in tool.get("parameters", {}).items()
                },
            },
        }
        toks = count_tokens(json.dumps(schema, indent=2))
        total_all += toks
        cat = tool["category"]
        cat_tokens[cat] = cat_tokens.get(cat, 0) + toks

    t_search = count_tokens(json.dumps(search_tools_schema, indent=2))
    t_unload = count_tokens(json.dumps(unload_tools_schema, indent=2))
    t_startup = t_search + t_unload

    lines = []
    lines.append("=" * 70)
    lines.append("OKTA MCP SERVER — TOOL TOKEN METRICS (2-TOOL STARTUP)")
    lines.append("=" * 70)
    lines.append("")

    lines.append("-" * 70)
    lines.append("1. STARTUP TOOL DEFINITIONS (always in context)")
    lines.append("-" * 70)
    lines.append(f"  search_tools:     {t_search:>5} tokens")
    lines.append(f"  unload_tools:     {t_unload:>5} tokens")
    lines.append(f"  TOTAL at startup: {t_startup:>5} tokens")
    lines.append("")

    lines.append("-" * 70)
    lines.append("2. CATEGORY COSTS (loaded on-demand)")
    lines.append("-" * 70)
    lines.append(f"  {'Category':<20} {'Tools':<8} {'Tokens':<10}")
    lines.append("  " + "-" * 38)
    for cat in sorted(cat_tokens):
        cnt = sum(1 for t in TOOL_CATALOG if t["category"] == cat)
        lines.append(f"  {cat:<20} {cnt:<8} {cat_tokens[cat]:<10}")
    lines.append("  " + "-" * 38)
    lines.append(f"  {'ALL 40 tools':<20} {len(TOOL_CATALOG):<8} {total_all:<10}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("3. CONTEXT WINDOW COMPARISON")
    lines.append("-" * 70)
    lines.append("")
    lines.append(f"  A) All 40 tools upfront:             {total_all:>5} tokens")
    lines.append(f"  B) 2 startup tools only:             {t_startup:>5} tokens  (current impl)")
    savings = total_all - t_startup
    lines.append(f"     Savings vs A:                     {savings:>5} tokens ({savings / total_all * 100:.1f}%)")
    lines.append("")

    scenarios = [
        ("users only", {"users"}),
        ("users + groups", {"users", "groups"}),
        ("users + groups + logs", {"users", "groups", "system_logs"}),
        ("ALL categories loaded", set(cat_tokens.keys())),
    ]
    for name, cats in scenarios:
        scene_toks = t_startup + sum(cat_tokens.get(c, 0) for c in cats)
        label = f"B + {name}:"
        lines.append(f"  {label:<40} {scene_toks:>5} tokens")
    lines.append("")

    lines.append("-" * 70)
    lines.append("4. TOKEN REDUCTION RATIO")
    lines.append("-" * 70)
    lines.append(f"  Startup vs All-40:  {t_startup}/{total_all} = {t_startup / total_all * 100:.1f}%  ({total_all / t_startup:.1f}x reduction)")
    lines.append("")

    pricing = {
        "GPT-4o": 2.50,
        "GPT-4.1": 2.00,
        "Claude Sonnet 4": 3.00,
        "Claude Opus 4": 15.00,
    }

    lines.append("-" * 70)
    lines.append("5. DOLLAR COST PER PROMPT (input tokens only)")
    lines.append("-" * 70)
    lines.append(f"  {'Model':<20} {'All 40':<14} {'2 startup':<14} {'Savings/prompt':<14}")
    lines.append("  " + "-" * 56)
    for model, price in pricing.items():
        cost_a = total_all / 1_000_000 * price
        cost_b = t_startup / 1_000_000 * price
        lines.append(f"  {model:<20} ${cost_a:.6f}     ${cost_b:.6f}     ${cost_a - cost_b:.6f}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("6. COST OVER 100-PROMPT SESSION")
    lines.append("-" * 70)
    lines.append(f"  {'Model':<20} {'All 40':<14} {'2 startup':<14} {'Saved':<14}")
    lines.append("  " + "-" * 56)
    for model, price in pricing.items():
        cost_a = 100 * total_all / 1_000_000 * price
        cost_b = 100 * t_startup / 1_000_000 * price
        lines.append(f"  {model:<20} ${cost_a:.4f}      ${cost_b:.4f}      ${cost_a - cost_b:.4f}")
    lines.append("")
    lines.append("=" * 70)

    report = "\n".join(lines)
    print(report)


if __name__ == "__main__":
    main()
