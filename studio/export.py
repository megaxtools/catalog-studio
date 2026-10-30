"""خروجی‌ساز: Excel/CSV بر اساس اسکیما، دانلود تصاویر پوشه‌بندی‌شده، حذف پس‌زمینه و بسته‌ی فشرده."""
from __future__ import annotations

import csv
import json
import threading
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import db, services
from . import align as align_mod
from .images import RAW_SUFFIX, REMBG_SUFFIX, BgRemover, download_image, is_intermediate, process_file, stage_of
from .textutil import jalali_human, safe_filename

EXCEL_CELL_LIMIT = 32000


class ExportJobs:
    def __init__(self):
        self.cancel: dict[int, bool] = {}

    def recover(self):
        db.ex("UPDATE exports SET status='error', error='اجرای برنامه قطع شد؛ خروجی را دوباره بسازید.' WHERE status IN ('running','pending')")

    def create(self, opts: dict) -> int:
        if not opts.get("dataset_ids"):
            raise ValueError("دست‌کم یک بانک داده انتخاب کنید.")
        fmts = [f for f in (opts.get("formats") or ["xlsx", "csv"]) if f in ("xlsx", "csv", "json")]
        if not fmts:
            raise ValueError("دست‌کم یک قالب فایل (Excel، CSV یا JSON) انتخاب کنید.")
        opts["formats"] = fmts
        fs = {f: int(s) for f, s in (opts.get("format_schemas") or {}).items() if f in fmts and s}
        for s_ in fs.values():
            if not db.q1("SELECT id FROM schemas WHERE id=?", [s_]):
                raise ValueError("اسکیمای انتخاب‌شده برای یکی از قالب‌ها پیدا نشد.")
        opts["format_schemas"] = fs
        opts["schema_id"] = int(opts.get("schema_id") or services.get_schema(None)["id"])
        name = safe_filename(opts.get("name") or services.suggest_export_name(opts["dataset_ids"]))
        opts["name"] = name
        eid = db.ex("INSERT INTO exports(name, dataset_ids, schema_id, options, status, created_at) VALUES(?,?,?,?,?,?)",
                    [name, db.jdump(opts["dataset_ids"]), opts.get("schema_id") or services.get_schema(None)["id"],
                     db.jdump(opts), "pending", db.now()])
        db.update("exports", eid, title=opts.get("title") or name, state="draft", updated_at=db.now())
        self.cancel[eid] = False
        threading.Thread(target=self._run, args=(eid,), daemon=True).start()
        return eid

    def stop(self, eid: int):
        self.cancel[eid] = True

    def _step(self, eid, text, done=None, total=None):
        f = {"step": text}
        if done is not None:
            f["progress_done"] = done
        if total is not None:
            f["progress_total"] = total
        db.update("exports", eid, **f)

    def _check(self, eid):
        if self.cancel.get(eid):
            raise InterruptedError("لغو شد")

    def _run(self, eid: int):
        exp = db.q1("SELECT * FROM exports WHERE id=?", [eid])
        opts = db.jload(exp["options"], {})
        settings = db.get_settings()
        db.update("exports", eid, status="running")
        try:
            result = self.build(eid, opts, settings)
            db.update("exports", eid, status="completed", result=result, finished_at=db.now(), step="آماده است.")
            db.log("export", eid, f"خروجی «{opts['name']}» ساخته شد.", level="success", step="export")
        except InterruptedError:
            db.update("exports", eid, status="cancelled", step="لغو شد.")
        except Exception as exc:  # noqa: BLE001
            db.update("exports", eid, status="error", error=str(exc), step="خطا")
            db.log("export", eid, "ساخت خروجی ناموفق بود.", level="error", step="export", detail=traceback.format_exc())

    # ------------------------------------------------------------------
    def load_items(self, opts: dict) -> list[dict]:
        statuses = opts.get("statuses") or ["done", "partial"]
        ids = opts.get("item_ids") or []
        items = []
        for did in opts["dataset_ids"]:
            rows = db.q(f"SELECT * FROM items WHERE dataset_id=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY seq, id",
                        [did, *statuses])
            for r in rows:
                if ids and r["id"] not in ids:
                    continue
                items.append(services.item_row(r))
        return items

    def build(self, eid: int, opts: dict, settings: dict) -> dict:
        schema = services.get_schema(opts.get("schema_id"))
        name = opts["name"]
        root = services.ensure_dir(opts.get("output_root") or settings["output_root"])
        items = self.load_items(opts)
        if not items:
            raise ValueError("هیچ محصولی با فیلترهای انتخاب‌شده پیدا نشد.")
        if opts.get("ai_fill"):
            items = self.ai_fill(eid, opts, schema, items, settings)
        self._step(eid, "آماده‌سازی ردیف‌ها", 0, len(items))
        # گذر اول برای تعیین اسلاگ‌ها و نام پوشه‌ها
        services.build_rows(schema, items, settings)
        folder_mode = opts.get("folder_mode", "slug")
        used: dict[str, int] = {}
        for it in items:
            fn = services.item_folder_name(it, folder_mode)
            n = used.get(fn.lower(), 0)
            used[fn.lower()] = n + 1
            it["_folder"] = fn if not n else f"{fn}-{n + 1}"

        img_cols = [c for c in schema["columns"] if c.get("input") in ("image", "images") and c.get("include", True) is not False]
        image_map: dict[str, str] = {}
        stats = {"images_downloaded": 0, "images_failed": 0, "images_bg": 0, "bg_failed": 0}
        warnings: list[dict] = []
        local_files: list[tuple[dict, str, Path]] = []  # (item, url, path)
        img_src: dict[int, tuple[str, list[str]]] = {}

        # --- مرحله‌های تصویر: خام (feature_raw) ← حذف پس‌زمینه (feature_raw_rembg) ← نهایی (feature)
        use_rembg = opts.get("rembg", True) is not False
        acfg = opts.get("align", True)
        if acfg is None:
            acfg = True
        if acfg is False:
            aopts = False
        elif isinstance(acfg, dict) or opts.get("align_options"):
            aopts = align_mod.normalize(acfg if isinstance(acfg, dict) else opts.get("align_options"), settings.get("image_align"))
        elif opts.get("image_padding") is not None or opts.get("image_size"):  # کلاینت‌های نسخه‌های قبل
            aopts = align_mod.from_legacy(int(opts.get("image_size") or settings.get("image_size", 1280)),
                                          float(opts.get("image_padding") if opts.get("image_padding") is not None else settings.get("image_padding_pct", 6)))
        else:
            aopts = align_mod.normalize(settings.get("image_align"))
        processing = use_rembg or bool(aopts)
        keep_raw = opts.get("keep_raw", True) is not False
        stats["pipeline"] = {"rembg": use_rembg, "align": bool(aopts), "keep_raw": keep_raw}
        if aopts:
            stats["align"] = {k: aopts[k] for k in ("canvas_w", "canvas_h", "margin_top", "margin_right", "margin_bottom", "margin_left", "trim", "format")}

        if opts.get("images", True) and img_cols:
            raw_tag = RAW_SUFFIX if processing else ""
            jobs = []
            for it in items:
                feat = self._col_value(it, img_cols, "image", schema, settings)
                gal = self._col_value(it, img_cols, "images", schema, settings)
                img_src[it["id"]] = (feat if isinstance(feat, str) else "", [u for u in services.as_list(gal) if isinstance(u, str) and u])
                base = root / name / it["_folder"]
                if isinstance(feat, str) and feat:
                    jobs.append((it, feat, base / f"feature{raw_tag}"))
                for i, u in enumerate(services.as_list(gal), 1):
                    if isinstance(u, str) and u:
                        jobs.append((it, u, base / f"gallery_{i}{raw_tag}"))
            total = len(jobs)
            self._step(eid, "دانلود تصاویر خام" if processing else "دانلود تصاویر", 0, total)
            sess = requests.Session()
            sess.headers.update({"User-Agent": settings.get("user_agent")})
            done = 0
            with ThreadPoolExecutor(max_workers=int(settings.get("image_download_workers", 4))) as pool:
                futs = {pool.submit(download_image, sess, u, p, 3, it["url"]): (it, u, p) for it, u, p in jobs}
                for fut in as_completed(futs):
                    it, u, p = futs[fut]
                    done += 1
                    try:
                        path = fut.result()
                        local_files.append((it, u, path))
                        image_map[u] = path.relative_to(root).as_posix()
                        stats["images_downloaded"] += 1
                    except Exception as exc:  # noqa: BLE001
                        stats["images_failed"] += 1
                        warnings.append({"item_id": it["id"], "column": "images", "flag": "image_failed",
                                         "title": it["data"].get("title", ""), "detail": f"{u} — {exc}"})
                    if done % 3 == 0 or done == total:
                        self._step(eid, "دانلود تصاویر", done, total)
                        if self.cancel.get(eid):
                            pool.shutdown(cancel_futures=True)
                            self._check(eid)

            if processing:
                remover = BgRemover(opts.get("rembg_model") or settings.get("rembg_model"), opts.get("rembg_engine", "auto")) if use_rembg else None
                suffix = align_mod.out_suffix(aopts) if aopts else ".png"
                label = "حذف پس‌زمینه و ترازبندی تصاویر" if use_rembg and aopts else ("حذف پس‌زمینه‌ی تصاویر" if use_rembg else "ترازبندی تصاویر")
                self._step(eid, label, 0, len(local_files))
                for i, (it, u, p) in enumerate(sorted(local_files, key=lambda x: str(x[2])), 1):
                    self._check(eid)
                    base_name, _ = stage_of(p)
                    final = p.with_name(base_name + suffix)                                   # feature.png
                    inter = p.with_name(base_name + REMBG_SUFFIX + ".png") if (use_rembg and aopts and keep_raw) else None  # feature_raw_rembg.png
                    try:
                        # ترازبندی ارزان است و همیشه با قاعده‌ی فعلی ساخته می‌شود؛ حذف پس‌زمینه از فایل میانی دوباره استفاده می‌شود
                        if not final.exists() or aopts or opts.get("overwrite_bg"):
                            info = process_file(p, final, remover, align=aopts if aopts else False, intermediate=inter,
                                                reuse_intermediate=not opts.get("overwrite_bg"))
                            if info.get("low_res"):
                                warnings.append({"item_id": it["id"], "column": "images", "flag": "low_res", "title": it["data"].get("title", ""),
                                                 "detail": f"{final.relative_to(root)}: سوژه {info['scale']} برابر بزرگ شد و ممکن است تار باشد"})
                        image_map[u] = final.relative_to(root).as_posix()
                        stats["images_bg"] += 1
                        if not keep_raw and p.exists() and p != final:
                            p.unlink()
                    except Exception as exc:  # noqa: BLE001
                        stats["bg_failed"] += 1
                        warnings.append({"item_id": it["id"], "column": "images", "flag": "bg_failed",
                                         "title": it["data"].get("title", ""), "detail": str(exc)})
                        if "پوشه‌ی مدل‌ها" in str(exc):
                            raise
                    self._step(eid, label, i, len(local_files))
                stats["bg_engine"] = remover.engine_used if remover else ""

        from . import catalogs
        item_images = {}
        for it in items:
            feat, gal = img_src.get(it["id"], ("", []))
            item_images[it["id"]] = {"feature": image_map.get(feat, "") if feat else "", "gallery": [image_map[u] for u in gal if u in image_map]}
        files: dict[str, str] = {}
        if keep_raw:
            self._step(eid, "ذخیره‌ی داده‌ی خام")
            p = root / f"{name}{RAW_SUFFIX}.xlsx"
            self.write_raw(p, items)
            files["raw_xlsx"] = str(p)
            p = root / f"{name}{RAW_SUFFIX}.json"
            with open(p, "w", encoding="utf-8") as fh:
                json.dump([{"item_id": it["id"], "dataset_id": it["dataset_id"], "url": it["url"], "status": it["status"],
                            "raw": it.get("data") or {}, "manual": it.get("manual") or {}, "edits": it.get("overrides") or {},
                            "ai": it.get("ai") or {}} for it in items], fh, ensure_ascii=False, indent=1, default=str)
            files["raw_json"] = str(p)
        self._step(eid, "ثبت ردیف‌های خروجی در پایگاه داده")
        db.update("exports", eid, result={"root": str(root)})
        warnings.extend(catalogs.snapshot(eid, opts, items, settings, item_images))
        res = catalogs.write_files(eid, stats=stats, extra_files=files, step=lambda t: self._step(eid, t))
        res.update({"warnings": warnings[:500], "warning_count": len(warnings)})
        return res

    def ai_fill(self, eid: int, opts: dict, schema: dict, items: list[dict], settings: dict) -> list[dict]:
        """پیش از ساخت خروجی: ستون‌های خالی (یا ستون‌های انتخابی) با هوش مصنوعی تکمیل می‌شوند."""
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from . import ai_gen
        af = opts["ai_fill"] if isinstance(opts["ai_fill"], dict) else {}
        keys = af.get("columns")
        mode = af.get("mode", "fill_missing")
        if af.get("use_schema"):
            cfg = ai_gen.build_config(schema, None)
        else:
            cols = [c for c in schema["columns"] if ai_gen.ai_capable(c) and c.get("include") is not False and (not keys or c["key"] in keys)]
            cfg = ai_gen.build_config(schema, [{"key": c["key"], "mode": mode} for c in cols])
        if af.get("provider_id"):
            cfg["provider_id"] = af["provider_id"]
        if not cfg["fields"] and not cfg["images_list"]:
            return items
        total = len(items)
        self._step(eid, "تکمیل ستون‌ها با هوش مصنوعی", 0, total)
        dss: dict[int, dict] = {}
        done = [0]
        errs: list[str] = []

        fatal: list[str] = []
        stop = lambda: bool(self.cancel.get(eid) or fatal)  # noqa: E731

        def work(it):
            if stop():
                return
            from .ai import AICancelled, set_context
            set_context(purpose="تکمیل پیش از خروجی", ref=f"export:{eid}", item_id=it["id"])
            ds = dss.get(it["dataset_id"]) or services.get_dataset(it["dataset_id"])
            dss[it["dataset_id"]] = ds
            try:
                client = ai_gen.client_for(cfg)
                client.cancel_check = stop
                out = ai_gen.generate_for_item(it, cfg, ds, schema, client, settings, overwrite_ai=mode != "fill_missing",
                                               with_images=bool(cfg["images_list"]))
                if out["results"]:
                    ai_gen.save_results(it["id"], out["results"], note=f"export:{eid}")
            except AICancelled:
                return
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "fatal", False) and not fatal:
                    fatal.append(str(exc))
                errs.append(f"{it['data'].get('title', it['id'])}: {exc}")

        with _TPE(max_workers=max(1, min(6, int(af.get("concurrency") or 3)))) as pool:
            for _ in pool.map(work, items):
                done[0] += 1
                if done[0] % 2 == 0 or done[0] == total:
                    self._step(eid, "تکمیل ستون‌ها با هوش مصنوعی", done[0], total)
        self._check(eid)
        if fatal:
            raise RuntimeError(f"تکمیل با هوش مصنوعی متوقف شد: {fatal[0]}")
        if errs:
            db.log("export", eid, f"تکمیل با هوش مصنوعی برای {len(errs)} محصول ناموفق بود.", level="warning", step="ai", detail="\n".join(errs[:50]))
        self._ai_errors = errs
        return self.load_items(opts)

    def write_raw(self, path: Path, items: list[dict]):
        """داده‌ی خام استخراج‌شده (پیش از قواعد متن، نگاشت، ورود دستی، ویرایش و هوش مصنوعی) — خروجی نهایی نیست."""
        from openpyxl import Workbook
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        from openpyxl.styles import Font, PatternFill

        first = ["title", "title_en", "brand", "brand_en", "category", "breadcrumb", "short_description", "long_description",
                 "specifications", "featured_image", "gallery", "price", "sku"]
        keys: list[str] = []
        for it in items:
            for k in (it.get("data") or {}):
                if k not in keys and not k.startswith("_"):
                    keys.append(k)
        keys = [k for k in first if k in keys] + [k for k in keys if k not in first]
        wb = Workbook()
        ws = wb.active
        ws.title = "raw"
        ws.sheet_view.rightToLeft = True
        head = ["item_id", "dataset", "source_url", "status", "scraped_at", "origin"] + keys
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="71717A")

        def cell(v):
            if v is None:
                return ""
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            if isinstance(v, str):
                v = ILLEGAL_CHARACTERS_RE.sub("", v)[:32000]
            return v

        codes: dict[int, str] = {}
        for it in items:
            if it["dataset_id"] not in codes:
                d = services.get_dataset(it["dataset_id"])
                codes[it["dataset_id"]] = d["code"] if d else ""
            data = it.get("data") or {}
            origin = "ai" if str(it["url"]).startswith("ai-generated:") else "scraped"
            ws.append([it["id"], codes[it["dataset_id"]], "" if origin == "ai" else it["url"], it["status"], it.get("scraped_at") or "", origin]
                      + [cell(data.get(k)) for k in keys])
        note = wb.create_sheet("README")
        note.sheet_view.rightToLeft = True
        for line in ("این فایل «خام» است و خروجی نهایی نیست.",
                     "داده دقیقاً همان چیزی است که از منبع استخراج یا با هوش مصنوعی تولید شده است؛ پیش از قواعد متن، نگاشت برند/دسته، ورود دستی و ویرایش‌ها.",
                     "تصاویر: لینک‌های اصلی منبع. نسخه‌های خام دانلودشده با پسوند _raw و نسخه‌های بدون پس‌زمینه با پسوند _raw_rembg کنار تصویر نهایی هستند.",
                     "لایه‌های ورود دستی، ویرایش و هوش مصنوعی هر محصول در فایل JSON هم‌نام آمده است."):
            note.append([line])
        wb.save(path)

    def _col_value(self, it, img_cols, inp, schema, settings):
        ds = services.get_dataset(it["dataset_id"])
        for c in img_cols:
            if c.get("input") == inp:
                v, _ = services.column_value(c, it, ds, settings)
                return v
        return None

    def write_xlsx(self, path: Path, headers, rows, items, schema, opts, stats):
        wb = Workbook()
        ws = wb.active
        ws.title = "products"
        ws.sheet_view.rightToLeft = True
        head_fill = PatternFill("solid", fgColor="4F39F6")
        head_font = Font(bold=True, color="FFFFFF", name="Tahoma")
        ws.append(headers)
        for c in ws[1]:
            c.fill, c.font = head_fill, head_font
            c.alignment = Alignment(horizontal="center", vertical="center")
        for r in rows:
            ws.append([(str(v)[:EXCEL_CELL_LIMIT] if isinstance(v, str) else v) for v in r])
        widths = {}
        for i, h in enumerate(headers, 1):
            longest = max([len(str(h))] + [min(len(str(r[i - 1] or "")), 60) for r in rows[:200]])
            widths[i] = max(12, min(60, longest + 2))
            ws.column_dimensions[get_column_letter(i)].width = widths[i]
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=isinstance(c.value, str) and len(c.value) > 60)
        ws.freeze_panes = "B2"

        sp = wb.create_sheet("specifications")
        sp.sheet_view.rightToLeft = True
        sp.append(["slug", "title", "group", "name", "value"])
        for c in sp[1]:
            c.fill, c.font = head_fill, head_font
        for it in items:
            for s in it["data"].get("specifications") or []:
                sp.append([it.get("_slug", ""), it["data"].get("title", ""), s.get("group", ""), s.get("name", ""), s.get("value", "")])
        for col, w in zip("ABCDE", (34, 50, 24, 30, 50)):
            sp.column_dimensions[col].width = w
        sp.freeze_panes = "A2"

        info = wb.create_sheet("info")
        info.sheet_view.rightToLeft = True
        info.append(["کلید", "مقدار"])
        for c in info[1]:
            c.fill, c.font = head_fill, head_font
        info.append(["نام خروجی", opts["name"]])
        info.append(["زمان ساخت", jalali_human()])
        info.append(["اسکیما", schema["name"]])
        info.append(["تعداد محصول", len(rows)])
        for k, v in stats.items():
            if k == "align" and isinstance(v, dict):
                v = (f"بوم {v['canvas_w']}×{v['canvas_h']}، فاصله از لبه‌ها (بالا/راست/پایین/چپ) "
                     f"{v['margin_top']}/{v['margin_right']}/{v['margin_bottom']}/{v['margin_left']} پیکسل، تریم {v['trim']}، {v['format']}")
            elif isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            info.append([k, v])
        for did in opts["dataset_ids"]:
            d = services.get_dataset(did)
            if d:
                info.append(["بانک داده", f"{d['code']} — {d['title']}"])
                info.append(["لینک دسته‌بندی", d["category_url"]])
        info.column_dimensions["A"].width = 24
        info.column_dimensions["B"].width = 90
        wb.save(path)


EXPORTS = ExportJobs()
