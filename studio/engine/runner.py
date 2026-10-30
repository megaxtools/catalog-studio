"""اجرای بانک داده: کشف لینک‌ها، استخراج محصولات، توقف/ادامه و تصمیم‌گیری در خطا."""
from __future__ import annotations

import threading
import time
import traceback

from .. import db, services
from .errors import ACTIONS, KINDS, Paused, ScrapeError, classify_exception
from .fetcher import (api_listing_page, connectivity_ok, links_from_html, polite_delay, product_key,
                      set_query_param)
from .scrape import Fetchers, scrape_product


class JobManager:
    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}
        self.flags: dict[int, str | None] = {}
        self.lock = threading.Lock()

    def recover(self):
        for d in db.q("SELECT id FROM datasets WHERE status IN ('running','waiting','starting')"):
            db.update("datasets", d["id"], status="paused", step="اجرای قبلی ناتمام ماند؛ با «ادامه» از همان نقطه شروع می‌شود.")
            db.ex("UPDATE incidents SET status='superseded', resolved_at=? WHERE dataset_id=? AND status='open'", [db.now(), d["id"]])

    def is_running(self, did: int) -> bool:
        t = self.threads.get(did)
        return bool(t and t.is_alive())

    def start(self, did: int) -> None:
        with self.lock:
            if self.is_running(did):
                return
            self.flags[did] = None
            db.ex("UPDATE incidents SET status='superseded', resolved_at=? WHERE dataset_id=? AND status='open'", [db.now(), did])
            db.update("datasets", did, status="starting", step="در حال آماده‌سازی…", updated_at=db.now())
            t = threading.Thread(target=self._run, args=(did,), daemon=True, name=f"dataset-{did}")
            self.threads[did] = t
            t.start()

    def pause(self, did: int) -> None:
        self.flags[did] = "pause"
        if not self.is_running(did):
            db.update("datasets", did, status="paused", step="متوقف شد.")

    def stop(self, did: int) -> None:
        self.flags[did] = "stop"
        if not self.is_running(did):
            db.update("datasets", did, status="stopped", step="به درخواست شما پایان یافت.")

    def _run(self, did: int) -> None:
        DatasetRun(did, self).run()


class DatasetRun:
    def __init__(self, did: int, mgr: JobManager):
        self.did = did
        self.mgr = mgr
        self.settings = db.get_settings()
        self.ds = services.get_dataset(did)
        self.src = services.get_source(self.ds["source_id"])
        self.cfg = self.src["config"]
        self.schema = services.get_schema(self.ds["schema_id"])
        self.required = services.required_canonical(self.schema)
        self.policies = dict(self.ds["policies"] or {})
        self.options = self.ds["options"] or {}
        self.cursor = dict(self.ds["cursor"] or {})
        self.f = Fetchers(self.settings, self.cfg, headless=None if not self.options.get("show_browser") else False)
        self.limit = self.ds["item_limit"]
        self.empty_pages = 0

    # ---------- کمکی ----------
    def log(self, msg: str, level: str = "info", step: str = "", item_id=None, detail: str = ""):
        db.log("dataset", self.did, msg, level=level, step=step, item_id=item_id, detail=detail)

    def set_step(self, text: str, **extra):
        db.update("datasets", self.did, step=text, updated_at=db.now(), **extra)

    def control(self):
        flag = self.mgr.flags.get(self.did)
        if flag:
            raise Paused(flag)

    def collected(self) -> int:
        return db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND status IN ('done','partial')", [self.did]) or 0

    def queued(self) -> int:
        return db.val("SELECT COUNT(*) FROM items WHERE dataset_id=? AND status='queued' AND url NOT LIKE 'ai-generated:%'", [self.did]) or 0

    def need(self) -> int | None:
        if not self.limit:
            return None
        return max(0, self.limit - self.collected() - self.queued())

    def save_cursor(self):
        db.update("datasets", self.did, cursor=self.cursor, updated_at=db.now())

    # ---------- چرخه‌ی اصلی ----------
    def run(self):
        db.update("datasets", self.did, status="running", started_at=self.ds["started_at"] or db.now(),
                  step="در حال اجرا", updated_at=db.now())
        self.log("اجرا آغاز شد." if not self.ds["started_at"] else "اجرا از آخرین نقطه‌ی ذخیره‌شده ادامه یافت.", step="run")
        final_status, final_step = "completed", "تکمیل شد."
        try:
            while True:
                self.control()
                if self.limit and self.collected() >= self.limit:
                    final_step = f"به سقف تعیین‌شده ({self.limit} محصول) رسید."
                    break
                item = db.q1("SELECT * FROM items WHERE dataset_id=? AND status='queued' AND url NOT LIKE 'ai-generated:%' ORDER BY seq, id LIMIT 1", [self.did])
                if item:
                    self.process_item(services.item_row(item))
                    continue
                if self.ds_discovery_done():
                    final_step = "همه‌ی محصولات قابل‌دسترسی استخراج شدند."
                    break
                self.discover()
        except Paused as p:
            if str(p) == "stop":
                final_status, final_step = "stopped", "به درخواست شما پایان یافت؛ با «ادامه» از همین نقطه ادامه می‌یابد."
            else:
                final_status, final_step = "paused", "متوقف شد؛ با «ادامه» دقیقاً از همین نقطه ادامه می‌یابد."
            self.log(final_step, level="warning", step="control")
        except Exception as exc:  # noqa: BLE001
            final_status, final_step = "error", f"خطای پیش‌بینی‌نشده: {exc}"
            self.log("اجرا با خطای پیش‌بینی‌نشده متوقف شد.", level="error", step="run", detail=traceback.format_exc())
        finally:
            self.f.close()
            self.mgr.flags[self.did] = None
            fields = {"status": final_status, "step": final_step, "updated_at": db.now()}
            if final_status == "completed":
                fields["finished_at"] = db.now()
            db.update("datasets", self.did, **fields)
            services.refresh_dataset_naming(self.did)
            if final_status == "completed":
                self.log(f"پایان اجرا: {self.collected()} محصول در بانک داده.", level="success", step="run")
                self._ai_after()

    def _ai_after(self):
        """تولید خودکار با هوش مصنوعی پس از استخراج (اگر برای این بانک تنظیم شده باشد)."""
        try:
            opts = db.jload(db.val("SELECT options FROM datasets WHERE id=?", [self.did]), {}) or {}
            spec = opts.get("ai_after")
            if not spec or opts.get("queue_job_id"):
                return
            from ..ai_gen import start_after_scrape
            if db.val("SELECT COUNT(*) FROM ai_jobs WHERE dataset_id=? AND status IN ('running','pending')", [self.did]):
                return
            start_after_scrape(self.did, spec)
        except Exception as exc:  # noqa: BLE001
            self.log(f"تولید خودکار با هوش مصنوعی آغاز نشد: {exc}", level="warning", step="ai")

    def ds_discovery_done(self) -> bool:
        return bool(db.val("SELECT discovery_done FROM datasets WHERE id=?", [self.did]))

    # ---------- کشف لینک‌ها ----------
    def discover(self):
        lcfg = self.cfg.get("listing", {}) or {}
        mode = lcfg.get("mode", "browser")
        ptype = (lcfg.get("pagination") or {}).get("type", "scroll")
        while True:
            try:
                if mode == "api":
                    self._discover_api(lcfg)
                elif ptype in ("param", "none"):
                    self._discover_param(lcfg, mode)
                else:
                    self._discover_scroll(lcfg)
                return
            except Paused:
                raise
            except Exception as exc:  # noqa: BLE001
                err = classify_exception(exc)
                if err.kind in ("unknown", "parse_error", "not_found"):
                    err = ScrapeError("listing_error", "خواندن صفحه‌ی دسته‌بندی ممکن نشد.", err.detail or str(exc))
                action = self.decide(err, None, attempt=self.cursor.get("listing_attempts", 0))
                self.cursor["listing_attempts"] = self.cursor.get("listing_attempts", 0) + 1
                if action == "reload":
                    self.f.reset_browser()
                elif action == "wait_network":
                    self.wait_network()
                elif action == "show_browser":
                    self.f.reset_browser(headless=False)
                elif action in ("skip", "continue_partial"):
                    db.update("datasets", self.did, discovery_done=1)
                    return
                elif action == "pause":
                    raise Paused("pause")

    def _mark_done(self, why: str):
        db.update("datasets", self.did, discovery_done=1)
        self.log(why, step="discover")

    def _discover_api(self, lcfg: dict):
        api = lcfg.get("api", {})
        page = int(self.cursor.get("page", api.get("start_page", 1)))
        self.set_step(f"خواندن فهرست محصولات · صفحه {page}")
        links, info = api_listing_page(self.f.http, self.ds["category_url"], lcfg, page)
        self.cursor["listing_attempts"] = 0
        if page == int(api.get("start_page", 1)):
            upd = {}
            if info.get("total_items"):
                upd["total_expected"] = int(info["total_items"])
            if info.get("category_label") and not self.options.get("category_label_manual"):
                upd["category_label"] = str(info["category_label"])
            if upd:
                db.update("datasets", self.did, **upd)
                services.refresh_dataset_naming(self.did)
        self.log(f"صفحه {page}: {len(links)} لینک محصول پیدا شد.", step="discover")
        if not links:
            self._mark_done("صفحه‌ی خالی؛ پایان فهرست محصولات.")
            return
        added, complete = self.enqueue(links)
        if complete:
            self.cursor["page"] = page + 1
        self.save_cursor()
        tp = info.get("total_pages")
        if complete and tp and page >= int(tp):
            self._mark_done(f"همه‌ی {tp} صفحه‌ی فهرست خوانده شد.")
        polite_delay(self.settings, self.cfg)

    def _page_url(self, lcfg: dict, page: int) -> str:
        pag = lcfg.get("pagination", {}) or {}
        start = int(pag.get("start", 1))
        url = self.ds["category_url"]
        if pag.get("type") == "none":
            return url
        if page == start and not pag.get("always_param"):
            return url
        return set_query_param(url, pag.get("param", "page"), page)

    def _discover_param(self, lcfg: dict, mode: str):
        pag = lcfg.get("pagination", {}) or {}
        page = int(self.cursor.get("page", pag.get("start", 1)))
        url = self._page_url(lcfg, page)
        self.set_step(f"خواندن صفحه‌ی دسته‌بندی · صفحه {page}")
        if mode == "http":
            b = self.f.http.bundle(url)
            links = links_from_html(b.html, b.base_url, lcfg)
            title = b.soup.find("h1").get_text(" ").strip() if b.soup.find("h1") else ""
        else:
            links, info = self.f.browser.links_on_page(url, lcfg)
            title = info.get("h1") or ""
        self.cursor["listing_attempts"] = 0
        if page == int(pag.get("start", 1)) and title and not self.options.get("category_label_manual"):
            db.update("datasets", self.did, category_label=title[:80])
            services.refresh_dataset_naming(self.did)
        self.log(f"صفحه {page}: {len(links)} لینک محصول پیدا شد.", step="discover")
        if not links:
            self._mark_done("صفحه‌ی بدون محصول؛ پایان فهرست.")
            return
        added, complete = self.enqueue(links)
        new_on_page = self.cursor.pop("_last_new", 0)
        if complete:
            self.cursor["page"] = page + 1
            if new_on_page == 0:
                self.empty_pages += 1
            else:
                self.empty_pages = 0
        self.save_cursor()
        if pag.get("type") == "none" or self.empty_pages >= 2 or page >= int(pag.get("max_pages", 500)):
            self._mark_done("صفحه‌ی جدیدی با محصول تازه پیدا نشد؛ پایان فهرست.")
        polite_delay(self.settings, self.cfg)

    def _discover_scroll(self, lcfg: dict):
        known = {r["url"] for r in db.q("SELECT url FROM items WHERE dataset_id=?", [self.did])}
        need = self.need()
        want = None if need is None else need + len(known)
        self.set_step("پیمایش صفحه‌ی دسته‌بندی برای یافتن محصولات…")

        def prog(total, fresh):
            self.set_step(f"پیمایش صفحه‌ی دسته‌بندی · {total} لینک پیدا شد")
            self.control()

        links, info = self.f.browser.collect_links(self.ds["category_url"], lcfg, want, prog, None)
        self.cursor["listing_attempts"] = 0
        if info.get("h1") and not self.options.get("category_label_manual"):
            db.update("datasets", self.did, category_label=info["h1"][:80])
            services.refresh_dataset_naming(self.did)
        self.log(f"{len(links)} لینک محصول در صفحه‌ی دسته‌بندی پیدا شد.", step="discover")
        before = self.queued()
        self.enqueue(links)
        reached_want = want is not None and len(links) >= want
        if not reached_want or self.queued() == before:
            self._mark_done("پیمایش صفحه‌ی دسته‌بندی کامل شد.")
        self.save_cursor()

    def enqueue(self, links: list[str]) -> tuple[int, bool]:
        """خروجی: (تعداد افزوده‌شده، آیا همه‌ی لینک‌های این صفحه بررسی شد)"""
        dup_policy = self.options.get("duplicates", "skip")
        seq = (db.val("SELECT MAX(seq) FROM items WHERE dataset_id=?", [self.did]) or 0) + 1
        added, new_count = 0, 0
        for i, url in enumerate(links):
            need = self.need()
            if need is not None and need <= 0:
                self.cursor["_last_new"] = new_count
                return added, False
            key = product_key(url, self.cfg)
            if db.q1("SELECT id FROM items WHERE dataset_id=? AND product_key=?", [self.did, key]):
                continue
            new_count += 1
            prev = db.q1("""SELECT * FROM items WHERE source_id=? AND product_key=? AND dataset_id<>?
                            AND status IN ('done','partial') ORDER BY id DESC LIMIT 1""", [self.src["id"], key, self.did])
            if prev and dup_policy == "skip":
                self.cursor["duplicates_skipped"] = self.cursor.get("duplicates_skipped", 0) + 1
                db.log("dataset", self.did, "محصول تکراری (قبلاً استخراج شده) رد شد.", level="debug", step="dedupe", detail=url)
                continue
            if prev and dup_policy == "reuse":
                db.ex("""INSERT INTO items(dataset_id, source_id, url, product_key, seq, status, data, missing, scraped_at,
                         created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      [self.did, self.src["id"], url, key, seq, prev["status"], prev["data"], prev["missing"],
                       prev["scraped_at"], db.now(), db.now()])
                self.cursor["duplicates_reused"] = self.cursor.get("duplicates_reused", 0) + 1
            else:
                db.ex("""INSERT INTO items(dataset_id, source_id, url, product_key, seq, status, created_at, updated_at)
                         VALUES(?,?,?,?,?,?,?,?)""", [self.did, self.src["id"], url, key, seq, "queued", db.now(), db.now()])
            seq += 1
            added += 1
        found = db.val("SELECT COUNT(*) FROM items WHERE dataset_id=?", [self.did])
        db.update("datasets", self.did, total_found=found)
        self.cursor["_last_new"] = new_count
        return added, True

    # ---------- استخراج محصول ----------
    def process_item(self, item: dict):
        attempt = 0
        title_hint = item["url"]
        while True:
            self.control()
            attempt += 1
            n = self.collected() + 1
            tgt = self.limit or db.val("SELECT total_expected FROM datasets WHERE id=?", [self.did]) or "?"
            self.set_step(f"استخراج محصول {n} از {tgt}")
            db.update("items", item["id"], attempts=item["attempts"] + attempt, updated_at=db.now())
            try:
                rec, how, _ = scrape_product(item["url"], self.cfg, self.f, self.required)
                self.save_item(item["id"], "done", rec, [])
                self.log(f"استخراج شد: {rec.get('title', '')[:80]}", level="success", step="product", item_id=item["id"])
                polite_delay(self.settings, self.cfg)
                return
            except Paused:
                raise
            except Exception as exc:  # noqa: BLE001
                err = classify_exception(exc)
                if err.partial and err.partial.get("title"):
                    title_hint = err.partial["title"]
                self.log(f"{KINDS[err.kind]['title']}: {err.message}", level="warning", step="product",
                         item_id=item["id"], detail=f"{item['url']}\n{err.detail}")
                action = self.decide(err, item, attempt - 1, title_hint)
                if action == "retry":
                    continue
                if action == "reload":
                    self.f.reset_browser()
                    continue
                if action == "wait_network":
                    self.wait_network()
                    continue
                if action == "show_browser":
                    self.f.reset_browser(headless=False)
                    self.log("مرورگر قابل‌مشاهده باز شد؛ در صورت نیاز کپچا را حل کنید.", step="product", item_id=item["id"])
                    continue
                if action == "continue_partial":
                    self.save_item(item["id"], "partial", err.partial or {"source_url": item["url"]}, err.missing,
                                   error=err.message)
                    self.log("با اطلاعات ناقص ذخیره شد.", level="warning", step="product", item_id=item["id"])
                    return
                if action == "skip":
                    db.update("items", item["id"], status="skipped", error=err.message, updated_at=db.now())
                    self.log("محصول رد شد.", level="warning", step="product", item_id=item["id"])
                    return
                if action == "pause":
                    raise Paused("pause")
                raise Paused("pause")

    def save_item(self, iid: int, status: str, rec: dict, missing: list, error: str = ""):
        db.update("items", iid, status=status, data=rec, missing=missing, error=error, scraped_at=db.now(), updated_at=db.now())
        services.refresh_dataset_naming(self.did)

    # ---------- تصمیم در خطا ----------
    def decide(self, err: ScrapeError, item: dict | None, attempt: int, title_hint: str = "") -> str:
        max_r = int(self.settings.get("max_retries", 3))
        if err.kind in ("network", "timeout", "http_error") and attempt < max_r:
            wait = [3, 8, 20, 45][min(attempt, 3)]
            self.set_step(f"تلاش دوباره‌ی خودکار ({attempt + 1} از {max_r}) پس از {wait} ثانیه…")
            self._sleep(wait)
            return "reload" if err.kind == "timeout" else "retry"
        if err.kind == "blocked" and attempt < 1:
            self.set_step("منبع درخواست را محدود کرد؛ ۳۰ ثانیه صبر و تلاش دوباره…")
            self._sleep(30)
            return "reload"
        allowed = KINDS[err.kind]["actions"]
        pol = self.policies.get(err.kind, "ask")
        if pol != "ask" and pol in allowed:
            self.log(f"تصمیم خودکار طبق تنظیمات: {ACTIONS[pol]['label']}", step="decide", item_id=item and item["id"])
            return pol
        if pol != "ask" and pol not in allowed:
            pass
        options = [{"action": a, **ACTIONS[a]} for a in allowed]
        iid = db.ex(
            """INSERT INTO incidents(dataset_id, item_id, kind, title, message, detail, url, options, created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [self.did, item["id"] if item else None, err.kind, KINDS[err.kind]["title"], err.message,
             (err.detail or "")[:4000], item["url"] if item else self.ds["category_url"], db.jdump(options), db.now()],
        )
        db.update("datasets", self.did, status="waiting", step="در انتظار تصمیم شما درباره‌ی یک خطا", updated_at=db.now())
        self.log(f"منتظر تصمیم شما: {KINDS[err.kind]['title']}", level="warning", step="decide",
                 item_id=item and item["id"], detail=title_hint)
        while True:
            flag = self.mgr.flags.get(self.did)
            if flag:
                db.update("incidents", iid, status="superseded", resolved_at=db.now())
                raise Paused(flag)
            inc = db.q1("SELECT * FROM incidents WHERE id=?", [iid])
            if inc and inc["status"] == "resolved":
                decision = inc["decision"]
                if inc["apply_all"]:
                    self.policies[err.kind] = decision
                    db.update("datasets", self.did, policies=self.policies)
                db.update("datasets", self.did, status="running", step="ادامه‌ی اجرا", updated_at=db.now())
                self.log(f"تصمیم شما: {ACTIONS.get(decision, {}).get('label', decision)}", step="decide",
                         item_id=item and item["id"])
                return decision
            time.sleep(0.8)

    def _sleep(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            self.control()
            time.sleep(0.5)

    def wait_network(self):
        url = self.ds["category_url"]
        n = 0
        while not connectivity_ok(url):
            n += 1
            self.set_step(f"اتصال برقرار نیست؛ بررسی دوباره در ۱۵ ثانیه (تلاش {n})")
            self._sleep(15)
        self.log("اتصال دوباره برقرار شد.", level="success", step="network")
        db.update("datasets", self.did, status="running")


def rescrape_item(item_id: int) -> dict:
    """استخراج دوباره‌ی یک محصول از صفحه‌ی بانک داده (بدون پرسش در خطا)."""
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))
    ds = services.get_dataset(it["dataset_id"])
    src = services.get_source(it["source_id"])
    settings = db.get_settings()
    f = Fetchers(settings, src["config"])
    try:
        rec, _, _ = scrape_product(it["url"], src["config"], f, services.required_canonical(services.get_schema(ds["schema_id"])))
        db.update("items", item_id, status="done", data=rec, missing=[], error="", scraped_at=db.now(), updated_at=db.now())
        db.log("dataset", ds["id"], "محصول دوباره استخراج شد.", level="success", step="rescrape", item_id=item_id)
    except Exception as exc:  # noqa: BLE001
        err = classify_exception(exc)
        if err.partial:
            db.update("items", item_id, status="partial", data=err.partial, missing=err.missing, error=err.message, updated_at=db.now())
        else:
            db.update("items", item_id, error=err.message, updated_at=db.now())
        db.log("dataset", ds["id"], f"استخراج دوباره ناموفق: {err.message}", level="warning", step="rescrape", item_id=item_id, detail=err.detail)
    finally:
        f.close()
    return services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))


MANAGER = JobManager()
