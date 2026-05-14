# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Governance End-User API tools for the Okta MCP server.

Covers My Requests, My Catalogs, and My Settings governance endpoints.
"""

import json
from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.validation import validate_ids


async def _gov_request(client, method: str, path: str, body: dict | None = None, query_params: dict | None = None):
    """Execute a raw HTTP request against the Okta governance API."""
    url = f"{client._base_url}{path}"
    if query_params:
        qs = "&".join(f"{k}={v}" for k, v in query_params.items() if v is not None)
        if qs:
            url = f"{url}?{qs}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body_str = json.dumps(body) if body else None
    request, err = await client._request_executor.create_request(
        method, url, body_str, headers, {}, keep_empty_params=False
    )
    if err:
        return None, err
    _, response_body, err = await client._request_executor.execute(request)
    if err:
        return None, err
    if not response_body:
        return None, None
    data = json.loads(response_body) if isinstance(response_body, str) else response_body
    return data, None


# ═══════════════════════════════════════════════════════════════
#  MY REQUESTS
# ═══════════════════════════════════════════════════════════════

@validate_ids("entry_id")
async def create_my_request(entry_id: str, request_data: dict, ctx: Context = None) -> list:
    """Create a request for a catalog entry (end-user).

    Parameters:
        entry_id (str, required): The ID of the catalog entry.
        request_data (dict, required): Request data.

    Returns:
        List containing the created request.
    """
    logger.info(f"Creating my request for entry {entry_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}/requests", body=request_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Request created."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id", "request_id")
async def get_my_request(entry_id: str, request_id: str, ctx: Context = None) -> list:
    """Retrieve my request.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.
        request_id (str, required): The ID of the request.

    Returns:
        List containing the request object.
    """
    logger.info(f"Getting my request {request_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}/requests/{request_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  MY CATALOGS
# ═══════════════════════════════════════════════════════════════

async def list_my_catalog_entries(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    match: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """List my entries for the default access request catalog.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        match (str, optional): Match expression.
        limit (int, optional): Maximum results per page.

    Returns:
        List of catalog entry objects.
    """
    logger.info("Listing my catalog entries")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if after:
            qp["after"] = after
        if match:
            qp["match"] = match
        if limit:
            qp["limit"] = limit
        data, err = await _gov_request(client, "GET", "/governance/api/v2/my/catalogs/default/entries", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id")
async def get_my_catalog_entry(entry_id: str, ctx: Context = None) -> list:
    """Retrieve my catalog entry.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.

    Returns:
        List containing the catalog entry object.
    """
    logger.info(f"Getting my catalog entry {entry_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id")
async def get_my_catalog_entry_request_fields(entry_id: str, ctx: Context = None) -> list:
    """Retrieve the request fields for my catalog entry.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.

    Returns:
        List containing the request fields.
    """
    logger.info(f"Getting request fields for my catalog entry {entry_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}/request-fields")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id")
async def list_my_catalog_entry_users(
    entry_id: str,
    ctx: Context = None,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """List my catalog entry users.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.

    Returns:
        List of user objects.
    """
    logger.info(f"Listing users for my catalog entry {entry_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if after:
            qp["after"] = after
        if limit:
            qp["limit"] = limit
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}/users", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id", "user_id")
async def get_my_catalog_entry_user_request_fields(entry_id: str, user_id: str, ctx: Context = None) -> list:
    """Retrieve the entry request fields for a user.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.
        user_id (str, required): The ID of the user.

    Returns:
        List containing the request fields.
    """
    logger.info(f"Getting request fields for entry {entry_id} user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/my/catalogs/default/entries/{entry_id}/users/{user_id}/request-fields")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  MY SETTINGS
# ═══════════════════════════════════════════════════════════════

async def get_my_settings(ctx: Context = None) -> list:
    """Retrieve my settings.

    Returns:
        List containing the settings object.
    """
    logger.info("Getting my settings")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", "/governance/api/v1/my/settings")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


async def update_my_settings(settings_data: dict, ctx: Context = None) -> list:
    """Update my settings.

    Parameters:
        settings_data (dict, required): Partial update data.

    Returns:
        List containing the updated settings.
    """
    logger.info("Updating my settings")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", "/governance/api/v1/my/settings", body=settings_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Settings updated."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_my_eligible_delegates(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """List my eligible delegates.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.

    Returns:
        List of eligible delegate user objects.
    """
    logger.info("Listing my eligible delegates")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if after:
            qp["after"] = after
        if limit:
            qp["limit"] = limit
        data, err = await _gov_request(client, "GET", "/governance/api/v1/my/settings/delegate/users", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

_ALL_END_USER_TOOLS = [
    create_my_request, get_my_request,
    list_my_catalog_entries, get_my_catalog_entry, get_my_catalog_entry_request_fields,
    list_my_catalog_entry_users, get_my_catalog_entry_user_request_fields,
    get_my_settings, update_my_settings, list_my_eligible_delegates,
]

for _fn in _ALL_END_USER_TOOLS:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {fn.__name__: fn for fn in _ALL_END_USER_TOOLS}
