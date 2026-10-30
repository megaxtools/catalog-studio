import { S, api, icon, esc, attr, fa, toast, okToast, errToast, confirmDlg } from './core.js';

const M = { info: null, client: 'claude_desktop', alt: false, showTools: false };

async function copy(text) {
  try { await navigator.clipboard.writeText(text); okToast('کپی شد.'); }
  catch (e) {
    const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); okToast('کپی شد.'); } catch (e2) { toast('کپی ممکن نشد؛ دستی انتخاب کنید.', 'err'); }
    t.remove();
  }
}

export const MCP = {
  title: 'اتصال ایجنت‌ها (MCP)',
  crumb: 'اتصال Claude، ChatGPT، opencode، Antigravity، Hermes، Cursor و هر ایجنت دیگر به استودیو',
  async render() {
    M.info = await api('/api/mcp/info');
    return `<div id="mcp-body"></div>`;
  },
  mount() { this.draw(); },
  draw() {
    const i = M.info;
    const c = i.clients.find((x) => x.id === M.client) || i.clients[0];
    const snippet = M.alt && c.alt ? c.alt : c.snippet;
    document.getElementById('mcp-body').innerHTML = `
    <div class="grid g-side">
      <div class="stack">
        <div class="card"><div class="card-b flex wrap">
          <div class="src-logo">${icon('cpu', 20)}</div>
          <div class="grow"><b style="font-size:15px;color:var(--z-900)">سرور MCP ${i.enabled ? 'فعال است' : 'خاموش است'}</b>
            <div class="small muted">${fa(i.tools)} ابزار (${fa(i.tools - i.write_tools)} خواندنی، ${fa(i.write_tools)} نوشتنی) · منابع و پرامپت‌های آماده · stdio، Streamable HTTP و SSE</div></div>
          <label class="check"><input type="checkbox" data-change="enabled" ${i.enabled ? 'checked' : ''}> فعال</label>
          <label class="check"><input type="checkbox" data-change="ro" ${i.read_only ? 'checked' : ''}> فقط‌خواندنی</label>
          <button class="btn soft" data-act="selftest">${icon('flask', 16)} خودآزمایی</button>
        </div><div id="st-out" class="card-b p0" style="padding:0 20px 14px !important"></div></div>

        <div class="card">
          <div class="card-h"><h2>اتصال یک ایجنت</h2><span class="sub">ایجنت را انتخاب کنید</span></div>
          <div class="card-b">
            <div class="flex wrap mb16">${i.clients.map((x) => `<button class="btn sm ${x.id === c.id ? 'primary' : ''}" data-act="client" data-id="${x.id}">${esc(x.name)}</button>`).join('')}</div>
            <div class="flex wrap mb8"><b style="color:var(--z-900)">${esc(c.name)}</b>
              <span class="tag">${{ stdio: 'stdio (اجرای محلی)', remote: 'HTTPS عمومی', cli: 'خط فرمان', any: 'همه‌ی روش‌ها' }[c.kind] || c.kind}</span>
              ${c.alt ? `<div class="seg"><button class="${M.alt ? '' : 'on'}" data-act="alt" data-v="0">stdio</button><button class="${M.alt ? 'on' : ''}" data-act="alt" data-v="1">HTTP</button></div>` : ''}
              <span class="grow"></span>
              ${c.install && !M.alt ? `<button class="btn sm primary" data-act="install" data-id="${c.id}">${icon('download', 14)} نصب خودکار</button>` : ''}
              <button class="btn sm" data-act="copy">${icon('copy', 14)} کپی</button></div>
            <div class="small muted mb8">${icon('folder', 13)} محل: <span class="ltr" style="unicode-bidi:plaintext">${esc(c.file)}</span></div>
            ${c.format === 'text' ? `<div class="outbox" style="unicode-bidi:plaintext">${esc(snippet)}</div>` : `<pre class="tree" style="white-space:pre-wrap;word-break:break-all;max-height:360px">${esc(snippet)}</pre>`}
            ${c.notes ? `<div class="alert info mt12">${icon('info')}<div>${esc(c.notes)}</div></div>` : ''}
            <div id="inst-out" class="mt8"></div>
          </div>
        </div>

        <div class="card"><div class="card-h"><h3>ابزارهای در دسترس ایجنت</h3><span class="sp"></span><button class="btn sm ghost" data-act="tools">${icon(M.showTools ? 'chevronUp' : 'chevronDown', 14)} ${M.showTools ? 'بستن' : 'نمایش همه'}</button></div>
          ${M.showTools ? `<table class="tbl"><tbody>${i.tool_list.map((t) => `<tr><td class="ltr nowrap" style="width:220px"><span class="kbd">${esc(t.name)}</span></td>
            <td class="small">${esc(t.description)}</td><td class="nowrap">${t.destructive ? '<span class="chip err">حذف</span>' : t.write ? '<span class="chip wait">نوشتن</span>' : '<span class="chip ok">خواندن</span>'}</td></tr>`).join('')}</tbody></table>` : ''}
        </div>
      </div>

      <div class="stack">
        <div class="card"><div class="card-h"><h3>نشانی‌ها</h3></div><div class="card-b small">
          <div class="lbl">Streamable HTTP</div><div class="pathbox mt8">${esc(i.urls.http)}</div>
          <div class="lbl mt12">SSE (برای کلاینت‌های قدیمی)</div><div class="pathbox mt8">${esc(i.urls.sse)}</div>
          <div class="lbl mt12">stdio</div><div class="pathbox mt8">${esc(i.python)} ${esc(i.script)}</div>
          <div class="hint mt8">در حالت stdio اگر استودیو باز نباشد، خودکار در پس‌زمینه اجرا می‌شود.</div>
        </div></div>
        <div class="card"><div class="card-h"><h3>توکن دسترسی</h3></div><div class="card-b small">
          ${i.token ? `<div class="pathbox">${esc(i.token)}</div>
            <div class="btns mt8"><button class="btn sm" data-act="copytok">${icon('copy', 14)} کپی</button><button class="btn sm" data-act="token">${icon('refresh', 14)} توکن تازه</button><button class="btn sm ghost danger" data-act="cleartok">${icon('trash', 14)} حذف</button></div>
            <div class="hint mt8">با توکن، اتصال HTTP فقط با <span class="kbd">Authorization: Bearer …</span> یا نشانی <span class="kbd">/mcp/t/&lt;توکن&gt;</span> پذیرفته می‌شود.</div>`
          : `<div class="muted">بدون توکن، اتصال HTTP فقط از همین رایانه پذیرفته می‌شود (برای Claude Desktop، opencode، Antigravity، Hermes و Cursor کافی است).</div>
            <button class="btn sm primary mt12" data-act="token">${icon('shield', 14)} ساخت توکن</button>
            <div class="hint mt8">برای ChatGPT یا ایجنتی روی رایانه‌ی دیگر، توکن لازم است.</div>`}
        </div></div>
        <div class="card"><div class="card-h"><h3>امنیت</h3></div><div class="card-b small" style="line-height:2">
          <div class="flex top">${icon('shield', 15)}<span>رابط و API استودیو فقط از همین رایانه باز است؛ اگر استودیو را با تونل منتشر کنید، از بیرون فقط مسیر MCP با توکن پاسخ می‌دهد.</span></div>
          <div class="flex top">${icon('eye', 15)}<span>با «فقط‌خواندنی» ایجنت‌ها فقط می‌توانند ببینند و تحلیل کنند.</span></div>
          <div class="flex top">${icon('refresh', 15)}<span>نوشته‌های ایجنت مثل خروجی هوش مصنوعی برگشت‌پذیرند و ویرایش دستی شما بر آن‌ها مقدم است.</span></div>
        </div></div>
      </div>
    </div>`;
  },
  async reload() { M.info = await api('/api/mcp/info'); this.draw(); },
  act: {
    client: (el) => { M.client = el.dataset.id; M.alt = false; MCP.draw(); },
    alt: (el) => { M.alt = el.dataset.v === '1'; MCP.draw(); },
    tools: () => { M.showTools = !M.showTools; MCP.draw(); },
    copy: () => { const c = M.info.clients.find((x) => x.id === M.client); copy(M.alt && c.alt ? c.alt : c.snippet); },
    copytok: () => copy(M.info.token),
    token: async () => {
      if (M.info.token && !(await confirmDlg('توکن تازه', 'توکن فعلی باطل می‌شود و ایجنت‌هایی که با آن وصل‌اند باید توکن جدید بگیرند.', 'ساخت توکن تازه'))) return;
      await api('/api/mcp/token', { body: {} }); await MCP.reload(); okToast('توکن ساخته شد.');
    },
    cleartok: async () => { await api('/api/mcp/token', { body: { clear: true } }); await MCP.reload(); },
    install: async (el) => {
      const out = document.getElementById('inst-out');
      try {
        const r = await api('/api/mcp/install', { body: { client: el.dataset.id } });
        out.innerHTML = `<div class="alert ok">${icon('checkCircle')}<div><b>به ${esc(r.client)} اضافه شد.</b><span class="ltr" style="unicode-bidi:plaintext">${esc(r.path)}</span><br>${esc(r.note)}</div></div>`;
      } catch (e) { out.innerHTML = `<div class="alert err">${icon('alert')}<div>${esc(e.message)}</div></div>`; }
    },
    selftest: async () => {
      const out = document.getElementById('st-out');
      out.innerHTML = `<div class="small muted flex">${icon('loader', 15, 'spin')} در حال آزمایش…</div>`;
      const r = await api('/api/mcp/selftest', { body: {} });
      out.innerHTML = r.ok ? `<div class="alert ok">${icon('checkCircle')}<div><b>MCP سالم است.</b>پروتکل ${esc(r.protocol)} · ${fa(r.tools)} ابزار</div></div>` : `<div class="alert err">${icon('alert')}<div>${esc(r.overview || 'ناموفق')}</div></div>`;
    },
  },
  change: {
    enabled: async (el) => { await api('/api/settings', { method: 'PUT', body: { mcp_enabled: el.checked } }); MCP.reload(); },
    ro: async (el) => { await api('/api/settings', { method: 'PUT', body: { mcp_read_only: el.checked } }); MCP.reload(); },
  },
};
