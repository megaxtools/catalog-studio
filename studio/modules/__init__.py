"""چارچوب ماژول‌های استودیو.

هر قابلیت جانبی یک «ماژول» است با شناسه، نام، توضیح، وابستگی‌ها، مهاجرت‌های پایگاه داده، مسیرهای API، صفحه‌های رابط و
ابزارهای MCP خودش. ماژول‌ها دو گونه‌اند:

- **ماژول‌های داخلی** (builtin): قابلیت‌هایی که کدشان در هسته است (استخراج، هوش مصنوعی، حذف پس‌زمینه، …) و این‌جا فقط
  مانیفست و دروازه‌ی (gate) فعال/غیرفعال دارند.
- **ماژول‌های بسته‌ای**: پوشه‌ای زیر `studio/modules/<id>/` با متغیر `MODULE` در `__init__.py` (مثل خودروها، ویرایشگر
  تصویر، کنترل کیفیت، تشخیص تکراری). اگر import یا مهاجرت یک ماژول خطا بدهد، فقط همان ماژول «خطا» می‌گیرد و
  غیرفعال می‌شود؛ هسته و بقیه‌ی ماژول‌ها کار می‌کنند. با حذف پوشه‌ی یک ماژول، استودیو بدون آن بالا می‌آید.

وضعیت روشن/خاموش هر ماژول در تنظیمات (`settings.modules = {id: bool}`) ذخیره می‌شود.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import traceback
from dataclasses import dataclass, field
from typing import Callable

from .. import db


@dataclass
class Module:
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    core: bool = False                 # هسته؛ قابل غیرفعال کردن نیست
    default_enabled: bool = True
    requires: tuple = ()               # شناسه‌ی ماژول‌های لازم
    migrations: list = field(default_factory=list)   # [(نسخه، SQL)] — به‌ترتیب و فقط یک بار اجرا می‌شوند
    init: Callable | None = None       # پس از مهاجرت‌ها (مثلاً بارگذاری داده‌ی اولیه)
    health: Callable | None = None     # ← (ok: bool, پیام)
    nav: list = field(default_factory=list)          # برای مستندات؛ منوی رابط در app.js با mod مشخص می‌شود
    tables: list = field(default_factory=list)       # جدول‌های متعلق به ماژول (برای مستندات و پاک‌سازی)
    paths: list = field(default_factory=list)        # الگوهای مسیر API که به این ماژول تعلق دارند [(روش‌ها، regex)]
    builtin: bool = False
    status: str = "ok"                 # ok | error
    error: str = ""
    on_toggle: Callable | None = None  # هنگام روشن/خاموش شدن


REGISTRY: dict[str, Module] = {}
_PATH_RULES: list[tuple[set | None, re.Pattern, str]] = []
_loaded = False


def register(m: Module) -> Module:
    REGISTRY[m.id] = m
    for methods, rx in m.paths:
        _PATH_RULES.append((set(methods) if methods else None, re.compile(rx), m.id))
    return m


def get(mid: str) -> Module | None:
    return REGISTRY.get(mid)


def module_for_path(method: str, path: str) -> str | None:
    for methods, rx, mid in _PATH_RULES:
        if (methods is None or method in methods) and rx.search(path):
            return mid
    return None


def _flags() -> dict:
    try:
        return db.get_settings().get("modules") or {}
    except Exception:  # noqa: BLE001 — پیش از آماده شدن پایگاه داده
        return {}


def is_enabled(mid: str, _seen: set | None = None) -> bool:
    m = REGISTRY.get(mid)
    if not m:
        return False
    if m.status != "ok":
        return False
    if m.core:
        return True
    on = _flags().get(mid, m.default_enabled)
    if not on:
        return False
    seen = (_seen or set()) | {mid}
    return all(r in seen or is_enabled(r, seen) for r in m.requires)


def require(mid: str):
    """برای کدهایی که خارج از مسیرهای HTTP به ماژول نیاز دارند."""
    if not is_enabled(mid):
        m = REGISTRY.get(mid)
        raise ValueError(f"ماژول «{m.name if m else mid}» غیرفعال است. از «سیستم ← ماژول‌ها» فعالش کنید.")


def set_enabled(mid: str, on: bool) -> dict:
    m = REGISTRY.get(mid)
    if not m:
        raise ValueError("ماژول پیدا نشد.")
    if m.core and not on:
        raise ValueError("ماژول‌های هسته قابل غیرفعال کردن نیستند.")
    if on:
        missing = [r for r in m.requires if not is_enabled(r)]
        if missing:
            names = "، ".join(REGISTRY[r].name if r in REGISTRY else r for r in missing)
            raise ValueError(f"اول این ماژول‌ها را فعال کنید: {names}")
    flags = dict(_flags())
    flags[mid] = bool(on)
    db.set_settings({"modules": flags})
    if m.on_toggle:
        try:
            m.on_toggle(bool(on))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    db.log("system", None, f"ماژول «{m.name}» {'فعال' if on else 'غیرفعال'} شد.")
    return describe(m)


def describe(m: Module) -> dict:
    ok, msg = True, ""
    if m.status == "ok" and m.health and is_enabled(m.id):
        try:
            ok, msg = m.health()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, str(exc)
    dependents = [x.id for x in REGISTRY.values() if m.id in x.requires]
    return {"id": m.id, "name": m.name, "description": m.description, "version": m.version, "core": m.core, "builtin": m.builtin,
            "requires": list(m.requires), "dependents": dependents, "enabled": is_enabled(m.id),
            "switch": bool(_flags().get(m.id, m.default_enabled)) if not m.core else True,
            "status": m.status, "error": m.error, "healthy": ok, "health": msg, "tables": m.tables}


def status_list() -> list[dict]:
    order = {True: 0, False: 1}
    return [describe(m) for m in sorted(REGISTRY.values(), key=lambda x: (order[x.core], not x.builtin, x.id))]


def enabled_map() -> dict[str, bool]:
    return {mid: is_enabled(mid) for mid in REGISTRY}


# ---------------------------------------------------------------------------
# مهاجرت‌های نسخه‌دار هر ماژول
# ---------------------------------------------------------------------------

def _applied(mid: str) -> set[int]:
    return {r["version"] for r in db.q("SELECT version FROM schema_migrations WHERE module=?", [mid])}


def migrate(m: Module) -> None:
    done = _applied(m.id)
    for ver, sql in m.migrations:
        if ver in done:
            continue
        c = db.conn()
        with db._lock:  # noqa: SLF001
            try:
                c.commit()
                c.execute("BEGIN")
                for stmt in _split_sql(sql) if isinstance(sql, str) else []:
                    c.execute(stmt)
                if callable(sql):
                    sql(c)
                c.execute("INSERT INTO schema_migrations(module, version, applied_at) VALUES(?,?,?)", [m.id, ver, db.now()])
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise


def _split_sql(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


# ---------------------------------------------------------------------------
# بارگذاری
# ---------------------------------------------------------------------------

def load_all() -> None:
    """ماژول‌های داخلی و بسته‌ای را ثبت می‌کند، مهاجرت‌هایشان را اجرا می‌کند و init را صدا می‌زند."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import builtin  # noqa: F401 — ثبت ماژول‌های داخلی
    pkg_path = __path__  # type: ignore[name-defined]
    for info in sorted(pkgutil.iter_modules(pkg_path), key=lambda x: x.name):
        if not info.ispkg:
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
            m = getattr(mod, "MODULE", None)
            if isinstance(m, Module) and m.id not in REGISTRY:
                register(m)
        except Exception as exc:  # noqa: BLE001 — ماژول خراب، بقیه کار کنند
            traceback.print_exc()
            register(Module(id=info.name, name=info.name, description="بارگذاری این ماژول ناموفق بود.", status="error",
                            error=f"{type(exc).__name__}: {exc}"))
    for m in REGISTRY.values():
        if m.status != "ok":
            continue
        try:
            migrate(m)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            m.status, m.error = "error", f"مهاجرت پایگاه داده: {exc}"
            continue
    for m in REGISTRY.values():
        if m.status == "ok" and m.init:
            try:
                m.init()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                m.status, m.error = "error", f"راه‌اندازی: {exc}"
