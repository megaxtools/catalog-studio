"""تست انتها‌به‌انتها: سایت آزمایشی محلی ← استخراج ← تصمیم در خطا ← توقف/ادامه ← خروجی ← حذف پس‌زمینه."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-e2e").resolve()
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


print("۱) تنظیمات و منابع")
j(c.put("/api/settings", json={"delay_min_ms": 30, "delay_max_ms": 60, "output_root": str(OUT), "browser_channel": "chromium", "max_retries": 2}))
shop_cfg = {
    "key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
    "listing": {"mode": "browser", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page", "start": 1}},
    "product": {"mode": "browser", "capture_xhr": ["*"], "auto_expand": True, "scroll": True, "scroll_times": 2},
    "request": {"timeout_s": 20}, "fields": [
        {"key": "title", "strategies": [{"type": "jsonld", "at_type": "Product", "path": "name"}, {"type": "css", "selector": "h1", "attr": "text"}]},
        {"key": "gallery", "strategies": [{"type": "css", "selector": ".product-gallery img", "attr": "src", "all": True}], "transforms": ["strip_query"]},
    ],
}
shop = j(c.post("/api/sources", json={"config": shop_cfg}))
dk_cfg = {
    "key": "fixture-dk", "name": "API آزمایشی", "domains": ["localhost"], "product_id_pattern": r"dkp-(\d+)",
    "listing": {"mode": "api", "api": {"url": BASE + "/dk/v1/categories/{slug}/search/?page={page}", "params_from_url": {"slug": r"category-([^/?#]+)"},
                "items_path": "data.products", "item_fields": {"id": "id"}, "url_template": BASE + "/dk-product/dkp-{id}/",
                "total_pages_path": "data.pager.total_pages", "total_items_path": "data.pager.total_items", "category_label_path": "data.category.title_fa"}},
    "product": {"mode": "api", "api": {"url": BASE + "/dk/v2/product/{id}/", "params_from_url": {"id": r"dkp-(\d+)"}}},
    "fields": __import__("json").load(open(ROOT / "studio/defaults/sources/01_digikala.json", encoding="utf-8"))["fields"],
}
dk = j(c.post("/api/sources", json={"config": dk_cfg}))
inf_cfg = {**shop_cfg, "key": "fixture-infinite", "name": "اسکرول آزمایشی", "domains": ["127.0.0.2"],
           "listing": {"mode": "browser", "link_pattern": r"/product/p-\d+", "pagination": {"type": "scroll", "idle_rounds": 3, "pause_ms": 500}}}
inf = j(c.post("/api/sources", json={"config": inf_cfg}))
ok(len(j(c.get("/api/sources"))) == 7, "۴ منبع پیش‌فرض + ۳ منبع آزمایشی")

print("۲) آزمایش زنده")
t = j(c.post(f"/api/sources/{shop['id']}/test-listing", json={"url": BASE + "/category/oils"}))
ok(t["ok"] and t["count"] == 8, f"لینک‌های صفحه‌ی اول دسته: {t.get('count')}")
t = j(c.post(f"/api/sources/{shop['id']}/test-product", json={"url": BASE + "/product/p-3"}))
r = t["record"]
ok(t["ok"] and "کاسپین" in r["title"], "عنوان از JSON-LD")
ok(len(r["gallery"]) >= 2 and "?" not in r["featured_image"], f"تصاویر: شاخص + {len(r['gallery'])} گالری، بدون پارامتر")
names = [s["name"] for s in r["specifications"]]
ok("سطح کیفیت" in names, "کلیک خودکار روی «مشاهده بیشتر» و خواندن مشخصات پنهان")
ok(r["dimensions"]["item_weight"] == "3600" and r["dimensions"]["item_length"] == "20", f"ابعاد از مشخصات: {r['dimensions']}")
ok(r["dimension_codes"].get("volume") == "4 لیتر", f"dimension_codes: {r['dimension_codes']}")
ok(r["brand"] == "کاسپین" and t["explorer"]["groups"], "برند و کاوشگر داده")
t = j(c.post(f"/api/sources/{dk['id']}/test-product", json={"url": BASE + "/dk-product/dkp-1001/"}))
ok(t["ok"] and t["record"]["title_en"].startswith("Behran") and len(t["record"]["specifications"]) == 4, "حالت API (ساختار دیجی‌کالا)")
ok(t["record"]["dimensions"]["packaging_length"] == "25", "ابعاد بسته‌بندی از مشخصات API")


def wait_ds(did, until=("completed",), decide=None, timeout=240, pause_after=None):
    t0 = time.time()
    paused = False
    while time.time() - t0 < timeout:
        d = j(c.get(f"/api/datasets/{did}"))
        if d["open_incident"] and decide:
            inc = d["open_incident"]
            action = decide(inc)
            print(f"     · تصمیم برای «{inc['title']}»: {action}")
            j(c.post(f"/api/incidents/{inc['id']}/resolve", json={"action": action}))
        if pause_after and not paused and d["counts"]["done"] >= pause_after:
            j(c.post(f"/api/datasets/{did}/do/pause", json={}))
            paused = True
            while j(c.get(f"/api/datasets/{did}"))["status"] not in ("paused",):
                time.sleep(0.3)
            return j(c.get(f"/api/datasets/{did}"))
        if d["status"] in until:
            return d
        time.sleep(0.6)
    raise SystemExit(f"timeout: {d['status']} {d['step']}")


def decide(inc):
    return {"not_found": "skip", "missing_fields": "continue_partial"}.get(inc["kind"], "retry")


print("۳) استخراج با صفحه‌بندی پارامتری، خطای ۵۰۳ (تکرار خودکار)، ۴۰۴ و فیلد خالی")
d1 = j(c.post("/api/datasets", json={"category_url": BASE + "/category/oils", "source_id": shop["id"], "limit": 12}))
d1 = wait_ds(d1["id"], decide=decide)
ok(d1["counts"]["done"] + d1["counts"]["partial"] == 12, f"۱۲ محصول جمع شد (کامل {d1['counts']['done']}، ناقص {d1['counts']['partial']}، رد {d1['counts']['skipped']})")
ok(d1["counts"]["partial"] == 1 and d1["counts"]["skipped"] == 1, "محصول ۵ ناقص و محصول ۹ (۴۰۴) رد شد")
ok("12items" in d1["name"] and d1["name"].startswith("fixture-shop__oils__"), f"نام بانک: {d1['name']}")
logs = j(c.get(f"/api/datasets/{d1['id']}/logs"))
ok(any("503" in (l["message"] + l["detail"]) for l in logs), "خطای ۵۰۳ ثبت و خودکار تکرار شد")

print("۴) توقف و ادامه از همان نقطه (حالت API)")
d2 = j(c.post("/api/datasets", json={"category_url": "http://localhost:8899/search/category-engine-oil/", "limit": ""}))
ok(d2["source"]["key"] == "fixture-dk", "تشخیص خودکار منبع از دامنه")
d2 = wait_ds(d2["id"], pause_after=4)
done_at_pause = d2["counts"]["done"]
ok(d2["status"] == "paused" and done_at_pause >= 4, f"متوقف شد پس از {done_at_pause} محصول")
j(c.post(f"/api/datasets/{d2['id']}/do/resume", json={}))
d2 = wait_ds(d2["id"])
ok(d2["counts"]["done"] == 14 and d2["total_expected"] == 14, "ادامه تا پایان: ۱۴ محصول، بدون تکرار")
ok(d2["category_label"] == "روغن موتور", "عنوان دسته از API")
items = j(c.get(f"/api/datasets/{d2['id']}/items?size=50"))["items"]
ok(len({i["url"] for i in items}) == 14, "هیچ لینک تکراری در بانک نیست")

print("۵) اجرای دوباره روی همان دسته: محصولات تکراری رد می‌شوند")
d3 = j(c.post("/api/datasets", json={"category_url": BASE + "/category/oils", "source_id": shop["id"], "limit": 5}))
d3 = wait_ds(d3["id"], decide=decide)
items3 = j(c.get(f"/api/datasets/{d3['id']}/items?size=50"))["items"]
ids3 = sorted(int(i["url"].rsplit("-", 1)[1]) for i in items3 if i["status"] in ("done", "partial"))
ok(len(ids3) == 5 and min(ids3) > 12, f"فقط محصولات جدید: {ids3}")

print("۶) صفحه‌ی اسکرول بی‌پایان")
d4 = j(c.post("/api/datasets", json={"category_url": "http://127.0.0.2:8899/infinite", "source_id": inf["id"], "duplicates": "rescrape"}))
d4 = wait_ds(d4["id"], decide=decide)
ok(d4["total_found"] == 13, f"همه‌ی ۱۳ لینک با اسکرول پیدا شد ({d4['total_found']})")

print("۷) ویرایش دستی و تکمیل گروهی")
it = [i for i in items3 if i["status"] == "done"][0]
j(c.post("/api/items/bulk", json={"ids": [i["id"] for i in items3], "manual": {
    "vendor_notes": "نصب رایگان در محل کسب‌وکار",
    "user_dos_donts_description": {"dos": ["سطح روغن را هر ماه بررسی کنید"], "donts": ["با روغن دیگر مخلوط نکنید"], "pre_post_purchase": ["پس از خرید، فاکتور را نگه دارید"]},
    "vendor_dos_donts_description": {"dos": ["اصالت کالا را تضمین کنید"], "donts": ["کالای باز شده نفروشید"], "shipping_returns": ["مرجوعی تا ۷ روز"]}}}))
j(c.put(f"/api/items/{it['id']}", json={"overrides": {"slug": "custom-slug-test"}, "manual": {**j(c.get(f"/api/items/{it['id']}"))["manual"]}}))
j(c.post("/api/mappings", json={"rows": [{"kind": "category", "source_value": "روغن موتور", "target_slug": "engine-oil"},
                                         {"kind": "brand", "source_value": "کاسپین", "target_slug": "caspian"}]}))
un = j(c.get("/api/mappings/unmapped"))
ok(not any(u["value"] == "کاسپین" for u in un["brand"]), "نگاشت برند ثبت شد")

print("۸) خروجی Excel/CSV + تصاویر + حذف پس‌زمینه + ZIP")
ex = j(c.post("/api/exports", json={"dataset_ids": [d3["id"], d2["id"]], "formats": ["xlsx", "csv"], "images": True, "rembg": True,
                                    "rembg_model": "u2netp", "zip": True, "link_mode": "relative"}))
t0 = time.time()
while True:
    e = j(c.get(f"/api/exports/{ex['id']}"))
    if e["status"] in ("completed", "error"):
        break
    time.sleep(1)
    if time.time() - t0 > 600:
        raise SystemExit("export timeout")
ok(e["status"] == "completed", f"خروجی ساخته شد ({e.get('error') or e['result'].get('rows')} ردیف) در {time.time() - t0:.0f} ثانیه")
res = e["result"]
name = e["name"]
ok(Path(res["files"]["xlsx"]).exists() and Path(res["files"]["zip"]).exists() and "multi-2__19items" in name, f"فایل‌ها: {name}.xlsx / .csv / .zip")
folders = sorted(p.name for p in (OUT / name).iterdir())
ok(len(folders) == 19, f"۱۹ پوشه‌ی محصول (۵ + ۱۴): نمونه {folders[:2]}")
sample = OUT / name / folders[0]
names_ = sorted(p.name for p in sample.iterdir())
ok({"feature.png", "feature_raw.jpg", "feature_raw_rembg.png", "gallery_1.png", "gallery_1_raw.jpg", "gallery_1_raw_rembg.png"} <= set(names_),
   f"نام‌گذاری مرحله‌ها (خام/میانی/نهایی): {names_[:6]}")
ok(not (OUT / "rembg").exists(), "پوشه‌ی جدای rembg ساخته نمی‌شود")
ok(Path(res["files"]["raw_xlsx"]).name == f"{name}_raw.xlsx" and Path(res["files"]["raw_json"]).exists(), "داده‌ی خام با پسوند _raw")
import zipfile  # noqa: E402
zn = zipfile.ZipFile(res["files"]["zip"]).namelist()
ok(not any("_raw" in n for n in zn) and any(n.endswith("/feature.png") for n in zn) and f"{name}.xlsx" in zn, "ZIP فقط فایل‌های نهایی")
rb = OUT / name / folders[0] / "feature.png"
from PIL import Image  # noqa: E402
im = Image.open(rb)
ok(im.size == (1280, 1280) and im.mode == "RGBA" and im.getpixel((5, 5))[3] == 0, f"rembg: {im.size} {im.mode}، گوشه شفاف، موتور {res['stats'].get('bg_engine')}")
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(res["files"]["xlsx"])
ws = wb["products"]
hdr = [x.value for x in ws[1]]
need = ["title", "slug", "category_slug", "brand_slug", "status", "product_type", "requires_vehicle_at_booking", "short_description",
        "long_description", "vendor_notes", "user_dos_donts_description.dos", "user_dos_donts_description.donts",
        "user_dos_donts_description.pre_post_purchase", "vendor_dos_donts_description.shipping_returns", "dimensions",
        "dimension_codes", "specifications", "featured_images", "images_gallery", "source_url"]
ok(all(h in hdr for h in need), "همه‌ی ستون‌های اسکیمای مگا کارز در Excel")
row = {hdr[i]: ws.cell(row=2, column=i + 1).value for i in range(len(hdr))}
ok(row["category_slug"] == "engine-oil" and row["brand_slug"] == "caspian", f"نگاشت‌ها: {row['category_slug']} / {row['brand_slug']}")
ok(row["featured_images"].startswith(f"{name}/") and row["featured_images"].endswith("feature.png"), f"پیوند تصویر: {row['featured_images']}")
ok(row["user_dos_donts_description.dos"].startswith("• "), "بولت‌ها جدا و بولت‌دار")
ok(row["source_url"].startswith(BASE + "/product/p-"), "لینک منبع ثبت شد")
ok(row["slug"] == "custom-slug-test", "ویرایش دستی اسلاگ در خروجی اعمال شد")
dk_rows = [ws.cell(row=r, column=hdr.index("slug") + 1).value for r in range(2, ws.max_row + 1)]
ok(any(s.startswith("behran-super-pishtaz-20w-50") for s in dk_rows), "اسلاگ از عنوان انگلیسی منبع")
ok("specifications" in wb.sheetnames and wb["specifications"].max_row > 20, "شیت خوانای مشخصات")
csv_text = Path(res["files"]["csv"]).read_text(encoding="utf-8-sig")
ok(csv_text.splitlines()[0].startswith("title,slug,category_slug"), "CSV با UTF-8")

print("۹) ابزار مستقل حذف پس‌زمینه روی یک مسیر")
src_dir = DATA / "manual_imgs" / "batch-a"
(src_dir / "p1").mkdir(parents=True)
shutil.copy(OUT / name / folders[0] / "feature_raw.jpg", src_dir / "p1" / "feature.jpg")
shutil.copy(OUT / name / folders[0] / "gallery_1_raw.jpg", src_dir / "p1" / "gallery_1.jpg")
b = j(c.post("/api/bg", json={"input_path": str(src_dir), "model": "isnet-general-use", "size": 1280}))
while True:
    bj = [x for x in j(c.get("/api/bg")) if x["id"] == b["id"]][0]
    if bj["status"] in ("completed", "error"):
        break
    time.sleep(1)
outp = DATA / "manual_imgs" / "rembg" / "batch-a" / "p1"
ok(bj["status"] == "completed" and sorted(p.name for p in outp.iterdir()) == ["feature.png", "feature_raw_rembg.png", "gallery_1.png", "gallery_1_raw_rembg.png"], f"خروجی در {outp.relative_to(DATA)} با همان سلسله‌مراتب")
shutil.copy(outp / "feature.png", DATA / "sample_rembg.png")
shutil.copy(src_dir / "p1" / "feature.jpg", DATA / "sample_src.jpg")
print("\nهمه‌ی آزمون‌ها موفق بود ✅")
