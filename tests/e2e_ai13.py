"""تست نسخه‌ی ۱.۳: دستیار هوش مصنوعی در همه‌جا و تولید بانک داده/محصول بدون اسکرپ."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-ai13").resolve()
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


def wait_ds(did, until=("completed", "error", "paused", "stopped"), t=120):
    t0 = time.time()
    while time.time() - t0 < t:
        d = j(c.get(f"/api/datasets/{did}"))
        if d["status"] in until:
            return d
        time.sleep(0.5)
    raise SystemExit(f"timeout {d['status']} {d['step']}")


j(c.put("/api/settings", json={"delay_min_ms": 10, "delay_max_ms": 20, "output_root": str(DATA / "output"), "queue_enabled": False}))
prov = j(c.post("/api/ai/providers", json={"name": "mock", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key",
                                          "text_model": "mock-text", "image_model": "mock-image", "image_mode": "images_api"}))
j(c.put("/api/settings", json={"ai_default_provider_id": prov["id"]}))

print("۱) دستیار همه‌منظوره")
r = j(c.post("/api/ai/assist", json={"task": "text", "label": "عنوان بانک داده", "instruction": "یک عنوان بنویس", "page": "بانک داده"}))
ok(r["ok"] and "عنوان بانک داده" in r["value"], f"متن آزاد: «{r.get('value')}»")
r = j(c.post("/api/ai/assist", json={"task": "text", "label": "کلیدواژه‌ها", "format": "slug", "instruction": "x"}))
ok(r["ok"] and r["value"] == r["value"].lower() and " " not in r["value"], f"قالب اسلاگ: {r['value']}")
sc = j(c.post("/api/ai/assist", json={"task": "schema", "description": "اسکیمای کاتالوگ لاستیک خودرو"}))
keys = [x["key"] for x in sc["columns"]]
ok(sc["ok"] and len(sc["columns"]) == 12 and len(set(keys)) == 12 and all(x["kind"] in ("manual", "scraped", "constant", "mapping", "auto") for x in sc["columns"]),
   f"ساخت اسکیما: {len(keys)} ستون یکتا")
new_schema = j(c.post("/api/schemas", json={"name": sc["name"], "columns": sc["columns"]}))
col = j(c.post("/api/ai/assist", json={"task": "column", "description": "ستونی برای گارانتی", "schema_columns": sc["columns"]}))
ok(col["ok"] and col["column"]["key"] not in keys, f"پیشنهاد ستون: {col['column']['key']} / {col['column']['input']}")
mp = j(c.post("/api/ai/assist", json={"task": "mappings", "kind": "category", "values": ["روغن موتور", "ضدیخ"]}))
ok(mp["ok"] and [x["target_slug"] for x in mp["rows"]] == ["slug-0", "slug-1"], "پیشنهاد نگاشت (اسلاگ استاندارد)")
rl = j(c.post("/api/ai/assist", json={"task": "rules", "description": "نام فروشگاه‌ها را حذف کن"}))
ok(rl["ok"] and rl["rules"][0]["action"] == "remove" and rl["rules"][0]["find"] == "دیجی‌کالا", "ساخت قاعده از توصیف")

print("۲) تولید بانک داده بدون اسکرپ")
schema_id = j(c.get("/api/schemas"))[0]["id"]
ds = j(c.post("/api/ai/datasets", json={"product_type": "روغن موتور بنزینی", "category_label": "روغن موتور", "brands": "بهران، کاسپین",
                                       "count": 5, "schema_id": schema_id, "images": {"enabled": True, "count": 2}}))
ok(ds["source"]["key"] == "ai-generated" and ds["item_limit"] == 5, f"بانک ساخته شد: {ds['code']}")
d = wait_ds(ds["id"])
ok(d["status"] == "completed" and d["counts"]["done"] == 5, f"۵ محصول تولید شد ({d['name']})")
items = j(c.get(f"/api/datasets/{ds['id']}/items"))["items"]
titles = [i["title"] for i in items]
ok(len(set(titles)) == 5, "عنوان‌ها یکتا")
it = j(c.get(f"/api/items/{items[0]['id']}/detail"))
cols = it["columns"]
ok(it["scraped_data_after_rules"]["specifications"] and cols["long_description"]["value"] and cols["vendor_notes"]["value"]
   and cols["user_dos_donts_description"]["value"]["dos"], "همه‌ی فیلدهای اسکیما پر شد (توضیحات، مشخصات، بایدها/نبایدها، …)")
ok(cols["dimensions"]["value"]["item_weight"] == "123" and cols["dimension_codes"]["value"].get("volume") == "4 لیتر", "ابعاد و متغیرها")
ok(Path(cols["featured_images"]["value"]).exists() and len(cols["images_gallery"]["value"]) == 1, "تصویر شاخص + ۱ تصویر گالری تولید شد")
ok(cols["source_url"]["value"] == "", "لینک منبع برای محصول تولیدی خالی است")

print("۳) توقف و ادامه")
fixture_site.AI_DELAY[0] = 0.4
ds2 = j(c.post("/api/ai/datasets", json={"product_type": "ضدیخ", "count": 12, "concurrency": 1}))
t0 = time.time()
while j(c.get(f"/api/datasets/{ds2['id']}"))["counts"]["done"] < 2 and time.time() - t0 < 60:
    time.sleep(0.1)
j(c.post(f"/api/datasets/{ds2['id']}/do/pause", json={}))
d2 = wait_ds(ds2["id"], ("paused", "completed"))
n_at_pause = d2["counts"]["done"]
j(c.post(f"/api/datasets/{ds2['id']}/do/resume", json={}))
d2 = wait_ds(ds2["id"], ("completed", "error"))
fixture_site.AI_DELAY[0] = 0
ok(0 < n_at_pause < 12 and d2["counts"]["done"] == 12 and d2["counts"]["total"] == 12, f"متوقف در {n_at_pause}، ادامه تا ۱۲ بدون تکرار")

print("۴) افزودن محصول تولیدی به بانک اسکرپ‌شده")
j(c.post("/api/sources", json={"config": {"key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
                                          "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page"}},
                                          "product": {"mode": "http"}}}))
sd = j(c.post("/api/datasets", json={"category_url": FX + "/category/oils", "limit": 3}))
wait_ds(sd["id"])
j(c.post(f"/api/datasets/{sd['id']}/ai-add", json={"count": 2, "product_type": "روغن موتور دیزلی"}))
sd2 = wait_ds(sd["id"])
its = j(c.get(f"/api/datasets/{sd['id']}/items"))["items"]
ok(sd2["counts"]["done"] == 5 and sum(1 for i in its if i["url"].startswith("ai-generated:")) == 2, "۳ اسکرپ‌شده + ۲ تولیدی در یک بانک")
ok(not (sd2["options"].get("ai_generate") or {}).get("active"), "پس از پایان، بانک به حالت عادی برگشت")

print("۵) تولید یک ستون برای کل بانک و یک فیلد برای یک محصول")
job = j(c.post(f"/api/datasets/{sd['id']}/ai-column", json={"column": "vendor_notes", "mode": "overwrite", "instruction": "یک جمله درباره‌ی نصب"}))
t0 = time.time()
while True:
    jj = next(x for x in j(c.get("/api/ai/jobs")) if x["id"] == job["id"])
    if jj["status"] in ("completed", "error") or time.time() - t0 > 60:
        break
    time.sleep(0.5)
ok(jj["status"] == "completed" and jj["progress_done"] == 5 and "ستون" in jj["profile"]["name"], f"ستون vendor_notes برای {jj['progress_done']} محصول")
scraped_item = next(i for i in its if not i["url"].startswith("ai-generated:"))
f = j(c.post("/api/ai/assist", json={"task": "field", "item_id": scraped_item["id"], "column": "short_description", "mode": "rewrite", "save": True}))
it2 = j(c.get(f"/api/items/{scraped_item['id']}/detail"))
ok(f["ok"] and it2["columns"]["short_description"]["source"] == "ai_or_agent", "تولید یک فیلد محصول (ذخیره‌ی برگشت‌پذیر)")
f2 = j(c.post("/api/ai/assist", json={"task": "field", "item_id": scraped_item["id"], "column": "user_dos_donts_description"}))
ok(isinstance(f2["value"], dict) and set(f2["value"]) == {"dos", "donts", "pre_post_purchase"}, "فیلد چندبخشی با شکل درست")
r = j(c.put(f"/api/items/{scraped_item['id']}", json={"ai_set": {"vendor_notes": "پیشنهاد دستیار"}}))
ok(r["preview"]["vendor_notes"]["value"] == "پیشنهاد دستیار" and r["preview"]["vendor_notes"]["flag"] == "ai", "ai_set از ویرایشگر محصول")
rg = j(c.post(f"/api/items/{items[1]['id']}/rescrape", json={}))
ok(rg["status"] == "done" and rg["data"].get("_ai_generated"), "تولید دوباره‌ی یک محصول تولیدی")

print("۶) تحلیل ساختار منبع با هوش مصنوعی")
srcs = j(c.get("/api/sources"))
shop = next(s for s in srcs if s["key"] == "fixture-shop")
t = j(c.post(f"/api/sources/{shop['id']}/test-product", json={"url": FX + "/product/p-3"}))
sf = j(c.post("/api/ai/assist", json={"task": "source_fields", "explorer": t["explorer"], "record": t["record"]}))
ok(sf["ok"] and {x["key"] for x in sf["fields"]} >= {"title", "brand", "gallery"} and sf["fields"][0]["strategies"][0]["type"] == "jsonld",
   "پیشنهاد مسیر فیلدها از روی داده‌ی صفحه")

print("۷) خروجی و صف")
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "zip": False, "rembg": False, "align": False}))
t0 = time.time()
while True:
    e = j(c.get(f"/api/exports/{ex['id']}"))
    if e["status"] in ("completed", "error") or time.time() - t0 > 60:
        break
    time.sleep(0.5)
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(e["result"]["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
row = {hdr[i]: ws.cell(row=2, column=i + 1).value for i in range(len(hdr))}
folder = DATA / "output" / e["name"]
ok(e["status"] == "completed" and ws.max_row == 6 and row["featured_images"].endswith("feature.png") and len(list(folder.iterdir())) == 5,
   "خروجی Excel و پوشه‌ی تصاویر محصولات تولیدی")
q = j(c.post("/api/queue", json={"ai_generate": {"product_type": "شامپو خودرو", "count": 3}, "title": "تولید از صف"}))
j(c.post("/api/queue/toggle", json={"enabled": True}))
t0 = time.time()
while True:
    qj = next(x for x in j(c.get("/api/queue"))["jobs"] if x["id"] == q["id"])
    if qj["status"] in ("done", "failed") or time.time() - t0 > 90:
        break
    time.sleep(0.7)
ok(qj["status"] == "done" and qj["dataset"]["counts"]["done"] == 3, "کار صف از نوع «تولید با هوش مصنوعی»")

print("۸) ابزارهای MCP نسخه‌ی ۱.۳")
import json as _json  # noqa: E402
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
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    res = r["result"]
    if res.get("isError"):
        print(res["content"][0]["text"])
    return res, _json.loads(res["content"][0]["text"]) if not res.get("isError") else None


tl = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})["result"]["tools"]
names = {t["name"] for t in tl}
ok({"ai_assist", "generate_dataset_with_ai", "ai_add_products", "ai_generate_column", "regenerate_ai_item"} <= names, f"{len(names)} ابزار MCP")
_, a1 = mcall("ai_assist", {"task": "text", "payload": {"label": "توضیح کوتاه", "instruction": "بنویس"}})
ok(a1 and a1["ok"] and a1["value"], "ai_assist از طریق MCP")
_, g1 = mcall("generate_dataset_with_ai", {"product_type": "واکس لاستیک", "count": 2, "images": False})
ok(g1 and g1["id"], "generate_dataset_with_ai")
d3 = wait_ds(g1["id"])
ok(d3["status"] == "completed" and d3["counts"]["done"] == 2, "بانک داده‌ی تولیدی MCP کامل شد")
_, g2 = mcall("ai_add_products", {"dataset_id": g1["id"], "count": 1, "images": False})
d3 = wait_ds(g1["id"])
ok(d3["counts"]["done"] == 3, "ai_add_products")
_, g3 = mcall("ai_generate_column", {"dataset_id": g1["id"], "column": "vendor_notes", "mode": "overwrite"})
ok(g3 and g3["id"], "ai_generate_column")
_, w = mcall("wait_for", {"kind": "ai_job", "id": g3["id"], "timeout_s": 60})
ok(w["finished"] and w["state"]["status"] == "completed", "کار تولید ستون از MCP تمام شد")
_, g4 = mcall("generate_dataset_with_ai", {"product_type": "خوشبوکننده", "count": 2, "queue": True})
ok(g4 and g4["queued_job"]["id"], "generate_dataset_with_ai در صف")
pr = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "generate_catalog_with_ai", "arguments": {"product_type": "x", "count": "3"}}})
ok("generate_dataset_with_ai" in pr["result"]["messages"][0]["content"]["text"], "پرامپت ساخت کاتالوگ با AI")

print(f"\n(درخواست‌های سرویس ساختگی: {fixture_site.AI_CALLS})")
print("همه‌ی آزمون‌ها موفق بود ✅")
