"""تست MCP: یک ایجنت واقعی از راه stdio، Streamable HTTP و SSE به استودیو وصل می‌شود."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-mcp").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
for m in (ROOT / "data" / "models").glob("*.onnx"):
    os.symlink(m, DATA / "models" / m.name)
PORT = 8777
os.environ.update({"CATALOG_STUDIO_DATA": str(DATA), "CATALOG_STUDIO_PORT": str(PORT)})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import requests  # noqa: E402
import uvicorn  # noqa: E402

import fixture_site  # noqa: E402
from studio.api import create_app  # noqa: E402

threading.Thread(target=fixture_site.serve, args=(8899,), daemon=True).start()
srv = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=srv.run, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
FX = "http://127.0.0.1:8899"
S = requests.Session()
S.trust_env = False
for _ in range(40):
    try:
        S.get(BASE + "/api/settings", timeout=1)
        break
    except requests.RequestException:
        time.sleep(0.25)


def ok(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        raise SystemExit(1)


S.put(BASE + "/api/settings", json={"delay_min_ms": 10, "delay_max_ms": 20, "output_root": str(DATA / "output"), "max_retries": 1, "queue_enabled": False})
S.post(BASE + "/api/sources", json={"config": {
    "key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
    "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page", "start": 1}},
    "product": {"mode": "http"},
    "fields": [{"key": "gallery", "strategies": [{"type": "css", "selector": ".product-gallery img", "attr": "src", "all": True}], "transforms": ["strip_query"]}]}})


class StdioClient:
    def __init__(self, env_extra=None):
        env = {**os.environ, "CATALOG_STUDIO_URL": BASE, "CATALOG_STUDIO_AUTOSTART": "0", **(env_extra or {})}
        self.p = subprocess.Popen([sys.executable, str(ROOT / "mcp_server.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, cwd="/", text=True, encoding="utf-8", bufsize=1)
        self.n = 0

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise SystemExit("stdio server died: " + self.p.stderr.read())
        r = json.loads(line)
        assert r["id"] == self.n
        return r

    def call(self, name, args=None):
        r = self.rpc("tools/call", {"name": name, "arguments": args or {}})["result"]
        if r.get("isError"):
            return r, None
        txt = r["content"][0]["text"]
        try:
            return r, json.loads(txt)
        except ValueError:
            return r, txt

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


print("۱) اتصال stdio (مثل Claude Desktop / opencode / Hermes)")
c = StdioClient()
init = c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test-agent", "version": "1"}})
c.rpc("notifications/initialized", notify=True)
ok(init["result"]["protocolVersion"] == "2025-06-18" and "Mega Catalog Studio" in init["result"]["instructions"], "initialize و دستورالعمل سرور")
old = c.rpc("initialize", {"protocolVersion": "2024-11-05"})
ok(old["result"]["protocolVersion"] == "2024-11-05", "سازگاری با نسخه‌ی قدیمی پروتکل")
tools = c.rpc("tools/list")["result"]["tools"]
names = {t["name"] for t in tools}
ok(len(tools) >= 60 and {"set_item_fields", "generate_item_image", "start_extraction", "create_export", "find_gaps"} <= names, f"{len(tools)} ابزار")
ok(all(t["inputSchema"]["type"] == "object" for t in tools), "اسکیمای ورودی همه‌ی ابزارها معتبر")
ok(len(c.rpc("resources/list")["result"]["resources"]) == 5 and len(c.rpc("resources/templates/list")["result"]["resourceTemplates"]) == 3, "منابع و قالب منابع")
pr = c.rpc("prompts/get", {"name": "complete_missing_fields", "arguments": {"dataset_id": "1"}})["result"]
ok("find_gaps" in pr["messages"][0]["content"]["text"], "پرامپت آماده‌ی «تکمیل اطلاعات ناقص»")
ok(c.rpc("foo/bar")["error"]["code"] == -32601, "پاسخ استاندارد به متد ناشناخته")

print("۲) استخراج از طریق ایجنت")
_, ov = c.call("studio_overview")
ok(ov["counts"]["sources"] == 5, "studio_overview")
_, ds = c.call("start_extraction", {"category_url": FX + "/category/oils", "limit": 3, "policies": {"not_found": "skip", "missing_fields": "continue_partial"}})
did = ds["id"]
_, w = c.call("wait_for", {"kind": "dataset", "id": did, "timeout_s": 90})
ok(w["finished"] and w["state"]["status"] == "completed" and w["state"]["counts"]["done"] == 3, "start_extraction + wait_for: ۳ محصول")
_, items = c.call("list_items", {"dataset_id": did})
iid = items["items"][0]["id"]
_, gaps = c.call("find_gaps", {"dataset_id": did})
ok(gaps["items_with_gaps"] == 3 and gaps["empty_count_by_column"].get("vendor_notes") == 3, f"find_gaps: {gaps['empty_count_by_column']}")
_, it = c.call("get_item", {"item_id": iid})
ok(it["columns"]["title"]["value"] and it["columns"]["vendor_notes"]["empty"] and it["scraped_data_after_rules"]["specifications"], "get_item: ستون‌ها و داده‌ی خام")

print("۳) تکمیل و ویرایش توسط ایجنت")
r, it2 = c.call("set_item_fields", {"item_id": iid, "values": {
    "vendor_notes": "نصب رایگان در محل کسب‌وکار",
    "user_dos_donts_description": {"dos": ["سطح روغن را ماهانه بررسی کنید"], "donts": ["با روغن دیگر مخلوط نکنید"], "pre_post_purchase": ["فاکتور را نگه دارید"]},
    "dimensions": {"packaging_weight": "۴۲۰۰"}, "short_description": "روغن موتور مناسب خودروهای بنزینی."}})
ok(not r.get("isError") and it2["columns"]["vendor_notes"]["source"] == "ai_or_agent", "set_item_fields (برگشت‌پذیر)")
ok(it2["columns"]["dimensions"]["value"]["packaging_weight"] == "4200", "عدد فارسی به لاتین تبدیل شد")
r, bad = c.call("set_item_fields", {"item_id": iid, "values": {"not_a_column": "x"}})
ok(r["isError"] and "ستون‌های مجاز" in r["content"][0]["text"], "خطای روشن برای ستون ناموجود")
_, g2 = c.call("find_gaps", {"dataset_id": did})
ok(g2["empty_count_by_column"].get("vendor_notes") == 2, "کمبودها پس از تکمیل کم شد")
c.call("bulk_set_fields", {"dataset_id": did, "values": {"vendor_notes": "ارسال با پیک"}, "mode": "override"})
_, it3 = c.call("get_item", {"item_id": items["items"][1]["id"]})
ok(it3["columns"]["vendor_notes"]["value"] == "ارسال با پیک", "bulk_set_fields روی کل بانک")

print("۴) تصاویر")
r, meta = c.call("get_item_images", {"item_id": iid, "max": 3})
pics = [x for x in r["content"] if x["type"] == "image"]
ok(len(pics) == 3 and pics[0]["mimeType"] == "image/jpeg", "get_item_images: ایجنت تصویر محصول را می‌بیند")
_, prov = c.call("save_ai_provider", {"name": "mock", "kind": "openai", "base_url": FX + "/ai/openai/v1", "api_key": "test-key",
                                      "text_model": "mock-text", "image_model": "mock-image", "image_mode": "images_api"})
_, t = c.call("test_ai_provider", {"provider_id": prov["id"]})
ok(t["ok"], "save_ai_provider + test_ai_provider")
r, gi = c.call("generate_item_image", {"item_id": iid, "mode": "add", "target": "images_gallery"})
ok(not r.get("isError") and any(x["type"] == "image" for x in r["content"]) and Path(gi["paths"][0]).exists(), "generate_item_image: تصویر ساخته و برگردانده شد")
buf = io.BytesIO()
from PIL import Image  # noqa: E402
Image.new("RGB", (64, 64), (10, 120, 200)).save(buf, "PNG")
r, at = c.call("attach_item_image", {"item_id": iid, "data_base64": base64.b64encode(buf.getvalue()).decode(), "mode": "add"})
ok(not r.get("isError"), "attach_item_image (base64)")
_, it4 = c.call("get_item", {"item_id": iid})
ok(len(it4["columns"]["images_gallery"]["value"]) == 4, "گالری: ۲ تصویر اصلی + تولیدی + پیوستی")

print("۵) هوش مصنوعی، قواعد، صف، خروجی")
_, profs = c.call("list_ai_profiles")
_, sp = c.call("save_ai_profile", {"profile_id": profs["profiles"][0]["id"], "name": profs["profiles"][0]["name"], "config": {"provider_id": prov["id"]}})
r, pv = c.call("ai_preview", {"item_id": items["items"][2]["id"], "profile_id": sp["id"]})
ok(pv["ok"] and "long_description" in pv["fields"], "ai_preview با هوش مصنوعی خود استودیو")
_, job = c.call("run_ai_generation", {"dataset_id": did, "profile_id": sp["id"]})
_, wj = c.call("wait_for", {"kind": "ai_job", "id": job["id"], "timeout_s": 60})
ok(wj["state"]["status"] == "completed", "run_ai_generation + wait_for")
_, rule = c.call("save_rule", {"name": "حذف دیجی‌کالا", "action": "remove", "target": "*", "find": "دیجی‌کالا"})
_, tr = c.call("test_rules", {"text": "خرید از دیجی‌کالا"})
ok(tr["output"] == "خرید از", "save_rule + test_rules")
_, qj = c.call("add_queue_job", {"category_url": FX + "/category/oils", "limit": 2, "title": "از ایجنت"})
_, ql = c.call("list_queue")
ok(any(j["id"] == qj["id"] for j in ql["jobs"]) and not ql["enabled"], "add_queue_job + list_queue")
_, ex = c.call("create_export", {"dataset_ids": [did], "rembg": False, "zip": False})
_, we = c.call("wait_for", {"kind": "export", "id": ex["id"], "timeout_s": 90})
ok(we["state"]["status"] == "completed", "create_export + wait_for")
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(we["state"]["result"]["files"]["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
row = {hdr[i]: ws.cell(row=2, column=i + 1).value for i in range(len(hdr))}
ok(row["vendor_notes"] in ("نصب رایگان در محل کسب‌وکار", "ارسال با پیک") and "gallery_4.png" in row["images_gallery"], "نتیجه‌ی کار ایجنت در Excel")
txt = c.rpc("resources/read", {"uri": f"studio://dataset/{did}/gaps"})["result"]["contents"][0]["text"]
ok(json.loads(txt)["dataset_id"] == did, "resources/read")
c.close()

print("۶) حالت فقط‌خواندنی")
ro = StdioClient({"CATALOG_STUDIO_MCP_READONLY": "1"})
ro.rpc("initialize", {"protocolVersion": "2025-06-18"})
rt = {t["name"] for t in ro.rpc("tools/list")["result"]["tools"]}
r, _ = ro.call("set_item_fields", {"item_id": iid, "values": {"vendor_notes": "x"}})
ok("set_item_fields" not in rt and "get_item" in rt and r["isError"], f"فقط {len(rt)} ابزار خواندنی")
ro.close()

print("۷) Streamable HTTP و توکن")
h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
r = S.post(BASE + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}, headers=h)
ok(r.status_code == 200 and r.headers.get("Mcp-Session-Id") and r.json()["result"]["protocolVersion"] == "2025-03-26", "initialize روی /mcp")
r = S.post(BASE + "/mcp", json=[{"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                                                          "params": {"name": "list_datasets", "arguments": {}}}], headers=h)
ok(r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == 1, "پیام دسته‌ای (batch)")
ok(S.post(BASE + "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h).status_code == 202, "اعلان بدون پاسخ: 202")
tok = S.post(BASE + "/api/mcp/token", json={}).json()["token"]
call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "studio_overview", "arguments": {}}}
ok(S.post(BASE + "/mcp", json=call, headers=h).status_code == 401, "بدون توکن: 401")
ok(S.post(BASE + "/mcp", json=call, headers={**h, "Authorization": f"Bearer {tok}"}).status_code == 200, "Authorization: Bearer")
ok(S.post(BASE + f"/mcp/t/{tok}", json=call, headers=h).status_code == 200, "توکن داخل نشانی (برای ChatGPT)")
ext = {"Host": "abc.trycloudflare.com"}
ok(S.get(BASE + "/api/settings", headers=ext).status_code == 403, "از بیرون (تونل): رابط و API استودیو بسته است")
ok(S.post(BASE + f"/mcp/t/{tok}", json=call, headers={**h, **ext}).status_code == 200, "از بیرون: MCP با توکن باز است")
ok(S.post(BASE + "/mcp/t/wrong", json=call, headers={**h, **ext}).status_code == 401, "از بیرون با توکن نادرست: 401")

print("۸) SSE قدیمی")
got: dict = {}


def sse_reader():
    with S.get(BASE + f"/mcp/sse?token={tok}", stream=True, timeout=30) as resp:
        ev = None
        for line in resp.iter_lines(decode_unicode=True):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                got.setdefault(ev, []).append(line[5:].strip())
                if ev == "message":
                    return


th = threading.Thread(target=sse_reader, daemon=True)
th.start()
for _ in range(50):
    if got.get("endpoint"):
        break
    time.sleep(0.1)
ep = got["endpoint"][0]
r = S.post(BASE + ep, json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
th.join(10)
ok(r.status_code == 202 and json.loads(got["message"][0])["id"] == 9, f"SSE: endpoint={ep.split('?')[0]} و پاسخ روی جریان رویداد")

print("۹) نصب خودکار در پیکربندی کلاینت‌ها")
home = DATA / "home"
home.mkdir()
os.environ["HOME"] = str(home)
os.environ["APPDATA"] = str(home / "AppData")
cfg = home / ".config" / "Claude" / "claude_desktop_config.json"
cfg.parent.mkdir(parents=True)
cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
for cl in ("claude_desktop", "opencode", "cursor", "antigravity"):
    r = S.post(BASE + "/api/mcp/install", json={"client": cl}).json()
    ok(r.get("ok"), f"نصب در {r.get('client')}: {r.get('path', '').replace(str(home), '~')}")
cd = json.loads(cfg.read_text(encoding="utf-8"))
ok("other" in cd["mcpServers"] and cd["theme"] == "dark" and cd["mcpServers"]["mega-catalog-studio"]["args"][0].endswith("mcp_server.py"),
   "پیکربندی قبلی Claude Desktop حفظ شد و پشتیبان گرفته شد")
oc = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
ok(oc["mcp"]["mega-catalog-studio"]["type"] == "local", "قالب opencode")
info = S.get(BASE + "/api/mcp/info").json()
ok({c["id"] for c in info["clients"]} >= {"claude_desktop", "opencode", "chatgpt", "antigravity", "hermes", "cursor", "codex", "generic"},
   f"راهنمای اتصال برای {len(info['clients'])} کلاینت")
st = S.post(BASE + "/api/mcp/selftest", json={}).json()
ok(st["ok"] and st["tools"] == len(tools), "خودآزمایی MCP از داخل استودیو")
print("\nهمه‌ی آزمون‌ها موفق بود ✅")
srv.should_exit = True
