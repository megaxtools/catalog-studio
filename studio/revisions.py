"""ریویژن‌ها (کنترل نسخه‌ی داده).

هر بار که یک موجودیت مهم تغییر می‌کند، یک نسخه‌ی کامل (snapshot) با شماره‌ی بعدی ذخیره می‌شود؛ همراه با فهرست
تغییرات نسبت به نسخه‌ی قبل (کدام فیلد، مقدار قبلی، مقدار جدید)، کننده (کاربر، هوش مصنوعی، ایجنت، سیستم) و یادداشت.

موجودیت‌ها:
    raw_item      محصول خام (نسخه‌ی ۱ = داده‌ی استخراج‌شده)
    product       محصول تمیز در ویرایشگر
    schema        اسکیما
    template      الگوی خروجی
    catalog       تنظیمات کاتالوگ (انتشارها خودشان نسخه‌دار و تغییرناپذیرند)
    ref_brand / ref_category / vehicle_*    داده‌های مرجع

بازگردانی همیشه یک نسخه‌ی تازه می‌سازد (تاریخچه هرگز پاک نمی‌شود). مالک هر موجودیت با `register_restorer` تابع
بازگرداندن snapshot را ثبت می‌کند.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import db

ENTITY_LABELS = {
    "raw_item": "محصول خام", "product": "محصول تمیز", "schema": "اسکیما", "template": "الگوی خروجی",
    "catalog": "کاتالوگ", "ref_brand": "برند", "ref_category": "دسته‌بندی",
    "vehicle_brand": "برند خودرو", "vehicle_model": "مدل خودرو", "vehicle_trim": "تیپ خودرو",
}
ACTION_LABELS = {
    "create": "ایجاد", "scrape": "استخراج", "import": "ورود از داده‌ی خام", "edit": "ویرایش", "ai": "هوش مصنوعی",
    "bulk": "ویرایش گروهی", "images": "تصاویر", "status": "تغییر وضعیت", "restore": "بازگردانی", "merge": "ادغام",
    "delete": "حذف", "compat": "سازگاری با خودرو", "migrate": "انتقال از نسخه‌ی ۱",
}

_RESTORERS: dict[str, Callable[[int, dict, str], None]] = {}


def register_restorer(entity: str, fn: Callable[[int, dict, str], None]) -> None:
    _RESTORERS[entity] = fn


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _flatten(v: Any, prefix: str = "") -> dict[str, Any]:
    """شیء تودرتو → {مسیر: مقدار برگ} برای مقایسه‌ی دقیق فیلدبه‌فیلد. فهرست‌ها برگ حساب می‌شوند."""
    out: dict[str, Any] = {}
    if isinstance(v, dict) and v:
        for k, x in v.items():
            out.update(_flatten(x, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix or "(کل)"] = v
    return out


def diff(old: dict | None, new: dict | None) -> list[dict]:
    """تغییرات میان دو snapshot: [{field, old, new}] — مسیرها مثل values.title یا images."""
    a, b = _flatten(old or {}), _flatten(new or {})
    out = []
    for k in sorted(set(a) | set(b)):
        if _dump(a.get(k)) != _dump(b.get(k)):
            out.append({"field": k, "old": a.get(k), "new": b.get(k)})
    return out


def latest(entity: str, entity_id: int) -> dict | None:
    r = db.q1("SELECT * FROM revisions WHERE entity=? AND entity_id=? ORDER BY rev DESC LIMIT 1", [entity, entity_id])
    return _row(r) if r else None


def record(entity: str, entity_id: int, snapshot: dict, actor: str = "ui", action: str = "edit", note: str = "",
           force: bool = False) -> dict | None:
    """ثبت نسخه‌ی تازه اگر با نسخه‌ی قبل فرق داشته باشد. خروجی: ریویژن ثبت‌شده یا None."""
    prev = latest(entity, entity_id)
    changes = diff(prev["snapshot"] if prev else {}, snapshot) if prev else []
    if prev and not changes and not force:
        return None
    rev = (prev["rev"] if prev else 0) + 1
    uid = db.get_settings().get("current_user_id") or 1
    rid = db.ex("INSERT INTO revisions(entity, entity_id, rev, action, snapshot, changes, actor, user_id, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [entity, entity_id, rev, action, _dump(snapshot), _dump(changes[:500]), actor, uid, note[:500], db.now()])
    return {"id": rid, "rev": rev, "changes": len(changes)}


def _row(r: dict) -> dict:
    r = dict(r)
    r["snapshot"] = db.jload(r.get("snapshot"), {}) or {}
    r["changes"] = db.jload(r.get("changes"), []) or []
    return r


def list_revisions(entity: str, entity_id: int, light: bool = True) -> list[dict]:
    rows = [_row(r) for r in db.q("SELECT * FROM revisions WHERE entity=? AND entity_id=? ORDER BY rev DESC", [entity, entity_id])]
    users = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    for r in rows:
        r["user"] = users.get(r.get("user_id"), "")
        r["action_label"] = ACTION_LABELS.get(r["action"], r["action"])
        r["fields"] = sorted({c["field"].split(".")[0] if not c["field"].startswith("values.") else c["field"].split(".")[1]
                              for c in r["changes"]})
        if light:
            r.pop("snapshot", None)
            r["changes"] = r["changes"][:40]
    return rows


def get_revision(entity: str, entity_id: int, rev: int) -> dict:
    r = db.q1("SELECT * FROM revisions WHERE entity=? AND entity_id=? AND rev=?", [entity, entity_id, rev])
    if not r:
        raise ValueError("این نسخه پیدا نشد.")
    return _row(r)


def compare(entity: str, entity_id: int, a: int, b: int) -> dict:
    ra, rb = get_revision(entity, entity_id, a), get_revision(entity, entity_id, b)
    return {"a": {"rev": a, "created_at": ra["created_at"], "action": ra["action"]},
            "b": {"rev": b, "created_at": rb["created_at"], "action": rb["action"]},
            "changes": diff(ra["snapshot"], rb["snapshot"])}


def restore(entity: str, entity_id: int, rev: int, actor: str = "ui") -> dict:
    fn = _RESTORERS.get(entity)
    if not fn:
        raise ValueError("بازگردانی این نوع داده پشتیبانی نمی‌شود.")
    r = get_revision(entity, entity_id, rev)
    fn(entity_id, r["snapshot"], actor)
    return record(entity, entity_id, r["snapshot"], actor=actor, action="restore", note=f"بازگردانی به نسخه‌ی {rev}", force=True) or {}


def recent(entity: str | None = None, limit: int = 100, page: int = 1, q: str = "", actor: str = "") -> dict:
    where, args = [], []
    if entity:
        where.append("entity=?")
        args.append(entity)
    if actor:
        where.append("actor=?")
        args.append(actor)
    if q:
        where.append("(changes LIKE ? OR note LIKE ?)")
        args += [f"%{q}%"] * 2
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.val(f"SELECT COUNT(*) FROM revisions {w}", args) or 0
    rows = db.q(f"SELECT id, entity, entity_id, rev, action, actor, user_id, note, created_at, substr(changes,1,1500) AS changes FROM revisions {w} "
                f"ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, (page - 1) * limit])
    for r in rows:
        try:
            ch = json.loads(r["changes"])
        except ValueError:
            ch = []
        r["fields"] = sorted({c["field"] for c in ch})[:12] if isinstance(ch, list) else []
        r.pop("changes", None)
        r["entity_label"] = ENTITY_LABELS.get(r["entity"], r["entity"])
        r["action_label"] = ACTION_LABELS.get(r["action"], r["action"])
    return {"total": total, "rows": rows, "page": page, "size": limit}
