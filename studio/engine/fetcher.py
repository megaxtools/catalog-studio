"""دریافت صفحات: حالت API/HTTP با requests و حالت مرورگر با Playwright."""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode, unquote

import requests

from ..config import SCREENSHOTS_DIR
from .errors import ScrapeError, classify_exception
from .extract import PageBundle, EXPAND_TEXTS, resolve_path

BLOCK_MARKERS = re.compile(
    r"captcha|cf-challenge|are you a robot|access denied|ddos protection|arvancloud|"
    r"درخواست شما مسدود|دسترسی شما محدود|ربات نیستید", re.I)


def _status_error(status: int, url: str) -> ScrapeError | None:
    if status is None or status < 400:
        return None
    if status == 404 or status == 410:
        return ScrapeError("not_found", f"صفحه پیدا نشد (HTTP {status}).", url)
    if status in (401, 403, 429):
        return ScrapeError("blocked", f"منبع درخواست را رد کرد (HTTP {status}).", url)
    return ScrapeError("http_error", f"سرور منبع خطا داد (HTTP {status}).", url)


def fill_template(tpl: str, params: dict) -> str:
    def rep(m):
        return str(params.get(m.group(1), ""))
    return re.sub(r"\{(\w+)\}", rep, tpl)


def params_from_url(url: str, patterns: dict) -> dict:
    out = {}
    decoded = unquote(url)
    for name, pat in (patterns or {}).items():
        m = re.search(pat, url) or re.search(pat, decoded)
        if m:
            out[name] = m.group(1) if m.groups() else m.group(0)
    return out


def set_query_param(url: str, key: str, value) -> str:
    p = urlparse(url)
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != key]
    qs.append((key, str(value)))
    return urlunparse(p._replace(query=urlencode(qs)))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HttpFetcher:
    def __init__(self, settings: dict, cfg: dict):
        self.settings = settings
        self.cfg = cfg
        self.s = requests.Session()
        headers = {
            "User-Agent": settings.get("user_agent"),
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        headers.update(cfg.get("request", {}).get("headers", {}) or {})
        self.s.headers.update(headers)
        self.timeout = int(cfg.get("request", {}).get("timeout_s") or settings.get("page_timeout_s", 45))

    def get(self, url: str, want_json: bool = False):
        try:
            r = self.s.get(url, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise classify_exception(exc) from exc
        err = _status_error(r.status_code, url)
        if err:
            raise err
        if want_json:
            try:
                return r.json(), r
            except ValueError as exc:
                if BLOCK_MARKERS.search(r.text[:5000]):
                    raise ScrapeError("blocked", "به‌جای داده، صفحه‌ی امنیتی/کپچا برگشت.", url) from exc
                raise ScrapeError("parse_error", "پاسخ منبع JSON معتبر نبود.", r.text[:500]) from exc
        return r.text, r

    def bundle(self, url: str) -> PageBundle:
        html, r = self.get(url)
        b = PageBundle(url=url, final_url=r.url, status=r.status_code, html=html)
        text = b.soup.get_text(" ", strip=True)[:6000]
        if BLOCK_MARKERS.search(text) and len(text) < 2500:
            raise ScrapeError("blocked", "صفحه‌ی امنیتی یا کپچا نمایش داده شد.", url)
        return b

    def close(self):
        self.s.close()


# ---------------------------------------------------------------------------
# مرورگر
# ---------------------------------------------------------------------------

_STATE_JS = """
() => {
  const out = {};
  for (const k of ['__NUXT__', '__INITIAL_STATE__', '__PRELOADED_STATE__', '__APOLLO_STATE__', '__remixContext', '__STATE__']) {
    try { if (window[k]) out[k] = JSON.parse(JSON.stringify(window[k])); } catch (e) {}
  }
  return out;
}
"""

_EXPAND_JS = """
(texts) => {
  let n = 0;
  const els = Array.from(document.querySelectorAll('button, [role=button], span, div, a, p'));
  for (const el of els) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 40) continue;
    if (!texts.some(x => t === x || t.startsWith(x))) continue;
    if (el.tagName === 'A') {
      const href = el.getAttribute('href') || '';
      if (href && !href.startsWith('#') && !href.startsWith('javascript')) continue;
    }
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    try { el.click(); n++; } catch (e) {}
    if (n > 12) break;
  }
  return n;
}
"""

_LINKS_JS = "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"


class BrowserFetcher:
    def __init__(self, settings: dict, cfg: dict, headless: bool | None = None):
        self.settings = settings
        self.cfg = cfg
        self.headless = settings.get("headless", True) if headless is None else headless
        self._pw = None
        self._browser = None
        self._ctx = None
        self.channel_used = ""

    # --- چرخه‌ی عمر ---
    def start(self):
        if self._browser:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        channel = self.settings.get("browser_channel", "auto")
        tries = ["msedge", "chrome", None] if channel == "auto" else [None if channel == "chromium" else channel, None]
        last = None
        for ch in tries:
            try:
                kw = {"headless": self.headless, "args": ["--disable-blink-features=AutomationControlled"]}
                if ch:
                    kw["channel"] = ch
                self._browser = self._pw.chromium.launch(**kw)
                self.channel_used = ch or "chromium"
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if not self._browser:
            self.close()
            raise ScrapeError("unknown", "مرورگر اجرا نشد. Edge/Chrome نصب نیست یا Chromium پلی‌رایت دانلود نشده.", str(last))
        self.new_context()

    def new_context(self):
        if self._ctx:
            try:
                self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._browser.new_context(
            locale="fa-IR", user_agent=self.settings.get("user_agent"),
            viewport={"width": 1366, "height": 900}, extra_http_headers={"Accept-Language": "fa-IR,fa;q=0.9"},
        )
        if self.settings.get("block_heavy_resources", True):
            self._ctx.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "media", "font") else route.continue_())

    def close(self):
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._ctx = None

    # --- کمکی ---
    def _timeout_ms(self) -> int:
        return int(self.cfg.get("request", {}).get("timeout_s") or self.settings.get("page_timeout_s", 45)) * 1000

    def _goto(self, page, url: str):
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms())
        except Exception as exc:  # noqa: BLE001
            raise classify_exception(exc) from exc
        status = resp.status if resp else None
        err = _status_error(status, url) if status else None
        if err:
            raise err
        try:
            page.wait_for_load_state("networkidle", timeout=min(12000, self._timeout_ms()))
        except Exception:  # noqa: BLE001
            pass
        return status

    def _check_blocked(self, page, url: str):
        try:
            title = page.title() or ""
            body = page.evaluate("() => (document.body ? document.body.innerText.slice(0, 4000) : '')") or ""
        except Exception:  # noqa: BLE001
            return
        if BLOCK_MARKERS.search(title + " " + body) and len(body) < 4000:
            raise ScrapeError("blocked", "صفحه‌ی امنیتی یا کپچا نمایش داده شد.", url)

    def run_actions(self, page, actions: list):
        for a in actions or []:
            t = a.get("type")
            try:
                if t == "wait":
                    page.wait_for_selector(a["selector"], timeout=int(a.get("timeout_ms", 10000)))
                elif t == "wait_ms":
                    page.wait_for_timeout(int(a.get("ms", 1000)))
                elif t == "click":
                    loc = page.locator(a["selector"])
                    count = loc.count() if a.get("all") else min(1, loc.count())
                    for i in range(count):
                        try:
                            loc.nth(i).click(timeout=4000)
                            page.wait_for_timeout(int(a.get("wait_ms", 600)))
                        except Exception:  # noqa: BLE001
                            if not a.get("optional", True):
                                raise
                elif t == "click_text":
                    page.evaluate(_EXPAND_JS, a.get("texts") or EXPAND_TEXTS)
                    page.wait_for_timeout(int(a.get("wait_ms", 800)))
                elif t == "scroll":
                    self.scroll(page, int(a.get("times", 6)))
                elif t == "hover":
                    page.hover(a["selector"], timeout=4000)
            except ScrapeError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not a.get("optional", True):
                    raise ScrapeError("timeout", f"عملیات «{t}» روی صفحه انجام نشد.", str(exc)) from exc

    def scroll(self, page, times: int = 6, pause_ms: int = 500):
        for _ in range(times):
            page.evaluate("() => window.scrollBy(0, Math.max(600, window.innerHeight * 0.9))")
            page.wait_for_timeout(pause_ms)

    # --- صفحه‌ی محصول ---
    def bundle(self, url: str, pcfg: dict, screenshot: bool = False) -> PageBundle:
        self.start()
        page = self._ctx.new_page()
        captured: list = []
        patterns = pcfg.get("capture_xhr", ["*"])

        def on_response(resp):
            try:
                rt = resp.request.resource_type
                if rt not in ("xhr", "fetch"):
                    return
                u = resp.url
                if patterns and "*" not in patterns and not any(p in u for p in patterns):
                    return
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                if len(captured) >= 40:
                    return
                body = resp.body()
                if len(body) > 4_000_000:
                    return
                captured.append({"url": u, "status": resp.status, "json": json.loads(body)})
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)
        try:
            status = self._goto(page, url)
            self._check_blocked(page, url)
            ws = pcfg.get("wait_selector")
            if ws:
                try:
                    page.wait_for_selector(ws, timeout=int(pcfg.get("wait_timeout_ms", 15000)))
                except Exception as exc:  # noqa: BLE001
                    raise ScrapeError("timeout", "بخش اصلی صفحه‌ی محصول بارگذاری نشد.", f"selector: {ws}") from exc
            if pcfg.get("scroll", True):
                self.scroll(page, int(pcfg.get("scroll_times", 5)), 350)
            self.run_actions(page, pcfg.get("actions", []))
            if pcfg.get("auto_expand", True):
                try:
                    clicked = page.evaluate(_EXPAND_JS, pcfg.get("expand_texts") or EXPAND_TEXTS)
                    if clicked:
                        page.wait_for_timeout(900)
                except Exception:  # noqa: BLE001
                    pass
            html = page.content()
            states = {}
            try:
                states = page.evaluate(_STATE_JS) or {}
            except Exception:  # noqa: BLE001
                pass
            shot = ""
            if screenshot:
                SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                p = SCREENSHOTS_DIR / f"test_{int(time.time() * 1000)}.jpg"
                try:
                    page.screenshot(path=str(p), type="jpeg", quality=70, full_page=False)
                    shot = str(p)
                except Exception:  # noqa: BLE001
                    pass
            b = PageBundle(url=url, final_url=page.url, status=status, html=html, xhr=captured, states=states,
                           screenshot=shot, title=page.title())
            return b
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    # --- صفحه‌ی دسته ---
    def collect_links(self, url: str, lcfg: dict, want: int | None, on_progress: Callable | None = None,
                      known: set | None = None) -> tuple[list[str], dict]:
        """برای صفحه‌بندی اسکرولی یا دکمه‌ی «بیشتر»: همه‌ی لینک‌ها را در یک صفحه جمع می‌کند."""
        self.start()
        page = self._ctx.new_page()
        info = {"title": ""}
        try:
            self._goto(page, url)
            self._check_blocked(page, url)
            ws = lcfg.get("wait_selector")
            if ws:
                try:
                    page.wait_for_selector(ws, timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
            self.run_actions(page, lcfg.get("actions", []))
            info["title"] = page.title()
            info["h1"] = page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.innerText.trim() : ''; }")
            pat = re.compile(lcfg.get("link_pattern") or ".")
            pag = lcfg.get("pagination", {}) or {}
            ptype = pag.get("type", "scroll")
            links: list[str] = []
            seen: set = set()
            idle, rounds = 0, 0
            max_rounds = int(pag.get("max_rounds", 400))
            idle_limit = int(pag.get("idle_rounds", 4))
            while rounds < max_rounds:
                rounds += 1
                hrefs = page.evaluate(_LINKS_JS) or []
                new = 0
                for h in hrefs:
                    if not pat.search(h) and not pat.search(unquote(h)):
                        continue
                    h = normalize_link(h, lcfg)
                    if h in seen:
                        continue
                    seen.add(h)
                    links.append(h)
                    new += 1
                fresh = len([x for x in links if not known or x not in known])
                if on_progress:
                    on_progress(len(links), fresh)
                if want and fresh >= want:
                    break
                idle = idle + 1 if new == 0 else 0
                if idle >= idle_limit:
                    break
                if ptype == "click":
                    sel = pag.get("click_selector")
                    clicked = False
                    if sel:
                        try:
                            loc = page.locator(sel).first
                            if loc.count() and loc.is_visible():
                                loc.click(timeout=5000)
                                clicked = True
                        except Exception:  # noqa: BLE001
                            pass
                    if not clicked:
                        try:
                            clicked = bool(page.evaluate(_EXPAND_JS, pag.get("click_texts") or ["نمایش بیشتر", "مشاهده بیشتر", "محصولات بیشتر", "بیشتر"]))
                        except Exception:  # noqa: BLE001
                            pass
                    page.wait_for_timeout(int(pag.get("pause_ms", 1500)))
                    if not clicked:
                        self.scroll(page, 2, 600)
                elif ptype == "scroll":
                    # کمی بالا و دوباره پایین تا رویداد scroll حتماً اجرا شود (برای سایت‌های مبتنی بر scroll/IntersectionObserver)
                    page.evaluate("() => window.scrollBy(0, -Math.min(800, window.innerHeight))")
                    page.wait_for_timeout(150)
                    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
                    try:
                        page.mouse.wheel(0, 1600)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(int(pag.get("pause_ms", 1400)))
                else:
                    break
            return links, info
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    def links_on_page(self, url: str, lcfg: dict) -> tuple[list[str], dict]:
        """یک صفحه‌ی منفرد (صفحه‌بندی با پارامتر) را باز و لینک‌ها را جمع می‌کند."""
        self.start()
        page = self._ctx.new_page()
        try:
            self._goto(page, url)
            self._check_blocked(page, url)
            ws = lcfg.get("wait_selector")
            if ws:
                try:
                    page.wait_for_selector(ws, timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
            self.run_actions(page, lcfg.get("actions", []))
            self.scroll(page, int(lcfg.get("scroll_times", 4)), 400)
            hrefs = page.evaluate(_LINKS_JS) or []
            info = {"title": page.title(), "h1": page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.innerText.trim() : ''; }")}
            return filter_links(hrefs, lcfg), info
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def normalize_link(u: str, lcfg: dict) -> str:
    p = urlparse(u)
    keep = lcfg.get("keep_query_params")
    if keep is None:
        q = ""
    else:
        q = urlencode([(k, v) for k, v in parse_qsl(p.query) if k in keep])
    return urlunparse(p._replace(query=q, fragment=""))


def filter_links(hrefs: list[str], lcfg: dict, base: str = "") -> list[str]:
    pat = re.compile(lcfg.get("link_pattern") or ".")
    out, seen = [], set()
    for h in hrefs:
        if base:
            h = urljoin(base, h)
        if not (pat.search(h) or pat.search(unquote(h))):
            continue
        h = normalize_link(h, lcfg)
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def links_from_html(html: str, base: str, lcfg: dict) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "")
    return filter_links(hrefs, lcfg, base)


def api_listing_page(http: HttpFetcher, category_url: str, lcfg: dict, page_no: int) -> tuple[list[str], dict]:
    api = lcfg.get("api", {})
    params = params_from_url(category_url, api.get("params_from_url", {}))
    params["page"] = page_no
    url = fill_template(api["url"], params)
    data, _ = http.get(url, want_json=True)
    items = resolve_path(data, api.get("items_path", ""))
    if items and isinstance(items[0], list):
        items = items[0]
    links = []
    for it in items:
        if not isinstance(it, dict):
            continue
        p = dict(params)
        for k, path in (api.get("item_fields") or {"id": "id"}).items():
            vals = resolve_path(it, path)
            p[k] = vals[0] if vals else ""
        links.append(fill_template(api.get("url_template", "{url}"), p))
    info = {}
    for k in ("total_pages", "total_items", "category_label"):
        path = api.get(f"{k}_path")
        if path:
            v = resolve_path(data, path)
            if v:
                info[k] = v[0]
    return links, info


def product_key(url: str, cfg: dict) -> str:
    pat = cfg.get("product_id_pattern")
    if pat:
        m = re.search(pat, url) or re.search(pat, unquote(url))
        if m:
            return m.group(1) if m.groups() else m.group(0)
    p = urlparse(url)
    return unquote(p.path).rstrip("/")


def polite_delay(settings: dict, cfg: dict):
    r = cfg.get("request", {}) or {}
    lo = int(r.get("delay_min_ms", settings.get("delay_min_ms", 900)))
    hi = int(r.get("delay_max_ms", settings.get("delay_max_ms", 1800)))
    time.sleep(random.uniform(lo, max(lo, hi)) / 1000.0)


def connectivity_ok(url: str, timeout: int = 8) -> bool:
    try:
        p = urlparse(url)
        requests.head(f"{p.scheme}://{p.netloc}/", timeout=timeout, allow_redirects=True)
        return True
    except Exception:  # noqa: BLE001
        return False
