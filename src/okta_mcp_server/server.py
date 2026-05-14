# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, List, Optional

from loguru import logger
from mcp.server.fastmcp import FastMCP

from okta_mcp_server.utils.auth.auth_manager import OktaAuthManager


def _patch_okta_sdk_models() -> None:
    """Patch Okta SDK pydantic models that have incorrect field types.

    LogSecurityContext.userBehaviors is typed as List[StrictStr] in the generated
    SDK, but the Okta API actually returns a list of behavior objects.  Relax the
    annotation to List[Any] so pydantic validation does not reject real responses.
    """
    try:
        from okta.models.log_security_context import LogSecurityContext

        # Pydantic v2: update the class-level annotation then rebuild the model
        LogSecurityContext.__annotations__["user_behaviors"] = Optional[List[Any]]
        LogSecurityContext.model_rebuild(force=True)
        logger.debug("Patched LogSecurityContext.userBehaviors → List[Any]")
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Could not patch LogSecurityContext: {exc}")

LOG_FILE = os.environ.get("OKTA_LOG_FILE")


@dataclass
class OktaAppContext:
    okta_auth_manager: OktaAuthManager


@asynccontextmanager
async def okta_authorisation_flow(server: FastMCP) -> AsyncIterator[OktaAppContext]:
    """
    Manages the application lifecycle. It initializes the OktaManager on startup
    and yields the context. Authentication is deferred to the first tool call so
    the MCP server can start serving immediately without blocking on browser auth.
    """
    logger.info("Starting Okta authorization flow")
    manager = OktaAuthManager()
    # Defer authentication — tools call manager.authenticate() lazily via is_valid_token()
    logger.info("OktaAuthManager ready (authentication deferred to first tool call)")

    try:
        yield OktaAppContext(okta_auth_manager=manager)
    finally:
        logger.debug("Clearing Okta tokens")
        manager.clear_tokens()


mcp = FastMCP("Okta IDaaS MCP Server", lifespan=okta_authorisation_flow)


def main():
    """Run the Okta MCP server."""
    logger.remove()

    if LOG_FILE:
        logger.add(
            LOG_FILE,
            mode="w",
            level=os.environ.get("OKTA_LOG_LEVEL", "INFO"),
            retention="5 days",
            enqueue=True,
            serialize=True,
        )

    logger.add(
        sys.stderr, level=os.environ.get("OKTA_LOG_LEVEL", "INFO"), format="{time} {level} {message}", serialize=True
    )

    logger.info("Starting Okta MCP Server — Dynamic KG Orchestrator mode")

    # Patch Okta SDK models with incorrect field types before any tools load
    _patch_okta_sdk_models()

    # Register KG-based orchestrator tools at startup
    from okta_mcp_server.tools.orchestrator import orchestrator_kg  # noqa: F401
    from okta_mcp_server.tools.orchestrator.knowledge_graph import get_knowledge_graph

    # Eagerly build the knowledge graph so it's ready for the first query
    kg = get_knowledge_graph()
    stats = kg.get_stats()
    logger.info(
        f"Knowledge graph loaded: {stats['total_nodes']} tool nodes, "
        f"{stats['total_connections']} connections"
    )

    mcp.run()

