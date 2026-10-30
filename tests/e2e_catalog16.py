"""تست نسخه‌ی ۱.۶: توقف هوش مصنوعی، ثبت همه‌چیز، JSON و اسکیمای جدا برای هر قالب، مدیریت کامل خروجی‌های نهایی."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-cat16").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
for m in (ROOT / "data" / "models").glob("*.onnx"):
    os.symlink(m, DATA / "models" / m.name)
os.environ.update({"CATALOG_STUDIO_DATA": str(DATA), "CATALOG_STUDIO_ALLOWED_HOSTS": "testserver"})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fixture_site  # noqa: E402
from PIL import Image  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from studio.api import create_app  # noqa: E402

threading.Thread(target=fixture_site.serve, args=(8899,), daemon=True).start()
time.sleep(0.4)
c = TestClient(create_app())
c.headers["X-Studio-Client"] = "ui"
FX = "http://127.0.0.1:8899"


def ok(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        raise SystemExit(1)


def j(r):
    if r.status_code >= 400:
        print(r.text)
    r.raise_for_status()
    return r.json()


def wait(url, until, t=120, key="status"):
    t0 = time.time()
    while time.time() - t0 < t:
        d = j(c.get(url))
        if d[key] in until:
            return d
        time.sleep(0.3)
    raise SystemExit(f"timeout {url} {d.get(key)}")


def wait_job(jid, until=("completed", "error", "paused"), t=120):
    t0 = time.time()
    while time.time() - t0 < t:
        jj = next(x for x in j(c.get("/api/ai/jobs")) if x["id"] == jid)
        if jj["status"] in until:
            return jj
        time.sleep(0.2)
    raise SystemExit(f"ai job timeout {jj['status']} {jj['step']}")


j(c.put("/api/settings", json={"delay_min_ms": 10, "delay_max_ms": 20, "output_root": str(DATA / "output"), "queue_enabled": False}))
prov = j(c.post("/api/ai/providers", json={"name": "mock", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key",
                                          "text_model": "mock-text", "image_model": "mock-image", "image_mode": "images_api", "timeout_s": 30}))
j(c.put("/api/settings", json={"ai_default_provider_id": prov["id"]}))
src = j(c.post("/api/sources", json={"config": {
    "key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
    "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page"}},
    "product": {"mode": "http"}}}))
ds = j(c.post("/api/datasets", json={"category_url": FX + "/category/oils", "limit": 6}))
wait(f"/api/datasets/{ds['id']}", ("completed", "error"))
items = j(c.get(f"/api/datasets/{ds['id']}/items"))["items"]
ok(len(items) == 6, "بانک داده با ۶ محصول")
cols_sel = [{"key": "short_description", "mode": "overwrite"}, {"key": "vendor_notes", "mode": "overwrite"}]

print("۱) توقف هوش مصنوعی در خطا و توقف دستی")
bad = j(c.post("/api/ai/providers", json={"name": "bad-key", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "wrong",
                                         "text_model": "mock-text"}))
t0 = time.time()
job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": cols_sel, "provider_id": bad["id"]}))
jj = wait_job(job["id"])
ok(jj["status"] == "error" and "کلید API" in jj["error"] and time.time() - t0 < 8, f"کلید نامعتبر: فوراً متوقف شد ({time.time() - t0:.1f} ثانیه) — {jj['error'][:50]}")
for model, word in (("mock-quota", "سهمیه"), ("mock-bad", "پیدا نشد")):
    pv = j(c.post("/api/ai/providers", json={"name": model, "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key", "text_model": model}))
    t0 = time.time()
    job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": cols_sel, "provider_id": pv["id"]}))
    jj = wait_job(job["id"])
    ok(jj["status"] == "error" and word in jj["error"] and time.time() - t0 < 8, f"{model}: خطای قطعی و توقف فوری ({time.time() - t0:.1f} ثانیه)")
p500 = j(c.post("/api/ai/providers", json={"name": "p500", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key", "text_model": "mock-500"}))
t0 = time.time()
job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": cols_sel, "provider_id": p500["id"]}))
jj = wait_job(job["id"], t=200)
ok(jj["status"] == "error" and "پیاپی" in jj["error"] and jj["progress_done"] <= 4, f"خطای موقت تکراری: پس از ۳ خطای پیاپی متوقف شد ({time.time() - t0:.0f} ثانیه)")
fixture_site.AI_DELAY[0] = 1.5
job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": cols_sel}))
time.sleep(0.8)
t0 = time.time()
j(c.post(f"/api/ai/jobs/{job['id']}/stop", json={}))
jj = wait_job(job["id"], ("paused", "completed", "error"), t=20)
ok(jj["status"] == "paused" and time.time() - t0 < 4 and jj["progress_done"] < 6, f"توقف دستی در {time.time() - t0:.1f} ثانیه ({jj['progress_done']} از ۶)")
fixture_site.AI_DELAY[0] = 0
j(c.post(f"/api/ai/jobs/{job['id']}/resume", json={}))
ok(wait_job(job["id"])["status"] == "completed", "ادامه پس از توقف تا پایان")
aid = j(c.post("/api/ai/datasets", json={"product_type": "ضدیخ", "count": 3, "provider_id": bad["id"], "images": {"enabled": False}}))
d = wait(f"/api/datasets/{aid['id']}", ("error", "completed", "paused"), t=30)
ok(d["status"] == "error" and "کلید API" in d["step"], "بانک داده‌ی تولیدی هم با کلید نامعتبر فوراً متوقف شد")

print("۲) ثبت همه‌چیز")
j(c.post("/api/ai/assist", json={"task": "text", "label": "عنوان", "instruction": "بنویس"}))
j(c.post(f"/api/sources/{src['id']}/test-product", json={"url": FX + "/product/p-2"}))
j(c.post("/api/align/preview", json={"path": str(DATA), "options": {"margin": 60}}))
act = j(c.get("/api/activity?size=200"))["rows"]
acts = {a["action"] for a in act}
ok({"دستیار هوش مصنوعی", "آزمایش زنده‌ی صفحه‌ی محصول", "پیش‌نمایش ترازبندی", "شروع تولید گروهی با هوش مصنوعی",
    "ساخت بانک داده"} <= acts, f"فعالیت‌ها ثبت شدند ({len(act)} مورد)")
ok(all(a["client"] == "ui" for a in act) and any(a["status"] >= 400 or True for a in act), "منبع درخواست (رابط کاربری) ثبت شد")
one = j(c.get(f"/api/activity?id={act[0]['id']}"))
ok(one["request"] and one["response"] is not None, "ورودی و پاسخ هر فعالیت ذخیره می‌شود")
prov_act = next(a for a in act if a["action"] == "ساخت اتصال هوش مصنوعی")
ok("test-key" not in j(c.get(f"/api/activity?id={prov_act['id']}"))["request"], "کلید API در گزارش پنهان می‌شود")
calls = j(c.get("/api/ai-calls?size=300"))
ok(calls["total"] >= 10 and calls["sum"]["errors"] >= 3, f"همه‌ی درخواست‌های هوش مصنوعی ثبت شدند ({calls['total']} درخواست، {calls['sum']['errors']} خطا)")
cl = j(c.get(f"/api/ai-calls?id={calls['rows'][0]['id']}"))
ok(cl["prompt"] and (cl["response"] or cl["error"]), "پرامپت و پاسخ هر درخواست هوش مصنوعی ذخیره می‌شود")
ok(any(r["purpose"].startswith("تولید گروهی") and r["item_id"] for r in calls["rows"]), "هدف و محصول هر درخواست ثبت می‌شود")
it0 = items[0]["id"]
j(c.put(f"/api/items/{it0}", json={"overrides": {"title": "عنوان ویرایش‌شده"}}))
h = j(c.get(f"/api/history?entity=item&entity_id={it0}"))["rows"]
ok(any(x["field"] == "overrides:title" and "ویرایش‌شده" in x["new"] for x in h) and any(x["action"] == "ai" for x in h), "تاریخچه‌ی ویرایش دستی و هوش مصنوعی محصول")
hid = next(x["id"] for x in h if x["field"] == "overrides:title")
j(c.post(f"/api/history/{hid}/revert", json={}))
ok("title" not in j(c.get(f"/api/items/{it0}"))["overrides"], "بازگردانی تغییر از تاریخچه")

print("۳) JSON و اسکیمای جدا برای هر قالب")
schemas = j(c.get("/api/schemas"))
base = schemas[0]
small = j(c.post("/api/schemas", json={"name": "اسکیمای JSON", "columns": [
    {"key": "title", "label": "عنوان", "kind": "scraped", "from": "title", "input": "text"},
    {"key": "slug", "label": "اسلاگ", "kind": "auto", "generator": "slug"},
    {"key": "brand_slug", "label": "برند", "kind": "mapping", "map": "brand"},
    {"key": "specs", "label": "مشخصات", "kind": "scraped", "from": "specifications", "input": "specs", "spec_format": "list"},
    {"key": "dos", "label": "بایدها", "kind": "manual", "input": "bullet_groups", "groups": [{"key": "dos", "label": "بایدها"}, {"key": "donts", "label": "نبایدها"}]},
    {"key": "dimensions", "label": "ابعاد", "kind": "scraped", "from": "dimensions", "input": "group", "subkeys": ["item_weight", "item_width"]},
    {"key": "active", "label": "فعال", "kind": "constant", "value": "true", "input": "bool"},
    {"key": "featured_images", "label": "تصویر", "kind": "scraped", "from": "featured_image", "input": "image"},
    {"key": "images_gallery", "label": "گالری", "kind": "scraped", "from": "gallery", "input": "images"}]}))
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "formats": ["xlsx", "csv", "json"], "schema_id": base["id"],
                                   "format_schemas": {"json": small["id"]}, "rembg": False, "align": {"margin": 60}, "zip": True}))
e = wait(f"/api/exports/{ex['id']}", ("completed", "error"), t=120)
ok(e["status"] == "completed", f"خروجی ساخته شد: {e.get('error') or ''}")
files = e["result"]["files"]
recs = json.loads(Path(files["json"]).read_text(encoding="utf-8"))
r0 = recs[0]
ok(isinstance(recs, list) and len(recs) == 6 and set(r0) == {"title", "slug", "brand_slug", "specs", "dos", "dimensions", "active", "featured_images", "images_gallery"},
   "JSON: یک آرایه از ۶ شیء با ستون‌های اسکیمای خودش")
ok(isinstance(r0["specs"], list) and isinstance(r0["dos"], dict) and isinstance(r0["dos"]["dos"], list) and r0["active"] is True
   and isinstance(r0["images_gallery"], list) and r0["featured_images"].endswith("feature.png"), "ساختار حفظ شد: مشخصات آرایه، بولت‌ها شیء، بولی، گالری آرایه")
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(files["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
ok("user_dos_donts_description.dos" in hdr and "dos" not in hdr, "Excel با اسکیمای خودش (مگا کارز)")
ok(Path(files["csv"]).read_text(encoding="utf-8-sig").splitlines()[0].startswith("title,slug"), "CSV")
zn = zipfile.ZipFile(files["zip"]).namelist()
ok(any(n.endswith(".json") for n in zn) and not any("_raw" in n for n in zn), "JSON داخل بسته‌ی نهایی")

print("۴) مدیریت خروجی‌های نهایی")
cats = j(c.get("/api/catalogs"))
cat = next(x for x in cats if x["id"] == ex["id"])
ok(cat["managed"] and cat["rows"] == 6 and set(cat["formats"]) == {"xlsx", "csv", "json"} and cat["format_schemas"]["json"]["id"] == small["id"], "فهرست خروجی‌ها با ردیف‌ها و اسکیمای هر قالب")
det = j(c.get(f"/api/catalogs/{ex['id']}"))
ok(len(det["schemas"]) == 2, "دو اسکیما در یک خروجی")
rows = j(c.get(f"/api/catalogs/{ex['id']}/rows?schema_id={small['id']}"))["rows"]
r1 = rows[0]
ok(r1["v"]["title"] and r1["image_urls"]["feature"], "ردیف‌ها با مقادیر و تصاویر")
j(c.put(f"/api/catalogs/{ex['id']}/rows/{r1['id']}", json={"schema_id": small["id"], "values": {"title": "عنوان نهایی دستی", "dos": {"dos": ["الف"], "donts": ["ب"]}}}))
ok(j(c.get(f"/api/catalogs/{ex['id']}"))["files_stale"], "پس از ویرایش، فایل‌ها «نیازمند بازسازی» علامت می‌خورند")
j(c.post(f"/api/catalogs/{ex['id']}/rows/bulk", json={"schema_id": base["id"], "find_replace": {"key": "long_description", "find": "روغن", "replace": "روانکار"}}))
j(c.put(f"/api/catalogs/{ex['id']}/rows/{rows[5]['id']}", json={"status": "excluded"}))
res = j(c.post(f"/api/catalogs/{ex['id']}/rebuild", json={}))
recs = json.loads(Path(res["files"]["json"]).read_text(encoding="utf-8"))
ws = load_workbook(res["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
ld = ws.cell(row=2, column=hdr.index("long_description") + 1).value
ok(len(recs) == 5 and recs[0]["title"] == "عنوان نهایی دستی" and recs[0]["dos"] == {"dos": ["الف"], "donts": ["ب"]}, "بازسازی: JSON با ویرایش دستی و بدون ردیف کنارگذاشته")
ok("روانکار" in ld and "روغن" not in ld and ws.max_row == 6, "بازسازی: Excel با جست‌وجو و جایگزینی گروهی")
hist = j(c.get(f"/api/history?entity=export_row&parent_id={ex['id']}&size=200"))["rows"]
ok(len(hist) >= 7, f"تاریخچه‌ی ویرایش خروجی ({len(hist)} مورد)")
h1 = next(x for x in hist if x["field"] == f"{small['id']}:title")
j(c.post(f"/api/history/{h1['id']}/revert", json={}))
ok(j(c.get(f"/api/catalogs/{ex['id']}/rows?schema_id={small['id']}&ids={r1['id']}"))["rows"][0]["v"]["title"] != "عنوان نهایی دستی", "بازگردانی ویرایش خروجی")

print("۵) تصاویر خروجی")
rid = r1["id"]
buf = io.BytesIO()
im = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
from PIL import ImageDraw  # noqa: E402
ImageDraw.Draw(im).rectangle([300, 100, 399, 499], fill=(10, 120, 200, 255))
im.save(buf, "PNG")
du = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
r = j(c.post(f"/api/catalogs/{ex['id']}/rows/{rid}/images/upload", json={"slot": "gallery", "data_url": du, "name": "new.png", "rembg": False}))
ok(r["ok"], f"بارگذاری تصویر: {r.get('error', '')}")
imgs = r["row"]["images"]
n_gal = len(imgs["gallery"])
outroot = Path(e["result"]["root"])
last = outroot / imgs["gallery"][-1]
ok(last.name == f"gallery_{n_gal}.png" and Image.open(last).size == (1280, 1280) and (last.parent / f"gallery_{n_gal}_raw.png").exists(),
   f"تصویر جدید ترازشده و هم‌نام‌گذاری‌شده: {last.name} (+ نسخه‌ی خام)")
r = j(c.post(f"/api/catalogs/{ex['id']}/rows/{rid}/images/make_feature", json={"index": n_gal - 1}))
im2 = r["row"]["images"]
ok(im2["feature"].endswith("feature.png") and len(im2["gallery"]) == n_gal, "تصویر گالری شاخص شد و نام‌ها مرتب شدند")
r = j(c.post(f"/api/catalogs/{ex['id']}/rows/{rid}/images/delete", json={"slot": "gallery", "index": 0}))
ok(len(r["row"]["images"]["gallery"]) == n_gal - 1 and (outroot / r["row"]["images"]["gallery"][0]).name == "gallery_1.png", "حذف تصویر گالری (به پوشه‌ی _removed)")
r = j(c.post(f"/api/catalogs/{ex['id']}/rows/{rid}/images/generate", json={"slot": "gallery"}))
ok(r["ok"] and len(r["row"]["images"]["gallery"]) == n_gal, "تولید تصویر با هوش مصنوعی برای ردیف خروجی")
r = j(c.post(f"/api/catalogs/{ex['id']}/rows/{rid}/images/reprocess", json={"slot": "all", "rembg": False}))
ok(r["ok"], "پردازش دوباره‌ی همه‌ی تصاویر ردیف با قاعده‌ی ترازبندی")
hi = [x for x in j(c.get(f"/api/history?entity=export_row&entity_id={rid}&size=100"))["rows"] if x["field"] == "images"]
ok(len(hi) >= 5, "تاریخچه‌ی تغییرات تصاویر")

print("۶) هوش مصنوعی روی خروجی")
r = j(c.post(f"/api/catalogs/{ex['id']}/ai", json={"schema_id": base["id"], "row_ids": [rid], "wait": True,
                                                  "columns": [{"key": "long_description", "mode": "overwrite"}]}))
ok(r["ok"] and "long_description" in r["generated"] and r["row"]["e"].get("long_description") == "ai", "تک‌فیلد با هوش مصنوعی (فوری)")
job = j(c.post(f"/api/catalogs/{ex['id']}/ai", json={"schema_id": small["id"], "columns": [{"key": "dos", "mode": "overwrite"}, {"key": "brand_slug", "mode": "overwrite"}]}))
jj = wait_job(job["id"])
rows2 = j(c.get(f"/api/catalogs/{ex['id']}/rows?schema_id={small['id']}"))["rows"]
ok(jj["status"] == "completed" and all(x["e"].get("dos") == "ai" for x in rows2 if x["status"] == "ok"), "گروهی: بولت‌ها و نگاشت برند همه‌ی ردیف‌ها با هوش مصنوعی")
sy = j(c.post(f"/api/catalogs/{ex['id']}/sync", json={"schema_id": base["id"]}))
ok(sy["items_updated"] >= 1 and "long_description" in j(c.get(f"/api/items/{r1['item_id']}"))["overrides"], "اعمال ویرایش‌های خروجی روی بانک داده")
j(c.put(f"/api/catalogs/{ex['id']}", json={"title": "کاتالوگ روغن موتور — نهایی", "state": "approved", "notes": "بازبینی شد"}))
cat = next(x for x in j(c.get("/api/catalogs?state=approved")) if x["id"] == ex["id"])
ok(cat["title"] == "کاتالوگ روغن موتور — نهایی", "عنوان، وضعیت و یادداشت خروجی")
added = j(c.post(f"/api/catalogs/{ex['id']}/schemas", json={"schema_id": j(c.post("/api/schemas", json={"name": "سوم", "columns": [
    {"key": "name", "label": "نام", "kind": "scraped", "from": "title", "input": "text"}]}))["id"]}))
ok(len(added["schemas"]) == 3, "افزودن اسکیمای دیگر به خروجی ساخته‌شده")

print("۷) حذف خروجی")
ex2 = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "formats": ["json"], "rembg": False, "align": False, "images": False, "name": "temp-export"}))
e2 = wait(f"/api/exports/{ex2['id']}", ("completed", "error"))
ok(Path(e2["result"]["files"]["json"]).exists(), "خروجی فقط JSON")
d = j(c.delete(f"/api/catalogs/{ex2['id']}?files=1"))
ok(not Path(e2["result"]["files"]["json"]).exists() and "temp-export.json" in d["removed"], "حذف خروجی همراه با فایل‌ها")
ok(any(x["action"] == "delete" for x in j(c.get(f"/api/history?entity=export&entity_id={ex2['id']}"))["rows"]), "حذف هم در تاریخچه ثبت شد")

print("۸) ابزارهای ایجنت (MCP) برای خروجی‌ها و گزارش‌ها")
from studio import mcp_core  # noqa: E402


class _MApi:
    def _r(self, m, path, body=None, params=None):
        r = c.request(m, path, json=body, params={k: v for k, v in (params or {}).items() if v not in (None, "")}, headers={"X-Studio-Client": "mcp"})
        if r.status_code >= 400:
            raise mcp_core.ToolError(r.json().get("error"))
        return r.json()

    def get(self, path, **kw):
        return self._r("GET", path, params=kw)

    def post(self, path, body=None):
        return self._r("POST", path, body or {})

    def put(self, path, body):
        return self._r("PUT", path, body)

    def delete(self, path):
        return self._r("DELETE", path)


MA = _MApi()


def T(_tool, **a):
    return mcp_core.TOOLS[_tool]["fn"](MA, a)


need = {"list_catalogs", "get_catalog", "get_catalog_rows", "update_catalog_row", "bulk_edit_catalog", "catalog_image_action", "catalog_ai",
        "update_catalog", "rebuild_catalog_files", "sync_catalog_to_datasets", "delete_catalog", "get_activity", "get_ai_calls", "get_history", "revert_history"}
ok(need <= set(mcp_core.TOOLS) and mcp_core.SERVER_VERSION == "1.6.1", f"{len(mcp_core.TOOLS)} ابزار MCP")
mc = T("list_catalogs")
ok(any(x["id"] == ex["id"] for x in mc), "list_catalogs")
gc = T("get_catalog", catalog_id=ex["id"])
ok(gc["schemas"] and gc["schemas"][0]["columns"][0]["key"], "get_catalog با ستون‌های اسکیما")
rows_m = T("get_catalog_rows", catalog_id=ex["id"], size=3)
ok(len(rows_m["rows"]) == 3 and "values" in rows_m["rows"][0], "get_catalog_rows")
rid_m = rows_m["rows"][0]["row_id"]
u = T("update_catalog_row", catalog_id=ex["id"], row_id=rid_m, values={"title": "عنوان از ایجنت"})
ok(u["values"]["title"] == "عنوان از ایجنت" and u["edited_by"]["title"] == "mcp", "update_catalog_row (ثبت با کننده‌ی ایجنت)")
b = T("bulk_edit_catalog", catalog_id=ex["id"], row_ids=[rid_m], append={"title": " — ویژه"})
ok(b["updated"] == 1, "bulk_edit_catalog")
buf = io.BytesIO()
Image.new("RGB", (300, 500), (10, 120, 200)).save(buf, "PNG")
im_m = T("catalog_image_action", catalog_id=ex["id"], row_id=rid_m, action="upload", data_base64=base64.b64encode(buf.getvalue()).decode(), name="agent.png", rembg=False)
ok(len(im_m["images"]["gallery"]) >= 1, "catalog_image_action (بارگذاری تصویر)")
ai_m = T("catalog_ai", catalog_id=ex["id"], row_ids=[rid_m], wait=True, columns=[{"key": "long_description", "mode": "overwrite"}])
ok("long_description" in ai_m["generated"], "catalog_ai")
up_m = T("update_catalog", catalog_id=ex["id"], state="approved")
ok(up_m["state"] == "approved", "update_catalog")
ok(T("rebuild_catalog_files", catalog_id=ex["id"]) is not None and not j(c.get(f"/api/catalogs/{ex['id']}"))["files_stale"], "rebuild_catalog_files")
hm = T("get_history", entity="export_row", entity_id=rid_m)
ok(any(h["actor"] == "mcp" for h in hm["rows"]), "get_history")
T("revert_history", history_id=next(h["id"] for h in hm["rows"] if h["actor"] == "mcp" and h["field"].endswith(":title")))
act = T("get_activity", client="mcp")
ok(act["total"] >= 6 and all(r["client"] == "mcp" for r in act["rows"]), "get_activity (درخواست‌های ایجنت ثبت شده‌اند)")
ok(T("get_ai_calls")["total"] >= 1, "get_ai_calls")

print("۹) شروع استودیو")
from studio import images as img_mod, __main__ as mainmod  # noqa: E402
t0 = time.time()
img_mod._REMBG_OK = None
img_mod.rembg_available()
ok(time.time() - t0 < 0.5, "بررسی rembg بدون import سنگین")
ok(mainmod._probe("127.0.0.1", 1) is None and mainmod._port_free("127.0.0.1", 0) in (True, False), "ابزار تشخیص نمونه‌ی در حال اجرا")
ok(j(c.get("/api/health"))["app"] == "mega-catalog-studio", "نقطه‌ی سلامت /api/health")
print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
