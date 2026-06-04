"""
tools.py — Vertex AI Agent Builder path tools
==============================================
Provides a real GitLab MCP toolset for the Vertex AI / Agent Engine path.
The agent connects to GitLab via the official GitLab MCP server running as a
local subprocess (stdio transport), which speaks the Model Context Protocol.

This file is ONLY used by app/agent_builder/agent.py (the Vertex AI path).
The direct 4-agent pipeline uses app/services/gitlab_mcp.py (REST) instead —
that code is completely untouched.

Prerequisites for the Vertex AI path:
  - Node.js / npx must be installed on the machine running the agent.
  - The first run auto-downloads @gitlab-org/gitlab-mcp via npx (cached after that).
  - GITLAB_PAT must be set in .env with the `api` scope.
"""
from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
from mcp.client.stdio import StdioServerParameters
from app.config import settings
import logging

logger = logging.getLogger(__name__)


def create_gitlab_mcp_toolset() -> MCPToolset:
    """
    Build an ADK MCPToolset that launches the official GitLab MCP server
    as a subprocess via npx and communicates over stdio.

    The toolset exposes GitLab capabilities (read files, list trees, create
    branches, commit files, open merge requests) to the LlmAgent through the
    MCP protocol — not raw REST calls.

    Returns:
        MCPToolset instance ready to be passed to LlmAgent(tools=[...]).
    """
    logger.info("Creating GitLab MCPToolset (stdio → npx @gitlab-org/gitlab-mcp)")
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@zereight/mcp-gitlab"],
                env={
                    # PAT with `api` scope — same value already in .env
                    "GITLAB_PERSONAL_ACCESS_TOKEN": settings.GITLAB_PAT,
                    # Target the public GitLab instance
                    "GITLAB_API_URL": "https://gitlab.com/api/v4",
                }
            )
        )
    )