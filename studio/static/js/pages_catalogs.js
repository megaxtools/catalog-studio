// خروجی‌های نهایی (کاتالوگ‌ها): فهرست، مدیریت، ویرایش دستی و هوش مصنوعی هر فیلد و تصویر، تک‌به‌تک یا گروهی
import {
  S, api, icon, esc, attr, fa, num, jdate, toast, okToast, errToast, openLayer, confirmDlg, promptDlg, emptyState, every, go, trunc, fileUrl, openPath,
} from './core.js';
import { colInput, readCol, writeCol } from './pages_main.js';
import { historyTable, bindHistory } from './pages_logs.js';
import { busy, noProviderHint } from './ai_assist.js';
import { DEF_MODES, defPreview } from './defaults_ui.js';

const STATES = { draft: ['idle', 'پیش‌نویس'], review: ['wait', 'در حال بازبینی'], approved: ['ok', 'تأییدشده'], published: ['run', 'منتشرشده در مگا کارز'] };
const stChip = (s) => { const [c, t] = STATES[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}</span>`; };
const FMT = { xlsx: ['Excel', 'fileSheet'], csv: ['CSV', 'list'], json: ['JSON', 'code'] };
const ACTOR = { ui: 'کاربر', mcp: 'ایجنت', ai: 'هوش مصنوعی', api: 'API', system: 'سیستم' };
const TXT_MODES = { overwrite: 'تولید از نو', rewrite: 'بازنویسی یکتا', fill_missing: 'فقط اگر خالی است' };
const IMG_MODES = { fill_missing: 'فقط اگر تصویری نیست', add: 'افزودن تصویر', overwrite: 'جایگزینی شاخص' };
const isImg = (c) => ['image', 'images'].includes(c.input);
const SYS = ['source_url', 'source_name', 'dataset_code', 'scraped_at', 'product_key'];
const aiOk = (c) => !(c.kind === 'auto' && SYS.includes(c.generator || 'slug'));

function filesBtns(f) {
  return `${['xlsx', 'csv', 'json'].filter((k) => f[k]).map((k) => `<a class="btn sm" href="${fileUrl(f[k], true)}">${icon(FMT[k][1], 14)} ${FMT[k][0]}</a>`).join('')}
    ${f.zip ? `<a class="btn sm" href="${fileUrl(f.zip, true)}">${icon('package', 14)} ZIP نهایی</a>` : ''}
    ${f.raw_xlsx ? `<a class="btn sm ghost" href="${fileUrl(f.raw_xlsx, true)}" title="خروجی نهایی نیست">${icon('download', 14)} داده‌ی خام</a>` : ''}`;
}

// ======================================================================
// فهرست
// ======================================================================
const CL = { q: '', state: '' };
export const Catalogs = {
  title: 'خروجی‌های نهایی',
  crumb: 'کاتالوگ‌های ساخته‌شده؛ منبع ساخت محصولات در مگا کارز — مدیریت، ویرایش و بازسازی فایل‌ها',
  top: () => `<a class="btn primary" href="#/exports">${icon('plus')} ساخت خروجی جدید</a>`,
  async render() {
    return `<div class="card"><div class="flex wrap" style="padding:14px 16px;border-bottom:1px solid var(--z-100)">
        <div class="seg">${[['', 'همه'], ...Object.entries(STATES).map(([k, v]) => [k, v[1]])].map(([k, l]) => `<button class="${CL.state === k ? 'on' : ''}" data-act="st" data-v="${k}">${l}</button>`).join('')}</div>
        <span class="grow"></span><input class="inp sm" style="width:260px" placeholder="جست‌وجو در نام، عنوان و یادداشت…" data-input="q" value="${attr(CL.q)}"></div>
      <div id="cl-list"></div></div>`;
  },
  async mount() { await this.load(); every(4000, () => this.load(true)); },
  async load(silent) {
    const qs = new URLSearchParams();
    if (CL.q) qs.set('q', CL.q);
    if (CL.state) qs.set('state', CL.state);
    const list = await api(`/api/catalogs?${qs}`);
    const el = document.getElementById('cl-list');
    if (!el) return;
    const sig = JSON.stringify(list.map((x) => [x.id, x.status, x.state, x.rows_edited, x.files_stale, x.title]));
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    el.innerHTML = list.length ? list.map((c) => `
      <div style="padding:16px 20px;border-bottom:1px solid var(--z-100)">
        <div class="flex wrap">
          <span class="src-logo" style="width:40px;height:40px;border-radius:12px">${icon('package', 18)}</span>
          <div class="grow" style="min-width:260px"><a href="#/catalogs/${c.id}"><b style="color:var(--z-900);font-size:15px">${esc(c.title)}</b></a>
            <div class="xs muted ltr" style="text-align:right">${esc(c.name)}</div>
            <div class="flex wrap xs mt8" style="gap:6px">${Object.entries(c.format_schemas).map(([f, s]) => `<span class="tag">${icon(FMT[f][1], 11)} ${FMT[f][0]} · ${esc(s.name)}</span>`).join('')}
              <span class="muted">${jdate(c.created_at)} · ${num(c.rows_ok)} ردیف${c.rows_edited ? ` · ${num(c.rows_edited)} ردیف ویرایش‌شده` : ''}</span></div></div>
          ${c.status !== 'completed' ? `<span class="chip ${c.status === 'error' ? 'err' : 'run'}">${esc(c.status === 'error' ? 'خطا' : c.step || c.status)}</span>` : stChip(c.state)}
          ${c.files_stale ? `<span class="tag" style="color:var(--warn)">${icon('alert', 12)} نیازمند بازسازی فایل‌ها</span>` : ''}
          ${c.managed ? `<a class="btn sm primary" href="#/catalogs/${c.id}">${icon('edit', 14)} مدیریت</a>` : '<span class="xs muted" title="ساخته‌شده پیش از نسخه‌ی ۱.۶">بدون ردیف قابل ویرایش</span>'}
          <button class="btn sm icon ghost danger" data-act="del" data-id="${c.id}" title="حذف">${icon('trash', 14)}</button>
        </div>
        ${c.status === 'completed' ? `<div class="btns mt12">${filesBtns(c.files)}</div>` : ''}
      </div>`).join('') : emptyState('package', 'هنوز خروجی‌ای ندارید', 'از «خروجی‌ساز» بانک‌های داده را به فایل نهایی تبدیل کنید.', `<a class="btn primary" href="#/exports">${icon('plus', 16)} ساخت خروجی</a>`);
  },
  act: {
    st: (el) => { CL.state = el.dataset.v; el.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === el)); Catalogs.load(); },
    del: (el) => deleteCatalog(Number(el.dataset.id), () => Catalogs.load()),
  },
  input: { q: (() => { let t; return (el) => { clearTimeout(t); t = setTimeout(() => { CL.q = el.value.trim(); Catalogs.load(); }, 350); }; })() },
};

function deleteCatalog(id, after) {
  const l = openLayer('modal', `<div class="card-h"><h3>حذف خروجی</h3></div><div class="card-b">
    <div>این خروجی و همه‌ی ردیف‌ها و ویرایش‌هایش از استودیو حذف شود؟ (رکورد حذف در تاریخچه می‌ماند.)</div>
    <label class="check mt12"><input type="checkbox" id="del-files"> فایل‌های روی دیسک (Excel، CSV، JSON، ZIP و پوشه‌ی تصاویر) هم حذف شوند</label></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn danger" id="del-ok">${icon('trash', 16)} حذف</button></div>`);
  l.box.querySelector('#del-ok').addEventListener('click', async () => {
    try {
      await api(`/api/catalogs/${id}?files=${l.box.querySelector('#del-files').checked ? 1 : 0}`, { method: 'DELETE' });
      okToast('خروجی حذف شد.'); l.close(); after && after();
    } catch (e) { errToast(e); }
  });
}

// ======================================================================
// جزئیات و مدیریت یک خروجی
// ======================================================================
const C = { id: 0, det: null, sid: 0, page: 1, q: '', filter: '', sel: new Set(), rows: null };
const schemaOf = () => C.det.schemas.find((s) => s.id === C.sid) || C.det.schemas[0];
const cols = () => schemaOf().columns;

export const CatalogDetail = {
  title: 'مدیریت خروجی',
  crumb: 'خروجی‌های نهایی',
  top: () => `<a class="btn ghost" href="#/catalogs">${icon('chevronRight', 16)} همه‌ی خروجی‌ها</a>`,
  async render(p) {
    C.id = Number(p.id); C.page = 1; C.q = ''; C.filter = ''; C.sel = new Set();
    C.det = await api(`/api/catalogs/${C.id}`);
    C.sid = C.det.schemas[0]?.id;
    document.getElementById('page-title').textContent = C.det.title;
    if (!C.det.managed) {
      return `<div class="alert warn">${icon('alert')}<div><b>این خروجی پیش از نسخه‌ی ۱.۶ ساخته شده است.</b>ردیف‌هایش در پایگاه داده ذخیره نشده‌اند. برای مدیریت و ویرایش، از «خروجی‌ساز» همان بانک‌ها را دوباره خروجی بگیرید.</div></div>
        <div class="card mt16"><div class="card-b btns">${filesBtns(C.det.files)}</div></div>`;
    }
    return `<div id="cd-head"></div><div id="cd-jobs"></div>
      <div class="card mt16"><div class="tabs" id="cd-tabs"></div><div id="cd-bar"></div><div class="tbl-wrap" id="cd-rows"></div><div class="pager" id="cd-pager"></div></div>`;
  },
  async mount(view) {
    if (!C.det.managed) return;
    bindHistory(view, () => this.refresh());
    this.head();
    this.tabs();
    await this.load();
    every(2500, () => this.jobs());
    every(6000, async () => { const d = await api(`/api/catalogs/${C.id}`).catch(() => null); if (d && (d.files_stale !== C.det.files_stale || d.rows_edited !== C.det.rows_edited)) { C.det = { ...C.det, ...d }; this.head(); } });
  },
  async refresh() { C.det = await api(`/api/catalogs/${C.id}`); this.head(); await this.load(); },
  head() {
    const d = C.det;
    document.getElementById('cd-head').innerHTML = `
      <div class="card"><div class="card-b">
        <div class="flex top wrap">
          <span class="src-logo">${icon('package', 20)}</span>
          <div class="grow" style="min-width:300px">
            <input class="inp" id="cd-title" value="${attr(d.title)}" style="font-size:17px;font-weight:800;height:44px" data-ai-label="عنوان کاتالوگ">
            <div class="flex wrap small muted mt8" style="gap:8px"><span class="tag ltr">${esc(d.name)}</span><span>${jdate(d.created_at)}</span>
              ${d.datasets.map((x) => `<a class="tag" href="#/datasets/${x.id}">${icon('database', 12)} ${esc(trunc(x.title, 40))}</a>`).join('')}</div>
          </div>
          <select class="inp" id="cd-state" style="width:auto">${Object.entries(STATES).map(([k, v]) => `<option value="${k}" ${d.state === k ? 'selected' : ''}>${v[1]}</option>`).join('')}</select>
          <button class="btn primary" data-act="savemeta">${icon('save', 16)} ذخیره</button>
        </div>
        <textarea class="inp mt12" id="cd-notes" rows="2" placeholder="یادداشت (مثلاً وضعیت بازبینی، تغییرات لازم، تاریخ انتشار در مگا کارز)">${esc(d.notes || '')}</textarea>
        ${d.files_stale ? `<div class="alert warn mt12">${icon('alert')}<div class="grow"><b>فایل‌ها با آخرین ویرایش‌ها هم‌خوان نیستند.</b>پس از پایان ویرایش‌ها، فایل‌های نهایی را دوباره بسازید.</div><button class="btn sm primary" data-act="rebuild">${icon('refresh', 14)} بازسازی فایل‌ها</button></div>` : ''}
        <div class="kpi-line mt12"><span>ردیف <b>${num(d.rows_ok)}</b></span><span>ویرایش‌شده <b>${num(d.rows_edited)}</b></span>${d.rows - d.rows_ok ? `<span>کنار گذاشته <b>${num(d.rows - d.rows_ok)}</b></span>` : ''}
          ${Object.entries(d.format_schemas).map(([f, s]) => `<span>${FMT[f][0]} <b>${esc(s.name)}</b></span>`).join('')}<span>تغییرات ثبت‌شده <b>${num(d.history_count)}</b></span></div>
        <div class="btns mt12">${filesBtns(d.files)}
          <button class="btn sm soft" data-act="rebuild">${icon('refresh', 14)} بازسازی فایل‌ها</button>
          <button class="btn sm ghost" data-act="settings">${icon('settings', 14)} قالب‌ها و اسکیماها</button>
          <button class="btn sm ghost" data-act="sync" title="ویرایش‌های این خروجی به‌عنوان ویرایش دستی روی محصولات بانک داده هم اعمال شود">${icon('database', 14)} اعمال روی بانک داده</button>
          <button class="btn sm ghost" data-act="hist">${icon('clock', 14)} تاریخچه</button>
          ${d.files.images_dir ? `<button class="btn sm ghost" data-act="folder">${icon('folder', 14)} پوشه</button>` : ''}
          <button class="btn sm icon ghost danger" data-act="del" title="حذف خروجی">${icon('trash', 14)}</button></div>
      </div></div>`;
  },
  tabs() {
    document.getElementById('cd-tabs').innerHTML = C.det.schemas.map((s) => `<button class="${s.id === C.sid ? 'on' : ''}" data-act="schema" data-id="${s.id}">${icon('columns', 15)} ${esc(s.name)} ${s.formats.map((f) => `<span class="tag" style="font-size:10.5px">${FMT[f][0]}</span>`).join('')}</button>`).join('');
    document.getElementById('cd-bar').innerHTML = `<div class="flex wrap" style="padding:14px 16px;border-bottom:1px solid var(--z-100)">
      <div class="seg">${[['', 'همه'], ['edited', 'ویرایش‌شده'], ['warn', 'دارای هشدار'], ['noimage', 'بدون تصویر'], ['excluded', 'کنار گذاشته']].map(([k, l]) => `<button class="${C.filter === k ? 'on' : ''}" data-act="flt" data-v="${k}">${l}</button>`).join('')}</div>
      <input class="inp sm" style="width:240px" placeholder="جست‌وجو در همه‌ی فیلدها…" data-input="q" value="${attr(C.q)}">
      <span class="grow"></span><span class="small muted" id="cd-selc"></span>
      <button class="btn sm soft" data-act="ai">${icon('sparkles', 14)} هوش مصنوعی</button>
      <button class="btn sm soft" data-act="bulk">${icon('edit', 14)} ویرایش گروهی</button>
      <span id="cd-selb"></span></div>`;
  },
  async load() {
    const qs = new URLSearchParams({ schema_id: C.sid, page: C.page, size: 50 });
    if (C.q) qs.set('q', C.q);
    if (C.filter) qs.set('filter', C.filter);
    C.rows = await api(`/api/catalogs/${C.id}/rows?${qs}`);
    const show = cols().filter((c) => !isImg(c) && !['json', 'specs', 'group', 'bullet_groups'].includes(c.input)).slice(0, 4);
    const el = document.getElementById('cd-rows');
    if (!el) return;
    el.innerHTML = C.rows.rows.length ? `<table class="tbl"><thead><tr><th style="width:34px"><input type="checkbox" data-change="selall"></th><th style="width:40px">#</th><th style="width:60px"></th>
      ${show.map((c) => `<th>${esc(c.label || c.key)}</th>`).join('')}<th>تصاویر</th><th>ویرایش</th><th></th></tr></thead><tbody>
      ${C.rows.rows.map((r) => `<tr class="click ${C.sel.has(r.id) ? 'sel' : ''} ${r.status === 'excluded' ? 'muted' : ''}" data-act="row" data-id="${r.id}">
        <td><input type="checkbox" data-change="sel" data-id="${r.id}" ${C.sel.has(r.id) ? 'checked' : ''}></td><td class="small muted">${fa(r.seq)}</td>
        <td>${r.image_urls.feature ? `<img class="thumb checker" style="object-fit:contain" loading="lazy" src="${attr(r.image_urls.feature)}&t=${encodeURIComponent(r.updated_at || '')}">` : `<div class="thumb ph">${icon('image', 16)}</div>`}</td>
        ${show.map((c) => `<td class="small" style="max-width:260px">${r.e[c.key] ? `<span class="edot" title="ویرایش‌شده توسط ${attr(ACTOR[r.e[c.key]] || r.e[c.key])}"></span>` : ''}${r.f[c.key] ? `<span class="xs" style="color:var(--warn)">${icon('alert', 11)}</span>` : ''}<span class="${c.key === show[0].key ? '' : 'muted'}">${esc(trunc(typeof r.v[c.key] === 'object' ? JSON.stringify(r.v[c.key]) : r.v[c.key] ?? '', c.key === show[0].key ? 90 : 50))}</span></td>`).join('')}
        <td class="small nowrap">${r.images.feature ? '۱' : '۰'} + ${fa((r.images.gallery || []).length)}</td>
        <td>${Object.keys(r.e).length ? `<span class="tag p">${fa(Object.keys(r.e).length)} فیلد</span>` : '<span class="xs muted">—</span>'}${r.status === 'excluded' ? ' <span class="tag">کنار گذاشته</span>' : ''}</td>
        <td>${icon('chevronLeft', 14)}</td></tr>`).join('')}</tbody></table>` : `<div class="card-b">${emptyState('list', 'ردیفی نیست', 'فیلتر یا جست‌وجو را تغییر دهید.')}</div>`;
    const pages = Math.max(1, Math.ceil(C.rows.total / C.rows.size));
    document.getElementById('cd-pager').innerHTML = `<button class="btn sm" data-act="pg" data-p="${C.page - 1}" ${C.page <= 1 ? 'disabled' : ''}>${icon('chevronRight', 16)} قبلی</button>
      <span class="small">صفحه ${fa(C.page)} از ${fa(pages)} · ${num(C.rows.total)} ردیف</span>
      <button class="btn sm" data-act="pg" data-p="${C.page + 1}" ${C.page >= pages ? 'disabled' : ''}>بعدی ${icon('chevronLeft', 16)}</button>`;
    this.selUI();
  },
  selUI() {
    const n = C.sel.size;
    const c = document.getElementById('cd-selc');
    if (c) c.textContent = n ? `${fa(n)} ردیف انتخاب شده` : '';
    const b = document.getElementById('cd-selb');
    if (b) b.innerHTML = n ? `<button class="btn sm" data-act="exclude" data-v="excluded">${icon('eye', 14)} کنار گذاشتن</button><button class="btn sm" data-act="exclude" data-v="ok">${icon('check', 14)} بازگرداندن</button><button class="btn sm ghost" data-act="selclear">${icon('x', 14)}</button>` : '';
  },
  async jobs() {
    const box = document.getElementById('cd-jobs');
    if (!box) return;
    const jobs = (await api('/api/ai/jobs').catch(() => [])).filter((j) => Number(j.options?.catalog_id) === C.id && ['running', 'pending', 'paused', 'error'].includes(j.status)).slice(0, 2);
    const html = jobs.map((j) => {
      const pct = j.progress_total ? Math.round(j.progress_done / j.progress_total * 100) : 0;
      return `<div class="card mt16"><div class="card-b flex wrap"><span style="color:var(--primary)">${icon(j.status === 'running' ? 'loader' : 'sparkles', 18, j.status === 'running' ? 'spin' : '')}</span>
        <div class="grow"><b class="small">${esc(j.profile?.name || 'هوش مصنوعی')}</b><div class="xs muted">${esc(j.step || '')}${j.error ? ` · <span style="color:var(--err)">${esc(j.error)}</span>` : ''}</div>
        <div class="flex mt8"><div class="grow"><div class="prog"><i style="width:${pct}%"></i></div></div><span class="xs nowrap">${fa(j.progress_done)} از ${fa(j.progress_total)}</span></div></div>
        ${j.status === 'running' ? `<button class="btn sm" data-act="jstop" data-id="${j.id}">${icon('pause', 14)} توقف</button>` : `<button class="btn sm soft" data-act="jresume" data-id="${j.id}">${icon('play', 14)} ادامه</button><button class="btn sm icon ghost" data-act="jdel" data-id="${j.id}">${icon('x', 14)}</button>`}</div></div>`;
    }).join('');
    const was = box.dataset.running === '1';
    const running = jobs.some((j) => j.status === 'running');
    if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
    if (running) { C._tick = (C._tick || 0) + 1; if (C._tick % 2 === 0) this.load(); } else if (was) { this.refresh(); }
    box.dataset.running = running ? '1' : '0';
  },
  act: {
    schema: (el) => { C.sid = Number(el.dataset.id); C.page = 1; CatalogDetail.tabs(); CatalogDetail.load(); },
    flt: (el) => { C.filter = el.dataset.v; C.page = 1; el.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === el)); CatalogDetail.load(); },
    pg: (el) => { C.page = Number(el.dataset.p); CatalogDetail.load(); },
    row: (el, ev) => { if (ev.target.closest('input,a,button')) return; openRow(Number(el.dataset.id)); },
    selclear: () => { C.sel.clear(); CatalogDetail.load(); },
    exclude: async (el) => { await api(`/api/catalogs/${C.id}/rows/bulk`, { body: { row_ids: [...C.sel], status: el.dataset.v } }); okToast('انجام شد.'); C.sel.clear(); CatalogDetail.refresh(); },
    savemeta: async () => {
      C.det = await api(`/api/catalogs/${C.id}`, { method: 'PUT', body: { title: document.getElementById('cd-title').value.trim(), state: document.getElementById('cd-state').value, notes: document.getElementById('cd-notes').value } });
      document.getElementById('page-title').textContent = C.det.title;
      okToast('ذخیره شد.'); CatalogDetail.head();
    },
    rebuild: async (el) => {
      busy(el, true, 'در حال ساخت فایل‌ها…');
      try { await api(`/api/catalogs/${C.id}/rebuild`, { body: {} }); okToast('فایل‌های نهایی با آخرین ویرایش‌ها ساخته شدند.'); await CatalogDetail.refresh(); } catch (e) { errToast(e); busy(el, false); }
    },
    sync: async () => {
      if (!(await confirmDlg('اعمال روی بانک داده', `ویرایش‌های این خروجی (اسکیمای «${esc(schemaOf().name)}») به‌عنوان «ویرایش دستی» روی محصولات بانک داده هم ثبت شوند تا در خروجی‌های بعدی هم بیایند؟`, 'اعمال'))) return;
      const r = await api(`/api/catalogs/${C.id}/sync`, { body: { schema_id: C.sid } });
      okToast(`${fa(r.items_updated)} محصول به‌روز شد.`);
    },
    hist: async () => {
      const r = await api(`/api/history?parent_id=${C.id}&size=300`);
      const l = openLayer('modal', `<div class="card-h"><h3>تاریخچه‌ی تغییرات این خروجی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="tbl-wrap" style="max-height:70vh">${historyTable(r.rows.filter((h) => h.entity !== 'item'))}</div>`, { wide: true });
      bindHistory(l.box, () => { l.close(); CatalogDetail.refresh(); });
    },
    folder: () => openPath(C.det.files.images_dir),
    del: () => deleteCatalog(C.id, () => go('#/catalogs')),
    settings: () => openSettings(),
    bulk: () => openBulkEdit(),
    ai: () => openCatalogAI([...C.sel]),
    jstop: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/stop`, { body: {} }); CatalogDetail.jobs(); },
    jresume: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/resume`, { body: {} }); CatalogDetail.jobs(); },
    jdel: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/delete`, { body: {} }); CatalogDetail.jobs(); },
  },
  change: {
    sel: (el) => { const id = Number(el.dataset.id); el.checked ? C.sel.add(id) : C.sel.delete(id); el.closest('tr').classList.toggle('sel', el.checked); CatalogDetail.selUI(); },
    selall: (el) => { C.rows.rows.forEach((r) => (el.checked ? C.sel.add(r.id) : C.sel.delete(r.id))); CatalogDetail.load(); },
  },
  input: { q: (() => { let t; return (el) => { clearTimeout(t); t = setTimeout(() => { C.q = el.value.trim(); C.page = 1; CatalogDetail.load(); }, 350); }; })() },
};

// ----------------------------------------------------------------------------- تنظیمات قالب‌ها
async function openSettings() {
  const d = C.det;
  const all = S.boot.schemas;
  const inCat = new Set(d.schemas.map((s) => s.id));
  const l = openLayer('modal', `<div class="card-h"><h3>قالب‌ها، اسکیماها و پیوند تصاویر</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b">
      <div class="lbl mb8">قالب فایل‌ها و اسکیمای هر قالب</div>
      <div class="fmt-grid">${['xlsx', 'csv', 'json'].map((f) => `<div class="fmt-row"><label class="check grow"><input type="checkbox" data-f="${f}" ${d.formats.includes(f) ? 'checked' : ''}> ${icon(FMT[f][1], 14)} ${FMT[f][0]}</label>
        <select class="inp sm" data-fs="${f}" style="max-width:280px">${d.schemas.map((s) => `<option value="${s.id}" ${d.format_schemas[f]?.id === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>`).join('')}</div>
      <div class="hint mt8">فقط اسکیماهایی که در این خروجی هستند قابل انتخاب‌اند. برای اسکیمای دیگر، اول آن را به خروجی اضافه کنید (مقادیرش از محصولات بانک داده محاسبه می‌شود).</div>
      <div class="flex mt12"><select class="inp sm" id="st-add" style="max-width:280px">${all.filter((s) => !inCat.has(s.id)).map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select>
        <button class="btn sm soft" id="st-addb" ${all.some((s) => !inCat.has(s.id)) ? '' : 'disabled'}>${icon('plus', 14)} افزودن اسکیما به خروجی</button></div>
      <div class="lbl mt24 mb8">پیوند تصاویر در فایل‌ها</div>
      <select class="inp sm" id="st-link" style="max-width:320px">${[['relative', 'مسیر نسبی فایل‌های نهایی'], ['prefix', 'پیشوند دلخواه (CDN)'], ['source', 'لینک اصلی منبع']].map(([k, l2]) => `<option value="${k}" ${d.link_mode === k ? 'selected' : ''}>${l2}</option>`).join('')}</select>
      <input class="inp sm ltr mt8" id="st-prefix" value="${attr(d.options.link_prefix || '')}" placeholder="https://cdn.megacars.ir/catalog/">
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="st-ok">${icon('save', 16)} ذخیره</button></div>`);
  const b = l.box;
  b.querySelector('#st-addb').addEventListener('click', async (ev) => {
    busy(ev.currentTarget, true, 'در حال محاسبه…');
    try { C.det = await api(`/api/catalogs/${C.id}/schemas`, { body: { schema_id: Number(b.querySelector('#st-add').value) } }); okToast('اسکیما افزوده شد.'); l.close(); CatalogDetail.tabs(); CatalogDetail.head(); openSettings(); } catch (e) { errToast(e); }
  });
  b.querySelector('#st-ok').addEventListener('click', async () => {
    const formats = [...b.querySelectorAll('[data-f]')].filter((x) => x.checked).map((x) => x.dataset.f);
    if (!formats.length) { toast('دست‌کم یک قالب انتخاب کنید.', 'err'); return; }
    const fs = {};
    formats.forEach((f) => { fs[f] = Number(b.querySelector(`[data-fs="${f}"]`).value); });
    try {
      C.det = await api(`/api/catalogs/${C.id}`, { method: 'PUT', body: { formats, format_schemas: fs, link_mode: b.querySelector('#st-link').value, link_prefix: b.querySelector('#st-prefix').value.trim() } });
      okToast('ذخیره شد؛ برای اعمال روی فایل‌ها «بازسازی» را بزنید.'); l.close(); CatalogDetail.tabs(); CatalogDetail.head();
    } catch (e) { errToast(e); }
  });
}

// ----------------------------------------------------------------------------- ویرایش گروهی
function openBulkEdit() {
  const cs = cols().filter((c) => !isImg(c));
  const n = C.sel.size;
  const l = openLayer('modal', `<div class="card-h"><h3>ویرایش گروهی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:70vh;overflow:auto">
      <div class="seg mb12" id="be-scope"><button class="${n ? 'on' : ''}" data-s="sel" ${n ? '' : 'disabled'}>${fa(n)} ردیف انتخاب‌شده</button><button class="${n ? '' : 'on'}" data-s="all">همه‌ی ${fa(C.det.rows)} ردیف</button></div>
      <div class="form-grid"><div class="field"><label>ستون</label><select class="inp" id="be-col">${cs.map((c) => `<option value="${attr(c.key)}">${esc(c.label || c.key)} (${esc(c.key)})</option>`).join('')}</select></div>
        <div class="field"><label>عملیات</label><select class="inp" id="be-op"><option value="set">تعیین مقدار</option><option value="replace">جست‌وجو و جایگزینی</option><option value="prepend">افزودن به ابتدا</option><option value="append">افزودن به انتها</option><option value="default">اعمال مقدار پیش‌فرض اسکیما</option></select></div></div>
      <div id="be-ed" class="mt12"></div>
      <div class="hint mt8">همه‌ی تغییرها با مقدار قبلی در تاریخچه ثبت می‌شوند و قابل بازگرداندن‌اند.</div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="be-ok">${icon('check', 16)} اعمال</button></div>`, { wide: true });
  const b = l.box;
  let scope = n ? 'sel' : 'all';
  b.querySelectorAll('[data-s]').forEach((x) => x.addEventListener('click', () => { scope = x.dataset.s; b.querySelectorAll('[data-s]').forEach((y) => y.classList.toggle('on', y === x)); }));
  const draw = () => {
    const col = cs.find((c) => c.key === b.querySelector('#be-col').value);
    const op = b.querySelector('#be-op').value;
    b.querySelector('#be-ed').innerHTML = op === 'set' ? `<div class="field" data-col="${attr(col.key)}"><label class="lbl">${esc(col.label || col.key)}</label>${colInput(col, null, {})}</div>`
      : op === 'replace' ? `<div class="form-grid"><div class="field"><label>جست‌وجو</label><input class="inp" id="be-find" data-noai></div><div class="field"><label>جایگزین</label><input class="inp" id="be-rep"></div></div><label class="check small mt8"><input type="checkbox" id="be-rx"> عبارت باقاعده (Regex)</label>`
        : op === 'default' ? defaultBox(col)
        : `<div class="field"><label>متن</label><input class="inp" id="be-add"></div>`;
  };
  b.querySelector('#be-col').addEventListener('change', draw);
  b.querySelector('#be-op').addEventListener('change', draw);
  draw();
  b.querySelector('#be-ok').addEventListener('click', async () => {
    const col = cs.find((c) => c.key === b.querySelector('#be-col').value);
    const op = b.querySelector('#be-op').value;
    const body = { schema_id: C.sid, row_ids: scope === 'sel' ? [...C.sel] : [] };
    try {
      if (op === 'set') body.set = { [col.key]: readCol(b.querySelector('[data-col]'), col) };
      else if (op === 'replace') body.find_replace = { key: col.key, find: b.querySelector('#be-find').value, replace: b.querySelector('#be-rep').value, regex: b.querySelector('#be-rx').checked };
      else if (op === 'default') { body.apply_default = [col.key]; body.default_mode = b.querySelector('#be-dm').value; }
      else body[op] = { [col.key]: b.querySelector('#be-add').value };
      const r = await api(`/api/catalogs/${C.id}/rows/bulk`, { body });
      okToast(`${fa(r.updated)} ردیف تغییر کرد.`); l.close(); CatalogDetail.refresh();
    } catch (e) { errToast(e); }
  });
}

function defaultBox(col) {
  const live = (S.boot.schemas.find((x) => x.id === C.sid)?.columns || []).find((c) => c.key === col.key) || col;
  const pv = defPreview(live, live.default);
  if (!pv) return `<div class="alert info">${icon('info')}<div>این ستون در اسکیمای «${esc(schemaOf().name)}» مقدار پیش‌فرض ندارد. در «اسکیماهای داده» برای ستون پیش‌فرض تعیین و ذخیره کنید، بعد همین‌جا اعمالش کنید.</div></div>`;
  return `<div class="pathbox small" style="white-space:pre-wrap">${esc(pv)}</div>
    <div class="field mt12"><label>نحوه‌ی اعمال</label><select class="inp" id="be-dm" style="max-width:280px">${DEF_MODES.map(([k, t]) => `<option value="${k}" ${(live.default_mode || 'fill') === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
    <div class="hint">پیش‌فرض فعلی اسکیما استفاده می‌شود، حتی اگر پس از ساخت این خروجی تعریف شده باشد.</div>`;
}

// ----------------------------------------------------------------------------- هوش مصنوعی گروهی
function openCatalogAI(sel) {
  const cs = cols().filter(aiOk);
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} ویرایش خروجی با هوش مصنوعی</h3><span class="sub">${esc(schemaOf().name)}</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:72vh;overflow:auto">
      <div class="seg mb12" id="ca-scope"><button class="${sel.length ? 'on' : ''}" data-s="sel" ${sel.length ? '' : 'disabled'}>${fa(sel.length)} ردیف انتخاب‌شده</button><button class="${sel.length ? '' : 'on'}" data-s="all">همه‌ی ردیف‌ها</button></div>
      <div class="tbl-wrap" style="border:1px solid var(--z-200);border-radius:14px;max-height:380px"><table class="tbl"><thead><tr><th></th><th>ستون</th><th>حالت</th><th>دستور</th></tr></thead><tbody>
        ${cs.map((c) => `<tr data-key="${attr(c.key)}"><td><input type="checkbox" data-pick></td><td><b class="small">${esc(c.label || c.key)}</b><div class="xs muted ltr" style="text-align:right">${esc(c.key)} · ${esc(c.input || 'text')}</div></td>
          <td><select class="inp sm" data-mode>${Object.entries(isImg(c) ? IMG_MODES : TXT_MODES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></td>
          <td><div class="flex" style="gap:6px"><input class="inp sm grow" data-instr placeholder="${attr(c.ai_instruction || 'اختیاری')}" style="min-width:200px">${isImg(c) ? '<input class="inp sm" type="number" min="1" max="6" value="1" data-count style="width:58px">' : ''}</div></td></tr>`).join('')}</tbody></table></div>
      <div class="hint mt8">نتیجه مستقیم در ردیف‌های همین خروجی ذخیره و در تاریخچه ثبت می‌شود (برگشت‌پذیر). داده‌ی بانک داده تغییر نمی‌کند مگر «اعمال روی بانک داده» را بزنید.</div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ca-go">${icon('sparkles', 16)} شروع</button></div>`, { wide: true });
  const b = l.box;
  let scope = sel.length ? 'sel' : 'all';
  b.querySelectorAll('[data-s]').forEach((x) => x.addEventListener('click', () => { scope = x.dataset.s; b.querySelectorAll('[data-s]').forEach((y) => y.classList.toggle('on', y === x)); }));
  b.querySelector('#ca-go').addEventListener('click', async () => {
    const columns = [...b.querySelectorAll('tbody tr')].filter((tr) => tr.querySelector('[data-pick]').checked)
      .map((tr) => ({ key: tr.dataset.key, mode: tr.querySelector('[data-mode]').value, instruction: tr.querySelector('[data-instr]').value, count: Number(tr.querySelector('[data-count]')?.value || 1) }));
    if (!columns.length) { toast('دست‌کم یک ستون انتخاب کنید.', 'err'); return; }
    try {
      await api(`/api/catalogs/${C.id}/ai`, { body: { schema_id: C.sid, columns, row_ids: scope === 'sel' ? sel : [] } });
      okToast('ویرایش با هوش مصنوعی آغاز شد.'); l.close(); CatalogDetail.jobs();
    } catch (e) { noProviderHint(e); }
  });
}

// ----------------------------------------------------------------------------- کشوی ردیف
async function openRow(rid) {
  const ids = (C.rows?.rows || []).map((r) => r.id);
  const idx = ids.indexOf(rid);
  let row = (await api(`/api/catalogs/${C.id}/rows?schema_id=${C.sid}&ids=${rid}`)).rows[0];
  const cs = cols().filter((c) => !isImg(c));
  const layer = openLayer('drawer', `
    <div class="drawer-h"><h3 class="ellipsis">${esc(row.v.title || row.title || 'ردیف')}</h3>${row.status === 'excluded' ? '<span class="tag">کنار گذاشته</span>' : ''}
      <button class="btn sm icon ghost" data-nav="${ids[idx - 1] || ''}" ${idx <= 0 ? 'disabled' : ''}>${icon('chevronRight', 16)}</button>
      <button class="btn sm icon ghost" data-nav="${ids[idx + 1] || ''}" ${idx < 0 || idx >= ids.length - 1 ? 'disabled' : ''}>${icon('chevronLeft', 16)}</button>
      <button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="drawer-b"><div id="rw-imgs"></div>
      <div class="sec-title">${icon('columns', 16)} فیلدهای «${esc(schemaOf().name)}» <span class="line"></span>
        <button class="btn xs soft" data-rai-all>${icon('sparkles', 12)} همه‌ی فیلدهای خالی با AI</button></div>
      ${cs.map((c) => `<div class="field mt16" data-col="${attr(c.key)}"><div class="flex"><label class="lbl ltr" style="text-align:right">${esc(c.label || c.key)} <span class="xs muted">(${esc(c.key)})</span></label>
        ${row.e[c.key] ? `<span class="tag p">ویرایش‌شده · ${esc(ACTOR[row.e[c.key]] || row.e[c.key])}</span>` : ''}${row.f[c.key] ? `<span class="tag" style="color:var(--warn)">${row.f[c.key] === 'unmapped' ? 'نگاشت‌نشده' : 'خالی'}</span>` : ''}
        <span class="grow"></span>${aiOk(c) ? `<button class="btn xs soft" data-rai="${attr(c.key)}" title="تولید یا بازنویسی این فیلد با هوش مصنوعی">${icon('sparkles', 12)} AI</button>` : ''}
        <button class="btn xs ghost" data-rhist="${attr(c.key)}" title="تاریخچه‌ی این فیلد">${icon('clock', 12)}</button></div>
        ${colInput(c, row.v[c.key], {})}</div>`).join('')}
      <div class="field mt16"><label class="lbl">یادداشت ردیف</label><input class="inp" data-note value="${attr(row.note || '')}"></div>
      <div id="rw-hist" class="mt16"></div>
    </div>
    <div class="drawer-f">
      <button class="btn" data-excl>${row.status === 'excluded' ? `${icon('check', 16)} بازگرداندن به خروجی` : `${icon('eye', 16)} کنار گذاشتن از خروجی`}</button>
      <button class="btn ghost danger" data-rdel>${icon('trash', 16)}</button>
      <span class="grow"></span><button class="btn" data-close>بستن</button><button class="btn primary" data-save>${icon('save', 16)} ذخیره</button></div>`);
  const box = layer.box;
  const orig = {};
  cs.forEach((c) => { orig[c.key] = readCol(box.querySelector(`[data-col="${CSS.escape(c.key)}"]`), c); });
  const drawImgs = () => { box.querySelector('#rw-imgs').innerHTML = imagesHtml(row); };
  drawImgs();
  bindHistory(box, async () => { layer.close(); await CatalogDetail.load(); openRow(rid); });
  box.querySelectorAll('[data-nav]').forEach((b) => b.addEventListener('click', () => { const n = Number(b.dataset.nav); if (!n) return; layer.close(); openRow(n); }));
  box.addEventListener('click', async (ev) => {
    const ai = ev.target.closest('[data-rai]');
    if (ai) {
      const key = ai.dataset.rai;
      const col = cs.find((c) => c.key === key);
      const ins = await promptDlg(`تولید «${col.label || key}» با هوش مصنوعی`, 'دستور (اختیاری)', '', 'خالی = دستور پیش‌فرض ستون در اسکیما. نتیجه بلافاصله ذخیره و در تاریخچه ثبت می‌شود.');
      if (ins === null) return;
      busy(ai, true, '…');
      try {
        const r = await api(`/api/catalogs/${C.id}/ai`, { body: { schema_id: C.sid, row_ids: [rid], wait: true, columns: [{ key, mode: 'overwrite', instruction: ins }] } });
        if (!r.ok) throw new Error(r.error);
        row = r.row;
        const el = box.querySelector(`[data-col="${CSS.escape(key)}"]`);
        writeCol(el, col, row.v[key]);
        orig[key] = readCol(el, col);
        okToast('تولید و ذخیره شد (در تاریخچه قابل بازگرداندن است).');
        CatalogDetail.load();
      } catch (e) { noProviderHint(e); } finally { busy(ai, false); }
    }
    if (ev.target.closest('[data-rai-all]')) {
      const btn = ev.target.closest('[data-rai-all]');
      busy(btn, true, '…');
      try {
        const r = await api(`/api/catalogs/${C.id}/ai`, { body: { schema_id: C.sid, row_ids: [rid], wait: true, columns: cs.filter(aiOk).map((c) => ({ key: c.key, mode: 'fill_missing' })) } });
        if (!r.ok) throw new Error(r.error);
        okToast(`${fa(Object.keys(r.generated).length)} فیلد تکمیل شد.`); layer.close(); CatalogDetail.load(); openRow(rid);
      } catch (e) { noProviderHint(e); busy(btn, false); }
    }
    const hh = ev.target.closest('[data-rhist]');
    if (hh) {
      const r = await api(`/api/history?entity=export_row&entity_id=${rid}&size=100`);
      const f = `${C.sid}:${hh.dataset.rhist}`;
      box.querySelector('#rw-hist').innerHTML = `<div class="sec-title">${icon('clock', 16)} تاریخچه‌ی «${esc(hh.dataset.rhist)}» <span class="line"></span></div>${historyTable(r.rows.filter((h) => h.field === f), { noEntity: true })}`;
      box.querySelector('#rw-hist').scrollIntoView({ behavior: 'smooth' });
    }
    const ia = ev.target.closest('[data-img]');
    if (ia) {
      const [action, slot, index] = ia.dataset.img.split(':');
      const body = { slot, index: Number(index || 0), rembg: box.querySelector('#rw-rembg')?.checked };
      if (action === 'delete' && !(await confirmDlg('حذف تصویر', 'این تصویر از خروجی حذف شود؟ فایل به پوشه‌ی _removed منتقل می‌شود.', 'حذف', true))) return;
      if (action === 'move') body.to = Number(ia.dataset.to);
      if (action === 'generate') {
        const p = await promptDlg('ساخت تصویر با هوش مصنوعی', 'توضیح تصویر (اختیاری)', '', 'خالی = عکس محصول روی پس‌زمینه‌ی سفید');
        if (p === null) return;
        if (p) body.prompt = p;
      }
      if (action === 'url') {
        const u = await promptDlg('افزودن تصویر از لینک', 'آدرس تصویر', '');
        if (!u) return;
        body.url = u;
      }
      await imgAction(action, body, ia);
    }
    if (ev.target.closest('[data-excl]')) {
      await api(`/api/catalogs/${C.id}/rows/${rid}`, { method: 'PUT', body: { status: row.status === 'excluded' ? 'ok' : 'excluded' } });
      okToast('انجام شد.'); layer.close(); CatalogDetail.refresh();
    }
    if (ev.target.closest('[data-rdel]')) {
      if (!(await confirmDlg('حذف ردیف', 'این ردیف از خروجی حذف شود؟ (در تاریخچه می‌ماند.)', 'حذف', true))) return;
      await api(`/api/catalogs/${C.id}/rows/${rid}`, { method: 'DELETE' });
      okToast('حذف شد.'); layer.close(); CatalogDetail.refresh();
    }
  });
  box.addEventListener('change', async (ev) => {
    const f = ev.target.closest('[data-upload]');
    if (f && f.files[0]) {
      const file = f.files[0];
      const du = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(file); });
      await imgAction('upload', { slot: f.dataset.upload, data_url: du, name: file.name, rembg: box.querySelector('#rw-rembg')?.checked }, f.closest('label'));
    }
  });
  async function imgAction(action, body, el) {
    const lbl = { upload: 'بارگذاری…', url: 'دریافت…', generate: 'در حال ساخت تصویر…', reprocess: 'پردازش…' }[action];
    if (el && lbl) busy(el, true, lbl);
    try {
      const r = await api(`/api/catalogs/${C.id}/rows/${rid}/images/${action}`, { body });
      if (!r.ok) throw new Error(r.error);
      row = { ...row, ...r.row };
      drawImgs();
      CatalogDetail.load();
    } catch (e) { noProviderHint(e); if (el && lbl) busy(el, false); }
  }
  box.querySelector('[data-save]').addEventListener('click', async () => {
    try {
      const values = {};
      for (const c of cs) {
        const v = readCol(box.querySelector(`[data-col="${CSS.escape(c.key)}"]`), c);
        if (JSON.stringify(v ?? '') !== JSON.stringify(orig[c.key] ?? '')) values[c.key] = v;
      }
      const note = box.querySelector('[data-note]').value;
      if (!Object.keys(values).length && note === (row.note || '')) { toast('تغییری نبود.'); return; }
      await api(`/api/catalogs/${C.id}/rows/${rid}`, { method: 'PUT', body: { schema_id: C.sid, values, note } });
      okToast(`${fa(Object.keys(values).length)} فیلد ذخیره شد.`); layer.close(); CatalogDetail.refresh();
    } catch (e) { errToast(e); }
  });
}

function imagesHtml(row) {
  const u = row.image_urls || {};
  const t = encodeURIComponent(row.updated_at || Date.now());
  const g = row.images.gallery || [];
  const card = (src, slot, i, label) => `<div class="cimg"><div class="cimg-i checker">${src ? `<a href="${attr(src)}&t=${t}" target="_blank"><img src="${attr(src)}&t=${t}"></a>` : `<div class="muted small">${icon('image', 22)}</div>`}</div>
    <div class="xs muted ellipsis">${label}</div>
    <div class="flex" style="gap:2px;flex-wrap:wrap">${slot === 'gallery' ? `<button class="btn xs ghost" data-img="make_feature:gallery:${i}" title="تصویر شاخص شود">${icon('target', 12)}</button>
      ${i > 0 ? `<button class="btn xs ghost" data-img="move:gallery:${i}" data-to="${i - 1}" title="جلوتر">${icon('chevronRight', 12)}</button>` : ''}
      ${i < g.length - 1 ? `<button class="btn xs ghost" data-img="move:gallery:${i}" data-to="${i + 1}" title="عقب‌تر">${icon('chevronLeft', 12)}</button>` : ''}` : ''}
      ${src ? `<button class="btn xs ghost" data-img="reprocess:${slot}:${i}" title="پردازش دوباره (حذف پس‌زمینه/ترازبندی) از نسخه‌ی خام">${icon('frame', 12)}</button>
      <button class="btn xs ghost danger" data-img="delete:${slot}:${i}" title="حذف">${icon('trash', 12)}</button>` : ''}</div></div>`;
  return `<div class="sec-title">${icon('image', 16)} تصاویر نهایی <span class="line"></span><span class="xs muted">${row.images.feature ? '۱' : '۰'} شاخص + ${fa(g.length)} گالری</span></div>
    <div class="cimgs">${card(u.feature, 'feature', 0, 'feature (شاخص)')}${g.map((_, i) => card(u.gallery[i], 'gallery', i, `gallery_${i + 1}`)).join('')}</div>
    <div class="flex wrap mt12" style="gap:6px">
      <label class="btn sm soft">${icon('upload', 14)} بارگذاری به گالری<input type="file" accept="image/*" data-upload="gallery" hidden></label>
      <label class="btn sm">${icon('upload', 14)} جایگزینی شاخص<input type="file" accept="image/*" data-upload="feature" hidden></label>
      <button class="btn sm" data-img="url:gallery:0">${icon('link', 14)} از لینک</button>
      <button class="btn sm soft" data-img="generate:gallery:0">${icon('sparkles', 14)} ساخت تصویر با AI</button>
      <button class="btn sm ghost" data-img="generate:feature:0">${icon('sparkles', 14)} شاخص با AI</button>
      <button class="btn sm ghost" data-img="reprocess:all:0">${icon('frame', 14)} پردازش دوباره‌ی همه</button>
      <label class="check small"><input type="checkbox" id="rw-rembg" ${C.det.options.rembg === false ? '' : 'checked'}> حذف پس‌زمینه هنگام افزودن</label></div>
    <div class="hint mt8">تصاویر افزوده‌شده با قاعده‌ی ترازبندی همین خروجی آماده می‌شوند و نام‌ها خودکار به feature و gallery_1..N مرتب می‌شوند. نسخه‌ی خام هر تصویر با پسوند _raw کنارش می‌ماند و تصاویر حذف‌شده به پوشه‌ی _removed می‌روند.</div>`;
}
