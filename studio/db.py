"""لایه‌ی دیتابیس SQLite: جداول، مهاجرت و توابع کمکی."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DB_PATH, DEFAULT_SETTINGS

_lock = threading.RLock()
_local = threading.local()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schemas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    columns TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    schema_id INTEGER,
    category_url TEXT NOT NULL,
    category_label TEXT DEFAULT '',
    category_key TEXT DEFAULT '',
    item_limit INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    step TEXT DEFAULT '',
    total_found INTEGER DEFAULT 0,
    total_expected INTEGER,
    discovery_done INTEGER NOT NULL DEFAULT 0,
    cursor TEXT NOT NULL DEFAULT '{}',
    options TEXT NOT NULL DEFAULT '{}',
    policies TEXT NOT NULL DEFAULT '{}',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    product_key TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    data TEXT NOT NULL DEFAULT '{}',
    overrides TEXT NOT NULL DEFAULT '{}',
    manual TEXT NOT NULL DEFAULT '{}',
    missing TEXT NOT NULL DEFAULT '[]',
    error TEXT DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    scraped_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(dataset_id, product_key)
);
CREATE INDEX IF NOT EXISTS idx_items_ds ON items(dataset_id, status);
CREATE INDEX IF NOT EXISTS idx_items_key ON items(source_id, product_key);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    scope TEXT NOT NULL,
    ref_id INTEGER,
    item_id INTEGER,
    step TEXT DEFAULT '',
    message TEXT NOT NULL,
    detail TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_logs_scope ON logs(scope, ref_id, id);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    item_id INTEGER,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT DEFAULT '',
    url TEXT DEFAULT '',
    options TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    decision TEXT,
    apply_all INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    source_id INTEGER,
    source_value TEXT NOT NULL,
    target_slug TEXT NOT NULL,
    target_label TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(kind, source_id, source_value)
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dataset_ids TEXT NOT NULL,
    schema_id INTEGER NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    step TEXT DEFAULT '',
    progress_done INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    result TEXT NOT NULL DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS text_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    source_id INTEGER,
    target TEXT NOT NULL DEFAULT '*',
    action TEXT NOT NULL,
    find TEXT DEFAULT '',
    value TEXT DEFAULT '',
    flags TEXT NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    text_model TEXT DEFAULT '',
    image_model TEXT DEFAULT '',
    image_mode TEXT DEFAULT 'images_api',
    headers TEXT NOT NULL DEFAULT '{}',
    proxy TEXT DEFAULT '',
    timeout_s INTEGER DEFAULT 90,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    step TEXT DEFAULT '',
    progress_done INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS queue_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position INTEGER NOT NULL DEFAULT 0,
    title TEXT DEFAULT '',
    source_id INTEGER NOT NULL,
    category_url TEXT NOT NULL,
    item_limit INTEGER,
    schema_id INTEGER,
    options TEXT NOT NULL DEFAULT '{}',
    policies TEXT NOT NULL DEFAULT '{}',
    ai_profile_id INTEGER,
    scheduled_at TEXT,
    repeat_hours REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    dataset_id INTEGER,
    ai_job_id INTEGER,
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    client TEXT DEFAULT '',          -- ui | mcp | api
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    action TEXT DEFAULT '',
    status INTEGER,
    ms INTEGER DEFAULT 0,
    request TEXT DEFAULT '',
    response TEXT DEFAULT '',
    error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(id);

CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider_id INTEGER,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    kind TEXT DEFAULT 'chat',
    purpose TEXT DEFAULT '',
    ref TEXT DEFAULT '',
    item_id INTEGER,
    ok INTEGER DEFAULT 1,
    status INTEGER,
    error TEXT DEFAULT '',
    ms INTEGER DEFAULT 0,
    tokens INTEGER DEFAULT 0,
    prompt TEXT DEFAULT '',
    response TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    entity TEXT NOT NULL,           -- item | export | export_row
    entity_id INTEGER NOT NULL,
    parent_id INTEGER,              -- بانک داده یا خروجی
    field TEXT DEFAULT '',
    action TEXT DEFAULT 'edit',
    actor TEXT DEFAULT 'ui',        -- ui | mcp | ai | system
    old TEXT DEFAULT '',
    new TEXT DEFAULT '',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_history_entity ON history(entity, entity_id, id);
CREATE INDEX IF NOT EXISTS idx_history_parent ON history(parent_id, id);

CREATE TABLE IF NOT EXISTS export_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    export_id INTEGER NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
    item_id INTEGER,
    seq INTEGER DEFAULT 0,
    folder TEXT DEFAULT '',
    title TEXT DEFAULT '',
    images TEXT NOT NULL DEFAULT '{}',   -- {"feature": rel, "gallery": [rel...]}
    values_json TEXT NOT NULL DEFAULT '{}',  -- {schema_id: {col_key: value}}
    flags TEXT NOT NULL DEFAULT '{}',        -- {schema_id: {col_key: flag}}
    edited TEXT NOT NULL DEFAULT '{}',       -- {schema_id: {col_key: actor}}
    status TEXT DEFAULT 'ok',                -- ok | excluded
    note TEXT DEFAULT '',
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_export_rows ON export_rows(export_id, seq);

CREATE TABLE IF NOT EXISTS bg_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_path TEXT NOT NULL,
    output_path TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    progress_done INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    last_file TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn = c
    return c


def init() -> None:
    with _lock:
        c = conn()
        c.executescript(SCHEMA_SQL)
        cols = {r[1] for r in c.execute("PRAGMA table_info(items)").fetchall()}
        if "ai" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN ai TEXT NOT NULL DEFAULT '{}'")
        ecols = {r[1] for r in c.execute("PRAGMA table_info(exports)").fetchall()}
        for col, ddl in (("title", "TEXT DEFAULT ''"), ("notes", "TEXT DEFAULT ''"), ("state", "TEXT DEFAULT 'draft'"),
                         ("updated_at", "TEXT"), ("files_stale", "INTEGER DEFAULT 0")):
            if col not in ecols:
                c.execute(f"ALTER TABLE exports ADD COLUMN {col} {ddl}")
        c.commit()


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def q(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, tuple(args)).fetchall()]


def q1(sql: str, args: Iterable[Any] = ()) -> dict | None:
    return _row(conn().execute(sql, tuple(args)).fetchone())


def val(sql: str, args: Iterable[Any] = ()) -> Any:
    r = conn().execute(sql, tuple(args)).fetchone()
    return r[0] if r else None


def ex(sql: str, args: Iterable[Any] = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, tuple(args))
        c.commit()
        return cur.lastrowid


def exmany(sql: str, rows: list[tuple]) -> None:
    with _lock:
        c = conn()
        c.executemany(sql, rows)
        c.commit()


def update(table: str, row_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    ex(f"UPDATE {table} SET {cols} WHERE id=?", [*vals, row_id])


def jload(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


# ---------- تنظیمات ----------

def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        out[r["key"]] = jload(r["value"], r["value"])
    return out


def set_settings(values: dict) -> dict:
    for k, v in values.items():
        if k not in DEFAULT_SETTINGS:
            continue
        ex("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
           [k, jdump(v)])
    return get_settings()


# ---------- لاگ ----------

def history(entity: str, entity_id: int, field: str, old: Any, new: Any, actor: str = "ui", action: str = "edit",
            parent_id: int | None = None, note: str = "") -> None:
    """ثبت هر تغییر داده (مقدار قبلی و جدید) برای ردگیری و بازگردانی."""
    def s_(v):
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    try:
        ex("INSERT INTO history(ts, entity, entity_id, parent_id, field, action, actor, old, new, note) VALUES(?,?,?,?,?,?,?,?,?,?)",
           [now(), entity, entity_id, parent_id, field, action, actor, s_(old)[:20000], s_(new)[:20000], note])
    except Exception:  # noqa: BLE001
        pass


def log(scope: str, ref_id: int | None, message: str, level: str = "info", step: str = "",
        item_id: int | None = None, detail: str = "") -> int:
    return ex(
        "INSERT INTO logs(ts, level, scope, ref_id, item_id, step, message, detail) VALUES(?,?,?,?,?,?,?,?)",
        [now(), level, scope, ref_id, item_id, step, message, detail[:8000] if detail else ""],
    )
