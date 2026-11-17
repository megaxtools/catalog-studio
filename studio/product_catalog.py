"""کاتالوگ محصولات: الگوهای خروجی (درخت فایل)، کاتالوگ‌ها و انتشارهای نسخه‌دار.

- «الگوی خروجی» تعیین می‌کند هر انتشار چه فایل‌هایی دارد: هر خروجی یک نوع (محصولات، برندها، دسته‌ها، خودروها،
  سازگاری)، یک قالب (JSON، Excel، CSV)، یک اسکیما (برای محصولات) و یک مسیر در درخت فایل دارد. تصاویر هم با الگوی
  مسیر و نام دلخواه کپی می‌شوند.
- «کاتالوگ» = انتخاب محصولات تمیز (بانک‌ها، وضعیت، حداقل کیفیت، برند/دسته) + یک الگوی خروجی.
- «انتشار» = یک بار ساخت کاتالوگ با شماره‌ی ترتیبی (r1، r2، …). هر انتشار تغییرناپذیر است: فایل‌ها، نسخه‌ی الگو،
  ریویژن هر محصول و رکورد اصلی هر محصول ذخیره می‌شود و تفاوتش با انتشار قبلی محاسبه می‌شود.

نشانه‌های مسیر: {catalog} {release} {date} · برای هر محصول {slug} {uid} {id} {brand_slug} {category_slug} · برای تصاویر {name} {ext} {n}
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import threading
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

from . import compat, db, modules, refdata, revisions, services, workbench
from .config import WORKBENCH_DIR

KINDS = {"products": "محصولات", "brands": "برندها", "categories": "دسته‌بندی‌ها", "vehicles": "خودروهای سازگار",
         "compatibility": "جدول سازگاری محصول و خودرو"}
FORMATS = {"json": "JSON (آرایه)", "xlsx": "Excel", "csv": "CSV"}
KIND_FIELDS = {
    "brands": ["name", "name_en", "slug", "country", "category_slugs", "description", "aliases", "products"],
    "categories": ["name", "name_en", "slug", "parent_slug", "path", "path_slug", "brand_slugs", "description", "products"],
    "vehicles": ["level", "brand", "brand_en", "brand_slug", "model", "model_en", "model_slug", "trim", "trim_en", "trim_slug", "slug_path", "products"],
    "compatibility": ["product_uid", "product_slug", "product_title", "all", "level", "brand_slug", "model_slug", "trim_slug", "slug_path", "label"],
}
STATES = {"draft": "پیش‌نویس", "active": "فعال", "archived": "بایگانی"}
_TOKEN = re.compile(r"\{(\w+)\}")
PRODUCT_TOKENS = {"slug", "uid", "id", "brand_slug", "category_slug"}


# ---------------------------------------------------------------------------
# الگوهای خروجی
# ---------------------------------------------------------------------------

DEFAULT_IMAGES = {"enabled": True, "path": "images/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}",
                  "which": "all", "link": "relative", "prefix": ""}


def tpl_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["config"] = normalize_config(db.jload(r.get("config"), {}) or {})
    return r


def normalize_config(c: dict) -> dict:
    c = dict(c or {})
    c["root"] = (c.get("root") or "{catalog}-r{release}").strip().strip("/") or "{catalog}-r{release}"
    outs = []
    for i, o in enumerate(c.get("outputs") or [], 1):
        kind = o.get("kind") or "products"
        fmt = o.get("format") or "json"
        if kind not in KINDS or fmt not in FORMATS:
            continue
        path = _clean_path(o.get("path") or f"{kind}.{fmt}")
        if not path.lower().endswith("." + fmt):
            path = re.sub(r"\.(json|xlsx|csv)$", "", path, flags=re.I) + "." + fmt
        outs.append({"id": o.get("id") or f"o{i}", "name": o.get("name") or KINDS[kind], "kind": kind, "format": fmt, "path": path,
                     "schema_id": int(o["schema_id"]) if kind == "products" and o.get("schema_id") else None,
                     "fields": [f for f in (o.get("fields") or KIND_FIELDS.get(kind, [])) if f in KIND_FIELDS.get(kind, [])] if kind != "products" else None,
                     "json_wrap": o.get("json_wrap") or "", "indent": int(o.get("indent", 2) or 0)})
    c["outputs"] = outs
    im = {**DEFAULT_IMAGES, **(c.get("images") or {})}
    im["path"] = _clean_path(im.get("path") or DEFAULT_IMAGES["path"])
    im["enabled"] = bool(im.get("enabled"))
    im["which"] = im.get("which") if im.get("which") in ("all", "feature") else "all"
    im["link"] = im.get("link") if im.get("link") in ("relative", "prefix", "source") else "relative"
    c["images"] = im
    c["zip"] = c.get("zip", True) is not False
    c["manifest"] = c.get("manifest", True) is not False
    return c


def _clean_path(p: str) -> str:
    p = str(p or "").replace("\\", "/").strip()
    parts = [x for x in p.split("/") if x not in ("", ".", "..")]
    return "/".join(parts)


def validate_config(c: dict) -> list[str]:
    errs = []
    c = normalize_config(c)
    if not c["outputs"] and not c["images"]["enabled"]:
        errs.append("الگو دست‌کم یک خروجی یا تصاویر لازم دارد.")
    seen = set()
    for o in c["outputs"]:
        if o["kind"] == "products" and not o["schema_id"]:
            errs.append(f"برای خروجی «{o['name']}» اسکیما انتخاب کنید.")
        elif o["kind"] == "products" and not db.q1("SELECT id FROM schemas WHERE id=?", [o["schema_id"]]):
            errs.append(f"اسکیمای خروجی «{o['name']}» پیدا نشد.")
        toks = set(_TOKEN.findall(o["path"]))
        if toks & PRODUCT_TOKENS and (o["kind"] != "products" or o["format"] != "json"):
            errs.append(f"مسیر «{o['path']}»: فایل جدا برای هر محصول فقط در خروجی JSON محصولات ممکن است.")
        if o["path"] in seen:
            errs.append(f"مسیر «{o['path']}» تکراری است.")
        seen.add(o["path"])
    if c["images"]["enabled"] and not {"slug", "uid", "id"} & set(_TOKEN.findall(c["images"]["path"])):
        errs.append("مسیر تصاویر باید {slug} یا {uid} داشته باشد تا تصاویر محصولات روی هم نوشته نشوند.")
    if c["images"]["enabled"] and "{name}" not in c["images"]["path"] and "{n}" not in c["images"]["path"]:
        errs.append("مسیر تصاویر باید {name} یا {n} داشته باشد.")
    return errs


def list_templates() -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM tpl_outputs ORDER BY is_default DESC, id"):
        t = tpl_row(r)
        t["used_by"] = db.val("SELECT COUNT(*) FROM cat_catalogs WHERE template_id=?", [t["id"]]) or 0
        t["tree"] = preview_tree(t["config"])
        out.append(t)
    return out


def get_template(tid: int) -> dict:
    t = tpl_row(db.q1("SELECT * FROM tpl_outputs WHERE id=?", [tid]))
    if not t:
        raise ValueError("الگوی خروجی پیدا نشد.")
    t["tree"] = preview_tree(t["config"])
    return t


def save_template(body: dict, tid: int | None = None, actor: str = "ui") -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("نام الگو لازم است.")
    cfg = normalize_config(body.get("config") or {})
    errs = validate_config(cfg)
    if errs:
        raise ValueError("؛ ".join(errs))
    now = db.now()
    if body.get("is_default"):
        db.ex("UPDATE tpl_outputs SET is_default=0")
    if tid:
        get_template(tid)
        db.update("tpl_outputs", tid, name=name, description=body.get("description") or "", config=cfg,
                  is_default=1 if body.get("is_default") else 0, updated_at=now)
        action = "edit"
    else:
        tid = db.ex("INSERT INTO tpl_outputs(name, description, config, is_default, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    [name, body.get("description") or "", db.jdump(cfg), 1 if body.get("is_default") else 0, now, now])
        action = "create"
    revisions.record("template", tid, {"name": name, "description": body.get("description") or "", "config": cfg}, actor=actor, action=action)
    return get_template(tid)


def delete_template(tid: int, actor: str = "ui") -> dict:
    t = get_template(tid)
    n = db.val("SELECT COUNT(*) FROM cat_catalogs WHERE template_id=?", [tid]) or 0
    if n:
        raise ValueError(f"{n} کاتالوگ از این الگو استفاده می‌کند.")
    revisions.record("template", tid, {"name": t["name"], "config": t["config"]}, actor=actor, action="delete", force=True)
    db.ex("DELETE FROM tpl_outputs WHERE id=?", [tid])
    return {"ok": True}


def _restore_tpl(tid: int, snap: dict, actor: str):
    db.update("tpl_outputs", tid, name=snap.get("name") or "الگو", description=snap.get("description") or "",
              config=normalize_config(snap.get("config") or {}), updated_at=db.now())


revisions.register_restorer("template", _restore_tpl)


def preview_tree(cfg: dict, sample: list[dict] | None = None) -> list[dict]:
    """پیش‌نمایش درخت فایل‌های یک انتشار با دو محصول نمونه."""
    cfg = normalize_config(cfg)
    sample = sample or [{"slug": "castrol-edge-5w30-4l", "uid": "P1-12", "id": 12, "brand_slug": "castrol", "category_slug": "engine-oil", "images": 3},
                        {"slug": "bosch-wiper-blade-60", "uid": "P1-13", "id": 13, "brand_slug": "bosch", "category_slug": "wiper", "images": 1}]
    ctx = {"catalog": "mega-catalog", "release": "3", "date": datetime.now().strftime("%Y%m%d")}
    files: list[dict] = []
    for o in cfg["outputs"]:
        if set(_TOKEN.findall(o["path"])) & PRODUCT_TOKENS:
            for s in sample:
                files.append({"path": fill(o["path"], {**ctx, **s}), "label": f"{o['name']} ({FORMATS[o['format']]})"})
        else:
            sch = services.get_schema(o["schema_id"]) if o.get("schema_id") else None
            files.append({"path": fill(o["path"], ctx), "label": f"{o['name']} ({FORMATS[o['format']]}{' · ' + sch['name'] if sch else ''})"})
    if cfg["images"]["enabled"]:
        for s in sample:
            for i in range(s["images"] if cfg["images"]["which"] == "all" else 1):
                name = cfg["images"]["feature_name"] if i == 0 else fill(cfg["images"]["gallery_name"], {"n": str(i)})
                files.append({"path": fill(cfg["images"]["path"], {**ctx, **s, "name": name, "ext": "png", "n": str(i)}), "label": "تصویر شاخص" if i == 0 else "گالری"})
    if cfg["manifest"]:
        files.append({"path": "manifest.json", "label": "شناسنامه‌ی انتشار"})
    root = fill(cfg["root"], ctx)
    return [{"path": f"{root}/{f['path']}", "label": f["label"]} for f in sorted(files, key=lambda x: x["path"])] + \
           ([{"path": f"{root}.zip", "label": "بسته‌ی فشرده"}] if cfg["zip"] else [])


def fill(pattern: str, ctx: dict) -> str:
    def rep(m):
        v = ctx.get(m.group(1))
        return str(v) if v not in (None, "") else m.group(0) if m.group(1) not in ctx else "none"
    out = _TOKEN.sub(rep, pattern)
    out = re.sub(r'[<>:"|?*\x00-\x1f]', "-", out)
    return _clean_path(out)


# ---------------------------------------------------------------------------
# کاتالوگ‌ها
# ---------------------------------------------------------------------------

def cat_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["selection"] = db.jload(r.get("selection"), {}) or {}
    r["options"] = db.jload(r.get("options"), {}) or {}
    return r


def get_catalog(cid: int) -> dict:
    c = cat_row(db.q1("SELECT * FROM cat_catalogs WHERE id=?", [cid]))
    if not c:
        raise ValueError("کاتالوگ پیدا نشد.")
    return c


def catalog_summary(c: dict) -> dict:
    c = dict(c)
    t = db.q1("SELECT id, name FROM tpl_outputs WHERE id=?", [c.get("template_id")])
    c["template"] = dict(t) if t else None
    last = db.q1("SELECT id, number, status, created_at, finished_at, stats, step, progress_done, progress_total FROM cat_releases WHERE catalog_id=? ORDER BY number DESC LIMIT 1", [c["id"]])
    if last:
        last = dict(last)
        last["stats"] = db.jload(last["stats"], {}) or {}
    c["last_release"] = last
    c["releases"] = db.val("SELECT COUNT(*) FROM cat_releases WHERE catalog_id=?", [c["id"]]) or 0
    c["state_label"] = STATES.get(c["state"], c["state"])
    return c


def list_catalogs() -> list[dict]:
    return [catalog_summary(cat_row(r)) for r in db.q("SELECT * FROM cat_catalogs ORDER BY id DESC")]


def _norm_selection(s: dict) -> dict:
    return {"bank_ids": [int(i) for i in s.get("bank_ids") or []], "statuses": [x for x in (s.get("statuses") or ["approved"]) if x in workbench.ACTIVE],
            "min_quality": int(s["min_quality"]) if s.get("min_quality") not in (None, "") else None,
            "require_ready": s.get("require_ready", True) is not False, "brand_ids": [int(i) for i in s.get("brand_ids") or []],
            "category_ids": [int(i) for i in s.get("category_ids") or []], "include_ids": [int(i) for i in s.get("include_ids") or []],
            "exclude_ids": [int(i) for i in s.get("exclude_ids") or []]}


def save_catalog(body: dict, cid: int | None = None, actor: str = "ui") -> dict:
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("عنوان کاتالوگ لازم است.")
    slug = (body.get("slug") or "").strip().lower() or services.slugify(body.get("slug_hint") or title) or "catalog"
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug):
        raise ValueError("شناسه‌ی انگلیسی کاتالوگ معتبر نیست.")
    if db.q1("SELECT id FROM cat_catalogs WHERE slug=? AND id<>?", [slug, cid or 0]):
        raise ValueError(f"شناسه‌ی «{slug}» تکراری است.")
    tid = int(body.get("template_id") or 0) or None
    if not tid:
        d = db.q1("SELECT id FROM tpl_outputs ORDER BY is_default DESC, id LIMIT 1")
        tid = d["id"] if d else None
    if not tid or not db.q1("SELECT id FROM tpl_outputs WHERE id=?", [tid]):
        raise ValueError("الگوی خروجی انتخاب نشده است.")
    sel = _norm_selection(body.get("selection") or {})
    state = body.get("state") if body.get("state") in STATES else "draft"
    now = db.now()
    if cid:
        get_catalog(cid)
        db.update("cat_catalogs", cid, title=title, slug=slug, description=body.get("description") or "", template_id=tid, selection=sel,
                  options=body.get("options") or {}, state=state, updated_at=now)
        action = "edit"
    else:
        cid = db.ex("INSERT INTO cat_catalogs(slug, title, description, template_id, selection, options, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    [slug, title, body.get("description") or "", tid, db.jdump(sel), db.jdump(body.get("options") or {}), state, now, now])
        action = "create"
    revisions.record("catalog", cid, {"title": title, "slug": slug, "description": body.get("description") or "", "template_id": tid,
                                      "selection": sel, "state": state}, actor=actor, action=action)
    return catalog_summary(get_catalog(cid))


def _restore_cat(cid: int, snap: dict, actor: str):
    db.update("cat_catalogs", cid, title=snap["title"], slug=snap["slug"], description=snap.get("description") or "",
              template_id=snap.get("template_id"), selection=snap.get("selection") or {}, state=snap.get("state") or "draft", updated_at=db.now())


revisions.register_restorer("catalog", _restore_cat)


def delete_catalog(cid: int, files: bool = False, actor: str = "ui") -> dict:
    c = get_catalog(cid)
    rels = db.q("SELECT id, root FROM cat_releases WHERE catalog_id=?", [cid])
    if files:
        for r in rels:
            if r["root"]:
                shutil.rmtree(r["root"], ignore_errors=True)
                Path(r["root"] + ".zip").unlink(missing_ok=True)
    for r in rels:
        db.ex("DELETE FROM cat_release_items WHERE release_id=?", [r["id"]])
    db.ex("DELETE FROM cat_releases WHERE catalog_id=?", [cid])
    db.ex("DELETE FROM cat_catalogs WHERE id=?", [cid])
    revisions.record("catalog", cid, {"title": c["title"], "slug": c["slug"], "selection": c["selection"]}, actor=actor, action="delete", force=True)
    return {"ok": True, "releases": len(rels)}


def select_products(c: dict) -> tuple[list[dict], list[dict]]:
    """(محصولات انتخاب‌شده، محصولات کنارگذاشته با دلیل)"""
    s = _norm_selection(c["selection"])
    where = ["status IN ({})".format(",".join("?" * len(s["statuses"]) or "''"))]
    args: list = list(s["statuses"])
    if s["bank_ids"]:
        where.append(f"bank_id IN ({','.join('?' * len(s['bank_ids']))})")
        args += s["bank_ids"]
    if s["brand_ids"]:
        where.append(f"brand_id IN ({','.join('?' * len(s['brand_ids']))})")
        args += s["brand_ids"]
    if s["category_ids"]:
        where.append(f"category_id IN ({','.join('?' * len(s['category_ids']))})")
        args += s["category_ids"]
    sql = f"SELECT * FROM wb_products WHERE ({' AND '.join(where)})"
    if s["include_ids"]:
        sql += f" OR (id IN ({','.join('?' * len(s['include_ids']))}) AND status IN ('draft','review','approved','rejected'))"
        args += s["include_ids"]
    rows = [workbench.product_row(r) for r in db.q(sql + " ORDER BY bank_id, seq, id", args)]
    chosen, skipped = [], []
    minq = s["min_quality"] if s["min_quality"] is not None else int((db.get_settings().get("quality") or {}).get("min_score", 70))
    qon = modules.is_enabled("quality")
    for p in rows:
        if p["id"] in s["exclude_ids"]:
            skipped.append({"id": p["id"], "title": p["title"], "why": "دستی کنار گذاشته شده"})
            continue
        if qon and s["require_ready"]:
            qd = p.get("quality_detail") or {}
            if qd.get("errors"):
                skipped.append({"id": p["id"], "title": p["title"], "why": "خطای کیفیت: " + "؛ ".join(e["label"] for e in qd["errors"][:3])})
                continue
            if (p.get("quality") or 0) < minq:
                skipped.append({"id": p["id"], "title": p["title"], "why": f"امتیاز کیفیت {p.get('quality') or 0} کمتر از {minq}"})
                continue
        chosen.append(p)
    return chosen, skipped


def preview_selection(cid: int) -> dict:
    c = get_catalog(cid)
    chosen, skipped = select_products(c)
    return {"count": len(chosen), "skipped": skipped[:300], "skipped_count": len(skipped),
            "sample": [{"id": p["id"], "title": p["title"], "slug": p["slug"], "quality": p.get("quality")} for p in chosen[:50]]}


# ---------------------------------------------------------------------------
# ساخت انتشار
# ---------------------------------------------------------------------------

def _records(o: dict, products: list[dict], img_map: dict, cfg: dict, schemas: dict) -> list:
    """رکوردهای یک خروجی (برای JSON ساختاریافته؛ برای Excel/CSV بعداً تخت می‌شوند)."""
    from .catalogs import structured
    kind = o["kind"]
    if kind == "products":
        sc = schemas[o["schema_id"]]
        out = []
        for p in products:
            rec = {}
            for col in sc["columns"]:
                if col.get("include", True) is False:
                    continue
                role = workbench.core_role(col)
                if role in ("feature", "gallery"):
                    links = img_map.get(p["id"]) or {"feature": "", "gallery": []}
                    v = links["feature"] if role == "feature" else links["gallery"]
                else:
                    v = workbench.product_value(p, col)
                rec[col["key"]] = structured(col, v) if col.get("input") != "vehicles" and role != "compat" else v
            out.append(rec)
        return out
    counts_b: dict = {}
    counts_c: dict = {}
    for p in products:
        if p.get("brand_id"):
            counts_b[p["brand_id"]] = counts_b.get(p["brand_id"], 0) + 1
        if p.get("category_id"):
            counts_c[p["category_id"]] = counts_c.get(p["category_id"], 0) + 1
    if kind == "brands":
        out = []
        for bid, n in sorted(counts_b.items()):
            b = refdata.get("brand", bid)
            if b:
                cidx = refdata.category_index()
                out.append({**{k: b.get(k, "") for k in ("name", "name_en", "slug", "country", "description")}, "aliases": b.get("aliases") or [],
                            "category_slugs": [cidx[c]["slug"] for c in b.get("category_ids") or [] if c in cidx], "products": n})
        return [{f: r.get(f, "") for f in o["fields"]} for r in out]
    if kind == "categories":
        cats = {c["id"]: c for c in refdata.list_items("category", with_counts=False)}
        cidx = refdata.category_index()
        all_brands = refdata.list_items("brand", with_counts=False)
        out = []
        for cid, n in sorted(counts_c.items()):
            c = cats.get(cid)
            if c:
                par = cats.get(c.get("parent_id"))
                rel = set(refdata.related_categories(cid, cidx))
                out.append({"name": c["name"], "name_en": c.get("name_en", ""), "slug": c["slug"], "parent_slug": par["slug"] if par else "",
                            "path": c.get("path", c["name"]), "path_slug": c.get("path_slug", c["slug"]), "description": c.get("description") or "",
                            "brand_slugs": [b["slug"] for b in all_brands if rel & set(b["category_ids"])], "products": n})
        return [{f: r.get(f, "") for f in o["fields"]} for r in out]
    if kind == "vehicles":
        seen: dict[str, dict] = {}
        for p in products:
            for it in compat.describe(p["compat"])["items"]:
                key = it["slug_path"]
                r = seen.setdefault(key, {"level": it["t"], **{k: it.get(k, "") for k in ("brand", "brand_en", "brand_slug", "model", "model_en",
                                                                                          "model_slug", "trim", "trim_en", "trim_slug", "slug_path")}, "products": 0})
                r["products"] += 1
        return [{f: r.get(f, "") for f in o["fields"]} for r in sorted(seen.values(), key=lambda x: x["slug_path"])]
    if kind == "compatibility":
        out = []
        for p in products:
            d = compat.describe(p["compat"])
            base = {"product_uid": p["uid"], "product_slug": p["slug"], "product_title": p["title"]}
            if d["all"]:
                out.append({**base, "all": True, "level": "all", "brand_slug": "", "model_slug": "", "trim_slug": "", "slug_path": "all", "label": "همه‌ی خودروها"})
            for it in d["items"]:
                out.append({**base, "all": False, "level": it["t"], "brand_slug": it.get("brand_slug", ""), "model_slug": it.get("model_slug", ""),
                            "trim_slug": it.get("trim_slug", ""), "slug_path": it["slug_path"], "label": it.get("display") or it["label"]})
        return [{f: r.get(f, "") for f in o["fields"]} for r in out]
    return []


def _flat(o: dict, records: list, schemas: dict) -> tuple[list[str], list[list]]:
    if o["kind"] != "products":
        heads = o["fields"]
        return heads, [[r.get(h, "") if not isinstance(r.get(h), (list, dict)) else json.dumps(r.get(h), ensure_ascii=False) for h in heads] for r in records]
    sc = schemas[o["schema_id"]]
    cols = [c for c in sc["columns"] if c.get("include", True) is not False]
    heads: list[str] = []
    rows = []
    for rec in records:
        row = []
        for col in cols:
            row.extend(services.expand_column(col, rec.get(col["key"]), None))
        if not heads:
            heads = [k for k, _ in row]
        rows.append([v for _, v in row])
    if not heads:
        for col in cols:
            heads.extend(k for k, _ in services.expand_column(col, None, None))
    return heads, rows


def _write(path: Path, fmt: str, o: dict, records, schemas: dict, title: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if fmt == "json":
        data = records
        if o.get("json_wrap"):
            data = {o["json_wrap"]: records}
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=o.get("indent") or None, default=str), encoding="utf-8")
    elif fmt == "csv":
        heads, rows = _flat(o, records, schemas)
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(heads)
            for r in rows:
                w.writerow(["" if v is None else v for v in r])
    else:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        heads, rows = _flat(o, records, schemas)
        wb = Workbook()
        ws = wb.active
        ws.title = (o.get("name") or "data")[:30]
        ws.sheet_view.rightToLeft = True
        ws.append(heads)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="4F39F6")
        for r in rows:
            ws.append(["" if v is None else v for v in r])
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, str) and "\n" in c.value:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
        for i, h in enumerate(heads, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(60, max(12, len(str(h)) + 4))
        ws.freeze_panes = "A2"
        info = wb.create_sheet("info")
        info.append(["عنوان", title])
        info.append(["تعداد ردیف", len(rows)])
        info.append(["ساخته‌شده در", db.now()])
        wb.save(tmp)
    tmp.replace(path)


class ReleaseJobs:
    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}

    def recover(self):
        db.ex("UPDATE cat_releases SET status='error', error='استودیو حین ساخت بسته شد', step='خطا' WHERE status IN ('running','pending')")

    def start(self, cid: int, note: str = "", wait: bool = False) -> dict:
        c = get_catalog(cid)
        if db.q1("SELECT id FROM cat_releases WHERE catalog_id=? AND status IN ('running','pending')", [cid]):
            raise ValueError("یک انتشار از این کاتالوگ در حال ساخت است.")
        num = (db.val("SELECT MAX(number) FROM cat_releases WHERE catalog_id=?", [cid]) or 0) + 1
        rid = db.ex("INSERT INTO cat_releases(catalog_id, number, status, step, note, created_at) VALUES(?,?,?,?,?,?)",
                    [cid, num, "running", "آماده‌سازی", note or "", db.now()])
        t = threading.Thread(target=self._run, args=(rid,), daemon=True)
        self.threads[rid] = t
        t.start()
        if wait:
            t.join(900)
        return get_release(rid)

    def _run(self, rid: int):
        try:
            build(rid)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            db.update("cat_releases", rid, status="error", error=str(exc)[:800], step="خطا", finished_at=db.now())


RELEASES = ReleaseJobs()


def build(rid: int):
    r = db.q1("SELECT * FROM cat_releases WHERE id=?", [rid])
    c = get_catalog(r["catalog_id"])
    tpl = get_template(c["template_id"])
    cfg = tpl["config"]
    step = lambda s, d=None, t=None: db.update("cat_releases", rid, step=s, **({"progress_done": d} if d is not None else {}),  # noqa: E731
                                               **({"progress_total": t} if t is not None else {}))
    step("انتخاب محصولات")
    products, skipped = select_products(c)
    if not products:
        raise ValueError("هیچ محصولی شرایط این کاتالوگ را ندارد (وضعیت، کیفیت یا فیلترها را بررسی کنید).")
    ctx = {"catalog": c["slug"], "release": str(r["number"]), "date": datetime.now().strftime("%Y%m%d")}
    base = Path(db.get_settings()["output_root"]) / "catalogs" / c["slug"]
    root = base / fill(cfg["root"], ctx)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    schemas = {}
    for o in cfg["outputs"]:
        if o["kind"] == "products":
            sc = services.get_schema(o["schema_id"])
            if not sc:
                raise ValueError(f"اسکیمای خروجی «{o['name']}» پیدا نشد.")
            schemas[o["schema_id"]] = {"id": sc["id"], "name": sc["name"], "columns": sc["columns"]}
    # تصاویر
    img_map: dict[int, dict] = {}
    files: list[dict] = []
    imc = cfg["images"]
    step("کپی تصاویر", 0, len(products))
    for i, p in enumerate(products, 1):
        pctx = {**ctx, "slug": p["slug"], "uid": p["uid"], "id": p["id"],
                "brand_slug": (refdata.get("brand", p.get("brand_id")) or {}).get("slug", "no-brand"),
                "category_slug": (refdata.get("category", p.get("category_id")) or {}).get("slug", "no-category")}
        p["_ctx"] = pctx
        links = {"feature": "", "gallery": []}
        ims = p["images"] if imc["which"] == "all" else p["images"][:1]
        for n, im in enumerate(ims):
            if imc["link"] == "source" or not imc["enabled"]:
                link = im.get("src") if str(im.get("src", "")).startswith("http") else ""
            else:
                srcp = WORKBENCH_DIR / (im.get("final") or "")
                if not im.get("final") or not srcp.exists():
                    continue
                name = imc["feature_name"] if n == 0 else fill(imc["gallery_name"], {"n": str(n)})
                rel = fill(imc["path"], {**pctx, "name": name, "ext": srcp.suffix.lstrip(".").lower(), "n": str(n)})
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(srcp, dst)
                files.append({"path": rel, "kind": "image", "size": dst.stat().st_size})
                link = (imc["prefix"].rstrip("/") + "/" + rel) if imc["link"] == "prefix" and imc.get("prefix") else rel
            if n == 0:
                links["feature"] = link
            else:
                links["gallery"].append(link)
        img_map[p["id"]] = links
        if i % 10 == 0:
            step("کپی تصاویر", i)
    # خروجی‌های داده
    main_records: dict[int, dict] = {}
    for o in cfg["outputs"]:
        step(f"ساخت {o['name']} ({FORMATS[o['format']]})")
        recs = _records(o, products, img_map, cfg, schemas)
        if o["kind"] == "products" and not main_records:
            main_records = {p["id"]: rec for p, rec in zip(products, recs)}
        if set(_TOKEN.findall(o["path"])) & PRODUCT_TOKENS:
            for p, rec in zip(products, recs):
                rel = fill(o["path"], p["_ctx"])
                _write(root / rel, "json", {**o, "json_wrap": ""}, rec, schemas, c["title"])
                files.append({"path": rel, "kind": o["kind"], "size": (root / rel).stat().st_size})
        else:
            rel = fill(o["path"], ctx)
            _write(root / rel, o["format"], o, recs, schemas, c["title"])
            files.append({"path": rel, "kind": o["kind"], "format": o["format"], "rows": len(recs), "size": (root / rel).stat().st_size, "output": o["id"]})
    # شناسنامه، اقلام و تفاوت با انتشار قبل
    prev = db.q1("SELECT id, number FROM cat_releases WHERE catalog_id=? AND status='completed' AND id<>? ORDER BY number DESC LIMIT 1", [c["id"], rid])
    prev_items = {x["uid"]: dict(x) for x in db.q("SELECT uid, product_rev, title, record FROM cat_release_items WHERE release_id=?", [prev["id"]])} if prev else {}
    db.ex("DELETE FROM cat_release_items WHERE release_id=?", [rid])
    added, changed, same = [], [], 0
    for p in products:
        rec = main_records.get(p["id"]) or {"title": p["title"], "slug": p["slug"]}
        db.ex("INSERT INTO cat_release_items(release_id, product_id, uid, product_rev, title, record) VALUES(?,?,?,?,?,?)",
              [rid, p["id"], p["uid"], p.get("rev"), p["title"], json.dumps(rec, ensure_ascii=False, default=str)])
        if prev:
            old = prev_items.get(p["uid"])
            if not old:
                added.append({"uid": p["uid"], "title": p["title"]})
            else:
                ch = revisions.diff(json.loads(old["record"] or "{}"), rec)
                if ch:
                    changed.append({"uid": p["uid"], "title": p["title"], "fields": [x["field"] for x in ch][:20], "from_rev": old["product_rev"], "to_rev": p.get("rev")})
                else:
                    same += 1
    removed = [{"uid": u, "title": x["title"]} for u, x in prev_items.items() if u not in {p["uid"] for p in products}] if prev else []
    diff = {"previous": prev["number"] if prev else None, "added": added, "removed": removed, "changed": changed, "unchanged": same}
    stats = {"products": len(products), "skipped": len(skipped), "files": len(files), "images": sum(1 for f in files if f["kind"] == "image"),
             "added": len(added), "removed": len(removed), "changed": len(changed)}
    if cfg["manifest"]:
        man = {"catalog": c["slug"], "title": c["title"], "release": r["number"], "created_at": db.now(), "template": tpl["name"],
               "stats": stats, "outputs": [{k: o[k] for k in ("name", "kind", "format", "path")} for o in cfg["outputs"]],
               "products": [{"uid": p["uid"], "slug": p["slug"], "rev": p.get("rev")} for p in products]}
        (root / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        files.append({"path": "manifest.json", "kind": "manifest", "size": (root / "manifest.json").stat().st_size})
    zip_path = ""
    if cfg["zip"]:
        step("ساخت بسته‌ی فشرده")
        zp = root.with_name(root.name + ".zip")
        tmp = zp.with_name(zp.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    z.write(f, (Path(root.name) / f.relative_to(root)).as_posix())
        tmp.replace(zp)
        zip_path = str(zp)
    snap = {"template": {"id": tpl["id"], "name": tpl["name"], "config": cfg}, "schemas": schemas, "selection": c["selection"], "skipped": skipped[:500]}
    db.update("cat_releases", rid, status="completed", step="آماده", root=str(root), files={"list": files, "zip": zip_path, "root": str(root)},
              stats=stats, diff=diff, snapshot=snap, finished_at=db.now(), progress_done=len(products), progress_total=len(products))
    db.log("catalog", c["id"], f"انتشار {r['number']} کاتالوگ «{c['title']}» با {len(products)} محصول ساخته شد.", level="success")


def rel_row(r: dict | None, full: bool = False) -> dict | None:
    if not r:
        return None
    r = dict(r)
    for k, d in (("files", {}), ("stats", {}), ("diff", {}), ("snapshot", {})):
        r[k] = db.jload(r.get(k), d) or d
    if not full:
        r["snapshot"] = {"template": {"name": (r["snapshot"].get("template") or {}).get("name")}, "skipped": (r["snapshot"].get("skipped") or [])[:50]}
    return r


def get_release(rid: int, full: bool = False) -> dict:
    r = rel_row(db.q1("SELECT * FROM cat_releases WHERE id=?", [rid]), full)
    if not r:
        raise ValueError("انتشار پیدا نشد.")
    return r


def list_releases(cid: int) -> list[dict]:
    return [rel_row(r) for r in db.q("SELECT * FROM cat_releases WHERE catalog_id=? ORDER BY number DESC", [cid])]


def release_items(rid: int, q: str = "", page: int = 1, size: int = 100) -> dict:
    where, args = ["release_id=?"], [rid]
    if q:
        where.append("(title LIKE ? OR uid LIKE ?)")
        args += [f"%{q}%"] * 2
    w = " AND ".join(where)
    total = db.val(f"SELECT COUNT(*) FROM cat_release_items WHERE {w}", args) or 0
    rows = db.q(f"SELECT * FROM cat_release_items WHERE {w} ORDER BY id LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])
    for r in rows:
        r["record"] = json.loads(r["record"] or "{}")
    return {"total": total, "rows": rows}


def compare_releases(a_id: int, b_id: int) -> dict:
    a, b = get_release(a_id), get_release(b_id)
    ia = {x["uid"]: x for x in db.q("SELECT uid, title, product_rev, record FROM cat_release_items WHERE release_id=?", [a_id])}
    ib = {x["uid"]: x for x in db.q("SELECT uid, title, product_rev, record FROM cat_release_items WHERE release_id=?", [b_id])}
    changed = []
    for u in set(ia) & set(ib):
        ch = revisions.diff(json.loads(ia[u]["record"] or "{}"), json.loads(ib[u]["record"] or "{}"))
        if ch:
            changed.append({"uid": u, "title": ib[u]["title"], "changes": ch[:30]})
    return {"a": a["number"], "b": b["number"], "added": [{"uid": u, "title": ib[u]["title"]} for u in set(ib) - set(ia)],
            "removed": [{"uid": u, "title": ia[u]["title"]} for u in set(ia) - set(ib)], "changed": changed}


def delete_release(rid: int, files: bool = True) -> dict:
    r = get_release(rid)
    if files and r.get("root"):
        shutil.rmtree(r["root"], ignore_errors=True)
        if r["files"].get("zip"):
            Path(r["files"]["zip"]).unlink(missing_ok=True)
    db.ex("DELETE FROM cat_release_items WHERE release_id=?", [rid])
    db.ex("DELETE FROM cat_releases WHERE id=?", [rid])
    db.history("cat_release", rid, "*", {"catalog_id": r["catalog_id"], "number": r["number"]}, "", action="delete")
    return {"ok": True}
