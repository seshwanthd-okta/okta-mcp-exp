# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Authenticator Enrollments, Classification, Linked Objects, OAuth Tokens, and Risk tools."""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.validation import validate_ids


# ── Authenticator Enrollments ──

@validate_ids("user_id")
async def list_authenticator_enrollments(user_id: str, ctx: Context = None) -> list:
    """List all authenticator enrollments for a user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of authenticator enrollment objects.
    """
    logger.info(f"Listing authenticator enrollments for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        enrollments, _, err = await client.list_authenticator_enrollments(user_id)
        if err:
            return [f"Error: {err}"]
        return enrollments if enrollments else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def create_authenticator_enrollment(user_id: str, enrollment_data: dict, ctx: Context = None) -> list:
    """Create an auto-activated Phone authenticator enrollment.

    Parameters:
        user_id (str, required): The ID of the user.
        enrollment_data (dict, required): Enrollment data including phoneNumber and method.

    Returns:
        List containing the created enrollment.
    """
    logger.info(f"Creating authenticator enrollment for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        enrollment, _, err = await client.create_authenticator_enrollment(user_id, enrollment_data)
        if err:
            return [f"Error: {err}"]
        return [enrollment]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def create_tac_authenticator_enrollment(user_id: str, enrollment_data: dict, ctx: Context = None) -> list:
    """Create an auto-activated Temporary access code (TAC) authenticator enrollment.

    Parameters:
        user_id (str, required): The ID of the user.
        enrollment_data (dict, required): TAC enrollment configuration.

    Returns:
        List containing the created TAC enrollment.
    """
    logger.info(f"Creating TAC authenticator enrollment for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        enrollment, _, err = await client.create_tac_authenticator_enrollment(user_id, enrollment_data)
        if err:
            return [f"Error: {err}"]
        return [enrollment]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "enrollment_id")
async def get_authenticator_enrollment(user_id: str, enrollment_id: str, ctx: Context = None) -> list:
    """Retrieve a specific authenticator enrollment.

    Parameters:
        user_id (str, required): The ID of the user.
        enrollment_id (str, required): The ID of the enrollment.

    Returns:
        List containing the enrollment object.
    """
    logger.info(f"Getting enrollment {enrollment_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        enrollment, _, err = await client.get_authenticator_enrollment(user_id, enrollment_id)
        if err:
            return [f"Error: {err}"]
        return [enrollment]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "enrollment_id")
async def delete_authenticator_enrollment(user_id: str, enrollment_id: str, ctx: Context = None) -> list:
    """Delete an authenticator enrollment.

    Parameters:
        user_id (str, required): The ID of the user.
        enrollment_id (str, required): The ID of the enrollment to delete.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting enrollment {enrollment_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_authenticator_enrollment(user_id, enrollment_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Enrollment {enrollment_id} deleted for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


# ── User Classification ──

@validate_ids("user_id")
async def get_user_classification(user_id: str, ctx: Context = None) -> list:
    """Retrieve a user's classification.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List containing the classification object.
    """
    logger.info(f"Getting classification for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        classification, _, err = await client.get_user_classification(user_id)
        if err:
            return [f"Error: {err}"]
        return [classification]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def replace_user_classification(user_id: str, classification_data: dict, ctx: Context = None) -> list:
    """Replace a user's classification.

    Parameters:
        user_id (str, required): The ID of the user.
        classification_data (dict, required): Classification data.

    Returns:
        List containing the updated classification.
    """
    logger.info(f"Replacing classification for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        classification, _, err = await client.replace_user_classification(user_id, classification_data)
        if err:
            return [f"Error: {err}"]
        return [classification]
    except Exception as e:
        return [f"Exception: {e}"]


# ── User Linked Objects ──

@validate_ids("user_id")
async def list_linked_objects_for_user(user_id: str, relationship_name: str, ctx: Context = None) -> list:
    """List the primary or all associated linked object values for a user.

    Parameters:
        user_id (str, required): The ID or login of the user.
        relationship_name (str, required): The name of the relationship.

    Returns:
        List of linked object values.
    """
    logger.info(f"Listing linked objects for user {user_id}, relationship {relationship_name}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        objects, _, err = await client.list_linked_objects_for_user(user_id, relationship_name)
        if err:
            return [f"Error: {err}"]
        return objects if objects else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "primary_user_id")
async def assign_linked_object(user_id: str, primary_relationship_name: str, primary_user_id: str, ctx: Context = None) -> list:
    """Assign a linked object value for primary.

    Parameters:
        user_id (str, required): The ID of the associated user.
        primary_relationship_name (str, required): The primary relationship name.
        primary_user_id (str, required): The ID of the primary user.

    Returns:
        List containing the result.
    """
    logger.info(f"Assigning linked object for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.assign_linked_object_value_for_primary(user_id, primary_relationship_name, primary_user_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Linked object assigned for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def delete_linked_object(user_id: str, relationship_name: str, ctx: Context = None) -> list:
    """Delete a linked object value for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        relationship_name (str, required): The name of the relationship.

    Returns:
        List containing the result.
    """
    logger.info(f"Deleting linked object for user {user_id}, relationship {relationship_name}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.delete_linked_object_for_user(user_id, relationship_name)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Linked object removed for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


# ── User OAuth 2.0 Token Management ──

@validate_ids("user_id", "client_id")
async def list_refresh_tokens_for_client(user_id: str, client_id: str, ctx: Context = None, expand: Optional[str] = None, after: Optional[str] = None, limit: Optional[int] = None) -> list:
    """List all refresh tokens for a user and client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.
        expand (str, optional): Expand related resources.
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum tokens to return.

    Returns:
        List of refresh token objects.
    """
    logger.info(f"Listing refresh tokens for user {user_id} and client {client_id}")
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
        tokens, _, err = await client.list_refresh_tokens_for_user_and_client(user_id, client_id, query_params)
        if err:
            return [f"Error: {err}"]
        return tokens if tokens else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "client_id")
async def revoke_tokens_for_client(user_id: str, client_id: str, ctx: Context = None) -> list:
    """Revoke all refresh tokens for a user and client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.

    Returns:
        List containing the result.
    """
    logger.info(f"Revoking tokens for user {user_id} and client {client_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.revoke_tokens_for_user_and_client(user_id, client_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"All tokens revoked for user {user_id} and client {client_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "client_id", "token_id")
async def get_refresh_token_for_client(user_id: str, client_id: str, token_id: str, ctx: Context = None, expand: Optional[str] = None) -> list:
    """Retrieve a specific refresh token for a user and client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.
        token_id (str, required): The ID of the token.
        expand (str, optional): Expand related resources.

    Returns:
        List containing the token object.
    """
    logger.info(f"Getting token {token_id} for user {user_id} and client {client_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        query_params = {}
        if expand:
            query_params["expand"] = expand
        token, _, err = await client.get_refresh_token_for_user_and_client(user_id, client_id, token_id, query_params)
        if err:
            return [f"Error: {err}"]
        return [token]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "client_id", "token_id")
async def revoke_token_for_client(user_id: str, client_id: str, token_id: str, ctx: Context = None) -> list:
    """Revoke a specific refresh token for a user and client.

    Parameters:
        user_id (str, required): The ID of the user.
        client_id (str, required): The ID of the client.
        token_id (str, required): The ID of the token.

    Returns:
        List containing the result.
    """
    logger.info(f"Revoking token {token_id} for user {user_id} and client {client_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        result = await client.revoke_token_for_user_and_client(user_id, client_id, token_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Token {token_id} revoked for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


# ── User Risk ──

@validate_ids("user_id")
async def get_user_risk(user_id: str, ctx: Context = None) -> list:
    """Retrieve a user's risk level.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List containing the risk object.
    """
    logger.info(f"Getting risk for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        risk, _, err = await client.get_user_risk(user_id)
        if err:
            return [f"Error: {err}"]
        return [risk]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def upsert_user_risk(user_id: str, risk_data: dict, ctx: Context = None) -> list:
    """Upsert a user's risk level.

    Parameters:
        user_id (str, required): The ID of the user.
        risk_data (dict, required): Risk data including riskLevel.

    Returns:
        List containing the updated risk object.
    """
    logger.info(f"Upserting risk for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager
    try:
        client = await get_okta_client(manager)
        risk, _, err = await client.upsert_user_risk(user_id, risk_data)
        if err:
            return [f"Error: {err}"]
        return [risk]
    except Exception as e:
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    list_authenticator_enrollments, create_authenticator_enrollment,
    create_tac_authenticator_enrollment, get_authenticator_enrollment,
    delete_authenticator_enrollment,
    get_user_classification, replace_user_classification,
    list_linked_objects_for_user, assign_linked_object, delete_linked_object,
    list_refresh_tokens_for_client, revoke_tokens_for_client,
    get_refresh_token_for_client, revoke_token_for_client,
    get_user_risk, upsert_user_risk,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "list_authenticator_enrollments": list_authenticator_enrollments,
    "create_authenticator_enrollment": create_authenticator_enrollment,
    "create_tac_authenticator_enrollment": create_tac_authenticator_enrollment,
    "get_authenticator_enrollment": get_authenticator_enrollment,
    "delete_authenticator_enrollment": delete_authenticator_enrollment,
    "get_user_classification": get_user_classification,
    "replace_user_classification": replace_user_classification,
    "list_linked_objects_for_user": list_linked_objects_for_user,
    "assign_linked_object": assign_linked_object,
    "delete_linked_object": delete_linked_object,
    "list_refresh_tokens_for_client": list_refresh_tokens_for_client,
    "revoke_tokens_for_client": revoke_tokens_for_client,
    "get_refresh_token_for_client": get_refresh_token_for_client,
    "revoke_token_for_client": revoke_token_for_client,
    "get_user_risk": get_user_risk,
    "upsert_user_risk": upsert_user_risk,
}
