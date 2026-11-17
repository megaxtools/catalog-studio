"""مسیرهای HTTP نسخه‌ی ۲: ماژول‌ها، کاربران، ریویژن‌ها، داده‌های مرجع، ویرایشگر داده‌ها، کاتالوگ محصولات، پشتیبان و راهنما."""
from __future__ import annotations

import re
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from . import backup, compat, db, import_specs, modules, product_catalog as pc, refdata, revisions, services, workbench
from .config import DOCS_DIR, VERSION
from starlette.responses import Response

from .web import actor_of, pid, route


def _int(v):
    return int(v) if v not in (None, "", "null") else None


# ---------------------------------------------------------------------------
# نمای کلی، ماژول‌ها، کاربران
# ---------------------------------------------------------------------------

@route("/api/overview")
async def overview(request, body):
    return {
        "version": VERSION,
        "raw": {"datasets": db.val("SELECT COUNT(*) FROM datasets") or 0, "items": db.val("SELECT COUNT(*) FROM items WHERE status IN ('done','partial')") or 0},
        "editor": {"banks": db.val("SELECT COUNT(*) FROM wb_banks") or 0,
                   "products": db.val("SELECT COUNT(*) FROM wb_products WHERE status IN ('draft','review','approved','rejected')") or 0,
                   "review": db.val("SELECT COUNT(*) FROM wb_products WHERE status='review'") or 0,
                   "approved": db.val("SELECT COUNT(*) FROM wb_products WHERE status='approved'") or 0,
                   "running": db.val("SELECT COUNT(*) FROM wb_banks WHERE status IN ('running','pending')") or 0,
                   "dupes": (db.val("SELECT COUNT(*) FROM dup_pairs WHERE status='open'") or 0) if modules.is_enabled("dedup") else 0},
        "catalog": {"catalogs": db.val("SELECT COUNT(*) FROM cat_catalogs") or 0, "releases": db.val("SELECT COUNT(*) FROM cat_releases WHERE status='completed'") or 0,
                    "building": db.val("SELECT COUNT(*) FROM cat_releases WHERE status IN ('running','pending')") or 0},
        "ref": {"brands": db.val("SELECT COUNT(*) FROM ref_brands") or 0, "categories": db.val("SELECT COUNT(*) FROM ref_categories") or 0},
        "modules": modules.enabled_map(),
    }


@route("/api/modules")
async def modules_list(request, body):
    return modules.status_list()


@route("/api/modules/{mid:str}", methods=("PUT",))
async def module_toggle(request, body):
    return modules.set_enabled(request.path_params["mid"], bool(body.get("enabled")))


@route("/api/users", methods=("GET", "POST"))
async def users_ep(request, body):
    if request.method == "POST":
        name, username = (body.get("name") or "").strip(), (body.get("username") or "").strip().lower()
        if not name or not re.match(r"^[a-z0-9_.-]{3,}$", username):
            raise ValueError("نام و نام کاربری انگلیسی (دست‌کم ۳ حرف) لازم است.")
        if db.q1("SELECT id FROM users WHERE username=?", [username]):
            raise ValueError("این نام کاربری تکراری است.")
        role = body.get("role") if body.get("role") in ("admin", "operator") else "operator"
        uid = db.ex("INSERT INTO users(username, name, role, active, created_at) VALUES(?,?,?,?,?)", [username, name, role, 1, db.now()])
        return db.q1("SELECT * FROM users WHERE id=?", [uid])
    cur = int(db.get_settings().get("current_user_id") or 1)
    rows = db.q("SELECT * FROM users ORDER BY id")
    for r in rows:
        r["current"] = r["id"] == cur
        r["revisions"] = db.val("SELECT COUNT(*) FROM revisions WHERE user_id=?", [r["id"]]) or 0
    return rows


@route("/api/users/{id:int}", methods=("PUT",))
async def user_ep(request, body):
    uid = pid(request)
    u = db.q1("SELECT * FROM users WHERE id=?", [uid])
    if not u:
        raise ValueError("کاربر پیدا نشد.")
    upd = {}
    if body.get("name"):
        upd["name"] = body["name"].strip()
    if body.get("role") in ("admin", "operator"):
        if uid == 1 and body["role"] != "admin":
            raise ValueError("مدیر اصلی باید نقش مدیر داشته باشد.")
        upd["role"] = body["role"]
    if "active" in body:
        if uid == 1 and not body["active"]:
            raise ValueError("مدیر اصلی غیرفعال نمی‌شود.")
        upd["active"] = 1 if body["active"] else 0
    if upd:
        db.update("users", uid, **upd)
    return db.q1("SELECT * FROM users WHERE id=?", [uid])


# ---------------------------------------------------------------------------
# ریویژن‌ها
# ---------------------------------------------------------------------------

@route("/api/revisions")
async def revs_list(request, body):
    qp = request.query_params
    if qp.get("entity_id"):
        return revisions.list_revisions(qp["entity"], int(qp["entity_id"]), light=qp.get("full") != "1")
    return revisions.recent(qp.get("entity") or None, int(qp.get("size") or 100), int(qp.get("page") or 1), qp.get("q", ""), qp.get("actor", ""))


@route("/api/revisions/get")
async def revs_get(request, body):
    qp = request.query_params
    r = revisions.get_revision(qp["entity"], int(qp["entity_id"]), int(qp["rev"]))
    prev = db.q1("SELECT rev FROM revisions WHERE entity=? AND entity_id=? AND rev<? ORDER BY rev DESC LIMIT 1", [qp["entity"], int(qp["entity_id"]), int(qp["rev"])])
    r["previous"] = prev["rev"] if prev else None
    return r


@route("/api/revisions/compare")
async def revs_compare(request, body):
    qp = request.query_params
    return revisions.compare(qp["entity"], int(qp["entity_id"]), int(qp["a"]), int(qp["b"]))


@route("/api/revisions/restore", methods=("POST",))
async def revs_restore(request, body):
    return revisions.restore(body["entity"], int(body["entity_id"]), int(body["rev"]), actor_of(request))


# ---------------------------------------------------------------------------
# داده‌های مرجع (برند و دسته)
# ---------------------------------------------------------------------------

@route("/api/ref/{kind:str}", methods=("GET", "POST"))
async def ref_list(request, body):
    kind = request.path_params["kind"]
    if request.method == "POST":
        return refdata.save(kind, body, None, actor_of(request))
    qp = request.query_params
    return refdata.list_items(kind, qp.get("q", ""), qp.get("active") == "1", category_id=_int(qp.get("category_id")),
                              inherit=qp.get("inherit", "1") != "0")


@route("/api/ref/{kind:str}/tree")
async def ref_tree(request, body):
    if request.path_params["kind"] != "category":
        raise ValueError("درخت فقط برای دسته‌بندی‌هاست.")
    return refdata.tree(request.query_params.get("q", ""))


@route("/api/ref/{kind:str}/bulk", methods=("POST",))
async def ref_bulk(request, body):
    return await run_in_threadpool(refdata.bulk, request.path_params["kind"], body.get("ids") or [], body.get("action") or "",
                                   body.get("value"), actor_of(request))


@route("/api/ref/{kind:str}/apply", methods=("POST",))
async def ref_apply(request, body):
    return await run_in_threadpool(refdata.apply_items, request.path_params["kind"], body.get("items") or [], actor_of(request))


@route("/api/ref/{kind:str}/export")
async def ref_export(request, body):
    qp = request.query_params
    ids = [int(x) for x in (qp.get("ids") or "").split(",") if x.strip().isdigit()]
    data, mime, name = refdata.export_file(request.path_params["kind"], qp.get("format") or "xlsx", ids or None)
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@route("/api/ref/{kind:str}/unmatched")
async def ref_unmatched(request, body):
    return refdata.unmatched(request.path_params["kind"])


@route("/api/ref/{kind:str}/link", methods=("POST",))
async def ref_link(request, body):
    return refdata.link_unmatched(request.path_params["kind"], body["name"], int(body["id"]), body.get("add_alias", True), actor_of(request))


@route("/api/ref/{kind:str}/add-unmatched", methods=("POST",))
async def ref_add_unmatched(request, body):
    kind = request.path_params["kind"]
    out = []
    for it in body.get("items") or []:
        r = refdata.save(kind, {"name": it.get("name_fa") or it["name"], "name_en": it.get("name_en", ""), "slug": it.get("slug", ""),
                                "aliases": [it["name"]] if it.get("name_fa") and it.get("name_fa") != it["name"] else []}, None, actor_of(request))
        res = refdata.link_unmatched(kind, it["name"], r["id"], add_alias=False, actor=actor_of(request))
        out.append({"id": r["id"], "name": r["name"], "linked": res["linked"]})
    return {"created": out}


@route("/api/ref/{kind:str}/import", methods=("POST",))
async def ref_import(request, body):
    kind = request.path_params["kind"]
    rows = (refdata.parse_upload(body["data_url"], body.get("name") or "x.xlsx", kind, body.get("mapping"))
            if body.get("data_url") else body.get("rows") or [])
    return await run_in_threadpool(refdata.import_rows, kind, rows, actor_of(request), body.get("update", True))


@route("/api/ref/{kind:str}/{id:int}", methods=("GET", "PUT", "DELETE"))
async def ref_item(request, body):
    kind, rid = request.path_params["kind"], pid(request)
    if request.method == "PUT":
        return refdata.save(kind, body, rid, actor_of(request))
    if request.method == "DELETE":
        return refdata.delete(kind, rid, actor_of(request))
    r = refdata.get(kind, rid)
    if not r:
        raise ValueError("پیدا نشد.")
    return r


# ---------------------------------------------------------------------------
# ویرایشگر داده‌ها
# ---------------------------------------------------------------------------

@route("/api/wb/banks", methods=("GET", "POST"))
async def wb_banks(request, body):
    if request.method == "POST":
        return workbench.create_bank(body, actor_of(request))
    return workbench.list_banks()


@route("/api/wb/banks/{id:int}", methods=("GET", "PUT", "DELETE"))
async def wb_bank(request, body):
    bid = pid(request)
    if request.method == "PUT":
        return workbench.update_bank(bid, body, actor_of(request))
    if request.method == "DELETE":
        return workbench.delete_bank(bid, request.query_params.get("files", "1") == "1", actor_of(request))
    b = workbench.bank_summary(workbench.get_bank(bid))
    sc = workbench.bank_schema(b)
    b["columns"] = [{**c, "role": workbench.core_role(c)} for c in sc["columns"] if c.get("include", True) is not False]
    return b


@route("/api/wb/banks/{id:int}/add-datasets", methods=("POST",))
async def wb_add(request, body):
    return workbench.add_datasets(pid(request), body.get("dataset_ids") or [], actor_of(request))


@route("/api/wb/banks/{id:int}/do/{action:str}", methods=("POST",))
async def wb_do(request, body):
    bid, a = pid(request), request.path_params["action"]
    if a == "stop":
        workbench.BANK_JOBS.stop(bid)
    elif a in ("resume", "start"):
        workbench.BANK_JOBS.start(bid)
    elif a == "rescore":
        if modules.is_enabled("quality"):
            from .modules.quality import rescore_bank
            return {"rescored": await run_in_threadpool(rescore_bank, bid)}
    else:
        raise ValueError("عملیات نامعتبر است.")
    return workbench.bank_summary(workbench.get_bank(bid))


@route("/api/wb/banks/{id:int}/ai", methods=("POST",))
async def wb_bank_ai(request, body):
    from . import ai_gen
    from .api import ai_job_row
    bid = pid(request)
    b = workbench.get_bank(bid)
    schema = workbench.bank_schema(b)
    base = ai_gen.get_profile(int(body["profile_id"]))["config"] if body.get("profile_id") else None
    cfg = ai_gen.build_config(schema, body.get("columns") or [], base)
    for k in ("provider_id", "model", "seo_keywords", "extra_context"):
        if body.get(k):
            cfg[k] = body[k]
    if not cfg["fields"] and not cfg["images_list"]:
        raise ValueError("هیچ ستونی برای تولید انتخاب نشده است.")
    ids = workbench.filtered_ids(bid, body) if (body.get("ids") or body.get("filter")) else []
    opts = {"bank_id": bid, "schema_id": schema["id"], "row_ids": ids, "config": cfg, "title": f"ویرایشگر: «{b['title']}»"}
    jid = ai_gen.AI_JOBS.create((b["dataset_ids"] or [0])[0], int(body.get("profile_id") or 0) or None, opts)
    return ai_job_row(db.q1("SELECT * FROM ai_jobs WHERE id=?", [jid]))


@route("/api/wb/products")
async def wb_products(request, body):
    qp = request.query_params
    ids = [int(x) for x in (qp.get("ids") or "").split(",") if x]
    return workbench.list_products(_int(qp.get("bank_id")), qp.get("q", ""), qp.get("status", ""), qp.get("filter", ""),
                                   int(qp.get("page") or 1), max(1, min(500, int(qp.get("size") or 50))), ids or None,
                                   _int(qp.get("brand_id")), _int(qp.get("category_id")), qp.get("sort", "seq"), light=qp.get("full") != "1")


@route("/api/wb/products/bulk", methods=("POST",))
async def wb_bulk(request, body):
    return await run_in_threadpool(workbench.bulk, _int(body.get("bank_id")), body, actor_of(request))


@route("/api/wb/products/bulk-images", methods=("POST",))
async def wb_bulk_images(request, body):
    return await run_in_threadpool(workbench.bulk_images, _int(body.get("bank_id")), body, actor_of(request))


@route("/api/wb/products/{id:int}", methods=("GET", "PUT", "DELETE"))
async def wb_product(request, body):
    p_id = pid(request)
    if request.method == "PUT":
        await run_in_threadpool(workbench.update_product, p_id, body, actor_of(request), "edit", body.get("_note", ""), bool(body.get("force")))
    elif request.method == "DELETE":
        return workbench.delete_product(p_id, request.query_params.get("hard") == "1", actor_of(request))
    p = workbench.get_product(p_id)
    out = workbench.view(p)
    out["revisions"] = len(revisions.list_revisions("product", p_id))
    return out


@route("/api/wb/products/{id:int}/images/{action:str}", methods=("POST",))
async def wb_image(request, body):
    p_id, a = pid(request), request.path_params["action"]
    if a == "generate":
        modules.require("ai")
    return await run_in_threadpool(workbench.image_action, p_id, a, body, actor_of(request))


@route("/api/wb/products/{id:int}/ai", methods=("POST",))
async def wb_product_ai(request, body):
    from . import ai_gen
    from .ai import set_context
    p_id = pid(request)
    p = workbench.get_product(p_id)
    schema = workbench.bank_schema(workbench.get_bank(p["bank_id"]))
    cfg = ai_gen.build_config(schema, body.get("columns") or [], None)
    for k in ("provider_id", "model"):
        if body.get(k):
            cfg[k] = body[k]

    def work():
        set_context(purpose="ویرایشگر داده‌ها (تک‌محصول)", ref=f"product:{p_id}")
        client = ai_gen.client_for(cfg)
        res = workbench.ai_product(p_id, cfg, client, db.get_settings(), actor="ai")
        return {"ok": True, "generated": res, "product": workbench.view(workbench.get_product(p_id))}
    try:
        return await run_in_threadpool(work)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@route("/api/wb/products/{id:int}/compat-suggest", methods=("POST",))
async def wb_compat_suggest(request, body):
    p = workbench.get_product(pid(request))
    src = (p["sources"] or [{}])[0]
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [src.get("item_id")])) if src.get("item_id") else None
    text = p["title"] + " " + " ".join(str(v) for v in p["values"].values() if isinstance(v, str))[:3000]
    if it:
        text += " " + workbench._item_text(it, services.get_dataset(it["dataset_id"]))  # noqa: SLF001
    if body.get("ai"):
        modules.require("ai")
        modules.require("vehicles")
        from .ai import set_context
        from .ai_studio import default_client
        from .modules.vehicles import service as vs

        def work():
            set_context(purpose="پیشنهاد سازگاری با خودرو", ref=f"product:{p['id']}")
            client, _ = default_client(body.get("provider_id"))
            return vs.ai_suggest(text, client)
        return await run_in_threadpool(work)
    return compat.suggest(text)


@route("/api/wb/products/{id:int}/sources")
async def wb_sources(request, body):
    """داده‌ی خام (نسخه‌ی صفر) محصول تمیز برای مقایسه."""
    p = workbench.get_product(pid(request))
    out = []
    for s in p["sources"]:
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [s.get("item_id")])) if s.get("item_id") else None
        out.append({**s, "data": it["data"] if it else None, "item_status": it["status"] if it else None})
    return out


@route("/api/wb/from-legacy/{id:int}", methods=("POST",))
async def wb_from_legacy(request, body):
    return await run_in_threadpool(workbench.from_legacy_export, pid(request), body.get("title") or "", actor_of(request))


# ---------------------------------------------------------------------------
# کاتالوگ محصولات
# ---------------------------------------------------------------------------

@route("/api/cat/meta")
async def cat_meta(request, body):
    try:
        from .modules.vehicles.service import EXPORT_FORMATS
    except Exception:  # noqa: BLE001 — ماژول خودروها حذف شده باشد
        EXPORT_FORMATS = {"structured": "ساختاریافته"}
    return {"kinds": pc.KINDS, "formats": pc.FORMATS, "kind_fields": pc.KIND_FIELDS, "states": pc.STATES, "vehicle_formats": EXPORT_FORMATS,
            "statuses": workbench.STATUSES}


@route("/api/cat/templates", methods=("GET", "POST"))
async def cat_templates(request, body):
    if request.method == "POST":
        return pc.save_template(body, None, actor_of(request))
    return pc.list_templates()


@route("/api/cat/templates/preview", methods=("POST",))
async def cat_tpl_preview(request, body):
    cfg = pc.normalize_config(body.get("config") or {})
    return {"tree": pc.preview_tree(cfg), "errors": pc.validate_config(cfg), "config": cfg}


@route("/api/cat/templates/{id:int}", methods=("GET", "PUT", "DELETE"))
async def cat_template(request, body):
    tid = pid(request)
    if request.method == "PUT":
        return pc.save_template(body, tid, actor_of(request))
    if request.method == "DELETE":
        return pc.delete_template(tid, actor_of(request))
    return pc.get_template(tid)


@route("/api/cat/catalogs", methods=("GET", "POST"))
async def cat_catalogs(request, body):
    if request.method == "POST":
        return pc.save_catalog(body, None, actor_of(request))
    return pc.list_catalogs()


@route("/api/cat/catalogs/{id:int}", methods=("GET", "PUT", "DELETE"))
async def cat_catalog(request, body):
    cid = pid(request)
    if request.method == "PUT":
        return pc.save_catalog(body, cid, actor_of(request))
    if request.method == "DELETE":
        return pc.delete_catalog(cid, request.query_params.get("files") == "1", actor_of(request))
    return pc.catalog_summary(pc.get_catalog(cid))


@route("/api/cat/catalogs/{id:int}/preview")
async def cat_preview(request, body):
    return await run_in_threadpool(pc.preview_selection, pid(request))


@route("/api/cat/catalogs/{id:int}/release", methods=("POST",))
async def cat_release(request, body):
    return await run_in_threadpool(pc.RELEASES.start, pid(request), body.get("note") or "", bool(body.get("wait")))


@route("/api/cat/catalogs/{id:int}/releases")
async def cat_releases(request, body):
    return pc.list_releases(pid(request))


@route("/api/cat/releases/compare")
async def cat_rel_compare(request, body):
    qp = request.query_params
    return pc.compare_releases(int(qp["a"]), int(qp["b"]))


@route("/api/cat/releases/{id:int}", methods=("GET", "DELETE"))
async def cat_rel(request, body):
    rid = pid(request)
    if request.method == "DELETE":
        return pc.delete_release(rid, request.query_params.get("files", "1") == "1")
    return pc.get_release(rid, full=request.query_params.get("full") == "1")


@route("/api/cat/releases/{id:int}/items")
async def cat_rel_items(request, body):
    qp = request.query_params
    return pc.release_items(pid(request), qp.get("q", ""), int(qp.get("page") or 1), int(qp.get("size") or 100))


# ---------------------------------------------------------------------------
# پشتیبان‌گیری
# ---------------------------------------------------------------------------

@route("/api/backups", methods=("GET", "POST"))
async def backups(request, body):
    if request.method == "POST":
        return await run_in_threadpool(backup.create, body.get("note") or "", bool(body.get("with_images")))
    return backup.list_backups()


@route("/api/backups/restore", methods=("POST",))
async def backups_restore(request, body):
    return backup.schedule_restore(body["name"])


@route("/api/backups/cancel-restore", methods=("POST",))
async def backups_cancel(request, body):
    return backup.cancel_restore()


@route("/api/backups/upload", methods=("POST",))
async def backups_upload(request, body):
    return backup.upload(body["data_url"], body.get("name") or "backup.zip")


@route("/api/backups/{name:str}", methods=("DELETE",))
async def backups_delete(request, body):
    from .config import BACKUP_DIR
    p = BACKUP_DIR / Path(request.path_params["name"]).name
    if p.exists() and p.suffix == ".zip":
        p.unlink()
    return {"ok": True}


# ---------------------------------------------------------------------------
# ورود فایل: مشخصات، نمونه، تحلیل پیش از ورود، ورود داده‌ی خام
# ---------------------------------------------------------------------------

@route("/api/import/specs")
async def import_specs_ep(request, body):
    return import_specs.all_specs()


@route("/api/import/sample/{kind:str}")
async def import_sample(request, body):
    data, mime, name = import_specs.sample(request.path_params["kind"], request.query_params.get("format") or "xlsx")
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@route("/api/import/analyze", methods=("POST",))
async def import_analyze(request, body):
    return import_specs.analyze(body.get("kind") or "raw", body["data_url"], body.get("name") or "x.xlsx")


@route("/api/datasets/import-file", methods=("POST",))
async def dataset_import_file(request, body):
    from . import raw_import
    return await run_in_threadpool(raw_import.import_file, body["data_url"], body.get("name") or "x.xlsx", body.get("title") or "",
                                   _int(body.get("schema_id")), body.get("category_label") or "", body.get("mapping"), actor_of(request))


# ---------------------------------------------------------------------------
# هوش مصنوعی در برندها، دسته‌ها، الگوها، تکراری‌ها و ورود فایل (ماژول ai)
# ---------------------------------------------------------------------------

def _ref_items(kind, body):
    if body.get("items"):
        return body["items"]
    ids = [int(i) for i in body.get("ids") or []]
    rows = [refdata.get(kind, i) for i in ids] if ids else refdata.list_items(kind, with_counts=False)
    return [r for r in rows if r]


@route("/api/ref/{kind:str}/ai-complete", methods=("POST",), module="ai")
async def ref_ai_complete(request, body):
    from . import ai_tasks
    kind = request.path_params["kind"]
    items = _ref_items(kind, body)
    return await run_in_threadpool(ai_tasks.ref_complete, kind, items, body.get("fields"), body.get("only_empty", True), body.get("provider_id"))


@route("/api/ref/{kind:str}/ai-match", methods=("POST",), module="ai")
async def ref_ai_match(request, body):
    from . import ai_tasks
    return await run_in_threadpool(ai_tasks.ref_match, request.path_params["kind"], body.get("names"), body.get("provider_id"))


@route("/api/ref/{kind:str}/ai-generate", methods=("POST",), module="ai")
async def ref_ai_generate(request, body):
    from . import ai_tasks
    return await run_in_threadpool(ai_tasks.ref_generate, request.path_params["kind"], body.get("prompt") or "", _int(body.get("parent_id")),
                                   int(body.get("count") or 15), body.get("provider_id"))


@route("/api/cat/templates/ai", methods=("POST",), module="ai")
async def cat_tpl_ai(request, body):
    from . import ai_tasks
    return await run_in_threadpool(ai_tasks.template_design, body.get("prompt") or "", body.get("provider_id"))


@route("/api/dupes/{id:int}/ai", methods=("POST",), module="ai")
async def dupe_ai(request, body):
    modules.require("dedup")
    from . import ai_tasks
    return await run_in_threadpool(ai_tasks.dupe_check, pid(request), body.get("provider_id"))


@route("/api/import/ai-map", methods=("POST",), module="ai")
async def import_ai_map(request, body):
    from . import ai_tasks
    return await run_in_threadpool(ai_tasks.column_map, body.get("kind") or "raw", body.get("headers") or [], body.get("preview"), body.get("provider_id"))


# ---------------------------------------------------------------------------
# راهنما و مستندات
# ---------------------------------------------------------------------------

def _doc_title(p: Path) -> str:
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return p.stem


@route("/api/docs")
async def docs_list(request, body):
    out = []
    for group, label in (("guide", "راهنمای کار با استودیو"), ("design", "مستندات طراحی و توسعه")):
        d = DOCS_DIR / group
        if d.exists():
            out.append({"group": group, "label": label, "docs": [{"path": f"{group}/{p.name}", "title": _doc_title(p)} for p in sorted(d.glob("*.md"))]})
    return out


@route("/api/docs/{path:path}")
async def docs_get(request, body):
    rel = request.path_params["path"]
    p = (DOCS_DIR / rel).resolve()
    if DOCS_DIR.resolve() not in p.parents or p.suffix != ".md" or not p.exists():
        raise ValueError("سند پیدا نشد.")
    return {"path": rel, "title": _doc_title(p), "content": p.read_text(encoding="utf-8")}
