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

    # Gemini
    GEMINI_API_KEY: str

    # Agent Builder (Vertex AI Reasoning Engine)
    AGENT_ENGINE_RESOURCE: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()