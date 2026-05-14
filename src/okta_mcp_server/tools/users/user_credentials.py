# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""User Credentials tools for the Okta MCP server.

Provides operations to manage user credentials:
    - expire_password                      POST /api/v1/users/{id}/lifecycle/expire_password
    - expire_password_with_temp_password   POST /api/v1/users/{id}/lifecycle/expire_password_with_temp_password
    - reset_password                       POST /api/v1/users/{id}/lifecycle/reset_password
    - change_password                      POST /api/v1/users/{userId}/credentials/change_password
    - change_recovery_question             POST /api/v1/users/{userId}/credentials/change_recovery_question
    - forgot_password                      POST /api/v1/users/{userId}/credentials/forgot_password
    - forgot_password_set_new_password     POST /api/v1/users/{userId}/credentials/forgot_password_recovery_question
"""

from typing import Optional

from loguru import logger
from mcp.server.fastmcp import Context

from okta_mcp_server.server import mcp
from okta_mcp_server.utils.client import get_okta_client
from okta_mcp_server.utils.validation import validate_ids


@validate_ids("user_id")
async def expire_password(
    user_id: str,
    ctx: Context = None,
) -> list:
    """Expire a user's password, forcing a change on next sign-in.

    Parameters:
        user_id (str, required): The ID of the user.

    Returns:
        List containing the user object with updated status.
    """
    logger.info(f"Expiring password for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        user, _, err = await client.expire_password(user_id)
        if err:
            logger.error(f"Error expiring password: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully expired password for user {user_id}")
        return [user]
    except Exception as e:
        logger.error(f"Exception expiring password: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def expire_password_with_temp_password(
    user_id: str,
    ctx: Context = None,
    revoke_sessions: bool = False,
) -> list:
    """Expire a user's password and reset it to a temporary password.

    Parameters:
        user_id (str, required): The ID of the user.
        revoke_sessions (bool, optional): Whether to revoke outstanding sessions. Default: False.

    Returns:
        List containing the temporary password.
    """
    logger.info(f"Expiring password with temp password for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        temp_pw, _, err = await client.expire_password_with_temp_password(
            user_id, query_params={"revokeSessions": revoke_sessions}
        )
        if err:
            logger.error(f"Error expiring password with temp: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully expired password with temp for user {user_id}")
        return [temp_pw]
    except Exception as e:
        logger.error(f"Exception expiring password with temp: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def reset_password(
    user_id: str,
    send_email: bool = True,
    revoke_sessions: bool = False,
    ctx: Context = None,
) -> list:
    """Reset a user's password. Generates a one-time token (OTT).

    Parameters:
        user_id (str, required): The ID of the user.
        send_email (bool, optional): Whether to send the reset email. Default: True.
        revoke_sessions (bool, optional): Whether to revoke sessions. Default: False.

    Returns:
        List containing the password reset token or status.
    """
    logger.info(f"Resetting password for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        token, _, err = await client.reset_password(
            user_id, send_email=send_email, query_params={"revokeSessions": revoke_sessions}
        )
        if err:
            logger.error(f"Error resetting password: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully reset password for user {user_id}")
        return [token]
    except Exception as e:
        logger.error(f"Exception resetting password: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def change_password(
    user_id: str,
    change_password_data: dict,
    ctx: Context = None,
    strict: Optional[bool] = None,
) -> list:
    """Update a user's password by validating the current password.

    Parameters:
        user_id (str, required): The ID of the user.
        change_password_data (dict, required): Dict with 'oldPassword' and 'newPassword' objects,
            each containing a 'value' key.
        strict (bool, optional): If True, validates against password policy.

    Returns:
        List containing the updated credentials.
    """
    logger.info(f"Changing password for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        query_params = {}
        if strict is not None:
            query_params["strict"] = strict
        creds, _, err = await client.change_password(user_id, change_password_data, query_params)
        if err:
            logger.error(f"Error changing password: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully changed password for user {user_id}")
        return [creds]
    except Exception as e:
        logger.error(f"Exception changing password: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def change_recovery_question(
    user_id: str,
    credentials_data: dict,
    ctx: Context = None,
) -> list:
    """Update a user's recovery question and answer.

    Parameters:
        user_id (str, required): The ID of the user.
        credentials_data (dict, required): Dict with 'password' (containing 'value')
            and 'recovery_question' (containing 'question' and 'answer').

    Returns:
        List containing the updated credentials.
    """
    logger.info(f"Changing recovery question for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        creds, _, err = await client.change_recovery_question(user_id, credentials_data)
        if err:
            logger.error(f"Error changing recovery question: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully changed recovery question for user {user_id}")
        return [creds]
    except Exception as e:
        logger.error(f"Exception changing recovery question: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def forgot_password(
    user_id: str,
    send_email: bool = True,
    ctx: Context = None,
) -> list:
    """Start the forgot password flow for a user.

    Parameters:
        user_id (str, required): The ID of the user.
        send_email (bool, optional): Whether to send a forgot password email. Default: True.

    Returns:
        List containing the forgot password response.
    """
    logger.info(f"Starting forgot password flow for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result, _, err = await client.forgot_password(user_id, send_email=send_email)
        if err:
            logger.error(f"Error starting forgot password: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully started forgot password for user {user_id}")
        return [result]
    except Exception as e:
        logger.error(f"Exception starting forgot password: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


@validate_ids("user_id")
async def forgot_password_set_new_password(
    user_id: str,
    credentials_data: dict,
    send_email: bool = True,
    ctx: Context = None,
) -> list:
    """Reset password with recovery question validation.

    Parameters:
        user_id (str, required): The ID of the user.
        credentials_data (dict, required): Dict with 'password' and 'recovery_question'.
        send_email (bool, optional): Whether to send an email. Default: True.

    Returns:
        List containing the result.
    """
    logger.info(f"Setting new password with recovery question for user {user_id}")
    manager = ctx.request_context.lifespan_context.okta_auth_manager

    try:
        client = await get_okta_client(manager)
        result, _, err = await client.forgot_password_set_new_password(
            user_id, credentials_data, send_email=send_email
        )
        if err:
            logger.error(f"Error setting new password: {err}")
            return [f"Error: {err}"]

        logger.info(f"Successfully set new password for user {user_id}")
        return [result]
    except Exception as e:
        logger.error(f"Exception setting new password: {type(e).__name__}: {e}")
        return [f"Exception: {e}"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

for _fn in [
    expire_password, expire_password_with_temp_password, reset_password,
    change_password, change_recovery_question, forgot_password,
    forgot_password_set_new_password,
]:
    mcp.tool()(_fn)

# ---------------------------------------------------------------------------
# Engine action registry
# ---------------------------------------------------------------------------

ENGINE_ACTIONS = {
    "expire_password": expire_password,
    "expire_password_with_temp_password": expire_password_with_temp_password,
    "reset_password": reset_password,
    "change_password": change_password,
    "change_recovery_question": change_recovery_question,
    "forgot_password": forgot_password,
    "forgot_password_set_new_password": forgot_password_set_new_password,
}
