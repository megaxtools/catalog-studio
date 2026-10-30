"""راهنمای اتصال ایجنت‌ها به MCP استودیو و نصب خودکار در پیکربندی کلاینت‌ها."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

from . import db
from .config import PORT, ROOT_DIR
from .mcp_core import TOOLS

NAME = "mega-catalog-studio"


def _python() -> str:
    exe = Path(sys.executable)
    # در ویندوز pythonw پنجره‌ی کنسول باز نمی‌کند ولی stdio دارد؛ python.exe مطمئن‌تر است
    return str(exe)


def _script() -> str:
    return str(ROOT_DIR / "mcp_server.py")


def urls(token: str = "") -> dict:
    base = f"http://127.0.0.1:{PORT}"
    return {"http": f"{base}/mcp", "http_token_path": f"{base}/mcp/t/{token}" if token else "",
            "sse": f"{base}/mcp/sse", "sse_token_path": f"{base}/mcp/t/{token}/sse" if token else ""}


def _home() -> Path:
    return Path.home()


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (_home() / "AppData" / "Roaming"))


def claude_desktop_path() -> Path:
    if sys.platform == "win32":
        return _appdata() / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return _home() / ".config" / "Claude" / "claude_desktop_config.json"


def _stdio_entry() -> dict:
    return {"command": _python(), "args": [_script()], "env": {"PYTHONUTF8": "1"}}


# کلاینت‌هایی که پیکربندی JSON با mcpServers دارند و می‌توان خودکار نصب کرد
INSTALLERS = {
    "claude_desktop": {"name": "Claude Desktop", "path": claude_desktop_path, "key": "mcpServers", "entry": "stdio"},
    "cursor": {"name": "Cursor", "path": lambda: _home() / ".cursor" / "mcp.json", "key": "mcpServers", "entry": "stdio"},
    "windsurf": {"name": "Windsurf", "path": lambda: _home() / ".codeium" / "windsurf" / "mcp_config.json", "key": "mcpServers", "entry": "stdio"},
    "antigravity": {"name": "Google Antigravity", "path": lambda: _home() / ".gemini" / "config" / "mcp_config.json", "key": "mcpServers", "entry": "stdio"},
    "gemini_cli": {"name": "Gemini CLI", "path": lambda: _home() / ".gemini" / "settings.json", "key": "mcpServers", "entry": "stdio"},
    "lmstudio": {"name": "LM Studio", "path": lambda: _home() / ".lmstudio" / "mcp.json", "key": "mcpServers", "entry": "stdio"},
    "opencode": {"name": "opencode", "path": lambda: _home() / ".config" / "opencode" / "opencode.json", "key": "mcp", "entry": "opencode"},
}


def install(client: str, name: str = NAME) -> dict:
    spec = INSTALLERS.get(client)
    if not spec:
        raise ValueError("این کلاینت نصب خودکار ندارد؛ پیکربندی را از صفحه‌ی MCP کپی کنید.")
    path = spec["path"]()
    data: dict = {}
    if path.exists():
        txt = path.read_text(encoding="utf-8").strip()
        if txt:
            try:
                data = json.loads(txt)
            except ValueError as exc:
                raise ValueError(f"فایل پیکربندی {path} JSON معتبر نیست (شاید کامنت دارد)؛ پیکربندی را دستی اضافه کنید.") from exc
        shutil.copyfile(path, path.with_suffix(path.suffix + f".bak-{int(time.time())}"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    if spec["entry"] == "opencode":
        data.setdefault("$schema", "https://opencode.ai/config.json")
        entry = {"type": "local", "command": [_python(), _script()], "enabled": True, "environment": {"PYTHONUTF8": "1"}}
    else:
        entry = _stdio_entry()
    data.setdefault(spec["key"], {})[name] = entry
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "client": spec["name"], "path": str(path),
            "note": f"{spec['name']} را یک بار کامل ببندید و دوباره باز کنید تا ابزارهای «{name}» ظاهر شوند."}


def install_claude_desktop(name: str = NAME) -> dict:
    return install("claude_desktop", name)


def new_token() -> str:
    tok = secrets.token_urlsafe(24)
    db.set_settings({"mcp_token": tok})
    return tok


def info() -> dict:
    st = db.get_settings()
    token = st.get("mcp_token") or ""
    u = urls(token)
    py, sc = _python(), _script()
    stdio_json = json.dumps({"mcpServers": {NAME: _stdio_entry()}}, ensure_ascii=False, indent=2)
    auth_hdr = {"Authorization": f"Bearer {token}"} if token else {}
    http_json_url = lambda key: json.dumps({"mcpServers": {NAME: {key: u["http"], **({"headers": auth_hdr} if token else {})}}}, ensure_ascii=False, indent=2)  # noqa: E731
    yaml_stdio = (f"mcp_servers:\n  {NAME.replace('-', '_')}:\n    command: \"{py.replace(chr(92), '/')}\"\n    args: [\"{sc.replace(chr(92), '/')}\"]\n"
                  f"    env:\n      PYTHONUTF8: \"1\"")
    yaml_http = f"mcp_servers:\n  {NAME.replace('-', '_')}:\n    url: \"{u['http']}\"" + (f"\n    headers:\n      Authorization: \"Bearer {token}\"" if token else "")
    opencode = json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {NAME: {"type": "local", "command": [py, sc], "enabled": True,
                                                                                       "environment": {"PYTHONUTF8": "1"}}}}, ensure_ascii=False, indent=2)
    opencode_remote = json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {NAME: {"type": "remote", "url": u["http"], "enabled": True,
                                                                                              **({"headers": auth_hdr} if token else {})}}}, ensure_ascii=False, indent=2)
    codex = f'[mcp_servers.{NAME.replace("-", "_")}]\ncommand = {json.dumps(py)}\nargs = [{json.dumps(sc)}]\nenv = {{ PYTHONUTF8 = "1" }}'
    vscode = json.dumps({"servers": {NAME: {"type": "stdio", "command": py, "args": [sc], "env": {"PYTHONUTF8": "1"}}}}, ensure_ascii=False, indent=2)
    claude_code = f'claude mcp add {NAME} --scope user -- "{py}" "{sc}"\n# یا اتصال HTTP:\nclaude mcp add --transport http {NAME} {u["http"]}' + \
        (f' --header "Authorization: Bearer {token}"' if token else "")
    clients = [
        {"id": "claude_desktop", "name": "Claude Desktop", "kind": "stdio", "file": str(claude_desktop_path()), "format": "json", "snippet": stdio_json,
         "install": True, "notes": "با «نصب خودکار» به فایل پیکربندی اضافه می‌شود؛ سپس Claude Desktop را کامل ببندید و باز کنید."},
        {"id": "claude_code", "name": "Claude Code", "kind": "cli", "file": "خط فرمان", "format": "bash", "snippet": claude_code, "install": False,
         "notes": "دستور را در ترمینال اجرا کنید."},
        {"id": "opencode", "name": "opencode", "kind": "stdio", "file": "~/.config/opencode/opencode.json یا opencode.json پروژه", "format": "json",
         "snippet": opencode, "alt": opencode_remote, "install": True, "notes": "نسخه‌ی دوم (remote) برای اتصال HTTP است."},
        {"id": "chatgpt", "name": "ChatGPT Desktop / Web (Developer mode)", "kind": "remote", "file": "Settings → Apps & Connectors → Advanced → Developer mode → Create",
         "format": "text", "snippet": ("۱) در همین صفحه یک توکن بسازید.\n۲) یک تونل HTTPS به استودیو باز کنید، مثلاً:\n"
                                       f"   cloudflared tunnel --url http://127.0.0.1:{PORT}\n"
                                       "۳) در ChatGPT یک Connector جدید بسازید با نشانی:\n"
                                       f"   https://<آدرس-تونل>/mcp/t/{token or '<توکن>'}\n   و Authentication را «No authentication» بگذارید (توکن داخل نشانی است)."),
         "install": False, "notes": "ChatGPT فقط به سرورهای HTTPS عمومی وصل می‌شود. از بیرون فقط مسیر MCP با توکن باز است و رابط استودیو بسته می‌ماند."},
        {"id": "antigravity", "name": "Google Antigravity", "kind": "stdio", "file": "Agent panel → … → MCP Servers → Manage MCP Servers → View raw config",
         "format": "json", "snippet": stdio_json, "alt": json.dumps({"mcpServers": {NAME: {"serverUrl": u["http"], **({"headers": auth_hdr} if token else {})}}}, ensure_ascii=False, indent=2),
         "install": True, "notes": "اگر نصب خودکار در Antigravity دیده نشد، همین JSON را در «View raw config» بچسبانید. نسخه‌ی دوم اتصال HTTP است (serverUrl)."},
        {"id": "hermes", "name": "Hermes Agent", "kind": "stdio", "file": "~/.hermes/config.yaml", "format": "yaml", "snippet": yaml_stdio, "alt": yaml_http,
         "install": False, "notes": "زیر کلید mcp_servers اضافه کنید. نسخه‌ی دوم اتصال HTTP است."},
        {"id": "cursor", "name": "Cursor", "kind": "stdio", "file": "~/.cursor/mcp.json", "format": "json", "snippet": stdio_json, "alt": http_json_url("url"), "install": True},
        {"id": "windsurf", "name": "Windsurf", "kind": "stdio", "file": "~/.codeium/windsurf/mcp_config.json", "format": "json", "snippet": stdio_json,
         "alt": http_json_url("serverUrl"), "install": True},
        {"id": "vscode", "name": "VS Code (Copilot)", "kind": "stdio", "file": ".vscode/mcp.json", "format": "json", "snippet": vscode, "install": False},
        {"id": "gemini_cli", "name": "Gemini CLI", "kind": "stdio", "file": "~/.gemini/settings.json", "format": "json", "snippet": stdio_json,
         "alt": http_json_url("httpUrl"), "install": True},
        {"id": "codex", "name": "OpenAI Codex CLI", "kind": "stdio", "file": "~/.codex/config.toml", "format": "toml", "snippet": codex, "install": False},
        {"id": "lmstudio", "name": "LM Studio", "kind": "stdio", "file": "~/.lmstudio/mcp.json", "format": "json", "snippet": stdio_json, "install": True},
        {"id": "generic", "name": "هر ایجنت دیگر (n8n، Dify، LibreChat، Cline، …)", "kind": "any", "file": "—", "format": "text",
         "snippet": (f"stdio:  {py} {sc}\nStreamable HTTP:  {u['http']}\nSSE (قدیمی):  {u['sse']}\n"
                     + (f"Header:  Authorization: Bearer {token}\nیا نشانی با توکن:  {u['http_token_path']}" if token else "بدون توکن (فقط از همین رایانه)")),
         "install": False},
    ]
    return {"enabled": st.get("mcp_enabled", True), "read_only": st.get("mcp_read_only", False), "token": token, "urls": u,
            "python": py, "script": sc, "tools": len(TOOLS), "write_tools": sum(1 for t in TOOLS.values() if t["write"]),
            "tool_list": [{"name": k, "description": t["spec"]["description"][:160], "write": t["write"],
                           "destructive": t["spec"]["annotations"]["destructiveHint"]} for k, t in TOOLS.items()],
            "clients": clients}
