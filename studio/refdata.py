"""داده‌های مرجع: برندها و دسته‌بندی‌های مگا کارز (فهرست‌های کنترل‌شده).

محصولات تمیز فقط به برند و دسته‌ای از همین فهرست‌ها وصل می‌شوند. نام‌هایی که در داده‌ی خام با هیچ مورد فهرست جور
نشوند، به‌عنوان «پیشنهاد» نگه داشته می‌شوند تا اپراتور یا آن را به یک مورد موجود وصل کند یا (با یک کلیک) به فهرست
بیفزاید. اسلاگ‌ها فقط انگلیسی‌اند.
"""
from __future__ import annotations

import csv
import io
import json
import re

from . import db, revisions
from .textutil import normalize_fa, slugify, to_latin_digits

KINDS = {"brand": "ref_brands", "category": "ref_categories"}
LABELS = {"brand": "برند", "category": "دسته‌بندی"}
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def norm(s: str) -> str:
    """نرمال‌سازی برای مقایسه‌ی نام‌ها: حروف عربی/فارسی، ارقام، فاصله و نیم‌فاصله، حروف کوچک."""
    s = normalize_fa(to_latin_digits(str(s or ""))).lower()
    s = s.replace("‌", " ").replace("-", " ").replace("_", " ")
    s = re.sub(r"[()\[\]«»\"'.,،:؛/\\]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _table(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError("نوع داده‌ی مرجع نامعتبر است.")
    return KINDS[kind]


def row(kind: str, r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["aliases"] = db.jload(r.get("aliases"), []) or []
    if kind == "brand":
        r["category_ids"] = [int(x) for x in (db.jload(r.get("category_ids"), []) or []) if str(x).isdigit() or isinstance(x, int)]
    r["kind"] = kind
    return r


def get(kind: str, rid: int | None) -> dict | None:
    if not rid:
        return None
    return row(kind, db.q1(f"SELECT * FROM {_table(kind)} WHERE id=?", [rid]))


def snapshot(kind: str, r: dict) -> dict:
    keys = ["name", "name_en", "slug", "aliases", "description", "notes", "active"] + (["parent_id", "sort"] if kind == "category" else ["country", "category_ids"])
    return {k: r.get(k) for k in keys}


def list_items(kind: str, q: str = "", active_only: bool = False, with_counts: bool = True, category_id: int | None = None,
               inherit: bool = True) -> list[dict]:
    """فهرست موارد. برای برندها با category_id فقط برندهایی که در آن دسته نمایش داده می‌شوند (inherit: با والدها و زیرشاخه‌ها)."""
    t = _table(kind)
    sql, args = f"SELECT * FROM {t} WHERE 1=1", []
    if active_only:
        sql += " AND active=1"
    if q:
        sql += " AND (name LIKE ? OR name_en LIKE ? OR slug LIKE ? OR aliases LIKE ?)"
        args += [f"%{q}%"] * 4
    order = " ORDER BY sort, name" if kind == "category" else " ORDER BY name"
    rows = [row(kind, r) for r in db.q(sql + order, args)]
    cats = category_index()
    if kind == "brand" and category_id:
        allowed = set(related_categories(category_id, cats) if inherit else [category_id])
        rows = [r for r in rows if allowed & set(r["category_ids"])]
    if with_counts:
        col = "brand_id" if kind == "brand" else "category_id"
        counts = {r["k"]: r["n"] for r in db.q(f"SELECT {col} AS k, COUNT(*) AS n FROM wb_products WHERE {col} IS NOT NULL AND status NOT IN ('merged','archived') GROUP BY {col}")}
        for r in rows:
            r["products"] = counts.get(r["id"], 0)
    if kind == "category":
        bcount: dict[int, int] = {}
        for b in db.q("SELECT category_ids FROM ref_brands"):
            for cid in db.jload(b["category_ids"], []) or []:
                bcount[int(cid)] = bcount.get(int(cid), 0) + 1
        for r in rows:
            c = cats.get(r["id"]) or {}
            r["path"] = c.get("path", r["name"])
            r["path_slug"] = c.get("path_slug", r["slug"])
            r["depth"] = c.get("depth", 0)
            r["children"] = len(c.get("children", []))
            r["brands"] = bcount.get(r["id"], 0)
    else:
        for r in rows:
            r["categories"] = [{"id": cid, "name": cats[cid]["name"], "slug": cats[cid]["slug"], "path": cats[cid]["path"]} for cid in r["category_ids"] if cid in cats]
    return rows


def category_index() -> dict[int, dict]:
    """همه‌ی دسته‌ها با مسیر، عمق و فرزندان (برای درخت و ارث‌بری برندها)."""
    rows = {r["id"]: dict(r) for r in db.q("SELECT id, name, name_en, slug, parent_id, sort, active FROM ref_categories ORDER BY sort, name")}
    for r in rows.values():
        r["children"] = []
    for r in rows.values():
        p = r.get("parent_id")
        if p in rows:
            rows[p]["children"].append(r["id"])
    for r in rows.values():
        parts, sparts, p, guard = [r["name"]], [r["slug"]], r.get("parent_id"), 0
        while p and p in rows and guard < 12:
            parts.insert(0, rows[p]["name"])
            sparts.insert(0, rows[p]["slug"])
            p = rows[p].get("parent_id")
            guard += 1
        r["path"], r["path_slug"], r["depth"] = " › ".join(parts), "/".join(sparts), guard
    return rows


def descendants(cid: int, cats: dict | None = None) -> list[int]:
    cats = cats or category_index()
    out, stack = [], list((cats.get(cid) or {}).get("children", []))
    while stack:
        x = stack.pop()
        if x in out:
            continue
        out.append(x)
        stack.extend(cats.get(x, {}).get("children", []))
    return out


def ancestors(cid: int, cats: dict | None = None) -> list[int]:
    cats = cats or category_index()
    out, p = [], (cats.get(cid) or {}).get("parent_id")
    while p and p in cats and p not in out:
        out.append(p)
        p = cats[p].get("parent_id")
    return out


def related_categories(cid: int, cats: dict | None = None) -> list[int]:
    """دسته، والدهایش و زیرشاخه‌هایش: برندی که به هرکدام وصل باشد در این دسته نمایش داده می‌شود."""
    cats = cats or category_index()
    return [cid, *ancestors(cid, cats), *descendants(cid, cats)]


def tree(q: str = "") -> list[dict]:
    """درخت دسته‌بندی‌ها با تعداد محصول و برند هر گره (و جمع زیرشاخه‌ها)."""
    items = {r["id"]: r for r in list_items("category")}
    for r in items.values():
        r["nodes"] = []
    roots = []
    for r in sorted(items.values(), key=lambda x: (x.get("sort") or 0, x["name"])):
        (items[r["parent_id"]]["nodes"] if r.get("parent_id") in items else roots).append(r)

    def total(n):
        n["products_total"] = n["products"] + sum(total(c) for c in n["nodes"])
        return n["products_total"]
    for r in roots:
        total(r)
    if q:
        nq = norm(q)

        def keep(n):
            n["nodes"] = [c for c in n["nodes"] if keep(c)]
            return bool(n["nodes"]) or nq in norm(" ".join([n["name"], n.get("name_en") or "", n["slug"], *n["aliases"]]))
        roots = [r for r in roots if keep(r)]
    return roots


def _check(kind: str, data: dict, rid: int | None = None) -> dict:
    t = _table(kind)
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("نام لازم است.")
    slug = (data.get("slug") or "").strip().lower() or slugify(data.get("name_en") or name)
    if not _SLUG_RE.match(slug):
        raise ValueError(f"اسلاگ «{slug}» معتبر نیست؛ فقط حروف کوچک انگلیسی، عدد و خط تیره.")
    dup = db.q1(f"SELECT id FROM {t} WHERE slug=? AND id<>?", [slug, rid or 0])
    if dup:
        raise ValueError(f"اسلاگ «{slug}» قبلاً برای مورد دیگری ثبت شده است.")
    aliases = data.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [a.strip() for a in re.split(r"[\n,،]", aliases) if a.strip()]
    out = {"name": name, "name_en": (data.get("name_en") or "").strip(), "slug": slug, "aliases": aliases,
           "description": (data.get("description") or "").strip(), "notes": data.get("notes") or "",
           "active": 1 if data.get("active", True) not in (False, 0, "0") else 0}
    if kind == "category":
        out["parent_id"] = int(data["parent_id"]) if data.get("parent_id") else None
        out["sort"] = int(data.get("sort") or 0)
        if rid and out["parent_id"]:
            if out["parent_id"] == rid or out["parent_id"] in descendants(rid):
                raise ValueError("دسته نمی‌تواند زیرمجموعه‌ی خودش یا زیرشاخه‌هایش باشد.")
        if out["parent_id"] and not db.q1("SELECT id FROM ref_categories WHERE id=?", [out["parent_id"]]):
            raise ValueError("دسته‌ی والد پیدا نشد.")
    else:
        out["country"] = data.get("country") or ""
        ids = []
        for c in data.get("category_ids") or []:
            cid = int(c)
            if not db.q1("SELECT id FROM ref_categories WHERE id=?", [cid]):
                raise ValueError(f"دسته‌بندی {cid} پیدا نشد.")
            if cid not in ids:
                ids.append(cid)
        out["category_ids"] = ids
    return out


def save(kind: str, data: dict, rid: int | None = None, actor: str = "ui") -> dict:
    t = _table(kind)
    v = _check(kind, data, rid)
    now = db.now()
    if rid:
        if not get(kind, rid):
            raise ValueError("مورد پیدا نشد.")
        db.update(t, rid, **v, updated_at=now)
        action = "edit"
    else:
        cols = list(v) + ["created_at", "updated_at"]
        vals = [db.jdump(x) if isinstance(x, (list, dict)) else x for x in v.values()] + [now, now]
        rid = db.ex(f"INSERT INTO {t}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals)
        action = "create"
    r = get(kind, rid)
    revisions.record(f"ref_{kind}", rid, snapshot(kind, r), actor=actor, action=action)
    return r


def delete(kind: str, rid: int, actor: str = "ui") -> dict:
    t = _table(kind)
    r = get(kind, rid)
    if not r:
        raise ValueError("مورد پیدا نشد.")
    col = "brand_id" if kind == "brand" else "category_id"
    n = db.val(f"SELECT COUNT(*) FROM wb_products WHERE {col}=?", [rid]) or 0
    if n:
        raise ValueError(f"{n} محصول به این {LABELS[kind]} وصل است؛ اول آن‌ها را به مورد دیگری منتقل کنید یا این مورد را «غیرفعال» کنید.")
    if kind == "category" and db.val("SELECT COUNT(*) FROM ref_categories WHERE parent_id=?", [rid]):
        raise ValueError("این دسته زیرمجموعه دارد؛ اول زیرشاخه‌ها را حذف یا جابه‌جا کنید.")
    revisions.record(f"ref_{kind}", rid, snapshot(kind, r), actor=actor, action="delete", force=True)
    db.ex(f"DELETE FROM {t} WHERE id=?", [rid])
    if kind == "category":  # دسته از برندهای وصل‌شده هم برداشته می‌شود (با نسخه)
        for b in db.q("SELECT id, category_ids FROM ref_brands"):
            ids = db.jload(b["category_ids"], []) or []
            if rid in ids:
                cur = get("brand", b["id"])
                save("brand", {**cur, "category_ids": [c for c in ids if c != rid]}, b["id"], actor)
    return {"ok": True}


def _restore(kind):
    def fn(rid: int, snap: dict, actor: str):
        if get(kind, rid):
            v = _check(kind, snap, rid)
            db.update(_table(kind), rid, **v, updated_at=db.now())
        else:
            raise ValueError("این مورد حذف شده است؛ آن را دوباره بسازید.")
    return fn


revisions.register_restorer("ref_brand", _restore("brand"))
revisions.register_restorer("ref_category", _restore("category"))


# ---------------------------------------------------------------------------
# تطبیق نام‌های خام با فهرست مرجع
# ---------------------------------------------------------------------------

def _index(kind: str) -> dict[str, int]:
    idx: dict[str, int] = {}
    for r in list_items(kind, active_only=True, with_counts=False):
        for name in [r["name"], r.get("name_en"), r["slug"], r["slug"].replace("-", " "), *r["aliases"]]:
            if name:
                idx.setdefault(norm(name), r["id"])
    return idx


def resolve(kind: str, *candidates: str) -> int | None:
    """اولین نامزدی که با نام، نام انگلیسی، اسلاگ یا نام‌های دیگر یک مورد فهرست جور شود."""
    idx = _index(kind)
    for c in candidates:
        if c and norm(c) in idx:
            return idx[norm(c)]
    return None


def unmatched(kind: str) -> list[dict]:
    """نام‌های خامی که در محصولات تمیز به هیچ مورد فهرست وصل نشده‌اند (با تعداد)."""
    col = "brand_id" if kind == "brand" else "category_id"
    key = f"{kind}_raw"
    counts: dict[str, int] = {}
    for r in db.q(f"SELECT meta FROM wb_products WHERE {col} IS NULL AND status<>'merged'"):
        raw = (db.jload(r["meta"], {}) or {}).get(key) or ""
        if raw:
            counts[raw] = counts.get(raw, 0) + 1
    return [{"name": k, "count": v, "slug": slugify(k)} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def link_unmatched(kind: str, raw_name: str, rid: int, add_alias: bool = True, actor: str = "ui") -> dict:
    """همه‌ی محصولاتی که نام خامشان raw_name است به مورد rid وصل می‌شوند (و نام به «نام‌های دیگر» افزوده می‌شود)."""
    from . import workbench
    r = get(kind, rid)
    if not r:
        raise ValueError("مورد پیدا نشد.")
    if add_alias and norm(raw_name) not in {norm(a) for a in [r["name"], r.get("name_en"), *r["aliases"]]}:
        save(kind, {**r, "aliases": r["aliases"] + [raw_name]}, rid, actor)
    col = "brand_id" if kind == "brand" else "category_id"
    n = 0
    for p in db.q(f"SELECT id, meta FROM wb_products WHERE {col} IS NULL"):
        if norm((db.jload(p["meta"], {}) or {}).get(f"{kind}_raw") or "") == norm(raw_name):
            workbench.update_product(p["id"], {kind: rid}, actor=actor, action="edit", note=f"اتصال «{raw_name}»")
            n += 1
    return {"linked": n}


# ---------------------------------------------------------------------------
# عملیات گروهی
# ---------------------------------------------------------------------------

BULK_ACTIONS = {"delete", "activate", "deactivate", "set_parent", "add_categories", "remove_categories", "set_categories",
                "add_aliases", "set_country"}


def bulk(kind: str, ids: list, action: str, value=None, actor: str = "ui") -> dict:
    """یک عملیات روی چند مورد. هر مورد جدا ذخیره و نسخه‌دار می‌شود؛ خطای یک مورد بقیه را متوقف نمی‌کند."""
    if action not in BULK_ACTIONS:
        raise ValueError("عملیات گروهی نامعتبر است.")
    if action in ("set_parent",) and kind != "category":
        raise ValueError("تعیین والد فقط برای دسته‌بندی‌هاست.")
    if action in ("add_categories", "remove_categories", "set_categories", "set_country") and kind != "brand":
        raise ValueError("این عملیات فقط برای برندهاست.")
    ids = [int(i) for i in ids or []]
    if not ids:
        raise ValueError("موردی انتخاب نشده است.")
    done, errors = 0, []
    vals = [int(x) for x in (value or [])] if action.endswith("_categories") else value
    # حذف دسته‌ها از برگ به ریشه تا «زیرمجموعه دارد» مانع نشود
    if action == "delete" and kind == "category":
        cats = category_index()
        ids.sort(key=lambda i: -(cats.get(i, {}).get("depth", 0)))
    for rid in ids:
        r = get(kind, rid)
        if not r:
            errors.append({"id": rid, "error": "پیدا نشد."})
            continue
        try:
            if action == "delete":
                delete(kind, rid, actor)
            else:
                d = dict(r)
                if action == "activate":
                    d["active"] = 1
                elif action == "deactivate":
                    d["active"] = 0
                elif action == "set_parent":
                    d["parent_id"] = int(value) if value else None
                elif action == "add_categories":
                    d["category_ids"] = list(dict.fromkeys([*r["category_ids"], *vals]))
                elif action == "remove_categories":
                    d["category_ids"] = [c for c in r["category_ids"] if c not in vals]
                elif action == "set_categories":
                    d["category_ids"] = vals
                elif action == "add_aliases":
                    d["aliases"] = list(dict.fromkeys([*r["aliases"], *[a.strip() for a in re.split(r"[\n,،|]", str(value or "")) if a.strip()]]))
                elif action == "set_country":
                    d["country"] = str(value or "")
                save(kind, d, rid, actor)
            done += 1
        except ValueError as exc:
            errors.append({"id": rid, "name": r["name"], "error": str(exc)})
    return {"done": done, "total": len(ids), "errors": errors}


def apply_items(kind: str, items: list[dict], actor: str = "ui") -> dict:
    """ذخیره‌ی چند مورد یک‌جا (مثلاً پیشنهادهای تأییدشده‌ی هوش مصنوعی). مورد با id ویرایش و بدون id افزوده می‌شود."""
    added = updated = 0
    errors = []
    for it in items or []:
        try:
            data = dict(it)
            if kind == "brand" and data.get("categories") and not data.get("category_ids"):
                data["category_ids"] = resolve_categories(data["categories"])
            if kind == "category" and data.get("parent") and not data.get("parent_id"):
                data["parent_id"] = resolve("category", str(data["parent"]))
            if data.get("id"):
                cur = get(kind, int(data["id"]))
                if not cur:
                    raise ValueError("پیدا نشد.")
                merged = {**cur, **{k: v for k, v in data.items() if v not in (None, "") and k != "id"}}
                save(kind, merged, int(data["id"]), actor)
                updated += 1
            else:
                save(kind, data, None, actor)
                added += 1
        except (ValueError, TypeError) as exc:
            errors.append({"name": it.get("name") or it.get("id"), "error": str(exc)})
    return {"added": added, "updated": updated, "errors": errors}


def resolve_categories(vals) -> list[int]:
    from .import_specs import split_list
    out = []
    for v in split_list(vals) if not isinstance(vals, list) else vals:
        cid = int(v) if isinstance(v, int) or str(v).isdigit() else resolve("category", str(v))
        if cid and cid not in out:
            out.append(cid)
    return out


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------

def export_rows(kind: str, ids: list | None = None) -> list[dict]:
    rows = list_items(kind)
    if ids:
        want = {int(i) for i in ids}
        rows = [r for r in rows if r["id"] in want]
    out = []
    byid = category_index() if kind == "category" else {}
    for r in rows:
        o = {"name": r["name"], "name_en": r.get("name_en") or "", "slug": r["slug"]}
        if kind == "brand":
            o["categories"] = "|".join(c["slug"] for c in r.get("categories") or [])
        else:
            o["parent"] = byid[r["parent_id"]]["slug"] if r.get("parent_id") in byid else ""
            o["sort"] = r.get("sort") or 0
            o["path"] = r.get("path_slug")
        o["aliases"] = "|".join(r["aliases"])
        if kind == "brand":
            o["country"] = r.get("country") or ""
        o.update({"description": r.get("description") or "", "notes": r.get("notes") or "", "active": r["active"], "products": r.get("products", 0)})
        if kind == "category":
            o["brands"] = r.get("brands", 0)
        out.append(o)
    return out


def export_file(kind: str, fmt: str = "xlsx", ids: list | None = None) -> tuple[bytes, str, str]:
    from .import_specs import FORMATS, write_table
    if fmt not in FORMATS:
        raise ValueError("قالب فایل نامعتبر است.")
    rows = export_rows(kind, ids)
    if fmt == "json":
        for r in rows:
            r["aliases"] = [a for a in r["aliases"].split("|") if a]
            if kind == "brand":
                r["categories"] = [c for c in r["categories"].split("|") if c]
    heads = list(rows[0].keys()) if rows else (["name", "name_en", "slug", "categories", "aliases", "country", "description", "notes", "active"]
                                                if kind == "brand" else ["name", "name_en", "slug", "parent", "sort", "aliases", "description", "notes", "active"])
    name = "brands" if kind == "brand" else "categories"
    return write_table(rows, heads, fmt, sheet=name), FORMATS[fmt][0], f"{name}.{FORMATS[fmt][1]}"


# ---------------------------------------------------------------------------
# ورود
# ---------------------------------------------------------------------------

def import_rows(kind: str, rows: list[dict], actor: str = "ui", update: bool = True) -> dict:
    """ورود گروهی طبق مشخصات import_specs (name اجباری؛ name_en، slug، aliases، description، notes، active؛
    برند: categories و country؛ دسته: parent و sort). موارد موجود (همان اسلاگ یا همان نام) به‌روز می‌شوند."""
    from .import_specs import split_list, truthy
    added = updated = skipped = 0
    errors = []
    pending_parent: list[tuple[int, str]] = []
    for i, r in enumerate(rows, 1):
        try:
            name = str(r.get("name") or "").strip()
            if not name:
                skipped += 1
                continue
            data = {"name": name, "name_en": str(r.get("name_en") or "").strip(), "slug": str(r.get("slug") or "").strip().lower(),
                    "aliases": split_list(r.get("aliases")), "notes": str(r.get("notes") or ""), "description": str(r.get("description") or "")}
            if "active" in r and r.get("active") not in (None, ""):
                data["active"] = 1 if truthy(r.get("active")) else 0
            if kind == "brand":
                if r.get("country"):
                    data["country"] = str(r["country"])
                if r.get("categories") not in (None, "", []):
                    cats = resolve_categories(r["categories"])
                    missing = [c for c in split_list(r["categories"]) if not resolve("category", str(c))] if not isinstance(r["categories"], list) else []
                    if missing:
                        errors.append(f"ردیف {i}: دسته‌بندی «{'، '.join(missing)}» در فهرست نیست و نادیده گرفته شد.")
                    data["category_ids"] = cats
            else:
                if r.get("sort") not in (None, ""):
                    data["sort"] = int(float(r["sort"]))
            existing = db.q1(f"SELECT id FROM {_table(kind)} WHERE slug=?", [data["slug"]]) if data["slug"] else None
            if not existing:
                rid = resolve(kind, name)
                existing = {"id": rid} if rid else None
            if existing:
                if not update:
                    skipped += 1
                    rid = existing["id"]
                else:
                    cur = get(kind, existing["id"])
                    merged = {**cur, **{k: v for k, v in data.items() if v not in ("", [], None)}}
                    if "active" in data:
                        merged["active"] = data["active"]
                    rid = save(kind, merged, existing["id"], actor)["id"]
                    updated += 1
            else:
                rid = save(kind, data, None, actor)["id"]
                added += 1
            if kind == "category" and str(r.get("parent") or "").strip():
                pending_parent.append((rid, str(r["parent"]).strip()))
        except (ValueError, TypeError) as exc:
            errors.append(f"ردیف {i}: {exc}")
    # والدها پس از ساخت همه‌ی ردیف‌ها؛ پس ترتیب ردیف‌ها مهم نیست
    for rid, parent in pending_parent:
        pid = db.q1("SELECT id FROM ref_categories WHERE slug=?", [parent.lower()])
        pid = pid["id"] if pid else resolve("category", parent)
        if not pid:
            errors.append(f"والد «{parent}» برای «{get(kind, rid)['name']}» پیدا نشد.")
            continue
        cur = get("category", rid)
        if cur.get("parent_id") != pid:
            try:
                save("category", {**cur, "parent_id": pid}, rid, actor)
            except ValueError as exc:
                errors.append(f"«{cur['name']}»: {exc}")
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors[:50]}


def parse_upload(data_url: str, name: str, kind: str = "brand", mapping: dict | None = None) -> list[dict]:
    """فایل xlsx/csv/json بارگذاری‌شده → ردیف‌ها با کلیدهای استاندارد (سرستون انگلیسی یا فارسی)."""
    from . import import_specs
    return import_specs.parse(kind, data_url, name, mapping)


def seed_from_mappings() -> dict:
    """برای نصب‌های قدیمی: نگاشت‌های برند و دسته‌ی نسخه‌ی ۱ به فهرست مرجع تبدیل می‌شوند (فقط اگر فهرست خالی باشد)."""
    out = {}
    for kind in ("brand", "category"):
        if db.val(f"SELECT COUNT(*) FROM {_table(kind)}"):
            continue
        rows: dict[str, dict] = {}
        for m in db.q("SELECT * FROM mappings WHERE kind=?", [kind]):
            slug = (m["target_slug"] or "").strip().lower()
            if not _SLUG_RE.match(slug):
                continue
            r = rows.setdefault(slug, {"name": m.get("target_label") or m["source_value"], "slug": slug, "aliases": []})
            if m["source_value"] not in r["aliases"] and m["source_value"] != r["name"]:
                r["aliases"].append(m["source_value"])
        out[kind] = import_rows(kind, list(rows.values()), actor="system")
    return out
