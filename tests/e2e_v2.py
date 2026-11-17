"""تست نسخه‌ی ۲: ماژول‌ها، داده‌های مرجع، خودروها و سازگاری، ویرایشگر داده (بانک تمیز، محصولات، تصاویر، ویرایشگر تصویر)،
ریویژن‌ها، کنترل کیفیت، تکراری‌ها، کاتالوگ و انتشارهای نسخه‌دار، پشتیبان‌گیری و انتقال از نسخه‌ی ۱."""
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
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-v2").resolve()
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

WB = DATA / "workbench"


def wait_bank(bid, t=180):
    t0 = time.time()
    while time.time() - t0 < t:
        b = j(c.get(f"/api/wb/banks/{bid}"))
        if b["status"] in ("completed", "error", "paused"):
            return b
        time.sleep(0.3)
    raise SystemExit("bank timeout")


def wait_release(rid, t=180):
    t0 = time.time()
    while time.time() - t0 < t:
        r = j(c.get(f"/api/cat/releases/{rid}"))
        if r["status"] in ("completed", "error"):
            return r
        time.sleep(0.3)
    raise SystemExit("release timeout")


print("۱) ماژول‌ها و زیرساخت")
mods = {m["id"]: m for m in j(c.get("/api/modules"))}
ok({"core", "vehicles", "image_editor", "quality", "dedup", "ai", "scraper"} <= set(mods) and all(m["status"] == "ok" for m in mods.values()), f"{len(mods)} ماژول بارگذاری شد")
ok(mods["vehicles"]["healthy"] and "186 برند" in mods["vehicles"]["health"], "بانک خودروها با ۱۸۶ برند بارگذاری شد")
r = c.put("/api/modules/core", json={"enabled": False})
ok(r.status_code == 400, "ماژول هسته غیرفعال نمی‌شود")
j(c.put("/api/modules/scraper", json={"enabled": False}))
r = c.post("/api/datasets", json={"category_url": FX + "/category/oils", "limit": 2})
ok(r.status_code == 503 and "غیرفعال" in r.json()["error"], "مسیرهای ماژول غیرفعال پاسخ ۵۰۳ می‌دهند (استخراج خاموش)")
r = c.put("/api/modules/queue", json={"enabled": True})
ok(not j(c.get("/api/modules"))[[m["id"] for m in j(c.get("/api/modules"))].index("queue")]["enabled"], "وابستگی: صف بدون استخراج فعال نیست")
j(c.put("/api/modules/scraper", json={"enabled": True}))
ok(j(c.get("/api/users"))[0]["role"] == "admin", "کاربر مدیر به‌طور پیش‌فرض")
ok(j(c.get("/api/health"))["version"].startswith("2."), "نسخه‌ی ۲")

print("۲) داده‌های مرجع و خودروها")
brand = j(c.post("/api/ref/brand", json={"name": "کاسپین", "name_en": "Caspian", "aliases": ["caspian oil"]}))
ok(brand["slug"] == "caspian", "برند مرجع با اسلاگ انگلیسی")
r = c.post("/api/ref/brand", json={"name": "تکراری", "slug": "caspian"})
ok(r.status_code == 400, "اسلاگ تکراری پذیرفته نمی‌شود")
cat_root = j(c.post("/api/ref/category", json={"name": "روانکارها", "name_en": "Lubricants"}))
cat = j(c.post("/api/ref/category", json={"name": "روغن موتور", "name_en": "Engine Oil", "parent_id": cat_root["id"]}))
ok(cat["slug"] == "engine-oil" and any(x["path"] == "روانکارها › روغن موتور" for x in j(c.get("/api/ref/category"))), "دسته‌بندی درختی")
imp = j(c.post("/api/ref/brand/import", json={"rows": [{"name": "بهران", "name_en": "Behran"}, {"name": "کاسپین", "name_en": "Caspian"}]}))
ok(imp["added"] == 1 and imp["updated"] == 1, "ورود گروهی برندها (افزودن و به‌روزرسانی)")
peugeot = next(b for b in j(c.get("/api/vehicles/brands?q=پژو")) if b["name"] == "پژو")
tree = j(c.get(f"/api/vehicles/brands/{peugeot['id']}/tree"))
m206 = next(m for m in tree["models"] if m["name"] == "206")
ok(peugeot["slug"] == "peugeot" and len(m206["trims"]) >= 6, "درخت پژو ← 206 ← تیپ‌ها")
t2 = next(t for t in m206["trims"] if t["name"] == "تیپ 2")
nv = j(c.post("/api/vehicles/normalize", json={"value": {"items": [{"t": "brand", "id": peugeot["id"]}, {"t": "trim", "id": t2["id"]}, {"t": "model", "id": m206["id"]}]}}))
ok(nv["value"]["items"] == [{"t": "brand", "id": peugeot["id"]}], "انتخاب برند همه‌ی مدل‌ها و تیپ‌هایش را می‌پوشاند")
r = c.post("/api/vehicles/normalize", json={"value": {"items": [{"t": "trim", "id": 999999}]}})
ok(r.status_code == 400, "فقط خودروهای بانک خودروها قابل انتخاب‌اند")
s = j(c.post("/api/vehicles/suggest", json={"text": "لنت ترمز جلو مناسب پژو 206 تیپ 2"}))
ok(s["value"]["items"] == [{"t": "trim", "id": t2["id"]}] and s["confidence"] >= 85, "تطبیق متن با تیپ خودرو")
ok(j(c.post("/api/vehicles/suggest", json={"text": "مناسب تمام خودروها"}))["value"] == {"all": True}, "«همه‌ی خودروها» از متن")
newm = j(c.post("/api/vehicles/model", json={"brand_id": peugeot["id"], "name": "408 آزمایشی"}))
ok(newm["slug"] and newm["auto_en"] == 1, "افزودن مدل با اسلاگ خودکار")
ok(c.delete(f"/api/vehicles/brand/{peugeot['id']}").status_code == 400, "حذف برند دارای مدل ممنوع است")
ai_en = j(c.post("/api/vehicles/ai-english", json={"level": "model", "ids": [newm["id"]], "update_slugs": True}))
ok(ai_en["model"]["updated"] == 1, "تکمیل نام انگلیسی با هوش مصنوعی")

print("۳) بانک تمیز از داده‌ی خام")
for c_ in j(c.get("/api/schemas")):
    if c_["is_default"]:
        mega = c_
ok(any(col["key"] == "compatible_vehicles" and col["kind"] == "ref" for col in mega["columns"]), "ستون اجباری «خودروهای سازگار» به اسکیمای مگا کارز اضافه شد")
bank = j(c.post("/api/wb/banks", json={"dataset_ids": [ds["id"]], "schema_id": mega["id"], "title": "روغن‌ها — تمیز", "rembg": False,
                                      "align": {"margin": 60, "canvas_w": 600, "canvas_h": 600}}))
b = wait_bank(bank["id"])
ok(b["status"] == "completed" and b["counts"]["total"] == 6, f"۶ محصول وارد بانک تمیز شد ({b['step']})")
prods = j(c.get(f"/api/wb/products?bank_id={bank['id']}&size=50"))["rows"]
p1 = prods[0]
ok(p1["brand"] and p1["brand"]["slug"] == "caspian" and p1["category"] and p1["category"]["slug"] == "engine-oil", "برند و دسته از فهرست مرجع تطبیق داده شدند")
ok(p1["images"] and p1["images"][0]["w"] == 600 and p1["compat_info"]["all"], "تصاویر ترازشده (۶۰۰×۶۰۰) و سازگاری پیش‌فرض «همه‌ی خودروها»")
full = j(c.get(f"/api/wb/products/{p1['id']}"))
ok(full["revisions"] == 1 and full["sources"][0]["item_id"], "نسخه‌ی ۱ محصول = ورود از داده‌ی خام، با منبع خام")
raw_src = j(c.get(f"/api/wb/products/{p1['id']}/sources"))
ok(raw_src[0]["data"]["title"], "داده‌ی خام (نسخه‌ی صفر) در دسترس است")

print("۴) ویرایش و ریویژن")
pid1 = p1["id"]
up = j(c.put(f"/api/wb/products/{pid1}", json={"values": {"short_description": "توضیح کوتاه ویرایش‌شده برای این روغن موتور."},
                                               "compat": {"items": [{"t": "trim", "id": t2["id"]}]}, "title": "روغن موتور کاسپین ویرایش‌شده"}))
ok(up["title"] == "روغن موتور کاسپین ویرایش‌شده" and up["v"]["short_description"].startswith("توضیح کوتاه") and up["compat_info"]["items"][0]["label"] == "پژو 206 تیپ 2", "ویرایش عنوان، فیلد و سازگاری")
ok(up["edited"].get("short_description") == "ui" and up["edited"].get("compat") == "ui", "علامت «ویرایش‌شده» با کننده")
r = c.put(f"/api/wb/products/{pid1}", json={"slug": "اسلاگ فارسی"})
ok(r.status_code == 400, "اسلاگ فارسی پذیرفته نمی‌شود")
r = c.put(f"/api/wb/products/{pid1}", json={"brand": 99999})
ok(r.status_code == 400, "برند خارج از فهرست مرجع پذیرفته نمی‌شود")
revs = j(c.get(f"/api/revisions?entity=product&entity_id={pid1}"))
ok(len(revs) == 2 and {"title", "compat", "short_description"} <= set(revs[0]["fields"]), "ریویژن ۲ با فهرست فیلدهای تغییرکرده")
cmp_ = j(c.get(f"/api/revisions/compare?entity=product&entity_id={pid1}&a=1&b=2"))
ok(any(x["field"] == "title" for x in cmp_["changes"]) and any(x["field"].startswith("values.short_description") for x in cmp_["changes"]), "مقایسه‌ی دو نسخه (قبل و بعد هر فیلد)")
j(c.post("/api/revisions/restore", json={"entity": "product", "entity_id": pid1, "rev": 1}))
back = j(c.get(f"/api/wb/products/{pid1}"))
ok(back["title"] == p1["title"] and back["compat_info"]["all"] and back["revisions"] == 3, "بازگردانی به نسخه‌ی ۱ (به‌صورت نسخه‌ی ۳)")

print("۵) تصاویر و ویرایشگر تصویر")
buf = io.BytesIO()
Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, "PNG")
du = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
pv = j(c.post(f"/api/wb/products/{pid1}/images/upload", json={"data_url": du, "name": "red.png", "rembg": False}))
n0 = len(pv["images"])
new_img = pv["images"][-1]
ok(new_img["final_url"] and new_img["w"] == 600, "بارگذاری تصویر و ترازبندی خودکار")
recipe = {"rotate": 90, "flip_h": True, "crop": {"x": 10, "y": 10, "w": 200, "h": 300}, "adjust": {"hue": 120, "saturation": 100, "brightness": 100, "contrast": 100},
          "erase": [{"size": 40, "points": [[50, 50], [120, 120]]}]}
pv = j(c.post(f"/api/wb/products/{pid1}/images/edit", json={"image_id": new_img["id"], "recipe": recipe}))
im = next(x for x in pv["images"] if x["id"] == new_img["id"])
from studio import workbench as _wb  # noqa: E402
raw_im = next(x for x in _wb.get_product(pid1)["images"] if x["id"] == new_img["id"])
ed = Image.open(WB / raw_im["edit"]).convert("RGBA")
px = ed.getpixel((150, 250))
ok(im["edited"] and ed.size == (200, 300) and px[1] > px[0], f"ویرایش غیرمخرب: چرخش، برش، تغییر رنگ (قرمز ← سبز {px[:3]})")
ok(ed.getpixel((45, 45))[3] == 0 or ed.getpixel((60, 60))[3] == 0, "پاک‌کن: ناحیه‌ی پاک‌شده شفاف است")
ok((WB / raw_im["raw"]).exists() and Image.open(WB / raw_im["raw"]).size == (400, 300), "فایل اصلی دست‌نخورده می‌ماند")
pv = j(c.post(f"/api/wb/products/{pid1}/images/make_feature", json={"image_id": new_img["id"]}))
ok(pv["images"][0]["id"] == new_img["id"], "تصویر شاخص شد")
pv = j(c.post(f"/api/wb/products/{pid1}/images/reset_edit", json={"image_id": new_img["id"]}))
ok(not pv["images"][0]["edited"], "برگرداندن ویرایش تصویر")
pv = j(c.post(f"/api/wb/products/{pid1}/images/delete", json={"image_id": new_img["id"]}))
ok(len(pv["images"]) == n0 - 1, "حذف تصویر از محصول")
pv = j(c.post(f"/api/wb/products/{pid1}/images/generate", json={"prompt": "عکس محصول"}))
ok(len(pv["images"]) == n0 and pv["images"][-1]["origin"] == "ai", "ساخت تصویر با هوش مصنوعی")
j(c.put("/api/modules/image_editor", json={"enabled": False}))
r = c.post(f"/api/wb/products/{pid1}/images/edit", json={"image_id": pv["images"][0]["id"], "recipe": recipe})
ok(r.status_code == 400 and "غیرفعال" in r.json()["error"], "ویرایشگر تصویر خاموش: ویرایش رد می‌شود، بقیه کار می‌کند")
j(c.put("/api/modules/image_editor", json={"enabled": True}))

print("۶) کیفیت، بازبینی و عملیات گروهی")
q = full["quality_detail"]
ok(isinstance(full["quality"], int) and "score" in q, f"امتیاز کیفیت محاسبه شد ({full['quality']})")
bad = next((p for p in prods if not p["title"] or len(p["title"]) < 10 or p["quality"] < 50), None)
gate = c.put(f"/api/wb/products/{prods[1]['id']}", json={"brand": None})
r = c.put(f"/api/wb/products/{prods[1]['id']}", json={"status": "approved"})
ok(r.status_code == 400 and "برند" in r.json()["error"], "تأیید محصول بدون برند ممکن نیست (دروازه‌ی کیفیت)")
j(c.put(f"/api/wb/products/{prods[1]['id']}", json={"brand": brand["id"]}))
bk = j(c.post("/api/wb/products/bulk", json={"bank_id": bank["id"], "filter": {"bank_id": bank["id"]},
                                             "set": {"vendor_notes": "یادداشت مشترک کسب‌وکار"}, "append": {"long_description": "\nپاراگراف ثابت پایانی."}}))
ok(bk["updated"] == 6, "ویرایش گروهی روی همه‌ی نتیجه‌های فیلتر")
bk = j(c.post("/api/wb/products/bulk", json={"ids": [p["id"] for p in prods[:3]], "compat": {"mode": "add", "value": {"items": [{"t": "model", "id": m206["id"]}]}}}))
p2 = j(c.get(f"/api/wb/products/{prods[1]['id']}"))
ok(bk["updated"] == 3 and p2["compat_info"]["items"][0]["display"].startswith("پژو 206"), "سازگاری گروهی (افزودن مدل)")
bk = j(c.post("/api/wb/products/bulk", json={"filter": {"bank_id": bank["id"]}, "status": "approved"}))
appr = j(c.get(f"/api/wb/products?bank_id={bank['id']}&status=approved"))["total"]
ok(appr >= 4, f"تأیید گروهی ({appr} محصول تأیید شد، {len(bk['errors'])} به‌دلیل کیفیت رد شد)")
aij = j(c.post(f"/api/wb/banks/{bank['id']}/ai", json={"columns": [{"key": "short_description", "mode": "overwrite"}], "ids": [prods[2]["id"], prods[3]["id"]]}))
jj = wait_job(aij["id"])
p3 = j(c.get(f"/api/wb/products/{prods[2]['id']}"))
ok(jj["status"] == "completed" and "متن یکتای" in p3["v"]["short_description"] and p3["edited"]["short_description"] == "ai", "هوش مصنوعی گروهی روی بانک تمیز")
one = j(c.post(f"/api/wb/products/{prods[3]['id']}/ai", json={"columns": [{"key": "long_description", "mode": "overwrite"}]}))
ok(one["ok"] and "long_description" in one["generated"], "هوش مصنوعی تک‌محصول")

print("۷) تکراری‌ها")
bank2 = j(c.post("/api/wb/banks", json={"dataset_ids": [ds["id"]], "schema_id": mega["id"], "title": "تکراری", "images": False}))
wait_bank(bank2["id"])
pairs = j(c.get("/api/dupes"))
ok(len(pairs) >= 6 and all("لینک منبع یکسان" in x["reasons"] for x in pairs[:3]), f"{len(pairs)} جفت تکراری پیدا شد")
pr = pairs[0]
a_id, b_id = (pr["a"]["id"], pr["b"]["id"]) if pr["a"]["bank_id"] == bank["id"] else (pr["b"]["id"], pr["a"]["id"])
mg = j(c.post("/api/dupes/merge", json={"primary_id": a_id, "secondary_id": b_id}))
sec = j(c.get(f"/api/wb/products/{b_id}"))
ok(sec["status"] == "merged" and sec["merged_into"] == a_id and mg["meta"].get("merged_from") == [b_id], "ادغام: محصول دوم «ادغام‌شده» شد و منبعش ثبت شد")
ok(c.put(f"/api/wb/products/{b_id}", json={"title": "x" * 12}).status_code == 400, "محصول ادغام‌شده قابل ویرایش نیست")

print("۸) کاتالوگ و انتشار")
tpls = j(c.get("/api/cat/templates"))
ok(len(tpls) >= 3 and tpls[0]["is_default"], "الگوهای خروجی پیش‌فرض")
cfg_bad = {"outputs": [{"kind": "brands", "format": "xlsx", "path": "x/{slug}.xlsx"}]}
ok(j(c.post("/api/cat/templates/preview", json={"config": cfg_bad}))["errors"], "اعتبارسنجی الگو (فایل جدا برای هر محصول فقط در JSON)")
small = next(s for s in j(c.get("/api/schemas")) if s["usage"] == "catalog")
tpl = j(c.post("/api/cat/templates", json={"name": "آزمایشی", "config": {
    "root": "{catalog}/r{release}", "images": {"enabled": True, "path": "media/{brand_slug}/{slug}/{name}.{ext}", "feature_name": "main", "gallery_name": "g{n}"},
    "outputs": [{"name": "محصولات", "kind": "products", "format": "json", "schema_id": mega["id"], "path": "data/products.json"},
                {"name": "تصاویر و عنوان", "kind": "products", "format": "json", "schema_id": small["id"], "path": "items/{slug}.json"},
                {"name": "برندها", "kind": "brands", "format": "xlsx", "path": "brands.xlsx"},
                {"name": "سازگاری", "kind": "compatibility", "format": "csv", "path": "compat/compat.csv"},
                {"name": "خودروها", "kind": "vehicles", "format": "json", "path": "vehicles.json"}]}}))
ok(any(f["path"].endswith("/media/castrol/castrol-edge-5w30-4l/main.png") for f in tpl["tree"]), "پیش‌نمایش درخت فایل الگو")
catv = j(c.post("/api/cat/catalogs", json={"title": "کاتالوگ روغن", "slug": "oil-catalog", "template_id": tpl["id"],
                                         "selection": {"bank_ids": [bank["id"]], "statuses": ["approved"], "min_quality": 0}}))
prev = j(c.get(f"/api/cat/catalogs/{catv['id']}/preview"))
ok(prev["count"] == appr - 0 or prev["count"] >= 3, f"پیش‌نمایش انتخاب ({prev['count']} محصول، {prev['skipped_count']} کنار گذاشته)")
rel = j(c.post(f"/api/cat/catalogs/{catv['id']}/release", json={"note": "اولین انتشار"}))
rel = wait_release(rel["id"])
ok(rel["status"] == "completed", f"انتشار ۱ ساخته شد {rel.get('error') or ''}")
root = Path(rel["root"])
recs = json.loads((root / "data/products.json").read_text(encoding="utf-8"))
ok(isinstance(recs, list) and len(recs) == rel["stats"]["products"] and "compatible_vehicles" in recs[0], "products.json آرایه‌ی محصولات با ستون سازگاری")
r0 = next(x for x in recs if not x["compatible_vehicles"]["all"]) if any(not x["compatible_vehicles"]["all"] for x in recs) else recs[0]
ok(r0["compatible_vehicles"]["all"] or r0["compatible_vehicles"]["vehicles"][0]["brand_slug"] == "peugeot", "سازگاری ساختاریافته با اسلاگ برند/مدل")
ok(r0["featured_images"].startswith("media/caspian/") and (root / r0["featured_images"]).exists(), "تصاویر در مسیر الگو و پیوندشان در JSON")
per = list((root / "items").glob("*.json"))
ok(len(per) == len(recs) and set(json.loads(per[0].read_text(encoding="utf-8"))) == {"title", "slug", "brand", "featured_image", "gallery"}, "یک فایل JSON برای هر محصول با اسکیمای کاتالوگ")
from openpyxl import load_workbook  # noqa: E402
wb_ = load_workbook(root / "brands.xlsx")
ok(wb_.active.cell(row=2, column=3).value == "caspian", "برندها در Excel")
ok((root / "compat/compat.csv").exists() and (root / "manifest.json").exists() and Path(rel["files"]["zip"]).exists(), "جدول سازگاری، شناسنامه و ZIP")
veh = json.loads((root / "vehicles.json").read_text(encoding="utf-8"))
ok(any(v["slug_path"].startswith("peugeot/206") for v in veh), "فهرست خودروهای سازگار")
# انتشار دوم با تغییر
pid_changed = recs[0]
first_pid = next(p["id"] for p in j(c.get(f"/api/wb/products?bank_id={bank['id']}&status=approved&size=50"))["rows"] if p["slug"] == pid_changed["slug"])
j(c.put(f"/api/wb/products/{first_pid}", json={"title": "عنوان تازه برای انتشار دوم روغن موتور"}))
rel2 = wait_release(j(c.post(f"/api/cat/catalogs/{catv['id']}/release", json={}))["id"])
ok(rel2["number"] == 2 and rel2["diff"]["previous"] == 1 and len(rel2["diff"]["changed"]) == 1 and rel2["diff"]["changed"][0]["fields"], "انتشار ۲: تفاوت با انتشار ۱ (یک محصول تغییرکرده)")
ok(Path(rel["root"]).exists() and json.loads((Path(rel["root"]) / "data/products.json").read_text(encoding="utf-8"))[0]["title"] == recs[0]["title"], "انتشار ۱ تغییرناپذیر ماند")
cmpr = j(c.get(f"/api/cat/releases/compare?a={rel['id']}&b={rel2['id']}"))
ok(len(cmpr["changed"]) == 1 and any(ch["field"] == "title" for ch in cmpr["changed"][0]["changes"]), "مقایسه‌ی دو انتشار")
items = j(c.get(f"/api/cat/releases/{rel2['id']}/items"))
ok(items["total"] == rel2["stats"]["products"] and items["rows"][0]["product_rev"], "اقلام انتشار با ریویژن هر محصول")
j(c.put("/api/modules/vehicles", json={"enabled": False}))
r = c.post("/api/vehicles/suggest", json={"text": "پژو"})
rel3 = wait_release(j(c.post(f"/api/cat/catalogs/{catv['id']}/release", json={}))["id"])
ok(r.status_code == 503 and rel3["status"] == "completed", "ماژول خودروها خاموش: API آن ۵۰۳، ساخت کاتالوگ همچنان کار می‌کند")
j(c.put("/api/modules/vehicles", json={"enabled": True}))
crev = j(c.get(f"/api/revisions?entity=catalog&entity_id={catv['id']}"))
ok(len(crev) == 1, "تنظیمات کاتالوگ هم نسخه‌دار است")

print("۹) اسکیماها و الگوها")
sch = j(c.get(f"/api/schemas/{mega['id']}"))
ok(sch["used"]["banks"] >= 2 and "آزمایشی" in sch["used"]["templates"] and sch["usage_label"], "محل استفاده‌ی هر اسکیما")
ok(c.delete(f"/api/schemas/{small['id']}").status_code == 400, "اسکیمای در حال استفاده حذف نمی‌شود")
j(c.put(f"/api/schemas/{small['id']}", json={**small, "description": "توضیح تازه"}))
ok(len(j(c.get(f"/api/revisions?entity=schema&entity_id={small['id']}"))) >= 1, "اسکیماها هم نسخه‌دارند")
ok(len(j(c.get("/api/schemas?usage=catalog"))) >= 2, "فیلتر اسکیماها بر اساس کاربرد")

print("۱۰) انتقال از نسخه‌ی ۱ و پشتیبان")
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "formats": ["json"], "rembg": False, "zip": False}))
wait(f"/api/exports/{ex['id']}", ("completed", "error"), t=120)
conv = j(c.post(f"/api/wb/from-legacy/{ex['id']}", json={"title": "از خروجی قدیمی"}))
lp = j(c.get(f"/api/wb/products?bank_id={conv['bank']['id']}"))["rows"]
ok(conv["products"] == 6 and lp[0]["images"] and lp[0]["brand"], "تبدیل «خروجی نهایی» نسخه‌ی ۱ به بانک تمیز (با تصاویر و برند)")
bk_ = j(c.post("/api/backups", json={"note": "آزمایش"}))
ok(bk_["size"] > 1000 and any(x["name"] == bk_["name"] for x in j(c.get("/api/backups"))["backups"]), "پشتیبان‌گیری از پایگاه داده")
j(c.post("/api/backups/restore", json={"name": bk_["name"]}))
ok(j(c.get("/api/backups"))["pending_restore"], "بازگردانی برای شروع بعدی آماده شد")
j(c.post("/api/backups/cancel-restore", json={}))
ov = j(c.get("/api/overview"))
ok(ov["editor"]["products"] >= 12 and ov["catalog"]["releases"] == 3, "نمای کلی بخش‌ها")
docs = j(c.get("/api/docs"))
ok(any(g["group"] == "guide" for g in docs), "راهنما و مستندات در دسترس است")

print("۱۱) ابزارهای MCP نسخه‌ی ۲")
from studio import mcp_core  # noqa: E402


class _TCApi(mcp_core.StudioAPI):
    """همان StudioAPI ولی از طریق TestClient (بدون سرور واقعی)."""

    def __init__(self):
        super().__init__("http://testserver")
        self.s = c
        self.base = ""
        self._checked = True

    def call(self, method, path, body=None, params=None, timeout=600):
        r = c.request(method, path, json=body, params=params, headers={"X-Studio-Client": "mcp"})
        data = r.json()
        if r.status_code >= 400:
            raise mcp_core.ToolError(data.get("error") if isinstance(data, dict) else str(data))
        return data


srv = mcp_core.Server(_TCApi())
names = {t["name"] for t in srv.tools()}
ok(mcp_core.SERVER_VERSION.startswith("2.") and {"list_banks", "update_product", "search_vehicles", "build_release", "restore_revision"} <= names,
   f"ابزارهای نسخه‌ی ۲ فهرست شدند ({len(names)} ابزار)")


def mcp(name, **args):
    r = srv.call_tool(name, args)
    if r["isError"]:
        raise AssertionError(r["content"][0]["text"])
    return json.loads(r["content"][0]["text"]) if r["content"][0]["text"][:1] in "[{" else r["content"][0]["text"]


lpm = mcp("list_products", bank_id=bank["id"], size=5)
ok(lpm["total"] >= 6 and "compat" in lpm["rows"][0], "list_products (فشرده)")
vs = mcp("search_vehicles", q="پژو 206")
vtrim = next((x for x in vs if x.get("t") == "trim" or x.get("level") == "trim"), vs[0])
vt, vid = vtrim.get("t") or vtrim.get("level"), vtrim["id"]
mp = mcp("update_product", product_id=pid1, compat={"all": False, "items": [{"t": vt, "id": vid}]}, note="از MCP")
ok(mp["compat"] and "206" in mp["compat"], "update_product با سازگاری از بانک خودروها")
mrev = mcp("list_revisions", entity="product", entity_id=pid1)
ok(mrev[0]["actor"] == "mcp", "ریویژن با کننده‌ی mcp ثبت شد")
cmp_ = mcp("compare_revisions", entity="product", entity_id=pid1, a=mrev[1]["rev"])
ok(cmp_ and "compat" in json.dumps(cmp_, ensure_ascii=False), "compare_revisions")
ok(isinstance(mcp("product_quality", product_id=pid1).get("score"), int), "product_quality")
pim = srv.call_tool("get_product_images", {"product_id": pid1, "max": 1})
ok(any(cc["type"] == "image" for cc in pim["content"]), "get_product_images تصویر نهایی را برمی‌گرداند")
ok(mcp("save_output_template", preview=True, config={"outputs": [{"kind": "brands", "format": "xlsx", "path": "b.xlsx"}]})["tree"], "پیش‌نمایش الگو از MCP")
ok(len(mcp("list_releases", catalog_id=catv["id"])) >= 2, "list_releases")
j(c.put("/api/modules/vehicles", json={"enabled": False}))
srv._mods_at = 0  # noqa: SLF001
ok("search_vehicles" not in {t["name"] for t in srv.tools()} and srv.call_tool("search_vehicles", {"q": "x"})["isError"],
   "ابزارهای ماژول خاموش پنهان و غیرقابل اجرا هستند")
j(c.put("/api/modules/vehicles", json={"enabled": True}))

print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
