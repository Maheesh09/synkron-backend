from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, pipeline, dashboard
from app.database import connect_db, disconnect_db
import logging
from contextlib import asynccontextmanager
import firebase_admin
from app.config import settings as _settings

# Initialise the Firebase Admin SDK once. On Cloud Run this uses the service
# account's Application Default Credentials; verify_id_token only needs the
# project id to validate the token audience.
if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": _settings.FIREBASE_PROJECT_ID})


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
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
    allow_origins=["http://localhost:3000", "https://synkron.dev"],
    allow_methods=["*"],
    allow_headers=["*"],
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