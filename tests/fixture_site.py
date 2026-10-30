"""سایت آزمایشی محلی برای تست انتها‌به‌انتهای استودیو (شبیه‌ساز فروشگاه و API)."""
from __future__ import annotations

import io
import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFilter

FAIL_ONCE: set = set()
N_PRODUCTS = 22


def product_img(n: int, w=900, h=900) -> bytes:
    rnd = random.Random(n)
    im = Image.new("RGB", (w, h), (245, 245, 247) if n % 2 else (255, 255, 255))
    d = ImageDraw.Draw(im)
    # سایه
    sh = Image.new("L", (w, h), 0)
    ImageDraw.Draw(sh).ellipse((w * .28, h * .78, w * .72, h * .86), fill=90)
    im.paste((200, 200, 205), mask=sh.filter(ImageFilter.GaussianBlur(14)))
    col = (rnd.randint(20, 200), rnd.randint(40, 120), rnd.randint(120, 240))
    # بدنه‌ی گالن روغن
    d.rounded_rectangle((w * .32, h * .25, w * .68, h * .8), radius=40, fill=col)
    d.rectangle((w * .44, h * .17, w * .56, h * .26), fill=(30, 30, 30))
    d.rounded_rectangle((w * .36, h * .42, w * .64, h * .62), radius=14, fill=(250, 250, 250))
    d.text((w * .40, h * .49), f"OIL {n}", fill=(20, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def product_html(pid: int) -> str:
    title = f"روغن موتور خودرو کاسپین مدل 20W-50 SG حجم {pid % 4 + 1} لیتر کد {pid}"
    imgs = [f"/img/{pid}_{i}.jpg?w=300" for i in range(1, 4)]
    ld = {
        "@context": "https://schema.org", "@type": "Product", "name": title if pid != 5 else "",
        "image": [i.split('?')[0] for i in imgs], "brand": {"@type": "Brand", "name": "کاسپین"},
        "description": "روغن موتور مناسب خودروهای بنزینی با محافظت بالا در برابر سایش. " * 4,
        "sku": f"CSP-{pid}", "offers": {"@type": "Offer", "price": 1250000 + pid * 1000, "priceCurrency": "IRR"},
    }
    h1 = f"<h1 class='product-title'>{title}</h1>" if pid != 5 else "<h1></h1>"
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>{title}</title>
<meta name="description" content="خرید {title} با بهترین قیمت">
<meta property="og:image" content="/img/{pid}_1.jpg">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False) if pid != 5 else '{}'}</script>
<script type="application/ld+json">{json.dumps({"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"خانه"},{"@type":"ListItem","position":2,"name":"روغن موتور"},{"@type":"ListItem","position":3,"name":title}]}, ensure_ascii=False)}</script>
</head><body>
<nav class="breadcrumb"><a href="/">خانه</a> / <a href="/category/oils">روغن موتور</a></nav>
{h1}
<div class="product-gallery">{''.join(f'<img data-src="{u}" src="/static/ph.gif" width="300">' for u in imgs)}</div>
<section class="product-specs"><h2>مشخصات</h2>
<table><tr><th colspan="1">مشخصات کلی</th></tr>
<tr><td>حجم</td><td>{pid % 4 + 1} لیتر</td></tr>
<tr><td>ویسکوزیته</td><td>20W-50</td></tr>
<tr><td>وزن</td><td>{(pid % 4 + 1) * 0.9:.1f} کیلوگرم</td></tr>
<tr><td>ابعاد</td><td>20 × 12 × 28 سانتی‌متر</td></tr>
</table>
<div id="more-specs"></div>
<button type="button" onclick="document.getElementById('more-specs').innerHTML='<table><tr><td>سطح کیفیت</td><td>SG</td></tr><tr><td>کشور سازنده</td><td>ایران</td></tr></table>';this.remove()">مشاهده بیشتر</button>
</section>
<section class="product-description"><h2>معرفی محصول</h2><p>این روغن موتور برای استفاده در خودروهای بنزینی طراحی شده است و از موتور در دمای بالا محافظت می‌کند.</p><p>بسته‌بندی گالن پلاستیکی با درب پلمب‌شده.</p></section>
</body></html>"""


def category_html(page: int, per=8) -> str:
    start = (page - 1) * per + 1
    ids = [i for i in range(start, start + per) if i <= N_PRODUCTS]
    links = "".join(f'<a class="card" href="/product/p-{i}?ref=cat">محصول {i}</a>' for i in ids)
    return f"<!doctype html><html dir='rtl'><head><meta charset='utf-8'><title>روغن موتور</title></head><body><h1>روغن موتور</h1>{links}</body></html>"


INFINITE = """<!doctype html><html dir='rtl'><head><meta charset='utf-8'><title>بی‌پایان</title></head><body><h1>ضدیخ و ضدجوش</h1>
<div id="list" style="min-height:2000px"></div><script>
let page=1, loading=false;
async function more(){ if(loading) return; loading=true; const r=await fetch('/api/list?page='+page); const d=await r.json();
 d.items.forEach(i=>{const a=document.createElement('a'); a.href='/product/p-'+i; a.textContent='محصول '+i; a.style.display='block'; a.style.height='120px'; document.getElementById('list').appendChild(a);});
 if(d.items.length) page++; loading=false; }
more(); window.addEventListener('scroll',()=>{ if(window.innerHeight+window.scrollY>=document.body.offsetHeight-300) more(); });
</script></body></html>"""


def dk_search(slug: str, page: int) -> dict:
    per = 6
    total = 14
    ids = [1000 + i for i in range((page - 1) * per + 1, min(page * per, total) + 1)]
    return {"status": 200, "data": {"products": [{"id": i, "title_fa": f"محصول {i}"} for i in ids],
                                    "pager": {"current_page": page, "total_pages": 3, "total_items": total},
                                    "category": {"title_fa": "روغن موتور"}}}


def dk_product(pid: int) -> dict:
    return {"status": 200, "data": {"product": {
        "id": pid, "title_fa": f"روغن موتور خودرو بهران مدل سوپر پیشتاز 20W-50 حجم 4 لیتر شماره {pid}",
        "title_en": f"Behran Super Pishtaz 20W-50 Engine Oil 4L No {pid}",
        "brand": {"title_fa": "بهران", "title_en": "Behran", "code": "behran"},
        "category": {"title_fa": "روغن موتور", "code": "engine-oil"},
        "images": {"main": {"url": [f"http://127.0.0.1:8899/img/{pid}_1.jpg?x-oss-process=image/resize,w_800"]},
                   "list": [{"url": [f"http://127.0.0.1:8899/img/{pid}_{i}.jpg?x-oss-process=image/resize,w_800"]} for i in range(1, 4)]},
        "specifications": [{"title": "مشخصات", "attributes": [
            {"title": "حجم", "values": ["4 لیتر"]}, {"title": "گرانروی", "values": ["20W-50"]},
            {"title": "وزن", "values": ["3500 گرم"]}, {"title": "ابعاد بسته‌بندی", "values": ["25 × 15 × 30 سانتی‌متر"]}]}],
        "review": {"description": "<p>روغن موتور مناسب برای خودروهای سواری.</p>"},
        "expert_reviews": {"review_sections": [{"title": "معرفی", "sections": [{"template": "text", "text": "<p>بهران سوپر پیشتاز، روغنی چندمنظوره است.</p>"}]}]},
        "default_variant": {"price": {"selling_price": 14500000}},
    }}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="text/html; charset=utf-8", code=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        if p.startswith("/category/oils"):
            return self.send(category_html(int(q.get("page", ["1"])[0])))
        if p == "/infinite":
            return self.send(INFINITE)
        if p == "/api/list":
            pg = int(q.get("page", ["1"])[0])
            items = [i for i in range((pg - 1) * 5 + 1, pg * 5 + 1) if i <= 13]
            return self.send(json.dumps({"items": items}), "application/json")
        if p.startswith("/product/p-"):
            pid = int(p.rsplit("-", 1)[1])
            if pid == 7 and pid not in FAIL_ONCE:
                FAIL_ONCE.add(pid)
                return self.send("خطای سرور", code=503)
            if pid == 9:
                return self.send("not found", code=404)
            return self.send(product_html(pid))
        if p.startswith("/img/"):
            name = p.rsplit("/", 1)[1].split(".")[0]
            n = int(name.split("_")[0]) * 10 + int(name.split("_")[1])
            return self.send(product_img(n), "image/jpeg")
        if p.startswith("/dk/v1/categories/"):
            slug = p.split("/")[4]
            return self.send(json.dumps(dk_search(slug, int(q.get("page", ["1"])[0])), ensure_ascii=False), "application/json")
        if p.startswith("/dk/v2/product/"):
            pid = int(p.strip("/").split("/")[-1])
            return self.send(json.dumps(dk_product(pid), ensure_ascii=False), "application/json")
        if p.startswith("/ai/"):
            return ai_get(self, p)
        if p == "/static/ph.gif":
            return self.send(b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;", "image/gif")
        return self.send("not found", code=404)


# ---------------------------------------------------------------- هوش مصنوعی ساختگی
import base64 as _b64
import re as _re

AI_KEY = "test-key"
AI_CALLS = {"chat": 0, "image": 0}
AI_DELAY = [0.0]


def _png() -> bytes:
    im = Image.new("RGB", (512, 512), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((170, 110, 340, 420), radius=30, fill=(200, 40, 60))
    d.rectangle((230, 70, 280, 112), fill=(20, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


_CNT = [0]


def _mk(keys, i):
    _CNT[0] += 1
    n = _CNT[0]
    o = {}
    for k in keys:
        o[k] = {"title": f"محصول آزمایشی شماره {n}", "title_en": f"Test Product {n}", "brand": "برند آزمایشی", "brief": "محصول نمونه",
                "key": (["title", "brand", "gallery"][i % 3] if "strategies" in keys else f"ai_col_{n}"), "label": f"ستون هوشمند {n}",
                "kind": "manual", "input": ["text", "longtext", "bullets"][i % 3], "instruction": "دستور نمونه",
                "strategies": [{"type": "jsonld", "at_type": "Product", "path": ["name", "brand.name", "image"][i % 3]}],
                "source_value": f"مقدار {i}", "target_slug": f"Slug {i}", "target_label": f"برچسب {i}",
                "name": f"قاعده {n}", "action": "remove", "target": "*", "find": "دیجی‌کالا", "value": ""}.get(k, f"{k} {n}")
    return o


def mock_answer(prompt: str) -> str:
    if "single word: OK" in prompt:
        return "OK"
    m = _re.search(r"- عنوان: (.+)", prompt)
    title = m.group(1).strip() if m else "محصول"
    out = {}
    for key, desc in _re.findall(r'^- "(\w+)": (.+)$', prompt, _re.M):
        m2 = _re.search(r"آرایه‌ای از (\d+) شیء JSON با کلیدهای (.+)", desc)
        if m2:
            ks = _re.findall(r'"(\w+)"', m2.group(2))
            out[key] = [_mk(ks, i) for i in range(int(m2.group(1)))]
            continue
        if desc.startswith("آرایه‌ای از اشیاء {"):
            out[key] = [{"group": "مشخصات کلی", "name": "حجم", "value": "4 لیتر"}, {"group": "مشخصات کلی", "name": "وزن", "value": "3600 گرم"},
                        {"group": "مشخصات کلی", "name": "ویسکوزیته", "value": "10W-40"}]
            continue
        if desc.startswith("شیء JSON با کلیدهای") and "آرایه‌ای از رشته‌هاست" not in desc and "یک عدد" not in desc:
            out[key] = _mk(_re.findall(r'"(\w+)"', desc), 0)
            continue
        if desc.startswith("رشته‌ی متنی") and key == "value":
            out[key] = f"متن تولیدی دستیار برای «{(_re.search(r'فیلد: «(.+?)»', prompt) or [None, 'فیلد'])[1]}»"
            continue
        if "آرایه‌ای از رشته‌هاست" in desc:
            keys = _re.findall(r'"(\w+)" \(', desc)
            out[key] = {k: [f"نکته‌ی {i} برای {k}" for i in (1, 2, 3)] for k in keys}
        elif "یک عدد به‌صورت رشته" in desc:
            keys = _re.findall(r'"(\w+)"', desc.split("؛")[0])
            out[key] = {k: "123" for k in keys}
        elif "آدرس تصویر" in desc or "آدرس‌های تصویر" in desc:
            urls = _re.findall(r"^(https?://\S+)$", prompt, _re.M)
            out[key] = urls[:3] if "آدرس‌های" in desc else (urls[0] if urls else "")
        elif desc.startswith("یک عدد"):
            out[key] = "42"
        elif "اسلاگ" in desc:
            out[key] = "AI Generated Slug " + key
        elif "آرایه‌ای از رشته‌ها" in desc:
            out[key] = ["بولت یک", "بولت دو"]
        else:
            out[key] = f"متن یکتای تولیدشده برای «{title}» در فیلد {key}. دیجی‌کالا را نام نبر."
    return "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"


def ai_get(h, p):
    if p.endswith("/models"):
        if "/gemini/" in p:
            return h.send(json.dumps({"models": [{"name": "models/mock-gemini"}, {"name": "models/mock-gemini-image"}]}), "application/json")
        return h.send(json.dumps({"data": [{"id": "mock-text"}, {"id": "mock-image"}]}), "application/json")
    return h.send("not found", code=404)


def ai_post(h, p, body):
    auth = h.headers.get("Authorization", "") + h.headers.get("x-api-key", "") + h.headers.get("x-goog-api-key", "")
    if AI_KEY not in auth:
        return h.send(json.dumps({"error": {"message": "invalid api key"}}), "application/json", 401)
    if body.get("model") == "mock-500":  # خطای موقت سرور (برای آزمون توقف پس از خطاهای پیاپی)
        AI_CALLS["chat"] += 1
        return h.send(json.dumps({"error": {"message": "upstream overloaded"}}), "application/json", 503)
    if body.get("model") == "mock-quota":
        AI_CALLS["chat"] += 1
        return h.send(json.dumps({"error": {"message": "You exceeded your current quota, please check your plan and billing details."}}), "application/json", 429)
    if body.get("model") == "mock-bad":
        AI_CALLS["chat"] += 1
        return h.send(json.dumps({"error": {"message": "Unknown model: mock-bad"}}), "application/json", 404)
    if p.endswith("/chat/completions"):
        AI_CALLS["chat"] += 1
        if AI_DELAY[0]:
            time.sleep(AI_DELAY[0])
        if body.get("modalities"):
            AI_CALLS["image"] += 1
            url = "data:image/png;base64," + _b64.b64encode(_png()).decode()
            return h.send(json.dumps({"choices": [{"message": {"content": "", "images": [{"image_url": {"url": url}}]}}]}), "application/json")
        msgs = body.get("messages", [])
        user = msgs[-1]["content"]
        if isinstance(user, list):
            user = " ".join(x.get("text", "") for x in user if isinstance(x, dict))
        return h.send(json.dumps({"choices": [{"message": {"content": mock_answer(user)}}], "usage": {"total_tokens": 321}}, ensure_ascii=False), "application/json")
    if p.endswith("/images/generations") or p.endswith("/images/edits"):
        AI_CALLS["image"] += 1
        return h.send(json.dumps({"data": [{"b64_json": _b64.b64encode(_png()).decode()}]}), "application/json")
    if p.endswith("/v1/messages"):
        AI_CALLS["chat"] += 1
        text = " ".join(c.get("text", "") for c in body["messages"][-1]["content"] if c.get("type") == "text")
        return h.send(json.dumps({"content": [{"type": "text", "text": mock_answer(text)}], "usage": {"input_tokens": 100, "output_tokens": 50}}, ensure_ascii=False), "application/json")
    if ":generateContent" in p:
        AI_CALLS["chat"] += 1
        if "IMAGE" in json.dumps(body.get("generationConfig", {})):
            AI_CALLS["image"] += 1
            return h.send(json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": _b64.b64encode(_png()).decode()}}]}}]}), "application/json")
        text = " ".join(x.get("text", "") for x in body["contents"][-1]["parts"])
        return h.send(json.dumps({"candidates": [{"content": {"parts": [{"text": mock_answer(text)}]}}], "usageMetadata": {"totalTokenCount": 222}}, ensure_ascii=False), "application/json")
    return h.send("not found", code=404)


def _do_post(self):
    n = int(self.headers.get("Content-Length", 0) or 0)
    raw = self.rfile.read(n) if n else b""
    p = urlparse(self.path).path
    if "multipart" in self.headers.get("Content-Type", ""):
        body = {}
    else:
        body = json.loads(raw or b"{}")
    if p.startswith("/ai/"):
        return ai_post(self, p, body)
    return self.send("not found", code=404)


H.do_POST = _do_post


def serve(port=8899):
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8899)
