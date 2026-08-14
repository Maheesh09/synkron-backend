from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlsplit
from app.routers import webhook, pipeline, dashboard
from app.database import connect_db, disconnect_db
import logging
from contextlib import asynccontextmanager
import firebase_admin
from app.config import settings as _settings


def normalize_cors_origins(raw: str):
    """Convert env entries like https://example.com/* or localhost:3000 into
    valid browser origin strings. We intentionally drop any path/query/fragment
    suffix because CORS origins must be exact origins, not full URLs."""
    origins = []
    for item in (raw or "").split(","):
        origin = item.strip()
        if not origin:
            continue
        if origin == "*":
            origins.append("*")
            continue
        if "://" not in origin:
            origin = f"https://{origin}" if not origin.startswith("https://") and not origin.startswith("https://") else origin
        parsed = urlsplit(origin)
        host = parsed.netloc or parsed.path
        if host:
            origins.append(f"{parsed.scheme}://{host}")
    return list(dict.fromkeys(origins))


_cors_origins = normalize_cors_origins(_settings.CORS_ALLOWED_ORIGINS)

# Initialise the Firebase Admin SDK once. On Cloud Run this uses the service
# account's Application Default Credentials; verify_id_token only needs the
# project id to validate the token audience.
if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": _settings.FIREBASE_PROJECT_ID})


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await connect_db()
    except Exception as e:
        logging.exception(f"Failed to connect to database: {e}")
    yield
    await disconnect_db()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

app = FastAPI(
    title="Synkron API",
    version="1.0.0",
    description="AI documentation agent powered by GitLab + Gemini",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type",],
)


# Routes
app.include_router(webhook.router,  prefix="/webhook",  tags=["Webhook"])
app.include_router(pipeline.router,  prefix="/internal", tags=["Internal"])
app.include_router(dashboard.router, prefix="/api",      tags=["Dashboard"])


@app.get("/")
async def root():
    return {"service": "synkron", "status": "running", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}