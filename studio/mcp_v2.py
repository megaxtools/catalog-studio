"""ابزارهای MCP نسخه‌ی ۲: ماژول‌ها، داده‌ی مرجع، خودروها و سازگاری، ویرایشگر داده‌ها (بانک‌های تمیز و محصولات)،
کیفیت، تکراری‌ها، الگوها و کاتالوگ‌ها و انتشارها، ریویژن‌ها و پشتیبان.

همه‌ی ابزارها فقط HTTP API استودیو را صدا می‌زنند (مثل بقیه‌ی ابزارهای mcp_core). ابزارهای وابسته به یک ماژول با module=
علامت خورده‌اند تا اگر آن ماژول خاموش بود، به ایجنت نشان داده نشوند.
"""
from __future__ import annotations

import base64
import io

from .mcp_core import B, I, IDS, O, S, Images, ToolError, p, tool

ARR = {"type": "array"}
STATUSES = ["draft", "review", "approved", "rejected", "archived"]
COMPAT_DESC = ('Vehicle compatibility value: {"all": true} (every vehicle, the default) or {"all": false, "items": [{"t": "brand|model|trim", '
               '"id": N}]}. Selecting a brand covers all its models; a model covers all its trims. Ids come ONLY from the vehicles bank '
               '(search_vehicles).')


def _clean(a: dict, *drop: str) -> dict:
    return {k: v for k, v in a.items() if k not in drop and v is not None}


def _compact_product(r: dict) -> dict:
    out = {k: r.get(k) for k in ("id", "bank_id", "uid", "title", "slug", "status", "quality", "rev")}
    out["brand"] = (r.get("brand") or {}).get("slug") or (f"? {r['brand_raw']}" if r.get("brand_raw") else None)
    out["category"] = (r.get("category") or {}).get("slug") or (f"? {r['category_raw']}" if r.get("category_raw") else None)
    out["compat"] = (r.get("compat_info") or {}).get("label")
    if r.get("compat_auto"):
        out["compat_auto"] = True
    out["images"] = len(r.get("images") or [])
    return out


# ---------------------------------------------------------------------------
# ماژول‌ها و نمای کلی
# ---------------------------------------------------------------------------

@tool("v2_overview", "Overview of the v2 pipeline: raw datasets → clean banks (data editor) → product catalogs/releases; review queue, open "
      "duplicates, reference lists and which modules are enabled. Start here for anything about clean data or catalogs.")
def _ov(api, a):
    return api.get("/api/overview")


@tool("list_modules", "Studio modules (image editor, vehicles, quality, dedup, AI, scraper, rembg, align, MCP, legacy export, …) with "
      "enabled/health/dependency info. Core modules cannot be disabled.")
def _mods(api, a):
    return [{k: m.get(k) for k in ("id", "name", "core", "enabled", "status", "healthy", "health", "requires", "dependents", "error")} for m in api.get("/api/modules")]


@tool("set_module_enabled", "Enable or disable a non-core studio module. Disabling hides its pages, API and MCP tools; data is kept.",
      {"module_id": p(S, "Module id"), "enabled": p(B, "true/false")}, ["module_id", "enabled"], write=True)
def _mod_set(api, a):
    return api.put(f"/api/modules/{a['module_id']}", {"enabled": bool(a["enabled"])})


# ---------------------------------------------------------------------------
# داده‌های مرجع
# ---------------------------------------------------------------------------

@tool("list_reference", "Reference lists used by clean products: kind=brand (product brands) or category (product categories, tree). "
      "Every product's brand/category must be one of these.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "q": p(S, "Search")}, ["kind"])
def _ref_list(api, a):
    rows = api.get(f"/api/ref/{a['kind']}", q=a.get("q"))
    return [{k: r.get(k) for k in ("id", "name", "name_en", "slug", "aliases", "parent_id", "path", "products", "active") if r.get(k) not in (None, "", [])} for r in rows]


@tool("save_reference", "Create (no id) or update a brand/category in the reference list. Fields: name (Persian), name_en, slug (English, "
      "unique), aliases (source spellings that should resolve to it), parent_id (categories), active.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "id": p(I, "Existing id to update"), "name": p(S, "Persian name"),
       "name_en": p(S, "English name"), "slug": p(S, "Slug"), "aliases": p(ARR, "Aliases", items=S), "parent_id": p(I, "Parent category"),
       "active": p(B, "Active")}, ["kind"], write=True)
def _ref_save(api, a):
    body = _clean(a, "kind", "id")
    return api.put(f"/api/ref/{a['kind']}/{a['id']}", body) if a.get("id") else api.post(f"/api/ref/{a['kind']}", body)


@tool("unmatched_reference", "Brand/category values found in clean products that are not linked to the reference list yet (with counts).",
      {"kind": p(S, "brand | category", enum=["brand", "category"])}, ["kind"])
def _ref_unmatched(api, a):
    return api.get(f"/api/ref/{a['kind']}/unmatched")


@tool("link_reference", "Link an unmatched source value to a reference brand/category (updates all products that have it; adds it as alias).",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "name": p(S, "Unmatched value"), "id": p(I, "Reference id")},
      ["kind", "name", "id"], write=True)
def _ref_link(api, a):
    return api.post(f"/api/ref/{a['kind']}/link", {"name": a["name"], "id": a["id"]})


# ---------------------------------------------------------------------------
# خودروها و سازگاری
# ---------------------------------------------------------------------------

@tool("search_vehicles", "Search the vehicles bank (brand → model → trim) by Persian or English name. Returns ids usable in compatibility values.",
      {"q": p(S, "Search text, e.g. «پژو ۲۰۶» or 'tiba'"), "limit": p(I, "Max (default 30)")}, ["q"], module="vehicles")
def _veh_search(api, a):
    return api.get("/api/vehicles/search", q=a["q"], limit=a.get("limit") or 30)


@tool("vehicle_tree", "All models and trims of one vehicle brand (from search_vehicles or list_vehicle_brands).",
      {"brand_id": p(I, "Vehicle brand id")}, ["brand_id"], module="vehicles")
def _veh_tree(api, a):
    return api.get(f"/api/vehicles/brands/{a['brand_id']}/tree")


@tool("list_vehicle_brands", "Vehicle brands with model/trim counts.", {"q": p(S, "Filter")}, module="vehicles")
def _veh_brands(api, a):
    return [{k: b.get(k) for k in ("id", "name", "name_en", "slug", "models", "trims")} for b in api.get("/api/vehicles/brands", q=a.get("q"))]


@tool("describe_compatibility", "Validate/normalize a compatibility value and describe it in Persian (paths of the selected vehicles).",
      {"value": p(O, COMPAT_DESC)}, ["value"], module="vehicles")
def _veh_desc(api, a):
    return api.post("/api/vehicles/normalize", {"value": a["value"]})


@tool("suggest_compatibility", "Suggest vehicle compatibility for a clean product (or any text) from the vehicles bank. ai=true uses the studio's AI; "
      "otherwise a fast name matcher. Returns a value + confidence; review before saving with update_product(compat=...).",
      {"product_id": p(I, "Clean product id"), "text": p(S, "Free text instead of a product"), "ai": p(B, "Use the studio's AI")}, module="vehicles")
def _veh_suggest(api, a):
    if a.get("product_id"):
        return api.post(f"/api/wb/products/{a['product_id']}/compat-suggest", {"ai": bool(a.get("ai"))})
    if not a.get("text"):
        raise ToolError("product_id یا text لازم است.")
    return api.post("/api/vehicles/suggest", {"text": a["text"], "ai": bool(a.get("ai"))})


@tool("save_vehicle", "Add (no id) or edit a vehicle in the bank. level: brand | model | trim. Fields: name, name_en, slug, brand_id (model), "
      "model_id (trim). English names/slugs are used in catalog exports.",
      {"level": p(S, "brand | model | trim", enum=["brand", "model", "trim"]), "id": p(I, "Id to update"), "name": p(S, "Persian name"),
       "name_en": p(S, "English name"), "slug": p(S, "Slug"), "brand_id": p(I, "For models"), "model_id": p(I, "For trims")},
      ["level"], write=True, module="vehicles")
def _veh_save(api, a):
    body = _clean(a, "level", "id")
    return api.put(f"/api/vehicles/{a['level']}/{a['id']}", body) if a.get("id") else api.post(f"/api/vehicles/{a['level']}", body)


# ---------------------------------------------------------------------------
# ویرایشگر داده‌ها: بانک‌های تمیز
# ---------------------------------------------------------------------------

@tool("list_banks", "Clean data banks (data editor): each is built from raw datasets with a schema; shows status counts, average quality and "
      "what is missing (brand/category/images).")
def _banks(api, a):
    return [{k: b.get(k) for k in ("id", "title", "status", "schema", "datasets", "counts", "quality_avg", "missing", "progress", "error")}
            for b in api.get("/api/wb/banks")]


@tool("get_bank", "One clean bank with its schema columns (key, label, input, core role).", {"bank_id": p(I, "Bank id")}, ["bank_id"])
def _bank(api, a):
    b = api.get(f"/api/wb/banks/{a['bank_id']}")
    b["columns"] = [{k: c.get(k) for k in ("key", "label", "input", "kind", "required", "role") if c.get(k) not in (None, "", False)} for c in b.get("columns") or []]
    return b


@tool("create_bank", "Create a clean bank from raw datasets (copies their products, downloads images, removes backgrounds, aligns, links brands/"
      "categories, suggests vehicle compatibility). Runs in the background — follow with get_bank.",
      {"dataset_ids": p(IDS, "Raw dataset ids"), "title": p(S, "Title"), "schema_id": p(I, "Schema (default: the dataset's)"),
       "rembg": p(B, "Remove backgrounds (default true)"), "align": p(B, "Align images (default true)"),
       "max_images": p(I, "Max images per product (default 10)"), "compat_suggest": p(B, "Suggest compatibility (default true)")},
      ["dataset_ids"], write=True)
def _bank_create(api, a):
    return api.post("/api/wb/banks", _clean(a))


@tool("add_datasets_to_bank", "Import more raw datasets into an existing clean bank (already-imported products are skipped).",
      {"bank_id": p(I, "Bank id"), "dataset_ids": p(IDS, "Dataset ids")}, ["bank_id", "dataset_ids"], write=True)
def _bank_add(api, a):
    return api.post(f"/api/wb/banks/{a['bank_id']}/add-datasets", {"dataset_ids": a["dataset_ids"]})


@tool("bank_from_legacy_export", "Convert a v1 export (create_export / list_exports) into a clean bank, keeping its edited values and images.",
      {"export_id": p(I, "v1 export id"), "title": p(S, "Title")}, ["export_id"], write=True)
def _bank_legacy(api, a):
    return api.post(f"/api/wb/from-legacy/{a['export_id']}", {"title": a.get("title") or ""})


# ---------------------------------------------------------------------------
# محصولات تمیز
# ---------------------------------------------------------------------------

PRODUCT_FILTER = {"bank_id": p(I, "Bank id"), "status": p(S, "Comma-separated: " + ", ".join(STATUSES)), "q": p(S, "Search title/slug/uid"),
                  "filter": p(S, "noimage | nobrand | nocategory | compat_all | compat_auto | warn | edited | lowq"),
                  "brand_id": p(I, "Reference brand"), "category_id": p(I, "Reference category")}


@tool("list_products", "Clean products (compact): id, uid, title, slug, brand/category slug (or '? raw' when unlinked), status, quality, "
      "compatibility text, image count. Use filters to find work (e.g. filter=nobrand, status=review).",
      {**PRODUCT_FILTER, "page": p(I, "Page"), "size": p(I, "Page size (≤200)")})
def _products(api, a):
    r = api.get("/api/wb/products", **{**_clean(a), "size": min(200, a.get("size") or 50)})
    return {"total": r["total"], "page": r["page"], "rows": [_compact_product(x) for x in r["rows"]]}


@tool("get_product", "Everything about one clean product: all schema values (v), brand/category, compatibility (+ auto suggestion), images "
      "(with edit recipes), quality errors/warnings, sources, revision number.", {"product_id": p(I, "Product id")}, ["product_id"])
def _product(api, a):
    r = api.get(f"/api/wb/products/{a['product_id']}")
    for im in r.get("images") or []:
        for k in ("final_url", "base_url", "raw_url"):
            im.pop(k, None)
    return r


@tool("get_product_images", "Look at a clean product's final images (after background removal, edits and alignment).",
      {"product_id": p(I, "Product id"), "max": p(I, "Max images (default 4)"), "side": p(I, "Thumbnail size px (default 640)")}, ["product_id"])
def _product_images(api, a):
    from PIL import Image
    r = api.get(f"/api/wb/products/{a['product_id']}")
    pics, meta = [], []
    for im in (r.get("images") or [])[: int(a.get("max") or 4)]:
        meta.append({k: im.get(k) for k in ("id", "origin", "w", "h", "edited", "error") if im.get(k) not in (None, "")})
        url = im.get("final_url") or im.get("base_url")
        if not url:
            continue
        try:
            resp = api.s.get(api.base + url, timeout=30)
            img = Image.open(io.BytesIO(resp.content))
            img.thumbnail((int(a.get("side") or 640),) * 2)
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, "PNG")
            pics.append((base64.b64encode(buf.getvalue()).decode(), "image/png"))
        except Exception:  # noqa: BLE001
            continue
    return Images(meta, pics)


@tool("update_product", "Edit a clean product (every change is a new revision; reversible). Pass only what changes: title, slug, values "
      "{column_key: value} (shape follows the column input), brand_id / category_id (reference ids, or null), compat (" + COMPAT_DESC + "), "
      "status (draft | review | approved | rejected; approve is blocked by quality errors unless force), note.",
      {"product_id": p(I, "Product id"), "title": p(S, "Title"), "slug": p(S, "Slug"), "values": p(O, "{column_key: value}"),
       "brand_id": {"type": ["integer", "null"], "description": "Reference brand id"}, "category_id": {"type": ["integer", "null"], "description": "Reference category id"},
       "compat": p(O, "Compatibility value"), "status": p(S, "Status", enum=STATUSES[:4]), "note": p(S, "Internal note"),
       "force": p(B, "Approve despite quality errors")}, ["product_id"], write=True)
def _product_update(api, a):
    body = {k: v for k, v in a.items() if k != "product_id" and (v is not None or k in ("brand_id", "category_id"))}
    return _compact_product(api.put(f"/api/wb/products/{a['product_id']}", body))


@tool("bulk_update_products", "Change many clean products at once (ids, or every product matching the filter). Operations can be combined: "
      "set {key: value}; find_replace {key, find, replace, regex}; prepend / append {key: text}; apply_default [keys] (schema defaults); "
      "brand / category (reference id or null); compat {mode: set|add|remove, value}; status; note. Each product gets a revision.",
      {"ids": p(IDS, "Product ids"), "filter": p(O, "Instead of ids: {bank_id, status, q, filter, brand_id, category_id}"),
       "bank_id": p(I, "Bank id (with filter)"), "set": p(O, "{key: value}"), "find_replace": p(O, "{key, find, replace, regex}"),
       "prepend": p(O, "{key: text}"), "append": p(O, "{key: text}"), "apply_default": p(ARR, "Column keys", items=S),
       "brand": {"type": ["integer", "null"]}, "category": {"type": ["integer", "null"]}, "compat": p(O, "{mode, value}"),
       "status": p(S, "Status", enum=STATUSES[:4]), "note": p(S, "Note")}, write=True)
def _bulk(api, a):
    if not a.get("ids") and not a.get("filter"):
        raise ToolError("ids یا filter لازم است.")
    return api.post("/api/wb/products/bulk", {k: v for k, v in a.items() if v is not None or k in ("brand", "category")})


@tool("product_image_action", "Change a clean product's images (non-destructive; every change is a revision). action: url (add from url), upload "
      "(data_url base64), generate (studio AI image; prompt), delete, make_feature, move (to index), edit (recipe: rotate, flip_h, flip_v, "
      "crop {x,y,w,h}, adjust {hue, saturation, brightness, contrast}, bg, erase strokes), reset_edit, rembg (on=true/false), reprocess.",
      {"product_id": p(I, "Product id"), "action": p(S, "Action", enum=["url", "upload", "generate", "delete", "make_feature", "move", "edit",
                                                                        "reset_edit", "rembg", "reprocess"]),
       "image_id": p(I, "Image id (from get_product)"), "url": p(S, "Image URL"), "data_url": p(S, "data:image/...;base64,..."),
       "prompt": p(S, "Prompt for generate"), "to": p(I, "Target index for move"), "recipe": p(O, "Edit recipe"), "on": p(B, "For rembg")},
      ["product_id", "action"], write=True)
def _img(api, a):
    r = api.post(f"/api/wb/products/{a['product_id']}/images/{a['action']}", _clean(a, "product_id", "action"))
    return {"images": [{k: im.get(k) for k in ("id", "origin", "w", "h", "edited", "use_rembg", "error")} for im in (r.get("images") or [])],
            "quality": r.get("quality"), "rev": r.get("rev")}


@tool("product_ai", "Fill/rewrite columns of one clean product with the studio's AI (saved as a revision with actor ai).",
      {"product_id": p(I, "Product id"), "columns": p(ARR, "[{key, mode: fill|rewrite|improve, instruction}] or column keys"),
       "provider_id": p(I, "AI connection"), "model": p(S, "Model")}, ["product_id", "columns"], write=True, module="ai")
def _pai(api, a):
    cols = [c if isinstance(c, dict) else {"key": c} for c in a["columns"]]
    r = api.post(f"/api/wb/products/{a['product_id']}/ai", {**_clean(a, "product_id"), "columns": cols})
    if not r.get("ok"):
        raise ToolError(r.get("error") or "تولید ناموفق بود.")
    return {"generated": r.get("generated"), "product": _compact_product(r["product"])}


@tool("bank_ai", "Background AI job over a clean bank (all products, ids, or a filter) for chosen columns. Follow with list_ai_jobs / wait_for(ai_job).",
      {"bank_id": p(I, "Bank id"), "columns": p(ARR, "[{key, mode, instruction}] or keys"), "ids": p(IDS, "Only these products"),
       "filter": p(O, "{status, filter, q}"), "profile_id": p(I, "AI profile"), "provider_id": p(I, "AI connection")},
      ["bank_id", "columns"], write=True, module="ai")
def _bai(api, a):
    cols = [c if isinstance(c, dict) else {"key": c} for c in a["columns"]]
    r = api.post(f"/api/wb/banks/{a['bank_id']}/ai", {**_clean(a, "bank_id"), "columns": cols})
    return {k: r.get(k) for k in ("id", "status", "progress_total", "step")}


@tool("product_raw_sources", "Raw (version 0) scraped data behind a clean product, to compare with the cleaned values.",
      {"product_id": p(I, "Product id")}, ["product_id"])
def _psrc(api, a):
    return api.get(f"/api/wb/products/{a['product_id']}/sources")


# ---------------------------------------------------------------------------
# کیفیت و تکراری‌ها
# ---------------------------------------------------------------------------

@tool("product_quality", "Quality score (0-100), errors (block approval/publishing) and warnings of a clean product.",
      {"product_id": p(I, "Product id")}, ["product_id"], module="quality")
def _q(api, a):
    return api.get(f"/api/quality/products/{a['product_id']}")


@tool("find_duplicates", "Scan a clean bank (or all) for likely duplicate products and list open pairs with score and reasons.",
      {"bank_id": p(I, "Bank id"), "threshold": p(I, "Min similarity 50-100 (default 75)"), "rescan": p(B, "Scan again first (default true)")},
      module="dedup")
def _dupes(api, a):
    if a.get("rescan", True):
        api.post("/api/dupes/scan", {"bank_id": a.get("bank_id"), "threshold": a.get("threshold") or 75})
    pairs = api.get("/api/dupes", bank_id=a.get("bank_id"))
    return [{"pair_id": x["id"], "score": x["score"], "reasons": x.get("reasons"),
             "a": {k: (x.get("a") or {}).get(k) for k in ("id", "title", "status")}, "b": {k: (x.get("b") or {}).get(k) for k in ("id", "title", "status")}}
            for x in pairs]


@tool("merge_duplicates", "Merge two duplicate products: primary stays, secondary becomes 'merged' (its sources/images join the primary). "
      "choose {field: 'b'} takes that field from the secondary.",
      {"primary_id": p(I, "Product to keep"), "secondary_id": p(I, "Product to merge in"), "choose": p(O, "{title|slug|brand|category|compat|<key>: 'b'}")},
      ["primary_id", "secondary_id"], write=True, module="dedup")
def _merge(api, a):
    return _compact_product(api.post("/api/dupes/merge", _clean(a)))


@tool("dismiss_duplicate", "Mark a duplicate pair as not duplicate.", {"pair_id": p(I, "Pair id")}, ["pair_id"], write=True, module="dedup")
def _dismiss(api, a):
    return api.post(f"/api/dupes/{a['pair_id']}/dismiss")


# ---------------------------------------------------------------------------
# ریویژن‌ها
# ---------------------------------------------------------------------------

ENTITIES = ["product", "schema", "template", "catalog", "ref_brand", "ref_category", "vehicle_brand", "vehicle_model", "vehicle_trim"]


@tool("list_revisions", "Version history of an entity (newest first): rev, time, actor (ui/ai/mcp/api/system), action and changed fields. "
      "Without entity_id: latest revisions across the studio.",
      {"entity": p(S, "Entity", enum=ENTITIES), "entity_id": p(I, "Id"), "page": p(I, "Page (recent mode)")})
def _revs(api, a):
    return api.get("/api/revisions", **_clean(a))


@tool("compare_revisions", "Field-by-field diff between two revisions of an entity (b defaults to the current one).",
      {"entity": p(S, "Entity", enum=ENTITIES), "entity_id": p(I, "Id"), "a": p(I, "Older rev"), "b": p(I, "Newer rev")}, ["entity", "entity_id", "a"])
def _rcmp(api, a):
    b = a.get("b")
    if not b:
        revs = api.get("/api/revisions", entity=a["entity"], entity_id=a["entity_id"])
        b = max(r["rev"] for r in revs) if revs else a["a"]
    return api.get("/api/revisions/compare", entity=a["entity"], entity_id=a["entity_id"], a=a["a"], b=b)


@tool("restore_revision", "Restore an entity to an earlier revision (creates a new revision; nothing is lost).",
      {"entity": p(S, "Entity", enum=ENTITIES), "entity_id": p(I, "Id"), "rev": p(I, "Revision to restore")}, ["entity", "entity_id", "rev"], write=True)
def _rrest(api, a):
    return api.post("/api/revisions/restore", a)


# ---------------------------------------------------------------------------
# الگوهای خروجی، کاتالوگ‌ها و انتشارها
# ---------------------------------------------------------------------------

@tool("list_output_templates", "File-tree templates for product catalogs: which files (products/brands/categories/vehicles/compatibility as "
      "json/xlsx/csv, each with its own schema) and where images go.")
def _tpls(api, a):
    return api.get("/api/cat/templates")


@tool("get_output_template", "Full template config and its file-tree preview.", {"template_id": p(I, "Template id")}, ["template_id"])
def _tpl(api, a):
    t = api.get(f"/api/cat/templates/{a['template_id']}")
    t["tree"] = api.post("/api/cat/templates/preview", {"config": t.get("config") or {}}).get("tree")
    return t


@tool("save_output_template", "Create (no template_id) or update a template. config = {root, zip, manifest, images: {enabled, path (tokens "
      "{slug} {uid} {name} {n} {ext} {brand} {category}), feature_name, gallery_name, which: all|feature, link: relative|prefix|source, prefix}, "
      "outputs: [{name, kind: products|brands|categories|vehicles|compatibility, format: json|xlsx|csv, schema_id (products), path (a product "
      "token like {slug} in a JSON path writes one file per product), fields, vehicle_format}]}. Use preview=true to only validate and see the tree.",
      {"template_id": p(I, "Template id"), "name": p(S, "Name"), "description": p(S, "Description"), "config": p(O, "Config"),
       "preview": p(B, "Only validate and preview")}, write=True)
def _tpl_save(api, a):
    if a.get("preview"):
        return api.post("/api/cat/templates/preview", {"config": a.get("config") or {}})
    body = _clean(a, "template_id", "preview")
    return api.put(f"/api/cat/templates/{a['template_id']}", body) if a.get("template_id") else api.post("/api/cat/templates", body)


@tool("list_product_catalogs", "Product catalogs (v2): each selects approved clean products and builds versioned releases with a template.")
def _cats(api, a):
    return api.get("/api/cat/catalogs")


@tool("save_product_catalog", "Create (no catalog_id) or update a product catalog. selection = {bank_ids, statuses (default [approved]), "
      "brand_ids, category_ids, include_ids, exclude_ids, require_ready (quality gate), min_quality}.",
      {"catalog_id": p(I, "Catalog id"), "title": p(S, "Title"), "slug": p(S, "Slug (folder name)"), "template_id": p(I, "Output template"),
       "description": p(S, "Description"), "selection": p(O, "Selection")}, write=True)
def _cat_save(api, a):
    body = _clean(a, "catalog_id")
    return api.put(f"/api/cat/catalogs/{a['catalog_id']}", body) if a.get("catalog_id") else api.post("/api/cat/catalogs", body)


@tool("preview_catalog_selection", "Which products a catalog would include now, and which are skipped with the reason (status, quality, …).",
      {"catalog_id": p(I, "Catalog id")}, ["catalog_id"])
def _cat_prev(api, a):
    return api.get(f"/api/cat/catalogs/{a['catalog_id']}/preview")


@tool("build_release", "Build a new immutable release of a catalog (files + images + manifest + zip) and a diff vs the previous release. "
      "wait=true blocks until done.", {"catalog_id": p(I, "Catalog id"), "note": p(S, "Release note"), "wait": p(B, "Wait for completion")},
      ["catalog_id"], write=True)
def _rel(api, a):
    return api.post(f"/api/cat/catalogs/{a['catalog_id']}/release", {"note": a.get("note") or "", "wait": bool(a.get("wait"))})


@tool("list_releases", "Releases of a catalog with status, file root, counts and diff summary.", {"catalog_id": p(I, "Catalog id")}, ["catalog_id"])
def _rels(api, a):
    return api.get(f"/api/cat/catalogs/{a['catalog_id']}/releases")


@tool("get_release", "One release: status, files, stats and diff (added/removed/changed products).", {"release_id": p(I, "Release id")}, ["release_id"])
def _rel_get(api, a):
    return api.get(f"/api/cat/releases/{a['release_id']}")


@tool("compare_releases", "Diff between two releases of the same catalog (products added, removed and changed fields).",
      {"a": p(I, "Older release id"), "b": p(I, "Newer release id")}, ["a", "b"])
def _rel_cmp(api, a):
    return api.get("/api/cat/releases/compare", a=a["a"], b=a["b"])


# ---------------------------------------------------------------------------
# پشتیبان
# ---------------------------------------------------------------------------

@tool("create_backup", "Back up the studio database (optionally with clean-bank images) into a zip.",
      {"note": p(S, "Note"), "with_images": p(B, "Include images")}, write=True)
def _bk(api, a):
    return api.post("/api/backups", _clean(a))


@tool("list_backups", "Existing backups.")
def _bks(api, a):
    return api.get("/api/backups")


# ---------------------------------------------------------------------------
# نسخه‌ی ۲.۱: برند/دسته (درخت، گروهی، خروجی)، ورود فایل و هوش مصنوعی
# ---------------------------------------------------------------------------

def _file_payload(a: dict) -> tuple[str, str]:
    """فایل ورودی ابزار: data_base64 (یا data: URL) یا path محلی."""
    if a.get("path"):
        from pathlib import Path
        pth = Path(a["path"]).expanduser()
        if not pth.exists():
            raise ToolError(f"فایل پیدا نشد: {pth}")
        return "data:application/octet-stream;base64," + base64.b64encode(pth.read_bytes()).decode(), a.get("name") or pth.name
    if not a.get("data_base64"):
        raise ToolError("data_base64 یا path لازم است.")
    d = a["data_base64"]
    return (d if d.startswith("data:") else "data:application/octet-stream;base64," + d), a.get("name") or "upload.xlsx"


FILE_PROPS = {"data_base64": p(S, "File content as base64 (or a data: URL)"), "path": p(S, "Local file path instead of data_base64"),
              "name": p(S, "File name with extension: .xlsx, .csv or .json")}


@tool("import_format", "Import format of a section: columns (English header key, accepted Persian header, required, description, example) and "
      "example rows. kind: brand | category | vehicles | raw (raw product data). Persian or English headers are both accepted.",
      {"kind": p(S, "Section", enum=["brand", "category", "vehicles", "raw"])}, ["kind"])
def _imp_fmt(api, a):
    return api.get("/api/import/specs")[a["kind"]]


@tool("category_tree", "The reference category tree (nested nodes with slug, path, product and brand counts).", {"q": p(S, "Filter")})
def _cat_tree(api, a):
    def slim(n):
        return {"id": n["id"], "name": n["name"], "slug": n["slug"], "products": n.get("products_total"), "brands": n.get("brands"),
                "active": n.get("active"), "nodes": [slim(x) for x in n.get("nodes") or []]}
    return [slim(n) for n in api.get("/api/ref/category/tree", q=a.get("q"))]


@tool("bulk_reference", "Bulk action on brands/categories (each change is a revision). action: delete | activate | deactivate | add_aliases (value: "
      "comma text) | set_parent (categories; value: parent id or null) | add_categories / remove_categories / set_categories (brands; value: "
      "category ids) | set_country (brands).",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "ids": p(IDS, "Ids"), "action": p(S, "Action"),
       "value": {"description": "Action value (id, list of ids or text)"}}, ["kind", "ids", "action"], write=True)
def _ref_bulk(api, a):
    return api.post(f"/api/ref/{a['kind']}/bulk", {"ids": a["ids"], "action": a["action"], "value": a.get("value")})


@tool("export_reference", "Export brands or categories as rows (same columns as the import format; brands include category slugs).",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "ids": p(IDS, "Only these ids")}, ["kind"])
def _ref_export(api, a):
    return api.get(f"/api/ref/{a['kind']}/export", format="json", ids=",".join(map(str, a.get("ids") or [])))


@tool("brands_in_category", "Brands that are shown in a category (linked to it, its parents or its sub-categories; inherit=false: only directly linked).",
      {"category_id": p(I, "Category id"), "inherit": p(B, "Include parents/children (default true)")}, ["category_id"])
def _brands_in(api, a):
    rows = api.get("/api/ref/brand", category_id=a["category_id"], inherit="1" if a.get("inherit", True) else "0")
    return [{k: r.get(k) for k in ("id", "name", "name_en", "slug")} for r in rows]


@tool("import_reference_file", "Import brands or categories from an xlsx/csv/json file (see import_format). Existing items (same slug or name) are updated.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), **FILE_PROPS, "mapping": p(O, "Optional {file header: column key}")},
      ["kind"], write=True)
def _ref_import_file(api, a):
    data_url, name = _file_payload(a)
    return api.post(f"/api/ref/{a['kind']}/import", {"data_url": data_url, "name": name, "mapping": a.get("mapping")})


@tool("import_dataset_file", "Create a RAW dataset from a product file (xlsx/csv/json; see import_format kind=raw). Only title is required; unknown "
      "columns are kept in raw data. Use analyze=true first to see detected headers and the suggested mapping; pass mapping {header: key} to fix it. "
      "Afterwards build a clean bank with create_bank(dataset_ids=[id]).",
      {**FILE_PROPS, "title": p(S, "Dataset title"), "schema_id": p(I, "Schema (default: default schema)"), "category_label": p(S, "Category label"),
       "mapping": p(O, "{file header: field key}"), "analyze": p(B, "Only analyze the file")}, write=True)
def _ds_import_file(api, a):
    data_url, name = _file_payload(a)
    if a.get("analyze"):
        return api.post("/api/import/analyze", {"kind": "raw", "data_url": data_url, "name": name})
    r = api.post("/api/datasets/import-file", {"data_url": data_url, "name": name, "title": a.get("title"), "schema_id": a.get("schema_id"),
                                               "category_label": a.get("category_label"), "mapping": a.get("mapping")})
    return {k: r.get(k) for k in ("id", "code", "title", "status", "counts", "schema_id")}


@tool("ai_complete_reference", "Studio AI proposes missing fields for brands/categories (name_en, slug, aliases, description, categories for brands, "
      "parent for categories, country). Returns proposals only — review, then save with apply_reference.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "ids": p(IDS, "Ids (default: all)"),
       "fields": p(ARR, "Fields to propose", items=S), "only_empty": p(B, "Only fill empty fields (default true)")}, ["kind"], module="ai")
def _ai_ref_complete(api, a):
    return api.post(f"/api/ref/{a['kind']}/ai-complete", _clean(a, "kind"))


@tool("ai_match_reference", "Studio AI maps raw brand/category names that matched nothing (unmatched_reference) to existing items or proposes new ones.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "names": p(ARR, "Raw names (default: all unmatched)", items=S)}, ["kind"], module="ai")
def _ai_ref_match(api, a):
    return api.post(f"/api/ref/{a['kind']}/ai-match", _clean(a, "kind"))


@tool("ai_generate_reference", "Studio AI proposes a brand list (with categories) or a category tree from a description. Proposals only.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "prompt": p(S, "What is needed"), "parent_id": p(I, "Parent category (category tree)"),
       "count": p(I, "Max items")}, ["kind", "prompt"], module="ai")
def _ai_ref_gen(api, a):
    return api.post(f"/api/ref/{a['kind']}/ai-generate", _clean(a, "kind"))


@tool("apply_reference", "Save several brands/categories at once (e.g. approved AI proposals). Items with id are updated, without id created. "
      "Brands may use categories (slugs) or category_ids; categories may use parent (slug) or parent_id.",
      {"kind": p(S, "brand | category", enum=["brand", "category"]), "items": p(ARR, "Items", items=O)}, ["kind", "items"], write=True)
def _ref_apply(api, a):
    return api.post(f"/api/ref/{a['kind']}/apply", {"items": a["items"]})


@tool("ai_design_template", "Studio AI designs an output template (file tree) from a description; returns config + tree preview + validation. "
      "Save it with save_output_template(config=...).", {"prompt": p(S, "Desired output structure")}, ["prompt"], module="ai")
def _ai_tpl(api, a):
    return api.post("/api/cat/templates/ai", {"prompt": a["prompt"]})


@tool("ai_check_duplicate", "Studio AI judges whether a duplicate pair (find_duplicates) is really the same product, with a reason and which to keep.",
      {"pair_id": p(I, "Pair id")}, ["pair_id"], module="ai")
def _ai_dupe(api, a):
    return api.post(f"/api/dupes/{a['pair_id']}/ai", {})
