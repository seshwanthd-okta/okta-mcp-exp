# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Factors tools for the Okta MCP server.

Provides operations to manage user MFA factors:
    - list_factors                  GET    /api/v1/users/{userId}/factors
    - enroll_factor                 POST   /api/v1/users/{userId}/factors
    - list_supported_factors        GET    /api/v1/users/{userId}/factors/catalog
    - list_supported_security_questions GET /api/v1/users/{userId}/factors/questions
    - get_factor                    GET    /api/v1/users/{userId}/factors/{factorId}
    - unenroll_factor               DELETE /api/v1/users/{userId}/factors/{factorId}
    - activate_factor               POST   /api/v1/users/{userId}/factors/{factorId}/lifecycle/activate
    - verify_factor                 POST   /api/v1/users/{userId}/factors/{factorId}/verify
    - get_factor_transaction_status GET    /api/v1/users/{userId}/factors/{factorId}/transactions/{transactionId}
    - list_yubikey_otp_tokens       GET    /api/v1/org/factors/yubikey_token/tokens
    - get_yubikey_otp_token         GET    /api/v1/org/factors/yubikey_token/tokens/{tokenId}
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.pagination import auto_paginate
from okta_mcp_server.utils.validation import validate_ids


@validate_ids("user_id")
async def list_factors(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List all enrolled factors for a user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of enrolled factor objects.
    """
    logger.info(f"Listing factors for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        factors, resp, err = await client.list_factors(user_id)
        if err:
            return [f"Error: {err}"]
        return factors if factors else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def enroll_factor(
    user_id: str,
    factor_data: dict,
    ctx: Context = None,
    update_phone: Optional[bool] = None,
    activate: Optional[bool] = None,
) -> list:
    """Enroll a factor for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_data (dict, required): Factor enrollment data including factorType and provider.
        update_phone (bool, optional): Whether to update the phone number.
        activate (bool, optional): Whether to activate the factor immediately.

    Returns:
        List containing the enrolled factor.
    """
    logger.info(f"Enrolling factor for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if update_phone is not None:
            query_params["updatePhone"] = update_phone
        if activate is not None:
            query_params["activate"] = activate
        factor, _, err = await client.enroll_factor(user_id, factor_data, query_params)
        if err:
            return [f"Error: {err}"]
        return [factor]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_supported_factors(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List all supported factors for a user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of supported factor objects.
    """
    logger.info(f"Listing supported factors for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        factors, _, err = await client.list_supported_factors(user_id)
        if err:
            return [f"Error: {err}"]
        return factors if factors else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def list_supported_security_questions(
    user_id: str,
    ctx: Context = None,
) -> list:
    """List all supported security questions for a user.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List of security question objects.
    """
    logger.info(f"Listing security questions for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        questions, _, err = await client.list_supported_security_questions(user_id)
        if err:
            return [f"Error: {err}"]
        return questions if questions else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "factor_id")
async def get_factor(
    user_id: str,
    factor_id: str,
    ctx: Context = None,
) -> list:
    """Retrieve a specific factor for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_id (str, required): The ID of the factor.

    Returns:
        List containing the factor object.
    """
    logger.info(f"Getting factor {factor_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        factor, _, err = await client.get_factor(user_id, factor_id)
        if err:
            return [f"Error: {err}"]
        return [factor]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "factor_id")
async def unenroll_factor(
    user_id: str,
    factor_id: str,
    ctx: Context = None,
) -> list:
    """Unenroll (delete) a factor for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_id (str, required): The ID of the factor to unenroll.

    Returns:
        List containing the result.
    """
    logger.info(f"Unenrolling factor {factor_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result = await client.unenroll_factor(user_id, factor_id)
        err = result[-1] if isinstance(result, tuple) else None
        if err:
            return [f"Error: {err}"]
        return [f"Factor {factor_id} unenrolled for user {user_id}."]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "factor_id")
async def activate_factor(
    user_id: str,
    factor_id: str,
    activation_data: Optional[dict] = None,
    ctx: Context = None,
) -> list:
    """Activate a factor for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_id (str, required): The ID of the factor to activate.
        activation_data (dict, optional): Activation data (e.g., passCode for TOTP).

    Returns:
        List containing the activated factor.
    """
    logger.info(f"Activating factor {factor_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        factor, _, err = await client.activate_factor(
            user_id, factor_id, activation_data or {}
        )
        if err:
            return [f"Error: {err}"]
        return [factor]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "factor_id")
async def verify_factor(
    user_id: str,
    factor_id: str,
    verify_data: Optional[dict] = None,
    ctx: Context = None,
) -> list:
    """Verify a factor for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_id (str, required): The ID of the factor to verify.
        verify_data (dict, optional): Verification data (e.g., passCode).

    Returns:
        List containing the verification result.
    """
    logger.info(f"Verifying factor {factor_id} for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result, _, err = await client.verify_factor(
            user_id, factor_id, verify_data or {}
        )
        if err:
            return [f"Error: {err}"]
        return [result]
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("user_id", "factor_id", "transaction_id")
async def get_factor_transaction_status(
    user_id: str,
    factor_id: str,
    transaction_id: str,
    ctx: Context = None,
) -> list:
    """Retrieve a factor transaction status.

    Parameters:
        user_id (str, required): The ID of the user.
        factor_id (str, required): The ID of the factor.
        transaction_id (str, required): The ID of the transaction.

    Returns:
        List containing the transaction status.
    """
    logger.info(f"Getting transaction {transaction_id} for factor {factor_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result, _, err = await client.get_factor_transaction_status(
            user_id, factor_id, transaction_id
        )
        if err:
            return [f"Error: {err}"]
        return [result]
    except Exception as e:
        return [f"Exception: {e}"]


async def list_yubikey_otp_tokens(
    ctx: Context = None,
    after: Optional[str] = None,
    limit: Optional[int] = None,
    filter: Optional[str] = None,
) -> list:
    """List all YubiKey OTP tokens.

    Parameters:
        after (str, optional): Pagination cursor.
        limit (int, optional): Maximum number of tokens to return.
        filter (str, optional): Filter expression.

    Returns:
        List of YubiKey OTP token objects.
    """
    logger.info("Listing YubiKey OTP tokens")
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
        tokens, _, err = await client.list_yubikey_otp_tokens(query_params)
        if err:
            return [f"Error: {err}"]
        return tokens if tokens else []
    except Exception as e:
        return [f"Exception: {e}"]


@validate_ids("token_id")
async def get_yubikey_otp_token(
    token_id: str,
    ctx: Context = None,
) -> list:
    """Retrieve a specific YubiKey OTP token.

    Parameters:
        token_id (str, required): The ID of the token.

    Returns:
        List containing the token object.
    """
    logger.info(f"Getting YubiKey OTP token {token_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        token, _, err = await client.get_yubikey_otp_token_by_id(token_id)
        if err:
            return [f"Error: {err}"]
        return [token]
    except Exception as e:
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    list_factors, enroll_factor, list_supported_factors,
    list_supported_security_questions, get_factor, unenroll_factor,
    activate_factor, verify_factor, get_factor_transaction_status,
    list_yubikey_otp_tokens, get_yubikey_otp_token,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "list_factors": list_factors,
    "enroll_factor": enroll_factor,
    "list_supported_factors": list_supported_factors,
    "list_supported_security_questions": list_supported_security_questions,
    "get_factor": get_factor,
    "unenroll_factor": unenroll_factor,
    "activate_factor": activate_factor,
    "verify_factor": verify_factor,
    "get_factor_transaction_status": get_factor_transaction_status,
    "list_yubikey_otp_tokens": list_yubikey_otp_tokens,
    "get_yubikey_otp_token": get_yubikey_otp_token,
}
