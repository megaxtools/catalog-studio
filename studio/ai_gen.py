"""تولید محتوا با هوش مصنوعی: قالب‌های تولید، ساخت پرامپت، تولید برای هر محصول و اجرای گروهی."""
from __future__ import annotations

import base64
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from . import db, rules, services
from .ai import AIClient, AIError, get_provider, parse_json
from .config import AI_IMAGES_DIR
from .textutil import slugify, to_latin_digits

MODES = {
    "fill_missing": "فقط اگر خالی است (رفع نقص)",
    "rewrite": "بازنویسی یکتا از روی متن فعلی",
    "overwrite": "تولید از نو (جایگزینی کامل)",
}

DEFAULT_SYSTEM = (
    "تو نویسنده‌ی حرفه‌ای محتوای فروشگاهی و متخصص سئو برای «مگا کارز» هستی؛ بازار آنلاین خدمات و قطعات خودرو در ایران. "
    "متن‌ها فارسیِ روان، دقیق، یکتا (نه رونوشت منبع) و بدون اغراق باشند. هیچ مشخصه‌ی فنی، استاندارد، گواهی یا عددی را از خودت نساز؛ "
    "فقط از داده‌ی محصول استفاده کن و اگر اطلاعاتی نیست، کلی و درست بنویس. نام فروشگاه‌ها و رقبا را نیاور. "
    "به هر تعمیرگاه یا فروشگاه «کسب‌وکار» بگو و هرگز واژه‌ی «شعبه» را به کار نبر. قیمت و تخفیف را ذکر نکن."
)

DEFAULT_IMAGE_PROMPT = (
    "Professional e-commerce product photo of: {title}. Brand: {brand}. Category: {category}. "
    "Single product, centered, front view, on a pure white seamless background, soft studio lighting, sharp focus, "
    "realistic, high detail, no extra text, no watermark."
)

DEFAULT_PROFILE = {
    "provider_id": None, "model": "", "image_model": "", "temperature": 0.7, "max_tokens": 3000,
    "batch": True, "concurrency": 2, "schema_id": None,
    "system_prompt": DEFAULT_SYSTEM, "seo_keywords": "", "banned_words": "", "extra_context": "",
    "fields": [
        {"target": "short_description", "enabled": True, "mode": "rewrite", "max_chars": 250,
         "instruction": "توضیح کوتاه یکتا در ۱ تا ۲ جمله که کلیدواژه‌ی اصلی محصول (نوع + برند + مدل) در آن آمده باشد."},
        {"target": "long_description", "enabled": True, "mode": "rewrite", "max_chars": 1800,
         "instruction": "توضیح کامل و یکتا در ۳ تا ۵ پاراگراف کوتاه: معرفی محصول، ویژگی‌ها و مزایا بر اساس مشخصات، کاربرد و سازگاری، نکات نگهداری و استفاده. بدون تیتر Markdown."},
        {"target": "user_dos_donts_description", "enabled": True, "mode": "fill_missing", "max_chars": 0,
         "instruction": "برای هر بخش ۳ تا ۵ بولت کوتاه و کاربردی برای مشتری بنویس."},
        {"target": "vendor_dos_donts_description", "enabled": True, "mode": "fill_missing", "max_chars": 0,
         "instruction": "برای هر بخش ۳ تا ۵ بولت کوتاه برای کسب‌وکار فروشنده بنویس (نگهداری، اصالت کالا، بسته‌بندی، ارسال و مرجوعی)."},
        {"target": "dimensions", "enabled": False, "mode": "fill_missing", "max_chars": 0,
         "instruction": "فقط کلیدهای خالی را با تخمین منطقی بر اساس نوع و حجم محصول پر کن (وزن به گرم، ابعاد به سانتی‌متر، فقط عدد)."},
        {"target": "slug", "enabled": False, "mode": "overwrite", "max_chars": 80,
         "instruction": "اسلاگ انگلیسی سئوشده: نوع محصول + برند + مدل + حجم، با حروف کوچک و خط تیره."},
    ],
    "images": {"enabled": False, "target": "featured_images", "mode": "fill_missing", "count": 1, "size": "1024x1024",
               "use_reference": True, "prompt": DEFAULT_IMAGE_PROMPT},
}


# ---------------------------------------------------------------------------
# قالب‌ها
# ---------------------------------------------------------------------------

def seed():
    if not db.val("SELECT COUNT(*) FROM ai_profiles"):
        db.ex("INSERT INTO ai_profiles(name, description, config, created_at, updated_at) VALUES(?,?,?,?,?)",
              ["توضیحات یکتا و سئو (پیش‌فرض)", "بازنویسی توضیحات، تکمیل بایدها و نبایدها", db.jdump(DEFAULT_PROFILE), db.now(), db.now()])


def profile_row(r):
    if not r:
        return None
    r = dict(r)
    cfg = {**json.loads(json.dumps(DEFAULT_PROFILE)), **db.jload(r["config"], {})}
    r["config"] = cfg
    return r


def get_profile(pid: int):
    return profile_row(db.q1("SELECT * FROM ai_profiles WHERE id=?", [pid]))


def list_profiles():
    return [profile_row(r) for r in db.q("SELECT * FROM ai_profiles ORDER BY id")]


# ---------------------------------------------------------------------------
# ساخت پرامپت
# ---------------------------------------------------------------------------

def _fmt_spec(specs) -> str:
    lines = []
    for s in (specs or [])[:80]:
        if isinstance(s, dict):
            lines.append(f"- {s.get('name', '')}: {s.get('value', '')}")
    return "\n".join(lines)


def product_context(item: dict, ds: dict, src: dict | None) -> dict:
    d = rules.cleaned(item)
    return {
        "title": d.get("title", ""), "title_en": d.get("title_en", ""), "brand": d.get("brand", "") or d.get("brand_en", ""),
        "category": ds.get("category_label") or d.get("category", ""), "source": (src or {}).get("name", ""),
        "specs": _fmt_spec(d.get("specifications")), "short_description": d.get("short_description", ""),
        "long_description": (d.get("long_description") or "")[:3500], "url": item.get("url", ""),
    }


def _shape(col: dict) -> tuple[str, str]:
    """شکل خروجی مورد انتظار برای هر ستون: (نوع، توضیح برای مدل)"""
    inp = col.get("input") or "text"
    if (col.get("kind") == "auto" and col.get("generator", "slug") == "slug") or col.get("kind") == "mapping":
        return "slug", "رشته‌ی اسلاگ انگلیسی (فقط a-z، 0-9 و خط تیره)"
    if inp == "bullets":
        return "list", "آرایه‌ای از رشته‌ها (هر عضو یک بولت، بدون علامت بولت)"
    if inp == "bullet_groups":
        keys = ", ".join(f'"{g["key"]}" ({g.get("label", "")})' for g in col.get("groups", []))
        return "groups", f"شیء JSON با کلیدهای {keys}؛ مقدار هر کلید آرایه‌ای از رشته‌هاست"
    if inp == "group":
        keys = ", ".join(f'"{k}"' for k in col.get("subkeys", []))
        return "group", f"شیء JSON با کلیدهای {keys}؛ مقدار هر کلید یک عدد به‌صورت رشته یا رشته‌ی خالی"
    if inp == "specs":
        return "specs", 'آرایه‌ای از اشیاء {"group": ..., "name": ..., "value": ...}'
    if inp == "json":
        return "json", "مقدار JSON مناسب"
    if inp == "bool":
        return "bool", '"true" یا "false"'
    if inp == "number":
        return "number", "یک عدد"
    if inp == "longtext":
        return "text", "رشته‌ی متنی چندپاراگرافی (بدون Markdown)"
    return "text", "رشته‌ی متنی (بدون Markdown)"


def _is_empty(v) -> bool:
    if v in (None, "", [], {}):
        return True
    if isinstance(v, dict):
        return all(_is_empty(x) for x in v.values())
    return False


def _current(col, item, ds, settings):
    """مقدار فعلی ستون بدون در نظر گرفتن خروجی قبلی AI."""
    tmp = {**item, "ai": {}}
    v, _ = services.column_value(col, tmp, ds, settings, with_default=False)  # پیش‌فرض اسکیما جای تولید را نمی‌گیرد
    return v


def plan_fields(profile: dict, item: dict, ds: dict, schema: dict, settings: dict, overwrite_ai: bool = False) -> list[dict]:
    cols = {c["key"]: c for c in schema["columns"]}
    plan = []
    for f in profile.get("fields", []):
        if not f.get("enabled", True):
            continue
        col = cols.get(f.get("target"))
        if not col or col.get("input") in ("image", "images") or not ai_capable(col):
            continue
        if col["key"] in (item.get("overrides") or {}):
            continue  # ویرایش دستی کاربر همیشه مقدم است
        if not overwrite_ai and col["key"] in (item.get("ai") or {}):
            continue
        cur = _current(col, item, ds, settings)
        mode = f.get("mode", "rewrite")
        if mode == "fill_missing":
            if col.get("input") == "group":
                if isinstance(cur, dict) and all(not _is_empty(cur.get(k)) for k in col.get("subkeys", [])):
                    continue
            elif not _is_empty(cur):
                continue
        plan.append({"field": f, "col": col, "current": cur, "shape": _shape(col)})
    return plan


def _field_instruction(p: dict) -> str:
    f, col, cur = p["field"], p["col"], p["current"]
    mode = f.get("mode", "rewrite")
    parts = [f.get("instruction", "").strip()]
    if f.get("max_chars"):
        parts.append(f"حداکثر حدود {f['max_chars']} نویسه.")
    if mode == "rewrite" and not _is_empty(cur):
        cur_s = cur if isinstance(cur, str) else json.dumps(cur, ensure_ascii=False)
        parts.append(f"متن فعلی را کاملاً بازنویسی کن تا یکتا باشد ولی اطلاعات درستش حفظ شود. متن فعلی: «{cur_s[:2500]}»")
    elif mode == "fill_missing" and col.get("input") == "group" and isinstance(cur, dict):
        parts.append(f"مقادیر موجود را تغییر نده؛ فقط کلیدهای خالی را پر کن. مقدار فعلی: {json.dumps(cur, ensure_ascii=False)}")
    else:
        parts.append("از نو بنویس.")
    return " ".join(x for x in parts if x)


def build_prompt(profile: dict, ctx: dict, plan: list[dict]) -> tuple[str, str]:
    system = profile.get("system_prompt") or DEFAULT_SYSTEM
    lines = ["داده‌ی محصول:",
             f"- عنوان: {ctx['title']}"]
    if ctx.get("title_en"):
        lines.append(f"- عنوان انگلیسی: {ctx['title_en']}")
    lines += [f"- برند: {ctx['brand'] or 'نامشخص'}", f"- دسته: {ctx['category'] or 'نامشخص'}"]
    if ctx.get("specs"):
        lines += ["مشخصات فنی:", ctx["specs"]]
    if ctx.get("short_description") and not any(p["col"].get("from") == "short_description" and p["field"].get("mode") == "rewrite" for p in plan):
        lines.append(f"توضیح کوتاه منبع: {ctx['short_description'][:600]}")
    if ctx.get("long_description") and not any(p["col"].get("from") == "long_description" and p["field"].get("mode") == "rewrite" for p in plan):
        lines.append(f"توضیح منبع: {ctx['long_description'][:2500]}")
    if profile.get("extra_context"):
        lines.append(f"توضیح تکمیلی: {profile['extra_context']}")
    if profile.get("seo_keywords"):
        lines.append(f"کلیدواژه‌های سئو (طبیعی و بدون تکرار افراطی به کار ببر): {profile['seo_keywords']}")
    if profile.get("banned_words"):
        lines.append(f"این واژه‌ها و عبارت‌ها را هرگز به کار نبر: {profile['banned_words']}")
    lines.append("")
    lines.append("فقط و فقط یک شیء JSON معتبر برگردان (بدون توضیح، بدون ```) با این کلیدها:")
    for p in plan:
        lines.append(f'- "{p["col"]["key"]}": {p["shape"][1]}. {_field_instruction(p)}')
    return system, "\n".join(lines)


def _normalize(shape: str, v, col: dict, settings: dict):
    if shape == "slug":
        return slugify(str(v), settings.get("slug_dictionary"))
    if shape == "list":
        if isinstance(v, str):
            v = [x for x in v.split("\n")]
        return [str(x).lstrip("•-* ").strip() for x in (v or []) if str(x).strip()]
    if shape == "groups":
        v = v if isinstance(v, dict) else {}
        out = {}
        for g in col.get("groups", []):
            x = v.get(g["key"], [])
            if isinstance(x, str):
                x = x.split("\n")
            out[g["key"]] = [str(i).lstrip("•-* ").strip() for i in (x or []) if str(i).strip()]
        return out
    if shape == "group":
        v = v if isinstance(v, dict) else {}
        out = {}
        for k in col.get("subkeys", []):
            x = v.get(k, "")
            x = to_latin_digits(str(x)).strip() if x not in (None,) else ""
            out[k] = x
        return out
    if shape == "specs":
        if isinstance(v, dict):
            v = [{"group": "", "name": k, "value": str(x)} for k, x in v.items()]
        return [{"group": str(s.get("group", "")), "name": str(s.get("name", "")), "value": str(s.get("value", ""))}
                for s in (v or []) if isinstance(s, dict) and s.get("name")]
    if shape == "bool":
        return "true" if str(v).lower() in ("true", "1", "yes", "بله") else "false"
    if shape == "number":
        return to_latin_digits(str(v)).strip()
    if shape == "json":
        return v
    if isinstance(v, (list, dict)):
        v = "\n".join(map(str, v)) if isinstance(v, list) else json.dumps(v, ensure_ascii=False)
    return str(v or "").strip()


# ---------------------------------------------------------------------------
# تولید برای یک محصول
# ---------------------------------------------------------------------------

def _ref_image(item: dict) -> bytes | None:
    d = rules.cleaned(item)
    u = d.get("featured_image") or (d.get("gallery") or [None])[0]
    if not u:
        return None
    try:
        if not str(u).startswith("http") and Path(u).is_file():
            return Path(u).read_bytes()
        r = requests.get(u, timeout=40, headers={"User-Agent": db.get_settings().get("user_agent"), "Referer": item.get("url", "")})
        if r.status_code < 400 and r.content:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None
    return None


def generate_for_item(item: dict, profile: dict, ds: dict, schema: dict, client: AIClient, settings: dict,
                      overwrite_ai: bool = False, with_images: bool = True, save_images_dir: Path | None = None) -> dict:
    """خروجی: {results: {col_key: entry}, prompt, raw, skipped}"""
    src = services.get_source(item["source_id"])
    ctx = product_context(item, ds, src)
    plan = plan_fields(profile, item, ds, schema, settings, overwrite_ai)
    results: dict = {}
    raw_all: list[str] = []
    model = profile.get("model") or client.p.get("text_model")
    prompt_shown = ""
    if plan:
        groups = [plan] if profile.get("batch", True) else [[p] for p in plan]
        for grp in groups:
            system, user = build_prompt(profile, ctx, grp)
            prompt_shown = prompt_shown or user
            raw = client.chat(system, user, model=model, temperature=float(profile.get("temperature", 0.7)),
                              max_tokens=int(profile.get("max_tokens", 3000)))
            raw_all.append(raw)
            try:
                obj = parse_json(raw)
            except AIError:
                if len(grp) == 1 and grp[0]["shape"][0] == "text":
                    obj = {grp[0]["col"]["key"]: raw}
                else:
                    raise
            if not isinstance(obj, dict):
                obj = {grp[0]["col"]["key"]: obj} if len(grp) == 1 else {}
            for p in grp:
                k = p["col"]["key"]
                if k not in obj:
                    continue
                val = _normalize(p["shape"][0], obj[k], p["col"], settings)
                if _is_empty(val):
                    continue
                if p["col"].get("input") == "group" and p["field"].get("mode") == "fill_missing" and isinstance(p["current"], dict):
                    val = {kk: (p["current"].get(kk) if not _is_empty(p["current"].get(kk)) else val.get(kk, "")) for kk in p["col"].get("subkeys", [])}
                results[k] = {"value": val, "mode": p["field"].get("mode"), "model": model, "at": db.now()}
    if with_images:
        cols = {c["key"]: c for c in schema["columns"]}
        iclient = None
        for img_cfg in image_configs(profile):
            col = cols.get(img_cfg.get("target"))
            if not col or col.get("input") not in ("image", "images") or col["key"] in (item.get("overrides") or {}):
                continue
            if not overwrite_ai and col["key"] in (item.get("ai") or {}):
                continue
            cur = _current(col, item, ds, settings)
            mode = img_cfg.get("mode", "fill_missing")
            if mode == "fill_missing" and not _is_empty(cur):
                continue
            if iclient is None:
                iclient = image_client_for(profile, client)
            n = 1 if col.get("input") == "image" else max(1, min(6, int(img_cfg.get("count", 1))))
            prompt = (img_cfg.get("prompt") or DEFAULT_IMAGE_PROMPT).format_map(_SafeDict(ctx))
            if img_cfg.get("instruction"):
                prompt += " " + str(img_cfg["instruction"])
            ref = _ref_image(item) if img_cfg.get("use_reference", True) else None
            out_dir = save_images_dir or (AI_IMAGES_DIR / f"ds{item['dataset_id']}" / f"item{item['id']}")
            out_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for i in range(n):
                angle = "" if i == 0 else [", side view", ", back view showing label", ", detail close-up", ", in use context", ", top view"][min(i - 1, 4)]
                data = iclient.image(prompt + angle, model=profile.get("image_model") or None, size=img_cfg.get("size", "1024x1024"), reference=ref)
                p = out_dir / f"{col['key']}_{i + 1}_{int(time.time() * 1000)}.png"
                p.write_bytes(data)
                paths.append(str(p))
            val = paths[0] if col.get("input") == "image" else paths
            results[col["key"]] = {"value": val, "mode": mode, "model": profile.get("image_model") or iclient.p.get("image_model"),
                                   "at": db.now(), "merge": "append" if mode == "add" else "", "kind": "image", "prompt": prompt}
    return {"results": results, "prompt": prompt_shown, "raw": "\n\n".join(raw_all), "planned": [p["col"]["key"] for p in plan]}


class _SafeDict(dict):
    def __missing__(self, k):
        return ""


def image_configs(profile: dict) -> list[dict]:
    """فهرست تنظیمات تولید تصویر (هر ستون تصویری یک مورد)؛ سازگار با قالب‌های قدیمی که فقط images داشتند."""
    lst = [x for x in (profile.get("images_list") or []) if x.get("enabled", True) and x.get("target")]
    one = profile.get("images") or {}
    if one.get("enabled") and one.get("target") and one["target"] not in {x["target"] for x in lst}:
        lst.append(one)
    return lst


def image_client_for(profile: dict, text_client: AIClient) -> AIClient:
    if profile.get("image_provider_id"):
        prov = get_provider(int(profile["image_provider_id"]))
        if prov:
            return AIClient(prov)
    if text_client.p.get("image_mode", "none") != "none" and text_client.p.get("kind") != "anthropic":
        return text_client
    from .ai_studio import default_client
    return default_client(None, need_image=True)[0]


# ---------------------------------------------------------------------------
# ستون‌های قابل تولید و تنظیمات پیش‌فرض
# ---------------------------------------------------------------------------

SYSTEM_GENERATORS = {"source_url", "source_name", "dataset_code", "scraped_at", "product_key"}


def ai_capable(col: dict, allow_fixed: bool = False) -> bool:
    """مقادیر سیستمی (لینک منبع، شناسه‌ی بانک، زمان استخراج…) واقعیت‌اند و با هوش مصنوعی ساخته نمی‌شوند.
    ستونی که پیش‌فرض اسکیمایش «همیشه همین مقدار» است هم در تولید خودکار کنار گذاشته می‌شود."""
    if col.get("kind") == "auto" and col.get("generator", "slug") in SYSTEM_GENERATORS:
        return False
    return allow_fixed or not services.fixed_default(col)


def default_instruction(col: dict) -> str:
    label = col.get("label") or col["key"]
    inp = col.get("input") or "text"
    if col.get("ai_instruction"):
        return col["ai_instruction"]
    if col.get("kind") == "mapping":
        return f"اسلاگ انگلیسی کوتاه، استاندارد و سئوشده برای {'برند' if col.get('map') == 'brand' else 'دسته‌بندی'} این محصول (مثلاً caspian یا engine-oil)."
    if col.get("kind") == "auto" and col.get("generator", "slug") == "slug":
        return "اسلاگ انگلیسی سئوشده: نوع محصول + برند + مدل + ویژگی کلیدی، با حروف کوچک و خط تیره."
    return {
        "text": f"مقدار دقیق و مناسب برای «{label}».",
        "longtext": f"متن کامل، یکتا و روان برای «{label}» بر اساس داده‌ی محصول.",
        "bullets": f"۳ تا ۶ بولت کوتاه و کاربردی برای «{label}».",
        "bullet_groups": f"برای هر بخش «{label}» ۳ تا ۵ بولت کوتاه و کاربردی.",
        "group": "فقط بر اساس داده‌ی محصول؛ اگر مقداری معلوم نیست تخمین منطقی بزن (وزن به گرم، ابعاد به سانتی‌متر، فقط عدد).",
        "specs": "مشخصات فنی را از داده‌ی محصول استخراج و مرتب کن؛ عدد یا استاندارد ساختگی ننویس.",
        "json": f"مقدار JSON مناسب برای «{label}».",
        "bool": f"آیا «{label}» برای این محصول برقرار است؟",
        "number": f"عدد مناسب برای «{label}» (فقط عدد).",
        "image": "عکس محصولی حرفه‌ای روی پس‌زمینه‌ی سفید.",
        "images": "عکس‌های محصول از زاویه‌های مختلف روی پس‌زمینه‌ی سفید.",
    }.get(inp, f"مقدار مناسب برای «{label}».")


def schema_ai_columns(schema: dict) -> list[dict]:
    """ستون‌هایی که در اسکیما برایشان تولید با هوش مصنوعی تنظیم شده است (ai_mode یا نوع «ai»)."""
    return [c for c in schema["columns"] if ai_capable(c) and c.get("include") is not False
            and (c.get("kind") == "ai" or c.get("ai_mode") not in (None, "", "off"))]


def build_config(schema: dict, selections: list[dict] | None = None, base: dict | None = None) -> dict:
    """ساخت تنظیمات تولید از انتخاب ستون‌ها. selections: [{key, mode, instruction, max_chars, count}];
    اگر None باشد، ستون‌های AI اسکیما استفاده می‌شوند."""
    cfg = {**json.loads(json.dumps(DEFAULT_PROFILE)), **json.loads(json.dumps(base or {}))}
    cols = {c["key"]: c for c in schema["columns"]}
    if selections is None:
        selections = [{"key": c["key"], "mode": (c.get("ai_mode") if c.get("ai_mode") not in (None, "", "off") else "fill_missing")}
                      for c in schema_ai_columns(schema)]
    fields, imgs = [], []
    for sel in selections:
        col = cols.get(sel.get("key"))
        if not col or not ai_capable(col):
            continue
        instr = (sel.get("instruction") or "").strip() or default_instruction(col)
        mode = sel.get("mode") or "fill_missing"
        if col.get("input") in ("image", "images"):
            imgs.append({"enabled": True, "target": col["key"], "mode": mode if mode in ("fill_missing", "add", "overwrite") else "fill_missing",
                         "count": int(sel.get("count") or 1), "size": sel.get("size") or "1024x1024", "use_reference": sel.get("use_reference", True),
                         "prompt": sel.get("prompt") or DEFAULT_IMAGE_PROMPT, "instruction": sel.get("instruction") or ""})
        else:
            fields.append({"target": col["key"], "enabled": True, "mode": mode if mode in MODES else "fill_missing",
                           "max_chars": int(sel.get("max_chars") or 0), "instruction": instr})
    cfg["fields"] = fields
    cfg["images_list"] = imgs
    cfg["images"] = {**(cfg.get("images") or {}), "enabled": False}
    return cfg


def save_results(item_id: int, results: dict, error: str = "", actor: str = "ai", note: str = ""):
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))
    ai = dict(it.get("ai") or {})
    for k, e in results.items():
        db.history("item", item_id, k, (ai.get(k) or {}).get("value", ""), e.get("value"), actor=actor, action="ai",
                   parent_id=it["dataset_id"], note=note)
    ai.update(results)
    ai["__meta"] = {"at": db.now(), "error": error}
    db.update("items", item_id, ai=ai, updated_at=db.now())


def client_for(profile: dict) -> AIClient:
    prov = get_provider(int(profile.get("provider_id") or 0)) if profile.get("provider_id") else None
    if prov:
        return AIClient(prov)
    from .ai_studio import default_client  # اتصال پیش‌فرض دستیار
    return default_client(None)[0]


def preview(profile_cfg: dict, item_id: int, with_images: bool = False) -> dict:
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))
    if not it:
        raise ValueError("محصول پیدا نشد.")
    ds = services.get_dataset(it["dataset_id"])
    schema = services.get_schema(ds["schema_id"])
    settings = db.get_settings()
    client = client_for(profile_cfg)
    tmp_dir = AI_IMAGES_DIR / "_preview"
    out = generate_for_item(it, profile_cfg, ds, schema, client, settings, overwrite_ai=True, with_images=with_images, save_images_dir=tmp_dir)
    cols = {c["key"]: c for c in schema["columns"]}
    fields = {}
    for k, e in out["results"].items():
        before = _current(cols[k], it, ds, settings) if k in cols else None
        val = e["value"]
        if e.get("kind") != "image" and k in cols:
            val = rules.apply_value(val, cols[k].get("from") or k, it.get("source_id"), all_fields=True)
        if e.get("kind") == "image":
            imgs = val if isinstance(val, list) else [val]
            val = ["data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode() for p in imgs]
        fields[k] = {"before": before, "after": val, "label": cols.get(k, {}).get("label", k)}
    return {"fields": fields, "prompt": out["prompt"], "raw": out["raw"], "tokens": client.usage_tokens, "planned": out["planned"],
            "title": it["data"].get("title", "")}


# ---------------------------------------------------------------------------
# اجرای گروهی
# ---------------------------------------------------------------------------

class AIJobs:
    def __init__(self):
        self.cancel: dict[int, bool] = {}
        self.threads: dict[int, threading.Thread] = {}

    def recover(self):
        db.ex("UPDATE ai_jobs SET status='paused', step='اجرای برنامه قطع شد؛ با «ادامه» از همان‌جا ادامه می‌یابد.' WHERE status IN ('running','pending')")

    def create(self, dataset_id: int, profile_id: int | None, options: dict) -> int:
        if options.get("config"):
            profile_id = profile_id or 0
        elif not get_profile(profile_id):
            raise ValueError("قالب تولید پیدا نشد.")
        jid = db.ex("INSERT INTO ai_jobs(dataset_id, profile_id, options, status, created_at) VALUES(?,?,?,?,?)",
                    [dataset_id, profile_id, db.jdump(options), "pending", db.now()])
        self.start(jid)
        return jid

    def is_running(self, jid: int) -> bool:
        t = self.threads.get(jid)
        return bool(t and t.is_alive())

    def start(self, jid: int):
        if self.is_running(jid):
            return
        self.cancel[jid] = False
        t = threading.Thread(target=self._run, args=(jid,), daemon=True, name=f"ai-{jid}")
        self.threads[jid] = t
        t.start()

    def stop(self, jid: int):
        self.cancel[jid] = True
        if self.is_running(jid):
            # درخواست‌های در جریان نیمه‌کاره رها می‌شوند؛ وضعیت بلافاصله «در حال توقف» نمایش داده می‌شود
            db.update("ai_jobs", jid, step="در حال توقف… (منتظر پاسخ درخواست‌های در جریان)")
        else:
            db.update("ai_jobs", jid, status="paused", step="متوقف شد.")

    def heal(self):
        """کارهایی که «در حال اجرا» مانده‌اند ولی رشته‌ی اجرایشان زنده نیست، متوقف علامت می‌خورند."""
        for r in db.q("SELECT id FROM ai_jobs WHERE status IN ('running','pending')"):
            if not self.is_running(r["id"]):
                db.update("ai_jobs", r["id"], status="paused", step="اجرا قطع شده بود؛ با «ادامه» از همان‌جا ادامه می‌یابد.")

    def _items(self, job: dict, opts: dict) -> list[int]:
        scope = opts.get("scope", "all")
        did = job["dataset_id"]
        if scope == "selected" and opts.get("item_ids"):
            ids = [int(i) for i in opts["item_ids"]]
            return [r["id"] for r in db.q(f"SELECT id FROM items WHERE id IN ({','.join('?' * len(ids))}) ORDER BY seq, id", ids)]
        sts = ("partial",) if scope == "partial" else ("done", "partial")
        return [r["id"] for r in db.q(f"SELECT id FROM items WHERE dataset_id=? AND status IN ({','.join('?' * len(sts))}) ORDER BY seq, id", [did, *sts])]

    def _run(self, jid: int):
        from concurrent.futures import CancelledError
        from .ai import AICancelled, set_context
        job = db.q1("SELECT * FROM ai_jobs WHERE id=?", [jid])
        opts = db.jload(job["options"], {})
        prof = get_profile(job["profile_id"]) if job["profile_id"] else None
        if opts.get("config"):
            prof = {"name": opts.get("title") or "تولید سفارشی", "config": {**json.loads(json.dumps(DEFAULT_PROFILE)), **opts["config"]}}
        db.update("ai_jobs", jid, status="running", error="", step="آماده‌سازی")
        if opts.get("catalog_id"):
            return self._run_catalog(jid, job, opts, prof)
        fatal: list[str] = []
        try:
            if not prof:
                raise ValueError("قالب تولید این اجرا حذف شده است.")
            cfg = prof["config"]
            ds = services.get_dataset(job["dataset_id"])
            schema = services.get_schema(ds["schema_id"])
            settings = db.get_settings()
            ids = self._items(job, opts)
            done_ids = set(opts.get("_done_ids") or [])
            todo = [i for i in ids if i not in done_ids]
            db.update("ai_jobs", jid, progress_total=len(ids), progress_done=len(ids) - len(todo))
            db.log("ai", jid, f"تولید با «{prof['name']}» برای {len(todo)} محصول آغاز شد.", step="ai")
            client_tokens = [int(job.get("tokens") or 0)]
            failed = [int(job.get("failed") or 0)]
            lock = threading.Lock()
            stop_now = lambda: bool(self.cancel.get(jid) or fatal)  # noqa: E731

            def work(iid: int):
                if stop_now():
                    return iid, "cancel", ""
                set_context(purpose=f"تولید گروهی ({prof['name']})", ref=f"ai_job:{jid}", item_id=iid)
                client = client_for(cfg)
                client.cancel_check = stop_now
                it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
                try:
                    out = generate_for_item(it, cfg, ds, schema, client, settings, overwrite_ai=bool(opts.get("overwrite_ai")),
                                            with_images=opts.get("images", True))
                    save_results(iid, out["results"], actor="ai", note=f"ai_job:{jid}")
                    return iid, "ok", (client.usage_tokens, len(out["results"]))
                except AICancelled:
                    return iid, "cancel", ""
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "fatal", False):
                        with lock:
                            if not fatal:
                                fatal.append(str(exc))
                        return iid, "fatal", str(exc)
                    save_results(iid, {}, error=str(exc))
                    db.log("ai", jid, f"تولید برای محصول {iid} ناموفق بود: {exc}", level="warning", step="ai", item_id=iid,
                           detail=traceback.format_exc()[-1500:])
                    return iid, "err", str(exc)

            conc = max(1, min(8, int(cfg.get("concurrency", 2))))
            consecutive_err = [0]
            last_err = [""]
            with ThreadPoolExecutor(max_workers=conc) as pool:
                futs = [pool.submit(work, i) for i in todo]
                for fut in as_completed(futs):
                    try:
                        iid, st, info = fut.result()
                    except CancelledError:
                        continue
                    with lock:
                        if st == "ok":
                            done_ids.add(iid)
                            client_tokens[0] += info[0]
                            consecutive_err[0] = 0
                        elif st == "err":
                            done_ids.add(iid)
                            failed[0] += 1
                            consecutive_err[0] += 1
                            last_err[0] = info
                        opts["_done_ids"] = sorted(done_ids)
                        db.update("ai_jobs", jid, progress_done=len(done_ids), failed=failed[0], tokens=client_tokens[0],
                                  options=opts, step=f"تولید محتوا · {len(done_ids)} از {len(ids)}" if not stop_now() else "در حال توقف…")
                    if consecutive_err[0] >= 3 and not fatal:
                        fatal.append(f"۳ خطای پیاپی؛ آخرین خطا: {last_err[0]}")
                    if stop_now():
                        for f in futs:
                            f.cancel()
            if fatal:
                db.update("ai_jobs", jid, status="error", error=fatal[0], step="به‌دلیل خطا متوقف شد؛ پس از رفع مشکل «ادامه» را بزنید.")
                db.log("ai", jid, f"تولید متوقف شد: {fatal[0]}", level="error", step="ai")
                return
            if self.cancel.get(jid):
                db.update("ai_jobs", jid, status="paused", step="متوقف شد؛ با «ادامه» از همان‌جا ادامه می‌یابد.")
                db.log("ai", jid, "تولید به درخواست کاربر متوقف شد.", level="warning", step="ai")
                return
            db.update("ai_jobs", jid, status="completed", finished_at=db.now(), step="تمام شد.")
            db.log("ai", jid, f"تولید تمام شد: {len(done_ids) - failed[0]} موفق، {failed[0]} ناموفق.", level="success", step="ai")
        except Exception as exc:  # noqa: BLE001
            db.update("ai_jobs", jid, status="error", error=str(exc), step="خطا")
            db.log("ai", jid, "اجرای تولید با خطا متوقف شد.", level="error", step="ai", detail=traceback.format_exc())


def _run_catalog(self, jid: int, job: dict, opts: dict, prof: dict):
    """هوش مصنوعی روی ردیف‌های یک خروجی نهایی (کاتالوگ): نتیجه مستقیم در ردیف‌های خروجی ذخیره می‌شود."""
    from concurrent.futures import CancelledError
    from . import catalogs
    from .ai import AICancelled, set_context
    eid = int(opts["catalog_id"])
    sid = int(opts["schema_id"])
    cfg = prof["config"]
    fatal: list[str] = []
    try:
        ids = [int(i) for i in opts.get("row_ids") or []] or [r["id"] for r in db.q(
            "SELECT id FROM export_rows WHERE export_id=? AND status='ok' ORDER BY seq, id", [eid])]
        done_ids = set(opts.get("_done_ids") or [])
        todo = [i for i in ids if i not in done_ids]
        settings = db.get_settings()
        db.update("ai_jobs", jid, progress_total=len(ids), progress_done=len(ids) - len(todo))
        db.log("ai", jid, f"ویرایش خروجی {eid} با هوش مصنوعی برای {len(todo)} ردیف آغاز شد.", step="ai")
        failed = [int(job.get("failed") or 0)]
        tokens = [int(job.get("tokens") or 0)]
        lock = threading.Lock()
        stop_now = lambda: bool(self.cancel.get(jid) or fatal)  # noqa: E731

        def work(rid):
            if stop_now():
                return rid, "cancel", ""
            set_context(purpose=f"ویرایش کاتالوگ نهایی ({prof['name']})", ref=f"export:{eid}", item_id=None)
            client = client_for(cfg)
            client.cancel_check = stop_now
            try:
                catalogs.ai_row(eid, rid, sid, cfg, client, settings, overwrite=bool(opts.get("overwrite_ai")))
                return rid, "ok", client.usage_tokens
            except AICancelled:
                return rid, "cancel", ""
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "fatal", False):
                    with lock:
                        if not fatal:
                            fatal.append(str(exc))
                    return rid, "fatal", str(exc)
                db.log("ai", jid, f"ویرایش ردیف {rid} ناموفق بود: {exc}", level="warning", step="ai", detail=traceback.format_exc()[-1500:])
                return rid, "err", str(exc)

        consecutive = [0]
        with ThreadPoolExecutor(max_workers=max(1, min(8, int(cfg.get("concurrency", 2))))) as pool:
            futs = [pool.submit(work, i) for i in todo]
            for fut in as_completed(futs):
                try:
                    rid, st, info = fut.result()
                except CancelledError:
                    continue
                with lock:
                    if st in ("ok", "err"):
                        done_ids.add(rid)
                    if st == "ok":
                        tokens[0] += int(info or 0)
                        consecutive[0] = 0
                    elif st == "err":
                        failed[0] += 1
                        consecutive[0] += 1
                        if consecutive[0] >= 3 and not fatal:
                            fatal.append(f"۳ خطای پیاپی؛ آخرین خطا: {info}")
                    opts["_done_ids"] = sorted(done_ids)
                    db.update("ai_jobs", jid, progress_done=len(done_ids), failed=failed[0], tokens=tokens[0], options=opts,
                              step=f"ویرایش ردیف‌ها · {len(done_ids)} از {len(ids)}" if not stop_now() else "در حال توقف…")
                if stop_now():
                    for f in futs:
                        f.cancel()
        if fatal:
            db.update("ai_jobs", jid, status="error", error=fatal[0], step="به‌دلیل خطا متوقف شد؛ پس از رفع مشکل «ادامه» را بزنید.")
            return
        if self.cancel.get(jid):
            db.update("ai_jobs", jid, status="paused", step="متوقف شد؛ با «ادامه» از همان‌جا ادامه می‌یابد.")
            return
        db.update("ai_jobs", jid, status="completed", finished_at=db.now(), step="تمام شد.")
        db.log("ai", jid, f"ویرایش خروجی تمام شد: {len(done_ids) - failed[0]} موفق، {failed[0]} ناموفق.", level="success", step="ai")
    except Exception as exc:  # noqa: BLE001
        db.update("ai_jobs", jid, status="error", error=str(exc), step="خطا")
        db.log("ai", jid, "ویرایش خروجی با هوش مصنوعی متوقف شد.", level="error", step="ai", detail=traceback.format_exc())


AIJobs._run_catalog = _run_catalog
AI_JOBS = AIJobs()


def after_scrape_options(spec) -> tuple[int | None, dict] | None:
    """تبدیل تنظیم «پس از استخراج، تولید با هوش مصنوعی» به (قالب، گزینه‌های اجرا).
    spec: "schema" | "empty" | {"mode": "profile", "profile_id": N} | {"mode": "columns", "columns": [...]}"""
    if not spec:
        return None
    if isinstance(spec, (int, float)) or (isinstance(spec, str) and spec.isdigit()):
        spec = {"mode": "profile", "profile_id": int(spec)}
    if isinstance(spec, str):
        spec = {"mode": spec}
    mode = spec.get("mode")
    if mode == "profile" and spec.get("profile_id"):
        return int(spec["profile_id"]), {"scope": spec.get("scope", "all")}
    return None, {"scope": spec.get("scope", "all"), "_after": spec}


def start_after_scrape(dataset_id: int, spec) -> int | None:
    """پس از پایان استخراج: تولید خودکار ستون‌های انتخابی با هوش مصنوعی."""
    conv = after_scrape_options(spec)
    if not conv:
        return None
    pid, opts = conv
    ds = services.get_dataset(dataset_id)
    schema = services.get_schema(ds["schema_id"])
    if pid is None:
        sp = opts.pop("_after")
        if sp.get("mode") == "empty":
            sel = [{"key": c["key"], "mode": "fill_missing"} for c in schema["columns"] if ai_capable(c) and c.get("include") is not False]
        elif sp.get("mode") == "columns":
            sel = sp.get("columns") or []
        else:
            sel = None  # ستون‌های AI اسکیما
        cfg = build_config(schema, sel)
        if not cfg["fields"] and not cfg["images_list"]:
            db.log("dataset", dataset_id, "تولید خودکار پس از استخراج انجام نشد: ستونی برای تولید تنظیم نشده است.", level="warning", step="ai")
            return None
        opts["config"] = cfg
        opts["title"] = {"empty": "تکمیل همه‌ی ستون‌های خالی", "columns": "ستون‌های انتخابی"}.get(sp.get("mode"), "ستون‌های AI اسکیما")
    jid = AI_JOBS.create(dataset_id, pid, opts)
    db.log("dataset", dataset_id, "استخراج تمام شد؛ تولید خودکار با هوش مصنوعی آغاز شد.", step="ai")
    return jid


def clear_ai(item_ids: list[int], keys: list[str] | None = None):
    for iid in item_ids:
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
        if not it:
            continue
        ai = dict(it.get("ai") or {})
        if keys:
            for k in keys:
                ai.pop(k, None)
        else:
            ai = {}
        db.update("items", iid, ai=ai, updated_at=db.now())
