"""قالب ورود فایل در همه‌ی بخش‌ها: مشخصات ستون‌ها، فایل نمونه (Excel/CSV/JSON) و خواندن فایل بارگذاری‌شده.

هر بخش (برندها، دسته‌بندی‌ها، خودروها، داده‌ی خام) یک «مشخصات ورود» دارد: ستون‌ها با نام انگلیسی (کلید)، نام فارسی
قابل‌قبول در سرستون، اجباری/اختیاری، توضیح و مثال. رابط کاربری از همین مشخصات راهنمای ورود را نشان می‌دهد و فایل
نمونه همیشه با همین ستون‌ها ساخته می‌شود؛ پس راهنما و نمونه و خواندن فایل هیچ‌وقت از هم جدا نمی‌شوند.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re

FORMATS = {"xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
           "csv": ("text/csv; charset=utf-8", "csv"), "json": ("application/json; charset=utf-8", "json")}

LIST_SEP = "جدا با ویرگول یا «|»"


def _c(key, fa, desc, example, required=False, aliases=(), kind="text"):
    return {"key": key, "header_fa": fa, "desc": desc, "example": example, "required": required, "aliases": list(aliases), "kind": kind}


SPECS: dict[str, dict] = {
    "brand": {
        "title": "برندها", "file": "brands-sample",
        "intro": "هر ردیف یک برند. اگر برندی با همین اسلاگ (یا همین نام) از قبل باشد، به‌روز می‌شود؛ وگرنه افزوده می‌شود.",
        "columns": [
            _c("name", "نام", "نام فارسی برند", "کاسپین", True, ("title", "brand", "برند")),
            _c("name_en", "نام انگلیسی", "نام لاتین برند", "Caspian", aliases=("english", "brand_en")),
            _c("slug", "اسلاگ", "شناسه‌ی انگلیسی یکتا (حروف کوچک، عدد، خط تیره)؛ اگر خالی باشد از نام انگلیسی ساخته می‌شود", "caspian"),
            _c("categories", "دسته‌بندی‌ها", f"اسلاگ یا نام دسته‌هایی که این برند در آن‌ها نمایش داده می‌شود؛ {LIST_SEP}", "engine-oil|gear-oil",
               aliases=("category", "دسته", "دسته‌بندی", "category_slugs"), kind="list"),
            _c("aliases", "نام‌های دیگر", f"املاهای دیگر برند در داده‌ی خام (برای تطبیق خودکار)؛ {LIST_SEP}", "کاسپین ایران|Caspian Oil", kind="list"),
            _c("country", "کشور", "کشور سازنده (اختیاری)", "ایران"),
            _c("description", "توضیح", "توضیح کوتاه برند برای نمایش", "تولیدکننده‌ی روغن موتور و روانکار"),
            _c("notes", "یادداشت", "یادداشت داخلی", ""),
            _c("active", "فعال", "1 یا 0 (پیش‌فرض 1)", "1", kind="bool"),
        ],
        "examples": [
            {"name": "کاسپین", "name_en": "Caspian", "slug": "caspian", "categories": "engine-oil|gear-oil", "aliases": "کاسپین ایران|Caspian Oil",
             "country": "ایران", "description": "تولیدکننده‌ی روغن موتور و روانکار", "notes": "", "active": 1},
            {"name": "بوش", "name_en": "Bosch", "slug": "bosch", "categories": "wiper-blade|spark-plug", "aliases": "BOSCH|بوشی",
             "country": "آلمان", "description": "", "notes": "", "active": 1},
        ],
    },
    "category": {
        "title": "دسته‌بندی‌ها", "file": "categories-sample",
        "intro": "هر ردیف یک دسته. ستون parent اسلاگ یا نام دسته‌ی والد است و برای دسته‌های ریشه خالی می‌ماند؛ ترتیب ردیف‌ها مهم نیست.",
        "columns": [
            _c("name", "نام", "نام فارسی دسته", "روغن موتور", True, ("title", "category", "دسته")),
            _c("name_en", "نام انگلیسی", "نام لاتین دسته", "Engine Oil", aliases=("english",)),
            _c("slug", "اسلاگ", "شناسه‌ی انگلیسی یکتا؛ اگر خالی باشد از نام انگلیسی ساخته می‌شود", "engine-oil"),
            _c("parent", "والد", "اسلاگ یا نام دسته‌ی والد (برای ریشه خالی)", "oils-fluids", aliases=("parent_slug", "دسته والد", "دسته‌ی والد")),
            _c("sort", "ترتیب", "عدد ترتیب نمایش میان هم‌سطح‌ها", "1", kind="number"),
            _c("aliases", "نام‌های دیگر", f"نام‌های دیگر این دسته در داده‌ی خام؛ {LIST_SEP}", "روغن|روغن خودرو", kind="list"),
            _c("description", "توضیح", "توضیح کوتاه دسته", ""),
            _c("notes", "یادداشت", "یادداشت داخلی", ""),
            _c("active", "فعال", "1 یا 0 (پیش‌فرض 1)", "1", kind="bool"),
        ],
        "examples": [
            {"name": "روغن و مایعات", "name_en": "Oils & Fluids", "slug": "oils-fluids", "parent": "", "sort": 1, "aliases": "", "description": "", "notes": "", "active": 1},
            {"name": "روغن موتور", "name_en": "Engine Oil", "slug": "engine-oil", "parent": "oils-fluids", "sort": 1, "aliases": "روغن|روغن خودرو",
             "description": "", "notes": "", "active": 1},
            {"name": "روغن گیربکس", "name_en": "Gear Oil", "slug": "gear-oil", "parent": "oils-fluids", "sort": 2, "aliases": "واسکازین",
             "description": "", "notes": "", "active": 1},
        ],
    },
    "vehicles": {
        "title": "بانک خودروها", "file": "vehicles-sample",
        "intro": "هر ردیف یک تیپ (یا یک مدل بدون تیپ). برند و مدل تکراری فقط یک بار ساخته می‌شوند. نام و اسلاگ انگلیسی اختیاری‌اند؛ "
                 "اگر خالی باشند خودکار ساخته و برای بازبینی علامت می‌خورند.",
        "columns": [
            _c("brand", "برند", "نام فارسی برند خودرو", "پژو", True, ("برند خودرو",)),
            _c("model", "مدل", "نام فارسی مدل", "206", aliases=("مدل خودرو",)),
            _c("type", "تیپ", "نام فارسی تیپ (اختیاری)", "تیپ 2", aliases=("trim", "تیپ خودرو")),
            _c("brand_en", "نام انگلیسی برند", "", "Peugeot"),
            _c("brand_slug", "اسلاگ برند", "", "peugeot"),
            _c("model_en", "نام انگلیسی مدل", "", "206"),
            _c("model_slug", "اسلاگ مدل", "", "206"),
            _c("type_en", "نام انگلیسی تیپ", "", "Type 2", aliases=("trim_en",)),
            _c("type_slug", "اسلاگ تیپ", "", "type-2", aliases=("trim_slug",)),
        ],
        "examples": [
            {"brand": "پژو", "model": "206", "type": "تیپ 2", "brand_en": "Peugeot", "brand_slug": "peugeot", "model_en": "206", "model_slug": "206",
             "type_en": "Type 2", "type_slug": "type-2"},
            {"brand": "پژو", "model": "206", "type": "تیپ 5", "brand_en": "Peugeot", "brand_slug": "peugeot", "model_en": "206", "model_slug": "206",
             "type_en": "Type 5", "type_slug": "type-5"},
            {"brand": "ایران خودرو", "model": "سمند", "type": "", "brand_en": "", "brand_slug": "", "model_en": "", "model_slug": "", "type_en": "", "type_slug": ""},
        ],
    },
    "raw": {
        "title": "داده‌ی خام محصولات", "file": "raw-products-sample",
        "intro": "هر ردیف یک محصول. فقط «عنوان» اجباری است. ستون‌های دیگر هر نامی داشته باشند در داده‌ی خام نگه داشته می‌شوند و "
                 "می‌توانید پیش از ورود آن‌ها را به فیلدهای استاندارد وصل کنید. تصاویر با نشانی اینترنتی وارد می‌شوند و هنگام ساخت "
                 "بانک تمیز دانلود می‌شوند.",
        "columns": [
            _c("title", "عنوان", "عنوان کامل فارسی محصول", "روغن موتور کاسپین 20W-50 حجم 4 لیتر", True, ("name", "نام", "نام محصول", "عنوان محصول")),
            _c("title_en", "عنوان انگلیسی", "", "Caspian 20W-50 Engine Oil 4L"),
            _c("brand", "برند", "نام برند (با فهرست مرجع تطبیق داده می‌شود)", "کاسپین"),
            _c("brand_en", "برند انگلیسی", "", "Caspian"),
            _c("category", "دسته‌بندی", "نام یا اسلاگ دسته (با فهرست مرجع تطبیق داده می‌شود)", "روغن موتور", aliases=("دسته",)),
            _c("short_description", "توضیح کوتاه", "", "روغن موتور مناسب خودروهای بنزینی", aliases=("summary", "خلاصه")),
            _c("long_description", "توضیح بلند", "", "", aliases=("description", "توضیحات", "توضیح")),
            _c("specifications", "مشخصات", "هر خط «گروه | نام | مقدار» یا «نام: مقدار»؛ یا آرایه‌ی JSON از {group, name, value}",
               "مشخصات کلی | حجم | 4 لیتر\nمشخصات کلی | ویسکوزیته | 20W-50", aliases=("specs", "مشخصات فنی"), kind="specs"),
            _c("featured_image", "تصویر شاخص", "نشانی اینترنتی تصویر اصلی", "https://example.com/caspian-1.jpg", aliases=("image", "تصویر", "image_url")),
            _c("gallery", "تصاویر گالری", f"نشانی تصاویر دیگر؛ {LIST_SEP} یا هر خط یکی", "https://example.com/caspian-2.jpg|https://example.com/caspian-3.jpg",
               aliases=("images", "گالری", "تصاویر"), kind="list"),
            _c("sku", "کد کالا", "", "CSP-2050-4"),
            _c("source_url", "لینک منبع", "نشانی صفحه‌ی محصول (اگر دارد)", "", aliases=("url", "link", "لینک")),
            _c("compatible_vehicles", "خودروهای سازگار", "متن آزاد سازگاری (مثلاً «پژو 206، پراید»)؛ هنگام ساخت بانک تمیز به بانک خودروها تطبیق داده می‌شود",
               "پژو 206|سمند", aliases=("سازگاری", "compat", "vehicles")),
        ],
        "examples": [
            {"title": "روغن موتور کاسپین 20W-50 حجم 4 لیتر", "title_en": "Caspian 20W-50 Engine Oil 4L", "brand": "کاسپین", "brand_en": "Caspian",
             "category": "روغن موتور", "short_description": "روغن موتور مناسب خودروهای بنزینی", "long_description": "",
             "specifications": "مشخصات کلی | حجم | 4 لیتر\nمشخصات کلی | ویسکوزیته | 20W-50",
             "featured_image": "https://example.com/caspian-1.jpg", "gallery": "https://example.com/caspian-2.jpg", "sku": "CSP-2050-4",
             "source_url": "", "compatible_vehicles": "پژو 206|سمند"},
            {"title": "تیغه برف پاک کن بوش 60 سانتی", "title_en": "Bosch Wiper Blade 60cm", "brand": "بوش", "brand_en": "Bosch",
             "category": "تیغه برف پاک کن", "short_description": "", "long_description": "", "specifications": "طول: 60 سانتی‌متر",
             "featured_image": "https://example.com/bosch-60.jpg", "gallery": "", "sku": "", "source_url": "", "compatible_vehicles": ""},
        ],
    },
}


def spec(kind: str) -> dict:
    if kind not in SPECS:
        raise ValueError("بخش ورود نامعتبر است.")
    s = SPECS[kind]
    return {"kind": kind, **{k: v for k, v in s.items() if k != "examples"}, "examples": s["examples"],
            "formats": list(FORMATS), "accept": ".xlsx,.csv,.json"}


def all_specs() -> dict:
    return {k: spec(k) for k in SPECS}


def _cell(v):
    return v if isinstance(v, (int, float)) else ("" if v is None else str(v))


def write_table(rows: list[dict], heads: list[str], fmt: str, sheet: str = "data", header_fa: dict | None = None) -> bytes:
    """ردیف‌ها → فایل xlsx/csv/json. در Excel یک ردیف دوم راهنما (نام فارسی) نمی‌گذاریم تا فایل مستقیم قابل ورود باشد."""
    if fmt == "json":
        return json.dumps([{h: r.get(h, "") for h in heads} for r in rows], ensure_ascii=False, indent=2).encode("utf-8")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(heads)
        for r in rows:
            w.writerow([_cell(r.get(h)) for h in heads])
        return ("﻿" + buf.getvalue()).encode("utf-8")
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:30]
    ws.sheet_view.rightToLeft = True
    ws.append(heads)
    for i, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4F39F6")
        if header_fa and header_fa.get(h):
            c.comment = Comment(header_fa[h], "Mega Catalog Studio")
        ws.column_dimensions[c.column_letter].width = max(14, min(48, len(h) + 8))
    for r in rows:
        ws.append([_cell(r.get(h)) for h in heads])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sample(kind: str, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    s = SPECS.get(kind)
    if not s:
        raise ValueError("بخش ورود نامعتبر است.")
    if fmt not in FORMATS:
        raise ValueError("قالب فایل نامعتبر است.")
    heads = [c["key"] for c in s["columns"]]
    fa = {c["key"]: f"{c['header_fa']}{' (اجباری)' if c['required'] else ''}: {c['desc']}" for c in s["columns"]}
    rows = s["examples"]
    if fmt == "json":
        rows = [_jsonish(kind, r) for r in rows]
    data = write_table(rows, heads, fmt, sheet=kind, header_fa=fa)
    if fmt == "xlsx":
        data = _add_guide_sheet(data, s)
    return data, FORMATS[fmt][0], f"{s['file']}.{FORMATS[fmt][1]}"


def _jsonish(kind: str, r: dict) -> dict:
    """در نمونه‌ی JSON، ستون‌های فهرستی به‌صورت آرایه نشان داده می‌شوند."""
    out = dict(r)
    for c in SPECS[kind]["columns"]:
        v = out.get(c["key"])
        if c["kind"] == "list" and isinstance(v, str):
            out[c["key"]] = split_list(v)
        if c["kind"] == "specs" and isinstance(v, str):
            out[c["key"]] = parse_specs(v)
    return out


def _add_guide_sheet(data: bytes, s: dict) -> bytes:
    from openpyxl import load_workbook
    from openpyxl.styles import Font
    wb = load_workbook(io.BytesIO(data))
    ws = wb.create_sheet("راهنما")
    ws.sheet_view.rightToLeft = True
    ws.append([s["title"]])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([s["intro"]])
    ws.append([])
    ws.append(["ستون (سرستون انگلیسی)", "نام فارسی قابل‌قبول", "اجباری", "توضیح", "مثال"])
    for c in ws[4]:
        c.font = Font(bold=True)
    for col in s["columns"]:
        ws.append([col["key"], col["header_fa"], "بله" if col["required"] else "", col["desc"], str(col["example"])])
    for letter, w in zip("ABCDE", (24, 22, 8, 70, 40)):
        ws.column_dimensions[letter].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# خواندن فایل
# ---------------------------------------------------------------------------

def decode(data_url: str) -> bytes:
    return base64.b64decode(data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url)


def read_table(raw: bytes, name: str) -> tuple[list[str], list[dict]]:
    """فایل xlsx/csv/json → (سرستون‌ها، ردیف‌ها با سرستون اصلی). فقط شیت اول Excel خوانده می‌شود."""
    low = (name or "").lower()
    if low.endswith(".json"):
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        rows = [r for r in data if isinstance(r, dict)]
        heads: list[str] = []
        for r in rows:
            for k in r:
                if k not in heads:
                    heads.append(k)
        return heads, rows
    if low.endswith(".csv") or low.endswith(".txt"):
        text = raw.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rd = csv.reader(io.StringIO(text), dialect)
        allrows = [r for r in rd]
    else:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        allrows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    allrows = [r for r in allrows if any(x not in (None, "") for x in r)]
    if not allrows:
        return [], []
    heads = [str(h or "").strip() or f"col{i + 1}" for i, h in enumerate(allrows[0])]
    rows = [{heads[i]: (v if v is not None else "") for i, v in enumerate(r) if i < len(heads)} for r in allrows[1:]]
    return heads, rows


def _hnorm(s: str) -> str:
    s = str(s or "").strip().lower().replace("‌", " ").replace("ي", "ی").replace("ك", "ک")
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[\s_\-]+", " ", s).strip()


def auto_mapping(kind: str, heads: list[str]) -> dict[str, str]:
    """سرستون فایل → کلید استاندارد (با نام انگلیسی، فارسی یا نام‌های دیگر). سرستون ناشناخته به «» نگاشت می‌شود."""
    idx: dict[str, str] = {}
    for c in SPECS[kind]["columns"]:
        for n in [c["key"], c["header_fa"], *c["aliases"]]:
            idx.setdefault(_hnorm(n), c["key"])
    out, used = {}, set()
    for h in heads:
        k = idx.get(_hnorm(h), "")
        if k and k in used:
            k = ""
        out[h] = k
        if k:
            used.add(k)
    return out


def apply_mapping(rows: list[dict], mapping: dict[str, str], keep_extra: bool = False) -> list[dict]:
    out = []
    for r in rows:
        o = {}
        extra = {}
        for h, v in r.items():
            k = mapping.get(h)
            if k:
                o[k] = v
            elif keep_extra and v not in ("", None):
                extra[h] = v
        if keep_extra and extra:
            o["_extra"] = extra
        out.append(o)
    return out


def parse(kind: str, data_url: str, name: str, mapping: dict | None = None) -> list[dict]:
    """فایل بارگذاری‌شده → ردیف‌ها با کلیدهای استاندارد همان بخش."""
    heads, rows = read_table(decode(data_url), name)
    m = auto_mapping(kind, heads)
    if mapping:
        m.update({h: k for h, k in mapping.items() if h in m})
    return apply_mapping(rows, m, keep_extra=(kind == "raw"))


def analyze(kind: str, data_url: str, name: str) -> dict:
    """پیش از ورود: سرستون‌ها، نگاشت پیشنهادی، چند ردیف نمونه و کمبود ستون‌های اجباری."""
    heads, rows = read_table(decode(data_url), name)
    m = auto_mapping(kind, heads)
    req = [c["key"] for c in SPECS[kind]["columns"] if c["required"]]
    missing = [k for k in req if k not in m.values()]
    preview = [{h: (str(v)[:120] if v is not None else "") for h, v in r.items()} for r in rows[:5]]
    return {"headers": heads, "mapping": m, "rows": len(rows), "preview": preview, "missing_required": missing,
            "unmapped": [h for h, k in m.items() if not k]}


# ---------------------------------------------------------------------------
# کمک‌تابع‌های مقدار
# ---------------------------------------------------------------------------

def split_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[\n|,،;؛]+", str(v or "")) if x.strip()]


def split_urls(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[\s|,،;]+", str(v or "")) if x.strip().startswith(("http://", "https://", "data:", "/"))]


def parse_specs(v) -> list[dict]:
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict) and (x.get("name") or x.get("value")):
                out.append({"group": str(x.get("group") or "مشخصات کلی"), "name": str(x.get("name") or ""), "value": str(x.get("value") or "")})
        return out
    s = str(v or "").strip()
    if s.startswith("["):
        try:
            return parse_specs(json.loads(s))
        except ValueError:
            pass
    out = []
    for line in re.split(r"[\n;؛]+", s):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            out.append({"group": parts[0] or "مشخصات کلی", "name": parts[1], "value": " | ".join(parts[2:])})
        elif len(parts) == 2:
            out.append({"group": "مشخصات کلی", "name": parts[0], "value": parts[1]})
        elif ":" in line or "：" in line:
            k, _, val = line.replace("：", ":").partition(":")
            out.append({"group": "مشخصات کلی", "name": k.strip(), "value": val.strip()})
    return out


def truthy(v, default=True) -> bool:
    if v in (None, ""):
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "خیر", "نه", "غیرفعال")
