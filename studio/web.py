"""ثبت مسیرهای HTTP استودیو (مشترک بین هسته و ماژول‌ها).

هر مسیر می‌تواند به یک ماژول تعلق داشته باشد (`module=`). اگر آن ماژول غیرفعال یا خراب باشد، مسیر پاسخ 503 با پیام
فارسی می‌دهد و بقیه‌ی استودیو بدون مشکل کار می‌کند. مسیرهای ماژول‌های داخلی قدیمی‌تر بر اساس پیشوند مسیر
به ماژولشان نسبت داده می‌شوند (`modules.module_for_path`).
"""
from __future__ import annotations

import json
import traceback

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

routes: list = []


def route(path: str, methods=("GET",), module: str | None = None):
    def deco(fn):
        async def endpoint(request: Request):
            from . import modules
            mod = module or modules.module_for_path(request.method, path)
            if mod and not modules.is_enabled(mod):
                m = modules.get(mod)
                name = m.name if m else mod
                why = f" ({m.error})" if m and m.error else ""
                return JSONResponse({"error": f"ماژول «{name}» غیرفعال است{why}. از «سیستم ← ماژول‌ها» فعالش کنید.",
                                     "module_disabled": mod}, status_code=503)
            try:
                body = {}
                if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                    raw = await request.body()
                    body = json.loads(raw) if raw else {}
                res = await fn(request, body)
                if isinstance(res, Response):
                    return res
                return JSONResponse(res)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except PermissionError as exc:
                return JSONResponse({"error": str(exc)}, status_code=403)
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ in ("AIError", "AICancelled"):  # خطای سرویس هوش مصنوعی: پیام خوانا، نه خطای داخلی
                    return JSONResponse({"error": str(exc), "ai_error": True}, status_code=400)
                traceback.print_exc()
                return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)
        endpoint.__name__ = fn.__name__
        routes.append(Route(path, endpoint, methods=list(methods)))
        return fn
    return deco


def pid(request: Request, name: str = "id") -> int:
    return int(request.path_params[name])


def actor_of(request) -> str:
    """کانال درخواست: ui | mcp | api"""
    return request.headers.get("x-studio-client") or "api"
