"""ماژول «خودروها»: بانک مرجع خودروها (برند ← مدل ← تیپ) و انتخاب «سازگاری با خودرو» برای محصولات.

اگر این ماژول غیرفعال شود، سازگاری محصولات «همه‌ی خودروها» نمایش داده می‌شود، مقادیر ذخیره‌شده دست نمی‌خورند و
بقیه‌ی استودیو کار می‌کند.
"""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ... import db
from ...web import actor_of, pid, route
from .. import Module
from . import service

MIGRATIONS = [(1, """
CREATE TABLE IF NOT EXISTS veh_brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    slug TEXT UNIQUE NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    sort INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    auto_en INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS veh_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    slug TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    auto_en INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (brand_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_veh_models_brand ON veh_models(brand_id);
CREATE TABLE IF NOT EXISTS veh_trims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    slug TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    auto_en INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (model_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_veh_trims_model ON veh_trims(model_id)
""")]


def _health():
    s = service.stats()
    return (s["brands"] > 0, f"{s['brands']} برند، {s['models']} مدل، {s['trims']} تیپ")


MODULE = Module(
    id="vehicles", name="خودروها و سازگاری", version="1.0.0",
    description="بانک مرجع خودروها (برند، مدل، تیپ) با اسلاگ انگلیسی و انتخاب سازگاری محصولات فقط از همین بانک.",
    migrations=MIGRATIONS, init=service.seed, health=_health, tables=["veh_brands", "veh_models", "veh_trims"],
)
M = "vehicles"


@route("/api/vehicles/stats", module=M)
async def v_stats(request, body):
    return service.stats()


@route("/api/vehicles/brands", module=M)
async def v_brands(request, body):
    return service.brands(request.query_params.get("q", ""))


@route("/api/vehicles/brands/{id:int}/tree", module=M)
async def v_tree(request, body):
    return service.brand_tree(pid(request))


@route("/api/vehicles/search", module=M)
async def v_search(request, body):
    return service.search(request.query_params.get("q", ""), int(request.query_params.get("limit") or 60))


@route("/api/vehicles/describe", methods=("POST",), module=M)
async def v_describe(request, body):
    return service.describe(body.get("value"))


@route("/api/vehicles/normalize", methods=("POST",), module=M)
async def v_normalize(request, body):
    v = service.normalize(body.get("value"))
    return {"value": v, **service.describe(v)}


@route("/api/vehicles/suggest", methods=("POST",), module=M)
async def v_suggest(request, body):
    text = body.get("text") or ""
    if body.get("ai"):
        from .. import require
        require("ai")
        from ...ai import set_context
        from ...ai_studio import default_client

        def work():
            set_context(purpose="پیشنهاد سازگاری با خودرو", ref=body.get("ref") or "")
            client, _ = default_client(body.get("provider_id"))
            return service.ai_suggest(text, client)
        return await run_in_threadpool(work)
    return service.suggest(text)


@route("/api/vehicles/import", methods=("POST",), module=M)
async def v_import(request, body):
    rows = service.parse_upload(body["data_url"], body.get("name") or "x.xlsx", body.get("mapping")) if body.get("data_url") else body.get("rows") or []
    return await run_in_threadpool(service.import_rows, rows, actor_of(request))


@route("/api/vehicles/export", module=M)
async def v_export(request, body):
    rows = service.export_rows()
    if request.query_params.get("format") == "xlsx":
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "vehicles"
        heads = ["brand", "brand_en", "brand_slug", "model", "model_en", "model_slug", "type", "type_en", "type_slug"]
        ws.append(heads)
        for r in rows:
            ws.append([r.get(h, "") for h in heads])
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="vehicles.xlsx"'})
    return rows


@route("/api/vehicles/ai-english", methods=("POST",), module=M)
async def v_ai_english(request, body):
    from .. import require
    require("ai")
    from ...ai import set_context
    from ...ai_studio import default_client

    def work():
        set_context(purpose="نام انگلیسی خودروها", ref="vehicles")
        client, _ = default_client(body.get("provider_id"))
        out = {}
        for level in body.get("levels") or [body.get("level") or "brand"]:
            out[level] = service.ai_english(level, client, body.get("ids"), body.get("only_auto", True), bool(body.get("update_slugs")),
                                            int(body.get("limit") or 400), actor_of(request) if actor_of(request) != "ui" else "ai")
        return out
    return await run_in_threadpool(work)


# مسیرهای عمومی در انتها ثبت می‌شوند تا مسیرهای خاص بالا را نپوشانند
@route("/api/vehicles/{level:str}", methods=("POST",), module=M)
async def v_create(request, body):
    return service.save(request.path_params["level"], body, None, actor_of(request))


@route("/api/vehicles/{level:str}/{id:int}", methods=("GET", "PUT", "DELETE"), module=M)
async def v_item(request, body):
    level, vid = request.path_params["level"], pid(request)
    if request.method == "DELETE":
        return service.delete(level, vid, actor_of(request))
    if request.method == "PUT":
        return service.save(level, body, vid, actor_of(request))
    r = service.get(level, vid)
    if not r:
        raise ValueError("پیدا نشد.")
    r["path"] = service.path_of(level, vid)
    r["used_by"] = service.usage(level, vid)
    return r


db  # noqa: B018
