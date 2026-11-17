"""داده‌های اولیه و انتقال خودکار از نسخه‌ی ۱ به ۲ (فقط افزایشی؛ هیچ داده‌ای حذف یا بازنویسی نمی‌شود)."""
from __future__ import annotations

import json

from . import db, revisions

COMPAT_COL = {"key": "compatible_vehicles", "label": "خودروهای سازگار", "kind": "ref", "ref": "vehicles", "input": "vehicles",
              "vehicle_format": "structured", "required": True, "include": True}

CATALOG_SCHEMA = {
    "name": "عنوان و تصاویر (کاتالوگ)", "usage": "catalog",
    "description": "اسکیمای کوچک برای خروجی‌هایی که فقط عنوان، اسلاگ و تصاویر محصول را لازم دارند.",
    "columns": [
        {"key": "title", "label": "عنوان محصول", "kind": "scraped", "from": "title", "input": "text", "required": True},
        {"key": "slug", "label": "اسلاگ", "kind": "auto", "generator": "slug", "input": "text"},
        {"key": "brand", "label": "برند", "kind": "ref", "ref": "brand", "ref_field": "slug", "input": "text"},
        {"key": "featured_image", "label": "تصویر شاخص", "kind": "scraped", "from": "featured_image", "input": "image"},
        {"key": "gallery", "label": "گالری", "kind": "scraped", "from": "gallery", "input": "images", "export": "json"},
    ],
}


def _restore_schema(sid: int, snap: dict, actor: str):
    if not db.q1("SELECT id FROM schemas WHERE id=?", [sid]):
        raise ValueError("این اسکیما حذف شده است.")
    db.ex("UPDATE schemas SET name=?, description=?, usage=?, columns=?, updated_at=? WHERE id=?",
          [snap.get("name") or "اسکیما", snap.get("description") or "", snap.get("usage") or "general", db.jdump(snap.get("columns") or []), db.now(), sid])


revisions.register_restorer("schema", _restore_schema)


def _ensure_compat_column():
    """ستون اجباری «خودروهای سازگار» به اسکیمای پیش‌فرض مگا کارز افزوده می‌شود (فقط یک بار)."""
    done = db.get_settings().get("_v2_compat_col")
    if done:
        return
    for s in db.q("SELECT * FROM schemas WHERE name LIKE '%مگا کارز%' OR is_default=1"):
        cols = db.jload(s["columns"], []) or []
        if any(c.get("input") == "vehicles" or (c.get("kind") == "ref" and c.get("ref") == "vehicles") for c in cols):
            continue
        pos = next((i + 1 for i, c in enumerate(cols) if c.get("key") in ("brand_slug", "category_slug")), len(cols))
        for i, c in enumerate(cols):
            if c.get("key") == "brand_slug":
                pos = i + 1
        cols.insert(pos, dict(COMPAT_COL))
        db.ex("UPDATE schemas SET columns=?, updated_at=? WHERE id=?", [db.jdump(cols), db.now(), s["id"]])
        revisions.record("schema", s["id"], {"name": s["name"], "description": s.get("description"), "usage": "general", "columns": cols,
                                              "is_default": s["is_default"]}, actor="system", action="migrate", note="افزودن ستون سازگاری با خودرو")
    db.ex("INSERT INTO settings(key, value) VALUES('_v2_compat_col', 'true') ON CONFLICT(key) DO UPDATE SET value='true'")


def _default_templates():
    if db.val("SELECT COUNT(*) FROM tpl_outputs"):
        return
    from .product_catalog import save_template
    main = db.q1("SELECT id FROM schemas WHERE is_default=1 ORDER BY id LIMIT 1") or db.q1("SELECT id FROM schemas ORDER BY id LIMIT 1")
    if not main:
        return
    small = db.q1("SELECT id FROM schemas WHERE name=?", [CATALOG_SCHEMA["name"]])
    if not small:
        sid = db.ex("INSERT INTO schemas(name, description, columns, is_default, usage, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    [CATALOG_SCHEMA["name"], CATALOG_SCHEMA["description"], json.dumps(CATALOG_SCHEMA["columns"], ensure_ascii=False), 0,
                     "catalog", db.now(), db.now()])
        small = {"id": sid}
    save_template({
        "name": "مگا کارز — کامل", "is_default": True,
        "description": "همه‌ی داده‌ها با اسکیمای مگا کارز (JSON و Excel)، برندها، دسته‌ها، خودروهای سازگار و جدول سازگاری؛ تصاویر در پوشه‌ی هر محصول.",
        "config": {"root": "{catalog}-r{release}", "zip": True, "manifest": True,
                   "images": {"enabled": True, "path": "images/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}", "which": "all", "link": "relative"},
                   "outputs": [
                       {"name": "محصولات", "kind": "products", "format": "json", "schema_id": main["id"], "path": "products.json"},
                       {"name": "محصولات (Excel)", "kind": "products", "format": "xlsx", "schema_id": main["id"], "path": "products.xlsx"},
                       {"name": "برندها", "kind": "brands", "format": "xlsx", "path": "brands.xlsx"},
                       {"name": "دسته‌بندی‌ها", "kind": "categories", "format": "json", "path": "categories.json"},
                       {"name": "خودروهای سازگار", "kind": "vehicles", "format": "json", "path": "vehicles.json"},
                       {"name": "سازگاری", "kind": "compatibility", "format": "csv", "path": "compatibility.csv"},
                   ]},
    }, actor="system")
    save_template({
        "name": "عنوان و تصاویر + برندها",
        "description": "نمونه: عنوان و تصاویر محصولات در یک JSON داخل پوشه‌ی data، برندها در Excel در ریشه، تصاویر بر اساس برند.",
        "config": {"root": "{catalog}-r{release}", "zip": True, "manifest": True,
                   "images": {"enabled": True, "path": "images/{brand_slug}/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}",
                              "which": "all", "link": "relative"},
                   "outputs": [
                       {"name": "عنوان و تصاویر", "kind": "products", "format": "json", "schema_id": small["id"], "path": "data/products.json"},
                       {"name": "برندها", "kind": "brands", "format": "xlsx", "path": "brands.xlsx"},
                   ]},
    }, actor="system")
    save_template({
        "name": "یک فایل JSON برای هر محصول",
        "description": "نمونه: برای هر محصول یک فایل JSON جدا کنار تصاویرش (products/{slug}/product.json).",
        "config": {"root": "{catalog}-r{release}", "zip": True, "manifest": True,
                   "images": {"enabled": True, "path": "products/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}",
                              "which": "all", "link": "relative"},
                   "outputs": [{"name": "محصول", "kind": "products", "format": "json", "schema_id": main["id"], "path": "products/{slug}/product.json"}]},
    }, actor="system")


def run():
    from . import refdata
    db.ex("UPDATE schemas SET usage='general' WHERE usage IS NULL OR usage=''")
    refdata.seed_from_mappings()
    _ensure_compat_column()
    _default_templates()
