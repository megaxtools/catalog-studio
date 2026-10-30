"""کاتالوگ‌های نهایی (خروجی‌ها): ردیف‌های هر خروجی در پایگاه داده ذخیره می‌شوند و فایل‌ها (Excel، CSV، JSON، ZIP) از همین
ردیف‌ها ساخته می‌شوند. هر قالب فایل می‌تواند اسکیمای خودش را داشته باشد. ویرایش دستی و هوش مصنوعی روی هر فیلد و تصاویر،
تک‌به‌تک یا گروهی، با ثبت کامل تاریخچه.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from . import align as align_mod
from . import db, services
from .images import RAW_SUFFIX, REMBG_SUFFIX, IMAGE_EXTS, is_intermediate, stage_of

FORMATS = ("xlsx", "csv", "json")
STATES = {"draft": "پیش‌نویس", "review": "در حال بازبینی", "approved": "تأییدشده", "published": "منتشرشده در مگا کارز"}


# ---------------------------------------------------------------------------
# کمک‌ها
# ---------------------------------------------------------------------------

def export_row_meta(e: dict) -> dict:
    e = dict(e)
    e["options"] = db.jload(e.get("options"), {}) if isinstance(e.get("options"), str) else (e.get("options") or {})
    e["result"] = db.jload(e.get("result"), {}) if isinstance(e.get("result"), str) else (e.get("result") or {})
    e["dataset_ids"] = db.jload(e.get("dataset_ids"), []) if isinstance(e.get("dataset_ids"), str) else e.get("dataset_ids")
    return e


def get_export(eid: int) -> dict:
    e = db.q1("SELECT * FROM exports WHERE id=?", [eid])
    if not e:
        raise ValueError("خروجی پیدا نشد.")
    return export_row_meta(e)


def format_schemas(opts: dict) -> dict[str, int]:
    """اسکیمای هر قالب فایل؛ اگر تعیین نشده باشد، اسکیمای اصلی خروجی."""
    base = opts.get("schema_id") or services.get_schema(None)["id"]
    fs = opts.get("format_schemas") or {}
    formats = opts.get("formats") or ["xlsx", "csv"]
    return {f: int(fs.get(f) or base) for f in formats if f in FORMATS}


def schema_of(e: dict, sid: int) -> dict:
    """اسکیمای ذخیره‌شده در خود خروجی (تا تغییر یا حذف اسکیما در آینده، خروجی‌های ساخته‌شده را خراب نکند)."""
    snap = (e.get("options") or {}).get("schema_snapshots") or {}
    sc = snap.get(str(sid))
    if sc:
        return sc
    return services.get_schema(sid)


def schema_ids(opts: dict) -> list[int]:
    ids = list(dict.fromkeys([int(opts.get("schema_id") or services.get_schema(None)["id"]), *format_schemas(opts).values(),
                              *[int(k) for k in (opts.get("schema_snapshots") or {})]]))
    return ids


def row_dict(r: dict) -> dict:
    r = dict(r)
    r["images"] = db.jload(r.get("images"), {}) or {}
    r["values"] = db.jload(r.pop("values_json", "{}"), {}) or {}
    r["flags"] = db.jload(r.get("flags"), {}) or {}
    r["edited"] = db.jload(r.get("edited"), {}) or {}
    return r


def _same(a, b) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(b, ensure_ascii=False, sort_keys=True, default=str)


def _root(e: dict) -> Path:
    return Path(e["result"].get("root") or e["options"].get("output_root") or db.get_settings()["output_root"])


def mark_stale(eid: int):
    db.update("exports", eid, files_stale=1, updated_at=db.now())


# ---------------------------------------------------------------------------
# ساخت ردیف‌ها (snapshot)
# ---------------------------------------------------------------------------

def snapshot(eid: int, opts: dict, items: list[dict], settings: dict, item_images: dict[int, dict]) -> list[dict]:
    """ردیف‌های خروجی را از روی محصولات می‌سازد و در جدول export_rows ذخیره می‌کند. خروجی: هشدارها."""
    warnings: list[dict] = []
    per_schema: dict[str, list[tuple[dict, dict]]] = {}
    for sid in schema_ids(opts):
        schema = services.get_schema(sid)
        ds_cache: dict = {}
        src_cache: dict = {}
        used_slugs: dict[str, int] = {}
        vals = []
        for it in items:
            ds = ds_cache.get(it["dataset_id"]) or services.get_dataset(it["dataset_id"])
            ds_cache[it["dataset_id"]] = ds
            src = src_cache.get(it["source_id"]) or services.get_source(it["source_id"])
            src_cache[it["source_id"]] = src
            v_row, f_row = {}, {}
            for col in schema["columns"]:
                if col.get("include", True) is False:
                    continue
                v, flag = services.column_value(col, it, ds, settings, src)
                if col.get("kind") == "auto" and col.get("generator", "slug") == "slug" and v:
                    n = used_slugs.get(v, 0)
                    used_slugs[v] = n + 1
                    if n:
                        v = f"{v}-{n + 1}"
                if flag in ("missing", "unmapped"):
                    warnings.append({"item_id": it["id"], "column": col["key"], "flag": flag, "title": it["data"].get("title", "")})
                v_row[col["key"]] = v
                if flag:
                    f_row[col["key"]] = flag
            vals.append((v_row, f_row))
        per_schema[str(sid)] = vals
    e = get_export(eid)
    eo = dict(e["options"])
    eo["schema_snapshots"] = {}
    for sid in schema_ids(opts):
        sc = services.get_schema(sid)
        eo["schema_snapshots"][str(sid)] = {"id": sc["id"], "name": sc["name"], "columns": sc["columns"]}
    db.update("exports", eid, options=eo)
    db.ex("DELETE FROM export_rows WHERE export_id=?", [eid])
    for i, it in enumerate(items):
        values = {sid: per_schema[sid][i][0] for sid in per_schema}
        flags = {sid: per_schema[sid][i][1] for sid in per_schema}
        db.ex("""INSERT INTO export_rows(export_id, item_id, seq, folder, title, images, values_json, flags, edited, status, updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              [eid, it["id"], i + 1, it.get("_folder", ""), it["data"].get("title", ""), db.jdump(item_images.get(it["id"]) or {}),
               db.jdump(values), db.jdump(flags), "{}", "ok", db.now()])
    db.history("export", eid, "*", "", f"{len(items)} ردیف", actor="system", action="build", parent_id=eid)
    return warnings


# ---------------------------------------------------------------------------
# مقدارهای ساخت‌یافته (JSON) و تخت (Excel/CSV)
# ---------------------------------------------------------------------------

def _num(v):
    if isinstance(v, (int, float)) or v in (None, ""):
        return v if v != "" else None
    try:
        from .textutil import to_latin_digits
        s = to_latin_digits(str(v)).replace(",", "").strip()
        f = float(s)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return v


def image_links(col: dict, value, row: dict, link_mode: str, prefix: str):
    """مقدار ستون تصویری بر اساس تصاویر نهایی ردیف و روش پیوند (مسیر نسبی، پیشوند CDN، لینک منبع)."""
    imgs = row.get("images") or {}
    is_one = (col.get("input") == "image")
    if link_mode != "source" and (imgs.get("feature") or imgs.get("gallery")):
        pre = (prefix.rstrip("/") + "/") if link_mode == "prefix" and prefix else ""
        if is_one:
            return (pre + imgs["feature"]) if imgs.get("feature") else ""
        return [pre + g for g in imgs.get("gallery") or []]
    if is_one:
        return value if isinstance(value, str) else (services.as_list(value) or [""])[0]
    return [u for u in services.as_list(value) if u]


def structured(col: dict, v):
    """مقدار ستون برای JSON: ساختار حفظ می‌شود (بولت‌ها آرایه، گروه‌ها شیء، مشخصات آرایه/شیء، عددها عدد، بله/خیر بولی)."""
    inp = col.get("input") or "text"
    if inp == "bullet_groups":
        d = v if isinstance(v, dict) else {}
        return {g["key"]: services.as_list(d.get(g["key"])) for g in col.get("groups", [])}
    if inp == "group":
        d = v if isinstance(v, dict) else {}
        return {s: _num(d.get(s, "")) if str(d.get(s, "")).strip() else None for s in col.get("subkeys", [])}
    if inp == "specs":
        return services.specs_to_json(v, col.get("spec_format", "flat")) if v else ([] if col.get("spec_format") == "list" else {})
    if inp in ("bullets", "images"):
        return [x for x in services.as_list(v) if x not in (None, "")]
    if inp == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return True if s in ("true", "1", "yes", "بله") else (False if s in ("false", "0", "no", "خیر") else None)
    if inp == "number":
        return _num(v)
    if inp == "json":
        if isinstance(v, str) and v.strip()[:1] in ("{", "["):
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v if v not in ("",) else None
    if isinstance(v, (list, dict)):
        return v
    return "" if v is None else v


def records(e: dict, fmt: str) -> tuple[dict, list[dict]]:
    """(اسکیما، ردیف‌های قابل نوشتن) برای یک قالب فایل."""
    sid = format_schemas(e["options"]).get(fmt) or int(e["options"].get("schema_id") or e["schema_id"])
    schema = schema_of(e, sid)
    rows = [row_dict(r) for r in db.q("SELECT * FROM export_rows WHERE export_id=? AND status='ok' ORDER BY seq, id", [e["id"]])]
    return schema, rows


def _cols(schema: dict) -> list[dict]:
    return [c for c in schema["columns"] if c.get("include", True) is not False]


def row_value(row: dict, schema: dict, col: dict, e: dict):
    v = (row["values"].get(str(schema["id"])) or {}).get(col["key"])
    if col.get("input") in ("image", "images"):
        o = e["options"]
        v = image_links(col, v, row, o.get("link_mode", "relative"), o.get("link_prefix", ""))
    return v


def flat_table(e: dict, fmt: str) -> tuple[list[str], list[list], dict, list[dict]]:
    schema, rows = records(e, fmt)
    headers: list[str] = []
    out = []
    for row in rows:
        rec = []
        for col in _cols(schema):
            rec.extend(services.expand_column(col, row_value(row, schema, col, e), None))
        if not headers:
            headers = [k for k, _ in rec]
        out.append([v for _, v in rec])
    if not headers:
        for col in _cols(schema):
            headers.extend(k for k, _ in services.expand_column(col, None, None))
    return headers, out, schema, rows


def json_records(e: dict) -> list[dict]:
    schema, rows = records(e, "json")
    return [{col["key"]: structured(col, row_value(row, schema, col, e)) for col in _cols(schema)} for row in rows]


# ---------------------------------------------------------------------------
# نوشتن فایل‌ها
# ---------------------------------------------------------------------------

def write_files(eid: int, stats: dict | None = None, extra_files: dict | None = None, step=None) -> dict:
    """فایل‌های نهایی را از ردیف‌های ذخیره‌شده می‌سازد (هم هنگام ساخت خروجی، هم «بازسازی» پس از ویرایش)."""
    from .export import EXPORTS
    e = get_export(eid)
    o = e["options"]
    name = o["name"]
    root = services.ensure_dir(_root(e))
    files: dict[str, str] = {k: v for k, v in (e["result"].get("files") or {}).items() if k in ("raw_xlsx", "raw_json", "images_dir")}
    files.update(extra_files or {})
    stats = stats if stats is not None else (e["result"].get("stats") or {})
    fs = format_schemas(o)
    n_rows = n_cols = 0
    if "xlsx" in fs:
        step and step("ساخت فایل Excel")
        headers, rows, schema, rws = flat_table(e, "xlsx")
        spec_col = next((c for c in _cols(schema) if c.get("input") == "specs"), None)
        slug_col = next((c for c in _cols(schema) if c.get("kind") == "auto" and c.get("generator", "slug") == "slug"), None)
        pseudo = [{"_slug": (r["values"].get(str(schema["id"])) or {}).get(slug_col["key"], "") if slug_col else "",
                   "data": {"title": r.get("title", ""), "specifications": (r["values"].get(str(schema["id"])) or {}).get(spec_col["key"]) if spec_col else []}}
                  for r in rws]
        for p in pseudo:
            if not isinstance(p["data"]["specifications"], list):
                p["data"]["specifications"] = []
        p = root / f"{name}.xlsx"
        EXPORTS.write_xlsx(p, headers, rows, pseudo, schema, o, {**stats, "schema_xlsx": schema["name"]})
        files["xlsx"] = str(p)
        n_rows, n_cols = len(rows), len(headers)
    else:
        files.pop("xlsx", None)
    if "csv" in fs:
        step and step("ساخت فایل CSV")
        headers, rows, schema, _ = flat_table(e, "csv")
        p = root / f"{name}.csv"
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            for r in rows:
                w.writerow(["" if v is None else v for v in r])
        files["csv"] = str(p)
        n_rows, n_cols = n_rows or len(rows), n_cols or len(headers)
    if "json" in fs:
        step and step("ساخت فایل JSON")
        recs = json_records(e)
        p = root / f"{name}.json"
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(recs, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(p)
        files["json"] = str(p)
        n_rows = n_rows or len(recs)
        n_cols = n_cols or (len(recs[0]) if recs else 0)
    if o.get("zip", True):
        step and step("ساخت بسته‌ی فشرده‌ی نهایی (ZIP)")
        zp = root / f"{name}.zip"
        with_raw = bool(o.get("zip_include_raw"))
        keep = {str(Path(r)) for r in _final_image_paths(eid, root)}
        tmpz = zp.with_name(zp.name + ".tmp")
        with zipfile.ZipFile(tmpz, "w", zipfile.ZIP_DEFLATED) as z:
            for k in ("xlsx", "csv", "json") + (("raw_xlsx", "raw_json") if with_raw else ()):
                if k in files and Path(files[k]).exists():
                    z.write(files[k], Path(files[k]).name)
            folder = root / name
            if folder.exists():
                for f in sorted(folder.rglob("*")):
                    if not f.is_file() or f.name.endswith((".part", ".tmp")):
                        continue
                    if is_intermediate(f):
                        if not with_raw:
                            continue  # خام و میانی در بسته‌ی نهایی نمی‌آیند
                    elif keep and str(f) not in keep:
                        continue  # تصاویری که از کاتالوگ حذف شده‌اند
                    z.write(f, f.relative_to(root).as_posix())
        tmpz.replace(zp)
        files["zip"] = str(zp)
    if (root / name).exists():
        files["images_dir"] = str(root / name)
    res = dict(e["result"])
    res.update({"root": str(root), "files": files, "rows": n_rows, "columns": n_cols, "stats": stats,
                "format_schemas": {f: schema_of(e, s)["name"] for f, s in fs.items()}, "built_at": db.now()})
    db.update("exports", eid, result=res, files_stale=0, updated_at=db.now())
    return res


def _final_image_paths(eid: int, root: Path) -> list[Path]:
    out = []
    for r in db.q("SELECT images FROM export_rows WHERE export_id=? AND status='ok'", [eid]):
        im = db.jload(r["images"], {}) or {}
        for p in [im.get("feature")] + list(im.get("gallery") or []):
            if p:
                out.append(root / p)
    return out


# ---------------------------------------------------------------------------
# فهرست، جزئیات و مدیریت
# ---------------------------------------------------------------------------

def summary(e: dict) -> dict:
    e = export_row_meta(e)
    o = e["options"]
    cnt = db.q1("SELECT COUNT(*) AS n, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok, SUM(CASE WHEN edited<>'{}' THEN 1 ELSE 0 END) AS edited "
                "FROM export_rows WHERE export_id=?", [e["id"]])
    fs = format_schemas(o)
    return {
        "id": e["id"], "name": e["name"], "title": e.get("title") or e["name"], "notes": e.get("notes") or "", "state": e.get("state") or "draft",
        "status": e["status"], "step": e.get("step"), "error": e.get("error"), "created_at": e["created_at"], "updated_at": e.get("updated_at"),
        "finished_at": e.get("finished_at"), "dataset_ids": e["dataset_ids"], "formats": list(fs),
        "format_schemas": {f: {"id": s, "name": (schema_of(e, s) or {}).get("name", "?")} for f, s in fs.items()},
        "rows": cnt["n"] or 0, "rows_ok": cnt["ok"] or 0, "rows_edited": cnt["edited"] or 0, "files_stale": bool(e.get("files_stale")),
        "files": e["result"].get("files") or {}, "root": e["result"].get("root"), "managed": bool(cnt["n"]),
        "datasets": [d for d in (db.q1("SELECT id, code, title FROM datasets WHERE id=?", [i]) for i in e["dataset_ids"]) if d],
        "link_mode": o.get("link_mode", "relative"), "options": {k: o.get(k) for k in ("rembg", "align", "keep_raw", "zip", "images", "link_mode", "link_prefix", "folder_mode")},
    }


def list_catalogs(q: str = "", state: str = "") -> list[dict]:
    sql, args = "SELECT * FROM exports WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR title LIKE ? OR notes LIKE ?)"
        args += [f"%{q}%"] * 3
    if state:
        sql += " AND state=?"
        args.append(state)
    return [summary(e) for e in db.q(sql + " ORDER BY id DESC LIMIT 300", args)]


def detail(eid: int) -> dict:
    e = get_export(eid)
    out = summary(e)
    out["schemas"] = []
    for sid in schema_ids(e["options"]):
        sc = schema_of(e, sid)
        if sc:
            out["schemas"].append({"id": sc["id"], "name": sc["name"], "formats": [f for f, s in format_schemas(e["options"]).items() if s == sid],
                                   "columns": _cols(sc)})
    out["history_count"] = db.val("SELECT COUNT(*) FROM history WHERE (entity='export_row' OR entity='export') AND parent_id=?", [eid]) or 0
    return out


def file_url(root: Path, rel: str) -> str:
    from urllib.parse import quote
    return f"/api/file?path={quote(str(root / rel))}&any=1"


def get_rows(eid: int, sid: int | None = None, q: str = "", flt: str = "", page: int = 1, size: int = 50, ids: list | None = None) -> dict:
    e = get_export(eid)
    sid = sid or schema_ids(e["options"])[0]
    root = _root(e)
    where, args = ["export_id=?"], [eid]
    if q:
        where.append("(title LIKE ? OR values_json LIKE ? OR folder LIKE ?)")
        args += [f"%{q}%"] * 3
    if flt == "edited":
        where.append("edited<>'{}'")
    elif flt == "excluded":
        where.append("status='excluded'")
    elif flt == "noimage":
        where.append("(images='{}' OR images LIKE '%\"feature\": \"\"%')")
    elif flt == "warn":
        where.append("flags LIKE ?")
        args.append(f'%"{sid}": {{"%')
    if ids:
        where.append(f"id IN ({','.join('?' * len(ids))})")
        args += [int(i) for i in ids]
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) FROM export_rows WHERE {w}", args) or 0
    rows = [row_dict(r) for r in db.q(f"SELECT * FROM export_rows WHERE {w} ORDER BY seq, id LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])]
    for r in rows:
        r["v"] = r["values"].get(str(sid)) or {}
        r["f"] = r["flags"].get(str(sid)) or {}
        r["e"] = r["edited"].get(str(sid)) or {}
        im = r["images"]
        r["image_urls"] = {"feature": file_url(root, im["feature"]) if im.get("feature") else "",
                           "gallery": [file_url(root, g) for g in im.get("gallery") or []]}
        r.pop("values")
        r.pop("flags")
        r.pop("edited")
    return {"total": total, "page": page, "size": size, "schema_id": sid, "rows": rows}


def update_meta(eid: int, body: dict, actor: str = "ui") -> dict:
    e = get_export(eid)
    upd = {}
    for k in ("title", "notes", "state"):
        if k in body and body[k] != e.get(k):
            if k == "state" and body[k] not in STATES:
                raise ValueError("وضعیت نامعتبر است.")
            db.history("export", eid, k, e.get(k) or "", body[k], actor=actor, action="meta", parent_id=eid)
            upd[k] = body[k]
    if "link_mode" in body or "link_prefix" in body or "zip_include_raw" in body or "format_schemas" in body or "formats" in body:
        o = dict(e["options"])
        for k in ("link_mode", "link_prefix", "zip_include_raw"):
            if k in body:
                o[k] = body[k]
        if "formats" in body:
            o["formats"] = [f for f in body["formats"] if f in FORMATS] or ["xlsx"]
        if "format_schemas" in body:
            new_fs = {f: int(s) for f, s in (body["format_schemas"] or {}).items() if f in FORMATS and s}
            missing = [s for s in new_fs.values() if str(s) not in _snap_schema_ids(eid)]
            if missing:
                raise ValueError("برای اسکیمایی که در زمان ساخت این خروجی نبوده، خروجی را دوباره بسازید یا آن اسکیما را به خروجی اضافه کنید.")
            o["format_schemas"] = new_fs
        db.history("export", eid, "options", {k: e["options"].get(k) for k in ("link_mode", "link_prefix", "formats", "format_schemas")},
                   {k: o.get(k) for k in ("link_mode", "link_prefix", "formats", "format_schemas")}, actor=actor, action="meta", parent_id=eid)
        upd["options"] = o
        upd["files_stale"] = 1
    if upd:
        upd["updated_at"] = db.now()
        db.update("exports", eid, **upd)
    return detail(eid)


def _snap_schema_ids(eid: int) -> set[str]:
    r = db.q1("SELECT values_json FROM export_rows WHERE export_id=? LIMIT 1", [eid])
    return set((db.jload(r["values_json"], {}) or {}).keys()) if r else set()


def add_schema(eid: int, sid: int, actor: str = "ui") -> dict:
    """افزودن یک اسکیمای دیگر به خروجی (مثلاً برای قالب JSON) — مقادیر از محصولات بانک داده محاسبه می‌شوند."""
    e = get_export(eid)
    if not db.q1("SELECT id FROM schemas WHERE id=?", [sid]):
        raise ValueError("اسکیما پیدا نشد.")
    schema = services.get_schema(sid)
    eo = dict(e["options"])
    eo.setdefault("schema_snapshots", {})[str(sid)] = {"id": schema["id"], "name": schema["name"], "columns": schema["columns"]}
    db.update("exports", eid, options=eo)
    settings = db.get_settings()
    used: dict[str, int] = {}
    for r in db.q("SELECT * FROM export_rows WHERE export_id=? ORDER BY seq, id", [eid]):
        row = row_dict(r)
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [row["item_id"]])) if row["item_id"] else None
        vals, flags = {}, {}
        if it:
            ds = services.get_dataset(it["dataset_id"])
            src = services.get_source(it["source_id"])
            for col in _cols(schema):
                v, fl = services.column_value(col, it, ds, settings, src)
                if col.get("kind") == "auto" and col.get("generator", "slug") == "slug" and v:
                    n = used.get(v, 0)
                    used[v] = n + 1
                    v = f"{v}-{n + 1}" if n else v
                vals[col["key"]] = v
                if fl:
                    flags[col["key"]] = fl
        row["values"][str(sid)] = vals
        row["flags"][str(sid)] = flags
        db.update("export_rows", row["id"], values_json=row["values"], flags=row["flags"], updated_at=db.now())
    db.history("export", eid, "schemas", "", schema["name"], actor=actor, action="add_schema", parent_id=eid)
    mark_stale(eid)
    return detail(eid)


def _get_row(eid: int, rid: int) -> dict:
    r = db.q1("SELECT * FROM export_rows WHERE id=? AND export_id=?", [rid, eid])
    if not r:
        raise ValueError("ردیف پیدا نشد.")
    return row_dict(r)


def _save_row(row: dict, **extra):
    db.update("export_rows", row["id"], values_json=row["values"], flags=row["flags"], edited=row["edited"],
              images=row["images"], updated_at=db.now(), **extra)


def set_values(eid: int, rid: int, sid: int, values: dict, actor: str = "ui", note: str = "") -> dict:
    row = _get_row(eid, rid)
    schema = schema_of(get_export(eid), sid)
    cols = {c["key"]: c for c in schema["columns"]}
    bad = [k for k in values if k not in cols]
    if bad:
        raise ValueError(f"این ستون‌ها در اسکیمای «{schema['name']}» نیستند: {', '.join(bad)}")
    v = row["values"].setdefault(str(sid), {})
    ed = row["edited"].setdefault(str(sid), {})
    fl = row["flags"].setdefault(str(sid), {})
    changed = 0
    for k, nv in values.items():
        if cols[k].get("input") in ("image", "images"):
            continue  # تصاویر با عملیات تصویر مدیریت می‌شوند
        if _same(v.get(k), nv):
            continue
        db.history("export_row", rid, f"{sid}:{k}", v.get(k, ""), nv, actor=actor, action="edit" if actor != "ai" else "ai", parent_id=eid, note=note)
        v[k] = nv
        ed[k] = actor
        fl.pop(k, None)
        changed += 1
    if changed:
        _save_row(row)
        mark_stale(eid)
    return row


def update_row(eid: int, rid: int, body: dict, actor: str = "ui") -> dict:
    row = _get_row(eid, rid)
    if body.get("values"):
        row = set_values(eid, rid, int(body.get("schema_id") or schema_ids(get_export(eid)["options"])[0]), body["values"], actor)
    extra = {}
    for k in ("status", "note", "title"):
        if k in body and body[k] != row.get(k):
            if k == "status" and body[k] not in ("ok", "excluded"):
                raise ValueError("وضعیت ردیف نامعتبر است.")
            db.history("export_row", rid, k, row.get(k) or "", body[k], actor=actor, action=k, parent_id=eid)
            extra[k] = body[k]
    if extra:
        db.update("export_rows", rid, updated_at=db.now(), **extra)
        mark_stale(eid)
    return _get_row(eid, rid)


def delete_row(eid: int, rid: int, actor: str = "ui"):
    row = _get_row(eid, rid)
    db.history("export_row", rid, "*", {k: row.get(k) for k in ("item_id", "title", "images", "values")}, "", actor=actor, action="delete", parent_id=eid)
    db.ex("DELETE FROM export_rows WHERE id=?", [rid])
    mark_stale(eid)


def bulk(eid: int, body: dict, actor: str = "ui") -> dict:
    """ویرایش گروهی: تعیین مقدار، جست‌وجو و جایگزینی، افزودن پیشوند/پسوند، تغییر وضعیت ردیف‌ها."""
    e = get_export(eid)
    sid = int(body.get("schema_id") or schema_ids(e["options"])[0])
    ids = [int(i) for i in body.get("row_ids") or []] or [r["id"] for r in db.q("SELECT id FROM export_rows WHERE export_id=?", [eid])]
    n = 0
    fr = body.get("find_replace") or {}
    live, snap = {}, {c["key"]: c for c in (schema_of(e, sid) or {}).get("columns", [])}
    if body.get("apply_default"):  # پیش‌فرض‌های فعلی اسکیما (حتی اگر پس از ساخت خروجی تعریف شده باشند)
        cur_schema = services.schema_row(db.q1("SELECT * FROM schemas WHERE id=?", [sid]))  # اگر حذف شده باشد، نسخه‌ی ذخیره‌شده
        live = {c["key"]: c for c in (cur_schema or {}).get("columns", [])}
    for rid in ids:
        row = _get_row(eid, rid)
        vals = {}
        for k, val in (body.get("set") or {}).items():
            vals[k] = val
        if fr.get("key") and fr.get("find") is not None:
            cur = (row["values"].get(str(sid)) or {}).get(fr["key"])
            nv = _replace_any(cur, fr["find"], fr.get("replace", ""), bool(fr.get("regex")))
            if not _same(cur, nv):
                vals[fr["key"]] = nv
        for k, add in (body.get("prepend") or {}).items():
            cur = (row["values"].get(str(sid)) or {}).get(k) or ""
            if isinstance(cur, str):
                vals[k] = add + cur
        for k, add in (body.get("append") or {}).items():
            cur = (row["values"].get(str(sid)) or {}).get(k) or ""
            if isinstance(cur, str):
                vals[k] = cur + add
        for k in body.get("apply_default") or []:
            col = live.get(k) or snap.get(k)
            if not col:
                continue
            cur = vals.get(k, (row["values"].get(str(sid)) or {}).get(k))
            nv = services.apply_default(col, cur, mode=body.get("default_mode"))
            if not _same(cur, nv):
                vals[k] = nv
        if vals:
            set_values(eid, rid, sid, vals, actor, note="bulk")
            n += 1
        if body.get("status") in ("ok", "excluded") and body["status"] != row.get("status"):
            update_row(eid, rid, {"status": body["status"]}, actor)
            n += 1
    return {"updated": n}


def _replace_any(v, find: str, rep: str, regex: bool):
    if isinstance(v, str):
        return re.sub(find, rep, v) if regex else v.replace(find, rep)
    if isinstance(v, list):
        return [_replace_any(x, find, rep, regex) for x in v]
    if isinstance(v, dict):
        return {k: _replace_any(x, find, rep, regex) for k, x in v.items()}
    return v


def revert(h: dict, actor: str = "ui"):
    eid = h["parent_id"]
    try:
        old = json.loads(h["old"]) if h["old"] not in ("", None) else ""
    except ValueError:
        old = h["old"]
    if h["action"] == "images":
        row = _get_row(eid, h["entity_id"])
        db.history("export_row", row["id"], "images", row["images"], old, actor=actor, action="images", parent_id=eid, note=f"revert:{h['id']}")
        row["images"] = old if isinstance(old, dict) else {}
        _save_row(row)
        mark_stale(eid)
        return
    if ":" in h["field"]:
        sid, key = h["field"].split(":", 1)
        set_values(eid, h["entity_id"], int(sid), {key: old}, actor, note=f"revert:{h['id']}")
        return
    if h["field"] in ("status", "note", "title"):
        update_row(eid, h["entity_id"], {h["field"]: old}, actor)
        return
    raise ValueError("این تغییر قابل بازگردانی نیست.")


def sync_to_items(eid: int, sid: int | None = None, actor: str = "ui") -> dict:
    """ویرایش‌های خروجی به‌عنوان «ویرایش دستی» روی محصولات بانک داده هم اعمال می‌شوند (برای خروجی‌های بعدی)."""
    e = get_export(eid)
    n = 0
    for r in db.q("SELECT * FROM export_rows WHERE export_id=? AND edited<>'{}'", [eid]):
        row = row_dict(r)
        if not row["item_id"]:
            continue
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [row["item_id"]]))
        if not it:
            continue
        ds = services.get_dataset(it["dataset_id"])
        item_cols = {c["key"] for c in services.get_schema(ds["schema_id"])["columns"]}
        ov = dict(it.get("overrides") or {})
        for s, keys in row["edited"].items():
            if sid and int(s) != int(sid):
                continue
            for k in keys:
                if k in item_cols:
                    ov[k] = (row["values"].get(s) or {}).get(k)
        if ov != (it.get("overrides") or {}):
            services.record_item_change(it, {"overrides": ov}, actor, note=f"export:{eid}")
            db.update("items", it["id"], overrides=ov, updated_at=db.now())
            n += 1
    db.history("export", eid, "sync", "", f"{n} محصول", actor=actor, action="sync", parent_id=eid)
    return {"items_updated": n}


def delete_catalog(eid: int, delete_files: bool = False, actor: str = "ui") -> dict:
    e = get_export(eid)
    removed = []
    if delete_files:
        root = _root(e)
        name = e["options"].get("name") or e["name"]
        for k, p in (e["result"].get("files") or {}).items():
            pp = Path(p)
            if k != "images_dir" and pp.exists() and pp.is_file() and pp.parent == root:
                pp.unlink()
                removed.append(pp.name)
        d = root / name
        if d.exists() and d.is_dir() and d.parent == root:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name + "/")
    db.history("export", eid, "*", {"name": e["name"], "title": e.get("title"), "files": e["result"].get("files")}, "", actor=actor,
               action="delete", parent_id=eid, note="files deleted" if delete_files else "")
    db.ex("DELETE FROM export_rows WHERE export_id=?", [eid])
    db.ex("DELETE FROM exports WHERE id=?", [eid])
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------------------
# تصاویر ردیف
# ---------------------------------------------------------------------------

def _row_dir(e: dict, row: dict) -> Path:
    root = _root(e)
    name = e["options"].get("name") or e["name"]
    folder = row.get("folder") or f"row-{row['id']}"
    d = root / name / folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def _align_opts(e: dict):
    o = e["options"]
    if o.get("align") is False:
        return False
    if isinstance(o.get("align"), dict):
        return align_mod.normalize(o["align"], db.get_settings().get("image_align"))
    return align_mod.normalize(db.get_settings().get("image_align"))


def _variants(p: Path) -> list[Path]:
    """همه‌ی نسخه‌های یک تصویر (نهایی، خام، میانی) با هر پسوندی."""
    base, _ = stage_of(p)
    return [f for f in p.parent.glob(base + "*") if f.suffix.lower() in IMAGE_EXTS and stage_of(f)[0] == base]


def _rename_set(src: Path, new_base: str):
    """تغییر نام یک تصویر و همه‌ی نسخه‌های خام/میانی‌اش به نام پایه‌ی جدید (مثلاً gallery_3 → gallery_2)."""
    moved = {}
    for f in _variants(src):
        _, st = stage_of(f)
        suf = {"raw": RAW_SUFFIX, "rembg": REMBG_SUFFIX, "final": ""}[st]
        dst = f.with_name(new_base + suf + f.suffix)
        tmp = f.with_name(f"__tmp_{new_base}{suf}{f.suffix}")
        f.replace(tmp)
        moved[tmp] = dst
    return moved


def _normalize_names(e: dict, row: dict):
    """پس از حذف، جابه‌جایی یا افزودن، نام فایل‌ها دوباره feature و gallery_1..N می‌شوند."""
    root = _root(e)
    im = row["images"]
    order = [("feature", im.get("feature"))] + [(f"gallery_{i}", g) for i, g in enumerate(im.get("gallery") or [], 1)]
    pending = {}
    for base, rel in order:
        if not rel:
            continue
        p = root / rel
        if not p.exists():
            continue
        if stage_of(p)[0] != base:
            pending.update(_rename_set(p, base))
    for tmp, dst in pending.items():
        tmp.replace(dst)
    # مسیرهای جدید
    def rel_of(base, old_rel):
        if not old_rel:
            return ""
        p = root / old_rel
        ext = p.suffix
        return str(Path(old_rel).parent / f"{base}{ext}").replace("\\", "/")
    im["feature"] = rel_of("feature", im.get("feature")) if im.get("feature") else ""
    im["gallery"] = [rel_of(f"gallery_{i}", g) for i, g in enumerate(im.get("gallery") or [], 1)]
    row["images"] = im


def image_action(eid: int, rid: int, action: str, body: dict, actor: str = "ui") -> dict:
    from . import images as img_mod
    e = get_export(eid)
    row = _get_row(eid, rid)
    root = _root(e)
    before = json.loads(json.dumps(row["images"]))
    im = row["images"]
    im.setdefault("gallery", [])
    im.setdefault("feature", "")
    slot = body.get("slot", "gallery")
    idx = int(body.get("index") or 0)
    d = _row_dir(e, row)
    aopts = _align_opts(e) if body.get("align", True) is not False else False
    use_rembg = bool(body.get("rembg", e["options"].get("rembg", True)))

    def process(raw: Path, base: str) -> str:
        """از فایل خام، نسخه‌ی میانی و نهایی ساخته می‌شود."""
        suffix = align_mod.out_suffix(aopts) if aopts else (".png" if use_rembg else raw.suffix)
        final = d / f"{base}{suffix}"
        if use_rembg or aopts:
            remover = img_mod.BgRemover(e["options"].get("rembg_model") or db.get_settings()["rembg_model"]) if use_rembg else None
            inter = d / f"{base}{REMBG_SUFFIX}.png" if (use_rembg and aopts) else None
            img_mod.process_file(raw, final, remover, align=aopts if aopts else False, intermediate=inter, reuse_intermediate=False)
        else:
            shutil.copyfile(raw, final)
        return final.relative_to(root).as_posix()

    def new_base(target_slot: str) -> str:
        return "feature" if target_slot == "feature" else f"gallery_{len(im['gallery']) + 1}"

    def prep():
        """پیش از نوشتن فایل جدید شاخص، فایل قبلی کنار گذاشته می‌شود تا هم‌نام نشوند."""
        if slot == "feature" and im.get("feature"):
            _discard(root / im["feature"])
            im["feature"] = ""
        return "feature" if slot == "feature" else "__new"

    def put(rel: str, target_slot: str, replace_index: int | None = None):
        if target_slot == "feature":
            im["feature"] = rel
        elif replace_index is not None and 0 <= replace_index < len(im["gallery"]):
            _discard(root / im["gallery"][replace_index])
            im["gallery"][replace_index] = rel
        else:
            im["gallery"].append(rel)

    if action == "upload":
        data = body.get("data_url") or ""
        raw_bytes = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data)
        ext = (Path(body.get("name") or "x.png").suffix.lower() or ".png")
        ext = ext if ext in IMAGE_EXTS else ".png"
        base = prep()
        raw = d / f"{base}{RAW_SUFFIX}{ext}"
        raw.write_bytes(raw_bytes)
        rel = process(raw, base)
        put(rel, slot, idx if body.get("replace") else None)
    elif action == "url":
        import requests
        r = requests.get(body["url"], timeout=40, headers={"User-Agent": db.get_settings().get("user_agent")})
        r.raise_for_status()
        ext = img_mod.guess_ext(body["url"], r.headers.get("content-type", ""))
        base = prep()
        raw = d / f"{base}{RAW_SUFFIX}{ext}"
        raw.write_bytes(r.content)
        rel = process(raw, base)
        put(rel, slot, idx if body.get("replace") else None)
    elif action == "generate":
        from .ai import set_context
        from .ai_studio import default_client
        set_context(purpose="تصویر کاتالوگ نهایی", ref=f"export:{eid}", item_id=row.get("item_id"))
        client, _ = default_client(body.get("provider_id"), need_image=True)
        title = row.get("title") or ""
        prompt = (body.get("prompt") or "Professional e-commerce product photo of: {title}. Single product, centered, pure white background, "
                  "soft studio lighting, realistic, high detail, no text, no watermark.").replace("{title}", title)
        ref = None
        if body.get("use_reference", True) and im.get("feature") and (root / im["feature"]).exists():
            ref = (root / im["feature"]).read_bytes()
        data = client.image(prompt, size=body.get("size") or "1024x1024", reference=ref)
        base = prep()
        raw = d / f"{base}{RAW_SUFFIX}.png"
        raw.write_bytes(data)
        rel = process(raw, base)
        put(rel, slot, idx if body.get("replace") else None)
    elif action == "delete":
        if slot == "feature":
            if im.get("feature"):
                _discard(root / im["feature"])
            im["feature"] = im["gallery"].pop(0) if (body.get("promote", True) and im["gallery"]) else ""
        elif 0 <= idx < len(im["gallery"]):
            _discard(root / im["gallery"].pop(idx))
    elif action == "make_feature":
        if 0 <= idx < len(im["gallery"]):
            g = im["gallery"].pop(idx)
            if im.get("feature"):
                im["gallery"].insert(0, im["feature"])
            im["feature"] = g
    elif action == "move":
        to = int(body.get("to") or 0)
        if 0 <= idx < len(im["gallery"]) and 0 <= to < len(im["gallery"]):
            g = im["gallery"].pop(idx)
            im["gallery"].insert(to, g)
    elif action == "reprocess":
        targets = [("feature", im["feature"])] if slot == "feature" else ([(f"g{idx}", im["gallery"][idx])] if slot == "gallery" and idx < len(im["gallery"]) else [])
        if slot == "all":
            targets = [("feature", im["feature"])] + [(f"g{i}", g) for i, g in enumerate(im["gallery"])]
        for _, rel in targets:
            if not rel:
                continue
            p = root / rel
            base, _st = stage_of(p)
            raws = [f for f in _variants(p) if stage_of(f)[1] == "raw"]
            src = raws[0] if raws else p
            if src == p:  # خامی نیست؛ از نسخه‌ی نهایی فعلی یک خام ساخته می‌شود
                src = p.with_name(base + RAW_SUFFIX + p.suffix)
                shutil.copyfile(p, src)
            newrel = process(src, base)
            if newrel != rel:
                if p.exists() and (root / newrel) != p:
                    p.unlink()
                if slot == "feature" or rel == im.get("feature"):
                    im["feature"] = newrel
                else:
                    im["gallery"] = [newrel if g == rel else g for g in im["gallery"]]
    else:
        raise ValueError("عملیات تصویر ناشناخته است.")
    _normalize_names(e, row)
    db.history("export_row", rid, "images", before, row["images"], actor=actor, action="images", parent_id=eid, note=action)
    _save_row(row)
    mark_stale(eid)
    out = get_rows(eid, ids=[rid])["rows"]
    return out[0] if out else {}


def _discard(p: Path):
    """تصویر حذف‌شده از کاتالوگ به پوشه‌ی _removed منتقل می‌شود (نه حذف قطعی)."""
    if not p.exists():
        return
    trash = p.parent / "_removed"
    trash.mkdir(exist_ok=True)
    stamp = db.now().replace(":", "").replace("-", "")[:15]
    for f in _variants(p):
        f.replace(trash / f"{stamp}_{f.name}")


# ---------------------------------------------------------------------------
# هوش مصنوعی روی ردیف‌های خروجی
# ---------------------------------------------------------------------------

def ai_row(eid: int, rid: int, sid: int, cfg: dict, client, settings: dict, overwrite: bool = False, actor: str = "ai") -> dict:
    """تولید مقدار ستون‌های انتخابی یک ردیف خروجی با هوش مصنوعی؛ نتیجه مستقیم در ردیف ذخیره می‌شود."""
    from . import ai_gen
    from .ai import AIError, parse_json
    e = get_export(eid)
    row = _get_row(eid, rid)
    schema = schema_of(e, sid)
    cols = {c["key"]: c for c in schema["columns"]}
    cur = row["values"].get(str(sid)) or {}
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [row["item_id"]])) if row.get("item_id") else None
    if it:
        ds = services.get_dataset(it["dataset_id"])
        ctx = ai_gen.product_context(it, ds, services.get_source(it["source_id"]))
    else:
        ctx = {"title": row.get("title", ""), "title_en": "", "brand": "", "category": "", "specs": "", "short_description": "", "long_description": ""}
    # مقادیر فعلی همین ردیف (پس از ویرایش‌ها) بر داده‌ی منبع مقدم‌اند
    ctx["title"] = cur.get("title") or ctx["title"]
    if isinstance(cur.get("short_description"), str) and cur.get("short_description"):
        ctx["short_description"] = cur["short_description"]
    plan = []
    for f in cfg.get("fields") or []:
        col = cols.get(f.get("target"))
        if not col or not ai_gen.ai_capable(col, allow_fixed=True) or col.get("input") in ("image", "images"):
            continue
        v = cur.get(col["key"])
        if f.get("mode") == "fill_missing" and not ai_gen._is_empty(v):
            continue
        plan.append({"field": f, "col": col, "current": v, "shape": ai_gen._shape(col)})
    results = {}
    if plan:
        system, user = ai_gen.build_prompt(cfg, ctx, plan)
        raw = client.chat(system, user, model=cfg.get("model") or None, temperature=float(cfg.get("temperature", 0.7)),
                          max_tokens=int(cfg.get("max_tokens", 3000)))
        try:
            obj = parse_json(raw)
        except AIError:
            obj = {plan[0]["col"]["key"]: raw} if len(plan) == 1 else {}
        for p in plan:
            k = p["col"]["key"]
            if k in obj:
                val = ai_gen._normalize(p["shape"][0], obj[k], p["col"], settings)
                if not ai_gen._is_empty(val):
                    results[k] = val
        if results:
            set_values(eid, rid, sid, results, actor=actor, note="ai")
    for ic in ai_gen.image_configs(cfg):
        col = cols.get(ic.get("target"))
        if not col:
            continue
        im = row["images"]
        has = bool(im.get("feature")) if col.get("input") == "image" else bool(im.get("gallery"))
        if ic.get("mode", "fill_missing") == "fill_missing" and has:
            continue
        slot = "feature" if col.get("input") == "image" else "gallery"
        n = 1 if slot == "feature" else max(1, min(6, int(ic.get("count") or 1)))
        for _ in range(n):
            image_action(eid, rid, "generate", {"slot": slot, "prompt": (ic.get("prompt") or "").format_map(ai_gen._SafeDict(ctx)) or None,
                                                "replace": ic.get("mode") == "overwrite" and slot == "feature"}, actor="ai")
        results[col["key"]] = f"{n} تصویر"
    return results
