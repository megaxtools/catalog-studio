"""ماژول «کنترل کیفیت»: امتیاز کامل بودن هر محصول تمیز و دروازه‌ی ورود به کاتالوگ.

خطاها (مانع تأیید و ورود به کاتالوگ): ستون اجباری خالی، عنوان نامعتبر، اسلاگ نامعتبر، نبودن برند یا دسته، نبودن تصویر شاخص.
هشدارها (از امتیاز کم می‌کنند): متن بلند کوتاه، عنوان خیلی بلند، تصویر کم‌کیفیت، واژه‌های ممنوع (شعبه، قیمت…)،
پیشنهاد خودکار سازگاری که تأیید نشده است.
"""
from __future__ import annotations

import re

from ... import db
from ...web import pid, route
from .. import Module

MODULE = Module(
    id="quality", name="کنترل کیفیت", version="1.0.0",
    description="امتیاز کامل بودن هر محصول (فیلدهای اجباری، متن، تصویر، سازگاری) و حداقل امتیاز برای تأیید و ورود به کاتالوگ.",
)
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple)):
        return all(_empty(x) for x in v)
    if isinstance(v, dict):
        return all(_empty(x) for x in v.values())
    return False


def _texts(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for y in v for x in _texts(y)]
    if isinstance(v, dict):
        return [x for y in v.values() for x in _texts(y)]
    return []


def score(p: dict) -> dict:
    from ... import workbench
    cfg = {"min_score": 70, "min_image_px": 800, "min_long_chars": 150, "title_min": 10, "title_max": 120,
           "forbidden": ["شعبه", "تومان", "ریال", "قیمت"], **(db.get_settings().get("quality") or {})}
    bank = workbench.get_bank(p["bank_id"])
    schema = workbench.bank_schema(bank)
    errors, warnings = [], []
    t = (p.get("title") or "").strip()
    if len(t) < int(cfg["title_min"]):
        errors.append({"key": "title", "label": f"عنوان کوتاه‌تر از {cfg['title_min']} حرف است"})
    elif len(t) > int(cfg["title_max"]):
        warnings.append({"key": "title", "label": f"عنوان بلندتر از {cfg['title_max']} حرف است"})
    if not _SLUG.match(p.get("slug") or ""):
        errors.append({"key": "slug", "label": "اسلاگ انگلیسی معتبر ندارد"})
    roles = {workbench.core_role(c) for c in schema["columns"] if c.get("include", True) is not False}
    if "brand" in roles and not p.get("brand_id"):
        errors.append({"key": "brand", "label": "برند از فهرست مرجع انتخاب نشده است"})
    if "category" in roles and not p.get("category_id"):
        errors.append({"key": "category", "label": "دسته‌بندی از فهرست مرجع انتخاب نشده است"})
    if not p.get("images"):
        errors.append({"key": "images", "label": "تصویر شاخص ندارد"})
    else:
        small = [im for im in p["images"] if min(int(im.get("w") or 0), int(im.get("h") or 0)) < int(cfg["min_image_px"])]
        if small:
            warnings.append({"key": "images", "label": f"{len(small)} تصویر کوچک‌تر از {cfg['min_image_px']} پیکسل است"})
        if len(p["images"]) < 2:
            warnings.append({"key": "images", "label": "تصویر گالری ندارد"})
    if (p.get("meta") or {}).get("compat_auto"):
        warnings.append({"key": "compat", "label": "سازگاری با خودرو پیشنهاد خودکار است و تأیید نشده"})
    forb = [w for w in cfg.get("forbidden") or [] if w]
    for col in schema["columns"]:
        if col.get("include", True) is False:
            continue
        role = workbench.core_role(col)
        if role in ("feature", "gallery", "brand", "category", "slug", "compat"):
            continue
        v = workbench.product_value(p, col)
        if col.get("required") and _empty(v):
            errors.append({"key": col["key"], "label": f"«{col.get('label') or col['key']}» خالی است"})
            continue
        if col.get("input") == "longtext" and isinstance(v, str) and v.strip() and len(v.strip()) < int(cfg["min_long_chars"]):
            warnings.append({"key": col["key"], "label": f"«{col.get('label') or col['key']}» کوتاه‌تر از {cfg['min_long_chars']} حرف است"})
        hits = sorted({w for w in forb for s in _texts(v) if w in s})
        if hits:
            warnings.append({"key": col["key"], "label": f"«{col.get('label') or col['key']}» واژه‌ی ممنوع دارد: {'، '.join(hits)}"})
    s = max(0, 100 - 15 * len(errors) - 5 * len(warnings))
    return {"score": s, "errors": errors, "warnings": warnings, "min": int(cfg["min_score"]),
            "ready": not errors and s >= int(cfg["min_score"])}


def rescore_bank(bank_id: int | None = None) -> int:
    from ... import workbench
    n = 0
    sql = "SELECT id FROM wb_products WHERE status IN ('draft','review','approved','rejected')" + (" AND bank_id=?" if bank_id else "")
    for r in db.q(sql, [bank_id] if bank_id else []):
        p = workbench.get_product(r["id"])
        res = score(p)
        db.update("wb_products", p["id"], quality=res["score"], quality_detail=res)
        n += 1
    return n


@route("/api/quality/products/{id:int}", module="quality")
async def q_product(request, body):
    from ... import workbench
    return score(workbench.get_product(pid(request)))


@route("/api/quality/rescore", methods=("POST",), module="quality")
async def q_rescore(request, body):
    from starlette.concurrency import run_in_threadpool
    return {"rescored": await run_in_threadpool(rescore_bank, body.get("bank_id"))}


@route("/api/quality/settings", methods=("GET", "PUT"), module="quality")
async def q_settings(request, body):
    if request.method == "PUT":
        cur = db.get_settings().get("quality") or {}
        cur.update({k: v for k, v in body.items() if k in ("min_score", "min_image_px", "min_long_chars", "title_min", "title_max", "forbidden")})
        db.set_settings({"quality": cur})
    return db.get_settings().get("quality")
