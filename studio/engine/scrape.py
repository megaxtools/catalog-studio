"""دریافت و استخراج یک محصول بر اساس پیکربندی منبع."""
from __future__ import annotations

from .errors import ScrapeError
from .extract import PageBundle, extract_product
from .fetcher import BrowserFetcher, HttpFetcher, fill_template, params_from_url


class Fetchers:
    """نگه‌دارنده‌ی تنبل (Lazy) برای HTTP و مرورگر."""

    def __init__(self, settings: dict, cfg: dict, headless: bool | None = None):
        self.settings, self.cfg = settings, cfg
        self.headless = headless
        self._http: HttpFetcher | None = None
        self._browser: BrowserFetcher | None = None

    @property
    def http(self) -> HttpFetcher:
        if self._http is None:
            self._http = HttpFetcher(self.settings, self.cfg)
        return self._http

    @property
    def browser(self) -> BrowserFetcher:
        if self._browser is None:
            self._browser = BrowserFetcher(self.settings, self.cfg, self.headless)
        return self._browser

    def reset_browser(self, headless: bool | None = None):
        if self._browser:
            self._browser.close()
        self._browser = None
        if headless is not None:
            self.headless = headless

    def fresh_context(self):
        if self._browser and self._browser._browser:
            self._browser.new_context()

    def close(self):
        if self._http:
            self._http.close()
        if self._browser:
            self._browser.close()
        self._http = self._browser = None


def fetch_bundle(url: str, cfg: dict, f: Fetchers, mode: str | None = None, screenshot: bool = False) -> PageBundle:
    pcfg = cfg.get("product", {}) or {}
    mode = mode or pcfg.get("mode", "browser")
    if mode == "api":
        api = pcfg.get("api", {})
        params = params_from_url(url, api.get("params_from_url") or {"id": cfg.get("product_id_pattern", r"(\d+)")})
        if not params:
            raise ScrapeError("parse_error", "شناسه‌ی محصول از لینک استخراج نشد.", url)
        api_url = fill_template(api["url"], params)
        data, r = f.http.get(api_url, want_json=True)
        return PageBundle(url=url, final_url=url, status=r.status_code, api=data)
    if mode == "http":
        return f.http.bundle(url)
    return f.browser.bundle(url, pcfg, screenshot=screenshot)


def scrape_product(url: str, cfg: dict, f: Fetchers, required: list[str] | None = None,
                   screenshot: bool = False, explain: bool = False) -> tuple[dict, dict, PageBundle]:
    pcfg = cfg.get("product", {}) or {}
    try:
        b = fetch_bundle(url, cfg, f, screenshot=screenshot)
    except ScrapeError as e:
        fb = pcfg.get("fallback_mode")
        if fb and e.kind in ("blocked", "parse_error", "http_error"):
            b = fetch_bundle(url, cfg, f, mode=fb, screenshot=screenshot)
        else:
            raise
    try:
        rec, how = extract_product(b, cfg, explain=explain)
    except Exception as exc:  # noqa: BLE001
        raise ScrapeError("parse_error", "در تحلیل محتوای صفحه خطا رخ داد.", f"{type(exc).__name__}: {exc}") from exc
    rec["source_url"] = url
    if (how.get("_ai") or {}).get("error"):
        rec["_ai_extract_error"] = how["_ai"]["error"]
    missing = [k for k in (required or []) if rec.get(k) in (None, "", [], {})]
    if missing:
        raise ScrapeError("missing_fields", "برخی فیلدهای اجباری خالی ماندند: " + "، ".join(missing),
                          partial=rec, missing=missing)
    return rec, how, b
