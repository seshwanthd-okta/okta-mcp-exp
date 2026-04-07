# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Okta Orchestrator Knowledge Graph — Dynamic Capability Graph

A purely data-driven directed graph that encodes tool capabilities and
data-flow dependencies.  There are NO predefined workflows, intents, or
keyword matchers.  The graph is queried dynamically at runtime:

    - By entity type / operation type   → which tools exist?
    - By available parameters           → which tools can I call right now?
    - By target action                  → what prerequisites do I need?
    - By reachability                   → what can I reach from tool X?
    - By dependency chain               → build me a full execution path to tool Y

The LLM queries the graph, receives the relevant subgraph, and composes
the workflow itself.  The graph provides the map; the LLM decides the route.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OperationType(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class EntityType(str, Enum):
    USER = "user"
    GROUP = "group"
    APPLICATION = "application"
    POLICY = "policy"
    POLICY_RULE = "policy_rule"
    DEVICE_ASSURANCE = "device_assurance"
    LOG = "log"
    BRAND = "brand"
    CUSTOM_DOMAIN = "custom_domain"
    EMAIL_DOMAIN = "email_domain"
    THEME = "theme"
    CUSTOM_PAGE = "custom_page"
    EMAIL_TEMPLATE = "email_template"


# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------

@dataclass
class ToolNode:
    """A node representing a single Okta SDK action."""
    action: str                               # dispatcher key, e.g. "get_user"
    entity_type: EntityType
    operation: OperationType
    description: str
    required_params: list[str]                # params that MUST be supplied
    optional_params: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    is_destructive: bool = False
    is_iterable: bool = False                 # can operate over a list (for_each)
    tags: list[str] = field(default_factory=list)  # free-form labels for searching


@dataclass
class Edge:
    """Directed data-flow edge: source output → target input."""
    source: str          # source ToolNode action
    target: str          # target ToolNode action
    source_output: str   # field path from source result, e.g. "id", "items"
    target_param: str    # parameter name on target, e.g. "user_id"
    description: str = ""
    is_iteration: bool = False   # True when source produces a list to iterate over


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

class OktaKnowledgeGraph:
    """In-memory directed capability graph — no predefined workflows."""

    def __init__(self) -> None:
        self._nodes: dict[str, ToolNode] = {}
        self._edges: list[Edge] = []
        self._adjacency: dict[str, list[Edge]] = {}     # source → edges
        self._reverse_adj: dict[str, list[Edge]] = {}    # target → edges

    # ── Node management ──

    def add_node(self, node: ToolNode) -> None:
        self._nodes[node.action] = node
        self._adjacency.setdefault(node.action, [])
        self._reverse_adj.setdefault(node.action, [])

    def get_node(self, action: str) -> ToolNode | None:
        return self._nodes.get(action)

    # ── Edge management ──

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self._nodes:
            raise ValueError(f"Source node '{edge.source}' not in graph")
        if edge.target not in self._nodes:
            raise ValueError(f"Target node '{edge.target}' not in graph")
        self._edges.append(edge)
        self._adjacency[edge.source].append(edge)
        self._reverse_adj[edge.target].append(edge)

    def get_outgoing_edges(self, action: str) -> list[Edge]:
        return self._adjacency.get(action, [])

    def get_incoming_edges(self, action: str) -> list[Edge]:
        return self._reverse_adj.get(action, [])

    # ==================================================================
    # DYNAMIC QUERIES — no predefined workflows, pure graph traversal
    # ==================================================================

    def query_tools(
        self,
        entity_type: str | None = None,
        operation: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        """Filter tools by entity type, operation, or tag.

        All filters are optional and combined with AND logic.
        Returns serialised node dicts.
        """
        nodes = list(self._nodes.values())
        if entity_type:
            et = entity_type.lower()
            nodes = [n for n in nodes if n.entity_type.value == et]
        if operation:
            op = operation.lower()
            nodes = [n for n in nodes if n.operation.value == op]
        if tag:
            t = tag.lower()
            nodes = [n for n in nodes if t in [x.lower() for x in n.tags]]
        return [self._serialise_node(n) for n in nodes]

    def query_callable_tools(self, available_params: list[str]) -> list[dict]:
        """Given params you already have, which tools can you call right now?

        A tool is callable if all its required_params are in available_params.
        """
        available = set(available_params)
        result = []
        for node in self._nodes.values():
            if set(node.required_params).issubset(available):
                result.append(self._serialise_node(node))
        return result

    def query_reachable(self, start_action: str, max_depth: int = 10) -> dict:
        """BFS from start_action — return all reachable tools with depth and edges.

        Returns a subgraph: the tools you can reach and the data-flow edges
        connecting them.
        """
        if start_action not in self._nodes:
            return {"error": f"Unknown action '{start_action}'", "nodes": [], "edges": []}

        visited: dict[str, int] = {start_action: 0}
        queue: deque[str] = deque([start_action])
        reached_edges: list[dict] = []

        while queue:
            current = queue.popleft()
            depth = visited[current]
            if depth >= max_depth:
                continue
            for edge in self.get_outgoing_edges(current):
                reached_edges.append(self._serialise_edge(edge))
                if edge.target not in visited:
                    visited[edge.target] = depth + 1
                    queue.append(edge.target)

        nodes = [
            {**self._serialise_node(self._nodes[a]), "depth": d}
            for a, d in visited.items()
        ]
        return {"nodes": nodes, "edges": reached_edges}

    def query_dependencies(self, target_action: str) -> dict:
        """Reverse BFS — what tools must run before target_action?

        Returns the prerequisite subgraph: tools whose outputs feed into
        the target (transitively), plus the edges connecting them.
        """
        if target_action not in self._nodes:
            return {"error": f"Unknown action '{target_action}'", "nodes": [], "edges": []}

        visited: dict[str, int] = {target_action: 0}
        queue: deque[str] = deque([target_action])
        dep_edges: list[dict] = []

        while queue:
            current = queue.popleft()
            depth = visited[current]
            for edge in self.get_incoming_edges(current):
                dep_edges.append(self._serialise_edge(edge))
                if edge.source not in visited:
                    visited[edge.source] = depth + 1
                    queue.append(edge.source)

        nodes = [
            {**self._serialise_node(self._nodes[a]), "depth": d}
            for a, d in visited.items()
        ]
        return {"nodes": nodes, "edges": dep_edges}

    def query_path(self, start_action: str, end_action: str) -> list[dict] | None:
        """Find shortest data-flow path between two tools.

        Returns an ordered list of edges from start to end, or None if
        no path exists.
        """
        if start_action not in self._nodes or end_action not in self._nodes:
            return None

        # BFS
        parent: dict[str, Edge | None] = {start_action: None}
        queue: deque[str] = deque([start_action])

        while queue:
            current = queue.popleft()
            if current == end_action:
                # Reconstruct path
                path: list[dict] = []
                node = end_action
                while parent[node] is not None:
                    path.append(self._serialise_edge(parent[node]))
                    node = parent[node].source
                path.reverse()
                return path
            for edge in self.get_outgoing_edges(current):
                if edge.target not in parent:
                    parent[edge.target] = edge
                    queue.append(edge.target)

        return None  # no path

    def build_execution_chain(self, actions: list[str]) -> list[dict]:
        """Given an ordered list of actions the LLM wants to run, resolve
        parameter bindings from graph edges and return step descriptors.

        The LLM decides the sequence; the KG resolves the wiring.

        Returns a list of step dicts:
            [{"step": 1, "action": ..., "params": {...}, "description": ...,
              "is_destructive": ..., "for_each": ...}, ...]
        """
        steps: list[dict] = []
        action_to_step: dict[str, int] = {}

        for idx, action_name in enumerate(actions):
            node = self._nodes.get(action_name)
            if not node:
                raise ValueError(f"Unknown action '{action_name}'")

            step_num = idx + 1
            action_to_step[action_name] = step_num
            params: dict[str, Any] = {}
            for_each: str | None = None

            # Resolve params from incoming edges whose source is a prior step
            for edge in self.get_incoming_edges(action_name):
                if edge.source in action_to_step:
                    src_step = action_to_step[edge.source]
                    if edge.is_iteration and node.is_iterable:
                        for_each = f"$step{src_step}"
                    else:
                        params[edge.target_param] = f"$step{src_step}.{edge.source_output}"

            steps.append({
                "step": step_num,
                "action": action_name,
                "params": params,
                "description": node.description,
                "is_destructive": node.is_destructive,
                "for_each": for_each,
            })

        return steps

    # ── Introspection ──

    def get_stats(self) -> dict:
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "entity_types": sorted({n.entity_type.value for n in self._nodes.values()}),
            "operations": sorted({n.operation.value for n in self._nodes.values()}),
        }

    def to_dict(self) -> dict:
        """Full graph serialisation."""
        return {
            "nodes": {k: self._serialise_node(v) for k, v in self._nodes.items()},
            "edges": [self._serialise_edge(e) for e in self._edges],
        }

    # ── Serialisation helpers ──

    @staticmethod
    def _serialise_node(node: ToolNode) -> dict:
        return {
            "action": node.action,
            "entity_type": node.entity_type.value,
            "operation": node.operation.value,
            "description": node.description,
            "required_params": node.required_params,
            "optional_params": node.optional_params,
            "outputs": node.outputs,
            "is_destructive": node.is_destructive,
            "is_iterable": node.is_iterable,
            "tags": node.tags,
        }

    @staticmethod
    def _serialise_edge(edge: Edge) -> dict:
        return {
            "source": edge.source,
            "target": edge.target,
            "source_output": edge.source_output,
            "target_param": edge.target_param,
            "description": edge.description,
            "is_iteration": edge.is_iteration,
        }


# ---------------------------------------------------------------------------
# Graph builder — populates the KG with all known Okta tool capabilities
# and data-flow edges.  NO workflows, NO intents.
# ---------------------------------------------------------------------------

def build_okta_knowledge_graph() -> OktaKnowledgeGraph:
    """Construct the Okta capability graph."""
    kg = OktaKnowledgeGraph()

    # ===================================================================
    # TOOL NODES
    # ===================================================================

    # ── Users ──
    kg.add_node(ToolNode(
        action="get_user",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Look up a user by ID, login, email, or display name",
        required_params=["user_id"],
        outputs=["id", "profile", "status"],
        tags=["lookup", "identity", "resolve"],
    ))
    kg.add_node(ToolNode(
        action="list_users",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Search or list users with optional filters",
        required_params=[],
        optional_params=["search", "filter", "q", "limit"],
        outputs=["items"],
        tags=["search", "bulk", "filter"],
    ))
    kg.add_node(ToolNode(
        action="deactivate_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Deactivate a user account",
        required_params=["user_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["lifecycle", "disable", "offboard"],
    ))
    kg.add_node(ToolNode(
        action="suspend_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Suspend a user account (reversible)",
        required_params=["user_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["lifecycle", "temporary", "lock"],
    ))
    kg.add_node(ToolNode(
        action="activate_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Activate a user account and optionally send activation email",
        required_params=["user_id"],
        optional_params=["send_email"],
        outputs=["status", "activation_token"],
        tags=["lifecycle", "enable", "onboard"],
    ))
    kg.add_node(ToolNode(
        action="clear_user_sessions",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Revoke all active sessions for a user (forces sign-out)",
        required_params=["user_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["session", "security", "revoke"],
    ))

    # ── Groups ──
    kg.add_node(ToolNode(
        action="list_user_groups",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all groups a user belongs to",
        required_params=["user_id"],
        outputs=["items"],
        tags=["membership", "enumerate"],
    ))
    kg.add_node(ToolNode(
        action="remove_user_from_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Remove a user from a group",
        required_params=["group_id", "user_id"],
        outputs=["status"],
        is_destructive=True,
        is_iterable=True,
        tags=["membership", "revoke", "access"],
    ))
    kg.add_node(ToolNode(
        action="add_user_to_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Add a user to a group",
        required_params=["group_id", "user_id"],
        outputs=["status"],
        tags=["membership", "grant", "access"],
    ))
    kg.add_node(ToolNode(
        action="get_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="Get a group by ID or name",
        required_params=[],
        optional_params=["group_id", "name"],
        outputs=["id", "profile"],
        tags=["lookup", "resolve"],
    ))

    # ── Applications ──
    kg.add_node(ToolNode(
        action="list_user_app_assignments",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="List all application assignments for a user",
        required_params=["user_id"],
        outputs=["items"],
        tags=["assignment", "enumerate", "access"],
    ))
    kg.add_node(ToolNode(
        action="list_applications",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="List all applications from the Okta organization",
        required_params=[],
        optional_params=["q", "after", "limit", "filter", "expand"],
        outputs=["items"],
        tags=["search", "bulk", "filter"],
    ))
    kg.add_node(ToolNode(
        action="get_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="Get an application by ID",
        required_params=["app_id"],
        optional_params=["expand"],
        outputs=["id", "label", "status", "signOnMode", "settings"],
        tags=["lookup", "resolve"],
    ))
    kg.add_node(ToolNode(
        action="create_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Create a new application in the Okta organization",
        required_params=["app_config"],
        optional_params=["activate"],
        outputs=["id", "label", "status"],
        tags=["create", "onboard"],
    ))
    kg.add_node(ToolNode(
        action="update_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Update an application by ID",
        required_params=["app_id", "app_config"],
        outputs=["id", "label", "status"],
        tags=["update", "modify"],
    ))
    kg.add_node(ToolNode(
        action="delete_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.DELETE,
        description="Delete an application by ID",
        required_params=["app_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove"],
    ))
    kg.add_node(ToolNode(
        action="activate_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Activate an application",
        required_params=["app_id"],
        outputs=["status"],
        tags=["lifecycle", "enable"],
    ))
    kg.add_node(ToolNode(
        action="deactivate_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Deactivate an application",
        required_params=["app_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["lifecycle", "disable"],
    ))

    # ── Users (additional) ──
    kg.add_node(ToolNode(
        action="create_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Create a new user in the Okta organization",
        required_params=["profile"],
        outputs=["id", "profile", "status"],
        tags=["create", "onboard", "identity"],
    ))
    kg.add_node(ToolNode(
        action="update_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Update an existing user's profile",
        required_params=["user_id", "profile"],
        outputs=["id", "profile", "status"],
        tags=["update", "modify", "identity"],
    ))
    kg.add_node(ToolNode(
        action="delete_deactivated_user",
        entity_type=EntityType.USER,
        operation=OperationType.DELETE,
        description="Permanently delete a deactivated or deprovisioned user",
        required_params=["user_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "offboard"],
    ))
    kg.add_node(ToolNode(
        action="get_user_profile_attributes",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all user profile attributes supported by the Okta org",
        required_params=[],
        outputs=["attributes"],
        tags=["schema", "profile", "introspect"],
    ))

    # ── Groups (additional) ──
    kg.add_node(ToolNode(
        action="list_groups",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List or search groups in the Okta organization",
        required_params=[],
        optional_params=["search", "filter", "q", "limit"],
        outputs=["items"],
        tags=["search", "bulk", "filter"],
    ))
    kg.add_node(ToolNode(
        action="create_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Create a new group in the Okta organization",
        required_params=["profile"],
        outputs=["id", "profile"],
        tags=["create", "onboard"],
    ))
    kg.add_node(ToolNode(
        action="delete_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.DELETE,
        description="Delete a group by ID",
        required_params=["group_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove"],
    ))
    kg.add_node(ToolNode(
        action="update_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Update a group by ID with a new profile",
        required_params=["group_id", "profile"],
        outputs=["id", "profile"],
        tags=["update", "modify"],
    ))
    kg.add_node(ToolNode(
        action="list_group_users",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all users in a group",
        required_params=["group_id"],
        optional_params=["limit", "after"],
        outputs=["items"],
        tags=["membership", "enumerate"],
    ))
    kg.add_node(ToolNode(
        action="list_group_apps",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all applications assigned to a group",
        required_params=["group_id"],
        outputs=["items"],
        tags=["assignment", "enumerate", "access"],
    ))

    # ── Policies ──
    kg.add_node(ToolNode(
        action="list_policies",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="List policies by type with optional status and query filters",
        required_params=["type"],
        optional_params=["status", "q", "limit", "after"],
        outputs=["items"],
        tags=["search", "bulk", "filter"],
    ))
    kg.add_node(ToolNode(
        action="get_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="Retrieve a specific policy by ID",
        required_params=["policy_id"],
        outputs=["id", "type", "name", "status", "conditions", "settings"],
        tags=["lookup", "resolve"],
    ))
    kg.add_node(ToolNode(
        action="create_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Create a new policy",
        required_params=["policy_data"],
        outputs=["id", "type", "name", "status"],
        tags=["create"],
    ))
    kg.add_node(ToolNode(
        action="update_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Update an existing policy",
        required_params=["policy_id", "policy_data"],
        outputs=["id", "type", "name", "status"],
        tags=["update", "modify"],
    ))
    kg.add_node(ToolNode(
        action="delete_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.DELETE,
        description="Delete a policy",
        required_params=["policy_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove"],
    ))
    kg.add_node(ToolNode(
        action="activate_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Activate a policy",
        required_params=["policy_id"],
        outputs=["status"],
        tags=["lifecycle", "enable"],
    ))
    kg.add_node(ToolNode(
        action="deactivate_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Deactivate a policy",
        required_params=["policy_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["lifecycle", "disable"],
    ))

    # ── Policy Rules ──
    kg.add_node(ToolNode(
        action="list_policy_rules",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.READ,
        description="List all rules for a specific policy",
        required_params=["policy_id"],
        outputs=["items"],
        tags=["search", "enumerate"],
    ))
    kg.add_node(ToolNode(
        action="get_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.READ,
        description="Retrieve a specific policy rule",
        required_params=["policy_id", "rule_id"],
        outputs=["id", "name", "status", "conditions", "actions"],
        tags=["lookup", "resolve"],
    ))
    kg.add_node(ToolNode(
        action="create_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Create a new rule for a policy",
        required_params=["policy_id", "rule_data"],
        outputs=["id", "name", "status"],
        tags=["create"],
    ))
    kg.add_node(ToolNode(
        action="update_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Update an existing policy rule",
        required_params=["policy_id", "rule_id", "rule_data"],
        outputs=["id", "name", "status"],
        tags=["update", "modify"],
    ))
    kg.add_node(ToolNode(
        action="delete_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.DELETE,
        description="Delete a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove"],
    ))
    kg.add_node(ToolNode(
        action="activate_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Activate a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs=["status"],
        tags=["lifecycle", "enable"],
    ))
    kg.add_node(ToolNode(
        action="deactivate_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Deactivate a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["lifecycle", "disable"],
    ))

    # ── Device Assurance ──
    kg.add_node(ToolNode(
        action="list_device_assurance_policies",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.READ,
        description="List all device assurance policies",
        required_params=[],
        outputs=["items"],
        tags=["search", "bulk", "audit"],
    ))
    kg.add_node(ToolNode(
        action="get_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.READ,
        description="Retrieve a specific device assurance policy by ID",
        required_params=["device_assurance_id"],
        outputs=["id", "name", "platform", "osVersion", "status"],
        tags=["lookup", "resolve"],
    ))
    kg.add_node(ToolNode(
        action="create_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.WRITE,
        description="Create a new device assurance policy",
        required_params=["policy_data"],
        outputs=["id", "name", "platform", "status"],
        tags=["create"],
    ))
    kg.add_node(ToolNode(
        action="replace_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.WRITE,
        description="Replace (fully update) an existing device assurance policy",
        required_params=["device_assurance_id", "policy_data"],
        outputs=["id", "name", "platform", "status", "changes"],
        tags=["update", "modify", "replace"],
    ))
    kg.add_node(ToolNode(
        action="delete_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.DELETE,
        description="Delete a device assurance policy",
        required_params=["device_assurance_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove"],
    ))

    # ── System Logs ──
    kg.add_node(ToolNode(
        action="get_logs",
        entity_type=EntityType.LOG,
        operation=OperationType.READ,
        description="Retrieve system logs from the Okta organization",
        required_params=[],
        optional_params=["since", "until", "filter", "q", "limit", "after"],
        outputs=["items"],
        tags=["audit", "search", "events", "monitoring"],
    ))

    # ── Brands ──
    kg.add_node(ToolNode(
        action="list_brands",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="List all brands in the Okta organization",
        required_params=[],
        outputs=["items"],
        tags=["search", "bulk", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="Get a brand by ID",
        required_params=["brand_id"],
        outputs=["id", "name", "custom_privacy_policy_url"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="create_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.WRITE,
        description="Create a new brand",
        required_params=["brand_data"],
        outputs=["id", "name"],
        tags=["create", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.WRITE,
        description="Replace (update) a brand",
        required_params=["brand_id", "brand_data"],
        outputs=["id", "name"],
        tags=["update", "modify", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.DELETE,
        description="Delete a brand",
        required_params=["brand_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "customization"],
    ))
    kg.add_node(ToolNode(
        action="list_brand_domains",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="List all domains associated with a brand",
        required_params=["brand_id"],
        outputs=["items"],
        tags=["enumerate", "customization"],
    ))

    # ── Custom Domains ──
    kg.add_node(ToolNode(
        action="list_custom_domains",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.READ,
        description="List all custom domains",
        required_params=[],
        outputs=["items"],
        tags=["search", "bulk", "customization"],
    ))
    kg.add_node(ToolNode(
        action="create_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Create a new custom domain",
        required_params=["domain_data"],
        outputs=["id", "domain"],
        tags=["create", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.READ,
        description="Get a custom domain by ID",
        required_params=["domain_id"],
        outputs=["id", "domain", "status"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Replace (update) a custom domain",
        required_params=["domain_id", "domain_data"],
        outputs=["id", "domain"],
        tags=["update", "modify", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.DELETE,
        description="Delete a custom domain",
        required_params=["domain_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "customization"],
    ))
    kg.add_node(ToolNode(
        action="upsert_custom_domain_certificate",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Upsert a certificate for a custom domain",
        required_params=["domain_id", "certificate_data"],
        outputs=["status"],
        tags=["certificate", "ssl", "customization"],
    ))
    kg.add_node(ToolNode(
        action="verify_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Verify a custom domain",
        required_params=["domain_id"],
        outputs=["status"],
        tags=["verify", "dns", "customization"],
    ))

    # ── Email Domains ──
    kg.add_node(ToolNode(
        action="list_email_domains",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.READ,
        description="List all email domains",
        required_params=[],
        outputs=["items"],
        tags=["search", "bulk", "customization"],
    ))
    kg.add_node(ToolNode(
        action="create_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Create a new email domain",
        required_params=["email_domain_data"],
        outputs=["id", "domain"],
        tags=["create", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.READ,
        description="Get an email domain by ID",
        required_params=["email_domain_id"],
        outputs=["id", "domain", "status"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Replace (update) an email domain",
        required_params=["email_domain_id", "email_domain_data"],
        outputs=["id", "domain"],
        tags=["update", "modify", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.DELETE,
        description="Delete an email domain",
        required_params=["email_domain_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "customization"],
    ))
    kg.add_node(ToolNode(
        action="verify_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Verify an email domain",
        required_params=["email_domain_id"],
        outputs=["status"],
        tags=["verify", "dns", "customization"],
    ))

    # ── Themes ──
    kg.add_node(ToolNode(
        action="list_brand_themes",
        entity_type=EntityType.THEME,
        operation=OperationType.READ,
        description="List all themes for a brand",
        required_params=["brand_id"],
        outputs=["items"],
        tags=["search", "enumerate", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_brand_theme",
        entity_type=EntityType.THEME,
        operation=OperationType.READ,
        description="Get a specific theme for a brand",
        required_params=["brand_id", "theme_id"],
        outputs=["id", "primaryColorHex", "secondaryColorHex"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_brand_theme",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Replace (update) a theme for a brand",
        required_params=["brand_id", "theme_id", "theme_data"],
        outputs=["id"],
        tags=["update", "modify", "customization"],
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_logo",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a logo for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs=["status"],
        tags=["upload", "logo", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_logo",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the logo for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "logo", "customization"],
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_favicon",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a favicon for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs=["status"],
        tags=["upload", "favicon", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_favicon",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the favicon for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "favicon", "customization"],
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_background_image",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a background image for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs=["status"],
        tags=["upload", "background", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_background_image",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the background image for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "background", "customization"],
    ))

    # ── Custom Pages ──
    kg.add_node(ToolNode(
        action="get_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the customized error page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "error_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the customized error page for a brand",
        required_params=["brand_id", "page_content"],
        outputs=["page_content"],
        tags=["update", "error_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the customized error page for a brand (revert to default)",
        required_params=["brand_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "error_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_default_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the default error page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "error_page", "default", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the preview error page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "error_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the preview error page for a brand",
        required_params=["brand_id", "page_content"],
        outputs=["page_content"],
        tags=["update", "error_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the preview error page for a brand",
        required_params=["brand_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "error_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_error_page_resources",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the error page resources for a brand",
        required_params=["brand_id"],
        outputs=["resources"],
        tags=["lookup", "error_page", "resources", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the customized sign-in page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "sign_in_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the customized sign-in page for a brand",
        required_params=["brand_id", "page_content"],
        outputs=["page_content"],
        tags=["update", "sign_in_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the customized sign-in page for a brand (revert to default)",
        required_params=["brand_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "sign_in_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_default_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the default sign-in page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "sign_in_page", "default", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the preview sign-in page for a brand",
        required_params=["brand_id"],
        outputs=["page_content"],
        tags=["lookup", "sign_in_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the preview sign-in page for a brand",
        required_params=["brand_id", "page_content"],
        outputs=["page_content"],
        tags=["update", "sign_in_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the preview sign-in page for a brand",
        required_params=["brand_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "sign_in_page", "preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_sign_in_page_resources",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the sign-in page resources for a brand",
        required_params=["brand_id"],
        outputs=["resources"],
        tags=["lookup", "sign_in_page", "resources", "customization"],
    ))
    kg.add_node(ToolNode(
        action="list_sign_in_widget_versions",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="List all available sign-in widget versions",
        required_params=[],
        outputs=["items"],
        tags=["search", "sign_in_page", "widget", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_sign_out_page_settings",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the sign-out page settings for a brand",
        required_params=["brand_id"],
        outputs=["settings"],
        tags=["lookup", "sign_out_page", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_sign_out_page_settings",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the sign-out page settings for a brand",
        required_params=["brand_id", "settings"],
        outputs=["settings"],
        tags=["update", "sign_out_page", "customization"],
    ))

    # ── Email Templates ──
    kg.add_node(ToolNode(
        action="list_email_templates",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="List all email templates for a brand",
        required_params=["brand_id"],
        outputs=["items"],
        tags=["search", "enumerate", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_template",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get a specific email template for a brand",
        required_params=["brand_id", "template_name"],
        outputs=["template"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="list_email_customizations",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="List all customizations for an email template",
        required_params=["brand_id", "template_name"],
        outputs=["items"],
        tags=["search", "enumerate", "customization"],
    ))
    kg.add_node(ToolNode(
        action="create_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Create a customization for an email template",
        required_params=["brand_id", "template_name", "customization_data"],
        outputs=["id"],
        tags=["create", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get a specific email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs=["id", "language", "subject", "body"],
        tags=["lookup", "resolve", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Replace an email customization",
        required_params=["brand_id", "template_name", "customization_id", "customization_data"],
        outputs=["id"],
        tags=["update", "modify", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.DELETE,
        description="Delete an email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "customization"],
    ))
    kg.add_node(ToolNode(
        action="delete_all_email_customizations",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.DELETE,
        description="Delete all customizations for an email template",
        required_params=["brand_id", "template_name"],
        outputs=["status"],
        is_destructive=True,
        tags=["delete", "remove", "bulk", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_customization_preview",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Preview an email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs=["preview"],
        tags=["preview", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_default_content",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get the default content for an email template",
        required_params=["brand_id", "template_name"],
        outputs=["content"],
        tags=["lookup", "default", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_default_content_preview",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Preview the default content for an email template",
        required_params=["brand_id", "template_name"],
        outputs=["preview"],
        tags=["preview", "default", "customization"],
    ))
    kg.add_node(ToolNode(
        action="get_email_settings",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get email settings for a template",
        required_params=["brand_id", "template_name"],
        outputs=["settings"],
        tags=["lookup", "settings", "customization"],
    ))
    kg.add_node(ToolNode(
        action="replace_email_settings",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Replace email settings for a template",
        required_params=["brand_id", "template_name", "settings"],
        outputs=["settings"],
        tags=["update", "settings", "customization"],
    ))
    kg.add_node(ToolNode(
        action="send_test_email",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Send a test email for a template customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs=["status"],
        tags=["test", "send", "customization"],
    ))

    # ===================================================================
    # EDGES — data-flow dependencies
    # ===================================================================

    # get_user produces user_id for downstream tools
    for target in [
        "list_user_groups", "deactivate_user", "suspend_user",
        "activate_user", "clear_user_sessions", "list_user_app_assignments",
        "remove_user_from_group", "add_user_to_group",
    ]:
        kg.add_edge(Edge(
            source="get_user",
            target=target,
            source_output="id",
            target_param="user_id",
            description=f"User ID from lookup feeds into {target}",
        ))

    # list_user_groups → remove_user_from_group (iteration over group list)
    kg.add_edge(Edge(
        source="list_user_groups",
        target="remove_user_from_group",
        source_output="items",
        target_param="group_id",
        description="Iterate over groups to remove user from each",
        is_iteration=True,
    ))

    # get_group → add_user_to_group
    kg.add_edge(Edge(
        source="get_group",
        target="add_user_to_group",
        source_output="id",
        target_param="group_id",
        description="Group ID from lookup feeds into add_user_to_group",
    ))

    # get_user → user write operations (additional)
    for target in ["update_user", "delete_deactivated_user"]:
        kg.add_edge(Edge(
            source="get_user",
            target=target,
            source_output="id",
            target_param="user_id",
            description=f"User ID from lookup feeds into {target}",
        ))

    # get_group → group operations that need group_id
    for target in [
        "delete_group", "update_group", "list_group_users", "list_group_apps",
    ]:
        kg.add_edge(Edge(
            source="get_group",
            target=target,
            source_output="id",
            target_param="group_id",
            description=f"Group ID from lookup feeds into {target}",
        ))

    # get_application → application operations that need app_id
    for target in [
        "update_application", "delete_application",
        "activate_application", "deactivate_application",
    ]:
        kg.add_edge(Edge(
            source="get_application",
            target=target,
            source_output="id",
            target_param="app_id",
            description=f"Application ID from lookup feeds into {target}",
        ))

    # get_policy → policy operations that need policy_id
    for target in [
        "update_policy", "delete_policy", "activate_policy",
        "deactivate_policy", "list_policy_rules", "create_policy_rule",
    ]:
        kg.add_edge(Edge(
            source="get_policy",
            target=target,
            source_output="id",
            target_param="policy_id",
            description=f"Policy ID from lookup feeds into {target}",
        ))

    # get_policy_rule → policy rule operations that need rule_id
    for target in [
        "update_policy_rule", "delete_policy_rule",
        "activate_policy_rule", "deactivate_policy_rule",
    ]:
        kg.add_edge(Edge(
            source="get_policy_rule",
            target=target,
            source_output="id",
            target_param="rule_id",
            description=f"Rule ID from lookup feeds into {target}",
        ))

    # list_policy_rules → get_policy_rule (drill into a specific rule)
    kg.add_edge(Edge(
        source="list_policy_rules",
        target="get_policy_rule",
        source_output="items",
        target_param="rule_id",
        description="Rule list feeds into get_policy_rule for drill-down",
        is_iteration=True,
    ))

    # get_device_assurance_policy → device assurance write operations
    for target in [
        "replace_device_assurance_policy", "delete_device_assurance_policy",
    ]:
        kg.add_edge(Edge(
            source="get_device_assurance_policy",
            target=target,
            source_output="id",
            target_param="device_assurance_id",
            description=f"Device assurance ID from lookup feeds into {target}",
        ))

    # get_brand → brand-dependent operations
    for target in [
        "replace_brand", "delete_brand", "list_brand_domains",
        "list_brand_themes", "list_email_templates",
        "get_customized_error_page", "replace_customized_error_page",
        "delete_customized_error_page", "get_default_error_page",
        "get_preview_error_page", "replace_preview_error_page",
        "delete_preview_error_page", "get_error_page_resources",
        "get_customized_sign_in_page", "replace_customized_sign_in_page",
        "delete_customized_sign_in_page", "get_default_sign_in_page",
        "get_preview_sign_in_page", "replace_preview_sign_in_page",
        "delete_preview_sign_in_page", "get_sign_in_page_resources",
        "get_sign_out_page_settings", "replace_sign_out_page_settings",
    ]:
        kg.add_edge(Edge(
            source="get_brand",
            target=target,
            source_output="id",
            target_param="brand_id",
            description=f"Brand ID from lookup feeds into {target}",
        ))

    # get_brand_theme → theme operations that need brand_id + theme_id
    for target in [
        "replace_brand_theme",
        "upload_brand_theme_logo", "delete_brand_theme_logo",
        "upload_brand_theme_favicon", "delete_brand_theme_favicon",
        "upload_brand_theme_background_image", "delete_brand_theme_background_image",
    ]:
        kg.add_edge(Edge(
            source="get_brand_theme",
            target=target,
            source_output="id",
            target_param="theme_id",
            description=f"Theme ID from lookup feeds into {target}",
        ))

    # get_custom_domain → custom domain operations
    for target in [
        "replace_custom_domain", "delete_custom_domain",
        "upsert_custom_domain_certificate", "verify_custom_domain",
    ]:
        kg.add_edge(Edge(
            source="get_custom_domain",
            target=target,
            source_output="id",
            target_param="domain_id",
            description=f"Domain ID from lookup feeds into {target}",
        ))

    # get_email_domain → email domain operations
    for target in [
        "replace_email_domain", "delete_email_domain", "verify_email_domain",
    ]:
        kg.add_edge(Edge(
            source="get_email_domain",
            target=target,
            source_output="id",
            target_param="email_domain_id",
            description=f"Email domain ID from lookup feeds into {target}",
        ))

    # get_email_template → email template operations
    for target in [
        "list_email_customizations", "create_email_customization",
        "get_email_default_content", "get_email_default_content_preview",
        "get_email_settings", "replace_email_settings",
        "delete_all_email_customizations",
    ]:
        kg.add_edge(Edge(
            source="get_email_template",
            target=target,
            source_output="template",
            target_param="template_name",
            description=f"Template name from lookup feeds into {target}",
        ))

    # get_email_customization → email customization operations
    for target in [
        "replace_email_customization", "delete_email_customization",
        "get_email_customization_preview", "send_test_email",
    ]:
        kg.add_edge(Edge(
            source="get_email_customization",
            target=target,
            source_output="id",
            target_param="customization_id",
            description=f"Customization ID from lookup feeds into {target}",
        ))

    logger.info(
        f"Knowledge graph built: {len(kg._nodes)} nodes, "
        f"{len(kg._edges)} edges"
    )
    return kg


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_graph: OktaKnowledgeGraph | None = None


def get_knowledge_graph() -> OktaKnowledgeGraph:
    """Return the singleton knowledge graph, building it on first access."""
    global _graph
    if _graph is None:
        _graph = build_okta_knowledge_graph()
    return _graph


def reset_knowledge_graph() -> None:
    """Reset the singleton — used in tests."""
    global _graph
    _graph = None
