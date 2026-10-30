"""ثبت همه‌ی فعالیت‌ها: هر درخواست تغییردهنده (و درخواست‌های آزمایشی/پیش‌نمایش) با ورودی، نتیجه، زمان و مدت در جدول activity."""
from __future__ import annotations

import json
import re
import time

from . import db

SECRET_KEYS = re.compile(r"(api_key|apikey|token|password|secret|authorization|mcp_token)", re.I)
LOG_GET = re.compile(r"^/api/(sources/detect|file|bg/preview-output|exports/\d+/download|catalogs/\d+/files)")
SKIP = re.compile(r"^/api/(summary|health)$")
MAX_REQ = 6000
MAX_RES = 3000

ACTIONS: list[tuple[str, str, str]] = [
    ("POST", r"^/api/sources/\d+/test-listing$", "آزمایش زنده‌ی صفحه‌ی دسته‌بندی"),
    ("POST", r"^/api/sources/\d+/test-product$", "آزمایش زنده‌ی صفحه‌ی محصول"),
    ("POST", r"^/api/sources/\d+/duplicate$", "کپی منبع"),
    ("POST", r"^/api/sources$", "ساخت منبع"),
    ("PUT", r"^/api/sources/\d+$", "ویرایش منبع"),
    ("DELETE", r"^/api/sources/\d+$", "حذف منبع"),
    ("POST", r"^/api/schemas", "ساخت/کپی اسکیما"),
    ("PUT", r"^/api/schemas/\d+$", "ویرایش اسکیما"),
    ("DELETE", r"^/api/schemas/\d+$", "حذف اسکیما"),
    ("POST", r"^/api/datasets$", "ساخت بانک داده"),
    ("POST", r"^/api/datasets/\d+/do/(\w[\w-]*)$", "کنترل اجرای بانک داده: {1}"),
    ("PUT", r"^/api/datasets/\d+$", "ویرایش تنظیمات بانک داده"),
    ("DELETE", r"^/api/datasets/\d+$", "حذف بانک داده"),
    ("POST", r"^/api/datasets/\d+/ai-add$", "افزودن محصول با هوش مصنوعی"),
    ("POST", r"^/api/datasets/\d+/ai-column$", "تولید یک ستون با هوش مصنوعی"),
    ("PUT", r"^/api/items/\d+$", "ویرایش محصول"),
    ("DELETE", r"^/api/items/\d+$", "حذف محصول"),
    ("POST", r"^/api/items/bulk$", "ویرایش گروهی محصولات"),
    ("POST", r"^/api/items/\d+/rescrape$", "استخراج/تولید دوباره‌ی محصول"),
    ("POST", r"^/api/items/\d+/ai$", "تولید هوش مصنوعی برای یک محصول"),
    ("POST", r"^/api/items/ai-clear$", "حذف خروجی هوش مصنوعی"),
    ("POST", r"^/api/items/\d+/fields$", "نوشتن فیلدها (ایجنت)"),
    ("POST", r"^/api/items/\d+/generate-image$", "تولید تصویر محصول"),
    ("POST", r"^/api/items/\d+/attach-image$", "پیوست تصویر به محصول"),
    ("POST", r"^/api/ai/assist$", "دستیار هوش مصنوعی"),
    ("POST", r"^/api/ai/preview$", "پیش‌نمایش تولید هوش مصنوعی"),
    ("POST", r"^/api/ai/jobs$", "شروع تولید گروهی با هوش مصنوعی"),
    ("POST", r"^/api/ai/jobs/\d+/(\w+)$", "کنترل اجرای هوش مصنوعی: {1}"),
    ("POST", r"^/api/ai/datasets$", "ساخت بانک داده با هوش مصنوعی"),
    ("POST", r"^/api/ai/providers$", "ساخت اتصال هوش مصنوعی"),
    ("PUT", r"^/api/ai/providers/\d+$", "ویرایش اتصال هوش مصنوعی"),
    ("DELETE", r"^/api/ai/providers/\d+$", "حذف اتصال هوش مصنوعی"),
    ("POST", r"^/api/ai/providers/\d+/(\w[\w-]*)$", "آزمایش/فهرست مدل‌های اتصال: {1}"),
    ("POST", r"^/api/ai/profiles", "ساخت/کپی قالب تولید"),
    ("PUT", r"^/api/ai/profiles/\d+$", "ویرایش قالب تولید"),
    ("DELETE", r"^/api/ai/profiles/\d+$", "حذف قالب تولید"),
    ("POST", r"^/api/rules/test$", "آزمایش قاعده‌ی متن"),
    ("POST", r"^/api/rules$", "ساخت قاعده‌ی متن"),
    ("PUT", r"^/api/rules/\d+$", "ویرایش قاعده‌ی متن"),
    ("DELETE", r"^/api/rules/\d+$", "حذف قاعده‌ی متن"),
    ("POST", r"^/api/mappings$", "ثبت نگاشت"),
    ("DELETE", r"^/api/mappings/\d+$", "حذف نگاشت"),
    ("POST", r"^/api/queue$", "افزودن به صف"),
    ("POST", r"^/api/queue/toggle$", "روشن/خاموش کردن صف"),
    ("POST", r"^/api/queue/\d+/(\w[\w-]*)$", "کنترل صف: {1}"),
    ("PUT", r"^/api/queue/\d+$", "ویرایش کار صف"),
    ("DELETE", r"^/api/queue/\d+$", "حذف از صف"),
    ("POST", r"^/api/exports$", "ساخت خروجی"),
    ("POST", r"^/api/exports/\d+/cancel$", "لغو خروجی"),
    ("POST", r"^/api/exports/suggest-name$", ""),
    ("PUT", r"^/api/catalogs/\d+$", "ویرایش مشخصات خروجی"),
    ("DELETE", r"^/api/(catalogs|exports)/\d+$", "حذف خروجی"),
    ("PUT", r"^/api/catalogs/\d+/rows/\d+$", "ویرایش ردیف خروجی"),
    ("POST", r"^/api/catalogs/\d+/rows/bulk$", "ویرایش گروهی ردیف‌های خروجی"),
    ("POST", r"^/api/catalogs/\d+/ai$", "ویرایش خروجی با هوش مصنوعی"),
    ("POST", r"^/api/catalogs/\d+/rows/\d+/images/(\w[\w-]*)$", "مدیریت تصویر خروجی: {1}"),
    ("POST", r"^/api/catalogs/\d+/rebuild$", "بازسازی فایل‌های خروجی"),
    ("POST", r"^/api/catalogs/\d+/sync$", "اعمال ویرایش‌های خروجی روی بانک داده"),
    ("POST", r"^/api/catalogs/\d+/revert$", "بازگردانی تغییر خروجی"),
    ("POST", r"^/api/bg$", "شروع پردازش تصاویر"),
    ("POST", r"^/api/bg/\d+/(\w+)$", "کنترل پردازش تصاویر: {1}"),
    ("POST", r"^/api/align/preview$", "پیش‌نمایش ترازبندی"),
    ("POST", r"^/api/models/[\w-]+/download$", "دانلود مدل حذف پس‌زمینه"),
    ("PUT", r"^/api/settings$", "ویرایش تنظیمات"),
    ("POST", r"^/api/mcp/(\w+)$", "MCP: {1}"),
    ("POST", r"^/api/system/(\w[\w-]*)$", "سیستم: {1}"),
    ("GET", r"^/api/sources/detect$", "تشخیص منبع از لینک"),
    ("GET", r"^/api/file$", "دانلود فایل"),
    ("POST", r"^/mcp", "درخواست MCP"),
]
_ACTIONS = [(m, re.compile(p), label) for m, p, label in ACTIONS]


def action_label(method: str, path: str) -> str:
    for m, rx, label in _ACTIONS:
        if m == method:
            mm = rx.match(path)
            if mm:
                return label.replace("{1}", mm.group(1)) if "{1}" in label and mm.groups() else label
    return ""


def mask(obj):
    if isinstance(obj, dict):
        return {k: ("•••" if SECRET_KEYS.search(str(k)) and v else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(x) for x in obj[:200]]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 200:
        return obj[:60] + f"…[{len(obj)} نویسه]"
    return obj


def _text(raw: bytes, limit: int) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw.decode("utf-8"))
        return json.dumps(mask(data), ensure_ascii=False)[:limit]
    except Exception:  # noqa: BLE001
        try:
            return raw.decode("utf-8", "replace")[:limit]
        except Exception:  # noqa: BLE001
            return f"[{len(raw)} bytes]"


class ActivityMiddleware:
    """میان‌افزار ASGI: هر درخواست تغییردهنده یا آزمایشی با بدنه‌ی ورودی و خلاصه‌ی پاسخ در پایگاه داده ثبت می‌شود."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        if not (path.startswith("/api/") or path.startswith("/mcp")) or SKIP.match(path):
            return await self.app(scope, receive, send)
        if method == "GET" and not LOG_GET.match(path):
            return await self.app(scope, receive, send)
        if method == "GET" and path == "/api/file" and b"download=1" not in (scope.get("query_string") or b""):
            return await self.app(scope, receive, send)  # پیش‌نمایش تصاویر بندانگشتی؛ فقط دانلود فایل ثبت می‌شود
        if method in ("OPTIONS", "HEAD"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        client = headers.get("x-studio-client") or ("mcp" if path.startswith("/mcp") else "api")
        t0 = time.time()
        req_chunks: list[bytes] = []
        res_chunks: list[bytes] = []
        status = [0]
        size = [0]

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request" and sum(len(c) for c in req_chunks) < MAX_REQ * 2:
                req_chunks.append(msg.get("body", b""))
            return msg

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status[0] = msg["status"]
                ct = dict((k.decode("latin1").lower(), v.decode("latin1")) for k, v in msg.get("headers", []))
                snd.json = "json" in ct.get("content-type", "")
            elif msg["type"] == "http.response.body":
                b = msg.get("body", b"")
                size[0] += len(b)
                if getattr(snd, "json", False) and sum(len(c) for c in res_chunks) < MAX_RES * 2:
                    res_chunks.append(b)
            await send(msg)

        err = ""
        try:
            await self.app(scope, recv, snd)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                req = _text(b"".join(req_chunks), MAX_REQ)
                if scope.get("query_string"):
                    req = (f"?{scope['query_string'].decode('latin1')[:500]} " + req).strip()
                res = _text(b"".join(res_chunks), MAX_RES) if res_chunks else (f"[{size[0]} bytes]" if size[0] else "")
                label = action_label(method, path)
                if path.startswith("/mcp") and req:
                    try:
                        j = json.loads(b"".join(req_chunks).decode("utf-8"))
                        if isinstance(j, dict) and j.get("method") == "tools/call":
                            label = f"MCP: {(j.get('params') or {}).get('name', '')}"
                        elif isinstance(j, dict):
                            label = f"MCP: {j.get('method', '')}"
                    except Exception:  # noqa: BLE001
                        pass
                if not path.endswith("suggest-name"):
                    if status[0] >= 400 and not err:
                        err = res[:500]
                    db.ex("INSERT INTO activity(ts, client, method, path, action, status, ms, request, response, error) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          [db.now(), client, method, path, label, status[0] or 500, int((time.time() - t0) * 1000), req, res, err])
            except Exception:  # noqa: BLE001
                pass


def prune(keep: int = 300_000):
    try:
        mx = db.val("SELECT MAX(id) FROM activity") or 0
        if mx > keep:
            db.ex("DELETE FROM activity WHERE id < ?", [mx - keep])
        mx = db.val("SELECT MAX(id) FROM ai_calls") or 0
        if mx > keep:
            db.ex("DELETE FROM ai_calls WHERE id < ?", [mx - keep])
    except Exception:  # noqa: BLE001
        pass
