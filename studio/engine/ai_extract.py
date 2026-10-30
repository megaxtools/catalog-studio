"""استخراج یا تولید فیلدهای اسکرپر با هوش مصنوعی از روی محتوای صفحه.

دو راه فعال‌سازی در پیکربندی منبع:
- راهبرد {"type": "ai", "mode": "extract" | "generate", "instruction": "..."} در فهرست راهبردهای یک فیلد؛
  وقتی راهبردهای دیگرِ آن فیلد چیزی پیدا نکنند اجرا می‌شود.
- {"product": {"ai_fallback": {"enabled": true, "fields": [...], "mode": "extract"}}}؛ هر فیلدِ فهرست که پس از همه‌ی
  راهبردها خالی ماند با هوش مصنوعی از متن صفحه استخراج می‌شود.
همه‌ی فیلدهای معلق یک محصول در یک درخواست فرستاده می‌شوند.
"""
from __future__ import annotations

import json
import re
from typing import Any

SHAPES = {
    "text": "رشته‌ی متنی",
    "html": "رشته‌ی متنی",
    "number": "یک عدد (بدون واحد)",
    "list": "آرایه‌ای از رشته‌ها",
    "specs": 'آرایه‌ای از اشیاء {"group": ..., "name": ..., "value": ...}',
    "image": "یک آدرس تصویر از فهرست «تصاویر صفحه»",
    "images": "آرایه‌ای از آدرس‌های تصویر از فهرست «تصاویر صفحه» (فقط تصاویر خودِ محصول، نه لوگو و بنر)",
    "json": "مقدار JSON مناسب",
}


def page_text(b, limit: int = 12000) -> str:
    soup = b.soup
    try:
        from bs4 import BeautifulSoup
        s2 = BeautifulSoup(str(soup), "lxml")
        for t in s2(["script", "style", "noscript", "svg", "header", "footer", "nav", "iframe"]):
            t.decompose()
        txt = s2.get_text("\n")
    except Exception:  # noqa: BLE001
        txt = soup.get_text("\n")
    txt = re.sub(r"[ \t‌]{2,}", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    return txt[:limit]


def run(b, pending: dict[str, dict], ctx: dict, cfg: dict) -> tuple[dict, dict]:
    """pending: {key: {"type": ftype, "label": ..., "mode": extract|generate, "instruction": ...}}
    خروجی: (مقادیر خام برای هر کلید، خطاها)"""
    from ..ai_studio import _ask, default_client
    from .extract import auto_images

    pcfg = cfg.get("product") or {}
    client, model = default_client((pcfg.get("ai_fallback") or {}).get("provider_id") or pcfg.get("ai_provider_id"))
    imgs = []
    if any(p["type"] in ("image", "images") for p in pending.values()):
        imgs = auto_images(b)[:40]
    known = {k: v for k, v in ctx.items() if k in ("title", "title_en", "brand", "category", "short_description") and v}
    if ctx.get("specifications"):
        known["specifications"] = [f"{s.get('name')}: {s.get('value')}" for s in ctx["specifications"][:30]]
    ld = []
    try:
        from .extract import _jsonld_products
        ld = _jsonld_products(b)[:1]
    except Exception:  # noqa: BLE001
        ld = []
    intro = ["از محتوای صفحه‌ی محصول زیر، مقدار فیلدهای خواسته‌شده را استخراج کن.",
             f"آدرس صفحه: {b.base_url}"]
    if b.title:
        intro.append(f"عنوان صفحه: {b.title}")
    if known:
        intro.append("داده‌هایی که پیش‌تر استخراج شده: " + json.dumps(known, ensure_ascii=False)[:2500])
    if ld:
        intro.append("JSON-LD محصول: " + json.dumps(ld[0], ensure_ascii=False)[:3000])
    if imgs:
        intro.append("تصاویر صفحه:\n" + "\n".join(imgs))
    intro.append("متن صفحه:\n" + page_text(b))
    intro.append("قاعده: برای فیلدهای «استخراج» فقط از محتوای صفحه استفاده کن و اگر در صفحه نیست مقدار خالی بده؛ "
                 "برای فیلدهای «تولید» اگر در صفحه نبود، بر اساس داده‌های محصول یک مقدار درست و فارسی بنویس. هیچ عدد یا مشخصه‌ای را از خودت نساز.")
    keys = []
    for k, p in pending.items():
        how = "تولید" if p.get("mode") == "generate" else "استخراج"
        desc = f"{SHAPES.get(p['type'], 'رشته‌ی متنی')} — {p.get('label') or k} ({how})"
        if p.get("instruction"):
            desc += f". {p['instruction']}"
        keys.append((k, desc))
    obj = _ask(client, model, "\n".join(intro), keys, temperature=0.2, max_tokens=3000,
               system="تو یک استخراج‌گر دقیق داده‌ی محصول از صفحات فروشگاه‌های اینترنتی هستی. فقط JSON برگردان.")
    out: dict[str, Any] = {}
    for k, p in pending.items():
        v = obj.get(k)
        if v in (None, "", [], {}):
            continue
        if p["type"] in ("image", "images") and imgs:
            allowed = set(imgs)
            vs = v if isinstance(v, list) else [v]
            vs = [x for x in vs if isinstance(x, str) and (x in allowed or x.startswith("http"))]
            if not vs:
                continue
            v = vs if p["type"] == "images" else vs[0]
        out[k] = v
    return out, {}
