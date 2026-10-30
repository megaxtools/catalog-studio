"""سرور MCP استودیو کاتالوگ مگا (انتقال stdio).

ایجنت‌ها (Claude Desktop، opencode، Antigravity، Hermes، Cursor و …) این فایل را با پایتونِ محیط برنامه اجرا می‌کنند:
    <پوشه‌ی برنامه>\\.venv\\Scripts\\python.exe <پوشه‌ی برنامه>\\mcp_server.py
اگر استودیو باز نباشد، خودکار در پس‌زمینه اجرا می‌شود (برای غیرفعال کردن: CATALOG_STUDIO_AUTOSTART=0).
متغیرهای اختیاری: CATALOG_STUDIO_URL (پیش‌فرض http://127.0.0.1:8765) و CATALOG_STUDIO_MCP_READONLY=1 برای حالت فقط‌خواندنی.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from studio.mcp_core import run_stdio  # noqa: E402

if __name__ == "__main__":
    run_stdio()
