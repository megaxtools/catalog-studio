"""ورود داده‌ی خام محصولات از فایل (Excel/CSV/JSON) به‌صورت یک «بانک داده‌ی خام» تازه.

محصولات واردشده مثل محصولات استخراج‌شده رفتار می‌کنند: داده‌ی خام دست‌نخورده می‌ماند، اسکیمای بانک ستون‌ها را می‌سازد و
از آن می‌شود بانک تمیز ساخت (تصاویر در همان مرحله از نشانی‌ها دانلود می‌شوند). ستون‌های ناشناخته هم با نام سرستون
در داده‌ی خام نگه داشته می‌شوند تا در اسکیما (ستون «استخراجی» با همان نام) قابل استفاده باشند.
"""
from __future__ import annotations

import re

from . import db, import_specs, services
from .textutil import slugify

SOURCE_KEY = "file-import"


def ensure_source() -> dict:
    row = db.q1("SELECT id FROM sources WHERE key=?", [SOURCE_KEY])
    if row:
        return services.get_source(row["id"])
    cfg = {"key": SOURCE_KEY, "name": "ورود از فایل", "virtual": True, "domains": [],
           "notes": "منبع مجازی برای محصولاتی که از فایل Excel/CSV/JSON وارد می‌شوند.", "listing": {}, "product": {}, "fields": []}
    return services.save_source(cfg)


def _item_data(r: dict) -> dict:
    d: dict = {}
    for k in ("title", "title_en", "brand", "brand_en", "category", "short_description", "long_description", "sku", "compatible_vehicles"):
        v = r.get(k)
        if v not in (None, ""):
            d[k] = str(v).strip() if not isinstance(v, list) else "، ".join(map(str, v))
    if r.get("specifications") not in (None, "", []):
        d["specifications"] = import_specs.parse_specs(r["specifications"])
    imgs = import_specs.split_urls(r.get("gallery"))
    feat = import_specs.split_urls(r.get("featured_image"))
    if feat:
        d["featured_image"] = feat[0]
        imgs = feat[1:] + imgs
    elif imgs:
        d["featured_image"] = imgs[0]
        imgs = imgs[1:]
    if imgs:
        d["gallery"] = list(dict.fromkeys(imgs))
    if d.get("category"):
        d["breadcrumb"] = [x.strip() for x in re.split(r"[›>/]", d["category"]) if x.strip()]
    for k, v in (r.get("_extra") or {}).items():
        key = str(k).strip()
        if key and key not in d:
            d[key] = v if isinstance(v, (int, float, list, dict)) else str(v)
    return d


def import_file(data_url: str, name: str, title: str = "", schema_id: int | None = None, category_label: str = "",
                mapping: dict | None = None, actor: str = "ui") -> dict:
    rows = import_specs.parse("raw", data_url, name, mapping)
    rows = [r for r in rows if str(r.get("title") or "").strip()]
    if not rows:
        raise ValueError("هیچ ردیفی با «عنوان» (title) در فایل پیدا نشد. ستون عنوان را مشخص کنید یا فایل نمونه را ببینید.")
    src = ensure_source()
    label = (category_label or title or re.sub(r"\.\w+$", "", name) or "ورود از فایل").strip()
    ds = services.create_dataset(src["id"], f"file://{slugify(name) or 'upload'}", len(rows), schema_id,
                                 {"file_import": {"name": name, "rows": len(rows)}, "category_label_manual": True}, {}, label)
    did = ds["id"]
    now = db.now()
    seq, keys = 0, set()
    for r in rows:
        seq += 1
        d = _item_data(r)
        key = (slugify(d.get("sku") or d.get("title_en") or d["title"]) or f"row-{seq}")[:80]
        while key in keys:
            key = f"{key[:74]}-{seq}"
        keys.add(key)
        url = str(r.get("source_url") or "").strip() or f"file://{ds['code']}/{seq}"
        db.ex("""INSERT INTO items(dataset_id, source_id, url, product_key, seq, status, data, scraped_at, created_at, updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?)""", [did, src["id"], url, key, seq, "done", db.jdump(d), now, now, now])
    upd = {"status": "completed", "step": f"{len(rows)} محصول از فایل وارد شد", "total_found": len(rows), "total_expected": len(rows),
           "discovery_done": 1, "started_at": now, "finished_at": now, "category_key": slugify(label) or "upload"}
    if title:
        upd["title"] = title
    db.update("datasets", did, **upd)
    if not title:
        services.refresh_dataset_naming(did)
    db.log("dataset", did, f"{len(rows)} محصول از فایل «{name}» وارد شد ({actor}).", level="success", step="import")
    return services.get_dataset(did)
