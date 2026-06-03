from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import webhook, pipeline, dashboard
from app.database import connect_db, disconnect_db
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

app = FastAPI(
    title="Synkron API",
    version="1.0.0",
    description="AI documentation agent powered by GitLab MCP + Google Cloud Agent Builder + Gemini"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await connect_db()


@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()


# ── Routes ──────────────────────────────────────────────────────────────
app.include_router(webhook.router,  prefix="/webhook",  tags=["Webhook"])
app.include_router(pipeline.router,  prefix="/internal", tags=["Internal"])
app.include_router(dashboard.router, prefix="/api",      tags=["Dashboard"])


@app.get("/")
async def root():
    return {"service": "synkron", "status": "running", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}