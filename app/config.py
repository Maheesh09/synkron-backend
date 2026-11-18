from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):

    GITHUB_APP_ID: str = ""
    GITHUB_APP_PRIVATE_KEY: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    # Commit author login of this App, e.g. "synkron-docs[bot]". Optional:
    # looked up from GitHub (GET /app) when empty.
    GITHUB_APP_BOT_LOGIN: str = ""
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

    # Firebase Authentication — project that mints the user ID tokens.
    FIREBASE_PROJECT_ID: str = ""

    # CORS
    CORS_ALLOWED_ORIGINS: str = ""

    RATE_LIMIT_PER_HOUR: int = 20

    # Must match the Cloud Tasks queue's --max-attempts. On the last attempt a
    # retryable error is recorded as a failure instead of asking for a retry.
    PIPELINE_MAX_ATTEMPTS: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()