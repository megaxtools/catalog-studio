"""موتور استخراج: بسته‌ی صفحه، مسیرهای JSON، راهبردهای استخراج، تبدیل‌ها و حدس هوشمند."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

from bs4 import BeautifulSoup, Tag

from ..textutil import clean_text, html_to_text, normalize_fa, parse_number, to_latin_digits

# ---------------------------------------------------------------------------
# فیلدهای استاندارد (Canonical) که هر منبع می‌تواند پر کند
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: list[dict] = [
    {"key": "title", "label": "عنوان محصول", "type": "text"},
    {"key": "title_en", "label": "عنوان انگلیسی", "type": "text"},
    {"key": "brand", "label": "برند", "type": "text"},
    {"key": "brand_en", "label": "برند (انگلیسی)", "type": "text"},
    {"key": "category", "label": "دسته‌بندی در منبع", "type": "text"},
    {"key": "breadcrumb", "label": "مسیر دسته‌بندی (Breadcrumb)", "type": "list"},
    {"key": "short_description", "label": "توضیح کوتاه", "type": "text"},
    {"key": "long_description", "label": "توضیح بلند", "type": "text"},
    {"key": "specifications", "label": "مشخصات فنی (Specifications)", "type": "specs"},
    {"key": "featured_image", "label": "تصویر شاخص", "type": "image"},
    {"key": "gallery", "label": "تصاویر گالری", "type": "images"},
    {"key": "variants", "label": "متغیرها (Variants)", "type": "json"},
    {"key": "dimension_codes", "label": "کدهای متغیر (dimension_codes)", "type": "json"},
    {"key": "dimensions", "label": "ابعاد و وزن (Dimensions)", "type": "json"},
    {"key": "price", "label": "قیمت", "type": "number"},
    {"key": "sku", "label": "کد کالا (SKU)", "type": "text"},
]
CANONICAL_KEYS = [f["key"] for f in CANONICAL_FIELDS]

DIMENSION_KEYS = ["item_weight", "item_width", "item_length", "item_height",
                  "packaging_weight", "packaging_width", "packaging_length", "packaging_height"]

DEFAULT_DIMENSION_CODE_MAP = {
    "حجم": "volume", "وزن خالص": "net_weight", "ویسکوزیته": "viscosity", "گرانروی": "viscosity",
    "درجه گرانروی": "viscosity", "رنگ": "color", "سایز": "size", "اندازه": "size", "تعداد در بسته": "pack_qty",
}

EXPAND_TEXTS = ["مشاهده بیشتر", "نمایش بیشتر", "مشاهده همه", "نمایش همه", "مشخصات کامل", "نمایش کامل",
                "ادامه مطلب", "مشاهده کامل", "بیشتر بخوانید", "همه مشخصات", "مشاهده همه مشخصات",
                "نمایش مشخصات کامل", "Show more", "Read more", "See more"]


# ---------------------------------------------------------------------------
# بسته‌ی صفحه
# ---------------------------------------------------------------------------

@dataclass
class PageBundle:
    url: str
    final_url: str = ""
    status: int | None = None
    html: str = ""
    api: Any = None
    xhr: list = field(default_factory=list)          # [{url, status, json}]
    states: dict = field(default_factory=dict)       # name -> obj
    screenshot: str = ""
    title: str = ""
    _soup: BeautifulSoup | None = None
    _jsonld: list | None = None
    _meta: dict | None = None

    @property
    def soup(self) -> BeautifulSoup:
        if self._soup is None:
            self._soup = BeautifulSoup(self.html or "", "lxml")
        return self._soup

    @property
    def base_url(self) -> str:
        return self.final_url or self.url

    @property
    def jsonld(self) -> list:
        if self._jsonld is None:
            out: list = []
            for s in self.soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
                txt = s.string or s.get_text() or ""
                try:
                    data = json.loads(txt.strip())
                except ValueError:
                    try:
                        data = json.loads(re.sub(r"[\x00-\x1f]", " ", txt.strip()))
                    except ValueError:
                        continue
                stack = data if isinstance(data, list) else [data]
                for obj in stack:
                    if isinstance(obj, dict) and "@graph" in obj and isinstance(obj["@graph"], list):
                        out.extend(o for o in obj["@graph"] if isinstance(o, dict))
                    elif isinstance(obj, dict):
                        out.append(obj)
            self._jsonld = out
        return self._jsonld

    @property
    def meta(self) -> dict:
        if self._meta is None:
            m: dict = {}
            for t in self.soup.find_all("meta"):
                k = t.get("property") or t.get("name") or t.get("itemprop")
                v = t.get("content")
                if k and v and k not in m:
                    m[k] = v
            self._meta = m
        return self._meta

    def state(self, name: str) -> Any:
        if name in self.states:
            return self.states[name]
        if name == "__NEXT_DATA__":
            tag = self.soup.find("script", id="__NEXT_DATA__")
            if tag and tag.string:
                try:
                    self.states[name] = json.loads(tag.string)
                    return self.states[name]
                except ValueError:
                    pass
        return None


# ---------------------------------------------------------------------------
# مسیرهای JSON مثل data.product.images.list[].url[0]
# ---------------------------------------------------------------------------

_SEG_RE = re.compile(r"([^.\[\]]+)|\[(\d*|\*)\]")


def _parse_path(path: str) -> list:
    segs: list = []
    for m in _SEG_RE.finditer(path or ""):
        if m.group(1) is not None:
            segs.append(m.group(1))
        else:
            g = m.group(2)
            segs.append("[]" if g in ("", "*") else int(g))
    return segs


def resolve_path(obj: Any, path: str) -> list:
    """همه‌ی مقادیر منطبق با مسیر را برمی‌گرداند (به صورت فهرست)."""
    if not path:
        return [obj] if obj is not None else []
    cur = [obj]
    for seg in _parse_path(path):
        nxt: list = []
        for c in cur:
            if c is None:
                continue
            if seg == "[]" or seg == "*":
                if isinstance(c, list):
                    nxt.extend(c)
                elif isinstance(c, dict):
                    nxt.extend(c.values())
            elif isinstance(seg, int):
                if isinstance(c, list) and -len(c) <= seg < len(c):
                    nxt.append(c[seg])
            else:
                if isinstance(c, dict) and seg in c:
                    nxt.append(c[seg])
                elif isinstance(c, list):
                    # دسترسی ضمنی به همه‌ی اعضای آرایه
                    for el in c:
                        if isinstance(el, dict) and seg in el:
                            nxt.append(el[seg])
        cur = nxt
    return [c for c in cur if c is not None and c != "" and c != []]


def flatten(obj: Any, prefix: str = "", out: list | None = None, limit: int = 2500) -> list:
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out, limit)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:60]):
            flatten(v, f"{prefix}[{i}]", out, limit)
    else:
        if obj is None or obj == "":
            return out
        s = str(obj)
        out.append({"path": prefix, "value": s[:240]})
    return out


# ---------------------------------------------------------------------------
# حدس هوشمند (Auto)
# ---------------------------------------------------------------------------

_SPEC_HINT = re.compile(r"spec|attribute|attr|feature|propert|param|detail|technical|مشخصات|ویژگی", re.I)
_IMG_HINT = re.compile(r"gallery|slider|swiper|carousel|product|thumb|zoom|image|photo|media|picture", re.I)
_IMG_SKIP = re.compile(r"logo|icon|sprite|avatar|placeholder|banner|badge|flag|emoji|loading|blank|pixel|\.svg", re.I)
_DESC_HINT = re.compile(r"description|review|content|about|intro|detail|توضیح|معرفی|نقد", re.I)


def _jsonld_products(b: PageBundle) -> list[dict]:
    res = []
    for o in b.jsonld:
        t = o.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(str(x).lower() == "product" for x in types):
            res.append(o)
    return res


def _img_urls_from_jsonld_image(v: Any) -> list[str]:
    out: list[str] = []
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, list):
        for x in v:
            out.extend(_img_urls_from_jsonld_image(x))
    elif isinstance(v, dict):
        for k in ("contentUrl", "url"):
            if isinstance(v.get(k), str):
                out.append(v[k])
                break
    return out


def _best_from_srcset(srcset: str) -> str:
    best, best_w = "", -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1:
            w = int(parse_number(bits[1]) or 0)
        if w >= best_w:
            best, best_w = bits[0], w
    return best


def _img_src(tag: Tag) -> str:
    for a in ("data-zoom-image", "data-large", "data-full", "data-src-large", "data-original", "data-lazy-src",
              "data-src", "src"):
        v = tag.get(a)
        if v and not str(v).startswith("data:"):
            return v
    ss = tag.get("srcset") or tag.get("data-srcset")
    if ss:
        return _best_from_srcset(ss)
    return ""


def auto_images(b: PageBundle) -> list[str]:
    urls: list[str] = []
    for p in _jsonld_products(b):
        urls.extend(_img_urls_from_jsonld_image(p.get("image")))
    containers = [t for t in b.soup.find_all(True, attrs={"class": True})
                  if _IMG_HINT.search(" ".join(t.get("class", [])))]
    for c in containers[:40]:
        for img in c.find_all(["img", "source"]):
            src = _img_src(img)
            if not src:
                continue
            w = parse_number(img.get("width")) if img.get("width") else None
            if w is not None and w < 120:
                continue
            urls.append(src)
    og = b.meta.get("og:image")
    if og:
        urls.append(og)
    out, seen = [], set()
    for u in urls:
        u = urljoin(b.base_url, u.strip())
        if _IMG_SKIP.search(u):
            continue
        k = norm_image_key(u)
        if k in seen:
            continue
        seen.add(k)
        out.append(u)
    return out[:30]


def _heading_before(tag: Tag) -> str:
    h = tag.find_previous(["h2", "h3", "h4", "caption", "strong"])
    if h:
        t = clean_text(h.get_text(" "))
        if 0 < len(t) <= 60:
            return t
    return ""


def auto_specs(b: PageBundle) -> list[dict]:
    soup = b.soup
    specs: list[dict] = []
    seen: set = set()

    def add(group: str, name: str, value: str) -> None:
        name = clean_text(name).rstrip(":：").strip()
        value = clean_text(value)
        if not name or not value or len(name) > 70 or len(value) > 600 or name == value:
            return
        key = (name, value)
        if key in seen:
            return
        seen.add(key)
        specs.append({"group": group or "", "name": name, "value": value})

    # جدول‌ها
    for table in soup.find_all("table"):
        group = ""
        cap = table.find("caption")
        group = clean_text(cap.get_text(" ")) if cap else _heading_before(table)
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if len(cells) == 2:
                add(group, cells[0].get_text(" "), cells[1].get_text("\n"))
            elif len(cells) == 1 and cells[0].name == "th":
                group = clean_text(cells[0].get_text(" "))
    # فهرست‌های تعریف
    for dl in soup.find_all("dl"):
        group = _heading_before(dl)
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                add(group, dt.get_text(" "), dd.get_text("\n"))
    # ردیف‌های key/value داخل ظرف‌های «مشخصات»
    containers = [t for t in soup.find_all(True)
                  if _SPEC_HINT.search(" ".join(t.get("class", [])) + " " + (t.get("id") or ""))]
    for c in containers[:30]:
        group = _heading_before(c)
        for row in c.find_all(["li", "div", "p"], recursive=True):
            kids = [k for k in row.find_all(True, recursive=False) if clean_text(k.get_text(" "))]
            if len(kids) == 2 and not kids[0].find(["li", "table"]) and len(kids[0].get_text()) <= 70:
                add(group, kids[0].get_text(" "), kids[1].get_text("\n"))
            elif not kids:
                txt = clean_text(row.get_text(" "))
                m = re.match(r"^([^:：]{2,60})[:：]\s*(.+)$", txt)
                if m:
                    add(group, m.group(1), m.group(2))
    # JSON-LD additionalProperty
    for p in _jsonld_products(b):
        for prop in p.get("additionalProperty", []) or []:
            if isinstance(prop, dict):
                add("", str(prop.get("name", "")), str(prop.get("value", "")))
    return specs


def auto_value(key: str, b: PageBundle, ctx: dict) -> Any:
    prods = _jsonld_products(b)
    p = prods[0] if prods else {}
    if key == "title":
        if p.get("name"):
            return p["name"]
        h1 = b.soup.find("h1")
        if h1 and clean_text(h1.get_text(" ")):
            return h1.get_text(" ")
        return b.meta.get("og:title") or (b.soup.title.string if b.soup.title else "")
    if key == "brand":
        br = p.get("brand")
        if isinstance(br, dict) and br.get("name"):
            return br["name"]
        if isinstance(br, str) and br:
            return br
        return spec_lookup(ctx.get("specifications") or [], ["برند", "نام تجاری", "سازنده", "Brand"])
    if key == "sku":
        return p.get("sku") or p.get("mpn") or ""
    if key in ("long_description",):
        if p.get("description") and len(str(p["description"])) > 120:
            return p["description"]
        best = ""
        for t in b.soup.find_all(True, attrs={"class": True}):
            cls = " ".join(t.get("class", [])) + " " + (t.get("id") or "")
            if _DESC_HINT.search(cls):
                txt = clean_text(t.get_text("\n"))
                if len(txt) > len(best) and len(txt) < 20000:
                    best = txt
        return best or p.get("description") or b.meta.get("description", "")
    if key == "short_description":
        return b.meta.get("description") or b.meta.get("og:description") or ""
    if key == "featured_image":
        imgs = ctx.get("gallery") or auto_images(b)
        return imgs[0] if imgs else ""
    if key == "gallery":
        return auto_images(b)
    if key == "specifications":
        return auto_specs(b)
    if key == "price":
        offers = p.get("offers")
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict):
            return offers.get("price") or offers.get("lowPrice")
        return None
    if key == "breadcrumb":
        for o in b.jsonld:
            if str(o.get("@type", "")).lower() == "breadcrumblist":
                names = []
                for el in o.get("itemListElement", []) or []:
                    if isinstance(el, dict):
                        nm = el.get("name") or (el.get("item") or {}).get("name") if isinstance(el.get("item"), dict) else el.get("name")
                        if nm:
                            names.append(str(nm))
                if names:
                    return names
        nav = b.soup.find(attrs={"class": re.compile("breadcrumb", re.I)}) or b.soup.find("nav", attrs={"aria-label": re.compile("breadcrumb", re.I)})
        if nav:
            return [clean_text(a.get_text(" ")) for a in nav.find_all(["a", "span"]) if clean_text(a.get_text(" "))]
        return []
    if key == "category":
        bc = ctx.get("breadcrumb") or auto_value("breadcrumb", b, ctx)
        if isinstance(bc, list) and len(bc) >= 2:
            return bc[-2] if len(bc) > 2 else bc[-1]
        return ""
    return None


def spec_lookup(specs: list, names: list[str]) -> str:
    names_n = [normalize_fa(n).strip() for n in names]
    for s in specs or []:
        nm = normalize_fa(str(s.get("name", ""))).strip()
        if nm in names_n:
            return s.get("value", "")
    for s in specs or []:
        nm = normalize_fa(str(s.get("name", ""))).strip()
        if any(n and n in nm for n in names_n):
            return s.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# راهبردها
# ---------------------------------------------------------------------------

def _css_values(b: PageBundle, st: dict) -> list:
    sel = st.get("selector") or ""
    if not sel:
        return []
    try:
        nodes = b.soup.select(sel)
    except Exception:  # noqa: BLE001 - انتخابگر نامعتبر
        return []
    if not st.get("all"):
        nodes = nodes[:1]
    attr = st.get("attr") or "text"
    out = []
    for n in nodes:
        if attr == "text":
            out.append(n.get_text("\n"))
        elif attr == "html":
            out.append(str(n))
        elif attr == "src":
            out.append(_img_src(n) if n.name in ("img", "source") else n.get("src", ""))
        else:
            out.append(n.get(attr, ""))
    return [o for o in out if o]


def run_strategy(st: dict, b: PageBundle, key: str, ctx: dict) -> Any:
    t = st.get("type")
    if t == "api":
        return resolve_path(b.api, st.get("path", ""))
    if t == "xhr":
        match = st.get("match", "")
        for x in b.xhr:
            if match and match not in x.get("url", ""):
                continue
            vals = resolve_path(x.get("json"), st.get("path", ""))
            if vals:
                return vals
        return []
    if t == "jsonld":
        at = (st.get("at_type") or "").lower()
        for o in b.jsonld:
            ty = o.get("@type")
            tys = [str(x).lower() for x in (ty if isinstance(ty, list) else [ty])]
            if at and at not in tys:
                continue
            vals = resolve_path(o, st.get("path", ""))
            if vals:
                return vals
        return []
    if t == "state":
        return resolve_path(b.state(st.get("name", "__NEXT_DATA__")), st.get("path", ""))
    if t == "css":
        return _css_values(b, st)
    if t == "meta":
        v = b.meta.get(st.get("name", ""))
        return [v] if v else []
    if t == "regex":
        target = st.get("target", "html")
        src = b.html if target == "html" else (b.base_url if target == "url" else b.soup.get_text("\n"))
        try:
            rx = re.compile(st.get("pattern", ""), re.S)
        except re.error:
            return []
        g = int(st.get("group", 1) or 0)
        if st.get("all"):
            return [m.group(g) for m in rx.finditer(src or "")]
        m = rx.search(src or "")
        return [m.group(g)] if m else []
    if t == "spec":
        v = spec_lookup(ctx.get("specifications") or [], st.get("names", []))
        return [v] if v else []
    if t == "auto":
        v = auto_value(key, b, ctx)
        if v is None or v == "" or v == []:
            return []
        return v if isinstance(v, list) and key not in ("specifications",) else [v]
    if t == "const":
        return [st.get("value")]
    return []


# ---------------------------------------------------------------------------
# تبدیل‌ها
# ---------------------------------------------------------------------------

def norm_image_key(u: str) -> str:
    p = urlparse(u)
    return f"{p.netloc}{p.path}".lower()


def strip_query(u: str, keep: list | None = None) -> str:
    p = urlparse(u)
    if not p.query:
        return u
    if keep:
        q = [(k, v) for k, v in parse_qsl(p.query) if k in keep]
        return urlunparse(p._replace(query=urlencode(q)))
    return urlunparse(p._replace(query=""))


def _specs_from_groups(values: list, opt: dict) -> list[dict]:
    out: list[dict] = []
    gk, ik, nk, vk = opt.get("group", "title"), opt.get("items", "attributes"), opt.get("name", "title"), opt.get("value", "values")
    for g in values:
        if not isinstance(g, dict):
            continue
        if ik not in g and "name" in g and "value" in g:
            out.append(g)   # قبلاً به فرم مشخصات استاندارد درآمده (مثلاً از حدس هوشمند)
            continue
        gname = str(g.get(gk, "") or "")
        for it in g.get(ik, []) or []:
            if not isinstance(it, dict):
                continue
            v = it.get(vk)
            if isinstance(v, list):
                v = "، ".join(str(x) for x in v if x not in (None, ""))
            out.append({"group": gname, "name": str(it.get(nk, "")), "value": str(v or "")})
    return out


def _specs_from_kv(values: list, opt: dict) -> list[dict]:
    nk, vk, gk = opt.get("name", "name"), opt.get("value", "value"), opt.get("group", "")
    out = []
    for it in values:
        if isinstance(it, dict):
            v = it.get(vk)
            if isinstance(v, list):
                v = "، ".join(str(x) for x in v)
            out.append({"group": str(it.get(gk, "")) if gk else "", "name": str(it.get(nk, "")), "value": str(v or "")})
    return out


def apply_transforms(values: list, transforms: list, base_url: str) -> list:
    vals = list(values)
    for tr in transforms or []:
        t = tr if isinstance(tr, str) else tr.get("type")
        opt = {} if isinstance(tr, str) else tr
        if t == "text":
            vals = [html_to_text(v) if isinstance(v, str) else v for v in vals]
        elif t == "strip":
            vals = [v.strip() if isinstance(v, str) else v for v in vals]
        elif t == "first":
            vals = vals[:1]
        elif t == "last":
            vals = vals[-1:]
        elif t == "unique":
            seen, nv = set(), []
            for v in vals:
                k = json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else v
                if k not in seen:
                    seen.add(k)
                    nv.append(v)
            vals = nv
        elif t == "abs_url":
            vals = [urljoin(base_url, v) if isinstance(v, str) else v for v in vals]
        elif t == "strip_query":
            vals = [strip_query(v, opt.get("keep")) if isinstance(v, str) else v for v in vals]
        elif t == "replace":
            try:
                rx = re.compile(opt.get("pattern", ""))
                vals = [rx.sub(opt.get("repl", ""), v) if isinstance(v, str) else v for v in vals]
            except re.error:
                pass
        elif t == "split":
            sep = opt.get("sep", ",")
            nv = []
            for v in vals:
                nv.extend([s.strip() for s in v.split(sep)] if isinstance(v, str) else [v])
            vals = [v for v in nv if v != ""]
        elif t == "join":
            vals = [opt.get("sep", "\n").join(str(v) for v in vals)] if vals else []
        elif t == "latin_digits":
            vals = [to_latin_digits(v) if isinstance(v, str) else v for v in vals]
        elif t == "number":
            vals = [parse_number(v) for v in vals]
            vals = [v for v in vals if v is not None]
        elif t == "multiply":
            vals = [v * float(opt.get("by", 1)) if isinstance(v, (int, float)) else v for v in vals]
        elif t == "limit":
            vals = vals[: int(opt.get("n", 10))]
        elif t == "skip":
            vals = vals[int(opt.get("n", 1)):]
        elif t == "prefix":
            vals = [f"{opt.get('value', '')}{v}" for v in vals]
        elif t == "json_parse":
            nv = []
            for v in vals:
                try:
                    nv.append(json.loads(v) if isinstance(v, str) else v)
                except ValueError:
                    nv.append(v)
            vals = nv
        elif t == "specs_groups":
            vals = _specs_from_groups(vals, opt)
        elif t == "specs_kv":
            vals = _specs_from_kv(vals, opt)
        elif t == "flatten":
            nv = []
            for v in vals:
                nv.extend(v if isinstance(v, list) else [v])
            vals = nv
    return vals


def coerce(ftype: str, vals: list, base_url: str) -> Any:
    if ftype in ("text", "html"):
        txt = "\n".join(html_to_text(v) if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in vals if v not in (None, ""))
        return clean_text(txt)
    if ftype == "number":
        for v in vals:
            n = parse_number(v)
            if n is not None:
                return int(n) if n == int(n) else n
        return None
    if ftype == "image":
        for v in vals:
            if isinstance(v, str) and v.strip():
                return urljoin(base_url, v.strip())
        return ""
    if ftype == "images":
        out, seen = [], set()
        for v in vals:
            if isinstance(v, list):
                v = v[0] if v else ""
            if not isinstance(v, str) or not v.strip():
                continue
            u = urljoin(base_url, v.strip())
            k = norm_image_key(u)
            if k not in seen:
                seen.add(k)
                out.append(u)
        return out
    if ftype == "list":
        return [clean_text(v) if isinstance(v, str) else v for v in vals if v not in (None, "")]
    if ftype == "specs":
        out = []
        for v in vals:
            if isinstance(v, dict) and "name" in v:
                out.append({"group": clean_text(str(v.get("group", ""))), "name": clean_text(str(v["name"])),
                            "value": clean_text(str(v.get("value", "")))})
            elif isinstance(v, list):
                out.extend(coerce("specs", v, base_url))
        return [s for s in out if s["name"] and s["value"]]
    if ftype == "json":
        if len(vals) == 1:
            return vals[0]
        return vals
    return vals


# ---------------------------------------------------------------------------
# استخراج یک محصول
# ---------------------------------------------------------------------------

def field_defs(cfg: dict) -> list[dict]:
    defs = {f["key"]: dict(f) for f in CANONICAL_FIELDS}
    for f in cfg.get("fields", []):
        base = defs.get(f["key"], {"key": f["key"], "label": f.get("label", f["key"]), "type": f.get("type", "text")})
        base.update({k: v for k, v in f.items() if v is not None})
        defs[f["key"]] = base
    order = ["specifications", "breadcrumb", "gallery"]
    keys = order + [k for k in defs if k not in order]
    return [defs[k] for k in keys if k in defs]


AI_FALLBACK_DEFAULT = ["title", "brand", "category", "short_description", "long_description", "specifications", "featured_image", "gallery"]


def extract_product(b: PageBundle, cfg: dict, explain: bool = False) -> tuple[dict, dict]:
    """خروجی: (رکورد استاندارد، توضیح راهبرد موفق هر فیلد)."""
    ctx: dict = {}
    how: dict = {}
    defs = {}
    pending: dict[str, dict] = {}
    for fd in field_defs(cfg):
        key = fd["key"]
        defs[key] = fd
        strategies = fd.get("strategies")
        if strategies is None:
            strategies = [{"type": "auto"}] if key in CANONICAL_KEYS else []
        value = None
        ai_st = None
        for i, st in enumerate(strategies):
            if st.get("type") == "ai":
                # راهبرد هوش مصنوعی وقتی اجرا می‌شود که بقیه‌ی راهبردهای این فیلد چیزی پیدا نکنند
                ai_st = ai_st or (i + 1, st)
                continue
            try:
                raw = run_strategy(st, b, key, ctx)
            except Exception as exc:  # noqa: BLE001
                if explain:
                    how.setdefault(key, {"errors": []})["errors"].append(f"#{i + 1}: {exc}")
                continue
            if not raw:
                continue
            raw = apply_transforms(raw if isinstance(raw, list) else [raw], fd.get("transforms", []), b.base_url)
            v = coerce(fd.get("type", "text"), raw, b.base_url)
            if v not in (None, "", [], {}):
                value = v
                how[key] = {"strategy": i + 1, "type": st.get("type")}
                break
        if value is not None:
            ctx[key] = value
        elif ai_st:
            pending[key] = {"type": fd.get("type", "text"), "label": fd.get("label", key), "mode": ai_st[1].get("mode", "extract"),
                            "instruction": ai_st[1].get("instruction", ""), "strategy": ai_st[0]}
    fb = (cfg.get("product") or {}).get("ai_fallback") or {}
    if fb.get("enabled"):
        for k in fb.get("fields") or AI_FALLBACK_DEFAULT:
            fd = defs.get(k)
            if fd and ctx.get(k) in (None, "", [], {}) and k not in pending:
                pending[k] = {"type": fd.get("type", "text"), "label": fd.get("label", k), "mode": fb.get("mode", "extract"),
                              "instruction": (fb.get("instructions") or {}).get(k, ""), "strategy": "fallback"}
    if pending and not cfg.get("_no_ai"):
        try:
            from .ai_extract import run as ai_run
            vals, _ = ai_run(b, pending, ctx, cfg)
            for k, v in vals.items():
                fd = defs[k]
                raw = apply_transforms(v if isinstance(v, list) else [v], fd.get("transforms", []), b.base_url)
                cv = coerce(fd.get("type", "text"), raw, b.base_url)
                if cv not in (None, "", [], {}):
                    ctx[k] = cv
                    how[k] = {"strategy": pending[k]["strategy"], "type": "ai", "mode": pending[k]["mode"]}
            missing = [k for k in pending if k not in vals]
            if missing and explain:
                how["_ai"] = {"asked": list(pending), "empty": missing}
        except Exception as exc:  # noqa: BLE001
            how["_ai"] = {"asked": list(pending), "error": str(exc)}
    return finalize_record(ctx, cfg), how


def finalize_record(rec: dict, cfg: dict) -> dict:
    rec = dict(rec)
    gallery = rec.get("gallery") or []
    feat = rec.get("featured_image") or ""
    if not feat and gallery:
        feat = gallery[0]
    if feat:
        fk = norm_image_key(feat)
        gallery = [g for g in gallery if norm_image_key(g) != fk]
    limit = int(cfg.get("max_gallery", 12) or 12)
    rec["featured_image"] = feat
    rec["gallery"] = gallery[:limit]
    specs = rec.get("specifications") or []
    if not rec.get("dimensions"):
        dims = dimensions_from_specs(specs)
        if any(dims.values()):
            rec["dimensions"] = dims
    if not rec.get("dimension_codes"):
        codes = dimension_codes_from(specs, rec.get("variants"), cfg.get("dimension_code_map") or DEFAULT_DIMENSION_CODE_MAP)
        if codes:
            rec["dimension_codes"] = codes
    if not rec.get("brand") and specs:
        b = spec_lookup(specs, ["برند", "نام تجاری", "Brand"])
        if b:
            rec["brand"] = b
    return rec


# ---------------------------------------------------------------------------
# ابعاد و کدهای متغیر از روی مشخصات
# ---------------------------------------------------------------------------

def _fmt(n: float | None) -> str:
    if n is None:
        return ""
    n = round(n, 2)
    return str(int(n)) if n == int(n) else str(n)


def _to_grams(text: str) -> float | None:
    t = normalize_fa(to_latin_digits(text)).lower()
    n = parse_number(t)
    if n is None:
        return None
    if "میلی‌گرم" in t or "میلی گرم" in t or re.search(r"\bmg\b", t):
        return n / 1000
    if "کیلو" in t or re.search(r"\bkg\b", t):
        return n * 1000
    if "تن" in t.split():
        return n * 1_000_000
    return n


def _to_cm(n: float | None, text: str) -> float | None:
    if n is None:
        return None
    t = normalize_fa(text).lower()
    if "میلی" in t or "mm" in t:
        return n / 10
    if re.search(r"(^|\s)متر|(^|\s)m(\s|$)", t) and "سانتی" not in t:
        return n * 100
    return n


def dimensions_from_specs(specs: list) -> dict:
    d = {k: "" for k in DIMENSION_KEYS}
    for s in specs or []:
        name = normalize_fa(s.get("name", ""))
        val = str(s.get("value", ""))
        pack = "بسته" in name or "کارتن" in name or "package" in name.lower()
        pre = "packaging_" if pack else "item_"
        if "وزن" in name or "weight" in name.lower():
            g = _to_grams(val)
            if g is not None and not d[pre + "weight"]:
                d[pre + "weight"] = _fmt(g)
        elif "ابعاد" in name or "dimension" in name.lower() or "اندازه" in name:
            nums = re.findall(r"\d+(?:\.\d+)?", to_latin_digits(val).replace("٫", "."))
            if len(nums) >= 3:
                l, w, h = (_to_cm(float(x), val) for x in nums[:3])
                for k, v in (("length", l), ("width", w), ("height", h)):
                    if not d[pre + k]:
                        d[pre + k] = _fmt(v)
        else:
            for fa, en in (("طول", "length"), ("عرض", "width"), ("ارتفاع", "height"), ("پهنا", "width"), ("قطر", "width")):
                if name.startswith(fa) or name == fa:
                    n = parse_number(to_latin_digits(val))
                    if n is not None and not d[pre + en]:
                        d[pre + en] = _fmt(_to_cm(n, val))
    return d


def dimension_codes_from(specs: list, variants: Any, code_map: dict) -> dict:
    codes: dict = {}
    for s in specs or []:
        nm = normalize_fa(s.get("name", "")).strip()
        for fa, code in code_map.items():
            if nm == normalize_fa(fa) and code not in codes:
                codes[code] = s.get("value", "")
    if isinstance(variants, list):
        for v in variants:
            if not isinstance(v, dict):
                continue
            for k in ("size", "color", "volume", "themes"):
                x = v.get(k)
                if isinstance(x, dict) and x.get("title"):
                    codes.setdefault(k, [])
                    if isinstance(codes[k], list) and x["title"] not in codes[k]:
                        codes[k].append(x["title"])
    return codes


# ---------------------------------------------------------------------------
# کاوشگر داده برای آزمایش زنده
# ---------------------------------------------------------------------------

def explorer(b: PageBundle) -> dict:
    groups = []
    if b.api is not None:
        groups.append({"type": "api", "label": "پاسخ API", "match": "", "leaves": flatten(b.api)})
    for i, o in enumerate(b.jsonld[:6]):
        groups.append({"type": "jsonld", "label": f"JSON-LD · {o.get('@type', '?')}", "at_type": str(o.get("@type", "")) if not isinstance(o.get("@type"), list) else "",
                       "leaves": flatten(o, limit=800)})
    nd = b.state("__NEXT_DATA__")
    if nd:
        groups.append({"type": "state", "name": "__NEXT_DATA__", "label": "Next.js (__NEXT_DATA__)", "leaves": flatten(nd, limit=2500)})
    for name, obj in b.states.items():
        if name == "__NEXT_DATA__" or obj is None:
            continue
        groups.append({"type": "state", "name": name, "label": f"وضعیت صفحه ({name})", "leaves": flatten(obj, limit=2000)})
    for x in b.xhr[:25]:
        u = urlparse(x.get("url", ""))
        groups.append({"type": "xhr", "match": u.path, "label": f"درخواست شبکه · {u.netloc}{u.path}", "leaves": flatten(x.get("json"), limit=1500)})
    metas = [{"path": k, "value": str(v)[:240]} for k, v in b.meta.items()]
    h = []
    for tag in b.soup.find_all(["h1", "h2"])[:15]:
        t = clean_text(tag.get_text(" "))
        if t:
            h.append({"tag": tag.name, "text": t[:200]})
    return {
        "groups": groups,
        "meta": metas,
        "headings": h,
        "auto_specs": auto_specs(b)[:120],
        "auto_images": auto_images(b),
        "html_size": len(b.html or ""),
        "title": b.title or (b.soup.title.string if b.soup.title and b.soup.title.string else ""),
    }
