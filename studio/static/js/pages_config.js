import {
  S, api, icon, esc, attr, fa, num, jdate, toast, okToast, errToast, openLayer, confirmDlg, emptyState,
  go, refreshBoot, sourceLogo, trunc, fieldLabel,
} from './core.js';
import { specsTable, decodeURIComponentSafe } from './pages_main.js';
import { assist, busy, noProviderHint } from './ai_assist.js';
import { defaultChip, defPreview, openDefaultEditor } from './defaults_ui.js';

// ======================================================================
// منابع
// ======================================================================
export const Sources = {
  title: 'منابع و اسکرپرها',
  crumb: 'تعریف، ویرایش و آزمایش ساختار هر منبع',
  top: () => `<a class="btn primary" href="#/sources/new">${icon('plus')} منبع جدید</a>`,
  async render() {
    const list = await api('/api/sources');
    return `
    <div class="alert info mb16">${icon('info')}<div><b>کالیبراسیون روی سیستم خودتان</b>ساختار سایت‌ها ممکن است تغییر کند. برای هر منبع، «آزمایش زنده» را با یک لینک دسته و یک لینک محصول اجرا کنید؛ کاوشگر داده همه‌ی داده‌های JSON، جدول‌ها و درخواست‌های شبکه‌ی صفحه را نشان می‌دهد تا هر فیلد را با یک کلیک به منبعش وصل کنید.</div></div>
    <div class="grid g3">${list.filter((s) => !s.config.virtual).map((s) => `
      <div class="card src-card">
        <div class="flex"><div class="src-logo">${sourceLogo(s.name)}</div><div class="grow"><b style="font-size:15px;color:var(--z-900)">${esc(s.name)}</b><div class="xs muted ltr" style="text-align:right">${esc((s.config.domains || []).join('، '))}</div></div></div>
        <div class="small muted" style="min-height:48px">${esc(trunc(s.config.notes || '', 150))}</div>
        <div class="flex wrap small"><span class="tag">فهرست: ${modeName(s.config.listing?.mode)}${s.config.listing?.pagination?.type && s.config.listing?.mode !== 'api' ? ' · ' + pagName(s.config.listing.pagination.type) : ''}</span><span class="tag">محصول: ${modeName(s.config.product?.mode)}</span><span class="tag">${fa((s.config.fields || []).length)} فیلد</span></div>
        <div class="kpi-line small"><span>بانک داده <b>${num(s.datasets)}</b></span><span>محصول <b>${num(s.products)}</b></span></div>
        <div class="btns"><a class="btn sm soft" href="#/sources/${s.id}">${icon('edit', 14)} ویرایش و آزمایش</a><button class="btn sm ghost" data-act="dup" data-id="${s.id}">${icon('copy', 14)} کپی</button>
          <button class="btn sm ghost" data-act="exp" data-id="${s.id}" title="برون‌ریزی JSON">${icon('download', 14)}</button>
          ${s.datasets ? '' : `<button class="btn sm ghost danger" data-act="del" data-id="${s.id}">${icon('trash', 14)}</button>`}</div>
      </div>`).join('')}
      <div class="card src-card" style="border-style:dashed;align-items:center;justify-content:center;text-align:center;box-shadow:none">
        <div class="em-ic" style="width:52px;height:52px;border-radius:16px;display:grid;place-items:center;background:var(--primary-50);color:var(--primary)">${icon('plus', 24)}</div>
        <b>افزودن منبع تازه</b><div class="small muted">از صفر یا با درون‌ریزی فایل JSON یک منبع</div>
        <div class="btns"><a class="btn sm primary" href="#/sources/new">${icon('plus', 14)} منبع جدید</a><button class="btn sm" data-act="imp">${icon('upload', 14)} درون‌ریزی</button></div>
      </div>
    </div>`;
  },
  act: {
    dup: async (el) => { const s = await api(`/api/sources/${el.dataset.id}/duplicate`, { body: {} }); okToast('کپی ساخته شد.'); go(`#/sources/${s.id}`); },
    del: async (el) => { if (!(await confirmDlg('حذف منبع', 'این منبع حذف شود؟', 'حذف', true))) return; await api(`/api/sources/${el.dataset.id}`, { method: 'DELETE' }); await refreshBoot(); go('#/sources'); location.reload(); },
    exp: async (el) => {
      const s = await api(`/api/sources/${el.dataset.id}`);
      const blob = new Blob([JSON.stringify(s.config, null, 2)], { type: 'application/json' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `source-${s.key}.json`; a.click();
    },
    imp: () => {
      const l = openLayer('modal', `<div class="card-h"><h3>درون‌ریزی منبع</h3></div><div class="card-b"><textarea class="inp mono" rows="12" id="imp" placeholder='{"key": "...", "name": "...", ...}'></textarea></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="imp-ok">درون‌ریزی</button></div>`, { wide: true });
      l.box.querySelector('#imp-ok').addEventListener('click', async () => {
        try { const cfg = JSON.parse(l.box.querySelector('#imp').value); const s = await api('/api/sources', { body: { config: cfg } }); l.close(); okToast('منبع افزوده شد.'); go(`#/sources/${s.id}`); }
        catch (e) { errToast(e); }
      });
    },
  },
};

const modeName = (m) => ({ api: 'API', browser: 'مرورگر', http: 'HTTP' }[m] || m || '—');
const pagName = (p) => ({ scroll: 'اسکرول', param: 'پارامتر صفحه', click: 'دکمه‌ی بیشتر', none: 'تک‌صفحه' }[p] || p);

// ======================================================================
// ویرایشگر منبع
// ======================================================================
const SE = { id: null, cfg: null, tab: 'general', lt: null, pt: null, filter: '', busy: false };

const BLANK = {
  key: '', name: '', domains: [], notes: '', sample_category_url: '', sample_product_url: '', product_id_pattern: '',
  listing: { mode: 'browser', link_pattern: '/product/', pagination: { type: 'scroll', param: 'page', start: 1, idle_rounds: 4, pause_ms: 1400, max_rounds: 400 } },
  product: { mode: 'browser', capture_xhr: ['*'], auto_expand: true, scroll: true, scroll_times: 5 },
  request: { headers: {}, timeout_s: 45 }, max_gallery: 12, fields: [],
};

const STRAT_TYPES = {
  auto: 'حدس هوشمند', jsonld: 'JSON-LD', state: 'داده‌ی صفحه (Next/Nuxt)', xhr: 'درخواست شبکه (XHR)', api: 'پاسخ API',
  css: 'انتخابگر CSS', meta: 'متا تگ', spec: 'از جدول مشخصات', regex: 'عبارت باقاعده', const: 'مقدار ثابت', ai: 'هوش مصنوعی',
};

function getPath(o, p) { return p.split('.').reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, p, v) {
  const ks = p.split('.'); let cur = o;
  ks.slice(0, -1).forEach((k) => { if (cur[k] == null || typeof cur[k] !== 'object') cur[k] = {}; cur = cur[k]; });
  cur[ks[ks.length - 1]] = v;
}

export const SourceEditor = {
  title: 'ویرایش منبع',
  crumb: 'منابع و اسکرپرها',
  top: () => `<a class="btn ghost" href="#/sources">${icon('chevronRight', 16)} بازگشت</a><button class="btn primary" data-act="save">${icon('save', 16)} ذخیره‌ی منبع</button>`,
  async render(p) {
    await refreshBoot();
    SE.id = p.id === 'new' ? null : Number(p.id);
    SE.cfg = SE.id ? structuredClone((await api(`/api/sources/${SE.id}`)).config) : structuredClone(BLANK);
    SE.tab = SE.id ? 'test' : 'general'; SE.lt = null; SE.pt = null; SE.filter = '';
    document.getElementById('page-title').textContent = SE.id ? `منبع: ${SE.cfg.name}` : 'منبع جدید';
    return `<div class="card"><div class="tabs" id="se-tabs"></div><div id="se-body"></div></div>`;
  },
  mount() { this.draw(); },
  draw() {
    const t = [['test', 'flask', 'آزمایش زنده'], ['general', 'info', 'عمومی'], ['listing', 'list', 'صفحه‌ی دسته‌بندی'], ['product', 'box', 'صفحه‌ی محصول'], ['fields', 'columns', 'فیلدها'], ['json', 'code', 'JSON خام']];
    document.getElementById('se-tabs').innerHTML = t.map(([k, ic, l]) => `<button class="${SE.tab === k ? 'on' : ''}" data-act="tab" data-t="${k}">${icon(ic, 16)} ${l}</button>`).join('');
    const b = document.getElementById('se-body');
    b.innerHTML = ({ general: genTab, listing: listTab, product: prodTab, fields: fieldsTab, json: jsonTab, test: testTab })[SE.tab]();
  },
  act: {
    tab: (el) => { if (SE.tab === 'json' && !applyJson()) return; SE.tab = el.dataset.t; SourceEditor.draw(); },
    save: async () => {
      if (SE.tab === 'json' && !applyJson()) return;
      if (!SE.cfg.name) { toast('نام منبع را وارد کنید.', 'err'); SE.tab = 'general'; SourceEditor.draw(); return; }
      const s = SE.id ? await api(`/api/sources/${SE.id}`, { method: 'PUT', body: { config: SE.cfg } }) : await api('/api/sources', { body: { config: SE.cfg } });
      SE.cfg = s.config;
      await refreshBoot();
      okToast('منبع ذخیره شد.');
      if (!SE.id) { SE.id = s.id; history.replaceState(null, '', `#/sources/${s.id}`); }
    },
    addfield: () => {
      const key = prompt('کلید فیلد جدید (انگلیسی، مثل warranty):');
      if (!key) return;
      SE.cfg.fields = SE.cfg.fields || [];
      SE.cfg.fields.push({ key: key.trim(), label: key.trim(), type: 'text', strategies: [{ type: 'auto' }] });
      SourceEditor.draw();
    },
    addcanon: (el) => {
      SE.cfg.fields = SE.cfg.fields || [];
      SE.cfg.fields.push({ key: el.dataset.k, strategies: [{ type: 'auto' }] });
      SourceEditor.draw();
    },
    delfield: (el) => { SE.cfg.fields.splice(Number(el.dataset.i), 1); SourceEditor.draw(); },
    addaistrat: (el) => { const f = SE.cfg.fields[Number(el.dataset.i)]; f.strategies = f.strategies || []; f.strategies.push({ type: 'ai', mode: 'extract', instruction: '' }); SourceEditor.draw(); },
    addstrat: (el) => { const f = SE.cfg.fields[Number(el.dataset.i)]; f.strategies = f.strategies || []; f.strategies.push({ type: 'css', selector: '', attr: 'text' }); SourceEditor.draw(); },
    delstrat: (el) => { SE.cfg.fields[Number(el.dataset.i)].strategies.splice(Number(el.dataset.j), 1); SourceEditor.draw(); },
    upstrat: (el) => { const s = SE.cfg.fields[Number(el.dataset.i)].strategies; const j = Number(el.dataset.j); if (j > 0) { [s[j - 1], s[j]] = [s[j], s[j - 1]]; SourceEditor.draw(); } },
    addaction: (el) => { const k = el.dataset.k; const o = getPath(SE.cfg, k) || []; o.push({ type: 'click_text', texts: ['مشاهده بیشتر'], optional: true }); setPath(SE.cfg, k, o); SourceEditor.draw(); },
    delaction: (el) => { const o = getPath(SE.cfg, el.dataset.k); o.splice(Number(el.dataset.i), 1); SourceEditor.draw(); },
    testlist: async (el) => {
      const url = document.getElementById('t-cat').value.trim();
      SE.cfg.sample_category_url = url;
      el.disabled = true; SE.lt = { loading: true }; drawTestResults();
      try { SE.lt = await api(`/api/sources/${SE.id || 0}/test-listing`, { body: { url, config: SE.cfg, max_links: 60 } }); }
      catch (e) { SE.lt = { ok: false, error: e.message }; }
      el.disabled = false; drawTestResults();
    },
    testprod: async (el) => {
      const url = document.getElementById('t-prod').value.trim();
      SE.cfg.sample_product_url = url;
      el.disabled = true; SE.pt = { loading: true }; drawTestResults();
      try { SE.pt = await api(`/api/sources/${SE.id || 0}/test-product`, { body: { url, config: SE.cfg, show_browser: document.getElementById('t-show').checked } }); }
      catch (e) { SE.pt = { ok: false, error: e.message }; }
      el.disabled = false; drawTestResults();
    },
    use: (el) => useLeaf(el),
    aifields: async (el) => {
      busy(el, true, 'در حال تحلیل داده‌ها…');
      try {
        const r = await assist('source_fields', { explorer: SE.pt.explorer, record: SE.pt.record });
        SE.aiFields = r.fields;
        const box = document.getElementById('ai-fields');
        if (!r.fields.length) { box.innerHTML = '<div class="card-b muted small">پیشنهادی پیدا نشد.</div>'; return; }
        box.innerHTML = `<div class="card-b"><div class="ai-inline">
          <div class="flex mb8"><b class="grow">${icon('sparkles', 15)} راهبردهای پیشنهادی هوش مصنوعی</b><button class="btn sm primary" data-act="aifieldsapply">${icon('check', 14)} افزودن موارد انتخاب‌شده</button></div>
          ${r.fields.map((f, i) => `<label class="check small" style="display:flex;align-items:flex-start;gap:8px;padding:4px 0"><input type="checkbox" data-aif="${i}" checked>
            <span><b>${esc(fieldLabel(f.key))}</b> <span class="xs muted">(${esc(f.key)})</span><div class="ltr xs" style="text-align:left">${f.strategies.map((x) => esc(JSON.stringify(x))).join('<br>')}</div></span></label>`).join('')}
          <div class="hint">راهبردها در اولویت اول هر فیلد قرار می‌گیرند. پس از افزودن، آزمایش را دوباره اجرا کنید و نتیجه را بسنجید.</div></div></div>`;
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    aifieldsapply: () => {
      SE.cfg.fields = SE.cfg.fields || [];
      let n = 0;
      document.querySelectorAll('[data-aif]').forEach((c) => {
        if (!c.checked) return;
        const f = SE.aiFields[Number(c.dataset.aif)];
        let t = SE.cfg.fields.find((x) => x.key === f.key);
        if (!t) { t = { key: f.key, strategies: [] }; SE.cfg.fields.push(t); }
        t.strategies = [...f.strategies, ...(t.strategies || [])];
        n++;
      });
      document.getElementById('ai-fields').innerHTML = '';
      okToast(`${fa(n)} فیلد به‌روز شد. آزمایش را دوباره اجرا و سپس ذخیره کنید.`);
    },
    useurl: (el) => { document.getElementById('t-prod').value = el.dataset.u; toast('لینک در «آزمایش صفحه‌ی محصول» قرار گرفت.'); },
  },
  input: {
    cfg: (el) => bindCfg(el),
    filter: (el) => { SE.filter = el.value.trim().toLowerCase(); const ex = document.getElementById('explorer'); if (ex) ex.innerHTML = explorerHtml(); },
  },
  change: { cfg: (el) => { bindCfg(el); if (el.dataset.redraw) SourceEditor.draw(); } },
};

function bindCfg(el) {
  const p = el.dataset.path;
  let v;
  if (el.type === 'checkbox') v = el.checked;
  else if (el.type === 'number') v = el.value === '' ? undefined : Number(el.value);
  else if (el.dataset.kind === 'list') v = el.value.split(/[\n,،]/).map((x) => x.trim()).filter(Boolean);
  else if (el.dataset.kind === 'json') {
    try { v = el.value.trim() ? JSON.parse(el.value) : undefined; el.style.borderColor = ''; } catch (e) { el.style.borderColor = 'var(--err)'; return; }
  } else v = el.value;
  setPath(SE.cfg, p, v);
}

function applyJson() {
  const t = document.getElementById('se-json');
  if (!t) return true;
  try { SE.cfg = JSON.parse(t.value); return true; } catch (e) { toast('JSON معتبر نیست: ' + e.message, 'err'); return false; }
}

function inp(path, label, opts = {}) {
  const v = getPath(SE.cfg, path);
  const cls = `inp ${opts.ltr ? 'ltr' : ''} ${opts.mono ? 'mono' : ''}`;
  let ctl;
  if (opts.options) ctl = `<select class="inp" data-change="cfg" data-path="${path}" ${opts.redraw ? 'data-redraw="1"' : ''}>${opts.options.map(([k, l]) => `<option value="${k}" ${String(v) === String(k) ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  else if (opts.check) return `<label class="check"><input type="checkbox" data-change="cfg" data-path="${path}" ${v ? 'checked' : ''}> ${label}</label>`;
  else if (opts.area) ctl = `<textarea class="${cls}" rows="${opts.rows || 3}" data-input="cfg" data-path="${path}" ${opts.kind ? `data-kind="${opts.kind}"` : ''}>${esc(opts.kind === 'list' ? (v || []).join('\n') : opts.kind === 'json' ? (v === undefined ? '' : JSON.stringify(v, null, 2)) : (v ?? ''))}</textarea>`;
  else ctl = `<input class="${cls}" ${opts.type ? `type="${opts.type}"` : ''} data-input="cfg" data-path="${path}" ${opts.kind ? `data-kind="${opts.kind}"` : ''} value="${attr(opts.kind === 'list' ? (v || []).join(', ') : (v ?? ''))}" placeholder="${attr(opts.ph || '')}">`;
  return `<div class="field ${opts.full ? 'full' : ''}"><label>${label}</label>${ctl}${opts.hint ? `<div class="hint">${opts.hint}</div>` : ''}</div>`;
}

function genTab() {
  return `<div class="card-b"><div class="form-grid">
    ${inp('name', 'نام منبع', { ph: 'مثلاً دیجی‌کالا' })}
    ${inp('key', 'کلید انگلیسی (در نام فایل‌ها)', { ltr: true, ph: 'digikala' })}
    ${inp('domains', 'دامنه‌ها', { ltr: true, kind: 'list', ph: 'digikala.com', hint: 'برای تشخیص خودکار منبع از روی لینک. با ویرگول جدا کنید.' })}
    ${inp('product_id_pattern', 'الگوی شناسه‌ی محصول در لینک (Regex)', { ltr: true, mono: true, ph: 'dkp-(\\d+)', hint: 'گروه اول، شناسه‌ی یکتای محصول است و برای جلوگیری از تکرار استفاده می‌شود.' })}
    ${inp('sample_category_url', 'لینک دسته‌بندی نمونه', { ltr: true, full: true })}
    ${inp('sample_product_url', 'لینک محصول نمونه', { ltr: true, full: true })}
    ${inp('max_gallery', 'بیشترین تعداد تصویر گالری', { type: 'number' })}
    ${inp('request.timeout_s', 'مهلت بارگذاری (ثانیه)', { type: 'number' })}
    ${inp('request.delay_min_ms', 'کمترین مکث بین درخواست‌ها (ms)', { type: 'number', hint: 'خالی = از تنظیمات کلی' })}
    ${inp('request.delay_max_ms', 'بیشترین مکث بین درخواست‌ها (ms)', { type: 'number' })}
    ${inp('request.headers', 'هدرهای HTTP اضافه (JSON)', { area: true, kind: 'json', mono: true, full: true, rows: 4 })}
    ${inp('notes', 'یادداشت', { area: true, full: true })}
  </div></div>`;
}

function actionsEditor(key) {
  const acts = getPath(SE.cfg, key) || [];
  return `<div class="field full"><label>عملیات روی صفحه (به‌ترتیب)</label>
    ${acts.map((a, i) => `<div class="strat" style="grid-template-columns:28px 150px 1fr auto"><span class="n">${fa(i + 1)}</span>
      <select class="inp sm" data-change="cfg" data-path="${key}.${i}.type" data-redraw="1">${[['click_text', 'کلیک روی متن'], ['click', 'کلیک روی انتخابگر'], ['wait', 'صبر برای انتخابگر'], ['wait_ms', 'مکث (ms)'], ['scroll', 'اسکرول'], ['hover', 'نگه‌داشتن ماوس']].map(([k, l]) => `<option value="${k}" ${a.type === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <div class="params">${a.type === 'click_text' ? `<input class="inp sm" data-input="cfg" data-kind="list" data-path="${key}.${i}.texts" value="${attr((a.texts || []).join('، '))}" placeholder="مشاهده بیشتر، نمایش همه">`
        : a.type === 'wait_ms' ? `<input class="inp sm" type="number" data-input="cfg" data-path="${key}.${i}.ms" value="${attr(a.ms ?? 1000)}">`
        : a.type === 'scroll' ? `<input class="inp sm" type="number" data-input="cfg" data-path="${key}.${i}.times" value="${attr(a.times ?? 6)}" placeholder="تعداد">`
        : `<input class="inp sm mono" data-input="cfg" data-path="${key}.${i}.selector" value="${attr(a.selector || '')}" placeholder="CSS selector">${a.type === 'click' ? `<label class="check xs"><input type="checkbox" data-change="cfg" data-path="${key}.${i}.all" ${a.all ? 'checked' : ''}> همه</label>` : ''}`}</div>
      <button class="btn xs ghost danger" data-act="delaction" data-k="${key}" data-i="${i}">${icon('x', 13)}</button></div>`).join('')}
    <div><button class="btn sm ghost" data-act="addaction" data-k="${key}">${icon('plus', 14)} افزودن عملیات</button></div>
    <div class="hint">مثلاً کلیک روی «نمایش مشخصات کامل» یا صبر تا ظاهر شدن جدول مشخصات.</div></div>`;
}

function listTab() {
  const mode = SE.cfg.listing?.mode;
  const pt = SE.cfg.listing?.pagination?.type;
  return `<div class="card-b"><div class="form-grid">
    ${inp('listing.mode', 'روش خواندن فهرست محصولات', { options: [['browser', 'مرورگر (صفحات پویا)'], ['http', 'HTTP ساده (صفحات ایستا)'], ['api', 'API منبع (JSON)']], redraw: true })}
    ${inp('listing.link_pattern', 'الگوی لینک محصول (Regex)', { ltr: true, mono: true, ph: '/product/dkp-\\d+', hint: 'فقط لینک‌هایی که با این الگو جور باشند، محصول حساب می‌شوند.' })}
    ${mode === 'api' ? `
      ${inp('listing.api.url', 'آدرس API (با {page} و پارامترهای دیگر)', { ltr: true, mono: true, full: true })}
      ${inp('listing.api.params_from_url', 'پارامترها از لینک دسته (JSON: نام → Regex)', { area: true, kind: 'json', mono: true, rows: 3 })}
      ${inp('listing.api.item_fields', 'فیلدهای هر آیتم (JSON: نام → مسیر)', { area: true, kind: 'json', mono: true, rows: 3 })}
      ${inp('listing.api.items_path', 'مسیر آرایه‌ی محصولات', { ltr: true, mono: true })}
      ${inp('listing.api.url_template', 'الگوی لینک محصول', { ltr: true, mono: true })}
      ${inp('listing.api.total_pages_path', 'مسیر تعداد کل صفحات', { ltr: true, mono: true })}
      ${inp('listing.api.total_items_path', 'مسیر تعداد کل محصولات', { ltr: true, mono: true })}
      ${inp('listing.api.category_label_path', 'مسیر عنوان دسته', { ltr: true, mono: true })}
      ${inp('listing.api.start_page', 'شماره‌ی صفحه‌ی اول', { type: 'number' })}` : `
      ${inp('listing.pagination.type', 'صفحه‌بندی', { options: [['scroll', 'اسکرول بی‌پایان'], ['param', 'پارامتر صفحه در لینک (?page=2)'], ['click', 'دکمه‌ی «نمایش بیشتر»'], ['none', 'تک‌صفحه']], redraw: true })}
      ${pt === 'param' ? `${inp('listing.pagination.param', 'نام پارامتر صفحه', { ltr: true, ph: 'page' })}${inp('listing.pagination.start', 'شماره‌ی صفحه‌ی اول', { type: 'number' })}${inp('listing.pagination.max_pages', 'بیشترین تعداد صفحه', { type: 'number' })}` : ''}
      ${pt === 'click' ? `${inp('listing.pagination.click_selector', 'انتخابگر دکمه‌ی «بیشتر» (اختیاری)', { ltr: true, mono: true, hint: 'اگر خالی باشد، دکمه‌ای با متن «نمایش بیشتر/مشاهده بیشتر» جست‌وجو می‌شود.' })}` : ''}
      ${pt === 'scroll' || pt === 'click' ? `${inp('listing.pagination.idle_rounds', 'توقف پس از چند دور بدون محصول جدید', { type: 'number' })}${inp('listing.pagination.pause_ms', 'مکث هر دور (ms)', { type: 'number' })}${inp('listing.pagination.max_rounds', 'بیشترین دور', { type: 'number' })}` : ''}
      ${inp('listing.wait_selector', 'صبر برای انتخابگر (اختیاری)', { ltr: true, mono: true })}
      ${inp('listing.keep_query_params', 'پارامترهای لینک محصول که حفظ شوند', { ltr: true, kind: 'list', hint: 'به‌طور پیش‌فرض پارامترهای لینک محصول حذف می‌شوند.' })}
      ${actionsEditor('listing.actions')}`}
  </div></div>`;
}

function prodTab() {
  const mode = SE.cfg.product?.mode;
  return `<div class="card-b"><div class="form-grid">
    ${inp('product.mode', 'روش خواندن صفحه‌ی محصول', { options: [['browser', 'مرورگر (صفحات پویا)'], ['http', 'HTTP ساده'], ['api', 'API منبع (JSON)']], redraw: true })}
    ${inp('product.fallback_mode', 'روش جایگزین در صورت خطا', { options: [['', 'ندارد'], ['browser', 'مرورگر'], ['http', 'HTTP ساده']] })}
    ${mode === 'api' ? `${inp('product.api.url', 'آدرس API محصول (با {id})', { ltr: true, mono: true, full: true })}${inp('product.api.params_from_url', 'پارامترها از لینک محصول (JSON)', { area: true, kind: 'json', mono: true, rows: 3, full: true })}` : `
      ${inp('product.wait_selector', 'صبر برای انتخابگر بخش اصلی', { ltr: true, mono: true, hint: 'اگر این بخش ظاهر نشود، خطای «بارگذاری ناقص» ثبت می‌شود.' })}
      ${inp('product.capture_xhr', 'ضبط درخواست‌های شبکه (الگوها)', { ltr: true, kind: 'list', hint: '* یعنی همه‌ی پاسخ‌های JSON؛ برای کارایی بهتر بخشی از آدرس API را بنویسید.' })}
      ${inp('product.scroll_times', 'تعداد اسکرول برای بارگذاری تنبل', { type: 'number' })}
      <div class="field">${inp('product.auto_expand', 'کلیک خودکار روی «مشاهده بیشتر»، «مشخصات کامل» و موارد مشابه', { check: true })}${inp('product.scroll', 'اسکرول صفحه پیش از استخراج', { check: true })}</div>
      ${inp('product.expand_texts', 'متن دکمه‌های گسترش (اختیاری)', { kind: 'list', full: true, ph: 'مشاهده بیشتر، نمایش همه، مشخصات کامل' })}
      ${actionsEditor('product.actions')}`}
    <div class="field full"><div class="ai-inline">
      <div class="flex wrap" style="gap:10px"><span style="color:var(--primary)">${icon('sparkles', 18)}</span><b class="grow">پشتیبان هوش مصنوعی برای فیلدهای خالی</b>
        ${inp('product.ai_fallback.enabled', 'فعال', { check: true })}</div>
      <div class="hint mt8">اگر پس از همه‌ی راهبردها فیلدی خالی ماند، هوش مصنوعی آن را از متن صفحه (و فهرست تصاویر صفحه) استخراج می‌کند. همه‌ی فیلدهای خالی یک محصول در یک درخواست فرستاده می‌شوند. از اتصال پیش‌فرض دستیار استفاده می‌شود.</div>
      <div class="form-grid mt12">
        ${inp('product.ai_fallback.mode', 'رفتار', { options: [['extract', 'فقط استخراج از صفحه (اگر نبود خالی بماند)'], ['generate', 'استخراج، و اگر نبود تولید']] })}
        ${inp('product.ai_fallback.fields', 'فیلدها', { ltr: true, kind: 'list', ph: 'title, brand, category, short_description, long_description, specifications, featured_image, gallery', hint: 'خالی = عنوان، برند، دسته، توضیحات، مشخصات و تصاویر. کلیدهای فیلدهای سفارشی هم مجازند.' })}
      </div></div></div>
    ${inp('dimension_code_map', 'نگاشت ویژگی‌ها به dimension_codes (JSON)', { area: true, kind: 'json', mono: true, rows: 4, full: true, hint: 'مثلاً {"حجم": "volume", "ویسکوزیته": "viscosity"} — مقدار این ویژگی‌ها از جدول مشخصات در متغیرهای محصول قرار می‌گیرد.' })}
  </div></div>`;
}

function stratParams(s, i, j) {
  const p = (name, ph, cls = 'mono') => `<input class="inp sm ${cls}" data-input="cfg" data-path="fields.${i}.strategies.${j}.${name}" value="${attr(s[name] ?? '')}" placeholder="${attr(ph)}">`;
  switch (s.type) {
    case 'api': return p('path', 'data.product.title_fa');
    case 'xhr': return p('match', 'بخشی از آدرس، مثل /v2/product') + p('path', 'data.product.title_fa');
    case 'jsonld': return p('at_type', 'Product') + p('path', 'name');
    case 'state': return p('name', '__NEXT_DATA__') + p('path', 'props.pageProps…');
    case 'css': return p('selector', 'h1, .product-title') + `<select class="inp sm" style="max-width:120px" data-change="cfg" data-path="fields.${i}.strategies.${j}.attr">${['text', 'html', 'src', 'href', 'content', 'data-src'].map((a) => `<option ${s.attr === a ? 'selected' : ''}>${a}</option>`).join('')}</select><label class="check xs"><input type="checkbox" data-change="cfg" data-path="fields.${i}.strategies.${j}.all" ${s.all ? 'checked' : ''}> همه</label>`;
    case 'meta': return p('name', 'og:image');
    case 'spec': return `<input class="inp sm" data-input="cfg" data-kind="list" data-path="fields.${i}.strategies.${j}.names" value="${attr((s.names || []).join('، '))}" placeholder="برند، نام تجاری">`;
    case 'regex': return `<select class="inp sm" style="max-width:100px" data-change="cfg" data-path="fields.${i}.strategies.${j}.target">${['html', 'text', 'url'].map((a) => `<option ${s.target === a ? 'selected' : ''}>${a}</option>`).join('')}</select>` + p('pattern', '"sku":"(\\w+)"');
    case 'const': return p('value', 'مقدار', '');
    case 'ai': return `<select class="inp sm" style="max-width:150px" data-change="cfg" data-path="fields.${i}.strategies.${j}.mode">${[['extract', 'فقط استخراج'], ['generate', 'استخراج، وگرنه تولید']].map(([k, l]) => `<option value="${k}" ${(s.mode || 'extract') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`
      + `<input class="inp sm" data-input="cfg" data-path="fields.${i}.strategies.${j}.instruction" value="${attr(s.instruction || '')}" placeholder="دستور اختیاری — مثلاً: نام برند را فقط به فارسی بنویس" data-ai-label="دستور استخراج هوش مصنوعی">`;
    default: return '<span class="xs muted">JSON-LD، تیتر صفحه، جدول‌ها و گالری به‌طور خودکار بررسی می‌شوند.</span>';
  }
}

function fieldsTab() {
  const fields = SE.cfg.fields || [];
  const present = new Set(fields.map((f) => f.key));
  const missingCanon = (S.boot.canonical_fields || []).filter((f) => !f.custom && !present.has(f.key));
  return `<div class="card-b">
    <div class="alert p mb16">${icon('info')}<div>هر فیلد چند «راهبرد» دارد که به‌ترتیب امتحان می‌شوند؛ اولین راهبردی که مقدار برگرداند استفاده می‌شود. فیلدهای استانداردی که این‌جا تعریف نشوند، با «حدس هوشمند» پر می‌شوند. ساده‌ترین راه: در «آزمایش زنده» روی مقدار درست در کاوشگر داده کلیک کنید.</div></div>
    ${fields.map((f, i) => `
      <div class="fieldbox">
        <div class="fh"><b>${esc(fieldLabel(f.key) || f.label || f.key)}</b><span class="tag ltr">${esc(f.key)}</span><span class="grow"></span>
          <select class="inp sm" style="width:140px" data-change="cfg" data-path="fields.${i}.type" title="نوع مقدار">${[['', 'نوع پیش‌فرض'], ['text', 'متن'], ['list', 'فهرست'], ['number', 'عدد'], ['image', 'تصویر'], ['images', 'چند تصویر'], ['specs', 'مشخصات'], ['json', 'JSON']].map(([k, l]) => `<option value="${k}" ${(f.type || '') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <button class="btn xs ghost danger" data-act="delfield" data-i="${i}" title="حذف فیلد">${icon('trash', 13)}</button></div>
        ${(f.strategies || []).map((s, j) => `<div class="strat"><span class="n">${fa(j + 1)}</span>
          <select class="inp sm" data-change="cfg" data-path="fields.${i}.strategies.${j}.type" data-redraw="1">${Object.entries(STRAT_TYPES).map(([k, l]) => `<option value="${k}" ${s.type === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <div class="params">${stratParams(s, i, j)}</div>
          <div class="btns" style="gap:2px">${j ? `<button class="btn xs ghost" data-act="upstrat" data-i="${i}" data-j="${j}" title="اولویت بالاتر">${icon('arrowUp', 13)}</button>` : ''}<button class="btn xs ghost danger" data-act="delstrat" data-i="${i}" data-j="${j}">${icon('x', 13)}</button></div></div>`).join('')}
        <div class="flex mt8"><button class="btn xs ghost" data-act="addstrat" data-i="${i}">${icon('plus', 13)} راهبرد</button>
          ${(f.strategies || []).some((x) => x.type === 'ai') ? '' : `<button class="btn xs soft" data-act="addaistrat" data-i="${i}" title="اگر راهبردهای دیگر چیزی پیدا نکردند، هوش مصنوعی از متن صفحه استخراج کند">${icon('sparkles', 12)} راهبرد هوش مصنوعی</button>`}<span class="grow"></span>
          <span class="xs muted">تبدیل‌ها:</span><input class="inp sm mono" style="max-width:360px" data-input="cfg" data-kind="json" data-path="fields.${i}.transforms" value="${attr(f.transforms ? JSON.stringify(f.transforms) : '')}" placeholder='["text", "strip_query", {"type":"join","sep":"\\n"}]'></div>
      </div>`).join('')}
    <div class="flex wrap mt16"><button class="btn sm soft" data-act="addfield">${icon('plus', 14)} فیلد سفارشی</button>
      ${missingCanon.map((f) => `<button class="btn xs" data-act="addcanon" data-k="${f.key}">${icon('plus', 12)} ${esc(f.label)}</button>`).join('')}</div>
    <details class="mt16"><summary class="small muted" style="cursor:pointer">راهنمای تبدیل‌ها (Transforms)</summary><div class="small mt8" style="line-height:2">
      <span class="kbd">text</span> تبدیل HTML به متن · <span class="kbd">first</span> فقط اولی · <span class="kbd">unique</span> حذف تکراری · <span class="kbd">strip_query</span> حذف پارامترهای لینک (تصویر با کیفیت اصلی) ·
      <span class="kbd">{"type":"join","sep":"\\n"}</span> چسباندن · <span class="kbd">{"type":"split","sep":","}</span> شکستن · <span class="kbd">{"type":"replace","pattern":"…","repl":"…"}</span> جایگزینی ·
      <span class="kbd">number</span> عدد · <span class="kbd">{"type":"specs_groups","group":"title","items":"attributes","name":"title","value":"values"}</span> تبدیل گروه‌های مشخصات ·
      <span class="kbd">{"type":"specs_kv","name":"key","value":"value"}</span> مشخصات کلید/مقدار · <span class="kbd">flatten</span> صاف‌کردن آرایه‌ها · <span class="kbd">{"type":"limit","n":10}</span></div></details>
  </div>`;
}

function jsonTab() {
  return `<div class="card-b"><textarea class="inp mono" id="se-json" rows="34" spellcheck="false">${esc(JSON.stringify(SE.cfg, null, 2))}</textarea>
    <div class="hint mt8">ویرایش مستقیم پیکربندی. پس از تغییر، با رفتن به تب دیگر یا «ذخیره‌ی منبع» اعمال می‌شود.</div></div>`;
}

// ---------------- آزمایش زنده ----------------
function testTab() {
  return `<div class="card-b">
    <div class="grid g2">
      <div class="field"><label>۱. آزمایش صفحه‌ی دسته‌بندی</label>
        <div class="inp-group"><input class="inp ltr" id="t-cat" value="${attr(SE.cfg.sample_category_url || '')}" placeholder="لینک صفحه‌ی دسته‌بندی"><button class="btn soft" data-act="testlist">${icon('play', 16)} اجرا</button></div>
        <div class="hint">پیدا شدن لینک محصولات و صفحه‌بندی بررسی می‌شود.</div></div>
      <div class="field"><label>۲. آزمایش صفحه‌ی محصول</label>
        <div class="inp-group"><input class="inp ltr" id="t-prod" value="${attr(SE.cfg.sample_product_url || '')}" placeholder="لینک صفحه‌ی یک محصول"><button class="btn primary" data-act="testprod">${icon('flask', 16)} اجرا</button></div>
        <label class="check small mt8"><input type="checkbox" id="t-show"> نمایش مرورگر هنگام آزمایش</label></div>
    </div>
    <div class="hint mt8">آزمایش با پیکربندی فعلی همین صفحه انجام می‌شود (حتی اگر هنوز ذخیره نشده باشد).</div>
  </div>
  <div id="test-results"></div>`;
}

function drawTestResults() {
  const el = document.getElementById('test-results');
  if (!el) return;
  let h = '';
  const lt = SE.lt;
  if (lt) {
    h += `<div style="border-top:1px solid var(--z-100)"><div class="card-h"><h3>نتیجه‌ی صفحه‌ی دسته‌بندی</h3><span class="sp"></span>${lt.loading ? `<span class="small muted flex">${icon('loader', 16, 'spin')} در حال باز کردن صفحه…</span>` : lt.ok ? `<span class="chip ok">${fa(lt.count)} لینک محصول</span>` : '<span class="chip err">ناموفق</span>'}</div>`;
    if (!lt.loading) {
      if (!lt.ok) h += `<div class="card-b"><div class="alert err">${icon('alert')}<div><b>${esc(lt.error)}</b><pre class="xs ltr" style="white-space:pre-wrap;margin:6px 0 0">${esc(lt.detail || '')}</pre></div></div></div>`;
      else {
        h += `<div class="card-b">${lt.info && (lt.info.h1 || lt.info.category_label || lt.info.total_items) ? `<div class="kpi-line mb12">${lt.info.h1 ? `<span>عنوان صفحه <b>${esc(lt.info.h1)}</b></span>` : ''}${lt.info.category_label ? `<span>دسته <b>${esc(lt.info.category_label)}</b></span>` : ''}${lt.info.total_items ? `<span>کل محصولات <b>${num(lt.info.total_items)}</b></span>` : ''}${lt.info.total_pages ? `<span>کل صفحات <b>${num(lt.info.total_pages)}</b></span>` : ''}</div>` : ''}
          ${lt.count ? `<div style="max-height:240px;overflow:auto;border:1px solid var(--z-200);border-radius:14px">${lt.links.map((u, i) => `<div class="leaf" style="grid-template-columns:30px 1fr auto"><span class="xs muted">${fa(i + 1)}</span><span class="p">${esc(decodeURIComponentSafe(u))}</span><button class="btn xs ghost" data-act="useurl" data-u="${attr(u)}" title="آزمایش این محصول">${icon('flask', 13)}</button></div>`).join('')}</div>`
            : `<div class="alert warn">${icon('alert')}<div>هیچ لینکی با «الگوی لینک محصول» جور نشد. الگو را در تب «صفحه‌ی دسته‌بندی» اصلاح کنید.</div></div>`}
          ${lt.next_page_url ? `<div class="hint mt8">صفحه‌ی بعد: <span class="kbd">${esc(decodeURIComponentSafe(lt.next_page_url))}</span></div>` : ''}</div>`;
      }
    }
    h += '</div>';
  }
  const pt = SE.pt;
  if (pt) {
    h += `<div style="border-top:1px solid var(--z-100)"><div class="card-h"><h3>نتیجه‌ی صفحه‌ی محصول</h3><span class="sp"></span>${pt.loading ? `<span class="small muted flex">${icon('loader', 16, 'spin')} در حال باز کردن و تحلیل صفحه…</span>` : pt.ok ? '<span class="chip ok">استخراج موفق</span>' : '<span class="chip err">ناموفق</span>'}</div>`;
    if (!pt.loading) {
      if (!pt.ok) h += `<div class="card-b p0" style="padding:0 20px 12px !important"><div class="alert err">${icon('alert')}<div><b>${esc(pt.error)}</b>${pt.detail ? `<pre class="xs ltr" style="white-space:pre-wrap;margin:6px 0 0;max-height:120px;overflow:auto">${esc(pt.detail)}</pre>` : ''}</div></div></div>`;
      h += `<div class="grid g2" style="padding:0 20px 20px;gap:20px;align-items:start">
        <div>${pt.record ? recordView(pt.record, pt.how || {}) : ''}</div>
        <div>${pt.screenshot ? `<div class="lbl mb8">نمای صفحه</div><img class="shot" src="${pt.screenshot}">` : ''}</div></div>`;
      if (pt.explorer) h += `<div style="border-top:1px solid var(--z-100)"><div class="card-h"><h3>کاوشگر داده‌ی صفحه</h3><span class="sub">برای اتصال هر مقدار به یک فیلد، روی «استفاده» بزنید</span><span class="sp"></span>
        <button class="btn sm soft" data-act="aifields">${icon('sparkles', 14)} پیشنهاد مسیر فیلدها با AI</button>
        <input class="inp sm" style="width:280px" placeholder="جست‌وجو در مسیر یا مقدار…" data-input="filter" value="${attr(SE.filter)}"></div><div id="ai-fields"></div><div id="explorer">${explorerHtml()}</div></div>`;
    }
    h += '</div>';
  }
  el.innerHTML = h;
}

function recordView(r, how) {
  const keys = ['title', 'title_en', 'brand', 'brand_en', 'category', 'breadcrumb', 'short_description', 'long_description', 'price', 'sku', 'dimension_codes', 'dimensions', 'variants'];
  const custom = Object.keys(r).filter((k) => !keys.includes(k) && !['specifications', 'featured_image', 'gallery', 'source_url'].includes(k));
  const row = (k) => {
    const v = r[k];
    const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length) || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
    const hw = how[k]?.strategy ? `<span class="tag ${how[k].type === 'ai' ? 'p' : ''}" style="font-size:10.5px">${how[k].strategy === 'fallback' ? 'پشتیبان' : 'راهبرد ' + fa(how[k].strategy)} · ${esc(STRAT_TYPES[how[k].type] || how[k].type)}</span>` : '';
    return `<div class="res-row"><div class="k">${esc(fieldLabel(k))}<small>${esc(k)}</small>${hw}</div><div class="res-val">${empty ? '<span class="muted">— خالی —</span>' : esc(typeof v === 'string' ? trunc(v, 900) : JSON.stringify(v, null, 1))}</div></div>`;
  };
  const imgs = [r.featured_image, ...(r.gallery || [])].filter(Boolean);
  const aiNote = how._ai ? `<div class="alert ${how._ai.error ? 'err' : 'info'} mb8">${icon('sparkles')}<div>${how._ai.error ? `<b>استخراج با هوش مصنوعی ناموفق بود</b>${esc(how._ai.error)}` : `هوش مصنوعی برای ${fa(how._ai.asked.length)} فیلد فراخوانده شد؛ در صفحه پیدا نشد: ${esc(how._ai.empty.join('، '))}`}</div></div>` : '';
  return `${aiNote}<div class="lbl mb8">داده‌ی استخراج‌شده</div>
    <div class="res-row"><div class="k">تصاویر<small>featured_image + gallery</small></div><div class="imgs">${imgs.slice(0, 12).map((u, i) => `<a href="${attr(u)}" target="_blank" title="${i ? 'gallery_' + i : 'feature'}"><img src="${attr(u)}" referrerpolicy="no-referrer"></a>`).join('') || '<span class="muted">— خالی —</span>'}</div></div>
    ${keys.map(row).join('')}${custom.map(row).join('')}
    <div class="lbl mt16 mb8">مشخصات (${fa((r.specifications || []).length)})</div>${specsTable(r.specifications || [])}`;
}

function explorerHtml() {
  const ex = SE.pt?.explorer;
  if (!ex) return '';
  const f = SE.filter;
  const match = (l) => !f || l.path.toLowerCase().includes(f) || String(l.value).toLowerCase().includes(f);
  let h = '';
  const fieldsOpts = (S.boot.canonical_fields || []).map((x) => `<option value="${x.key}">${esc(x.label)}</option>`).join('');
  const useBtn = (type, extra, path) => `<button class="btn xs soft" data-act="use" data-type="${type}" data-extra="${attr(JSON.stringify(extra))}" data-path="${attr(path)}">${icon('target', 12)} استفاده</button>`;
  for (const g of ex.groups) {
    const leaves = g.leaves.filter(match);
    if (!leaves.length) continue;
    const extra = g.type === 'xhr' ? { match: g.match } : g.type === 'state' ? { name: g.name } : g.type === 'jsonld' ? { at_type: g.at_type } : {};
    h += `<details ${f || ex.groups.length <= 3 ? 'open' : ''} style="border-bottom:1px solid var(--z-100)"><summary class="flex" style="padding:10px 20px;cursor:pointer"><b class="small">${esc(g.label)}</b><span class="tag">${fa(leaves.length)}</span></summary>
      <div style="max-height:360px;overflow:auto">${leaves.slice(0, 600).map((l) => `<div class="leaf"><span class="p">${esc(l.path)}</span><span class="v">${esc(l.value)}</span>${useBtn(g.type, extra, l.path)}</div>`).join('')}</div></details>`;
  }
  const metas = ex.meta.filter(match);
  if (metas.length) h += `<details style="border-bottom:1px solid var(--z-100)"><summary class="flex" style="padding:10px 20px;cursor:pointer"><b class="small">متا تگ‌ها</b><span class="tag">${fa(metas.length)}</span></summary>
    <div>${metas.map((l) => `<div class="leaf"><span class="p">${esc(l.path)}</span><span class="v">${esc(l.value)}</span>${useBtn('meta', { name: l.path }, '')}</div>`).join('')}</div></details>`;
  if (ex.auto_specs?.length) h += `<details style="border-bottom:1px solid var(--z-100)"><summary class="flex" style="padding:10px 20px;cursor:pointer"><b class="small">جدول‌های مشخصات شناسایی‌شده در HTML</b><span class="tag">${fa(ex.auto_specs.length)}</span></summary><div style="padding:10px 20px">${specsTable(ex.auto_specs)}</div></details>`;
  if (ex.auto_images?.length) h += `<details style="border-bottom:1px solid var(--z-100)"><summary class="flex" style="padding:10px 20px;cursor:pointer"><b class="small">تصاویر شناسایی‌شده در HTML</b><span class="tag">${fa(ex.auto_images.length)}</span></summary><div class="imgs" style="padding:10px 20px">${ex.auto_images.map((u) => `<a href="${attr(u)}" target="_blank"><img src="${attr(u)}" referrerpolicy="no-referrer"></a>`).join('')}</div></details>`;
  if (ex.headings?.length) h += `<details><summary class="flex" style="padding:10px 20px;cursor:pointer"><b class="small">تیترهای صفحه</b></summary><div>${ex.headings.map((x) => `<div class="leaf"><span class="p">${x.tag}</span><span class="v">${esc(x.text)}</span>${useBtn('css', { selector: x.tag, attr: 'text' }, '')}</div>`).join('')}</div></details>`;
  return h || '<div class="card-b muted small">داده‌ای مطابق جست‌وجو پیدا نشد.</div>';
}

function useLeaf(el) {
  const type = el.dataset.type;
  const extra = JSON.parse(el.dataset.extra || '{}');
  let path = el.dataset.path;
  const opts = (S.boot.canonical_fields || []).map((x) => `<option value="${x.key}">${esc(x.label)} (${x.key})</option>`).join('');
  const hasIdx = /\[\d+\]/.test(path);
  const l = openLayer('modal', `<div class="card-h"><h3>استفاده از این مقدار</h3></div><div class="card-b">
    <div class="pathbox mb12">${esc(type)} ${extra.match ? '· ' + esc(extra.match) : ''} ${esc(path || extra.name || extra.selector || '')}</div>
    <div class="field"><label>برای فیلد</label><select class="inp" id="u-f">${opts}</select></div>
    ${hasIdx ? `<div class="field mt12"><label>محدوده</label><select class="inp" id="u-scope"><option value="one">فقط همین مورد (${esc(path)})</option><option value="all">همه‌ی موارد مشابه (${esc(path.replace(/\[\d+\](?!.*\[\d+\])/, '[]'))})</option><option value="allall">همه‌ی اندیس‌ها (${esc(path.replace(/\[\d+\]/g, '[]'))})</option></select>
      <div class="hint">برای گالری تصاویر یا فهرست مشخصات «همه‌ی موارد» را انتخاب کنید.</div></div>` : ''}
    <div class="hint mt12">این راهبرد در اولویت اول فیلد قرار می‌گیرد. برای دیدن نتیجه، آزمایش را دوباره اجرا کنید.</div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="u-ok">افزودن</button></div>`);
  l.box.querySelector('#u-ok').addEventListener('click', () => {
    const key = l.box.querySelector('#u-f').value;
    const sc = l.box.querySelector('#u-scope')?.value;
    if (sc === 'all') path = path.replace(/\[\d+\](?!.*\[\d+\])/, '[]');
    if (sc === 'allall') path = path.replace(/\[\d+\]/g, '[]');
    const st = { type, ...extra };
    if (path) st.path = path;
    SE.cfg.fields = SE.cfg.fields || [];
    let f = SE.cfg.fields.find((x) => x.key === key);
    if (!f) { f = { key, strategies: [] }; SE.cfg.fields.push(f); }
    f.strategies = f.strategies || [];
    f.strategies.unshift(st);
    if (['featured_image', 'gallery'].includes(key) && !(f.transforms || []).includes('strip_query') && /\?/.test(String(el.closest('.leaf')?.querySelector('.v')?.textContent || ''))) {
      // پیشنهاد حذف پارامتر اندازه از لینک تصویر
      f.transforms = [...(f.transforms || []), 'strip_query'];
    }
    l.close();
    okToast(`راهبرد به فیلد «${fieldLabel(key)}» افزوده شد. ذخیره را فراموش نکنید.`);
  });
}

// ======================================================================
// اسکیماها
// ======================================================================
export const Schemas = {
  title: 'اسکیماهای داده',
  crumb: 'ساختار ستون‌های خروجی: استخراجی، دستی، ثابت، نگاشت و خودکار',
  top: () => `<button class="btn soft" data-act="aischema">${icon('sparkles')} ساخت اسکیما با AI</button><button class="btn primary" data-act="new">${icon('plus')} اسکیمای جدید</button>`,
  async render() {
    const list = await api('/api/schemas');
    const kinds = (cols) => { const c = {}; cols.forEach((x) => { c[x.kind] = (c[x.kind] || 0) + 1; }); return c; };
    const kl = { scraped: 'استخراجی', manual: 'دستی', constant: 'ثابت', mapping: 'نگاشت', auto: 'خودکار', ai: 'هوش مصنوعی' };
    return `<div class="grid g2">${list.map((s) => {
      const k = kinds(s.columns);
      return `<div class="card src-card">
        <div class="flex"><div class="src-logo">${icon('columns', 20)}</div><div class="grow"><b style="font-size:15px;color:var(--z-900)">${esc(s.name)}</b>${s.is_default ? ' <span class="tag p">پیش‌فرض</span>' : ''}<div class="xs muted">${esc(s.description || '')}</div></div></div>
        <div class="flex wrap">${Object.entries(k).map(([kk, n]) => `<span class="tag"><span class="kind-dot k-${kk}"></span>${kl[kk] || kk} ${fa(n)}</span>`).join('')}</div>
        <div class="ltr xs muted" style="text-align:left;line-height:1.9">${s.columns.map((c) => esc(c.key)).join(' · ')}</div>
        <div class="btns"><a class="btn sm soft" href="#/schemas/${s.id}">${icon('edit', 14)} ویرایش</a><button class="btn sm ghost" data-act="dup" data-id="${s.id}">${icon('copy', 14)} کپی</button>${list.length > 1 ? `<button class="btn sm ghost danger" data-act="del" data-id="${s.id}">${icon('trash', 14)}</button>` : ''}</div>
      </div>`;
    }).join('')}</div>`;
  },
  act: {
    new: async () => { const s = await api('/api/schemas', { body: { name: 'اسکیمای جدید', columns: [{ key: 'title', label: 'عنوان', kind: 'scraped', from: 'title', input: 'text', required: true }, { key: 'source_url', label: 'لینک منبع', kind: 'auto', generator: 'source_url' }] } }); await refreshBoot(); go(`#/schemas/${s.id}`); },
    dup: async (el) => { const s = await api(`/api/schemas/${el.dataset.id}/duplicate`, { body: {} }); await refreshBoot(); go(`#/schemas/${s.id}`); },
    aischema: () => openAISchema(),
    del: async (el) => { if (!(await confirmDlg('حذف اسکیما', 'این اسکیما حذف شود؟', 'حذف', true))) return; await api(`/api/schemas/${el.dataset.id}`, { method: 'DELETE' }); await refreshBoot(); location.reload(); },
  },
};

const SC = { s: null };
const KINDS = [['scraped', 'استخراجی'], ['manual', 'دستی'], ['ai', 'هوش مصنوعی'], ['constant', 'ثابت'], ['mapping', 'نگاشت'], ['auto', 'خودکار']];
const SYS_GENS = ['source_url', 'source_name', 'dataset_code', 'scraped_at', 'product_key'];
const AI_MODES_TXT = [['', 'خاموش'], ['fill_missing', 'اگر خالی بود'], ['rewrite', 'بازنویسی یکتا'], ['overwrite', 'همیشه از نو']];
const AI_MODES_IMG = [['', 'خاموش'], ['fill_missing', 'اگر تصویری نیست'], ['add', 'افزودن به تصاویر'], ['overwrite', 'جایگزینی کامل']];
const INPUTS = [['text', 'متن کوتاه'], ['longtext', 'متن بلند'], ['bullets', 'بولت'], ['bullet_groups', 'گروه بولت‌ها (چند ستون)'], ['group', 'گروه کلید/مقدار (مثل ابعاد)'], ['specs', 'مشخصات'], ['image', 'تصویر'], ['images', 'چند تصویر'], ['json', 'JSON'], ['bool', 'بله/خیر'], ['number', 'عدد']];
const GENS = [['slug', 'اسلاگ انگلیسی'], ['source_url', 'لینک صفحه‌ی محصول'], ['source_name', 'نام منبع'], ['dataset_code', 'شناسه‌ی بانک داده'], ['scraped_at', 'زمان استخراج'], ['product_key', 'شناسه‌ی محصول در منبع']];

export const SchemaEditor = {
  title: 'ویرایش اسکیما',
  crumb: 'اسکیماهای داده',
  top: () => `<a class="btn ghost" href="#/schemas">${icon('chevronRight', 16)} بازگشت</a><button class="btn primary" data-act="save">${icon('save', 16)} ذخیره‌ی اسکیما</button>`,
  async render(p) {
    await refreshBoot();
    SC.s = await api(`/api/schemas/${p.id}`);
    return `<div class="card"><div class="card-b"><div class="form-grid">
        <div class="field"><label>نام اسکیما</label><input class="inp" id="sc-name" value="${attr(SC.s.name)}"></div>
        <div class="field"><label>توضیح</label><input class="inp" id="sc-desc" value="${attr(SC.s.description || '')}"></div>
        <label class="check"><input type="checkbox" id="sc-def" ${SC.s.is_default ? 'checked' : ''}> اسکیمای پیش‌فرض برای اجراها و خروجی‌های جدید</label>
      </div></div></div>
      <div class="card mt16"><div class="card-h"><h2>ستون‌ها</h2><span class="sub">ترتیب ستون‌ها همان ترتیب فایل خروجی است · <span class="kind-dot k-scraped"></span>استخراجی: از منبع اسکرپ می‌شود · <span class="kind-dot k-manual"></span>دستی: در استودیو وارد می‌شود · <span class="kind-dot k-constant"></span>ثابت: پیش‌ساخته · <span class="kind-dot k-ai"></span>هوش مصنوعی: تولید خودکار · ${icon('edit', 11)} پیش‌فرض: مقداری که خودتان یک بار برای همه‌ی محصولات می‌نویسید</span><span class="sp"></span><button class="btn sm soft" data-act="aicol">${icon('sparkles', 14)} ستون با AI</button><button class="btn sm soft" data-act="aimore">${icon('wand', 14)} تکمیل اسکیما با AI</button><button class="btn sm" data-act="addcol">${icon('plus', 14)} ستون</button></div>
        <div id="sc-cols"></div></div>`;
  },
  mount() { this.draw(); },
  draw() {
    const fields = S.boot.canonical_fields || [];
    const head = `<div class="col-row head"><span></span><span>نام ستون در فایل</span><span>برچسب</span><span>نوع مقدار</span><span>منبع مقدار · نوع ورودی</span><span></span></div>`;
    document.getElementById('sc-cols').innerHTML = head + SC.s.columns.map((c, i) => {
      const src = c.kind === 'scraped' ? `<select class="inp sm" data-change="col" data-i="${i}" data-k="from">${fields.map((f) => `<option value="${f.key}" ${c.from === f.key ? 'selected' : ''}>${esc(f.label)}</option>`).join('')}</select>`
        : c.kind === 'constant' ? (['text', 'number', 'image'].includes(c.input || 'text') ? `<input class="inp sm" data-input="col" data-i="${i}" data-k="value" value="${attr(typeof c.value === 'object' && c.value !== null ? JSON.stringify(c.value) : (c.value ?? ''))}" placeholder="مقدار ثابت" style="min-width:0">` : '')
          + `<button class="btn xs soft nowrap" data-act="colconst" data-i="${i}" title="ویرایش مقدار ثابت در ویرایشگر کامل (چندخطی، بولت، گروه…)">${icon('edit', 12)} ${['text', 'number', 'image'].includes(c.input || 'text') ? '' : esc(trunc(defPreview(c, c.value) || 'تعیین مقدار', 26))}</button>`
        : c.kind === 'mapping' ? `<select class="inp sm" data-change="col" data-i="${i}" data-k="map"><option value="category" ${c.map === 'category' ? 'selected' : ''}>دسته‌بندی</option><option value="brand" ${c.map === 'brand' ? 'selected' : ''}>برند</option></select>`
        : c.kind === 'auto' ? `<select class="inp sm" data-change="col" data-i="${i}" data-k="generator">${GENS.map(([k, l]) => `<option value="${k}" ${c.generator === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`
        : c.kind === 'ai' ? `<span class="xs" style="color:var(--primary)">${icon('sparkles', 12)} مقدار با هوش مصنوعی ساخته می‌شود</span>`
        : `<span class="xs muted">در استودیو وارد می‌شود</span>`;
      const exp = c.input === 'bullet_groups' ? [['split', 'هر گروه یک ستون'], ['json', 'یک ستون JSON'], ['split+json', 'هر دو']]
        : c.input === 'group' ? [['json', 'یک ستون JSON'], ['split', 'هر کلید یک ستون']]
        : c.input === 'images' ? [['comma', 'جداشده با ویرگول'], ['json', 'آرایه‌ی JSON'], ['lines', 'هر خط یکی']] : null;
      return `<div class="col-row">
        <div class="ord"><button data-act="mv" data-i="${i}" data-d="-1" title="بالا">${icon('chevronUp', 15)}</button><button data-act="mv" data-i="${i}" data-d="1" title="پایین">${icon('chevronDown', 15)}</button></div>
        <input class="inp sm ltr" data-input="col" data-i="${i}" data-k="key" value="${attr(c.key)}" title="نام ستون در فایل">
        <input class="inp sm" data-input="col" data-i="${i}" data-k="label" value="${attr(c.label || '')}" placeholder="برچسب فارسی">
        <select class="inp sm" data-change="col" data-i="${i}" data-k="kind" data-redraw="1">${KINDS.map(([k, l]) => `<option value="${k}" ${c.kind === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <div class="flex">${src}<select class="inp sm" style="max-width:150px" data-change="col" data-i="${i}" data-k="input" data-redraw="1" title="نوع ورودی/قالب">${INPUTS.map(([k, l]) => `<option value="${k}" ${(c.input || 'text') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="flex"><label class="check xs" title="اجباری؛ اگر خالی بماند خطای «اطلاعات ناقص» داده می‌شود"><input type="checkbox" data-change="col" data-i="${i}" data-k="required" ${c.required ? 'checked' : ''}> اجباری</label>
          <label class="check xs"><input type="checkbox" data-change="col" data-i="${i}" data-k="include" ${c.include !== false ? 'checked' : ''}> در خروجی</label>
          <button class="btn xs ghost danger" data-act="delcol" data-i="${i}">${icon('trash', 13)}</button></div>
        ${`<div style="grid-column:2 / -1" class="flex wrap">
          ${c.kind === 'auto' && SYS_GENS.includes(c.generator || 'slug') ? `<span class="xs muted">${icon('sparkles', 12)} مقدار سیستمی؛ با هوش مصنوعی ساخته نمی‌شود</span>` : `<span class="xs" style="color:var(--primary)">${icon('sparkles', 12)} هوش مصنوعی:</span>
            <select class="inp sm" style="max-width:150px" data-change="col" data-i="${i}" data-k="ai_mode" data-redraw="1" title="تولید خودکار این ستون با هوش مصنوعی (پس از استخراج، در بانک‌های تولیدی و در دکمه‌ی «ستون‌های AI اسکیما»)">${(['image', 'images'].includes(c.input) ? AI_MODES_IMG : AI_MODES_TXT).filter(([k]) => !(c.kind === 'ai' && k === '')).map(([k, l]) => `<option value="${k}" ${(c.ai_mode || (c.kind === 'ai' ? 'fill_missing' : '')) === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
            ${c.ai_mode || c.kind === 'ai' ? `<input class="inp sm" style="max-width:460px;flex:1" data-input="col" data-i="${i}" data-k="ai_instruction" value="${attr(c.ai_instruction || '')}" placeholder="دستور تولید (اختیاری) — مثلاً: ۳ بولت کوتاه درباره‌ی نکات نصب" data-ai-label="دستور تولید هوش مصنوعی برای ستون ${attr(c.label || c.key)}">` : ''}`}
          ${defaultChip(c, i)}
          ${exp ? `<span class="xs muted">قالب خروجی:</span><select class="inp sm" style="max-width:200px" data-change="col" data-i="${i}" data-k="export">${exp.map(([k, l]) => `<option value="${k}" ${(c.export || exp[0][0]) === k ? 'selected' : ''}>${l}</option>`).join('')}</select>` : ''}
          ${c.input === 'specs' ? `<span class="xs muted">قالب مشخصات:</span><select class="inp sm" style="max-width:240px" data-change="col" data-i="${i}" data-k="spec_format">${[['flat', 'شیء نام→مقدار'], ['grouped', 'گروه‌بندی‌شده'], ['list', 'فهرست کامل']].map(([k, l]) => `<option value="${k}" ${(c.spec_format || 'flat') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>` : ''}
          ${c.kind === 'mapping' ? `<span class="xs muted">اگر نگاشت نبود:</span><select class="inp sm" style="max-width:220px" data-change="col" data-i="${i}" data-k="fallback"><option value="auto" ${c.fallback !== 'empty' ? 'selected' : ''}>اسلاگ پیشنهادی خودکار</option><option value="empty" ${c.fallback === 'empty' ? 'selected' : ''}>خالی بماند</option></select>` : ''}
          ${c.input === 'bullet_groups' ? `<span class="xs muted">گروه‌ها (هر خط key: برچسب):</span><textarea class="inp sm mono" rows="3" style="max-width:420px;height:auto;padding:6px 10px" data-input="colgroups" data-i="${i}">${esc((c.groups || []).map((g) => `${g.key}: ${g.label}`).join('\n'))}</textarea>` : ''}
          ${c.input === 'group' ? `<span class="xs muted">کلیدها:</span><input class="inp sm mono" style="max-width:520px" data-input="colsubs" data-i="${i}" value="${attr((c.subkeys || []).join(', '))}">` : ''}
        </div>`}
      </div>`;
    }).join('');
  },
  input: {
    col: (el) => { SC.s.columns[Number(el.dataset.i)][el.dataset.k] = el.value; },
    colgroups: (el) => { SC.s.columns[Number(el.dataset.i)].groups = el.value.split('\n').map((l) => l.split(':')).filter((x) => x[0]?.trim()).map((x) => ({ key: x[0].trim(), label: (x[1] || x[0]).trim() })); },
    colsubs: (el) => { SC.s.columns[Number(el.dataset.i)].subkeys = el.value.split(/[,،\s]+/).map((x) => x.trim()).filter(Boolean); },
  },
  change: {
    col: (el) => {
      const c = SC.s.columns[Number(el.dataset.i)];
      c[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value;
      if (el.dataset.k === 'kind') {
        if (c.kind === 'scraped' && !c.from) c.from = 'title';
        if (c.kind === 'auto' && !c.generator) c.generator = 'slug';
        if (c.kind === 'mapping' && !c.map) c.map = 'category';
        if (c.kind === 'ai' && !c.ai_mode) c.ai_mode = 'fill_missing';
      }
      if (el.dataset.k === 'input' && c.input === 'bullet_groups' && !c.groups) c.groups = [{ key: 'dos', label: 'بایدها' }, { key: 'donts', label: 'نبایدها' }, { key: 'notes', label: 'نکات' }];
      if (el.dataset.k === 'input' && c.input === 'group' && !c.subkeys) c.subkeys = ['item_weight', 'item_width', 'item_length', 'item_height', 'packaging_weight', 'packaging_width', 'packaging_length', 'packaging_height'];
      if (el.dataset.redraw) SchemaEditor.draw();
    },
  },
  act: {
    aicol: async (el) => {
      const desc = await aiAsk('ستون جدید با هوش مصنوعی', 'چه ستونی لازم دارید؟', 'مثلاً: گارانتی محصول به‌صورت متن کوتاه که هوش مصنوعی پر کند');
      if (!desc) return;
      busy(el, true);
      try {
        const r = await assist('column', { description: desc, schema_columns: SC.s.columns });
        SC.s.columns.push(r.column);
        SchemaEditor.draw();
        okToast(`ستون «${r.column.label}» افزوده شد؛ بررسی و ذخیره کنید.`);
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    aimore: async (el) => {
      const desc = await aiAsk('تکمیل اسکیما با هوش مصنوعی', 'چه ستون‌هایی کم است؟ (اختیاری)', 'مثلاً: ستون‌های سئو و اطلاعات سازگاری با خودرو');
      if (desc === null) return;
      busy(el, true);
      try {
        const r = await assist('schema', { description: `${SC.s.name}. ${desc || 'ستون‌های مفید و رایج کاتالوگ که در اسکیما نیستند'}`, base_columns: SC.s.columns });
        if (!r.columns.length) { toast('ستون تازه‌ای پیشنهاد نشد.'); return; }
        SC.s.columns.push(...r.columns);
        SchemaEditor.draw();
        okToast(`${fa(r.columns.length)} ستون پیشنهادی افزوده شد؛ موارد ناخواسته را حذف و ذخیره کنید.`);
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    addcol: () => { SC.s.columns.push({ key: `field_${SC.s.columns.length + 1}`, label: '', kind: 'manual', input: 'text' }); SchemaEditor.draw(); },
    coldef: async (el) => {
      const c = SC.s.columns[Number(el.dataset.i)];
      const r = await openDefaultEditor(c);
      if (!r) return;
      if (r.value === null) { delete c.default; delete c.default_mode; } else { c.default = r.value; c.default_mode = r.mode; }
      SchemaEditor.draw();
      toast('مقدار پیش‌فرض تغییر کرد؛ «ذخیره‌ی اسکیما» را بزنید.');
    },
    colconst: async (el) => {
      const c = SC.s.columns[Number(el.dataset.i)];
      const r = await openDefaultEditor(c, { constant: true });
      if (!r) return;
      c.value = r.value === null ? '' : r.value;
      SchemaEditor.draw();
      toast('مقدار ثابت تغییر کرد؛ «ذخیره‌ی اسکیما» را بزنید.');
    },
    delcol: (el) => { SC.s.columns.splice(Number(el.dataset.i), 1); SchemaEditor.draw(); },
    mv: (el) => { const i = Number(el.dataset.i); const j = i + Number(el.dataset.d); const c = SC.s.columns; if (j < 0 || j >= c.length) return; [c[i], c[j]] = [c[j], c[i]]; SchemaEditor.draw(); },
    save: async () => {
      const keys = SC.s.columns.map((c) => c.key);
      if (new Set(keys).size !== keys.length) { toast('نام ستون‌ها باید یکتا باشد.', 'err'); return; }
      await api(`/api/schemas/${SC.s.id}`, { method: 'PUT', body: { name: document.getElementById('sc-name').value, description: document.getElementById('sc-desc').value, is_default: document.getElementById('sc-def').checked, columns: SC.s.columns } });
      await refreshBoot();
      okToast('اسکیما ذخیره شد.');
    },
  },
};

// ======================================================================
// هوش مصنوعی در اسکیماها
// ======================================================================
function aiAsk(title, label, ph) {
  return new Promise((resolve) => {
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} ${esc(title)}</h3></div><div class="card-b">
      <div class="field"><label>${esc(label)}</label><textarea class="inp" rows="3" id="aa-d" placeholder="${attr(ph)}"></textarea></div></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="aa-ok">${icon('sparkles', 16)} تولید</button></div>`, { onClose: () => resolve(null) });
    l.box.querySelector('#aa-ok').addEventListener('click', () => { resolve(l.box.querySelector('#aa-d').value.trim()); l.close(); });
    setTimeout(() => l.box.querySelector('#aa-d').focus(), 50);
  });
}

const KL = { scraped: 'استخراجی', manual: 'دستی', constant: 'ثابت', mapping: 'نگاشت', auto: 'خودکار', ai: 'هوش مصنوعی' };

function openAISchema() {
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} ساخت اسکیما با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:70vh;overflow:auto">
      <div class="field"><label>چه کاتالوگی می‌خواهید؟</label>
        <textarea class="inp" rows="3" id="as-d" placeholder="مثلاً: کاتالوگ لاستیک خودرو برای فروشگاه آنلاین با سایز، شاخص بار، کشور سازنده، گارانتی، توضیح سئو و بایدها/نبایدهای نصب"></textarea></div>
      <div class="flex mt12"><button class="btn primary" id="as-go">${icon('sparkles', 16)} طراحی ستون‌ها</button><span class="small muted" id="as-st"></span></div>
      <div id="as-res"></div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="as-ok" disabled>${icon('check', 16)} ساخت اسکیما</button></div>`, { wide: true });
  const b = l.box;
  let res = null;
  b.querySelector('#as-go').addEventListener('click', async (ev) => {
    const d = b.querySelector('#as-d').value.trim();
    if (!d) { toast('توضیح کاتالوگ را بنویسید.', 'err'); return; }
    const btn = ev.currentTarget;
    busy(btn, true, 'در حال طراحی…');
    try {
      res = await assist('schema', { description: d });
      b.querySelector('#as-res').innerHTML = `<div class="form-grid mt16"><div class="field"><label>نام</label><input class="inp" id="as-name" value="${attr(res.name)}"></div>
        <div class="field"><label>توضیح</label><input class="inp" id="as-desc" value="${attr(res.description)}"></div></div>
        <div class="tbl-wrap mt12" style="border:1px solid var(--z-200);border-radius:14px"><table class="tbl"><thead><tr><th></th><th>ستون</th><th>برچسب</th><th>نوع مقدار</th><th>ورودی</th><th>جزئیات</th></tr></thead><tbody>
        ${res.columns.map((c, i) => `<tr><td><input type="checkbox" data-asc="${i}" checked></td><td class="ltr small">${esc(c.key)}</td><td>${esc(c.label)}</td>
          <td><span class="tag"><span class="kind-dot k-${c.kind}"></span>${KL[c.kind] || c.kind}</span></td><td class="small">${esc(c.input)}</td>
          <td class="xs muted">${esc(c.from || c.value || c.map || c.generator || c.ai_instruction || '')}</td></tr>`).join('')}</tbody></table></div>`;
      b.querySelector('#as-ok').disabled = false;
      b.querySelector('#as-st').textContent = `${fa(res.columns.length)} ستون پیشنهاد شد`;
    } catch (e) { noProviderHint(e); } finally { busy(btn, false); }
  });
  b.querySelector('#as-ok').addEventListener('click', async () => {
    const cols = res.columns.filter((c, i) => b.querySelector(`[data-asc="${i}"]`).checked);
    if (!cols.some((c) => c.key === 'source_url')) cols.push({ key: 'source_url', label: 'لینک منبع', kind: 'auto', generator: 'source_url' });
    const s = await api('/api/schemas', { body: { name: b.querySelector('#as-name').value, description: b.querySelector('#as-desc').value, columns: cols } });
    await refreshBoot();
    l.close();
    okToast('اسکیما ساخته شد.');
    go(`#/schemas/${s.id}`);
  });
}
