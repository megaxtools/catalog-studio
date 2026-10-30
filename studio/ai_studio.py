"""هوش مصنوعی در همه‌جای استودیو: دستیار همه‌منظوره و تولید بانک داده/محصول بدون اسکرپ."""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path

from . import ai_gen, db, rules, services
from .ai import AICancelled, AIClient, AIError, get_provider, parse_json
from .config import AI_IMAGES_DIR
from .engine.extract import CANONICAL_FIELDS, DIMENSION_KEYS, finalize_record
from .textutil import slugify, to_latin_digits

KINDS = ["scraped", "manual", "constant", "mapping", "auto", "ai"]
INPUTS = ["text", "longtext", "bullets", "bullet_groups", "group", "specs", "image", "images", "json", "bool", "number"]
GENERATORS = ["slug", "source_url", "source_name", "dataset_code", "scraped_at", "product_key"]
RULE_ACTIONS = ["remove", "replace", "regex", "drop_line", "prepend", "append", "drop_spec", "drop_image"]
STRATEGY_TYPES = ["api", "xhr", "jsonld", "state", "css", "meta", "regex", "spec", "auto", "const", "ai"]
AI_URL_PREFIX = "ai-generated:"

SYSTEM_ASSIST = (
    "تو دستیار هوشمند «استودیو کاتالوگ مگا» هستی؛ ابزاری برای ساخت کاتالوگ محصولات و خدمات خودرو برای بازار آنلاین «مگا کارز» در ایران. "
    "پاسخ‌ها دقیق، کاربردی و به فارسی روان باشند مگر اینکه خلافش خواسته شود. اطلاعات فنی، عدد یا گواهی را از خودت نساز. "
    "به هر تعمیرگاه یا فروشگاه «کسب‌وکار» بگو و واژه‌ی «شعبه» را به کار نبر. خروجی را فقط به شکل JSON خواسته‌شده بده."
)


# ---------------------------------------------------------------------------
# اتصال پیش‌فرض
# ---------------------------------------------------------------------------

def default_client(provider_id: int | None = None, need_image: bool = False) -> tuple[AIClient, str | None]:
    st = db.get_settings()
    pid = provider_id or (st.get("ai_default_image_provider_id") if need_image else None) or st.get("ai_default_provider_id")
    prov = get_provider(int(pid)) if pid else None
    if not prov:
        if need_image:
            row = db.q1("SELECT id FROM ai_providers WHERE image_mode<>'none' AND kind<>'anthropic' AND image_model<>'' ORDER BY id LIMIT 1")
        else:
            row = db.q1("SELECT id FROM ai_providers WHERE text_model<>'' ORDER BY id LIMIT 1") or db.q1("SELECT id FROM ai_providers ORDER BY id LIMIT 1")
        prov = get_provider(row["id"]) if row else None
    if not prov:
        raise AIError("هنوز اتصال هوش مصنوعی ندارید. در «هوش مصنوعی ← اتصال‌ها» یک اتصال بسازید.")
    model = None if need_image else (st.get("ai_default_model") or None) if not provider_id else None
    return AIClient(prov), model


def _ask(client: AIClient, model: str | None, intro: str, keys: list[tuple[str, str]], temperature: float = 0.6,
         max_tokens: int = 3000, system: str = SYSTEM_ASSIST, images: list[bytes] | None = None) -> dict:
    lines = [intro.strip(), "", "فقط و فقط یک شیء JSON معتبر برگردان (بدون توضیح، بدون ```) با این کلیدها:"]
    lines += [f'- "{k}": {d}' for k, d in keys]
    raw = client.chat(system, "\n".join(lines), model=model, temperature=temperature, max_tokens=max_tokens, images=images)
    obj = parse_json(raw)
    if not isinstance(obj, dict):
        obj = {keys[0][0]: obj}
    return obj


def _ctx_text(ctx) -> str:
    if not ctx:
        return ""
    if isinstance(ctx, str):
        return ctx[:6000]
    return json.dumps(ctx, ensure_ascii=False)[:6000]


# ---------------------------------------------------------------------------
# دستیار همه‌منظوره
# ---------------------------------------------------------------------------

def assist(task: str, payload: dict) -> dict:
    client, model = default_client(payload.get("provider_id"))
    model = payload.get("model") or model
    fn = {"text": _assist_text, "field": _assist_field, "schema": _assist_schema, "column": _assist_column,
          "mappings": _assist_mappings, "rules": _assist_rules, "source_fields": _assist_source_fields}.get(task)
    if not fn:
        raise ValueError(f"نوع درخواست ناشناخته: {task}")
    out = fn(client, model, payload)
    out["tokens"] = client.usage_tokens
    out["provider"] = client.p["name"]
    return out


def _assist_text(client, model, p):
    fmt = p.get("format") or "text"
    shape = {"text": "رشته‌ی متنی", "lines": "آرایه‌ای از رشته‌ها (هر عضو یک خط/بولت)", "slug": "رشته‌ی اسلاگ انگلیسی (a-z، 0-9 و خط تیره)",
             "json": "مقدار JSON مناسب", "english": "رشته‌ی متنی به انگلیسی", "keywords": "رشته‌ای از عبارت‌ها که با ویرگول جدا شده‌اند"}.get(fmt, "رشته‌ی متنی")
    intro = [f"فیلد: «{p.get('label') or 'متن'}»"]
    if p.get("page"):
        intro.append(f"بخش استودیو: {p['page']}")
    if p.get("context"):
        intro.append(f"زمینه: {_ctx_text(p['context'])}")
    if p.get("current"):
        intro.append(f"مقدار فعلی: «{str(p['current'])[:4000]}»")
    intro.append(f"دستور: {p.get('instruction') or 'یک مقدار مناسب و حرفه‌ای برای این فیلد بنویس.'}")
    if p.get("max_chars"):
        intro.append(f"حداکثر حدود {p['max_chars']} نویسه.")
    obj = _ask(client, model, "\n".join(intro), [("value", shape)], temperature=float(p.get("temperature", 0.7)))
    v = obj.get("value", "")
    if fmt == "slug":
        v = slugify(str(v))
    elif fmt == "lines" and isinstance(v, str):
        v = [x.strip("•-* ") for x in v.split("\n") if x.strip()]
    elif fmt in ("text", "english", "keywords") and isinstance(v, list):
        v = ("، " if fmt == "keywords" else "\n").join(map(str, v))
    return {"value": v}


def _assist_field(client, model, p):
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [int(p["item_id"])]))
    if not it:
        raise ValueError("محصول پیدا نشد.")
    ds = services.get_dataset(it["dataset_id"])
    schema = services.get_schema(ds["schema_id"])
    cols = {c["key"]: c for c in schema["columns"]}
    col = cols.get(p.get("column"))
    if not col:
        raise ValueError("ستون در اسکیمای این محصول نیست.")
    settings = db.get_settings()
    mode = p.get("mode") or "rewrite"
    field = {"target": col["key"], "enabled": True, "mode": mode, "max_chars": p.get("max_chars") or 0,
             "instruction": p.get("instruction") or f"مقدار مناسب برای «{col.get('label') or col['key']}» بنویس."}
    prof = {**json.loads(json.dumps(ai_gen.DEFAULT_PROFILE)), "fields": [field], "images": {"enabled": False}}
    if col.get("input") in ("image", "images"):
        from . import agent_ops
        r = agent_ops.generate_image(it["id"], provider_id=p.get("image_provider_id"), prompt=p.get("instruction") or "",
                                     target=col["key"], mode="add" if col.get("input") == "images" else "replace")
        return {"value": r["paths"], "column": col["key"], "saved": True, "image": True}
    cur = ai_gen._current(col, it, ds, settings)
    plan = [{"field": field, "col": col, "current": cur, "shape": ai_gen._shape(col)}]
    src = services.get_source(it["source_id"])
    ctx = ai_gen.product_context(it, ds, src)
    system, user = ai_gen.build_prompt(prof, ctx, plan)
    raw = client.chat(system, user, model=model, temperature=0.7, max_tokens=3000)
    try:
        obj = parse_json(raw)
    except AIError:
        obj = {col["key"]: raw}
    val = obj.get(col["key"]) if isinstance(obj, dict) else obj
    val = ai_gen._normalize(plan[0]["shape"][0], val, col, settings)
    if col.get("input") == "group" and mode == "fill_missing" and isinstance(cur, dict):
        val = {k: (cur.get(k) if not ai_gen._is_empty(cur.get(k)) else val.get(k, "")) for k in col.get("subkeys", [])}
    if p.get("save"):
        ai_gen.save_results(it["id"], {col["key"]: {"value": val, "mode": mode, "model": model or client.p.get("text_model"), "at": db.now()}})
    return {"value": val, "column": col["key"], "saved": bool(p.get("save"))}


def _norm_column(c: dict, used: set) -> dict | None:
    if not isinstance(c, dict):
        return None
    key = re.sub(r"[^a-z0-9_.]", "_", slugify(str(c.get("key") or c.get("label") or "field")).replace("-", "_")).strip("_") or "field"
    base, i = key, 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    used.add(key)
    kind = c.get("kind") if c.get("kind") in KINDS else "manual"
    inp = c.get("input") if c.get("input") in INPUTS else "text"
    out = {"key": key, "label": str(c.get("label") or key), "kind": kind, "input": inp}
    canon = {f["key"] for f in CANONICAL_FIELDS}
    if kind == "scraped":
        out["from"] = c.get("from") if c.get("from") in canon else ("title" if inp == "text" else "long_description")
    if kind == "constant":
        out["value"] = str(c.get("value") or "")
    if kind == "mapping":
        out["map"] = c.get("map") if c.get("map") in ("brand", "category") else "category"
        out["fallback"] = "auto"
    if kind == "auto":
        out["generator"] = c.get("generator") if c.get("generator") in GENERATORS else "slug"
    if inp == "bullet_groups":
        gs = c.get("groups") or []
        out["groups"] = [{"key": slugify(str(g.get("key") or g.get("label") or f"g{n}")).replace("-", "_") or f"g{n}", "label": str(g.get("label") or g.get("key"))}
                         for n, g in enumerate(gs) if isinstance(g, dict)] or [{"key": "dos", "label": "بایدها"}, {"key": "donts", "label": "نبایدها"}]
        out["export"] = "split"
    if inp == "group":
        out["subkeys"] = [slugify(str(x)).replace("-", "_") for x in (c.get("subkeys") or []) if str(x).strip()] or list(DIMENSION_KEYS)
        out["export"] = "json"
    if inp == "images":
        out["export"] = "comma"
    if inp in ("specs", "json"):
        out["export"] = "json"
    if c.get("required"):
        out["required"] = True
    if c.get("instruction"):
        out["ai_instruction"] = str(c["instruction"])
    if kind == "ai":
        out["ai_mode"] = "fill_missing"
    elif c.get("ai_mode") in ("fill_missing", "rewrite", "overwrite", "add"):
        out["ai_mode"] = c["ai_mode"]
    return out


_COL_KEYS = ('"key" (انگلیسی snake_case)، "label" (فارسی)، "kind" (یکی از scraped|manual|constant|mapping|auto|ai؛ ai یعنی مقدار فقط با هوش مصنوعی ساخته می‌شود)، '
             '"input" (یکی از text|longtext|bullets|bullet_groups|group|specs|image|images|json|bool|number)، "from" (برای scraped: یکی از '
             + "|".join(f["key"] for f in CANONICAL_FIELDS) + ')، "value" (برای constant)، "map" (برای mapping: brand|category)، '
             '"generator" (برای auto: slug|source_url|...)، "groups" (برای bullet_groups: آرایه‌ی {key,label})، "subkeys" (برای group)، '
             '"required" (true/false)، "instruction" (دستور کوتاه تولید محتوای این ستون)، "ai_mode" (اگر ستون باید با هوش مصنوعی تولید یا تکمیل شود: fill_missing|rewrite|overwrite، وگرنه خالی)')


def _assist_schema(client, model, p):
    intro = ("یک اسکیمای خروجی کاتالوگ محصول طراحی کن. هر ستون یک فیلد فایل Excel خروجی است. ستون‌هایی که از سایت منبع خوانده می‌شوند "
             "kind=scraped، ستون‌هایی که کاربر یا هوش مصنوعی تکمیل می‌کند kind=manual، مقادیر ثابت kind=constant، اسلاگ برند/دسته kind=mapping "
             "و اسلاگ و لینک منبع kind=auto باشند.\n"
             f"توضیح کاربر: {p.get('description') or 'اسکیمای کامل کاتالوگ محصولات خودرویی'}")
    if p.get("base_columns"):
        intro += f"\nستون‌های فعلی (تکرار نکن، فقط تکمیل کن): {', '.join(c.get('key', '') for c in p['base_columns'])}"
    obj = _ask(client, model, intro, [("name", "نام فارسی اسکیما"), ("description", "توضیح کوتاه"),
                                      ("columns", f"آرایه‌ای از 12 شیء JSON با کلیدهای {_COL_KEYS}")], max_tokens=5000)
    used = {c.get("key") for c in (p.get("base_columns") or [])}
    cols = [x for x in (_norm_column(c, used) for c in (obj.get("columns") or [])) if x]
    return {"name": obj.get("name") or "اسکیمای تولیدشده", "description": obj.get("description") or "", "columns": cols}


def _assist_column(client, model, p):
    intro = f"یک ستون برای اسکیمای خروجی کاتالوگ طراحی کن.\nتوضیح کاربر: {p.get('description')}"
    if p.get("schema_columns"):
        intro += f"\nستون‌های موجود: {', '.join(c.get('key', '') for c in p['schema_columns'])}"
    obj = _ask(client, model, intro, [("column", f"شیء JSON با کلیدهای {_COL_KEYS}")])
    col = _norm_column(obj.get("column") or obj, {c.get("key") for c in (p.get("schema_columns") or [])})
    return {"column": col}


def _assist_mappings(client, model, p):
    vals = [str(v) for v in (p.get("values") or []) if str(v).strip()][:120]
    if not vals:
        return {"rows": []}
    kind = p.get("kind", "category")
    intro = (f"برای هر مقدار {'برند' if kind == 'brand' else 'دسته‌بندی'} زیر یک اسلاگ انگلیسی سئوشده و یک برچسب فارسی پیشنهاد بده. "
             "برای برندها نام رسمی لاتین برند را اسلاگ کن (مثلاً کاسپین → caspian). برای دسته‌ها اسلاگ کوتاه و توصیفی بده (مثلاً روغن موتور → engine-oil).\n"
             f"مقادیر: {json.dumps(vals, ensure_ascii=False)}")
    if p.get("targets"):
        intro += f"\nاگر مناسب است، از این اسلاگ‌های موجود استفاده کن: {', '.join(p['targets'][:200])}"
    obj = _ask(client, model, intro, [("rows", f'آرایه‌ای از {len(vals)} شیء JSON با کلیدهای "source_value", "target_slug", "target_label"')], temperature=0.2)
    rows = []
    by = {str(r.get("source_value")): r for r in (obj.get("rows") or []) if isinstance(r, dict)}
    for i, v in enumerate(vals):
        r = by.get(v) or ((obj.get("rows") or [{}])[i] if i < len(obj.get("rows") or []) else {})
        slug = slugify(str(r.get("target_slug") or v)) or slugify(v)
        rows.append({"source_value": v, "target_slug": slug, "target_label": str(r.get("target_label") or v)})
    return {"rows": rows}


def _assist_rules(client, model, p):
    intro = ("بر اساس توضیح کاربر، قاعده‌های پاک‌سازی متن بساز. عملیات‌ها: remove (حذف عبارت‌ها؛ چند عبارت با | جدا)، replace (find→value)، "
             "regex (الگوی پایتون)، drop_line (حذف خط‌های شامل عبارت)، prepend/append (افزودن value به ابتدا/انتها)، drop_spec (حذف ردیف مشخصات)، "
             "drop_image (حذف تصویر با آدرس شامل عبارت). target یکی از * یا title، short_description، long_description، specifications، gallery، brand است.\n"
             f"توضیح کاربر: {p.get('description')}")
    obj = _ask(client, model, intro, [("rules", 'آرایه‌ای از 3 شیء JSON با کلیدهای "name", "action", "target", "find", "value"')], temperature=0.2)
    out = []
    for r in obj.get("rules") or []:
        if not isinstance(r, dict):
            continue
        a = r.get("action") if r.get("action") in RULE_ACTIONS else "remove"
        tgt = str(r.get("target") or "*")
        if a in ("prepend", "append") and tgt == "*":
            tgt = "short_description"
        out.append({"name": str(r.get("name") or a), "action": a, "target": tgt, "find": str(r.get("find") or ""), "value": str(r.get("value") or ""),
                    "flags": {"split": "" if a == "regex" else "|"}})
    return {"rules": out}


def _assist_source_fields(client, model, p):
    ex = p.get("explorer") or {}
    groups = []
    for g in (ex.get("groups") or [])[:8]:
        groups.append({"type": g.get("type"), "match": g.get("match"), "name": g.get("name"), "at_type": g.get("at_type"),
                       "leaves": [{"path": l["path"], "value": str(l["value"])[:120]} for l in (g.get("leaves") or [])[:150]]})
    canon = [f["key"] for f in CANONICAL_FIELDS if f["key"] not in ("dimensions", "dimension_codes")]
    intro = ("داده‌های ساخت‌یافته‌ی یک صفحه‌ی محصول (JSON-LD، داده‌ی Next/Nuxt، پاسخ‌های شبکه) در زیر آمده است. برای هر فیلد استاندارد، "
             "بهترین مسیر داده را پیدا کن و یک «راهبرد» استخراج پیشنهاد بده. راهبرد یکی از این‌هاست: "
             '{"type":"jsonld","at_type":"Product","path":"..."}، {"type":"state","name":"__NEXT_DATA__","path":"..."}، '
             '{"type":"xhr","match":"<بخشی از آدرس>","path":"..."}، {"type":"api","path":"..."}، {"type":"meta","name":"og:image"}، '
             '{"type":"css","selector":"h1","attr":"text"}، و اگر داده‌ی ساخت‌یافته‌ای برای فیلدی نیست ولی در متن صفحه آمده، '
             '{"type":"ai","mode":"extract","instruction":"..."} (استخراج با هوش مصنوعی از متن صفحه). در مسیرها [] یعنی همه‌ی اعضای آرایه و [0] یعنی اولی. '
             "برای تصاویر گالری مسیر آرایه با [] بده. اگر داده‌ای برای فیلدی نیست، آن را نیاور.\n"
             f"فیلدهای استاندارد: {', '.join(canon)}\n"
             f"تیترهای صفحه: {json.dumps(ex.get('headings', [])[:5], ensure_ascii=False)}\n"
             f"داده‌ها: {json.dumps(groups, ensure_ascii=False)[:24000]}")
    if p.get("record"):
        intro += f"\nنتیجه‌ی فعلی استخراج (برای مقایسه): {json.dumps({k: v for k, v in p['record'].items() if k in canon}, ensure_ascii=False)[:3000]}"
    obj = _ask(client, model, intro, [("fields", 'آرایه‌ای از 8 شیء JSON با کلیدهای "key", "strategies"')], temperature=0.1, max_tokens=4000)
    out = []
    for f in obj.get("fields") or []:
        if not isinstance(f, dict) or f.get("key") not in canon:
            continue
        sts = []
        for s in f.get("strategies") or []:
            if isinstance(s, dict) and s.get("type") in STRATEGY_TYPES:
                sts.append({k: v for k, v in s.items() if k in ("type", "path", "match", "name", "at_type", "selector", "attr", "all", "names", "mode", "instruction")})
        if sts:
            out.append({"key": f["key"], "strategies": sts})
    return {"fields": out}


# ---------------------------------------------------------------------------
# تولید بانک داده / محصول بدون اسکرپ
# ---------------------------------------------------------------------------

def ensure_ai_source() -> dict:
    row = db.q1("SELECT id FROM sources WHERE key='ai-generated'")
    if row:
        return services.get_source(row["id"])
    cfg = {"key": "ai-generated", "name": "تولید با هوش مصنوعی", "virtual": True, "domains": [],
           "notes": "منبع مجازی برای محصولاتی که بدون اسکرپ و فقط با هوش مصنوعی ساخته می‌شوند.", "listing": {}, "product": {}, "fields": []}
    return services.save_source(cfg)


def create_dataset(spec: dict) -> dict:
    if not (spec.get("product_type") or "").strip():
        raise ValueError("نوع محصول را مشخص کنید.")
    count = max(1, min(1000, int(spec.get("count") or 10)))
    src = ensure_ai_source()
    label = (spec.get("category_label") or spec["product_type"]).strip()
    url = f"ai://generate/{slugify(label) or 'products'}"
    spec = {**spec, "count": count, "active": True}
    ds = services.create_dataset(src["id"], url, count, spec.get("schema_id"), {"ai_only": True, "ai_generate": spec, "category_label_manual": True},
                                 {}, label)
    db.update("datasets", ds["id"], category_key=slugify(label) or "products")
    services.refresh_dataset_naming(ds["id"])
    db.log("dataset", ds["id"], f"بانک داده‌ی تولیدی با هوش مصنوعی ساخته شد: {count} × «{spec['product_type']}»", step="ai")
    if spec.get("start", True):
        AI_DATASETS.start(ds["id"])
    return services.get_dataset(ds["id"])


def add_products(dataset_id: int, spec: dict) -> dict:
    ds = services.get_dataset(dataset_id)
    if not ds:
        raise ValueError("بانک داده پیدا نشد.")
    n = max(1, min(500, int(spec.get("count") or 1)))
    existing_ai = db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND url LIKE ?", [dataset_id, AI_URL_PREFIX + "%"]) or 0
    cur = (ds["options"] or {}).get("ai_generate") or {}
    new = {**cur, **{k: v for k, v in spec.items() if v not in (None, "")}}
    new["product_type"] = new.get("product_type") or ds.get("category_label") or "محصول خودرویی"
    new["count"] = existing_ai + n
    new["active"] = True
    opts = {**(ds["options"] or {}), "ai_generate": new}
    upd = {"options": opts}
    if ds.get("item_limit") and ds["item_limit"] < ds["counts"]["done"] + ds["counts"]["partial"] + n:
        upd["item_limit"] = ds["counts"]["done"] + ds["counts"]["partial"] + n
    db.update("datasets", dataset_id, **upd)
    AI_DATASETS.start(dataset_id)
    return services.get_dataset(dataset_id)


def _canon_keys() -> list[tuple[str, str]]:
    return [
        ("title", "عنوان کامل فارسی محصول (نوع + برند + مدل + ویژگی کلیدی مثل حجم/اندازه)"),
        ("title_en", "عنوان انگلیسی محصول"),
        ("brand", "نام فارسی برند"),
        ("brand_en", "نام لاتین برند"),
        ("category", "نام دسته‌بندی"),
        ("short_description", "رشته‌ی متنی؛ توضیح کوتاه یکتا در ۱ تا ۲ جمله"),
        ("long_description", "رشته‌ی متنی؛ توضیح کامل در ۳ تا ۵ پاراگراف کوتاه (معرفی، ویژگی‌ها، کاربرد و سازگاری، نگهداری)"),
        ("specifications", 'آرایه‌ای از اشیاء {"group": ..., "name": ..., "value": ...}؛ ۶ تا ۱۲ ردیف مشخصات فنی واقع‌گرایانه با واحد'),
        ("dimensions", "شیء JSON با کلیدهای " + ", ".join(f'"{k}"' for k in DIMENSION_KEYS) + "؛ مقدار هر کلید یک عدد به‌صورت رشته (وزن گرم، ابعاد سانتی‌متر)"),
    ]


def gen_columns(cols: list[dict]) -> list[dict]:
    """ستون‌هایی که در تولید بدون اسکرپ مستقیم با هوش مصنوعی پر می‌شوند (ستون‌های استخراجی از داده‌ی استاندارد ساخته می‌شوند)."""
    return [c for c in cols if c.get("input") not in ("image", "images") and ai_gen.ai_capable(c) and c.get("include") is not False
            and (c.get("kind") in ("manual", "ai") or (c.get("kind") != "scraped" and c.get("ai_mode") not in (None, "", "off")))]


class AIDatasetRunner:
    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}
        self.flags: dict[int, str | None] = {}

    def is_running(self, did: int) -> bool:
        t = self.threads.get(did)
        return bool(t and t.is_alive())

    def start(self, did: int):
        if self.is_running(did):
            return
        self.flags[did] = None
        db.update("datasets", did, status="starting", step="آماده‌سازی تولید با هوش مصنوعی…", updated_at=db.now())
        t = threading.Thread(target=self._run, args=(did,), daemon=True, name=f"ai-ds-{did}")
        self.threads[did] = t
        t.start()

    def heal(self):
        for r in db.q("SELECT id, options FROM datasets WHERE status IN ('running','starting')"):
            if (db.jload(r["options"], {}) or {}).get("ai_only") and not self.is_running(r["id"]):
                db.update("datasets", r["id"], status="paused", step="اجرا قطع شده بود؛ با «ادامه» از همان نقطه ادامه می‌یابد.")

    def pause(self, did: int, final: str = "pause"):
        self.flags[did] = final
        if not self.is_running(did):
            db.update("datasets", did, status="paused" if final == "pause" else "stopped", step="متوقف شد.")
        else:
            db.update("datasets", did, step="در حال توقف… (منتظر پاسخ درخواست‌های در جریان)")

    # ------------------------------------------------------------------
    def _step(self, did, text, **kw):
        db.update("datasets", did, step=text, updated_at=db.now(), **kw)

    def _check(self, did):
        f = self.flags.get(did)
        if f:
            raise InterruptedError(f)

    def _run(self, did: int):
        ds = services.get_dataset(did)
        spec = dict((ds["options"] or {}).get("ai_generate") or {})
        final, final_step = "completed", "تولید با هوش مصنوعی تمام شد."
        db.update("datasets", did, status="running", started_at=ds["started_at"] or db.now(), updated_at=db.now())
        try:
            schema = services.get_schema(ds["schema_id"])
            client, dmodel = default_client(spec.get("provider_id"))
            client.cancel_check = lambda: bool(self.flags.get(did))
            from .ai import set_context
            set_context(purpose="تولید بانک داده بدون اسکرپ", ref=f"dataset:{did}")
            model = spec.get("model") or dmodel
            target = int(spec.get("count") or 10)
            self._plan(did, ds, spec, client, model, target)
            self._generate(did, ds, spec, schema, client, model)
        except InterruptedError as e:
            final = "stopped" if str(e) == "stop" else "paused"
            final_step = "متوقف شد؛ با «ادامه» از همان نقطه ادامه می‌یابد."
        except AICancelled:
            final = "stopped" if self.flags.get(did) == "stop" else "paused"
            final_step = "متوقف شد؛ با «ادامه» از همان نقطه ادامه می‌یابد."
        except Exception as exc:  # noqa: BLE001
            final, final_step = "error", f"خطا در تولید: {exc}"
            db.log("dataset", did, "تولید با هوش مصنوعی متوقف شد.", level="error", step="ai", detail=traceback.format_exc())
        finally:
            self.flags[did] = None
            ds2 = services.get_dataset(did)
            opts = dict(ds2["options"] or {})
            if final == "completed":
                g = dict(opts.get("ai_generate") or {})
                g["active"] = False
                opts["ai_generate"] = g
                db.update("datasets", did, options=opts, discovery_done=1, finished_at=db.now())
            db.update("datasets", did, status=final, step=final_step, updated_at=db.now())
            services.refresh_dataset_naming(did)
            if final == "completed":
                db.log("dataset", did, final_step, level="success", step="ai")

    def _ai_items(self, did) -> list[dict]:
        return db.q("SELECT id, data, status FROM items WHERE dataset_id=? AND url LIKE ? ORDER BY seq, id", [did, AI_URL_PREFIX + "%"])

    def _plan(self, did, ds, spec, client, model, target):
        existing = self._ai_items(did)
        titles = [db.jload(r["data"], {}).get("title", "") for r in db.q("SELECT data FROM items WHERE dataset_id=?", [did])]
        tries = 0
        while len(existing) < target:
            self._check(did)
            need = min(15, target - len(existing))
            self._step(did, f"برنامه‌ریزی محصولات · {len(existing)} از {target}")
            intro = [f"برای کاتالوگ «مگا کارز» فهرست {need} محصول متمایز و واقعی‌نما از نوع «{spec['product_type']}» پیشنهاد بده."]
            if spec.get("category_label"):
                intro.append(f"دسته‌بندی: {spec['category_label']}")
            if spec.get("brands"):
                intro.append(f"برندها (فقط از همین‌ها یا مشابه آن‌ها): {spec['brands']}")
            if spec.get("notes"):
                intro.append(f"توضیحات تکمیلی کاربر: {spec['notes']}")
            intro.append("محصولات باید از نظر برند، مدل، حجم/اندازه یا کاربرد با هم فرق داشته باشند و برای بازار ایران واقع‌گرایانه باشند. "
                         "نام مدل یا کد تجاری را فقط اگر مطمئنی واقعی است بیاور؛ در غیر این صورت توصیفی نام‌گذاری کن.")
            if titles:
                intro.append(f"این محصولات قبلاً هستند و نباید تکرار شوند: {json.dumps(titles[-120:], ensure_ascii=False)}")
            obj = _ask(client, model, "\n".join(intro), [("products", f'آرایه‌ای از {need} شیء JSON با کلیدهای "title", "title_en", "brand", "brief"')],
                       temperature=0.9, max_tokens=4000)
            added = 0
            seq = (db.val("SELECT MAX(seq) FROM items WHERE dataset_id=?", [did]) or 0) + 1
            for pr in obj.get("products") or []:
                if not isinstance(pr, dict) or not str(pr.get("title") or "").strip():
                    continue
                t = str(pr["title"]).strip()
                if t in titles:
                    continue
                key = (slugify(pr.get("title_en") or t) or f"p{seq}")[:80]
                if db.q1("SELECT id FROM items WHERE dataset_id=? AND product_key=?", [did, key]):
                    key = f"{key}-{seq}"
                db.ex("""INSERT INTO items(dataset_id, source_id, url, product_key, seq, status, data, created_at, updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      [did, ds["source_id"], f"{AI_URL_PREFIX}{ds['code']}:{seq}", key, seq, "queued",
                       db.jdump({"title": t, "title_en": str(pr.get("title_en") or ""), "brand": str(pr.get("brand") or ""), "_brief": str(pr.get("brief") or "")}),
                       db.now(), db.now()])
                titles.append(t)
                seq += 1
                added += 1
                if len(existing) + added >= target:
                    break
            existing = self._ai_items(did)
            db.update("datasets", did, total_found=db.val("SELECT COUNT(*) FROM items WHERE dataset_id=?", [did]), total_expected=target)
            if not added:
                tries += 1
                if tries >= 3:
                    db.log("dataset", did, "مدل محصول تازه‌ی غیرتکراری پیشنهاد نداد؛ تولید با همین تعداد ادامه می‌یابد.", level="warning", step="ai")
                    break
            else:
                tries = 0

    def _generate(self, did, ds, spec, schema, client, model):
        settings = db.get_settings()
        cols = [c for c in schema["columns"] if c.get("include") is not False]
        manual_cols = gen_columns(cols)
        todo = [r["id"] for r in db.q("SELECT id FROM items WHERE dataset_id=? AND url LIKE ? AND status IN ('queued','failed') ORDER BY seq, id",
                                      [did, AI_URL_PREFIX + "%"])]
        total = len(self._ai_items(did))
        img = spec.get("images") or {}
        lock = threading.Lock()
        errs = [0]

        def work(iid):
            self._check(did)
            from .ai import set_context
            set_context(purpose="تولید بانک داده بدون اسکرپ", ref=f"dataset:{did}", item_id=iid)
            it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [iid]))
            last = None
            for attempt in range(2):
                try:
                    self._one(it, ds, spec, manual_cols, client, model, settings, img)
                    return iid, ""
                except (InterruptedError, AICancelled):
                    raise InterruptedError(self.flags.get(did) or "pause")
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "fatal", False):
                        self.flags[did] = self.flags.get(did) or "fatal"
                        raise
                    last = exc
                    self._check(did)
                    time.sleep(2 * (attempt + 1))
            db.update("items", iid, status="failed", error=str(last), updated_at=db.now())
            db.log("dataset", did, f"تولید محصول ناموفق بود: {last}", level="warning", step="ai", item_id=iid)
            return iid, str(last)

        conc = max(1, min(6, int(spec.get("concurrency") or 2)))
        with ThreadPoolExecutor(max_workers=conc) as pool:
            futs = [pool.submit(work, i) for i in todo]
            for fut in as_completed(futs):
                try:
                    _, err = fut.result()
                except CancelledError:
                    continue
                except InterruptedError:
                    for f in futs:
                        f.cancel()
                    if self.flags.get(did) == "fatal":
                        continue
                    raise
                except Exception as exc:  # noqa: BLE001  — خطای قطعی (کلید، اعتبار، مدل، شبکه)
                    for f in futs:
                        f.cancel()
                    raise RuntimeError(str(exc)) from exc
                with lock:
                    errs[0] = errs[0] + 1 if err else 0
                    done = db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND url LIKE ? AND status='done'", [did, AI_URL_PREFIX + "%"])
                    self._step(did, f"تولید محصولات با هوش مصنوعی · {done} از {total}")
                    services.refresh_dataset_naming(did)
                if errs[0] >= 3:
                    for f in futs:
                        f.cancel()
                    raise RuntimeError(f"۳ خطای پیاپی؛ آخرین خطا: {err}")
                if self.flags.get(did):
                    pool.shutdown(cancel_futures=True)
                    raise InterruptedError(self.flags[did])

    def _one(self, it, ds, spec, manual_cols, client, model, settings, img):
        d = it["data"]
        intro = [f"برای کاتالوگ «مگا کارز» اطلاعات کامل این محصول را بنویس.",
                 f"- عنوان: {d.get('title')}", f"- برند: {d.get('brand') or 'نامشخص'}", f"- نوع محصول: {spec['product_type']}"]
        if d.get("_brief"):
            intro.append(f"- توضیح کوتاه: {d['_brief']}")
        if spec.get("category_label"):
            intro.append(f"- دسته‌بندی: {spec['category_label']}")
        if spec.get("notes"):
            intro.append(f"- توضیحات تکمیلی کاربر: {spec['notes']}")
        if spec.get("seo_keywords"):
            intro.append(f"کلیدواژه‌های سئو: {spec['seo_keywords']}")
        intro.append("مشخصات فنی باید با نوع محصول سازگار و واقع‌گرایانه باشد. متن‌ها فارسی، یکتا و بدون اغراق، بدون ذکر قیمت و نام فروشگاه‌ها.")
        keys = _canon_keys()
        for c in manual_cols:
            shape = ai_gen._shape(c)[1]
            instr = ai_gen.default_instruction(c)
            keys.append((c["key"], f"{shape}. {instr}"))
        obj = _ask(client, model, "\n".join(intro), keys, temperature=float(spec.get("temperature", 0.7)), max_tokens=int(spec.get("max_tokens", 4500)))
        # عنوان یکتای مرحله‌ی برنامه‌ریزی حفظ می‌شود تا محصولات تکراری نشوند
        data = {"title": str(d.get("title") or obj.get("title") or ""), "title_en": str(d.get("title_en") or obj.get("title_en") or ""),
                "brand": str(d.get("brand") or obj.get("brand") or ""), "brand_en": str(obj.get("brand_en") or ""),
                "category": str(obj.get("category") or spec.get("category_label") or spec["product_type"]),
                "short_description": str(obj.get("short_description") or ""), "long_description": ai_gen._normalize("text", obj.get("long_description"), {}, settings),
                "specifications": ai_gen._normalize("specs", obj.get("specifications") or [], {}, settings), "_ai_generated": True}
        dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
        data["dimensions"] = {k: to_latin_digits(str(dims.get(k, "") or "")).strip() for k in DIMENSION_KEYS}
        data = finalize_record(data, {})
        aiv = {}
        for c in manual_cols:
            if c["key"] in obj:
                v = ai_gen._normalize(ai_gen._shape(c)[0], obj[c["key"]], c, settings)
                if not ai_gen._is_empty(v):
                    aiv[c["key"]] = {"value": v, "mode": "overwrite", "model": model or client.p.get("text_model"), "at": db.now()}
        if img.get("enabled"):
            data.update(self._images(it, data, ds, spec, img))
        db.update("items", it["id"], data=data, status="done", error="", missing=[], scraped_at=db.now(), updated_at=db.now(),
                  ai={**(it.get("ai") or {}), **aiv, "__meta": {"at": db.now(), "error": "", "generated": True}})

    def _images(self, it, data, ds, spec, img) -> dict:
        iclient, _ = default_client(img.get("provider_id"), need_image=True)
        iclient.cancel_check = lambda: bool(self.flags.get(it["dataset_id"]))
        ctx = {"title": data["title"], "title_en": data.get("title_en", ""), "brand": data.get("brand", ""), "category": data.get("category", ""),
               "specs": "\n".join(f"- {s['name']}: {s['value']}" for s in data.get("specifications", [])[:12])}
        prompt = (img.get("prompt") or ai_gen.DEFAULT_IMAGE_PROMPT).format_map(ai_gen._SafeDict(ctx))
        n = max(1, min(4, int(img.get("count") or 1)))
        out = AI_IMAGES_DIR / f"ds{it['dataset_id']}" / f"item{it['id']}"
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(n):
            angle = "" if i == 0 else [", side view", ", back view showing label", ", detail close-up", ", in use context"][min(i - 1, 3)]
            b = iclient.image(prompt + angle, model=img.get("model") or None, size=img.get("size") or "1024x1024")
            p = out / f"{'feature' if i == 0 else f'gallery_{i}'}_{int(time.time() * 1000)}.png"
            p.write_bytes(b)
            paths.append(str(p))
        return {"featured_image": paths[0], "gallery": paths[1:]}

    def regenerate_item(self, item_id: int) -> dict:
        it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))
        ds = services.get_dataset(it["dataset_id"])
        spec = dict((ds["options"] or {}).get("ai_generate") or {"product_type": ds.get("category_label") or "محصول"})
        schema = services.get_schema(ds["schema_id"])
        client, dmodel = default_client(spec.get("provider_id"))
        manual_cols = gen_columns(schema["columns"])
        self._one(it, ds, spec, manual_cols, client, spec.get("model") or dmodel, db.get_settings(), spec.get("images") or {})
        return services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))


AI_DATASETS = AIDatasetRunner()


def is_ai_dataset(ds: dict) -> bool:
    g = (ds.get("options") or {}).get("ai_generate") or {}
    return bool((ds.get("options") or {}).get("ai_only") or g.get("active"))


# ---------------------------------------------------------------------------
# تولید یک ستون برای کل بانک داده
# ---------------------------------------------------------------------------

def column_job(dataset_id: int, column: str, mode: str = "fill_missing", instruction: str = "", scope: str = "all",
               item_ids: list | None = None, provider_id: int | None = None, model: str | None = None) -> int:
    ds = services.get_dataset(dataset_id)
    schema = services.get_schema(ds["schema_id"])
    col = next((c for c in schema["columns"] if c["key"] == column), None)
    if not col:
        raise ValueError("ستون در اسکیمای این بانک نیست.")
    client, dmodel = default_client(provider_id)
    cfg = {"provider_id": client.p["id"], "model": model or dmodel or "", "batch": True,
           "fields": [], "images": {"enabled": False}}
    if col.get("input") in ("image", "images"):
        iclient, _ = default_client(provider_id, need_image=True)
        cfg["provider_id"] = iclient.p["id"]
        cfg["images"] = {"enabled": True, "target": column, "mode": "add" if mode == "add" else mode, "count": 1, "size": "1024x1024",
                         "use_reference": True, "prompt": instruction or ai_gen.DEFAULT_IMAGE_PROMPT}
    else:
        cfg["fields"] = [{"target": column, "enabled": True, "mode": mode, "max_chars": 0,
                          "instruction": instruction or col.get("ai_instruction") or f"مقدار مناسب برای «{col.get('label') or column}» بنویس."}]
    return ai_gen.AI_JOBS.create(dataset_id, None, {"config": cfg, "scope": scope, "item_ids": item_ids or [], "overwrite_ai": mode != "fill_missing",
                                                    "title": f"تولید ستون «{col.get('label') or column}»"})
