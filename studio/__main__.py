"""اجرای استودیو: python -m studio"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def _probe(host: str, port: int, timeout: float = 1.5) -> dict | None:
    """اگر استودیو روی این پورت در حال اجراست، پاسخ health را برمی‌گرداند."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
            return j if j.get("app") == "mega-catalog-studio" else None
    except Exception:  # noqa: BLE001
        return None


def _port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _open_when_ready(url: str, host: str, port: int):
    """مرورگر فقط وقتی باز می‌شود که استودیو واقعاً آماده‌ی پاسخ است."""
    for _ in range(240):
        if _probe(host, port, 1.0):
            webbrowser.open(url)
            return
        time.sleep(0.5)
    print("  استودیو هنوز آماده نشده است؛ چند لحظه بعد نشانی بالا را در مرورگر باز کنید.")


def main():
    from .config import APP_NAME_EN, HOST, PORT, VERSION

    no_browser = os.environ.get("CATALOG_STUDIO_NO_BROWSER") == "1" or "--no-browser" in sys.argv
    port = PORT
    running = _probe(HOST, port)
    if running:
        url = f"http://{HOST}:{port}"
        print(f"\n  استودیو از قبل در حال اجراست (نسخه‌ی {running.get('version')}): {url}\n  همان پنجره‌ی قبلی را استفاده کنید؛ این پنجره بسته می‌شود.\n")
        if not no_browser:
            webbrowser.open(url)
        time.sleep(3)
        return
    if not _port_free(HOST, port):
        for p in range(PORT + 1, PORT + 20):
            if _port_free(HOST, p):
                print(f"  پورت {port} در اختیار برنامه‌ی دیگری است؛ استودیو روی پورت {p} اجرا می‌شود.")
                port = p
                os.environ["CATALOG_STUDIO_PORT"] = str(p)
                from . import config
                config.PORT = p
                break

    import uvicorn

    from .api import create_app
    from .images import warmup

    if sys.platform == "win32":
        import asyncio
        # Playwright در ویندوز به Proactor نیاز دارد
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    url = f"http://{HOST}:{port}"
    print(f"\n  {APP_NAME_EN} v{VERSION}\n  {url}\n  در حال آماده‌سازی… مرورگر به‌محض آماده شدن باز می‌شود.\n  برای بستن، این پنجره را ببندید یا Ctrl+C بزنید.\n")
    app = create_app()
    if not no_browser:
        threading.Thread(target=_open_when_ready, args=(url, HOST, port), daemon=True).start()
    threading.Thread(target=lambda: (time.sleep(6), warmup()), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning", timeout_keep_alive=30)


if __name__ == "__main__":
    main()
