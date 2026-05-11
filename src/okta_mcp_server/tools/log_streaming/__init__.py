# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Log Streaming tools for the Okta MCP server."""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.pagination import create_paginated_response, paginate_all_results
from okta_mcp_server.utils.validation import validate_ids


async def list_log_streams(
    ctx: Context,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    filter: Optional[str] = None,
    fetch_all: bool = False,
) -> dict:
    """List all log streams.

    Parameters:
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum number per page.
        filter (str, optional): Filter expression.
        fetch_all (bool, optional): Fetch all pages. Default: False.

    Returns:
        Dict containing list of log stream objects.
    """
    logger.info("Listing log streams")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        query_params = {}
        if after:
            query_params["after"] = after
        if limit:
            query_params["limit"] = limit
        if filter:
            query_params["filter"] = filter
        streams, response, err = await client.list_log_streams(query_params)
        if err:
            return {"error": f"Error: {err}"}
        if not streams:
            return create_paginated_response([], response, fetch_all)
        if fetch_all and response and hasattr(response, "has_next") and response.has_next():
            all_streams, pagination_info = await paginate_all_results(response, streams)
            return create_paginated_response(all_streams, response, fetch_all_used=True, pagination_info=pagination_info)
        return create_paginated_response(streams, response, fetch_all_used=fetch_all)
    except Exception as e:
        return {"error": f"Exception: {e}"}


async def create_log_stream(stream_data: dict, ctx: Context = None) -> list:
    """Create a new log stream.

    Parameters:
        stream_data (dict, required): Log stream configuration including type and settings.

    Returns:
        List containing the created log stream.
    """
    logger.info("Creating log stream")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        stream, _, err = await client.create_log_stream(stream_data)
        if err:
            return [f"Error: {err}"]
        return [stream]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("stream_id")
async def get_log_stream(stream_id: str, ctx: Context = None) -> list:
    """Retrieve a specific log stream.

    Parameters:
        stream_id (str, required): The ID of the log stream.

    Returns:
        List containing the log stream object.
    """
    logger.info(f"Getting log stream {stream_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        stream, _, err = await client.get_log_stream(stream_id)
        if err:
            return [f"Error: {err}"]
        return [stream]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("stream_id")
async def replace_log_stream(stream_id: str, stream_data: dict, ctx: Context = None) -> list:
    """Replace a log stream.

    Parameters:
        stream_id (str, required): The ID of the log stream.
        stream_data (dict, required): Updated log stream configuration.

    Returns:
        List containing the updated log stream.
    """
    logger.info(f"Replacing log stream {stream_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        stream, _, err = await client.replace_log_stream(stream_id, stream_data)
        if err:
            return [f"Error: {err}"]
        return [stream]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("stream_id")
async def delete_log_stream(stream_id: str, ctx: Context = None) -> list:
    """Delete a log stream.

    Parameters:
        stream_id (str, required): The ID of the log stream.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting log stream {stream_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete log stream {stream_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_log_stream(stream_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Log stream {stream_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("stream_id")
async def activate_log_stream(stream_id: str, ctx: Context = None) -> list:
    """Activate a log stream.

    Parameters:
        stream_id (str, required): The ID of the log stream.

    Returns:
        List containing the result.
    """
    logger.info(f"Activating log stream {stream_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        stream, _, err = await client.activate_log_stream(stream_id)
        if err:
            return [f"Error: {err}"]
        return [stream]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("stream_id")
async def deactivate_log_stream(stream_id: str, ctx: Context = None) -> list:
    """Deactivate a log stream.

    Parameters:
        stream_id (str, required): The ID of the log stream.

    Returns:
        List containing the result.
    """
    logger.info(f"Deactivating log stream {stream_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        stream, _, err = await client.deactivate_log_stream(stream_id)
        if err:
            return [f"Error: {err}"]
        return [stream]
    except Exception as e:
        return [f"Exception: {e}"]


for _fn in [list_log_streams, create_log_stream, get_log_stream, replace_log_stream, delete_log_stream, activate_log_stream, deactivate_log_stream]:
    mcp.tool()(_fn)

ENGINE_ACTIONS = {
    "list_log_streams": list_log_streams,
    "create_log_stream": create_log_stream,
    "get_log_stream": get_log_stream,
    "replace_log_stream": replace_log_stream,
    "delete_log_stream": delete_log_stream,
    "activate_log_stream": activate_log_stream,
    "deactivate_log_stream": deactivate_log_stream,
}
