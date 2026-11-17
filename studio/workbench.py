"""ویرایشگر داده‌ها: بانک‌های تمیز و محصولات تمیز.

جریان داده:  داده‌ی خام (بانک داده و محصولات خام، تغییرناپذیر)  →  بانک تمیز (این فایل)  →  کاتالوگ و انتشار

- هر «بانک تمیز» یک اسکیمای ویرایش دارد و از یک یا چند بانک داده‌ی خام ساخته می‌شود.
- هر «محصول تمیز» فیلدهای هسته دارد (عنوان، اسلاگ، برند، دسته، سازگاری با خودرو، تصاویر، وضعیت) و مقدار بقیه‌ی
  ستون‌های اسکیما را در values نگه می‌دارد. منبع خامش (محصول خام، بانک، لینک) در sources ثبت است.
- هر تغییر یک ریویژن کامل می‌سازد (revisions، موجودیت «product»).
- تصاویر غیرمخرب‌اند: خام ← (حذف پس‌زمینه) ← (دستور ویرایش) ← (ترازبندی) ← نهایی. فایل‌ها در
  data/workbench/bank-<id>/<uid>/ با نام img-<n>_raw.*، img-<n>_raw_rembg.png، img-<n>_edit.png و img-<n>.png.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import threading
import traceback
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

from . import align as align_mod
from . import compat, db, modules, refdata, revisions, rules, services
from .config import WORKBENCH_DIR
from .images import IMAGE_EXTS, download_image
from .textutil import slugify

STATUSES = {"draft": "پیش‌نویس", "review": "در انتظار بازبینی", "approved": "تأییدشده", "rejected": "ردشده",
            "archived": "بایگانی‌شده", "merged": "ادغام‌شده"}
ACTIVE = ("draft", "review", "approved", "rejected")
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# نقش ستون‌ها
# ---------------------------------------------------------------------------

def core_role(col: dict) -> str | None:
    """ستون‌هایی که به فیلدهای هسته‌ی محصول وصل‌اند."""
    kind, inp = col.get("kind"), col.get("input")
    if inp == "vehicles" or (kind == "ref" and col.get("ref") == "vehicles"):
        return "compat"
    if (kind == "mapping" and col.get("map", "brand") == "brand") or (kind == "ref" and col.get("ref") == "brand"):
        return "brand"
    if (kind == "mapping" and col.get("map") == "category") or (kind == "ref" and col.get("ref") == "category"):
        return "category"
    if kind == "auto" and col.get("generator", "slug") == "slug":
        return "slug"
    if col.get("key") == "title" and kind not in ("constant",):
        return "title"
    if inp == "image":
        return "feature"
    if inp == "images":
        return "gallery"
    return None


def file_url(rel: str, ver: str = "") -> str:
    if not rel:
        return ""
    return f"/api/file?path={quote(str(WORKBENCH_DIR / rel))}&any=1" + (f"&v={quote(ver)}" if ver else "")


# ---------------------------------------------------------------------------
# بانک‌ها
# ---------------------------------------------------------------------------

def bank_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["dataset_ids"] = db.jload(r.get("dataset_ids"), []) or []
    r["options"] = db.jload(r.get("options"), {}) or {}
    return r


def get_bank(bid: int) -> dict:
    b = bank_row(db.q1("SELECT * FROM wb_banks WHERE id=?", [bid]))
    if not b:
        raise ValueError("بانک تمیز پیدا نشد.")
    return b


def bank_schema(b: dict) -> dict:
    sc = services.get_schema(b.get("schema_id"))
    if not sc:
        raise ValueError("اسکیمای این بانک پیدا نشد.")
    return sc


def bank_summary(b: dict) -> dict:
    b = dict(b)
    cnt = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM wb_products WHERE bank_id=? GROUP BY status", [b["id"]])}
    b["counts"] = {k: cnt.get(k, 0) for k in STATUSES}
    b["counts"]["total"] = sum(v for k, v in cnt.items() if k not in ("merged", "archived"))
    q = db.q1("SELECT AVG(quality) AS q, SUM(CASE WHEN brand_id IS NULL THEN 1 ELSE 0 END) AS nb, "
              "SUM(CASE WHEN category_id IS NULL THEN 1 ELSE 0 END) AS nc, SUM(CASE WHEN images='[]' THEN 1 ELSE 0 END) AS ni "
              "FROM wb_products WHERE bank_id=? AND status IN ('draft','review','approved','rejected')", [b["id"]])
    b["quality_avg"] = round(q["q"]) if q and q["q"] is not None else None
    b["missing"] = {"brand": q["nb"] or 0, "category": q["nc"] or 0, "images": q["ni"] or 0} if q else {}
    sc = services.get_schema(b.get("schema_id"))
    b["schema"] = {"id": sc["id"], "name": sc["name"]} if sc else None
    b["datasets"] = [d for d in (db.q1("SELECT id, code, title FROM datasets WHERE id=?", [i]) for i in b["dataset_ids"]) if d]
    return b


def list_banks() -> list[dict]:
    return [bank_summary(bank_row(r)) for r in db.q("SELECT * FROM wb_banks ORDER BY id DESC")]


def _bank_dir(bid: int) -> Path:
    d = WORKBENCH_DIR / f"bank-{bid}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_bank(body: dict, actor: str = "ui") -> dict:
    ds_ids = [int(i) for i in body.get("dataset_ids") or []]
    if not ds_ids and not body.get("empty"):
        raise ValueError("دست‌کم یک بانک داده‌ی خام انتخاب کنید.")
    for i in ds_ids:
        if not services.get_dataset(i):
            raise ValueError(f"بانک داده‌ی {i} پیدا نشد.")
    sid = int(body.get("schema_id") or 0) or (services.get_dataset(ds_ids[0])["schema_id"] if ds_ids else None) or services.get_schema(None)["id"]
    if not db.q1("SELECT id FROM schemas WHERE id=?", [sid]):
        raise ValueError("اسکیما پیدا نشد.")
    title = (body.get("title") or "").strip() or (services.get_dataset(ds_ids[0])["title"] if ds_ids else "بانک تمیز")
    opts = {
        "images": body.get("images", True) is not False, "rembg": body.get("rembg", True) is not False,
        "align": body.get("align", True), "rembg_model": body.get("rembg_model") or "", "max_images": int(body.get("max_images") or 10),
        "statuses": body.get("statuses") or ["done", "partial"], "item_ids": [int(i) for i in body.get("item_ids") or []],
        "compat_suggest": body.get("compat_suggest", True) is not False,
    }
    now = db.now()
    code = "WB-" + now[2:10].replace("-", "") + "-" + uuid.uuid4().hex[:4].upper()
    bid = db.ex("INSERT INTO wb_banks(code, title, schema_id, dataset_ids, options, status, step, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [code, title, sid, db.jdump(ds_ids), db.jdump(opts), "pending" if ds_ids else "completed", "", now, now])
    db.log("workbench", bid, f"بانک تمیز «{title}» ساخته شد.")
    if ds_ids:
        BANK_JOBS.start(bid)
    return bank_summary(get_bank(bid))


def update_bank(bid: int, body: dict, actor: str = "ui") -> dict:
    b = get_bank(bid)
    upd = {}
    for k in ("title", "notes"):
        if k in body:
            upd[k] = body[k]
    if "options" in body:
        o = {**b["options"], **{k: v for k, v in (body["options"] or {}).items() if k in ("rembg", "align", "rembg_model", "images", "max_images", "compat_suggest")}}
        upd["options"] = o
    if "schema_id" in body and int(body["schema_id"]) != b["schema_id"]:
        if not db.q1("SELECT id FROM schemas WHERE id=?", [int(body["schema_id"])]):
            raise ValueError("اسکیما پیدا نشد.")
        upd["schema_id"] = int(body["schema_id"])
    if upd:
        db.update("wb_banks", bid, **upd, updated_at=db.now())
    return bank_summary(get_bank(bid))


def add_datasets(bid: int, ds_ids: list[int], actor: str = "ui") -> dict:
    b = get_bank(bid)
    ids = list(dict.fromkeys(b["dataset_ids"] + [int(i) for i in ds_ids]))
    db.update("wb_banks", bid, dataset_ids=ids, status="pending", updated_at=db.now())
    BANK_JOBS.start(bid)
    return bank_summary(get_bank(bid))


def delete_bank(bid: int, files: bool = True, actor: str = "ui") -> dict:
    b = get_bank(bid)
    BANK_JOBS.stop(bid)
    n = db.val("SELECT COUNT(*) FROM wb_products WHERE bank_id=?", [bid]) or 0
    db.ex("DELETE FROM wb_products WHERE bank_id=?", [bid])
    db.ex("DELETE FROM wb_banks WHERE id=?", [bid])
    if files:
        shutil.rmtree(WORKBENCH_DIR / f"bank-{bid}", ignore_errors=True)
    db.history("wb_bank", bid, "*", {"title": b["title"], "products": n}, "", actor=actor, action="delete")
    return {"ok": True, "products": n}


# ---------------------------------------------------------------------------
# محصولات
# ---------------------------------------------------------------------------

def product_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["compat"] = compat.parse(r.get("compat"))
    r["values"] = db.jload(r.pop("values_json", "{}"), {}) or {}
    for k, d in (("images", []), ("flags", {}), ("quality_detail", {}), ("sources", []), ("meta", {})):
        r[k] = db.jload(r.get(k), d) or d
    return r


def get_product(pid: int) -> dict:
    p = product_row(db.q1("SELECT * FROM wb_products WHERE id=?", [pid]))
    if not p:
        raise ValueError("محصول پیدا نشد.")
    return p


def snapshot(p: dict) -> dict:
    return {"title": p["title"], "slug": p["slug"], "brand_id": p.get("brand_id"), "category_id": p.get("category_id"),
            "compat": p["compat"], "values": p["values"], "status": p["status"], "note": p.get("note") or "",
            "images": [{k: im.get(k) for k in ("id", "src", "raw", "rembg", "edit", "final", "recipe", "use_rembg", "origin")} for im in p["images"]]}


def _save(p: dict, actor: str, action: str, note: str = "", rescore: bool = True) -> dict:
    if rescore and modules.is_enabled("quality"):
        try:
            from .modules.quality import score
            res = score(p)
            p["quality"], p["quality_detail"] = res["score"], res
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    p["rev"] = int(p.get("rev") or 0)
    rv = revisions.record("product", p["id"], snapshot(p), actor=actor, action=action, note=note)
    if rv:
        p["rev"] = rv["rev"]
    db.update("wb_products", p["id"], title=p["title"], slug=p["slug"], brand_id=p.get("brand_id"), category_id=p.get("category_id"),
              compat=db.jdump(p["compat"]), values_json=p["values"], images=p["images"], flags=p["flags"], status=p["status"],
              quality=p.get("quality"), quality_detail=p.get("quality_detail") or {}, sources=p["sources"], meta=p["meta"],
              merged_into=p.get("merged_into"), rev=p["rev"], note=p.get("note") or "", updated_at=db.now())
    return p


def _unique_slug(bank_id: int, slug: str, exclude: int = 0) -> str:
    base, n = slug or "product", 1
    s = base
    while db.q1("SELECT id FROM wb_products WHERE bank_id=? AND slug=? AND id<>? AND status<>'merged'", [bank_id, s, exclude]):
        n += 1
        s = f"{base}-{n}"
    return s


def product_value(p: dict, col: dict):
    """مقدار یک ستون اسکیما برای محصول تمیز (ستون‌های هسته از فیلدهای هسته خوانده می‌شوند)."""
    role = core_role(col)
    if role == "title":
        return p["title"]
    if role == "slug":
        return p["slug"]
    if role in ("brand", "category"):
        r = refdata.get(role, p.get(f"{role}_id"))
        if not r:
            return ""
        f = col.get("ref_field") or "slug"
        return r.get(f, r["slug"]) if f != "id" else r["id"]
    if role == "compat":
        return compat.export(p["compat"], col.get("vehicle_format") or "structured")
    if role == "feature":
        return p["images"][0]["final"] if p["images"] else ""
    if role == "gallery":
        return [im["final"] for im in p["images"][1:]]
    if col.get("kind") == "constant":
        if col["key"] in p["values"]:
            return p["values"][col["key"]]
        cv = services.coerce_value(col, col.get("value", ""))
        return "" if cv is None else cv
    v = p["values"].get(col["key"])
    d = services.column_default(col)
    if d is not None:
        v = services.apply_default(col, v, d)
    return v


def view(p: dict, schema: dict | None = None, light: bool = False) -> dict:
    """نمای محصول برای رابط: مقادیر همه‌ی ستون‌ها، برند و دسته، سازگاری، تصاویر با نشانی."""
    if schema is None:
        schema = bank_schema(get_bank(p["bank_id"]))
    out = {k: p.get(k) for k in ("id", "bank_id", "uid", "seq", "title", "slug", "brand_id", "category_id", "status", "quality", "rev",
                                 "note", "created_at", "updated_at", "merged_into")}
    out["status_label"] = STATUSES.get(p["status"], p["status"])
    out["flags"] = p["flags"]
    out["edited"] = (p.get("meta") or {}).get("edited") or {}
    out["v"] = {c["key"]: product_value(p, c) for c in schema["columns"] if c.get("include", True) is not False and core_role(c) not in ("feature", "gallery")}
    b = refdata.get("brand", p.get("brand_id"))
    c = refdata.get("category", p.get("category_id"))
    out["brand"] = {"id": b["id"], "name": b["name"], "slug": b["slug"]} if b else None
    out["category"] = {"id": c["id"], "name": c["name"], "slug": c["slug"]} if c else None
    meta = p.get("meta") or {}
    out["brand_raw"], out["category_raw"] = meta.get("brand_raw", ""), meta.get("category_raw", "")
    out["compat"] = p["compat"]
    out["compat_info"] = compat.describe(p["compat"])
    out["compat_auto"] = bool(meta.get("compat_auto"))
    ver = p.get("updated_at") or ""
    out["images"] = [{**{k: im.get(k) for k in ("id", "src", "origin", "w", "h", "use_rembg")}, "final_url": file_url(im.get("final"), ver),
                      "base_url": file_url(im.get("rembg") or im.get("raw"), ver), "raw_url": file_url(im.get("raw"), ver),
                      "recipe": im.get("recipe"), "edited": bool(im.get("recipe")), "error": im.get("error", "")} for im in p["images"]]
    out["thumb"] = out["images"][0]["final_url"] if out["images"] else ""
    if not light:
        out["sources"] = p["sources"]
        out["quality_detail"] = p.get("quality_detail") or {}
        out["meta"] = {k: meta.get(k) for k in ("compat_suggest", "brand_raw", "category_raw", "merged_from") if meta.get(k)}
    return out


def list_products(bank_id: int | None = None, q: str = "", status: str = "", flt: str = "", page: int = 1, size: int = 50,
                  ids: list | None = None, brand_id: int | None = None, category_id: int | None = None, sort: str = "seq",
                  light: bool = True) -> dict:
    where, args = [], []
    if bank_id:
        where.append("bank_id=?")
        args.append(bank_id)
    if status:
        sts = [s for s in status.split(",") if s in STATUSES]
        where.append(f"status IN ({','.join('?' * len(sts))})")
        args += sts
    else:
        where.append("status IN ('draft','review','approved','rejected')")
    if q:
        where.append("(title LIKE ? OR slug LIKE ? OR values_json LIKE ? OR uid LIKE ?)")
        args += [f"%{q}%"] * 4
    if brand_id:
        where.append("brand_id=?")
        args.append(brand_id)
    if category_id:
        where.append("category_id=?")
        args.append(category_id)
    flt_sql = {"noimage": "images='[]'", "nobrand": "brand_id IS NULL", "nocategory": "category_id IS NULL",
               "compat_all": "compat LIKE '%\"all\": true%'", "compat_auto": "meta LIKE '%\"compat_auto\": true%'",
               "warn": "flags<>'{}'", "edited": "meta LIKE '%\"edited\": {\"%'", "lowq": "(quality IS NULL OR quality < ?)"}
    for f in [x for x in (flt or "").split(",") if x]:
        if f in flt_sql:
            where.append(flt_sql[f])
            if f == "lowq":
                args.append(int((db.get_settings().get("quality") or {}).get("min_score", 70)))
    if ids:
        where.append(f"id IN ({','.join('?' * len(ids))})")
        args += [int(i) for i in ids]
    w = " AND ".join(where) or "1=1"
    order = {"seq": "bank_id, seq, id", "quality": "quality ASC, id", "-quality": "quality DESC, id", "updated": "updated_at DESC",
             "title": "title"}.get(sort, "bank_id, seq, id")
    total = db.val(f"SELECT COUNT(*) FROM wb_products WHERE {w}", args) or 0
    rows = [product_row(r) for r in db.q(f"SELECT * FROM wb_products WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])]
    schemas: dict = {}
    out = []
    for p in rows:
        if p["bank_id"] not in schemas:
            schemas[p["bank_id"]] = bank_schema(get_bank(p["bank_id"]))
        out.append(view(p, schemas[p["bank_id"]], light=light))
    return {"total": total, "page": page, "size": size, "rows": out}


def filtered_ids(bank_id: int | None, body: dict) -> list[int]:
    """شناسه‌های محصولاتی که یک عملیات گروهی رویشان اجرا می‌شود (انتخاب‌شده‌ها یا همه‌ی نتیجه‌های فیلتر)."""
    if body.get("ids"):
        return [int(i) for i in body["ids"]]
    f = body.get("filter") or {}
    res = list_products(bank_id or f.get("bank_id"), f.get("q", ""), f.get("status", ""), f.get("filter", ""), 1, 100000,
                        brand_id=f.get("brand_id"), category_id=f.get("category_id"))
    return [r["id"] for r in res["rows"]]


# ---------------------------------------------------------------------------
# ویرایش
# ---------------------------------------------------------------------------

def _mark_edited(p: dict, key: str, actor: str):
    p.setdefault("meta", {}).setdefault("edited", {})[key] = actor
    p["flags"].pop(key, None)


def update_product(pid: int, body: dict, actor: str = "ui", action: str = "edit", note: str = "", force: bool = False) -> dict:
    p = get_product(pid)
    if p["status"] == "merged" and not force:
        raise ValueError("این محصول در محصول دیگری ادغام شده و قابل ویرایش نیست.")
    schema = bank_schema(get_bank(p["bank_id"]))
    cols = {c["key"]: c for c in schema["columns"]}
    changed = []
    values = dict(body.get("values") or {})
    # ستون‌های هسته از values به فیلدهای هسته منتقل می‌شوند
    for k in list(values):
        col = cols.get(k)
        if not col:
            raise ValueError(f"ستون «{k}» در اسکیمای این بانک نیست.")
        role = core_role(col)
        if role in ("title", "slug"):
            body[role] = values.pop(k)
        elif role in ("brand", "category"):
            v = values.pop(k)
            body[role] = v if isinstance(v, int) or v in (None, "") else (refdata.resolve(role, str(v)) or _bad_ref(role, v))
        elif role == "compat":
            body["compat"] = values.pop(k)
        elif role in ("feature", "gallery"):
            values.pop(k)
    if "title" in body:
        t = str(body["title"] or "").strip()
        if not t:
            raise ValueError("عنوان نمی‌تواند خالی باشد.")
        if t != p["title"]:
            p["title"] = t
            _mark_edited(p, "title", actor)
            changed.append("title")
    if "slug" in body:
        s = str(body["slug"] or "").strip().lower()
        if not _SLUG_RE.match(s):
            raise ValueError(f"اسلاگ «{s}» معتبر نیست؛ فقط حروف کوچک انگلیسی، عدد و خط تیره.")
        if s != p["slug"]:
            if db.q1("SELECT id FROM wb_products WHERE bank_id=? AND slug=? AND id<>? AND status<>'merged'", [p["bank_id"], s, pid]):
                raise ValueError(f"اسلاگ «{s}» در همین بانک تکراری است.")
            p["slug"] = s
            _mark_edited(p, "slug", actor)
            changed.append("slug")
    for role in ("brand", "category"):
        if role in body:
            rid = int(body[role]) if body[role] not in (None, "", 0) else None
            if rid and not refdata.get(role, rid):
                raise ValueError(f"{refdata.LABELS[role]} انتخاب‌شده در فهرست مرجع نیست.")
            if rid != p.get(f"{role}_id"):
                p[f"{role}_id"] = rid
                _mark_edited(p, role, actor)
                changed.append(role)
    if "compat" in body:
        cv = compat.normalize(body["compat"])
        if cv != p["compat"]:
            p["compat"] = cv
            p["meta"].pop("compat_auto", None)
            _mark_edited(p, "compat", actor)
            changed.append("compat")
        elif p["meta"].get("compat_auto"):
            p["meta"].pop("compat_auto", None)  # تأیید پیشنهاد خودکار
            changed.append("compat")
    for k, nv in values.items():
        col = cols[k]
        if col.get("kind") == "constant" and nv in (None, ""):
            if k in p["values"]:
                p["values"].pop(k)
                changed.append(k)
            continue
        nv = services.coerce_value(col, nv) if isinstance(nv, str) and col.get("input") not in ("text", "longtext", None) else nv
        if json.dumps(p["values"].get(k), ensure_ascii=False, sort_keys=True) != json.dumps(nv, ensure_ascii=False, sort_keys=True):
            p["values"][k] = nv
            _mark_edited(p, k, actor)
            changed.append(k)
    if "status" in body and body["status"] != p["status"]:
        st = body["status"]
        if st not in STATUSES or st == "merged":
            raise ValueError("وضعیت نامعتبر است.")
        if st == "approved" and not force and modules.is_enabled("quality"):
            from .modules.quality import score
            res = score(p)
            if res["errors"]:
                raise ValueError("پیش از تأیید این موارد را برطرف کنید: " + "؛ ".join(e["label"] for e in res["errors"][:5]))
        p["status"] = st
        changed.append("status")
        if action == "edit":
            action = "status"
    if "note" in body and (body["note"] or "") != (p.get("note") or ""):
        p["note"] = body["note"] or ""
        changed.append("note")
    if not changed:
        return p
    return _save(p, actor, action, note or body.get("_note", ""))


def _bad_ref(role: str, v):
    raise ValueError(f"«{v}» در فهرست {refdata.LABELS[role]}‌ها نیست؛ اول آن را در «داده‌های مرجع» اضافه کنید.")


def _replace_any(v, find: str, rep: str, regex: bool):
    if isinstance(v, str):
        return re.sub(find, rep, v) if regex else v.replace(find, rep)
    if isinstance(v, list):
        return [_replace_any(x, find, rep, regex) for x in v]
    if isinstance(v, dict):
        return {k: _replace_any(x, find, rep, regex) for k, x in v.items()}
    return v


def bulk(bank_id: int | None, body: dict, actor: str = "ui") -> dict:
    """عملیات گروهی روی محصولات انتخاب‌شده یا همه‌ی نتیجه‌های فیلتر.

    set {key: value} · find_replace {key, find, replace, regex} · prepend/append {key: text} · apply_default [keys]
    brand (id) · category (id) · compat {mode: set|add|remove, value} · status · note
    """
    ids = filtered_ids(bank_id, body)
    n, errors = 0, []
    fr = body.get("find_replace") or {}
    for pid in ids:
        try:
            p = get_product(pid)
            schema = bank_schema(get_bank(p["bank_id"]))
            cols = {c["key"]: c for c in schema["columns"]}
            upd: dict = {"values": {}}
            for k, v in (body.get("set") or {}).items():
                upd["values"][k] = v
            if fr.get("key") and fr.get("find") not in (None, ""):
                col = cols.get(fr["key"])
                cur = product_value(p, col) if col else None
                nv = _replace_any(cur, fr["find"], fr.get("replace", ""), bool(fr.get("regex")))
                if json.dumps(cur, ensure_ascii=False) != json.dumps(nv, ensure_ascii=False):
                    upd["values"][fr["key"]] = nv
            for mode in ("prepend", "append"):
                for k, add in (body.get(mode) or {}).items():
                    col = cols.get(k)
                    if not col:
                        continue
                    cur = product_value(p, col)
                    upd["values"][k] = services.apply_default({**col, "default": add}, cur, add, mode)
            for k in body.get("apply_default") or []:
                col = cols.get(k)
                if col:
                    cur = p["values"].get(k)
                    nv = services.apply_default(col, cur, mode=body.get("default_mode"))
                    if json.dumps(cur, ensure_ascii=False) != json.dumps(nv, ensure_ascii=False):
                        upd["values"][k] = nv
            for role in ("brand", "category", "status", "note"):
                if role in body and body[role] not in (None, "__keep__"):
                    upd[role] = body[role]
            if body.get("compat"):
                cm = body["compat"]
                mode = cm.get("mode", "set")
                newv = compat.normalize(cm.get("value"))
                if mode == "set":
                    upd["compat"] = newv
                elif not newv.get("all"):
                    cur = p["compat"]
                    cur_items = [] if cur.get("all") else cur["items"]
                    if mode == "add":
                        upd["compat"] = {"all": False, "items": cur_items + newv["items"]}
                    elif mode == "remove" and cur_items:
                        rm = {(i["t"], i["id"]) for i in newv["items"]}
                        left = [i for i in cur_items if (i["t"], i["id"]) not in rm]
                        upd["compat"] = {"all": False, "items": left} if left else {"all": True}
            if not upd["values"]:
                upd.pop("values")
            before = p.get("rev")
            r = update_product(pid, upd, actor=actor, action="bulk", force=bool(body.get("force")))
            if r.get("rev") != before:
                n += 1
        except ValueError as exc:
            errors.append({"id": pid, "error": str(exc)})
    return {"updated": n, "total": len(ids), "errors": errors[:50]}


def delete_product(pid: int, hard: bool = False, actor: str = "ui") -> dict:
    p = get_product(pid)
    if not hard:
        update_product(pid, {"status": "archived"}, actor=actor, action="delete", force=True)
        return {"ok": True, "archived": True}
    revisions.record("product", pid, snapshot(p), actor=actor, action="delete", force=True)
    db.ex("DELETE FROM wb_products WHERE id=?", [pid])
    return {"ok": True}


def _restore(pid: int, snap: dict, actor: str):
    p = get_product(pid)
    for k in ("title", "slug", "brand_id", "category_id", "compat", "values", "status", "note"):
        if k in snap:
            p[k] = snap[k]
    if "images" in snap:
        old = {im["id"]: im for im in p["images"]}
        p["images"] = [{**old.get(im["id"], {}), **im} for im in snap["images"]]
    if p["status"] == "merged" and not p.get("merged_into"):
        p["status"] = "draft"
    db.update("wb_products", pid, title=p["title"], slug=p["slug"], brand_id=p.get("brand_id"), category_id=p.get("category_id"),
              compat=db.jdump(p["compat"]), values_json=p["values"], images=p["images"], status=p["status"], note=p.get("note") or "",
              updated_at=db.now())
    if modules.is_enabled("quality"):
        from .modules.quality import score
        res = score(p)
        db.update("wb_products", pid, quality=res["score"], quality_detail=res)


revisions.register_restorer("product", _restore)


# ---------------------------------------------------------------------------
# ورود از داده‌ی خام
# ---------------------------------------------------------------------------

def _item_text(it: dict, ds: dict) -> str:
    d = rules.cleaned(it)
    specs = " ".join(f"{s.get('name', '')} {s.get('value', '')}" for s in (d.get("specifications") or []) if isinstance(s, dict))
    return " ".join(str(x or "") for x in (d.get("title"), d.get("title_en"), d.get("short_description"), specs,
                                             (d.get("long_description") or "")[:1500], d.get("compatible_vehicles")))


def _raw_image_urls(it: dict, schema: dict, ds: dict, settings: dict) -> list[str]:
    urls: list[str] = []
    for col in schema["columns"]:
        if col.get("input") in ("image", "images"):
            v, _ = services.column_value(col, it, ds, settings)
            urls += [u for u in services.as_list(v) if isinstance(u, str) and u]
    if not urls:
        d = rules.cleaned(it)
        urls = [u for u in [d.get("featured_image")] + list(d.get("gallery") or []) if u]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def product_from_item(bank: dict, it: dict, seq: int, settings: dict, schema: dict, session=None) -> dict:
    ds = services.get_dataset(it["dataset_id"])
    src = services.get_source(it["source_id"])
    d = rules.cleaned(it)
    values, flags = {}, {}
    title, slug = d.get("title") or it.get("product_key") or "محصول", ""
    brand_val = cat_val = ""
    for col in schema["columns"]:
        if col.get("include", True) is False:
            continue
        role = core_role(col)
        if role in ("feature", "gallery", "compat"):
            continue
        v, flag = services.column_value(col, it, ds, settings, src)
        if role == "title":
            title = v or title
        elif role == "slug":
            slug = v or slug
        elif role == "brand":
            brand_val = v or ""
        elif role == "category":
            cat_val = v or ""
        elif col.get("kind") != "constant":
            values[col["key"]] = v
        if flag in ("missing",):
            flags[col["key"]] = flag
    brand_raw = (d.get("brand") or d.get("brand_en") or "").strip()
    crumbs = [str(x).strip() for x in (d.get("breadcrumb") or []) if str(x).strip()] if isinstance(d.get("breadcrumb"), list) else []
    cat_item = str(d.get("category") or (crumbs[-1] if crumbs else "") or "").strip()
    cat_raw = (cat_item or ds.get("category_label") or "").strip()
    brand_id = refdata.resolve("brand", brand_val, brand_raw, d.get("brand_en") or "")
    # دسته‌ی خود محصول (یا آخرین قدم breadcrumb) بر برچسب دسته‌ی بانک داده مقدم است
    category_id = refdata.resolve("category", cat_val, cat_item, *crumbs[::-1], ds.get("category_label") or "")
    meta = {"brand_raw": brand_raw if not brand_id else "", "category_raw": cat_raw if not category_id else "", "edited": {}}
    cv = compat.parse(None)
    if bank["options"].get("compat_suggest", True) and compat.available():
        sug = compat.suggest(_item_text(it, ds))
        if sug["matches"]:
            meta["compat_suggest"] = {"value": sug["value"], "confidence": sug["confidence"],
                                      "labels": [m.get("display") or m.get("label") for m in sug["matches"]][:20]}
            if sug["confidence"] >= 85:
                cv = sug["value"]
                meta["compat_auto"] = True
    slug = _unique_slug(bank["id"], (slug or slugify(d.get("title_en") or title) or "product").lower())
    now = db.now()
    uid = f"P{bank['id']}-{it['id']}-{uuid.uuid4().hex[:4]}"
    pid = db.ex("""INSERT INTO wb_products(bank_id, uid, seq, title, slug, brand_id, category_id, compat, values_json, images, flags, status,
                   sources, meta, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [bank["id"], uid, seq, title, slug, brand_id, category_id, db.jdump(cv), db.jdump(values), "[]", db.jdump(flags), "draft",
                 db.jdump([{"item_id": it["id"], "dataset_id": it["dataset_id"], "url": it.get("url", ""), "source": (src or {}).get("name", "")}]),
                 db.jdump(meta), now, now])
    p = get_product(pid)
    if bank["options"].get("images", True):
        for u in _raw_image_urls(it, schema, ds, settings)[: int(bank["options"].get("max_images") or 10)]:
            try:
                _add_image(p, bank, "url", {"url": u, "_session": session, "_referer": it.get("url", "")}, origin="source")
            except Exception as exc:  # noqa: BLE001
                p["meta"].setdefault("image_errors", []).append({"url": u, "error": str(exc)[:200]})
    return _save(p, "system", "import", note=f"از محصول خام {it['id']}")


class BankJobs:
    """ساخت بانک تمیز از داده‌ی خام در پس‌زمینه (قابل توقف و ادامه)."""

    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}
        self.cancel: dict[int, bool] = {}

    def recover(self):
        db.ex("UPDATE wb_banks SET status='paused', step='متوقف شد (استودیو بسته شده بود)' WHERE status IN ('running','pending')")

    def start(self, bid: int):
        t = self.threads.get(bid)
        if t and t.is_alive():
            return
        self.cancel[bid] = False
        db.update("wb_banks", bid, status="running", step="در حال آماده‌سازی", error="", updated_at=db.now())
        t = threading.Thread(target=self._run, args=(bid,), daemon=True)
        self.threads[bid] = t
        t.start()

    def stop(self, bid: int):
        self.cancel[bid] = True

    def wait(self, bid: int, timeout: float = 300):
        t = self.threads.get(bid)
        if t:
            t.join(timeout)

    def _run(self, bid: int):
        try:
            b = get_bank(bid)
            schema = bank_schema(b)
            settings = db.get_settings()
            sts = b["options"].get("statuses") or ["done", "partial"]
            only = set(b["options"].get("item_ids") or [])
            done_items = {s["item_id"] for r in db.q("SELECT sources FROM wb_products WHERE bank_id=?", [bid])
                          for s in (db.jload(r["sources"], []) or []) if s.get("item_id")}
            items = []
            for did in b["dataset_ids"]:
                for r in db.q(f"SELECT * FROM items WHERE dataset_id=? AND status IN ({','.join('?' * len(sts))}) ORDER BY seq, id", [did, *sts]):
                    if r["id"] in done_items or (only and r["id"] not in only):
                        continue
                    items.append(services.item_row(r))
            seq0 = db.val("SELECT COALESCE(MAX(seq), 0) FROM wb_products WHERE bank_id=?", [bid]) or 0
            db.update("wb_banks", bid, progress_total=len(items), progress_done=0, step=f"ورود {len(items)} محصول از داده‌ی خام")
            sess = requests.Session()
            sess.headers["User-Agent"] = settings.get("user_agent")
            for i, it in enumerate(items, 1):
                if self.cancel.get(bid):
                    db.update("wb_banks", bid, status="paused", step="متوقف شد", updated_at=db.now())
                    return
                try:
                    product_from_item(b, it, seq0 + i, settings, schema, sess)
                except Exception as exc:  # noqa: BLE001
                    db.log("workbench", bid, f"ورود محصول خام {it['id']} ناموفق بود: {exc}", level="warning", detail=traceback.format_exc()[-1500:])
                db.update("wb_banks", bid, progress_done=i, step=f"ورود محصولات ({i} از {len(items)})", updated_at=db.now())
            db.update("wb_banks", bid, status="completed", step="آماده", finished_at=db.now(), updated_at=db.now())
            db.log("workbench", bid, f"ورود {len(items)} محصول به بانک تمیز تمام شد.", level="success")
            if modules.is_enabled("dedup"):
                try:
                    from .modules.dedup import scan
                    scan(bid)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            db.update("wb_banks", bid, status="error", error=str(exc)[:500], step="خطا", updated_at=db.now())


BANK_JOBS = BankJobs()


# ---------------------------------------------------------------------------
# تصاویر
# ---------------------------------------------------------------------------

def _pdir(p: dict) -> Path:
    d = _bank_dir(p["bank_id"]) / p["uid"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rel(path: Path) -> str:
    return path.relative_to(WORKBENCH_DIR).as_posix()


def _next_img_id(p: dict) -> int:
    n = int(p["meta"].get("img_seq") or 0) + 1
    p["meta"]["img_seq"] = n
    return n


def _align_opts(bank: dict):
    a = bank["options"].get("align", True)
    if a is False or not modules.is_enabled("align"):
        return False
    if isinstance(a, dict):
        return align_mod.normalize(a, db.get_settings().get("image_align"))
    return align_mod.normalize(db.get_settings().get("image_align"))


def render_image(p: dict, bank: dict, im: dict, redo_rembg: bool = False) -> dict:
    """ساخت دوباره‌ی نسخه‌ی نهایی یک تصویر: خام ← حذف پس‌زمینه ← ویرایش ← ترازبندی."""
    from PIL import Image, ImageOps
    from .images import BgRemover
    d = _pdir(p)
    base = f"img-{im['id']}"
    raw = WORKBENCH_DIR / im["raw"]
    use_rembg = bool(im.get("use_rembg", bank["options"].get("rembg", True))) and modules.is_enabled("rembg")
    im["use_rembg"] = bool(im.get("use_rembg", bank["options"].get("rembg", True)))
    work = None
    if use_rembg:
        rp = d / f"{base}_raw_rembg.png"
        if rp.exists() and not redo_rembg:
            with Image.open(rp) as x:
                x.load()
                work = x.convert("RGBA")
        else:
            with Image.open(raw) as x:
                x.load()
                if getattr(x, "is_animated", False):
                    x.seek(0)
                work = BgRemover(bank["options"].get("rembg_model") or db.get_settings()["rembg_model"]).remove(x)
            align_mod.save_image(work, rp, {"format": "png"})
        im["rembg"] = _rel(rp)
    else:
        im["rembg"] = ""
        with Image.open(raw) as x:
            x.load()
            if getattr(x, "is_animated", False):
                x.seek(0)
            work = ImageOps.exif_transpose(x).convert("RGBA")
    ep = d / f"{base}_edit.png"
    if im.get("recipe") and modules.is_enabled("image_editor"):
        from .modules import image_editor
        work = image_editor.apply(work, im["recipe"])
        align_mod.save_image(work, ep, {"format": "png"})
        im["edit"] = _rel(ep)
    else:
        im["edit"] = ""
    aopts = _align_opts(bank)
    for old in d.glob(f"{base}.*"):
        old.unlink(missing_ok=True)
    if aopts:
        out, _ = align_mod.align_image(work, {**aopts, "_normalized": True})
        final = d / f"{base}{align_mod.out_suffix(aopts)}"
        align_mod.save_image(out, final, aopts)
    else:
        out = work
        final = d / f"{base}.png"
        align_mod.save_image(out, final, {"format": "png"})
    im["final"] = _rel(final)
    im["w"], im["h"] = out.size
    im.pop("error", None)
    return im


def _add_image(p: dict, bank: dict, kind: str, body: dict, origin: str = "upload") -> dict:
    d = _pdir(p)
    iid = _next_img_id(p)
    base = d / f"img-{iid}_raw"
    if kind == "url":
        url = body["url"]
        sess = body.get("_session")
        if sess is None:
            sess = requests.Session()
            sess.headers["User-Agent"] = db.get_settings().get("user_agent")
        raw = download_image(sess, url, base, referer=body.get("_referer") or "")
        src = url
    elif kind == "upload":
        data = body.get("data_url") or ""
        raw_bytes = base64.b64decode(data.split(",", 1)[1] if data.startswith("data:") else data)
        ext = Path(body.get("name") or "x.png").suffix.lower() or ".png"
        raw = base.with_suffix(ext if ext in IMAGE_EXTS else ".png")
        raw.write_bytes(raw_bytes)
        src = body.get("name") or "upload"
    elif kind == "bytes":
        raw = base.with_suffix(".png")
        raw.write_bytes(body["bytes"])
        src = body.get("src") or "ai"
    else:
        raise ValueError("نوع تصویر نامعتبر است.")
    im = {"id": iid, "src": src, "origin": origin, "raw": _rel(raw), "recipe": None,
          "use_rembg": body.get("rembg", bank["options"].get("rembg", True)) is not False}
    render_image(p, bank, im)
    if body.get("slot") == "feature":
        p["images"].insert(0, im)
    else:
        p["images"].append(im)
    return im


def image_action(pid: int, action: str, body: dict, actor: str = "ui") -> dict:
    p = get_product(pid)
    bank = get_bank(p["bank_id"])
    ims = p["images"]
    iid = int(body.get("image_id") or 0)
    idx = next((i for i, x in enumerate(ims) if x["id"] == iid), -1)
    if action in ("delete", "make_feature", "move", "reprocess", "edit", "reset_edit", "rembg") and idx < 0 and not (action == "reprocess" and body.get("all")):
        raise ValueError("تصویر پیدا نشد.")
    note = action
    if action == "upload":
        _add_image(p, bank, "upload", body)
    elif action == "url":
        if not body.get("url"):
            raise ValueError("نشانی تصویر لازم است.")
        _add_image(p, bank, "url", body, origin="url")
    elif action == "generate":
        modules.require("ai")
        from .ai import set_context
        from .ai_studio import default_client
        set_context(purpose="تصویر محصول تمیز", ref=f"product:{pid}")
        client, _ = default_client(body.get("provider_id"), need_image=True)
        prompt = (body.get("prompt") or "Professional e-commerce product photo of: {title}. Single product, centered, pure white background, "
                  "soft studio lighting, realistic, high detail, no text, no watermark.").replace("{title}", p["title"])
        ref = None
        if body.get("use_reference", True) and ims and ims[0].get("raw") and (WORKBENCH_DIR / ims[0]["raw"]).exists():
            ref = (WORKBENCH_DIR / ims[0]["raw"]).read_bytes()
        data = client.image(prompt, size=body.get("size") or "1024x1024", reference=ref)
        _add_image(p, bank, "bytes", {"bytes": data, "src": "ai", "slot": body.get("slot"), "rembg": body.get("rembg")}, origin="ai")
    elif action == "delete":
        ims.pop(idx)  # فایل‌ها می‌مانند تا بازگردانی از ریویژن ممکن باشد
    elif action == "make_feature":
        ims.insert(0, ims.pop(idx))
    elif action == "move":
        to = max(0, min(len(ims) - 1, int(body.get("to") or 0)))
        ims.insert(to, ims.pop(idx))
    elif action == "edit":
        modules.require("image_editor")
        from .modules import image_editor
        ims[idx]["recipe"] = image_editor.normalize(body.get("recipe"))
        render_image(p, bank, ims[idx])
        note = "ویرایش تصویر: " + (image_editor.summary(ims[idx]["recipe"]) or "بدون ویرایش")
    elif action == "reset_edit":
        ims[idx]["recipe"] = None
        render_image(p, bank, ims[idx])
    elif action == "rembg":
        ims[idx]["use_rembg"] = bool(body.get("on", True))
        render_image(p, bank, ims[idx])
    elif action == "reprocess":
        for im in (ims if body.get("all") else [ims[idx]]):
            if im.get("raw"):
                render_image(p, bank, im, redo_rembg=bool(body.get("redo_rembg")))
    else:
        raise ValueError("عملیات تصویر ناشناخته است.")
    _save(p, actor, "images", note=note)
    return view(get_product(pid))


def bulk_images(bank_id: int | None, body: dict, actor: str = "ui") -> dict:
    """پردازش دوباره‌ی تصاویر گروهی (مثلاً پس از تغییر قاعده‌ی ترازبندی بانک)."""
    ids = filtered_ids(bank_id, body)
    n = 0
    for pid in ids:
        p = get_product(pid)
        if p["images"]:
            image_action(pid, "reprocess", {"all": True, "redo_rembg": bool(body.get("redo_rembg")), "image_id": p["images"][0]["id"]}, actor)
            n += 1
    return {"processed": n}


# ---------------------------------------------------------------------------
# هوش مصنوعی
# ---------------------------------------------------------------------------

def ai_product(pid: int, cfg: dict, client, settings: dict, actor: str = "ai") -> dict:
    """تولید ستون‌های انتخابی یک محصول تمیز با هوش مصنوعی؛ نتیجه با ریویژن ذخیره می‌شود."""
    from . import ai_gen
    from .ai import AIError, parse_json
    p = get_product(pid)
    bank = get_bank(p["bank_id"])
    schema = bank_schema(bank)
    cols = {c["key"]: c for c in schema["columns"]}
    src = (p["sources"] or [{}])[0]
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [src.get("item_id")])) if src.get("item_id") else None
    if it:
        ds = services.get_dataset(it["dataset_id"])
        ctx = ai_gen.product_context(it, ds, services.get_source(it["source_id"]))
    else:
        ctx = {"title": "", "title_en": "", "brand": "", "category": "", "specs": "", "short_description": "", "long_description": "", "source": "", "url": ""}
    ctx["title"] = p["title"]
    b = refdata.get("brand", p.get("brand_id"))
    c = refdata.get("category", p.get("category_id"))
    ctx["brand"] = (b or {}).get("name") or ctx["brand"]
    ctx["category"] = (c or {}).get("name") or ctx["category"]
    for k in ("short_description", "long_description"):
        if isinstance(p["values"].get(k), str) and p["values"].get(k):
            ctx[k] = p["values"][k][:3500]
    plan = []
    for f in cfg.get("fields") or []:
        col = cols.get(f.get("target"))
        if not col or not ai_gen.ai_capable(col, allow_fixed=True) or core_role(col) in ("brand", "category", "compat", "feature", "gallery"):
            continue
        v = product_value(p, col)
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
        for pl in plan:
            k = pl["col"]["key"]
            if k in obj:
                val = ai_gen._normalize(pl["shape"][0], obj[k], pl["col"], settings)
                if not ai_gen._is_empty(val):
                    results[k] = val
        if results:
            update_product(pid, {"values": dict(results)}, actor=actor, action="ai")
    for ic in ai_gen.image_configs(cfg):
        col = cols.get(ic.get("target"))
        if not col:
            continue
        p = get_product(pid)
        role = core_role(col)
        has = bool(p["images"]) if role == "feature" else len(p["images"]) > 1
        if ic.get("mode", "fill_missing") == "fill_missing" and has:
            continue
        n = 1 if role == "feature" else max(1, min(6, int(ic.get("count") or 1)))
        for _ in range(n):
            image_action(pid, "generate", {"slot": "feature" if role == "feature" else "gallery",
                                           "prompt": (ic.get("prompt") or "").format_map(ai_gen._SafeDict(ctx)) or None}, actor="ai")
        results[col["key"]] = f"{n} تصویر"
    return results


# ---------------------------------------------------------------------------
# تبدیل «خروجی نهایی» نسخه‌ی ۱.۶ به بانک تمیز
# ---------------------------------------------------------------------------

def from_legacy_export(eid: int, title: str = "", actor: str = "ui") -> dict:
    from . import catalogs
    e = catalogs.get_export(eid)
    sid = catalogs.schema_ids(e["options"])[0]
    schema = services.get_schema(sid) or catalogs.schema_of(e, sid)
    now = db.now()
    code = "WB-" + now[2:10].replace("-", "") + "-" + uuid.uuid4().hex[:4].upper()
    opts = {"images": True, "rembg": False, "align": e["options"].get("align", True), "compat_suggest": True, "legacy_export": eid}
    bid = db.ex("INSERT INTO wb_banks(code, title, schema_id, dataset_ids, options, status, step, created_at, updated_at, finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [code, title or (e.get("title") or e["name"]), sid, db.jdump(e["dataset_ids"]), db.jdump(opts), "completed", "آماده", now, now, now])
    bank = get_bank(bid)
    root = catalogs._root(e)  # noqa: SLF001
    n = 0
    for r in db.q("SELECT * FROM export_rows WHERE export_id=? ORDER BY seq, id", [eid]):
        row = catalogs.row_dict(r)
        vals = row["values"].get(str(sid)) or {}
        values, title_v, slug_v, brand_v, cat_v = {}, row.get("title") or "", "", "", ""
        for col in schema["columns"]:
            role = core_role(col)
            v = vals.get(col["key"])
            if role == "title":
                title_v = v or title_v
            elif role == "slug":
                slug_v = v or ""
            elif role == "brand":
                brand_v = v or ""
            elif role == "category":
                cat_v = v or ""
            elif role is None and col.get("kind") != "constant" and v is not None:
                values[col["key"]] = v
        brand_id = refdata.resolve("brand", brand_v)
        cat_id = refdata.resolve("category", cat_v)
        uid = f"P{bid}-L{row['id']}-{uuid.uuid4().hex[:4]}"
        pid = db.ex("""INSERT INTO wb_products(bank_id, uid, seq, title, slug, brand_id, category_id, compat, values_json, images, flags, status,
                       sources, meta, note, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [bid, uid, row["seq"], title_v or "محصول", _unique_slug(bid, (slug_v or slugify(title_v) or "product").lower()), brand_id, cat_id,
                     db.jdump({"all": True}), db.jdump(values), "[]", "{}", "draft" if row.get("status") == "ok" else "archived",
                     db.jdump([{"item_id": row.get("item_id"), "legacy_export": eid, "legacy_row": row["id"]}]),
                     db.jdump({"brand_raw": brand_v if not brand_id else "", "category_raw": cat_v if not cat_id else "", "edited": {}}),
                     row.get("note") or "", now, now])
        p = get_product(pid)
        im = row["images"] or {}
        for rel in [im.get("feature")] + list(im.get("gallery") or []):
            if rel and (root / rel).exists():
                try:
                    _add_image(p, bank, "upload", {"data_url": base64.b64encode((root / rel).read_bytes()).decode(), "name": Path(rel).name, "rembg": False},
                               origin="legacy")
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        _save(p, actor, "migrate", note=f"از خروجی نسخه‌ی ۱ شماره‌ی {eid}")
        n += 1
    return {"bank": bank_summary(get_bank(bid)), "products": n}

