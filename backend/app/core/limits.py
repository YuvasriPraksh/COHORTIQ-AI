"""Request body size limits enforced as pure ASGI middleware.

``RequestSizeLimitMiddleware`` protects the API before any route code runs:

1. If ``Content-Length`` declares a body larger than the limit for the path,
   the request is answered with HTTP 413 immediately. The body is never read.
2. Otherwise every ``http.request`` message is counted as it streams in, so
   requests without ``Content-Length`` (chunked transfer) are limited too. The
   middleware never buffers the body: messages are passed through unchanged.
3. When the running count exceeds the limit, the application is told the client
   disconnected (so it stops reading), any response the application then tries
   to send is discarded, and a 413 is sent instead. This is necessary because
   FastAPI converts errors raised while reading a body into HTTP 400.

Responses that started before the limit was crossed are passed through
untouched, and non-HTTP scopes (``lifespan``, ``websocket``) are not affected.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

INVALID_CONTENT_LENGTH_DETAIL = "Invalid Content-Length header."


@dataclass(frozen=True)
class BodyLimit:
    """Maximum body size in bytes and the client-facing 413 message."""

    max_bytes: int
    detail: str


class _InvalidContentLength(Exception):
    """Raised for a malformed or conflicting Content-Length header."""


def _declared_content_length(scope: Scope) -> int | None:
    values = {
        value.strip()
        for name, value in scope.get("headers", [])
        if name.lower() == b"content-length"
    }
    if not values:
        return None
    if len(values) > 1:
        raise _InvalidContentLength
    raw = values.pop()
    if not raw.isdigit():
        raise _InvalidContentLength
    return int(raw)


async def _send_json(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


class RequestSizeLimitMiddleware:
    """Reject request bodies larger than a per-path limit with HTTP 413."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_limit: BodyLimit,
        path_limits: Mapping[str, BodyLimit] | None = None,
    ) -> None:
        self.app = app
        self.default_limit = default_limit
        self.path_limits = dict(path_limits or {})

    def limit_for(self, path: str) -> BodyLimit:
        return self.path_limits.get(path.rstrip("/") or "/", self.default_limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = self.limit_for(path)

        try:
            declared = _declared_content_length(scope)
        except _InvalidContentLength:
            await _send_json(send, 400, INVALID_CONTENT_LENGTH_DETAIL)
            return

        if declared is not None and declared > limit.max_bytes:
            logger.warning(
                "Rejected request before reading body: Content-Length %d exceeds %d bytes (path=%s).",
                declared,
                limit.max_bytes,
                path,
            )
            await _send_json(send, 413, limit.detail)
            return

        received = 0
        exceeded = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                # Never read past the limit; tell the app the client went away.
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if exceeded and not response_started:
                # Discard the app's reaction to the truncated body; 413 follows.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not (exceeded and not response_started):
                raise
            # The error was caused by cutting off an oversized body.

        if exceeded and not response_started:
            logger.warning(
                "Rejected streamed request body over %d bytes (path=%s).", limit.max_bytes, path
            )
            await _send_json(send, 413, limit.detail)
