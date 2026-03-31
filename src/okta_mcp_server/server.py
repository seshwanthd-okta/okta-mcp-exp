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

from loguru import logger
from mcp.server.fastmcp import FastMCP

from okta_mcp_server.utils.auth.auth_manager import OktaAuthManager

LOG_FILE = os.environ.get("OKTA_LOG_FILE")


@dataclass
class OktaAppContext:
    okta_auth_manager: OktaAuthManager


@asynccontextmanager
async def okta_authorisation_flow(server: FastMCP) -> AsyncIterator[OktaAppContext]:
    """
    Manages the application lifecycle. It initializes the OktaManager on startup,
    performs authorization, and yields the context for use in tools.
    """
    logger.info("Starting Okta authorization flow")
    manager = OktaAuthManager()
    await manager.authenticate()
    logger.info("Okta authentication completed successfully")

    try:
        yield OktaAppContext(okta_auth_manager=manager)
    finally:
        logger.debug("Clearing Okta tokens")
        manager.clear_tokens()


mcp = FastMCP("Okta IDaaS MCP Server", lifespan=okta_authorisation_flow)

# ── Tool call interceptor for usage tracking ──────────────────────────────
# Shadows mcp._tool_manager.call_tool with a wrapper that records every tool
# invocation in registry._usage_counts and _call_sequence.  This gives the
# LLM access to frequency and recency data so it can reason about which
# loaded categories are worth keeping vs unloading.
_original_call_tool = mcp._tool_manager.call_tool


async def _recording_call_tool(*args, **kwargs):
    # First positional arg is always the tool name
    name = args[0] if args else kwargs.get("name", "unknown")
    from okta_mcp_server.tools.tool_search.registry import record_tool_call  # lazy to avoid circular import
    record_tool_call(name)
    return await _original_call_tool(*args, **kwargs)


mcp._tool_manager.call_tool = _recording_call_tool


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

    logger.info("Starting Okta MCP Server")
    # Only load tool_search at startup — all other tool categories are
    # lazy-loaded on-demand when the model calls search_tools().
    from okta_mcp_server.tools.tool_search import tool_search  # noqa: F401

    mcp.run()

