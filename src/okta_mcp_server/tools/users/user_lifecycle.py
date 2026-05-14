# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Lifecycle tools for the Okta MCP server.

Provides additional lifecycle operations beyond those in users.py:
    - reactivate_user      POST /api/v1/users/{id}/lifecycle/reactivate
    - reset_factors         POST /api/v1/users/{id}/lifecycle/reset_factors
    - unlock_user           POST /api/v1/users/{id}/lifecycle/unlock
    - unsuspend_user        POST /api/v1/users/{id}/lifecycle/unsuspend
    - list_user_blocks      GET  /api/v1/users/{id}/blocks
    - list_user_clients     GET  /api/v1/users/{userId}/clients
    - list_user_devices     GET  /api/v1/users/{userId}/devices
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.validation import validate_ids


@validate_ids("user_id")
async def reactivate_user(
    user_id: str,
    send_email: bool = False,
    ctx: Context = None,
) -> list:
    """Reactivate a user. This operation can only be performed on users with a PROVISIONED status.

    Parameters:
        user_id (str, required): The ID of the user to reactivate.
        send_email (bool, optional): Whether to send an activation email. Default: False.

    Returns:
        List containing the reactivation result.
    """
    logger.info(f"Reactivating user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        token, _, err = await client.reactivate_user(user_id, send_email=send_email)
        if err:
            logger.error(f"Error reactivating user: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully reactivated user {user_id}")
        return [{
            "status": "reactivated",
            "user_id": user_id,
            "activation_token": getattr(token, "activationToken", None) if token else None,
        }]
    except Exception as e:
        logger.error(f"Exception reactivating user: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def reset_factors(
    user_id: str,
    ctx: Context = None,
) -> list:
    """Reset all MFA factors for a user.

    Parameters:
        user_id (str, required): The ID of the user whose factors to reset.

    Returns:
        List containing the result of the factor reset.
    """
    logger.info(f"Resetting factors for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.reset_factors(user_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error resetting factors: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully reset factors for user {user_id}")
        return [f"All MFA factors reset for user {user_id}."]
    except Exception as e:
        logger.error(f"Exception resetting factors: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def unlock_user(
    user_id: str,
    ctx: Context = None,
) -> list:
    """Unlock a locked-out user.

    Parameters:
        user_id (str, required): The ID of the user to unlock.

    Returns:
        List containing the unlock result.
    """
    logger.info(f"Unlocking user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.unlock_user(user_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error unlocking user: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully unlocked user {user_id}")
        return [f"User {user_id} unlocked successfully."]
    except Exception as e:
        logger.error(f"Exception unlocking user: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def unsuspend_user(
    user_id: str,
    ctx: Context = None,
) -> list:
    """Unsuspend a suspended user, returning them to ACTIVE status.

    Parameters:
        user_id (str, required): The ID of the user to unsuspend.

    Returns:
        List containing the unsuspend result.
    """
    logger.info(f"Unsuspending user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.unsuspend_user(user_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            logger.error(f"Error unsuspending user: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully unsuspended user {user_id}")
        return [f"User {user_id} unsuspended successfully."]
    except Exception as e:
        logger.error(f"Exception unsuspending user: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_user_blocks(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List information about how a user is blocked from accessing their account.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List containing user block information.
    """
    logger.info(f"Listing blocks for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        blocks, _, err = await client.list_user_blocks(user_id)
        if err:
            logger.error(f"Error listing user blocks: {err}")
            return [f"Error: {err}"]

        return blocks if blocks else []
    except Exception as e:
        logger.error(f"Exception listing user blocks: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_user_clients(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List all clients for a user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of client objects.
    """
    logger.info(f"Listing clients for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        clients, _, err = await client.list_user_clients(user_id)
        if err:
            logger.error(f"Error listing user clients: {err}")
            return [f"Error: {err}"]

        return clients if clients else []
    except Exception as e:
        logger.error(f"Exception listing user clients: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_user_devices(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List all devices for an enrolled user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of device objects.
    """
    logger.info(f"Listing devices for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        devices, _, err = await client.list_user_devices(user_id)
        if err:
            logger.error(f"Error listing user devices: {err}")
            return [f"Error: {err}"]

        return devices if devices else []
    except Exception as e:
        logger.error(f"Exception listing user devices: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    reactivate_user, reset_factors, unlock_user, unsuspend_user,
    list_user_blocks, list_user_clients, list_user_devices,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "reactivate_user": reactivate_user,
    "reset_factors": reset_factors,
    "unlock_user": unlock_user,
    "unsuspend_user": unsuspend_user,
    "list_user_blocks": list_user_blocks,
    "list_user_clients": list_user_clients,
    "list_user_devices": list_user_devices,
}
