# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Extended Policy tools: simulate, list policy apps, clone policy, and policy resource mappings."""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.validation import validate_ids


async def simulate_policy(simulation_data: dict, ctx: Context = None) -> list:
    """Simulate a policy evaluation.

    Parameters:
        simulation_data (dict, required): Simulation configuration including policyTypes, appInstance, user, etc.

    Returns:
        List containing the simulation result.
    """
    logger.info("Simulating policy")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result, _, err = await client.simulate_policy(simulation_data)
        if err:
            return [f"Error: {err}"]
        return [result]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id")
async def list_policy_apps(
    policy_id: str,
    ctx: Context = None,
    expand: Optional[str] = None,
) -> list:
    """List all applications assigned to a policy.

    Parameters:
        policy_id (str, required): The ID of the policy.
        expand (str, optional): Expand related resources.

    Returns:
        List of application objects.
    """
    logger.info(f"Listing apps for policy {policy_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        apps, _, err = await client.list_policy_apps(policy_id)
        if err:
            return [f"Error: {err}"]
        return apps if apps else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id")
async def clone_policy(policy_id: str, ctx: Context = None) -> list:
    """Clone a policy.

    Parameters:
        policy_id (str, required): The ID of the policy to clone.

    Returns:
        List containing the cloned policy.
    """
    logger.info(f"Cloning policy {policy_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        policy, _, err = await client.clone_policy(policy_id)
        if err:
            return [f"Error: {err}"]
        return [policy]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id")
async def list_policy_resource_mappings(
    policy_id: str,
    ctx: Context = None,
) -> list:
    """List all resource mappings for a policy.

    Parameters:
        policy_id (str, required): The ID of the policy.

    Returns:
        List of resource mapping objects.
    """
    logger.info(f"Listing resource mappings for policy {policy_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        mappings, _, err = await client.list_policy_resource_mappings(policy_id)
        if err:
            return [f"Error: {err}"]
        return mappings if mappings else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id")
async def create_policy_resource_mapping(policy_id: str, mapping_data: dict, ctx: Context = None) -> list:
    """Create a resource mapping for a policy.

    Parameters:
        policy_id (str, required): The ID of the policy.
        mapping_data (dict, required): Resource mapping configuration.

    Returns:
        List containing the created mapping.
    """
    logger.info(f"Creating resource mapping for policy {policy_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        mapping, _, err = await client.create_policy_resource_mapping(policy_id, mapping_data)
        if err:
            return [f"Error: {err}"]
        return [mapping]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id", "mapping_id")
async def get_policy_resource_mapping(policy_id: str, mapping_id: str, ctx: Context = None) -> list:
    """Retrieve a specific resource mapping for a policy.

    Parameters:
        policy_id (str, required): The ID of the policy.
        mapping_id (str, required): The ID of the mapping.

    Returns:
        List containing the mapping object.
    """
    logger.info(f"Getting resource mapping {mapping_id} for policy {policy_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        mapping, _, err = await client.get_policy_resource_mapping(policy_id, mapping_id)
        if err:
            return [f"Error: {err}"]
        return [mapping]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("policy_id", "mapping_id")
async def delete_policy_resource_mapping(policy_id: str, mapping_id: str, ctx: Context = None) -> list:
    """Delete a resource mapping for a policy.

    Parameters:
        policy_id (str, required): The ID of the policy.
        mapping_id (str, required): The ID of the mapping.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting resource mapping {mapping_id} for policy {policy_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete resource mapping {mapping_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_policy_resource_mapping(policy_id, mapping_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Resource mapping {mapping_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [simulate_policy, list_policy_apps, clone_policy, list_policy_resource_mappings, create_policy_resource_mapping, get_policy_resource_mapping, delete_policy_resource_mapping]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "simulate_policy": simulate_policy,
    "list_policy_apps": list_policy_apps,
    "clone_policy": clone_policy,
    "list_policy_resource_mappings": list_policy_resource_mappings,
    "create_policy_resource_mapping": create_policy_resource_mapping,
    "get_policy_resource_mapping": get_policy_resource_mapping,
    "delete_policy_resource_mapping": delete_policy_resource_mapping,
}
