"""تست قابلیت‌های نسخه‌ی ۱.۱: اتصال هوش مصنوعی (OpenAI-compatible، Anthropic، Gemini)، قواعد متن، صف و زمان‌بندی."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-feat").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
for m in (ROOT / "data" / "models").glob("*.onnx"):
    os.symlink(m, DATA / "models" / m.name)
os.environ["CATALOG_STUDIO_DATA"] = str(DATA)
os.environ["CATALOG_STUDIO_ALLOWED_HOSTS"] = "testserver"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fixture_site  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from studio.api import create_app  # noqa: E402

threading.Thread(target=fixture_site.serve, args=(8899,), daemon=True).start()
time.sleep(0.5)
c = TestClient(create_app())
BASE = "http://127.0.0.1:8899"
OUT = DATA / "output"


def ok(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        raise SystemExit(1)


def j(r):
    if r.status_code >= 400:
        print(r.text)
    r.raise_for_status()
    return r.json()


def wait(fn, cond, timeout=240, step=0.7):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if cond(v):
            return v
        time.sleep(step)
    raise SystemExit(f"timeout: {v}")


j(c.put("/api/settings", json={"delay_min_ms": 20, "delay_max_ms": 40, "output_root": str(OUT), "browser_channel": "chromium",
                               "max_retries": 1, "queue_enabled": False}))
shop = j(c.post("/api/sources", json={"config": {
    "key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
    "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page", "start": 1}},
    "product": {"mode": "http"}, "fields": [
        {"key": "gallery", "strategies": [{"type": "css", "selector": ".product-gallery img", "attr": "src", "all": True}], "transforms": ["strip_query"]}]}}))
dk = j(c.post("/api/sources", json={"config": {
    "key": "fixture-dk", "name": "API آزمایشی", "domains": ["localhost"], "product_id_pattern": r"dkp-(\d+)",
    "listing": {"mode": "api", "api": {"url": BASE + "/dk/v1/categories/{slug}/search/?page={page}", "params_from_url": {"slug": r"category-([^/?#]+)"},
                "items_path": "data.products", "item_fields": {"id": "id"}, "url_template": BASE + "/dk-product/dkp-{id}/",
                "total_pages_path": "data.pager.total_pages", "total_items_path": "data.pager.total_items", "category_label_path": "data.category.title_fa"}},
    "product": {"mode": "api", "api": {"url": BASE + "/dk/v2/product/{id}/", "params_from_url": {"id": r"dkp-(\d+)"}}},
    "fields": json.load(open(ROOT / "studio/defaults/sources/01_digikala.json", encoding="utf-8"))["fields"]}}))
schema_id = j(c.get("/api/schemas"))[0]["id"]
schema2 = j(c.post(f"/api/schemas/{schema_id}/duplicate", json={}))

print("۱) صف و زمان‌بندی")
future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
q1 = j(c.post("/api/queue", json={"category_url": BASE + "/category/oils", "source_id": shop["id"], "limit": 4, "schema_id": schema_id,
                                  "policies": {"not_found": "skip", "missing_fields": "continue_partial"}, "title": "نوبت اول"}))
q2 = j(c.post("/api/queue", json={"category_url": "http://localhost:8899/search/category-engine-oil/", "limit": 3,
                                  "schema_id": schema2["id"], "repeat_hours": 24, "title": "نوبت دوم"}))
q3 = j(c.post("/api/queue", json={"category_url": BASE + "/category/oils", "source_id": shop["id"], "limit": 2, "scheduled_at": future, "title": "زمان‌بندی‌شده"}))
ok(q2["source"]["key"] == "fixture-dk" and q3["scheduled_at"], "سه کار در صف (تشخیص منبع و زمان شروع)")
time.sleep(4)
ok(all(x["status"] == "queued" for x in j(c.get("/api/queue"))["jobs"]), "با صف خاموش هیچ کاری شروع نشد")
j(c.post("/api/queue/toggle", json={"enabled": True}))
st = wait(lambda: j(c.get("/api/queue"))["jobs"], lambda js: any(x["id"] == q1["id"] and x["status"] == "running" for x in js), 30)
ok(next(x for x in st if x["id"] == q2["id"])["status"] == "queued", "نوبت اول در حال اجرا و نوبت دوم منتظر")
st = wait(lambda: j(c.get("/api/queue"))["jobs"], lambda js: next(x for x in js if x["id"] == q2["id"])["status"] == "done", 240)
a = next(x for x in st if x["id"] == q1["id"])
b = next(x for x in st if x["id"] == q2["id"])
ok(a["status"] == "done" and a["dataset"]["counts"]["done"] + a["dataset"]["counts"]["partial"] == 4, "نوبت اول: ۴ محصول با اسکیمای اول")
ok(b["dataset"]["schema_id"] == schema2["id"] and b["dataset"]["counts"]["done"] == 3, "نوبت دوم پس از پایان نوبت اول: ۳ محصول با اسکیمای دوم")
ok(a["finished_at"] <= b["started_at"], "اجرای ترتیبی (شروع دوم بعد از پایان اول)")
rep = [x for x in st if x["category_url"].endswith("category-engine-oil/") and x["status"] == "queued"]
ok(len(rep) == 1 and rep[0]["scheduled_at"] > datetime.now(timezone.utc).isoformat(), "تکرار دوره‌ای: اجرای بعدی ۲۴ ساعت بعد زمان‌بندی شد")
ok(next(x for x in st if x["id"] == q3["id"])["status"] == "queued", "کار زمان‌بندی‌شده تا زمانش نرسیده اجرا نشد")
j(c.post(f"/api/queue/{rep[0]['id']}/skip", json={}))
j(c.post("/api/queue/toggle", json={"enabled": False}))
ds_shop, ds_dk = a["dataset_id"], b["dataset_id"]

print("۲) اتصال‌های هوش مصنوعی")
provs = {}
for kind, base, mode in (("openai", BASE + "/ai/openai/v1", "images_api"), ("anthropic", BASE + "/ai/anthropic", "none"),
                         ("gemini", BASE + "/ai/gemini/v1beta", "gemini"), ("openai", BASE + "/ai/router/v1", "chat_modalities")):
    p = j(c.post("/api/ai/providers", json={"name": f"{kind}-{mode}", "kind": kind, "base_url": base, "api_key": "test-key",
                                            "text_model": "mock-text", "image_model": "mock-image", "image_mode": mode}))
    t = j(c.post(f"/api/ai/providers/{p['id']}/test", json={}))
    ok(t.get("ok") and t["reply"].startswith("OK") and "api_key" not in p and p["has_key"], f"اتصال {kind}/{mode}: پاسخ «{t.get('reply')}»، کلید پنهان")
    provs[f"{kind}-{mode}"] = p
m = j(c.post(f"/api/ai/providers/{provs['gemini-gemini']['id']}/models", json={}))
ok("mock-gemini" in m["models"], "دریافت فهرست مدل‌ها")
bad = j(c.post("/api/ai/providers", json={"name": "bad", "kind": "openai", "base_url": BASE + "/ai/openai/v1", "api_key": "wrong", "text_model": "x"}))
t = j(c.post(f"/api/ai/providers/{bad['id']}/test", json={}))
ok(not t["ok"] and "401" in t["error"], "کلید نادرست: پیام خطای روشن")
for name in ("openai-images_api", "gemini-gemini", "openai-chat_modalities"):
    t = j(c.post(f"/api/ai/providers/{provs[name]['id']}/test-image", json={}))
    ok(t["ok"] and t["image"].startswith("data:image/png"), f"تولید تصویر: {name}")

print("۳) قواعد متن")
rules = j(c.get("/api/rules"))["rules"]
r_store = next(r for r in rules if r["action"] == "remove" and r["target"] == "*")
j(c.put(f"/api/rules/{r_store['id']}", json={"enabled": True}))
j(c.post("/api/rules", json={"name": "حذف «شماره» از عنوان", "target": "title", "action": "regex", "find": r"\s*شماره\s*\d+", "value": ""}))
j(c.post("/api/rules", json={"name": "حذف ردیف وزن", "target": "specifications", "action": "drop_spec", "find": "وزن"}))
j(c.post("/api/rules", json={"name": "پسوند توضیح کوتاه", "target": "short_description", "action": "append", "value": " — مگا کارز"}))
t = j(c.post("/api/rules/test", json={"text": "خرید از دیجی‌کالا با ارسال سریع", "target": "long_description"}))
ok(t["output"] == "خرید از با ارسال سریع", f"آزمایش قاعده: «{t['output']}»")
items = j(c.get(f"/api/datasets/{ds_dk}/items"))["items"]
it = j(c.get(f"/api/items/{items[0]['id']}"))
ok("شماره" not in it["preview"]["title"]["value"], f"عنوان پس از قاعده: {it['preview']['title']['value']}")
ok("وزن" not in json.dumps(it["preview"]["specifications"]["value"], ensure_ascii=False), "ردیف «وزن» از مشخصات حذف شد")
ok("شماره" in it["data"]["title"], "داده‌ی اصلی دست‌نخورده ماند (غیرمخرب)")

print("۴) قالب تولید و پیش‌نمایش")
prof = j(c.get("/api/ai/profiles"))["profiles"][0]
cfg = prof["config"]
cfg["provider_id"] = provs["openai-images_api"]["id"]
cfg["model"] = "mock-text"
cfg["seo_keywords"] = "روغن موتور بهران"
cfg["fields"][4]["enabled"] = True   # dimensions: فقط کلیدهای خالی
cfg["images"] = {**cfg["images"], "enabled": True, "target": "images_gallery", "mode": "add", "count": 1, "use_reference": True}
j(c.put(f"/api/ai/profiles/{prof['id']}", json={"name": prof["name"], "description": "", "config": cfg}))
pv = j(c.post("/api/ai/preview", json={"profile_id": prof["id"], "item_id": items[0]["id"], "images": True}))
ok(pv["ok"], f"پیش‌نمایش: {pv.get('error', '')}")
f = pv["fields"]
ok(set(f) >= {"short_description", "long_description", "user_dos_donts_description", "vendor_dos_donts_description", "dimensions", "images_gallery"},
   f"فیلدهای تولیدشده: {sorted(f)}")
ok(isinstance(f["user_dos_donts_description"]["after"], dict) and len(f["user_dos_donts_description"]["after"]["dos"]) == 3, "بایدها/نبایدها به‌شکل سه گروه بولت")
dims = f["dimensions"]["after"]
ok(dims["item_weight"] == "3500" or dims["item_weight"] == "", f"ابعاد: مقدار استخراج‌شده حفظ شد ({dims['item_weight']})")
ok(dims["packaging_length"] == "25" and dims["item_height"] == "123", "فقط کلیدهای خالی ابعاد پر شد")
ok("کلیدواژه‌های سئو" in pv["prompt"] and "بهران" in pv["prompt"], "کلیدواژه‌ی سئو در پرامپت")
ok(f["images_gallery"]["after"][0].startswith("data:image/png"), "پیش‌نمایش تصویر تولیدشده")

print("۵) تولید گروهی روی بانک داده (سه نوع سرویس‌دهنده)")
for name, did in (("openai-images_api", ds_dk), ("anthropic-none", ds_shop)):
    cfg2 = dict(cfg)
    cfg2["provider_id"] = provs[name]["id"]
    cfg2["images"] = {**cfg["images"], "enabled": name != "anthropic-none"}
    pr = j(c.post("/api/ai/profiles", json={"name": f"قالب {name}", "config": cfg2}))
    job = j(c.post("/api/ai/jobs", json={"dataset_id": did, "profile_id": pr["id"], "scope": "all"}))
    job = wait(lambda: next(x for x in j(c.get("/api/ai/jobs")) if x["id"] == job["id"]), lambda x: x["status"] in ("completed", "error"), 120)
    ok(job["status"] == "completed" and job["failed"] == 0 and job["progress_done"] == job["progress_total"] > 0,
       f"{name}: {job['progress_done']} محصول، {job['tokens']} توکن")
gm = dict(cfg)
gm["provider_id"] = provs["gemini-gemini"]["id"]
gm["batch"] = False
gm["images"] = {**cfg["images"], "enabled": False}
pr = j(c.post("/api/ai/profiles", json={"name": "gemini per-field", "config": gm}))
r = j(c.post(f"/api/items/{items[1]['id']}/ai", json={"profile_id": pr["id"]}))
ok(r["ok"] and "long_description" in r["generated"], f"Gemini، هر فیلد یک درخواست: {r.get('generated') or r.get('error')}")

it = j(c.get(f"/api/items/{items[0]['id']}"))
pvw = it["preview"]
ok(pvw["long_description"]["flag"] == "ai" and "دیجی‌کالا" not in pvw["long_description"]["value"], "قاعده‌ی حذف روی متن AI هم اعمال شد")
ok(pvw["short_description"]["value"].endswith("— مگا کارز"), "قاعده‌ی افزودن روی توضیح کوتاه")
gal = pvw["images_gallery"]["value"]
ok(len(gal) == 3 and str(gal[-1]).endswith(".png") and Path(gal[-1]).exists(), "تصویر AI به گالری اضافه شد (حالت add)")
j(c.put(f"/api/items/{items[0]['id']}", json={"overrides": {"short_description": "متن دستی من"}}))
it = j(c.get(f"/api/items/{items[0]['id']}"))
ok(it["preview"]["short_description"]["value"] == "متن دستی من", "ویرایش دستی بر خروجی AI مقدم است")

print("۶) خروجی نهایی")
ex = j(c.post("/api/exports", json={"dataset_ids": [ds_dk], "schema_id": schema_id, "images": True, "rembg": False, "zip": False}))
e = wait(lambda: j(c.get(f"/api/exports/{ex['id']}")), lambda x: x["status"] in ("completed", "error"), 120)
ok(e["status"] == "completed", f"خروجی: {e.get('error') or e['result']['rows']} ردیف")
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(e["result"]["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
row = {hdr[i]: ws.cell(row=2, column=i + 1).value for i in range(len(hdr))}
ok(row["long_description"].startswith("متن یکتای تولیدشده"), "توضیح بلند یکتا در Excel")
ok(row["user_dos_donts_description.dos"].startswith("• نکته‌ی 1"), "بولت‌های تولیدشده در ستون جدا")
gal = row["images_gallery"].split(",")
ok(len(gal) == 3 and gal[-1].endswith("gallery_3.png") and (OUT / gal[-1]).exists(), f"تصویر AI در پوشه‌ی محصول: {gal[-1]}")
j(c.post("/api/items/ai-clear", json={"dataset_id": ds_dk}))
it = j(c.get(f"/api/items/{items[2]['id']}"))
ok(it["preview"]["long_description"]["flag"] != "ai", "بازگشت به داده‌ی استخراج‌شده با حذف خروجی‌های AI")
print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
