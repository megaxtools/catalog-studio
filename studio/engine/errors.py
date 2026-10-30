"""سناریوهای خطا و رفتارهای قابل‌انتخاب برای هر خطا."""
from __future__ import annotations

ACTIONS: dict[str, dict] = {
    "retry": {"label": "تکرار همین مرحله (Retry)", "hint": "استخراج همین محصول از همین مرحله دوباره انجام می‌شود."},
    "reload": {"label": "بارگذاری مجدد صفحه (Refresh)", "hint": "صفحه با یک نشست تازه‌ی مرورگر دوباره باز می‌شود."},
    "continue_partial": {"label": "ادامه با اطلاعات ناقص", "hint": "هرچه استخراج شده ذخیره می‌شود و محصول «ناقص» علامت می‌خورد."},
    "skip": {"label": "رد کردن این محصول (Skip)", "hint": "این محصول کنار گذاشته می‌شود و کار با محصول بعدی ادامه پیدا می‌کند."},
    "wait_network": {"label": "صبر تا برقراری اتصال", "hint": "هر ۱۵ ثانیه اتصال بررسی می‌شود و پس از وصل شدن، کار خودکار ادامه پیدا می‌کند."},
    "show_browser": {"label": "باز کردن مرورگر برای حل دستی", "hint": "مرورگر قابل‌مشاهده باز می‌شود تا کپچا یا مانع را خودتان رد کنید؛ سپس تکرار می‌شود."},
    "pause": {"label": "توقف و ادامه در زمانی دیگر (Pause)", "hint": "کار در همین نقطه ذخیره و متوقف می‌شود."},
}

KINDS: dict[str, dict] = {
    "network": {
        "title": "قطع اتصال اینترنت یا منبع",
        "actions": ["wait_network", "retry", "skip", "pause"],
    },
    "timeout": {
        "title": "بارگذاری ناقص یا طولانی صفحه",
        "actions": ["reload", "retry", "continue_partial", "skip", "pause"],
    },
    "blocked": {
        "title": "مسدود شدن دسترسی یا کپچا (Blocked)",
        "actions": ["show_browser", "wait_network", "retry", "skip", "pause"],
    },
    "http_error": {
        "title": "پاسخ خطا از سرور منبع",
        "actions": ["retry", "reload", "skip", "pause"],
    },
    "not_found": {
        "title": "صفحه‌ی محصول پیدا نشد (404)",
        "actions": ["skip", "retry", "pause"],
    },
    "missing_fields": {
        "title": "بارگذاری نشدن بخشی از اطلاعات محصول",
        "actions": ["reload", "retry", "continue_partial", "skip", "pause"],
    },
    "parse_error": {
        "title": "خطا در استخراج اطلاعات",
        "actions": ["retry", "reload", "continue_partial", "skip", "pause"],
    },
    "listing_error": {
        "title": "خطا در خواندن صفحه‌ی دسته‌بندی",
        "actions": ["reload", "retry", "pause"],
    },
    "unknown": {
        "title": "خطای پیش‌بینی‌نشده",
        "actions": ["retry", "reload", "skip", "pause"],
    },
}

# رفتار خودکار پیش‌فرض: ask یعنی از کاربر پرسیده شود
DEFAULT_POLICIES = {k: "ask" for k in KINDS}

POLICY_CHOICES = ["ask", "retry", "reload", "continue_partial", "skip", "pause"]


class ScrapeError(Exception):
    def __init__(self, kind: str, message: str, detail: str = "", partial: dict | None = None,
                 missing: list | None = None):
        super().__init__(message)
        self.kind = kind if kind in KINDS else "unknown"
        self.message = message
        self.detail = detail
        self.partial = partial
        self.missing = missing or []


class Paused(Exception):
    """کاربر درخواست توقف داده است."""


def classify_exception(exc: Exception) -> ScrapeError:
    if isinstance(exc, ScrapeError):
        return exc
    name = type(exc).__name__
    text = str(exc)
    low = text.lower()
    net_markers = ("err_internet_disconnected", "err_name_not_resolved", "err_connection", "err_network",
                   "err_address_unreachable", "err_proxy", "err_tunnel", "connectionerror", "max retries exceeded",
                   "failed to establish", "name or service not known", "getaddrinfo", "connection reset",
                   "connection aborted", "remote end closed", "err_timed_out", "nodename nor servname")
    if any(m in low for m in net_markers) or name in ("ConnectionError", "ConnectTimeout", "ProxyError", "SSLError"):
        return ScrapeError("network", "ارتباط با منبع برقرار نشد.", f"{name}: {text}")
    if "timeout" in low or name in ("TimeoutError", "ReadTimeout", "Timeout"):
        return ScrapeError("timeout", "صفحه در زمان مقرر کامل بارگذاری نشد.", f"{name}: {text}")
    return ScrapeError("unknown", "خطای پیش‌بینی‌نشده رخ داد.", f"{name}: {text}")


def describe_kinds() -> dict:
    return {
        "kinds": {k: {"title": v["title"], "actions": v["actions"]} for k, v in KINDS.items()},
        "actions": ACTIONS,
        "policy_choices": POLICY_CHOICES,
    }
