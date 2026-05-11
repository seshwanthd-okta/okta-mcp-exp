# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Profile Mappings tools for the Okta MCP server."""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.pagination import create_paginated_response, paginate_all_results
from okta_mcp_server.utils.validation import validate_ids


async def list_profile_mappings(
    ctx: Context,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    fetch_all: bool = False,
) -> dict:
    """List all profile mappings.

    Parameters:
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum mappings per page.
        source_id (str, optional): Filter by source ID.
        target_id (str, optional): Filter by target ID.
        fetch_all (bool, optional): Fetch all pages. Default: False.

    Returns:
        Dict containing list of profile mapping objects.
    """
    logger.info("Listing profile mappings")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        query_params = {}
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit
        if source_id:
            query_params["sourceId"] = source_id
        if target_id:
            query_params["targetId"] = target_id
        mappings, response, err = await client.list_profile_mappings(query_params)
        if err:
            return {"error": f"Error: {err}"}
        if not mappings:
            return create_paginated_response([], response, fetch_all)
        if fetch_all and response and hasattr(response, "has_next") and response.has_next():
            all_mappings, pagination_info = await paginate_all_results(response, mappings)
            return create_paginated_response(all_mappings, response, fetch_all_used=True, pagination_info=pagination_info)
        return create_paginated_response(mappings, response, fetch_all_used=fetch_all)
    except Exception as e:
        return {"error": f"Exception: {e}"}


@validate_ids("mapping_id")
async def get_profile_mapping(mapping_id: str, ctx: Context = None) -> list:
    """Retrieve a specific profile mapping.

    Parameters:
        mapping_id (str, required): The ID of the profile mapping.

    Returns:
        List containing the profile mapping object.
    """
    logger.info(f"Getting profile mapping {mapping_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        mapping, _, err = await client.get_profile_mapping(mapping_id)
        if err:
            return [f"Error: {err}"]
        return [mapping]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("mapping_id")
async def update_profile_mapping(mapping_id: str, mapping_data: dict, ctx: Context = None) -> list:
    """Update a profile mapping.

    Parameters:
        mapping_id (str, required): The ID of the profile mapping.
        mapping_data (dict, required): Updated mapping configuration.

    Returns:
        List containing the updated profile mapping.
    """
    logger.info(f"Updating profile mapping {mapping_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        mapping, _, err = await client.update_profile_mapping(mapping_id, mapping_data)
        if err:
            return [f"Error: {err}"]
        return [mapping]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_profile_mappings, get_profile_mapping, update_profile_mapping]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_profile_mappings": list_profile_mappings,
    "get_profile_mapping": get_profile_mapping,
    "update_profile_mapping": update_profile_mapping,
}
