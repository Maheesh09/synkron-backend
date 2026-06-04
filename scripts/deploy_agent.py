"""
Run once to deploy the Synkron ADK agent to Vertex AI Agent Engine.
"""
import os, sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from app.agent_builder.agent import deploy_to_agent_engine

if __name__ == "__main__":
    print(" Deploying Synkron agent to Vertex AI Agent Engine...")
    print(" This takes 3–8 minutes. Do not interrupt.\n")
    resource = deploy_to_agent_engine()
    print(f"\n Done!")
    print(f" Copy this into your .env file:")
    print(f"   AGENT_ENGINE_RESOURCE={resource}")