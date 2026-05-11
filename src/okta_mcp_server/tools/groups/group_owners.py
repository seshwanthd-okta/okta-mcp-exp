# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Group Owners tools for the Okta MCP server.

Provides operations to manage owners of Okta groups:
    - list_group_owners        GET    /api/v1/groups/{groupId}/owners
    - assign_group_owner       POST   /api/v1/groups/{groupId}/owners
    - delete_group_owner       DELETE /api/v1/groups/{groupId}/owners/{ownerId}
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.pagination import auto_paginate, build_query_params, create_paginated_response
from okta_mcp_server.utils.validation import validate_ids


@validate_ids("group_id")
async def list_group_owners(
    group_id: str,
    ctx: Context = None,
    search: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """List all owners for a specific group.

    Parameters:
        group_id (str, required): The ID of the group.
        search (str, optional): Search string to filter owners.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum number of owners to return per page.

    Returns:
        Dict containing list of group owner objects.
    """
    logger.info(f"Listing owners for group {group_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if search:
            query_params["search"] = search
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit

        owners, response, err = await client.list_group_owners(group_id, **query_params)
        if err:
            logger.error(f"Error listing group owners: {err}")
            return {"error": f"Error: {err}"}

        if not owners:
            return create_paginated_response([], response)

        return create_paginated_response(owners, response)
    except Exception as e:
        logger.error(f"Exception listing group owners: {type(e).__name__}: {e}")
        return {"error": f"Exception: {e}"}


@validate_ids("group_id")
async def assign_group_owner(
    group_id: str,
    owner_data: dict,
    ctx: Context = None,
) -> list:
    """Assign an owner to a group.

    Parameters:
        group_id (str, required): The ID of the group.
        owner_data (dict, required): Owner data including 'id' and 'type' (USER or GROUP).

    Returns:
        List containing the assigned owner details.
    """
    logger.info(f"Assigning owner to group {group_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result, _, err = await client.assign_group_owner(group_id, owner_data)
        if err:
            logger.error(f"Error assigning group owner: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully assigned owner to group {group_id}")
        return [result]
    except Exception as e:
        logger.error(f"Exception assigning group owner: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("group_id", "owner_id")
async def delete_group_owner(
    group_id: str,
    owner_id: str,
    ctx: Context = None,
) -> list:
    """Delete an owner from a specific group.

    Parameters:
        group_id (str, required): The ID of the group.
        owner_id (str, required): The ID of the owner to remove.

    Returns:
        List containing the result of the deletion.
    """
    logger.info(f"Deleting owner {owner_id} from group {group_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.delete_group_owner(group_id, owner_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error deleting group owner: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully deleted owner {owner_id} from group {group_id}")
        return [f"Owner {owner_id} removed from group {group_id} successfully."]
    except Exception as e:
        logger.error(f"Exception deleting group owner: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [list_group_owners, assign_group_owner, delete_group_owner]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "list_group_owners": list_group_owners,
    "assign_group_owner": assign_group_owner,
    "delete_group_owner": delete_group_owner,
}
