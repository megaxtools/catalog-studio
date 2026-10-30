"""رابط برنامه‌نویسی (HTTP API) استودیو و سرو کردن رابط کاربری."""
from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import db, services
from .config import APP_NAME, APP_NAME_EN, DATA_DIR, MODELS_DIR, STATIC_DIR, VERSION
from .engine.errors import DEFAULT_POLICIES, describe_kinds
from .engine.extract import CANONICAL_FIELDS, explorer
from .engine.fetcher import BrowserFetcher, HttpFetcher, api_listing_page, links_from_html, set_query_param
from .engine.runner import MANAGER, rescrape_item
from .engine.scrape import Fetchers, scrape_product
from .export import EXPORTS
from . import ai as ai_mod, ai_gen, ai_studio, rules as rules_mod, jobqueue, agent_ops, mcp_core, mcp_setup, mcp_http
from . import align as align_mod
from . import catalogs
from PIL import Image
from .images import BG_JOBS, MODELS, default_bg_output, download_model, download_state, model_status, rembg_available

routes: list = []


class _NoCacheStatic(StaticFiles):
    """پس از به‌روزرسانی نسخه، مرورگر فایل‌های قدیمی رابط را از حافظه‌ی نهان نخواند."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


def route(path: str, methods=("GET",)):
    def deco(fn):
        async def endpoint(request: Request):
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
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)
        routes.append(Route(path, endpoint, methods=list(methods)))
        return fn
    return deco


def pid(request: Request, name: str = "id") -> int:
    return int(request.path_params[name])


# ---------------------------------------------------------------------------
# عمومی
# ---------------------------------------------------------------------------

@route("/api/bootstrap")
async def bootstrap(request, body):
    sources = services.list_sources()
    return {
        "app": {"name": APP_NAME, "name_en": APP_NAME_EN, "version": VERSION, "data_dir": str(DATA_DIR)},
        "settings": db.get_settings(),
        "sources": sources,
        "schemas": services.list_schemas(),
        "canonical_fields": services.canonical_fields(sources),
        "errors": describe_kinds(),
        "default_policies": DEFAULT_POLICIES,
        "rembg_models": model_status(),
        "rembg_lib": rembg_available(),
        "ai_profiles": [{"id": p["id"], "name": p["name"]} for p in ai_gen.list_profiles()],
        "ai_providers": db.val("SELECT COUNT(*) FROM ai_providers"),
        "ai_modes": ai_gen.MODES,
    }


@route("/api/summary")
async def summary(request, body):
    active = [services.get_dataset(r["id"]) for r in
              db.q("SELECT id FROM datasets ORDER BY CASE WHEN status IN ('running','waiting','starting') THEN 0 ELSE 1 END, updated_at DESC LIMIT 8")]
    incidents = db.q("SELECT i.*, d.title AS dataset_title FROM incidents i JOIN datasets d ON d.id=i.dataset_id WHERE i.status='open' ORDER BY i.id DESC")
    for i in incidents:
        i["options"] = db.jload(i["options"], [])
    return {
        "counts": {
            "datasets": db.val("SELECT COUNT(*) FROM datasets"),
            "products": db.val("SELECT COUNT(*) FROM items WHERE status IN ('done','partial')"),
            "partial": db.val("SELECT COUNT(*) FROM items WHERE status='partial'"),
            "running": db.val("SELECT COUNT(*) FROM datasets WHERE status IN ('running','starting','waiting')"),
            "exports": db.val("SELECT COUNT(*) FROM exports WHERE status='completed'"),
            "sources": db.val("SELECT COUNT(*) FROM sources"),
        },
        "active": active,
        "incidents": incidents,
        "recent_exports": [export_row(r) for r in db.q("SELECT * FROM exports ORDER BY id DESC LIMIT 5")],
        "bg_jobs": [bg_row(r) for r in db.q("SELECT * FROM bg_jobs WHERE status IN ('running','pending') ORDER BY id DESC")],
        "queue": {"enabled": db.get_settings().get("queue_enabled", True),
                  "queued": db.val("SELECT COUNT(*) FROM queue_jobs WHERE status='queued'"),
                  "active": db.q1("SELECT id, title, status FROM queue_jobs WHERE status IN ('running','ai_running') LIMIT 1")},
        "ai_running": db.val("SELECT COUNT(*) FROM ai_jobs WHERE status IN ('running','pending')"),
    }


def actor_of(request) -> str:
    return request.headers.get("x-studio-client") or "api"


@route("/api/health")
async def health(request, body):
    from .config import VERSION
    return {"ok": True, "app": "mega-catalog-studio", "version": VERSION}


@route("/api/settings", methods=("GET", "PUT"))
async def settings_ep(request, body):
    if request.method == "PUT":
        return db.set_settings(body)
    return db.get_settings()


@route("/api/system")
async def system(request, body):
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "data_dir": str(DATA_DIR),
            "models_dir": str(MODELS_DIR), "rembg_lib": rembg_available(), "models": model_status()}
    try:
        import playwright  # noqa: F401
        info["playwright"] = True
    except Exception:  # noqa: BLE001
        info["playwright"] = False
    try:
        import onnxruntime
        info["onnxruntime"] = onnxruntime.__version__
    except Exception:  # noqa: BLE001
        info["onnxruntime"] = ""
    return info


@route("/api/system/check-browser", methods=("POST",))
async def check_browser(request, body):
    def work():
        s = db.get_settings()
        b = BrowserFetcher(s, {}, headless=True)
        try:
            b.start()
            return {"ok": True, "channel": b.channel_used}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": getattr(exc, "message", str(exc)), "detail": getattr(exc, "detail", "")}
        finally:
            b.close()
    return await run_in_threadpool(work)


@route("/api/open-folder", methods=("POST",))
async def open_folder(request, body):
    p = Path(body.get("path", ""))
    if not p.exists():
        raise ValueError("مسیر وجود ندارد.")
    target = p if p.is_dir() else p.parent
    if os.name == "nt":
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True}


@route("/api/file")
async def file_ep(request, body):
    p = Path(request.query_params.get("path", ""))
    allowed = [Path(db.get_settings()["output_root"]).resolve(), DATA_DIR.resolve()]
    rp = p.resolve()
    if not any(rp == a or a in rp.parents for a in allowed) and request.query_params.get("any") != "1":
        return JSONResponse({"error": "دسترسی به این مسیر مجاز نیست."}, status_code=403)
    if not rp.exists() or not rp.is_file():
        return JSONResponse({"error": "فایل پیدا نشد."}, status_code=404)
    return FileResponse(rp, filename=rp.name if request.query_params.get("download") else None)


# ---------------------------------------------------------------------------
# منابع
# ---------------------------------------------------------------------------

@route("/api/sources", methods=("GET", "POST"))
async def sources_ep(request, body):
    if request.method == "POST":
        return services.save_source(body.get("config") or body)
    return services.list_sources()


@route("/api/sources/detect")
async def detect_ep(request, body):
    s = services.detect_source(request.query_params.get("url", ""))
    return {"source": s}


@route("/api/sources/{id:int}", methods=("GET", "PUT", "DELETE"))
async def source_ep(request, body):
    sid = pid(request)
    if request.method == "PUT":
        return services.save_source(body.get("config") or body, sid)
    if request.method == "DELETE":
        if db.val("SELECT COUNT(*) FROM datasets WHERE source_id=?", [sid]):
            raise ValueError("این منبع بانک داده دارد؛ ابتدا بانک‌های آن را حذف کنید یا منبع را غیرفعال نگه دارید.")
        db.ex("DELETE FROM sources WHERE id=?", [sid])
        return {"ok": True}
    return services.get_source(sid)


@route("/api/sources/{id:int}/duplicate", methods=("POST",))
async def source_dup(request, body):
    s = services.get_source(pid(request))
    cfg = dict(s["config"])
    cfg["name"] = cfg.get("name", "") + " (کپی)"
    cfg["key"] = cfg.get("key", "source") + "-copy"
    return services.save_source(cfg)


def _test_cfg(request, body) -> dict:
    if body.get("config"):
        return body["config"]
    return services.get_source(pid(request))["config"]


@route("/api/sources/{id:int}/test-listing", methods=("POST",))
async def test_listing(request, body):
    cfg = _test_cfg(request, body)
    url = body.get("url") or cfg.get("sample_category_url")
    if not url:
        raise ValueError("لینک دسته‌بندی نمونه را وارد کنید.")
    max_links = int(body.get("max_links", 40))

    def work():
        s = db.get_settings()
        lcfg = cfg.get("listing", {}) or {}
        f = Fetchers(s, cfg)
        try:
            mode = lcfg.get("mode", "browser")
            ptype = (lcfg.get("pagination") or {}).get("type", "scroll")
            info = {}
            if mode == "api":
                links, info = api_listing_page(f.http, url, lcfg, int(lcfg.get("api", {}).get("start_page", 1)))
            elif mode == "http":
                b = f.http.bundle(url)
                links = links_from_html(b.html, b.base_url, lcfg)
            elif ptype in ("param", "none"):
                links, info = f.browser.links_on_page(url, lcfg)
            else:
                links, info = f.browser.collect_links(url, lcfg, max_links)
            nxt = ""
            if mode != "api" and ptype == "param":
                pag = lcfg.get("pagination") or {}
                nxt = set_query_param(url, pag.get("param", "page"), int(pag.get("start", 1)) + 1)
            return {"ok": True, "count": len(links), "links": links[:max_links], "info": info, "next_page_url": nxt}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": getattr(exc, "message", str(exc)), "detail": getattr(exc, "detail", traceback.format_exc()[-1500:])}
        finally:
            f.close()
    return await run_in_threadpool(work)


@route("/api/sources/{id:int}/test-product", methods=("POST",))
async def test_product(request, body):
    cfg = _test_cfg(request, body)
    url = body.get("url") or cfg.get("sample_product_url")
    if not url:
        raise ValueError("لینک محصول نمونه را وارد کنید.")
    show = bool(body.get("show_browser"))

    def work():
        s = db.get_settings()
        f = Fetchers(s, cfg, headless=False if show else None)
        bundle = None
        try:
            rec, how, bundle = scrape_product(url, cfg, f, [], screenshot=True, explain=True)
            res = {"ok": True, "record": rec, "how": how}
        except Exception as exc:  # noqa: BLE001
            rec = getattr(exc, "partial", None)
            res = {"ok": False, "error": getattr(exc, "message", str(exc)), "kind": getattr(exc, "kind", ""),
                   "detail": getattr(exc, "detail", "") or traceback.format_exc()[-1500:], "record": rec}
        finally:
            f.close()
        if bundle is not None:
            res["explorer"] = explorer(bundle)
            if bundle.screenshot and Path(bundle.screenshot).exists():
                res["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(Path(bundle.screenshot).read_bytes()).decode()
                Path(bundle.screenshot).unlink(missing_ok=True)
        return res
    return await run_in_threadpool(work)


@route("/api/sources/{id:int}/explore", methods=("POST",))
async def explore_page(request, body):
    """فقط کاوشگر داده (بدون استخراج) برای صفحه‌ای که هنوز پیکربندی ندارد."""
    cfg = _test_cfg(request, body)
    url = body.get("url")
    mode = body.get("mode") or cfg.get("product", {}).get("mode", "browser")

    def work():
        s = db.get_settings()
        f = Fetchers(s, cfg)
        try:
            from .engine.scrape import fetch_bundle
            b = fetch_bundle(url, cfg, f, mode=mode, screenshot=True)
            res = {"ok": True, "explorer": explorer(b)}
            if b.screenshot and Path(b.screenshot).exists():
                res["screenshot"] = "data:image/jpeg;base64," + base64.b64encode(Path(b.screenshot).read_bytes()).decode()
            return res
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": getattr(exc, "message", str(exc)), "detail": getattr(exc, "detail", "")}
        finally:
            f.close()
    return await run_in_threadpool(work)


# ---------------------------------------------------------------------------
# اسکیماها
# ---------------------------------------------------------------------------

@route("/api/schemas", methods=("GET", "POST"))
async def schemas_ep(request, body):
    if request.method == "POST":
        sid = db.ex("INSERT INTO schemas(name, description, columns, is_default, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    [body.get("name") or "اسکیمای جدید", body.get("description", ""), db.jdump(body.get("columns", [])), 0, db.now(), db.now()])
        return services.get_schema(sid)
    return services.list_schemas()


@route("/api/schemas/{id:int}", methods=("GET", "PUT", "DELETE"))
async def schema_ep(request, body):
    sid = pid(request)
    if request.method == "PUT":
        if body.get("is_default"):
            db.ex("UPDATE schemas SET is_default=0")
        db.ex("UPDATE schemas SET name=?, description=?, columns=?, is_default=?, updated_at=? WHERE id=?",
              [body.get("name"), body.get("description", ""), db.jdump(body.get("columns", [])), 1 if body.get("is_default") else 0, db.now(), sid])
        return services.get_schema(sid)
    if request.method == "DELETE":
        if db.val("SELECT COUNT(*) FROM schemas") <= 1:
            raise ValueError("دست‌کم یک اسکیما باید باقی بماند.")
        db.ex("UPDATE datasets SET schema_id=NULL WHERE schema_id=?", [sid])
        db.ex("DELETE FROM schemas WHERE id=?", [sid])
        return {"ok": True}
    return services.get_schema(sid)


@route("/api/schemas/{id:int}/duplicate", methods=("POST",))
async def schema_dup(request, body):
    s = services.get_schema(pid(request))
    nid = db.ex("INSERT INTO schemas(name, description, columns, is_default, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                [s["name"] + " (کپی)", s["description"], db.jdump(s["columns"]), 0, db.now(), db.now()])
    return services.get_schema(nid)


# ---------------------------------------------------------------------------
# بانک‌های داده و اجرا
# ---------------------------------------------------------------------------

@route("/api/datasets", methods=("GET", "POST"))
async def datasets_ep(request, body):
    if request.method == "POST":
        url = (body.get("category_url") or "").strip()
        if not url.startswith("http"):
            raise ValueError("لینک صفحه‌ی دسته‌بندی معتبر نیست.")
        sid = body.get("source_id") or (services.detect_source(url) or {}).get("id")
        if not sid:
            raise ValueError("منبع این لینک شناخته نشد؛ منبع را دستی انتخاب کنید.")
        limit = body.get("limit")
        limit = int(limit) if limit not in (None, "", 0, "0") else None
        policies = {**DEFAULT_POLICIES, **(body.get("policies") or {})}
        opts = {"duplicates": body.get("duplicates", "skip"), "show_browser": bool(body.get("show_browser"))}
        if body.get("category_label"):
            opts["category_label_manual"] = True
        if body.get("ai_after"):
            opts["ai_after"] = body["ai_after"]
        ds = services.create_dataset(int(sid), url, limit, body.get("schema_id"), opts, policies, body.get("category_label", ""))
        if body.get("start", True):
            MANAGER.start(ds["id"])
        return services.get_dataset(ds["id"])
    ai_studio.AI_DATASETS.heal()
    return services.list_datasets()


@route("/api/datasets/{id:int}", methods=("GET", "PUT", "DELETE"))
async def dataset_ep(request, body):
    did = pid(request)
    if request.method == "DELETE":
        if MANAGER.is_running(did):
            raise ValueError("ابتدا اجرای این بانک را متوقف کنید.")
        for t in ("items", "incidents"):
            db.ex(f"DELETE FROM {t} WHERE dataset_id=?", [did])
        db.ex("DELETE FROM logs WHERE scope='dataset' AND ref_id=?", [did])
        db.ex("DELETE FROM datasets WHERE id=?", [did])
        return {"ok": True}
    if request.method == "PUT":
        d = services.get_dataset(did)
        fields = {}
        opts = dict(d["options"])
        if "name" in body and body["name"] and body["name"] != d["name"]:
            from .textutil import safe_filename
            fields["name"] = safe_filename(body["name"])
            opts["custom_name"] = True
        if "title" in body and body["title"]:
            fields["title"] = body["title"]
            opts["custom_name"] = True
        if "category_label" in body:
            fields["category_label"] = body["category_label"]
            opts["category_label_manual"] = True
        if "item_limit" in body:
            v = body["item_limit"]
            fields["item_limit"] = int(v) if v not in (None, "", 0, "0") else None
            if fields["item_limit"] is None or fields["item_limit"] > (d["item_limit"] or 0):
                fields["discovery_done"] = 0 if not d["discovery_done"] or d["status"] != "completed" else d["discovery_done"]
        if "policies" in body:
            fields["policies"] = {**d["policies"], **body["policies"]}
        if "options" in body:
            opts.update(body["options"])
        if "schema_id" in body:
            fields["schema_id"] = body["schema_id"]
        if "notes" in body:
            fields["notes"] = body["notes"]
        fields["options"] = opts
        fields["updated_at"] = db.now()
        db.update("datasets", did, **fields)
        if opts.get("custom_name") is not True:
            services.refresh_dataset_naming(did)
        return services.get_dataset(did)
    d = services.get_dataset(did)
    if not d:
        return JSONResponse({"error": "پیدا نشد"}, status_code=404)
    d["running"] = MANAGER.is_running(did)
    return d


@route("/api/datasets/{id:int}/do/{action:str}", methods=("POST",))
async def dataset_action(request, body):
    did = pid(request)
    action = request.path_params["action"]
    dsx = services.get_dataset(did)
    if dsx and ai_studio.is_ai_dataset(dsx):
        if action in ("start", "resume", "retry-failed", "rediscover"):
            if action == "retry-failed":
                db.ex("UPDATE items SET status='queued', error='' WHERE dataset_id=? AND status IN ('failed','skipped') AND url LIKE 'ai-generated:%'", [did])
            ai_studio.AI_DATASETS.start(did)
        elif action in ("pause", "stop"):
            ai_studio.AI_DATASETS.pause(did, action)
        return services.get_dataset(did)
    if action in ("start", "resume"):
        MANAGER.start(did)
    elif action == "pause":
        MANAGER.pause(did)
    elif action == "stop":
        MANAGER.stop(did)
    elif action == "retry-failed":
        db.ex("UPDATE items SET status='queued', error='' WHERE dataset_id=? AND status IN ('failed','skipped')", [did])
        MANAGER.start(did)
    elif action == "rediscover":
        db.update("datasets", did, discovery_done=0, cursor={})
        MANAGER.start(did)
    else:
        raise ValueError("عملیات ناشناخته")
    return services.get_dataset(did)


@route("/api/datasets/{id:int}/items")
async def dataset_items(request, body):
    did = pid(request)
    qp = request.query_params
    where, args = ["dataset_id=?"], [did]
    if qp.get("status"):
        sts = qp["status"].split(",")
        where.append(f"status IN ({','.join('?' * len(sts))})")
        args += sts
    if qp.get("q"):
        where.append("(data LIKE ? OR url LIKE ?)")
        args += [f"%{qp['q']}%", f"%{qp['q']}%"]
    page = int(qp.get("page", 1))
    size = min(200, int(qp.get("size", 50)))
    total = db.val(f"SELECT COUNT(*) FROM items WHERE {' AND '.join(where)}", args)
    rows = db.q(f"SELECT * FROM items WHERE {' AND '.join(where)} ORDER BY seq, id LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])
    items = []
    for r in rows:
        it = services.item_row(r)
        d = it["data"]
        items.append({"id": it["id"], "url": it["url"], "status": it["status"], "seq": it["seq"], "error": it["error"],
                      "missing": it["missing"], "title": it["overrides"].get("title") or rules_mod.cleaned(it).get("title", ""),
                      "brand": d.get("brand", ""), "image": d.get("featured_image", ""),
                      "gallery_count": len(d.get("gallery") or []), "specs_count": len(d.get("specifications") or []),
                      "has_manual": bool(it["manual"]), "has_overrides": bool(it["overrides"]), "scraped_at": it["scraped_at"],
                      "has_ai": any(k != "__meta" for k in (it["ai"] or {})), "ai_error": ((it["ai"] or {}).get("__meta") or {}).get("error", "")})
    return {"total": total, "page": page, "size": size, "items": items}


@route("/api/datasets/{id:int}/logs")
async def dataset_logs(request, body):
    did = pid(request)
    after = int(request.query_params.get("after", 0))
    level = request.query_params.get("level")
    sql = "SELECT * FROM logs WHERE scope='dataset' AND ref_id=? AND id>?"
    args = [did, after]
    if level:
        sql += " AND level=?"
        args.append(level)
    else:
        sql += " AND level<>'debug'"
    return db.q(sql + " ORDER BY id DESC LIMIT 300", args)[::-1]


@route("/api/datasets/{id:int}/incidents")
async def dataset_incidents(request, body):
    rows = db.q("SELECT * FROM incidents WHERE dataset_id=? ORDER BY id DESC LIMIT 200", [pid(request)])
    for r in rows:
        r["options"] = db.jload(r["options"], [])
    return rows


@route("/api/datasets/{id:int}/preview", methods=("POST",))
async def dataset_preview(request, body):
    did = pid(request)
    schema = services.get_schema(body.get("schema_id") or services.get_dataset(did)["schema_id"])
    rows = db.q("SELECT * FROM items WHERE dataset_id=? AND status IN ('done','partial') ORDER BY seq, id LIMIT 30", [did])
    items = [services.item_row(r) for r in rows]
    headers, data, warnings = services.build_rows(schema, items, db.get_settings())
    return {"headers": headers, "rows": data, "warnings": warnings}


# ---------------------------------------------------------------------------
# آیتم‌ها
# ---------------------------------------------------------------------------

@route("/api/items/{id:int}", methods=("GET", "PUT", "DELETE"))
async def item_ep(request, body):
    iid = pid(request)
    if request.method == "DELETE":
        old = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
        if old:
            db.history("item", iid, "*", {k: old.get(k) for k in ("url", "data", "manual", "overrides", "ai", "status")}, "", actor=actor_of(request),
                       action="delete", parent_id=old["dataset_id"])
        db.ex("DELETE FROM items WHERE id=?", [iid])
        return {"ok": True}
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
    if not it:
        return JSONResponse({"error": "پیدا نشد"}, status_code=404)
    if request.method == "PUT":
        fields = {"updated_at": db.now()}
        if "overrides" in body:
            fields["overrides"] = {k: v for k, v in body["overrides"].items() if v is not None}
        if "manual" in body:
            fields["manual"] = body["manual"]
        if "data" in body:
            fields["data"] = {**it["data"], **body["data"]}
        if body.get("status") in ("done", "partial", "skipped", "queued"):
            fields["status"] = body["status"]
        if "ai_clear" in body or "ai_set" in body:
            ai = dict(it.get("ai") or {})
            if "ai_clear" in body:
                for k in body["ai_clear"] or list(ai.keys()):
                    ai.pop(k, None)
            for k, v in (body.get("ai_set") or {}).items():
                ai[k] = {"value": v, "mode": "overwrite", "model": body.get("ai_model") or "assistant", "at": db.now()}
                fields.setdefault("overrides", dict(it.get("overrides") or {})).pop(k, None)
                fields.setdefault("manual", dict(it.get("manual") or {})).pop(k, None)
            fields["ai"] = ai
        services.record_item_change(it, fields, actor_of(request))
        db.update("items", iid, **fields)
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
    ds = services.get_dataset(it["dataset_id"])
    schema = services.get_schema(ds["schema_id"])
    settings = db.get_settings()
    preview = {}
    for col in schema["columns"]:
        v, flag = services.column_value(col, it, ds, settings)
        preview[col["key"]] = {"value": v, "flag": flag}
    it["preview"] = preview
    it["schema"] = schema
    return it


@route("/api/items/bulk", methods=("POST",))
async def items_bulk(request, body):
    ids = [int(i) for i in body.get("ids", [])]
    if not ids:
        raise ValueError("هیچ محصولی انتخاب نشده است.")
    mode = body.get("mode", "merge")  # merge | replace
    n = 0
    for iid in ids:
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
        if not it:
            continue
        fields = {"updated_at": db.now()}
        if "manual" in body:
            fields["manual"] = body["manual"] if mode == "replace" else {**it["manual"], **body["manual"]}
        if "overrides" in body:
            fields["overrides"] = {**it["overrides"], **body["overrides"]}
        if body.get("status"):
            fields["status"] = body["status"]
        if body.get("delete"):
            db.history("item", iid, "*", {k: it.get(k) for k in ("url", "data", "manual", "overrides", "ai", "status")}, "",
                       actor=actor_of(request), action="delete", parent_id=it["dataset_id"], note="bulk")
        else:
            services.record_item_change(it, fields, actor_of(request), note="bulk")
            db.update("items", iid, **fields)
        n += 1
    if body.get("delete"):
        db.ex(f"DELETE FROM items WHERE id IN ({','.join('?' * len(ids))})", ids)
    return {"updated": n}


@route("/api/items/{id:int}/rescrape", methods=("POST",))
async def item_rescrape(request, body):
    iid = pid(request)
    it = db.q1("SELECT url FROM items WHERE id=?", [iid])
    if it and it["url"].startswith(ai_studio.AI_URL_PREFIX):
        return await run_in_threadpool(ai_studio.AI_DATASETS.regenerate_item, iid)
    return await run_in_threadpool(rescrape_item, iid)


# ---------------------------------------------------------------------------
# خطاها و تصمیم‌ها
# ---------------------------------------------------------------------------

@route("/api/incidents/{id:int}/resolve", methods=("POST",))
async def incident_resolve(request, body):
    iid = pid(request)
    inc = db.q1("SELECT * FROM incidents WHERE id=?", [iid])
    if not inc or inc["status"] != "open":
        raise ValueError("این مورد دیگر فعال نیست.")
    action = body.get("action")
    allowed = [o["action"] for o in db.jload(inc["options"], [])]
    if action not in allowed:
        raise ValueError("این گزینه برای این خطا مجاز نیست.")
    db.update("incidents", iid, status="resolved", decision=action, apply_all=1 if body.get("apply_all") else 0, resolved_at=db.now())
    if not MANAGER.is_running(inc["dataset_id"]):
        if action == "pause":
            db.update("datasets", inc["dataset_id"], status="paused")
        else:
            MANAGER.start(inc["dataset_id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# نگاشت‌ها
# ---------------------------------------------------------------------------

@route("/api/mappings", methods=("GET", "POST"))
async def mappings_ep(request, body):
    if request.method == "POST":
        rows = body.get("rows") or [body]
        n = 0
        for r in rows:
            if not r.get("source_value") or not r.get("target_slug"):
                continue
            sid = r.get("source_id") or None
            existing = db.q1("SELECT id FROM mappings WHERE kind=? AND source_value=? AND " + ("source_id=?" if sid else "source_id IS NULL"),
                             [r["kind"], r["source_value"].strip(), *([sid] if sid else [])])
            if existing:
                db.ex("UPDATE mappings SET target_slug=?, target_label=? WHERE id=?", [r["target_slug"].strip(), r.get("target_label", ""), existing["id"]])
            else:
                db.ex("INSERT INTO mappings(kind, source_id, source_value, target_slug, target_label, created_at) VALUES(?,?,?,?,?,?)",
                      [r["kind"], sid, r["source_value"].strip(), r["target_slug"].strip(), r.get("target_label", ""), db.now()])
            n += 1
        return {"saved": n}
    kind = request.query_params.get("kind")
    sql = "SELECT m.*, s.name AS source_name FROM mappings m LEFT JOIN sources s ON s.id=m.source_id"
    args = []
    if kind:
        sql += " WHERE m.kind=?"
        args.append(kind)
    return db.q(sql + " ORDER BY m.kind, m.source_value", args)


@route("/api/mappings/{id:int}", methods=("DELETE",))
async def mapping_del(request, body):
    db.ex("DELETE FROM mappings WHERE id=?", [pid(request)])
    return {"ok": True}


@route("/api/mappings/unmapped")
async def mappings_unmapped(request, body):
    return services.unmapped_values()


@route("/api/mappings/targets")
async def mappings_targets(request, body):
    return db.q("SELECT DISTINCT kind, target_slug, target_label FROM mappings ORDER BY target_slug")


# ---------------------------------------------------------------------------
# خروجی‌ها
# ---------------------------------------------------------------------------

def export_row(r):
    r = dict(r)
    r["dataset_ids"] = db.jload(r["dataset_ids"], [])
    r["options"] = db.jload(r["options"], {})
    r["result"] = db.jload(r["result"], {})
    return r


@route("/api/exports", methods=("GET", "POST"))
async def exports_ep(request, body):
    if request.method == "POST":
        eid = EXPORTS.create(body)
        return export_row(db.q1("SELECT * FROM exports WHERE id=?", [eid]))
    return [export_row(r) for r in db.q("SELECT * FROM exports ORDER BY id DESC LIMIT 100")]


@route("/api/exports/{id:int}", methods=("GET", "DELETE"))
async def export_ep(request, body):
    eid = pid(request)
    if request.method == "DELETE":
        db.ex("DELETE FROM exports WHERE id=?", [eid])
        return {"ok": True}
    return export_row(db.q1("SELECT * FROM exports WHERE id=?", [eid]))


@route("/api/exports/{id:int}/cancel", methods=("POST",))
async def export_cancel(request, body):
    EXPORTS.stop(pid(request))
    return {"ok": True}


# ---------------------------------------------------------------------------
# کاتالوگ‌های نهایی (مدیریت خروجی‌ها)
# ---------------------------------------------------------------------------

@route("/api/catalogs")
async def catalogs_list(request, body):
    qp = request.query_params
    return catalogs.list_catalogs(qp.get("q", ""), qp.get("state", ""))


@route("/api/catalogs/{id:int}", methods=("GET", "PUT", "DELETE"))
async def catalog_ep(request, body):
    eid = pid(request)
    if request.method == "DELETE":
        return await run_in_threadpool(catalogs.delete_catalog, eid, request.query_params.get("files") == "1", actor_of(request))
    if request.method == "PUT":
        return catalogs.update_meta(eid, body, actor_of(request))
    return catalogs.detail(eid)


@route("/api/catalogs/{id:int}/rows")
async def catalog_rows(request, body):
    qp = request.query_params
    ids = [int(x) for x in (qp.get("ids") or "").split(",") if x]
    return catalogs.get_rows(pid(request), int(qp["schema_id"]) if qp.get("schema_id") else None, qp.get("q", ""), qp.get("filter", ""),
                             int(qp.get("page") or 1), max(1, min(500, int(qp.get("size") or 50))), ids or None)


@route("/api/catalogs/{id:int}/rows/{rid:int}", methods=("PUT", "DELETE"))
async def catalog_row(request, body):
    eid, rid = pid(request), int(request.path_params["rid"])
    if request.method == "DELETE":
        catalogs.delete_row(eid, rid, actor_of(request))
        return {"ok": True}
    catalogs.update_row(eid, rid, body, actor_of(request))
    return catalogs.get_rows(eid, int(body.get("schema_id")) if body.get("schema_id") else None, ids=[rid])["rows"][0]


@route("/api/catalogs/{id:int}/rows/bulk", methods=("POST",))
async def catalog_bulk(request, body):
    return catalogs.bulk(pid(request), body, actor_of(request))


@route("/api/catalogs/{id:int}/rows/{rid:int}/images/{action:str}", methods=("POST",))
async def catalog_image(request, body):
    eid, rid, a = pid(request), int(request.path_params["rid"]), request.path_params["action"]

    def work():
        try:
            return {"ok": True, "row": catalogs.image_action(eid, rid, a, body, actor_of(request))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    return await run_in_threadpool(work)


@route("/api/catalogs/{id:int}/ai", methods=("POST",))
async def catalog_ai(request, body):
    """ویرایش ردیف‌های خروجی با هوش مصنوعی (هر ستون، تصاویر)، تک‌ردیف یا گروهی، در پس‌زمینه."""
    eid = pid(request)
    e = catalogs.get_export(eid)
    sid = int(body.get("schema_id") or catalogs.schema_ids(e["options"])[0])
    schema = catalogs.schema_of(e, sid)
    base = ai_gen.get_profile(int(body["profile_id"]))["config"] if body.get("profile_id") else None
    cfg = ai_gen.build_config(schema, body.get("columns") or [], base)
    for k in ("provider_id", "model", "seo_keywords", "extra_context"):
        if body.get(k):
            cfg[k] = body[k]
    if not cfg["fields"] and not cfg["images_list"]:
        raise ValueError("هیچ ستونی برای تولید انتخاب نشده است.")
    opts = {"catalog_id": eid, "schema_id": sid, "row_ids": [int(i) for i in body.get("row_ids") or []], "config": cfg,
            "overwrite_ai": bool(body.get("overwrite")), "title": f"ویرایش خروجی «{e.get('title') or e['name']}»"}
    if body.get("wait") and len(opts["row_ids"]) == 1:
        # یک ردیف: همان لحظه (برای دکمه‌ی AI کنار هر فیلد)
        def work():
            from .ai import set_context
            set_context(purpose="ویرایش کاتالوگ نهایی (تک‌فیلد)", ref=f"export:{eid}")
            client = ai_gen.client_for(cfg)
            try:
                res = catalogs.ai_row(eid, opts["row_ids"][0], sid, cfg, client, db.get_settings(), overwrite=True)
                return {"ok": True, "generated": res, "row": catalogs.get_rows(eid, sid, ids=opts["row_ids"])["rows"][0]}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
        return await run_in_threadpool(work)
    jid = ai_gen.AI_JOBS.create((e["dataset_ids"] or [0])[0], int(body.get("profile_id") or 0) or None, opts)
    return ai_job_row(db.q1("SELECT * FROM ai_jobs WHERE id=?", [jid]))


@route("/api/catalogs/{id:int}/rebuild", methods=("POST",))
async def catalog_rebuild(request, body):
    eid = pid(request)
    db.history("export", eid, "files", "", "rebuild", actor=actor_of(request), action="rebuild", parent_id=eid)
    return await run_in_threadpool(catalogs.write_files, eid)


@route("/api/catalogs/{id:int}/sync", methods=("POST",))
async def catalog_sync(request, body):
    return await run_in_threadpool(catalogs.sync_to_items, pid(request), body.get("schema_id"), actor_of(request))


@route("/api/catalogs/{id:int}/schemas", methods=("POST",))
async def catalog_add_schema(request, body):
    return await run_in_threadpool(catalogs.add_schema, pid(request), int(body["schema_id"]), actor_of(request))


@route("/api/exports/suggest-name", methods=("POST",))
async def export_suggest(request, body):
    ids = body.get("dataset_ids") or []
    return {"name": services.suggest_export_name(ids) if ids else ""}


# ---------------------------------------------------------------------------
# حذف پس‌زمینه
# ---------------------------------------------------------------------------

def bg_row(r):
    r = dict(r)
    r["options"] = db.jload(r["options"], {})
    return r


@route("/api/bg", methods=("GET", "POST"))
async def bg_ep(request, body):
    if request.method == "POST":
        st = db.get_settings()
        rembg = body.get("rembg", True) is not False
        if "align" in body or "align_options" in body:
            al = body.get("align")
            align = (align_mod.normalize(al if isinstance(al, dict) else body.get("align_options"), st.get("image_align"))
                     if (al is None or al) else False)
        elif "size" in body or "padding" in body:  # کلاینت‌های نسخه‌های قبل
            align = align_mod.from_legacy(int(body.get("size", 1280)), float(body.get("padding", 6)))
        else:
            align = align_mod.normalize(st.get("image_align"))
        jid = BG_JOBS.create(body.get("input_path", ""), body.get("output_path") or None, {
            "model": body.get("model") or st["rembg_model"], "rembg": rembg, "align": align,
            "overwrite": bool(body.get("overwrite")), "engine": body.get("engine", "auto"),
            "keep_intermediate": body.get("keep_intermediate", True) is not False, "redo_rembg": bool(body.get("redo_rembg"))})
        return bg_row(db.q1("SELECT * FROM bg_jobs WHERE id=?", [jid]))
    return [bg_row(r) for r in db.q("SELECT * FROM bg_jobs ORDER BY id DESC LIMIT 50")]


@route("/api/bg/preview-output")
async def bg_preview(request, body):
    p = request.query_params.get("path", "")
    if not p:
        return {"output": ""}
    inp = Path(p).expanduser()
    rembg = request.query_params.get("rembg", "1") != "0"
    count = 0
    if inp.exists() and inp.is_dir():
        from .images import list_images
        count = len(list_images(inp, exclude=default_bg_output(inp, rembg)))
    return {"output": str(default_bg_output(inp, rembg)), "exists": inp.exists(), "images": count}


@route("/api/align/preview", methods=("POST",))
async def align_preview(request, body):
    """پیش‌نمایش قبل/بعد ترازبندی روی چند تصویر نمونه از یک پوشه، یک فایل یا تصویر بارگذاری‌شده."""
    def work():
        from .images import BgRemover, list_images
        st = db.get_settings()
        opts = align_mod.normalize(body.get("options"), st.get("image_align"))
        remover = BgRemover(body.get("model") or st["rembg_model"]) if body.get("rembg") else None
        limit = max(1, min(12, int(body.get("limit") or (3 if remover else 6))))
        samples: list[tuple[str, Image.Image]] = []
        if body.get("data_url"):
            samples.append((body.get("file_name") or "تصویر بارگذاری‌شده", align_mod.decode_data_url(body["data_url"])))
        else:
            p = Path(str(body.get("path") or "")).expanduser()
            if not p.exists():
                raise ValueError("این مسیر وجود ندارد.")
            if p.is_file():
                files = [p]
            else:
                files = list_images(p, exclude=default_bg_output(p, bool(remover)))
                # از هر پوشه‌ی محصول یک تصویر (ترجیحاً feature) تا نمونه‌ها متنوع باشند
                pick, seen = [], set()
                for f in sorted(files, key=lambda x: (str(x.parent), not x.stem.startswith("feature"), x.name)):
                    if f.parent not in seen:
                        seen.add(f.parent)
                        pick.append(f)
                files = (pick + [f for f in files if f not in pick])[:limit]
            for f in files[:limit]:
                with Image.open(f) as im:
                    im.load()
                    samples.append((str(f.relative_to(p)) if p.is_dir() else f.name, im.copy()))
        out = []
        for name, im in samples:
            try:
                out.append(align_mod.preview_image(im, opts, remover, name))
            except Exception as exc:  # noqa: BLE001
                out.append({"name": name, "error": str(exc)})
        return {"ok": True, "options": opts, "samples": out}
    try:
        return await run_in_threadpool(work)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@route("/api/bg/{id:int}/{action:str}", methods=("POST",))
async def bg_action(request, body):
    jid = pid(request)
    a = request.path_params["action"]
    if a == "stop":
        BG_JOBS.stop(jid)
    elif a == "resume":
        BG_JOBS.start(jid)
    elif a == "delete":
        db.ex("DELETE FROM bg_jobs WHERE id=?", [jid])
    return {"ok": True}


@route("/api/models")
async def models_ep(request, body):
    return {"models": model_status(), "rembg_lib": rembg_available(),
            "downloads": {n: download_state(n) for n in MODELS}}


@route("/api/models/{name:str}/download", methods=("POST",))
async def model_download(request, body):
    return download_model(request.path_params["name"])


# ---------------------------------------------------------------------------
# لاگ‌ها
# ---------------------------------------------------------------------------

@route("/api/logs")
async def logs_ep(request, body):
    qp = request.query_params
    sql, args = "SELECT * FROM logs WHERE 1=1", []
    if qp.get("scope"):
        sql += " AND scope=?"
        args.append(qp["scope"])
    if qp.get("ref_id"):
        sql += " AND ref_id=?"
        args.append(int(qp["ref_id"]))
    if qp.get("level"):
        sql += " AND level=?"
        args.append(qp["level"])
    else:
        sql += " AND level<>'debug'"
    return db.q(sql + " ORDER BY id DESC LIMIT 500", args)


def _paged(table: str, qp, where: list[str], args: list, search_cols: list[str], order: str = "id DESC", light: list[str] | None = None):
    if qp.get("q"):
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in search_cols) + ")")
        args += [f"%{qp['q']}%"] * len(search_cols)
    if qp.get("from"):
        where.append("ts >= ?")
        args.append(qp["from"])
    if qp.get("to"):
        where.append("ts <= ?")
        args.append(qp["to"])
    w = (" WHERE " + " AND ".join(where)) if where else ""
    size = max(1, min(500, int(qp.get("size") or 100)))
    page = max(1, int(qp.get("page") or 1))
    total = db.val(f"SELECT COUNT(*) FROM {table}{w}", args) or 0
    cols = ", ".join(light) if light else "*"
    rows = db.q(f"SELECT {cols} FROM {table}{w} ORDER BY {order} LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])
    return {"total": total, "page": page, "size": size, "rows": rows}


@route("/api/activity")
async def activity_ep(request, body):
    """همه‌ی فعالیت‌ها (درخواست‌های تغییردهنده، آزمایش‌ها، پیش‌نمایش‌ها و درخواست‌های MCP)."""
    qp = request.query_params
    if qp.get("id"):
        return db.q1("SELECT * FROM activity WHERE id=?", [int(qp["id"])])
    where, args = [], []
    if qp.get("client"):
        where.append("client=?")
        args.append(qp["client"])
    if qp.get("errors") == "1":
        where.append("status>=400")
    return _paged("activity", qp, where, args, ["path", "action", "request", "error"],
                  light=["id", "ts", "client", "method", "path", "action", "status", "ms", "substr(request,1,300) AS request", "substr(error,1,300) AS error"])


@route("/api/ai-calls")
async def ai_calls_ep(request, body):
    """همه‌ی درخواست‌های ارسال‌شده به سرویس‌های هوش مصنوعی با پرامپت، پاسخ، توکن و مدت."""
    qp = request.query_params
    if qp.get("id"):
        return db.q1("SELECT * FROM ai_calls WHERE id=?", [int(qp["id"])])
    where, args = [], []
    if qp.get("errors") == "1":
        where.append("ok=0")
    if qp.get("item_id"):
        where.append("item_id=?")
        args.append(int(qp["item_id"]))
    r = _paged("ai_calls", qp, where, args, ["provider", "model", "purpose", "ref", "error", "prompt"],
               light=["id", "ts", "provider", "model", "kind", "purpose", "ref", "item_id", "ok", "status", "substr(error,1,300) AS error", "ms", "tokens"])
    r["sum"] = db.q1("SELECT COUNT(*) AS calls, COALESCE(SUM(tokens),0) AS tokens, COALESCE(SUM(1-ok),0) AS errors FROM ai_calls")
    return r


@route("/api/history")
async def history_ep(request, body):
    """تاریخچه‌ی تغییرات داده (محصولات و خروجی‌ها) با مقدار قبلی و جدید."""
    qp = request.query_params
    if qp.get("id"):
        return db.q1("SELECT * FROM history WHERE id=?", [int(qp["id"])])
    where, args = [], []
    for k in ("entity", "actor", "action"):
        if qp.get(k):
            where.append(f"{k}=?")
            args.append(qp[k])
    for k in ("entity_id", "parent_id"):
        if qp.get(k):
            where.append(f"{k}=?")
            args.append(int(qp[k]))
    return _paged("history", qp, where, args, ["field", "old", "new", "note"],
                  light=["id", "ts", "entity", "entity_id", "parent_id", "field", "action", "actor", "substr(old,1,400) AS old", "substr(new,1,400) AS new", "note"])


@route("/api/history/{id:int}/revert", methods=("POST",))
async def history_revert(request, body):
    """بازگرداندن مقدار قبلی یک تغییر (برای ویرایش محصولات و ردیف‌های خروجی)."""
    h = db.q1("SELECT * FROM history WHERE id=?", [pid(request)])
    if not h:
        raise ValueError("رکورد تاریخچه پیدا نشد.")
    try:
        old = json.loads(h["old"]) if h["old"] not in ("", None) else ""
    except ValueError:
        old = h["old"]
    actor = actor_of(request)
    if h["entity"] == "item" and ":" in h["field"]:
        layer, key = h["field"].split(":", 1)
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [h["entity_id"]]))
        if not it:
            raise ValueError("محصول دیگر وجود ندارد.")
        if layer in ("overrides", "manual"):
            d = dict(it.get(layer) or {})
            if old in ("", None):
                d.pop(key, None)
            else:
                d[key] = old
            services.record_item_change(it, {layer: d}, actor, note=f"revert:{h['id']}")
            db.update("items", it["id"], **{layer: d, "updated_at": db.now()})
        elif layer == "ai":
            ai = dict(it.get("ai") or {})
            if old in ("", None):
                ai.pop(key, None)
            else:
                ai[key] = {**(ai.get(key) or {}), "value": old, "at": db.now()}
            services.record_item_change(it, {"ai": ai}, actor, note=f"revert:{h['id']}")
            db.update("items", it["id"], ai=ai, updated_at=db.now())
        else:
            raise ValueError("این نوع تغییر قابل بازگردانی نیست.")
        return {"ok": True}
    if h["entity"] == "export_row":
        from . import catalogs
        catalogs.revert(h, actor)
        return {"ok": True}
    raise ValueError("این نوع تغییر قابل بازگردانی نیست.")


# ---------------------------------------------------------------------------
# قواعد متن
# ---------------------------------------------------------------------------

@route("/api/rules", methods=("GET", "POST"))
async def rules_ep(request, body):
    if request.method == "POST":
        pos = (db.val("SELECT MAX(position) FROM text_rules") or 0) + 1
        rid = db.ex("""INSERT INTO text_rules(name, enabled, source_id, target, action, find, value, flags, position, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    [body.get("name") or "قاعده‌ی جدید", 1 if body.get("enabled", True) else 0, body.get("source_id") or None,
                     body.get("target") or "*", body.get("action") or "remove", body.get("find", ""), body.get("value", ""),
                     db.jdump(body.get("flags") or {"split": "|"}), pos, db.now()])
        rules_mod.bump()
        return {"id": rid}
    return {"rules": rules_mod.all_rules(), "actions": rules_mod.ACTIONS, "text_fields": rules_mod.TEXT_FIELDS}


@route("/api/rules/{id:int}", methods=("PUT", "DELETE"))
async def rule_ep(request, body):
    rid = pid(request)
    if request.method == "DELETE":
        db.ex("DELETE FROM text_rules WHERE id=?", [rid])
    else:
        cur = db.q1("SELECT * FROM text_rules WHERE id=?", [rid])
        merged = {**cur, **{k: v for k, v in body.items() if k in ("name", "enabled", "source_id", "target", "action", "find", "value", "flags", "position")}}
        db.ex("""UPDATE text_rules SET name=?, enabled=?, source_id=?, target=?, action=?, find=?, value=?, flags=?, position=? WHERE id=?""",
              [merged["name"], 1 if merged["enabled"] else 0, merged["source_id"] or None, merged["target"], merged["action"],
               merged["find"] or "", merged["value"] or "", merged["flags"] if isinstance(merged["flags"], str) else db.jdump(merged["flags"]),
               merged["position"], rid])
    rules_mod.bump()
    return {"ok": True}


@route("/api/rules/test", methods=("POST",))
async def rules_test(request, body):
    return rules_mod.test(body.get("text", ""), body.get("rule"), body.get("target") or "long_description", body.get("source_id"))


# ---------------------------------------------------------------------------
# هوش مصنوعی
# ---------------------------------------------------------------------------

@route("/api/ai/providers", methods=("GET", "POST"))
async def ai_providers(request, body):
    if request.method == "POST":
        pid_ = db.ex("""INSERT INTO ai_providers(name, kind, base_url, api_key, text_model, image_model, image_mode, headers, proxy, timeout_s,
                        created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                     [body.get("name") or "اتصال جدید", body.get("kind", "openai"), (body.get("base_url") or "").strip(),
                      (body.get("api_key") or "").strip(), body.get("text_model", ""), body.get("image_model", ""),
                      body.get("image_mode", "images_api"), db.jdump(body.get("headers") or {}), body.get("proxy", ""),
                      int(body.get("timeout_s") or 90), db.now(), db.now()])
        return ai_mod.public_provider(ai_mod.get_provider(pid_))
    rows = [ai_mod.public_provider(ai_mod.provider_row(r)) for r in db.q("SELECT * FROM ai_providers ORDER BY id")]
    return {"providers": rows, "presets": ai_mod.PRESETS}


@route("/api/ai/providers/{id:int}", methods=("GET", "PUT", "DELETE"))
async def ai_provider(request, body):
    i = pid(request)
    if request.method == "DELETE":
        db.ex("DELETE FROM ai_providers WHERE id=?", [i])
        return {"ok": True}
    p = ai_mod.get_provider(i)
    if request.method == "PUT":
        key = body.get("api_key")
        if key is None or key == "" and body.get("keep_key", True):
            key = p["api_key"]
        db.ex("""UPDATE ai_providers SET name=?, kind=?, base_url=?, api_key=?, text_model=?, image_model=?, image_mode=?, headers=?,
                 proxy=?, timeout_s=?, updated_at=? WHERE id=?""",
              [body.get("name", p["name"]), body.get("kind", p["kind"]), (body.get("base_url", p["base_url"]) or "").strip(), key.strip(),
               body.get("text_model", p["text_model"]), body.get("image_model", p["image_model"]), body.get("image_mode", p["image_mode"]),
               db.jdump(body.get("headers", p["headers"]) or {}), body.get("proxy", p["proxy"]), int(body.get("timeout_s") or p["timeout_s"] or 90),
               db.now(), i])
        p = ai_mod.get_provider(i)
    return ai_mod.public_provider(p)


@route("/api/ai/providers/{id:int}/{action:str}", methods=("POST",))
async def ai_provider_action(request, body):
    p = ai_mod.get_provider(pid(request))
    a = request.path_params["action"]

    def work():
        c = ai_mod.AIClient(p)
        try:
            if a == "test":
                return c.ping()
            if a == "models":
                return {"ok": True, "models": c.list_models()}
            if a == "test-image":
                data = c.image(body.get("prompt") or "A simple red engine oil bottle on a white background, product photo")
                return {"ok": True, "image": "data:image/png;base64," + base64.b64encode(data).decode()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "عملیات ناشناخته"}
    return await run_in_threadpool(work)


@route("/api/ai/profiles", methods=("GET", "POST"))
async def ai_profiles(request, body):
    if request.method == "POST":
        cfg = body.get("config") or ai_gen.DEFAULT_PROFILE
        i = db.ex("INSERT INTO ai_profiles(name, description, config, created_at, updated_at) VALUES(?,?,?,?,?)",
                  [body.get("name") or "قالب جدید", body.get("description", ""), db.jdump(cfg), db.now(), db.now()])
        return ai_gen.get_profile(i)
    return {"profiles": ai_gen.list_profiles(), "modes": ai_gen.MODES, "default": ai_gen.DEFAULT_PROFILE}


@route("/api/ai/profiles/{id:int}", methods=("GET", "PUT", "DELETE"))
async def ai_profile(request, body):
    i = pid(request)
    if request.method == "DELETE":
        db.ex("DELETE FROM ai_profiles WHERE id=?", [i])
        return {"ok": True}
    if request.method == "PUT":
        db.ex("UPDATE ai_profiles SET name=?, description=?, config=?, updated_at=? WHERE id=?",
              [body.get("name"), body.get("description", ""), db.jdump(body.get("config") or {}), db.now(), i])
    return ai_gen.get_profile(i)


@route("/api/ai/profiles/{id:int}/duplicate", methods=("POST",))
async def ai_profile_dup(request, body):
    p = ai_gen.get_profile(pid(request))
    i = db.ex("INSERT INTO ai_profiles(name, description, config, created_at, updated_at) VALUES(?,?,?,?,?)",
              [p["name"] + " (کپی)", p["description"], db.jdump(p["config"]), db.now(), db.now()])
    return ai_gen.get_profile(i)


@route("/api/ai/preview", methods=("POST",))
async def ai_preview(request, body):
    def work():
        try:
            cfg = _job_config(body, item_id=int(body["item_id"]))
            return {"ok": True, **ai_gen.preview(cfg, int(body["item_id"]), bool(body.get("images")))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    return await run_in_threadpool(work)


@route("/api/ai/sample-items")
async def ai_sample_items(request, body):
    did = request.query_params.get("dataset_id")
    sql = "SELECT i.id, i.dataset_id, i.data, d.title AS ds_title FROM items i JOIN datasets d ON d.id=i.dataset_id WHERE i.status IN ('done','partial')"
    args = []
    if did:
        sql += " AND i.dataset_id=?"
        args.append(int(did))
    rows = db.q(sql + " ORDER BY i.id DESC LIMIT 60", args)
    return [{"id": r["id"], "dataset_id": r["dataset_id"], "ds_title": r["ds_title"], "title": db.jload(r["data"], {}).get("title", "")} for r in rows]


def ai_job_row(r):
    r = dict(r)
    r["options"] = {k: v for k, v in db.jload(r["options"], {}).items() if k not in ("_done_ids", "config")}
    r["dataset"] = db.q1("SELECT id, title, code FROM datasets WHERE id=?", [r["dataset_id"]])
    r["profile"] = db.q1("SELECT id, name FROM ai_profiles WHERE id=?", [r["profile_id"]]) if r["profile_id"] else {"id": 0, "name": r["options"].get("title") or "تولید سفارشی"}
    return r


def _job_config(body: dict, dataset_id: int | None = None, item_id: int | None = None) -> dict:
    """تنظیمات تولید: قالب ذخیره‌شده، یا ستون‌های انتخابی (با قالب اختیاری به‌عنوان پایه‌ی لحن و سئو)، یا ستون‌های AI اسکیما."""
    if body.get("config"):
        return body["config"]
    base = ai_gen.get_profile(int(body["profile_id"]))["config"] if body.get("profile_id") else None
    if body.get("columns") is None and not body.get("use_schema"):
        if not base:
            raise ValueError("قالب تولید یا ستون‌ها را انتخاب کنید.")
        return base
    if item_id and not dataset_id:
        dataset_id = db.val("SELECT dataset_id FROM items WHERE id=?", [item_id])
    ds = services.get_dataset(int(dataset_id or body.get("dataset_id")))
    schema = services.get_schema(body.get("schema_id") or ds["schema_id"])
    cfg = ai_gen.build_config(schema, None if body.get("use_schema") else body.get("columns"), base)
    for k in ("provider_id", "model", "image_provider_id", "seo_keywords", "extra_context"):
        if body.get(k):
            cfg[k] = body[k]
    if not cfg["fields"] and not cfg["images_list"]:
        raise ValueError("هیچ ستونی برای تولید انتخاب نشده است." if not body.get("use_schema") else "در اسکیمای این بانک، ستونی برای تولید با هوش مصنوعی تنظیم نشده است.")
    return cfg


@route("/api/ai/columns")
async def ai_columns(request, body):
    """ستون‌های اسکیما با قابلیت تولید، حالت و دستور پیش‌فرض (برای انتخاب در رابط و ایجنت‌ها)."""
    sid = request.query_params.get("schema_id")
    did = request.query_params.get("dataset_id")
    schema = services.get_schema(int(sid) if sid else (services.get_dataset(int(did))["schema_id"] if did else None))
    out = []
    for c in schema["columns"]:
        if c.get("include") is False:
            continue
        out.append({"key": c["key"], "label": c.get("label") or c["key"], "kind": c.get("kind"), "input": c.get("input") or "text",
                    "capable": ai_gen.ai_capable(c), "image": c.get("input") in ("image", "images"),
                    "schema_ai": c.get("kind") == "ai" or c.get("ai_mode") not in (None, "", "off"),
                    "mode": c.get("ai_mode") if c.get("ai_mode") not in (None, "", "off") else "fill_missing",
                    "instruction": ai_gen.default_instruction(c) if ai_gen.ai_capable(c) else ""})
    return {"schema_id": schema["id"], "columns": out}


@route("/api/ai/jobs", methods=("GET", "POST"))
async def ai_jobs(request, body):
    if request.method == "POST":
        did = int(body["dataset_id"])
        opts = {"scope": body.get("scope", "all"), "item_ids": body.get("item_ids") or [], "overwrite_ai": bool(body.get("overwrite_ai")),
                "images": body.get("images", True)}
        if body.get("columns") is not None or body.get("use_schema") or body.get("config"):
            opts["config"] = _job_config(body, did)
            opts["title"] = body.get("title") or ("ستون‌های AI اسکیما" if body.get("use_schema") else f"تولید {len(opts['config']['fields']) + len(opts['config']['images_list'])} ستون")
            if body.get("save_as"):
                p = db.ex("INSERT INTO ai_profiles(name, description, config, created_at, updated_at) VALUES(?,?,?,?,?)",
                          [body["save_as"], "ساخته‌شده از انتخاب ستون‌ها", db.jdump(opts["config"]), db.now(), db.now()])
                opts["title"] = body["save_as"]
                jid = ai_gen.AI_JOBS.create(did, p, opts)
            else:
                jid = ai_gen.AI_JOBS.create(did, int(body.get("profile_id") or 0) or None, opts)
        else:
            jid = ai_gen.AI_JOBS.create(did, int(body["profile_id"]), opts)
        return ai_job_row(db.q1("SELECT * FROM ai_jobs WHERE id=?", [jid]))
    ai_gen.AI_JOBS.heal()
    did = request.query_params.get("dataset_id")
    rows = db.q("SELECT * FROM ai_jobs" + (" WHERE dataset_id=?" if did else "") + " ORDER BY id DESC LIMIT 60", [int(did)] if did else [])
    return [ai_job_row(r) for r in rows]


@route("/api/ai/jobs/{id:int}/{action:str}", methods=("POST",))
async def ai_job_action(request, body):
    jid = pid(request)
    a = request.path_params["action"]
    if a == "stop":
        ai_gen.AI_JOBS.stop(jid)
    elif a == "resume":
        db.update("ai_jobs", jid, error="")
        ai_gen.AI_JOBS.start(jid)
    elif a == "delete":
        if ai_gen.AI_JOBS.is_running(jid):
            raise ValueError("ابتدا اجرا را متوقف کنید.")
        db.ex("DELETE FROM ai_jobs WHERE id=?", [jid])
    return {"ok": True}


@route("/api/items/{id:int}/ai", methods=("POST",))
async def item_ai(request, body):
    iid = pid(request)

    def work():
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
        ds = services.get_dataset(it["dataset_id"])
        schema = services.get_schema(ds["schema_id"])
        try:
            if body.get("all_empty"):  # همه‌ی ستون‌های خالیِ قابل تولید
                body["columns"] = [{"key": c["key"], "mode": "fill_missing"} for c in schema["columns"]
                                   if ai_gen.ai_capable(c) and c.get("include") is not False]
            cfg = _job_config(body, ds["id"])
            out = ai_gen.generate_for_item(it, cfg, ds, schema, ai_gen.client_for(cfg), db.get_settings(), overwrite_ai=True,
                                           with_images=bool(body.get("images", True)))
            ai_gen.save_results(iid, out["results"])
            return {"ok": True, "generated": list(out["results"].keys())}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    return await run_in_threadpool(work)


@route("/api/items/ai-clear", methods=("POST",))
async def items_ai_clear(request, body):
    ids = [int(i) for i in body.get("ids", [])]
    if body.get("dataset_id") and not ids:
        ids = [r["id"] for r in db.q("SELECT id FROM items WHERE dataset_id=?", [int(body["dataset_id"])])]
    ai_gen.clear_ai(ids, body.get("keys"))
    return {"cleared": len(ids)}


# ---------------------------------------------------------------------------
# صف و زمان‌بندی
# ---------------------------------------------------------------------------

@route("/api/queue", methods=("GET", "POST"))
async def queue_ep(request, body):
    if request.method == "POST":
        return jobqueue.add_job(body)
    return {"jobs": jobqueue.list_jobs(), "enabled": db.get_settings().get("queue_enabled", True), "error": jobqueue.QUEUE.last_error}


@route("/api/queue/toggle", methods=("POST",))
async def queue_toggle(request, body):
    db.set_settings({"queue_enabled": bool(body.get("enabled"))})
    jobqueue.QUEUE.wake()
    return {"enabled": db.get_settings()["queue_enabled"]}


@route("/api/queue/{id:int}", methods=("PUT", "DELETE"))
async def queue_job(request, body):
    jid = pid(request)
    j = db.q1("SELECT * FROM queue_jobs WHERE id=?", [jid])
    if not j:
        return JSONResponse({"error": "پیدا نشد"}, status_code=404)
    if request.method == "DELETE":
        if j["status"] in ("running", "ai_running"):
            raise ValueError("این کار در حال اجراست؛ ابتدا «رد شدن» را بزنید.")
        db.ex("DELETE FROM queue_jobs WHERE id=?", [jid])
        return {"ok": True}
    if j["status"] != "queued":
        raise ValueError("فقط کارهای در انتظار قابل ویرایش‌اند.")
    f = {}
    for k in ("title", "category_url", "schema_id", "ai_profile_id", "repeat_hours"):
        if k in body:
            f[k] = body[k] or (0 if k == "repeat_hours" else None if k != "title" else "")
    if "limit" in body:
        f["item_limit"] = int(body["limit"]) if body["limit"] not in (None, "", 0, "0") else None
    if "scheduled_at" in body:
        d = jobqueue._parse(body["scheduled_at"]) if body["scheduled_at"] else None
        f["scheduled_at"] = d.astimezone(jobqueue.timezone.utc).isoformat(timespec="seconds") if d else None
    if f:
        db.update("queue_jobs", jid, **f)
    jobqueue.QUEUE.wake()
    return jobqueue.job_row(db.q1("SELECT * FROM queue_jobs WHERE id=?", [jid]))


@route("/api/queue/{id:int}/{action:str}", methods=("POST",))
async def queue_action(request, body):
    jid = pid(request)
    a = request.path_params["action"]
    j = db.q1("SELECT * FROM queue_jobs WHERE id=?", [jid])
    if a == "up":
        jobqueue.move(jid, -1)
    elif a == "down":
        jobqueue.move(jid, 1)
    elif a == "top":
        jobqueue.move(jid, -99)
    elif a == "run-now":
        db.update("queue_jobs", jid, scheduled_at=None)
        jobqueue.move(jid, -99)
    elif a == "skip":
        if j["status"] == "running" and j["dataset_id"]:
            MANAGER.pause(j["dataset_id"])
        if j["status"] == "ai_running" and j["ai_job_id"]:
            ai_gen.AI_JOBS.stop(j["ai_job_id"])
        db.update("queue_jobs", jid, status="skipped", finished_at=db.now())
    elif a == "requeue":
        db.update("queue_jobs", jid, status="queued", dataset_id=None, ai_job_id=None, error="", started_at=None, finished_at=None)
    jobqueue.QUEUE.wake()
    return {"ok": True}


# ---------------------------------------------------------------------------
# هوش مصنوعی در همه‌جا (۱.۳)
# ---------------------------------------------------------------------------

@route("/api/ai/assist", methods=("POST",))
async def ai_assist_ep(request, body):
    task = body.pop("task", "text")

    def work():
        try:
            return {"ok": True, **ai_studio.assist(task, body)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    return await run_in_threadpool(work)


@route("/api/ai/datasets", methods=("POST",))
async def ai_dataset_create(request, body):
    return await run_in_threadpool(ai_studio.create_dataset, body)


@route("/api/datasets/{id:int}/ai-add", methods=("POST",))
async def ai_dataset_add(request, body):
    return await run_in_threadpool(ai_studio.add_products, pid(request), body)


@route("/api/datasets/{id:int}/ai-column", methods=("POST",))
async def ai_dataset_column(request, body):
    jid = await run_in_threadpool(ai_studio.column_job, pid(request), body.get("column"), body.get("mode", "fill_missing"),
                                  body.get("instruction", ""), body.get("scope", "all"), body.get("item_ids"), body.get("provider_id"), body.get("model"))
    return ai_job_row(db.q1("SELECT * FROM ai_jobs WHERE id=?", [jid]))


# ---------------------------------------------------------------------------
# عملیات ایجنت (MCP)
# ---------------------------------------------------------------------------

@route("/api/datasets/{id:int}/gaps")
async def dataset_gaps(request, body):
    cols = [c for c in (request.query_params.get("columns") or "").split(",") if c]
    sts = tuple((request.query_params.get("status") or "done,partial").split(","))
    return await run_in_threadpool(agent_ops.gaps, pid(request), cols or None, sts, int(request.query_params.get("limit", 500)))


@route("/api/items/{id:int}/detail")
async def item_detail_ep(request, body):
    return await run_in_threadpool(agent_ops.item_detail, pid(request), int(request.query_params.get("max_text", 4000)))


@route("/api/items/{id:int}/fields", methods=("POST",))
async def item_fields_ep(request, body):
    return await run_in_threadpool(agent_ops.set_fields, pid(request), body.get("values") or {}, body.get("mode", "ai"), body.get("agent", "mcp-agent"))


@route("/api/items/{id:int}/generate-image", methods=("POST",))
async def item_gen_image(request, body):
    def work():
        try:
            return {"ok": True, **agent_ops.generate_image(pid(request), body.get("provider_id"), body.get("profile_id"), body.get("prompt", ""),
                                                            body.get("target"), body.get("mode", "add"), body.get("size", "1024x1024"),
                                                            body.get("use_reference", True), int(body.get("count", 1)), body.get("model"))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    return await run_in_threadpool(work)


@route("/api/items/{id:int}/attach-image", methods=("POST",))
async def item_attach_image(request, body):
    return await run_in_threadpool(agent_ops.attach_image, pid(request), body.get("data_base64", ""), body.get("url", ""),
                                   body.get("path", ""), body.get("target"), body.get("mode", "add"))


@route("/api/items/{id:int}/images")
async def item_images_ep(request, body):
    iid = pid(request)
    thumbs = request.query_params.get("thumbs") == "1"
    mx = int(request.query_params.get("max", 6))
    side = int(request.query_params.get("side", 768))

    def work():
        imgs = agent_ops.item_images(iid)[:mx]
        if thumbs:
            it = db.q1("SELECT url FROM items WHERE id=?", [iid])
            for im in imgs:
                try:
                    im["base64"], im["mime"] = agent_ops.load_image_for_agent(im["src"], it["url"], side)
                except Exception as exc:  # noqa: BLE001
                    im["error"] = str(exc)
        return imgs
    return await run_in_threadpool(work)


@route("/api/incidents")
async def incidents_ep(request, body):
    rows = db.q("SELECT i.*, d.title AS dataset_title FROM incidents i JOIN datasets d ON d.id=i.dataset_id WHERE i.status='open' ORDER BY i.id DESC")
    for r in rows:
        r["options"] = db.jload(r["options"], [])
    return rows


@route("/api/mcp/info")
async def mcp_info_ep(request, body):
    return mcp_setup.info()


@route("/api/mcp/install", methods=("POST",))
async def mcp_install_ep(request, body):
    return mcp_setup.install(body.get("client") or "claude_desktop", body.get("name") or "mega-catalog-studio")


@route("/api/mcp/token", methods=("POST",))
async def mcp_token_ep(request, body):
    if body.get("clear"):
        db.set_settings({"mcp_token": ""})
        return {"token": ""}
    return {"token": mcp_setup.new_token()}


@route("/api/mcp/selftest", methods=("POST",))
async def mcp_selftest(request, body):
    def work():
        from .mcp_http import server
        srv = server()
        init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        tl = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        ov = srv.call_tool("studio_overview", {})
        return {"ok": not ov.get("isError"), "protocol": init["result"]["protocolVersion"], "tools": len(tl["result"]["tools"]),
                "overview": ov["content"][0]["text"][:600]}
    return await run_in_threadpool(work)


# ---------------------------------------------------------------------------
# برنامه
# ---------------------------------------------------------------------------

async def index(request):
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


def create_app() -> Starlette:
    db.init()
    services.seed_defaults()
    rules_mod.seed()
    ai_gen.seed()
    MANAGER.recover()
    BG_JOBS.recover()
    EXPORTS.recover()
    ai_gen.AI_JOBS.recover()
    jobqueue.QUEUE.recover()
    jobqueue.QUEUE.start()
    from starlette.middleware import Middleware
    from .activity import ActivityMiddleware, prune
    prune()
    app = Starlette(middleware=[Middleware(mcp_http.HostGuard), Middleware(ActivityMiddleware)], routes=[
        *routes,
        *mcp_http.ROUTES,
        Mount("/static", app=_NoCacheStatic(directory=str(STATIC_DIR)), name="static"),
        Route("/", index),
    ])
    return app
