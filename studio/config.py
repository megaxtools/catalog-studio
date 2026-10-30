"""مسیرها و تنظیمات پیش‌فرض استودیو."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "استودیو کاتالوگ مگا"
APP_NAME_EN = "Mega Catalog Studio"
VERSION = "1.6.1"

PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent
STATIC_DIR = PKG_DIR / "static"
DEFAULTS_DIR = PKG_DIR / "defaults"

DATA_DIR = Path(os.environ.get("CATALOG_STUDIO_DATA", ROOT_DIR / "data")).resolve()
DB_PATH = DATA_DIR / "studio.db"
MODELS_DIR = DATA_DIR / "models"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
AI_IMAGES_DIR = DATA_DIR / "ai_images"
DEFAULT_OUTPUT_DIR = DATA_DIR / "output"

HOST = os.environ.get("CATALOG_STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("CATALOG_STUDIO_PORT", "8765"))

DEFAULT_SETTINGS: dict = {
    "output_root": str(DEFAULT_OUTPUT_DIR),
    "browser_channel": "auto",          # auto | msedge | chrome | chromium
    "headless": True,
    "block_heavy_resources": True,      # عدم بارگذاری تصویر/فونت/ویدئو در مرورگر برای سرعت
    "delay_min_ms": 900,
    "delay_max_ms": 1800,
    "page_timeout_s": 45,
    "max_retries": 3,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "image_download_workers": 4,
    "rembg_model": "isnet-general-use",
    "image_size": 1280,
    "image_padding_pct": 6,             # (نسخه‌های قبل؛ جای خود را به image_align داده است)
    "image_align": {"canvas_w": 1280, "canvas_h": 1280, "margin": 60, "per_side": False, "trim": "auto", "alpha_threshold": 10,
                    "color_tolerance": 18, "despeckle": 2, "upscale": True, "background": "auto", "format": "png", "quality": 92},
    "slug_dictionary": {},              # واژه‌نامه سفارشی فارسی → انگلیسی برای اسلاگ
    "queue_enabled": True,              # اجرای خودکار صف استخراج
    "mcp_enabled": True,                # فعال بودن سرور MCP روی /mcp
    "mcp_read_only": False,             # فقط ابزارهای خواندنی برای ایجنت‌ها
    "mcp_token": "",                    # توکن اختیاری برای اتصال HTTP به /mcp
    "ai_default_provider_id": None,     # اتصال پیش‌فرض دستیار هوش مصنوعی
    "ai_default_model": "",             # مدل پیش‌فرض (خالی = مدل متن اتصال)
    "ai_default_image_provider_id": None,  # اتصال پیش‌فرض تولید تصویر
}

for d in (DATA_DIR, MODELS_DIR, SCREENSHOTS_DIR, AI_IMAGES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# rembg مدل‌ها را از این مسیر می‌خواند؛ موتور داخلی هم از همین مسیر استفاده می‌کند.
os.environ.setdefault("U2NET_HOME", str(MODELS_DIR))
