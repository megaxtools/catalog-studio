"""ابزارهای متن: تاریخ جلالی، اعداد، اسلاگ انگلیسی و پاک‌سازی متن."""
from __future__ import annotations

import html as _html
import re
import unicodedata
from datetime import datetime, timedelta, timezone

TEHRAN = timezone(timedelta(hours=3, minutes=30))

# ---------------- تاریخ جلالی ----------------

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                 "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def tehran_now() -> datetime:
    return datetime.now(TEHRAN)


def jalali_stamp(dt: datetime | None = None) -> str:
    """مثل 1405-08-05_1843"""
    dt = dt or tehran_now()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}-{jm:02d}-{jd:02d}_{dt.hour:02d}{dt.minute:02d}"


def jalali_human(dt: datetime | None = None) -> str:
    dt = dt or tehran_now()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return to_fa_digits(f"{jd} {JALALI_MONTHS[jm - 1]} {jy}، {dt.hour:02d}:{dt.minute:02d}")


# ---------------- ارقام و نویسه‌ها ----------------

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_LATIN = {ord(c): str(i) for i, c in enumerate(FA_DIGITS)} | {ord(c): str(i) for i, c in enumerate(AR_DIGITS)}
_TO_FA = {ord(str(i)): c for i, c in enumerate(FA_DIGITS)}


def to_latin_digits(s: str) -> str:
    return s.translate(_TO_LATIN) if isinstance(s, str) else s


def to_fa_digits(s: str) -> str:
    return str(s).translate(_TO_FA)


def normalize_fa(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = s.replace("ي", "ی").replace("ك", "ک").replace("ى", "ی").replace("ۀ", "ه")
    s = s.replace("‏", "").replace("‎", "").replace("\xa0", " ")
    return s


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|table|section|article)[^>]*>", re.I)


def html_to_text(s: str) -> str:
    if not isinstance(s, str):
        return s
    if "<" in s and ">" in s:
        s = _BLOCK_RE.sub("\n", s)
        s = _TAG_RE.sub("", s)
    s = _html.unescape(s)
    return clean_text(s)


def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = normalize_fa(s)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def parse_number(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = to_latin_digits(str(s)).replace("٫", ".").replace(",", "").replace("،", "")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


# ---------------- اسلاگ انگلیسی ----------------

BASE_DICTIONARY: dict[str, str] = {
    # عمومی خودرو و مصرفی
    "روغن": "oil", "موتور": "engine", "خودرو": "car", "ماشین": "car", "ضدیخ": "antifreeze",
    "روانکار": "lubricant", "ضد": "anti", "یخ": "freeze", "جوش": "boil", "ضدجوش": "coolant", "فیلتر": "filter", "هوا": "air",
    "کابین": "cabin", "بنزین": "fuel", "سوخت": "fuel", "لیتر": "l", "لیتری": "l", "میلی": "milli",
    "میلی‌لیتر": "ml", "میلی‌لیتری": "ml", "سی‌سی": "cc", "گرم": "g", "گرمی": "g", "کیلوگرم": "kg", "کیلو": "kg",
    "عدد": "pcs", "عددی": "pcs", "بسته": "pack", "پک": "pack", "مدل": "", "حجم": "", "کد": "",
    "بنزینی": "gasoline", "دیزلی": "diesel", "گازوئیلی": "diesel", "گیربکس": "gearbox", "دنده": "gear",
    "ترمز": "brake", "لنت": "brake-pad", "باتری": "battery", "لاستیک": "tire", "تایر": "tire",
    "واکس": "wax", "شامپو": "shampoo", "پولیش": "polish", "مکمل": "additive", "اسپری": "spray",
    "تمیزکننده": "cleaner", "پاک‌کننده": "cleaner", "شیشه": "glass", "شوی": "wash", "شوینده": "detergent",
    "آب": "water", "رادیاتور": "radiator", "هیدرولیک": "hydraulic", "فرمان": "steering", "فرمانی": "steering",
    "سینتتیک": "synthetic", "تمام": "full", "نیمه": "semi", "معدنی": "mineral", "پایه": "base",
    "شمع": "spark-plug", "تسمه": "belt", "تایم": "timing", "دینام": "alternator", "استارت": "starter",
    "چراغ": "lamp", "لامپ": "bulb", "جلو": "front", "عقب": "rear", "کمک": "shock", "فنر": "spring",
    "سیلندر": "cylinder", "پمپ": "pump", "واشر": "gasket", "کاسه": "cup", "نمد": "seal", "کیت": "kit",
    "داشبورد": "dashboard", "لاستیک‌ها": "tires", "رینگ": "rim", "صندلی": "seat", "روکش": "cover",
    "خوشبوکننده": "air-freshener", "معطر": "scented", "نانو": "nano", "سرامیک": "ceramic", "گریس": "grease",
    "ضدزنگ": "anti-rust", "زنگ": "rust", "پاک": "clean", "کننده": "", "و": "", "با": "with", "برای": "for",
    "مخصوص": "for", "سری": "series", "نوع": "", "رنگ": "color", "سفید": "white", "مشکی": "black",
    "قرمز": "red", "آبی": "blue", "سبز": "green", "زرد": "yellow", "طلایی": "gold", "نقره‌ای": "silver",
    "دستمال": "towel", "میکروفایبر": "microfiber", "اسفنج": "sponge", "برس": "brush", "کارواش": "carwash",
    "پراید": "pride", "پژو": "peugeot", "سمند": "samand", "دنا": "dena", "تیبا": "tiba", "ساینا": "saina",
    "شاهین": "shahin", "رانا": "rana", "کوییک": "quick", "ال۹۰": "l90", "تندر": "tondar",
    # برندهای رایج
    "کاسپین": "caspian", "بهران": "behran", "ایرانول": "iranol", "سپاهان": "sepahan", "پارس": "pars",
    "توتال": "total", "شل": "shell", "موبیل": "mobil", "کاسترول": "castrol", "الف": "elf",
    "لیکومولی": "liqui-moly", "اسپیدی": "speedy", "آیسین": "aisin", "بوش": "bosch", "مان": "mann",
    "سرکان": "serkan", "اکسل": "excel", "هپکو": "hepco", "پاکشوما": "pakshoma", "واروش": "varush",
    "پرشین": "persian", "پروتون": "proton", "زاگرس": "zagros", "نفت": "naft", "ابر": "abr",
    "گلاید": "glide", "پراید‌": "pride", "آلبرت": "albert", "فوکس": "fuchs", "پترونول": "petronol",
    "کیمیا": "kimia", "آریا": "aria", "رونیکس": "ronix", "سونکس": "sonax", "تورتل": "turtle",
    "اسپری‌": "spray", "واکسی": "wax", "مگا": "mega", "پلاس": "plus", "پرو": "pro", "سوپر": "super",
    "ویژه": "special", "اکسترا": "extra", "اولترا": "ultra", "ماکس": "max",
    "آماده": "ready", "مصرف": "use", "به": "", "کولانت": "coolant", "اصلی": "original", "اورجینال": "original",
    "پیشرفته": "advanced", "مکانیکی": "mechanical", "گالن": "gallon", "بطری": "bottle", "قوطی": "can",
    "مایع": "fluid", "ژل": "gel", "کرم": "cream", "خمیر": "paste", "دودزا": "smoke", "تقویت": "booster",
    "تقویت‌کننده": "booster", "نشت": "leak", "گیر": "stop", "انژکتور": "injector", "سوپاپ": "valve",
}

_TRANSLIT = {
    "ا": "a", "آ": "a", "أ": "a", "إ": "e", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "ch",
    "ح": "h", "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh",
    "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "gh", "ک": "k",
    "گ": "g", "ل": "l", "م": "m", "ن": "n", "و": "o", "ه": "h", "ی": "i", "ئ": "y", "ء": "",
    "ة": "h", "ؤ": "o",
}


def _translit_word(w: str) -> str:
    out = []
    for i, ch in enumerate(w):
        t = _TRANSLIT.get(ch)
        if t is None:
            out.append(ch)
            continue
        # «و» و «ی» در ابتدای کلمه صامت‌اند
        if ch == "و" and i == 0:
            t = "v"
        if ch == "ی" and i == 0:
            t = "y"
        if ch == "ا" and i > 0:
            t = "a"
        out.append(t)
    return "".join(out)


def slugify(text: str, dictionary: dict | None = None, max_len: int = 90) -> str:
    """تبدیل عنوان (فارسی یا انگلیسی) به اسلاگ انگلیسی."""
    if not text:
        return ""
    d = dict(BASE_DICTIONARY)
    if dictionary:
        d.update({normalize_fa(k): v for k, v in dictionary.items()})
    s = normalize_fa(to_latin_digits(str(text)))
    s = re.sub("روان[\\s\\-‌]?کار", "روانکار", s)
    s = re.sub("ضد[\\s\\-‌]?یخ", "ضدیخ", s)
    s = re.sub("ضد[\\s\\-‌]?جوش", "ضدجوش", s)
    s = s.replace("/", " ").replace("_", " ")
    tokens = re.findall(r"[A-Za-z0-9.+\-]+|[؀-ۿ‌]+", s)
    parts: list[str] = []
    for tok in tokens:
        if re.match(r"[A-Za-z0-9]", tok):
            parts.append(tok.lower())
            continue
        key = tok
        if key in d:
            if d[key]:
                parts.append(d[key])
            continue
        flat = key.replace("‌", "")
        if flat in d:
            if d[flat]:
                parts.append(d[flat])
            continue
        # تلاش برای جداکردن پسوندهای رایج
        for suf in ("‌های", "‌ها", "های", "ها", "ی"):
            if flat.endswith(suf.replace("‌", "")) and flat[: -len(suf.replace("‌", ""))] in d:
                base = d[flat[: -len(suf.replace("‌", ""))]]
                if base:
                    parts.append(base)
                break
        else:
            for sub in key.split("‌"):
                if sub in d:
                    if d[sub]:
                        parts.append(d[sub])
                elif sub:
                    parts.append(_translit_word(sub))
    slug = "-".join(parts)
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
    slug = slug.lower().replace(".", "-").replace("+", "-plus")
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug


def is_latin(s: str) -> bool:
    if not s:
        return False
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isascii()) / len(letters) > 0.8


def safe_filename(name: str, max_len: int = 120) -> str:
    name = normalize_fa(str(name)).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:max_len].rstrip(" .")) or "item"
