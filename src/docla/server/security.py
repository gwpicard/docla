"""Request checks for the local server."""

import re
import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "")
        origin = headers.get("origin")
        if not re.fullmatch(r"(?:127\.0\.0\.1|localhost)(?::[0-9]+)?", host):
            response = JSONResponse({"detail": "Invalid host"}, status_code=403)
        elif origin is not None and origin != f"http://{host}":
            response = JSONResponse({"detail": "Invalid origin"}, status_code=403)
        elif scope["path"].startswith("/api/") and not secrets.compare_digest(
            headers.get("X-Docla-Token", "").encode(), self.token.encode()
        ):
            response = JSONResponse({"detail": "Invalid token"}, status_code=401)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)
