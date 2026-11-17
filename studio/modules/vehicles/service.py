"""بانک خودروها (برند ← مدل ← تیپ) و منطق «سازگاری با خودرو».

مقدار سازگاری هر محصول:
    {"all": true}                                     سازگار با همه‌ی خودروها (پیش‌فرض)
    {"all": false, "items": [{"t": "brand", "id": 3}, {"t": "model", "id": 51}, {"t": "trim", "id": 120}]}

انتخاب برند یعنی همه‌ی مدل‌ها و تیپ‌هایش (حتی مدل‌هایی که بعداً به بانک اضافه شوند)، و انتخاب مدل یعنی همه‌ی
تیپ‌هایش. فقط خودروهای موجود در همین بانک قابل انتخاب‌اند.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ... import db, revisions
from ...refdata import norm
from .slugs import english_name, make_slug

LEVELS = {"brand": "veh_brands", "model": "veh_models", "trim": "veh_trims"}
LEVEL_LABELS = {"brand": "برند", "model": "مدل", "trim": "تیپ"}
PARENT = {"model": ("brand_id", "brand"), "trim": ("model_id", "model")}
ALL = {"all": True}
DATA_FILE = Path(__file__).parent / "data" / "cars-db.json"
_cache: dict = {"ver": -1}


def _bump():
    _cache["ver"] = -1


def _rowd(level: str, r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["aliases"] = db.jload(r.get("aliases"), []) or []
    r["level"] = level
    return r


def get(level: str, vid: int) -> dict | None:
    if level not in LEVELS:
        raise ValueError("سطح خودرو نامعتبر است.")
    return _rowd(level, db.q1(f"SELECT * FROM {LEVELS[level]} WHERE id=?", [vid]))


# ---------------------------------------------------------------------------
# بارگذاری اولیه و ورود
# ---------------------------------------------------------------------------

def _unique_slug(table: str, slug: str, scope_col: str | None, scope_id: int | None, exclude: int = 0) -> str:
    base, n = slug, 1
    while True:
        if scope_col:
            hit = db.q1(f"SELECT id FROM {table} WHERE slug=? AND {scope_col}=? AND id<>?", [slug, scope_id, exclude])
        else:
            hit = db.q1(f"SELECT id FROM {table} WHERE slug=? AND id<>?", [slug, exclude])
        if not hit:
            return slug
        n += 1
        slug = f"{base}-{n}"


def import_rows(rows: list, actor: str = "system") -> dict:
    """ردیف‌های {brand, model, type, brand_en?, brand_slug?, model_en?, model_slug?, type_en?, type_slug?} یا [برند، مدل، تیپ].
    موارد موجود تکرار نمی‌شوند؛ نام/اسلاگ انگلیسیِ داده‌شده روی مورد تازه می‌نشیند (و مورد خودکار را تکمیل می‌کند)."""
    now = db.now()
    added = {"brand": 0, "model": 0, "trim": 0}
    updated = 0
    brands = {norm(r["name"]): r["id"] for r in db.q("SELECT id, name FROM veh_brands")}
    models = {(r["brand_id"], norm(r["name"])): r["id"] for r in db.q("SELECT id, brand_id, name FROM veh_models")}
    trims = {(r["model_id"], norm(r["name"])): r["id"] for r in db.q("SELECT id, model_id, name FROM veh_trims")}
    c = db.conn()

    def fix_en(table, rid, en, slug, scope_col=None, scope_id=None):
        """اگر مورد موجود نام انگلیسی خودکار دارد و فایل نام/اسلاگ داده، تکمیلش کن."""
        nonlocal updated
        if not (en or slug):
            return
        cur = c.execute(f"SELECT name_en, slug, auto_en FROM {table} WHERE id=?", [rid]).fetchone()
        if not cur or not cur[2]:
            return
        new_slug = _unique_slug(table, slug, scope_col, scope_id, rid) if slug and slug != cur[1] else cur[1]
        c.execute(f"UPDATE {table} SET name_en=?, slug=?, auto_en=0, updated_at=? WHERE id=?", [en or cur[0], new_slug, now, rid])
        updated += 1

    with db._lock:  # noqa: SLF001
        for raw in rows:
            if isinstance(raw, dict):
                g = lambda *ks: next((str(raw.get(k) or "").strip() for k in ks if str(raw.get(k) or "").strip()), "")  # noqa: E731
                b, m, t = g("brand"), g("model"), g("type", "trim")
                ben, bsl, men, msl, ten, tsl = g("brand_en"), g("brand_slug"), g("model_en"), g("model_slug"), g("type_en", "trim_en"), g("type_slug", "trim_slug")
            else:
                b, m, t = [str(x or "").strip() for x in (list(raw) + ["", "", ""])[:3]]
                ben = bsl = men = msl = ten = tsl = ""
            bsl, msl, tsl = (make_slug(x, x) if x else "" for x in (bsl, msl, tsl))
            if not b:
                continue
            bid = brands.get(norm(b))
            if not bid:
                en = ben or english_name(b, "brand")
                slug = _unique_slug("veh_brands", bsl or make_slug(en, b), None, None)
                bid = c.execute("INSERT INTO veh_brands(name, name_en, slug, aliases, sort, active, auto_en, notes, created_at, updated_at) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?)", [b, en, slug, "[]", 0, 1, 0 if (ben or bsl) else 1, "", now, now]).lastrowid
                brands[norm(b)] = bid
                added["brand"] += 1
            else:
                fix_en("veh_brands", bid, ben, bsl)
            if not m:
                continue
            mid = models.get((bid, norm(m)))
            if not mid:
                en = men or english_name(m)
                slug = _unique_slug("veh_models", msl or make_slug(en, m), "brand_id", bid)
                mid = c.execute("INSERT INTO veh_models(brand_id, name, name_en, slug, aliases, active, auto_en, notes, created_at, updated_at) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?)", [bid, m, en, slug, "[]", 1, 0 if (men or msl) else 1, "", now, now]).lastrowid
                models[(bid, norm(m))] = mid
                added["model"] += 1
            else:
                fix_en("veh_models", mid, men, msl, "brand_id", bid)
            if not t:
                continue
            tid = trims.get((mid, norm(t)))
            if not tid:
                en = ten or english_name(t)
                slug = _unique_slug("veh_trims", tsl or make_slug(en, t), "model_id", mid)
                tid = c.execute("INSERT INTO veh_trims(model_id, name, name_en, slug, aliases, active, auto_en, notes, created_at, updated_at) "
                                "VALUES(?,?,?,?,?,?,?,?,?,?)", [mid, t, en, slug, "[]", 1, 0 if (ten or tsl) else 1, "", now, now]).lastrowid
                trims[(mid, norm(t))] = tid
                added["trim"] += 1
            else:
                fix_en("veh_trims", tid, ten, tsl, "model_id", mid)
        c.commit()
    _bump()
    if any(added.values()) or updated:
        db.log("system", None, f"بانک خودروها: {added['brand']} برند، {added['model']} مدل و {added['trim']} تیپ افزوده و {updated} مورد تکمیل شد ({actor}).")
    return {"added": added, "updated": updated}


def seed():
    if not db.val("SELECT COUNT(*) FROM veh_brands") and DATA_FILE.exists():
        import_rows(json.loads(DATA_FILE.read_text(encoding="utf-8")), actor="system")


def parse_upload(data_url: str, name: str, mapping: dict | None = None) -> list:
    """فایل xlsx/csv/json → ردیف‌ها. سرستون‌ها طبق مشخصات ورود (brand, model, type, …؛ فارسی هم قبول است).
    فایل بی‌سرستون (سه ستون برند، مدل، تیپ) هم پذیرفته می‌شود."""
    from ... import import_specs
    raw = import_specs.decode(data_url)
    if name.lower().endswith(".json"):
        data = json.loads(raw.decode("utf-8-sig"))
        if data and isinstance(data[0], list):
            return data
    heads, rows = import_specs.read_table(raw, name)
    m = import_specs.auto_mapping("vehicles", heads)
    if mapping:
        m.update({h: k for h, k in mapping.items() if h in m})
    if "brand" not in m.values():  # بدون سرستون: سرستون خودش ردیف اول است
        first = dict(zip(["brand", "model", "type"], heads))
        return [first] + [dict(zip(["brand", "model", "type"], list(r.values())[:3])) for r in rows]
    return import_specs.apply_mapping(rows, m)


# ---------------------------------------------------------------------------
# مرور، جست‌وجو و ویرایش
# ---------------------------------------------------------------------------

def stats() -> dict:
    return {"brands": db.val("SELECT COUNT(*) FROM veh_brands") or 0, "models": db.val("SELECT COUNT(*) FROM veh_models") or 0,
            "trims": db.val("SELECT COUNT(*) FROM veh_trims") or 0,
            "auto_en": (db.val("SELECT COUNT(*) FROM veh_brands WHERE auto_en=1") or 0) + (db.val("SELECT COUNT(*) FROM veh_models WHERE auto_en=1") or 0)
            + (db.val("SELECT COUNT(*) FROM veh_trims WHERE auto_en=1") or 0)}


def brands(q: str = "") -> list[dict]:
    rows = [_rowd("brand", r) for r in db.q("SELECT b.*, (SELECT COUNT(*) FROM veh_models m WHERE m.brand_id=b.id) AS models, "
                                             "(SELECT COUNT(*) FROM veh_trims t JOIN veh_models m ON m.id=t.model_id WHERE m.brand_id=b.id) AS trims "
                                             "FROM veh_brands b ORDER BY b.sort, b.name")]
    if q:
        nq = norm(q)
        rows = [r for r in rows if nq in norm(r["name"]) or nq in norm(r.get("name_en")) or nq in r["slug"]]
    return rows


def brand_tree(bid: int) -> dict:
    b = get("brand", bid)
    if not b:
        raise ValueError("برند پیدا نشد.")
    ms = [_rowd("model", r) for r in db.q("SELECT * FROM veh_models WHERE brand_id=? ORDER BY name", [bid])]
    trims: dict[int, list] = {}
    for t in db.q("SELECT t.* FROM veh_trims t JOIN veh_models m ON m.id=t.model_id WHERE m.brand_id=? ORDER BY t.name", [bid]):
        trims.setdefault(t["model_id"], []).append(_rowd("trim", t))
    for m in ms:
        m["trims"] = trims.get(m["id"], [])
    b["models"] = ms
    return b


def _index() -> dict:
    """نمایه‌ی حافظه‌ای همه‌ی خودروها برای توصیف، جست‌وجو و تطبیق متن."""
    ver = (db.val("SELECT MAX(updated_at) FROM veh_trims") or "", db.val("SELECT MAX(updated_at) FROM veh_models") or "",
           db.val("SELECT MAX(updated_at) FROM veh_brands") or "", db.val("SELECT COUNT(*) FROM veh_trims"),
           db.val("SELECT COUNT(*) FROM veh_models"), db.val("SELECT COUNT(*) FROM veh_brands"))
    if _cache.get("ver") == ver:
        return _cache
    B = {r["id"]: _rowd("brand", r) for r in db.q("SELECT * FROM veh_brands")}
    M = {r["id"]: _rowd("model", r) for r in db.q("SELECT * FROM veh_models")}
    T = {r["id"]: _rowd("trim", r) for r in db.q("SELECT * FROM veh_trims")}
    models_of: dict[int, list] = {}
    trims_of: dict[int, list] = {}
    for m in M.values():
        models_of.setdefault(m["brand_id"], []).append(m["id"])
    for t in T.values():
        trims_of.setdefault(t["model_id"], []).append(t["id"])
    _cache.clear()
    _cache.update({"ver": ver, "B": B, "M": M, "T": T, "models_of": models_of, "trims_of": trims_of, "matcher": None})
    return _cache


def path_of(level: str, vid: int) -> dict | None:
    ix = _index()
    if level == "brand":
        b = ix["B"].get(vid)
        return b and {"t": "brand", "id": vid, "brand": b["name"], "brand_en": b["name_en"], "brand_slug": b["slug"],
                      "label": b["name"], "slug_path": b["slug"]}
    if level == "model":
        m = ix["M"].get(vid)
        b = m and ix["B"].get(m["brand_id"])
        return m and b and {"t": "model", "id": vid, "brand": b["name"], "brand_en": b["name_en"], "brand_slug": b["slug"],
                            "model": m["name"], "model_en": m["name_en"], "model_slug": m["slug"],
                            "label": f"{b['name']} {m['name']}", "slug_path": f"{b['slug']}/{m['slug']}"}
    t = ix["T"].get(vid)
    m = t and ix["M"].get(t["model_id"])
    b = m and ix["B"].get(m["brand_id"])
    return t and m and b and {"t": "trim", "id": vid, "brand": b["name"], "brand_en": b["name_en"], "brand_slug": b["slug"],
                              "model": m["name"], "model_en": m["name_en"], "model_slug": m["slug"], "trim": t["name"],
                              "trim_en": t["name_en"], "trim_slug": t["slug"], "label": f"{b['name']} {m['name']} {t['name']}",
                              "slug_path": f"{b['slug']}/{m['slug']}/{t['slug']}"}


def search(q: str, limit: int = 60) -> list[dict]:
    ix = _index()
    nq = norm(q)
    if not nq:
        return []
    words = nq.split()
    out = []
    for level, key in (("brand", "B"), ("model", "M"), ("trim", "T")):
        for vid in ix[key]:
            p = path_of(level, vid)
            hay = norm(" ".join(str(p.get(k) or "") for k in ("brand", "brand_en", "model", "model_en", "trim", "trim_en")) + " " + p["slug_path"])
            if all(w in hay for w in words):
                out.append(p)
    rank = {"brand": 0, "model": 1, "trim": 2}
    out.sort(key=lambda p: (rank[p["t"]], len(p["label"])))
    return out[:limit]


def _snap(r: dict) -> dict:
    return {k: r.get(k) for k in ("name", "name_en", "slug", "aliases", "active", "notes", "brand_id", "model_id") if k in r}


def save(level: str, data: dict, vid: int | None = None, actor: str = "ui") -> dict:
    t = LEVELS.get(level)
    if not t:
        raise ValueError("سطح خودرو نامعتبر است.")
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("نام لازم است.")
    cur = get(level, vid) if vid else None
    if vid and not cur:
        raise ValueError("مورد پیدا نشد.")
    parent_col, parent_level = PARENT.get(level, (None, None))
    parent_id = int(data.get(parent_col) or (cur or {}).get(parent_col) or 0) if parent_col else None
    if parent_col and not get(parent_level, parent_id):
        raise ValueError(f"{LEVEL_LABELS[parent_level]} والد پیدا نشد.")
    name_en = (data.get("name_en") if data.get("name_en") is not None else (cur or {}).get("name_en")) or english_name(name, level)
    if cur:
        auto_en = 0 if (data.get("name_en") and data["name_en"] != cur.get("name_en")) else cur.get("auto_en", 1)
    else:
        auto_en = 0 if data.get("name_en") else 1
    slug = (data.get("slug") or (cur or {}).get("slug") or make_slug(name_en, name)).strip().lower()
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug):
        raise ValueError(f"اسلاگ «{slug}» معتبر نیست؛ فقط حروف کوچک انگلیسی، عدد و خط تیره.")
    clash = db.q1(f"SELECT id FROM {t} WHERE slug=? AND id<>? {'AND ' + parent_col + '=?' if parent_col else ''}",
                  [slug, vid or 0] + ([parent_id] if parent_col else []))
    if clash:
        raise ValueError(f"اسلاگ «{slug}» در همین سطح تکراری است.")
    aliases = data.get("aliases", (cur or {}).get("aliases") or [])
    if isinstance(aliases, str):
        aliases = [a.strip() for a in re.split(r"[\n,،]", aliases) if a.strip()]
    v = {"name": name, "name_en": name_en, "slug": slug, "aliases": aliases, "active": 1 if data.get("active", True) else 0,
         "notes": data.get("notes", (cur or {}).get("notes") or ""), "auto_en": auto_en}
    if parent_col:
        v[parent_col] = parent_id
    now = db.now()
    if vid:
        db.update(t, vid, **v, updated_at=now)
        action = "edit"
    else:
        cols = list(v) + ["created_at", "updated_at"]
        vals = [db.jdump(x) if isinstance(x, (list, dict)) else x for x in v.values()] + [now, now]
        vid = db.ex(f"INSERT INTO {t}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals)
        action = "create"
    _bump()
    r = get(level, vid)
    revisions.record(f"vehicle_{level}", vid, _snap(r), actor=actor, action=action)
    return r


def usage(level: str, vid: int) -> int:
    n = 0
    for r in db.q("SELECT compat FROM wb_products WHERE compat LIKE ?", [f'%"{level}"%']):
        c = db.jload(r["compat"], {}) or {}
        if any(i.get("t") == level and int(i.get("id") or 0) == vid for i in c.get("items") or []):
            n += 1
    return n


def delete(level: str, vid: int, actor: str = "ui") -> dict:
    r = get(level, vid)
    if not r:
        raise ValueError("مورد پیدا نشد.")
    used = usage(level, vid)
    if used:
        raise ValueError(f"{used} محصول به این {LEVEL_LABELS[level]} وصل است؛ به‌جای حذف، آن را «غیرفعال» کنید.")
    children = {"brand": ("veh_models", "brand_id"), "model": ("veh_trims", "model_id")}.get(level)
    if children and db.val(f"SELECT COUNT(*) FROM {children[0]} WHERE {children[1]}=?", [vid]):
        raise ValueError("این مورد زیرمجموعه دارد؛ اول زیرمجموعه‌ها را حذف کنید.")
    revisions.record(f"vehicle_{level}", vid, _snap(r), actor=actor, action="delete", force=True)
    db.ex(f"DELETE FROM {LEVELS[level]} WHERE id=?", [vid])
    _bump()
    return {"ok": True}


def _restorer(level):
    def fn(vid: int, snap: dict, actor: str):
        if not get(level, vid):
            raise ValueError("این مورد حذف شده است.")
        save(level, snap, vid, actor)
    return fn


for _lv in LEVELS:
    revisions.register_restorer(f"vehicle_{_lv}", _restorer(_lv))


# ---------------------------------------------------------------------------
# سازگاری با خودرو
# ---------------------------------------------------------------------------

def normalize(value, strict: bool = True) -> dict:
    """اعتبارسنجی و ساده‌سازی مقدار سازگاری؛ موارد زیرمجموعه‌ی یک انتخاب بالاتر حذف می‌شوند."""
    if value in (None, "", "all", True) or (isinstance(value, dict) and value.get("all")):
        return dict(ALL)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError("مقدار سازگاری نامعتبر است.") from None
    items = value.get("items") if isinstance(value, dict) else value
    if not isinstance(items, list):
        raise ValueError("مقدار سازگاری نامعتبر است.")
    ix = _index()
    keys = {"brand": "B", "model": "M", "trim": "T"}
    sel: set[tuple[str, int]] = set()
    for it in items:
        t = it.get("t") or it.get("type") or it.get("level")
        try:
            vid = int(it.get("id"))
        except (TypeError, ValueError):
            vid = 0
        if t not in keys or vid not in ix[keys[t]]:
            if strict:
                raise ValueError("فقط خودروهای موجود در «بانک خودروها» قابل انتخاب‌اند.")
            continue
        sel.add((t, vid))
    brands_sel = {i for t, i in sel if t == "brand"}
    models_sel = {i for t, i in sel if t == "model" and ix["M"][i]["brand_id"] not in brands_sel}
    trims_sel = {i for t, i in sel if t == "trim" and ix["T"][i]["model_id"] not in models_sel
                 and ix["M"][ix["T"][i]["model_id"]]["brand_id"] not in brands_sel}
    out = [{"t": "brand", "id": i} for i in sorted(brands_sel)] + [{"t": "model", "id": i} for i in sorted(models_sel)] + \
          [{"t": "trim", "id": i} for i in sorted(trims_sel)]
    return {"all": False, "items": out} if out else dict(ALL)


def describe(value) -> dict:
    v = normalize(value, strict=False)
    if v.get("all"):
        return {"all": True, "label": "همه‌ی خودروها", "items": []}
    items = [p for p in (path_of(i["t"], i["id"]) for i in v["items"]) if p]
    for p in items:
        p["display"] = p["label"] + (" (همه‌ی مدل‌ها)" if p["t"] == "brand" else " (همه‌ی تیپ‌ها)" if p["t"] == "model" and _index()["trims_of"].get(p["id"]) else "")
    lab = "، ".join(p["display"] for p in items[:4]) + (f" و {len(items) - 4} مورد دیگر" if len(items) > 4 else "")
    return {"all": False, "label": lab, "items": items}


def expand_leaves(value) -> list[dict]:
    """همه‌ی تیپ‌ها (یا مدل‌های بدون تیپ) پوشش‌داده‌شده."""
    v = normalize(value, strict=False)
    if v.get("all"):
        return []
    ix = _index()
    leaves: dict[tuple, dict] = {}

    def add_model(mid):
        ts = ix["trims_of"].get(mid) or []
        if ts:
            for tid in ts:
                leaves[("trim", tid)] = path_of("trim", tid)
        else:
            leaves[("model", mid)] = path_of("model", mid)
    for i in v["items"]:
        if i["t"] == "brand":
            for mid in ix["models_of"].get(i["id"]) or []:
                add_model(mid)
        elif i["t"] == "model":
            add_model(i["id"])
        else:
            leaves[("trim", i["id"])] = path_of("trim", i["id"])
    return [x for x in leaves.values() if x]


EXPORT_FORMATS = {"structured": "ساختاریافته (شیء JSON)", "slugs": "مسیر اسلاگ‌ها (peugeot/206/type-2)",
                  "names": "نام فارسی", "names_en": "نام انگلیسی", "expanded": "همه‌ی تیپ‌های پوشش‌داده‌شده (اسلاگ)"}


def export(value, fmt: str = "structured", all_token: str = "all"):
    """مقدار سازگاری برای خروجی کاتالوگ."""
    d = describe(value)
    if d["all"]:
        if fmt == "structured":
            return {"all": True, "vehicles": []}
        if fmt in ("names",):
            return ["همه‌ی خودروها"]
        return [all_token]
    if fmt == "structured":
        out = []
        for p in d["items"]:
            o = {"level": p["t"], "brand": p["brand"], "brand_en": p["brand_en"], "brand_slug": p["brand_slug"]}
            if p["t"] in ("model", "trim"):
                o.update({"model": p["model"], "model_en": p["model_en"], "model_slug": p["model_slug"]})
            if p["t"] == "trim":
                o.update({"trim": p["trim"], "trim_en": p["trim_en"], "trim_slug": p["trim_slug"]})
            out.append(o)
        return {"all": False, "vehicles": out}
    if fmt == "slugs":
        return [p["slug_path"] for p in d["items"]]
    if fmt == "names":
        return [p["display"] for p in d["items"]]
    if fmt == "names_en":
        return [" ".join(x for x in (p.get("brand_en"), p.get("model_en"), p.get("trim_en")) if x) for p in d["items"]]
    if fmt == "expanded":
        return [p["slug_path"] for p in expand_leaves(value)]
    return [p["slug_path"] for p in d["items"]]


# ---------------------------------------------------------------------------
# تطبیق متن با بانک خودروها (پیشنهاد سازگاری)
# ---------------------------------------------------------------------------
_ALL_RX = re.compile(r"(همه|تمام|تمامی|کلیه)\s*(ی\s*)?(انواع\s*)?(خودرو|ماشین)|universal|عمومی برای همه")


_GENERIC = {norm(w) for w in (
    "بنزینی", "بنزین", "دیزلی", "دیزل", "ساده", "کلاسیک", "اسپرت", "پلاس", "هیبرید", "برقی", "اتوماتیک", "دنده", "وانت", "ون", "کوپه",
    "سدان", "هاچبک", "کروک", "نیو", "سایر", "مدل", "مدلها", "لاکچری", "پرو", "مکس", "توربو", "اکو", "تیپ", "فول", "اسپورت", "استیشن",
    "پانوراما", "گرند", "کراس", "سوپر", "ویژه", "استاندارد", "معمولی", "قدیم", "جدید", "دوگانه", "سوز", "تک", "دو", "کابین", "صندوق", "دار",
    "پیکاپ", "روغن", "موتور", "فیلتر", "لنت", "ترمز", "مایع", "باتری", "لاستیک", "چراغ", "آینه", "بوق", "شمع", "تسمه", "پمپ")}


def _contains(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(r"(?<![\w؀-ۿ])" + re.escape(phrase) + r"(?![\w؀-ۿ])", text) is not None


def _matcher() -> dict:
    ix = _index()
    if ix.get("matcher"):
        return ix["matcher"]
    brand_names: dict[int, set] = {}
    for b in ix["B"].values():
        names = {norm(b["name"]), norm(b.get("name_en")), *[norm(a) for a in b["aliases"]]}
        names |= {norm(re.sub(r"\(.*?\)", "", b["name"]))}
        brand_names[b["id"]] = {n for n in names if n and len(n) >= 2}
    model_names: dict[int, set] = {}
    count: dict[str, int] = {}
    for m in ix["M"].values():
        names = {norm(m["name"]), norm(m.get("name_en")), *[norm(a) for a in m["aliases"]]}
        names = {n for n in names if n and n not in ("سایر مدل ها", "other models")}
        model_names[m["id"]] = names
        for n in names:
            count[n] = count.get(n, 0) + 1
    trim_names = {t["id"]: {n for n in {norm(t["name"]), norm(t.get("name_en"))} if n and len(n) >= 2} for t in ix["T"].values()}
    distinctive = {mid for mid, ns in model_names.items()
                   if any(count.get(n) == 1 and len(n) >= 4 and not n.isdigit() and not (set(n.split()) & _GENERIC) for n in ns)}
    ix["matcher"] = {"brand_names": brand_names, "model_names": model_names, "trim_names": trim_names, "count": count, "distinctive": distinctive}
    return ix["matcher"]


def suggest(text: str, max_items: int = 30) -> dict:
    """پیشنهاد سازگاری از روی متن (عنوان، توضیح، مشخصات). خروجی: {value, matches:[…], confidence}"""
    ix = _index()
    mt = _matcher()
    t = norm(text)
    if not t or not ix["B"]:
        return {"value": dict(ALL), "matches": [], "confidence": 0}
    if _ALL_RX.search(t):
        return {"value": dict(ALL), "matches": [{"t": "all", "label": "همه‌ی خودروها", "why": "عبارت «همه‌ی خودروها» در متن"}], "confidence": 80}
    found: dict[tuple, dict] = {}
    brands_hit = {bid for bid, ns in mt["brand_names"].items() if any(_contains(t, n) for n in ns)}
    for bid in brands_hit:
        models_hit = [mid for mid in ix["models_of"].get(bid) or [] if any(_contains(t, n) for n in mt["model_names"][mid])]
        if not models_hit:
            found[("brand", bid)] = {"why": "نام برند در متن"}
            continue
        for mid in models_hit:
            trims_hit = [tid for tid in ix["trims_of"].get(mid) or [] if any(_contains(t, n) for n in mt["trim_names"][tid])]
            if trims_hit:
                for tid in trims_hit:
                    found[("trim", tid)] = {"why": "نام برند، مدل و تیپ در متن"}
            else:
                found[("model", mid)] = {"why": "نام برند و مدل در متن"}
    for mid in mt["distinctive"]:
        m = ix["M"][mid]
        if m["brand_id"] in brands_hit:
            continue
        if any(_contains(t, n) for n in mt["model_names"][mid] if mt["count"].get(n) == 1 and len(n) >= 4 and not n.isdigit()):
            found[("model", mid)] = {"why": "نام مدل (بدون برند) در متن", "weak": True}
    # برندهایی که خودشان نام خودرو هستند (پراید، سمند، تیبا، دنا…) و مدلی برایشان پیدا نشد
    items = [{"t": k[0], "id": k[1]} for k in found][:max_items]
    if not items:
        return {"value": dict(ALL), "matches": [], "confidence": 0}
    val = normalize({"items": items}, strict=False)
    d = describe(val)
    why = {(k[0], k[1]): v["why"] for k, v in found.items()}
    for p in d["items"]:
        p["why"] = why.get((p["t"], p["id"]), "")
    weak = {(k[0], k[1]) for k, v in found.items() if v.get("weak")}
    strong = [p for p in d["items"] if p["t"] in ("model", "trim") and (p["t"], p["id"]) not in weak]
    conf = 85 if strong else 60
    return {"value": val, "matches": d["items"], "confidence": conf}


def ai_suggest(text: str, client) -> dict:
    """تطبیق با کمک هوش مصنوعی: فقط از میان نامزدهای بانک خودروها انتخاب می‌کند (شناسه‌ها)."""
    from ...ai import parse_json
    base = suggest(text)
    ix = _index()
    cands = []
    bids = {p.get("id") for p in base["matches"] if p.get("t") == "brand"} | {ix["M"][p["id"]]["brand_id"] for p in base["matches"] if p.get("t") == "model"}
    bids |= {ix["M"][ix["T"][p["id"]]["model_id"]]["brand_id"] for p in base["matches"] if p.get("t") == "trim"}
    if bids:
        for bid in bids:
            cands.append(path_of("brand", bid))
            for mid in ix["models_of"].get(bid) or []:
                cands.append(path_of("model", mid))
                for tid in ix["trims_of"].get(mid) or []:
                    cands.append(path_of("trim", tid))
    else:
        cands = [path_of("brand", bid) for bid in ix["B"]]
    cands = cands[:400]
    lines = "\n".join(f'{c["t"]}:{c["id"]} = {c["label"]}' for c in cands)
    system = ("You map automotive product text to vehicles from a fixed list. Answer ONLY JSON: "
              '{"all": true} if the product fits all cars or the text gives no specific vehicle; otherwise '
              '{"all": false, "items": [{"t": "brand|model|trim", "id": N}]}. Choose only from the list. Choose a brand when '
              "all its models fit, a model when all its trims fit.")
    user = f"متن محصول:\n{text[:3000]}\n\nفهرست مجاز:\n{lines}"
    raw = client.chat(system, user, temperature=0.1, max_tokens=800)
    try:
        obj = parse_json(raw)
        val = normalize(obj, strict=False)
    except Exception:  # noqa: BLE001
        val = base["value"]
    d = describe(val)
    return {"value": val, "matches": d["items"], "confidence": 90 if not val.get("all") else 50, "ai": True}


def ai_english(level: str, client, ids: list[int] | None = None, only_auto: bool = True, update_slugs: bool = False,
               limit: int = 400, actor: str = "ai") -> dict:
    """تکمیل نام انگلیسی رسمی خودروها با هوش مصنوعی (دسته‌ای)."""
    from ...ai import parse_json
    t = LEVELS[level]
    where = "auto_en=1" if only_auto else "1=1"
    if ids:
        where += f" AND id IN ({','.join(str(int(i)) for i in ids)})"
    rows = db.q(f"SELECT id FROM {t} WHERE {where} ORDER BY id LIMIT ?", [limit])
    done = 0
    for i in range(0, len(rows), 60):
        chunk = [path_of(level, r["id"]) for r in rows[i:i + 60]]
        lines = "\n".join(f'{c["id"]}: {c["label"]}' for c in chunk if c)
        system = ("Give the official English (Latin) name used internationally or in the Iranian car market for each vehicle "
                  f"{level} below. Answer ONLY a JSON object {{id: english_name}}. For a {level} give only that part's name "
                  "(not the brand). Keep numbers, engine codes and Latin parts as-is.")
        obj = parse_json(client.chat(system, lines, temperature=0.1, max_tokens=4000))
        for k, en in (obj or {}).items():
            try:
                vid = int(k)
            except ValueError:
                continue
            cur = get(level, vid)
            if not cur or not isinstance(en, str) or not en.strip():
                continue
            data = {**cur, "name_en": en.strip()}
            if update_slugs:
                data["slug"] = _unique_slug(t, make_slug(en.strip(), cur["name"]), PARENT.get(level, (None,))[0],
                                            cur.get(PARENT.get(level, (None,))[0]) if level != "brand" else None, exclude=vid)
            save(level, data, vid, actor)
            done += 1
    return {"updated": done}


def export_rows() -> list[dict]:
    out = []
    ix = _index()
    for b in sorted(ix["B"].values(), key=lambda x: x["name"]):
        mids = sorted(ix["models_of"].get(b["id"]) or [], key=lambda i: ix["M"][i]["name"])
        if not mids:
            out.append({"brand": b["name"], "brand_en": b["name_en"], "brand_slug": b["slug"]})
        for mid in mids:
            m = ix["M"][mid]
            tids = sorted(ix["trims_of"].get(mid) or [], key=lambda i: ix["T"][i]["name"])
            base = {"brand": b["name"], "brand_en": b["name_en"], "brand_slug": b["slug"], "model": m["name"], "model_en": m["name_en"], "model_slug": m["slug"]}
            if not tids:
                out.append(base)
            for tid in tids:
                tr = ix["T"][tid]
                out.append({**base, "type": tr["name"], "type_en": tr["name_en"], "type_slug": tr["slug"]})
    return out
