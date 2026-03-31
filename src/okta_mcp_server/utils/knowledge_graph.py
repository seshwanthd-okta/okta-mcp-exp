# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Tool-Search Knowledge Graph builder.

Builds a structured graph of the entire tool catalog at import time —
categories, tools, parameter signatures, tags, and cross-tool relationships
(shared parameters, shared tags, CRUD families, etc.).

The graph is exposed as an MCP **resource** so the LLM receives it as
context on the very first query, *before* it ever calls ``search_tools``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from okta_mcp_server.tools.tool_search.registry import CATEGORIES, TOOL_CATALOG


# ------------------------------------------------------------------
# Graph builder  (pure function — no I/O, no side-effects)
# ------------------------------------------------------------------

def build_tool_knowledge_graph(
    catalog: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Build the tool-search knowledge graph from the tool catalog.

    Parameters
    ----------
    catalog:
        Tool catalog list (defaults to ``TOOL_CATALOG``).

    Returns
    -------
    A JSON-serialisable dict with the following top-level keys:

    * ``categories``  – per-category tool listing
    * ``tools``       – flat list of every tool descriptor
    * ``tag_index``   – tag → [tool_name, …]
    * ``param_index`` – param_name → [tool_name, …]
    * ``crud_families`` – operation-verb → [tool_name, …]
    * ``relationships`` – list of ``{source, target, reason}`` edges
    * ``summary``     – counts & quick stats
    """
    catalog = catalog if catalog is not None else TOOL_CATALOG

    # ── Per-category grouping ────────────────────────────────────────
    categories: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tool in catalog:
        categories[tool["category"]].append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("parameters", {}),
            "tags": tool.get("tags", []),
        })

    # ── Tag index ────────────────────────────────────────────────────
    tag_index: Dict[str, List[str]] = defaultdict(list)
    for tool in catalog:
        for tag in tool.get("tags", []):
            tag_index[tag].append(tool["name"])

    # ── Parameter index (shared params → tools) ─────────────────────
    param_index: Dict[str, List[str]] = defaultdict(list)
    for tool in catalog:
        for pname in tool.get("parameters", {}):
            param_index[pname].append(tool["name"])

    # ── CRUD / lifecycle families ────────────────────────────────────
    crud_verbs = ["list", "get", "create", "update", "delete", "activate",
                  "deactivate", "add", "remove", "confirm"]
    crud_families: Dict[str, List[str]] = defaultdict(list)
    for tool in catalog:
        for verb in crud_verbs:
            if verb in tool.get("tags", []):
                crud_families[verb].append(tool["name"])

    # ── Cross-tool relationship edges ────────────────────────────────
    relationships: List[Dict[str, str]] = []
    tool_by_name: Dict[str, Dict[str, Any]] = {t["name"]: t for t in catalog}

    # 1) Shared-parameter edges (tools that share uncommon params)
    for pname, tnames in param_index.items():
        # Skip very common params (they'd connect almost everything)
        if pname in {"limit", "after", "fetch_all", "q", "filter"}:
            continue
        if len(tnames) >= 2:
            for i, a in enumerate(tnames):
                for b in tnames[i + 1:]:
                    relationships.append({
                        "source": a,
                        "target": b,
                        "reason": f"shared parameter '{pname}'",
                    })

    # 2) CRUD-family edges (e.g. create_policy ↔ delete_policy)
    #    Connect tools that operate on the same entity via different verbs.
    entity_ops: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for tool in catalog:
        name = tool["name"]
        for verb in crud_verbs:
            if name.startswith(verb + "_"):
                entity = name[len(verb) + 1:]
                entity_ops[entity].append((verb, name))
                break
            # Handle "confirm_delete_*" pattern
            if name.startswith("confirm_" + verb + "_"):
                entity = name[len("confirm_" + verb) + 1:]
                entity_ops[entity].append((f"confirm_{verb}", name))
                break

    for entity, ops in entity_ops.items():
        if len(ops) >= 2:
            for i, (v1, n1) in enumerate(ops):
                for v2, n2 in ops[i + 1:]:
                    relationships.append({
                        "source": n1,
                        "target": n2,
                        "reason": f"same entity '{entity}' ({v1} / {v2})",
                    })

    # 3) Cross-category edges (tools that share a tag across categories)
    tag_to_cats: Dict[str, Set[str]] = defaultdict(set)
    tag_to_tools: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for tool in catalog:
        for tag in tool.get("tags", []):
            tag_to_cats[tag].add(tool["category"])
            tag_to_tools[tag].append((tool["name"], tool["category"]))

    for tag, tool_cat_pairs in tag_to_tools.items():
        cats_for_tag = tag_to_cats[tag]
        if len(cats_for_tag) >= 2 and tag not in {"read", "write", "list", "pagination"}:
            by_cat: Dict[str, List[str]] = defaultdict(list)
            for tname, tcat in tool_cat_pairs:
                by_cat[tcat].append(tname)
            cat_list = sorted(by_cat.keys())
            for i, c1 in enumerate(cat_list):
                for c2 in cat_list[i + 1:]:
                    for n1 in by_cat[c1]:
                        for n2 in by_cat[c2]:
                            relationships.append({
                                "source": n1,
                                "target": n2,
                                "reason": f"cross-category tag '{tag}'",
                            })

    # ── De-duplicate relationship edges ──────────────────────────────
    seen_edges: set = set()
    unique_rels: List[Dict[str, str]] = []
    for rel in relationships:
        key = tuple(sorted([rel["source"], rel["target"]])) + (rel["reason"],)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_rels.append(rel)
    relationships = unique_rels

    # ── Summary ──────────────────────────────────────────────────────
    summary = {
        "total_tools": len(catalog),
        "total_categories": len(categories),
        "total_tags": len(tag_index),
        "total_relationships": len(relationships),
        "category_counts": {cat: len(tools) for cat, tools in sorted(categories.items())},
        "crud_verb_counts": {verb: len(names) for verb, names in sorted(crud_families.items())},
    }

    return {
        "categories": dict(categories),
        "tools": [
            {
                "name": t["name"],
                "category": t["category"],
                "description": t["description"],
                "parameters": t.get("parameters", {}),
                "tags": t.get("tags", []),
            }
            for t in catalog
        ],
        "tag_index": dict(tag_index),
        "param_index": dict(param_index),
        "crud_families": dict(crud_families),
        "relationships": relationships,
        "summary": summary,
    }


# ------------------------------------------------------------------
# Text renderer  (for the MCP resource mime_type=text/plain)
# ------------------------------------------------------------------

def graph_to_text(graph_data: Dict[str, Any]) -> str:
    """Render the tool knowledge graph as human-readable text for the LLM."""
    lines: List[str] = []
    lines.append("# Okta MCP Server — Tool Knowledge Graph")
    lines.append("")

    # ── Summary ──────────────────────────────────────────────────────
    s = graph_data.get("summary", {})
    lines.append("## Summary")
    lines.append(f"- Total tools: {s.get('total_tools', '?')}")
    lines.append(f"- Categories: {s.get('total_categories', '?')}")
    lines.append(f"- Unique tags: {s.get('total_tags', '?')}")
    lines.append(f"- Relationship edges: {s.get('total_relationships', '?')}")
    cc = s.get("category_counts", {})
    if cc:
        lines.append("- Tools per category: " + ", ".join(
            f"{cat} ({cnt})" for cat, cnt in cc.items()
        ))
    cv = s.get("crud_verb_counts", {})
    if cv:
        lines.append("- CRUD verbs: " + ", ".join(
            f"{verb} ({cnt})" for verb, cnt in cv.items()
        ))
    lines.append("")

    # ── Tools by category ────────────────────────────────────────────
    categories = graph_data.get("categories", {})
    lines.append("## Tools by Category")
    lines.append("")
    for cat_name in sorted(categories.keys()):
        tools = categories[cat_name]
        lines.append(f"### {cat_name} ({len(tools)} tools)")
        for t in tools:
            lines.append(f"  - **{t['name']}**: {t['description']}")
            params = t.get("parameters", {})
            if params:
                for pname, pdesc in params.items():
                    lines.append(f"    - `{pname}`: {pdesc}")
            tags = t.get("tags", [])
            if tags:
                lines.append(f"    - tags: {', '.join(tags)}")
        lines.append("")

    # ── CRUD families ────────────────────────────────────────────────
    crud = graph_data.get("crud_families", {})
    if crud:
        lines.append("## CRUD / Lifecycle Families")
        lines.append("")
        for verb in sorted(crud.keys()):
            tool_names = crud[verb]
            lines.append(f"  - **{verb}**: {', '.join(tool_names)}")
        lines.append("")

    # ── Cross-tool relationships ─────────────────────────────────────
    rels = graph_data.get("relationships", [])
    if rels:
        lines.append(f"## Cross-Tool Relationships ({len(rels)} edges)")
        lines.append("")
        for r in rels:
            lines.append(f"  - {r['source']} ↔ {r['target']}  ({r['reason']})")
        lines.append("")

    # ── Tag index ────────────────────────────────────────────────────
    tag_index = graph_data.get("tag_index", {})
    if tag_index:
        lines.append("## Tag Index")
        lines.append("")
        for tag in sorted(tag_index.keys()):
            tool_names = tag_index[tag]
            lines.append(f"  - **{tag}**: {', '.join(tool_names)}")
        lines.append("")

    return "\n".join(lines)
