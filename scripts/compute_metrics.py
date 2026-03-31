"""Compute token cost metrics for Okta MCP tool definitions."""

import json
import tiktoken

from okta_mcp_server.tools.tool_search.registry import TOOL_CATALOG, CATEGORIES
from okta_mcp_server.utils.knowledge_graph import build_tool_knowledge_graph, graph_to_text

enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def main():
    # 1. Token cost per tool definition (JSON schema sent to LLM)
    tool_metrics = []
    total_all_tools_tokens = 0
    category_tokens = {}

    for tool in TOOL_CATALOG:
        tool_schema = {
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
        schema_text = json.dumps(tool_schema, indent=2)
        tokens = count_tokens(schema_text)
        tool_metrics.append({
            "name": tool["name"],
            "category": tool["category"],
            "tokens": tokens,
            "chars": len(schema_text),
            "params_count": len(tool.get("parameters", {})),
        })
        total_all_tools_tokens += tokens
        cat = tool["category"]
        category_tokens[cat] = category_tokens.get(cat, 0) + tokens

    # 2. search_tools definition tokens
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
                    "description": "Python regex pattern matched against tool names, descriptions, and tags",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category. Valid: applications, groups, policies, system_logs, users",
                },
                "list_categories": {
                    "type": "boolean",
                    "description": "If True, return categories and tool count summary",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tools to return. Default: 10",
                },
            },
        },
    }
    search_tool_tokens = count_tokens(json.dumps(search_tools_schema, indent=2))

    # 3. Knowledge graph resource tokens
    graph = build_tool_knowledge_graph()
    graph_text = graph_to_text(graph)
    graph_tokens = count_tokens(graph_text)

    # 4. Pricing (per 1M input tokens)
    pricing = {
        "GPT-4o": {"input": 2.50},
        "GPT-4.1": {"input": 2.00},
        "Claude Sonnet 4": {"input": 3.00},
        "Claude Opus 4": {"input": 15.00},
    }

    # Build report
    lines = []
    lines.append("=" * 75)
    lines.append("OKTA MCP SERVER - TOOL DEFINITION TOKEN COST METRICS")
    lines.append("=" * 75)
    lines.append("")

    # Per-tool breakdown
    lines.append("-" * 75)
    lines.append("1. TOKEN COST PER TOOL DEFINITION")
    lines.append("-" * 75)
    lines.append(f"{'Tool Name':<35} {'Category':<15} {'Params':<7} {'Tokens':<8}")
    lines.append("-" * 75)
    for m in sorted(tool_metrics, key=lambda x: x["tokens"], reverse=True):
        lines.append(f"{m['name']:<35} {m['category']:<15} {m['params_count']:<7} {m['tokens']:<8}")
    lines.append("-" * 75)
    lines.append(f"{'TOTAL (all 40 tools)':<35} {'':15} {'':7} {total_all_tools_tokens:<8}")
    lines.append("")

    # Per-category breakdown
    lines.append("-" * 75)
    lines.append("2. TOKEN COST PER CATEGORY")
    lines.append("-" * 75)
    lines.append(f"{'Category':<20} {'Tools':<8} {'Tokens':<10} {'% of Total':<10}")
    lines.append("-" * 75)
    for cat in sorted(category_tokens.keys()):
        count = sum(1 for t in TOOL_CATALOG if t["category"] == cat)
        toks = category_tokens[cat]
        pct = (toks / total_all_tools_tokens * 100) if total_all_tools_tokens else 0
        lines.append(f"{cat:<20} {count:<8} {toks:<10} {pct:.1f}%")
    lines.append("-" * 75)
    lines.append(f"{'ALL':<20} {len(TOOL_CATALOG):<8} {total_all_tools_tokens:<10} 100.0%")
    lines.append("")

    # Architecture comparison
    arch_a = total_all_tools_tokens
    arch_b = search_tool_tokens
    arch_c = search_tool_tokens + graph_tokens

    lines.append("-" * 75)
    lines.append("3. ARCHITECTURE COMPARISON - PROMPT TOKEN COST")
    lines.append("-" * 75)
    lines.append("")
    lines.append(f"  Architecture A: All 40 tools loaded upfront")
    lines.append(f"    Tool definitions in context: {arch_a} tokens")
    lines.append(f"    Knowledge graph resource:    0 tokens")
    lines.append(f"    TOTAL per prompt:            {arch_a} tokens")
    lines.append("")
    lines.append(f"  Architecture B: search_tools only (no KG resource)")
    lines.append(f"    Tool definitions in context: {arch_b} tokens (search_tools only)")
    lines.append(f"    Knowledge graph resource:    0 tokens")
    lines.append(f"    TOTAL per prompt:            {arch_b} tokens")
    lines.append("")
    lines.append(f"  Architecture C: search_tools + knowledge graph resource")
    lines.append(f"    Tool definitions in context: {arch_b} tokens (search_tools only)")
    lines.append(f"    Knowledge graph resource:    {graph_tokens} tokens")
    lines.append(f"    TOTAL per prompt:            {arch_c} tokens")
    lines.append("")

    # After first search (users + system_logs)
    scenario_cats = {"users", "system_logs"}
    scenario_tokens = sum(category_tokens.get(c, 0) for c in scenario_cats)
    arch_b_after = search_tool_tokens + scenario_tokens
    arch_c_after = search_tool_tokens + graph_tokens + scenario_tokens

    lines.append(f"  After 1st search (users + system_logs loaded):")
    lines.append(f"    Arch A: {arch_a} tokens (unchanged)")
    lines.append(f"    Arch B: {arch_b_after} tokens (search_tools + 8 tools)")
    lines.append(f"    Arch C: {arch_c_after} tokens (search_tools + KG + 8 tools)")
    lines.append("")

    # After all categories loaded
    arch_b_full = search_tool_tokens + total_all_tools_tokens
    arch_c_full = search_tool_tokens + graph_tokens + total_all_tools_tokens

    lines.append(f"  After ALL categories loaded (worst case):")
    lines.append(f"    Arch A: {arch_a} tokens")
    lines.append(f"    Arch B: {arch_b_full} tokens (search_tools + all tools)")
    lines.append(f"    Arch C: {arch_c_full} tokens (search_tools + KG + all tools)")
    lines.append("")

    # Savings
    savings_b = arch_a - arch_b
    savings_c = arch_a - arch_c
    lines.append(f"  Savings (initial prompt, before any search):")
    lines.append(f"    B vs A: {savings_b} tokens saved ({savings_b / arch_a * 100:.1f}%)")
    if savings_c > 0:
        lines.append(f"    C vs A: {savings_c} tokens saved ({savings_c / arch_a * 100:.1f}%)")
    else:
        overhead = abs(savings_c)
        lines.append(f"    C vs A: {overhead} tokens MORE ({overhead / arch_a * 100:.1f}% overhead from KG)")
    lines.append("")

    # Dollar cost per prompt
    lines.append("-" * 75)
    lines.append("4. DOLLAR COST PER PROMPT (input tokens only)")
    lines.append("-" * 75)
    header = f"{'Model':<20} {'A (all)':<12} {'B (search)':<12} {'C (srch+KG)':<12} {'B saves':<10} {'C vs A':<10}"
    lines.append(header)
    lines.append("-" * 75)
    for model, prices in pricing.items():
        cost_a = arch_a / 1_000_000 * prices["input"]
        cost_b = arch_b / 1_000_000 * prices["input"]
        cost_c = arch_c / 1_000_000 * prices["input"]
        save_b = cost_a - cost_b
        save_c = cost_a - cost_c
        sign_c = "+" if save_c >= 0 else "-"
        lines.append(
            f"{model:<20} ${cost_a:.6f} ${cost_b:.6f} ${cost_c:.6f} ${save_b:.6f} {sign_c}${abs(save_c):.6f}"
        )
    lines.append("")

    # Over 100-prompt session
    lines.append("-" * 75)
    lines.append("5. COST OVER 100-PROMPT SESSION (tool defs input tokens only)")
    lines.append("-" * 75)
    lines.append(f"{'Model':<20} {'Arch A':<12} {'Arch B':<12} {'Arch C':<12}")
    lines.append("-" * 75)
    for model, prices in pricing.items():
        cost_a = 100 * arch_a / 1_000_000 * prices["input"]
        cost_b = 100 * arch_b / 1_000_000 * prices["input"]
        cost_c = 100 * arch_c / 1_000_000 * prices["input"]
        lines.append(f"{model:<20} ${cost_a:.4f}    ${cost_b:.4f}    ${cost_c:.4f}")
    lines.append("")

    # Knowledge graph breakdown
    lines.append("-" * 75)
    lines.append("6. KNOWLEDGE GRAPH RESOURCE BREAKDOWN")
    lines.append("-" * 75)
    lines.append(f"  Total chars:          {len(graph_text)}")
    lines.append(f"  Total tokens:         {graph_tokens}")
    lines.append(f"  Categories:           {graph['summary']['total_categories']}")
    lines.append(f"  Tools described:      {graph['summary']['total_tools']}")
    lines.append(f"  Relationships:        {graph['summary']['total_relationships']}")
    lines.append(f"  Unique tags:          {graph['summary']['total_tags']}")
    lines.append("")

    # Tradeoff analysis
    lines.append("-" * 75)
    lines.append("7. TRADEOFF ANALYSIS")
    lines.append("-" * 75)
    lines.append(f"  Knowledge graph: {graph_tokens} tokens")
    lines.append(f"  All tool definitions: {total_all_tools_tokens} tokens")
    if graph_tokens < total_all_tools_tokens:
        diff = total_all_tools_tokens - graph_tokens
        lines.append(f"  KG is {diff} tokens CHEAPER than loading all tools")
        lines.append(f"  KG provides full tool awareness at {graph_tokens / total_all_tools_tokens * 100:.1f}% of the cost")
    else:
        diff = graph_tokens - total_all_tools_tokens
        lines.append(f"  KG is {diff} tokens MORE than loading all tools")
        lines.append(f"  KG costs {graph_tokens / total_all_tools_tokens * 100:.1f}% of loading all tools")
    lines.append(f"  search_tools definition: {search_tool_tokens} tokens")
    lines.append(f"  Break-even: KG is worth it if it provides enough context")
    lines.append(f"              to avoid loading all {total_all_tools_tokens} tool-def tokens")
    lines.append("")
    lines.append("=" * 75)

    report = "\n".join(lines)
    print(report)

    with open("tool_cost_metrics.txt", "w") as f:
        f.write(report)
    print("\nReport saved to tool_cost_metrics.txt")


if __name__ == "__main__":
    main()
