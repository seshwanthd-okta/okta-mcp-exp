# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Types tools for the Okta MCP server."""

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.validation import validate_ids


async def list_user_types(ctx: Context = None) -> list:
    """List all user types.

    Returns:
        List of user type objects.
    """
    logger.info("Listing user types")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        types, _, err = await client.list_user_types()
        if err:
            return [f"Error: {err}"]
        return types if types else []
    except Exception as e:
        return [f"Exception: {e}"]


async def create_user_type(type_data: dict, ctx: Context = None) -> list:
    """Create a new user type.

    Parameters:
        type_data (dict, required): User type definition including name and displayName.

    Returns:
        List containing the created user type.
    """
    logger.info("Creating user type")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        user_type, _, err = await client.create_user_type(type_data)
        if err:
            return [f"Error: {err}"]
        return [user_type]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("type_id")
async def get_user_type(type_id: str, ctx: Context = None) -> list:
    """Retrieve a specific user type.

    Parameters:
        type_id (str, required): The ID of the user type.

    Returns:
        List containing the user type object.
    """
    logger.info(f"Getting user type {type_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        user_type, _, err = await client.get_user_type(type_id)
        if err:
            return [f"Error: {err}"]
        return [user_type]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("type_id")
async def update_user_type(type_id: str, type_data: dict, ctx: Context = None) -> list:
    """Update a user type (partial update).

    Parameters:
        type_id (str, required): The ID of the user type.
        type_data (dict, required): Updated user type fields.

    Returns:
        List containing the updated user type.
    """
    logger.info(f"Updating user type {type_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        user_type, _, err = await client.update_user_type(type_id, type_data)
        if err:
            return [f"Error: {err}"]
        return [user_type]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("type_id")
async def replace_user_type(type_id: str, type_data: dict, ctx: Context = None) -> list:
    """Replace a user type (full replacement).

    Parameters:
        type_id (str, required): The ID of the user type.
        type_data (dict, required): Complete user type definition.

    Returns:
        List containing the replaced user type.
    """
    logger.info(f"Replacing user type {type_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        user_type, _, err = await client.replace_user_type(type_id, type_data)
        if err:
            return [f"Error: {err}"]
        return [user_type]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("type_id")
async def delete_user_type(type_id: str, ctx: Context = None) -> list:
    """Delete a user type.

    Parameters:
        type_id (str, required): The ID of the user type to delete.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting user type {type_id}")
    outcome = await elicit_or_fallback(
        ctx,
        message=f"Are you sure you want to delete user type {type_id}?",
        schema=DeleteConfirmation,
        auto_confirm_on_fallback=True,
    )
    if not outcome.confirmed:
        return [{"message": "User type deletion cancelled."}]

    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_user_type(type_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"User type {type_id} deleted successfully."]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_user_types, create_user_type, get_user_type, update_user_type, replace_user_type, delete_user_type]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_user_types": list_user_types,
    "create_user_type": create_user_type,
    "get_user_type": get_user_type,
    "update_user_type": update_user_type,
    "replace_user_type": replace_user_type,
    "delete_user_type": delete_user_type,
}
