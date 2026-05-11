# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Group Rules tools for the Okta MCP server.

Provides operations to manage group rules:
    - list_group_rules         GET    /api/v1/groups/rules
    - create_group_rule        POST   /api/v1/groups/rules
    - get_group_rule           GET    /api/v1/groups/rules/{groupRuleId}
    - replace_group_rule       PUT    /api/v1/groups/rules/{groupRuleId}
    - delete_group_rule        DELETE /api/v1/groups/rules/{groupRuleId}
    - activate_group_rule      POST   /api/v1/groups/rules/{groupRuleId}/lifecycle/activate
    - deactivate_group_rule    POST   /api/v1/groups/rules/{groupRuleId}/lifecycle/deactivate
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.pagination import create_paginated_response, paginate_all_results
from okta_mcp_server.utils.validation import validate_ids


async def list_group_rules(
    ctx: Context,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    search: Optional[str] = None,
    expand: Optional[str] = None,
    fetch_all: bool = False,
) -> dict:
    """List all group rules for your org.

    Parameters:
        limit (int, optional): Maximum number of rules to return per page.
        after (str, optional): Pagination cursor.
        search (str, optional): Search string to filter group rules.
        expand (str, optional): Expand related resources.
        fetch_all (bool, optional): If True, fetch all pages. Default: False.

    Returns:
        Dict containing list of group rule objects.
    """
    logger.info("Listing group rules")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if limit:
            query_params["limit"] = limit
        if after:
            query_params["after"] = after
        if search:
            query_params["search"] = search
        if expand:
            query_params["expand"] = expand

        rules, response, err = await client.list_group_rules(query_params)
        if err:
            logger.error(f"Error listing group rules: {err}")
            return {"error": f"Error: {err}"}

        if not rules:
            return create_paginated_response([], response, fetch_all)

        if fetch_all and response and hasattr(response, "has_next") and response.has_next():
            all_rules, pagination_info = await paginate_all_results(response, rules)
            return create_paginated_response(all_rules, response, fetch_all_used=True, pagination_info=pagination_info)

        return create_paginated_response(rules, response, fetch_all_used=fetch_all)
    except Exception as e:
        logger.error(f"Exception listing group rules: {type(e).__name__}: {e}")
        return {"error": f"Exception: {e}"}


async def create_group_rule(
    rule_data: dict,
    ctx: Context = None,
) -> list:
    """Create a group rule to dynamically add users to the specified group.

    Parameters:
        rule_data (dict, required): The group rule definition including name, type, conditions, and actions.

    Returns:
        List containing the created group rule.
    """
    logger.info("Creating group rule")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        rule, _, err = await client.create_group_rule(rule_data)
        if err:
            logger.error(f"Error creating group rule: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully created group rule: {rule.id if hasattr(rule, 'id') else 'unknown'}")
        return [rule]
    except Exception as e:
        logger.error(f"Exception creating group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("rule_id")
async def get_group_rule(
    rule_id: str,
    ctx: Context = None,
    expand: Optional[str] = None,
) -> list:
    """Retrieve a specific group rule by ID.

    Parameters:
        rule_id (str, required): The ID of the group rule.
        expand (str, optional): Expand related resources.

    Returns:
        List containing the group rule.
    """
    logger.info(f"Getting group rule {rule_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if expand:
            query_params["expand"] = expand
        rule, _, err = await client.get_group_rule(rule_id, query_params)
        if err:
            logger.error(f"Error getting group rule: {err}")
            return [f"Error: {err}"]

        return [rule]
    except Exception as e:
        logger.error(f"Exception getting group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("rule_id")
async def replace_group_rule(
    rule_id: str,
    rule_data: dict,
    ctx: Context = None,
) -> list:
    """Replace a group rule. You can only update rules with status INACTIVE.

    Parameters:
        rule_id (str, required): The ID of the group rule to replace.
        rule_data (dict, required): The updated group rule definition.

    Returns:
        List containing the updated group rule.
    """
    logger.info(f"Replacing group rule {rule_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        rule, _, err = await client.replace_group_rule(rule_id, rule_data)
        if err:
            logger.error(f"Error replacing group rule: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully replaced group rule {rule_id}")
        return [rule]
    except Exception as e:
        logger.error(f"Exception replacing group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("rule_id")
async def delete_group_rule(
    rule_id: str,
    ctx: Context = None,
    remove_users: Optional[bool] = None,
) -> list:
    """Delete a specific group rule.

    Parameters:
        rule_id (str, required): The ID of the group rule to delete.
        remove_users (bool, optional): Whether to remove users from the group when deleting the rule.

    Returns:
        List containing the result of the deletion.
    """
    logger.info(f"Deleting group rule {rule_id}")

    outcome = await elicit_or_fallback(
        ctx,
        message=f"Are you sure you want to delete group rule {rule_id}?",
        schema=DeleteConfirmation,
        auto_confirm_on_fallback=True,
    )
    if not outcome.confirmed:
        return [{"message": "Group rule deletion cancelled."}]

    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if remove_users is not None:
            query_params["removeUsers"] = remove_users
        result = await client.delete_group_rule(rule_id, query_params)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error deleting group rule: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully deleted group rule {rule_id}")
        return [f"Group rule {rule_id} deleted successfully."]
    except Exception as e:
        logger.error(f"Exception deleting group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("rule_id")
async def activate_group_rule(
    rule_id: str,
    ctx: Context = None,
) -> list:
    """Activate a group rule.

    Parameters:
        rule_id (str, required): The ID of the group rule to activate.

    Returns:
        List containing the activation result.
    """
    logger.info(f"Activating group rule {rule_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.activate_group_rule(rule_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error activating group rule: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully activated group rule {rule_id}")
        return [f"Group rule {rule_id} activated successfully."]
    except Exception as e:
        logger.error(f"Exception activating group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("rule_id")
async def deactivate_group_rule(
    rule_id: str,
    ctx: Context = None,
) -> list:
    """Deactivate a group rule.

    Parameters:
        rule_id (str, required): The ID of the group rule to deactivate.

    Returns:
        List containing the deactivation result.
    """
    logger.info(f"Deactivating group rule {rule_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.deactivate_group_rule(rule_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error deactivating group rule: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully deactivated group rule {rule_id}")
        return [f"Group rule {rule_id} deactivated successfully."]
    except Exception as e:
        logger.error(f"Exception deactivating group rule: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    list_group_rules, create_group_rule, get_group_rule, replace_group_rule,
    delete_group_rule, activate_group_rule, deactivate_group_rule,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "list_group_rules": list_group_rules,
    "create_group_rule": create_group_rule,
    "get_group_rule": get_group_rule,
    "replace_group_rule": replace_group_rule,
    "delete_group_rule": delete_group_rule,
    "activate_group_rule": activate_group_rule,
    "deactivate_group_rule": deactivate_group_rule,
}
