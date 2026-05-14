# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""Governance API tools for the Okta MCP server.

Covers all Okta Identity Governance (OIG) admin APIs:
 - Request Conditions
 - Requests
 - Catalogs
 - Campaigns
 - Reviews
 - Entitlements & Values
 - Entitlement Bundles
 - Collections & Assignments
 - Grants
 - Principal Entitlements
 - Principal Access
 - Labels & Resource Labels
 - Resource Owners
 - Principal Settings
 - Delegates

These APIs use the /governance/api/ base path and are accessed via the
Okta SDK request executor (raw HTTP) since the SDK does not provide
dedicated client methods for most governance endpoints.
"""

import json
from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.elicitation import DeleteConfirmation, elicit_or_fallback
from okta_mcp_server.utils.validation import validate_ids


# ─── helpers ───

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
#  REQUEST CONDITIONS
# ═══════════════════════════════════════════════════════════════

@validate_ids("resource_id")
async def list_request_conditions(resource_id: str, ctx: Context = None) -> list:
    """List all resource request conditions.

    Parameters:
        resource_id (str, required): The ID of the resource.

    Returns:
        List of request condition objects.
    """
    logger.info(f"Listing request conditions for resource {resource_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/resources/{resource_id}/request-conditions")
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id")
async def create_request_condition(resource_id: str, condition_data: dict, ctx: Context = None) -> list:
    """Create a request condition for a resource.

    Parameters:
        resource_id (str, required): The ID of the resource.
        condition_data (dict, required): The request condition configuration.

    Returns:
        List containing the created request condition.
    """
    logger.info(f"Creating request condition for resource {resource_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v2/resources/{resource_id}/request-conditions", body=condition_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Request condition created for resource {resource_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id", "request_condition_id")
async def get_request_condition(resource_id: str, request_condition_id: str, ctx: Context = None) -> list:
    """Retrieve a specific resource request condition.

    Parameters:
        resource_id (str, required): The ID of the resource.
        request_condition_id (str, required): The ID of the request condition.

    Returns:
        List containing the request condition object.
    """
    logger.info(f"Getting request condition {request_condition_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/resources/{resource_id}/request-conditions/{request_condition_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id", "request_condition_id")
async def delete_request_condition(resource_id: str, request_condition_id: str, ctx: Context = None) -> list:
    """Delete a request condition.

    Parameters:
        resource_id (str, required): The ID of the resource.
        request_condition_id (str, required): The ID of the request condition.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting request condition {request_condition_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete request condition {request_condition_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v2/resources/{resource_id}/request-conditions/{request_condition_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Request condition {request_condition_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id", "request_condition_id")
async def update_request_condition(resource_id: str, request_condition_id: str, condition_data: dict, ctx: Context = None) -> list:
    """Update a request condition (partial update).

    Parameters:
        resource_id (str, required): The ID of the resource.
        request_condition_id (str, required): The ID of the request condition.
        condition_data (dict, required): Partial update data.

    Returns:
        List containing the updated request condition.
    """
    logger.info(f"Updating request condition {request_condition_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v2/resources/{resource_id}/request-conditions/{request_condition_id}", body=condition_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Request condition {request_condition_id} updated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id", "request_condition_id")
async def activate_request_condition(resource_id: str, request_condition_id: str, ctx: Context = None) -> list:
    """Activate a request condition.

    Parameters:
        resource_id (str, required): The ID of the resource.
        request_condition_id (str, required): The ID of the request condition.

    Returns:
        List containing the result.
    """
    logger.info(f"Activating request condition {request_condition_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v2/resources/{resource_id}/request-conditions/{request_condition_id}/activate")
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Request condition {request_condition_id} activated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("resource_id", "request_condition_id")
async def deactivate_request_condition(resource_id: str, request_condition_id: str, ctx: Context = None) -> list:
    """Deactivate a request condition.

    Parameters:
        resource_id (str, required): The ID of the resource.
        request_condition_id (str, required): The ID of the request condition.

    Returns:
        List containing the result.
    """
    logger.info(f"Deactivating request condition {request_condition_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v2/resources/{resource_id}/request-conditions/{request_condition_id}/deactivate")
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Request condition {request_condition_id} deactivated."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  REQUESTS
# ═══════════════════════════════════════════════════════════════

async def list_governance_requests(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all governance requests.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.
        order_by (str, optional): Ordering expression.

    Returns:
        List of governance request objects.
    """
    logger.info("Listing governance requests")
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
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", "/governance/api/v2/requests", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


async def create_governance_request(request_data: dict, ctx: Context = None) -> list:
    """Create a governance request.

    Parameters:
        request_data (dict, required): The governance request configuration.

    Returns:
        List containing the created request.
    """
    logger.info("Creating governance request")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v2/requests", body=request_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Governance request created."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("request_id")
async def get_governance_request(request_id: str, ctx: Context = None) -> list:
    """Retrieve a governance request.

    Parameters:
        request_id (str, required): The ID of the request.

    Returns:
        List containing the request object.
    """
    logger.info(f"Getting governance request {request_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/requests/{request_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("request_id")
async def create_governance_request_message(request_id: str, message_data: dict, ctx: Context = None) -> list:
    """Create a message for a governance request.

    Parameters:
        request_id (str, required): The ID of the request.
        message_data (dict, required): The message content.

    Returns:
        List containing the created message.
    """
    logger.info(f"Creating message for request {request_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v2/requests/{request_id}/messages", body=message_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Message created."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  CATALOGS
# ═══════════════════════════════════════════════════════════════

async def list_catalog_entries(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    match: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """List all entries for the default access request catalog.

    Parameters:
        filter (str, optional): Filter expression. Defaults to 'type sw "APP"' if not provided.
            The Okta API requires a filter parameter on this endpoint.
        after (str, optional): Pagination cursor.
        match (str, optional): Match expression.
        limit (int, optional): Maximum results per page.

    Returns:
        List of catalog entry objects.
    """
    logger.info("Listing catalog entries")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        # The Okta API requires a filter parameter on catalog endpoints
        qp["filter"] = filter if filter else 'type sw "APP"'
        if after:
            qp["after"] = after
        if match:
            qp["match"] = match
        if limit:
            qp["limit"] = limit
        data, err = await _gov_request(client, "GET", "/governance/api/v2/catalogs/default/entries", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id")
async def get_catalog_entry(entry_id: str, ctx: Context = None) -> list:
    """Retrieve a catalog entry.

    Parameters:
        entry_id (str, required): The ID of the catalog entry.

    Returns:
        List containing the catalog entry object.
    """
    logger.info(f"Getting catalog entry {entry_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/catalogs/default/entries/{entry_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_catalog_entries_for_user(
    user_id: str,
    ctx: Context = None,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    match: Optional[str] = None,
    limit: Optional[int] = None,
) -> list:
    """List all access request catalog entries for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        filter (str, optional): Filter expression. Defaults to 'type sw "APP"' if not provided.
            The Okta API requires a filter parameter on this endpoint.
        after (str, optional): Pagination cursor.
        match (str, optional): Match expression.
        limit (int, optional): Maximum results per page.

    Returns:
        List of catalog entry objects.
    """
    logger.info(f"Listing catalog entries for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        # The Okta API requires a filter parameter on catalog endpoints
        qp["filter"] = filter if filter else 'type sw "APP"'
        if after:
            qp["after"] = after
        if match:
            qp["match"] = match
        if limit:
            qp["limit"] = limit
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/catalogs/default/user/{user_id}/entries", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entry_id", "user_id")
async def get_catalog_entry_request_fields(entry_id: str, user_id: str, ctx: Context = None) -> list:
    """Retrieve the request fields for a catalog entry and user.

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
        data, err = await _gov_request(client, "GET", f"/governance/api/v2/catalogs/default/entries/{entry_id}/users/{user_id}/request-fields")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  CAMPAIGNS
# ═══════════════════════════════════════════════════════════════

async def create_campaign(campaign_data: dict, ctx: Context = None) -> list:
    """Create a campaign.

    Parameters:
        campaign_data (dict, required): Campaign configuration.

    Returns:
        List containing the created campaign.
    """
    logger.info("Creating campaign")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/campaigns", body=campaign_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Campaign created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_campaigns(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all campaigns.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.
        order_by (str, optional): Ordering expression.

    Returns:
        List of campaign objects.
    """
    logger.info("Listing campaigns")
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
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", "/governance/api/v1/campaigns", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("campaign_id")
async def get_campaign(campaign_id: str, ctx: Context = None) -> list:
    """Retrieve a campaign.

    Parameters:
        campaign_id (str, required): The ID of the campaign.

    Returns:
        List containing the campaign object.
    """
    logger.info(f"Getting campaign {campaign_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/campaigns/{campaign_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("campaign_id")
async def delete_campaign(campaign_id: str, ctx: Context = None) -> list:
    """Delete a campaign.

    Parameters:
        campaign_id (str, required): The ID of the campaign.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting campaign {campaign_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete campaign {campaign_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/campaigns/{campaign_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Campaign {campaign_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("campaign_id")
async def launch_campaign(campaign_id: str, ctx: Context = None) -> list:
    """Launch a campaign.

    Parameters:
        campaign_id (str, required): The ID of the campaign.

    Returns:
        List containing the result.
    """
    logger.info(f"Launching campaign {campaign_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v1/campaigns/{campaign_id}/launch")
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Campaign {campaign_id} launched."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("campaign_id")
async def end_campaign(campaign_id: str, ctx: Context = None) -> list:
    """End a campaign.

    Parameters:
        campaign_id (str, required): The ID of the campaign.

    Returns:
        List containing the result.
    """
    logger.info(f"Ending campaign {campaign_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v1/campaigns/{campaign_id}/end")
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Campaign {campaign_id} ended."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  REVIEWS
# ═══════════════════════════════════════════════════════════════

async def list_reviews(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all reviews.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.
        order_by (str, optional): Ordering expression.

    Returns:
        List of review objects.
    """
    logger.info("Listing reviews")
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
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", "/governance/api/v1/reviews", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("campaign_id")
async def reassign_reviews(campaign_id: str, reassignment_data: dict, ctx: Context = None) -> list:
    """Reassign reviews for a campaign.

    Parameters:
        campaign_id (str, required): The ID of the campaign.
        reassignment_data (dict, required): Reassignment configuration.

    Returns:
        List containing the result.
    """
    logger.info(f"Reassigning reviews for campaign {campaign_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v1/campaigns/{campaign_id}/reviews/reassign", body=reassignment_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Reviews reassigned."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("review_id")
async def get_review(review_id: str, ctx: Context = None) -> list:
    """Retrieve a review.

    Parameters:
        review_id (str, required): The ID of the review.

    Returns:
        List containing the review object.
    """
    logger.info(f"Getting review {review_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/reviews/{review_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  ENTITLEMENTS
# ═══════════════════════════════════════════════════════════════

async def create_entitlement(entitlement_data: dict, ctx: Context = None) -> list:
    """Create an entitlement.

    Parameters:
        entitlement_data (dict, required): Entitlement definition.

    Returns:
        List containing the created entitlement.
    """
    logger.info("Creating entitlement")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/entitlements", body=entitlement_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Entitlement created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_entitlements(
    ctx: Context,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    filter: Optional[str] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all entitlements.

    Parameters:
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        filter (str, optional): Filter expression.
        order_by (str, optional): Ordering expression.

    Returns:
        List of entitlement objects.
    """
    logger.info("Listing entitlements")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if filter:
            qp["filter"] = filter
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", "/governance/api/v1/entitlements", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id")
async def delete_entitlement(entitlement_id: str, ctx: Context = None) -> list:
    """Delete an entitlement.

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting entitlement {entitlement_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete entitlement {entitlement_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/entitlements/{entitlement_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Entitlement {entitlement_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id")
async def get_entitlement(entitlement_id: str, ctx: Context = None) -> list:
    """Retrieve an entitlement.

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.

    Returns:
        List containing the entitlement object.
    """
    logger.info(f"Getting entitlement {entitlement_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/entitlements/{entitlement_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id")
async def replace_entitlement(entitlement_id: str, entitlement_data: dict, ctx: Context = None) -> list:
    """Replace an entitlement.

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.
        entitlement_data (dict, required): Full entitlement data.

    Returns:
        List containing the updated entitlement.
    """
    logger.info(f"Replacing entitlement {entitlement_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PUT", f"/governance/api/v1/entitlements/{entitlement_id}", body=entitlement_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Entitlement {entitlement_id} replaced."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id")
async def update_entitlement(entitlement_id: str, entitlement_data: dict, ctx: Context = None) -> list:
    """Update an entitlement (partial update).

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.
        entitlement_data (dict, required): Partial update data.

    Returns:
        List containing the updated entitlement.
    """
    logger.info(f"Updating entitlement {entitlement_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v1/entitlements/{entitlement_id}", body=entitlement_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Entitlement {entitlement_id} updated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id")
async def list_entitlement_values(
    entitlement_id: str,
    ctx: Context = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    filter: Optional[str] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all values for an entitlement.

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        filter (str, optional): Filter expression.
        order_by (str, optional): Ordering expression.

    Returns:
        List of entitlement value objects.
    """
    logger.info(f"Listing values for entitlement {entitlement_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if filter:
            qp["filter"] = filter
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/entitlements/{entitlement_id}/values", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("entitlement_id", "value_id")
async def get_entitlement_value(entitlement_id: str, value_id: str, ctx: Context = None) -> list:
    """Retrieve a specific entitlement value.

    Parameters:
        entitlement_id (str, required): The ID of the entitlement.
        value_id (str, required): The ID of the value.

    Returns:
        List containing the entitlement value.
    """
    logger.info(f"Getting entitlement value {value_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/entitlements/{entitlement_id}/values/{value_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_all_entitlement_values(
    ctx: Context,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    filter: Optional[str] = None,
    order_by: Optional[str] = None,
) -> list:
    """List all entitlement values across all entitlements.

    Parameters:
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        filter (str, optional): Filter expression.
        order_by (str, optional): Ordering expression.

    Returns:
        List of entitlement value objects.
    """
    logger.info("Listing all entitlement values")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if filter:
            qp["filter"] = filter
        if order_by:
            qp["orderBy"] = order_by
        data, err = await _gov_request(client, "GET", "/governance/api/v1/entitlements/values", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  ENTITLEMENT BUNDLES
# ═══════════════════════════════════════════════════════════════

async def create_entitlement_bundle(bundle_data: dict, ctx: Context = None) -> list:
    """Create an entitlement bundle.

    Parameters:
        bundle_data (dict, required): Bundle definition.

    Returns:
        List containing the created bundle.
    """
    logger.info("Creating entitlement bundle")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/entitlement-bundles", body=bundle_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Entitlement bundle created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_entitlement_bundles(
    ctx: Context,
    filter: Optional[str] = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
    include: Optional[str] = None,
) -> list:
    """List all entitlement bundles.

    Parameters:
        filter (str, optional): Filter expression.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.
        order_by (str, optional): Ordering expression.
        include (str, optional): Related resources to include.

    Returns:
        List of entitlement bundle objects.
    """
    logger.info("Listing entitlement bundles")
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
        if order_by:
            qp["orderBy"] = order_by
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", "/governance/api/v1/entitlement-bundles", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("bundle_id")
async def get_entitlement_bundle(bundle_id: str, ctx: Context = None, include: Optional[str] = None) -> list:
    """Retrieve an entitlement bundle.

    Parameters:
        bundle_id (str, required): The ID of the bundle.
        include (str, optional): Related resources to include.

    Returns:
        List containing the bundle object.
    """
    logger.info(f"Getting entitlement bundle {bundle_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/entitlement-bundles/{bundle_id}", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("bundle_id")
async def replace_entitlement_bundle(bundle_id: str, bundle_data: dict, ctx: Context = None) -> list:
    """Replace an entitlement bundle.

    Parameters:
        bundle_id (str, required): The ID of the bundle.
        bundle_data (dict, required): Full bundle data.

    Returns:
        List containing the updated bundle.
    """
    logger.info(f"Replacing entitlement bundle {bundle_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PUT", f"/governance/api/v1/entitlement-bundles/{bundle_id}", body=bundle_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Bundle {bundle_id} replaced."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("bundle_id")
async def delete_entitlement_bundle(bundle_id: str, ctx: Context = None) -> list:
    """Delete an entitlement bundle.

    Parameters:
        bundle_id (str, required): The ID of the bundle.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting entitlement bundle {bundle_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete entitlement bundle {bundle_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/entitlement-bundles/{bundle_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Entitlement bundle {bundle_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  COLLECTIONS
# ═══════════════════════════════════════════════════════════════

async def create_collection(collection_data: dict, ctx: Context = None) -> list:
    """Create a resource collection.

    Parameters:
        collection_data (dict, required): Collection definition.

    Returns:
        List containing the created collection.
    """
    logger.info("Creating collection")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/collections", body=collection_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Collection created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_collections(
    ctx: Context,
    include: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    filter: Optional[str] = None,
) -> list:
    """List all resource collections.

    Parameters:
        include (str, optional): Related resources to include.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        filter (str, optional): Filter expression.

    Returns:
        List of collection objects.
    """
    logger.info("Listing collections")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if include:
            qp["include"] = include
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if filter:
            qp["filter"] = filter
        data, err = await _gov_request(client, "GET", "/governance/api/v1/collections", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def get_collection(collection_id: str, ctx: Context = None) -> list:
    """Retrieve a resource collection.

    Parameters:
        collection_id (str, required): The ID of the collection.

    Returns:
        List containing the collection object.
    """
    logger.info(f"Getting collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/collections/{collection_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def replace_collection(collection_id: str, collection_data: dict, ctx: Context = None) -> list:
    """Replace a resource collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        collection_data (dict, required): Full collection data.

    Returns:
        List containing the updated collection.
    """
    logger.info(f"Replacing collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PUT", f"/governance/api/v1/collections/{collection_id}", body=collection_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Collection {collection_id} replaced."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def delete_collection(collection_id: str, ctx: Context = None) -> list:
    """Delete a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting collection {collection_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete collection {collection_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/collections/{collection_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Collection {collection_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def list_collection_resources(
    collection_id: str,
    ctx: Context = None,
    include: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all resources in a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        include (str, optional): Related resources to include.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of collection resource objects.
    """
    logger.info(f"Listing resources for collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if include:
            qp["include"] = include
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/collections/{collection_id}/resources", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def add_collection_resources(collection_id: str, resources_data: dict, ctx: Context = None) -> list:
    """Add resources to a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        resources_data (dict, required): Resources to add.

    Returns:
        List containing the result.
    """
    logger.info(f"Adding resources to collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v1/collections/{collection_id}/resources", body=resources_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Resources added."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id", "resource_id")
async def delete_collection_resource(collection_id: str, resource_id: str, ctx: Context = None) -> list:
    """Delete a resource from a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        resource_id (str, required): The ID of the resource.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting resource {resource_id} from collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/collections/{collection_id}/resources/{resource_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Resource {resource_id} removed from collection {collection_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id", "resource_id")
async def get_collection_resource(collection_id: str, resource_id: str, ctx: Context = None) -> list:
    """Retrieve a specific collection resource.

    Parameters:
        collection_id (str, required): The ID of the collection.
        resource_id (str, required): The ID of the resource.

    Returns:
        List containing the resource object.
    """
    logger.info(f"Getting resource {resource_id} from collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/collections/{collection_id}/resources/{resource_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id", "resource_id")
async def replace_collection_resource(collection_id: str, resource_id: str, resource_data: dict, ctx: Context = None) -> list:
    """Replace a collection resource.

    Parameters:
        collection_id (str, required): The ID of the collection.
        resource_id (str, required): The ID of the resource.
        resource_data (dict, required): Full resource data.

    Returns:
        List containing the updated resource.
    """
    logger.info(f"Replacing resource {resource_id} in collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PUT", f"/governance/api/v1/collections/{collection_id}/resources/{resource_id}", body=resource_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Resource {resource_id} replaced."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def list_collection_unassigned_users(
    collection_id: str,
    ctx: Context = None,
    filter: Optional[str] = None,
) -> list:
    """Retrieve unassigned users for a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        filter (str, optional): Filter expression.

    Returns:
        List of unassigned user objects.
    """
    logger.info(f"Listing unassigned users for collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/collections/{collection_id}/catalog/users", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def list_collection_assignments(
    collection_id: str,
    ctx: Context = None,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all assignments for a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of assignment objects.
    """
    logger.info(f"Listing assignments for collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/collections/{collection_id}/assignments", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id")
async def assign_collection_to_principals(collection_id: str, assignment_data: dict, ctx: Context = None) -> list:
    """Assign a collection to principals.

    Parameters:
        collection_id (str, required): The ID of the collection.
        assignment_data (dict, required): Assignment configuration.

    Returns:
        List containing the result.
    """
    logger.info(f"Assigning collection {collection_id} to principals")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", f"/governance/api/v1/collections/{collection_id}/assignments", body=assignment_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Assignment created."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id", "assignment_id")
async def update_collection_assignment(collection_id: str, assignment_id: str, assignment_data: dict, ctx: Context = None) -> list:
    """Update a principal assignment for a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        assignment_id (str, required): The ID of the assignment.
        assignment_data (dict, required): Partial update data.

    Returns:
        List containing the updated assignment.
    """
    logger.info(f"Updating assignment {assignment_id} for collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v1/collections/{collection_id}/assignments/{assignment_id}", body=assignment_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Assignment {assignment_id} updated."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("collection_id", "assignment_id")
async def delete_collection_assignment(collection_id: str, assignment_id: str, ctx: Context = None) -> list:
    """Delete a principal assignment from a collection.

    Parameters:
        collection_id (str, required): The ID of the collection.
        assignment_id (str, required): The ID of the assignment.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting assignment {assignment_id} from collection {collection_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/collections/{collection_id}/assignments/{assignment_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Assignment {assignment_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_all_collection_assignments(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all assignments for all collections.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of assignment objects.
    """
    logger.info("Listing all collection assignments")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", "/governance/api/v1/collections/assignments", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  GRANTS
# ═══════════════════════════════════════════════════════════════

async def create_grant(grant_data: dict, ctx: Context = None) -> list:
    """Create a grant.

    Parameters:
        grant_data (dict, required): Grant definition.

    Returns:
        List containing the created grant.
    """
    logger.info("Creating grant")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/grants", body=grant_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Grant created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_grants(
    ctx: Context,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    filter: Optional[str] = None,
    include: Optional[str] = None,
) -> list:
    """List all grants.

    Parameters:
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum results per page.
        filter (str, optional): Filter expression.
        include (str, optional): Related resources to include.

    Returns:
        List of grant objects.
    """
    logger.info("Listing grants")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if after:
            qp["after"] = after
        if limit:
            qp["limit"] = limit
        if filter:
            qp["filter"] = filter
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", "/governance/api/v1/grants", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("grant_id")
async def get_grant(grant_id: str, ctx: Context = None, include: Optional[str] = None) -> list:
    """Retrieve a grant.

    Parameters:
        grant_id (str, required): The ID of the grant.
        include (str, optional): Related resources to include.

    Returns:
        List containing the grant object.
    """
    logger.info(f"Getting grant {grant_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/grants/{grant_id}", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("grant_id")
async def replace_grant(grant_id: str, grant_data: dict, ctx: Context = None) -> list:
    """Replace a grant.

    Parameters:
        grant_id (str, required): The ID of the grant.
        grant_data (dict, required): Full grant data.

    Returns:
        List containing the updated grant.
    """
    logger.info(f"Replacing grant {grant_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PUT", f"/governance/api/v1/grants/{grant_id}", body=grant_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Grant {grant_id} replaced."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("grant_id")
async def update_grant(grant_id: str, grant_data: dict, ctx: Context = None) -> list:
    """Update a grant (partial update).

    Parameters:
        grant_id (str, required): The ID of the grant.
        grant_data (dict, required): Partial update data.

    Returns:
        List containing the updated grant.
    """
    logger.info(f"Updating grant {grant_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v1/grants/{grant_id}", body=grant_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Grant {grant_id} updated."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  PRINCIPAL ENTITLEMENTS
# ═══════════════════════════════════════════════════════════════

async def list_principal_entitlements(
    ctx: Context,
    filter: Optional[str] = None,
) -> list:
    """Retrieve the principal's effective entitlements for a resource.

    Parameters:
        filter (str, optional): Filter expression.

    Returns:
        List of principal entitlement objects.
    """
    logger.info("Listing principal entitlements")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        data, err = await _gov_request(client, "GET", "/governance/api/v1/principal-entitlements", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("change_id")
async def get_principal_entitlement_changes(change_id: str, ctx: Context = None) -> list:
    """Retrieve principal entitlement changes.

    Parameters:
        change_id (str, required): The ID of the principal entitlements change.

    Returns:
        List containing the changes object.
    """
    logger.info(f"Getting principal entitlement changes {change_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/principal-entitlements-changes/{change_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_entitlement_history(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    include: Optional[str] = None,
) -> list:
    """Retrieve entitlement history.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        include (str, optional): Related resources to include.

    Returns:
        List of entitlement history entries.
    """
    logger.info("Listing entitlement history")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", "/governance/api/v1/principal-entitlements/history", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  PRINCIPAL ACCESS (V2)
# ═══════════════════════════════════════════════════════════════

async def revoke_principal_access(revocation_data: dict, ctx: Context = None) -> list:
    """Revoke a principal's access.

    Parameters:
        revocation_data (dict, required): Revocation configuration.

    Returns:
        List containing the result.
    """
    logger.info("Revoking principal access")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v2/revoke-principal-access", body=revocation_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Principal access revoked."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  LABELS
# ═══════════════════════════════════════════════════════════════

async def create_label(label_data: dict, ctx: Context = None) -> list:
    """Create a label.

    Parameters:
        label_data (dict, required): Label definition.

    Returns:
        List containing the created label.
    """
    logger.info("Creating label")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/labels", body=label_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Label created."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_labels(ctx: Context, filter: Optional[str] = None) -> list:
    """List all labels.

    Parameters:
        filter (str, optional): Filter expression.

    Returns:
        List of label objects.
    """
    logger.info("Listing labels")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        data, err = await _gov_request(client, "GET", "/governance/api/v1/labels", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("label_id")
async def delete_label(label_id: str, ctx: Context = None) -> list:
    """Delete a label.

    Parameters:
        label_id (str, required): The ID of the label.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting label {label_id}")
    outcome = await elicit_or_fallback(ctx, message=f"Delete label {label_id}?", schema=DeleteConfirmation, auto_confirm_on_fallback=True)
    if not outcome.confirmed:
        return [{"message": "Deletion cancelled."}]
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        _, err = await _gov_request(client, "DELETE", f"/governance/api/v1/labels/{label_id}")
        if err:
            return [f"Error: {err}"]
        return [f"Label {label_id} deleted."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("label_id")
async def get_label(label_id: str, ctx: Context = None) -> list:
    """Retrieve a label.

    Parameters:
        label_id (str, required): The ID of the label.

    Returns:
        List containing the label object.
    """
    logger.info(f"Getting label {label_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "GET", f"/governance/api/v1/labels/{label_id}")
        if err:
            return [f"Error: {err}"]
        return [data]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("label_id")
async def update_label(label_id: str, label_data: dict, ctx: Context = None) -> list:
    """Update a label (partial update).

    Parameters:
        label_id (str, required): The ID of the label.
        label_data (dict, required): Partial update data.

    Returns:
        List containing the updated label.
    """
    logger.info(f"Updating label {label_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v1/labels/{label_id}", body=label_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Label {label_id} updated."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_labeled_resources(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all labeled resources.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of labeled resource objects.
    """
    logger.info("Listing labeled resources")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", "/governance/api/v1/resource-labels", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


async def assign_labels_to_resources(assignment_data: dict, ctx: Context = None) -> list:
    """Assign labels to resources.

    Parameters:
        assignment_data (dict, required): Label assignment configuration.

    Returns:
        List containing the result.
    """
    logger.info("Assigning labels to resources")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/resource-labels/assign", body=assignment_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Labels assigned."]
    except Exception as e:
        return [f"Exception: {e}"]


async def remove_labels_from_resources(removal_data: dict, ctx: Context = None) -> list:
    """Remove labels from resources.

    Parameters:
        removal_data (dict, required): Label removal configuration.

    Returns:
        List containing the result.
    """
    logger.info("Removing labels from resources")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/resource-labels/unassign", body=removal_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Labels removed."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  RESOURCE OWNERS
# ═══════════════════════════════════════════════════════════════

async def configure_resource_owners(owner_data: dict, ctx: Context = None) -> list:
    """Configure resource owners.

    Parameters:
        owner_data (dict, required): Resource owner configuration.

    Returns:
        List containing the result.
    """
    logger.info("Configuring resource owners")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "POST", "/governance/api/v1/resource-owners", body=owner_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Resource owners configured."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_resources_with_owners(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
    include: Optional[str] = None,
) -> list:
    """List all resources with owners.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.
        include (str, optional): Related resources to include.

    Returns:
        List of resource owner objects.
    """
    logger.info("Listing resources with owners")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        if include:
            qp["include"] = include
        data, err = await _gov_request(client, "GET", "/governance/api/v1/resource-owners", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


async def update_resource_owner(owner_data: dict, ctx: Context = None) -> list:
    """Update a resource owner.

    Parameters:
        owner_data (dict, required): Partial update data.

    Returns:
        List containing the result.
    """
    logger.info("Updating resource owner")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", "/governance/api/v1/resource-owners", body=owner_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else ["Resource owner updated."]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_resources_without_owners(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all resources without owners.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of resource objects.
    """
    logger.info("Listing resources without owners")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", "/governance/api/v1/resource-owners/catalog/resources", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  PRINCIPAL SETTINGS
# ═══════════════════════════════════════════════════════════════

@validate_ids("principal_id")
async def update_principal_settings(principal_id: str, settings_data: dict, ctx: Context = None) -> list:
    """Update principal settings.

    Parameters:
        principal_id (str, required): The ID of the target principal.
        settings_data (dict, required): Partial update data.

    Returns:
        List containing the result.
    """
    logger.info(f"Updating principal settings for {principal_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        data, err = await _gov_request(client, "PATCH", f"/governance/api/v1/principal-settings/{principal_id}", body=settings_data)
        if err:
            return [f"Error: {err}"]
        return [data] if data else [f"Principal settings updated for {principal_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


# ═══════════════════════════════════════════════════════════════
#  DELEGATES
# ═══════════════════════════════════════════════════════════════

async def list_delegates(
    ctx: Context,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    after: Optional[str] = None,
) -> list:
    """List all delegate appointments.

    Parameters:
        filter (str, optional): Filter expression.
        limit (int, optional): Maximum results per page.
        after (str, optional): Pagination cursor.

    Returns:
        List of delegate appointment objects.
    """
    logger.info("Listing delegates")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        qp = {}
        if filter:
            qp["filter"] = filter
        if limit:
            qp["limit"] = limit
        if after:
            qp["after"] = after
        data, err = await _gov_request(client, "GET", "/governance/api/v1/delegates", query_params=qp)
        if err:
            return [f"Error: {err}"]
        return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

_ALL_GOVERNANCE_TOOLS = [
    # Request Conditions
    list_request_conditions, create_request_condition, get_request_condition,
    delete_request_condition, update_request_condition, activate_request_condition,
    deactivate_request_condition,
    # Requests
    list_governance_requests, create_governance_request, get_governance_request,
    create_governance_request_message,
    # Catalogs
    list_catalog_entries, get_catalog_entry, list_catalog_entries_for_user,
    get_catalog_entry_request_fields,
    # Campaigns
    create_campaign, list_campaigns, get_campaign, delete_campaign,
    launch_campaign, end_campaign,
    # Reviews
    list_reviews, reassign_reviews, get_review,
    # Entitlements
    create_entitlement, list_entitlements, delete_entitlement, get_entitlement,
    replace_entitlement, update_entitlement, list_entitlement_values,
    get_entitlement_value, list_all_entitlement_values,
    # Entitlement Bundles
    create_entitlement_bundle, list_entitlement_bundles, get_entitlement_bundle,
    replace_entitlement_bundle, delete_entitlement_bundle,
    # Collections
    create_collection, list_collections, get_collection, replace_collection,
    delete_collection, list_collection_resources, add_collection_resources,
    delete_collection_resource, get_collection_resource, replace_collection_resource,
    list_collection_unassigned_users, list_collection_assignments,
    assign_collection_to_principals, update_collection_assignment,
    delete_collection_assignment, list_all_collection_assignments,
    # Grants
    create_grant, list_grants, get_grant, replace_grant, update_grant,
    # Principal Entitlements
    list_principal_entitlements, get_principal_entitlement_changes, list_entitlement_history,
    # Principal Access
    revoke_principal_access,
    # Labels
    create_label, list_labels, delete_label, get_label, update_label,
    list_labeled_resources, assign_labels_to_resources, remove_labels_from_resources,
    # Resource Owners
    configure_resource_owners, list_resources_with_owners, update_resource_owner,
    list_resources_without_owners,
    # Principal Settings
    update_principal_settings,
    # Delegates
    list_delegates,
]

for _fn in _ALL_GOVERNANCE_TOOLS:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {fn.__name__: fn for fn in _ALL_GOVERNANCE_TOOLS}
