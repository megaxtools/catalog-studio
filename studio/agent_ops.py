"""عملیات مخصوص ایجنت‌ها (MCP): کمبودهای محصول، نوشتن فیلدها، تولید و پیوست تصویر."""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import requests
from PIL import Image

from . import ai_gen, db, rules, services
from .ai import AIClient, AIError, get_provider
from .config import AI_IMAGES_DIR

EMPTY = (None, "", [], {})


def _empty(v) -> bool:
    if v in EMPTY:
        return True
    if isinstance(v, dict):
        return all(_empty(x) for x in v.values())
    return False


def _ctx(item_id: int):
    it = services.item_row(db.q1("SELECT * FROM items WHERE id=?", [item_id]))
    if not it:
        raise ValueError(f"محصول {item_id} پیدا نشد.")
    ds = services.get_dataset(it["dataset_id"])
    schema = services.get_schema(ds["schema_id"])
    return it, ds, schema, db.get_settings()


def item_detail(item_id: int, max_text: int = 4000) -> dict:
    it, ds, schema, settings = _ctx(item_id)
    src = services.get_source(it["source_id"])
    cols = {}
    for c in schema["columns"]:
        if c.get("include") is False:
            continue
        v, flag = services.column_value(c, it, ds, settings, src)
        if isinstance(v, str) and len(v) > max_text:
            v = v[:max_text] + "…"
        cols[c["key"]] = {"label": c.get("label", ""), "kind": c.get("kind"), "input": c.get("input", "text"), "value": v,
                          "source": {"edited": "manual_edit", "ai": "ai_or_agent", "missing": "empty_required", "unmapped": "unmapped_suggestion"}.get(flag, "scraped/default"),
                          "empty": _empty(v)}
    data = dict(rules.cleaned(it))
    if isinstance(data.get("long_description"), str) and len(data["long_description"]) > max_text:
        data["long_description"] = data["long_description"][:max_text] + "…"
    return {"id": it["id"], "dataset_id": it["dataset_id"], "status": it["status"], "url": it["url"], "product_key": it["product_key"],
            "schema": {"id": schema["id"], "name": schema["name"]}, "columns": cols, "scraped_data_after_rules": data,
            "ai_fields": [k for k in (it.get("ai") or {}) if k != "__meta"], "ai_error": ((it.get("ai") or {}).get("__meta") or {}).get("error", ""),
            "manual_edit_fields": list((it.get("overrides") or {}).keys()), "missing_required": it.get("missing") or []}


def gaps(dataset_id: int, columns: list[str] | None = None, statuses=("done", "partial"), limit: int = 500) -> dict:
    ds = services.get_dataset(dataset_id)
    if not ds:
        raise ValueError("بانک داده پیدا نشد.")
    schema = services.get_schema(ds["schema_id"])
    settings = db.get_settings()
    cols = [c for c in schema["columns"] if c.get("include") is not False and c.get("kind") != "constant"
            and (not columns or c["key"] in columns)]
    out = []
    counts: dict[str, int] = {}
    rows = db.q(f"SELECT * FROM items WHERE dataset_id=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY seq, id",
                [dataset_id, *statuses])
    for r in rows:
        it = services.item_row(r)
        empty = []
        for c in cols:
            v, _ = services.column_value(c, it, ds, settings)
            if c.get("input") == "group" and isinstance(v, dict):
                miss = [k for k in c.get("subkeys", []) if _empty(v.get(k))]
                if miss:
                    empty.append(f"{c['key']}:{','.join(miss)}" if len(miss) < len(c.get("subkeys", [])) else c["key"])
                    counts[c["key"]] = counts.get(c["key"], 0) + 1
            elif _empty(v):
                empty.append(c["key"])
                counts[c["key"]] = counts.get(c["key"], 0) + 1
        if empty and len(out) < limit:
            out.append({"item_id": it["id"], "title": rules.cleaned(it).get("title", ""), "status": it["status"], "empty": empty})
    return {"dataset_id": dataset_id, "schema": schema["name"], "items_checked": len(rows), "items_with_gaps": len(out),
            "empty_count_by_column": counts, "items": out}


def set_fields(item_id: int, values: dict, mode: str = "ai", agent: str = "mcp-agent") -> dict:
    """mode=ai: برگشت‌پذیر و مثل خروجی هوش مصنوعی (ویرایش دستی کاربر مقدم است). mode=override: مثل ویرایش دستی."""
    it, ds, schema, settings = _ctx(item_id)
    cols = {c["key"]: c for c in schema["columns"]}
    unknown = [k for k in values if k not in cols]
    if unknown:
        raise ValueError(f"این ستون‌ها در اسکیمای «{schema['name']}» نیستند: {', '.join(unknown)}. ستون‌های مجاز: {', '.join(cols)}")
    ai = dict(it.get("ai") or {})
    overrides = dict(it.get("overrides") or {})
    manual = dict(it.get("manual") or {})
    shadowed = []
    for k, v in values.items():
        c = cols[k]
        shape = ai_gen._shape(c)[0]
        if shape != "json" and c.get("input") not in ("image", "images"):
            v = ai_gen._normalize(shape, v, c, settings)
        if v is None:
            ai.pop(k, None)
            overrides.pop(k, None)
            continue
        if mode == "override":
            if c.get("kind") == "manual":
                manual[k] = v
            else:
                overrides[k] = v
        else:
            ai[k] = {"value": v, "mode": "overwrite", "model": agent, "at": db.now(), "kind": "agent"}
            if k in overrides or (c.get("kind") == "manual" and not _empty(manual.get(k))):
                shadowed.append(k)
    services.record_item_change(it, {"ai": ai, "overrides": overrides, "manual": manual}, actor="mcp", note=agent)
    db.update("items", item_id, ai=ai, overrides=overrides, manual=manual, updated_at=db.now())
    res = item_detail(item_id)
    res["written"] = list(values.keys())
    if shadowed:
        res["note"] = (f"این ستون‌ها ذخیره شدند ولی ویرایش دستی کاربر بر آن‌ها مقدم است و دیده نمی‌شوند: {', '.join(shadowed)}. "
                       "برای جایگزینی، mode=override بدهید.")
    return res


# ---------------------------------------------------------------------------
# تصاویر
# ---------------------------------------------------------------------------

def _image_cols(schema) -> dict:
    return {c["key"]: c for c in schema["columns"] if c.get("input") in ("image", "images")}


def _attach(it, ds, schema, settings, paths: list[str], target: str | None, mode: str, model: str, prompt: str = "") -> dict:
    cols = _image_cols(schema)
    if not cols:
        raise ValueError("اسکیمای این بانک ستون تصویری ندارد.")
    if not target:
        target = next((k for k, c in cols.items() if c.get("input") == ("images" if mode == "add" else "image")), next(iter(cols)))
    if target not in cols:
        raise ValueError(f"ستون تصویری «{target}» نیست. ستون‌های تصویری: {', '.join(cols)}")
    col = cols[target]
    ai = dict(it.get("ai") or {})
    if col.get("input") == "image":
        val, merge = paths[0], ""
    else:
        prev = ai.get(target) if mode == "add" else None
        old = [] if not prev else (prev["value"] if isinstance(prev["value"], list) else [prev["value"]])
        val, merge = old + paths, ("append" if mode == "add" else "")
    ai[target] = {"value": val, "mode": mode, "model": model, "at": db.now(), "kind": "image", "merge": merge, "prompt": prompt}
    db.update("items", it["id"], ai=ai, updated_at=db.now())
    return {"item_id": it["id"], "target": target, "mode": mode, "paths": paths}


def _save_png(data: bytes, it: dict, target: str) -> str:
    out = AI_IMAGES_DIR / f"ds{it['dataset_id']}" / f"item{it['id']}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        buf = io.BytesIO()
        im.save(buf, "PNG")
        data = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"داده‌ی تصویر معتبر نیست: {exc}") from exc
    p = out / f"{target or 'image'}_{int(time.time() * 1000)}.png"
    p.write_bytes(data)
    return str(p)


def generate_image(item_id: int, provider_id: int | None = None, profile_id: int | None = None, prompt: str = "",
                   target: str | None = None, mode: str = "add", size: str = "1024x1024", use_reference: bool = True,
                   count: int = 1, model: str | None = None) -> dict:
    it, ds, schema, settings = _ctx(item_id)
    prof_cfg = ai_gen.get_profile(profile_id)["config"] if profile_id else None
    pid = provider_id or (prof_cfg or {}).get("provider_id")
    if not pid:
        row = db.q1("SELECT id FROM ai_providers WHERE image_mode<>'none' AND kind<>'anthropic' AND image_model<>'' ORDER BY id LIMIT 1")
        pid = row["id"] if row else None
    prov = get_provider(int(pid)) if pid else None
    if not prov:
        raise AIError("اتصالی با قابلیت تولید تصویر پیدا نشد. در «هوش مصنوعی ← اتصال‌ها» یک اتصال با مدل تصویر بسازید یا provider_id بدهید.")
    client = AIClient(prov)
    src = services.get_source(it["source_id"])
    ctx = ai_gen.product_context(it, ds, src)
    tpl = prompt or ((prof_cfg or {}).get("images") or {}).get("prompt") or ai_gen.DEFAULT_IMAGE_PROMPT
    full = tpl.format_map(ai_gen._SafeDict(ctx))
    ref = ai_gen._ref_image(it) if use_reference else None
    paths = []
    for _ in range(max(1, min(4, int(count)))):
        data = client.image(full, model=model or (prof_cfg or {}).get("image_model") or None, size=size, reference=ref)
        paths.append(_save_png(data, it, target or "image"))
    res = _attach(it, ds, schema, settings, paths, target, mode, model or prov.get("image_model") or prov["name"], full)
    res["prompt"] = full
    res["provider"] = prov["name"]
    return res


def attach_image(item_id: int, data_base64: str = "", url: str = "", path: str = "", target: str | None = None,
                 mode: str = "add") -> dict:
    it, ds, schema, settings = _ctx(item_id)
    if data_base64:
        b = data_base64.split(",", 1)[1] if data_base64.startswith("data:") else data_base64
        data = base64.b64decode(b)
    elif url:
        r = requests.get(url, timeout=60, headers={"User-Agent": settings.get("user_agent")})
        r.raise_for_status()
        data = r.content
    elif path:
        p = Path(path).expanduser()
        if not p.is_file():
            raise ValueError("فایل تصویر پیدا نشد.")
        data = p.read_bytes()
    else:
        raise ValueError("یکی از data_base64، url یا path را بدهید.")
    saved = _save_png(data, it, target or "image")
    return _attach(it, ds, schema, settings, [saved], target, mode, "mcp-agent")


def item_images(item_id: int) -> list[dict]:
    it, ds, schema, settings = _ctx(item_id)
    out = []
    cols = _image_cols(schema)
    if cols:
        for k, c in cols.items():
            v, flag = services.column_value(c, it, ds, settings)
            for i, u in enumerate(v if isinstance(v, list) else ([v] if v else [])):
                out.append({"column": k, "index": i, "src": u, "origin": "local" if not str(u).startswith("http") else "remote"})
    else:
        d = rules.cleaned(it)
        for i, u in enumerate([d.get("featured_image")] + (d.get("gallery") or [])):
            if u:
                out.append({"column": "featured_image" if i == 0 else "gallery", "index": i, "src": u, "origin": "remote"})
    return out


def load_image_for_agent(src: str, referer: str = "", max_side: int = 768) -> tuple[str, str]:
    """تصویر را برای نمایش به ایجنت کوچک می‌کند: (base64, mime)"""
    if str(src).startswith("http"):
        r = requests.get(src, timeout=40, headers={"User-Agent": db.get_settings().get("user_agent"), "Referer": referer})
        r.raise_for_status()
        data = r.content
    else:
        data = Path(str(src).replace("file://", "")).read_bytes()
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if im.mode == "RGBA":
        im.save(buf, "PNG")
        mime = "image/png"
    else:
        im.save(buf, "JPEG", quality=85)
        mime = "image/jpeg"
    return base64.b64encode(buf.getvalue()).decode(), mime
