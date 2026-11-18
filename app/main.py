from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlsplit
from app.routers import webhook, pipeline, dashboard
from app.database import connect_db, disconnect_db
import logging
import os
from contextlib import asynccontextmanager
import firebase_admin
from app.config import settings as _settings
from app.middleware.security_headers import SecurityHeadersMiddleware


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
            origin = f"https://{origin}"   # bare host: assume https
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


def warn_if_local_dev_on_cloud_run(local_dev: bool, environ) -> bool:
    """LOCAL_DEV disables HSTS, exposes /docs and bypasses Cloud Tasks. Cloud
    Run always sets K_SERVICE, so both together means a misconfigured deploy."""
    if local_dev and environ.get("K_SERVICE"):
        logging.getLogger(__name__).error(
            "LOCAL_DEV=true on Cloud Run service %r: HSTS is off, /docs is public "
            "and pipelines run in-process. Set LOCAL_DEV=false.", environ["K_SERVICE"])
        return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    warn_if_local_dev_on_cloud_run(_settings.LOCAL_DEV, os.environ)
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
    # Interactive docs expose the whole API surface; only serve them locally.
    docs_url="/docs" if _settings.LOCAL_DEV else None,
    redoc_url="/redoc" if _settings.LOCAL_DEV else None,
    openapi_url="/openapi.json" if _settings.LOCAL_DEV else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],   # the API exposes no PUT/PATCH/DELETE routes
    allow_headers=["Authorization", "Content-Type"],
)

# Added last, so it is the outermost middleware and also covers CORS
# preflight responses and 4xx errors.
app.add_middleware(SecurityHeadersMiddleware, hsts=not _settings.LOCAL_DEV)


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