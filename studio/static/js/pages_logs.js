// گزارش‌ها: رویدادها، فعالیت‌ها (همه‌ی درخواست‌ها حتی آزمایش‌ها)، درخواست‌های هوش مصنوعی، تاریخچه‌ی تغییرات داده
import { api, icon, esc, attr, fa, num, jdate, okToast, errToast, openLayer, confirmDlg, emptyState, every, trunc } from './core.js';
import { logRow } from './pages_main.js';

const LG = { tab: 'activity', page: 1, q: '', f: {}, data: null };
const TABS = [['activity', 'zap', 'فعالیت‌ها'], ['ai', 'sparkles', 'درخواست‌های هوش مصنوعی'], ['history', 'clock', 'تاریخچه‌ی تغییرات'], ['events', 'scroll', 'رویدادهای اجرا']];
const CLIENT = { ui: 'رابط کاربری', mcp: 'ایجنت (MCP)', api: 'API' };
const ACTOR = { ui: 'کاربر', mcp: 'ایجنت', ai: 'هوش مصنوعی', system: 'سیستم', api: 'API' };
const ENTITY = { item: 'محصول', export: 'خروجی', export_row: 'ردیف خروجی' };

export function pretty(v) {
  if (v === null || v === undefined || v === '') return '<span class="muted">—</span>';
  let s = v;
  if (typeof v === 'string') { try { s = JSON.stringify(JSON.parse(v), null, 2); } catch (e) { s = v; } } else s = JSON.stringify(v, null, 2);
  return `<pre class="pathbox" style="white-space:pre-wrap;max-height:340px;overflow:auto;direction:ltr;text-align:left">${esc(s)}</pre>`;
}

export function historyTable(rows, opts = {}) {
  if (!rows.length) return emptyState('clock', 'تغییری ثبت نشده است', '');
  return `<table class="tbl"><thead><tr><th>زمان</th>${opts.noEntity ? '' : '<th>مورد</th>'}<th>فیلد</th><th>کننده</th><th>قبل</th><th>بعد</th><th></th></tr></thead><tbody>
    ${rows.map((h) => `<tr><td class="small nowrap">${jdate(h.ts)}</td>
      ${opts.noEntity ? '' : `<td class="small nowrap">${esc(ENTITY[h.entity] || h.entity)} ${fa(h.entity_id)}${h.parent_id ? ` <span class="xs muted">· ${h.entity === 'item' ? 'بانک' : 'خروجی'} ${fa(h.parent_id)}</span>` : ''}</td>`}
      <td class="small ltr" style="text-align:right">${esc(h.field)} <span class="tag" style="font-size:10.5px">${esc(h.action)}</span>${h.note ? `<div class="xs muted">${esc(trunc(h.note, 40))}</div>` : ''}</td>
      <td class="small">${esc(ACTOR[h.actor] || h.actor)}</td>
      <td class="small" style="max-width:240px"><div class="ellipsis muted">${esc(trunc(h.old, 120))}</div></td>
      <td class="small" style="max-width:240px"><div class="ellipsis">${esc(trunc(h.new, 120))}</div></td>
      <td class="nowrap"><button class="btn xs ghost" data-hview="${h.id}" title="جزئیات">${icon('eye', 13)}</button>
        ${['edit', 'manual', 'ai', 'images', 'status'].includes(h.action) || /^(overrides|manual|ai):/.test(h.field) ? `<button class="btn xs ghost" data-hrevert="${h.id}" title="بازگرداندن مقدار قبلی">${icon('refresh', 13)}</button>` : ''}</td></tr>`).join('')}</tbody></table>`;
}

export function bindHistory(root, after) {
  root.addEventListener('click', async (ev) => {
    const v = ev.target.closest('[data-hview]');
    if (v) {
      const h = await api(`/api/history?id=${v.dataset.hview}`);
      openLayer('modal', `<div class="card-h"><h3>جزئیات تغییر</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="card-b"><div class="kpi-line mb12"><span>زمان <b>${jdate(h.ts)}</b></span><span>فیلد <b class="ltr">${esc(h.field)}</b></span><span>کننده <b>${esc(ACTOR[h.actor] || h.actor)}</b></span></div>
        <div class="grid g2"><div><div class="lbl mb8">مقدار قبلی</div>${pretty(h.old)}</div><div><div class="lbl mb8">مقدار جدید</div>${pretty(h.new)}</div></div></div>`, { wide: true });
    }
    const r = ev.target.closest('[data-hrevert]');
    if (r) {
      if (!(await confirmDlg('بازگرداندن تغییر', 'مقدار قبلی این فیلد بازگردانده شود؟ خود این بازگردانی هم در تاریخچه ثبت می‌شود.', 'بازگرداندن'))) return;
      try { await api(`/api/history/${r.dataset.hrevert}/revert`, { body: {} }); okToast('مقدار قبلی بازگردانده شد.'); if (after) after(); } catch (e) { errToast(e); }
    }
  });
}

export const Logs = {
  title: 'گزارش‌ها و تاریخچه',
  crumb: 'همه‌ی فعالیت‌ها، درخواست‌های هوش مصنوعی، تغییرات داده و رویدادهای اجرا — همه در پایگاه داده‌ی استودیو',
  async render() {
    LG.page = 1;
    return `<div class="card"><div class="tabs" id="lg-tabs"></div><div id="lg-bar"></div><div id="lg-body"></div><div class="pager" id="lg-pager"></div></div>`;
  },
  async mount(view) {
    bindHistory(view, () => this.load());
    view.addEventListener('click', (ev) => {
      const d = ev.target.closest('[data-detail]');
      if (d) this.detail(d.dataset.detail);
    });
    await this.draw();
    every(5000, () => { if (LG.page === 1 && !LG.q) this.load(true); });
  },
  async draw() {
    document.getElementById('lg-tabs').innerHTML = TABS.map(([k, ic, l]) => `<button class="${LG.tab === k ? 'on' : ''}" data-act="tab" data-t="${k}">${icon(ic, 16)} ${l}</button>`).join('');
    const bar = {
      activity: `<div class="seg">${[['', 'همه'], ['ui', 'رابط کاربری'], ['mcp', 'ایجنت‌ها'], ['api', 'API']].map(([k, l]) => `<button class="${(LG.f.client || '') === k ? 'on' : ''}" data-act="f" data-k="client" data-v="${k}">${l}</button>`).join('')}</div>
        <label class="check small"><input type="checkbox" data-change="errs" ${LG.f.errors ? 'checked' : ''}> فقط خطاها</label>`,
      ai: `<label class="check small"><input type="checkbox" data-change="errs" ${LG.f.errors ? 'checked' : ''}> فقط خطاها</label><span id="ai-sum" class="small muted"></span>`,
      history: `<div class="seg">${[['', 'همه'], ['item', 'محصولات'], ['export_row', 'ردیف‌های خروجی'], ['export', 'خروجی‌ها']].map(([k, l]) => `<button class="${(LG.f.entity || '') === k ? 'on' : ''}" data-act="f" data-k="entity" data-v="${k}">${l}</button>`).join('')}</div>
        <div class="seg">${[['', 'همه'], ['ui', 'کاربر'], ['ai', 'هوش مصنوعی'], ['mcp', 'ایجنت']].map(([k, l]) => `<button class="${(LG.f.actor || '') === k ? 'on' : ''}" data-act="f" data-k="actor" data-v="${k}">${l}</button>`).join('')}</div>`,
      events: `<div class="seg">${[['', 'همه'], ['dataset', 'اجراها'], ['ai', 'هوش مصنوعی'], ['export', 'خروجی‌ها'], ['bg', 'پردازش تصاویر'], ['queue', 'صف']].map(([k, l]) => `<button class="${(LG.f.scope || '') === k ? 'on' : ''}" data-act="f" data-k="scope" data-v="${k}">${l}</button>`).join('')}</div>
        <div class="seg">${[['', 'همه‌ی سطوح'], ['warning', 'هشدار'], ['error', 'خطا'], ['success', 'موفق']].map(([k, l]) => `<button class="${(LG.f.level || '') === k ? 'on' : ''}" data-act="f" data-k="level" data-v="${k}">${l}</button>`).join('')}</div>`,
    }[LG.tab];
    document.getElementById('lg-bar').innerHTML = `<div class="flex wrap" style="padding:14px 16px;border-bottom:1px solid var(--z-100)">${bar}<span class="grow"></span>
      ${LG.tab !== 'events' ? `<input class="inp sm" style="width:260px" placeholder="جست‌وجو…" data-input="q" value="${attr(LG.q)}">` : ''}</div>`;
    await this.load();
  },
  async load(silent) {
    const qs = new URLSearchParams({ page: LG.page, size: 50 });
    if (LG.q) qs.set('q', LG.q);
    Object.entries(LG.f).forEach(([k, v]) => { if (v) qs.set(k === 'errors' ? 'errors' : k, v === true ? '1' : v); });
    const body = document.getElementById('lg-body');
    if (!body) return;
    if (LG.tab === 'events') {
      const rows = await api(`/api/logs?${qs}`);
      body.innerHTML = rows.length ? `<div class="log" style="max-height:none">${rows.map((r) => logRow(r).replace('<div><div>', `<div><div><span class="tag" style="font-size:11px">${{ dataset: 'اجرا', export: 'خروجی', bg: 'تصاویر', ai: 'هوش مصنوعی', queue: 'صف' }[r.scope] || r.scope} ${r.ref_id ? fa(r.ref_id) : ''}</span> `)).join('')}</div>` : emptyState('scroll', 'رویدادی نیست', '');
      document.getElementById('lg-pager').innerHTML = '';
      return;
    }
    const url = { activity: '/api/activity', ai: '/api/ai-calls', history: '/api/history' }[LG.tab];
    const r = await api(`${url}?${qs}`);
    const sig = JSON.stringify(r.rows.map((x) => x.id));
    if (silent && body.dataset.sig === sig) return;
    body.dataset.sig = sig;
    if (LG.tab === 'activity') {
      body.innerHTML = r.rows.length ? `<table class="tbl"><thead><tr><th>زمان</th><th>فعالیت</th><th>منبع</th><th>وضعیت</th><th>مدت</th><th>ورودی</th><th></th></tr></thead><tbody>
        ${r.rows.map((a) => `<tr class="click" data-detail="activity:${a.id}"><td class="small nowrap">${jdate(a.ts)}</td>
          <td><b class="small" style="color:var(--z-900)">${esc(a.action || '')}</b><div class="xs muted ltr" style="text-align:right">${esc(a.method)} ${esc(a.path)}</div></td>
          <td class="small nowrap">${esc(CLIENT[a.client] || a.client)}</td>
          <td>${a.status >= 400 ? `<span class="chip err" title="${attr(a.error)}">${fa(a.status)}</span>` : `<span class="chip ok">${fa(a.status)}</span>`}</td>
          <td class="small nowrap">${fa(a.ms)} ms</td><td class="xs muted ltr" style="max-width:320px"><div class="ellipsis">${esc(a.request || '')}</div></td>
          <td>${icon('chevronLeft', 14)}</td></tr>`).join('')}</tbody></table>` : emptyState('zap', 'فعالیتی ثبت نشده', '');
    } else if (LG.tab === 'ai') {
      const s = r.sum || {};
      const el = document.getElementById('ai-sum');
      if (el) el.textContent = `کل: ${num(s.calls)} درخواست · ${num(s.tokens)} توکن · ${num(s.errors)} خطا`;
      body.innerHTML = r.rows.length ? `<table class="tbl"><thead><tr><th>زمان</th><th>هدف</th><th>اتصال / مدل</th><th>نوع</th><th>نتیجه</th><th>توکن</th><th>مدت</th><th></th></tr></thead><tbody>
        ${r.rows.map((a) => `<tr class="click" data-detail="ai:${a.id}"><td class="small nowrap">${jdate(a.ts)}</td>
          <td class="small"><b style="color:var(--z-900)">${esc(a.purpose || '—')}</b><div class="xs muted">${esc(a.ref || '')}${a.item_id ? ` · محصول ${fa(a.item_id)}` : ''}</div></td>
          <td class="small"><div>${esc(a.provider)}</div><div class="xs muted ltr" style="text-align:right">${esc(a.model)}</div></td>
          <td class="small">${a.kind === 'image' ? 'تصویر' : 'متن'}</td>
          <td>${a.ok ? '<span class="chip ok">موفق</span>' : `<span class="chip err" title="${attr(a.error)}">خطا</span><div class="xs" style="color:var(--err);max-width:220px">${esc(trunc(a.error, 70))}</div>`}</td>
          <td class="small">${num(a.tokens)}</td><td class="small nowrap">${fa((a.ms / 1000).toFixed(1))} ث</td><td>${icon('chevronLeft', 14)}</td></tr>`).join('')}</tbody></table>` : emptyState('sparkles', 'درخواستی ثبت نشده', '');
    } else {
      body.innerHTML = historyTable(r.rows);
    }
    const pages = Math.max(1, Math.ceil(r.total / r.size));
    document.getElementById('lg-pager').innerHTML = `
      <button class="btn sm" data-act="pg" data-p="${LG.page - 1}" ${LG.page <= 1 ? 'disabled' : ''}>${icon('chevronRight', 16)} قبلی</button>
      <span class="small">صفحه ${fa(LG.page)} از ${fa(pages)} · ${num(r.total)} مورد</span>
      <button class="btn sm" data-act="pg" data-p="${LG.page + 1}" ${LG.page >= pages ? 'disabled' : ''}>بعدی ${icon('chevronLeft', 16)}</button>`;
  },
  async detail(key) {
    const [kind, id] = key.split(':');
    if (kind === 'activity') {
      const a = await api(`/api/activity?id=${id}`);
      openLayer('modal', `<div class="card-h"><h3>${esc(a.action || 'فعالیت')}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="card-b"><div class="kpi-line mb12"><span>زمان <b>${jdate(a.ts)}</b></span><span>منبع <b>${esc(CLIENT[a.client] || a.client)}</b></span><span>وضعیت <b>${fa(a.status)}</b></span><span>مدت <b>${fa(a.ms)} ms</b></span></div>
        <div class="pathbox mb12 ltr">${esc(a.method)} ${esc(a.path)}</div>
        ${a.error ? `<div class="alert err mb12">${icon('alert')}<div>${esc(a.error)}</div></div>` : ''}
        <div class="grid g2"><div><div class="lbl mb8">ورودی</div>${pretty(a.request)}</div><div><div class="lbl mb8">پاسخ</div>${pretty(a.response)}</div></div></div>`, { wide: true });
    } else {
      const a = await api(`/api/ai-calls?id=${id}`);
      openLayer('modal', `<div class="card-h"><h3>درخواست هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="card-b"><div class="kpi-line mb12"><span>زمان <b>${jdate(a.ts)}</b></span><span>اتصال <b>${esc(a.provider)}</b></span><span>مدل <b class="ltr">${esc(a.model)}</b></span><span>توکن <b>${num(a.tokens)}</b></span><span>مدت <b>${fa(a.ms)} ms</b></span>${a.status ? `<span>HTTP <b>${fa(a.status)}</b></span>` : ''}</div>
        <div class="small mb12">${esc(a.purpose)} · ${esc(a.ref)}${a.item_id ? ` · محصول ${fa(a.item_id)}` : ''}</div>
        ${a.error ? `<div class="alert err mb12">${icon('alert')}<div>${esc(a.error)}</div></div>` : ''}
        <div class="lbl mb8">پرامپت</div><div class="outbox small" style="max-height:300px;overflow:auto;white-space:pre-wrap">${esc(a.prompt)}</div>
        <div class="lbl mt16 mb8">پاسخ</div><div class="outbox small" style="max-height:300px;overflow:auto;white-space:pre-wrap">${esc(a.response || '—')}</div></div>`, { wide: true });
    }
  },
  act: {
    tab: (el) => { LG.tab = el.dataset.t; LG.page = 1; LG.f = {}; LG.q = ''; Logs.draw(); },
    f: (el) => { LG.f[el.dataset.k] = el.dataset.v; LG.page = 1; el.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === el)); Logs.load(); },
    pg: (el) => { LG.page = Number(el.dataset.p); Logs.load(); },
  },
  change: { errs: (el) => { LG.f.errors = el.checked; LG.page = 1; Logs.load(); } },
  input: { q: (() => { let t; return (el) => { clearTimeout(t); t = setTimeout(() => { LG.q = el.value.trim(); LG.page = 1; Logs.load(); }, 350); }; })() },
};
