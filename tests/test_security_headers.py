"""Security headers are added to every response, including CORS preflights and errors."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.middleware.security_headers import API_CSP, DOCS_CSP, SecurityHeadersMiddleware


def _client(*, hsts: bool = True) -> TestClient:
    app = FastAPI()

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    @app.get("/api/cached")
    async def cached():
        return JSONResponse({"ok": True}, headers={"Cache-Control": "public, max-age=60"})

    @app.get("/api/missing")
    async def missing():
        raise HTTPException(404, "nope")

    app.add_middleware(CORSMiddleware, allow_origins=["https://www.synkron.dev"],
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization"])
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return TestClient(app)


EXPECTED = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cross-origin-opener-policy": "same-origin",
}


def test_api_response_has_all_security_headers():
    r = _client().get("/api/thing")
    assert r.status_code == 200
    for name, value in EXPECTED.items():
        assert r.headers[name] == value
    assert r.headers["content-security-policy"] == API_CSP
    assert "camera=()" in r.headers["permissions-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_error_responses_are_covered_too():
    r = _client().get("/api/missing")
    assert r.status_code == 404
    assert r.headers["x-frame-options"] == "DENY"


def test_cors_preflight_is_covered():
    r = _client().options("/api/thing", headers={
        "Origin": "https://www.synkron.dev",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://www.synkron.dev"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_route_headers_are_not_overridden():
    r = _client().get("/api/cached")
    assert r.headers["cache-control"] == "public, max-age=60"


def test_docs_get_a_policy_that_lets_swagger_load():
    r = _client().get("/docs")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == DOCS_CSP
    assert "cache-control" not in r.headers or r.headers["cache-control"] != "no-store"


def test_hsts_can_be_disabled_for_local_http():
    r = _client(hsts=False).get("/api/thing")
    assert "strict-transport-security" not in r.headers
    assert r.headers["x-frame-options"] == "DENY"


def test_header_names_are_not_duplicated():
    r = _client().get("/api/thing")
    names = [k.lower() for k, _ in r.headers.multi_items()]
    assert len(names) == len(set(names))
