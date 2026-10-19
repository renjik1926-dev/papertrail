"""Protecting a local server from websites in your browser (BUILD_PLAN §9).

Binding to 127.0.0.1 stops other machines, but any website you visit can still send requests
to 127.0.0.1:8000 from your browser. Three cheap defenses, all returning 403 forbidden_origin:
1. Host check (DNS rebinding): only `127.0.0.1` and `localhost`.
2. A required `X-PaperTrail: 1` header on every state-changing request. Browsers won't send a
   custom header cross-site without a CORS preflight, and CORS is never enabled.
3. Origin check on state-changing requests: if present, it must be the app's own origin
   (or the Vite dev server's when PAPERTRAIL_DEV is on).
Plus security headers on every response.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from starlette._utils import parse_host_header
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from papertrail.errors import DEFAULT_MESSAGES, ErrorCode

ALLOWED_HOSTS = ("127.0.0.1", "localhost")
REQUIRED_HEADER = "x-papertrail"
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEV_PORT = 5173

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; worker-src 'self' blob:; "
    "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


def _forbidden_body() -> bytes:
    message = DEFAULT_MESSAGES[ErrorCode.forbidden_origin]
    return json.dumps(
        {"error": {"code": ErrorCode.forbidden_origin.value, "message": message}}
    ).encode()


async def send_forbidden(send: Send) -> None:
    body = _forbidden_body()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]
    await send({"type": "http.response.start", "status": 403, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def allowed_origins(port: int, *, dev: bool) -> frozenset[str]:
    origins = {f"http://{host}:{port}" for host in ALLOWED_HOSTS}
    if dev:
        origins |= {f"http://{host}:{DEV_PORT}" for host in ALLOWED_HOSTS}
    return frozenset(origins)


class LocalHostMiddleware(TrustedHostMiddleware):
    """Starlette's TrustedHostMiddleware, answering with our 403 error shape."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] = ALLOWED_HOSTS) -> None:
        super().__init__(app, allowed_hosts=list(allowed_hosts), www_redirect=False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        parsed = parse_host_header(Headers(scope=scope).get("host"))
        if parsed is None or parsed.host.lower() not in self.allowed_hosts:
            await send_forbidden(send)
            return
        await self.app(scope, receive, send)


class RequestGuardMiddleware:
    """Required custom header and Origin check on state-changing requests."""

    def __init__(self, app: ASGIApp, *, origins: frozenset[str]) -> None:
        self.app = app
        self.origins = origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"].upper() in STATE_CHANGING:
            headers = Headers(scope=scope)
            if headers.get(REQUIRED_HEADER) != "1":
                await send_forbidden(send)
                return
            origin = headers.get("origin")
            if origin is not None and origin not in self.origins:
                await send_forbidden(send)
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
