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
    """A node representing a single Okta SDK action.

    Enriched outputs and param_bindings replace the old Edge-based wiring:
      - outputs: dict mapping output field name → predicate key.
        Suffix '[]' marks array outputs (e.g. "user.groups[]").
      - param_bindings: dict mapping required param name → predicate key.
        Suffix '[]' signals the engine should iterate over the array.
    """
    action: str                               # dispatcher key, e.g. "get_user"
    entity_type: EntityType
    operation: OperationType
    description: str
    required_params: list[str]                # params that MUST be supplied
    optional_params: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)          # field → predicate_key ([] = array)
    param_bindings: dict[str, str] = field(default_factory=dict)   # param → predicate_key ([] = iterate)
    is_destructive: bool = False
    tags: list[str] = field(default_factory=list)  # free-form labels for searching
    # Planning semantics for CSP solver
    preconditions: dict[str, str] = field(default_factory=dict)  # state required before execution
    effects: dict[str, str] = field(default_factory=dict)        # state changes after execution




# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

class OktaKnowledgeGraph:
    """In-memory directed capability graph — no predefined workflows.

    Connectivity is derived from precondition/effect matching (no explicit edges).
    Tool A connects to Tool B when A produces an effect that satisfies one of
    B's preconditions.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, ToolNode] = {}
        # Virtual adjacency — lazily computed from effects ↔ preconditions
        self._fwd: dict[str, list[str]] | None = None   # action → downstream actions
        self._rev: dict[str, list[str]] | None = None   # action → upstream actions

    # ── Node management ──

    def add_node(self, node: ToolNode) -> None:
        self._nodes[node.action] = node
        self._fwd = None  # invalidate cache
        self._rev = None

    def get_node(self, action: str) -> ToolNode | None:
        return self._nodes.get(action)

    # ── Virtual adjacency (replaces explicit edges) ──

    def _ensure_adjacency(self) -> None:
        """Build forward/reverse adjacency from effects → preconditions."""
        if self._fwd is not None:
            return
        fwd: dict[str, list[str]] = {a: [] for a in self._nodes}
        rev: dict[str, list[str]] = {a: [] for a in self._nodes}
        for a_name, a_node in self._nodes.items():
            for b_name, b_node in self._nodes.items():
                if a_name == b_name:
                    continue
                for pk, pv in b_node.preconditions.items():
                    if a_node.effects.get(pk) == pv:
                        fwd[a_name].append(b_name)
                        rev[b_name].append(a_name)
                        break  # one match is enough
        self._fwd = fwd
        self._rev = rev

    def get_downstream(self, action: str) -> list[str]:
        """Actions whose preconditions are satisfied by this action's effects."""
        self._ensure_adjacency()
        return self._fwd.get(action, [])

    def get_upstream(self, action: str) -> list[str]:
        """Actions whose effects satisfy this action's preconditions."""
        self._ensure_adjacency()
        return self._rev.get(action, [])

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
        """BFS from start_action — return all reachable tools with depth.

        Connectivity is derived from effects → preconditions matching.
        """
        if start_action not in self._nodes:
            return {"error": f"Unknown action '{start_action}'", "nodes": []}

        self._ensure_adjacency()
        visited: dict[str, int] = {start_action: 0}
        queue: deque[str] = deque([start_action])

        while queue:
            current = queue.popleft()
            depth = visited[current]
            if depth >= max_depth:
                continue
            for target in self.get_downstream(current):
                if target not in visited:
                    visited[target] = depth + 1
                    queue.append(target)

        nodes = [
            {**self._serialise_node(self._nodes[a]), "depth": d}
            for a, d in visited.items()
        ]
        return {"nodes": nodes}

    def query_dependencies(self, target_action: str) -> dict:
        """Reverse BFS — what tools must run before target_action?

        Connectivity is derived from effects → preconditions matching.
        """
        if target_action not in self._nodes:
            return {"error": f"Unknown action '{target_action}'", "nodes": []}

        self._ensure_adjacency()
        visited: dict[str, int] = {target_action: 0}
        queue: deque[str] = deque([target_action])

        while queue:
            current = queue.popleft()
            depth = visited[current]
            for source in self.get_upstream(current):
                if source not in visited:
                    visited[source] = depth + 1
                    queue.append(source)

        nodes = [
            {**self._serialise_node(self._nodes[a]), "depth": d}
            for a, d in visited.items()
        ]
        return {"nodes": nodes}

    def query_path(self, start_action: str, end_action: str) -> list[str] | None:
        """Find shortest path between two tools via precondition/effect links.

        Returns an ordered list of action names from start to end, or None
        if no path exists.
        """
        if start_action not in self._nodes or end_action not in self._nodes:
            return None

        self._ensure_adjacency()
        parent: dict[str, str | None] = {start_action: None}
        queue: deque[str] = deque([start_action])

        while queue:
            current = queue.popleft()
            if current == end_action:
                path: list[str] = []
                node = end_action
                while node is not None:
                    path.append(node)
                    node = parent[node]
                path.reverse()
                return path
            for target in self.get_downstream(current):
                if target not in parent:
                    parent[target] = current
                    queue.append(target)

        return None  # no path

    def build_execution_chain(self, actions: list[str]) -> list[dict]:
        """Given an ordered list of actions, resolve parameter bindings
        from enriched outputs and param_bindings — no edges needed.

        Returns a list of step dicts:
            [{"step": 1, "action": ..., "params": {...}, "description": ...,
              "is_destructive": ..., "for_each": ...}, ...]

        Wiring algorithm:
          1. Each step registers its enriched outputs as produced predicates.
          2. For subsequent steps, param_bindings map each param to a predicate key.
          3. If a prior step produced that predicate, the param is wired to
             "$stepN.field".
          4. If the prior output was array-typed ([]) and the binding is scalar,
             the step is set up for for_each iteration.
        """
        steps: list[dict] = []
        # predicate_key → (step_number, output_field_name, is_array)
        produced: dict[str, tuple[int, str, bool]] = {}

        for idx, action_name in enumerate(actions):
            node = self._nodes.get(action_name)
            if not node:
                raise ValueError(f"Unknown action '{action_name}'")

            step_num = idx + 1
            params: dict[str, Any] = {}
            for_each: str | None = None

            # Wire params from prior steps using param_bindings
            for param_name, pred_key in node.param_bindings.items():
                is_iter_binding = pred_key.endswith("[]")
                clean_key = pred_key.rstrip("[]")

                if clean_key in produced:
                    src_step, src_field, src_is_array = produced[clean_key]
                    if is_iter_binding or src_is_array:
                        # Array → scalar mismatch: iterate
                        for_each = f"$step{src_step}"
                    else:
                        params[param_name] = f"$step{src_step}.{src_field}"

            # Register this step's enriched outputs as produced predicates
            for field_name, pred_key in node.outputs.items():
                is_array = pred_key.endswith("[]")
                clean_key = pred_key.rstrip("[]")
                produced[clean_key] = (step_num, field_name, is_array)

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
        self._ensure_adjacency()
        # Count virtual connections (effect→precondition links)
        total_connections = sum(len(targets) for targets in self._fwd.values())
        return {
            "total_nodes": len(self._nodes),
            "total_connections": total_connections,
            "entity_types": sorted({n.entity_type.value for n in self._nodes.values()}),
            "operations": sorted({n.operation.value for n in self._nodes.values()}),
        }

    def to_dict(self) -> dict:
        """Full graph serialisation."""
        return {
            "nodes": {k: self._serialise_node(v) for k, v in self._nodes.items()},
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
            "param_bindings": node.param_bindings,
            "is_destructive": node.is_destructive,
            "tags": node.tags,
            "preconditions": node.preconditions,
            "effects": node.effects,
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
        outputs={'id': 'user.id', 'profile': 'user.profile', 'status': 'user.status'},
        tags=["lookup", "identity", "resolve"],
        preconditions={"user.identifier": "PROVIDED"},
        effects={"user.id": "KNOWN", "user.status": "KNOWN", "user.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_users",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Search or list users with optional filters",
        required_params=[],
        optional_params=["search", "filter", "q", "limit"],
        outputs={'items': 'user.list[]'},
        tags=["search", "bulk", "filter"],
        preconditions={},
        effects={"user.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Deactivate a user account",
        required_params=["user_id"],
        outputs={'status': 'user.status'},
        param_bindings={'user_id': 'user.id'},
        is_destructive=True,
        tags=["lifecycle", "disable", "offboard"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "DEACTIVATED"},
    ))
    kg.add_node(ToolNode(
        action="suspend_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Suspend a user account (reversible)",
        required_params=["user_id"],
        outputs={'status': 'user.status'},
        param_bindings={'user_id': 'user.id'},
        is_destructive=True,
        tags=["lifecycle", "temporary", "lock"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "SUSPENDED"},
    ))
    kg.add_node(ToolNode(
        action="activate_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Activate a user account and optionally send activation email",
        required_params=["user_id"],
        optional_params=["send_email"],
        outputs={'status': 'user.status', 'activation_token': 'user.activation_token'},
        param_bindings={'user_id': 'user.id'},
        tags=["lifecycle", "enable", "onboard"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="clear_user_sessions",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Revoke all active sessions for a user (forces sign-out)",
        required_params=["user_id"],
        outputs={'status': 'user.sessions'},
        param_bindings={'user_id': 'user.id'},
        is_destructive=True,
        tags=["session", "security", "revoke"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.sessions": "REVOKED"},
    ))

    # ── Groups ──
    kg.add_node(ToolNode(
        action="list_user_groups",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all groups a user belongs to",
        required_params=["user_id"],
        outputs={'items': 'user.groups[]'},
        param_bindings={'user_id': 'user.id'},
        tags=["membership", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.groups": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="remove_user_from_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Remove a user from a group",
        required_params=["group_id", "user_id"],
        outputs={'status': 'user.group_memberships'},
        param_bindings={'user_id': 'user.id', 'group_id': 'user.groups[]'},
        is_destructive=True,
        tags=["membership", "revoke", "access"],
        preconditions={"user.id": "KNOWN", "user.groups": "ENUMERATED"},
        effects={"user.group_memberships": "REVOKED"},
    ))
    kg.add_node(ToolNode(
        action="add_user_to_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Add a user to a group",
        required_params=["group_id", "user_id"],
        outputs={'status': 'user.group_membership'},
        param_bindings={'user_id': 'user.id', 'group_id': 'group.id'},
        tags=["membership", "grant", "access"],
        preconditions={"user.id": "KNOWN", "group.id": "KNOWN"},
        effects={"user.group_membership": "GRANTED"},
    ))
    kg.add_node(ToolNode(
        action="get_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="Get a group by ID or name",
        required_params=[],
        optional_params=["group_id", "name"],
        outputs={'id': 'group.id', 'profile': 'group.profile'},
        tags=["lookup", "resolve"],
        preconditions={"group.identifier": "PROVIDED"},
        effects={"group.id": "KNOWN", "group.profile": "KNOWN"},
    ))

    # ── Applications ──
    kg.add_node(ToolNode(
        action="list_user_app_assignments",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="List all application assignments for a user",
        required_params=["user_id"],
        outputs={'items': 'user.apps[]'},
        param_bindings={'user_id': 'user.id'},
        tags=["assignment", "enumerate", "access"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.apps": "AUDITED"},
    ))
    kg.add_node(ToolNode(
        action="list_applications",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="List all applications from the Okta organization",
        required_params=[],
        optional_params=["q", "after", "limit", "filter", "expand"],
        outputs={'items': 'application.list[]'},
        tags=["search", "bulk", "filter"],
        preconditions={},
        effects={"application.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.READ,
        description="Get an application by ID",
        required_params=["app_id"],
        optional_params=["expand"],
        outputs={'id': 'application.id', 'label': 'application.label', 'status': 'application.status', 'signOnMode': 'application.signOnMode', 'settings': 'application.settings'},
        tags=["lookup", "resolve"],
        preconditions={"application.identifier": "PROVIDED"},
        effects={"application.id": "KNOWN", "application.status": "KNOWN", "application.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Create a new application in the Okta organization",
        required_params=["app_config"],
        optional_params=["activate"],
        outputs={'id': 'application.id', 'label': 'application.label', 'status': 'application.status'},
        tags=["create", "onboard"],
        preconditions={"application.config": "PROVIDED"},
        effects={"application.id": "KNOWN", "application.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="update_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Update an application by ID",
        required_params=["app_id", "app_config"],
        outputs={'id': 'application.id', 'label': 'application.label', 'status': 'application.status'},
        param_bindings={'app_id': 'application.id'},
        tags=["update", "modify"],
        preconditions={"application.id": "KNOWN", "application.config": "PROVIDED"},
        effects={"application.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.DELETE,
        description="Delete an application by ID",
        required_params=["app_id"],
        outputs={'status': 'application.status'},
        param_bindings={'app_id': 'application.id'},
        is_destructive=True,
        tags=["delete", "remove"],
        preconditions={"application.id": "KNOWN"},
        effects={"application.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Activate an application",
        required_params=["app_id"],
        outputs={'status': 'application.status'},
        param_bindings={'app_id': 'application.id'},
        tags=["lifecycle", "enable"],
        preconditions={"application.id": "KNOWN"},
        effects={"application.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_application",
        entity_type=EntityType.APPLICATION,
        operation=OperationType.WRITE,
        description="Deactivate an application",
        required_params=["app_id"],
        outputs={'status': 'application.status'},
        param_bindings={'app_id': 'application.id'},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"application.id": "KNOWN"},
        effects={"application.status": "DEACTIVATED"},
    ))

    # ── Users (additional) ──
    kg.add_node(ToolNode(
        action="create_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Create a new user in the Okta organization",
        required_params=["profile"],
        outputs={'id': 'user.id', 'profile': 'user.profile', 'status': 'user.status'},
        tags=["create", "onboard", "identity"],
        preconditions={"user.profile_data": "PROVIDED"},
        effects={"user.id": "KNOWN", "user.status": "CREATED", "user.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="update_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Update an existing user's profile",
        required_params=["user_id", "profile"],
        outputs={'id': 'user.id', 'profile': 'user.profile', 'status': 'user.status'},
        param_bindings={'user_id': 'user.id'},
        tags=["update", "modify", "identity"],
        preconditions={"user.id": "KNOWN", "user.profile_data": "PROVIDED"},
        effects={"user.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_deactivated_user",
        entity_type=EntityType.USER,
        operation=OperationType.DELETE,
        description="Permanently delete a deactivated or deprovisioned user",
        required_params=["user_id"],
        outputs={'status': 'user.status'},
        param_bindings={'user_id': 'user.id'},
        is_destructive=True,
        tags=["delete", "remove", "offboard"],
        preconditions={"user.id": "KNOWN", "user.status": "DEACTIVATED"},
        effects={"user.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="get_user_profile_attributes",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all user profile attributes supported by the Okta org",
        required_params=[],
        outputs={'attributes': 'user.schema'},
        tags=["schema", "profile", "introspect"],
        preconditions={},
        effects={"user.schema": "KNOWN"},
    ))

    # ── Groups (additional) ──
    kg.add_node(ToolNode(
        action="list_groups",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List or search groups in the Okta organization",
        required_params=[],
        optional_params=["search", "filter", "q", "limit"],
        outputs={'items': 'group.list[]'},
        tags=["search", "bulk", "filter"],
        preconditions={},
        effects={"group.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Create a new group in the Okta organization",
        required_params=["profile"],
        outputs={'id': 'group.id', 'profile': 'group.profile'},
        tags=["create", "onboard"],
        preconditions={"group.profile_data": "PROVIDED"},
        effects={"group.id": "KNOWN", "group.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.DELETE,
        description="Delete a group by ID",
        required_params=["group_id"],
        outputs={'status': 'group.status'},
        param_bindings={'group_id': 'group.id'},
        is_destructive=True,
        tags=["delete", "remove"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="update_group",
        entity_type=EntityType.GROUP,
        operation=OperationType.WRITE,
        description="Update a group by ID with a new profile",
        required_params=["group_id", "profile"],
        outputs={'id': 'group.id', 'profile': 'group.profile'},
        param_bindings={'group_id': 'group.id'},
        tags=["update", "modify"],
        preconditions={"group.id": "KNOWN", "group.profile_data": "PROVIDED"},
        effects={"group.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="list_group_users",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all users in a group",
        required_params=["group_id"],
        optional_params=["limit", "after"],
        outputs={'items': 'group.users[]'},
        param_bindings={'group_id': 'group.id'},
        tags=["membership", "enumerate"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.users": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="list_group_apps",
        entity_type=EntityType.GROUP,
        operation=OperationType.READ,
        description="List all applications assigned to a group",
        required_params=["group_id"],
        outputs={'items': 'group.apps[]'},
        param_bindings={'group_id': 'group.id'},
        tags=["assignment", "enumerate", "access"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.apps": "ENUMERATED"},
    ))

    # ── Policies ──
    kg.add_node(ToolNode(
        action="list_policies",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="List policies by type with optional status and query filters",
        required_params=["type"],
        optional_params=["status", "q", "limit", "after"],
        outputs={'items': 'policy.list[]'},
        tags=["search", "bulk", "filter"],
        preconditions={"policy.type": "KNOWN"},
        effects={"policy.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="Retrieve a specific policy by ID",
        required_params=["policy_id"],
        outputs={'id': 'policy.id', 'type': 'policy.type', 'name': 'policy.name', 'status': 'policy.status', 'conditions': 'policy.conditions', 'settings': 'policy.settings'},
        tags=["lookup", "resolve"],
        preconditions={"policy.identifier": "PROVIDED"},
        effects={"policy.id": "KNOWN", "policy.status": "KNOWN", "policy.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Create a new policy",
        required_params=["policy_data"],
        outputs={'id': 'policy.id', 'type': 'policy.type', 'name': 'policy.name', 'status': 'policy.status'},
        tags=["create"],
        preconditions={"policy.data": "PROVIDED"},
        effects={"policy.id": "KNOWN", "policy.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="update_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Update an existing policy",
        required_params=["policy_id", "policy_data"],
        outputs={'id': 'policy.id', 'type': 'policy.type', 'name': 'policy.name', 'status': 'policy.status'},
        param_bindings={'policy_id': 'policy.id'},
        tags=["update", "modify"],
        preconditions={"policy.id": "KNOWN", "policy.data": "PROVIDED"},
        effects={"policy.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.DELETE,
        description="Delete a policy",
        required_params=["policy_id"],
        outputs={'status': 'policy.status'},
        param_bindings={'policy_id': 'policy.id'},
        is_destructive=True,
        tags=["delete", "remove"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Activate a policy",
        required_params=["policy_id"],
        outputs={'status': 'policy.status'},
        param_bindings={'policy_id': 'policy.id'},
        tags=["lifecycle", "enable"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Deactivate a policy",
        required_params=["policy_id"],
        outputs={'status': 'policy.status'},
        param_bindings={'policy_id': 'policy.id'},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.status": "DEACTIVATED"},
    ))

    # ── Policy Rules ──
    kg.add_node(ToolNode(
        action="list_policy_rules",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.READ,
        description="List all rules for a specific policy",
        required_params=["policy_id"],
        outputs={'items': 'policy.rules[]'},
        param_bindings={'policy_id': 'policy.id'},
        tags=["search", "enumerate"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.rules": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="get_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.READ,
        description="Retrieve a specific policy rule",
        required_params=["policy_id", "rule_id"],
        outputs={'id': 'policy_rule.id', 'name': 'policy_rule.name', 'status': 'policy_rule.status', 'conditions': 'policy_rule.conditions', 'actions': 'policy_rule.actions'},
        param_bindings={'policy_id': 'policy.id'},
        tags=["lookup", "resolve"],
        preconditions={"policy.id": "KNOWN", "policy_rule.identifier": "PROVIDED"},
        effects={"policy_rule.id": "KNOWN", "policy_rule.status": "KNOWN", "policy_rule.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Create a new rule for a policy",
        required_params=["policy_id", "rule_data"],
        outputs={'id': 'policy_rule.id', 'name': 'policy_rule.name', 'status': 'policy_rule.status'},
        param_bindings={'policy_id': 'policy.id'},
        tags=["create"],
        preconditions={"policy.id": "KNOWN", "policy_rule.data": "PROVIDED"},
        effects={"policy_rule.id": "KNOWN", "policy_rule.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="update_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Update an existing policy rule",
        required_params=["policy_id", "rule_id", "rule_data"],
        outputs={'id': 'policy_rule.id', 'name': 'policy_rule.name', 'status': 'policy_rule.status'},
        param_bindings={'policy_id': 'policy.id', 'rule_id': 'policy_rule.id'},
        tags=["update", "modify"],
        preconditions={"policy.id": "KNOWN", "policy_rule.id": "KNOWN", "policy_rule.data": "PROVIDED"},
        effects={"policy_rule.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.DELETE,
        description="Delete a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs={'status': 'policy_rule.status'},
        param_bindings={'policy_id': 'policy.id', 'rule_id': 'policy_rule.id'},
        is_destructive=True,
        tags=["delete", "remove"],
        preconditions={"policy.id": "KNOWN", "policy_rule.id": "KNOWN"},
        effects={"policy_rule.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Activate a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs={'status': 'policy_rule.status'},
        param_bindings={'policy_id': 'policy.id', 'rule_id': 'policy_rule.id'},
        tags=["lifecycle", "enable"],
        preconditions={"policy.id": "KNOWN", "policy_rule.id": "KNOWN"},
        effects={"policy_rule.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_policy_rule",
        entity_type=EntityType.POLICY_RULE,
        operation=OperationType.WRITE,
        description="Deactivate a policy rule",
        required_params=["policy_id", "rule_id"],
        outputs={'status': 'policy_rule.status'},
        param_bindings={'policy_id': 'policy.id', 'rule_id': 'policy_rule.id'},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"policy.id": "KNOWN", "policy_rule.id": "KNOWN"},
        effects={"policy_rule.status": "DEACTIVATED"},
    ))

    # ── Device Assurance ──
    kg.add_node(ToolNode(
        action="list_device_assurance_policies",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.READ,
        description="List all device assurance policies",
        required_params=[],
        outputs={'items': 'device_assurance.list[]'},
        tags=["search", "bulk", "audit"],
        preconditions={},
        effects={"device_assurance.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.READ,
        description="Retrieve a specific device assurance policy by ID",
        required_params=["device_assurance_id"],
        outputs={'id': 'device_assurance.id', 'name': 'device_assurance.name', 'platform': 'device_assurance.platform', 'osVersion': 'device_assurance.osVersion', 'status': 'device_assurance.status'},
        tags=["lookup", "resolve"],
        preconditions={"device_assurance.identifier": "PROVIDED"},
        effects={"device_assurance.id": "KNOWN", "device_assurance.status": "KNOWN", "device_assurance.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.WRITE,
        description="Create a new device assurance policy",
        required_params=["policy_data"],
        outputs={'id': 'device_assurance.id', 'name': 'device_assurance.name', 'platform': 'device_assurance.platform', 'status': 'device_assurance.status'},
        tags=["create"],
        preconditions={"device_assurance.data": "PROVIDED"},
        effects={"device_assurance.id": "KNOWN", "device_assurance.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="replace_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.WRITE,
        description="Replace (fully update) an existing device assurance policy",
        required_params=["device_assurance_id", "policy_data"],
        outputs={'id': 'device_assurance.id', 'name': 'device_assurance.name', 'platform': 'device_assurance.platform', 'status': 'device_assurance.status', 'changes': 'device_assurance.changes'},
        param_bindings={'device_assurance_id': 'device_assurance.id'},
        tags=["update", "modify", "replace"],
        preconditions={"device_assurance.id": "KNOWN", "device_assurance.data": "PROVIDED"},
        effects={"device_assurance.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_device_assurance_policy",
        entity_type=EntityType.DEVICE_ASSURANCE,
        operation=OperationType.DELETE,
        description="Delete a device assurance policy",
        required_params=["device_assurance_id"],
        outputs={'status': 'device_assurance.status'},
        param_bindings={'device_assurance_id': 'device_assurance.id'},
        is_destructive=True,
        tags=["delete", "remove"],
        preconditions={"device_assurance.id": "KNOWN"},
        effects={"device_assurance.status": "DELETED"},
    ))

    # ── System Logs ──
    kg.add_node(ToolNode(
        action="get_logs",
        entity_type=EntityType.LOG,
        operation=OperationType.READ,
        description="Retrieve system logs from the Okta organization",
        required_params=[],
        optional_params=["since", "until", "filter", "q", "limit", "after"],
        outputs={'items': 'log.events[]'},
        tags=["audit", "search", "events", "monitoring"],
        preconditions={},
        effects={"log.events": "RETRIEVED"},
    ))

    # ── Brands ──
    kg.add_node(ToolNode(
        action="list_brands",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="List all brands in the Okta organization",
        required_params=[],
        outputs={'items': 'brand.list[]'},
        tags=["search", "bulk", "customization"],
        preconditions={},
        effects={"brand.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="Get a brand by ID",
        required_params=["brand_id"],
        outputs={'id': 'brand.id', 'name': 'brand.name', 'custom_privacy_policy_url': 'brand.custom_privacy_policy_url'},
        tags=["lookup", "resolve", "customization"],
        preconditions={"brand.identifier": "PROVIDED"},
        effects={"brand.id": "KNOWN", "brand.profile": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.WRITE,
        description="Create a new brand",
        required_params=["brand_data"],
        outputs={'id': 'brand.id', 'name': 'brand.name'},
        tags=["create", "customization"],
        preconditions={"brand.data": "PROVIDED"},
        effects={"brand.id": "KNOWN", "brand.status": "CREATED"},
    ))
    kg.add_node(ToolNode(
        action="replace_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.WRITE,
        description="Replace (update) a brand",
        required_params=["brand_id", "brand_data"],
        outputs={'id': 'brand.id', 'name': 'brand.name'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "modify", "customization"],
        preconditions={"brand.id": "KNOWN", "brand.data": "PROVIDED"},
        effects={"brand.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_brand",
        entity_type=EntityType.BRAND,
        operation=OperationType.DELETE,
        description="Delete a brand",
        required_params=["brand_id"],
        outputs={'status': 'brand.status'},
        param_bindings={'brand_id': 'brand.id'},
        is_destructive=True,
        tags=["delete", "remove", "customization"],
        preconditions={"brand.id": "KNOWN"},
        effects={"brand.status": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="list_brand_domains",
        entity_type=EntityType.BRAND,
        operation=OperationType.READ,
        description="List all domains associated with a brand",
        required_params=["brand_id"],
        outputs={'items': 'brand.domains[]'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["enumerate", "customization"],
        preconditions={"brand.id": "KNOWN"},
        effects={"brand.domains": "ENUMERATED"},
    ))

    # ── Custom Domains ──
    kg.add_node(ToolNode(
        action="list_custom_domains",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.READ,
        description="List all custom domains",
        required_params=[],
        outputs={'items': 'custom_domain.list[]'},
        tags=["search", "bulk", "customization"],
        preconditions={},
        effects={'custom_domain.list': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="create_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Create a new custom domain",
        required_params=["domain_data"],
        outputs={'id': 'custom_domain.id', 'domain': 'custom_domain.domain'},
        tags=["create", "customization"],
        preconditions={'custom_domain.data': 'PROVIDED'},
        effects={'custom_domain.id': 'KNOWN', 'custom_domain.status': 'CREATED'},
    ))
    kg.add_node(ToolNode(
        action="get_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.READ,
        description="Get a custom domain by ID",
        required_params=["domain_id"],
        outputs={'id': 'custom_domain.id', 'domain': 'custom_domain.domain', 'status': 'custom_domain.status'},
        tags=["lookup", "resolve", "customization"],
        preconditions={'custom_domain.identifier': 'PROVIDED'},
        effects={'custom_domain.id': 'KNOWN', 'custom_domain.status': 'KNOWN', 'custom_domain.profile': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Replace (update) a custom domain",
        required_params=["domain_id", "domain_data"],
        outputs={'id': 'custom_domain.id', 'domain': 'custom_domain.domain'},
        param_bindings={'domain_id': 'custom_domain.id'},
        tags=["update", "modify", "customization"],
        preconditions={'custom_domain.id': 'KNOWN', 'custom_domain.data': 'PROVIDED'},
        effects={'custom_domain.profile': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.DELETE,
        description="Delete a custom domain",
        required_params=["domain_id"],
        outputs={'status': 'custom_domain.status'},
        param_bindings={'domain_id': 'custom_domain.id'},
        is_destructive=True,
        tags=["delete", "remove", "customization"],
        preconditions={'custom_domain.id': 'KNOWN'},
        effects={'custom_domain.status': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="upsert_custom_domain_certificate",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Upsert a certificate for a custom domain",
        required_params=["domain_id", "certificate_data"],
        outputs={'status': 'custom_domain.certificate'},
        param_bindings={'domain_id': 'custom_domain.id'},
        tags=["certificate", "ssl", "customization"],
        preconditions={'custom_domain.id': 'KNOWN', 'custom_domain.certificate_data': 'PROVIDED'},
        effects={'custom_domain.certificate': 'CONFIGURED'},
    ))
    kg.add_node(ToolNode(
        action="verify_custom_domain",
        entity_type=EntityType.CUSTOM_DOMAIN,
        operation=OperationType.WRITE,
        description="Verify a custom domain",
        required_params=["domain_id"],
        outputs={'status': 'custom_domain.status'},
        param_bindings={'domain_id': 'custom_domain.id'},
        tags=["verify", "dns", "customization"],
        preconditions={'custom_domain.id': 'KNOWN'},
        effects={'custom_domain.status': 'VERIFIED'},
    ))

    # ── Email Domains ──
    kg.add_node(ToolNode(
        action="list_email_domains",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.READ,
        description="List all email domains",
        required_params=[],
        outputs={'items': 'email_domain.list[]'},
        tags=["search", "bulk", "customization"],
        preconditions={},
        effects={'email_domain.list': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="create_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Create a new email domain",
        required_params=["email_domain_data"],
        outputs={'id': 'email_domain.id', 'domain': 'email_domain.domain'},
        tags=["create", "customization"],
        preconditions={'email_domain.data': 'PROVIDED'},
        effects={'email_domain.id': 'KNOWN', 'email_domain.status': 'CREATED'},
    ))
    kg.add_node(ToolNode(
        action="get_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.READ,
        description="Get an email domain by ID",
        required_params=["email_domain_id"],
        outputs={'id': 'email_domain.id', 'domain': 'email_domain.domain', 'status': 'email_domain.status'},
        tags=["lookup", "resolve", "customization"],
        preconditions={'email_domain.identifier': 'PROVIDED'},
        effects={'email_domain.id': 'KNOWN', 'email_domain.status': 'KNOWN', 'email_domain.profile': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Replace (update) an email domain",
        required_params=["email_domain_id", "email_domain_data"],
        outputs={'id': 'email_domain.id', 'domain': 'email_domain.domain'},
        param_bindings={'email_domain_id': 'email_domain.id'},
        tags=["update", "modify", "customization"],
        preconditions={'email_domain.id': 'KNOWN', 'email_domain.data': 'PROVIDED'},
        effects={'email_domain.profile': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.DELETE,
        description="Delete an email domain",
        required_params=["email_domain_id"],
        outputs={'status': 'email_domain.status'},
        param_bindings={'email_domain_id': 'email_domain.id'},
        is_destructive=True,
        tags=["delete", "remove", "customization"],
        preconditions={'email_domain.id': 'KNOWN'},
        effects={'email_domain.status': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="verify_email_domain",
        entity_type=EntityType.EMAIL_DOMAIN,
        operation=OperationType.WRITE,
        description="Verify an email domain",
        required_params=["email_domain_id"],
        outputs={'status': 'email_domain.status'},
        param_bindings={'email_domain_id': 'email_domain.id'},
        tags=["verify", "dns", "customization"],
        preconditions={'email_domain.id': 'KNOWN'},
        effects={'email_domain.status': 'VERIFIED'},
    ))

    # ── Themes ──
    kg.add_node(ToolNode(
        action="list_brand_themes",
        entity_type=EntityType.THEME,
        operation=OperationType.READ,
        description="List all themes for a brand",
        required_params=["brand_id"],
        outputs={'items': 'theme.list[]'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["search", "enumerate", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'theme.list': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_brand_theme",
        entity_type=EntityType.THEME,
        operation=OperationType.READ,
        description="Get a specific theme for a brand",
        required_params=["brand_id", "theme_id"],
        outputs={'id': 'theme.id', 'primaryColorHex': 'theme.primaryColorHex', 'secondaryColorHex': 'theme.secondaryColorHex'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "resolve", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.identifier': 'PROVIDED'},
        effects={'theme.id': 'KNOWN', 'theme.profile': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_brand_theme",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Replace (update) a theme for a brand",
        required_params=["brand_id", "theme_id"],
        outputs={'id': 'theme.id'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        tags=["update", "modify", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN'},
        effects={'theme.profile': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_logo",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a logo for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs={'status': 'theme.logo'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        tags=["upload", "logo", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN', 'theme.file': 'PROVIDED'},
        effects={'theme.logo': 'UPLOADED'},
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_logo",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the logo for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs={'status': 'theme.logo'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        is_destructive=True,
        tags=["delete", "logo", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN'},
        effects={'theme.logo': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_favicon",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a favicon for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs={'status': 'theme.favicon'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        tags=["upload", "favicon", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN', 'theme.file': 'PROVIDED'},
        effects={'theme.favicon': 'UPLOADED'},
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_favicon",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the favicon for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs={'status': 'theme.favicon'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        is_destructive=True,
        tags=["delete", "favicon", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN'},
        effects={'theme.favicon': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="upload_brand_theme_background_image",
        entity_type=EntityType.THEME,
        operation=OperationType.WRITE,
        description="Upload a background image for a brand theme",
        required_params=["brand_id", "theme_id", "file_path"],
        outputs={'status': 'theme.background'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        tags=["upload", "background", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN', 'theme.file': 'PROVIDED'},
        effects={'theme.background': 'UPLOADED'},
    ))
    kg.add_node(ToolNode(
        action="delete_brand_theme_background_image",
        entity_type=EntityType.THEME,
        operation=OperationType.DELETE,
        description="Delete the background image for a brand theme",
        required_params=["brand_id", "theme_id"],
        outputs={'status': 'theme.background'},
        param_bindings={'brand_id': 'brand.id', 'theme_id': 'theme.id'},
        is_destructive=True,
        tags=["delete", "background", "customization"],
        preconditions={'brand.id': 'KNOWN', 'theme.id': 'KNOWN'},
        effects={'theme.background': 'DELETED'},
    ))

    # ── Custom Pages ──
    kg.add_node(ToolNode(
        action="get_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the customized error page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.error_page'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "error_page", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the customized error page for a brand",
        required_params=["brand_id", "page_content"],
        outputs={'page_content': 'custom_page.error_page'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "error_page", "customization"],
        preconditions={'brand.id': 'KNOWN', 'custom_page.content': 'PROVIDED'},
        effects={'custom_page.error_page': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_customized_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the customized error page for a brand (revert to default)",
        required_params=["brand_id"],
        outputs={'status': 'custom_page.error_page'},
        param_bindings={'brand_id': 'brand.id'},
        is_destructive=True,
        tags=["delete", "error_page", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="get_default_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the default error page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.error_page_default'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "error_page", "default", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page_default': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the preview error page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.error_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "error_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page_preview': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the preview error page for a brand",
        required_params=["brand_id", "page_content"],
        outputs={'page_content': 'custom_page.error_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "error_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN', 'custom_page.content': 'PROVIDED'},
        effects={'custom_page.error_page_preview': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_preview_error_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the preview error page for a brand",
        required_params=["brand_id"],
        outputs={'status': 'custom_page.error_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        is_destructive=True,
        tags=["delete", "error_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page_preview': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="get_error_page_resources",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the error page resources for a brand",
        required_params=["brand_id"],
        outputs={'resources': 'custom_page.error_page_resources'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "error_page", "resources", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.error_page_resources': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the customized sign-in page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.sign_in_page'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "sign_in_page", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the customized sign-in page for a brand",
        required_params=["brand_id", "page_content"],
        outputs={'page_content': 'custom_page.sign_in_page'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "sign_in_page", "customization"],
        preconditions={'brand.id': 'KNOWN', 'custom_page.content': 'PROVIDED'},
        effects={'custom_page.sign_in_page': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_customized_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the customized sign-in page for a brand (revert to default)",
        required_params=["brand_id"],
        outputs={'status': 'custom_page.sign_in_page'},
        param_bindings={'brand_id': 'brand.id'},
        is_destructive=True,
        tags=["delete", "sign_in_page", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="get_default_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the default sign-in page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.sign_in_page_default'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "sign_in_page", "default", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page_default': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the preview sign-in page for a brand",
        required_params=["brand_id"],
        outputs={'page_content': 'custom_page.sign_in_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "sign_in_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page_preview': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the preview sign-in page for a brand",
        required_params=["brand_id", "page_content"],
        outputs={'page_content': 'custom_page.sign_in_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "sign_in_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN', 'custom_page.content': 'PROVIDED'},
        effects={'custom_page.sign_in_page_preview': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_preview_sign_in_page",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.DELETE,
        description="Delete the preview sign-in page for a brand",
        required_params=["brand_id"],
        outputs={'status': 'custom_page.sign_in_page_preview'},
        param_bindings={'brand_id': 'brand.id'},
        is_destructive=True,
        tags=["delete", "sign_in_page", "preview", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page_preview': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="get_sign_in_page_resources",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the sign-in page resources for a brand",
        required_params=["brand_id"],
        outputs={'resources': 'custom_page.sign_in_page_resources'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "sign_in_page", "resources", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_in_page_resources': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="list_sign_in_widget_versions",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="List all available sign-in widget versions",
        required_params=[],
        outputs={'items': 'custom_page.widget_versions[]'},
        tags=["search", "sign_in_page", "widget", "customization"],
        preconditions={},
        effects={'custom_page.widget_versions': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_sign_out_page_settings",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.READ,
        description="Get the sign-out page settings for a brand",
        required_params=["brand_id"],
        outputs={'settings': 'custom_page.sign_out_settings'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "sign_out_page", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'custom_page.sign_out_settings': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_sign_out_page_settings",
        entity_type=EntityType.CUSTOM_PAGE,
        operation=OperationType.WRITE,
        description="Replace the sign-out page settings for a brand",
        required_params=["brand_id", "settings"],
        outputs={'settings': 'custom_page.sign_out_settings'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["update", "sign_out_page", "customization"],
        preconditions={'brand.id': 'KNOWN', 'custom_page.settings': 'PROVIDED'},
        effects={'custom_page.sign_out_settings': 'UPDATED'},
    ))

    # ── Email Templates ──
    kg.add_node(ToolNode(
        action="list_email_templates",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="List all email templates for a brand",
        required_params=["brand_id"],
        outputs={'items': 'email_template.list[]'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["search", "enumerate", "customization"],
        preconditions={'brand.id': 'KNOWN'},
        effects={'email_template.list': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_email_template",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get a specific email template for a brand",
        required_params=["brand_id", "template_name"],
        outputs={'template': 'email_template.id'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["lookup", "resolve", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.identifier': 'PROVIDED'},
        effects={'email_template.id': 'KNOWN', 'email_template.profile': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="list_email_customizations",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="List all customizations for an email template",
        required_params=["brand_id", "template_name"],
        outputs={'items': 'email_template.customizations[]'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["search", "enumerate", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.customizations': 'ENUMERATED'},
    ))
    kg.add_node(ToolNode(
        action="create_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Create a customization for an email template",
        required_params=["brand_id", "template_name", "customization_data"],
        outputs={'id': 'email_template.customization_id'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["create", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_data': 'PROVIDED'},
        effects={'email_template.customization_id': 'KNOWN', 'email_template.customization': 'CREATED'},
    ))
    kg.add_node(ToolNode(
        action="get_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get a specific email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs={'id': 'email_template.customization_id', 'language': 'email_template.customization_language', 'subject': 'email_template.customization_subject', 'body': 'email_template.customization_body'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id', 'customization_id': 'email_template.customization_id'},
        tags=["lookup", "resolve", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_id': 'KNOWN'},
        effects={'email_template.customization_profile': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Replace an email customization",
        required_params=["brand_id", "template_name", "customization_id", "customization_data"],
        outputs={'id': 'email_template.customization_id'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id', 'customization_id': 'email_template.customization_id'},
        tags=["update", "modify", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_id': 'KNOWN', 'email_template.customization_data': 'PROVIDED'},
        effects={'email_template.customization_profile': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="delete_email_customization",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.DELETE,
        description="Delete an email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs={'status': 'email_template.customization'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id', 'customization_id': 'email_template.customization_id'},
        is_destructive=True,
        tags=["delete", "remove", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_id': 'KNOWN'},
        effects={'email_template.customization': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="delete_all_email_customizations",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.DELETE,
        description="Delete all customizations for an email template",
        required_params=["brand_id", "template_name"],
        outputs={'status': 'email_template.customizations'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        is_destructive=True,
        tags=["delete", "remove", "bulk", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.customizations': 'DELETED'},
    ))
    kg.add_node(ToolNode(
        action="get_email_customization_preview",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Preview an email customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs={'preview': 'email_template.customization_preview'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id', 'customization_id': 'email_template.customization_id'},
        tags=["preview", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_id': 'KNOWN'},
        effects={'email_template.customization_preview': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_email_default_content",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get the default content for an email template",
        required_params=["brand_id", "template_name"],
        outputs={'content': 'email_template.default_content'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["lookup", "default", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.default_content': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_email_default_content_preview",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Preview the default content for an email template",
        required_params=["brand_id", "template_name"],
        outputs={'preview': 'email_template.default_content_preview'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["preview", "default", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.default_content_preview': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="get_email_settings",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.READ,
        description="Get email settings for a template",
        required_params=["brand_id", "template_name"],
        outputs={'settings': 'email_template.settings'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["lookup", "settings", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.settings': 'KNOWN'},
    ))
    kg.add_node(ToolNode(
        action="replace_email_settings",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Replace email settings for a template",
        required_params=["brand_id", "template_name", "settings"],
        outputs={'settings': 'email_template.settings'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["update", "settings", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.settings_data': 'PROVIDED'},
        effects={'email_template.settings': 'UPDATED'},
    ))
    kg.add_node(ToolNode(
        action="send_test_email",
        entity_type=EntityType.EMAIL_TEMPLATE,
        operation=OperationType.WRITE,
        description="Send a test email for a template customization",
        required_params=["brand_id", "template_name", "customization_id"],
        outputs={'status': 'email_template.test_email'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id', 'customization_id': 'email_template.customization_id'},
        tags=["test", "send", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN', 'email_template.customization_id': 'KNOWN'},
        effects={'email_template.test_email': 'SENT'},
    ))

    logger.info(f"Knowledge graph built: {len(kg._nodes)} nodes")
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
