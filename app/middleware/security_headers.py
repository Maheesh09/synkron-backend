"""Security headers for every HTTP response.

Written as a pure ASGI middleware (not ``BaseHTTPMiddleware``) so it adds no
extra task or response buffering per request; it only rewrites the headers of
the ``http.response.start`` message on its way out.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The API only ever returns JSON, so the browser should never be allowed to
# load anything on its behalf or render it inside a frame.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

# Swagger UI / ReDoc (only enabled in local dev) load JS and CSS from jsDelivr
# and use inline scripts, so they need a looser policy.
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

BASE_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
        "microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "X-Permitted-Cross-Domain-Policies": "none",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = True) -> None:
        self.app = app
        self.headers = dict(BASE_HEADERS)
        if not hsts:  # plain-HTTP local dev: HSTS would pin localhost to HTTPS
            self.headers.pop("Strict-Transport-Security")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        is_docs = path.startswith(DOCS_PATHS)
        csp = DOCS_CSP if is_docs else API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}  # bytes, as ASGI sends them
                extra = [(b"content-security-policy", csp.encode())]
                extra += [(k.lower().encode(), v.encode()) for k, v in self.headers.items()]
                if not is_docs:
                    # API responses carry per-user data: never store them in shared caches.
                    extra.append((b"cache-control", b"no-store"))
                headers = list(message.get("headers", []))
                # Never override a header a route set deliberately.
                headers += [(k, v) for k, v in extra if k not in existing]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
