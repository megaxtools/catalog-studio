"""پشتیبان‌گیری و بازگردانی پایگاه داده‌ی استودیو.

- پشتیبان با API پشتیبان‌گیری SQLite ساخته می‌شود (در حین کار هم سازگار و کامل است) و در data/backups ذخیره می‌شود.
- به‌صورت پیش‌فرض روزی یک بار هنگام شروع استودیو پشتیبان خودکار گرفته می‌شود و فقط آخرین N پشتیبان نگه داشته می‌شود.
- بازگردانی امن است: فایل انتخاب‌شده آماده می‌شود و در شروع بعدی استودیو جایگزین پایگاه داده‌ی فعلی می‌شود
  (قبلش از وضعیت فعلی هم یک پشتیبان گرفته می‌شود).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from . import db
from .config import BACKUP_DIR, DB_PATH, VERSION, WORKBENCH_DIR

PENDING = BACKUP_DIR / "restore_pending.db"


def create(note: str = "", with_images: bool = False, auto: bool = False) -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"studio-{'auto-' if auto else ''}{stamp}"
    tmpdb = BACKUP_DIR / f"{name}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmpdb)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    zp = BACKUP_DIR / f"{name}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmpdb, "studio.db")
        z.writestr("backup.json", json.dumps({"version": VERSION, "created_at": db.now(), "note": note, "with_images": with_images,
                                              "auto": auto}, ensure_ascii=False, indent=2))
        if with_images and WORKBENCH_DIR.exists():
            for f in WORKBENCH_DIR.rglob("*"):
                if f.is_file():
                    z.write(f, "workbench/" + f.relative_to(WORKBENCH_DIR).as_posix())
    tmpdb.unlink(missing_ok=True)
    prune()
    db.log("system", None, f"پشتیبان «{zp.name}» ساخته شد.", level="success")
    return info(zp)


def info(p: Path) -> dict:
    meta = {}
    try:
        with zipfile.ZipFile(p) as z:
            meta = json.loads(z.read("backup.json").decode("utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {"name": p.name, "path": str(p), "size": p.stat().st_size, "created_at": meta.get("created_at"), "version": meta.get("version"),
            "note": meta.get("note", ""), "auto": meta.get("auto", False), "with_images": meta.get("with_images", False)}


def list_backups() -> dict:
    files = sorted(BACKUP_DIR.glob("studio-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    return {"backups": [info(p) for p in files], "pending_restore": PENDING.exists(), "dir": str(BACKUP_DIR)}


def prune():
    keep = int(db.get_settings().get("backup_keep") or 10)
    autos = sorted(BACKUP_DIR.glob("studio-auto-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in autos[keep:]:
        p.unlink(missing_ok=True)


def auto_daily():
    if not db.get_settings().get("backup_auto", True):
        return None
    today = datetime.now().strftime("%Y%m%d")
    if any(today in p.name for p in BACKUP_DIR.glob("studio-auto-*.zip")):
        return None
    try:
        return create(note="پشتیبان خودکار روزانه", auto=True)
    except Exception:  # noqa: BLE001
        return None


def schedule_restore(name: str) -> dict:
    p = BACKUP_DIR / Path(name).name
    if not p.exists():
        raise ValueError("فایل پشتیبان پیدا نشد.")
    with zipfile.ZipFile(p) as z:
        if "studio.db" not in z.namelist():
            raise ValueError("این فایل پشتیبان معتبر نیست.")
        with z.open("studio.db") as fh, open(PENDING, "wb") as out:
            shutil.copyfileobj(fh, out)
        if any(n.startswith("workbench/") for n in z.namelist()):
            (BACKUP_DIR / "restore_pending_images.flag").write_text(p.name, encoding="utf-8")
    db.log("system", None, f"بازگردانی پشتیبان «{p.name}» برای شروع بعدی آماده شد.", level="warning")
    return {"ok": True, "message": "استودیو را ببندید و دوباره اجرا کنید تا پشتیبان بازگردانده شود."}


def cancel_restore() -> dict:
    PENDING.unlink(missing_ok=True)
    (BACKUP_DIR / "restore_pending_images.flag").unlink(missing_ok=True)
    return {"ok": True}


def apply_pending() -> bool:
    """پیش از باز شدن پایگاه داده (در شروع استودیو) صدا زده می‌شود."""
    if not PENDING.exists():
        return False
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if DB_PATH.exists():
        shutil.copyfile(DB_PATH, BACKUP_DIR / f"before-restore-{stamp}.db")
    for ext in ("-wal", "-shm"):
        Path(str(DB_PATH) + ext).unlink(missing_ok=True)
    shutil.move(str(PENDING), str(DB_PATH))
    flag = BACKUP_DIR / "restore_pending_images.flag"
    if flag.exists():
        src = BACKUP_DIR / flag.read_text(encoding="utf-8").strip()
        if src.exists():
            with zipfile.ZipFile(src) as z:
                for n in z.namelist():
                    if n.startswith("workbench/") and not n.endswith("/"):
                        out = WORKBENCH_DIR / n[len("workbench/"):]
                        out.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(n) as fh, open(out, "wb") as o:
                            shutil.copyfileobj(fh, o)
        flag.unlink(missing_ok=True)
    print("  پشتیبان انتخاب‌شده بازگردانده شد.")
    return True


def upload(data_url: str, name: str) -> dict:
    import base64
    raw = base64.b64decode(data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url)
    nm = Path(name).name
    if not nm.startswith("studio-"):
        nm = "studio-upload-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip"
    p = BACKUP_DIR / nm
    p.write_bytes(raw)
    try:
        with zipfile.ZipFile(p) as z:
            if "studio.db" not in z.namelist():
                raise ValueError
    except Exception:  # noqa: BLE001
        p.unlink(missing_ok=True)
        raise ValueError("فایل بارگذاری‌شده پشتیبان معتبر استودیو نیست.") from None
    return info(p)
