"""کارهای هوش مصنوعی نسخه‌ی ۲ در بخش‌هایی که پیش‌تر AI نداشتند:

- برندها و دسته‌ها: تکمیل (نام انگلیسی، اسلاگ، نام‌های دیگر، توضیح، دسته‌های برند، والد دسته)، تطبیق نام‌های خام
  تطبیق‌نخورده، و پیشنهاد فهرست برند یا درخت دسته از یک توضیح.
- الگوی خروجی کاتالوگ: طراحی الگو (درخت فایل) از توضیح متنی.
- تکراری‌ها: داوری اینکه دو محصول واقعاً یکی‌اند یا نه.
- ورود فایل: نگاشت سرستون‌های ناشناخته به فیلدهای استاندارد.

هیچ‌کدام مستقیم چیزی ذخیره نمی‌کنند: «پیشنهاد» برمی‌گردانند تا کاربر (یا ایجنت) ببیند و تأیید کند؛ ذخیره با همان مسیرهای
معمولی انجام می‌شود و نسخه‌دار است. هر درخواست با set_context برچسب می‌خورد.
"""
from __future__ import annotations

import json
import re

from . import db, import_specs, refdata
from .ai import parse_json, set_context
from .ai_studio import SYSTEM_ASSIST, default_client
from .textutil import slugify

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _chat(task: str, prompt: str, provider_id=None, max_tokens: int = 3500, temperature: float = 0.3, purpose: str = "", ref: str = ""):
    set_context(purpose=purpose or task, ref=ref)
    client, model = default_client(provider_id)
    raw = client.chat(SYSTEM_ASSIST, f"TASK: {task}\n{prompt}", model=model, temperature=temperature, max_tokens=max_tokens)
    obj = parse_json(raw)
    if not isinstance(obj, (dict, list)):
        raise ValueError("پاسخ هوش مصنوعی قابل خواندن نبود؛ دوباره امتحان کنید.")
    return obj


def _clean_slug(s: str, fallback: str = "") -> str:
    s = slugify(str(s or "")) or slugify(fallback or "")
    return s if _SLUG_RE.match(s or "") else ""


def _cat_lines() -> str:
    cats = refdata.category_index()
    return "\n".join(f"{c['slug']} = {c['path']}" for c in sorted(cats.values(), key=lambda x: x["path"]))[:9000]


def _cat_slugs(vals) -> list[int]:
    out = []
    for v in import_specs.split_list(vals) if not isinstance(vals, list) else vals:
        r = db.q1("SELECT id FROM ref_categories WHERE slug=?", [str(v).strip().lower()])
        cid = r["id"] if r else refdata.resolve("category", str(v))
        if cid and cid not in out:
            out.append(cid)
    return out


# ---------------------------------------------------------------------------
# برندها و دسته‌ها
# ---------------------------------------------------------------------------

REF_FIELDS = {"brand": ["name_en", "slug", "aliases", "description", "categories", "country"],
              "category": ["name_en", "slug", "aliases", "description", "parent"]}


def ref_complete(kind: str, items: list[dict], fields: list[str] | None = None, only_empty: bool = True, provider_id=None) -> dict:
    """پیشنهاد برای تکمیل فیلدهای چند برند/دسته. items: [{id?, name, …}] (موارد ذخیره‌نشده هم قبول است)."""
    fields = [f for f in (fields or REF_FIELDS[kind]) if f in REF_FIELDS[kind]]
    if not items:
        raise ValueError("موردی برای تکمیل انتخاب نشده است.")
    items = items[:60]
    inp = []
    for i, it in enumerate(items):
        inp.append({"i": i, "name": it.get("name"), "name_en": it.get("name_en") or "", "slug": it.get("slug") or "",
                    "aliases": it.get("aliases") or [], "description": it.get("description") or ""})
    desc = {
        "name_en": "نام رسمی لاتین (برای برند همان نام تجاری بین‌المللی)",
        "slug": "اسلاگ انگلیسی کوتاه: فقط حروف کوچک، عدد و خط تیره",
        "aliases": "۲ تا ۶ املای رایج دیگر (فارسی و لاتین) که ممکن است در سایت‌های فروش آمده باشد",
        "description": "یک جمله‌ی کوتاه و دقیق فارسی؛ اگر اطلاعات مطمئن نداری خالی بگذار",
        "categories": "آرایه‌ای از اسلاگ دسته‌هایی که این برند در آن‌ها محصول دارد، فقط از فهرست دسته‌های زیر",
        "country": "کشور مبدأ برند به فارسی؛ اگر مطمئن نیستی خالی",
        "parent": "اسلاگ مناسب‌ترین دسته‌ی والد از فهرست زیر، یا خالی برای ریشه",
    }
    label = "برندهای" if kind == "brand" else "دسته‌بندی‌های"
    prompt = (f"{label} زیر در فهرست مرجع مارکت‌پلیس خودرویی «مگا کارز» هستند. برای هرکدام این فیلدها را پیشنهاد بده:\n"
              + "\n".join(f"- {f}: {desc[f]}" for f in fields)
              + ("\n\nفهرست دسته‌های موجود (اسلاگ = مسیر):\n" + _cat_lines() if ("categories" in fields or "parent" in fields) else "")
              + "\n\nورودی (JSON):\nINPUT: " + json.dumps(inp, ensure_ascii=False)
              + '\n\nفقط یک شیء JSON برگردان: {"items": [{"i": شماره‌ی ورودی, ' + ", ".join(f'"{f}": …' for f in fields) + "}]}")
    obj = _chat("ref_complete", prompt, provider_id, purpose=f"تکمیل {refdata.LABELS[kind]} با AI", ref=f"ref_{kind}")
    rows = obj.get("items") if isinstance(obj, dict) else obj
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            src = items[int(r.get("i"))]
        except (TypeError, ValueError, IndexError):
            continue
        prop: dict = {}
        for f in fields:
            v = r.get(f)
            if v in (None, "", []):
                continue
            if only_empty and src.get(f if f not in ("categories", "parent") else ("category_ids" if f == "categories" else "parent_id")) not in (None, "", [], 0):
                if f not in ("aliases",):
                    continue
            if f == "slug":
                v = _clean_slug(v, r.get("name_en") or src.get("name_en"))
                if not v:
                    continue
            elif f == "aliases":
                cur = {refdata.norm(a) for a in (src.get("aliases") or []) + [src.get("name") or ""]}
                v = [a for a in import_specs.split_list(v) if refdata.norm(a) not in cur][:8]
                if not v:
                    continue
                v = list(src.get("aliases") or []) + v
            elif f == "categories":
                ids = _cat_slugs(v)
                if not ids:
                    continue
                prop["category_ids"] = ids
                cats = refdata.category_index()
                prop["categories_label"] = [cats[c]["path"] for c in ids if c in cats]
                continue
            elif f == "parent":
                ids = _cat_slugs([v])
                if not ids or ids[0] == src.get("id"):
                    continue
                prop["parent_id"] = ids[0]
                prop["parent_label"] = refdata.category_index()[ids[0]]["path"]
                continue
            else:
                v = str(v).strip()
            prop[f] = v
        if prop:
            out.append({"id": src.get("id"), "name": src.get("name"), "proposal": prop})
    return {"items": out, "fields": fields}


def ref_match(kind: str, names: list[str] | None = None, provider_id=None) -> dict:
    """نام‌های خام تطبیق‌نخورده → وصل به مورد موجود (id) یا پیشنهاد مورد تازه."""
    names = names or [u["name"] for u in refdata.unmatched(kind)]
    names = [n for n in names if n][:80]
    if not names:
        return {"items": []}
    existing = refdata.list_items(kind, with_counts=False)
    lines = "\n".join(f"{r['id']} = {r['name']} / {r.get('name_en') or ''} / {r['slug']}" + (f" (نام‌های دیگر: {'، '.join(r['aliases'][:5])})" if r["aliases"] else "")
                      for r in existing)[:9000]
    label = refdata.LABELS[kind]
    prompt = (f"این نام‌ها در داده‌ی خام محصولات به‌عنوان {label} آمده‌اند ولی با فهرست مرجع جور نشده‌اند. برای هر نام:\n"
              f"- اگر همان یکی از موارد فهرست است (املای دیگر، فارسی/لاتین، با پسوند و پیشوند)، id آن را بده.\n"
              f"- اگر {label} تازه‌ای است، id را null بگذار و name (فارسی درست)، name_en و slug (انگلیسی) پیشنهاد بده.\n"
              f"- اگر اصلاً {label} نیست (مثلاً متن بی‌معنی)، skip را true بگذار.\n\n"
              f"فهرست مرجع (id = نام / نام انگلیسی / اسلاگ):\n{lines or '(خالی)'}\n\nINPUT: {json.dumps(names, ensure_ascii=False)}\n\n"
              'فقط JSON: {"items": [{"raw": "نام خام", "id": عدد یا null, "name": "", "name_en": "", "slug": "", "skip": false, "reason": "توضیح خیلی کوتاه"}]}')
    obj = _chat("ref_match", prompt, provider_id, purpose=f"تطبیق {label}های خام با AI", ref=f"ref_{kind}")
    valid = {r["id"]: r for r in existing}
    out = []
    for r in (obj.get("items") if isinstance(obj, dict) else obj) or []:
        if not isinstance(r, dict) or r.get("raw") not in names:
            continue
        rid = r.get("id")
        rid = int(rid) if isinstance(rid, (int, float)) or str(rid or "").isdigit() else None
        if rid and rid in valid:
            out.append({"raw": r["raw"], "action": "link", "id": rid, "target": valid[rid]["name"], "reason": r.get("reason") or ""})
        elif r.get("skip"):
            out.append({"raw": r["raw"], "action": "skip", "reason": r.get("reason") or ""})
        else:
            name = str(r.get("name") or r["raw"]).strip()
            out.append({"raw": r["raw"], "action": "new", "name": name, "name_en": str(r.get("name_en") or "").strip(),
                        "slug": _clean_slug(r.get("slug"), r.get("name_en") or name), "reason": r.get("reason") or ""})
    return {"items": out}


def ref_generate(kind: str, prompt_text: str, parent_id: int | None = None, count: int = 15, provider_id=None) -> dict:
    """از یک توضیح، فهرست برند یا درخت دسته پیشنهاد بده (موارد موجود علامت می‌خورند)."""
    if not (prompt_text or "").strip():
        raise ValueError("توضیح بدهید چه فهرستی لازم است.")
    count = max(1, min(80, int(count or 15)))
    if kind == "brand":
        prompt = (f"برای فهرست مرجع برندهای مارکت‌پلیس خودرویی «مگا کارز» حداکثر {count} برند واقعی و معتبر پیشنهاد بده که در بازار ایران "
                  f"عرضه می‌شوند. درخواست کاربر: «{prompt_text.strip()}».\nبرای هر برند دسته‌های مرتبط را فقط از فهرست دسته‌های زیر بده.\n\n"
                  f"فهرست دسته‌ها (اسلاگ = مسیر):\n{_cat_lines() or '(خالی)'}\n\n"
                  'فقط JSON: {"items": [{"name": "نام فارسی", "name_en": "", "slug": "", "aliases": [], "country": "", "categories": ["اسلاگ دسته"]}]}')
    else:
        parent = refdata.get("category", parent_id) if parent_id else None
        prompt = (f"برای مارکت‌پلیس خودرویی «مگا کارز» یک درخت دسته‌بندی (حداکثر {count} گره، حداکثر ۳ سطح) پیشنهاد بده. درخواست کاربر: "
                  f"«{prompt_text.strip()}»." + (f" همه زیر دسته‌ی «{parent['name']}» ({parent['slug']}) قرار می‌گیرند." if parent else "")
                  + f"\nدسته‌های موجود (برای جلوگیری از تکرار):\n{_cat_lines() or '(خالی)'}\n\n"
                  'فقط JSON: {"items": [{"name": "نام فارسی", "name_en": "", "slug": "", "parent": "اسلاگ والد (از همین فهرست یا موجود) یا خالی", "aliases": []}]}')
    obj = _chat("ref_generate", prompt, provider_id, max_tokens=4000, temperature=0.5, purpose=f"پیشنهاد {refdata.LABELS[kind]} با AI", ref=f"ref_{kind}")
    out, seen = [], set()
    for r in (obj.get("items") if isinstance(obj, dict) else obj) or []:
        if not isinstance(r, dict) or not str(r.get("name") or "").strip():
            continue
        name = str(r["name"]).strip()
        slug = _clean_slug(r.get("slug"), r.get("name_en") or name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        exist = db.q1(f"SELECT id FROM {refdata.KINDS[kind]} WHERE slug=?", [slug]) or ({"id": refdata.resolve(kind, name)} if refdata.resolve(kind, name) else None)
        item = {"name": name, "name_en": str(r.get("name_en") or "").strip(), "slug": slug, "aliases": import_specs.split_list(r.get("aliases") or []),
                "exists": bool(exist), "existing_id": exist["id"] if exist else None}
        if kind == "brand":
            item["country"] = str(r.get("country") or "")
            item["category_ids"] = _cat_slugs(r.get("categories") or [])
            cats = refdata.category_index()
            item["categories_label"] = [cats[c]["path"] for c in item["category_ids"] if c in cats]
        else:
            item["parent"] = str(r.get("parent") or "").strip().lower() or (refdata.get("category", parent_id)["slug"] if parent_id else "")
        out.append(item)
    return {"items": out}


# ---------------------------------------------------------------------------
# الگوی خروجی کاتالوگ
# ---------------------------------------------------------------------------

def template_design(prompt_text: str, provider_id=None) -> dict:
    from . import product_catalog as pc
    from .services import list_schemas
    if not (prompt_text or "").strip():
        raise ValueError("توضیح بدهید خروجی چه ساختاری داشته باشد.")
    schemas = "\n".join(f"{s['id']} = {s['name']} ({s.get('usage') or 'general'}): " + ", ".join(c["key"] for c in s["columns"][:25]) for s in list_schemas())[:6000]
    prompt = ("یک «الگوی خروجی کاتالوگ» (درخت فایل) برای استودیو طراحی کن. درخواست کاربر: «" + prompt_text.strip() + "».\n"
              "قواعد:\n- kind یکی از products, brands, categories, vehicles, compatibility\n- format یکی از json, xlsx, csv\n"
              "- schema_id فقط برای kind=products و فقط از فهرست اسکیماهای زیر\n"
              "- path مسیر نسبی فایل؛ برای یک فایل JSON به‌ازای هر محصول از {slug} در مسیر استفاده کن (فقط products + json)\n"
              "- images.path باید {slug} و {name} و {ext} داشته باشد؛ نشانه‌های مجاز: {slug} {uid} {id} {name} {n} {ext} {brand_slug} {category_slug}\n"
              "- root نام پوشه‌ی هر انتشار با نشانه‌های {catalog} {release} {date}\n\n"
              f"اسکیماها (id = نام (کاربرد): ستون‌ها):\n{schemas}\n\n"
              'فقط JSON: {"name": "نام فارسی الگو", "description": "", "config": {"root": "{catalog}-r{release}", "zip": true, "manifest": true, '
              '"images": {"enabled": true, "path": "images/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}", "which": "all"}, '
              '"outputs": [{"name": "", "kind": "products", "format": "json", "schema_id": 1, "path": "data/products.json"}]}}')
    obj = _chat("template_design", prompt, provider_id, max_tokens=2500, purpose="طراحی الگوی خروجی با AI", ref="template")
    if not isinstance(obj, dict):
        raise ValueError("پاسخ هوش مصنوعی قابل خواندن نبود.")
    cfg = obj.get("config") if isinstance(obj.get("config"), dict) else obj
    valid_ids = {s["id"] for s in list_schemas()}
    for o in cfg.get("outputs") or []:
        if o.get("kind") == "products" and o.get("schema_id") not in valid_ids:
            o["schema_id"] = next(iter(valid_ids), None)
    cfg = pc.normalize_config(cfg)
    return {"name": str(obj.get("name") or "الگوی پیشنهادی AI"), "description": str(obj.get("description") or ""), "config": cfg,
            "tree": pc.preview_tree(cfg), "errors": pc.validate_config(cfg)}


# ---------------------------------------------------------------------------
# تکراری‌ها
# ---------------------------------------------------------------------------

def dupe_check(pair_id: int, provider_id=None) -> dict:
    from . import workbench
    pr = db.q1("SELECT * FROM dup_pairs WHERE id=?", [pair_id])
    if not pr:
        raise ValueError("جفت تکراری پیدا نشد.")

    def brief(pid):
        v = workbench.view(workbench.get_product(pid))
        vals = {k: (x if not isinstance(x, str) else x[:400]) for k, x in (v.get("v") or {}).items() if x not in (None, "", [], {})}
        return {"title": v["title"], "brand": (v.get("brand") or {}).get("name") or v.get("brand_raw"), "category": (v.get("category") or {}).get("name"),
                "values": dict(list(vals.items())[:14]), "sources": [s.get("url") for s in v.get("sources") or []][:2]}
    a, b = brief(pr["a_id"]), brief(pr["b_id"])
    prompt = ("آیا این دو رکورد محصول در واقع «یک محصول» هستند (همان کالا با همان برند، مدل، اندازه/حجم/نوع)؟ تفاوت در متن توضیح یا منبع "
              "مهم نیست؛ تفاوت در حجم، سایز، رنگ، ویسکوزیته یا مدل یعنی دو محصول جدا.\n\n"
              f"A: {json.dumps(a, ensure_ascii=False)}\n\nB: {json.dumps(b, ensure_ascii=False)}\n\n"
              'فقط JSON: {"same": true/false, "confidence": 0-100, "reason": "یک جمله‌ی فارسی", "keep": "a" یا "b" (کدام کامل‌تر است)}')
    obj = _chat("dupe_check", prompt, provider_id, max_tokens=500, temperature=0.1, purpose="داوری تکراری با AI", ref=f"dup:{pair_id}")
    same = bool(obj.get("same")) if isinstance(obj, dict) else False
    return {"pair_id": pair_id, "same": same, "confidence": int(obj.get("confidence") or 0) if isinstance(obj, dict) else 0,
            "reason": str(obj.get("reason") or "") if isinstance(obj, dict) else "", "keep": (obj.get("keep") if isinstance(obj, dict) else None) or "a",
            "a_id": pr["a_id"], "b_id": pr["b_id"]}


# ---------------------------------------------------------------------------
# نگاشت سرستون‌های فایل ورودی
# ---------------------------------------------------------------------------

def column_map(kind: str, headers: list[str], preview: list[dict] | None = None, provider_id=None) -> dict:
    spec = import_specs.SPECS.get(kind)
    if not spec:
        raise ValueError("بخش ورود نامعتبر است.")
    keys = "\n".join(f"{c['key']} = {c['header_fa']}: {c['desc']}" for c in spec["columns"])
    sample = json.dumps((preview or [])[:3], ensure_ascii=False)[:3000]
    prompt = (f"سرستون‌های یک فایل ورودی ({spec['title']}) را به فیلدهای استاندارد وصل کن. هر فیلد حداکثر به یک سرستون. سرستونی که به "
              f"هیچ فیلدی نمی‌خورد را با رشته‌ی خالی برگردان.\n\nفیلدهای استاندارد:\n{keys}\n\nسرستون‌ها: {json.dumps(headers, ensure_ascii=False)}\n"
              f"چند ردیف نمونه: {sample}\n\n" + 'فقط JSON: {"mapping": {"سرستون": "کلید فیلد یا خالی"}}')
    obj = _chat("column_map", prompt, provider_id, max_tokens=1200, temperature=0.1, purpose="نگاشت ستون‌های فایل با AI", ref=f"import:{kind}")
    m = obj.get("mapping") if isinstance(obj, dict) else {}
    valid = {c["key"] for c in spec["columns"]}
    out, used = {}, set()
    for h in headers:
        k = str((m or {}).get(h) or "")
        if k in valid and k not in used:
            out[h] = k
            used.add(k)
        else:
            out[h] = ""
    return {"mapping": out}
