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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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

from fastapi.openapi.utils import get_openapi
from app.config import settings

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # 1. Add examples for /webhook/gitlab
    if "/webhook/gitlab" in openapi_schema.get("paths", {}):
        post_method = openapi_schema["paths"]["/webhook/gitlab"]["post"]
        if "parameters" not in post_method:
            post_method["parameters"] = []
        post_method["parameters"].extend([
            {
                "name": "X-Gitlab-Token",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "default": "your-webhook-secret"},
                "description": "GitLab Webhook Secret"
            },
            {
                "name": "X-Gitlab-Event",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "default": "Push Hook"},
                "description": "Event Type"
            }
        ])
        
        post_method["requestBody"] = {
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                    "examples": {
                        "Push Event": {
                            "summary": "Push Event (Triggers Pipeline)",
                            "value": {
                                "object_kind": "push",
                                "before": "0000000000000000000000000000000000000000",
                                "after": "a06f2362047f1787d68c3d710fc978fe6eeafb9f",
                                "total_commits_count": 1,
                                "user_username": "developer",
                                "project": {"id": 82768623}
                            }
                        },
                        "Merge Event": {
                            "summary": "Merge Event (Triggers Feedback)",
                            "value": {
                                "object_kind": "merge_request",
                                "object_attributes": {
                                    "action": "merge",
                                    "title": "Docs: Added synkron",
                                    "iid": 1
                                },
                                "project": {"id": 82768623}
                            }
                        }
                    }
                }
            }
        }

    # 2. Add examples for internal endpoints
    for path in ["/internal/run-pipeline", "/internal/process-feedback"]:
        if path in openapi_schema.get("paths", {}):
            post_method = openapi_schema["paths"][path]["post"]
            for param in post_method.get("parameters", []):
                if param["name"] == "x-internal-token":
                    param["schema"]["default"] = "your-internal-token"
            
            example_val = {
                "before": "0000000000000000000000000000000000000000",
                "after": "a06f2362047f1787d68c3d710fc978fe6eeafb9f",
                "project": {"id": 82768623}
            } if path == "/internal/run-pipeline" else {
                "project": {"id": 82768623},
                "object_attributes": {"iid": 1}
            }
            
            if "requestBody" in post_method:
                content = post_method["requestBody"].get("content", {})
                if "application/json" in content:
                    content["application/json"]["examples"] = {
                        "Example": {
                            "summary": "Simulate internal trigger",
                            "value": example_val
                        }
                    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi