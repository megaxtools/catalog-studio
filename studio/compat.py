"""رابط هسته با «سازگاری با خودرو».

هسته (ویرایشگر، کاتالوگ، داده‌ی خام) فقط از این فایل استفاده می‌کند. اگر ماژول «خودروها» فعال باشد، کار به آن سپرده
می‌شود؛ اگر نباشد، مقدار ذخیره‌شده دست نمی‌خورد و برای نمایش و خروجی «همه‌ی خودروها» در نظر گرفته می‌شود.
"""
from __future__ import annotations

import json

from . import modules

ALL = {"all": True}


def available() -> bool:
    return modules.is_enabled("vehicles")


def _svc():
    from .modules.vehicles import service
    return service


def parse(value) -> dict:
    if value in (None, "", "all", True):
        return dict(ALL)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return dict(ALL)
    if isinstance(value, list):
        value = {"all": False, "items": value}
    if not isinstance(value, dict) or value.get("all") or not value.get("items"):
        return dict(ALL)
    return {"all": False, "items": [{"t": i.get("t"), "id": int(i.get("id"))} for i in value["items"] if i.get("t") and i.get("id")]}


def normalize(value, strict: bool = True) -> dict:
    if not available():
        v = parse(value)
        if not v.get("all") and strict:
            raise ValueError("ماژول «خودروها و سازگاری» غیرفعال است؛ فقط «همه‌ی خودروها» قابل انتخاب است.")
        return v
    return _svc().normalize(value, strict=strict)


def describe(value) -> dict:
    v = parse(value)
    if not available():
        if v.get("all"):
            return {"all": True, "label": "همه‌ی خودروها", "items": []}
        return {"all": False, "label": f"{len(v['items'])} خودرو (ماژول خودروها غیرفعال است)", "items": [], "unavailable": True}
    return _svc().describe(v)


def export(value, fmt: str = "structured", all_token: str = "all"):
    if not available():
        return {"all": True, "vehicles": []} if fmt == "structured" else ([all_token] if fmt != "names" else ["همه‌ی خودروها"])
    return _svc().export(value, fmt, all_token)


def suggest(text: str) -> dict:
    if not available():
        return {"value": dict(ALL), "matches": [], "confidence": 0}
    try:
        return _svc().suggest(text)
    except Exception:  # noqa: BLE001 — تطبیق نباید کار اصلی را متوقف کند
        return {"value": dict(ALL), "matches": [], "confidence": 0}


def is_specific(value) -> bool:
    return not parse(value).get("all")


def leaves(value) -> list[dict]:
    if not available():
        return []
    return _svc().expand_leaves(value)
