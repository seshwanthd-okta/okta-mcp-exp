# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Devices tools for the Okta MCP server."""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.pagination import create_paginated_response, paginate_all_results
from okta_mcp_server.utils.validation import validate_ids


async def list_devices(
    ctx: Context,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    search: Optional[str] = None,
    expand: Optional[str] = None,
    fetch_all: bool = False,
) -> dict:
    """List all devices in the organization.

    Parameters:
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum devices per page.
        search (str, optional): Search filter expression.
        expand (str, optional): Expand related resources.
        fetch_all (bool, optional): Fetch all pages. Default: False.

    Returns:
        Dict containing list of device objects.
    """
    logger.info("Listing devices")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        query_params = {}
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit
        if search:
            query_params["search"] = search
        if expand:
            query_params["expand"] = expand
        devices, response, err = await client.list_devices(**query_params)
        if err:
            return {"error": f"Error: {err}"}
        if not devices:
            return create_paginated_response([], response, fetch_all)
        if fetch_all and response and hasattr(response, "has_next") and response.has_next():
            all_devices, pagination_info = await paginate_all_results(response, devices)
            return create_paginated_response(all_devices, response, fetch_all_used=True, pagination_info=pagination_info)
        return create_paginated_response(devices, response, fetch_all_used=fetch_all)
    except Exception as e:
        return {"error": f"Exception: {e}"}


@validate_ids("device_id")
async def get_device(device_id: str, ctx: Context = None, expand: Optional[str] = None) -> list:
    """Retrieve a specific device.

    Parameters:
        device_id (str, required): The ID of the device.
        expand (str, optional): Expand related resources.

    Returns:
        List containing the device object.
    """
    logger.info(f"Getting device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        device, _, err = await client.get_device(device_id)
        if err:
            return [f"Error: {err}"]
        return [device]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def delete_device(device_id: str, ctx: Context = None) -> list:
    """Delete a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting device {device_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete device {device_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Device deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_device(device_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device {device_id} deleted successfully."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def activate_device(device_id: str, ctx: Context = None) -> list:
    """Activate a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List containing the result.
    """
    logger.info(f"Activating device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.activate_device(device_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device {device_id} activated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def deactivate_device(device_id: str, ctx: Context = None) -> list:
    """Deactivate a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List containing the result.
    """
    logger.info(f"Deactivating device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.deactivate_device(device_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device {device_id} deactivated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def suspend_device(device_id: str, ctx: Context = None) -> list:
    """Suspend a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List containing the result.
    """
    logger.info(f"Suspending device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.suspend_device(device_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device {device_id} suspended."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def unsuspend_device(device_id: str, ctx: Context = None) -> list:
    """Unsuspend a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List containing the result.
    """
    logger.info(f"Unsuspending device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.unsuspend_device(device_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device {device_id} unsuspended."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("device_id")
async def list_device_users(device_id: str, ctx: Context = None) -> list:
    """List all users for a device.

    Parameters:
        device_id (str, required): The ID of the device.

    Returns:
        List of user objects.
    """
    logger.info(f"Listing users for device {device_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        users, _, err = await client.list_device_users(device_id)
        if err:
            return [f"Error: {err}"]
        return users if users else []
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_devices, get_device, delete_device, activate_device, deactivate_device, suspend_device, unsuspend_device, list_device_users]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_devices": list_devices,
    "get_device": get_device,
    "delete_device": delete_device,
    "activate_device": activate_device,
    "deactivate_device": deactivate_device,
    "suspend_device": suspend_device,
    "unsuspend_device": unsuspend_device,
    "list_device_users": list_device_users,
}
