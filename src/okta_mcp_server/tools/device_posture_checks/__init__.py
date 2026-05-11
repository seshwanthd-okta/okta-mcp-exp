# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Device Posture Checks tools for the Okta MCP server."""

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.validation import validate_ids


async def list_device_posture_checks(ctx: Context = None) -> list:
    """List all device posture checks.

    Returns:
        List of device posture check objects.
    """
    logger.info("Listing device posture checks")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        checks, _, err = await client.list_device_posture_checks()
        if err:
            return [f"Error: {err}"]
        return checks if checks else []
    except Exception as e:
        return [f"Exception: {e}"]


async def create_device_posture_check(check_data: dict, ctx: Context = None) -> list:
    """Create a device posture check.

    Parameters:
        check_data (dict, required): Device posture check definition.

    Returns:
        List containing the created posture check.
    """
    logger.info("Creating device posture check")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        check, _, err = await client.create_device_posture_check(check_data)
        if err:
            return [f"Error: {err}"]
        return [check]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_default_device_posture_checks(ctx: Context = None) -> list:
    """List all default device posture checks.

    Returns:
        List of default device posture check objects.
    """
    logger.info("Listing default device posture checks")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        checks, _, err = await client.list_default_device_posture_checks()
        if err:
            return [f"Error: {err}"]
        return checks if checks else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("check_id")
async def get_device_posture_check(check_id: str, ctx: Context = None) -> list:
    """Retrieve a specific device posture check.

    Parameters:
        check_id (str, required): The ID of the posture check.

    Returns:
        List containing the posture check object.
    """
    logger.info(f"Getting device posture check {check_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        check, _, err = await client.get_device_posture_check(check_id)
        if err:
            return [f"Error: {err}"]
        return [check]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("check_id")
async def replace_device_posture_check(check_id: str, check_data: dict, ctx: Context = None) -> list:
    """Replace a device posture check.

    Parameters:
        check_id (str, required): The ID of the posture check.
        check_data (dict, required): Updated posture check definition.

    Returns:
        List containing the updated posture check.
    """
    logger.info(f"Replacing device posture check {check_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        check, _, err = await client.replace_device_posture_check(check_id, check_data)
        if err:
            return [f"Error: {err}"]
        return [check]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("check_id")
async def delete_device_posture_check(check_id: str, ctx: Context = None) -> list:
    """Delete a device posture check.

    Parameters:
        check_id (str, required): The ID of the posture check.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting device posture check {check_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete device posture check {check_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_device_posture_check(check_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device posture check {check_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_device_posture_checks, create_device_posture_check, list_default_device_posture_checks, get_device_posture_check, replace_device_posture_check, delete_device_posture_check]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_device_posture_checks": list_device_posture_checks,
    "create_device_posture_check": create_device_posture_check,
    "list_default_device_posture_checks": list_default_device_posture_checks,
    "get_device_posture_check": get_device_posture_check,
    "replace_device_posture_check": replace_device_posture_check,
    "delete_device_posture_check": delete_device_posture_check,
}
