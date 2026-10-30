"""اتصال به سرویس‌دهنده‌های هوش مصنوعی: سازگار با OpenAI (هر Base URL و روتر)، Anthropic و Google Gemini."""
from __future__ import annotations

import base64
import json
import re
import threading
import time

import requests

from . import db

# پیش‌تنظیم‌ها (همه قابل ویرایش‌اند)
PRESETS: list[dict] = [
    {"id": "openai", "name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "image_mode": "images_api",
     "hint": "مدل متنی و تصویری را با «دریافت فهرست مدل‌ها» انتخاب کنید."},
    {"id": "anthropic", "name": "Anthropic (Claude)", "kind": "anthropic", "base_url": "https://api.anthropic.com", "image_mode": "none",
     "hint": "فقط تولید متن؛ Claude تصویر تولید نمی‌کند."},
    {"id": "gemini", "name": "Google Gemini", "kind": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "image_mode": "gemini",
     "hint": "برای تولید تصویر یک مدل تصویری Gemini را در «مدل تصویر» انتخاب کنید."},
    {"id": "openrouter", "name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "image_mode": "chat_modalities",
     "hint": "روتر چندمدلی؛ نام مدل به شکل provider/model است."},
    {"id": "avalai", "name": "AvalAI", "kind": "openai", "base_url": "https://api.avalai.ir/v1", "image_mode": "images_api",
     "hint": "روتر ایرانی سازگار با OpenAI. آدرس جایگزین: https://api.avalapis.ir/v1"},
    {"id": "deepseek", "name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "image_mode": "none", "hint": ""},
    {"id": "groq", "name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "image_mode": "none", "hint": ""},
    {"id": "mistral", "name": "Mistral", "kind": "openai", "base_url": "https://api.mistral.ai/v1", "image_mode": "none", "hint": ""},
    {"id": "xai", "name": "xAI (Grok)", "kind": "openai", "base_url": "https://api.x.ai/v1", "image_mode": "images_api", "hint": ""},
    {"id": "together", "name": "Together AI", "kind": "openai", "base_url": "https://api.together.xyz/v1", "image_mode": "images_api", "hint": ""},
    {"id": "ollama", "name": "Ollama (محلی)", "kind": "openai", "base_url": "http://localhost:11434/v1", "image_mode": "none",
     "hint": "مدل‌های محلی روی همین سیستم؛ کلید API لازم نیست."},
    {"id": "lmstudio", "name": "LM Studio (محلی)", "kind": "openai", "base_url": "http://localhost:1234/v1", "image_mode": "none", "hint": ""},
    {"id": "custom", "name": "روتر یا سرویس دلخواه (OpenAI-compatible)", "kind": "openai", "base_url": "", "image_mode": "images_api",
     "hint": "Base URL را از مستندات سرویس‌دهنده وارد کنید (معمولاً به /v1 ختم می‌شود)."},
]


class AIError(Exception):
    """fatal=True یعنی تکرار بی‌فایده است (کلید نامعتبر، مدل ناموجود، اعتبار تمام‌شده، قطع شبکه) و اجرای گروهی باید فوراً بایستد."""

    def __init__(self, msg: str = "", fatal: bool = False):
        super().__init__(msg)
        self.fatal = fatal


class AICancelled(AIError):
    """کاربر اجرا را متوقف کرده است."""


# زمینه‌ی هر درخواست (برای ثبت در گزارش درخواست‌های هوش مصنوعی): کار، محصول، هدف
_ctx = threading.local()


def set_context(**kw):
    _ctx.data = {k: v for k, v in kw.items() if v is not None}


def get_context() -> dict:
    return dict(getattr(_ctx, "data", None) or {})


def _log_call(client: "AIClient", kind: str, model: str, started: float, ok: bool, error: str = "", prompt: str = "",
              response: str = "", tokens: int = 0, status: int | None = None):
    try:
        ctx = {**get_context(), **(client.context or {})}
        db.ex("""INSERT INTO ai_calls(ts, provider_id, provider, model, kind, purpose, ref, item_id, ok, status, error, ms, tokens, prompt, response)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              [db.now(), client.p.get("id"), client.p.get("name"), model or "", kind, ctx.get("purpose", ""), str(ctx.get("ref", "")),
               ctx.get("item_id"), 1 if ok else 0, status, error[:2000], int((time.time() - started) * 1000), tokens,
               prompt[:6000], response[:4000]])
    except Exception:  # noqa: BLE001
        pass  # ثبت گزارش هرگز نباید درخواست را خراب کند


def provider_row(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["headers"] = db.jload(r.get("headers"), {}) or {}
    return r


def get_provider(pid: int) -> dict | None:
    return provider_row(db.q1("SELECT * FROM ai_providers WHERE id=?", [pid]))


def public_provider(p: dict) -> dict:
    p = dict(p)
    k = p.get("api_key") or ""
    p["api_key_masked"] = ("•" * 8 + k[-4:]) if len(k) > 4 else ("•" * len(k))
    p["has_key"] = bool(k)
    p.pop("api_key", None)
    return p


def parse_json(text: str):
    """اولین شیء یا آرایه‌ی JSON داخل متن را برمی‌گرداند."""
    if not text:
        raise AIError("پاسخ خالی بود.")
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s = t.find(open_c)
        e = t.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except ValueError:
                continue
    raise AIError("پاسخ مدل JSON معتبر نبود.")


class AIClient:
    def __init__(self, provider: dict):
        self.p = provider
        self.kind = provider["kind"]
        self.base = (provider.get("base_url") or "").rstrip("/")
        self.key = provider.get("api_key") or ""
        self.timeout = int(provider.get("timeout_s") or 90)
        self.s = requests.Session()
        if provider.get("proxy"):
            self.s.proxies = {"http": provider["proxy"], "https": provider["proxy"]}
        self.usage_tokens = 0
        self.cancel_check = None   # تابعی که اگر True برگرداند، درخواست‌ها متوقف می‌شوند
        self.context: dict = {}
        self._last_status = None

    def _check_cancel(self):
        if self.cancel_check and self.cancel_check():
            raise AICancelled("اجرا به درخواست کاربر متوقف شد.")

    def _sleep(self, sec: float):
        end = time.time() + sec
        while time.time() < end:
            self._check_cancel()
            time.sleep(min(0.25, max(0.0, end - time.time())))

    # ------------------------------------------------------------------ HTTP
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.kind == "anthropic":
            h.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        elif self.kind == "gemini":
            if self.key:
                h["x-goog-api-key"] = self.key
        elif self.key:
            h["Authorization"] = f"Bearer {self.key}"
        if "openrouter.ai" in self.base:
            h.setdefault("HTTP-Referer", "https://megacars.ir")
            h.setdefault("X-Title", "Mega Catalog Studio")
        h.update(self.p.get("headers") or {})
        return h

    def _req(self, method: str, url: str, body: dict | None = None, tries: int = 3) -> dict:
        last = None
        for i in range(tries):
            self._check_cancel()
            try:
                r = self.s.request(method, url, headers=self._headers(), json=body, timeout=(15, self.timeout))
            except requests.RequestException as exc:
                last = AIError(f"ارتباط با سرویس برقرار نشد: {exc}", fatal=True)
                if i < tries - 1:
                    self._sleep(2 * (i + 1))
                continue
            self._last_status = r.status_code
            text = r.text[:600]
            low = text.lower()
            if r.status_code == 429 and any(w in low for w in ("quota", "insufficient", "billing", "credit", "balance", "exceeded your")):
                raise AIError(f"اعتبار یا سهمیه‌ی این اتصال تمام شده است (HTTP 429): {text[:300]}", fatal=True)
            if r.status_code in (429, 500, 502, 503, 504, 529):
                last = AIError(f"سرویس موقتاً پاسخ نداد (HTTP {r.status_code}): {text[:300]}")
                if i < tries - 1:
                    self._sleep(min(20, 3 * (2 ** i)))
                continue
            if r.status_code >= 400:
                msg = text
                try:
                    j = r.json()
                    msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("error") or j.get("message") or msg)
                except ValueError:
                    pass
                if r.status_code in (401, 403):
                    raise AIError(f"کلید API پذیرفته نشد یا دسترسی ندارید (HTTP {r.status_code}): {msg}", fatal=True)
                if r.status_code == 402:
                    raise AIError(f"اعتبار حساب این اتصال کافی نیست (HTTP 402): {msg}", fatal=True)
                if r.status_code == 404:
                    raise AIError(f"آدرس سرویس یا مدل پیدا نشد (HTTP 404): {msg}", fatal=True)
                if r.status_code == 400 and "model" in str(msg).lower():
                    raise AIError(f"مدل نامعتبر است (HTTP 400): {msg}", fatal=True)
                raise AIError(f"خطای سرویس (HTTP {r.status_code}): {msg}")
            try:
                return r.json()
            except ValueError as exc:
                raise AIError(f"پاسخ سرویس JSON نبود: {r.text[:300]}") from exc
        raise last or AIError("درخواست ناموفق بود.")

    # ------------------------------------------------------------------ متن
    def chat(self, system: str, user: str, model: str | None = None, temperature: float = 0.7,
             max_tokens: int = 2000, images: list[bytes] | None = None) -> str:
        t0, tok0 = time.time(), self.usage_tokens
        m = model or self.p.get("text_model") or ""
        try:
            out = self._chat(system, user, model, temperature, max_tokens, images)
        except AICancelled:
            raise
        except Exception as exc:
            _log_call(self, "chat", m, t0, False, str(exc), f"[system]\n{system}\n\n[user]\n{user}", tokens=self.usage_tokens - tok0, status=self._last_status)
            raise
        _log_call(self, "chat", m, t0, True, "", f"[system]\n{system}\n\n[user]\n{user}", out, self.usage_tokens - tok0, self._last_status)
        return out

    def _chat(self, system: str, user: str, model: str | None = None, temperature: float = 0.7,
              max_tokens: int = 2000, images: list[bytes] | None = None) -> str:
        model = model or self.p.get("text_model")
        if not model:
            raise AIError("مدل متنی برای این اتصال انتخاب نشده است.")
        if self.kind == "anthropic":
            content: list = [{"type": "text", "text": user}]
            for im in images or []:
                content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": _mime(im), "data": base64.b64encode(im).decode()}})
            j = self._req("POST", f"{self.base}/v1/messages", {
                "model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                "messages": [{"role": "user", "content": content}]})
            u = j.get("usage") or {}
            self.usage_tokens += int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))
            return "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        if self.kind == "gemini":
            parts: list = [{"text": user}]
            for im in images or []:
                parts.append({"inline_data": {"mime_type": _mime(im), "data": base64.b64encode(im).decode()}})
            j = self._req("POST", f"{self.base}/models/{model}:generateContent", {
                "systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}})
            u = j.get("usageMetadata") or {}
            self.usage_tokens += int(u.get("totalTokenCount", 0))
            cands = j.get("candidates") or []
            if not cands:
                raise AIError(f"Gemini پاسخی برنگرداند: {json.dumps(j.get('promptFeedback', {}), ensure_ascii=False)[:300]}")
            return "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
        # سازگار با OpenAI
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:{_mime(im)};base64,{base64.b64encode(im).decode()}"}} for im in images]
        else:
            content = user
        body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        j = self._req("POST", f"{self.base}/chat/completions", body)
        u = j.get("usage") or {}
        self.usage_tokens += int(u.get("total_tokens", 0))
        ch = j.get("choices") or []
        if not ch:
            raise AIError(f"پاسخی دریافت نشد: {json.dumps(j, ensure_ascii=False)[:300]}")
        msg = ch[0].get("message") or {}
        c = msg.get("content")
        if isinstance(c, list):
            c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
        return c or ""

    # ------------------------------------------------------------------ تصویر
    def image(self, prompt: str, model: str | None = None, size: str = "1024x1024", reference: bytes | None = None) -> bytes:
        t0 = time.time()
        m = model or self.p.get("image_model") or ""
        try:
            out = self._image(prompt, model, size, reference)
        except AICancelled:
            raise
        except Exception as exc:
            _log_call(self, "image", m, t0, False, str(exc), prompt + (" [+reference]" if reference else ""), status=self._last_status)
            raise
        _log_call(self, "image", m, t0, True, "", prompt + (" [+reference]" if reference else ""), f"[{len(out)} bytes]", status=self._last_status)
        return out

    def _image(self, prompt: str, model: str | None = None, size: str = "1024x1024", reference: bytes | None = None) -> bytes:
        model = model or self.p.get("image_model")
        mode = self.p.get("image_mode") or "images_api"
        if self.kind == "anthropic" or mode == "none":
            raise AIError("این اتصال تولید تصویر را پشتیبانی نمی‌کند.")
        if not model:
            raise AIError("مدل تصویر برای این اتصال انتخاب نشده است.")
        if self.kind == "gemini" or mode == "gemini":
            parts: list = [{"text": prompt}]
            if reference:
                parts.append({"inline_data": {"mime_type": _mime(reference), "data": base64.b64encode(reference).decode()}})
            j = self._req("POST", f"{self.base}/models/{model}:generateContent", {
                "contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
            for c in j.get("candidates") or []:
                for p in (c.get("content") or {}).get("parts", []):
                    d = p.get("inline_data") or p.get("inlineData")
                    if d and d.get("data"):
                        return base64.b64decode(d["data"])
            raise AIError("مدل تصویری برنگرداند.")
        if mode == "chat_modalities":
            content: list | str = prompt
            if reference:
                content = [{"type": "text", "text": prompt},
                           {"type": "image_url", "image_url": {"url": f"data:{_mime(reference)};base64,{base64.b64encode(reference).decode()}"}}]
            j = self._req("POST", f"{self.base}/chat/completions", {
                "model": model, "modalities": ["image", "text"], "messages": [{"role": "user", "content": content}]})
            msg = ((j.get("choices") or [{}])[0]).get("message") or {}
            for im in msg.get("images") or []:
                u = (im.get("image_url") or {}).get("url", "")
                if u.startswith("data:"):
                    return base64.b64decode(u.split(",", 1)[1])
                if u:
                    return self.s.get(u, timeout=self.timeout).content
            raise AIError("مدل تصویری برنگرداند.")
        # images_api
        if reference:
            files = {"image": ("reference.png", reference, _mime(reference))}
            data = {"model": model, "prompt": prompt, "size": size, "n": "1"}
            h = {k: v for k, v in self._headers().items() if k.lower() != "content-type"}
            r = self.s.post(f"{self.base}/images/edits", headers=h, files=files, data=data, timeout=max(self.timeout, 180))
            if r.status_code >= 400:
                raise AIError(f"ویرایش تصویر ناموفق بود (HTTP {r.status_code}): {r.text[:300]}")
            j = r.json()
        else:
            body = {"model": model, "prompt": prompt, "size": size, "n": 1}
            if "dall-e" in model:
                body["response_format"] = "b64_json"
            j = self._req("POST", f"{self.base}/images/generations", body)
        d = (j.get("data") or [{}])[0]
        if d.get("b64_json"):
            return base64.b64decode(d["b64_json"])
        if d.get("url"):
            return self.s.get(d["url"], timeout=self.timeout).content
        raise AIError("سرویس تصویری برنگرداند.")

    # ------------------------------------------------------------------ مدل‌ها
    def list_models(self) -> list[str]:
        if self.kind == "anthropic":
            j = self._req("GET", f"{self.base}/v1/models?limit=100", tries=1)
            return sorted(m.get("id") for m in j.get("data", []) if m.get("id"))
        if self.kind == "gemini":
            j = self._req("GET", f"{self.base}/models?pageSize=200", tries=1)
            return sorted(m.get("name", "").removeprefix("models/") for m in j.get("models", []) if m.get("name"))
        j = self._req("GET", f"{self.base}/models", tries=1)
        items = j.get("data") if isinstance(j, dict) else j
        return sorted({m.get("id") for m in (items or []) if isinstance(m, dict) and m.get("id")})

    def ping(self) -> dict:
        t0 = time.time()
        out = self.chat("You are a health check.", "Reply with the single word: OK", max_tokens=20, temperature=0)
        return {"ok": True, "reply": out.strip()[:80], "ms": int((time.time() - t0) * 1000)}


def _mime(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
