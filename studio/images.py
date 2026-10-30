"""دانلود تصاویر، حذف پس‌زمینه (rembg یا موتور داخلی ONNX) و ترازبندی سوژه روی بوم نهایی."""
from __future__ import annotations

import io
import mimetypes
import os
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

from . import align as align_mod
from . import db
from .config import MODELS_DIR

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif", ".jfif"}

MODELS: dict[str, dict] = {
    "isnet-general-use": {"label": "ISNet عمومی — کیفیت بالا برای عکس محصول (پیشنهادی)", "size": 1024,
                          "mean": (0.5, 0.5, 0.5), "std": (1.0, 1.0, 1.0), "mb": 170},
    "u2net": {"label": "U²-Net — متعادل", "size": 320, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "mb": 168},
    "u2netp": {"label": "U²-Net سبک — سریع با دقت کمتر", "size": 320, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "mb": 4},
    "birefnet-general": {"label": "BiRefNet — دقیق‌ترین، کند روی CPU", "size": 1024, "mean": (0.485, 0.456, 0.406),
                         "std": (0.229, 0.224, 0.225), "mb": 928, "sigmoid": True},
    "birefnet-general-lite": {"label": "BiRefNet سبک — دقیق و سریع‌تر", "size": 1024, "mean": (0.485, 0.456, 0.406),
                              "std": (0.229, 0.224, 0.225), "mb": 214, "sigmoid": True},
}
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/{name}.onnx"


_REMBG_OK: bool | None = None


def rembg_available() -> bool:
    """فقط وجود بسته بررسی می‌شود (بدون import سنگین) تا صفحه‌ها در شروع کار معطل نمانند."""
    global _REMBG_OK
    if _REMBG_OK is None:
        import importlib.util
        try:
            _REMBG_OK = importlib.util.find_spec("rembg") is not None
        except Exception:  # noqa: BLE001
            _REMBG_OK = False
    return _REMBG_OK


def warmup():
    """بارگذاری پیش‌دستانه‌ی کتابخانه‌های سنگین در پس‌زمینه (اولین import در ویندوز ممکن است ده‌ها ثانیه طول بکشد)."""
    global _REMBG_OK
    if rembg_available():
        try:
            import rembg  # noqa: F401
        except Exception:  # noqa: BLE001
            _REMBG_OK = False


def model_status() -> list[dict]:
    out = []
    for name, m in MODELS.items():
        p = MODELS_DIR / f"{name}.onnx"
        out.append({"name": name, "label": m["label"], "mb": m["mb"], "installed": p.exists() and p.stat().st_size > 1_000_000,
                    "path": str(p)})
    return out


_download_state: dict = {}


def download_model(name: str) -> dict:
    if name not in MODELS:
        raise ValueError("مدل ناشناخته است.")
    if _download_state.get(name, {}).get("status") == "running":
        return _download_state[name]
    st = _download_state[name] = {"status": "running", "done": 0, "total": 0, "error": ""}

    def work():
        tmp = MODELS_DIR / f"{name}.onnx.part"
        try:
            with requests.get(MODEL_URL.format(name=name), stream=True, timeout=60) as r:
                r.raise_for_status()
                st["total"] = int(r.headers.get("content-length", 0))
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                        st["done"] += len(chunk)
            tmp.replace(MODELS_DIR / f"{name}.onnx")
            st["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            st["status"] = "error"
            st["error"] = str(exc)
            tmp.unlink(missing_ok=True)

    threading.Thread(target=work, daemon=True).start()
    return st


def download_state(name: str) -> dict:
    return _download_state.get(name, {"status": "idle"})


def ensure_model(name: str) -> Path:
    """اگر فایل مدل نباشد، همین‌جا (به‌صورت همگام) دانلودش می‌کند."""
    p = MODELS_DIR / f"{name}.onnx"
    if p.exists() and p.stat().st_size > 1_000_000:
        return p
    tmp = MODELS_DIR / f"{name}.onnx.part"
    try:
        with requests.get(MODEL_URL.format(name=name), stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        tmp.replace(p)
        return p
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"فایل مدل «{name}» در پوشه‌ی مدل‌ها نیست و دانلود خودکارش هم ممکن نشد ({exc}). "
                           f"فایل {name}.onnx را از {MODEL_URL.format(name=name)} بگیرید و در {MODELS_DIR} بگذارید.") from exc


# ---------------------------------------------------------------------------
# حذف پس‌زمینه
# ---------------------------------------------------------------------------

class BgRemover:
    def __init__(self, model: str = "isnet-general-use", engine: str = "auto"):
        self.model = model if model in MODELS else "isnet-general-use"
        self.engine = engine
        self._rembg_session = None
        self._ort = None
        self.engine_used = ""

    def _ensure(self):
        if self._rembg_session or self._ort:
            return
        if self.engine in ("auto", "rembg") and rembg_available():
            try:
                from rembg import new_session
                self._rembg_session = new_session(self.model)
                self.engine_used = "rembg"
                return
            except Exception:  # noqa: BLE001
                if self.engine == "rembg":
                    raise
        p = ensure_model(self.model)
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads = max(1, (os.cpu_count() or 2) // 2)
        self._ort = ort.InferenceSession(str(p), sess_options=so, providers=["CPUExecutionProvider"])
        self.engine_used = "builtin"

    def mask(self, img: Image.Image) -> Image.Image:
        import numpy as np
        m = MODELS[self.model]
        size = (m["size"], m["size"])
        im = img.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        arr = np.array(im).astype(np.float32)
        arr = arr / max(float(arr.max()), 1e-6)
        mean, std = m["mean"], m["std"]
        x = np.zeros_like(arr)
        for c in range(3):
            x[:, :, c] = (arr[:, :, c] - mean[c]) / std[c]
        x = np.expand_dims(x.transpose((2, 0, 1)), 0).astype(np.float32)
        out = self._ort.run(None, {self._ort.get_inputs()[0].name: x})
        pred = out[0][:, 0, :, :]
        if m.get("sigmoid"):
            pred = 1 / (1 + np.exp(-pred))
        ma, mi = float(pred.max()), float(pred.min())
        pred = (pred - mi) / max(ma - mi, 1e-6)
        mask = Image.fromarray((np.squeeze(pred) * 255).astype("uint8"), mode="L")
        return mask.resize(img.size, Image.Resampling.LANCZOS)

    def remove(self, img: Image.Image) -> Image.Image:
        self._ensure()
        img = ImageOps.exif_transpose(img)
        if self._rembg_session is not None:
            from rembg import remove
            out = remove(img, session=self._rembg_session)
            return out.convert("RGBA")
        mask = self.mask(img)
        rgba = img.convert("RGBA")
        empty = Image.new("RGBA", img.size, (0, 0, 0, 0))
        return Image.composite(rgba, empty, mask)


def fit_square(img: Image.Image, size: int = 1280, padding_pct: float = 6, background=None) -> Image.Image:
    """سازگاری با نسخه‌های قبل؛ ترازبندی با حاشیه‌ی درصدی."""
    out, _ = align_mod.align_image(img, align_mod.from_legacy(size, padding_pct))
    return out


# ---------------------------------------------------------------------------
# نام‌گذاری مرحله‌ها: feature_raw.jpg (خام) → feature_raw_rembg.png (میانی) → feature.png (نهایی)
# ---------------------------------------------------------------------------

RAW_SUFFIX = "_raw"
REMBG_SUFFIX = "_raw_rembg"


def stage_of(path: Path) -> tuple[str, str]:
    """(نام پایه، مرحله) — مرحله یکی از raw | rembg | final"""
    stem = Path(path).stem
    if stem.endswith(REMBG_SUFFIX):
        return stem[: -len(REMBG_SUFFIX)], "rembg"
    if stem.endswith(RAW_SUFFIX):
        return stem[: -len(RAW_SUFFIX)], "raw"
    return stem, "final"


def is_intermediate(path: Path) -> bool:
    return stage_of(path)[1] != "final"


def process_file(src: Path, dst: Path, remover: "BgRemover | None", size: int = 1280, padding: float = 6,
                 align: dict | None | bool = None, intermediate: Path | None = None, reuse_intermediate: bool = True) -> dict:
    """حذف پس‌زمینه (اختیاری) و ترازبندی (اختیاری).

    align=None → رفتار نسخه‌های قبل (بوم مربعی با حاشیه‌ی درصدی)
    align=False → بدون ترازبندی؛ فقط حذف پس‌زمینه با اندازه‌ی اصلی
    align=dict → تنظیمات ترازبندی (studio.align)
    intermediate → مسیر ذخیره‌ی خروجی میانیِ حذف پس‌زمینه (مثلاً feature_raw_rembg.png). اگر از قبل وجود داشته باشد،
                   حذف پس‌زمینه دوباره اجرا نمی‌شود (مثلاً وقتی فقط قاعده‌ی ترازبندی عوض شده است).
    """
    work = None
    if remover is not None and intermediate is not None and reuse_intermediate and Path(intermediate).exists():
        with Image.open(intermediate) as im:
            im.load()
            work = im.convert("RGBA")
    if work is None:
        with Image.open(src) as im:
            im.load()
            if getattr(im, "is_animated", False):
                im.seek(0)
            work = remover.remove(im) if remover is not None else ImageOps.exif_transpose(im).convert("RGBA")
        if remover is not None and intermediate is not None and align is not False:
            align_mod.save_image(work, intermediate, {"format": "png"})
    if align is False:
        align_mod.save_image(work, dst, {"format": "png"})
        return {}
    opts = align_mod.from_legacy(size, padding) if align is None else align_mod.normalize(align)
    out, info = align_mod.align_image(work, {**opts, "_normalized": True})
    align_mod.save_image(out, dst, opts)
    return info


def list_images(root: Path, exclude: Path | None = None) -> list[Path]:
    files = []
    for dp, dn, fn in os.walk(root):
        dpp = Path(dp)
        if exclude and (dpp == exclude or exclude in dpp.parents):
            dn[:] = []
            continue
        dn.sort()
        for f in sorted(fn):
            if Path(f).suffix.lower() in IMAGE_EXTS:
                files.append(dpp / f)
    return files


def pick_sources(files: list[Path], rembg: bool) -> list[Path]:
    """از هر تصویر (مثلاً feature) فقط یک نسخه پردازش می‌شود.

    با حذف پس‌زمینه: خام (feature_raw) ← بدون پسوند ← میانی؛ فقط ترازبندی: میانی (feature_raw_rembg) ← خام ← بدون پسوند.
    """
    order = {"raw": 0, "final": 1, "rembg": 2} if rembg else {"rembg": 0, "raw": 1, "final": 2}
    best: dict[tuple, Path] = {}
    for f in files:
        base, st = stage_of(f)
        k = (str(f.parent), base)
        if k not in best or order[st] < order[stage_of(best[k])[1]]:
            best[k] = f
    return sorted(best.values(), key=str)


def default_bg_output(input_path: Path, rembg: bool = True) -> Path:
    return input_path.parent / ("rembg" if rembg else "aligned") / input_path.name


# ---------------------------------------------------------------------------
# کار حذف پس‌زمینه برای یک مسیر
# ---------------------------------------------------------------------------

class BgJobs:
    def __init__(self):
        self.cancel: dict[int, bool] = {}
        self.threads: dict[int, threading.Thread] = {}

    def recover(self):
        db.ex("UPDATE bg_jobs SET status='paused' WHERE status IN ('running','pending')")

    def create(self, input_path: str, output_path: str | None, options: dict) -> int:
        inp = Path(input_path).expanduser()
        if not inp.exists() or not inp.is_dir():
            raise ValueError("مسیر ورودی وجود ندارد یا پوشه نیست.")
        if not options.get("rembg", True) and not options.get("align"):
            raise ValueError("دست‌کم یکی از «حذف پس‌زمینه» یا «ترازبندی» را انتخاب کنید.")
        if options.get("align"):
            options["align"] = align_mod.normalize(options["align"])
        out = Path(output_path).expanduser() if output_path else default_bg_output(inp, options.get("rembg", True))
        if out.resolve() == inp.resolve():
            raise ValueError("مسیر خروجی نباید همان مسیر ورودی باشد.")
        jid = db.ex("INSERT INTO bg_jobs(input_path, output_path, options, status, created_at) VALUES(?,?,?,?,?)",
                    [str(inp), str(out), db.jdump(options), "pending", db.now()])
        self.start(jid)
        return jid

    def start(self, jid: int):
        if self.threads.get(jid) and self.threads[jid].is_alive():
            return
        self.cancel[jid] = False
        t = threading.Thread(target=self._run, args=(jid,), daemon=True)
        self.threads[jid] = t
        t.start()

    def stop(self, jid: int):
        self.cancel[jid] = True

    def _run(self, jid: int, on_file=None):
        job = db.q1("SELECT * FROM bg_jobs WHERE id=?", [jid])
        opts = db.jload(job["options"], {})
        inp, out = Path(job["input_path"]), Path(job["output_path"])
        db.update("bg_jobs", jid, status="running", error="")
        try:
            files = pick_sources(list_images(inp, exclude=out), bool(opts.get("rembg", True)))
            db.update("bg_jobs", jid, progress_total=len(files))
            use_rembg = opts.get("rembg", True)
            remover = BgRemover(opts.get("model", "isnet-general-use"), opts.get("engine", "auto")) if use_rembg else None
            # کارهای قدیمی: بدون کلید align → بوم مربعی با حاشیه‌ی درصدی
            align = opts["align"] if "align" in opts else None
            suffix = align_mod.out_suffix(align) if isinstance(align, dict) else ".png"
            done = failed = 0
            stats = {"upscaled": 0, "low_res": 0, "empty": 0}
            for f in files:
                if self.cancel.get(jid):
                    db.update("bg_jobs", jid, status="paused")
                    return
                rel = f.relative_to(inp)
                base, _stage = stage_of(f)
                dst = out / rel.parent / f"{base}{suffix}"  # خروجی نهایی: feature.png
                inter = (out / rel.parent / f"{base}{REMBG_SUFFIX}.png") if (remover and align is not False and opts.get("keep_intermediate", True)) else None
                try:
                    if not dst.exists() or opts.get("overwrite"):
                        info = process_file(f, dst, remover, int(opts.get("size", 1280)), float(opts.get("padding", 6)), align,
                                            intermediate=inter, reuse_intermediate=not opts.get("redo_rembg"))
                        for k in stats:
                            stats[k] += 1 if info.get(k) else 0
                        if info.get("low_res"):
                            db.log("bg", jid, f"سوژه بیش از ۲٫۵ برابر بزرگ شد و ممکن است تار باشد: {rel}", level="warning", step="align")
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    db.log("bg", jid, f"پردازش ناموفق: {rel}", level="warning", step="rembg", detail=str(exc))
                    if "پوشه‌ی مدل‌ها" in str(exc):
                        raise
                db.update("bg_jobs", jid, progress_done=done + failed, failed=failed, last_file=str(dst))
                if on_file:
                    on_file(done + failed, len(files))
            db.update("bg_jobs", jid, status="completed", finished_at=db.now(),
                      options={**opts, "engine_used": remover.engine_used if remover else "", "stats": stats})
            what = "حذف پس‌زمینه و ترازبندی" if remover and align is not False else ("حذف پس‌زمینه" if remover else "ترازبندی")
            db.log("bg", jid, f"{what} تمام شد: {done} تصویر، {failed} ناموفق.", level="success", step="rembg")
        except Exception as exc:  # noqa: BLE001
            db.update("bg_jobs", jid, status="error", error=str(exc))
            db.log("bg", jid, "حذف پس‌زمینه با خطا متوقف شد.", level="error", step="rembg", detail=traceback.format_exc())


BG_JOBS = BgJobs()


# ---------------------------------------------------------------------------
# دانلود تصویر
# ---------------------------------------------------------------------------

def guess_ext(url: str, content_type: str = "") -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in IMAGE_EXTS:
        return ".jpg" if ext == ".jfif" else ext
    if content_type:
        e = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if e:
            return ".jpg" if e in (".jpe", ".jfif") else e
    return ".jpg"


def download_image(session: requests.Session, url: str, dst_no_ext: Path, retries: int = 3, referer: str = "") -> Path:
    existing = [p for p in dst_no_ext.parent.glob(dst_no_ext.name + ".*") if p.suffix.lower() in IMAGE_EXTS]
    if existing:
        return existing[0]
    local = url[7:] if url.startswith("file://") else url
    if not url.startswith(("http://", "https://")) and Path(local).is_file():
        # تصویر محلی (مثلاً تولیدشده با هوش مصنوعی)
        import shutil
        dst = dst_no_ext.with_suffix(Path(local).suffix.lower() or ".png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dst)
        return dst
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=40, headers={"Referer": referer} if referer else None)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "")
            data = r.content
            ext = guess_ext(url, ctype)
            if ext in (".webp", ".avif") or "webp" in ctype or "avif" in ctype:
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        buf = io.BytesIO()
                        has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
                        if has_alpha:
                            im.save(buf, "PNG")
                            ext = ".png"
                        else:
                            im.convert("RGB").save(buf, "JPEG", quality=95)
                            ext = ".jpg"
                        data = buf.getvalue()
                except Exception:  # noqa: BLE001
                    pass
            dst = dst_no_ext.with_suffix(ext)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(dst)
            return dst
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"دانلود تصویر ناموفق: {last}")
