# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

import keyring
from loguru import logger
from okta.client import Client as OktaClient

from okta_mcp_server.utils.auth.auth_manager import SERVICE_NAME, OktaAuthManager


async def get_okta_client(manager: OktaAuthManager) -> OktaClient:
    """Initialize and return an Okta client"""
    # Engine mode: return a pre-resolved client when available.
    resolved = getattr(manager, "_resolved_client", None)
    if resolved is not None:
        logger.debug("Returning pre-resolved Okta client (engine mode)")
        return resolved

    logger.debug("Initializing Okta client")
    if not await manager.is_valid_token():
        logger.warning("Token is invalid or expired, re-authenticating")
        await manager.authenticate()
    api_token = keyring.get_password(SERVICE_NAME, "api_token")
    if not api_token:
        raise RuntimeError(
            "No API token found in keyring after authentication. "
            "Ensure OKTA_ORG_URL and OKTA_CLIENT_ID are configured correctly "
            "and that authentication completed successfully."
        )
    config = {
        "orgUrl": manager.org_url,
        "token": api_token,
        "authorizationMode": "Bearer",
        "userAgent": "okta-mcp-server/0.0.1",
    }
    logger.debug(f"Okta client configured for org: {manager.org_url}")
    return OktaClient(config)
