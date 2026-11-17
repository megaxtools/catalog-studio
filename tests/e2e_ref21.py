"""تست نسخه‌ی ۲.۱: قالب و نمونه‌ی ورود در همه‌ی بخش‌ها، ورود داده‌ی خام از فایل، برندها و دسته‌ها (درخت، دسته‌های هر برند،
عملیات گروهی، خروجی)، هوش مصنوعی در برند/دسته/الگو/تکراری/نگاشت ستون‌ها، و ابزارهای MCP همین قابلیت‌ها."""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-ref21").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
for m in (ROOT / "data" / "models").glob("*.onnx"):
    os.symlink(m, DATA / "models" / m.name)
os.environ.update({"CATALOG_STUDIO_DATA": str(DATA), "CATALOG_STUDIO_ALLOWED_HOSTS": "testserver"})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fixture_site  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402
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


def durl(data: bytes, mime="application/octet-stream") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def wait(url, until, t=180, key="status"):
    t0 = time.time()
    while time.time() - t0 < t:
        d = j(c.get(url))
        if d[key] in until:
            return d
        time.sleep(0.3)
    raise SystemExit(f"timeout {url}")


j(c.put("/api/settings", json={"output_root": str(DATA / "output"), "queue_enabled": False}))
prov = j(c.post("/api/ai/providers", json={"name": "mock", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key",
                                          "text_model": "mock-text", "image_model": "mock-image", "image_mode": "images_api", "timeout_s": 30}))
j(c.put("/api/settings", json={"ai_default_provider_id": prov["id"]}))

print("۱) قالب ورود و فایل نمونه در هر بخش")
specs = j(c.get("/api/import/specs"))
ok(set(specs) == {"brand", "category", "vehicles", "raw"} and all(any(col["required"] for col in s["columns"]) for s in specs.values()),
   "مشخصات ورود برای برندها، دسته‌ها، خودروها و داده‌ی خام (با ستون‌های اجباری)")
for kind in specs:
    for fmt in ("xlsx", "csv", "json"):
        r = c.get(f"/api/import/sample/{kind}?format={fmt}")
        ok(r.status_code == 200 and len(r.content) > 50 and "attachment" in r.headers["content-disposition"], f"نمونه‌ی {kind}.{fmt}") if fmt == "xlsx" else None
        if r.status_code != 200:
            raise SystemExit(f"sample {kind} {fmt}")
wb = load_workbook(io.BytesIO(c.get("/api/import/sample/brand?format=xlsx").content))
ok(wb.sheetnames == ["brand", "راهنما"] and wb["brand"].cell(1, 1).value == "name", "نمونه‌ی Excel: شیت داده + شیت راهنما")
ok(isinstance(json.loads(c.get("/api/import/sample/raw?format=json").content)[0]["specifications"], list), "نمونه‌ی JSON با مشخصات ساختاریافته")

print("۲) دسته‌بندی‌ها: ورود نمونه (بی‌توجه به ترتیب) و درخت")
cat_csv = c.get("/api/import/sample/category?format=csv").content.decode("utf-8-sig").splitlines()
rev_csv = "\n".join([cat_csv[0]] + cat_csv[1:][::-1])  # فرزند پیش از والد
imp = j(c.post("/api/ref/category/import", json={"data_url": durl(rev_csv.encode()), "name": "cats.csv"}))
ok(imp["added"] == 3 and not imp["errors"], f"ورود دسته‌ها از CSV با فرزند پیش از والد ({imp})")
j(c.post("/api/ref/category", json={"name": "تیغه برف پاک کن", "name_en": "Wiper Blade"}))
tree = j(c.get("/api/ref/category/tree"))
root = next(n for n in tree if n["slug"] == "oils-fluids")
ok({x["slug"] for x in root["nodes"]} == {"engine-oil", "gear-oil"} and len(tree) == 2, "درخت دسته‌ها: ریشه با دو زیرشاخه")
cats = {x["slug"]: x for x in j(c.get("/api/ref/category"))}
r = c.put(f"/api/ref/category/{cats['oils-fluids']['id']}", json={**cats["oils-fluids"], "parent_id": cats["engine-oil"]["id"]})
ok(r.status_code == 400, "جلوگیری از دور در درخت (والد = زیرشاخه)")

print("۳) برندها: دسته‌های هر برند، ورود فارسی، فیلتر بر اساس دسته")
bimp = j(c.post("/api/ref/brand/import", json={"data_url": durl(c.get("/api/import/sample/brand?format=xlsx").content), "name": "b.xlsx"}))
ok(bimp["added"] == 2, "ورود نمونه‌ی برندها")
brands = {x["slug"]: x for x in j(c.get("/api/ref/brand"))}
ok([x["slug"] for x in brands["caspian"]["categories"]] == ["engine-oil", "gear-oil"] and brands["bosch"]["categories"][0]["slug"] == "wiper-blade",
   "دسته‌های هر برند از ستون categories")
fa_x = xlsx([["نام", "نام انگلیسی", "دسته‌بندی‌ها", "نام‌های دیگر"], ["بهران", "Behran", "روغن موتور", "بهران سپاهان|Behran Oil"]])
j(c.post("/api/ref/brand/import", json={"data_url": durl(fa_x), "name": "fa.xlsx"}))
behran = next(x for x in j(c.get("/api/ref/brand")) if x["slug"] == "behran")
ok(behran["category_ids"] == [cats["engine-oil"]["id"]] and "Behran Oil" in behran["aliases"], "سرستون فارسی و دسته با نام فارسی")
in_eo = {x["slug"] for x in j(c.get(f"/api/ref/brand?category_id={cats['engine-oil']['id']}"))}
in_root = {x["slug"] for x in j(c.get(f"/api/ref/brand?category_id={cats['oils-fluids']['id']}"))}
in_gear_strict = {x["slug"] for x in j(c.get(f"/api/ref/brand?category_id={cats['gear-oil']['id']}&inherit=0"))}
ok(in_eo == {"caspian", "behran"} and in_root == {"caspian", "behran"} and in_gear_strict == {"caspian"}, "برندهای هر دسته (با زیرشاخه‌ها و بدون ارث‌بری)")
ok(next(n for n in j(c.get("/api/ref/category/tree")) if n["slug"] == "oils-fluids")["nodes"][0]["brands"] >= 1, "تعداد برند در گره‌های درخت")

print("۴) عملیات گروهی و خروجی")
ids = [brands["caspian"]["id"], brands["bosch"]["id"]]
r = j(c.post("/api/ref/brand/bulk", json={"ids": ids, "action": "deactivate"}))
ok(r["done"] == 2 and all(not x["active"] for x in j(c.get("/api/ref/brand")) if x["id"] in ids), "غیرفعال کردن گروهی")
j(c.post("/api/ref/brand/bulk", json={"ids": ids, "action": "activate"}))
j(c.post("/api/ref/brand/bulk", json={"ids": ids, "action": "add_categories", "value": [cats["wiper-blade"]["id"]]}))
ok(cats["wiper-blade"]["id"] in j(c.get(f"/api/ref/brand/{ids[0]}"))["category_ids"], "افزودن گروهی دسته به برندها")
j(c.post("/api/ref/category/bulk", json={"ids": [cats["wiper-blade"]["id"]], "action": "set_parent", "value": cats["oils-fluids"]["id"]}))
ok(j(c.get(f"/api/ref/category/{cats['wiper-blade']['id']}"))["parent_id"] == cats["oils-fluids"]["id"], "تعیین والد گروهی")
revs = j(c.get(f"/api/revisions?entity=ref_brand&entity_id={ids[0]}"))
ok(len(revs) >= 4, "هر تغییر گروهی نسخه‌دار است")
for fmt in ("xlsx", "csv", "json"):
    r = c.get(f"/api/ref/brand/export?format={fmt}&ids={ids[0]}")
    ok(r.status_code == 200, f"خروجی برندها ({fmt})") if fmt == "xlsx" else None
ex_rows = json.loads(c.get("/api/ref/brand/export?format=json").content)
ok(len(ex_rows) == 3 and "engine-oil" in next(x for x in ex_rows if x["slug"] == "caspian")["categories"], "خروجی JSON با دسته‌ها")
ex_csv = c.get("/api/ref/category/export?format=csv").content
back = j(c.post("/api/ref/category/import", json={"data_url": durl(ex_csv), "name": "cats.csv"}))
ok(back["updated"] == 4 and back["added"] == 0, "خروجی دسته‌ها دوباره قابل ورود است (رفت و برگشت)")
tmp = j(c.post("/api/ref/category", json={"name": "موقت", "name_en": "Temp"}))
j(c.post("/api/ref/brand/bulk", json={"ids": [behran["id"]], "action": "add_categories", "value": [tmp["id"]]}))
dl = j(c.post("/api/ref/category/bulk", json={"ids": [tmp["id"], cats["oils-fluids"]["id"]], "action": "delete"}))
ok(dl["done"] == 1 and dl["errors"] and "زیرمجموعه" in dl["errors"][0]["error"], "حذف گروهی (دسته‌ی دارای زیرشاخه حذف نمی‌شود)")
ok(tmp["id"] not in j(c.get(f"/api/ref/brand/{behran['id']}"))["category_ids"], "با حذف دسته، از برندها هم برداشته شد")

print("۵) خودروها: ورود با سرستون فارسی و اسلاگ انگلیسی")
vcsv = "برند,مدل,تیپ,brand_en,brand_slug\nخودروی آزمایشی,مدل الف,تیپ یک,Test Motors,test-motors\n".encode()
vi = j(c.post("/api/vehicles/import", json={"data_url": durl(vcsv), "name": "v.csv"}))
tb = next(b for b in j(c.get("/api/vehicles/brands?q=test")) if b["slug"] == "test-motors")
ok(vi["added"]["brand"] == 1 and vi["added"]["trim"] == 1 and tb["name_en"] == "Test Motors" and not tb["auto_en"], "ورود خودرو با نام و اسلاگ انگلیسی")
vs = j(c.post("/api/vehicles/import", json={"data_url": durl(c.get("/api/import/sample/vehicles?format=xlsx").content), "name": "v.xlsx"}))
ok("added" in vs, "نمونه‌ی خودروها قابل ورود است")

print("۶) ورود داده‌ی خام از فایل (با نگاشت ستون‌ها و AI)")
raw = xlsx([["نام کالا", "مارک", "گروه", "عکس", "رنگ", "توضیح کوتاه"],
            ["روغن موتور کاسپین 20W-50 چهار لیتری", "کاسپین", "روغن موتور", f"{FX}/img/1_1.jpg", "زرد", "مناسب موتورهای بنزینی"],
            ["روغن موتور کاسپین 20W-50 چهار لیتری اصل", "کاسپین", "روغن موتور", f"{FX}/img/1_2.jpg", "زرد", ""],
            ["تیغه برف پاک کن بوش 60", "بوش", "تیغه برف پاک کن", f"{FX}/img/2_1.jpg", "", ""]])
an = j(c.post("/api/import/analyze", json={"kind": "raw", "data_url": durl(raw), "name": "raw.xlsx"}))
ok(an["rows"] == 3 and an["missing_required"] == ["title"] and an["mapping"]["توضیح کوتاه"] == "short_description", "تحلیل فایل: عنوان پیدا نشد، بقیه نگاشت شد")
am = j(c.post("/api/import/ai-map", json={"kind": "raw", "headers": an["headers"], "preview": an["preview"]}))
ok(am["mapping"]["نام کالا"] == "title" and am["mapping"]["مارک"] == "brand", "نگاشت سرستون‌ها با هوش مصنوعی")
mapping = {**an["mapping"], **{h: k for h, k in am["mapping"].items() if k}}
r = c.post("/api/datasets/import-file", json={"data_url": durl(raw), "name": "raw.xlsx"})
ok(r.status_code == 400 and "عنوان" in r.json()["error"], "بدون ستون عنوان، ورود خطای روشن می‌دهد")
rds = j(c.post("/api/datasets/import-file", json={"data_url": durl(raw), "name": "raw.xlsx", "title": "ورودی آزمایشی", "mapping": mapping}))
ritems = j(c.get(f"/api/datasets/{rds['id']}/items"))["items"]
d0 = j(c.get(f"/api/items/{ritems[0]['id']}"))["data"]
ok(rds["status"] == "completed" and len(ritems) == 3 and d0["brand"] == "کاسپین" and d0["featured_image"].endswith("1_1.jpg") and d0["رنگ"] == "زرد",
   "بانک خام از فایل: ۳ محصول، تصویر و ستون اضافه نگه داشته شد")
jraw = json.loads(c.get("/api/import/sample/raw?format=json").content)
jds = j(c.post("/api/datasets/import-file", json={"data_url": durl(json.dumps(jraw, ensure_ascii=False).encode()), "name": "raw.json"}))
ok(jds["counts"]["done"] == 2, "ورود نمونه‌ی JSON داده‌ی خام")
bank = j(c.post("/api/wb/banks", json={"dataset_ids": [rds["id"]], "title": "از فایل", "rembg": False, "align": False}))
b = wait(f"/api/wb/banks/{bank['id']}", ("completed", "error", "paused"))
prods = j(c.get(f"/api/wb/products?bank_id={bank['id']}"))["rows"]
ok(b["status"] == "completed" and len(prods) == 3 and prods[0]["brand"]["slug"] == "caspian" and prods[0]["images"], "بانک تمیز از داده‌ی واردشده (برند تطبیق، تصویر دانلود)")

print("۷) هوش مصنوعی در برندها و دسته‌ها")
pc_ = j(c.post("/api/ref/brand/ai-complete", json={"ids": [behran["id"]], "fields": ["description", "aliases", "country"]}))
ok(pc_["items"] and pc_["items"][0]["proposal"].get("description"), "پیشنهاد تکمیل برند با AI")
ap = j(c.post("/api/ref/brand/apply", json={"items": [{"id": x["id"], **x["proposal"]} for x in pc_["items"]]}))
bh = j(c.get(f"/api/ref/brand/{behran['id']}"))
ok(ap["updated"] == 1 and bh["description"].startswith("توضیح آزمایشی") and bh["country"] == "ایران", "اعمال پیشنهادهای تأییدشده")
new_un = j(c.post("/api/ref/brand/ai-complete", json={"items": [{"name": "موبیل"}], "fields": ["name_en", "slug", "categories"]}))
ok(new_un["items"][0]["proposal"]["slug"] == "mock-ref-0" and new_un["items"][0]["proposal"]["category_ids"], "تکمیل برند ذخیره‌نشده (فرم افزودن)")
mt = j(c.post("/api/ref/brand/ai-match", json={"names": ["کاسپین ایرانی", "ونوس"]}))
ok(mt["items"][0]["action"] == "link" and mt["items"][1]["action"] == "new" and mt["items"][1]["slug"] == "new-brand-1", "تطبیق نام‌های خام با AI")
gt = j(c.post("/api/ref/category/ai-generate", json={"prompt": "دسته‌های لوازم برقی خودرو"}))
ok(len(gt["items"]) == 3 and gt["items"][1]["parent"] == "electrical", "پیشنهاد درخت دسته با AI")
ga = j(c.post("/api/ref/category/apply", json={"items": gt["items"]}))
ok(ga["added"] == 3 and any(n["slug"] == "electrical" and len(n["nodes"]) == 2 for n in j(c.get("/api/ref/category/tree"))), "درخت پیشنهادی اعمال شد")
gb = j(c.post("/api/ref/brand/ai-generate", json={"prompt": "برندهای روغن موتور", "count": 5}))
ok(gb["items"][0]["slug"] == "liqui-moly" and gb["items"][0]["category_ids"], "پیشنهاد فهرست برند با AI")
gc = j(c.post("/api/ref/category/ai-complete", json={"ids": [cats["gear-oil"]["id"]], "fields": ["name_en", "description"], "only_empty": False}))
ok(gc["items"][0]["proposal"]["name_en"] == "Mock 0", "تکمیل دسته با AI")

print("۸) هوش مصنوعی در الگوی خروجی و تکراری‌ها")
td = j(c.post("/api/cat/templates/ai", json={"prompt": "برای هر محصول یک JSON با عنوان و تصاویر، و برندها در اکسل"}))
ok(not td["errors"] and any(f["path"].endswith(".json") for f in td["tree"]) and td["config"]["outputs"][1]["kind"] == "brands", "طراحی الگو با AI (با پیش‌نمایش درخت)")
pairs = j(c.get(f"/api/dupes?bank_id={bank['id']}"))
ok(pairs, "تکراری‌ها پس از ورود پیدا شدند")
dv = j(c.post(f"/api/dupes/{pairs[0]['id']}/ai", json={}))
ok(dv["same"] and dv["confidence"] == 90 and dv["reason"], "داوری تکراری با AI")
j(c.put("/api/modules/ai", json={"enabled": False}))
ok(c.post("/api/ref/brand/ai-complete", json={"ids": [behran["id"]]}).status_code == 503, "با خاموش بودن ماژول AI، مسیرهایش ۵۰۳")
j(c.put("/api/modules/ai", json={"enabled": True}))

print("۹) خروجی کاتالوگ: دسته‌های برند")
tpl = j(c.post("/api/cat/templates", json={"name": "برند و دسته", "config": {"images": {"enabled": False}, "outputs": [
    {"name": "برندها", "kind": "brands", "format": "json", "path": "brands.json"}, {"name": "دسته‌ها", "kind": "categories", "format": "json", "path": "categories.json"}]}}))
cat_ = j(c.post("/api/cat/catalogs", json={"title": "آزمایش برند", "slug": "brand-test", "template_id": tpl["id"],
                                         "selection": {"bank_ids": [bank["id"]], "statuses": ["draft", "review", "approved"], "require_ready": False, "min_quality": 0}}))
rel = j(c.post(f"/api/cat/catalogs/{cat_['id']}/release", json={"wait": True}))
rel = wait(f"/api/cat/releases/{rel['id']}", ("completed", "error"))
bj = json.loads((Path(rel["root"]) / "brands.json").read_text(encoding="utf-8"))
cj = json.loads((Path(rel["root"]) / "categories.json").read_text(encoding="utf-8"))
ok(rel["status"] == "completed" and "engine-oil" in next(x for x in bj if x["slug"] == "caspian")["category_slugs"], "brands.json با دسته‌های هر برند")
ok("caspian" in next(x for x in cj if x["slug"] == "engine-oil")["brand_slugs"], "categories.json با برندهای قابل نمایش در هر دسته")

print("۱۰) ابزارهای MCP")
from studio import mcp_core  # noqa: E402


class _TCApi(mcp_core.StudioAPI):
    def __init__(self):
        super().__init__("http://testserver")
        self.s, self.base, self._checked = c, "", True

    def call(self, method, path, body=None, params=None, timeout=600):
        r = c.request(method, path, json=body, params=params, headers={"X-Studio-Client": "mcp"})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.content}
        if r.status_code >= 400:
            raise mcp_core.ToolError(data.get("error"))
        return data


srv = mcp_core.Server(_TCApi())


def mcp(_tool, **args):
    r = srv.call_tool(_tool, args)
    if r["isError"]:
        raise AssertionError(r["content"][0]["text"])
    t = r["content"][0]["text"]
    return json.loads(t) if t[:1] in "[{" else t


ok(mcp_core.SERVER_VERSION == "2.1.0", "نسخه‌ی سرور MCP ۲.۱.۰")
ok(any(n["slug"] == "electrical" for n in mcp("category_tree")), "category_tree")
ok(mcp("bulk_reference", kind="brand", ids=[behran["id"]], action="set_country", value="ایران")["done"] == 1, "bulk_reference")
ok(mcp("import_format", kind="raw")["columns"][0]["key"] == "title", "import_format")
tsv = "title,brand\nمحصول ام‌سی‌پی,بوش\n"
ok(mcp("import_dataset_file", data_base64=base64.b64encode(tsv.encode()).decode(), name="m.csv")["counts"]["done"] == 1, "import_dataset_file")
ok(mcp("import_reference_file", kind="brand", data_base64=base64.b64encode("name,name_en\nالف,Alef\n".encode()).decode(), name="b.csv")["added"] == 1, "import_reference_file")
ok(mcp("ai_complete_reference", kind="category", ids=[cats["engine-oil"]["id"]], fields=["description"])["items"], "ai_complete_reference")
ok(mcp("ai_design_template", prompt="هر محصول یک فایل")["config"]["outputs"], "ai_design_template")
ok(mcp("ai_check_duplicate", pair_id=pairs[0]["id"])["same"], "ai_check_duplicate")
ok(len(mcp("export_reference", kind="brand")) >= 4, "export_reference")

print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
