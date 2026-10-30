"""ترازبندی تصاویر محصول.

۱) «تریم»: فضای خالی دور سوژه (پیکسل‌های شفاف، یا رنگ یکدست پس‌زمینه در تصاویر بدون شفافیت) شناسایی و بریده می‌شود.
۲) سوژه بدون تغییر نسبت ابعاد آن‌قدر بزرگ یا کوچک می‌شود که بُعدی که زودتر به حاشیه‌ی تعیین‌شده می‌رسد دقیقاً
   با فاصله‌ی مشخص (مثلاً ۶۰ یا ۱۰۰ پیکسل) از لبه‌ی بوم نهایی قرار بگیرد؛ بُعد دیگر به همان نسبت تغییر می‌کند.
۳) سوژه در مرکز ناحیه‌ی داخلی بوم (مثلاً ۱۲۸۰×۱۲۸۰) قرار می‌گیرد.
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

TRIM_MODES = ("auto", "alpha", "color", "none")
FORMATS = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}

DEFAULT_ALIGN = {
    "canvas_w": 1280,            # عرض بوم نهایی
    "canvas_h": 1280,            # ارتفاع بوم نهایی
    "margin": 60,                # فاصله‌ی سوژه تا لبه‌های بوم (پیکسل)
    "per_side": False,           # فاصله‌ی جداگانه برای هر لبه
    "margin_top": 60, "margin_right": 60, "margin_bottom": 60, "margin_left": 60,
    "trim": "auto",              # auto: شفافیت، و اگر تصویر شفافیت نداشت رنگ پس‌زمینه | alpha | color | none
    "alpha_threshold": 10,       # پیکسل‌های با شفافیت کمتر از این مقدار «خالی» حساب می‌شوند (۰ تا ۲۵۴)
    "color_tolerance": 18,       # اختلاف مجاز با رنگ پس‌زمینه در حالت رنگ (۰ تا ۱۰۰)
    "despeckle": 2,              # لکه‌ها و نویزهای جداافتاده‌ی کوچک‌تر از این اندازه (پیکسل) در تشخیص مرز نادیده گرفته می‌شوند
    "upscale": True,             # سوژه‌های کوچک هم بزرگ شوند تا به حاشیه برسند
    "background": "auto",        # auto | transparent | #rrggbb
    "format": "png",             # png | jpg | webp
    "quality": 92,
}


def _int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def normalize(opts: dict | None, base: dict | None = None) -> dict:
    """ادغام با پیش‌فرض‌ها و اعتبارسنجی."""
    o = {**DEFAULT_ALIGN, **(base or {}), **{k: v for k, v in (opts or {}).items() if v is not None and v != ""}}
    o["canvas_w"] = _int(o["canvas_w"], 16, 8000, 1280)
    o["canvas_h"] = _int(o["canvas_h"], 16, 8000, 1280)
    o["margin"] = _int(o["margin"], 0, 4000, 60)
    o["per_side"] = bool(o.get("per_side"))
    for s in ("top", "right", "bottom", "left"):
        k = f"margin_{s}"
        o[k] = _int(o.get(k), 0, 4000, o["margin"]) if o["per_side"] else o["margin"]
    if o["canvas_w"] - o["margin_left"] - o["margin_right"] < 8 or o["canvas_h"] - o["margin_top"] - o["margin_bottom"] < 8:
        raise ValueError("حاشیه‌ها از اندازه‌ی بوم بزرگ‌ترند؛ حاشیه را کم یا بوم را بزرگ کنید.")
    o["trim"] = o["trim"] if o["trim"] in TRIM_MODES else "auto"
    o["alpha_threshold"] = _int(o["alpha_threshold"], 0, 254, 10)
    o["color_tolerance"] = _int(o["color_tolerance"], 0, 100, 18)
    o["despeckle"] = _int(o["despeckle"], 0, 20, 2)
    o["upscale"] = o["upscale"] not in (False, 0, "0", "false")
    bg = str(o.get("background") or "auto").strip().lower()
    if bg == "white":
        bg = "#ffffff"
    if bg not in ("auto", "transparent") and not re.fullmatch(r"#[0-9a-f]{6}", bg):
        bg = "auto"
    o["background"] = bg
    o["format"] = o["format"] if o["format"] in FORMATS else "png"
    o["quality"] = _int(o["quality"], 40, 100, 92)
    return o


def from_legacy(size: int, padding_pct: float) -> dict:
    """تبدیل تنظیمات نسخه‌های قبل (درصد حاشیه) به تنظیمات ترازبندی."""
    return normalize({"canvas_w": size, "canvas_h": size, "margin": round(size * float(padding_pct) / 100), "trim": "alpha",
                      "alpha_threshold": 8, "despeckle": 0, "background": "transparent"})


def out_suffix(o: dict) -> str:
    return FORMATS.get((o or {}).get("format", "png"), ".png")


# ---------------------------------------------------------------------------
# تشخیص سوژه
# ---------------------------------------------------------------------------

def _corner_bg(rgb: np.ndarray, tol: int) -> tuple[tuple[int, int, int], int]:
    h, w = rgb.shape[:2]
    k = max(1, min(h, w) // 100)
    patches = [rgb[:k, :k], rgb[:k, w - k:], rgb[h - k:, :k], rgb[h - k:, w - k:]]
    cols = [np.median(p.reshape(-1, 3), axis=0) for p in patches]
    # رنگی که بیشترین گوشه‌ها با آن هم‌رنگ‌اند
    best, score = cols[0], -1
    for c in cols:
        s = sum(1 for d in cols if np.abs(c - d).max() <= max(tol, 6))
        if s > score:
            best, score = c, s
    return tuple(int(x) for x in best), score


def subject_mask(rgba: Image.Image, o: dict) -> tuple[np.ndarray | None, str, tuple | None]:
    arr = np.asarray(rgba)
    a = arr[..., 3]
    mode = o["trim"]
    if mode == "none":
        return None, "none", None
    has_alpha = int(a.min()) < 250
    if mode == "alpha" or (mode == "auto" and has_alpha):
        return a > o["alpha_threshold"], "alpha", None
    tol = round(o["color_tolerance"] * 2.55)
    rgb = arr[..., :3].astype(np.int16)
    bg, agree = _corner_bg(rgb, tol)
    if agree < 3:
        # گوشه‌ها هم‌رنگ نیستند؛ پس‌زمینه‌ی یکدستی وجود ندارد (مثلاً عکس لبه‌به‌لبه) → بدون تریم
        return None, "none", None
    diff = np.abs(rgb - np.array(bg, dtype=np.int16)).max(axis=2)
    mask = (diff > tol) & (a > o["alpha_threshold"])
    return mask, "color", bg


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    rows = np.flatnonzero(mask.any(axis=1))
    if not rows.size:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def subject_bbox(mask: np.ndarray, despeckle: int) -> tuple[int, int, int, int] | None:
    raw = _bbox(mask)
    if not raw or despeckle <= 0:
        return raw
    k = 2 * despeckle + 1
    m = Image.fromarray((mask * 255).astype(np.uint8))
    # برای سرعت روی تصاویر بزرگ، تشخیص لکه روی نسخه‌ی کوچک‌شده انجام می‌شود
    W, H = m.size
    f = max(1.0, max(W, H) / 1600)
    if f > 1:
        m = m.resize((max(1, round(W / f)), max(1, round(H / f))), Image.Resampling.BOX).point(lambda v: 255 if v > 127 else 0)
        k = max(3, 2 * max(1, round(despeckle / f)) + 1)
    opened = m.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
    ob = opened.getbbox()
    if not ob:
        return raw  # سوژه از اندازه‌ی لکه هم کوچک‌تر است
    pad = despeckle + 1
    x0, y0, x1, y1 = (round(ob[0] * f) - pad, round(ob[1] * f) - pad, round(ob[2] * f) + pad, round(ob[3] * f) + pad)
    # کادر نهایی: کادر بدون لکه، محدود به کادر واقعی پیکسل‌ها و سپس چسبیده به پیکسل‌های واقعی داخل آن
    x0, y0, x1, y1 = max(x0, raw[0]), max(y0, raw[1]), min(x1, raw[2]), min(y1, raw[3])
    tight = _bbox(mask[y0:y1, x0:x1])
    if not tight:
        return raw
    return x0 + tight[0], y0 + tight[1], x0 + tight[2], y0 + tight[3]


# ---------------------------------------------------------------------------
# ترازبندی
# ---------------------------------------------------------------------------

def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def align_image(img: Image.Image, opts: dict | None = None) -> tuple[Image.Image, dict]:
    o = opts if opts and opts.get("_normalized") else {**normalize(opts), "_normalized": True}
    img = ImageOps.exif_transpose(img)
    if getattr(img, "is_animated", False):
        img.seek(0)
    rgba = img.convert("RGBA")
    W0, H0 = rgba.size
    mask, method, bgc = subject_mask(rgba, o)
    bbox = subject_bbox(mask, o["despeckle"]) if mask is not None else None
    empty = mask is not None and bbox is None
    if not bbox:
        # چیزی جز پس‌زمینه پیدا نشد (مثلاً تصویر یکدست) → کل تصویر سوژه است
        bbox = (0, 0, W0, H0)
        if method == "color":
            method, bgc = "none", None
    sub = rgba.crop(bbox)
    w, h = sub.size
    CW, CH = o["canvas_w"], o["canvas_h"]
    l, t, r, b = o["margin_left"], o["margin_top"], o["margin_right"], o["margin_bottom"]
    aw, ah = CW - l - r, CH - t - b
    sx, sy = aw / w, ah / h
    scale = min(sx, sy)  # بُعدی که زودتر به حاشیه می‌رسد تعیین‌کننده است؛ نسبت ابعاد ثابت می‌ماند
    limited_by = "width" if sx <= sy else "height"
    if not o["upscale"]:
        scale = min(scale, 1.0)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    if (nw, nh) != (w, h):
        sub = sub.convert("RGBa").resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")
    x = l + round((aw - nw) / 2)
    y = t + round((ah - nh) / 2)

    bg = o["background"]
    if bg == "auto":
        fill = (*bgc, 255) if method == "color" and bgc else (0, 0, 0, 0)
    elif bg == "transparent":
        fill = (0, 0, 0, 0)
    else:
        fill = (*_hex(bg), 255)
    if o["format"] == "jpg" and fill[3] == 0:
        fill = (255, 255, 255, 255)
    canvas = Image.new("RGBA", (CW, CH), fill)
    canvas.alpha_composite(sub, (x, y))
    info = {
        "source_size": [W0, H0], "trim": method, "bbox": list(bbox), "trimmed": [W0 - w, H0 - h] if method != "none" else [0, 0],
        "subject_size": [w, h], "scale": round(scale, 4), "limited_by": limited_by, "placed": [x, y, nw, nh],
        "canvas": [CW, CH], "margins": [t, r, b, l], "upscaled": scale > 1.0001, "low_res": scale > 2.5, "empty": empty,
        "background_color": "#%02x%02x%02x" % bgc if bgc else None,
    }
    return canvas, info


def save_image(img: Image.Image, dst: Path, o: dict) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fmt = o.get("format", "png")
    tmp = dst.with_name(dst.name + ".tmp")
    if fmt == "jpg":
        img.convert("RGB").save(tmp, "JPEG", quality=o.get("quality", 92), optimize=True, progressive=True)
    elif fmt == "webp":
        img.save(tmp, "WEBP", quality=o.get("quality", 92), method=5)
    else:
        img.save(tmp, "PNG", optimize=True)
    tmp.replace(dst)
    return dst


def align_file(src: Path, dst: Path, opts: dict) -> dict:
    with Image.open(src) as im:
        im.load()
        out, info = align_image(im, opts)
    save_image(out, dst, opts)
    return info


# ---------------------------------------------------------------------------
# پیش‌نمایش
# ---------------------------------------------------------------------------

def _thumb_data_url(img: Image.Image, size: int = 360, keep_alpha: bool = True) -> str:
    im = img.copy()
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if keep_alpha:
        im.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    im.convert("RGB").save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def preview_image(img: Image.Image, opts: dict, remover=None, name: str = "") -> dict:
    o = {**normalize(opts), "_normalized": True}
    src = ImageOps.exif_transpose(img)
    work = remover.remove(src) if remover is not None else src
    out, info = align_image(work, o)
    before = work.convert("RGBA")
    # کادر سوژه روی تصویر «قبل» (به درصد) برای نمایش ناحیه‌ی بریده‌شده
    W0, H0 = info["source_size"]
    x0, y0, x1, y1 = info["bbox"]
    info["bbox_pct"] = [round(x0 / W0 * 100, 2), round(y0 / H0 * 100, 2), round((x1 - x0) / W0 * 100, 2), round((y1 - y0) / H0 * 100, 2)]
    return {"name": name, "before": _thumb_data_url(before), "after": _thumb_data_url(out), "info": info}


def decode_data_url(s: str) -> Image.Image:
    data = s.split(",", 1)[1] if s.startswith("data:") else s
    im = Image.open(io.BytesIO(base64.b64decode(data)))
    im.load()
    return im
