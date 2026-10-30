"""قواعد متن: حذف، جایگزینی، افزودن عبارت و فیلتر ردیف مشخصات/تصویر — به‌صورت غیرمخرب هنگام خواندن داده اعمال می‌شود."""
from __future__ import annotations

import copy
import re
import threading

from . import db
from .textutil import normalize_fa

ACTIONS = {
    "remove": "حذف عبارت",
    "replace": "جایگزینی عبارت",
    "regex": "جایگزینی با الگو (Regex)",
    "drop_line": "حذف خط‌های شامل عبارت",
    "prepend": "افزودن به ابتدا",
    "append": "افزودن به انتها",
    "drop_spec": "حذف ردیف مشخصات",
    "drop_image": "حذف تصویر با آدرس شامل عبارت",
}

# فیلدهای متنی که هدف «همه» شامل آن‌ها می‌شود
TEXT_FIELDS = ["title", "title_en", "brand", "brand_en", "category", "short_description", "long_description", "specifications"]

SEED_RULES = [
    {"name": "حذف نام فروشگاه‌ها از متن", "target": "*", "action": "remove", "find": "دیجی‌کالا|دیجیکالا|اسنپ‌شاپ|اسنپ شاپ|تپسی گاراژ|اسنپ کارفیکس",
     "flags": {"split": "|"}, "enabled": 0},
    {"name": "حذف خط‌های مربوط به ارسال و قیمت", "target": "long_description", "action": "drop_line", "find": "ارسال رایگان|تخفیف ویژه|قیمت",
     "flags": {"split": "|"}, "enabled": 0},
    {"name": "حذف ردیف کد کالا از مشخصات", "target": "specifications", "action": "drop_spec", "find": "کد کالا|شناسه کالا|SKU",
     "flags": {"split": "|"}, "enabled": 0},
    {"name": "افزودن جمله‌ی پایانی به توضیح کوتاه", "target": "short_description", "action": "append",
     "value": "\\nخرید و نصب از کسب‌وکارهای معتبر در مگا کارز.", "find": "", "enabled": 0},
]

_cache: dict = {"version": -1, "rules": []}
_lock = threading.Lock()
_version = [0]


def bump():
    _version[0] += 1


def seed():
    if not db.val("SELECT COUNT(*) FROM text_rules"):
        for i, r in enumerate(SEED_RULES):
            db.ex("""INSERT INTO text_rules(name, enabled, source_id, target, action, find, value, flags, position, created_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  [r["name"], r.get("enabled", 0), None, r["target"], r["action"], r.get("find", ""), r.get("value", ""),
                   db.jdump(r.get("flags", {})), i, db.now()])


def all_rules() -> list[dict]:
    rows = db.q("SELECT r.*, s.name AS source_name FROM text_rules r LEFT JOIN sources s ON s.id=r.source_id ORDER BY position, id")
    for r in rows:
        r["flags"] = db.jload(r["flags"], {})
    return rows


def active_rules() -> list[dict]:
    with _lock:
        if _cache["version"] != _version[0]:
            _cache["rules"] = [r for r in all_rules() if r["enabled"]]
            _cache["version"] = _version[0]
        return _cache["rules"]


# ---------------------------------------------------------------------------

def _terms(rule: dict) -> list[str]:
    find = rule.get("find") or ""
    sep = (rule.get("flags") or {}).get("split", "|")
    parts = [p.strip() for p in find.split(sep)] if sep else [find]
    return [p for p in parts if p]


def _pattern(rule: dict) -> re.Pattern | None:
    flags = rule.get("flags") or {}
    rf = re.IGNORECASE if not flags.get("case_sensitive") else 0
    if rule["action"] == "regex":
        try:
            return re.compile(rule.get("find") or "", rf | re.MULTILINE)
        except re.error:
            return None
    terms = _terms(rule)
    if not terms:
        return None
    alt = "|".join(re.escape(normalize_fa(t)) for t in sorted(terms, key=len, reverse=True))
    if flags.get("whole_word"):
        alt = rf"(?<![\w؀-ۿ])(?:{alt})(?![\w؀-ۿ])"
    return re.compile(alt, rf)


def _tidy(s: str) -> str:
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" +([،,.:؛!؟?)])", r"\1", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(ln.strip(" -–|،,") if ln.strip(" -–|،,") != "" else "" for ln in s.split("\n")).strip()


def apply_to_text(s: str, rule: dict) -> str:
    if not isinstance(s, str) or not s:
        return s
    a = rule["action"]
    if a == "prepend":
        v = (rule.get("value") or "").replace("\\n", "\n")
        return s if not v or s.startswith(v) else f"{v}{s}"
    if a == "append":
        v = (rule.get("value") or "").replace("\\n", "\n")
        return s if not v or s.endswith(v) else f"{s}{v}"
    pat = _pattern(rule)
    if not pat:
        return s
    src = normalize_fa(s)
    if a == "remove":
        return _tidy(pat.sub("", src))
    if a in ("replace", "regex"):
        return _tidy(pat.sub((rule.get("value") or "").replace("\\n", "\n"), src))
    if a == "drop_line":
        return _tidy("\n".join(ln for ln in src.split("\n") if not pat.search(ln)))
    return s


def _applies(rule: dict, field: str, source_id, all_fields: bool = False) -> bool:
    if rule.get("source_id") and source_id and int(rule["source_id"]) != int(source_id):
        return False
    t = rule.get("target") or "*"
    if t == "*":
        return (all_fields or field in TEXT_FIELDS) and rule["action"] not in ("prepend", "append")
    return t == field


def apply_value(value, field: str, source_id=None, rules: list | None = None, all_fields: bool = False):
    """اعمال قواعد روی مقدار یک فیلد (متن، فهرست، مشخصات، تصاویر، شیء)."""
    rules = active_rules() if rules is None else rules
    for r in rules:
        if not _applies(r, field, source_id, all_fields):
            continue
        a = r["action"]
        if a == "drop_spec":
            if isinstance(value, list):
                pat = _pattern({**r, "action": "remove"})
                if pat:
                    value = [s for s in value if not (isinstance(s, dict) and (pat.search(normalize_fa(str(s.get("name", "")))) or pat.search(normalize_fa(str(s.get("value", "")))) ))]
            continue
        if a == "drop_image":
            terms = _terms(r)
            if isinstance(value, list):
                value = [u for u in value if not any(t.lower() in str(u).lower() for t in terms)]
            elif isinstance(value, str) and any(t.lower() in value.lower() for t in terms):
                value = ""
            continue
        value = _apply_any(value, r)
    return value


def _apply_any(value, rule):
    if isinstance(value, str):
        return apply_to_text(value, rule)
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, dict) and "name" in v and "value" in v:
                if rule["action"] in ("prepend", "append"):
                    out.append(v)
                    continue
                nv = dict(v)
                nv["value"] = apply_to_text(str(v.get("value", "")), rule)
                if nv["value"]:
                    out.append(nv)
            elif isinstance(v, str):
                if rule["action"] in ("prepend", "append"):
                    out.append(v)
                    continue
                t = apply_to_text(v, rule)
                if t:
                    out.append(t)
            else:
                out.append(v)
        return out
    if isinstance(value, dict):
        return {k: (_apply_any(v, rule) if isinstance(v, (str, list)) and rule["action"] not in ("prepend", "append") else v)
                for k, v in value.items()}
    return value


def clean_data(data: dict, source_id=None) -> dict:
    rules = active_rules()
    if not rules:
        return data
    out = copy.deepcopy(data)
    fields = set(TEXT_FIELDS) | {r["target"] for r in rules if r["target"] != "*"} | {"featured_image", "gallery"}
    for f in fields:
        if f in out and out[f] not in (None, "", [], {}):
            out[f] = apply_value(out[f], f, source_id, rules)
    if out.get("featured_image") == "" and out.get("gallery"):
        out["featured_image"] = out["gallery"][0]
        out["gallery"] = out["gallery"][1:]
    return out


def cleaned(item: dict) -> dict:
    """داده‌ی پاک‌سازی‌شده‌ی یک آیتم (با کش روی خود دیکشنری آیتم)."""
    if "_clean" not in item:
        item["_clean"] = clean_data(item.get("data") or {}, item.get("source_id"))
    return item["_clean"]


def test(text: str, rule: dict | None = None, target: str = "long_description", source_id=None) -> dict:
    if rule:
        r = {**rule, "flags": rule.get("flags") or {}, "enabled": 1, "target": rule.get("target") or target}
        rules = [r]
    else:
        rules = active_rules()
    return {"output": apply_value(text, target, source_id, rules)}
