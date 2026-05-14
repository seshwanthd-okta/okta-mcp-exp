# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Device Integrations tools for the Okta MCP server."""

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.validation import validate_ids


async def list_device_integrations(ctx: Context = None) -> list:
    """List all device integrations.

    Returns:
        List of device integration objects.
    """
    logger.info("Listing device integrations")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        integrations, _, err = await client.list_device_integrations()
        if err:
            return [f"Error: {err}"]
        return integrations if integrations else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("integration_id")
async def get_device_integration(integration_id: str, ctx: Context = None) -> list:
    """Retrieve a specific device integration.

    Parameters:
        integration_id (str, required): The ID of the device integration.

    Returns:
        List containing the device integration object.
    """
    logger.info(f"Getting device integration {integration_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        integration, _, err = await client.get_device_integration(integration_id)
        if err:
            return [f"Error: {err}"]
        return [integration]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("integration_id")
async def activate_device_integration(integration_id: str, ctx: Context = None) -> list:
    """Activate a device integration.

    Parameters:
        integration_id (str, required): The ID of the device integration.

    Returns:
        List containing the result.
    """
    logger.info(f"Activating device integration {integration_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.activate_device_integration(integration_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device integration {integration_id} activated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("integration_id")
async def deactivate_device_integration(integration_id: str, ctx: Context = None) -> list:
    """Deactivate a device integration.

    Parameters:
        integration_id (str, required): The ID of the device integration.

    Returns:
        List containing the result.
    """
    logger.info(f"Deactivating device integration {integration_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.deactivate_device_integration(integration_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Device integration {integration_id} deactivated."]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_device_integrations, get_device_integration, activate_device_integration, deactivate_device_integration]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_device_integrations": list_device_integrations,
    "get_device_integration": get_device_integration,
    "activate_device_integration": activate_device_integration,
    "deactivate_device_integration": deactivate_device_integration,
}
