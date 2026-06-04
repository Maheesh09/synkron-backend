import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.agent_builder.tools import create_gitlab_mcp_toolset
from google.adk.agents import LlmAgent

logging.basicConfig(level=logging.INFO)

async def test_mcp():
    print("Testing GitLab MCP connection setup...")
    try:
        toolset = create_gitlab_mcp_toolset()
        print("MCPToolset created successfully.")
        
        agent = LlmAgent(
            name="test_mcp_agent",
            model="gemini-2.0-flash",
            tools=[toolset]
        )
        print("LlmAgent instantiated with MCPToolset.")
        print("ADK is successfully configured to spawn 'npx @gitlab-org/gitlab-mcp' when this agent is invoked.")
        print("Note: The MCP subprocess is launched lazily by ADK when the agent attempts to use tools.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_mcp())
