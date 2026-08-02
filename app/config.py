from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # GitLab (legacy — removed once the GitHub migration is complete)
    GITLAB_WEBHOOK_SECRET: str
    GITLAB_PAT: str

    # GitHub App
    # The App's identifier used as the JWT issuer. The numeric App ID works;
    # GitHub also accepts the Client ID.
    GITHUB_APP_ID: str = ""

    # The App's RSA private key. Either the raw PEM (multi-line, with the
    # BEGIN/END lines) or a base64-encoded PEM on a single line — the loader
    # in github_auth.py accepts both.
    GITHUB_APP_PRIVATE_KEY: str = ""
    
    # Secret set on the App's webhook config; used to verify X-Hub-Signature-256.
    GITHUB_WEBHOOK_SECRET: str = ""

    # Google Cloud (only required when using Cloud Tasks)
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()