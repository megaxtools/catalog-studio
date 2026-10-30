"""تست نسخه‌ی ۱.۶.۱: مقدار پیش‌فرض ستون‌های اسکیما (یک‌خطی، چندخطی، بولت، گروه) و نحوه‌ی اعمال آن."""
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
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-def161").resolve()
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

print("۱) اسکیما با مقادیر پیش‌فرض")
PRE = "پیش از خرید، سازگاری با خودرو را بررسی کنید.\nپس از خرید، فاکتور را نگه دارید.\n\nپاراگراف دوم."
sc = j(c.post("/api/schemas", json={"name": "پیش‌فرض‌ها", "columns": [
    {"key": "title", "label": "عنوان", "kind": "scraped", "from": "title", "input": "text"},
    {"key": "category_slug", "label": "دسته", "kind": "mapping", "map": "category", "default": "engine-oil"},
    {"key": "slug_fixed", "label": "اسلاگ ثابت", "kind": "auto", "generator": "slug", "default": "fixed-slug", "default_mode": "always"},
    {"key": "user_dos", "label": "بایدها و نبایدها", "kind": "manual", "input": "bullet_groups",
     "groups": [{"key": "dos", "label": "بایدها"}, {"key": "donts", "label": "نبایدها"}, {"key": "pre_post_purchase", "label": "پیش و پس از خرید"}],
     "default": {"dos": ["بایدِ ثابت ۱", "بایدِ ثابت ۲"], "donts": "نبایدِ ثابت", "pre_post_purchase": ["نکته‌ی خرید"]}},
    {"key": "purchase_text", "label": "متن خرید", "kind": "manual", "input": "longtext", "default": PRE},
    {"key": "notes", "label": "بولت‌ها", "kind": "scraped", "from": "title", "input": "bullets", "default": "- نکته‌ی ثابت پایانی", "default_mode": "append"},
    {"key": "long", "label": "توضیح", "kind": "scraped", "from": "long_description", "input": "longtext", "default": "پاراگراف ثابت پایانی.", "default_mode": "append"},
    {"key": "intro", "label": "مقدمه", "kind": "scraped", "from": "title", "input": "text", "default": "خرید", "default_mode": "prepend"},
    {"key": "dims", "label": "ابعاد", "kind": "scraped", "from": "dimensions", "input": "group", "subkeys": ["item_weight", "packaging_weight"],
     "default": {"packaging_weight": 500}},
    {"key": "count", "label": "تعداد", "kind": "manual", "input": "number", "default": "12"},
    {"key": "warranty", "label": "گارانتی", "kind": "manual", "input": "text", "default": "گارانتی اصالت", "ai_mode": "fill_missing"},
    {"key": "fixed_note", "label": "ثابت", "kind": "manual", "input": "text", "default": "متن ثابت", "default_mode": "always", "ai_mode": "fill_missing"},
    {"key": "extra", "label": "اضافه", "kind": "manual", "input": "text"},
    {"key": "tags", "label": "برچسب‌ها", "kind": "constant", "input": "bullets", "value": "روغن\nموتور"}]}))
j(c.put(f"/api/datasets/{ds['id']}", json={"schema_id": sc["id"]}))
it = j(c.get(f"/api/items/{items[0]['id']}"))
pv = {k: v["value"] for k, v in it["preview"].items()}
fl = {k: v["flag"] for k, v in it["preview"].items()}
ok(pv["category_slug"] == "engine-oil" and fl["category_slug"] == "", "یک‌خطی (اسلاگ دسته‌ی نگاشت‌نشده) ← پیش‌فرض، بدون هشدار")
ok(pv["slug_fixed"] == "fixed-slug", "«همیشه همین» جای مقدار خودکار را می‌گیرد")
ok(pv["user_dos"] == {"dos": ["بایدِ ثابت ۱", "بایدِ ثابت ۲"], "donts": ["نبایدِ ثابت"], "pre_post_purchase": ["نکته‌ی خرید"]}, "گروه بولت‌ها (بایدها، نبایدها، پیش و پس از خرید)")
ok(pv["purchase_text"] == PRE, "متن چندخطی و چندپاراگرافی دست‌نخورده")
ok(pv["notes"][-1] == "نکته‌ی ثابت پایانی" and len(pv["notes"]) == 2, "بولت: افزودن به انتهای مقدار استخراجی")
ok(pv["long"].endswith("\n\nپاراگراف ثابت پایانی.") and len(pv["long"]) > 40, "متن بلند: پاراگراف ثابت در انتها")
ok(pv["intro"].startswith("خرید ") and items[0]["title"] in pv["intro"], "متن کوتاه: افزودن به ابتدا")
ok(pv["dims"]["packaging_weight"] == 500 and pv["dims"].get("item_weight"), "گروه کلید/مقدار: فقط کلید خالی پر شد")
ok(pv["count"] == 12 and pv["tags"] == ["روغن", "موتور"], "عدد و مقدار ثابت چندخطی با نوع درست")

print("۲) ورود دستی و ویرایش بر پیش‌فرض مقدم است")
j(c.put(f"/api/items/{items[1]['id']}", json={"manual": {"user_dos": {"dos": ["دستی"], "donts": [], "pre_post_purchase": []}, "fixed_note": "دستی"},
                                               "overrides": {"slug_fixed": "edited-slug"}}))
pv1 = {k: v["value"] for k, v in j(c.get(f"/api/items/{items[1]['id']}"))["preview"].items()}
ok(pv1["user_dos"]["dos"] == ["دستی"] and pv1["user_dos"]["donts"] == ["نبایدِ ثابت"], "ورود دستی محصول مقدم است و بخش‌های خالی از پیش‌فرض پر می‌شوند")
ok(pv1["fixed_note"] == "دستی" and pv1["slug_fixed"] == "edited-slug", "ورود دستی و ویرایش بر «همیشه همین» مقدم است")

print("۳) هوش مصنوعی و پیش‌فرض")
job = j(c.post("/api/ai/jobs", json={"dataset_id": ds["id"], "columns": [{"key": "warranty", "mode": "fill_missing"}, {"key": "fixed_note", "mode": "fill_missing"}]}))
jj = wait_job(job["id"])
pv2 = {k: v["value"] for k, v in j(c.get(f"/api/items/{items[2]['id']}"))["preview"].items()}
ok(jj["status"] == "completed" and pv2["warranty"] and pv2["warranty"] != "گارانتی اصالت", "«اگر خالی بود»: هوش مصنوعی تولید می‌کند و پیش‌فرض فقط جایگزین نبودِ مقدار است")
ok(pv2["fixed_note"] == "متن ثابت", "ستون «همیشه همین» با هوش مصنوعی بازنویسی نمی‌شود")

print("۴) خروجی و کاتالوگ نهایی")
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "formats": ["json", "xlsx"], "schema_id": sc["id"], "images": False, "zip": False}))
e = wait(f"/api/exports/{ex['id']}", ("completed", "error"), t=120)
recs = json.loads(Path(e["result"]["files"]["json"]).read_text(encoding="utf-8"))
r0 = recs[0]
ok(r0["user_dos"]["donts"] == ["نبایدِ ثابت"] and r0["purchase_text"] == PRE and r0["category_slug"] == "engine-oil" and r0["count"] == 12,
   "JSON نهایی با مقادیر پیش‌فرض و ساختار درست")
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(e["result"]["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
cell = ws.cell(row=2, column=hdr.index("purchase_text") + 1).value
ok(cell == PRE, "Excel: متن چندخطی با شکستن خط‌ها")
sch = j(c.get(f"/api/schemas/{sc['id']}"))
for col in sch["columns"]:
    if col["key"] == "extra":
        col["default"] = "مقدار پیش‌فرض تازه"
j(c.put(f"/api/schemas/{sc['id']}", json={"name": sch["name"], "columns": sch["columns"]}))
b = j(c.post(f"/api/catalogs/{ex['id']}/rows/bulk", json={"apply_default": ["extra"]}))
rows = j(c.get(f"/api/catalogs/{ex['id']}/rows?size=50"))["rows"]
ok(b["updated"] == 6 and all(r["v"]["extra"] == "مقدار پیش‌فرض تازه" for r in rows), "اعمال پیش‌فرض تازه‌ی اسکیما روی خروجی ساخته‌شده")
b = j(c.post(f"/api/catalogs/{ex['id']}/rows/bulk", json={"apply_default": ["notes"], "default_mode": "append"}))
ok(b["updated"] == 0, "اعمال دوباره تکرار ایجاد نمی‌کند")
print("همه‌ی آزمون‌ها موفق بود ✅")
