"""ماژول «ویرایشگر تصویر»: ویرایش غیرمخرب تصاویر محصولات.

ویرایش‌ها به‌صورت «دستور ویرایش» (recipe) ذخیره می‌شوند و فایل اصلی هرگز تغییر نمی‌کند؛ هر وقت لازم باشد تصویر
ویرایش‌شده از روی نسخه‌ی پیش از ویرایش (خام یا بدون پس‌زمینه) دوباره ساخته می‌شود. ترتیب اجرا:

    چرخش و قرینه ← پاک‌کن (حذف المان‌ها) ← برش ← رنگ (Hue)، اشباع، روشنایی، کنتراست ← پس‌زمینه‌ی رنگی (اختیاری)

مختصات پاک‌کن و برش در فضای تصویرِ چرخیده/قرینه‌شده و پیش از برش است (همان چیزی که ویرایشگر رابط نشان می‌دهد).
فیلترهای رنگ دقیقاً معادل فیلترهای CSS مرورگر پیاده شده‌اند تا پیش‌نمایش و نتیجه یکی باشد.
"""
from __future__ import annotations

import math

from .. import Module

try:
    import numpy as np
    from PIL import Image, ImageDraw
    _OK = True
except Exception:  # noqa: BLE001
    _OK = False


def _health():
    return (_OK, "آماده" if _OK else "کتابخانه‌ی Pillow یا numpy در دسترس نیست")


MODULE = Module(
    id="image_editor", name="ویرایشگر تصویر", version="1.0.0",
    description="برش، چرخش، قرینه، پاک‌کن برای حذف المان‌ها و تنظیم رنگ (Hue)، اشباع، روشنایی و کنتراست — غیرمخرب و برگشت‌پذیر.",
    health=_health,
)

EMPTY = {"rotate": 0, "flip_h": False, "flip_v": False, "erase": [], "crop": None,
         "adjust": {"hue": 0, "saturation": 100, "brightness": 100, "contrast": 100}, "bg": None}


def normalize(recipe: dict | None) -> dict | None:
    """دستور ویرایش معتبر یا None (یعنی بدون ویرایش)."""
    if not recipe:
        return None
    r = {**EMPTY, **{k: v for k, v in recipe.items() if k in EMPTY}}
    r["rotate"] = int(r.get("rotate") or 0) % 360
    if r["rotate"] not in (0, 90, 180, 270):
        raise ValueError("چرخش فقط مضرب ۹۰ درجه است.")
    adj = {**EMPTY["adjust"], **(r.get("adjust") or {})}
    r["adjust"] = {"hue": max(-180, min(180, float(adj["hue"]))), "saturation": max(0, min(300, float(adj["saturation"]))),
                   "brightness": max(0, min(300, float(adj["brightness"]))), "contrast": max(0, min(300, float(adj["contrast"])))}
    strokes = []
    for s in r.get("erase") or []:
        pts = [[float(p[0]), float(p[1])] for p in (s.get("points") or []) if len(p) >= 2]
        if pts:
            strokes.append({"size": max(1.0, min(2000.0, float(s.get("size") or 30))), "points": pts[:5000]})
    r["erase"] = strokes[:500]
    c = r.get("crop")
    if c:
        c = {k: float(c.get(k) or 0) for k in ("x", "y", "w", "h")}
        r["crop"] = c if c["w"] >= 2 and c["h"] >= 2 else None
    r["flip_h"], r["flip_v"] = bool(r.get("flip_h")), bool(r.get("flip_v"))
    bg = r.get("bg")
    r["bg"] = bg if isinstance(bg, str) and bg.startswith("#") and len(bg) in (4, 7) else None
    if r == EMPTY:
        return None
    return r


def summary(recipe: dict | None) -> str:
    r = normalize(recipe)
    if not r:
        return ""
    parts = []
    if r["rotate"]:
        parts.append(f"چرخش {r['rotate']}°")
    if r["flip_h"] or r["flip_v"]:
        parts.append("قرینه")
    if r["erase"]:
        parts.append(f"پاک‌کن ({len(r['erase'])})")
    if r["crop"]:
        parts.append("برش")
    a = r["adjust"]
    if a["hue"] or a["saturation"] != 100 or a["brightness"] != 100 or a["contrast"] != 100:
        parts.append("رنگ")
    if r["bg"]:
        parts.append("پس‌زمینه")
    return "، ".join(parts)


def _hue_matrix(deg: float):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return np.array([
        [0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928],
        [0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283],
        [0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072],
    ], dtype=np.float32)


def _sat_matrix(v: float):
    return np.array([
        [0.213 + 0.787 * v, 0.715 - 0.715 * v, 0.072 - 0.072 * v],
        [0.213 - 0.213 * v, 0.715 + 0.285 * v, 0.072 - 0.072 * v],
        [0.213 - 0.213 * v, 0.715 - 0.715 * v, 0.072 + 0.928 * v],
    ], dtype=np.float32)


def apply(img: "Image.Image", recipe: dict | None) -> "Image.Image":
    """اجرای دستور ویرایش روی تصویر RGBA."""
    r = normalize(recipe)
    img = img.convert("RGBA")
    if not r:
        return img
    if r["flip_h"]:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if r["flip_v"]:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if r["rotate"]:
        img = img.rotate(-r["rotate"], expand=True)  # چرخش ساعت‌گرد مثل رابط
    if r["erase"]:
        mask = Image.new("L", img.size, 255)
        d = ImageDraw.Draw(mask)
        for s in r["erase"]:
            w = int(round(s["size"]))
            pts = [tuple(p) for p in s["points"]]
            if len(pts) > 1:
                d.line(pts, fill=0, width=w, joint="curve")
            for (x, y) in pts:
                d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=0)
        alpha = img.getchannel("A")
        from PIL import ImageChops
        img.putalpha(ImageChops.multiply(alpha, mask))
    if r["crop"]:
        c = r["crop"]
        box = (max(0, int(round(c["x"]))), max(0, int(round(c["y"]))),
               min(img.width, int(round(c["x"] + c["w"]))), min(img.height, int(round(c["y"] + c["h"]))))
        if box[2] - box[0] >= 2 and box[3] - box[1] >= 2:
            img = img.crop(box)
    a = r["adjust"]
    if a["hue"] or a["saturation"] != 100 or a["brightness"] != 100 or a["contrast"] != 100:
        arr = np.asarray(img).astype(np.float32) / 255.0
        rgb, alpha = arr[..., :3], arr[..., 3:]
        # ترتیب مثل CSS: hue-rotate → saturate → brightness → contrast
        if a["hue"]:
            rgb = np.clip(rgb @ _hue_matrix(a["hue"]).T, 0, 1)
        if a["saturation"] != 100:
            rgb = np.clip(rgb @ _sat_matrix(a["saturation"] / 100).T, 0, 1)
        if a["brightness"] != 100:
            rgb = np.clip(rgb * (a["brightness"] / 100), 0, 1)
        if a["contrast"] != 100:
            k = a["contrast"] / 100
            rgb = np.clip((rgb - 0.5) * k + 0.5, 0, 1)
        img = Image.fromarray((np.concatenate([rgb, alpha], axis=-1) * 255 + 0.5).astype(np.uint8), "RGBA")
    if r["bg"]:
        bg = Image.new("RGBA", img.size, r["bg"])
        bg.alpha_composite(img)
        img = bg
    return img
