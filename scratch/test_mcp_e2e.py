import asyncio
import sys
import os
import logging
from pprint import pprint

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.config import settings
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
from app.agent_builder.agent import _build_agent

logging.basicConfig(level=logging.INFO)

async def test_mcp_e2e():
    print("Testing real GitLab MCP tool execution...")
    
    # Needs to be a valid project ID that your PAT has access to
    # For a simple test, we will just ask the agent to list the repo tools or
    # try to use any basic tool. We'll give it a generic instruction to test
    # the server connection.
    
    # We use a throwaway agent just for this test
    agent = _build_agent()
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="test_app", session_service=session_service)
    
    # Need API key for the agent to reason
    api_key = settings.GOOGLE_API_KEY or settings.GEMINI_API_KEY
    if not api_key:
        print("❌ Cannot run E2E test without GOOGLE_API_KEY or GEMINI_API_KEY in .env")
        sys.exit(1)
        
    os.environ["GOOGLE_API_KEY"] = api_key
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
    
    await session_service.create_session(
        app_name="test_app",
        user_id="test-user",
        session_id="test-session-123"
    )
    
    # Give it a safe, read-only instruction that forces it to use an MCP tool
    # without needing a valid before/after SHA or Project ID, or we can provide a dummy one
    # and just see if the tool call attempts to execute.
    message_text = "Use your tools to list the branches or files for GitLab project ID 82768623. Output what you find, or the error if it fails."
    
    new_message = types.Content(
        role="user",
        parts=[types.Part(text=message_text)],
    )

    print("Running agent (this will invoke npx and connect to GitLab)...")
    try:
        async for event in runner.run_async(
            user_id="test-user",
            session_id="test-session-123",
            new_message=new_message,
        ):
            # Print events to see if tools are being called and returning data
            print(f"Event: {event}")
            
    except Exception as e:
        print(f"Error during execution: {e}")
        sys.exit(1)
        
    print("E2E test completed successfully.")

if __name__ == "__main__":
    asyncio.run(test_mcp_e2e())
