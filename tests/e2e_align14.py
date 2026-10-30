"""تست نسخه‌ی ۱.۴: ترازبندی تصاویر (تریم فضای خالی + فاصله‌ی ثابت از لبه‌ها + حفظ نسبت ابعاد)."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cs-align14").resolve()
if DATA.exists():
    shutil.rmtree(DATA)
(DATA / "models").mkdir(parents=True)
for m in (ROOT / "data" / "models").glob("*.onnx"):
    os.symlink(m, DATA / "models" / m.name)
os.environ.update({"CATALOG_STUDIO_DATA": str(DATA), "CATALOG_STUDIO_ALLOWED_HOSTS": "testserver"})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image, ImageDraw  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import fixture_site  # noqa: E402
from studio.api import create_app  # noqa: E402
from studio import align as A  # noqa: E402

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


def wait_bg(jid, t=120):
    t0 = time.time()
    while time.time() - t0 < t:
        b = next(x for x in j(c.get("/api/bg")) if x["id"] == jid)
        if b["status"] in ("completed", "error", "paused"):
            return b
        time.sleep(0.3)
    raise SystemExit("timeout")


def subject_box(im: Image.Image, bg=None):
    if bg is None:
        return im.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
    import numpy as np
    arr = np.asarray(im.convert("RGB")).astype(int)
    m = (np.abs(arr - np.array(bg)).max(axis=2) > 40)
    rows, cols = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def check_fit(box, size, margins, ratio, tol=2):
    """بُعد تعیین‌کننده دقیقاً روی حاشیه، بُعد دیگر وسط، و نسبت ابعاد ثابت."""
    W, H = size
    t, r, b, l = margins
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    aw, ah = W - l - r, H - t - b
    fits_w = abs(x0 - l) <= tol and abs((W - x1) - r) <= tol
    fits_h = abs(y0 - t) <= tol and abs((H - y1) - b) <= tol
    inside = x0 >= l - tol and y0 >= t - tol and x1 <= W - r + tol and y1 <= H - b + tol
    centered_x = abs((x0 - l) - (l + aw - x1)) <= tol + 1
    centered_y = abs((y0 - t) - (t + ah - y1)) <= tol + 1
    r2 = w / h
    return inside and (fits_w or fits_h) and centered_x and centered_y and abs(r2 - ratio) / ratio < 0.02


# ---------------------------------------------------------------------------
print("۱) هندسه‌ی ترازبندی روی تصاویر ساختگی")
SRC = DATA / "imgs" / "batch"
cases = {}


def save(rel, im):
    p = SRC / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p)
    return p


# الف) بطری بلند با فضای خالی زیاد و یک لکه‌ی جدا
im = Image.new("RGBA", (900, 700), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle([400, 100, 499, 499], 12, fill=(200, 20, 20, 255))
d.rectangle([10, 10, 11, 11], fill=(0, 0, 0, 255))
d.rectangle([400, 520, 499, 540], fill=(0, 0, 0, 5))  # سایه‌ی بسیار کم‌رنگ
cases["p-bottle/feature.png"] = (save("p-bottle/feature.png", im), 100 / 400)
# ب) محصول پهن و کوچک وسط یک بوم بزرگ
im = Image.new("RGBA", (2400, 2400), (0, 0, 0, 0))
ImageDraw.Draw(im).ellipse([1000, 1150, 1399, 1249], fill=(30, 90, 200, 255))
cases["p-wide/feature.png"] = (save("p-wide/feature.png", im), 400 / 100)
# ج) JPG با پس‌زمینه‌ی سفید (بدون شفافیت)
im = Image.new("RGB", (1000, 800), (255, 255, 255))
ImageDraw.Draw(im).rectangle([300, 200, 699, 599], fill=(20, 20, 20))
cases["p-jpg/gallery_1.jpg"] = (save("p-jpg/gallery_1.jpg", im), 1.0)
# د) سوژه‌ای که از قبل لبه‌به‌لبه است
im = Image.new("RGBA", (300, 600), (10, 160, 60, 255))
cases["p-full/feature.png"] = (save("p-full/feature.png", im), 0.5)

M = 60
b = j(c.post("/api/bg", json={"input_path": str(SRC), "rembg": False, "align": {"margin": M}}))
ok(b["output_path"].endswith(os.path.join("aligned", "batch")), f"خروجی پیش‌فرض ترازبندی: {b['output_path']}")
b = wait_bg(b["id"])
ok(b["status"] == "completed" and b["progress_done"] == 4 and not b["failed"], "کار ترازبندی بدون حذف پس‌زمینه تمام شد")
OUT = Path(b["output_path"])
for rel, (_, ratio) in cases.items():
    p = (OUT / rel).with_suffix(".png")
    out = Image.open(p)
    bg = (255, 255, 255) if rel.endswith(".jpg") else None
    box = subject_box(out, bg)
    ok(out.size == (1280, 1280) and check_fit(box, (1280, 1280), (M, M, M, M), ratio),
       f"{rel}: سوژه {box} ← فاصله‌ی {M} پیکسل از لبه‌ی تعیین‌کننده، وسط‌چین، نسبت {ratio:.2f} حفظ شد")
jpgout = Image.open(OUT / "p-jpg" / "gallery_1.png")
ok(jpgout.getpixel((5, 5)) == (255, 255, 255, 255), "تصویر بدون شفافیت: پس‌زمینه‌ی خودکار همان رنگ اصلی (سفید)")
st = b["options"]["stats"]
ok(st["upscaled"] >= 3, f"آمار: {st}")

print("۲) لکه‌ی ریز، حاشیه‌ی جداگانه، بدون بزرگ‌نمایی و فرمت JPG")
src = Image.open(cases["p-bottle/feature.png"][0])
out, info = A.align_image(src, {"margin": 100, "despeckle": 0})
ok(info["bbox"][0] == 10 and info["bbox"][1] == 10, "بدون حذف لکه، لکه‌ی گوشه جزو سوژه حساب می‌شود")
out, info = A.align_image(src, {"margin": 100})
ok(info["bbox"] == [400, 100, 500, 500], f"با «نادیده گرفتن لکه‌ها» کادر دقیق سوژه: {info['bbox']} (سایه‌ی کم‌رنگ هم حذف شد)")
ok(info["limited_by"] == "height" and info["placed"][1] == 100 and info["placed"][3] == 1080, f"ارتفاع تعیین‌کننده: {info['placed']}")
out, info = A.align_image(src, {"per_side": True, "margin_top": 200, "margin_bottom": 40, "margin_left": 60, "margin_right": 60})
ok(check_fit(subject_box(out), (1280, 1280), (200, 60, 40, 60), 0.25), f"حاشیه‌ی جداگانه برای هر لبه: {info['placed']}")
out, info = A.align_image(Image.open(cases["p-wide/feature.png"][0]), {"margin": 60, "upscale": False})
ok(info["scale"] == 1 and info["placed"][2:] == [400, 100], "بدون بزرگ‌نمایی: سوژه‌ی کوچک فقط وسط بوم")
out, info = A.align_image(src, {"margin": 80, "canvas_w": 1600, "canvas_h": 1000})
ok(out.size == (1600, 1000) and check_fit(subject_box(out), (1600, 1000), (80, 80, 80, 80), 0.25), "بوم غیرمربعی ۱۶۰۰×۱۰۰۰")
p = A.save_image(out, DATA / "x.jpg", A.normalize({"format": "jpg"}))
ok(Image.open(p).mode == "RGB", "خروجی JPG")
try:
    A.normalize({"margin": 700})
    ok(False, "حاشیه‌ی نامعتبر")
except ValueError:
    ok(True, "حاشیه‌ی بزرگ‌تر از بوم رد می‌شود")
r = c.post("/api/bg", json={"input_path": str(SRC), "rembg": False, "align": False})
ok(r.status_code == 400, "بدون هیچ مرحله‌ای، کار ساخته نمی‌شود")

print("۳) پیش‌نمایش")
pv = j(c.post("/api/align/preview", json={"path": str(SRC), "options": {"margin": 100}}))
ok(pv["ok"] and len(pv["samples"]) == 4 and all(s["after"].startswith("data:image/png") for s in pv["samples"]), "پیش‌نمایش ۴ نمونه از پوشه")
ok(pv["samples"][0]["info"]["margins"] == [100, 100, 100, 100], "پیش‌نمایش با قاعده‌ی تازه")
buf = io.BytesIO()
Image.open(cases["p-jpg/gallery_1.jpg"][0]).save(buf, "JPEG")
pv = j(c.post("/api/align/preview", json={"data_url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "options": {"margin": 60}}))
ok(pv["ok"] and pv["samples"][0]["info"]["trim"] == "color", "پیش‌نمایش تصویر بارگذاری‌شده (تریم رنگ)")
pv = j(c.post("/api/align/preview", json={"path": str(SRC / "p-bottle" / "feature.png"), "rembg": True, "model": "u2netp", "options": {"margin": 60}}))
ok(pv["ok"] and pv["samples"][0].get("after"), "پیش‌نمایش همراه با حذف پس‌زمینه")

print("۴) حذف پس‌زمینه + ترازبندی در یک کار")
b = j(c.post("/api/bg", json={"input_path": str(SRC / "p-jpg"), "rembg": True, "model": "u2netp", "align": {"margin": 100, "format": "webp"}}))
b = wait_bg(b["id"])
outp = Path(b["output_path"]) / "gallery_1.webp"
ok(b["status"] == "completed" and outp.exists() and Image.open(outp).size == (1280, 1280), f"rembg + ترازبندی ← {outp.name}")

print("۵) خروجی‌ساز با ترازبندی")
j(c.put("/api/settings", json={"delay_min_ms": 10, "delay_max_ms": 20, "output_root": str(DATA / "output"),
                               "image_align": {**A.DEFAULT_ALIGN, "margin": 80}}))
j(c.post("/api/sources", json={"config": {"key": "fixture-shop", "name": "فروشگاه آزمایشی", "domains": ["127.0.0.1"], "product_id_pattern": r"/product/p-(\d+)",
                                          "listing": {"mode": "http", "link_pattern": r"/product/p-\d+", "pagination": {"type": "param", "param": "page"}},
                                          "product": {"mode": "http"}}}))
ds = j(c.post("/api/datasets", json={"category_url": FX + "/category/oils", "limit": 2}))
t0 = time.time()
while j(c.get(f"/api/datasets/{ds['id']}"))["status"] not in ("completed", "error") and time.time() - t0 < 120:
    time.sleep(0.5)
ex = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "zip": True, "align": True, "rembg": False}))
t0 = time.time()
while True:
    e = j(c.get(f"/api/exports/{ex['id']}"))
    if e["status"] in ("completed", "error") or time.time() - t0 > 90:
        break
    time.sleep(0.5)
files = e["result"]["files"]
img_dir = Path(files.get("images_dir", ""))
pngs = sorted(x for x in img_dir.rglob("*.png") if "_raw" not in x.stem) if img_dir.exists() else []
raws = sorted(x for x in img_dir.rglob("*_raw.*")) if img_dir.exists() else []
ok(e["status"] == "completed" and pngs and len(raws) == len(pngs) and all(Image.open(x).size == (1280, 1280) for x in pngs),
   f"{len(pngs)} تصویر نهایی ۱۲۸۰×۱۲۸۰ (feature.png …) کنار {len(raws)} تصویر خام (_raw)")
ok(e["result"]["stats"]["align"]["margin_top"] == 80, "قاعده‌ی پیش‌فرض تنظیمات (۸۰ پیکسل) در خروجی")
from openpyxl import load_workbook  # noqa: E402
ws = load_workbook(files["xlsx"])["products"]
hdr = [x.value for x in ws[1]]
row = {hdr[i]: ws.cell(row=2, column=i + 1).value for i in range(len(hdr))}
ok(str(row["featured_images"]).endswith("/feature.png"), f"پیوند تصویر در Excel به نسخه‌ی نهایی: {row['featured_images']}")
import zipfile  # noqa: E402
names = zipfile.ZipFile(files["zip"]).namelist()
ok(any(n.endswith("/feature.png") for n in names) and not any("_raw" in n for n in names), "ZIP فقط تصاویر و داده‌ی نهایی")
ws_raw = load_workbook(files["raw_xlsx"])["raw"]
ok(ws_raw.max_row == 3 and [x.value for x in ws_raw[1]][:3] == ["item_id", "dataset", "source_url"], "داده‌ی خام در <name>_raw.xlsx")
# خروجی دوباره با حاشیه‌ی دیگر: تصویر نهایی با قاعده‌ی تازه ساخته می‌شود
ex2 = j(c.post("/api/exports", json={"dataset_ids": [ds["id"]], "zip": False, "rembg": False, "align": {"margin": 200}, "name": e["name"]}))
t0 = time.time()
while j(c.get(f"/api/exports/{ex2['id']}"))["status"] not in ("completed", "error") and time.time() - t0 < 60:
    time.sleep(0.4)
bx = subject_box(Image.open(pngs[0]), (255, 255, 255)) if Image.open(pngs[0]).getpixel((2, 2))[3] == 255 else subject_box(Image.open(pngs[0]))
ok(min(bx[0], bx[1], 1280 - bx[2], 1280 - bx[3]) >= 198, f"خروجی دوباره، تصویر نهایی را با حاشیه‌ی ۲۰۰ بازسازی کرد: {bx}")

print("۶) ابزارهای MCP")
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
    return r


r = mcall("preview_image_alignment", {"path": str(SRC), "margin": 100, "limit": 2})
ok(not r.get("isError") and sum(1 for x in r["content"] if x["type"] == "image") == 2, "preview_image_alignment با تصویر")
r = mcall("align_images", {"input_path": str(SRC), "output_path": str(DATA / "mcp_aligned"), "margin_top": 150, "margin": 60})
# پوشه‌ای با هر سه مرحله: فقط یک نسخه پردازش می‌شود و نام خروجی بدون پسوند است
STG = DATA / "staged" / "p1"
STG.mkdir(parents=True)
Image.open(cases["p-bottle/feature.png"][0]).save(STG / "feature_raw.png")
Image.open(cases["p-bottle/feature.png"][0]).save(STG / "feature_raw_rembg.png")
Image.open(cases["p-bottle/feature.png"][0]).save(STG / "feature.png")
bs = wait_bg(j(c.post("/api/bg", json={"input_path": str(STG.parent), "rembg": False, "align": {"margin": 60}}))["id"])
ok(bs["progress_total"] == 1 and sorted(p.name for p in (Path(bs["output_path"]) / "p1").iterdir()) == ["feature.png"],
   "ابزار پردازش: از خام/میانی/نهایی فقط یکی پردازش و خروجی feature.png نام گرفت")
jid = json.loads(r["content"][0]["text"])["id"]
bj = wait_bg(jid)
box = subject_box(Image.open(DATA / "mcp_aligned" / "p-bottle" / "feature.png"))
ok(bj["status"] == "completed" and check_fit(box, (1280, 1280), (150, 60, 60, 60), 0.25), f"align_images با حاشیه‌ی جداگانه: {box}")

print("\nهمه‌ی آزمون‌ها موفق بود ✅")
