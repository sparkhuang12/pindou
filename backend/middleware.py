from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .dependencies import request_ip
from .state import store
from .rate_limit import limiter


def register_middleware(app: FastAPI) -> None:
    class AuditMiddleware:
        def __init__(self, downstream: Any):
            self.downstream = downstream

        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            if scope.get("type") != "http":
                await self.downstream(scope, receive, send)
                return
            if scope.get("method") == "GET":
                await self.downstream(scope, receive, send)
                return
            request = Request(scope, receive)
            method = request.method
            path = request.url.path
            started = time.perf_counter()
            request_id = request.headers.get("x-request-id", "").strip()[:36] or uuid.uuid4().hex
            status_code = 500
            failure = ""

            async def send_with_request_id(message: dict[str, Any]) -> None:
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = int(message.get("status", 500))
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                    message = {**message, "headers": headers}
                await send(message)

            try:
                limit_rule = {
                    ("POST", "/api/auth/login"): (10, 900, "login"),
                    ("POST", "/api/auth/register"): (5, 3600, "register"),
                    ("POST", "/api/projects"): (20, 3600, "upload"),
                    ("POST", "/api/messages"): (20, 3600, "message"),
                }.get((method, path))
                if limit_rule:
                    limit, window, name = limit_rule
                    allowed, retry_after = limiter.allow(
                        f"{name}:{request_ip(request)}", limit, window
                    )
                    if not allowed:
                        response = JSONResponse(
                            {"detail": "请求过于频繁，请稍后再试"},
                            status_code=429,
                            headers={"Retry-After": str(retry_after)},
                        )
                        await response(scope, receive, send_with_request_id)
                        return
                await self.downstream(scope, receive, send_with_request_id)
            except Exception as exc:
                failure = type(exc).__name__
                raise
            finally:
                should_log = (
                    path.startswith("/api/")
                    and path not in {"/api/health", "/api/config", "/api/palette"}
                    and method in {"POST", "PUT", "PATCH", "DELETE"}
                )
                if should_log:
                    user_id = store.read_session_token(request.cookies.get(settings.session_cookie))
                    try:
                        store.record_activity(
                            user_id=user_id,
                            action=f"{method} {path}",
                            category="request",
                            status="success" if status_code < 400 else "failed",
                            request_id=request_id,
                            method=method,
                            path=path,
                            ip_address=request_ip(request),
                            user_agent=request.headers.get("user-agent", ""),
                            input_data={"query": dict(request.query_params)},
                            output_data={"http_status": status_code},
                            error_message=failure,
                            duration_ms=round((time.perf_counter() - started) * 1000),
                        )
                    except Exception:
                        pass

    app.add_middleware(AuditMiddleware)
