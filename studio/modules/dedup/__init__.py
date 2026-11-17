"""ماژول «تشخیص تکراری»: پیدا کردن محصولات تکراری (از یک یا چند منبع) و ادغامشان در یک محصول تمیز.

نامزدها با شباهت واژه‌های عنوان (پس از نرمال‌سازی)، برند یکسان و لینک منبع یکسان پیدا می‌شوند. ادغام: محصول اصلی
می‌ماند، مقادیر خالی‌اش از محصول دوم پر می‌شود (یا مقادیر انتخابی کاربر)، تصاویر و منابع جمع می‌شوند و محصول دوم
وضعیت «ادغام‌شده» می‌گیرد (با ریویژن، برگشت‌پذیر).
"""
from __future__ import annotations

import json
import re

from ... import db
from ...refdata import norm
from ...web import actor_of, pid, route
from .. import Module

MIGRATIONS = [(1, """
CREATE TABLE IF NOT EXISTS dup_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id INTEGER NOT NULL,
    b_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (a_id, b_id)
)
""")]

MODULE = Module(id="dedup", name="تشخیص تکراری", version="1.0.0", migrations=MIGRATIONS, tables=["dup_pairs"],
                description="پیدا کردن محصولات تکراری در بانک‌های تمیز و ادغامشان با حفظ تاریخچه.")
_STOP = {"برای", "مدل", "با", "و", "از", "به", "در", "کد", "سری", "عدد", "بسته", "the", "for", "and"}


def _tokens(title: str) -> set[str]:
    return {w for w in re.split(r"\s+", norm(title)) if w and w not in _STOP and (len(w) > 1 or w.isdigit())}


def similarity(a: dict, b: dict) -> tuple[int, list[str]]:
    reasons = []
    ta, tb = _tokens(a["title"]), _tokens(b["title"])
    j = len(ta & tb) / max(1, len(ta | tb))
    s = int(j * 100)
    if j >= 0.5:
        reasons.append(f"شباهت عنوان {int(j * 100)}٪")
    ua = {x.get("url") for x in json.loads(a["sources"] or "[]") if x.get("url")}
    ub = {x.get("url") for x in json.loads(b["sources"] or "[]") if x.get("url")}
    if ua & ub:
        s = 100
        reasons.append("لینک منبع یکسان")
    if a.get("brand_id") and a.get("brand_id") == b.get("brand_id"):
        s = min(100, s + 10)
        reasons.append("برند یکسان")
    elif a.get("brand_id") and b.get("brand_id"):
        s = max(0, s - 30)
    nums_a, nums_b = set(re.findall(r"\d+(?:\.\d+)?", norm(a["title"]))), set(re.findall(r"\d+(?:\.\d+)?", norm(b["title"])))
    if nums_a and nums_b and nums_a != nums_b:
        s = max(0, s - 25)  # «۴ لیتر» با «۱ لیتر» یکی نیست
    return s, reasons


def scan(bank_id: int | None = None, threshold: int = 75) -> dict:
    sql = "SELECT id, bank_id, title, brand_id, sources FROM wb_products WHERE status IN ('draft','review','approved','rejected')"
    rows = db.q(sql + (" AND bank_id=?" if bank_id else ""), [bank_id] if bank_id else [])
    if bank_id:  # مقایسه با بقیه‌ی بانک‌ها هم
        others = db.q(sql + " AND bank_id<>?", [bank_id])
    else:
        others = []
    pool = rows + others
    found = 0
    by_tok: dict[str, list[int]] = {}
    for i, r in enumerate(pool):
        for t in _tokens(r["title"]):
            by_tok.setdefault(t, []).append(i)
    seen = set()
    for i, a in enumerate(rows):
        cands = {j for t in _tokens(a["title"]) for j in by_tok.get(t, []) if j != i}
        for j in cands:
            b = pool[j]
            key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
            if key in seen:
                continue
            seen.add(key)
            s, reasons = similarity(a, b)
            if s < threshold:
                continue
            ex = db.q1("SELECT id, status FROM dup_pairs WHERE a_id=? AND b_id=?", list(key))
            if ex:
                continue
            db.ex("INSERT INTO dup_pairs(a_id, b_id, score, reasons, status, created_at) VALUES(?,?,?,?,?,?)",
                  [key[0], key[1], s, json.dumps(reasons, ensure_ascii=False), "open", db.now()])
            found += 1
    return {"found": found}


def list_pairs(status: str = "open", bank_id: int | None = None) -> list[dict]:
    from ... import workbench
    out = []
    for r in db.q("SELECT * FROM dup_pairs WHERE status=? ORDER BY score DESC, id LIMIT 500", [status]):
        try:
            a, b = workbench.get_product(r["a_id"]), workbench.get_product(r["b_id"])
        except ValueError:
            continue
        if a["status"] == "merged" or b["status"] == "merged":
            continue
        if bank_id and bank_id not in (a["bank_id"], b["bank_id"]):
            continue
        r = dict(r)
        r["reasons"] = json.loads(r["reasons"] or "[]")
        r["a"], r["b"] = workbench.view(a, light=True), workbench.view(b, light=True)
        out.append(r)
    return out


def merge(primary_id: int, secondary_id: int, choose: dict | None = None, actor: str = "ui") -> dict:
    """ادغام secondary در primary. choose: {فیلد یا کلید ستون: "a"|"b"} برای انتخاب مقدار؛ پیش‌فرض: مقدار اصلی، خالی‌ها از دومی."""
    from ... import workbench
    if primary_id == secondary_id:
        raise ValueError("دو محصول متفاوت انتخاب کنید.")
    a, b = workbench.get_product(primary_id), workbench.get_product(secondary_id)
    if "merged" in (a["status"], b["status"]):
        raise ValueError("یکی از محصولات قبلاً ادغام شده است.")
    choose = choose or {}
    upd: dict = {"values": {}}
    for k in ("title", "brand", "category", "compat"):
        src = choose.get(k)
        fld = {"brand": "brand_id", "category": "category_id"}.get(k, k)
        if src == "b" or (src is None and not a.get(fld) and b.get(fld) and k != "compat"):
            upd[k] = b.get(fld)
    if choose.get("compat") is None and a["compat"].get("all") and not b["compat"].get("all"):
        upd["compat"] = b["compat"]
    for k in set(a["values"]) | set(b["values"]):
        src = choose.get(k)
        av, bv = a["values"].get(k), b["values"].get(k)
        if src == "b" or (src is None and (av in (None, "", [], {}) and bv not in (None, "", [], {}))):
            upd["values"][k] = bv
    a2 = workbench.get_product(primary_id)
    have = {im.get("src") for im in a2["images"]}
    a2["images"] += [im for im in b["images"] if im.get("src") not in have or im.get("origin") != "source"]
    a2["sources"] += [s for s in b["sources"] if s not in a2["sources"]]
    a2["meta"].setdefault("merged_from", []).append(secondary_id)
    workbench._save(a2, actor, "merge", note=f"ادغام محصول {b['uid']}")  # noqa: SLF001
    if not upd["values"]:
        upd.pop("values")
    workbench.update_product(primary_id, upd, actor=actor, action="merge", note=f"ادغام محصول {b['uid']}", force=True)
    b["status"], b["merged_into"] = "merged", primary_id
    workbench._save(b, actor, "merge", note=f"ادغام در {a['uid']}", rescore=False)  # noqa: SLF001
    db.ex("UPDATE dup_pairs SET status='merged', decided_at=? WHERE (a_id=? AND b_id=?) OR (a_id=? AND b_id=?)",
          [db.now(), primary_id, secondary_id, secondary_id, primary_id])
    return workbench.view(workbench.get_product(primary_id))


@route("/api/dupes", module="dedup")
async def d_list(request, body):
    qp = request.query_params
    return list_pairs(qp.get("status", "open"), int(qp["bank_id"]) if qp.get("bank_id") else None)


@route("/api/dupes/scan", methods=("POST",), module="dedup")
async def d_scan(request, body):
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(scan, body.get("bank_id"), int(body.get("threshold") or 75))


@route("/api/dupes/{id:int}/dismiss", methods=("POST",), module="dedup")
async def d_dismiss(request, body):
    db.ex("UPDATE dup_pairs SET status='dismissed', decided_at=? WHERE id=?", [db.now(), pid(request)])
    return {"ok": True}


@route("/api/dupes/merge", methods=("POST",), module="dedup")
async def d_merge(request, body):
    return merge(int(body["primary_id"]), int(body["secondary_id"]), body.get("choose"), actor_of(request))
