# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Workflow definitions for the Okta MCP Orchestrator.

Each workflow is a function that takes user-supplied parameters and returns
a Plan with pre-populated steps.  The engine executes these steps server-side.

Start with one well-defined workflow and add more incrementally:
  1. offboard_user  — find user, list their groups, remove from all groups,
                      list app assignments, deactivate user
"""

from __future__ import annotations

import re

from loguru import logger

from okta_mcp_server.tools.orchestrator.engine import Plan, Step, create_plan


# ---------------------------------------------------------------------------
# Workflow registry
# ---------------------------------------------------------------------------

# Maps (action, target_type) tuples to builder functions.
# Also stores keyword patterns for intent matching.

WORKFLOW_REGISTRY: dict[str, dict] = {
    "offboard_user": {
        "action": "offboard",
        "target_type": "user",
        "description": "Offboard a user: find them, remove from all groups, and deactivate their account",
        "keywords": ["offboard", "terminate", "disable.*user", "remove.*all.*access", "deactivate.*user"],
        "builder": None,  # set after definition
        "required_params": ["user_identifier"],
        "scopes_needed": ["okta.users.manage", "okta.groups.manage"],
    },
    "suspend_user": {
        "action": "suspend",
        "target_type": "user",
        "description": (
            "Suspend a user: find them, revoke all active sessions, "
            "and suspend the account (reversible)"
        ),
        "keywords": [
            "suspend.*user",
            "lock.*out",
            "revoke.*session",
            "block.*user",
            "temporarily.*disable",
        ],
        "builder": None,  # set after definition
        "required_params": ["user_identifier"],
        "scopes_needed": ["okta.users.manage", "okta.sessions.manage"],
    },
    "onboard_user": {
        "action": "onboard",
        "target_type": "user",
        "description": (
            "Onboard a user: find them, activate their account "
            "(sends activation email), and report their current group memberships"
        ),
        "keywords": [
            "onboard",
            "activate.*user",
            "provision.*user",
            "welcome.*user",
            "enable.*user",
            "new.*employee",
        ],
        "builder": None,  # set after definition
        "required_params": ["user_identifier"],
        "scopes_needed": ["okta.users.manage", "okta.groups.read"],
    },
}


def match_workflow(action: str, target_type: str) -> str | None:
    """Match an (action, target_type) pair to a workflow name."""
    for name, entry in WORKFLOW_REGISTRY.items():
        if entry["action"] == action.lower() and entry["target_type"] == target_type.lower():
            return name
    return None


def match_workflow_by_keywords(intent: str) -> str | None:
    """Fuzzy match a free-form intent string to a workflow via keyword patterns."""
    for name, entry in WORKFLOW_REGISTRY.items():
        for pattern in entry.get("keywords", []):
            if re.search(pattern, intent, re.IGNORECASE):
                return name
    return None


def get_workflow_info() -> list[dict]:
    """Return a summary of all available workflows for discovery."""
    return [
        {
            "name": name,
            "action": entry["action"],
            "target_type": entry["target_type"],
            "description": entry["description"],
            "required_params": entry["required_params"],
            "scopes_needed": entry["scopes_needed"],
        }
        for name, entry in WORKFLOW_REGISTRY.items()
    ]


# ---------------------------------------------------------------------------
# Workflow: offboard_user
# ---------------------------------------------------------------------------

def build_offboard_user(user_identifier: str) -> Plan:
    """Build an offboard-user plan.

    Steps:
      1. Look up the user by login/email/id
      2. List all groups the user belongs to
      3. Remove the user from each group (for_each)
      4. List the user's app assignments (informational)
      5. Deactivate the user
    """
    logger.info(f"Building offboard_user plan for: {user_identifier}")

    steps = [
        Step(
            number=1,
            action="get_user",
            params={"user_id": user_identifier},
            description=f"Look up user '{user_identifier}'",
        ),
        Step(
            number=2,
            action="list_user_groups",
            params={"user_id": "$step1.id"},
            description="List all groups the user belongs to",
        ),
        Step(
            number=3,
            action="remove_user_from_group",
            params={"user_id": "$step1.id"},
            for_each="$step2",
            description="Remove user from each group",
            is_destructive=True,
        ),
        Step(
            number=4,
            action="list_user_app_assignments",
            params={"user_id": "$step1.id"},
            description="List the user's application assignments (informational)",
        ),
        Step(
            number=5,
            action="deactivate_user",
            params={"user_id": "$step1.id"},
            description="Deactivate the user account",
            is_destructive=True,
        ),
    ]

    return create_plan(
        workflow_name="offboard_user",
        description=f"Offboard user '{user_identifier}': remove from all groups and deactivate account",
        steps=steps,
    )


# Wire builder into registry
WORKFLOW_REGISTRY["offboard_user"]["builder"] = build_offboard_user


# ---------------------------------------------------------------------------
# Workflow: suspend_user
# ---------------------------------------------------------------------------

def build_suspend_user(user_identifier: str) -> Plan:
    """Build a suspend-user plan.

    Steps:
      1. Look up the user by login/email/id
      2. Revoke all active sessions (forces sign-out everywhere)
      3. Suspend the user account (reversible — can unsuspend later)
    """
    logger.info(f"Building suspend_user plan for: {user_identifier}")

    steps = [
        Step(
            number=1,
            action="get_user",
            params={"user_id": user_identifier},
            description=f"Look up user '{user_identifier}'",
        ),
        Step(
            number=2,
            action="clear_user_sessions",
            params={"user_id": "$step1.id", "keep_current": False},
            description="Revoke all active sessions (sign out everywhere)",
            is_destructive=True,
        ),
        Step(
            number=3,
            action="suspend_user",
            params={"user_id": "$step1.id"},
            description="Suspend the user account",
            is_destructive=True,
        ),
    ]

    return create_plan(
        workflow_name="suspend_user",
        description=(
            f"Suspend user '{user_identifier}': "
            "revoke all active sessions and suspend the account"
        ),
        steps=steps,
    )


# Wire builder into registry
WORKFLOW_REGISTRY["suspend_user"]["builder"] = build_suspend_user


# ---------------------------------------------------------------------------
# Workflow: onboard_user
# ---------------------------------------------------------------------------

def build_onboard_user(user_identifier: str, send_email: bool = True) -> Plan:
    """Build an onboard-user plan.

    Steps:
      1. Look up the user by login/email/id
      2. Activate the user account (optionally sends activation email)
      3. List current group memberships (informational — shows what they can access)
    """
    logger.info(f"Building onboard_user plan for: {user_identifier} (send_email={send_email})")

    steps = [
        Step(
            number=1,
            action="get_user",
            params={"user_id": user_identifier},
            description=f"Look up user '{user_identifier}'",
        ),
        Step(
            number=2,
            action="activate_user",
            params={"user_id": "$step1.id", "send_email": send_email},
            description=(
                "Activate the user account"
                + (" and send activation email" if send_email else " (no activation email)")
            ),
            is_destructive=False,
        ),
        Step(
            number=3,
            action="list_user_groups",
            params={"user_id": "$step1.id"},
            description="List current group memberships (shows what the user can access)",
        ),
    ]

    return create_plan(
        workflow_name="onboard_user",
        description=(
            f"Onboard user '{user_identifier}': activate account"
            + (" with activation email" if send_email else "")
            + " and report group memberships"
        ),
        steps=steps,
    )


# Wire builder into registry
WORKFLOW_REGISTRY["onboard_user"]["builder"] = build_onboard_user
