// ویرایشگر داده‌ها: بانک‌های تمیز، محصولات تمیز (فیلدها، برند، دسته، سازگاری، تصاویر، نسخه‌ها)، صف بازبینی و تکراری‌ها
import {
  S, api, icon, esc, attr, fa, num, jdate, toast, okToast, errToast, openLayer, confirmDlg, promptDlg, emptyState, every, go, trunc, debounce,
} from './core.js';
import { colInput, readCol, writeCol } from './pages_main.js';
import { busy, noProviderHint } from './ai_assist.js';
import { revisionsPanel, openRefPicker, compatChips, compatPicker, qualityBadge, statusChip, STATUS, fileToDataUrl, ACTOR, diffTable } from './widgets.js';

const modOn = (m) => (S.boot?.modules || {})[m] !== false;
const qmin = () => (S.boot?.settings?.quality || {}).min_score || 70;
const BSTAT = { pending: ['wait', 'در صف'], running: ['run', 'در حال ورود'], paused: ['wait', 'متوقف'], completed: ['ok', 'آماده'], error: ['err', 'خطا'] };
const bchip = (s) => { const [c, t] = BSTAT[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}</span>`; };
const FILTERS = [['nobrand', 'بدون برند'], ['nocategory', 'بدون دسته'], ['noimage', 'بدون تصویر'], ['compat_all', 'سازگاری: همه'], ['compat_auto', 'سازگاری خودکار تأییدنشده'],
  ['lowq', 'کیفیت پایین'], ['warn', 'دارای هشدار'], ['edited', 'ویرایش‌شده']];

// ======================================================================
// فهرست بانک‌های تمیز
// ======================================================================
export const Banks = {
  title: 'بانک‌های تمیز',
  crumb: 'ویرایشگر داده‌ها · داده‌ی خام را این‌جا تمیز، کامل و تأیید کنید',
  top: () => `<button class="btn primary" data-act="new">${icon('plus', 16)} بانک تمیز جدید</button>`,
  async render() {
    return `<div class="alert info">${icon('info')}<div><b>روند کار:</b> بانک تمیز از یک یا چند بانک داده‌ی خام ساخته می‌شود. در آن هر محصول را اصلاح می‌کنید (متن‌ها، برند، دسته، خودروهای سازگار، تصاویر)، برای بازبینی می‌فرستید و تأیید می‌کنید. فقط محصولات تأییدشده وارد کاتالوگ می‌شوند.</div></div>
      <div id="bk-list" class="mt16"></div>`;
  },
  async mount() { await this.load(); every(3000, () => this.load(true)); },
  async load(silent) {
    const list = await api('/api/wb/banks');
    const el = document.getElementById('bk-list');
    if (!el) return;
    const sig = JSON.stringify(list.map((b) => [b.id, b.status, b.progress_done, b.counts, b.quality_avg]));
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    el.innerHTML = list.length ? `<div class="grid2">${list.map((b) => {
      const pct = b.progress_total ? Math.round(b.progress_done / b.progress_total * 100) : 0;
      return `<div class="card"><div class="card-b">
        <div class="flex top"><span class="src-logo">${icon('inbox', 18)}</span><div class="grow"><a href="#/editor/${b.id}"><b style="font-size:15px;color:var(--z-900)">${esc(b.title)}</b></a>
          <div class="xs muted">${esc(b.code)} · ${jdate(b.created_at)} · اسکیما: ${esc(b.schema?.name || '—')}</div></div>${bchip(b.status)}</div>
        ${['running', 'pending'].includes(b.status) ? `<div class="mt12"><div class="prog"><i style="width:${pct}%"></i></div><div class="xs muted mt4">${esc(b.step || '')}</div></div>` : ''}
        ${b.status === 'error' ? `<div class="xs mt8" style="color:var(--err)">${esc(b.error)}</div>` : ''}
        <div class="kpi-line mt12"><span>محصولات <b>${num(b.counts.total)}</b></span><span>پیش‌نویس <b>${num(b.counts.draft)}</b></span><span>بازبینی <b>${num(b.counts.review)}</b></span>
          <span>تأییدشده <b>${num(b.counts.approved)}</b></span>${b.quality_avg !== null ? `<span>میانگین کیفیت <b>${fa(b.quality_avg)}</b></span>` : ''}</div>
        <div class="flex wrap mt8" style="gap:6px">${b.missing?.brand ? `<span class="tag" style="color:var(--warn)">${fa(b.missing.brand)} بدون برند</span>` : ''}${b.missing?.category ? `<span class="tag" style="color:var(--warn)">${fa(b.missing.category)} بدون دسته</span>` : ''}${b.missing?.images ? `<span class="tag" style="color:var(--warn)">${fa(b.missing.images)} بدون تصویر</span>` : ''}
          ${b.datasets.map((d) => `<a class="tag" href="#/datasets/${d.id}">${icon('database', 11)} ${esc(trunc(d.title, 30))}</a>`).join('')}</div>
        <div class="btns mt12"><a class="btn sm primary" href="#/editor/${b.id}">${icon('edit', 14)} ویرایش محصولات</a>
          <button class="btn sm icon ghost danger" data-act="del" data-id="${b.id}" title="حذف">${icon('trash', 14)}</button></div></div></div>`;
    }).join('')}</div>` : `<div class="card"><div class="card-b">${emptyState('inbox', 'هنوز بانک تمیزی ندارید', 'از یک بانک داده‌ی خام، بانک تمیز بسازید.', `<button class="btn primary" data-act="new">${icon('plus', 16)} بانک تمیز جدید</button>`)}</div></div>`;
  },
  act: {
    new: () => openNewBank(),
    del: async (el) => {
      if (!(await confirmDlg('حذف بانک تمیز', 'این بانک و همه‌ی محصولات تمیز و تصاویرش حذف شود؟ داده‌ی خام دست نمی‌خورد. انتشارهای قبلی کاتالوگ سالم می‌مانند.', 'حذف', true))) return;
      await api(`/api/wb/banks/${el.dataset.id}`, { method: 'DELETE' });
      okToast('حذف شد.'); Banks.load();
    },
  },
};

async function openNewBank(preselect = []) {
  const [dss, schemas] = await Promise.all([api('/api/datasets'), api('/api/schemas')]);
  const done = dss.filter((d) => ['completed', 'paused', 'stopped'].includes(d.status) || (d.counts?.done || 0) > 0);
  const legacy = modOn('legacy_export') ? await api('/api/catalogs').catch(() => []) : [];
  const sch = schemas.filter((s) => ['general', 'edit'].includes(s.usage || 'general'));
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('inbox', 18)} بانک تمیز جدید</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:72vh;overflow:auto">
      <div class="lbl mb8">۱. بانک‌های داده‌ی خام</div>
      <div class="pick-list" style="max-height:220px;border:1px solid var(--z-200);border-radius:12px;padding:6px">${done.map((d) => `<label class="pick"><input type="checkbox" data-ds="${d.id}" ${preselect.includes(d.id) ? 'checked' : ''}>
        <b>${esc(d.title)}</b><span class="xs muted">${num((d.counts?.done || 0) + (d.counts?.partial || 0))} محصول · ${jdate(d.created_at, false)}</span></label>`).join('') || '<div class="muted small">بانک داده‌ی خامی نیست.</div>'}</div>
      <div class="form-grid mt16"><div class="field"><label>عنوان بانک تمیز</label><input class="inp" id="nb-title" placeholder="مثلاً: روغن موتور — آماده‌ی مگا کارز"></div>
        <div class="field"><label>۲. اسکیمای ویرایش</label><select class="inp" id="nb-schema">${sch.map((s) => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
          <div class="hint">ستون‌هایی که در ویرایشگر می‌بینید. فقط اسکیماهای «عمومی» یا «ویرایشگر».</div></div></div>
      <div class="lbl mt16 mb8">۳. تصاویر</div>
      <div class="flex wrap" style="gap:14px"><label class="check"><input type="checkbox" id="nb-img" checked> دانلود تصاویر</label>
        ${modOn('rembg') ? '<label class="check"><input type="checkbox" id="nb-rembg" checked> حذف پس‌زمینه</label>' : ''}
        ${modOn('align') ? '<label class="check"><input type="checkbox" id="nb-align" checked> ترازبندی با قاعده‌ی پیش‌فرض تنظیمات</label>' : ''}
        <label class="check">حداکثر <input class="inp sm" type="number" id="nb-max" value="8" min="1" max="30" style="width:64px"> تصویر</label></div>
      ${modOn('vehicles') ? '<label class="check mt12"><input type="checkbox" id="nb-compat" checked> پیشنهاد خودکار «سازگاری با خودرو» از روی متن محصول (پیشنهادهای مطمئن اعمال می‌شوند و بعداً تأیید می‌کنید)</label>' : ''}
      ${legacy.length ? `<details class="mt24"><summary class="lbl" style="cursor:pointer">یا تبدیل یک «خروجی نهایی» نسخه‌ی ۱ به بانک تمیز</summary><div class="pick-list mt8">${legacy.filter((x) => x.managed).map((x) => `<button class="pick" data-legacy="${x.id}"><b>${esc(x.title)}</b><span class="xs muted">${num(x.rows)} ردیف</span><span class="grow"></span>${icon('chevronLeft', 14)}</button>`).join('')}</div></details>` : ''}
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="nb-ok">${icon('check', 16)} ساخت و ورود محصولات</button></div>`, { wide: true });
  const b = l.box;
  b.querySelector('#nb-ok').addEventListener('click', async () => {
    const ids = [...b.querySelectorAll('[data-ds]:checked')].map((x) => Number(x.dataset.ds));
    if (!ids.length) { toast('دست‌کم یک بانک داده‌ی خام انتخاب کنید.', 'err'); return; }
    try {
      const r = await api('/api/wb/banks', { body: { dataset_ids: ids, schema_id: Number(b.querySelector('#nb-schema').value), title: b.querySelector('#nb-title').value,
        images: b.querySelector('#nb-img').checked, rembg: b.querySelector('#nb-rembg')?.checked ?? false, align: b.querySelector('#nb-align')?.checked ?? false,
        max_images: Number(b.querySelector('#nb-max').value || 8), compat_suggest: b.querySelector('#nb-compat')?.checked ?? false } });
      okToast('بانک تمیز ساخته شد؛ ورود محصولات در پس‌زمینه انجام می‌شود.'); l.close(); go(`#/editor/${r.id}`);
    } catch (e) { errToast(e); }
  });
  b.querySelectorAll('[data-legacy]').forEach((x) => x.addEventListener('click', async () => {
    busy(x, true, 'در حال تبدیل…');
    try { const r = await api(`/api/wb/from-legacy/${x.dataset.legacy}`, { body: {} }); okToast(`${fa(r.products)} محصول منتقل شد.`); l.close(); go(`#/editor/${r.bank.id}`); } catch (e) { errToast(e); busy(x, false); }
  }));
}
export { openNewBank };

// ======================================================================
// یک بانک تمیز
// ======================================================================
const B = { id: 0, bank: null, status: '', flt: new Set(), q: '', sort: 'seq', page: 1, sel: new Set(), rows: null, allSel: false };
const roleCols = () => (B.bank?.columns || []);
const editCols = () => roleCols().filter((c) => !c.role);

export const Bank = {
  title: 'بانک تمیز',
  crumb: 'ویرایشگر داده‌ها',
  top: () => `<a class="btn ghost" href="#/editor">${icon('chevronRight', 16)} همه‌ی بانک‌ها</a>`,
  async render(p) {
    Object.assign(B, { id: Number(p.id), status: '', flt: new Set(), q: '', page: 1, sel: new Set(), allSel: false });
    B.bank = await api(`/api/wb/banks/${B.id}`);
    document.getElementById('page-title').textContent = B.bank.title;
    return `<div id="bk-head"></div>
      <div class="card mt16"><div id="bk-bar"></div><div class="tbl-wrap" id="bk-rows"></div><div class="pager" id="bk-pager"></div></div>`;
  },
  async mount() {
    this.head(); this.bar(); await this.load();
    every(3000, async () => {
      const b = await api(`/api/wb/banks/${B.id}`).catch(() => null);
      if (!b) return;
      const was = ['running', 'pending'].includes(B.bank.status);
      const changed = b.status !== B.bank.status || b.progress_done !== B.bank.progress_done;
      B.bank = b;
      if (changed) { this.head(); if (was) this.load(); }
      this.jobs();
    });
  },
  refresh() { return Promise.all([api(`/api/wb/banks/${B.id}`).then((b) => { B.bank = b; this.head(); }), this.load()]); },
  head() {
    const b = B.bank;
    const pct = b.progress_total ? Math.round(b.progress_done / b.progress_total * 100) : 0;
    document.getElementById('bk-head').innerHTML = `<div class="card"><div class="card-b">
      <div class="flex top wrap"><span class="src-logo">${icon('inbox', 20)}</span><div class="grow" style="min-width:280px">
        <b style="font-size:17px">${esc(b.title)}</b><div class="xs muted">${esc(b.code)} · اسکیمای ویرایش: <a href="#/schemas/${b.schema?.id}">${esc(b.schema?.name || '—')}</a> ·
          ${b.datasets.map((d) => `<a href="#/datasets/${d.id}">${esc(trunc(d.title, 40))}</a>`).join('، ')}</div></div>${bchip(b.status)}</div>
      ${['running', 'pending'].includes(b.status) ? `<div class="mt12 flex"><div class="grow"><div class="prog"><i style="width:${pct}%"></i></div><div class="xs muted mt4">${esc(b.step || '')}</div></div><button class="btn sm" data-act="stop">${icon('pause', 14)} توقف</button></div>` : ''}
      ${b.status === 'paused' ? `<div class="alert warn mt12">${icon('pause')}<div class="grow">ورود محصولات متوقف شده است.</div><button class="btn sm primary" data-act="resume">${icon('play', 14)} ادامه</button></div>` : ''}
      <div class="kpi-line mt12"><span>محصولات <b>${num(b.counts.total)}</b></span>${Object.entries(STATUS).filter(([k]) => !['merged'].includes(k)).map(([k, v]) => `<span>${v[1]} <b>${num(b.counts[k])}</b></span>`).join('')}
        ${b.quality_avg !== null ? `<span>میانگین کیفیت <b>${fa(b.quality_avg)}</b></span>` : ''}</div>
      <div class="btns mt12"><button class="btn sm soft" data-act="adds">${icon('plus', 14)} افزودن داده‌ی خام</button>
        ${modOn('ai') ? `<button class="btn sm soft" data-act="ai">${icon('sparkles', 14)} هوش مصنوعی</button>` : ''}
        ${modOn('quality') ? `<button class="btn sm ghost" data-act="rescore">${icon('star', 14)} محاسبه‌ی دوباره‌ی کیفیت</button>` : ''}
        <button class="btn sm ghost" data-act="bset">${icon('settings', 14)} تنظیمات تصاویر</button>
        <button class="btn sm ghost" data-act="tocat">${icon('rocket', 14)} ساخت کاتالوگ از این بانک</button></div>
      <div id="bk-jobs"></div></div></div>`;
  },
  bar() {
    document.getElementById('bk-bar').innerHTML = `<div style="padding:14px 16px;border-bottom:1px solid var(--z-100)">
      <div class="flex wrap"><div class="seg">${[['', 'همه'], ['draft', 'پیش‌نویس'], ['review', 'بازبینی'], ['approved', 'تأییدشده'], ['rejected', 'ردشده'], ['archived', 'بایگانی']].map(([k, t]) => `<button class="${B.status === k ? 'on' : ''}" data-act="st" data-v="${k}">${t}</button>`).join('')}</div>
        <input class="inp sm" style="width:220px" placeholder="جست‌وجو در عنوان، اسلاگ، فیلدها…" data-input="q" value="${attr(B.q)}">
        <select class="inp sm" style="width:auto" data-change="sort"><option value="seq">ترتیب ورود</option><option value="quality" ${B.sort === 'quality' ? 'selected' : ''}>کیفیت (کم به زیاد)</option><option value="updated" ${B.sort === 'updated' ? 'selected' : ''}>آخرین ویرایش</option><option value="title">عنوان</option></select>
        <span class="grow"></span><span class="small muted" id="bk-selc"></span><span id="bk-bulk"></span></div>
      <div class="flex wrap mt8" style="gap:6px">${FILTERS.filter(([k]) => !(['compat_all', 'compat_auto'].includes(k) && !modOn('vehicles')) && !(k === 'lowq' && !modOn('quality'))).map(([k, t]) => `<button class="chipbtn ${B.flt.has(k) ? 'on' : ''}" data-act="flt" data-v="${k}">${t}</button>`).join('')}</div></div>`;
    this.selUI();
  },
  filterParams() {
    const qs = new URLSearchParams({ bank_id: B.id });
    if (B.status) qs.set('status', B.status);
    if (B.q) qs.set('q', B.q);
    if (B.flt.size) qs.set('filter', [...B.flt].join(','));
    return qs;
  },
  async load() {
    const qs = this.filterParams();
    qs.set('page', B.page); qs.set('size', 50); qs.set('sort', B.sort);
    B.rows = await api(`/api/wb/products?${qs}`);
    const el = document.getElementById('bk-rows');
    if (!el) return;
    const minq = qmin();
    el.innerHTML = B.rows.rows.length ? `<table class="tbl"><thead><tr><th style="width:34px"><input type="checkbox" data-change="selall" ${B.allSel ? 'checked' : ''}></th><th style="width:60px"></th><th>محصول</th><th>برند</th><th>دسته</th>${modOn('vehicles') ? '<th>سازگاری</th>' : ''}${modOn('quality') ? '<th>کیفیت</th>' : ''}<th>وضعیت</th><th></th></tr></thead><tbody>
      ${B.rows.rows.map((r) => `<tr class="click ${B.sel.has(r.id) || B.allSel ? 'sel' : ''}" data-act="row" data-id="${r.id}">
        <td><input type="checkbox" data-change="sel" data-id="${r.id}" ${B.sel.has(r.id) || B.allSel ? 'checked' : ''}></td>
        <td>${r.thumb ? `<img class="thumb checker" loading="lazy" src="${attr(r.thumb)}">` : `<div class="thumb ph">${icon('image', 16)}</div>`}</td>
        <td style="max-width:360px"><b class="small">${esc(trunc(r.title, 90))}</b>${Object.keys(r.edited || {}).length ? ' <span class="edot" title="ویرایش‌شده"></span>' : ''}<div class="xs muted ltr" style="text-align:right">${esc(r.slug)}</div></td>
        <td class="small">${r.brand ? esc(r.brand.name) : `<span style="color:var(--warn)">${r.brand_raw ? esc(r.brand_raw) + ' ؟' : '—'}</span>`}</td>
        <td class="small">${r.category ? esc(r.category.name) : `<span style="color:var(--warn)">${r.category_raw ? esc(r.category_raw) + ' ؟' : '—'}</span>`}</td>
        ${modOn('vehicles') ? `<td class="small" style="max-width:230px">${compatChips(r.compat_info, 2)}${r.compat_auto ? ` <span class="xs" style="color:var(--warn)" title="پیشنهاد خودکار؛ تأیید نشده">${icon('alert', 11)}</span>` : ''}</td>` : ''}
        ${modOn('quality') ? `<td>${qualityBadge(r.quality, minq)}</td>` : ''}
        <td>${statusChip(r.status)}</td><td>${icon('chevronLeft', 14)}</td></tr>`).join('')}</tbody></table>`
      : `<div class="card-b">${emptyState('inbox', ['running', 'pending'].includes(B.bank.status) ? 'محصولات در حال ورود هستند…' : 'محصولی نیست', 'فیلتر یا جست‌وجو را تغییر دهید.')}</div>`;
    const pages = Math.max(1, Math.ceil(B.rows.total / B.rows.size));
    document.getElementById('bk-pager').innerHTML = `<button class="btn sm" data-act="pg" data-p="${B.page - 1}" ${B.page <= 1 ? 'disabled' : ''}>${icon('chevronRight', 16)} قبلی</button>
      <span class="small">صفحه ${fa(B.page)} از ${fa(pages)} · ${num(B.rows.total)} محصول</span>
      <button class="btn sm" data-act="pg" data-p="${B.page + 1}" ${B.page >= pages ? 'disabled' : ''}>بعدی ${icon('chevronLeft', 16)}</button>`;
    this.selUI();
  },
  selUI() {
    const n = B.allSel ? B.rows?.total || 0 : B.sel.size;
    const c = document.getElementById('bk-selc');
    if (c) c.innerHTML = n ? `${fa(n)} محصول انتخاب شده${!B.allSel && B.rows && B.sel.size >= B.rows.rows.length && B.rows.total > B.rows.rows.length ? ` · <a href="javascript:void 0" data-act="selfilter">انتخاب همه‌ی ${fa(B.rows.total)} نتیجه</a>` : ''}` : '';
    const b = document.getElementById('bk-bulk');
    if (b) b.innerHTML = `<button class="btn sm soft" data-act="bulk">${icon('edit', 14)} عملیات گروهی${n ? '' : ' (همه‌ی نتیجه‌ها)'}</button>${n ? `<button class="btn sm ghost" data-act="selclear">${icon('x', 14)}</button>` : ''}`;
  },
  selection() {
    if (B.allSel || !B.sel.size) {
      const f = Object.fromEntries(this.filterParams());
      return { filter: { bank_id: B.id, status: f.status || '', q: f.q || '', filter: f.filter || '' }, label: `همه‌ی ${fa(B.rows?.total || 0)} محصولِ نتیجه‌ی فیلتر` };
    }
    return { ids: [...B.sel], label: `${fa(B.sel.size)} محصول انتخاب‌شده` };
  },
  async jobs() {
    const box = document.getElementById('bk-jobs');
    if (!box || !modOn('ai')) return;
    const jobs = (await api('/api/ai/jobs').catch(() => [])).filter((j) => Number(j.options?.bank_id) === B.id && ['running', 'pending', 'paused', 'error'].includes(j.status)).slice(0, 2);
    const html = jobs.map((j) => {
      const pct = j.progress_total ? Math.round(j.progress_done / j.progress_total * 100) : 0;
      return `<div class="flex wrap mt12" style="background:var(--z-50);border-radius:12px;padding:10px 12px"><span style="color:var(--primary)">${icon(j.status === 'running' ? 'loader' : 'sparkles', 16, j.status === 'running' ? 'spin' : '')}</span>
        <div class="grow"><b class="small">هوش مصنوعی</b> <span class="xs muted">${esc(j.step || '')}</span>${j.error ? ` <span class="xs" style="color:var(--err)">${esc(j.error)}</span>` : ''}<div class="prog mt4"><i style="width:${pct}%"></i></div></div>
        ${j.status === 'running' ? `<button class="btn sm" data-act="jstop" data-id="${j.id}">${icon('pause', 14)} توقف</button>` : `<button class="btn sm soft" data-act="jresume" data-id="${j.id}">${icon('play', 14)} ادامه</button><button class="btn sm icon ghost" data-act="jdel" data-id="${j.id}">${icon('x', 14)}</button>`}</div>`;
    }).join('');
    const running = jobs.some((j) => j.status === 'running');
    if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
    if (running || box.dataset.running === '1') this.load();
    box.dataset.running = running ? '1' : '0';
  },
  act: {
    st: (el) => { B.status = el.dataset.v; B.page = 1; B.allSel = false; Bank.bar(); Bank.load(); },
    flt: (el) => { const v = el.dataset.v; B.flt.has(v) ? B.flt.delete(v) : B.flt.add(v); B.page = 1; B.allSel = false; Bank.bar(); Bank.load(); },
    pg: (el) => { B.page = Number(el.dataset.p); Bank.load(); },
    row: (el, ev) => { if (ev.target.closest('input,a,button')) return; openProduct(Number(el.dataset.id), (B.rows?.rows || []).map((r) => r.id)); },
    selclear: () => { B.sel.clear(); B.allSel = false; Bank.load(); },
    selfilter: () => { B.allSel = true; Bank.load(); },
    stop: async () => { await api(`/api/wb/banks/${B.id}/do/stop`, { body: {} }); toast('در حال توقف…'); },
    resume: async () => { await api(`/api/wb/banks/${B.id}/do/resume`, { body: {} }); Bank.refresh(); },
    rescore: async (el) => { busy(el, true, 'در حال محاسبه…'); try { const r = await api(`/api/wb/banks/${B.id}/do/rescore`, { body: {} }); okToast(`کیفیت ${fa(r.rescored)} محصول محاسبه شد.`); Bank.refresh(); } finally { busy(el, false); } },
    adds: async () => {
      const dss = (await api('/api/datasets')).filter((d) => !B.bank.dataset_ids.includes(d.id));
      const l = openLayer('modal', `<div class="card-h"><h3>افزودن داده‌ی خام به این بانک</h3></div><div class="card-b"><div class="pick-list">${dss.map((d) => `<label class="pick"><input type="checkbox" data-ds="${d.id}"> <b>${esc(d.title)}</b></label>`).join('') || '<div class="muted small">بانک خام دیگری نیست.</div>'}</div>
        <div class="hint mt8">محصولاتی که قبلاً وارد شده‌اند تکرار نمی‌شوند؛ محصولات تازه‌ی یک بانک خام هم با همین کار اضافه می‌شوند.</div></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ad-ok">افزودن</button></div>`);
      l.box.querySelector('#ad-ok').addEventListener('click', async () => {
        const ids = [...l.box.querySelectorAll('[data-ds]:checked')].map((x) => Number(x.dataset.ds));
        await api(`/api/wb/banks/${B.id}/add-datasets`, { body: { dataset_ids: ids.length ? ids : [] } });
        okToast('ورود محصولات آغاز شد.'); l.close(); Bank.refresh();
      });
    },
    bset: () => bankSettings(),
    tocat: () => go(`#/catalog?bank=${B.id}`),
    ai: () => openBankAI(Bank.selection()),
    bulk: () => openBulk(Bank.selection()),
    jstop: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/stop`, { body: {} }); Bank.jobs(); },
    jresume: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/resume`, { body: {} }); Bank.jobs(); },
    jdel: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/delete`, { body: {} }); Bank.jobs(); },
  },
  change: {
    sel: (el) => { const id = Number(el.dataset.id); B.allSel = false; el.checked ? B.sel.add(id) : B.sel.delete(id); el.closest('tr').classList.toggle('sel', el.checked); Bank.selUI(); },
    selall: (el) => { B.allSel = false; B.rows.rows.forEach((r) => (el.checked ? B.sel.add(r.id) : B.sel.delete(r.id))); Bank.load(); },
    sort: (el) => { B.sort = el.value; Bank.load(); },
  },
  input: { q: debounce((el) => { B.q = el.value.trim(); B.page = 1; B.allSel = false; Bank.load(); }, 350) },
};

function bankSettings() {
  const o = B.bank.options || {};
  const l = openLayer('modal', `<div class="card-h"><h3>تنظیمات این بانک</h3></div><div class="card-b">
      <div class="field"><label>عنوان</label><input class="inp" id="bs-title" value="${attr(B.bank.title)}"></div>
      <div class="field mt12"><label>یادداشت</label><textarea class="inp" id="bs-notes" rows="2">${esc(B.bank.notes || '')}</textarea></div>
      <div class="lbl mt16 mb8">تصاویر تازه و «پردازش دوباره»</div>
      ${modOn('rembg') ? `<label class="check"><input type="checkbox" id="bs-rembg" ${o.rembg !== false ? 'checked' : ''}> حذف پس‌زمینه</label>` : ''}
      ${modOn('align') ? `<label class="check mt8"><input type="checkbox" id="bs-align" ${o.align !== false ? 'checked' : ''}> ترازبندی</label>
        <div class="flex mt8"><span class="small">حاشیه</span><input class="inp sm" type="number" id="bs-margin" value="${typeof o.align === 'object' ? o.align.margin ?? '' : ''}" placeholder="پیش‌فرض تنظیمات" style="width:130px"><span class="small">پیکسل · بوم</span>
          <input class="inp sm" type="number" id="bs-cw" value="${typeof o.align === 'object' ? o.align.canvas_w ?? '' : ''}" placeholder="1280" style="width:90px">×<input class="inp sm" type="number" id="bs-ch" value="${typeof o.align === 'object' ? o.align.canvas_h ?? '' : ''}" placeholder="1280" style="width:90px"></div>` : ''}
      <label class="check mt16"><input type="checkbox" id="bs-reproc"> همه‌ی تصاویر همین حالا با این تنظیمات دوباره ساخته شوند</label>
    </div><div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="bs-ok">${icon('save', 16)} ذخیره</button></div>`);
  const b = l.box;
  b.querySelector('#bs-ok').addEventListener('click', async (ev) => {
    const al = b.querySelector('#bs-align');
    let align = al ? al.checked : false;
    if (align && (b.querySelector('#bs-margin').value || b.querySelector('#bs-cw').value)) {
      align = { margin: Number(b.querySelector('#bs-margin').value || 60) };
      if (b.querySelector('#bs-cw').value) { align.canvas_w = Number(b.querySelector('#bs-cw').value); align.canvas_h = Number(b.querySelector('#bs-ch').value || b.querySelector('#bs-cw').value); }
    }
    try {
      busy(ev.currentTarget, true, 'در حال ذخیره…');
      B.bank = { ...B.bank, ...(await api(`/api/wb/banks/${B.id}`, { method: 'PUT', body: { title: b.querySelector('#bs-title').value, notes: b.querySelector('#bs-notes').value, options: { rembg: b.querySelector('#bs-rembg')?.checked ?? false, align } } })) };
      if (b.querySelector('#bs-reproc').checked) { const r = await api('/api/wb/products/bulk-images', { body: { bank_id: B.id, filter: { bank_id: B.id } } }); okToast(`تصاویر ${fa(r.processed)} محصول دوباره ساخته شد.`); }
      l.close(); Bank.refresh();
    } catch (e) { errToast(e); }
  });
}

// ----------------------------------------------------------------------------- عملیات گروهی
function openBulk(sel) {
  const cols = editCols();
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('edit', 18)} عملیات گروهی</h3><span class="sub">${sel.label}</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:72vh;overflow:auto">
      <div class="seg mb16" id="bu-op">${[['field', 'فیلدها'], ['ref', 'برند و دسته'], ...(modOn('vehicles') ? [['compat', 'سازگاری با خودرو']] : []), ['status', 'وضعیت'], ['images', 'تصاویر']].map(([k, t], i) => `<button class="${i ? '' : 'on'}" data-op="${k}">${t}</button>`).join('')}</div>
      <div id="bu-ed"></div><div class="hint mt12">هر تغییر برای هر محصول یک نسخه‌ی تازه می‌سازد و قابل بازگرداندن است.</div>
    </div><div class="drawer-f" style="border-radius:0 0 20px 20px"><span class="small muted" id="bu-msg"></span><span class="grow"></span><button class="btn" data-close>انصراف</button><button class="btn primary" id="bu-ok">${icon('check', 16)} اعمال</button></div>`, { wide: true });
  const b = l.box;
  let op = 'field';
  const st = { brand: undefined, category: undefined, compat: undefined };
  const draw = () => {
    b.querySelectorAll('#bu-op button').forEach((x) => x.classList.toggle('on', x.dataset.op === op));
    const ed = b.querySelector('#bu-ed');
    if (op === 'field') {
      ed.innerHTML = `<div class="form-grid"><div class="field"><label>ستون</label><select class="inp" id="bu-col">${cols.map((c) => `<option value="${attr(c.key)}">${esc(c.label || c.key)}</option>`).join('')}</select></div>
        <div class="field"><label>عملیات</label><select class="inp" id="bu-fop"><option value="set">تعیین مقدار</option><option value="replace">جست‌وجو و جایگزینی</option><option value="prepend">افزودن به ابتدا</option><option value="append">افزودن به انتها</option><option value="default">اعمال مقدار پیش‌فرض اسکیما</option></select></div></div><div id="bu-fed" class="mt12"></div>`;
      const fdraw = () => {
        const col = cols.find((c) => c.key === b.querySelector('#bu-col').value);
        const fop = b.querySelector('#bu-fop').value;
        b.querySelector('#bu-fed').innerHTML = fop === 'set' ? `<div class="field" data-col="${attr(col.key)}"><label class="lbl">${esc(col.label || col.key)}</label>${colInput(col, null, {})}</div>`
          : fop === 'replace' ? `<div class="form-grid"><div class="field"><label>جست‌وجو</label><input class="inp" id="bu-find" data-noai></div><div class="field"><label>جایگزین</label><input class="inp" id="bu-rep" data-noai></div></div><label class="check small mt8"><input type="checkbox" id="bu-rx"> عبارت باقاعده (Regex)</label>`
            : fop === 'default' ? '<div class="small muted">مقدار پیش‌فرض فعلی همین ستون در اسکیما با نحوه‌ی اعمال تعریف‌شده در اسکیما اعمال می‌شود.</div>'
              : `<div class="field"><label>متن</label><textarea class="inp" id="bu-add" rows="3" data-noai></textarea></div>`;
      };
      b.querySelector('#bu-col').addEventListener('change', fdraw);
      b.querySelector('#bu-fop').addEventListener('change', fdraw);
      fdraw();
    } else if (op === 'ref') {
      ed.innerHTML = `<div class="flex wrap"><button class="btn" id="bu-brand">${icon('tag', 14)} انتخاب برند</button><span id="bu-bl" class="small"></span></div>
        <div class="flex wrap mt12"><button class="btn" id="bu-cat">${icon('tree', 14)} انتخاب دسته</button><span id="bu-cl" class="small"></span></div>`;
      b.querySelector('#bu-brand').onclick = async () => { const r = await openRefPicker('brand'); if (r !== undefined) { st.brand = r; b.querySelector('#bu-bl').textContent = r ? `شناسه‌ی ${fa(r)} انتخاب شد` : 'بدون برند'; } };
      b.querySelector('#bu-cat').onclick = async () => { const r = await openRefPicker('category'); if (r !== undefined) { st.category = r; b.querySelector('#bu-cl').textContent = r ? `شناسه‌ی ${fa(r)} انتخاب شد` : 'بدون دسته'; } };
    } else if (op === 'compat') {
      ed.innerHTML = `<div class="seg" id="bu-cm"><button class="on" data-cm="set">جایگزینی</button><button data-cm="add">افزودن به فعلی</button><button data-cm="remove">حذف از فعلی</button></div>
        <div class="flex wrap mt12"><button class="btn" id="bu-cp">${icon('car', 14)} انتخاب خودروها</button><span id="bu-cpl" class="small"></span></div>`;
      b.querySelector('#bu-cm').onclick = (e) => { const x = e.target.closest('[data-cm]'); if (x) b.querySelectorAll('#bu-cm button').forEach((y) => y.classList.toggle('on', y === x)); };
      b.querySelector('#bu-cp').onclick = async () => { const v = await compatPicker(st.compat); if (v !== undefined) { st.compat = v; const d = await api('/api/vehicles/describe', { body: { value: v } }); b.querySelector('#bu-cpl').textContent = d.label; } };
    } else if (op === 'status') {
      ed.innerHTML = `<div class="seg" id="bu-st">${[['review', 'ارسال برای بازبینی'], ['approved', 'تأیید'], ['rejected', 'رد'], ['draft', 'بازگشت به پیش‌نویس'], ['archived', 'بایگانی']].map(([k, t], i) => `<button class="${i ? '' : 'on'}" data-s="${k}">${t}</button>`).join('')}</div>
        <div class="field mt12"><label>یادداشت (اختیاری؛ مثلاً دلیل رد)</label><input class="inp" id="bu-note"></div><div class="hint mt8">محصولاتی که خطای کیفیت دارند تأیید نمی‌شوند و در گزارش پایان می‌آیند.</div>`;
      b.querySelector('#bu-st').onclick = (e) => { const x = e.target.closest('[data-s]'); if (x) b.querySelectorAll('#bu-st button').forEach((y) => y.classList.toggle('on', y === x)); };
    } else {
      ed.innerHTML = `<div class="small">همه‌ی تصاویر محصولات انتخاب‌شده با تنظیمات فعلی بانک (حذف پس‌زمینه و ترازبندی) و ویرایش‌های ذخیره‌شده‌ی هر تصویر دوباره ساخته می‌شوند.</div>
        ${modOn('rembg') ? '<label class="check mt12"><input type="checkbox" id="bu-redo"> حذف پس‌زمینه هم از نو اجرا شود</label>' : ''}`;
    }
  };
  b.querySelector('#bu-op').addEventListener('click', (e) => { const x = e.target.closest('[data-op]'); if (x) { op = x.dataset.op; draw(); } });
  draw();
  b.querySelector('#bu-ok').addEventListener('click', async (ev) => {
    const body = { bank_id: B.id, ...(sel.ids ? { ids: sel.ids } : { filter: sel.filter }) };
    try {
      if (op === 'field') {
        const col = cols.find((c) => c.key === b.querySelector('#bu-col').value);
        const fop = b.querySelector('#bu-fop').value;
        if (fop === 'set') body.set = { [col.key]: readCol(b.querySelector('#bu-fed [data-col]'), col) };
        else if (fop === 'replace') body.find_replace = { key: col.key, find: b.querySelector('#bu-find').value, replace: b.querySelector('#bu-rep').value, regex: b.querySelector('#bu-rx').checked };
        else if (fop === 'default') body.apply_default = [col.key];
        else body[fop] = { [col.key]: b.querySelector('#bu-add').value };
      } else if (op === 'ref') {
        if (st.brand === undefined && st.category === undefined) { toast('برند یا دسته انتخاب نشده است.', 'err'); return; }
        if (st.brand !== undefined) body.brand = st.brand;
        if (st.category !== undefined) body.category = st.category;
      } else if (op === 'compat') {
        if (st.compat === undefined) { toast('خودروها انتخاب نشده‌اند.', 'err'); return; }
        body.compat = { mode: b.querySelector('#bu-cm .on').dataset.cm, value: st.compat };
      } else if (op === 'status') {
        body.status = b.querySelector('#bu-st .on').dataset.s;
        if (b.querySelector('#bu-note').value) body.note = b.querySelector('#bu-note').value;
      } else {
        busy(ev.currentTarget, true, 'در حال پردازش…');
        const r = await api('/api/wb/products/bulk-images', { body: { ...body, redo_rembg: b.querySelector('#bu-redo')?.checked } });
        okToast(`تصاویر ${fa(r.processed)} محصول دوباره ساخته شد.`); l.close(); Bank.refresh(); return;
      }
      busy(ev.currentTarget, true, 'در حال اعمال…');
      const r = await api('/api/wb/products/bulk', { body });
      if (r.errors?.length) {
        b.querySelector('#bu-msg').innerHTML = '';
        openLayer('modal', `<div class="card-h"><h3>${fa(r.updated)} از ${fa(r.total)} محصول تغییر کرد</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
          <div class="card-b" style="max-height:60vh;overflow:auto"><div class="small mb8">این موارد اعمال نشدند:</div>${r.errors.map((x) => `<div class="small" style="padding:6px 0;border-bottom:1px solid var(--z-100)"><b>#${fa(x.id)}</b> ${esc(x.error)}</div>`).join('')}</div>`);
      } else okToast(`${fa(r.updated)} از ${fa(r.total)} محصول تغییر کرد.`);
      l.close(); B.sel.clear(); B.allSel = false; Bank.refresh();
    } catch (e) { errToast(e); busy(ev.currentTarget, false); }
  });
}

function openBankAI(sel) {
  const cols = roleCols().filter((c) => !['brand', 'category', 'compat'].includes(c.role) && !(c.kind === 'auto' && c.generator && c.generator !== 'slug'));
  const isImg = (c) => ['image', 'images'].includes(c.input);
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} هوش مصنوعی روی بانک تمیز</h3><span class="sub">${sel.label}</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:72vh;overflow:auto"><div class="tbl-wrap" style="border:1px solid var(--z-200);border-radius:14px;max-height:400px"><table class="tbl"><thead><tr><th></th><th>ستون</th><th>حالت</th><th>دستور</th></tr></thead><tbody>
      ${cols.map((c) => `<tr data-key="${attr(c.key)}"><td><input type="checkbox" data-pick></td><td><b class="small">${esc(c.label || c.key)}</b><div class="xs muted ltr" style="text-align:right">${esc(c.key)}</div></td>
        <td><select class="inp sm" data-mode>${(isImg(c) ? [['fill_missing', 'اگر تصویری نیست'], ['add', 'افزودن تصویر']] : [['fill_missing', 'فقط اگر خالی است'], ['rewrite', 'بازنویسی یکتا'], ['overwrite', 'تولید از نو']]).map(([k, t]) => `<option value="${k}">${t}</option>`).join('')}</select></td>
        <td><input class="inp sm" data-instr placeholder="${attr(c.ai_instruction || 'اختیاری')}" style="min-width:200px"></td></tr>`).join('')}</tbody></table></div>
      <div class="hint mt8">نتیجه‌ی هر محصول یک نسخه‌ی تازه می‌سازد (برگشت‌پذیر). برند، دسته و سازگاری با دکمه‌های اختصاصی خودشان پیشنهاد می‌شوند.</div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ba-go">${icon('sparkles', 16)} شروع</button></div>`, { wide: true });
  l.box.querySelector('#ba-go').addEventListener('click', async () => {
    const columns = [...l.box.querySelectorAll('tbody tr')].filter((tr) => tr.querySelector('[data-pick]').checked)
      .map((tr) => ({ key: tr.dataset.key, mode: tr.querySelector('[data-mode]').value, instruction: tr.querySelector('[data-instr]').value }));
    if (!columns.length) { toast('دست‌کم یک ستون انتخاب کنید.', 'err'); return; }
    try {
      await api(`/api/wb/banks/${B.id}/ai`, { body: { columns, ...(sel.ids ? { ids: sel.ids } : { filter: sel.filter }) } });
      okToast('تولید با هوش مصنوعی آغاز شد.'); l.close(); Bank.jobs();
    } catch (e) { noProviderHint(e); }
  });
}

// ======================================================================
// کشوی محصول تمیز
// ======================================================================
export async function openProduct(pid, ids = [], onChange) {
  let p = await api(`/api/wb/products/${pid}`);
  let bank = B.bank && B.bank.id === p.bank_id ? B.bank : await api(`/api/wb/banks/${p.bank_id}`);
  const cols = bank.columns;
  const fields = cols.filter((c) => !c.role);
  const idx = ids.indexOf(pid);
  let tab = 'info';
  const refresh = () => { (onChange || (() => (S.page === Bank ? Bank.load() : S.page?.refresh?.())))(); };
  const layer = openLayer('drawer', `<div class="drawer-h"><h3 class="ellipsis" id="pd-title">${esc(p.title)}</h3><span id="pd-st"></span>
      <button class="btn sm icon ghost" data-nav="${ids[idx - 1] || ''}" ${idx <= 0 ? 'disabled' : ''} title="محصول قبلی">${icon('chevronRight', 16)}</button>
      <button class="btn sm icon ghost" data-nav="${ids[idx + 1] || ''}" ${idx < 0 || idx >= ids.length - 1 ? 'disabled' : ''} title="محصول بعدی">${icon('chevronLeft', 16)}</button>
      <button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="tabs" id="pd-tabs">${[['info', 'edit', 'اطلاعات'], ['images', 'image', 'تصاویر'], ['revs', 'branch', 'نسخه‌ها'], ['raw', 'database', 'داده‌ی خام']].map(([k, ic, t]) => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${icon(ic, 14)} ${t}</button>`).join('')}</div>
    <div class="drawer-b" id="pd-body"></div>
    <div class="drawer-f" id="pd-foot"></div>`);
  const box = layer.box;
  const orig = {};
  const reload = async () => { p = await api(`/api/wb/products/${pid}`); draw(); refresh(); };
  const put = async (body, msg = 'ذخیره شد.') => { await api(`/api/wb/products/${pid}`, { method: 'PUT', body }); okToast(msg); await reload(); };

  const draw = () => {
    box.querySelector('#pd-title').textContent = p.title;
    box.querySelector('#pd-st').innerHTML = `${statusChip(p.status)} ${modOn('quality') ? qualityBadge(p.quality, qmin()) : ''} <span class="tag" title="شماره‌ی نسخه‌ی فعلی">${icon('branch', 11)} نسخه‌ی ${fa(p.rev)}</span>`;
    box.querySelectorAll('#pd-tabs button').forEach((x) => x.classList.toggle('on', x.dataset.tab === tab));
    const body = box.querySelector('#pd-body');
    if (tab === 'info') body.innerHTML = infoHtml();
    if (tab === 'images') body.innerHTML = imagesHtml();
    if (tab === 'revs') { body.innerHTML = '<div id="pd-revs"></div>'; revisionsPanel(body.querySelector('#pd-revs'), 'product', pid, reload); }
    if (tab === 'raw') { body.innerHTML = '<div class="muted small">در حال بارگذاری…</div>'; rawTab(body); }
    if (tab === 'info') fields.forEach((c) => { const el = body.querySelector(`[data-col="${CSS.escape(c.key)}"]`); if (el) orig[c.key] = readCol(el, c); });
    const merged = p.status === 'merged';
    box.querySelector('#pd-foot').innerHTML = merged ? `<div class="small muted">این محصول در محصول ${fa(p.merged_into)} ادغام شده است.</div>` : `
      ${p.status !== 'review' && p.status !== 'approved' ? `<button class="btn soft" data-st="review">${icon('send', 15)} ارسال برای بازبینی</button>` : ''}
      ${p.status !== 'approved' ? `<button class="btn soft" data-st="approved" style="color:var(--ok)">${icon('check', 15)} تأیید</button>` : `<button class="btn ghost" data-st="draft">${icon('undo', 15)} لغو تأیید</button>`}
      ${p.status === 'review' ? `<button class="btn ghost" data-st="rejected" style="color:var(--err)">${icon('x', 15)} رد</button>` : ''}
      <button class="btn ghost" data-st="archived" title="بایگانی (حذف از فهرست‌ها؛ برگشت‌پذیر)">${icon('archive', 15)}</button>
      <span class="grow"></span><button class="btn" data-close>بستن</button>${tab === 'info' ? `<button class="btn primary" data-save>${icon('save', 16)} ذخیره</button>` : ''}`;
  };

  const infoHtml = () => {
    const qd = p.quality_detail || {};
    const sug = p.meta?.compat_suggest;
    return `
      ${modOn('quality') && (qd.errors?.length || qd.warnings?.length) ? `<div class="qbox">${(qd.errors || []).map((e) => `<div class="q-err">${icon('alert', 13)} ${esc(e.label)}</div>`).join('')}${(qd.warnings || []).map((e) => `<div class="q-warn">${icon('info', 13)} ${esc(e.label)}</div>`).join('')}</div>` : ''}
      <div class="sec-title">${icon('star', 16)} فیلدهای اصلی <span class="line"></span></div>
      <div class="field"><label class="lbl">عنوان ${p.edited.title ? `<span class="tag p">ویرایش‌شده · ${ACTOR[p.edited.title] || ''}</span>` : ''}</label><input class="inp" data-core="title" value="${attr(p.title)}"></div>
      <div class="field mt12"><label class="lbl">اسلاگ انگلیسی</label><input class="inp ltr mono" data-core="slug" value="${attr(p.slug)}"></div>
      <div class="core-grid mt12">
        <div class="core-box"><div class="lbl">${icon('tag', 13)} برند</div><div class="mt4">${p.brand ? `<b>${esc(p.brand.name)}</b> <span class="xs muted ltr">${esc(p.brand.slug)}</span>` : `<span style="color:var(--warn)">انتخاب نشده</span>${p.brand_raw ? `<div class="xs muted">نام در داده‌ی خام: «${esc(p.brand_raw)}»</div>` : ''}`}</div>
          <button class="btn xs soft mt8" data-pick="brand">${icon('edit', 12)} ${p.brand ? 'تغییر' : 'انتخاب از فهرست'}</button></div>
        <div class="core-box"><div class="lbl">${icon('tree', 13)} دسته‌بندی</div><div class="mt4">${p.category ? `<b>${esc(p.category.name)}</b> <span class="xs muted ltr">${esc(p.category.slug)}</span>` : `<span style="color:var(--warn)">انتخاب نشده</span>${p.category_raw ? `<div class="xs muted">در داده‌ی خام: «${esc(p.category_raw)}»</div>` : ''}`}</div>
          <button class="btn xs soft mt8" data-pick="category">${icon('edit', 12)} ${p.category ? 'تغییر' : 'انتخاب از فهرست'}</button></div>
      </div>
      <div class="core-box mt12"><div class="flex"><div class="lbl grow">${icon('car', 13)} سازگاری با خودرو <span class="xs muted">(فیلد اجباری؛ اگر مشخص نشود «همه‌ی خودروها»)</span></div>
          ${modOn('vehicles') ? `<button class="btn xs soft" data-compat>${icon('edit', 12)} انتخاب خودروها</button>${modOn('ai') ? `<button class="btn xs ghost" data-compat-ai title="پیشنهاد با هوش مصنوعی از روی متن محصول">${icon('sparkles', 12)} پیشنهاد AI</button>` : ''}` : ''}</div>
        <div class="flex wrap mt8" style="gap:6px">${compatChips(p.compat_info, 30)}</div>
        ${p.compat_auto ? `<div class="alert warn mt8" style="padding:8px 10px">${icon('alert')}<div class="grow small">این سازگاری خودکار از روی متن پیشنهاد شده و هنوز تأیید نشده است.</div><button class="btn xs primary" data-compat-ok>تأیید</button></div>` : ''}
        ${!p.compat_auto && sug?.labels?.length && p.compat_info.all ? `<div class="xs muted mt8">${icon('sparkles', 11)} پیشنهاد از متن: ${sug.labels.map(esc).join('، ')} <a href="javascript:void 0" data-compat>بررسی</a></div>` : ''}</div>
      <div class="sec-title">${icon('columns', 16)} فیلدهای اسکیمای «${esc(bank.schema?.name || '')}» <span class="line"></span>
        ${modOn('ai') ? `<button class="btn xs soft" data-ai-empty>${icon('sparkles', 12)} همه‌ی فیلدهای خالی با AI</button>` : ''}</div>
      ${fields.map((c) => `<div class="field mt16" data-col="${attr(c.key)}"><div class="flex"><label class="lbl ltr" style="text-align:right">${esc(c.label || c.key)} <span class="xs muted">(${esc(c.key)})</span>${c.required ? ' <span style="color:var(--err)">*</span>' : ''}</label>
          ${p.edited[c.key] ? `<span class="tag p">ویرایش‌شده · ${esc(ACTOR[p.edited[c.key]] || p.edited[c.key])}</span>` : ''}${c.default !== undefined && c.default !== null && c.default !== '' ? `<span class="tag" title="مقدار پیش‌فرض اسکیما">${icon('edit', 10)} پیش‌فرض</span>` : ''}
          <span class="grow"></span>${modOn('ai') && c.kind !== 'constant' ? `<button class="btn xs soft" data-ai="${attr(c.key)}" title="تولید یا بازنویسی با هوش مصنوعی">${icon('sparkles', 12)} AI</button>` : ''}</div>
        ${colInput(c, p.v[c.key], {})}</div>`).join('')}
      <div class="field mt16"><label class="lbl">یادداشت</label><input class="inp" data-core="note" value="${attr(p.note || '')}"></div>
      <div class="xs muted mt16">شناسه‌ی یکتا: <span class="ltr">${esc(p.uid)}</span> · ساخته‌شده ${jdate(p.created_at)} · آخرین تغییر ${jdate(p.updated_at)}</div>`;
  };

  const imagesHtml = () => `
    <div class="sec-title">${icon('image', 16)} تصاویر محصول <span class="line"></span><span class="xs muted">تصویر اول = شاخص · ${fa(p.images.length)} تصویر</span></div>
    <div class="cimgs">${p.images.map((im, i) => `<div class="cimg ${i === 0 ? 'feat' : ''}"><div class="cimg-i checker"><a href="${attr(im.final_url)}" target="_blank"><img src="${attr(im.final_url)}"></a></div>
      <div class="xs muted ellipsis">${i === 0 ? '★ شاخص' : `گالری ${fa(i)}`} · ${fa(im.w || 0)}×${fa(im.h || 0)}${im.edited ? ` · <span style="color:var(--primary)">ویرایش‌شده</span>` : ''}${im.origin === 'ai' ? ' · AI' : ''}</div>
      <div class="flex" style="gap:2px;flex-wrap:wrap">
        ${modOn('image_editor') ? `<button class="btn xs soft" data-img="edit" data-i="${im.id}" title="ویرایش (برش، پاک‌کن، رنگ)">${icon('palette', 12)}</button>` : ''}
        ${i > 0 ? `<button class="btn xs ghost" data-img="make_feature" data-i="${im.id}" title="شاخص شود">${icon('star', 12)}</button><button class="btn xs ghost" data-img="move" data-i="${im.id}" data-to="${i - 1}" title="جلوتر">${icon('chevronRight', 12)}</button>` : ''}
        ${i < p.images.length - 1 ? `<button class="btn xs ghost" data-img="move" data-i="${im.id}" data-to="${i + 1}" title="عقب‌تر">${icon('chevronLeft', 12)}</button>` : ''}
        ${modOn('rembg') ? `<button class="btn xs ghost ${im.use_rembg ? 'on' : ''}" data-img="rembg" data-i="${im.id}" data-on="${im.use_rembg ? 0 : 1}" title="${im.use_rembg ? 'حذف پس‌زمینه روشن است (برای خاموش کردن بزنید)' : 'حذف پس‌زمینه خاموش است'}">${icon('eraser', 12)}</button>` : ''}
        ${im.edited ? `<button class="btn xs ghost" data-img="reset_edit" data-i="${im.id}" title="برگرداندن ویرایش">${icon('undo', 12)}</button>` : ''}
        <button class="btn xs ghost danger" data-img="delete" data-i="${im.id}" title="حذف از محصول (قابل بازگردانی از نسخه‌ها)">${icon('trash', 12)}</button></div></div>`).join('') || '<div class="muted small">تصویری ندارد.</div>'}</div>
    <div class="flex wrap mt16" style="gap:6px">
      <label class="btn sm soft">${icon('upload', 14)} بارگذاری<input type="file" accept="image/*" multiple data-upload hidden></label>
      <button class="btn sm" data-img="url">${icon('link', 14)} از لینک</button>
      ${modOn('ai') ? `<button class="btn sm soft" data-img="generate">${icon('sparkles', 14)} ساخت با AI</button>` : ''}
      <button class="btn sm ghost" data-img="reprocess">${icon('refresh', 14)} ساخت دوباره‌ی همه</button></div>
    <div class="hint mt12">ویرایش تصاویر غیرمخرب است: فایل اصلی دانلودشده دست نمی‌خورد و هر ویرایش از نو روی آن اجرا می‌شود (حذف پس‌زمینه ← ویرایش ← ترازبندی). نام نهایی فایل‌ها هنگام انتشار کاتالوگ طبق الگوی خروجی ساخته می‌شود.</div>`;

  const rawTab = async (body) => {
    const src = await api(`/api/wb/products/${pid}/sources`);
    body.innerHTML = `<div class="alert info">${icon('info')}<div>داده‌ی خام نسخه‌ی صفر محصول است و هیچ‌وقت تغییر نمی‌کند. اینجا برای مقایسه با نسخه‌ی تمیز نمایش داده می‌شود.</div></div>
      ${src.map((s) => `<div class="card mt12"><div class="card-b"><div class="flex wrap"><b class="small">${esc(s.source || 'منبع')}</b>${s.url ? `<a class="xs ltr ellipsis" href="${attr(s.url)}" target="_blank" style="max-width:420px">${esc(s.url)}</a>` : ''}
        ${s.dataset_id ? `<a class="tag" href="#/datasets/${s.dataset_id}">${icon('database', 11)} بانک خام</a>` : ''}</div>
        ${s.data ? `<pre class="pathbox mt8" style="max-height:420px;overflow:auto;white-space:pre-wrap">${esc(JSON.stringify(s.data, null, 2))}</pre>` : '<div class="muted small mt8">داده‌ی خام در دسترس نیست (مثلاً از خروجی نسخه‌ی ۱ منتقل شده).</div>'}</div></div>`).join('')}`;
  };

  draw();

  box.querySelectorAll('[data-nav]').forEach((x) => x.addEventListener('click', () => { const n = Number(x.dataset.nav); if (n) { layer.close(); openProduct(n, ids, onChange); } }));
  box.querySelector('#pd-tabs').addEventListener('click', (e) => { const t = e.target.closest('[data-tab]'); if (t) { tab = t.dataset.tab; draw(); } });
  box.addEventListener('click', async (ev) => {
    const t = ev.target;
    try {
      const pk = t.closest('[data-pick]');
      if (pk) {
        const kind = pk.dataset.pick;
        const r = await openRefPicker(kind, p[`${kind}_id`], p[`${kind}_raw`] || '');
        if (r !== undefined) await put({ [kind]: r });
        return;
      }
      if (t.closest('[data-compat]')) {
        const v = await compatPicker(p.compat_auto || p.compat_info.all ? (p.meta?.compat_suggest?.value && p.compat_info.all ? { all: true } : p.compat) : p.compat);
        if (v !== undefined) await put({ compat: v }, 'سازگاری ذخیره شد.');
        return;
      }
      if (t.closest('[data-compat-ok]')) { await put({ compat: p.compat }, 'سازگاری تأیید شد.'); return; }
      const cai = t.closest('[data-compat-ai]');
      if (cai) {
        busy(cai, true, '…');
        try {
          const s = await api(`/api/wb/products/${pid}/compat-suggest`, { body: { ai: true } });
          const m = await import('./mod_vehicles.js');
          const v = await m.openCompatPicker(p.compat, { suggestion: { value: s.value, labels: s.value.all ? ['همه‌ی خودروها'] : s.matches.map((x) => x.display || x.label) } });
          if (v !== undefined) await put({ compat: v }, 'سازگاری ذخیره شد.');
        } catch (e) { noProviderHint(e); } finally { busy(cai, false); }
        return;
      }
      const ai = t.closest('[data-ai]');
      if (ai) {
        const key = ai.dataset.ai;
        const col = fields.find((c) => c.key === key);
        const ins = await promptDlg(`تولید «${col.label || key}» با هوش مصنوعی`, 'دستور (اختیاری)', '', 'خالی = دستور پیش‌فرض ستون. نتیجه بلافاصله ذخیره می‌شود و نسخه‌ی تازه ثبت می‌شود.');
        if (ins === null) return;
        busy(ai, true, '…');
        try {
          const r = await api(`/api/wb/products/${pid}/ai`, { body: { columns: [{ key, mode: 'overwrite', instruction: ins }] } });
          if (!r.ok) throw new Error(r.error);
          p = r.product; okToast('تولید و ذخیره شد.'); draw(); refresh();
        } catch (e) { noProviderHint(e); } finally { busy(ai, false); }
        return;
      }
      const ae = t.closest('[data-ai-empty]');
      if (ae) {
        busy(ae, true, '…');
        try {
          const r = await api(`/api/wb/products/${pid}/ai`, { body: { columns: fields.filter((c) => c.kind !== 'constant').map((c) => ({ key: c.key, mode: 'fill_missing' })) } });
          if (!r.ok) throw new Error(r.error);
          p = r.product; okToast(`${fa(Object.keys(r.generated).length)} فیلد تکمیل شد.`); draw(); refresh();
        } catch (e) { noProviderHint(e); } finally { busy(ae, false); }
        return;
      }
      const im = t.closest('[data-img]');
      if (im) { await imageAct(im); return; }
      const st = t.closest('[data-st]');
      if (st) {
        const s = st.dataset.st;
        let note;
        if (s === 'rejected') { note = await promptDlg('رد محصول', 'دلیل رد (برای اپراتور)', ''); if (note === null) return; }
        if (s === 'archived' && !(await confirmDlg('بایگانی', 'محصول از فهرست‌ها و کاتالوگ‌ها کنار گذاشته شود؟ (برگشت‌پذیر)', 'بایگانی'))) return;
        await put({ status: s, ...(note ? { note } : {}) }, { review: 'برای بازبینی فرستاده شد.', approved: 'تأیید شد.', rejected: 'رد شد.', draft: 'به پیش‌نویس برگشت.', archived: 'بایگانی شد.' }[s]);
        return;
      }
      if (t.closest('[data-save]')) {
        const body = {};
        const values = {};
        for (const c of fields) {
          const el = box.querySelector(`[data-col="${CSS.escape(c.key)}"]`);
          const v = readCol(el, c);
          if (JSON.stringify(v ?? '') !== JSON.stringify(orig[c.key] ?? '')) values[c.key] = v;
        }
        if (Object.keys(values).length) body.values = values;
        const tt = box.querySelector('[data-core="title"]').value.trim();
        const sl = box.querySelector('[data-core="slug"]').value.trim();
        const nt = box.querySelector('[data-core="note"]').value;
        if (tt !== p.title) body.title = tt;
        if (sl !== p.slug) body.slug = sl;
        if (nt !== (p.note || '')) body.note = nt;
        if (!Object.keys(body).length) { toast('تغییری نبود.'); return; }
        await put(body, `ذخیره شد (نسخه‌ی تازه).`);
      }
    } catch (e) { errToast(e); }
  });
  box.addEventListener('change', async (ev) => {
    const f = ev.target.closest('[data-upload]');
    if (!f || !f.files.length) return;
    const lbl = f.closest('label');
    busy(lbl, true, 'بارگذاری…');
    try {
      for (const file of f.files) {
        p = await api(`/api/wb/products/${pid}/images/upload`, { body: { data_url: await fileToDataUrl(file), name: file.name } });
      }
      okToast('تصویر افزوده شد.'); draw(); refresh();
    } catch (e) { errToast(e); } finally { busy(lbl, false); }
  });

  async function imageAct(el) {
    const action = el.dataset.img;
    const iid = Number(el.dataset.i || 0);
    const body = { image_id: iid };
    if (action === 'delete' && !(await confirmDlg('حذف تصویر', 'تصویر از این محصول حذف شود؟ از «نسخه‌ها» قابل بازگرداندن است.', 'حذف', true))) return;
    if (action === 'move') body.to = Number(el.dataset.to);
    if (action === 'rembg') body.on = el.dataset.on === '1';
    if (action === 'reprocess') { body.all = true; body.image_id = p.images[0]?.id; }
    if (action === 'url') { const u = await promptDlg('افزودن تصویر از لینک', 'نشانی تصویر', ''); if (!u) return; body.url = u; }
    if (action === 'generate') { const pr = await promptDlg('ساخت تصویر با هوش مصنوعی', 'توضیح تصویر (اختیاری)', '', 'خالی = عکس محصول روی پس‌زمینه‌ی سفید'); if (pr === null) return; if (pr) body.prompt = pr; }
    if (action === 'edit') {
      const im = p.images.find((x) => x.id === iid);
      const m = await import('./mod_image_editor.js');
      const r = await m.openImageEditor({ url: im.base_url, recipe: im.recipe, title: `ویرایش تصویر ${p.images.indexOf(im) === 0 ? 'شاخص' : 'گالری'}` });
      if (!r) return;
      body.recipe = r.recipe;
    }
    busy(el, true, '…');
    try {
      p = await api(`/api/wb/products/${pid}/images/${action}`, { body });
      p.rev = (await api(`/api/wb/products/${pid}`)).rev;
      draw(); refresh();
    } catch (e) { noProviderHint(e); } finally { busy(el, false); }
  }
}

// ======================================================================
// صف بازبینی
// ======================================================================
const RV = { page: 1, rows: null };
export const Review = {
  title: 'صف بازبینی',
  crumb: 'ویرایشگر داده‌ها · محصولاتی که برای تأیید فرستاده شده‌اند (از همه‌ی بانک‌ها)',
  async render() { return '<div class="card"><div class="tbl-wrap" id="rv-rows"></div><div class="pager" id="rv-pager"></div></div>'; },
  async mount() { await this.load(); },
  refresh() { return this.load(); },
  async load() {
    RV.rows = await api(`/api/wb/products?status=review&page=${RV.page}&size=50&sort=updated`);
    const el = document.getElementById('rv-rows');
    if (!el) return;
    el.innerHTML = RV.rows.rows.length ? `<table class="tbl"><thead><tr><th style="width:60px"></th><th>محصول</th><th>برند / دسته</th>${modOn('vehicles') ? '<th>سازگاری</th>' : ''}${modOn('quality') ? '<th>کیفیت</th>' : ''}<th>آخرین تغییر</th><th></th></tr></thead><tbody>
      ${RV.rows.rows.map((r) => `<tr class="click" data-act="open" data-id="${r.id}"><td>${r.thumb ? `<img class="thumb checker" src="${attr(r.thumb)}">` : `<div class="thumb ph">${icon('image', 16)}</div>`}</td>
        <td><b class="small">${esc(trunc(r.title, 80))}</b><div class="xs muted ltr" style="text-align:right">${esc(r.slug)}</div></td>
        <td class="small">${esc(r.brand?.name || '—')} / ${esc(r.category?.name || '—')}</td>${modOn('vehicles') ? `<td class="small">${compatChips(r.compat_info, 2)}</td>` : ''}
        ${modOn('quality') ? `<td>${qualityBadge(r.quality, qmin())}</td>` : ''}<td class="xs muted">${jdate(r.updated_at)}</td>
        <td class="nowrap"><button class="btn xs soft" data-act="ok" data-id="${r.id}" style="color:var(--ok)">${icon('check', 12)} تأیید</button> <button class="btn xs ghost" data-act="no" data-id="${r.id}" style="color:var(--err)">${icon('x', 12)} رد</button></td></tr>`).join('')}</tbody></table>`
      : `<div class="card-b">${emptyState('checkCircle', 'صف بازبینی خالی است', 'محصولاتی که در ویرایشگر «ارسال برای بازبینی» شوند این‌جا می‌آیند.')}</div>`;
    const pages = Math.max(1, Math.ceil(RV.rows.total / 50));
    document.getElementById('rv-pager').innerHTML = `<button class="btn sm" data-act="pg" data-p="${RV.page - 1}" ${RV.page <= 1 ? 'disabled' : ''}>قبلی</button><span class="small">${num(RV.rows.total)} محصول</span><button class="btn sm" data-act="pg" data-p="${RV.page + 1}" ${RV.page >= pages ? 'disabled' : ''}>بعدی</button>`;
  },
  act: {
    open: (el, ev) => { if (ev.target.closest('button')) return; openProduct(Number(el.dataset.id), RV.rows.rows.map((r) => r.id), () => Review.load()); },
    pg: (el) => { RV.page = Number(el.dataset.p); Review.load(); },
    ok: async (el) => { await api(`/api/wb/products/${el.dataset.id}`, { method: 'PUT', body: { status: 'approved' } }); okToast('تأیید شد.'); Review.load(); },
    no: async (el) => {
      const n = await promptDlg('رد محصول', 'دلیل رد', '');
      if (n === null) return;
      await api(`/api/wb/products/${el.dataset.id}`, { method: 'PUT', body: { status: 'rejected', note: n } }); okToast('رد شد.'); Review.load();
    },
  },
};

// ======================================================================
// محصولات تکراری
// ======================================================================
export const Dupes = {
  title: 'محصولات تکراری',
  crumb: 'ویرایشگر داده‌ها · محصولاتی که از چند منبع یا چند بار وارد شده‌اند',
  top: () => `<button class="btn primary" data-act="scan">${icon('search', 16)} جست‌وجوی دوباره</button>`,
  async render() { return '<div id="dp-list"></div>'; },
  async mount() { await this.load(); },
  refresh() { return this.load(); },
  async load() {
    const pairs = await api('/api/dupes');
    const el = document.getElementById('dp-list');
    const card = (x) => `<div class="dp-card"><div class="flex">${x.thumb ? `<img class="thumb checker" src="${attr(x.thumb)}">` : `<div class="thumb ph">${icon('image', 16)}</div>`}
      <div class="grow"><a href="javascript:void 0" data-act="open" data-id="${x.id}"><b class="small">${esc(trunc(x.title, 90))}</b></a><div class="xs muted">${esc(x.brand?.name || 'بدون برند')} · ${statusChip(x.status)} ${modOn('quality') ? qualityBadge(x.quality, qmin()) : ''}</div>
      <div class="xs muted ltr" style="text-align:right">${esc(x.uid)} · بانک ${fa(x.bank_id)}</div></div></div></div>`;
    el.innerHTML = pairs.length ? pairs.map((pr) => `<div class="card mb12" data-pair="${pr.id}"><div class="card-b"><div class="flex wrap mb8"><span class="chip ${pr.score >= 90 ? 'err' : 'wait'}">شباهت ${fa(pr.score)}٪</span>${pr.reasons.map((r) => `<span class="tag">${esc(r)}</span>`).join('')}</div>
      <div class="grid2">${card(pr.a)}${card(pr.b)}</div><div class="dp-ai"></div>
      <div class="btns mt12"><button class="btn sm soft" data-act="merge" data-a="${pr.a.id}" data-b="${pr.b.id}">${icon('merge', 14)} ادغام در راست</button><button class="btn sm soft" data-act="merge" data-a="${pr.b.id}" data-b="${pr.a.id}">${icon('merge', 14)} ادغام در چپ</button>
        <button class="btn sm ghost" data-act="dismiss" data-id="${pr.id}">${icon('x', 14)} تکراری نیستند</button>
        ${modOn('ai') ? `<span class="grow"></span><button class="btn sm ghost" data-act="aijudge" data-id="${pr.id}" title="هوش مصنوعی دو محصول را مقایسه می‌کند">${icon('sparkles', 14)} داوری AI</button>` : ''}</div></div></div>`).join('')
      : `<div class="card"><div class="card-b">${emptyState('merge', 'محصول تکراری پیدا نشد', 'بعد از ورود هر بانک تمیز، تکراری‌ها خودکار جست‌وجو می‌شوند.')}</div></div>`;
  },
  act: {
    scan: async (el) => { busy(el, true, 'در حال جست‌وجو…'); try { const r = await api('/api/dupes/scan', { body: {} }); okToast(`${fa(r.found)} جفت تازه پیدا شد.`); Dupes.load(); } finally { busy(el, false); } },
    dismiss: async (el) => { await api(`/api/dupes/${el.dataset.id}/dismiss`, { body: {} }); Dupes.load(); },
    aijudge: async (el) => {
      busy(el, true, 'در حال داوری…');
      try {
        const r = await api(`/api/dupes/${el.dataset.id}/ai`, { body: {} });
        const keep = r.keep === 'b' ? [r.b_id, r.a_id] : [r.a_id, r.b_id];
        el.closest('[data-pair]').querySelector('.dp-ai').innerHTML = `<div class="alert ${r.same ? 'warn' : 'ok'} mt12">${icon('sparkles')}<div class="grow"><b class="small">${r.same ? 'به نظر هوش مصنوعی یک محصول‌اند' : 'به نظر هوش مصنوعی دو محصول جدا هستند'} (اطمینان ${fa(r.confidence)}٪)</b><div class="xs">${esc(r.reason)}</div></div>
          ${r.same ? `<button class="btn sm soft" data-act="merge" data-a="${keep[0]}" data-b="${keep[1]}">${icon('merge', 14)} ادغام در ${r.keep === 'b' ? 'چپ' : 'راست'} (کامل‌تر)</button>` : `<button class="btn sm soft" data-act="dismiss" data-id="${r.pair_id}">${icon('x', 14)} تکراری نیستند</button>`}</div>`;
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    open: (el) => openProduct(Number(el.dataset.id), [], () => Dupes.load()),
    merge: async (el) => {
      if (!(await confirmDlg('ادغام', 'محصول دوم در محصول اصلی ادغام شود؟ مقادیر خالی محصول اصلی از دومی پر می‌شود، تصاویر و منابع جمع می‌شوند و محصول دوم «ادغام‌شده» می‌شود. از «نسخه‌ها» برگشت‌پذیر است.', 'ادغام'))) return;
      await api('/api/dupes/merge', { body: { primary_id: Number(el.dataset.a), secondary_id: Number(el.dataset.b) } });
      okToast('ادغام شد.'); Dupes.load();
    },
  },
};

diffTable; // eslint-disable-line no-unused-expressions
