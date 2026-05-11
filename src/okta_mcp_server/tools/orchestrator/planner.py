# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
CSP-based Workflow Planner for the Okta Knowledge Graph.

Given a goal (a set of desired state predicates) and an initial state,
the planner uses backward-chaining search with constraint propagation to
find an ordered sequence of ToolNode actions that transitions the initial
state to the goal state.

Each ToolNode contributes:
  - preconditions: state predicates that must hold before the action runs
  - effects: state predicates that hold after the action runs

The planner works backward from the goal: it identifies which effects
satisfy unsatisfied goal predicates, selects the cheapest action, adds
that action's preconditions as new sub-goals, and repeats until all
predicates are satisfied by the initial state.

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    """Output of the planner — an ordered action sequence with rationale."""
    success: bool
    actions: list[str]                    # ordered action names
    steps: list[dict[str, Any]]           # detailed step info with state transitions
    goal_name: str
    initial_state: dict[str, str]
    final_state: dict[str, str]
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "actions": self.actions,
            "steps": self.steps,
            "goal_name": self.goal_name,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            **({"error": self.error} if self.error else {}),
        }



# ---------------------------------------------------------------------------
# CSP Planner — backward-chaining with best-first action selection
# ---------------------------------------------------------------------------

class CSPPlanner:
    """Constraint-based planner using backward-chaining search.

    Algorithm:
    1. Start with the goal state as unresolved constraints.
    2. For each unresolved predicate, find all actions whose effects
       produce it.
    3. Select the best candidate (fewest new preconditions introduced).
    4. Add the chosen action to the plan and its preconditions as new
       sub-goals (unless already satisfied).
    5. Repeat until all predicates are satisfied by the initial state
       or no action can satisfy a remaining predicate.
    6. Topologically sort the resulting action set to respect
       precondition ordering.
    """

    def __init__(self, nodes: dict[str, Any]) -> None:
        """Initialize with a dict of action_name → ToolNode."""
        self._nodes = nodes
        # Build reverse index: (predicate_key, predicate_value) → list of action names
        self._effect_index: dict[tuple[str, str], list[str]] = {}
        for action_name, node in nodes.items():
            for key, value in node.effects.items():
                self._effect_index.setdefault((key, value), []).append(action_name)

    def plan(
        self,
        goal_state: dict[str, str],
        initial_state: dict[str, str] | None = None,
        goal_name: str = "ad_hoc",
        max_steps: int = 20,
    ) -> PlanResult:
        """Generate an action sequence to reach goal_state from initial_state."""
        initial = dict(initial_state) if initial_state else {}

        logger.info(f"CSP planner: goal='{goal_name}', "
                     f"goal_predicates={len(goal_state)}, "
                     f"initial_predicates={len(initial)}")

        # Track which actions we've selected and their ordering constraints
        selected_actions: list[str] = []
        # Current accumulated state = initial + effects of selected actions
        current_state = dict(initial)
        # Predicates still unsatisfied
        open_goals = {k: v for k, v in goal_state.items()
                      if initial.get(k) != v}

        # Track which action satisfies which predicate (for explanation)
        action_rationale: dict[str, list[str]] = {}
        # Track ordering: action A must come before action B
        ordering: dict[str, set[str]] = {}  # action → set of actions that must precede it
        visited_predicates: set[tuple[str, str]] = set()

        while open_goals:
            if len(selected_actions) > max_steps:
                return PlanResult(
                    success=False, actions=[], steps=[], goal_name=goal_name,
                    initial_state=initial, final_state=current_state,
                    error=f"Exceeded max_steps ({max_steps}). Possible cycle or unsolvable goal.",
                )

            # Pick an unresolved predicate
            pred_key, pred_value = next(iter(open_goals.items()))
            pred_tuple = (pred_key, pred_value)

            if pred_tuple in visited_predicates:
                # Cycle detection — we already tried to resolve this
                return PlanResult(
                    success=False, actions=[], steps=[], goal_name=goal_name,
                    initial_state=initial, final_state=current_state,
                    error=f"Cycle detected: cannot resolve '{pred_key}={pred_value}'",
                )
            visited_predicates.add(pred_tuple)

            # Find candidate actions whose effects include this predicate
            candidates = self._effect_index.get(pred_tuple, [])
            if not candidates:
                return PlanResult(
                    success=False, actions=[], steps=[], goal_name=goal_name,
                    initial_state=initial, final_state=current_state,
                    error=f"No action produces effect '{pred_key}={pred_value}'",
                )

            # Select best candidate: prefer already-selected actions, then
            # fewest new preconditions
            best = self._select_best_action(
                candidates, selected_actions, current_state, open_goals,
            )

            if best not in selected_actions:
                selected_actions.append(best)
                ordering.setdefault(best, set())

            # Record rationale
            action_rationale.setdefault(best, []).append(f"{pred_key}={pred_value}")

            # Apply effects of this action to current state
            node = self._nodes[best]
            for ek, ev in node.effects.items():
                current_state[ek] = ev

            # Remove satisfied predicates from open goals
            del open_goals[pred_key]
            # Also remove any other open goals now satisfied
            newly_satisfied = [k for k, v in open_goals.items()
                               if current_state.get(k) == v]
            for k in newly_satisfied:
                del open_goals[k]

            # Add this action's unsatisfied preconditions as new open goals
            for pk, pv in node.preconditions.items():
                if current_state.get(pk) != pv:
                    open_goals[pk] = pv
                    # Record ordering: whatever satisfies this precondition
                    # must come before `best`
                    ordering.setdefault(best, set())

        # Topologically sort the selected actions based on dependency ordering
        sorted_actions = self._topological_sort(selected_actions, ordering)

        # Build detailed step list
        steps = self._build_steps(sorted_actions, initial, action_rationale)

        # Compute final state
        final_state = dict(initial)
        for action_name in sorted_actions:
            node = self._nodes[action_name]
            for ek, ev in node.effects.items():
                final_state[ek] = ev

        logger.info(f"CSP planner: found plan with {len(sorted_actions)} actions: "
                     f"{' → '.join(sorted_actions)}")

        return PlanResult(
            success=True,
            actions=sorted_actions,
            steps=steps,
            goal_name=goal_name,
            initial_state=initial,
            final_state=final_state,
        )

    def _select_best_action(
        self,
        candidates: list[str],
        already_selected: list[str],
        current_state: dict[str, str],
        open_goals: dict[str, str],
    ) -> str:
        """Select the best action from candidates.

        Priority:
        1. Already selected (no new action needed)
        2. Fewest unsatisfied preconditions (least new sub-goals)
        3. Most additional goal predicates satisfied (bonus effects)
        """
        # Prefer already-selected actions
        for c in candidates:
            if c in already_selected:
                return c

        def score(action_name: str) -> tuple[int, int]:
            node = self._nodes[action_name]
            # Count unsatisfied preconditions (lower = better → minimize)
            unsat_preconds = sum(
                1 for pk, pv in node.preconditions.items()
                if current_state.get(pk) != pv
            )
            # Count bonus goal predicates satisfied (higher = better → negate to minimize)
            bonus_effects = sum(
                1 for ek, ev in node.effects.items()
                if (ek, ev) != next(iter(open_goals.items()), (None, None))
                and open_goals.get(ek) == ev
            )
            return (unsat_preconds, -bonus_effects)

        return min(candidates, key=score)

    def _topological_sort(
        self,
        actions: list[str],
        _ordering: dict[str, set[str]],
    ) -> list[str]:
        """Topologically sort actions by their precondition/effect dependencies.

        An action A must come before action B if:
          - B has a precondition that A's effects satisfy, OR
          - B has a filter_template key that A's effects produce (soft dependency
            for auto-wiring filters from upstream results).
        """
        if len(actions) <= 1:
            return list(actions)

        action_set = set(actions)
        # Build real dependency edges from preconditions/effects
        deps: dict[str, set[str]] = {a: set() for a in actions}

        for action_b in actions:
            node_b = self._nodes[action_b]
            # Hard dependency: preconditions
            for pk, pv in node_b.preconditions.items():
                # Find which selected action produces this precondition's required state
                for action_a in actions:
                    if action_a == action_b:
                        continue
                    node_a = self._nodes[action_a]
                    if node_a.effects.get(pk) == pv:
                        deps[action_b].add(action_a)

            # Soft dependency: filter_templates — if B can consume a filter
            # from A's output, B should come after A
            if hasattr(node_b, "filter_templates") and node_b.filter_templates:
                for pred_key in node_b.filter_templates:
                    for action_a in actions:
                        if action_a == action_b:
                            continue
                        node_a = self._nodes[action_a]
                        # Check if action_a produces this predicate key (any value)
                        if pred_key in node_a.effects:
                            deps[action_b].add(action_a)

        # Kahn's algorithm
        in_degree = {a: len(deps[a]) for a in actions}
        queue = [a for a in actions if in_degree[a] == 0]
        # Maintain original insertion order for stability among equal-degree nodes
        action_order = {a: i for i, a in enumerate(actions)}
        queue.sort(key=lambda a: action_order[a])

        result: list[str] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for a in actions:
                if node in deps[a]:
                    deps[a].discard(node)
                    in_degree[a] -= 1
                    if in_degree[a] == 0:
                        queue.append(a)
            queue.sort(key=lambda a: action_order[a])

        if len(result) != len(actions):
            # Cycle detected — fall back to original order
            logger.warning("Topological sort detected cycle, falling back to insertion order")
            return list(actions)

        return result

    def _build_steps(
        self,
        actions: list[str],
        initial_state: dict[str, str],
        rationale: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Build detailed step descriptors with state transitions."""
        steps: list[dict[str, Any]] = []
        running_state = dict(initial_state)

        for idx, action_name in enumerate(actions):
            node = self._nodes[action_name]
            step = {
                "step": idx + 1,
                "action": action_name,
                "description": node.description,
                "entity_type": node.entity_type.value,
                "operation": node.operation.value,
                "is_destructive": node.is_destructive,
                "preconditions": dict(node.preconditions),
                "effects": dict(node.effects),
                "satisfies": rationale.get(action_name, []),
                "state_before": dict(running_state),
            }
            # Apply effects
            for ek, ev in node.effects.items():
                running_state[ek] = ev
            step["state_after"] = dict(running_state)
            steps.append(step)

        return steps


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def plan_for_state(
    goal_state: dict[str, str],
    initial_state: dict[str, str] | None = None,
    kg: Any = None,
) -> PlanResult:
    """Plan a workflow for an ad-hoc goal state.

    Args:
        goal_state: Dict of predicate → value that must hold at the end.
        initial_state: What's true before we start.
        kg: Knowledge graph instance. If None, uses the singleton.

    Returns:
        PlanResult with the ordered action sequence.
    """
    if kg is None:
        from okta_mcp_server.tools.orchestrator.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()

    planner = CSPPlanner(kg._nodes)
    return planner.plan(
        goal_state=goal_state,
        initial_state=initial_state,
        goal_name="ad_hoc",
    )
