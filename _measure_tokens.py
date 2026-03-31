#!/usr/bin/env python3
"""Measure token costs for every tool in the TOOL_CATALOG."""
import json
import sys

import tiktoken

sys.path.insert(0, "src")
from okta_mcp_server.tools.tool_search.registry import TOOL_CATALOG  # noqa: E402

enc = tiktoken.encoding_for_model("gpt-4")

results = []
cat_totals = {}

for tool in TOOL_CATALOG:
    name = tool["name"]
    cat = tool["category"]
    desc = tool.get("description", "")
    params = tool.get("parameters", {})

    # Simulate JSON function-calling schema sent to LLM
    schema = {
        "name": name,
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }
    for pname, pdesc in params.items():
        schema["parameters"]["properties"][pname] = {
            "type": "string",
            "description": pdesc,
        }
        if "(required)" in pdesc:
            schema["parameters"]["required"].append(pname)

    schema_str = json.dumps(schema, indent=2)
    name_tokens = len(enc.encode(name))
    desc_tokens = len(enc.encode(desc))
    params_tokens = len(enc.encode(json.dumps(params)))
    schema_tokens = len(enc.encode(schema_str))

    results.append(
        {
            "name": name,
            "category": cat,
            "param_count": len(params),
            "name_tokens": name_tokens,
            "desc_tokens": desc_tokens,
            "params_tokens": params_tokens,
            "schema_tokens": schema_tokens,
        }
    )

    if cat not in cat_totals:
        cat_totals[cat] = {"tools": 0, "total_schema_tokens": 0, "total_params": 0}
    cat_totals[cat]["tools"] += 1
    cat_totals[cat]["total_schema_tokens"] += schema_tokens
    cat_totals[cat]["total_params"] += len(params)

print("=== PER TOOL ===")
for r in sorted(results, key=lambda x: x["schema_tokens"], reverse=True):
    print(
        f"{r['name']}|{r['category']}|{r['param_count']}|"
        f"{r['name_tokens']}|{r['desc_tokens']}|"
        f"{r['params_tokens']}|{r['schema_tokens']}"
    )

print()
print("=== PER CATEGORY ===")
for cat, d in sorted(
    cat_totals.items(), key=lambda x: x[1]["total_schema_tokens"], reverse=True
):
    print(f"{cat}|{d['tools']}|{d['total_schema_tokens']}|{d['total_params']}")

grand_total = sum(d["total_schema_tokens"] for d in cat_totals.values())
total_tools = sum(d["tools"] for d in cat_totals.values())
print(f"\nGRAND_TOTAL|{total_tools}|{grand_total}")
