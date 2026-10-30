"""هسته‌ی سرور MCP استودیو: پروتکل JSON-RPC، ابزارها، منابع و پرامپت‌ها.

این ماژول فقط از طریق HTTP API با استودیو حرف می‌زند؛ پس هم در فرایند stdio (برای Claude Desktop و …)
و هم داخل خود استودیو (نشانی /mcp) قابل استفاده است.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

SERVER_NAME = "mega-catalog-studio"
SERVER_VERSION = "1.6.1"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MAX_TEXT = 90_000

INSTRUCTIONS = """Mega Catalog Studio (استودیو کاتالوگ مگا) — a local product-catalog studio for the Iranian automotive marketplace "Mega Cars".

Data model: sources (scraper configs) → datasets (one scrape run of a category URL, a.k.a. «بانک داده») → items (products).
Each dataset uses a schema whose columns are the export fields (title, slug, category_slug, brand_slug, short_description,
long_description, vendor_notes, user_dos_donts_description {dos, donts, pre_post_purchase}, vendor_dos_donts_description
{dos, donts, shipping_returns}, dimensions {item_/packaging_ weight(g), width/length/height(cm)}, dimension_codes,
specifications, featured_images, images_gallery, source_url).
Value precedence for a column: user manual edit > manual input > AI/agent value > scraped value (after text rules).

Typical workflows:
- Complete missing data: find_gaps(dataset_id) → get_item(item_id) (+ get_item_images to look at the product) →
  set_item_fields(item_id, values) with mode "ai" (reversible). Never invent technical specs, standards or numbers that are
  not in the scraped data; when unsure leave a field empty.
- Unique SEO copy: either write it yourself via set_item_fields, or use the studio's own AI (run_ai_generation with a profile).
- Product images: get_item_images to inspect, generate_item_image to create one with the configured image model,
  or attach_item_image to add an image you have (base64/URL/path).
- Scraping: start_extraction(category_url, limit) then wait_for(kind="dataset", id). If status becomes "waiting", call
  list_incidents and resolve_incident.
- Export: create_export(dataset_ids, formats=["xlsx","csv","json"], format_schemas={"json": <schema_id>}) then wait_for(kind="export", id).
  Each file format may use its own schema; JSON is one top-level array of structured product objects.
- Repeated text (e.g. the same dos/donts or pre/post-purchase lines for every product, a fixed category slug) belongs in the schema
  column's default (+ default_mode) via save_schema, not in every product; bulk_edit_catalog(apply_default=[key]) applies it to built catalogs.
- FINAL catalogs (the source for building products on Mega Cars) are managed in the studio after export: list_catalogs →
  get_catalog → get_catalog_rows. Edit any field of any row with update_catalog_row or bulk_edit_catalog (set / find_replace /
  prepend / append / exclude), images with catalog_image_action (upload, url, generate, delete, make_feature, move, reprocess),
  or with the studio's AI via catalog_ai. Every change is stored in history (get_history / revert_history). After editing call
  rebuild_catalog_files so xlsx/csv/json/zip match the edits; sync_catalog_to_datasets copies edits back to the datasets.
- Audit: get_activity (every request from the UI, agents and API), get_ai_calls (every AI request with tokens/errors), get_history.
- Image alignment: preview_image_alignment(path, margin) to check, then align_images(path, margin) — trims empty space around
  each product and fits it on a 1280×1280 canvas with the same margin, so all products look equally sized.
- AI-only catalog (no scraping): generate_dataset_with_ai(product_type, count, category_label?, brands?, images?) then
  wait_for(kind="dataset", id). The studio plans unique products and fills every schema column (+ images). Add more with
  ai_add_products; regenerate one product with regenerate_ai_item.
- One column for many products with the studio's AI: ai_generate_column(dataset_id, column, mode, instruction).
- Any set of columns with the studio's AI: get_ai_columns(dataset_id) then run_ai_generation(dataset_id, columns=[...]) — or
  use_schema / all_empty. start_extraction(ai_after=...) generates automatically after scraping; create_export(ai_fill=...) fills
  empty columns right before export. Scraper fields can use the strategy {"type":"ai","mode":"extract"} and sources can enable
  product.ai_fallback to extract still-empty fields from the page text with AI.
- Studio AI assistant for anything else: ai_assist(task, payload) — task "text" (any value), "field" (one product column),
  "schema" (design a schema), "column" (design one column), "mappings" (brand/category slugs), "rules" (text-cleanup rules),
  "source_fields" (scraper strategies from a live-test explorer).
Content language is Persian. Call every shop/garage «کسب‌وکار» and never use the word «شعبه». Do not mention prices or competitor stores.
"""


class ToolError(Exception):
    pass


# ---------------------------------------------------------------------------
# کلاینت API استودیو
# ---------------------------------------------------------------------------

class StudioAPI:
    def __init__(self, base: str | None = None, autostart: bool = False):
        self.base = (base or os.environ.get("CATALOG_STUDIO_URL") or f"http://127.0.0.1:{os.environ.get('CATALOG_STUDIO_PORT', '8765')}").rstrip("/")
        self.s = requests.Session()
        self.s.trust_env = False  # اتصال محلی؛ پراکسی سیستم دخالت نکند
        self.s.headers["X-Studio-Client"] = "mcp"
        self.autostart = autostart
        self._checked = False

    def ensure(self):
        if self._checked:
            return
        try:
            self.s.get(self.base + "/api/settings", timeout=3)
            self._checked = True
            return
        except requests.RequestException:
            if not self.autostart:
                raise ToolError(f"استودیو در {self.base} در دسترس نیست. ابتدا run.bat را اجرا کنید.")
        root = Path(__file__).resolve().parent.parent
        env = {**os.environ, "CATALOG_STUDIO_NO_BROWSER": "1", "PYTHONUTF8": "1"}
        kw: dict = {"cwd": str(root), "env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "studio"], **kw)
        for _ in range(60):
            time.sleep(0.5)
            try:
                self.s.get(self.base + "/api/settings", timeout=2)
                self._checked = True
                return
            except requests.RequestException:
                continue
        raise ToolError("استودیو به‌طور خودکار اجرا نشد؛ run.bat را دستی اجرا کنید.")

    def call(self, method: str, path: str, body: Any = None, params: dict | None = None, timeout: int = 600):
        self.ensure()
        try:
            r = self.s.request(method, self.base + path, json=body, params=params, timeout=timeout)
        except requests.RequestException as exc:
            self._checked = False
            raise ToolError(f"ارتباط با استودیو ممکن نشد: {exc}") from exc
        try:
            data = r.json()
        except ValueError:
            data = {"error": r.text[:500]}
        if r.status_code >= 400:
            raise ToolError((data or {}).get("error") if isinstance(data, dict) else str(data))
        return data

    def get(self, path, **params):
        return self.call("GET", path, params={k: v for k, v in params.items() if v not in (None, "")})

    def post(self, path, body=None):
        return self.call("POST", path, body if body is not None else {})

    def put(self, path, body):
        return self.call("PUT", path, body)

    def delete(self, path):
        return self.call("DELETE", path)


# ---------------------------------------------------------------------------
# ثبت ابزارها
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict] = {}


def tool(name: str, description: str, props: dict | None = None, required: list | None = None,
         write: bool = False, destructive: bool = False, title: str = ""):
    def deco(fn: Callable):
        TOOLS[name] = {
            "fn": fn, "write": write or destructive,
            "spec": {
                "name": name, "title": title or name.replace("_", " ").title(), "description": description,
                "inputSchema": {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False},
                "annotations": {"readOnlyHint": not (write or destructive), "destructiveHint": destructive,
                                "idempotentHint": not (write or destructive), "openWorldHint": False},
            },
        }
        return fn
    return deco


I = {"type": "integer"}
S = {"type": "string"}
B = {"type": "boolean"}
O = {"type": "object"}
IDS = {"type": "array", "items": {"type": "integer"}}


def p(t: dict, d: str, **extra) -> dict:
    return {**t, "description": d, **extra}


class Images:
    """نتیجه‌ی ابزار همراه با تصویر"""

    def __init__(self, text: Any, images: list[tuple[str, str]]):
        self.text, self.images = text, images


def _compact_ds(d: dict) -> dict:
    if not d:
        return d
    return {k: d.get(k) for k in ("id", "code", "name", "title", "status", "step", "category_url", "category_label", "item_limit",
                                  "total_found", "total_expected", "schema_id", "created_at", "finished_at")} | {
        "source": (d.get("source") or {}).get("key"), "counts": d.get("counts"), "progress": d.get("progress"),
        "open_incident": ({"id": d["open_incident"]["id"], "title": d["open_incident"]["title"], "message": d["open_incident"]["message"],
                           "options": [o["action"] for o in d["open_incident"].get("options", [])]} if d.get("open_incident") else None)}


# ----- نمای کلی و تنظیمات --------------------------------------------------

@tool("studio_overview", "Overview of the studio: counts, recent/active datasets, open incidents that need a decision, queue and AI-job state. Start here.")
def _overview(api, a):
    s = api.get("/api/summary")
    return {"counts": s["counts"], "queue": s.get("queue"), "ai_jobs_running": s.get("ai_running"),
            "datasets": [_compact_ds(d) for d in s["active"]],
            "open_incidents": [{"id": i["id"], "dataset_id": i["dataset_id"], "title": i["title"], "message": i["message"],
                                "options": [o["action"] for o in i["options"]]} for i in s["incidents"]],
            "recent_exports": [{"id": e["id"], "name": e["name"], "status": e["status"]} for e in s["recent_exports"]]}


@tool("get_settings", "Read studio settings (output folder, browser, delays, retries, image size, rembg model, slug dictionary, queue/MCP flags).")
def _get_settings(api, a):
    return api.get("/api/settings")


@tool("update_settings", "Update studio settings. Pass only the keys to change, e.g. {\"output_root\": \"D:\\\\Catalog\", \"delay_min_ms\": 1200}.",
      {"values": p(O, "Settings keys and new values")}, ["values"], write=True)
def _upd_settings(api, a):
    return api.put("/api/settings", a["values"])


# ----- منابع -----------------------------------------------------------------

@tool("list_sources", "List scraper sources (Digikala, Snappshop, …) with mode, domains and counts.")
def _list_sources(api, a):
    return [{"id": s["id"], "key": s["key"], "name": s["name"], "domains": s["config"].get("domains"), "listing_mode": s["config"].get("listing", {}).get("mode"),
             "product_mode": s["config"].get("product", {}).get("mode"), "datasets": s["datasets"], "products": s["products"]} for s in api.get("/api/sources")]


@tool("get_source", "Full scraper config of a source (listing/pagination, product page actions, field strategies and transforms).",
      {"source_id": p(I, "Source id")}, ["source_id"])
def _get_source(api, a):
    return api.get(f"/api/sources/{a['source_id']}")


@tool("detect_source", "Detect which source handles a URL (by domain).", {"url": p(S, "Category or product URL")}, ["url"])
def _detect(api, a):
    return api.get("/api/sources/detect", url=a["url"])


@tool("test_source", "Live-test a source on a sample URL. kind=listing tests product-link discovery on a category page; kind=product extracts one product "
      "and returns the record plus a data explorer (JSON-LD/Next.js/XHR paths) useful for fixing field strategies. Optional config tests unsaved changes.",
      {"source_id": p(I, "Source id"), "kind": p(S, "listing | product", enum=["listing", "product"]), "url": p(S, "Sample URL"),
       "config": p(O, "Optional full source config to test instead of the saved one"), "explorer_limit": p(I, "Max explorer leaves per group (default 60)")},
      ["source_id", "kind", "url"])
def _test_source(api, a):
    body = {"url": a["url"]}
    if a.get("config"):
        body["config"] = a["config"]
    if a["kind"] == "listing":
        return api.post(f"/api/sources/{a['source_id']}/test-listing", body)
    r = api.post(f"/api/sources/{a['source_id']}/test-product", body)
    r.pop("screenshot", None)
    lim = int(a.get("explorer_limit") or 60)
    ex = r.get("explorer")
    if ex:
        for g in ex.get("groups", []):
            g["leaves"] = g["leaves"][:lim]
        ex["auto_specs"] = ex.get("auto_specs", [])[:40]
    return r


@tool("create_source", "Create a new scraper source from a config object (same shape as get_source().config).",
      {"config": p(O, "Source config: key, name, domains, product_id_pattern, listing, product, fields, request")}, ["config"], write=True)
def _create_source(api, a):
    return api.post("/api/sources", {"config": a["config"]})


@tool("update_source", "Replace a source's config (get it first with get_source, modify, then send the whole config).",
      {"source_id": p(I, "Source id"), "config": p(O, "Full new config")}, ["source_id", "config"], write=True)
def _update_source(api, a):
    return api.put(f"/api/sources/{a['source_id']}", {"config": a["config"]})


@tool("delete_source", "Delete a source (only allowed when it has no datasets).", {"source_id": p(I, "Source id")}, ["source_id"], destructive=True)
def _del_source(api, a):
    return api.delete(f"/api/sources/{a['source_id']}")


# ----- اسکیما ----------------------------------------------------------------

@tool("list_schemas", "List export schemas with their column keys and kinds (scraped/manual/constant/mapping/auto).")
def _list_schemas(api, a):
    return [{"id": s["id"], "name": s["name"], "is_default": bool(s["is_default"]),
             "columns": [{"key": c["key"], "label": c.get("label"), "kind": c.get("kind"), "input": c.get("input", "text")} for c in s["columns"]]}
            for s in api.get("/api/schemas")]


@tool("get_schema", "Full schema definition (all column settings).", {"schema_id": p(I, "Schema id")}, ["schema_id"])
def _get_schema(api, a):
    return api.get(f"/api/schemas/{a['schema_id']}")


@tool("save_schema", "Create (no schema_id) or update a schema. Columns: [{key, label, kind: scraped|manual|constant|mapping|auto, from, value, map, "
      "generator, input: text|longtext|bullets|bullet_groups|group|specs|image|images|json|bool|number, export, groups, subkeys, required, include, "
      "default, default_mode: fill|always|prepend|append, ai_mode, ai_instruction}]. default is a schema-wide value typed like the column "
      "(string for text, multi-line string for longtext, list of lines for bullets, {group_key: [lines]} for bullet_groups, {subkey: value} for group); "
      "fill = only when empty, always = fixed value, prepend/append = added to the scraped/AI value. Use get_schema first and send all columns back.",
      {"schema_id": p(I, "Existing schema id to update (omit to create)"), "name": p(S, "Schema name"), "description": p(S, "Description"),
       "columns": {"type": "array", "items": O, "description": "Column definitions in export order"}, "is_default": p(B, "Make default")},
      ["name", "columns"], write=True)
def _save_schema(api, a):
    body = {"name": a["name"], "description": a.get("description", ""), "columns": a["columns"], "is_default": a.get("is_default", False)}
    if a.get("schema_id"):
        return api.put(f"/api/schemas/{a['schema_id']}", body)
    return api.post("/api/schemas", body)


@tool("delete_schema", "Delete a schema.", {"schema_id": p(I, "Schema id")}, ["schema_id"], destructive=True)
def _del_schema(api, a):
    return api.delete(f"/api/schemas/{a['schema_id']}")


# ----- بانک داده و استخراج --------------------------------------------------

@tool("list_datasets", "List datasets (scrape runs) with status, counts and progress.", {"status": p(S, "Optional status filter, e.g. completed, running, waiting, paused")})
def _list_ds(api, a):
    rows = [_compact_ds(d) for d in api.get("/api/datasets")]
    return [d for d in rows if not a.get("status") or d["status"] == a["status"]]


@tool("get_dataset", "Dataset details: status, current step, counts, progress, open incident.", {"dataset_id": p(I, "Dataset id")}, ["dataset_id"])
def _get_ds(api, a):
    d = api.get(f"/api/datasets/{a['dataset_id']}")
    return _compact_ds(d) | {"options": d.get("options"), "policies": d.get("policies"), "cursor": d.get("cursor")}


@tool("start_extraction", "Create a dataset from a CATEGORY page URL and (by default) start scraping it. Source is auto-detected from the domain. "
      "limit omitted = all products. policies maps error kinds (network, timeout, blocked, http_error, not_found, missing_fields, parse_error, "
      "listing_error, unknown) to ask|retry|reload|continue_partial|skip|pause — use skip/continue_partial for unattended runs.",
      {"category_url": p(S, "Category page URL"), "limit": p(I, "Max products"), "source_id": p(I, "Force a source"), "schema_id": p(I, "Schema id"),
       "duplicates": p(S, "skip | reuse | rescrape", enum=["skip", "reuse", "rescrape"]), "category_label": p(S, "Category title override"),
       "policies": p(O, "Error policies"), "show_browser": p(B, "Show the browser window"), "start": p(B, "Start immediately (default true)"),
       "ai_after": p(O, 'After scraping, generate with AI automatically: {"mode": "schema"} (schema AI columns) | {"mode": "empty"} (every empty column) | '
                        '{"mode": "profile", "profile_id": N} | {"mode": "columns", "columns": [...]}; optional "scope": all|partial')},
      ["category_url"], write=True)
def _start_extraction(api, a):
    body = {k: v for k, v in a.items() if v is not None}
    body.setdefault("start", True)
    return _compact_ds(api.post("/api/datasets", body))


@tool("control_dataset", "Control a scrape run: start, resume (continue from the saved point), pause, stop, retry-failed (re-queue skipped items), "
      "rediscover (re-read the category listing).",
      {"dataset_id": p(I, "Dataset id"), "action": p(S, "Action", enum=["start", "resume", "pause", "stop", "retry-failed", "rediscover"])},
      ["dataset_id", "action"], write=True)
def _ctl_ds(api, a):
    return _compact_ds(api.post(f"/api/datasets/{a['dataset_id']}/do/{a['action']}"))


@tool("update_dataset", "Update dataset settings: title, name (export file name), category_label, item_limit (raise it and resume to scrape more), "
      "schema_id, policies, notes.",
      {"dataset_id": p(I, "Dataset id"), "title": p(S, "Display title"), "name": p(S, "File name"), "category_label": p(S, "Category label"),
       "item_limit": p(I, "Max products (0 = all)"), "schema_id": p(I, "Schema id"), "policies": p(O, "Error policies"), "notes": p(S, "Notes")},
      ["dataset_id"], write=True)
def _upd_ds(api, a):
    body = {k: v for k, v in a.items() if k != "dataset_id" and v is not None}
    return _compact_ds(api.put(f"/api/datasets/{a['dataset_id']}", body))


@tool("delete_dataset", "Delete a dataset with all its items and logs (exported files on disk are kept).", {"dataset_id": p(I, "Dataset id")},
      ["dataset_id"], destructive=True)
def _del_ds(api, a):
    return api.delete(f"/api/datasets/{a['dataset_id']}")


@tool("list_incidents", "Open errors waiting for a decision (the scrape is paused until resolved), with allowed actions.")
def _incidents(api, a):
    return [{"id": i["id"], "dataset_id": i["dataset_id"], "dataset": i.get("dataset_title"), "kind": i["kind"], "title": i["title"],
             "message": i["message"], "url": i["url"], "detail": (i.get("detail") or "")[:600], "options": [o["action"] for o in i["options"]]}
            for i in api.get("/api/incidents")]


@tool("resolve_incident", "Answer an error decision: retry, reload, continue_partial, skip, wait_network, show_browser or pause. apply_all=true "
      "applies the same decision automatically to similar errors for the rest of the run.",
      {"incident_id": p(I, "Incident id"), "action": p(S, "Decision"), "apply_all": p(B, "Apply to similar errors")}, ["incident_id", "action"], write=True)
def _resolve(api, a):
    return api.post(f"/api/incidents/{a['incident_id']}/resolve", {"action": a["action"], "apply_all": a.get("apply_all", False)})


@tool("get_logs", "Read event logs. scope: dataset | export | bg | ai | queue; ref_id: id in that scope; level: info|warning|error|success|debug.",
      {"scope": p(S, "Scope"), "ref_id": p(I, "Id"), "level": p(S, "Level"), "limit": p(I, "Max rows (default 80)")})
def _logs(api, a):
    rows = api.get("/api/logs", scope=a.get("scope"), ref_id=a.get("ref_id"), level=a.get("level"))
    return [{k: r[k] for k in ("ts", "level", "scope", "ref_id", "item_id", "message")} | ({"detail": r["detail"][:400]} if r.get("detail") else {})
            for r in rows[: int(a.get("limit") or 80)]]


@tool("wait_for", "Wait until a long task changes state: kind=dataset (until completed/paused/stopped/error/waiting), ai_job, export, bg_job. "
      "Returns current state on timeout (max 110 s per call; call again to keep waiting).",
      {"kind": p(S, "Task kind", enum=["dataset", "ai_job", "export", "bg_job"]), "id": p(I, "Task id"), "timeout_s": p(I, "Seconds (default 60, max 110)")},
      ["kind", "id"])
def _wait(api, a):
    end = time.time() + min(110, int(a.get("timeout_s") or 60))
    kind, i = a["kind"], a["id"]
    while True:
        if kind == "dataset":
            st = _compact_ds(api.get(f"/api/datasets/{i}"))
            done = st["status"] in ("completed", "paused", "stopped", "error", "waiting")
        elif kind == "ai_job":
            st = next((j for j in api.get("/api/ai/jobs") if j["id"] == i), None)
            if not st:
                raise ToolError("اجرای تولید پیدا نشد.")
            done = st["status"] in ("completed", "paused", "error")
        elif kind == "export":
            st = api.get(f"/api/exports/{i}")
            done = st["status"] in ("completed", "error", "cancelled")
            if done and st.get("result"):
                st["result"]["warnings"] = st["result"].get("warnings", [])[:20]
        else:
            st = next((j for j in api.get("/api/bg") if j["id"] == i), None)
            if not st:
                raise ToolError("کار حذف پس‌زمینه پیدا نشد.")
            done = st["status"] in ("completed", "paused", "error")
        if done or time.time() >= end:
            return {"finished": done, "state": st}
        time.sleep(2)


# ----- محصولات ----------------------------------------------------------------

@tool("list_items", "List products of a dataset (compact): id, status, title, brand, missing required fields, whether AI/agent values exist.",
      {"dataset_id": p(I, "Dataset id"), "status": p(S, "Comma list: done,partial,queued,skipped"), "search": p(S, "Text search"),
       "page": p(I, "Page (default 1)"), "size": p(I, "Page size (default 50, max 200)")}, ["dataset_id"])
def _list_items(api, a):
    r = api.get(f"/api/datasets/{a['dataset_id']}/items", status=a.get("status"), q=a.get("search"), page=a.get("page") or 1, size=a.get("size") or 50)
    return {"total": r["total"], "page": r["page"], "size": r["size"],
            "items": [{k: it[k] for k in ("id", "seq", "status", "title", "brand", "missing", "has_ai", "has_overrides", "specs_count", "gallery_count", "url")}
                      for it in r["items"]]}


@tool("get_item", "Everything about one product: every schema column with its current value and origin (scraped / ai_or_agent / manual_edit), "
      "the scraped data after text rules (title, brand, specifications, descriptions…), and which fields are empty.",
      {"item_id": p(I, "Item id"), "max_text": p(I, "Truncate long texts (default 4000)")}, ["item_id"])
def _get_item(api, a):
    return api.get(f"/api/items/{a['item_id']}/detail", max_text=a.get("max_text") or 4000)


@tool("find_gaps", "Find products with empty schema columns in a dataset (what still needs to be completed), with per-column counts.",
      {"dataset_id": p(I, "Dataset id"), "columns": {"type": "array", "items": S, "description": "Only check these column keys"},
       "limit": p(I, "Max items listed (default 200)")}, ["dataset_id"])
def _gaps(api, a):
    return api.get(f"/api/datasets/{a['dataset_id']}/gaps", columns=",".join(a.get("columns") or []), limit=a.get("limit") or 200)


@tool("set_item_fields", "Write values into schema columns of a product. values = {column_key: value}. Shapes: text → string; bullets → list of strings; "
      "bullet_groups (e.g. user_dos_donts_description) → {dos:[…], donts:[…], pre_post_purchase:[…]}; group (dimensions) → {item_weight:'500', …} "
      "(grams/cm, digits only); specs → [{group,name,value}]; images → list of URLs/paths. mode=ai (default): stored as reversible agent output, "
      "the user's manual edits still win; mode=override: acts like a manual edit. Pass null as a value to remove your earlier value.",
      {"item_id": p(I, "Item id"), "values": p(O, "Column values"), "mode": p(S, "ai | override", enum=["ai", "override"])},
      ["item_id", "values"], write=True)
def _set_fields(api, a):
    return api.post(f"/api/items/{a['item_id']}/fields", {"values": a["values"], "mode": a.get("mode", "ai"), "agent": "mcp-agent"})


@tool("bulk_set_fields", "Write the same column values into many products (item_ids, or every scraped product of dataset_id). Same rules as set_item_fields.",
      {"values": p(O, "Column values"), "item_ids": p(IDS, "Item ids"), "dataset_id": p(I, "All done/partial items of this dataset"),
       "mode": p(S, "ai | override", enum=["ai", "override"])}, ["values"], write=True)
def _bulk_fields(api, a):
    ids = list(a.get("item_ids") or [])
    if not ids and a.get("dataset_id"):
        page = 1
        while True:
            r = api.get(f"/api/datasets/{a['dataset_id']}/items", status="done,partial", page=page, size=200)
            ids += [i["id"] for i in r["items"]]
            if len(ids) >= r["total"] or not r["items"]:
                break
            page += 1
    if not ids:
        raise ToolError("item_ids یا dataset_id بدهید.")
    for i in ids[:2000]:
        api.post(f"/api/items/{i}/fields", {"values": a["values"], "mode": a.get("mode", "ai"), "agent": "mcp-agent"})
    return {"updated": len(ids[:2000])}


@tool("update_item_raw", "Low-level item update: overrides (manual edits by column), manual (manual-input columns), status (done|partial|skipped|queued), "
      "ai_clear (list of column keys whose AI/agent value should be removed).",
      {"item_id": p(I, "Item id"), "overrides": p(O, "Column overrides"), "manual": p(O, "Manual column values"),
       "status": p(S, "Status"), "ai_clear": {"type": "array", "items": S, "description": "Columns to clear"}}, ["item_id"], write=True)
def _raw(api, a):
    body = {k: v for k, v in a.items() if k != "item_id" and v is not None}
    r = api.put(f"/api/items/{a['item_id']}", body)
    return {"id": r["id"], "status": r["status"], "preview": {k: v["value"] for k, v in r["preview"].items()}}


@tool("clear_ai_output", "Remove AI/agent values (revert to scraped data) for item_ids or a whole dataset; keys limits it to some columns.",
      {"item_ids": p(IDS, "Item ids"), "dataset_id": p(I, "Dataset id"), "keys": {"type": "array", "items": S, "description": "Column keys"}},
      write=True)
def _clear_ai(api, a):
    return api.post("/api/items/ai-clear", {"ids": a.get("item_ids") or [], "dataset_id": a.get("dataset_id"), "keys": a.get("keys")})


@tool("rescrape_item", "Scrape one product again from its source page.", {"item_id": p(I, "Item id")}, ["item_id"], write=True)
def _rescrape(api, a):
    r = api.post(f"/api/items/{a['item_id']}/rescrape")
    return {"id": r["id"], "status": r["status"], "error": r.get("error"), "title": r["data"].get("title")}


@tool("delete_items", "Delete products from their dataset.", {"item_ids": p(IDS, "Item ids")}, ["item_ids"], destructive=True)
def _del_items(api, a):
    return api.post("/api/items/bulk", {"ids": a["item_ids"], "delete": True})


@tool("preview_export_rows", "Preview the first export rows (exact column values that will go into Excel/CSV) for a dataset.",
      {"dataset_id": p(I, "Dataset id"), "schema_id": p(I, "Schema (default: dataset's)")}, ["dataset_id"])
def _preview_rows(api, a):
    r = api.post(f"/api/datasets/{a['dataset_id']}/preview", {"schema_id": a.get("schema_id")})
    return {"headers": r["headers"], "rows": [[str(v)[:300] if v is not None else "" for v in row] for row in r["rows"][:10]],
            "warnings": r["warnings"][:30]}


# ----- تصاویر -----------------------------------------------------------------

@tool("get_item_images", "Show a product's current images (scraped and AI/agent ones) as images you can look at, e.g. to describe the product or check quality.",
      {"item_id": p(I, "Item id"), "max": p(I, "Max images (default 4)"), "side": p(I, "Thumbnail size px (default 768)")}, ["item_id"])
def _item_images(api, a):
    imgs = api.get(f"/api/items/{a['item_id']}/images", thumbs="1", max=a.get("max") or 4, side=a.get("side") or 768)
    pics = [(im["base64"], im["mime"]) for im in imgs if im.get("base64")]
    meta = [{k: im.get(k) for k in ("column", "index", "src", "origin", "error") if im.get(k) is not None} for im in imgs]
    return Images(meta, pics)


@tool("generate_item_image", "Generate a product image with the studio's configured image model (OpenAI-compatible / Gemini / OpenRouter) and attach it "
      "to the product. mode: add (append to gallery), replace, fill_missing. use_reference sends the scraped photo as reference (recommended for "
      "branded goods). prompt may use {title} {brand} {category} {specs}. Returns the generated image.",
      {"item_id": p(I, "Item id"), "prompt": p(S, "Image prompt (default: e-commerce white-background template)"),
       "provider_id": p(I, "AI connection id (default: first one with an image model)"), "profile_id": p(I, "Use image settings of this AI profile"),
       "target": p(S, "Image column, e.g. images_gallery or featured_images"), "mode": p(S, "add | replace | fill_missing", enum=["add", "replace", "fill_missing"]),
       "size": p(S, "e.g. 1024x1024"), "use_reference": p(B, "Use scraped image as reference (default true)"), "count": p(I, "1-4"),
       "model": p(S, "Image model override")}, ["item_id"], write=True)
def _gen_image(api, a):
    body = {k: v for k, v in a.items() if k != "item_id" and v is not None}
    r = api.post(f"/api/items/{a['item_id']}/generate-image", body)
    if not r.get("ok"):
        raise ToolError(r.get("error") or "تولید تصویر ناموفق بود.")
    imgs = api.get(f"/api/items/{a['item_id']}/images", thumbs="1", max=20, side=512)
    pics = [(im["base64"], im["mime"]) for im in imgs if im.get("src") in r["paths"] and im.get("base64")]
    return Images({k: r[k] for k in ("item_id", "target", "mode", "paths", "provider", "prompt")}, pics)


@tool("attach_item_image", "Attach an image you already have to a product: data_base64 (PNG/JPEG/WebP, optionally a data: URL), a public url, or a local path. "
      "mode add appends to the gallery; replace replaces the target column.",
      {"item_id": p(I, "Item id"), "data_base64": p(S, "Base64 image"), "url": p(S, "Image URL"), "path": p(S, "Local file path"),
       "target": p(S, "Image column"), "mode": p(S, "add | replace", enum=["add", "replace"])}, ["item_id"], write=True)
def _attach(api, a):
    body = {k: v for k, v in a.items() if k != "item_id" and v is not None}
    return api.post(f"/api/items/{a['item_id']}/attach-image", body)


# ----- هوش مصنوعی ------------------------------------------------------------

@tool("list_ai_providers", "AI connections configured in the studio (keys are never returned) and available presets.")
def _ai_prov(api, a):
    r = api.get("/api/ai/providers")
    return {"providers": r["providers"], "presets": [{k: x[k] for k in ("id", "name", "kind", "base_url", "image_mode")} for x in r["presets"]]}


@tool("save_ai_provider", "Create (no provider_id) or update an AI connection. kind: openai (any OpenAI-compatible base URL or router: OpenAI, OpenRouter, "
      "AvalAI, DeepSeek, Groq, Ollama…), anthropic, gemini. image_mode: images_api | chat_modalities | gemini | none.",
      {"provider_id": p(I, "Existing id"), "name": p(S, "Name"), "kind": p(S, "openai | anthropic | gemini", enum=["openai", "anthropic", "gemini"]),
       "base_url": p(S, "Base URL"), "api_key": p(S, "API key (omit to keep existing)"), "text_model": p(S, "Text model"),
       "image_model": p(S, "Image model"), "image_mode": p(S, "Image mode"), "proxy": p(S, "HTTP/SOCKS proxy"), "timeout_s": p(I, "Timeout"),
       "headers": p(O, "Extra headers")}, write=True)
def _save_prov(api, a):
    body = {k: v for k, v in a.items() if k != "provider_id" and v is not None}
    if a.get("provider_id"):
        return api.put(f"/api/ai/providers/{a['provider_id']}", body)
    return api.post("/api/ai/providers", body)


@tool("test_ai_provider", "Test an AI connection: action=test (chat ping), models (list model ids), image (generate a test image).",
      {"provider_id": p(I, "Connection id"), "action": p(S, "test | models | image", enum=["test", "models", "image"])}, ["provider_id"])
def _test_prov(api, a):
    act = {"image": "test-image"}.get(a.get("action") or "test", a.get("action") or "test")
    r = api.post(f"/api/ai/providers/{a['provider_id']}/{act}")
    if r.get("image"):
        b64 = r.pop("image").split(",", 1)[1]
        return Images(r, [(b64, "image/png")])
    return r


@tool("delete_ai_provider", "Delete an AI connection.", {"provider_id": p(I, "Connection id")}, ["provider_id"], destructive=True)
def _del_prov(api, a):
    return api.delete(f"/api/ai/providers/{a['provider_id']}")


@tool("list_ai_profiles", "AI generation profiles (which columns to generate, with which mode and instructions).")
def _profiles(api, a):
    r = api.get("/api/ai/profiles")
    return {"modes": r["modes"], "profiles": [{"id": x["id"], "name": x["name"], "provider_id": x["config"].get("provider_id"),
                                               "fields": [{"target": f["target"], "mode": f["mode"], "enabled": f.get("enabled", True)} for f in x["config"].get("fields", [])],
                                               "images": x["config"].get("images", {}).get("enabled")} for x in r["profiles"]]}


@tool("get_ai_profile", "Full AI profile config (system prompt, SEO keywords, banned words, fields, image settings).", {"profile_id": p(I, "Profile id")}, ["profile_id"])
def _get_prof(api, a):
    return api.get(f"/api/ai/profiles/{a['profile_id']}")


@tool("save_ai_profile", "Create (no profile_id) or update an AI generation profile. config keys: provider_id, model, image_model, temperature, max_tokens, "
      "batch, concurrency, system_prompt, seo_keywords, banned_words, extra_context, fields [{target, enabled, mode: fill_missing|rewrite|overwrite, "
      "instruction, max_chars}], images {enabled, target, mode, count, size, use_reference, prompt}. When updating, send the full config.",
      {"profile_id": p(I, "Existing id"), "name": p(S, "Name"), "description": p(S, "Description"), "config": p(O, "Profile config")},
      ["name"], write=True)
def _save_prof(api, a):
    if a.get("profile_id"):
        cur = api.get(f"/api/ai/profiles/{a['profile_id']}")
        cfg = {**cur["config"], **(a.get("config") or {})}
        return api.put(f"/api/ai/profiles/{a['profile_id']}", {"name": a["name"], "description": a.get("description", cur["description"]), "config": cfg})
    body = {"name": a["name"], "description": a.get("description", "")}
    if a.get("config"):
        default = api.get("/api/ai/profiles")["default"]
        body["config"] = {**default, **a["config"]}
    return api.post("/api/ai/profiles", body)


@tool("delete_ai_profile", "Delete an AI profile.", {"profile_id": p(I, "Profile id")}, ["profile_id"], destructive=True)
def _del_prof(api, a):
    return api.delete(f"/api/ai/profiles/{a['profile_id']}")


@tool("ai_preview", "Dry-run an AI profile on one product with the studio's AI connection: returns before/after values and the prompt, saves nothing.",
      {"item_id": p(I, "Item id"), "profile_id": p(I, "Profile id"), "config": p(O, "Unsaved profile config to test instead"), "images": p(B, "Also generate images")},
      ["item_id"])
def _ai_prev(api, a):
    body = {"item_id": a["item_id"], "images": a.get("images", False)}
    if a.get("config"):
        body["config"] = a["config"]
    else:
        body["profile_id"] = a.get("profile_id") or api.get("/api/ai/profiles")["profiles"][0]["id"]
    r = api.post("/api/ai/preview", body)
    imgs = []
    for f in (r.get("fields") or {}).values():
        if isinstance(f.get("after"), list) and f["after"] and str(f["after"][0]).startswith("data:image"):
            imgs += [(u.split(",", 1)[1], "image/png") for u in f["after"]]
            f["after"] = f"[{len(f['after'])} image(s)]"
    return Images(r, imgs) if imgs else r


@tool("generate_ai_for_item", "Run an AI profile on one product with the studio's AI connection and save the result (reversible).",
      {"item_id": p(I, "Item id"), "profile_id": p(I, "Profile id"), "images": p(B, "Include image generation (default true)")},
      ["item_id", "profile_id"], write=True)
def _ai_item(api, a):
    return api.post(f"/api/items/{a['item_id']}/ai", {"profile_id": a["profile_id"], "images": a.get("images", True)})


@tool("run_ai_generation", "Start a background AI generation job over a dataset for ANY schema columns (texts, title, slug, brand/category "
      "mapping slugs, specifications, dimensions, bullet groups, constants, images…). Choose what to generate with ONE of: columns "
      "([{key, mode: fill_missing|rewrite|overwrite (images: fill_missing|add|overwrite), instruction?, count?}] — see get_ai_columns), "
      "use_schema=true (the columns marked for AI in the schema), all_empty=true (every empty column), or profile_id (a saved template; it can "
      "also be combined with columns as the tone/SEO base). scope: all | selected (with item_ids) | partial. Then wait_for(kind='ai_job').",
      {"dataset_id": p(I, "Dataset id"), "columns": {"type": "array", "items": O, "description": "Columns to generate"},
       "use_schema": p(B, "Use the schema's AI columns"), "all_empty": p(B, "Fill every empty AI-capable column"), "profile_id": p(I, "Template id"),
       "scope": p(S, "all | selected | partial", enum=["all", "selected", "partial"]), "item_ids": p(IDS, "For scope=selected"),
       "overwrite_ai": p(B, "Regenerate existing AI values"), "images": p(B, "Allow image generation"), "seo_keywords": p(S, "SEO keywords"),
       "provider_id": p(I, "AI connection")},
      ["dataset_id"], write=True)
def _ai_run(api, a):
    body = {k: v for k, v in a.items() if v is not None and k != "all_empty"}
    if a.get("all_empty"):
        cols = api.get("/api/ai/columns", dataset_id=a["dataset_id"])["columns"]
        body["columns"] = [{"key": c["key"], "mode": "fill_missing"} for c in cols if c["capable"]]
    if "columns" not in body and not body.get("use_schema") and not body.get("profile_id"):
        raise ToolError("columns، use_schema، all_empty یا profile_id را مشخص کنید.")
    r = api.post("/api/ai/jobs", body)
    return {k: r.get(k) for k in ("id", "status", "progress_total", "step", "profile")}


@tool("get_ai_columns", "Schema columns of a dataset (or schema) with AI capability, the schema's AI setting, default mode and instruction — "
      "use it to build the columns list for run_ai_generation.", {"dataset_id": p(I, "Dataset id"), "schema_id": p(I, "Schema id")})
def _ai_cols(api, a):
    return api.get("/api/ai/columns", dataset_id=a.get("dataset_id"), schema_id=a.get("schema_id"))


@tool("list_ai_jobs", "AI generation jobs with progress.", {"dataset_id": p(I, "Filter by dataset")})
def _ai_jobs(api, a):
    return api.get("/api/ai/jobs", dataset_id=a.get("dataset_id"))


@tool("control_ai_job", "Pause (stop), resume or delete an AI generation job.",
      {"job_id": p(I, "Job id"), "action": p(S, "stop | resume | delete", enum=["stop", "resume", "delete"])}, ["job_id", "action"], write=True)
def _ai_ctl(api, a):
    return api.post(f"/api/ai/jobs/{a['job_id']}/{a['action']}")


# ----- قواعد متن ---------------------------------------------------------------

@tool("list_rules", "Text rules (non-destructive filters applied to scraped data and AI output): remove/replace/regex/drop_line/prepend/append/"
      "drop_spec/drop_image.")
def _rules(api, a):
    r = api.get("/api/rules")
    return {"actions": r["actions"], "fields": r["text_fields"], "rules": r["rules"]}


@tool("save_rule", "Create (no rule_id) or update a text rule. target: '*' (all text fields) or a field (title, short_description, long_description, "
      "specifications, gallery, …). find: phrases separated by '|' (or a regex for action=regex). value: replacement or text to prepend/append.",
      {"rule_id": p(I, "Existing id"), "name": p(S, "Name"), "action": p(S, "Action", enum=["remove", "replace", "regex", "drop_line", "prepend", "append", "drop_spec", "drop_image"]),
       "target": p(S, "Field or *"), "find": p(S, "Phrase(s)"), "value": p(S, "Replacement / added text"), "source_id": p(I, "Only for this source"),
       "enabled": p(B, "Enabled"), "whole_word": p(B, "Whole words only"), "case_sensitive": p(B, "Case sensitive")}, write=True)
def _save_rule(api, a):
    body = {k: v for k, v in a.items() if k not in ("rule_id", "whole_word", "case_sensitive") and v is not None}
    if "whole_word" in a or "case_sensitive" in a or a.get("action"):
        body["flags"] = {"split": "" if a.get("action") == "regex" else "|", "whole_word": bool(a.get("whole_word")), "case_sensitive": bool(a.get("case_sensitive"))}
    if a.get("rule_id"):
        return api.put(f"/api/rules/{a['rule_id']}", body)
    return api.post("/api/rules", body)


@tool("delete_rule", "Delete a text rule.", {"rule_id": p(I, "Rule id")}, ["rule_id"], destructive=True)
def _del_rule(api, a):
    return api.delete(f"/api/rules/{a['rule_id']}")


@tool("test_rules", "Apply the active text rules (or one unsaved rule) to a sample text and return the result.",
      {"text": p(S, "Sample text"), "target": p(S, "Field (default long_description)"), "source_id": p(I, "Source"), "rule": p(O, "Unsaved rule to test")},
      ["text"])
def _test_rules(api, a):
    return api.post("/api/rules/test", a)


# ----- نگاشت‌ها --------------------------------------------------------------

@tool("list_mappings", "Brand/category mappings from source values to Mega Cars slugs, plus values still unmapped.", {"kind": p(S, "brand | category")})
def _maps(api, a):
    return {"mappings": api.get("/api/mappings", kind=a.get("kind")), "unmapped": api.get("/api/mappings/unmapped")}


@tool("set_mappings", "Save mappings. rows: [{kind: brand|category, source_value, target_slug, target_label?, source_id? (null = all sources)}].",
      {"rows": {"type": "array", "items": O, "description": "Mapping rows"}}, ["rows"], write=True)
def _set_maps(api, a):
    return api.post("/api/mappings", {"rows": a["rows"]})


@tool("delete_mapping", "Delete a mapping.", {"mapping_id": p(I, "Mapping id")}, ["mapping_id"], destructive=True)
def _del_map(api, a):
    return api.delete(f"/api/mappings/{a['mapping_id']}")


# ----- صف ---------------------------------------------------------------------

@tool("list_queue", "Extraction queue: running, waiting and finished jobs, and whether the queue is enabled.")
def _queue(api, a):
    r = api.get("/api/queue")
    return {"enabled": r["enabled"], "jobs": [{k: j.get(k) for k in ("id", "position", "title", "status", "category_url", "item_limit", "schema_id",
                                                                     "ai_profile_id", "scheduled_at", "repeat_hours", "dataset_id", "error")}
                                              for j in r["jobs"]]}


@tool("add_queue_job", "Add an extraction to the queue; jobs run one after another. scheduled_at: ISO datetime (not before); repeat_hours: re-run "
      "periodically; ai_profile_id: run AI generation after scraping (ai_scope all|partial).",
      {"category_url": p(S, "Category URL"), "limit": p(I, "Max products"), "source_id": p(I, "Source"), "schema_id": p(I, "Schema"),
       "title": p(S, "Job title"), "scheduled_at": p(S, "ISO datetime"), "repeat_hours": {"type": "number", "description": "Repeat every N hours"},
       "ai_profile_id": p(I, "AI profile"), "ai_scope": p(S, "all | partial"), "duplicates": p(S, "skip | reuse | rescrape"), "policies": p(O, "Error policies")},
      ["category_url"], write=True)
def _q_add(api, a):
    r = api.post("/api/queue", {k: v for k, v in a.items() if v is not None})
    return {k: r.get(k) for k in ("id", "position", "title", "status", "scheduled_at", "repeat_hours")}


@tool("update_queue_job", "Edit a waiting queue job.",
      {"job_id": p(I, "Job id"), "title": p(S, "Title"), "category_url": p(S, "URL"), "limit": p(I, "Limit"), "schema_id": p(I, "Schema"),
       "scheduled_at": p(S, "ISO datetime or empty"), "repeat_hours": {"type": "number"}, "ai_profile_id": p(I, "AI profile")}, ["job_id"], write=True)
def _q_upd(api, a):
    return api.put(f"/api/queue/{a['job_id']}", {k: v for k, v in a.items() if k != "job_id" and v is not None})


@tool("queue_action", "Queue job action: up, down, top, run-now (first in line, ignore start time), skip (stop the running job and move on), requeue.",
      {"job_id": p(I, "Job id"), "action": p(S, "Action", enum=["up", "down", "top", "run-now", "skip", "requeue"])}, ["job_id", "action"], write=True)
def _q_act(api, a):
    return api.post(f"/api/queue/{a['job_id']}/{a['action']}")


@tool("toggle_queue", "Turn automatic queue processing on or off.", {"enabled": p(B, "On/off")}, ["enabled"], write=True)
def _q_toggle(api, a):
    return api.post("/api/queue/toggle", {"enabled": a["enabled"]})


@tool("delete_queue_job", "Remove a (non-running) job from the queue.", {"job_id": p(I, "Job id")}, ["job_id"], destructive=True)
def _q_del(api, a):
    return api.delete(f"/api/queue/{a['job_id']}")


# ----- خروجی و تصاویر -------------------------------------------------------

@tool("create_export", "Build the FINAL polished catalog from one or more datasets: <name>.xlsx/.csv (text rules, mappings, manual edits and AI applied) "
      "and per-product image folders where feature.png / gallery_N.png are the final images (background removed + trimmed/aligned on the canvas). "
      "Non-final files are clearly suffixed: raw downloads feature_raw.*, background-removed intermediates feature_raw_rembg.png, raw data "
      "<name>_raw.xlsx / <name>_raw.json. The ZIP contains only final files. Then wait_for(kind='export').",
      {"dataset_ids": p(IDS, "Datasets"), "schema_id": p(I, "Schema"), "name": p(S, "File name (default: dataset name)"),
       "formats": {"type": "array", "items": S, "description": "xlsx, csv, json"}, "format_schemas": p(O, "Per-format schema {xlsx|csv|json: schema_id} (default: schema_id)"), "statuses": {"type": "array", "items": S, "description": "done, partial"},
       "images": p(B, "Download images (default true)"), "rembg": p(B, "Remove backgrounds (default true)"), "rembg_model": p(S, "Model"),
       "align": p(B, "Trim + align subjects with the default alignment rule (default true)"),
       "keep_raw": p(B, "Keep raw/intermediate files (_raw, _raw_rembg, raw data). Default true"),
       "zip": p(B, "ZIP package of final files (default true)"), "zip_include_raw": p(B, "Also put raw/intermediate files in the ZIP"),
       "ai_fill": p(O, 'Before building, fill columns with AI: {"mode": "fill_missing"} (every empty column) | {"use_schema": true} | {"columns": ["key", ...]}'),
       "link_mode": p(S, "relative | prefix | source"), "link_prefix": p(S, "CDN prefix"),
       "folder_mode": p(S, "slug | title | key"), "output_root": p(S, "Output folder"), "item_ids": p(IDS, "Only these items")},
      ["dataset_ids"], write=True)
def _export(api, a):
    r = api.post("/api/exports", {k: v for k, v in a.items() if v is not None})
    return {k: r.get(k) for k in ("id", "name", "status")}


@tool("list_exports", "Exports with status and file paths.")
def _exports(api, a):
    return [{"id": e["id"], "name": e["name"], "status": e["status"], "created_at": e["created_at"], "files": (e.get("result") or {}).get("files"),
             "rows": (e.get("result") or {}).get("rows"), "error": e.get("error")} for e in api.get("/api/exports")]


@tool("cancel_export", "Cancel a running export.", {"export_id": p(I, "Export id")}, ["export_id"], write=True)
def _cancel_export(api, a):
    return api.post(f"/api/exports/{a['export_id']}/cancel")


# ----- خروجی‌های نهایی (کاتالوگ‌ها) -------------------------------------------

def _row_compact(r: dict) -> dict:
    return {"row_id": r["id"], "seq": r.get("seq"), "item_id": r.get("item_id"), "status": r.get("status"), "note": r.get("note") or "",
            "values": r.get("v"), "flags": r.get("f") or {}, "edited_by": r.get("e") or {}, "images": r.get("images"), "updated_at": r.get("updated_at")}


@tool("list_catalogs", "Final catalogs (finished exports) stored in the studio with title, state (draft/review/approved/published), "
      "formats and the schema of each format, row counts, edited rows and whether files are stale (need rebuild_catalog_files).",
      {"q": p(S, "Search in name/title/notes"), "state": p(S, "Filter by state", enum=["draft", "review", "approved", "published"])})
def _list_catalogs(api, a):
    return [{k: c.get(k) for k in ("id", "title", "name", "state", "status", "created_at", "rows", "rows_ok", "rows_edited", "files_stale",
                                   "managed", "format_schemas", "files", "notes")} for c in api.get("/api/catalogs", q=a.get("q"), state=a.get("state"))]


@tool("get_catalog", "One final catalog: metadata, files, and its schemas (id, name, formats, columns with key/label/input type).",
      {"catalog_id": p(I, "Catalog (export) id")}, ["catalog_id"])
def _get_catalog(api, a):
    d = api.get(f"/api/catalogs/{a['catalog_id']}")
    d["schemas"] = [{"id": s["id"], "name": s["name"], "formats": s["formats"],
                     "columns": [{k: c.get(k) for k in ("key", "label", "input", "kind", "required") if c.get(k) is not None} for c in s["columns"]]}
                    for s in d.get("schemas", [])]
    return d


@tool("get_catalog_rows", "Rows of a final catalog with the values of one schema (default: the first). filter: edited | warn | noimage | excluded.",
      {"catalog_id": p(I, "Catalog id"), "schema_id": p(I, "Schema id inside the catalog"), "q": p(S, "Search"),
       "filter": p(S, "Filter", enum=["edited", "warn", "noimage", "excluded"]), "row_ids": p(IDS, "Only these rows"),
       "page": p(I, "Page (default 1)"), "size": p(I, "Page size (default 30, max 200)")}, ["catalog_id"])
def _catalog_rows(api, a):
    r = api.get(f"/api/catalogs/{a['catalog_id']}/rows", schema_id=a.get("schema_id"), q=a.get("q"), filter=a.get("filter"),
                ids=",".join(str(i) for i in a.get("row_ids") or []) or None, page=a.get("page") or 1, size=min(200, int(a.get("size") or 30)))
    return {"total": r["total"], "page": r["page"], "size": r["size"], "schema_id": r["schema_id"], "rows": [_row_compact(x) for x in r["rows"]]}


@tool("update_catalog_row", "Edit one row of a final catalog: values {column_key: value} for a schema (structured values allowed: lists, "
      "objects, numbers), status ok|excluded, note. Old values are kept in history (revert_history).",
      {"catalog_id": p(I, "Catalog id"), "row_id": p(I, "Row id"), "schema_id": p(I, "Schema id (default first)"), "values": p(O, "{column_key: value}"),
       "status": p(S, "ok | excluded", enum=["ok", "excluded"]), "note": p(S, "Row note")}, ["catalog_id", "row_id"], write=True)
def _upd_catalog_row(api, a):
    body = {k: a[k] for k in ("schema_id", "values", "status", "note") if a.get(k) is not None}
    return _row_compact(api.put(f"/api/catalogs/{a['catalog_id']}/rows/{a['row_id']}", body))


@tool("bulk_edit_catalog", "Edit many rows of a final catalog at once (row_ids empty = all rows). set {key: value}; "
      "find_replace {key, find, replace, regex}; prepend/append {key: text}; status ok|excluded. Recorded in history.",
      {"catalog_id": p(I, "Catalog id"), "schema_id": p(I, "Schema id"), "row_ids": p(IDS, "Rows (empty = all)"), "set": p(O, "{key: value}"),
       "find_replace": p(O, "{key, find, replace, regex}"), "prepend": p(O, "{key: text}"), "append": p(O, "{key: text}"),
       "status": p(S, "ok | excluded", enum=["ok", "excluded"]),
       "apply_default": {"type": "array", "items": S, "description": "Column keys: apply the schema's current default value"},
       "default_mode": p(S, "Override how the default is applied", enum=["fill", "always", "prepend", "append"])}, ["catalog_id"], write=True)
def _bulk_catalog(api, a):
    return api.post(f"/api/catalogs/{a['catalog_id']}/rows/bulk", {k: v for k, v in a.items() if k != "catalog_id" and v is not None})


@tool("delete_catalog_row", "Remove one row from a final catalog (kept in history).", {"catalog_id": p(I, "Catalog id"), "row_id": p(I, "Row id")},
      ["catalog_id", "row_id"], destructive=True)
def _del_catalog_row(api, a):
    return api.delete(f"/api/catalogs/{a['catalog_id']}/rows/{a['row_id']}")


@tool("catalog_image_action", "Manage the final images of a catalog row. action: upload (data_base64 or a local path), url, generate (studio image "
      "model, optional prompt), delete, make_feature (gallery index → feature), move (gallery index → to), reprocess (rembg/align again from raw; "
      "slot all = every image). slot: feature | gallery | all. New images get the catalog's alignment and are renamed feature / gallery_N.",
      {"catalog_id": p(I, "Catalog id"), "row_id": p(I, "Row id"),
       "action": p(S, "Action", enum=["upload", "url", "generate", "delete", "make_feature", "move", "reprocess"]),
       "slot": p(S, "feature | gallery | all", enum=["feature", "gallery", "all"]), "index": p(I, "Gallery index (0-based)"), "to": p(I, "Target index for move"),
       "url": p(S, "Image URL (action url)"), "path": p(S, "Local image path (action upload)"), "data_base64": p(S, "Image bytes base64 (action upload)"),
       "name": p(S, "File name for upload"), "prompt": p(S, "Prompt for generate"), "rembg": p(B, "Remove background (default: catalog setting)"),
       "replace": p(B, "Replace the image at index instead of adding")}, ["catalog_id", "row_id", "action"], write=True)
def _catalog_img(api, a):
    body = {k: v for k, v in a.items() if k not in ("catalog_id", "row_id", "action", "path", "data_base64") and v is not None}
    if a["action"] == "upload":
        if a.get("path"):
            pth = Path(a["path"]).expanduser()
            body["data_url"] = base64.b64encode(pth.read_bytes()).decode()
            body.setdefault("name", pth.name)
        else:
            body["data_url"] = a.get("data_base64") or ""
    r = api.post(f"/api/catalogs/{a['catalog_id']}/rows/{a['row_id']}/images/{a['action']}", body)
    if not r.get("ok"):
        raise ToolError(r.get("error") or "عملیات تصویر ناموفق بود")
    return {"row_id": a["row_id"], "images": r["row"]["images"]}


@tool("catalog_ai", "Edit a final catalog with the studio's AI. columns: [{key, mode (overwrite|rewrite|fill_missing; images: fill_missing|add|overwrite), "
      "instruction?, count?}]. One row + wait=true returns the result directly; otherwise an AI job starts (wait_for kind=ai_job, stop_ai_job).",
      {"catalog_id": p(I, "Catalog id"), "schema_id": p(I, "Schema id"), "columns": {"type": "array", "items": O, "description": "Columns to generate"},
       "row_ids": p(IDS, "Rows (empty = all)"), "wait": p(B, "Wait for a single row"), "profile_id": p(I, "AI profile (optional)")},
      ["catalog_id", "columns"], write=True)
def _catalog_ai(api, a):
    r = api.post(f"/api/catalogs/{a['catalog_id']}/ai", {k: v for k, v in a.items() if k != "catalog_id" and v is not None})
    if "ok" in r:
        if not r["ok"]:
            raise ToolError(r.get("error"))
        return {"generated": r.get("generated"), "row": _row_compact(r["row"])}
    return {"ai_job_id": r["id"], "status": r["status"]}


@tool("update_catalog", "Change a final catalog: title, state (draft/review/approved/published), notes, formats, format_schemas {xlsx|csv|json: schema_id}, "
      "link_mode (relative|prefix|source), link_prefix. Then rebuild_catalog_files.",
      {"catalog_id": p(I, "Catalog id"), "title": p(S, "Title"), "state": p(S, "State", enum=["draft", "review", "approved", "published"]),
       "notes": p(S, "Notes"), "formats": {"type": "array", "items": S, "description": "xlsx, csv, json"}, "format_schemas": p(O, "{format: schema_id}"),
       "link_mode": p(S, "relative | prefix | source"), "link_prefix": p(S, "CDN prefix")}, ["catalog_id"], write=True)
def _upd_catalog(api, a):
    d = api.put(f"/api/catalogs/{a['catalog_id']}", {k: v for k, v in a.items() if k != "catalog_id" and v is not None})
    return {k: d.get(k) for k in ("id", "title", "state", "notes", "formats", "format_schemas", "files_stale")}


@tool("add_catalog_schema", "Add another schema to a finished catalog (its values are computed from the dataset products) so a format can use it.",
      {"catalog_id": p(I, "Catalog id"), "schema_id": p(I, "Schema id")}, ["catalog_id", "schema_id"], write=True)
def _add_catalog_schema(api, a):
    d = api.post(f"/api/catalogs/{a['catalog_id']}/schemas", {"schema_id": a["schema_id"]})
    return {"schemas": [{"id": s["id"], "name": s["name"], "formats": s["formats"]} for s in d.get("schemas", [])]}


@tool("rebuild_catalog_files", "Rewrite the catalog's xlsx/csv/json/zip from its current (edited) rows.", {"catalog_id": p(I, "Catalog id")},
      ["catalog_id"], write=True)
def _rebuild_catalog(api, a):
    return api.post(f"/api/catalogs/{a['catalog_id']}/rebuild", {})


@tool("sync_catalog_to_datasets", "Copy the catalog's edited values back to the dataset products as manual edits (so future exports include them).",
      {"catalog_id": p(I, "Catalog id"), "schema_id": p(I, "Schema id")}, ["catalog_id"], write=True)
def _sync_catalog(api, a):
    return api.post(f"/api/catalogs/{a['catalog_id']}/sync", {k: v for k, v in a.items() if k == "schema_id" and v})


@tool("delete_catalog", "Delete a final catalog from the studio (history keeps a record). delete_files also removes its files from disk.",
      {"catalog_id": p(I, "Catalog id"), "delete_files": p(B, "Also delete files (default false)")}, ["catalog_id"], destructive=True)
def _del_catalog(api, a):
    return api.delete(f"/api/catalogs/{a['catalog_id']}?files={1 if a.get('delete_files') else 0}")


# ----- ثبت و تاریخچه --------------------------------------------------------

@tool("get_activity", "Activity log: every request made by the UI, agents (MCP) and API — including tests and previews — with status, duration and input.",
      {"client": p(S, "ui | mcp | api", enum=["ui", "mcp", "api"]), "q": p(S, "Search"), "errors_only": p(B, "Only failures"),
       "page": p(I, "Page"), "size": p(I, "Rows (default 50)")})
def _activity(api, a):
    r = api.get("/api/activity", client=a.get("client"), q=a.get("q"), errors="1" if a.get("errors_only") else None, page=a.get("page"), size=a.get("size") or 50)
    return r


@tool("get_ai_calls", "Every AI request the studio made (purpose, provider/model, tokens, duration, error).",
      {"q": p(S, "Search"), "errors_only": p(B, "Only failures"), "item_id": p(I, "Product id"), "page": p(I, "Page"), "size": p(I, "Rows (default 50)")})
def _ai_calls(api, a):
    return api.get("/api/ai-calls", q=a.get("q"), errors="1" if a.get("errors_only") else None, item_id=a.get("item_id"), page=a.get("page"), size=a.get("size") or 50)


@tool("get_history", "Data change history with old and new values (products: entity=item; catalogs: entity=export_row / export). "
      "parent_id = catalog id or dataset id.",
      {"entity": p(S, "item | export_row | export", enum=["item", "export_row", "export"]), "entity_id": p(I, "Entity id"), "parent_id": p(I, "Parent id"),
       "actor": p(S, "ui | mcp | ai | api"), "q": p(S, "Search"), "page": p(I, "Page"), "size": p(I, "Rows (default 50)")})
def _history(api, a):
    return api.get("/api/history", **{k: a.get(k) for k in ("entity", "entity_id", "parent_id", "actor", "q", "page")}, size=a.get("size") or 50)


@tool("revert_history", "Restore the old value of one history entry (the revert is itself recorded).", {"history_id": p(I, "History id")},
      ["history_id"], write=True)
def _revert(api, a):
    return api.post(f"/api/history/{a['history_id']}/revert", {})


_ALIGN_PROPS = {
    "margin": p(I, "Distance (px) between the trimmed subject and the canvas edges, e.g. 60 or 100 (default from settings, 60)"),
    "margin_top": p(I, "Per-side margin (sets per_side)"), "margin_right": p(I, "Per-side margin"), "margin_bottom": p(I, "Per-side margin"),
    "margin_left": p(I, "Per-side margin"), "canvas_w": p(I, "Canvas width (default 1280)"), "canvas_h": p(I, "Canvas height (default 1280)"),
    "trim": p(S, "How empty space is detected", enum=["auto", "alpha", "color", "none"]),
    "alpha_threshold": p(I, "Alpha below this counts as empty (0-254, default 10)"),
    "color_tolerance": p(I, "For non-transparent images: tolerance vs. corner background colour (0-100, default 18)"),
    "despeckle": p(I, "Ignore isolated specks smaller than N px when finding the subject (default 2, 0 = off)"),
    "upscale": p(B, "Enlarge small subjects up to the margin (default true)"),
    "background": p(S, "auto | transparent | #rrggbb"), "format": p(S, "png | jpg | webp"),
}
_ALIGN_KEYS = list(_ALIGN_PROPS)


def _align_opts(a: dict) -> dict:
    o = {k: a[k] for k in _ALIGN_KEYS if a.get(k) is not None}
    if any(a.get(k) is not None for k in ("margin_top", "margin_right", "margin_bottom", "margin_left")):
        o["per_side"] = True
        for k in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
            o.setdefault(k, a.get("margin") or 60)
    return o


@tool("remove_background", "Remove image backgrounds for a whole folder (keeps the folder hierarchy; output defaults to <parent>/rembg/<folder>). "
      "By default each subject is then trimmed and aligned on the canvas (see align_images). Then wait_for(kind='bg_job').",
      {"input_path": p(S, "Folder with images"), "output_path": p(S, "Output folder"),
       "model": p(S, "isnet-general-use | u2net | u2netp | birefnet-general | birefnet-general-lite"),
       "align": p(B, "Trim + align after removing the background (default true)"), "overwrite": p(B, "Overwrite"), **_ALIGN_PROPS},
      ["input_path"], write=True)
def _rembg(api, a):
    body = {"input_path": a["input_path"], "output_path": a.get("output_path"), "model": a.get("model"), "overwrite": a.get("overwrite"), "rembg": True}
    body["align"] = _align_opts(a) if a.get("align", True) is not False else False
    return api.post("/api/bg", {k: v for k, v in body.items() if v is not None})


@tool("align_images", "Image alignment («ترازبندی»): for every image of a folder (hierarchy kept; output defaults to <parent>/aligned/<folder>) "
      "trim the empty transparent/solid background around the subject (like Photoshop Trim), then scale it WITHOUT changing its aspect "
      "ratio so the dimension that reaches the margin first sits exactly `margin` px from the canvas edges, and centre it on the canvas "
      "(default 1280×1280). Makes all products look the same size. Then wait_for(kind='bg_job').",
      {"input_path": p(S, "Folder with images"), "output_path": p(S, "Output folder"), "overwrite": p(B, "Overwrite"), **_ALIGN_PROPS},
      ["input_path"], write=True)
def _align(api, a):
    body = {"input_path": a["input_path"], "output_path": a.get("output_path"), "overwrite": a.get("overwrite"), "rembg": False, "align": _align_opts(a)}
    return api.post("/api/bg", {k: v for k, v in body.items() if v is not None})


@tool("preview_image_alignment", "Preview alignment settings on up to 4 sample images of a folder (or one file) and return the results as images "
      "plus measurements (trim box, scale, which side limited the size).",
      {"path": p(S, "Folder or image file"), "rembg": p(B, "Also remove background in the preview (slower)"), "limit": p(I, "Samples (1-4)"), **_ALIGN_PROPS},
      ["path"])
def _align_preview(api, a):
    r = api.post("/api/align/preview", {"path": a["path"], "rembg": bool(a.get("rembg")), "limit": min(4, int(a.get("limit") or 3)), "options": _align_opts(a)})
    if not r.get("ok"):
        raise ToolError(r.get("error") or "پیش‌نمایش ممکن نشد.")
    pics, meta = [], []
    for smp in r["samples"]:
        if smp.get("after"):
            pics.append((smp["after"].split(",", 1)[1], "image/png"))
        meta.append({"name": smp.get("name"), "error": smp.get("error"), **{k: (smp.get("info") or {}).get(k) for k in
                     ("source_size", "trim", "bbox", "subject_size", "scale", "limited_by", "placed", "upscaled", "low_res")}})
    return Images({"options": r["options"], "samples": meta}, pics)


@tool("list_bg_jobs", "Background-removal jobs and installed models.")
def _bg_jobs(api, a):
    return {"jobs": api.get("/api/bg"), "models": api.get("/api/models")}


@tool("download_bg_model", "Download a background-removal model file.", {"name": p(S, "Model name")}, ["name"], write=True)
def _bg_model(api, a):
    return api.post(f"/api/models/{a['name']}/download")


# ----- هوش مصنوعی همه‌جا (نسخه‌ی ۱.۳) ---------------------------------------

def _okr(r):
    if isinstance(r, dict) and r.get("ok") is False:
        raise ToolError(r.get("error") or "AI request failed")
    return r


@tool("ai_assist", "Run the studio's own AI assistant (uses the default AI connection). Tasks and payload keys: "
      "text {label, instruction, current?, context?, format: text|lines|slug|english|keywords}; "
      "field {item_id, column, mode: rewrite|fill_missing|overwrite, instruction?, save: bool} (image columns generate an image); "
      "schema {description, base_columns?}; column {description, schema_columns?}; mappings {kind: brand|category, values: [..], targets?}; "
      "rules {description}; source_fields {explorer, record?}. Returns the suggestion (nothing is saved unless save=true for field).",
      {"task": p(S, "Task", enum=["text", "field", "schema", "column", "mappings", "rules", "source_fields"]), "payload": p(O, "Task payload"),
       "provider_id": p(I, "AI connection (default: studio default)"), "model": p(S, "Model override")}, ["task"], write=True)
def _ai_assist(api, a):
    body = {**(a.get("payload") or {}), "task": a["task"]}
    for k in ("provider_id", "model"):
        if a.get(k):
            body[k] = a[k]
    return _okr(api.post("/api/ai/assist", body))


@tool("generate_dataset_with_ai", "Create a whole dataset WITHOUT scraping: the studio's AI plans N unique realistic products of a type and fills "
      "every schema column (titles, descriptions, specs, dimensions, manual columns like dos/donts) plus images. Then wait_for(kind='dataset').",
      {"product_type": p(S, "Product type, e.g. «روغن موتور خودرو»"), "count": p(I, "Number of products (1-1000)"),
       "category_label": p(S, "Category (optional)"), "brands": p(S, "Comma-separated brands to use (optional)"),
       "notes": p(S, "Extra constraints (optional)"), "seo_keywords": p(S, "SEO keywords (optional)"), "schema_id": p(I, "Schema (default schema if omitted)"),
       "images": p(B, "Generate images (default true)"), "image_count": p(I, "Images per product 1-4 (default 1)"),
       "provider_id": p(I, "Text AI connection"), "image_provider_id": p(I, "Image AI connection"), "model": p(S, "Model override"),
       "start": p(B, "Start now (default true)"), "queue": p(B, "Add to the extraction queue instead of starting now")},
      ["product_type", "count"], write=True)
def _ai_dataset(api, a):
    spec = {k: a.get(k) for k in ("product_type", "count", "category_label", "brands", "notes", "seo_keywords", "schema_id", "provider_id", "model")
            if a.get(k) not in (None, "")}
    spec["images"] = {"enabled": a.get("images", True) is not False, "count": int(a.get("image_count") or 1), "provider_id": a.get("image_provider_id")}
    if a.get("queue"):
        r = api.post("/api/queue", {"ai_generate": spec, "limit": spec["count"], "schema_id": spec.get("schema_id"),
                                    "category_label": spec.get("category_label", ""), "title": f"AI: {spec['count']} × {spec['product_type']}"})
        return {"queued_job": {k: r.get(k) for k in ("id", "position", "title", "status")}}
    spec["start"] = a.get("start", True) is not False
    d = api.post("/api/ai/datasets", spec)
    return {k: d.get(k) for k in ("id", "code", "name", "title", "status", "item_limit")}


@tool("ai_add_products", "Add N more AI-generated products (no scraping) to any dataset; they will not duplicate existing titles.",
      {"dataset_id": p(I, "Dataset id"), "count": p(I, "How many"), "product_type": p(S, "Product type (default: dataset's)"),
       "brands": p(S, "Brands (optional)"), "notes": p(S, "Constraints (optional)"), "images": p(B, "Generate images (default true)")},
      ["dataset_id", "count"], write=True)
def _ai_add(api, a):
    body = {k: a.get(k) for k in ("count", "product_type", "brands", "notes") if a.get(k) not in (None, "")}
    body["images"] = {"enabled": a.get("images", True) is not False, "count": 1}
    d = api.post(f"/api/datasets/{a['dataset_id']}/ai-add", body)
    return {k: d.get(k) for k in ("id", "status", "step", "counts")}


@tool("ai_generate_column", "Generate one schema column with the studio's AI for many products of a dataset (background job; "
      "wait_for(kind='ai_job')). Image columns produce images.",
      {"dataset_id": p(I, "Dataset id"), "column": p(S, "Column key"), "mode": p(S, "fill_missing | rewrite | overwrite", enum=["fill_missing", "rewrite", "overwrite"]),
       "instruction": p(S, "What to write (optional)"), "scope": p(S, "all | partial"), "item_ids": p(IDS, "Only these items"),
       "provider_id": p(I, "AI connection"), "model": p(S, "Model")}, ["dataset_id", "column"], write=True)
def _ai_col(api, a):
    r = api.post(f"/api/datasets/{a['dataset_id']}/ai-column", {k: v for k, v in a.items() if k != "dataset_id" and v is not None})
    return {k: r.get(k) for k in ("id", "status", "progress_total", "step")}


@tool("regenerate_ai_item", "Regenerate an AI-generated product from scratch (same planned title), or re-scrape a scraped one.",
      {"item_id": p(I, "Item id")}, ["item_id"], write=True)
def _ai_regen(api, a):
    r = api.post(f"/api/items/{a['item_id']}/rescrape")
    return {k: r.get(k) for k in ("id", "status", "error")} if isinstance(r, dict) else r


# ---------------------------------------------------------------------------
# منابع و پرامپت‌های MCP
# ---------------------------------------------------------------------------

RESOURCES = [
    {"uri": "studio://overview", "name": "overview", "title": "نمای کلی استودیو", "mimeType": "application/json"},
    {"uri": "studio://schemas", "name": "schemas", "title": "اسکیماها", "mimeType": "application/json"},
    {"uri": "studio://sources", "name": "sources", "title": "منابع", "mimeType": "application/json"},
    {"uri": "studio://datasets", "name": "datasets", "title": "بانک‌های داده", "mimeType": "application/json"},
    {"uri": "studio://rules", "name": "rules", "title": "قواعد متن", "mimeType": "application/json"},
]
TEMPLATES = [
    {"uriTemplate": "studio://dataset/{id}", "name": "dataset", "title": "بانک داده", "mimeType": "application/json"},
    {"uriTemplate": "studio://dataset/{id}/gaps", "name": "dataset-gaps", "title": "کمبودهای بانک داده", "mimeType": "application/json"},
    {"uriTemplate": "studio://item/{id}", "name": "item", "title": "محصول", "mimeType": "application/json"},
]


def read_resource(api: StudioAPI, uri: str):
    parts = uri.replace("studio://", "").strip("/").split("/")
    if parts == ["overview"]:
        return _overview(api, {})
    if parts == ["schemas"]:
        return _list_schemas(api, {})
    if parts == ["sources"]:
        return _list_sources(api, {})
    if parts == ["datasets"]:
        return _list_ds(api, {})
    if parts == ["rules"]:
        return _rules(api, {})
    if len(parts) == 2 and parts[0] == "dataset":
        return _get_ds(api, {"dataset_id": int(parts[1])})
    if len(parts) == 3 and parts[0] == "dataset" and parts[2] == "gaps":
        return _gaps(api, {"dataset_id": int(parts[1])})
    if len(parts) == 2 and parts[0] == "item":
        return _get_item(api, {"item_id": int(parts[1])})
    raise ToolError(f"منبع ناشناخته: {uri}")


PROMPTS = {
    "generate_catalog_with_ai": {
        "title": "ساخت کاتالوگ کامل با هوش مصنوعی (بدون اسکرپ)",
        "description": "Create N products of a type entirely with the studio's AI, then review and export.",
        "arguments": [{"name": "product_type", "description": "Product type", "required": True},
                      {"name": "count", "description": "How many", "required": True},
                      {"name": "category", "description": "Category (optional)", "required": False}],
        "text": ("با generate_dataset_with_ai یک بانک داده با {count} محصول از نوع «{product_type}» (دسته: {category}) بساز، با wait_for "
                 "پیگیری کن، سپس find_gaps را اجرا کن و کمبودها را با ai_generate_column یا set_item_fields تکمیل کن. "
                 "در پایان create_export بساز و خلاصه‌ی محصولات و مسیر فایل را گزارش بده."),
    },
    "complete_missing_fields": {
        "title": "تکمیل اطلاعات ناقص محصولات",
        "description": "Find and fill empty columns of a dataset's products, using scraped data and product photos.",
        "arguments": [{"name": "dataset_id", "description": "Dataset id", "required": True},
                      {"name": "columns", "description": "Optional comma-separated column keys", "required": False}],
        "text": ("در «استودیو کاتالوگ مگا» محصولات بانک داده‌ی {dataset_id} را تکمیل کن.\n"
                 "۱) با find_gaps (ستون‌ها: {columns}) محصولات دارای کمبود را پیدا کن.\n"
                 "۲) برای هر محصول get_item و در صورت نیاز get_item_images را بخوان.\n"
                 "۳) مقادیر خالی را با set_item_fields (mode=ai) بنویس: فارسی روان، یکتا و دقیق. هیچ مشخصه‌ی فنی یا عددی را حدس نزن؛ "
                 "اگر مطمئن نیستی خالی بگذار. بایدها/نبایدها را بولتی و کاربردی بنویس. واژه‌ی «شعبه» ممنوع است و به فروشنده «کسب‌وکار» بگو.\n"
                 "۴) در پایان خلاصه‌ای از محصولات و فیلدهای تکمیل‌شده و موارد باقی‌مانده بده."),
    },
    "seo_rewrite": {
        "title": "بازنویسی یکتا و سئوی توضیحات",
        "description": "Rewrite short/long descriptions of a dataset uniquely for SEO.",
        "arguments": [{"name": "dataset_id", "description": "Dataset id", "required": True},
                      {"name": "keywords", "description": "SEO keywords", "required": False}],
        "text": ("توضیح کوتاه و توضیح بلند محصولات بانک داده‌ی {dataset_id} را برای سئو یکتا کن. کلیدواژه‌ها: {keywords}.\n"
                 "list_items را صفحه‌به‌صفحه بخوان، برای هر محصول get_item بگیر و short_description (۱ تا ۲ جمله، حداکثر ۲۵۰ نویسه) و "
                 "long_description (۳ تا ۵ پاراگراف کوتاه: معرفی، ویژگی‌ها بر اساس مشخصات، کاربرد و سازگاری، نگهداری) را بنویس و با "
                 "set_item_fields (mode=ai) ذخیره کن. اطلاعات فنی نساز، نام فروشگاه‌ها و قیمت را نیاور."),
    },
    "extract_category": {
        "title": "استخراج یک دسته‌بندی",
        "description": "Scrape a category page and report the result.",
        "arguments": [{"name": "category_url", "description": "Category URL", "required": True},
                      {"name": "limit", "description": "Max products", "required": False}],
        "text": ("صفحه‌ی دسته‌بندی {category_url} را با start_extraction (limit={limit}) استخراج کن، با wait_for پیگیری کن، اگر خطایی منتظر "
                 "تصمیم ماند با list_incidents ببین و منطقی‌ترین تصمیم را با resolve_incident بگیر، و در پایان find_gaps و یک گزارش کوتاه بده."),
    },
    "product_images": {
        "title": "بررسی و تولید تصاویر محصول",
        "description": "Check product images and generate missing ones.",
        "arguments": [{"name": "dataset_id", "description": "Dataset id", "required": True}],
        "text": ("تصاویر محصولات بانک داده‌ی {dataset_id} را بررسی کن (find_gaps با ستون‌های featured_images و images_gallery و get_item_images). "
                 "برای محصولات بدون تصویر، با generate_item_image (use_reference=true در صورت وجود تصویر مرجع) تصویر بساز و نتیجه را گزارش کن."),
    },
}


# ---------------------------------------------------------------------------
# پروتکل
# ---------------------------------------------------------------------------

def _text(obj) -> str:
    t = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1, default=str)
    if len(t) > MAX_TEXT:
        t = t[:MAX_TEXT] + "\n… (truncated; narrow the request, e.g. use paging or limits)"
    return t


class Server:
    def __init__(self, api: StudioAPI, read_only: bool | Callable[[], bool] = False):
        self.api = api
        self._ro = read_only

    @property
    def read_only(self) -> bool:
        return self._ro() if callable(self._ro) else bool(self._ro)

    def tools(self) -> list[dict]:
        return [t["spec"] for t in TOOLS.values() if not (self.read_only and t["write"])]

    def call_tool(self, name: str, args: dict) -> dict:
        t = TOOLS.get(name)
        if not t or (self.read_only and t["write"]):
            return {"content": [{"type": "text", "text": f"Unknown or disabled tool: {name}"}], "isError": True}
        try:
            res = t["fn"](self.api, args or {})
        except ToolError as exc:
            return {"content": [{"type": "text", "text": f"خطا: {exc}"}], "isError": True}
        except Exception as exc:  # noqa: BLE001
            return {"content": [{"type": "text", "text": f"خطای داخلی: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}"}], "isError": True}
        if isinstance(res, Images):
            content = [{"type": "text", "text": _text(res.text)}] + [{"type": "image", "data": b, "mimeType": m} for b, m in res.images]
            return {"content": content, "isError": False}
        return {"content": [{"type": "text", "text": _text(res)}], "isError": False}

    def handle(self, msg: dict) -> dict | None:
        mid = msg.get("id")
        method = msg.get("method")
        if method is None:  # پاسخ کلاینت به درخواست سرور (نداریم)
            return None
        params = msg.get("params") or {}
        is_notification = "id" not in msg
        try:
            if method == "initialize":
                req = params.get("protocolVersion")
                result = {
                    "protocolVersion": req if req in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False, "subscribe": False},
                                     "prompts": {"listChanged": False}, "logging": {}},
                    "serverInfo": {"name": SERVER_NAME, "title": "استودیو کاتالوگ مگا (Mega Catalog Studio)", "version": SERVER_VERSION},
                    "instructions": INSTRUCTIONS + ("\nThis connection is READ-ONLY." if self.read_only else ""),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                result = self.call_tool(params.get("name", ""), params.get("arguments") or {})
            elif method == "resources/list":
                result = {"resources": RESOURCES}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": TEMPLATES}
            elif method == "resources/read":
                uri = params.get("uri", "")
                result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": _text(read_resource(self.api, uri))}]}
            elif method == "prompts/list":
                result = {"prompts": [{"name": k, "title": v["title"], "description": v["description"], "arguments": v["arguments"]} for k, v in PROMPTS.items()]}
            elif method == "prompts/get":
                pr = PROMPTS.get(params.get("name"))
                if not pr:
                    raise ToolError("پرامپت ناشناخته")
                args = {a["name"]: "" for a in pr["arguments"]} | {k: str(v) for k, v in (params.get("arguments") or {}).items()}
                args = {k: (v or "همه") for k, v in args.items()}
                result = {"description": pr["description"], "messages": [{"role": "user", "content": {"type": "text", "text": pr["text"].format(**args)}}]}
            elif method == "logging/setLevel" or method.startswith("notifications/"):
                result = {}
            elif method == "completion/complete":
                result = {"completion": {"values": [], "hasMore": False}}
            else:
                if is_notification:
                    return None
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        except ToolError as exc:
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def handle_payload(self, payload) -> Any:
        if isinstance(payload, list):
            out = [r for r in (self.handle(m) for m in payload) if r is not None]
            return out or None
        return self.handle(payload)


# ---------------------------------------------------------------------------
# انتقال stdio
# ---------------------------------------------------------------------------

def run_stdio():
    try:
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    ro = os.environ.get("CATALOG_STUDIO_MCP_READONLY", "").lower() in ("1", "true", "yes")
    api = StudioAPI(autostart=os.environ.get("CATALOG_STUDIO_AUTOSTART", "1") != "0")
    srv = Server(api, read_only=ro)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = srv.handle_payload(payload)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def quote_path(s: str) -> str:
    return quote(s)
