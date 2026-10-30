"""تست نسخه‌ی ۱.۵: تولید با هوش مصنوعی برای هر ستون، در اسکیما (نوع مقدار)، اسکرپر (نوع فیلد/راهبرد)، بانک داده، صف و خروجی."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-ai15").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
os.environ.update({"CATALOG_STUDIO_DATA": str(DATA), "CATALOG_STUDIO_ALLOWED_HOSTS": "testserver"})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fixture_site  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from studio.api import create_app  # noqa: E402

threading.Thread(target=fixture_site.serve, args=(8899,), daemon=True).start()
time.sleep(0.4)
c = TestClient(create_app())
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
        time.sleep(0.4)
    raise SystemExit(f"timeout {url} {d.get(key)}")


def ai_jobs(did):
    return j(c.get(f"/api/ai/jobs?dataset_id={did}"))


def wait_job(jid, t=120):
    t0 = time.time()
    while time.time() - t0 < t:
        jj = next(x for x in j(c.get("/api/ai/jobs")) if x["id"] == jid)
        if jj["status"] in ("completed", "error", "paused"):
            return jj
        time.sleep(0.4)
    raise SystemExit("ai job timeout")


j(c.put("/api/settings", json={"delay_min_ms": 10, "delay_max_ms": 20, "output_root": str(DATA / "output"), "queue_enabled": False}))
prov = j(c.post("/api/ai/providers", json={"name": "mock", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key",
                                          "text_model": "mock-text", "image_model": "mock-image", "image_mode": "images_api"}))
j(c.put("/api/settings", json={"ai_default_provider_id": prov["id"]}))
src = j(c.post("/api/sources", json={"config": {
    "key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
    "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page"}},
    "product": {"mode": "http"}}}))

print("۱) اسکیما: نوع مقدار «هوش مصنوعی» و تولید AI برای هر نوع ستون")
base = j(c.get("/api/schemas"))[0]
cols = json.loads(json.dumps(base["columns"]))
byk = {x["key"]: x for x in cols}
byk["vendor_notes"]["ai_mode"] = "fill_missing"
byk["brand_slug"]["ai_mode"] = "overwrite"            # نگاشت
byk["dimensions"]["ai_mode"] = "fill_missing"          # گروه کلید/مقدار
byk["featured_images"]["ai_mode"] = "add"              # تصویر
cols.append({"key": "seo_title", "label": "عنوان سئو", "kind": "ai", "input": "text", "ai_instruction": "عنوان سئو حداکثر ۶۰ نویسه"})
cols.append({"key": "warranty", "label": "گارانتی", "kind": "scraped", "from": "warranty", "input": "text"})
sch = j(c.post("/api/schemas", json={"name": "اسکیمای آزمون AI", "columns": cols}))
ac = j(c.get(f"/api/ai/columns?schema_id={sch['id']}"))["columns"]
acm = {x["key"]: x for x in ac}
ok(not acm["source_url"]["capable"] and acm["brand_slug"]["capable"] and acm["status"]["capable"] and acm["slug"]["capable"],
   "همه‌ی ستون‌ها جز مقادیر سیستمی (لینک منبع) قابل تولیدند: متن، نگاشت، ثابت، اسلاگ…")
ok({k for k, x in acm.items() if x["schema_ai"]} == {"vendor_notes", "brand_slug", "dimensions", "featured_images", "seo_title"},
   "ستون‌های AI اسکیما شناسایی شدند (از جمله ستون نوع «هوش مصنوعی»)")
ok(acm["featured_images"]["image"] and acm["seo_title"]["instruction"].startswith("عنوان سئو"), "دستور پیش‌فرض و تشخیص ستون تصویری")

print("۲) اسکرپر: راهبرد «هوش مصنوعی» و پشتیبان AI برای فیلدهای خالی")
cfg = j(c.get(f"/api/sources/{src['id']}"))["config"]
cfg["fields"] = [{"key": "warranty", "label": "گارانتی", "type": "text", "strategies": [{"type": "css", "selector": ".no-such"}, {"type": "ai", "mode": "generate", "instruction": "مدت گارانتی"}]},
                 {"key": "title", "strategies": [{"type": "css", "selector": "h1.product-title"}]},
                 {"key": "gallery", "type": "images", "strategies": [{"type": "css", "selector": ".nothing", "attr": "src"}]},
                 {"key": "featured_image", "type": "image", "strategies": [{"type": "css", "selector": ".nothing", "attr": "src"}]}]
cfg["product"]["ai_fallback"] = {"enabled": True, "fields": ["title", "gallery", "featured_image"], "mode": "extract"}
t = j(c.post(f"/api/sources/{src['id']}/test-product", json={"url": FX + "/product/p-5", "config": cfg}))
rec, how = t["record"], t.get("how") or {}
ok(rec.get("warranty") and how.get("warranty", {}).get("type") == "ai", f"راهبرد AI فیلد سفارشی «گارانتی» را ساخت: {str(rec.get('warranty'))[:50]}")
ok(rec.get("title") and how.get("title", {}).get("strategy") == "fallback", "عنوانِ خالی (محصول ۵) با پشتیبان AI از متن صفحه استخراج شد")
ok(str(rec.get("featured_image", "")).startswith("http") and how.get("featured_image", {}).get("type") == "ai", "تصویر شاخص از فهرست تصاویر صفحه با AI انتخاب شد")
t2 = j(c.post(f"/api/sources/{src['id']}/test-product", json={"url": FX + "/product/p-3", "config": cfg}))
ok(how is not None and t2["how"].get("title", {}).get("type") == "css" and t2["how"].get("warranty", {}).get("type") == "ai",
   "وقتی راهبرد عادی موفق است، AI فقط برای فیلدهای خالی فراخوانده می‌شود")
j(c.put(f"/api/sources/{src['id']}", json={"config": cfg}))
sf = j(c.post("/api/ai/assist", json={"task": "source_fields", "explorer": t["explorer"], "record": t["record"]}))
ok(sf["ok"], "پیشنهاد راهبرد با AI همچنان کار می‌کند")

print("۳) پس از استخراج، تولید خودکار ستون‌های AI اسکیما")
ds = j(c.post("/api/datasets", json={"category_url": FX + "/category/oils", "limit": 3, "schema_id": sch["id"], "ai_after": {"mode": "schema"}}))
wait(f"/api/datasets/{ds['id']}", ("completed", "error"))
t0 = time.time()
while not ai_jobs(ds["id"]) and time.time() - t0 < 20:
    time.sleep(0.3)
jobs = ai_jobs(ds["id"])
ok(len(jobs) == 1 and jobs[0]["profile"]["name"] == "ستون‌های AI اسکیما", "کار تولید پس از پایان استخراج خودکار ساخته شد")
jj = wait_job(jobs[0]["id"])
items = j(c.get(f"/api/datasets/{ds['id']}/items"))["items"]
it = j(c.get(f"/api/items/{items[0]['id']}"))
pv = it["preview"]
ok(jj["status"] == "completed" and pv["seo_title"]["flag"] == "ai" and pv["seo_title"]["value"], f"ستون نوع «هوش مصنوعی»: {str(pv['seo_title']['value'])[:40]}")
ok(pv["brand_slug"]["flag"] == "ai" and pv["brand_slug"]["value"].startswith("ai-generated-slug"), f"ستون نگاشت با AI: {pv['brand_slug']['value']}")
ok(pv["vendor_notes"]["flag"] == "ai" and pv["dimensions"]["flag"] == "ai", "ستون دستی و ابعاد (گروه) با AI تکمیل شدند")
ok(isinstance(pv["featured_images"]["value"], list) or pv["featured_images"]["flag"] == "ai", "تصویر با AI ساخته شد (افزودن)")
ok(any(str(v).endswith(".png") and "ai_images" in str(v) for v in (pv["featured_images"]["value"] if isinstance(pv["featured_images"]["value"], list) else [pv["featured_images"]["value"]])),
   "مسیر تصویر تولیدی در ستون تصویر")

print("۴) انتخاب آزاد ستون‌ها در بانک داده (هر نوع مقدار)")
sel = [{"key": "status", "mode": "overwrite"}, {"key": "slug", "mode": "overwrite"}, {"key": "specifications", "mode": "overwrite"},
       {"key": "category_slug", "mode": "overwrite"}, {"key": "user_dos_donts_description", "mode": "overwrite"},
       {"key": "images_gallery", "mode": "add", "count": 2}, {"key": "source_url", "mode": "overwrite"}]
pr = j(c.post("/api/ai/preview", json={"item_id": items[1]["id"], "columns": sel, "images": True}))
ok(pr["ok"] and {"status", "slug", "specifications", "category_slug", "user_dos_donts_description", "images_gallery"} <= set(pr["fields"]) and "source_url" not in pr["fields"],
   f"پیش‌نمایش ستون‌های انتخابی: {sorted(pr['fields'])}")
job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": sel, "scope": "selected", "item_ids": [items[1]["id"]],
                                     "save_as": "قالب ستون‌های آزمون"}))
jj = wait_job(job["id"])
it1 = j(c.get(f"/api/items/{items[1]['id']}"))
p1 = it1["preview"]
ok(jj["status"] == "completed" and all(p1[k]["flag"] == "ai" for k in ("status", "slug", "specifications", "category_slug", "user_dos_donts_description")),
   "ثابت، اسلاگ، مشخصات، نگاشت دسته و بولت‌های گروهی با AI ساخته شدند")
ok(len(p1["images_gallery"]["value"]) >= 2 and p1["source_url"]["flag"] != "ai", "۲ تصویر گالری افزوده شد؛ لینک منبع دست نخورد")
prof = next(p for p in j(c.get("/api/ai/profiles"))["profiles"] if p["name"] == "قالب ستون‌های آزمون")
ok(len(prof["config"]["fields"]) == 5 and prof["config"]["images_list"][0]["target"] == "images_gallery", "انتخاب به‌عنوان قالب ذخیره شد (با تصاویر)")
job2 = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "profile_id": prof["id"], "scope": "selected", "item_ids": [items[2]["id"]]}))
ok(wait_job(job2["id"])["status"] == "completed", "اجرای قالب ذخیره‌شده")
r = j(c.post(f"/api/items/{items[2]['id']}/ai", json={"all_empty": True}))
ok(r["ok"], f"تولید همه‌ی ستون‌های خالی یک محصول: {len(r['generated'])} ستون")
r = j(c.post(f"/api/items/{items[2]['id']}/ai", json={"use_schema": True}))
ok(r["ok"] and "seo_title" in r["generated"], "تولید ستون‌های AI اسکیما برای یک محصول")

print("۵) خروجی: تکمیل ستون‌های خالی با AI پیش از ساخت فایل")
j(c.post("/api/items/ai-clear", json={"dataset_id": ds["id"]}))
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "schema_id": sch["id"], "zip": False, "rembg": False, "align": False,
                                   "ai_fill": {"columns": ["vendor_notes", "seo_title"]}}))
e = wait(f"/api/exports/{ex['id']}", ("completed", "error"), t=120)
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(e["result"]["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
vals = [ws.cell(row=r, column=hdr.index("seo_title") + 1).value for r in range(2, ws.max_row + 1)]
ok(e["status"] == "completed" and all(vals), f"ستون «عنوان سئو» در Excel با AI پر شد ({len(vals)} ردیف)")

print("۶) صف: تولید خودکار پس از استخراج")
q = j(c.post("/api/queue", json={"category_url": FX + "/category/oils", "limit": 2, "schema_id": sch["id"], "duplicates": "rescrape",
                                 "ai_after": {"mode": "empty"}}))
j(c.post("/api/queue/toggle", json={"enabled": True}))
t0 = time.time()
while True:
    qj = next(x for x in j(c.get("/api/queue"))["jobs"] if x["id"] == q["id"])
    if qj["status"] in ("done", "failed") or time.time() - t0 > 120:
        break
    time.sleep(0.5)
ok(qj["status"] == "done" and qj["ai_job_id"], "کار صف: استخراج ← تکمیل همه‌ی ستون‌های خالی با AI")

print("۷) MCP")
from studio import mcp_core  # noqa: E402


class TCApi(mcp_core.StudioAPI):
    def ensure(self):
        return None

    def call(self, method, path, body=None, params=None, timeout=600):
        r = c.request(method, path, json=body if method != "GET" else None, params=params)
        data = r.json()
        if r.status_code >= 400:
            raise mcp_core.ToolError(data.get("error"))
        return data


srv = mcp_core.Server(TCApi())


def mcall(name, args):
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
    if r.get("isError"):
        print(r["content"][0]["text"])
    return None if r.get("isError") else json.loads(r["content"][0]["text"])


g = mcall("get_ai_columns", {"dataset_id": ds["id"]})
ok(g and any(x["key"] == "brand_slug" and x["capable"] for x in g["columns"]), "get_ai_columns")
r = mcall("run_ai_generation", {"dataset_id": ds["id"], "all_empty": True, "scope": "selected", "item_ids": [items[0]["id"]]})
ok(r and wait_job(r["id"])["status"] == "completed", "run_ai_generation با all_empty")
r = mcall("run_ai_generation", {"dataset_id": ds["id"], "columns": [{"key": "brand_slug", "mode": "overwrite"}], "scope": "selected", "item_ids": [items[0]["id"]]})
ok(r and wait_job(r["id"])["status"] == "completed", "run_ai_generation با ستون انتخابی")
print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
