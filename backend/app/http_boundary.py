"""Bounded request buffering and redacted HTTP failures (pure ASGI)."""

import hashlib
import logging
import uuid
from urllib.parse import urlparse

from starlette.responses import JSONResponse

logger = logging.getLogger("personal_agent.http")


class HttpBoundary:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        headers = dict(scope.get("headers", []))

        async def reject(status, code, detail):
            response = JSONResponse(
                {"code": code, "detail": detail, "request_id": request_id}, status_code=status
            )
            await response(scope, receive, secure_send)

        started = False

        async def secure_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-request-id", request_id.encode()),
                ]
                if not self.settings.simulation:
                    message["headers"].append((b"strict-transport-security", b"max-age=31536000"))
            await send(message)

        if not self.settings.simulation and scope["path"] not in {"/health", "/ready"}:
            expected = urlparse(self.settings.public_origin).netloc.encode()
            if headers.get(b"host", b"") != expected:
                return await reject(400, "INVALID_HOST", "Host is not configured")
            if scope.get("scheme") != "https":
                return await reject(400, "HTTPS_REQUIRED", "Use HTTPS")
        if headers.get(b"content-encoding", b"identity") != b"identity":
            return await reject(415, "UNSUPPORTED_ENCODING", "Compressed request bodies are not accepted")
        maximum = 65536
        try:
            if int(headers.get(b"content-length", b"0")) > maximum:
                return await reject(413, "PAYLOAD_TOO_LARGE", "Request body exceeds 64 KiB")
        except ValueError:
            return await reject(400, "INVALID_LENGTH", "Invalid content length")
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > maximum:
                return await reject(413, "PAYLOAD_TOO_LARGE", "Request body exceeds 64 KiB")
            if not message.get("more_body", False):
                break
        scope["body_digest"] = hashlib.sha256(body).hexdigest()
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        try:
            await self.app(scope, bounded_receive, secure_send)
        except Exception as exc:
            # Never log exception text/traceback, request bodies, tokens, path IDs or SQL parameters.
            logger.error("request_failed request_id=%s type=%s", request_id, type(exc).__name__)
            if not started:
                await reject(500, "INTERNAL_ERROR", "Request failed; use the request ID for support")
