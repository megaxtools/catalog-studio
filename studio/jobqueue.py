"""صف و زمان‌بندی استخراج: اجرای ترتیبی، زمان شروع، تکرار دوره‌ای و تولید هوش مصنوعی پس از استخراج."""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import db, services
from .engine.errors import DEFAULT_POLICIES
from .engine.runner import MANAGER
from .textutil import slugify

FINISHED_DS = ("completed", "stopped", "error")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def job_row(r: dict) -> dict:
    r = dict(r)
    r["options"] = db.jload(r["options"], {})
    r["policies"] = db.jload(r["policies"], {})
    r["source"] = db.q1("SELECT id, key, name FROM sources WHERE id=?", [r["source_id"]])
    r["schema"] = db.q1("SELECT id, name FROM schemas WHERE id=?", [r["schema_id"]]) if r["schema_id"] else None
    r["ai_profile"] = db.q1("SELECT id, name FROM ai_profiles WHERE id=?", [r["ai_profile_id"]]) if r["ai_profile_id"] else None
    r["dataset"] = services.get_dataset(r["dataset_id"]) if r["dataset_id"] else None
    if r["ai_job_id"]:
        aj = db.q1("SELECT id, status, progress_done, progress_total, failed, step FROM ai_jobs WHERE id=?", [r["ai_job_id"]])
        r["ai_job"] = aj
    else:
        r["ai_job"] = None
    return r


def list_jobs(include_done: bool = True) -> list[dict]:
    sql = "SELECT * FROM queue_jobs"
    if not include_done:
        sql += " WHERE status NOT IN ('done','skipped','cancelled')"
    rows = db.q(sql + " ORDER BY CASE WHEN status IN ('running','ai_running') THEN 0 WHEN status='queued' THEN 1 ELSE 2 END, position, id")
    return [job_row(r) for r in rows]


def add_job(body: dict) -> dict:
    url = (body.get("category_url") or "").strip()
    if body.get("ai_generate"):
        from . import ai_studio
        if not (body["ai_generate"].get("product_type") or "").strip():
            raise ValueError("نوع محصول را مشخص کنید.")
        url = url or "ai://generate/" + (slugify(body["ai_generate"].get("category_label") or body["ai_generate"]["product_type"]) or "products")
        body["source_id"] = ai_studio.ensure_ai_source()["id"]
        body.setdefault("limit", body["ai_generate"].get("count"))
    elif not url.startswith("http"):
        raise ValueError("لینک صفحه‌ی دسته‌بندی معتبر نیست.")
    sid = body.get("source_id") or (services.detect_source(url) or {}).get("id")
    if not sid:
        raise ValueError("منبع این لینک شناخته نشد؛ منبع را دستی انتخاب کنید.")
    limit = body.get("limit")
    limit = int(limit) if limit not in (None, "", 0, "0") else None
    pos = (db.val("SELECT MAX(position) FROM queue_jobs") or 0) + 1
    sched = body.get("scheduled_at") or None
    if sched:
        d = _parse(sched)
        if not d:
            raise ValueError("زمان شروع معتبر نیست.")
        sched = d.astimezone(timezone.utc).isoformat(timespec="seconds")
    opts = {"duplicates": body.get("duplicates", "skip"), "show_browser": bool(body.get("show_browser")),
            "category_label": body.get("category_label", ""), "ai_scope": body.get("ai_scope", "all")}
    if body.get("ai_generate"):
        opts["ai_generate"] = body["ai_generate"]
    if body.get("ai_after"):
        opts["ai_after"] = body["ai_after"]
    jid = db.ex("""INSERT INTO queue_jobs(position, title, source_id, category_url, item_limit, schema_id, options, policies,
                   ai_profile_id, scheduled_at, repeat_hours, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [pos, body.get("title", ""), int(sid), url, limit, body.get("schema_id") or None, db.jdump(opts),
                 db.jdump({**DEFAULT_POLICIES, **(body.get("policies") or {})}), body.get("ai_profile_id") or None, sched,
                 float(body.get("repeat_hours") or 0), "queued", db.now()])
    db.log("queue", jid, "کار جدید به صف اضافه شد.", step="queue", detail=url)
    QUEUE.wake()
    return job_row(db.q1("SELECT * FROM queue_jobs WHERE id=?", [jid]))


def move(jid: int, direction: int):
    rows = db.q("SELECT id, position FROM queue_jobs WHERE status='queued' ORDER BY position, id")
    ids = [r["id"] for r in rows]
    if jid not in ids:
        return
    i = ids.index(jid)
    j = i + direction if direction in (-1, 1) else (0 if direction < 0 else len(ids) - 1)
    if direction == -99:
        j = 0
    if j < 0 or j >= len(ids):
        return
    ids.insert(j, ids.pop(i))
    for n, x in enumerate(ids, 1):
        db.ex("UPDATE queue_jobs SET position=? WHERE id=?", [n, x])


class QueueRunner:
    def __init__(self):
        self._t: threading.Thread | None = None
        self._ev = threading.Event()
        self.last_error = ""

    def start(self):
        if self._t and self._t.is_alive():
            return
        self._t = threading.Thread(target=self._loop, daemon=True, name="queue")
        self._t.start()

    def wake(self):
        self._ev.set()

    def recover(self):
        """پس از اجرای دوباره‌ی برنامه، کار در حال اجرای صف از همان نقطه ادامه می‌یابد."""
        if not db.get_settings().get("queue_enabled", True):
            return
        for j in db.q("SELECT * FROM queue_jobs WHERE status IN ('running','ai_running')"):
            if j["status"] == "running" and j["dataset_id"]:
                d = db.q1("SELECT status FROM datasets WHERE id=?", [j["dataset_id"]])
                if d and d["status"] in ("paused",):
                    MANAGER.start(j["dataset_id"])
            if j["status"] == "ai_running" and j["ai_job_id"]:
                from .ai_gen import AI_JOBS
                a = db.q1("SELECT status FROM ai_jobs WHERE id=?", [j["ai_job_id"]])
                if a and a["status"] == "paused":
                    AI_JOBS.start(j["ai_job_id"])

    def _loop(self):
        while True:
            try:
                self.tick()
                self.last_error = ""
            except Exception:  # noqa: BLE001
                self.last_error = traceback.format_exc()[-800:]
            self._ev.wait(3)
            self._ev.clear()

    def tick(self):
        from .ai_gen import AI_JOBS
        active = db.q1("SELECT * FROM queue_jobs WHERE status IN ('running','ai_running') ORDER BY position LIMIT 1")
        if active:
            if active["status"] == "running":
                d = db.q1("SELECT status FROM datasets WHERE id=?", [active["dataset_id"]]) if active["dataset_id"] else None
                if not d:
                    db.update("queue_jobs", active["id"], status="failed", error="بانک داده‌ی این کار حذف شد.", finished_at=db.now())
                    return
                if d["status"] in FINISHED_DS:
                    if d["status"] == "error":
                        self._finish(active, "failed", "استخراج با خطا متوقف شد.")
                        return
                    opts = db.jload(active["options"], {})
                    ajid = None
                    if active["ai_profile_id"]:
                        ajid = AI_JOBS.create(active["dataset_id"], active["ai_profile_id"], {"scope": opts.get("ai_scope", "all")})
                    elif opts.get("ai_after") and not opts.get("ai_generate"):
                        from .ai_gen import start_after_scrape
                        try:
                            ajid = start_after_scrape(active["dataset_id"], opts["ai_after"])
                        except Exception as exc:  # noqa: BLE001
                            db.log("queue", active["id"], f"تولید با هوش مصنوعی آغاز نشد: {exc}", level="warning", step="queue")
                    if ajid:
                        db.update("queue_jobs", active["id"], status="ai_running", ai_job_id=ajid)
                        db.log("queue", active["id"], "استخراج تمام شد؛ تولید با هوش مصنوعی آغاز شد.", step="queue")
                    else:
                        self._finish(active, "done")
                return
            if active["status"] == "ai_running":
                a = db.q1("SELECT status, error FROM ai_jobs WHERE id=?", [active["ai_job_id"]])
                if not a:
                    self._finish(active, "done")
                elif a["status"] == "completed":
                    self._finish(active, "done")
                elif a["status"] == "error":
                    self._finish(active, "failed", f"تولید هوش مصنوعی: {a['error']}")
                return
        if not db.get_settings().get("queue_enabled", True):
            return
        now = _now()
        for j in db.q("SELECT * FROM queue_jobs WHERE status='queued' ORDER BY position, id"):
            sch = _parse(j["scheduled_at"])
            if sch and sch > now:
                continue
            self._launch(j)
            return

    def _launch(self, j: dict):
        opts = db.jload(j["options"], {})
        if opts.get("ai_generate"):
            from . import ai_studio
            spec = {**opts["ai_generate"], "count": j["item_limit"] or opts["ai_generate"].get("count") or 10, "schema_id": j["schema_id"], "start": False}
            ds = ai_studio.create_dataset(spec)
            db.update("queue_jobs", j["id"], status="running", dataset_id=ds["id"], started_at=db.now())
            db.log("queue", j["id"], f"تولید بانک داده با هوش مصنوعی آغاز شد: {ds['code']}", step="queue")
            ai_studio.AI_DATASETS.start(ds["id"])
            return
        ds_opts = {"duplicates": opts.get("duplicates", "skip"), "show_browser": bool(opts.get("show_browser")), "queue_job_id": j["id"]}
        if opts.get("category_label"):
            ds_opts["category_label_manual"] = True
        ds = services.create_dataset(j["source_id"], j["category_url"], j["item_limit"], j["schema_id"], ds_opts,
                                     db.jload(j["policies"], {}), opts.get("category_label", ""))
        db.update("queue_jobs", j["id"], status="running", dataset_id=ds["id"], started_at=db.now())
        db.log("queue", j["id"], f"اجرای کار صف آغاز شد: {ds['code']}", step="queue")
        MANAGER.start(ds["id"])

    def _finish(self, j: dict, status: str, error: str = ""):
        db.update("queue_jobs", j["id"], status=status, error=error, finished_at=db.now())
        db.log("queue", j["id"], "کار صف تمام شد." if status == "done" else f"کار صف ناموفق بود: {error}",
               level="success" if status == "done" else "warning", step="queue")
        if float(j.get("repeat_hours") or 0) > 0:
            nxt = (_now() + timedelta(hours=float(j["repeat_hours"]))).isoformat(timespec="seconds")
            pos = (db.val("SELECT MAX(position) FROM queue_jobs") or 0) + 1
            db.ex("""INSERT INTO queue_jobs(position, title, source_id, category_url, item_limit, schema_id, options, policies,
                     ai_profile_id, scheduled_at, repeat_hours, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  [pos, j["title"], j["source_id"], j["category_url"], j["item_limit"], j["schema_id"], j["options"], j["policies"],
                   j["ai_profile_id"], nxt, j["repeat_hours"], "queued", db.now()])
            db.log("queue", j["id"], f"اجرای دوره‌ای بعدی زمان‌بندی شد ({j['repeat_hours']} ساعت بعد).", step="queue")


QUEUE = QueueRunner()
