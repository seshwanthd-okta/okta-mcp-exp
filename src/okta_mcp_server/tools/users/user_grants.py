# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Grants tools for the Okta MCP server.

Provides operations to manage user consent grants:
    - list_user_grants_for_client   GET    /api/v1/users/{userId}/clients/{clientId}/grants
    - revoke_grants_for_client      DELETE /api/v1/users/{userId}/clients/{clientId}/grants
    - list_user_grants              GET    /api/v1/users/{userId}/grants
    - revoke_all_user_grants        DELETE /api/v1/users/{userId}/grants
    - get_user_grant                GET    /api/v1/users/{userId}/grants/{grantId}
    - revoke_user_grant             DELETE /api/v1/users/{userId}/grants/{grantId}
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.pagination import create_paginated_response, paginate_all_results
from okta_mcp_server.utils.validation import validate_ids


@validate_ids("user_id", "client_id")
async def list_user_grants_for_client(
    user_id: str,
    client_id: str,
    ctx: Context = None,
    expand: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """List all grants for a user and a specific client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.
        expand (str, optional): Expand related resources.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum number of grants to return per page.

    Returns:
        Dict containing list of grant objects.
    """
    logger.info(f"Listing grants for user {user_id} and client {client_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if expand:
            query_params["expand"] = expand
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit
        grants, response, err = await client.list_grants_for_user_and_client(
            user_id, client_id, query_params
        )
        if err:
            return {"error": f"Error: {err}"}
        return create_paginated_response(grants or [], response)
    except Exception as e:
        return {"error": f"Exception: {e}"}


@validate_ids("user_id", "client_id")
async def revoke_grants_for_client(
    user_id: str,
    client_id: str,
    ctx: Context = None,
) -> list:
    """Revoke all grants for a user and a specific client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.

    Returns:
        List containing the result.
    """
    logger.info(f"Revoking grants for user {user_id} and client {client_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.revoke_grants_for_user_and_client(user_id, client_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"All grants revoked for user {user_id} and client {client_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_user_grants(
    user_id: str,
    ctx: Context = None,
    scope_id: Optional[str] = None,
    expand: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """List all user grants.

    Parameters:
        user_id (str, required): The ID of the user.
        scope_id (str, optional): Filter by scope ID.
        expand (str, optional): Expand related resources.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum number of grants to return per page.

    Returns:
        Dict containing list of grant objects.
    """
    logger.info(f"Listing grants for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if scope_id:
            query_params["scopeId"] = scope_id
        if expand:
            query_params["expand"] = expand
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit
        grants, response, err = await client.list_user_grants(user_id, query_params)
        if err:
            return {"error": f"Error: {err}"}
        return create_paginated_response(grants or [], response)
    except Exception as e:
        return {"error": f"Exception: {e}"}


@validate_ids("user_id")
async def revoke_all_user_grants(
    user_id: str,
    ctx: Context = None,
) -> list:
    """Revoke all user grants.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List containing the result.
    """
    logger.info(f"Revoking all grants for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.revoke_user_grants(user_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"All grants revoked for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "grant_id")
async def get_user_grant(
    user_id: str,
    grant_id: str,
    ctx: Context = None,
    expand: Optional[str] = None,
) -> list:
    """Retrieve a specific user grant.

    Parameters:
        user_id (str, required): The ID of the user.
        grant_id (str, required): The ID of the grant.
        expand (str, optional): Expand related resources.

    Returns:
        List containing the grant object.
    """
    logger.info(f"Getting grant {grant_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if expand:
            query_params["expand"] = expand
        grant, _, err = await client.get_user_grant(user_id, grant_id, query_params)
        if err:
            return [f"Error: {err}"]
        return [grant]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "grant_id")
async def revoke_user_grant(
    user_id: str,
    grant_id: str,
    ctx: Context = None,
) -> list:
    """Revoke a specific user grant.

    Parameters:
        user_id (str, required): The ID of the user.
        grant_id (str, required): The ID of the grant to revoke.

    Returns:
        List containing the result.
    """
    logger.info(f"Revoking grant {grant_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.revoke_user_grant(user_id, grant_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Grant {grant_id} revoked for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    list_user_grants_for_client, revoke_grants_for_client,
    list_user_grants, revoke_all_user_grants,
    get_user_grant, revoke_user_grant,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "list_user_grants_for_client": list_user_grants_for_client,
    "revoke_grants_for_client": revoke_grants_for_client,
    "list_user_grants": list_user_grants,
    "revoke_all_user_grants": revoke_all_user_grants,
    "get_user_grant": get_user_grant,
    "revoke_user_grant": revoke_user_grant,
}
