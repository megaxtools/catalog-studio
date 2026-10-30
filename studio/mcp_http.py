"""انتقال‌های شبکه‌ای MCP داخل خود استودیو: Streamable HTTP (/mcp) و SSE قدیمی (/mcp/sse)، به‌همراه احراز هویت و محافظ میزبان."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import db
from .config import PORT
from .mcp_core import Server, StudioAPI

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("CATALOG_STUDIO_ALLOWED_HOSTS", "").split(",") if h.strip()}

_server: Server | None = None
_sse_sessions: dict[str, asyncio.Queue] = {}


def server() -> Server:
    global _server
    if _server is None:
        _server = Server(StudioAPI(f"http://127.0.0.1:{PORT}"), read_only=lambda: bool(db.get_settings().get("mcp_read_only")))
    return _server


def _host(scope_headers: dict) -> str:
    h = scope_headers.get("host", "")
    if h.startswith("["):
        return h.split("]")[0] + "]"
    return h.rsplit(":", 1)[0].lower() if ":" in h else h.lower()


def is_local_host(host: str) -> bool:
    return host in LOCAL_HOSTS or host in EXTRA_HOSTS


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-api-key") or request.query_params.get("token") or request.path_params.get("token") or "").strip()


def check(request: Request) -> Response | None:
    st = db.get_settings()
    if not st.get("mcp_enabled", True):
        return JSONResponse({"error": "سرور MCP در تنظیمات استودیو خاموش است."}, status_code=403)
    token = (st.get("mcp_token") or "").strip()
    host = _host({k.decode(): v.decode() for k, v in request.scope["headers"]})
    if token:
        if not hmac.compare_digest(_token_from(request), token):
            return JSONResponse({"error": "توکن MCP نادرست است یا ارسال نشده (Authorization: Bearer <token>)."}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        return None
    if not is_local_host(host):
        return JSONResponse({"error": "برای دسترسی از بیرون از این رایانه، ابتدا در صفحه‌ی MCP استودیو یک توکن بسازید."}, status_code=401)
    origin = request.headers.get("origin", "")
    if origin and not any(h in origin for h in ("127.0.0.1", "localhost", "[::1]")) and not EXTRA_HOSTS:
        return JSONResponse({"error": "Origin غیرمجاز"}, status_code=403)
    return None


def _sid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Streamable HTTP
# ---------------------------------------------------------------------------

async def mcp_endpoint(request: Request):
    bad = check(request)
    if bad:
        return bad
    if request.method == "GET":
        if "text/event-stream" in request.headers.get("accept", ""):
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})
        return JSONResponse({"name": "mega-catalog-studio", "transport": "streamable-http", "hint": "POST JSON-RPC messages here."})
    if request.method == "DELETE":
        return Response(status_code=200)
    raw = await request.body()
    try:
        payload = json.loads(raw or b"null")
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    resp = await run_in_threadpool(server().handle_payload, payload)
    headers = {}
    msgs = payload if isinstance(payload, list) else [payload]
    if any(isinstance(m, dict) and m.get("method") == "initialize" for m in msgs):
        headers["Mcp-Session-Id"] = _sid()
    if resp is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(resp, headers=headers)


# ---------------------------------------------------------------------------
# SSE قدیمی (2024-11-05) برای کلاینت‌هایی که فقط SSE دارند
# ---------------------------------------------------------------------------

async def sse_endpoint(request: Request):
    bad = check(request)
    if bad:
        return bad
    sid = _sid()
    q: asyncio.Queue = asyncio.Queue()
    _sse_sessions[sid] = q
    tok = request.path_params.get("token") or request.query_params.get("token")
    base = f"/mcp/t/{tok}/messages" if request.path_params.get("token") else "/mcp/messages"
    endpoint = f"{base}?session_id={sid}" + (f"&token={tok}" if tok and not request.path_params.get("token") else "")

    async def gen():
        yield f"event: endpoint\ndata: {endpoint}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _sse_sessions.pop(sid, None)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def sse_messages(request: Request):
    bad = check(request)
    if bad:
        return bad
    sid = request.query_params.get("session_id", "")
    q = _sse_sessions.get(sid)
    if q is None:
        return JSONResponse({"error": "نشست SSE پیدا نشد."}, status_code=404)
    try:
        payload = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse({"error": "Parse error"}, status_code=400)
    resp = await run_in_threadpool(server().handle_payload, payload)
    if resp is not None:
        for r in (resp if isinstance(resp, list) else [resp]):
            await q.put(r)
    return Response(status_code=202)


ROUTES = [
    Route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    Route("/mcp/t/{token}", mcp_endpoint, methods=["GET", "POST", "DELETE"]),
    Route("/mcp/sse", sse_endpoint, methods=["GET"]),
    Route("/sse", sse_endpoint, methods=["GET"]),
    Route("/mcp/t/{token}/sse", sse_endpoint, methods=["GET"]),
    Route("/mcp/messages", sse_messages, methods=["POST"]),
    Route("/messages", sse_messages, methods=["POST"]),
    Route("/mcp/t/{token}/messages", sse_messages, methods=["POST"]),
]


class HostGuard:
    """رابط کاربری و API استودیو فقط از همین رایانه در دسترس باشد؛ از بیرون (مثلاً از طریق تونل) فقط مسیرهای MCP با توکن."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            host = _host(headers)
            path = scope.get("path", "")
            mcp_path = path == "/mcp" or path.startswith("/mcp/") or path in ("/sse", "/messages")
            if not is_local_host(host) and not mcp_path:
                res = JSONResponse({"error": "رابط استودیو فقط از همین رایانه در دسترس است."}, status_code=403)
                await res(scope, receive, send)
                return
        await self.app(scope, receive, send)
