from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # GitLab
    GITLAB_WEBHOOK_SECRET: str
    GITLAB_PAT: str

    # Google Cloud (only required when using Cloud Tasks or Vertex AI agent path)
    GOOGLE_CLOUD_PROJECT: str = ""
    GCP_REGION: str = "asia-south1"

    # MongoDB
    MONGODB_URI: str
    MONGODB_DB_NAME: str = "synkron-cluster"

    # Internal
    SERVICE_URL: str
    INTERNAL_SECRET: str
    LOCAL_DEV: bool = False

    # Gemini
    GEMINI_API_KEY: str

    # ── Agent Builder (ADK local runner + optional Vertex AI deployment) ─────
    # Set USE_AGENT_BUILDER=true in .env to run the ADK + MCP path instead of
    # the direct 4-agent REST pipeline.  No Vertex AI required — the agent runs
    # in-process against the Gemini API using GOOGLE_API_KEY.
    USE_AGENT_BUILDER: bool = False

    # Gemini API key for the local ADK runner (get from https://aistudio.google.com).
    # ADK reads GOOGLE_API_KEY directly from the environment; we surface it here
    # so run_agent() can ensure it's set before the Runner initialises.
    GOOGLE_API_KEY: str = ""

    # Only needed if you deploy to Vertex AI Agent Engine (optional).
    AGENT_ENGINE_RESOURCE: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()