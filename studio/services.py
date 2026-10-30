"""منطق کسب‌وکاری استودیو: منابع، اسکیماها، بانک‌های داده، نگاشت‌ها و ساخت ردیف خروجی."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import db
from .config import DEFAULTS_DIR
from .engine.extract import CANONICAL_FIELDS
from .textutil import TEHRAN, is_latin, jalali_human, jalali_stamp, safe_filename, slugify, to_fa_digits

# ---------------------------------------------------------------------------
# بذرهای اولیه
# ---------------------------------------------------------------------------


def seed_defaults() -> None:
    for p in sorted((DEFAULTS_DIR / "sources").glob("*.json")):
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not db.q1("SELECT id FROM sources WHERE key=?", [cfg["key"]]):
            db.ex("INSERT INTO sources(key, name, config, enabled, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                  [cfg["key"], cfg["name"], db.jdump(cfg), 1, db.now(), db.now()])
    if not db.val("SELECT COUNT(*) FROM schemas"):
        for p in sorted((DEFAULTS_DIR / "schemas").glob("*.json")):
            s = json.loads(p.read_text(encoding="utf-8"))
            db.ex("INSERT INTO schemas(name, description, columns, is_default, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                  [s["name"], s.get("description", ""), db.jdump(s["columns"]), 1 if s.get("is_default") else 0, db.now(), db.now()])


# ---------------------------------------------------------------------------
# منابع
# ---------------------------------------------------------------------------


def source_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["config"] = db.jload(r["config"], {})
    return r


def get_source(sid: int) -> dict | None:
    return source_row(db.q1("SELECT * FROM sources WHERE id=?", [sid]))


def list_sources() -> list[dict]:
    rows = [source_row(r) for r in db.q("SELECT * FROM sources ORDER BY id")]
    for r in rows:
        r["datasets"] = db.val("SELECT COUNT(*) FROM datasets WHERE source_id=?", [r["id"]])
        r["products"] = db.val("SELECT COUNT(*) FROM items WHERE source_id=? AND status IN ('done','partial')", [r["id"]])
    return rows


def detect_source(url: str) -> dict | None:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for s in list_sources():
        for d in s["config"].get("domains", []):
            d = d.lower().removeprefix("www.")
            if host == d or host.endswith("." + d):
                return s
    return None


def save_source(cfg: dict, sid: int | None = None) -> dict:
    key = slugify(cfg.get("key") or cfg.get("name") or "source") or f"source-{uuid.uuid4().hex[:5]}"
    cfg["key"] = key
    name = cfg.get("name") or key
    if sid:
        db.ex("UPDATE sources SET key=?, name=?, config=?, updated_at=? WHERE id=?", [key, name, db.jdump(cfg), db.now(), sid])
    else:
        base, i = key, 2
        while db.q1("SELECT id FROM sources WHERE key=?", [key]):
            key = f"{base}-{i}"
            i += 1
        cfg["key"] = key
        sid = db.ex("INSERT INTO sources(key, name, config, enabled, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    [key, name, db.jdump(cfg), 1, db.now(), db.now()])
    return get_source(sid)


# ---------------------------------------------------------------------------
# اسکیماها
# ---------------------------------------------------------------------------


def schema_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["columns"] = db.jload(r["columns"], [])
    return r


def get_schema(sid: int | None) -> dict | None:
    if sid:
        r = schema_row(db.q1("SELECT * FROM schemas WHERE id=?", [sid]))
        if r:
            return r
    return schema_row(db.q1("SELECT * FROM schemas ORDER BY is_default DESC, id LIMIT 1"))


def list_schemas() -> list[dict]:
    return [schema_row(r) for r in db.q("SELECT * FROM schemas ORDER BY is_default DESC, id")]


def required_canonical(schema: dict | None) -> list[str]:
    if not schema:
        return ["title"]
    req = [c["from"] for c in schema["columns"] if c.get("kind") == "scraped" and c.get("required") and c.get("from")]
    return req or ["title"]


# ---------------------------------------------------------------------------
# بانک‌های داده
# ---------------------------------------------------------------------------


def category_key_from_url(url: str) -> str:
    p = urlparse(url)
    segs = [unquote(s) for s in p.path.split("/") if s]
    skip = {"category", "search", "city", "tehran", "product", "products", "fa", "en", "c"}
    cand = ""
    for s in reversed(segs):
        if s.lower() in skip or s.isdigit():
            continue
        cand = s
        break
    cand = re.sub(r"^category-", "", cand)
    return slugify(cand) or (slugify(segs[-1]) if segs else "category") or "category"


def ds_title(source_name: str, category_label: str, count: int, created: datetime) -> str:
    return f"{source_name} · {category_label or 'دسته‌بندی'} · {to_fa_digits(count)} محصول · {jalali_human(created)}"


def ds_name(source_key: str, category_key: str, count: int, created: datetime) -> str:
    return safe_filename(f"{source_key}__{category_key}__{count}items__{jalali_stamp(created)}")


def create_dataset(source_id: int, category_url: str, item_limit: int | None, schema_id: int | None,
                   options: dict, policies: dict, category_label: str = "") -> dict:
    src = get_source(source_id)
    if not src:
        raise ValueError("منبع پیدا نشد.")
    created = datetime.now(TEHRAN)
    if not schema_id:
        sch = get_schema(None)
        schema_id = sch["id"] if sch else None
    ckey = category_key_from_url(category_url)
    label = category_label or unquote(urlparse(category_url).path.rstrip("/").split("/")[-1]).replace("-", " ")
    code = f"DS-{jalali_stamp(created).replace('-', '').replace('_', '-')}-{uuid.uuid4().hex[:4].upper()}"
    did = db.ex(
        """INSERT INTO datasets(code, name, title, source_id, schema_id, category_url, category_label, category_key,
           item_limit, status, cursor, options, policies, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [code, ds_name(src["key"], ckey, 0, created), ds_title(src["name"], label, 0, created), source_id,
         schema_id, category_url, label, ckey, item_limit, "pending", "{}", db.jdump(options), db.jdump(policies),
         created.isoformat(timespec="seconds"), db.now()],
    )
    db.log("dataset", did, f"بانک داده ساخته شد: {code}", step="create")
    return get_dataset(did)


def refresh_dataset_naming(did: int) -> None:
    d = db.q1("SELECT * FROM datasets WHERE id=?", [did])
    if not d:
        return
    src = get_source(d["source_id"])
    created = datetime.fromisoformat(d["created_at"]).astimezone(TEHRAN)
    n = db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND status IN ('done','partial')", [did]) or 0
    opts = db.jload(d["options"], {})
    if opts.get("custom_name"):
        return
    db.update("datasets", did, name=ds_name(src["key"], d["category_key"], n, created),
              title=ds_title(src["name"], d["category_label"], n, created), updated_at=db.now())


def dataset_counts(did: int) -> dict:
    rows = db.q("SELECT status, COUNT(*) c FROM items WHERE dataset_id=? GROUP BY status", [did])
    c = {r["status"]: r["c"] for r in rows}
    return {
        "queued": c.get("queued", 0), "done": c.get("done", 0), "partial": c.get("partial", 0),
        "failed": c.get("failed", 0), "skipped": c.get("skipped", 0),
        "total": sum(c.values()),
    }


def get_dataset(did: int) -> dict | None:
    d = db.q1("SELECT * FROM datasets WHERE id=?", [did])
    if not d:
        return None
    for k in ("cursor", "options", "policies"):
        d[k] = db.jload(d[k], {})
    d["counts"] = dataset_counts(did)
    src = db.q1("SELECT id, key, name FROM sources WHERE id=?", [d["source_id"]])
    d["source"] = src
    sch = db.q1("SELECT id, name FROM schemas WHERE id=?", [d["schema_id"]]) if d["schema_id"] else None
    d["schema"] = sch
    d["open_incident"] = db.q1("SELECT * FROM incidents WHERE dataset_id=? AND status='open' ORDER BY id DESC LIMIT 1", [did])
    if d["open_incident"]:
        d["open_incident"]["options"] = db.jload(d["open_incident"]["options"], [])
    collected = d["counts"]["done"] + d["counts"]["partial"]
    target = d["item_limit"] or d["total_expected"] or None
    d["progress"] = {"collected": collected, "target": target,
                     "pct": round(min(100, collected * 100 / target), 1) if target else None}
    return d


def list_datasets() -> list[dict]:
    ids = [r["id"] for r in db.q("SELECT id FROM datasets ORDER BY id DESC")]
    return [get_dataset(i) for i in ids]


# ---------------------------------------------------------------------------
# آیتم‌ها
# ---------------------------------------------------------------------------


def item_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    for k, dflt in (("data", {}), ("overrides", {}), ("manual", {}), ("missing", []), ("ai", {})):
        r[k] = db.jload(r[k], dflt)
    return r


# ---------------------------------------------------------------------------
# نگاشت‌ها
# ---------------------------------------------------------------------------


def lookup_mapping(kind: str, source_id: int | None, value: str) -> dict | None:
    if not value:
        return None
    v = value.strip()
    r = db.q1("SELECT * FROM mappings WHERE kind=? AND source_id=? AND source_value=?", [kind, source_id, v])
    if r:
        return r
    return db.q1("SELECT * FROM mappings WHERE kind=? AND source_id IS NULL AND source_value=?", [kind, v])


def mapping_source_value(kind: str, item: dict, ds: dict) -> str:
    data = item["data"]
    if kind == "brand":
        return (data.get("brand_en") if is_latin(data.get("brand_en") or "") else "") or data.get("brand") or ""
    if kind == "category":
        return ds.get("category_label") or data.get("category") or ""
    return ""


def unmapped_values() -> dict:
    out = {"brand": {}, "category": {}}
    for ds in db.q("SELECT * FROM datasets"):
        ds_d = dict(ds)
        sid = ds_d["source_id"]
        src = db.q1("SELECT name FROM sources WHERE id=?", [sid])
        for kind in ("brand", "category"):
            vals: dict[str, int] = {}
            if kind == "category":
                vals[ds_d["category_label"] or ""] = db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND status IN ('done','partial')", [ds_d["id"]]) or 0
            else:
                for it in db.q("SELECT data FROM items WHERE dataset_id=? AND status IN ('done','partial')", [ds_d["id"]]):
                    item = {"data": db.jload(it["data"], {})}
                    v = mapping_source_value("brand", item, ds_d)
                    if v:
                        vals[v] = vals.get(v, 0) + 1
            for v, n in vals.items():
                if not v or lookup_mapping(kind, sid, v):
                    continue
                key = f"{sid}|{v}"
                e = out[kind].setdefault(key, {"source_id": sid, "source_name": src["name"] if src else "", "value": v,
                                               "count": 0, "suggested": slugify(v)})
                e["count"] += n
    return {k: sorted(v.values(), key=lambda x: -x["count"]) for k, v in out.items()}


# ---------------------------------------------------------------------------
# ساخت مقدار ستون‌های خروجی
# ---------------------------------------------------------------------------


EMPTY = (None, "", [], {})

# ---------------------------------------------------------------------------
# مقدار پیش‌فرض ستون‌های اسکیما
#   default       مقدار (متن یک‌خطی، متن چندخطی، فهرست بولت، گروه بولت‌ها، کلید/مقدار، JSON، عدد، بله/خیر)
#   default_mode  fill    → فقط وقتی منبع، ورود دستی و هوش مصنوعی مقداری نداشتند (پیش‌فرض)
#                 always  → همیشه همین مقدار (فقط ویرایش دستی هر محصول یا ورود دستی جایش را می‌گیرد)
#                 prepend → به ابتدای مقدار موجود افزوده می‌شود (متن، بولت‌ها، تصاویر، مشخصات)
#                 append  → به انتهای مقدار موجود افزوده می‌شود
# ---------------------------------------------------------------------------
DEFAULT_MODES = ("fill", "always", "prepend", "append")
_LISTY = ("bullets", "images", "specs")


def is_empty(v) -> bool:
    if v in EMPTY:
        return True
    if isinstance(v, dict):
        return all(is_empty(x) for x in v.values())
    if isinstance(v, list):
        return all(is_empty(x) for x in v)
    if isinstance(v, str):
        return not v.strip()
    return False


def _lines(v, bullets: bool = False) -> list:
    if isinstance(v, list):
        return [x for x in v if not is_empty(x)]
    if v in (None, ""):
        return []
    out = []
    for ln in str(v).split("\n"):
        ln = ln.strip()
        if bullets:
            ln = re.sub(r"^[•\-*–]\s*", "", ln)
        if ln:
            out.append(ln)
    return out


def coerce_value(col: dict, v):
    """تبدیل مقدار واردشده در اسکیما (معمولاً متن) به نوع واقعی ستون."""
    if v is None:
        return None
    inp = col.get("input") or "text"
    if inp in ("bullets", "images"):
        return _lines(v, bullets=inp == "bullets")
    if inp in ("bullet_groups", "group", "specs", "json") and isinstance(v, str):
        t = v.strip()
        if not t:
            return "" if inp == "json" else ({} if inp != "specs" else [])
        try:
            v = json.loads(t)
        except ValueError:
            return t if inp == "json" else ({} if inp != "specs" else [])
    if inp == "bullet_groups":
        return {k: _lines(x, bullets=True) for k, x in (v or {}).items()} if isinstance(v, dict) else {}
    if inp == "group":
        return {k: x for k, x in v.items()} if isinstance(v, dict) else {}
    if inp == "number":
        if isinstance(v, (int, float)) or v == "":
            return v
        try:
            f = float(str(v).replace(",", "").strip())
            return int(f) if f.is_integer() else f
        except ValueError:
            return v
    if inp == "bool":
        if isinstance(v, bool) or v == "":
            return v
        return str(v).strip().lower() in ("true", "1", "yes", "بله", "آری", "دارد")
    if inp in ("text", "longtext", "image") and isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return v


def default_mode(col: dict) -> str:
    m = col.get("default_mode") or "fill"
    return m if m in DEFAULT_MODES else "fill"


def column_default(col: dict):
    """مقدار پیش‌فرض ستون (با نوع درست) یا None."""
    if col.get("kind") == "constant":
        return None
    d = coerce_value(col, col.get("default"))
    return None if is_empty(d) else d


def fixed_default(col: dict) -> bool:
    """ستونی که مقدارش همیشه همان پیش‌فرض اسکیماست (با هوش مصنوعی ساخته نمی‌شود)."""
    return default_mode(col) == "always" and column_default(col) is not None


def apply_default(col: dict, v, d=None, mode: str | None = None):
    """ادغام مقدار پیش‌فرض اسکیما با مقدار فعلی ستون."""
    d = column_default(col) if d is None else coerce_value(col, d)
    if is_empty(d):
        return v
    mode = mode or default_mode(col)
    inp = col.get("input") or "text"
    if mode == "always":
        return d
    if inp in ("group", "bullet_groups") and isinstance(d, dict):
        base = dict(v) if isinstance(v, dict) else {}
        for k, dv in d.items():
            if is_empty(dv):
                continue
            cur = base.get(k)
            if mode == "fill" or inp == "group" or is_empty(cur):
                if is_empty(cur):
                    base[k] = dv
                continue
            cur, dl = _lines(cur, True), _lines(dv, True)
            base[k] = dl + [x for x in cur if x not in dl] if mode == "prepend" else cur + [x for x in dl if x not in cur]
        return base
    if is_empty(v):
        return d
    if mode == "fill":
        return v
    if isinstance(v, list) or inp in _LISTY:
        cur = v if isinstance(v, list) else _lines(v, inp == "bullets")
        dl = d if isinstance(d, list) else [d]
        key = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)  # noqa: E731
        ck, dk = {key(x) for x in cur}, {key(x) for x in dl}
        return dl + [x for x in cur if key(x) not in dk] if mode == "prepend" else cur + [x for x in dl if key(x) not in ck]
    if isinstance(v, str) and isinstance(d, str):
        if d.strip() in v:
            return v
        sep = "\n\n" if inp == "longtext" else ("\n" if "\n" in d else " ")
        return f"{d}{sep}{v}" if mode == "prepend" else f"{v}{sep}{d}"
    return v


def _ai_value(col: dict, item: dict):
    """مقدار تولیدشده با هوش مصنوعی برای یک ستون (پس از اعمال قواعد متن)، یا None."""
    entry = (item.get("ai") or {}).get(col["key"])
    if not isinstance(entry, dict) or entry.get("value") in EMPTY:
        return None, None
    from . import rules
    if entry.get("kind") == "image":
        return entry["value"], entry
    v = rules.apply_value(entry["value"], col.get("from") or col["key"], item.get("source_id"), all_fields=True)
    return v, entry


def column_value(col: dict, item: dict, ds: dict, settings: dict, src: dict | None = None, with_default: bool = True) -> tuple:
    """خروجی: (مقدار، پرچم). اولویت: ویرایش دستی ← ورود دستی ← هوش مصنوعی ← داده‌ی استخراج‌شده (پس از قواعد متن)؛
    سپس مقدار پیش‌فرض اسکیما بر اساس default_mode (خالی‌ها، همیشه، ابتدا یا انتها)."""
    key = col["key"]
    if key in item.get("overrides", {}):
        return item["overrides"][key], "edited"
    d = column_default(col) if with_default else None
    if d is not None and default_mode(col) == "always":
        mv = (item.get("manual") or {}).get(key)
        if col.get("kind") in ("manual", "ai") and not is_empty(mv):
            return mv, ""
        return d, ""
    v, flag = _raw_value(col, item, ds, settings, src, has_default=d is not None)
    if d is not None:
        nv = apply_default(col, v, d)
        if flag in ("missing", "unmapped") and not is_empty(nv) and is_empty(v):
            flag = ""
        v = nv
    return v, flag


def _raw_value(col: dict, item: dict, ds: dict, settings: dict, src: dict | None = None, has_default: bool = False) -> tuple:
    from . import rules
    key = col["key"]
    kind = col.get("kind", "scraped")
    data = rules.cleaned(item)
    ai_v, ai_e = _ai_value(col, item)
    if kind == "scraped":
        v = data.get(col.get("from") or key)
        if ai_v is not None:
            inp = col.get("input")
            if inp == "group" and isinstance(v, dict) and isinstance(ai_v, dict):
                v = {**ai_v, **{k: x for k, x in v.items() if x not in EMPTY}} if ai_e.get("mode") == "fill_missing" else {**v, **ai_v}
            elif inp == "images" and ai_e.get("merge") == "append":
                v = list(v or []) + list(ai_v if isinstance(ai_v, list) else [ai_v])
            else:
                v = ai_v
            return v, "ai"
        return v, ("missing" if v in EMPTY and col.get("required") else "")
    if kind == "constant":
        if ai_v is not None:
            return ai_v, "ai"
        cv = coerce_value(col, col.get("value", ""))
        return ("" if cv is None else cv), ""
    if kind == "manual":
        v = item.get("manual", {}).get(key)
        empty = v in EMPTY or (isinstance(v, dict) and not any(x not in EMPTY for x in v.values()))
        if empty and ai_v is not None:
            return ai_v, "ai"
        if v in EMPTY:
            v = ""
        return v, ""
    if kind == "ai":  # ستونی که مقدارش فقط با هوش مصنوعی ساخته می‌شود
        if ai_v is not None:
            return ai_v, "ai"
        v = item.get("manual", {}).get(key)
        if v not in EMPTY:
            return v, ""
        return "", ("missing" if col.get("required") else "")
    if ai_v is not None:
        return ai_v, "ai"
    if kind == "mapping":
        mk = col.get("map", "brand")
        sv = mapping_source_value(mk, {**item, "data": data}, ds)
        m = lookup_mapping(mk, ds["source_id"], sv)
        if m:
            return m["target_slug"], ""
        if col.get("fallback", "auto") == "auto" and sv and not has_default:  # با مقدار پیش‌فرض، همان پیش‌فرض جای اسلاگ پیشنهادی می‌نشیند
            return slugify(sv, settings.get("slug_dictionary")), "unmapped"
        return "", "unmapped"
    if kind == "auto":
        gen = col.get("generator", "slug")
        if gen == "slug":
            if item.get("manual", {}).get("__slug"):
                return item["manual"]["__slug"], ""
            t_en = data.get("title_en") or ""
            base = t_en if is_latin(t_en) else data.get("title", "")
            return slugify(base, settings.get("slug_dictionary")), ""
        if gen == "source_url":
            u = item.get("url", "")
            return ("" if u.startswith("ai-generated:") else u), ""
        if gen == "source_name":
            return (src or {}).get("name", ""), ""
        if gen == "dataset_code":
            return ds.get("code", ""), ""
        if gen == "scraped_at":
            return item.get("scraped_at") or "", ""
        if gen == "product_key":
            return item.get("product_key", ""), ""
    return "", ""


def specs_to_json(specs: list, fmt: str = "flat"):
    if not isinstance(specs, list):
        return specs
    if fmt == "grouped":
        groups: dict[str, list] = {}
        for s in specs:
            groups.setdefault(s.get("group", "") or "عمومی", []).append({"name": s["name"], "value": s["value"]})
        return [{"group": g, "attributes": a} for g, a in groups.items()]
    if fmt == "list":
        return specs
    out: dict = {}
    for s in specs:
        k = s["name"]
        if k in out and out[k] != s["value"]:
            k = f"{s.get('group')} - {k}" if s.get("group") else f"{k} (2)"
        out[k] = s["value"]
    return out


def bullets_text(lines) -> str:
    if isinstance(lines, str):
        lines = [ln for ln in lines.split("\n")]
    return "\n".join(f"• {str(x).lstrip('•-* ').strip()}" for x in (lines or []) if str(x).strip())


def as_list(v) -> list:
    if v in (None, ""):
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [x.strip() for x in v.split("\n") if x.strip()]
    return [v]


def expand_column(col: dict, value, image_map: dict | None = None) -> list[tuple[str, object]]:
    """یک ستون اسکیما را به یک یا چند ستون Excel تبدیل می‌کند."""
    key = col["key"]
    inp = col.get("input") or "text"
    exp = col.get("export") or "text"
    img_map = image_map or {}

    def img(u):
        return img_map.get(u, u) if isinstance(u, str) else u

    if inp == "bullet_groups":
        groups = col.get("groups", [])
        v = value if isinstance(value, dict) else {}
        if exp == "json":
            return [(key, json.dumps({g["key"]: as_list(v.get(g["key"])) for g in groups}, ensure_ascii=False))]
        cols = [(f"{key}.{g['key']}", bullets_text(as_list(v.get(g["key"])))) for g in groups]
        if exp == "split+json":
            cols.append((key, json.dumps({g["key"]: as_list(v.get(g["key"])) for g in groups}, ensure_ascii=False)))
        return cols
    if inp == "group":
        subs = col.get("subkeys", [])
        v = value if isinstance(value, dict) else {}
        if exp == "split":
            return [(f"{key}.{s}", v.get(s, "")) for s in subs]
        return [(key, json.dumps({s: str(v.get(s, "") or "") for s in subs}, ensure_ascii=False) if (v or subs) else "")]
    if inp == "specs":
        if not value:
            return [(key, "")]
        return [(key, json.dumps(specs_to_json(value, col.get("spec_format", "flat")), ensure_ascii=False))]
    if inp == "bullets":
        return [(key, bullets_text(as_list(value)))]
    if inp == "image":
        return [(key, img(value) or "")]
    if inp == "images":
        lst = [img(u) for u in as_list(value)]
        if exp == "json":
            return [(key, json.dumps(lst, ensure_ascii=False))]
        if exp == "lines":
            return [(key, "\n".join(lst))]
        return [(key, ",".join(lst))]
    if inp == "json":
        if value in (None, "", [], {}):
            return [(key, "")]
        return [(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))]
    if inp == "bool":
        if isinstance(value, bool):
            return [(key, "true" if value else "false")]
        return [(key, str(value).lower() if value not in (None, "") else "")]
    if isinstance(value, (list, dict)):
        return [(key, json.dumps(value, ensure_ascii=False))]
    return [(key, "" if value is None else value)]


def build_rows(schema: dict, items: list[dict], settings: dict, image_map: dict | None = None,
               dedupe_slugs: bool = True) -> tuple[list[str], list[list], list[dict]]:
    """خروجی: (سرستون‌ها، ردیف‌ها، هشدارها)"""
    ds_cache: dict = {}
    src_cache: dict = {}
    headers: list[str] = []
    rows: list[list] = []
    warnings: list[dict] = []
    used_slugs: dict[str, int] = {}
    for it in items:
        ds = ds_cache.get(it["dataset_id"])
        if ds is None:
            ds = ds_cache[it["dataset_id"]] = get_dataset(it["dataset_id"])
        src = src_cache.get(it["source_id"])
        if src is None:
            src = src_cache[it["source_id"]] = get_source(it["source_id"])
        rec: list[tuple[str, object]] = []
        for col in schema["columns"]:
            if col.get("include", True) is False:
                continue
            v, flag = column_value(col, it, ds, settings, src)
            if col.get("kind") == "auto" and col.get("generator") == "slug" and dedupe_slugs and v:
                n = used_slugs.get(v, 0)
                used_slugs[v] = n + 1
                if n:
                    v = f"{v}-{n + 1}"
                it["_slug"] = v
            if flag in ("missing", "unmapped"):
                warnings.append({"item_id": it["id"], "column": col["key"], "flag": flag, "title": it["data"].get("title", "")})
            rec.extend(expand_column(col, v, image_map))
        if not headers:
            headers = [k for k, _ in rec]
        rows.append([v for _, v in rec])
    return headers, rows, warnings


def item_folder_name(item: dict, mode: str = "slug") -> str:
    if mode == "title":
        return safe_filename(item["data"].get("title") or item["product_key"], 100)
    if mode == "key":
        return safe_filename(item["product_key"], 100)
    return safe_filename(item.get("_slug") or slugify(item["data"].get("title_en") or item["data"].get("title", "")) or item["product_key"], 100)


def canonical_fields(sources: list[dict] | None = None) -> list[dict]:
    fields = [dict(f) for f in CANONICAL_FIELDS]
    keys = {f["key"] for f in fields}
    for s in sources or []:
        for f in s["config"].get("fields", []):
            if f["key"] not in keys:
                fields.append({"key": f["key"], "label": f.get("label", f["key"]), "type": f.get("type", "text"), "custom": True})
                keys.add(f["key"])
    return fields


def ensure_dir(p: str | Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def suggest_export_name(ids: list) -> str:
    ids = [int(i) for i in ids or []]
    if not ids:
        return "catalog-export"
    if len(ids) == 1:
        d = get_dataset(ids[0])
        return d["name"] if d else "catalog-export"
    total, srcs = 0, set()
    for i in ids:
        d = get_dataset(i)
        if d:
            total += d["counts"]["done"] + d["counts"]["partial"]
            srcs.add(d["source"]["key"])
    return safe_filename(f"{'+'.join(sorted(srcs))}__multi-{len(ids)}__{total}items__{jalali_stamp()}")


def record_item_change(before: dict, fields: dict, actor: str = "ui", note: str = ""):
    """ثبت تفاوت لایه‌های داده‌ی یک محصول (ویرایش، ورود دستی، هوش مصنوعی، داده، وضعیت) در تاریخچه."""
    iid, did = before["id"], before.get("dataset_id")
    for layer in ("overrides", "manual", "data"):
        if layer not in fields:
            continue
        old, new = before.get(layer) or {}, fields[layer] or {}
        for k in set(old) | set(new):
            if k.startswith("_") and layer == "data":
                continue
            if json.dumps(old.get(k), ensure_ascii=False, sort_keys=True, default=str) != json.dumps(new.get(k), ensure_ascii=False, sort_keys=True, default=str):
                db.history("item", iid, f"{layer}:{k}", old.get(k, ""), new.get(k, ""), actor=actor,
                           action={"overrides": "edit", "manual": "manual", "data": "data"}[layer], parent_id=did, note=note)
    if "ai" in fields:
        old, new = before.get("ai") or {}, fields["ai"] or {}
        for k in (set(old) | set(new)) - {"__meta"}:
            ov, nv = (old.get(k) or {}).get("value", ""), (new.get(k) or {}).get("value", "")
            if json.dumps(ov, ensure_ascii=False, default=str) != json.dumps(nv, ensure_ascii=False, default=str):
                db.history("item", iid, f"ai:{k}", ov, nv, actor=actor, action="ai" if k in new else "ai_clear", parent_id=did, note=note)
    if "status" in fields and fields["status"] != before.get("status"):
        db.history("item", iid, "status", before.get("status"), fields["status"], actor=actor, action="status", parent_id=did, note=note)
