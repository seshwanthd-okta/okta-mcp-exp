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
    GROUP_RULE = "group_rule"
    GROUP_OWNER = "group_owner"
    APPLICATION = "application"
    POLICY = "policy"
    POLICY_RULE = "policy_rule"
    DEVICE_ASSURANCE = "device_assurance"
    DEVICE = "device"
    DEVICE_INTEGRATION = "device_integration"
    DEVICE_POSTURE_CHECK = "device_posture_check"
    LOG = "log"
    LOG_STREAM = "log_stream"
    BRAND = "brand"
    CUSTOM_DOMAIN = "custom_domain"
    EMAIL_DOMAIN = "email_domain"
    THEME = "theme"
    CUSTOM_PAGE = "custom_page"
    EMAIL_TEMPLATE = "email_template"
    USER_TYPE = "user_type"
    USER_FACTOR = "user_factor"
    USER_GRANT = "user_grant"
    USER_CREDENTIAL = "user_credential"
    PROFILE_MAPPING = "profile_mapping"
    # Governance
    GOV_REQUEST_CONDITION = "gov_request_condition"
    GOV_REQUEST = "gov_request"
    GOV_CATALOG = "gov_catalog"
    GOV_CAMPAIGN = "gov_campaign"
    GOV_REVIEW = "gov_review"
    GOV_ENTITLEMENT = "gov_entitlement"
    GOV_ENTITLEMENT_BUNDLE = "gov_entitlement_bundle"
    GOV_COLLECTION = "gov_collection"
    GOV_GRANT = "gov_grant"
    GOV_PRINCIPAL_ENTITLEMENT = "gov_principal_entitlement"
    GOV_LABEL = "gov_label"
    GOV_RESOURCE_OWNER = "gov_resource_owner"
    GOV_DELEGATE = "gov_delegate"
    GOV_SETTINGS = "gov_settings"


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
      - filter_templates: dict mapping upstream predicate key to a filter
        expression template.  The template uses {value} as a placeholder
        for the resolved upstream data.  When build_execution_chain detects
        that an upstream step produces a matching predicate, it auto-wires
        the filter param with the interpolated template.
        Example: {"user.id": 'actor.id eq "{value}"'}
    """
    action: str                               # dispatcher key, e.g. "get_user"
    entity_type: EntityType
    operation: OperationType
    description: str
    required_params: list[str]                # params that MUST be supplied
    optional_params: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)          # field → predicate_key ([] = array)
    param_bindings: dict[str, str] = field(default_factory=dict)   # param → predicate_key ([] = iterate)
    filter_templates: dict[str, str] = field(default_factory=dict) # predicate_key → filter template
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
          5. If the node has filter_templates, and a prior step produced a
             matching predicate, the "filter" param is auto-wired with the
             template string using inline $stepN.field interpolation.
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

            # Auto-wire filter param from filter_templates
            if node.filter_templates and "filter" not in params:
                for pred_key, template in node.filter_templates.items():
                    if pred_key in produced:
                        src_step, src_field, src_is_array = produced[pred_key]
                        if not src_is_array:
                            # Build a filter string with inline $step reference
                            ref = f"$step{src_step}.{src_field}"
                            params["filter"] = template.replace("{value}", ref)
                        break  # use the first matching template

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
            "filter_templates": node.filter_templates,
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
        optional_params=["search", "filter", "q", "fetch_all", "after", "limit"],
        outputs={'items': 'user.list[]'},
        filter_templates={
            "group.id": 'memberOf.id eq "{value}"',
        },
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
        description="Get a group by its Okta ID",
        required_params=["group_id"],
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
        optional_params=["q", "after", "limit", "filter", "expand", "include_non_deleted"],
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
        optional_params=["search", "filter", "q", "fetch_all", "after", "limit"],
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
        optional_params=["fetch_all", "after", "limit"],
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
        optional_params=["status", "q", "limit", "after", "expand", "sort_by", "resource_id"],
        outputs={'items': 'policy.list[]'},
        tags=["search", "bulk", "filter"],
        preconditions={},
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
        optional_params=["since", "until", "filter", "q", "fetch_all", "limit", "after"],
        outputs={'items': 'log.events[]'},
        filter_templates={
            "user.id": 'actor.id eq "{value}"',
            "group.id": 'target.id eq "{value}"',
            "application.id": 'target.id eq "{value}"',
        },
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
        optional_params=["expand", "after", "limit", "q", "fetch_all"],
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
        optional_params=["expand"],
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
        required_params=["name"],
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
        required_params=["brand_id", "name"],
        optional_params=["agree_to_custom_privacy_policy", "custom_privacy_policy_url", "remove_powered_by_okta", "locale", "email_domain_id", "default_app"],
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
        required_params=["domain", "certificate_source_type"],
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
        required_params=["domain_id", "brand_id"],
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
        required_params=["domain_id", "certificate", "certificate_chain", "private_key_file_path"],
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
        optional_params=["expand_brands"],
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
        required_params=["brand_id", "domain", "display_name", "user_name"],
        optional_params=["validation_subdomain"],
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
        optional_params=["expand_brands"],
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
        required_params=["email_domain_id", "display_name", "user_name"],
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
        required_params=["brand_id", "theme_id", "primary_color_hex", "secondary_color_hex", "sign_in_page_touch_point_variant", "end_user_dashboard_touch_point_variant", "error_page_touch_point_variant", "email_template_touch_point_variant"],
        optional_params=["primary_color_contrast_hex", "secondary_color_contrast_hex", "loading_page_touch_point_variant"],
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
        required_params=["brand_id"],
        optional_params=["page_content", "csp_mode", "csp_report_uri", "csp_src_list"],
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
        required_params=["brand_id"],
        optional_params=["page_content", "csp_mode", "csp_report_uri", "csp_src_list"],
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
        optional_params=["expand"],
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
        required_params=["brand_id"],
        optional_params=["page_content", "widget_version", "widget_customizations", "csp_mode", "csp_report_uri", "csp_src_list"],
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
        required_params=["brand_id"],
        optional_params=["page_content", "widget_version", "widget_customizations", "csp_mode", "csp_report_uri", "csp_src_list"],
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
        optional_params=["expand"],
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
        description="List all available sign-in widget versions for a brand",
        required_params=["brand_id"],
        outputs={'items': 'custom_page.widget_versions[]'},
        param_bindings={'brand_id': 'brand.id'},
        tags=["search", "sign_in_page", "widget", "customization"],
        preconditions={'brand.id': 'KNOWN'},
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
        required_params=["brand_id", "type"],
        optional_params=["url"],
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
        optional_params=["expand"],
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
        optional_params=["expand"],
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
        required_params=["brand_id", "template_name", "language", "subject", "body"],
        optional_params=["is_default"],
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
        required_params=["brand_id", "template_name", "customization_id", "language", "subject", "body"],
        optional_params=["is_default"],
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
        optional_params=["language"],
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
        optional_params=["language"],
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
        optional_params=["language"],
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
        required_params=["brand_id", "template_name", "recipients"],
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
        description="Send a test email for a template to the current API user",
        required_params=["brand_id", "template_name"],
        optional_params=["language"],
        outputs={'status': 'email_template.test_email'},
        param_bindings={'brand_id': 'brand.id', 'template_name': 'email_template.id'},
        tags=["test", "send", "customization"],
        preconditions={'brand.id': 'KNOWN', 'email_template.id': 'KNOWN'},
        effects={'email_template.test_email': 'SENT'},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Group Rules
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_group_rules",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.READ,
        description="List all group rules",
        required_params=[],
        optional_params=["limit", "after", "search", "expand"],
        outputs={"items": "group_rule.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"group_rule.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.WRITE,
        description="Create a group rule",
        required_params=["rule_data"],
        outputs={"id": "group_rule.id"},
        tags=["create"],
        preconditions={},
        effects={"group_rule.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.READ,
        description="Retrieve a specific group rule",
        required_params=["rule_id"],
        optional_params=["expand"],
        outputs={"id": "group_rule.id", "status": "group_rule.status"},
        tags=["lookup"],
        preconditions={"group_rule.identifier": "PROVIDED"},
        effects={"group_rule.id": "KNOWN", "group_rule.status": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="replace_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.WRITE,
        description="Replace a group rule",
        required_params=["rule_id", "rule_data"],
        param_bindings={"rule_id": "group_rule.id"},
        tags=["update"],
        preconditions={"group_rule.id": "KNOWN"},
        effects={"group_rule.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.DELETE,
        description="Delete a group rule",
        required_params=["rule_id"],
        param_bindings={"rule_id": "group_rule.id"},
        is_destructive=True,
        tags=["delete"],
        preconditions={"group_rule.id": "KNOWN"},
        effects={"group_rule.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.WRITE,
        description="Activate a group rule",
        required_params=["rule_id"],
        param_bindings={"rule_id": "group_rule.id"},
        tags=["lifecycle", "enable"],
        preconditions={"group_rule.id": "KNOWN"},
        effects={"group_rule.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_group_rule",
        entity_type=EntityType.GROUP_RULE,
        operation=OperationType.WRITE,
        description="Deactivate a group rule",
        required_params=["rule_id"],
        param_bindings={"rule_id": "group_rule.id"},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"group_rule.id": "KNOWN"},
        effects={"group_rule.status": "INACTIVE"},
    ))

    # ── Group Owners ──
    kg.add_node(ToolNode(
        action="list_group_owners",
        entity_type=EntityType.GROUP_OWNER,
        operation=OperationType.READ,
        description="List all owners of a group",
        required_params=["group_id"],
        optional_params=["limit", "after", "filter"],
        outputs={"items": "group.owners[]"},
        param_bindings={"group_id": "group.id"},
        tags=["membership", "enumerate"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.owners": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="assign_group_owner",
        entity_type=EntityType.GROUP_OWNER,
        operation=OperationType.WRITE,
        description="Assign an owner to a group",
        required_params=["group_id", "owner_data"],
        param_bindings={"group_id": "group.id"},
        tags=["assign", "grant"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.owner": "ASSIGNED"},
    ))
    kg.add_node(ToolNode(
        action="delete_group_owner",
        entity_type=EntityType.GROUP_OWNER,
        operation=OperationType.DELETE,
        description="Remove an owner from a group",
        required_params=["group_id", "owner_id"],
        param_bindings={"group_id": "group.id"},
        is_destructive=True,
        tags=["revoke", "remove"],
        preconditions={"group.id": "KNOWN"},
        effects={"group.owner": "REMOVED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Lifecycle Extended
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="reactivate_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Reactivate a provisioned user",
        required_params=["user_id"],
        optional_params=["send_email"],
        param_bindings={"user_id": "user.id"},
        tags=["lifecycle", "reactivate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "PROVISIONED"},
    ))
    kg.add_node(ToolNode(
        action="reset_factors",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Reset all MFA factors for a user",
        required_params=["user_id"],
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["mfa", "reset", "security"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.factors": "RESET"},
    ))
    kg.add_node(ToolNode(
        action="unlock_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Unlock a locked-out user",
        required_params=["user_id"],
        param_bindings={"user_id": "user.id"},
        tags=["lifecycle", "unlock"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "UNLOCKED"},
    ))
    kg.add_node(ToolNode(
        action="unsuspend_user",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Unsuspend a suspended user",
        required_params=["user_id"],
        param_bindings={"user_id": "user.id"},
        tags=["lifecycle", "unsuspend"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="list_user_blocks",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all blocks for a user",
        required_params=["user_id"],
        outputs={"items": "user.blocks[]"},
        param_bindings={"user_id": "user.id"},
        tags=["security", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.blocks": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="list_user_clients",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all OAuth2 clients for a user",
        required_params=["user_id"],
        outputs={"items": "user.clients[]"},
        param_bindings={"user_id": "user.id"},
        tags=["oauth", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.clients": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="list_user_devices",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all devices for a user",
        required_params=["user_id"],
        outputs={"items": "user.devices[]"},
        param_bindings={"user_id": "user.id"},
        tags=["device", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.devices": "ENUMERATED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Credentials
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="expire_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Expire a user's password",
        required_params=["user_id"],
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["password", "security"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.password": "EXPIRED"},
    ))
    kg.add_node(ToolNode(
        action="expire_password_with_temp_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Expire password and return a temporary password",
        required_params=["user_id"],
        outputs={"tempPassword": "user.temp_password"},
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["password", "security", "temp"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.password": "EXPIRED", "user.temp_password": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="reset_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Generate a one-time reset password token",
        required_params=["user_id"],
        optional_params=["send_email"],
        outputs={"resetPasswordUrl": "user.reset_url"},
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["password", "reset"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.reset_url": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="change_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Change a user's password with current + new password",
        required_params=["user_id", "old_password", "new_password"],
        param_bindings={"user_id": "user.id"},
        tags=["password", "change"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.password": "CHANGED"},
    ))
    kg.add_node(ToolNode(
        action="change_recovery_question",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Change a user's recovery question",
        required_params=["user_id", "password", "recovery_question", "recovery_answer"],
        param_bindings={"user_id": "user.id"},
        tags=["recovery", "security"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.recovery_question": "CHANGED"},
    ))
    kg.add_node(ToolNode(
        action="forgot_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Initiate forgot password flow for a user",
        required_params=["user_id"],
        optional_params=["send_email"],
        param_bindings={"user_id": "user.id"},
        tags=["password", "recovery"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.password_reset": "INITIATED"},
    ))
    kg.add_node(ToolNode(
        action="forgot_password_set_new_password",
        entity_type=EntityType.USER_CREDENTIAL,
        operation=OperationType.WRITE,
        description="Set a new password via forgot password flow using recovery answer",
        required_params=["user_id", "new_password", "recovery_answer"],
        param_bindings={"user_id": "user.id"},
        tags=["password", "recovery"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.password": "RESET"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Factors
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_factors",
        entity_type=EntityType.USER_FACTOR,
        operation=OperationType.READ,
        description="List all enrolled factors for a user",
        required_params=["user_id"],
        outputs={"items": "user.factors[]"},
        param_bindings={"user_id": "user.id"},
        tags=["mfa", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.factors": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="enroll_factor",
        entity_type=EntityType.USER_FACTOR,
        operation=OperationType.WRITE,
        description="Enroll a new factor for a user",
        required_params=["user_id", "factor_data"],
        outputs={"id": "factor.id"},
        param_bindings={"user_id": "user.id"},
        tags=["mfa", "enroll"],
        preconditions={"user.id": "KNOWN"},
        effects={"factor.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_factor",
        entity_type=EntityType.USER_FACTOR,
        operation=OperationType.READ,
        description="Retrieve a specific factor for a user",
        required_params=["user_id", "factor_id"],
        outputs={"id": "factor.id", "status": "factor.status"},
        param_bindings={"user_id": "user.id", "factor_id": "factor.id"},
        tags=["mfa", "lookup"],
        preconditions={"user.id": "KNOWN", "factor.id": "KNOWN"},
        effects={"factor.status": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="unenroll_factor",
        entity_type=EntityType.USER_FACTOR,
        operation=OperationType.DELETE,
        description="Unenroll (delete) a factor for a user",
        required_params=["user_id", "factor_id"],
        param_bindings={"user_id": "user.id", "factor_id": "factor.id"},
        is_destructive=True,
        tags=["mfa", "delete"],
        preconditions={"user.id": "KNOWN", "factor.id": "KNOWN"},
        effects={"factor.id": "DELETED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Grants
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_user_grants",
        entity_type=EntityType.USER_GRANT,
        operation=OperationType.READ,
        description="List all grants for a user",
        required_params=["user_id"],
        optional_params=["scope_id", "expand", "after", "limit"],
        outputs={"items": "user.grants[]"},
        param_bindings={"user_id": "user.id"},
        tags=["oauth", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.grants": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="revoke_all_user_grants",
        entity_type=EntityType.USER_GRANT,
        operation=OperationType.DELETE,
        description="Revoke all grants for a user",
        required_params=["user_id"],
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["oauth", "revoke", "bulk"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.grants": "REVOKED"},
    ))
    kg.add_node(ToolNode(
        action="get_user_grant",
        entity_type=EntityType.USER_GRANT,
        operation=OperationType.READ,
        description="Retrieve a specific grant for a user",
        required_params=["user_id", "grant_id"],
        optional_params=["expand"],
        outputs={"id": "user_grant.id"},
        param_bindings={"user_id": "user.id"},
        tags=["oauth", "lookup"],
        preconditions={"user.id": "KNOWN"},
        effects={"user_grant.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="revoke_user_grant",
        entity_type=EntityType.USER_GRANT,
        operation=OperationType.DELETE,
        description="Revoke a specific grant for a user",
        required_params=["user_id", "grant_id"],
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["oauth", "revoke"],
        preconditions={"user.id": "KNOWN"},
        effects={"user_grant.id": "REVOKED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Types
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_user_types",
        entity_type=EntityType.USER_TYPE,
        operation=OperationType.READ,
        description="List all user types",
        required_params=[],
        outputs={"items": "user_type.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"user_type.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_user_type",
        entity_type=EntityType.USER_TYPE,
        operation=OperationType.WRITE,
        description="Create a new user type",
        required_params=["user_type_data"],
        outputs={"id": "user_type.id"},
        tags=["create"],
        preconditions={},
        effects={"user_type.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_user_type",
        entity_type=EntityType.USER_TYPE,
        operation=OperationType.READ,
        description="Retrieve a specific user type",
        required_params=["type_id"],
        outputs={"id": "user_type.id", "name": "user_type.name"},
        tags=["lookup"],
        preconditions={"user_type.identifier": "PROVIDED"},
        effects={"user_type.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_user_type",
        entity_type=EntityType.USER_TYPE,
        operation=OperationType.DELETE,
        description="Delete a user type",
        required_params=["type_id"],
        param_bindings={"type_id": "user_type.id"},
        is_destructive=True,
        tags=["delete"],
        preconditions={"user_type.id": "KNOWN"},
        effects={"user_type.id": "DELETED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — User Extended (Auth Enrollments, Classification, Linked Objects, Tokens, Risk)
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_authenticator_enrollments",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List all authenticator enrollments for a user",
        required_params=["user_id"],
        outputs={"items": "user.authenticator_enrollments[]"},
        param_bindings={"user_id": "user.id"},
        tags=["authenticator", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.authenticator_enrollments": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="get_user_classification",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Retrieve a user's classification",
        required_params=["user_id"],
        outputs={"classification": "user.classification"},
        param_bindings={"user_id": "user.id"},
        tags=["classification", "lookup"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.classification": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="replace_user_classification",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Replace a user's classification",
        required_params=["user_id", "classification_data"],
        param_bindings={"user_id": "user.id"},
        tags=["classification", "update"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.classification": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="list_linked_objects_for_user",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List linked objects for a user",
        required_params=["user_id", "relationship_name"],
        outputs={"items": "user.linked_objects[]"},
        param_bindings={"user_id": "user.id"},
        tags=["linked_object", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.linked_objects": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="list_refresh_tokens_for_client",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="List refresh tokens for a user and client",
        required_params=["user_id", "client_id"],
        optional_params=["expand", "after", "limit"],
        outputs={"items": "user.refresh_tokens[]"},
        param_bindings={"user_id": "user.id"},
        tags=["oauth", "token", "enumerate"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.refresh_tokens": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="revoke_tokens_for_client",
        entity_type=EntityType.USER,
        operation=OperationType.DELETE,
        description="Revoke all tokens for a user and client",
        required_params=["user_id", "client_id"],
        param_bindings={"user_id": "user.id"},
        is_destructive=True,
        tags=["oauth", "token", "revoke"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.refresh_tokens": "REVOKED"},
    ))
    kg.add_node(ToolNode(
        action="get_user_risk",
        entity_type=EntityType.USER,
        operation=OperationType.READ,
        description="Retrieve a user's risk level",
        required_params=["user_id"],
        outputs={"riskLevel": "user.risk_level"},
        param_bindings={"user_id": "user.id"},
        tags=["risk", "security", "lookup"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.risk_level": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="upsert_user_risk",
        entity_type=EntityType.USER,
        operation=OperationType.WRITE,
        description="Upsert a user's risk level",
        required_params=["user_id", "risk_data"],
        param_bindings={"user_id": "user.id"},
        tags=["risk", "security", "update"],
        preconditions={"user.id": "KNOWN"},
        effects={"user.risk_level": "UPDATED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Devices
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_devices",
        entity_type=EntityType.DEVICE,
        operation=OperationType.READ,
        description="List all devices",
        required_params=[],
        optional_params=["after", "limit", "search", "expand", "fetch_all"],
        outputs={"items": "device.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"device.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.READ,
        description="Retrieve a specific device",
        required_params=["device_id"],
        optional_params=["expand"],
        outputs={"id": "device.id", "status": "device.status"},
        tags=["lookup"],
        preconditions={"device.identifier": "PROVIDED"},
        effects={"device.id": "KNOWN", "device.status": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.DELETE,
        description="Delete a device",
        required_params=["device_id"],
        param_bindings={"device_id": "device.id"},
        is_destructive=True,
        tags=["delete"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.WRITE,
        description="Activate a device",
        required_params=["device_id"],
        param_bindings={"device_id": "device.id"},
        tags=["lifecycle", "enable"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.WRITE,
        description="Deactivate a device",
        required_params=["device_id"],
        param_bindings={"device_id": "device.id"},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.status": "DEACTIVATED"},
    ))
    kg.add_node(ToolNode(
        action="suspend_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.WRITE,
        description="Suspend a device",
        required_params=["device_id"],
        param_bindings={"device_id": "device.id"},
        is_destructive=True,
        tags=["lifecycle", "suspend"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.status": "SUSPENDED"},
    ))
    kg.add_node(ToolNode(
        action="unsuspend_device",
        entity_type=EntityType.DEVICE,
        operation=OperationType.WRITE,
        description="Unsuspend a device",
        required_params=["device_id"],
        param_bindings={"device_id": "device.id"},
        tags=["lifecycle", "unsuspend"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="list_device_users",
        entity_type=EntityType.DEVICE,
        operation=OperationType.READ,
        description="List all users for a device",
        required_params=["device_id"],
        outputs={"items": "device.users[]"},
        param_bindings={"device_id": "device.id"},
        tags=["enumerate"],
        preconditions={"device.id": "KNOWN"},
        effects={"device.users": "ENUMERATED"},
    ))

    # ── Device Integrations ──
    kg.add_node(ToolNode(
        action="list_device_integrations",
        entity_type=EntityType.DEVICE_INTEGRATION,
        operation=OperationType.READ,
        description="List all device integrations",
        required_params=[],
        outputs={"items": "device_integration.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"device_integration.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_device_integration",
        entity_type=EntityType.DEVICE_INTEGRATION,
        operation=OperationType.READ,
        description="Retrieve a specific device integration",
        required_params=["integration_id"],
        outputs={"id": "device_integration.id", "status": "device_integration.status"},
        tags=["lookup"],
        preconditions={"device_integration.identifier": "PROVIDED"},
        effects={"device_integration.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="activate_device_integration",
        entity_type=EntityType.DEVICE_INTEGRATION,
        operation=OperationType.WRITE,
        description="Activate a device integration",
        required_params=["integration_id"],
        param_bindings={"integration_id": "device_integration.id"},
        tags=["lifecycle", "enable"],
        preconditions={"device_integration.id": "KNOWN"},
        effects={"device_integration.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_device_integration",
        entity_type=EntityType.DEVICE_INTEGRATION,
        operation=OperationType.WRITE,
        description="Deactivate a device integration",
        required_params=["integration_id"],
        param_bindings={"integration_id": "device_integration.id"},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"device_integration.id": "KNOWN"},
        effects={"device_integration.status": "DEACTIVATED"},
    ))

    # ── Device Posture Checks ──
    kg.add_node(ToolNode(
        action="list_device_posture_checks",
        entity_type=EntityType.DEVICE_POSTURE_CHECK,
        operation=OperationType.READ,
        description="List all device posture checks",
        required_params=[],
        outputs={"items": "device_posture_check.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"device_posture_check.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_device_posture_check",
        entity_type=EntityType.DEVICE_POSTURE_CHECK,
        operation=OperationType.WRITE,
        description="Create a device posture check",
        required_params=["check_data"],
        outputs={"id": "device_posture_check.id"},
        tags=["create"],
        preconditions={},
        effects={"device_posture_check.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_device_posture_check",
        entity_type=EntityType.DEVICE_POSTURE_CHECK,
        operation=OperationType.READ,
        description="Retrieve a device posture check",
        required_params=["check_id"],
        outputs={"id": "device_posture_check.id"},
        tags=["lookup"],
        preconditions={"device_posture_check.identifier": "PROVIDED"},
        effects={"device_posture_check.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="replace_device_posture_check",
        entity_type=EntityType.DEVICE_POSTURE_CHECK,
        operation=OperationType.WRITE,
        description="Replace a device posture check",
        required_params=["check_id", "check_data"],
        param_bindings={"check_id": "device_posture_check.id"},
        tags=["update"],
        preconditions={"device_posture_check.id": "KNOWN"},
        effects={"device_posture_check.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_device_posture_check",
        entity_type=EntityType.DEVICE_POSTURE_CHECK,
        operation=OperationType.DELETE,
        description="Delete a device posture check",
        required_params=["check_id"],
        param_bindings={"check_id": "device_posture_check.id"},
        is_destructive=True,
        tags=["delete"],
        preconditions={"device_posture_check.id": "KNOWN"},
        effects={"device_posture_check.id": "DELETED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Log Streaming
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_log_streams",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.READ,
        description="List all log streams",
        required_params=[],
        optional_params=["after", "limit", "filter", "fetch_all"],
        outputs={"items": "log_stream.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"log_stream.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.WRITE,
        description="Create a log stream",
        required_params=["stream_data"],
        outputs={"id": "log_stream.id"},
        tags=["create"],
        preconditions={},
        effects={"log_stream.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.READ,
        description="Retrieve a specific log stream",
        required_params=["stream_id"],
        outputs={"id": "log_stream.id", "status": "log_stream.status"},
        tags=["lookup"],
        preconditions={"log_stream.identifier": "PROVIDED"},
        effects={"log_stream.id": "KNOWN", "log_stream.status": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="replace_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.WRITE,
        description="Replace a log stream",
        required_params=["stream_id", "stream_data"],
        param_bindings={"stream_id": "log_stream.id"},
        tags=["update"],
        preconditions={"log_stream.id": "KNOWN"},
        effects={"log_stream.profile": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="delete_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.DELETE,
        description="Delete a log stream",
        required_params=["stream_id"],
        param_bindings={"stream_id": "log_stream.id"},
        is_destructive=True,
        tags=["delete"],
        preconditions={"log_stream.id": "KNOWN"},
        effects={"log_stream.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.WRITE,
        description="Activate a log stream",
        required_params=["stream_id"],
        param_bindings={"stream_id": "log_stream.id"},
        tags=["lifecycle", "enable"],
        preconditions={"log_stream.id": "KNOWN"},
        effects={"log_stream.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_log_stream",
        entity_type=EntityType.LOG_STREAM,
        operation=OperationType.WRITE,
        description="Deactivate a log stream",
        required_params=["stream_id"],
        param_bindings={"stream_id": "log_stream.id"},
        is_destructive=True,
        tags=["lifecycle", "disable"],
        preconditions={"log_stream.id": "KNOWN"},
        effects={"log_stream.status": "DEACTIVATED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Profile Mappings
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="list_profile_mappings",
        entity_type=EntityType.PROFILE_MAPPING,
        operation=OperationType.READ,
        description="List all profile mappings",
        required_params=[],
        optional_params=["after", "limit", "source_id", "target_id", "fetch_all"],
        outputs={"items": "profile_mapping.list[]"},
        tags=["search", "bulk"],
        preconditions={},
        effects={"profile_mapping.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_profile_mapping",
        entity_type=EntityType.PROFILE_MAPPING,
        operation=OperationType.READ,
        description="Retrieve a specific profile mapping",
        required_params=["mapping_id"],
        outputs={"id": "profile_mapping.id"},
        tags=["lookup"],
        preconditions={"profile_mapping.identifier": "PROVIDED"},
        effects={"profile_mapping.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="update_profile_mapping",
        entity_type=EntityType.PROFILE_MAPPING,
        operation=OperationType.WRITE,
        description="Update a profile mapping",
        required_params=["mapping_id", "mapping_data"],
        param_bindings={"mapping_id": "profile_mapping.id"},
        tags=["update"],
        preconditions={"profile_mapping.id": "KNOWN"},
        effects={"profile_mapping.profile": "UPDATED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Policy Extended
    # ═══════════════════════════════════════════════════════════════
    kg.add_node(ToolNode(
        action="simulate_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="Simulate a policy evaluation",
        required_params=["simulation_data"],
        outputs={"result": "policy.simulation_result"},
        tags=["simulate", "test"],
        preconditions={},
        effects={"policy.simulation_result": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_policy_apps",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="List applications assigned to a policy",
        required_params=["policy_id"],
        outputs={"items": "policy.apps[]"},
        param_bindings={"policy_id": "policy.id"},
        tags=["enumerate", "assignment"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.apps": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="clone_policy",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Clone a policy",
        required_params=["policy_id"],
        outputs={"id": "policy.cloned_id"},
        param_bindings={"policy_id": "policy.id"},
        tags=["clone", "duplicate"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.cloned_id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_policy_resource_mappings",
        entity_type=EntityType.POLICY,
        operation=OperationType.READ,
        description="List resource mappings for a policy",
        required_params=["policy_id"],
        outputs={"items": "policy.resource_mappings[]"},
        param_bindings={"policy_id": "policy.id"},
        tags=["enumerate"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.resource_mappings": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="create_policy_resource_mapping",
        entity_type=EntityType.POLICY,
        operation=OperationType.WRITE,
        description="Create a resource mapping for a policy",
        required_params=["policy_id", "mapping_data"],
        param_bindings={"policy_id": "policy.id"},
        tags=["create", "mapping"],
        preconditions={"policy.id": "KNOWN"},
        effects={"policy.resource_mapping": "CREATED"},
    ))

    # ═══════════════════════════════════════════════════════════════
    # NEW TOOL NODES — Governance Admin APIs
    # ═══════════════════════════════════════════════════════════════

    # ── Request Conditions ──
    kg.add_node(ToolNode(
        action="list_request_conditions",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.READ,
        description="List all request conditions for a resource",
        required_params=["resource_id"],
        outputs={"items": "gov_request_condition.list[]"},
        tags=["governance", "enumerate"],
        preconditions={},
        effects={"gov_request_condition.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_request_condition",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.WRITE,
        description="Create a request condition for a resource",
        required_params=["resource_id", "condition_data"],
        outputs={"id": "gov_request_condition.id"},
        tags=["governance", "create"],
        preconditions={},
        effects={"gov_request_condition.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_request_condition",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.READ,
        description="Retrieve a request condition",
        required_params=["resource_id", "request_condition_id"],
        outputs={"id": "gov_request_condition.id"},
        tags=["governance", "lookup"],
        preconditions={"gov_request_condition.id": "KNOWN"},
        effects={"gov_request_condition.details": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_request_condition",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.DELETE,
        description="Delete a request condition",
        required_params=["resource_id", "request_condition_id"],
        is_destructive=True,
        tags=["governance", "delete"],
        preconditions={"gov_request_condition.id": "KNOWN"},
        effects={"gov_request_condition.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="activate_request_condition",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.WRITE,
        description="Activate a request condition",
        required_params=["resource_id", "request_condition_id"],
        tags=["governance", "lifecycle", "enable"],
        preconditions={"gov_request_condition.id": "KNOWN"},
        effects={"gov_request_condition.status": "ACTIVE"},
    ))
    kg.add_node(ToolNode(
        action="deactivate_request_condition",
        entity_type=EntityType.GOV_REQUEST_CONDITION,
        operation=OperationType.WRITE,
        description="Deactivate a request condition",
        required_params=["resource_id", "request_condition_id"],
        is_destructive=True,
        tags=["governance", "lifecycle", "disable"],
        preconditions={"gov_request_condition.id": "KNOWN"},
        effects={"gov_request_condition.status": "INACTIVE"},
    ))

    # ── Governance Requests ──
    kg.add_node(ToolNode(
        action="list_governance_requests",
        entity_type=EntityType.GOV_REQUEST,
        operation=OperationType.READ,
        description="List all governance requests",
        required_params=[],
        optional_params=["filter", "after", "limit", "order_by"],
        outputs={"items": "gov_request.list[]"},
        tags=["governance", "search", "bulk"],
        preconditions={},
        effects={"gov_request.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_governance_request",
        entity_type=EntityType.GOV_REQUEST,
        operation=OperationType.WRITE,
        description="Create a governance request",
        required_params=["request_data"],
        outputs={"id": "gov_request.id"},
        tags=["governance", "create"],
        preconditions={},
        effects={"gov_request.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_governance_request",
        entity_type=EntityType.GOV_REQUEST,
        operation=OperationType.READ,
        description="Retrieve a governance request",
        required_params=["request_id"],
        outputs={"id": "gov_request.id"},
        tags=["governance", "lookup"],
        preconditions={"gov_request.identifier": "PROVIDED"},
        effects={"gov_request.id": "KNOWN", "gov_request.details": "KNOWN"},
    ))

    # ── Catalogs ──
    kg.add_node(ToolNode(
        action="list_catalog_entries",
        entity_type=EntityType.GOV_CATALOG,
        operation=OperationType.READ,
        description="List all entries for the default access request catalog",
        required_params=["filter"],
        optional_params=["after", "match", "limit"],
        outputs={"items": "gov_catalog.entries[]"},
        tags=["governance", "catalog", "search"],
        preconditions={},
        effects={"gov_catalog.entries": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_catalog_entry",
        entity_type=EntityType.GOV_CATALOG,
        operation=OperationType.READ,
        description="Retrieve a catalog entry",
        required_params=["entry_id"],
        outputs={"id": "gov_catalog.entry_id"},
        tags=["governance", "catalog", "lookup"],
        preconditions={"gov_catalog.entry_identifier": "PROVIDED"},
        effects={"gov_catalog.entry_id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_catalog_entries_for_user",
        entity_type=EntityType.GOV_CATALOG,
        operation=OperationType.READ,
        description="List catalog entries for a user",
        required_params=["user_id", "filter"],
        optional_params=["after", "match", "limit"],
        outputs={"items": "gov_catalog.user_entries[]"},
        param_bindings={"user_id": "user.id"},
        tags=["governance", "catalog"],
        preconditions={"user.id": "KNOWN"},
        effects={"gov_catalog.user_entries": "KNOWN"},
    ))

    # ── Campaigns ──
    kg.add_node(ToolNode(
        action="create_campaign",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.WRITE,
        description="Create a governance campaign",
        required_params=["campaign_data"],
        outputs={"id": "gov_campaign.id"},
        tags=["governance", "campaign", "create"],
        preconditions={},
        effects={"gov_campaign.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_campaigns",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.READ,
        description="List all campaigns",
        required_params=[],
        optional_params=["filter", "after", "limit", "order_by"],
        outputs={"items": "gov_campaign.list[]"},
        tags=["governance", "campaign", "search"],
        preconditions={},
        effects={"gov_campaign.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_campaign",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.READ,
        description="Retrieve a campaign",
        required_params=["campaign_id"],
        outputs={"id": "gov_campaign.id", "status": "gov_campaign.status"},
        tags=["governance", "campaign", "lookup"],
        preconditions={"gov_campaign.identifier": "PROVIDED"},
        effects={"gov_campaign.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_campaign",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.DELETE,
        description="Delete a campaign",
        required_params=["campaign_id"],
        param_bindings={"campaign_id": "gov_campaign.id"},
        is_destructive=True,
        tags=["governance", "campaign", "delete"],
        preconditions={"gov_campaign.id": "KNOWN"},
        effects={"gov_campaign.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="launch_campaign",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.WRITE,
        description="Launch a campaign",
        required_params=["campaign_id"],
        param_bindings={"campaign_id": "gov_campaign.id"},
        tags=["governance", "campaign", "lifecycle"],
        preconditions={"gov_campaign.id": "KNOWN"},
        effects={"gov_campaign.status": "LAUNCHED"},
    ))
    kg.add_node(ToolNode(
        action="end_campaign",
        entity_type=EntityType.GOV_CAMPAIGN,
        operation=OperationType.WRITE,
        description="End a campaign",
        required_params=["campaign_id"],
        param_bindings={"campaign_id": "gov_campaign.id"},
        is_destructive=True,
        tags=["governance", "campaign", "lifecycle"],
        preconditions={"gov_campaign.id": "KNOWN"},
        effects={"gov_campaign.status": "ENDED"},
    ))

    # ── Reviews ──
    kg.add_node(ToolNode(
        action="list_reviews",
        entity_type=EntityType.GOV_REVIEW,
        operation=OperationType.READ,
        description="List all governance reviews",
        required_params=[],
        optional_params=["filter", "after", "limit", "order_by"],
        outputs={"items": "gov_review.list[]"},
        tags=["governance", "review", "search"],
        preconditions={},
        effects={"gov_review.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_review",
        entity_type=EntityType.GOV_REVIEW,
        operation=OperationType.READ,
        description="Retrieve a review",
        required_params=["review_id"],
        outputs={"id": "gov_review.id"},
        tags=["governance", "review", "lookup"],
        preconditions={"gov_review.identifier": "PROVIDED"},
        effects={"gov_review.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="reassign_reviews",
        entity_type=EntityType.GOV_REVIEW,
        operation=OperationType.WRITE,
        description="Reassign reviews for a campaign",
        required_params=["campaign_id", "reassignment_data"],
        param_bindings={"campaign_id": "gov_campaign.id"},
        tags=["governance", "review", "reassign"],
        preconditions={"gov_campaign.id": "KNOWN"},
        effects={"gov_review.reassignment": "DONE"},
    ))

    # ── Entitlements ──
    kg.add_node(ToolNode(
        action="list_entitlements",
        entity_type=EntityType.GOV_ENTITLEMENT,
        operation=OperationType.READ,
        description="List all entitlements",
        required_params=[],
        optional_params=["limit", "after", "filter", "order_by"],
        outputs={"items": "gov_entitlement.list[]"},
        tags=["governance", "entitlement", "search"],
        preconditions={},
        effects={"gov_entitlement.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_entitlement",
        entity_type=EntityType.GOV_ENTITLEMENT,
        operation=OperationType.WRITE,
        description="Create an entitlement",
        required_params=["entitlement_data"],
        outputs={"id": "gov_entitlement.id"},
        tags=["governance", "entitlement", "create"],
        preconditions={},
        effects={"gov_entitlement.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_entitlement",
        entity_type=EntityType.GOV_ENTITLEMENT,
        operation=OperationType.READ,
        description="Retrieve an entitlement",
        required_params=["entitlement_id"],
        outputs={"id": "gov_entitlement.id"},
        tags=["governance", "entitlement", "lookup"],
        preconditions={"gov_entitlement.identifier": "PROVIDED"},
        effects={"gov_entitlement.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_entitlement",
        entity_type=EntityType.GOV_ENTITLEMENT,
        operation=OperationType.DELETE,
        description="Delete an entitlement",
        required_params=["entitlement_id"],
        param_bindings={"entitlement_id": "gov_entitlement.id"},
        is_destructive=True,
        tags=["governance", "entitlement", "delete"],
        preconditions={"gov_entitlement.id": "KNOWN"},
        effects={"gov_entitlement.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="list_entitlement_values",
        entity_type=EntityType.GOV_ENTITLEMENT,
        operation=OperationType.READ,
        description="List all values for an entitlement",
        required_params=["entitlement_id"],
        optional_params=["limit", "after", "filter", "order_by"],
        outputs={"items": "gov_entitlement.values[]"},
        param_bindings={"entitlement_id": "gov_entitlement.id"},
        tags=["governance", "entitlement", "enumerate"],
        preconditions={"gov_entitlement.id": "KNOWN"},
        effects={"gov_entitlement.values": "ENUMERATED"},
    ))

    # ── Entitlement Bundles ──
    kg.add_node(ToolNode(
        action="list_entitlement_bundles",
        entity_type=EntityType.GOV_ENTITLEMENT_BUNDLE,
        operation=OperationType.READ,
        description="List all entitlement bundles",
        required_params=[],
        optional_params=["filter", "after", "limit", "order_by", "include"],
        outputs={"items": "gov_entitlement_bundle.list[]"},
        tags=["governance", "bundle", "search"],
        preconditions={},
        effects={"gov_entitlement_bundle.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_entitlement_bundle",
        entity_type=EntityType.GOV_ENTITLEMENT_BUNDLE,
        operation=OperationType.WRITE,
        description="Create an entitlement bundle",
        required_params=["bundle_data"],
        outputs={"id": "gov_entitlement_bundle.id"},
        tags=["governance", "bundle", "create"],
        preconditions={},
        effects={"gov_entitlement_bundle.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_entitlement_bundle",
        entity_type=EntityType.GOV_ENTITLEMENT_BUNDLE,
        operation=OperationType.READ,
        description="Retrieve an entitlement bundle",
        required_params=["bundle_id"],
        optional_params=["include"],
        outputs={"id": "gov_entitlement_bundle.id"},
        tags=["governance", "bundle", "lookup"],
        preconditions={"gov_entitlement_bundle.identifier": "PROVIDED"},
        effects={"gov_entitlement_bundle.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_entitlement_bundle",
        entity_type=EntityType.GOV_ENTITLEMENT_BUNDLE,
        operation=OperationType.DELETE,
        description="Delete an entitlement bundle",
        required_params=["bundle_id"],
        param_bindings={"bundle_id": "gov_entitlement_bundle.id"},
        is_destructive=True,
        tags=["governance", "bundle", "delete"],
        preconditions={"gov_entitlement_bundle.id": "KNOWN"},
        effects={"gov_entitlement_bundle.id": "DELETED"},
    ))

    # ── Collections ──
    kg.add_node(ToolNode(
        action="list_collections",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.READ,
        description="List all resource collections",
        required_params=[],
        optional_params=["include", "limit", "after", "filter"],
        outputs={"items": "gov_collection.list[]"},
        tags=["governance", "collection", "search"],
        preconditions={},
        effects={"gov_collection.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_collection",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.WRITE,
        description="Create a resource collection",
        required_params=["collection_data"],
        outputs={"id": "gov_collection.id"},
        tags=["governance", "collection", "create"],
        preconditions={},
        effects={"gov_collection.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_collection",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.READ,
        description="Retrieve a resource collection",
        required_params=["collection_id"],
        outputs={"id": "gov_collection.id"},
        tags=["governance", "collection", "lookup"],
        preconditions={"gov_collection.identifier": "PROVIDED"},
        effects={"gov_collection.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_collection",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.DELETE,
        description="Delete a collection",
        required_params=["collection_id"],
        param_bindings={"collection_id": "gov_collection.id"},
        is_destructive=True,
        tags=["governance", "collection", "delete"],
        preconditions={"gov_collection.id": "KNOWN"},
        effects={"gov_collection.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="list_collection_resources",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.READ,
        description="List all resources in a collection",
        required_params=["collection_id"],
        optional_params=["include", "limit", "after"],
        outputs={"items": "gov_collection.resources[]"},
        param_bindings={"collection_id": "gov_collection.id"},
        tags=["governance", "collection", "enumerate"],
        preconditions={"gov_collection.id": "KNOWN"},
        effects={"gov_collection.resources": "ENUMERATED"},
    ))
    kg.add_node(ToolNode(
        action="list_collection_assignments",
        entity_type=EntityType.GOV_COLLECTION,
        operation=OperationType.READ,
        description="List all assignments for a collection",
        required_params=["collection_id"],
        optional_params=["filter", "limit", "after"],
        outputs={"items": "gov_collection.assignments[]"},
        param_bindings={"collection_id": "gov_collection.id"},
        tags=["governance", "collection", "enumerate"],
        preconditions={"gov_collection.id": "KNOWN"},
        effects={"gov_collection.assignments": "ENUMERATED"},
    ))

    # ── Grants ──
    kg.add_node(ToolNode(
        action="list_grants",
        entity_type=EntityType.GOV_GRANT,
        operation=OperationType.READ,
        description="List all governance grants",
        required_params=[],
        optional_params=["after", "limit", "filter", "include"],
        outputs={"items": "gov_grant.list[]"},
        tags=["governance", "grant", "search"],
        preconditions={},
        effects={"gov_grant.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_grant",
        entity_type=EntityType.GOV_GRANT,
        operation=OperationType.WRITE,
        description="Create a governance grant",
        required_params=["grant_data"],
        outputs={"id": "gov_grant.id"},
        tags=["governance", "grant", "create"],
        preconditions={},
        effects={"gov_grant.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_grant",
        entity_type=EntityType.GOV_GRANT,
        operation=OperationType.READ,
        description="Retrieve a governance grant",
        required_params=["grant_id"],
        optional_params=["include"],
        outputs={"id": "gov_grant.id"},
        tags=["governance", "grant", "lookup"],
        preconditions={"gov_grant.identifier": "PROVIDED"},
        effects={"gov_grant.id": "KNOWN"},
    ))

    # ── Principal Entitlements ──
    kg.add_node(ToolNode(
        action="list_principal_entitlements",
        entity_type=EntityType.GOV_PRINCIPAL_ENTITLEMENT,
        operation=OperationType.READ,
        description="Retrieve principal's effective entitlements for a resource",
        required_params=[],
        optional_params=["filter"],
        outputs={"items": "gov_principal_entitlement.list[]"},
        tags=["governance", "principal", "entitlement"],
        preconditions={},
        effects={"gov_principal_entitlement.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_entitlement_history",
        entity_type=EntityType.GOV_PRINCIPAL_ENTITLEMENT,
        operation=OperationType.READ,
        description="Retrieve entitlement history",
        required_params=[],
        optional_params=["filter", "limit", "after", "include"],
        outputs={"items": "gov_principal_entitlement.history[]"},
        tags=["governance", "principal", "history"],
        preconditions={},
        effects={"gov_principal_entitlement.history": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="revoke_principal_access",
        entity_type=EntityType.GOV_PRINCIPAL_ENTITLEMENT,
        operation=OperationType.WRITE,
        description="Revoke a principal's access",
        required_params=["revocation_data"],
        is_destructive=True,
        tags=["governance", "principal", "revoke"],
        preconditions={},
        effects={"gov_principal_entitlement.access": "REVOKED"},
    ))

    # ── Labels ──
    kg.add_node(ToolNode(
        action="list_labels",
        entity_type=EntityType.GOV_LABEL,
        operation=OperationType.READ,
        description="List all governance labels",
        required_params=[],
        optional_params=["filter"],
        outputs={"items": "gov_label.list[]"},
        tags=["governance", "label", "search"],
        preconditions={},
        effects={"gov_label.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_label",
        entity_type=EntityType.GOV_LABEL,
        operation=OperationType.WRITE,
        description="Create a governance label",
        required_params=["label_data"],
        outputs={"id": "gov_label.id"},
        tags=["governance", "label", "create"],
        preconditions={},
        effects={"gov_label.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_label",
        entity_type=EntityType.GOV_LABEL,
        operation=OperationType.READ,
        description="Retrieve a governance label",
        required_params=["label_id"],
        outputs={"id": "gov_label.id"},
        tags=["governance", "label", "lookup"],
        preconditions={"gov_label.identifier": "PROVIDED"},
        effects={"gov_label.id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="delete_label",
        entity_type=EntityType.GOV_LABEL,
        operation=OperationType.DELETE,
        description="Delete a governance label",
        required_params=["label_id"],
        param_bindings={"label_id": "gov_label.id"},
        is_destructive=True,
        tags=["governance", "label", "delete"],
        preconditions={"gov_label.id": "KNOWN"},
        effects={"gov_label.id": "DELETED"},
    ))
    kg.add_node(ToolNode(
        action="list_labeled_resources",
        entity_type=EntityType.GOV_LABEL,
        operation=OperationType.READ,
        description="List all labeled resources",
        required_params=[],
        optional_params=["filter", "limit", "after"],
        outputs={"items": "gov_label.resources[]"},
        tags=["governance", "label", "enumerate"],
        preconditions={},
        effects={"gov_label.resources": "KNOWN"},
    ))

    # ── Resource Owners ──
    kg.add_node(ToolNode(
        action="list_resources_with_owners",
        entity_type=EntityType.GOV_RESOURCE_OWNER,
        operation=OperationType.READ,
        description="List all resources with owners",
        required_params=[],
        optional_params=["filter", "limit", "after", "include"],
        outputs={"items": "gov_resource_owner.list[]"},
        tags=["governance", "resource_owner", "search"],
        preconditions={},
        effects={"gov_resource_owner.list": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="list_resources_without_owners",
        entity_type=EntityType.GOV_RESOURCE_OWNER,
        operation=OperationType.READ,
        description="List all resources without owners",
        required_params=[],
        optional_params=["filter", "limit", "after"],
        outputs={"items": "gov_resource_owner.unowned[]"},
        tags=["governance", "resource_owner", "search"],
        preconditions={},
        effects={"gov_resource_owner.unowned": "KNOWN"},
    ))

    # ── Delegates ──
    kg.add_node(ToolNode(
        action="list_delegates",
        entity_type=EntityType.GOV_DELEGATE,
        operation=OperationType.READ,
        description="List all delegate appointments",
        required_params=[],
        optional_params=["filter", "limit", "after"],
        outputs={"items": "gov_delegate.list[]"},
        tags=["governance", "delegate", "search"],
        preconditions={},
        effects={"gov_delegate.list": "KNOWN"},
    ))

    # ── Governance End User ──
    kg.add_node(ToolNode(
        action="list_my_catalog_entries",
        entity_type=EntityType.GOV_CATALOG,
        operation=OperationType.READ,
        description="List my entries for the default access request catalog",
        required_params=[],
        optional_params=["filter", "after", "match", "limit"],
        outputs={"items": "gov_catalog.my_entries[]"},
        tags=["governance", "end_user", "catalog"],
        preconditions={},
        effects={"gov_catalog.my_entries": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_my_catalog_entry",
        entity_type=EntityType.GOV_CATALOG,
        operation=OperationType.READ,
        description="Retrieve my catalog entry",
        required_params=["entry_id"],
        outputs={"id": "gov_catalog.my_entry_id"},
        tags=["governance", "end_user", "catalog", "lookup"],
        preconditions={"gov_catalog.entry_identifier": "PROVIDED"},
        effects={"gov_catalog.my_entry_id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="create_my_request",
        entity_type=EntityType.GOV_REQUEST,
        operation=OperationType.WRITE,
        description="Create a request for a catalog entry (end-user)",
        required_params=["entry_id", "request_data"],
        outputs={"id": "gov_request.my_request_id"},
        tags=["governance", "end_user", "request", "create"],
        preconditions={},
        effects={"gov_request.my_request_id": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="get_my_settings",
        entity_type=EntityType.GOV_SETTINGS,
        operation=OperationType.READ,
        description="Retrieve my governance settings",
        required_params=[],
        outputs={"settings": "gov_settings.my_settings"},
        tags=["governance", "end_user", "settings"],
        preconditions={},
        effects={"gov_settings.my_settings": "KNOWN"},
    ))
    kg.add_node(ToolNode(
        action="update_my_settings",
        entity_type=EntityType.GOV_SETTINGS,
        operation=OperationType.WRITE,
        description="Update my governance settings",
        required_params=["settings_data"],
        tags=["governance", "end_user", "settings", "update"],
        preconditions={},
        effects={"gov_settings.my_settings": "UPDATED"},
    ))
    kg.add_node(ToolNode(
        action="list_my_eligible_delegates",
        entity_type=EntityType.GOV_DELEGATE,
        operation=OperationType.READ,
        description="List my eligible delegates",
        required_params=[],
        optional_params=["filter", "after", "limit"],
        outputs={"items": "gov_delegate.my_eligible[]"},
        tags=["governance", "end_user", "delegate"],
        preconditions={},
        effects={"gov_delegate.my_eligible": "KNOWN"},
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
