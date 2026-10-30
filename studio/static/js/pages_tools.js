import {
  S, api, icon, esc, attr, fa, num, jdate, chip, isLive, progress, toast, okToast, errToast, openLayer,
  confirmDlg, emptyState, every, go, openPath, fileUrl, refreshBoot, schemaById, trunc,
} from './core.js';
import { logRow } from './pages_main.js';
import { assist, busy, noProviderHint } from './ai_assist.js';
import { alignEditor, bindAlign, readAlign, runPreview, fileToDataUrl } from './align_ui.js';

// ======================================================================
// خروجی‌ساز
// ======================================================================
const EX = { sel: new Set(), datasets: [], getAlign: null, aiMode: 'empty', aiCols: null };

export const Exports = {
  title: 'خروجی‌ساز',
  crumb: 'ساخت فایل Excel، CSV و JSON، پوشه‌ی تصاویر و بسته‌ی فشرده',
  async render() {
    const [datasets, b] = await Promise.all([api('/api/datasets'), refreshBoot()]);
    EX.datasets = datasets.filter((d) => d.counts.done + d.counts.partial > 0);
    EX.sel = new Set();
    EX.aiMode = 'empty';
    EX.aiCols = null;
    const pre = sessionStorage.getItem('export-ds');
    if (pre) { EX.sel.add(Number(pre)); sessionStorage.removeItem('export-ds'); }
    const st = b.settings;
    return `
    <div class="grid g-side">
      <div class="card">
        <div class="card-h"><h2>ساخت خروجی جدید</h2></div>
        <div class="card-b">
          <div class="lbl">۱. بانک‌های داده</div>
          <div class="hint mb8">می‌توانید چند بانک را با هم در یک فایل ترکیب کنید.</div>
          ${EX.datasets.length ? `<div style="max-height:260px;overflow:auto;border:1px solid var(--z-200);border-radius:16px">${EX.datasets.map((d) => `
            <label class="flex" style="padding:10px 14px;border-bottom:1px solid var(--z-100);cursor:pointer">
              <input type="checkbox" class="check" data-change="pickds" value="${d.id}" ${EX.sel.has(d.id) ? 'checked' : ''} style="width:17px;height:17px;accent-color:var(--primary)">
              <div class="grow"><b class="small" style="color:var(--z-900)">${esc(trunc(d.title, 80))}</b><div class="xs muted ltr" style="text-align:right">${esc(d.name)}</div></div>
              <span class="tag">${num(d.counts.done)} کامل${d.counts.partial ? ' · ' + num(d.counts.partial) + ' ناقص' : ''}</span>${chip(d.status)}
            </label>`).join('')}</div>` : `<div class="alert info">${icon('info')}<div>هنوز بانک داده‌ای با محصول استخراج‌شده ندارید.</div></div>`}

          <div class="form-grid mt24">
            <div class="field"><label>۲. اسکیمای خروجی</label>
              <select class="inp" id="ex-schema" data-change="exschema">${b.schemas.map((s) => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
              <div class="hint">ستون‌ها، ترتیب و قالب خروجی از اسکیما می‌آید. <a href="#/schemas">ویرایش اسکیماها</a></div></div>
            <div class="field"><label>محصولات شامل</label>
              <div class="flex wrap" style="height:42px"><label class="check"><input type="checkbox" id="ex-done" checked> کامل</label><label class="check"><input type="checkbox" id="ex-partial" checked> ناقص</label></div></div>
            <div class="field full"><label>نام خروجی</label><input class="inp ltr" id="ex-name" data-input="tree" placeholder="به‌طور خودکار از نام بانک داده ساخته می‌شود">
              <div class="hint">همین نام برای فایل Excel، پوشه‌ی مادر تصاویر و فایل ZIP استفاده می‌شود.</div></div>
            <div class="field full"><label>مسیر ذخیره‌سازی</label><input class="inp ltr" id="ex-root" data-input="tree" value="${attr(st.output_root)}"></div>
          </div>

          <div class="lbl mt24">۳. قالب فایل و اسکیمای هر قالب</div>
          <div class="hint mb8">هر قالب می‌تواند اسکیمای خودش را داشته باشد؛ مثلاً Excel با اسکیمای مگا کارز و JSON با اسکیمای API.</div>
          <div class="fmt-grid">${[['xlsx', 'Excel (.xlsx)', true, 'fileSheet'], ['csv', 'CSV (UTF-8)', true, 'list'], ['json', 'JSON — آرایه‌ای از اشیاء ساخت‌یافته', false, 'code']].map(([k, l, on, ic]) => `
            <div class="fmt-row"><label class="check grow"><input type="checkbox" id="ex-${k}" data-fmt="${k}" data-change="tree" ${on ? 'checked' : ''}> ${icon(ic, 15)} ${l}</label>
              <select class="inp sm" id="ex-sch-${k}" data-change="tree" style="max-width:300px"><option value="">مانند اسکیمای اصلی</option>${b.schemas.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></div>`).join('')}</div>
          <label class="check mt12"><input type="checkbox" id="ex-zip" checked data-change="tree"> بسته‌ی فشرده‌ی نهایی (ZIP)</label>

          <div class="lbl mt24">۴. تصاویر</div>
          <div class="flex wrap mt8"><label class="check"><input type="checkbox" id="ex-img" checked data-change="tree"> دانلود و پوشه‌بندی تصاویر</label>
            <label class="check"><input type="checkbox" id="ex-bg" data-change="tree" checked> حذف پس‌زمینه (rembg)</label>
            <label class="check"><input type="checkbox" id="ex-align" data-change="tree" checked> ترازبندی سوژه (تریم و فاصله‌ی ثابت از لبه‌ها)</label></div>
          <div class="hint">تصویر نهایی هر محصول <span class="kbd">feature.png</span> و <span class="kbd">gallery_1.png</span> است: بدون پس‌زمینه و ترازشده. نسخه‌ی دانلودشده <span class="kbd">feature_raw</span> و نسخه‌ی بدون پس‌زمینه‌ی پیش از ترازبندی <span class="kbd">feature_raw_rembg</span> نام می‌گیرد.</div>
          <div class="flex wrap mt8"><label class="check"><input type="checkbox" id="ex-keepraw" checked data-change="tree"> نگه‌داشتن فایل‌های خام و میانی و داده‌ی خام</label>
            <label class="check"><input type="checkbox" id="ex-zipraw" data-change="tree"> فایل‌های خام هم در ZIP بیاید</label></div>
          <div id="ex-align-box" class="ai-inline hidden" style="background:var(--z-50);border-color:var(--z-200)">${alignEditor(st.image_align)}
            <div class="hint mt8">پیش‌فرض این قاعده را در <a href="#/bg">پردازش تصاویر</a> با پیش‌نمایش قبل/بعد تنظیم کنید.</div></div>
          <div class="form-grid mt12">
            <div class="field"><label class="small">نام پوشه‌ی هر محصول</label><select class="inp sm" id="ex-folder" data-change="tree"><option value="slug">اسلاگ انگلیسی (پیشنهادی)</option><option value="title">عنوان فارسی محصول</option><option value="key">شناسه‌ی محصول در منبع</option></select></div>
            <div class="field"><label class="small">مدل حذف پس‌زمینه</label><select class="inp sm" id="ex-model">${b.rembg_models.map((m) => `<option value="${m.name}" ${m.name === st.rembg_model ? 'selected' : ''}>${esc(m.label)}${m.installed ? '' : ' — نصب نشده'}</option>`).join('')}</select></div>
            <div class="field full"><label class="small">پیوند تصاویر در فایل داده</label>
              <div class="seg" id="ex-link"><button class="on" data-act="link" data-v="relative">مسیر نسبی فایل‌ها</button><button data-act="link" data-v="prefix">پیشوند دلخواه (CDN)</button><button data-act="link" data-v="source">لینک اصلی منبع</button></div>
              <input class="inp sm ltr mt8 hidden" id="ex-prefix" placeholder="https://cdn.megacars.ir/catalog/">
              <div class="hint">با «مسیر نسبی»، ستون‌های تصویر به تصاویر نهایی داخل پوشه‌ی خروجی (feature.png و gallery_N.png) اشاره می‌کنند.</div></div>
          </div>
          <div class="lbl mt24">۵. هوش مصنوعی پیش از خروجی</div>
          <div class="ai-inline mt8">
            <label class="check"><input type="checkbox" id="ex-ai" data-change="exai"> ${icon('sparkles', 14)} پیش از ساخت فایل‌ها، ستون‌ها با هوش مصنوعی تکمیل شوند</label>
            <div id="ex-ai-box" class="hidden mt12">
              <div class="seg" id="ex-ai-mode"><button class="on" data-act="exaimode" data-v="empty">همه‌ی ستون‌های خالی</button><button data-act="exaimode" data-v="schema">ستون‌های AI اسکیما</button><button data-act="exaimode" data-v="pick">انتخاب ستون‌ها</button></div>
              <div id="ex-ai-cols" class="hidden mt8 flex wrap" style="gap:6px"></div>
              <div class="hint mt8">فقط مقادیر خالی پر می‌شوند و ویرایش‌های دستی دست نمی‌خورند. نتیجه مثل هر خروجی دیگر هوش مصنوعی در بانک داده ذخیره و برگشت‌پذیر است. اگر ستون تصویری انتخاب شود، برای محصولات بدون تصویر، تصویر ساخته می‌شود.</div>
            </div></div>
        </div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn primary" data-act="build">${icon('package', 16)} ساخت خروجی</button></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h3>ساختار خروجی</h3></div><div class="card-b"><div class="tree" id="ex-tree"></div></div></div>
      </div>
    </div>
    <div class="card mt16"><div class="card-h"><h2>خروجی‌های ساخته‌شده</h2></div><div id="ex-list"></div></div>`;
  },
  async mount(view) {
    EX.getAlign = bindAlign(view.querySelector('#ex-align-box'), () => Exports.tree());
    await this.suggest();
    this.tree();
    await this.list();
    every(1500, () => this.list(true));
  },
  link: 'relative',
  async suggest() {
    const r = await api('/api/exports/suggest-name', { body: { dataset_ids: [...EX.sel] } });
    const el = document.getElementById('ex-name');
    if (el && (!el.dataset.touched)) el.value = r.name || '';
    this.tree();
  },
  tree() {
    const t = document.getElementById('ex-tree');
    if (!t) return;
    const name = document.getElementById('ex-name').value || 'export-name';
    const root = document.getElementById('ex-root').value || '';
    const img = document.getElementById('ex-img').checked;
    const bg = document.getElementById('ex-bg').checked;
    if (bg && !EX.bgWas) document.getElementById('ex-align').checked = true;
    EX.bgWas = bg;
    const al = document.getElementById('ex-align').checked;
    document.getElementById('ex-align-box').classList.toggle('hidden', !al);
    const raw = document.getElementById('ex-keepraw').checked;
    const zip = document.getElementById('ex-zip').checked;
    const zipRaw = document.getElementById('ex-zipraw').checked;
    const ao = al && EX.getAlign ? EX.getAlign() : null;
    const ext = ao ? ({ jpg: 'jpg', webp: 'webp' }[ao.format] || 'png') : bg ? 'png' : 'jpg';
    const proc = bg || al;
    const fin = [bg ? 'بدون پس‌زمینه' : '', ao ? `ترازشده ${fa(ao.canvas_w)}×${fa(ao.canvas_h)}` : ''].filter(Boolean).join('، ') || 'دانلودشده';
    const fold = { slug: 'caspian-engine-oil-20w-50-4l', title: 'روغن موتور کاسپین 20W-50', key: '9975369' }[document.getElementById('ex-folder').value];
    const F = (n, note) => `<span class="f">${n}</span>${note ? `  <span class="c"># ${note}</span>` : ''}`;
    const R = (n, note) => `<span class="c">${n}  # ${note}</span>`;
    const schName = (f) => { const v = document.getElementById(`ex-sch-${f}`)?.value; const sc = v ? S.boot.schemas.find((x) => String(x.id) === v) : schemaById(Number(document.getElementById('ex-schema').value)); return sc ? sc.name : ''; };
    const lines = [`<span class="c">${esc(root)}</span>`];
    ['xlsx', 'csv', 'json'].forEach((f) => { if (document.getElementById(`ex-${f}`)?.checked) lines.push(`├── ${F(esc(name) + '.' + f, 'نهایی · ' + esc(schName(f)))}`); });
    if (zip) lines.push(`├── ${F(esc(name) + '.zip', zipRaw ? 'همه‌ی فایل‌ها' : 'فقط فایل‌های نهایی')}`);
    if (raw) lines.push(`├── ${R(esc(name) + '_raw.xlsx', 'داده‌ی خام استخراج‌شده')}`, `├── ${R(esc(name) + '_raw.json', 'خام + لایه‌های ویرایش و AI')}`);
    if (img) {
      lines.push(`└── <span class="d">${esc(name)}/</span>`, `    └── <span class="d">${esc(fold)}/</span>`);
      const files = [F(`feature.${ext}`, `نهایی: ${fin}`)];
      if (proc && raw) files.push(R('feature_raw.jpg', 'خام دانلودشده'));
      if (bg && al && raw) files.push(R('feature_raw_rembg.png', 'میانی: بدون پس‌زمینه'));
      files.push(F(`gallery_1.${ext}`, ''));
      if (proc && raw) files.push(R('gallery_1_raw.jpg', 'خام'));
      if (bg && al && raw) files.push(R('gallery_1_raw_rembg.png', 'میانی'));
      files.forEach((f, i) => lines.push(`        ${i === files.length - 1 ? '└──' : '├──'} ${f}`));
    } else lines[lines.length - 1] = lines[lines.length - 1].replace('├──', '└──');
    t.innerHTML = lines.join('\n');
  },
  async list(silent) {
    const rows = await api('/api/exports').catch(() => null);
    const el = document.getElementById('ex-list');
    if (!rows || !el) return;
    const sig = JSON.stringify(rows.map((r) => [r.id, r.status, r.progress_done, r.step]));
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    if (!rows.length) { el.innerHTML = emptyState('fileSheet', 'هنوز خروجی‌ای نساخته‌اید', 'بانک‌های داده را انتخاب و «ساخت خروجی» را بزنید.'); return; }
    el.innerHTML = rows.map((r) => exportRow(r)).join('');
  },
  input: { tree: (el) => { if (el.id === 'ex-name') el.dataset.touched = '1'; Exports.tree(); } },
  change: {
    pickds: (el) => { const id = Number(el.value); el.checked ? EX.sel.add(id) : EX.sel.delete(id); Exports.suggest(); },
    exai: (el) => { document.getElementById('ex-ai-box').classList.toggle('hidden', !el.checked); },
    exschema: () => { EX.aiCols = null; if (EX.aiMode === 'pick') Exports.loadAICols(); },
    tree: () => Exports.tree(),
  },
  async loadAICols() {
    const box = document.getElementById('ex-ai-cols');
    if (!EX.aiCols) EX.aiCols = (await api(`/api/ai/columns?schema_id=${document.getElementById('ex-schema').value}`)).columns.filter((c) => c.capable);
    box.innerHTML = EX.aiCols.map((c) => `<label class="tag" style="cursor:pointer;gap:6px"><input type="checkbox" data-aicol="${attr(c.key)}" ${c.schema_ai ? 'checked' : ''}> ${esc(c.label)}</label>`).join('');
  },
  act: {
    exaimode: (el) => {
      EX.aiMode = el.dataset.v;
      document.querySelectorAll('#ex-ai-mode button').forEach((b) => b.classList.toggle('on', b === el));
      document.getElementById('ex-ai-cols').classList.toggle('hidden', EX.aiMode !== 'pick');
      if (EX.aiMode === 'pick') Exports.loadAICols();
    },
    link: (el) => {
      Exports.link = el.dataset.v;
      document.querySelectorAll('#ex-link button').forEach((b) => b.classList.toggle('on', b === el));
      document.getElementById('ex-prefix').classList.toggle('hidden', el.dataset.v !== 'prefix');
    },
    build: async (el) => {
      if (!EX.sel.size) { toast('دست‌کم یک بانک داده انتخاب کنید.', 'err'); return; }
      const statuses = [];
      if (document.getElementById('ex-done').checked) statuses.push('done');
      if (document.getElementById('ex-partial').checked) statuses.push('partial');
      const formats = [];
      const formatSchemas = {};
      ['xlsx', 'csv', 'json'].forEach((f) => {
        if (document.getElementById(`ex-${f}`).checked) {
          formats.push(f);
          const v = document.getElementById(`ex-sch-${f}`).value;
          if (v) formatSchemas[f] = Number(v);
        }
      });
      if (!formats.length) { toast('دست‌کم یک قالب فایل انتخاب کنید.', 'err'); return; }
      el.disabled = true;
      try {
        await api('/api/exports', { body: {
          dataset_ids: [...EX.sel], schema_id: Number(document.getElementById('ex-schema').value), statuses, formats, format_schemas: formatSchemas,
          name: document.getElementById('ex-name').value.trim(), output_root: document.getElementById('ex-root').value.trim(),
          images: document.getElementById('ex-img').checked, rembg: document.getElementById('ex-bg').checked,
          keep_raw: document.getElementById('ex-keepraw').checked, zip_include_raw: document.getElementById('ex-zipraw').checked,
          align: document.getElementById('ex-align').checked ? EX.getAlign() : false,
          ai_fill: document.getElementById('ex-ai').checked ? (EX.aiMode === 'schema' ? { use_schema: true } : EX.aiMode === 'pick'
            ? { columns: [...document.querySelectorAll('[data-aicol]:checked')].map((x) => x.dataset.aicol) } : { mode: 'fill_missing' }) : null,
          rembg_model: document.getElementById('ex-model').value, folder_mode: document.getElementById('ex-folder').value,
          link_mode: Exports.link, link_prefix: document.getElementById('ex-prefix').value.trim(), zip: document.getElementById('ex-zip').checked,
        } });
        okToast('ساخت خروجی آغاز شد.');
        Exports.list();
      } finally { el.disabled = false; }
    },
    open: (el) => openPath(el.dataset.path),
    cancel: async (el) => { await api(`/api/exports/${el.dataset.id}/cancel`, { body: {} }); },
    delx: async (el) => { await api(`/api/exports/${el.dataset.id}`, { method: 'DELETE' }); Exports.list(); },
    warns: async (el) => {
      const r = await api(`/api/exports/${el.dataset.id}`);
      const ws = r.result.warnings || [];
      const lbl = { unmapped: 'نگاشت‌نشده (مقدار پیشنهادی استفاده شد)', missing: 'فیلد اجباری خالی', image_failed: 'دانلود تصویر ناموفق', bg_failed: 'پردازش تصویر ناموفق', low_res: 'بزرگ‌نمایی زیاد در ترازبندی (ممکن است تار باشد)' };
      openLayer('modal', `<div class="card-h"><h3>هشدارهای خروجی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="tbl-wrap" style="max-height:60vh"><table class="tbl"><thead><tr><th>محصول</th><th>ستون</th><th>هشدار</th></tr></thead><tbody>
        ${ws.map((w) => `<tr><td class="small">${esc(trunc(w.title, 60))}</td><td class="ltr small">${esc(w.column)}</td><td class="small">${esc(lbl[w.flag] || w.flag)}${w.detail ? `<div class="xs muted ltr ellipsis" style="max-width:320px">${esc(w.detail)}</div>` : ''}</td></tr>`).join('')}</tbody></table></div>
        ${ws.some((w) => w.flag === 'unmapped') ? `<div class="card-b"><a class="btn soft" href="#/mappings" data-close>${icon('link', 16)} تکمیل نگاشت‌ها</a></div>` : ''}`, { wide: true });
    },
  },
};

function exportRow(r) {
  const live = ['running', 'pending'].includes(r.status);
  const res = r.result || {};
  const f = res.files || {};
  const pct = r.progress_total ? Math.round((r.progress_done / r.progress_total) * 100) : null;
  const st = res.stats || {};
  return `<div style="padding:16px 20px;border-bottom:1px solid var(--z-100)">
    <div class="flex wrap">
      <span class="src-logo" style="width:38px;height:38px;border-radius:12px">${icon('fileSheet', 18)}</span>
      <div class="grow"><b class="ltr" style="display:block;text-align:right;color:var(--z-900)">${esc(r.name)}</b>
        <div class="xs muted">${jdate(r.created_at)} · ${esc(schemaById(r.schema_id)?.name || '')} · ${fa(r.dataset_ids.length)} بانک داده</div></div>
      ${chip(r.status)}
      ${live ? `<button class="btn sm" data-act="cancel" data-id="${r.id}">${icon('stop', 14)} لغو</button>` : `<button class="btn sm icon ghost" data-act="delx" data-id="${r.id}" title="حذف از فهرست">${icon('trash', 14)}</button>`}
    </div>
    ${live ? `<div class="flex mt12"><div class="grow">${progress(pct, true)}</div><span class="small nowrap">${esc(r.step || '')} ${r.progress_total ? fa(r.progress_done) + '/' + fa(r.progress_total) : ''}</span></div>` : ''}
    ${r.status === 'error' ? `<div class="alert err mt12">${icon('alert')}<div>${esc(r.error)}</div></div>` : ''}
    ${r.status === 'completed' ? `
      <div class="kpi-line mt12"><span>ردیف <b>${num(res.rows)}</b></span><span>ستون <b>${num(res.columns)}</b></span>
        ${st.images_downloaded !== undefined ? `<span>تصویر <b>${num(st.images_downloaded)}</b></span>` : ''}
        ${st.images_bg ? `<span>تصویر نهایی پردازش‌شده <b>${num(st.images_bg)}</b></span>` : ''}
        ${st.images_failed ? `<span style="color:var(--err)">تصویر ناموفق <b>${num(st.images_failed)}</b></span>` : ''}
        ${res.warning_count ? `<a href="javascript:void 0" data-act="warns" data-id="${r.id}" style="color:var(--warn)">${icon('alert', 14)} ${fa(res.warning_count)} هشدار</a>` : ''}</div>
      <div class="btns mt12">
        ${f.xlsx ? `<a class="btn sm" href="${fileUrl(f.xlsx, true)}">${icon('download', 14)} Excel</a>` : ''}
        ${f.csv ? `<a class="btn sm" href="${fileUrl(f.csv, true)}">${icon('download', 14)} CSV</a>` : ''}
        ${f.zip ? `<a class="btn sm" href="${fileUrl(f.zip, true)}">${icon('package', 14)} ZIP نهایی</a>` : ''}
        ${f.raw_xlsx ? `<a class="btn sm ghost" href="${fileUrl(f.raw_xlsx, true)}" title="داده‌ی خام؛ خروجی نهایی نیست">${icon('download', 14)} داده‌ی خام</a>` : ''}
        ${f.json ? `<a class="btn sm" href="${fileUrl(f.json, true)}">${icon('code', 14)} JSON</a>` : ''}
        <a class="btn sm primary" href="#/catalogs/${r.id}">${icon('edit', 14)} مدیریت و ویرایش</a>
        <button class="btn sm soft" data-act="open" data-path="${attr(f.xlsx || f.json || f.zip || res.root)}">${icon('folder', 14)} باز کردن پوشه</button>
        ${f.images_dir ? `<button class="btn sm ghost" data-act="open" data-path="${attr(f.images_dir)}">${icon('image', 14)} پوشه‌ی تصاویر</button>` : ''}
        ${f.rembg_dir ? `<button class="btn sm ghost" data-act="open" data-path="${attr(f.rembg_dir)}">${icon('eraser', 14)} پوشه‌ی rembg</button>` : ''}
      </div>` : ''}
  </div>`;
}

// ======================================================================
// پردازش تصاویر: حذف پس‌زمینه و ترازبندی
// ======================================================================
const BGS = { getAlign: null };

function bgSteps() {
  return { rembg: document.getElementById('bg-st-rembg')?.checked, align: document.getElementById('bg-st-align')?.checked };
}

function bgTree(st) {
  const sub = st.rembg ? 'rembg' : 'aligned';
  const a = BGS.getAlign ? BGS.getAlign() : S.boot.settings.image_align || {};
  const ext = st.align ? ({ jpg: 'jpg', webp: 'webp' }[a.format] || 'png') : 'png';
  const note = st.rembg && st.align ? `نهایی: بدون پس‌زمینه، ترازشده ${fa(a.canvas_w)}×${fa(a.canvas_h)}` : st.rembg ? 'نهایی: بدون پس‌زمینه، اندازه‌ی اصلی' : `نهایی: ترازشده ${fa(a.canvas_w)}×${fa(a.canvas_h)}`;
  const inter = st.rembg && st.align && document.getElementById('bg-keepint')?.checked !== false;
  return `<span class="c">D:\\Catalog\\</span>\n├── <span class="d">digikala__…_1843/</span>\n│   └── <span class="d">caspian-engine-oil/</span>\n│       ├── <span class="f">feature_raw.jpg</span>  <span class="c"># ورودی</span>\n│       └── <span class="f">gallery_1_raw.jpg</span>\n└── <span class="d">${sub}/</span>\n    └── <span class="d">digikala__…_1843/</span>\n        └── <span class="d">caspian-engine-oil/</span>\n            ├── <span class="f">feature.${ext}</span>  <span class="c"># ${note}</span>\n${inter ? '            ├── <span class="c">feature_raw_rembg.png  # میانی: بدون پس‌زمینه، پیش از ترازبندی</span>\n' : ''}            └── <span class="f">gallery_1.${ext}</span>`;
}

export const Bg = {
  title: 'پردازش تصاویر',
  crumb: 'حذف پس‌زمینه و ترازبندی سوژه برای یک پوشه، با حفظ ساختار پوشه‌ها',
  async render() {
    const [b, m] = await Promise.all([refreshBoot(), api('/api/models')]);
    const st = b.settings;
    return `
    <div class="grid g-side">
      <div class="card">
        <div class="card-h"><h2>پردازش یک پوشه</h2><span class="sp"></span>${m.rembg_lib ? '<span class="chip ok">کتابخانه‌ی rembg نصب است</span>' : '<span class="chip info" title="rembg نصب نیست؛ از موتور داخلی با همان مدل‌های rembg استفاده می‌شود">موتور داخلی ONNX</span>'}</div>
        <div class="card-b">
          <div class="field"><label>مسیر پوشه‌ی تصاویر</label>
            <input class="inp ltr" id="bg-in" data-input="preview" placeholder="${attr(st.output_root)}\\digikala__engine-oil__48items__1405-08-05_1843">
            <div class="hint">همه‌ی تصاویر داخل این پوشه و زیرپوشه‌هایش پردازش می‌شوند.</div></div>
          <div class="field mt16"><label>مراحل</label>
            <div class="steps2">
              <label class="pick on"><input type="checkbox" id="bg-st-rembg" data-change="steps" checked><div class="grow"><b>${icon('eraser', 15)} حذف پس‌زمینه</b><div class="xs muted">با مدل rembg؛ خروجی شفاف PNG</div></div></label>
              <label class="pick on"><input type="checkbox" id="bg-st-align" data-change="steps" checked><div class="grow"><b>${icon('frame', 15)} ترازبندی سوژه</b><div class="xs muted">تریم فضای خالی و قرار دادن سوژه با فاصله‌ی ثابت از لبه‌ها</div></div></label>
            </div></div>
          <div class="field mt16"><label>مسیر خروجی</label>
            <input class="inp ltr" id="bg-out" placeholder="خودکار: کنار پوشه‌ی ورودی، داخل rembg/ یا aligned/">
            <div class="hint" id="bg-hint">خروجی با همان سلسله‌مراتب و نام فایل‌ها کنار پوشه‌ی ورودی ذخیره می‌شود.</div></div>
          <div id="bg-align-box" class="mt16"><div class="sec-title">${icon('frame', 16)} قاعده‌ی ترازبندی <span class="line"></span></div>${alignEditor(st.image_align)}</div>
          <div id="bg-rembg-box" class="mt16"><div class="sec-title">${icon('eraser', 16)} مدل حذف پس‌زمینه <span class="line"></span></div><div id="bg-models">${modelsHtml(m, st.rembg_model)}</div></div>
          <label class="check mt16"><input type="checkbox" id="bg-over"> بازنویسی فایل‌های نهایی که قبلاً ساخته شده‌اند (برای اعمال قاعده‌ی تازه؛ حذف پس‌زمینه از فایل میانی دوباره استفاده می‌شود)</label>
          <label class="check mt8"><input type="checkbox" id="bg-keepint" checked data-change="steps"> نگه‌داشتن نسخه‌ی میانی بدون پس‌زمینه (<span class="ltr">_raw_rembg</span>) کنار تصویر نهایی</label>
          <div class="hint mt8">در هر پوشه از هر تصویر فقط یک نسخه پردازش می‌شود: اگر <span class="kbd">feature_raw</span> و <span class="kbd">feature</span> هر دو باشند، نسخه‌ی خام ورودی است. خروجی نهایی بدون پسوند (<span class="kbd">feature.png</span>) نام می‌گیرد.</div>
        </div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px">
          <button class="btn ghost" data-act="savealign" title="این قاعده پیش‌فرض خروجی‌ساز و کارهای بعدی شود">${icon('save', 16)} ذخیره به‌عنوان پیش‌فرض</button>
          <span class="grow"></span>
          <button class="btn soft" data-act="pvfolder">${icon('eye', 16)} پیش‌نمایش</button>
          <button class="btn primary" data-act="start">${icon('play', 16)} <span id="bg-start-lbl">شروع پردازش</span></button></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h3>ترازبندی چه می‌کند؟</h3></div>
          <div class="card-b small" style="line-height:2.1">
            <div class="flex top">${icon('crop', 16)}<span><b>۱. تریم:</b> فضای خالی شفاف (یا رنگ یکدست پس‌زمینه) دور سوژه، مثل Trim فتوشاپ، شناسایی و حذف می‌شود.</span></div>
            <div class="flex top">${icon('frame', 16)}<span><b>۲. اندازه:</b> سوژه بدون تغییر نسبت ابعاد بزرگ یا کوچک می‌شود. بُعدی که زودتر به فاصله‌ی تعیین‌شده می‌رسد (عرض یا ارتفاع) اندازه را تعیین می‌کند و بُعد دیگر به همان نسبت تغییر می‌کند.</span></div>
            <div class="flex top">${icon('target', 16)}<span><b>۳. مرکز:</b> سوژه وسط بوم نهایی قرار می‌گیرد. همه‌ی محصولات به یک اندازه دیده می‌شوند.</span></div>
          </div></div>
        <div class="card"><div class="card-h"><h3>ساختار خروجی</h3></div><div class="card-b"><div class="tree" id="bg-tree">${bgTree({ rembg: true, align: true })}</div></div></div>
      </div>
    </div>
    <div class="card mt16"><div class="card-h"><h2>پیش‌نمایش قبل و بعد</h2><span class="sub">کادر نارنجی: سوژه‌ی شناسایی‌شده · خط‌چین بنفش: حاشیه‌ی تعیین‌شده</span><span class="sp"></span>
        <label class="check small"><input type="checkbox" id="pv-rembg"> با حذف پس‌زمینه (کندتر)</label>
        <label class="btn sm">${icon('upload', 14)} آزمایش با یک تصویر<input type="file" accept="image/*" data-change="pvfile" hidden></label>
        <button class="btn sm soft" data-act="pvfolder">${icon('eye', 14)} نمونه‌های پوشه</button></div>
      <div id="bg-prev"><div class="card-b muted small">مسیر پوشه را وارد کنید و «پیش‌نمایش» را بزنید، یا یک تصویر را برای آزمایش انتخاب کنید. با هر تغییر در قاعده، پیش‌نمایش به‌روز می‌شود.</div></div></div>
    <div class="card mt16"><div class="card-h"><h2>کارهای پردازش تصویر</h2></div><div id="bg-list"></div></div>`;
  },
  async mount(view) {
    BGS.last = null;
    BGS.getAlign = bindAlign(view.querySelector('#bg-align-box'), () => { Bg.syncSteps(); clearTimeout(BGS.t); if (BGS.last) BGS.t = setTimeout(() => Bg.preview(BGS.last), 500); });
    await this.list();
    every(1500, () => this.list(true));
  },
  syncSteps() {
    const st = bgSteps();
    document.getElementById('bg-rembg-box').classList.toggle('hidden', !st.rembg);
    document.getElementById('bg-align-box').classList.toggle('hidden', !st.align);
    document.querySelectorAll('.steps2 .pick').forEach((p) => p.classList.toggle('on', p.querySelector('input').checked));
    document.getElementById('bg-tree').innerHTML = bgTree(st);
    document.getElementById('bg-start-lbl').textContent = st.rembg && st.align ? 'شروع حذف پس‌زمینه و ترازبندی' : st.rembg ? 'شروع حذف پس‌زمینه' : st.align ? 'شروع ترازبندی' : 'مرحله‌ای انتخاب نشده';
    document.getElementById('pv-rembg').checked = !!st.rembg && document.getElementById('pv-rembg').checked;
  },
  async preview(src) {
    BGS.last = src;
    const body = { ...src, options: BGS.getAlign(), rembg: document.getElementById('pv-rembg').checked };
    if (!bgSteps().align) body.options = { ...body.options, trim: 'none', margin: 0, per_side: false };
    await runPreview(document.getElementById('bg-prev'), body);
  },
  async list(silent) {
    const [rows, m] = await Promise.all([api('/api/bg').catch(() => null), api('/api/models').catch(() => null)]);
    if (m) {
      const box = document.getElementById('bg-models');
      const sig = JSON.stringify(m.downloads) + JSON.stringify(m.models.map((x) => x.installed));
      if (box && box.dataset.sig !== sig) { const cur = document.querySelector('input[name=bgmodel]:checked')?.value; box.dataset.sig = sig; box.innerHTML = modelsHtml(m, cur || S.boot.settings.rembg_model); }
    }
    const el = document.getElementById('bg-list');
    if (!rows || !el) return;
    const sig = JSON.stringify(rows.map((r) => [r.id, r.status, r.progress_done]));
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    if (!rows.length) { el.innerHTML = emptyState('frame', 'هنوز کاری اجرا نشده', 'مسیر یک پوشه‌ی تصویر را بدهید.'); return; }
    el.innerHTML = rows.map((r) => {
      const live = ['running', 'pending'].includes(r.status);
      const pct = r.progress_total ? Math.round((r.progress_done / r.progress_total) * 100) : null;
      const o = r.options || {};
      const al = o.align && typeof o.align === 'object' ? o.align : null;
      const steps = [o.rembg !== false ? `حذف پس‌زمینه (${esc(o.model || '')}${o.engine_used ? ' · ' + (o.engine_used === 'rembg' ? 'rembg' : 'موتور داخلی') : ''})` : '',
        al ? `ترازبندی ${al.per_side ? `${fa(al.margin_top)}/${fa(al.margin_right)}/${fa(al.margin_bottom)}/${fa(al.margin_left)}` : fa(al.margin)} پیکسل روی ${fa(al.canvas_w)}×${fa(al.canvas_h)}` : (o.align === undefined ? 'بوم مربعی (نسخه‌ی قبل)' : '')].filter(Boolean).join(' + ');
      const stt = o.stats || {};
      return `<div style="padding:14px 20px;border-bottom:1px solid var(--z-100)">
        <div class="flex wrap"><div class="grow"><div class="pathbox">${esc(r.input_path)}</div><div class="xs muted mt8">خروجی: <span class="ltr">${esc(r.output_path)}</span> · ${jdate(r.created_at)}</div>
          <div class="xs mt8"><span class="tag p">${steps}</span>${stt.upscaled ? ` <span class="tag">${fa(stt.upscaled)} سوژه بزرگ‌نمایی شد</span>` : ''}${stt.low_res ? ` <span class="tag" style="color:var(--warn)">${fa(stt.low_res)} تصویر کم‌کیفیت</span>` : ''}${stt.empty ? ` <span class="tag" style="color:var(--warn)">${fa(stt.empty)} تصویر بدون فضای خالی قابل تشخیص</span>` : ''}</div></div>
          ${chip(r.status)}
          ${live ? `<button class="btn sm" data-act="bgstop" data-id="${r.id}">${icon('pause', 14)} توقف</button>` : r.status !== 'completed' ? `<button class="btn sm soft" data-act="bgresume" data-id="${r.id}">${icon('play', 14)} ادامه</button>` : ''}
          <button class="btn sm soft" data-act="open" data-path="${attr(r.output_path)}">${icon('folder', 14)} پوشه</button>
          ${live ? '' : `<button class="btn sm icon ghost" data-act="bgdel" data-id="${r.id}">${icon('trash', 14)}</button>`}</div>
        <div class="flex mt8"><div class="grow">${progress(pct, live)}</div><span class="small nowrap">${fa(r.progress_done)} از ${fa(r.progress_total)}${r.failed ? ` · <span style="color:var(--err)">${fa(r.failed)} ناموفق</span>` : ''}</span></div>
        ${r.error ? `<div class="alert err mt8">${icon('alert')}<div>${esc(r.error)}</div></div>` : ''}
        ${r.last_file ? `<div class="flex mt8"><img class="thumb checker" style="width:72px;height:72px;object-fit:contain" src="${fileUrl(r.last_file)}&any=1&t=${r.progress_done}" onerror="this.style.display='none'"><span class="xs muted ltr ellipsis">${esc(r.last_file)}</span></div>` : ''}
      </div>`;
    }).join('');
  },
  input: {
    preview: debounce2(async (el) => {
      const v = el.value.trim();
      if (!v) return;
      const r = await api(`/api/bg/preview-output?path=${encodeURIComponent(v)}&rembg=${bgSteps().rembg ? 1 : 0}`);
      document.getElementById('bg-hint').innerHTML = r.exists
        ? `${fa(r.images)} تصویر پیدا شد. خروجی: <span class="kbd">${esc(r.output)}</span>`
        : `<span style="color:var(--err)">این مسیر وجود ندارد.</span>`;
    }),
  },
  change: {
    steps: () => { Bg.syncSteps(); const i = document.getElementById('bg-in'); if (i.value.trim()) Bg.input.preview(i); },
    pvfile: async (el) => {
      const f = el.files[0];
      if (!f) return;
      Bg.preview({ data_url: await fileToDataUrl(f), file_name: f.name });
      el.value = '';
    },
  },
  act: {
    start: async () => {
      const st = bgSteps();
      if (!st.rembg && !st.align) { toast('دست‌کم یک مرحله را انتخاب کنید.', 'err'); return; }
      const model = document.querySelector('input[name=bgmodel]:checked')?.value;
      await api('/api/bg', { body: {
        input_path: document.getElementById('bg-in').value.trim(), output_path: document.getElementById('bg-out').value.trim(),
        model, rembg: st.rembg, align: st.align ? BGS.getAlign() : false, overwrite: document.getElementById('bg-over').checked,
        keep_intermediate: document.getElementById('bg-keepint').checked,
      } });
      okToast(st.rembg && st.align ? 'حذف پس‌زمینه و ترازبندی آغاز شد.' : st.rembg ? 'حذف پس‌زمینه آغاز شد.' : 'ترازبندی آغاز شد.');
      Bg.list();
    },
    pvfolder: () => {
      const p = document.getElementById('bg-in').value.trim();
      if (!p) { toast('ابتدا مسیر پوشه‌ی تصاویر را وارد کنید یا یک تصویر برای آزمایش انتخاب کنید.', 'err'); return; }
      Bg.preview({ path: p });
      document.getElementById('bg-prev').scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    savealign: async () => {
      await api('/api/settings', { method: 'PUT', body: { image_align: BGS.getAlign() } });
      await refreshBoot();
      okToast('قاعده‌ی ترازبندی پیش‌فرض شد (خروجی‌ساز و کارهای بعدی).');
    },
    dl: async (el) => { await api(`/api/models/${el.dataset.name}/download`, { body: {} }); toast('دانلود مدل آغاز شد.'); },
    bgstop: async (el) => { await api(`/api/bg/${el.dataset.id}/stop`, { body: {} }); },
    bgresume: async (el) => { await api(`/api/bg/${el.dataset.id}/resume`, { body: {} }); },
    bgdel: async (el) => { await api(`/api/bg/${el.dataset.id}/delete`, { body: {} }); Bg.list(); },
    open: (el) => openPath(el.dataset.path),
  },
};

function modelsHtml(m, current) {
  return `<div class="stack">${m.models.map((x) => {
    const d = m.downloads[x.name] || {};
    const dl = d.status === 'running' ? `<span class="xs muted nowrap">${icon('loader', 14, 'spin')} ${d.total ? fa(Math.round(d.done / d.total * 100)) + '٪' : '…'}</span>`
      : x.installed ? '<span class="chip ok">نصب است</span>' : `<button class="btn xs soft" data-act="dl" data-name="${x.name}">${icon('download', 13)} دانلود ${fa(x.mb)} مگابایت</button>`;
    return `<label class="pick ${x.name === current ? 'on' : ''}" style="padding:9px 12px;margin-top:6px">
      <input type="radio" name="bgmodel" value="${x.name}" ${x.name === current ? 'checked' : ''} style="accent-color:var(--primary)" onchange="document.querySelectorAll('#bg-models .pick').forEach(p=>p.classList.toggle('on', p.contains(this)))">
      <div class="grow"><b class="small">${esc(x.label)}</b><div class="xs muted ltr" style="text-align:right">${esc(x.name)}</div></div>${dl}${d.status === 'error' ? `<span class="xs" style="color:var(--err)">${esc(trunc(d.error, 40))}</span>` : ''}</label>`;
  }).join('')}</div>`;
}

function debounce2(fn) { let t; return (el) => { clearTimeout(t); t = setTimeout(() => fn(el), 450); }; }

// ======================================================================
// نگاشت‌ها
// ======================================================================
const MP = { kind: 'category' };
export const Mappings = {
  title: 'نگاشت برند و دسته',
  crumb: 'اتصال مقادیر منبع به اسلاگ‌های مگا کارز',
  async render() {
    return `
    <div class="alert p mb16">${icon('info')}<div>هر برند یا دسته‌ی منبع فقط یک بار به اسلاگ مگا کارز وصل می‌شود و در همه‌ی خروجی‌های بعدی خودکار به‌کار می‌رود. مقادیر نگاشت‌نشده در خروجی با اسلاگ پیشنهادی پر و در هشدارها علامت‌گذاری می‌شوند.</div></div>
    <div class="card">
      <div class="tabs" id="mp-tabs"></div>
      <div id="mp-body"></div>
    </div>`;
  },
  async mount() { await this.draw(); },
  async draw() {
    document.getElementById('mp-tabs').innerHTML = [['category', 'layers', 'دسته‌بندی (category_slug)'], ['brand', 'hash', 'برند (brand_slug)']]
      .map(([k, ic, l]) => `<button class="${MP.kind === k ? 'on' : ''}" data-act="kind" data-k="${k}">${icon(ic, 16)} ${l}</button>`).join('');
    const [un, maps, targets] = await Promise.all([api('/api/mappings/unmapped'), api(`/api/mappings?kind=${MP.kind}`), api('/api/mappings/targets')]);
    const list = un[MP.kind] || [];
    const dl = `<datalist id="mp-targets">${targets.filter((t) => t.kind === MP.kind).map((t) => `<option value="${attr(t.target_slug)}">${esc(t.target_label || '')}</option>`).join('')}</datalist>`;
    document.getElementById('mp-body').innerHTML = `${dl}
      <div class="card-h"><h3>مقادیر نگاشت‌نشده</h3><span class="sub">${fa(list.length)} مورد</span><span class="sp"></span>${list.length ? `<button class="btn sm soft" data-act="aimap">${icon('sparkles', 14)} پیشنهاد اسلاگ با AI</button><button class="btn sm primary" data-act="saveall">${icon('save', 14)} ذخیره‌ی همه</button>` : ''}</div>
      ${list.length ? `<table class="tbl"><thead><tr><th>مقدار در منبع</th><th>منبع</th><th>تعداد محصول</th><th style="width:300px">اسلاگ مگا کارز</th><th>دامنه</th><th></th></tr></thead><tbody>
        ${list.map((u, i) => `<tr data-row="${i}" data-src="${u.source_id}" data-val="${attr(u.value)}"><td><b>${esc(u.value)}</b></td><td class="small">${esc(u.source_name)}</td><td>${num(u.count)}</td>
          <td><input class="inp sm ltr" list="mp-targets" data-t value="" placeholder="${attr(u.suggested)}" data-ai="1" data-ai-format="slug" data-ai-label="اسلاگ انگلیسی برای ${attr(MP.kind === 'brand' ? 'برند' : 'دسته')} «${attr(u.value)}»"><div class="xs muted" data-lbl></div></td>
          <td><select class="inp sm" data-scope><option value="source">فقط همین منبع</option><option value="global">همه‌ی منابع</option></select></td>
          <td><button class="btn xs soft" data-act="saveone" data-i="${i}">${icon('check', 13)} ثبت</button></td></tr>`).join('')}</tbody></table>`
        : `<div class="card-b">${emptyState('checkCircle', 'همه‌ی مقادیر نگاشت شده‌اند', 'مقدار تازه‌ای در بانک‌های داده پیدا نشد.')}</div>`}
      <div class="card-h" style="border-top:1px solid var(--z-100)"><h3>نگاشت‌های ثبت‌شده</h3><span class="sub">${fa(maps.length)} مورد</span><span class="sp"></span><button class="btn sm" data-act="import">${icon('upload', 14)} درون‌ریزی گروهی</button></div>
      ${maps.length ? `<table class="tbl"><thead><tr><th>مقدار در منبع</th><th>منبع</th><th>اسلاگ</th><th>برچسب</th><th></th></tr></thead><tbody>
        ${maps.map((m) => `<tr><td>${esc(m.source_value)}</td><td class="small">${m.source_id ? esc(m.source_name || '') : '<span class="tag">همه‌ی منابع</span>'}</td><td class="ltr"><span class="tag p">${esc(m.target_slug)}</span></td><td class="small">${esc(m.target_label || '')}</td>
        <td><button class="btn xs ghost danger" data-act="delmap" data-id="${m.id}">${icon('trash', 13)}</button></td></tr>`).join('')}</tbody></table>` : '<div class="card-b muted small">هنوز نگاشتی ثبت نشده است.</div>'}`;
  },
  act: {
    kind: (el) => { MP.kind = el.dataset.k; Mappings.draw(); },
    saveone: async (el) => { const tr = el.closest('tr'); await saveRows([tr]); },
    saveall: async () => { await saveRows([...document.querySelectorAll('tr[data-row]')]); },
    aimap: async (el) => {
      const trs = [...document.querySelectorAll('tr[data-row]')];
      const targets = [...document.querySelectorAll('#mp-targets option')].map((o) => o.value);
      busy(el, true);
      try {
        const r = await assist('mappings', { kind: MP.kind, values: trs.map((t) => t.dataset.val), targets });
        const by = Object.fromEntries(r.rows.map((x) => [x.source_value, x]));
        trs.forEach((t) => {
          const x = by[t.dataset.val];
          if (!x) return;
          const inp = t.querySelector('[data-t]');
          if (!inp.value) inp.value = x.target_slug;
          t.dataset.label = x.target_label || '';
          t.querySelector('[data-lbl]').textContent = x.target_label || '';
        });
        okToast(`${fa(r.rows.length)} اسلاگ پیشنهاد شد؛ بررسی و «ذخیره‌ی همه» را بزنید.`);
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    delmap: async (el) => { await api(`/api/mappings/${el.dataset.id}`, { method: 'DELETE' }); Mappings.draw(); },
    import: () => {
      const l = openLayer('modal', `<div class="card-h"><h3>درون‌ریزی گروهی نگاشت‌ها</h3></div><div class="card-b">
        <div class="hint mb8">هر خط: <span class="kbd">مقدار منبع , اسلاگ , برچسب (اختیاری)</span> — برای «${MP.kind === 'brand' ? 'برند' : 'دسته‌بندی'}» و همه‌ی منابع.</div>
        <textarea class="inp mono" rows="10" id="imp" placeholder="روغن موتور, engine-oil, روغن موتور\nکاسپین, caspian"></textarea></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="imp-ok">درون‌ریزی</button></div>`);
      l.box.querySelector('#imp-ok').addEventListener('click', async () => {
        const rows = l.box.querySelector('#imp').value.split('\n').map((x) => x.split(/[,،\t]/).map((s) => s.trim())).filter((x) => x[0] && x[1])
          .map((x) => ({ kind: MP.kind, source_value: x[0], target_slug: x[1], target_label: x[2] || '' }));
        const r = await api('/api/mappings', { body: { rows } });
        okToast(`${fa(r.saved)} نگاشت ثبت شد.`); l.close(); Mappings.draw();
      });
    },
  },
};

async function saveRows(trs) {
  const rows = trs.map((tr) => {
    const inp = tr.querySelector('[data-t]');
    const v = inp.value.trim() || inp.placeholder;
    return { kind: MP.kind, source_value: tr.dataset.val, target_slug: v, target_label: tr.dataset.label || '', source_id: tr.querySelector('[data-scope]').value === 'source' ? Number(tr.dataset.src) : null };
  }).filter((r) => r.target_slug);
  const r = await api('/api/mappings', { body: { rows } });
  okToast(`${fa(r.saved)} نگاشت ثبت شد.`);
  Mappings.draw();
}

export const Settings = {
  title: 'تنظیمات',
  crumb: 'مسیرها، مرورگر، سرعت و تصاویر',
  async render() {
    const [st, sys] = await Promise.all([api('/api/settings'), api('/api/system')]);
    const dict = Object.entries(st.slug_dictionary || {}).map(([k, v]) => `${k} = ${v}`).join('\n');
    return `
    <div class="grid g-side">
      <div class="card">
        <div class="card-h"><h2>تنظیمات عمومی</h2></div>
        <div class="card-b">
          <div class="form-grid">
            <div class="field full"><label>مسیر پیش‌فرض خروجی‌ها</label><div class="inp-group"><input class="inp ltr" id="s-out" value="${attr(st.output_root)}"><button class="btn" data-act="open" data-path="${attr(st.output_root)}">${icon('folder', 16)}</button></div>
              <div class="hint">مثلاً <span class="kbd">D:\\Catalog</span>. پوشه در صورت نبود ساخته می‌شود.</div></div>
            <div class="field"><label>مرورگر</label><select class="inp" id="s-browser">
              ${[['auto', 'خودکار (Edge، سپس Chrome، سپس Chromium)'], ['msedge', 'Microsoft Edge'], ['chrome', 'Google Chrome'], ['chromium', 'Chromium پلی‌رایت']].map(([k, l]) => `<option value="${k}" ${st.browser_channel === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
              <div class="hint">Edge روی همه‌ی ویندوزها نصب است و نیازی به دانلود مرورگر جداگانه نیست.</div></div>
            <div class="field"><label>نمایش مرورگر</label><select class="inp" id="s-headless"><option value="1" ${st.headless ? 'selected' : ''}>پنهان (سریع‌تر)</option><option value="0" ${!st.headless ? 'selected' : ''}>قابل مشاهده</option></select></div>
            <div class="field"><label>کمترین مکث بین درخواست‌ها (میلی‌ثانیه)</label><input class="inp" id="s-dmin" type="number" value="${st.delay_min_ms}"></div>
            <div class="field"><label>بیشترین مکث بین درخواست‌ها (میلی‌ثانیه)</label><input class="inp" id="s-dmax" type="number" value="${st.delay_max_ms}"><div class="hint">مکث تصادفی بین این دو عدد، فشار روی منبع و احتمال مسدود شدن را کم می‌کند.</div></div>
            <div class="field"><label>مهلت بارگذاری صفحه (ثانیه)</label><input class="inp" id="s-timeout" type="number" value="${st.page_timeout_s}"></div>
            <div class="field"><label>تعداد تلاش خودکار پیش از پرسیدن</label><input class="inp" id="s-retries" type="number" value="${st.max_retries}"></div>
            <div class="field"><label>دانلود هم‌زمان تصاویر</label><input class="inp" id="s-workers" type="number" value="${st.image_download_workers}"></div>
            <div class="field"><label class="check" style="height:42px"><input type="checkbox" id="s-block" ${st.block_heavy_resources ? 'checked' : ''}> عدم بارگذاری تصویر/فونت در مرورگر (سریع‌تر)</label></div>
          </div>
          <hr class="sep">
          <div class="form-grid">
            <div class="field"><label>مدل پیش‌فرض حذف پس‌زمینه</label><select class="inp" id="s-model">${sys.models.map((m) => `<option value="${m.name}" ${st.rembg_model === m.name ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select></div>
            <div class="field"><label>شناسه‌ی مرورگر (User-Agent)</label><input class="inp ltr" id="s-ua" value="${attr(st.user_agent)}"></div>
          </div>
          <div class="field mt16" id="s-align"><label>قاعده‌ی پیش‌فرض ترازبندی تصاویر</label>
            <div class="hint mb8">در خروجی‌ساز و «پردازش تصاویر» استفاده می‌شود. پیش‌نمایش قبل/بعد در <a href="#/bg">پردازش تصاویر</a>.</div>${alignEditor(st.image_align)}</div>
          <hr class="sep">
          <div class="field"><label>واژه‌نامه‌ی اسلاگ</label>
            <textarea class="inp mono" id="s-dict" rows="7" placeholder="ایرانول = iranol\nموتورسیکلت = motorcycle">${esc(dict)}</textarea>
            <div class="hint">هر خط «واژه‌ی فارسی = معادل انگلیسی». واژه‌هایی که این‌جا نیستند، حرف‌به‌حرف به لاتین برگردانده می‌شوند. اولویت با عنوان انگلیسی منبع است.</div></div>
        </div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn primary" data-act="save">${icon('save', 16)} ذخیره</button></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h3>وضعیت سیستم</h3></div><div class="card-b">
          <dl class="kv">
            <dt>Python</dt><dd class="ltr">${esc(sys.python)}</dd>
            <dt>سیستم‌عامل</dt><dd class="ltr small">${esc(sys.platform)}</dd>
            <dt>Playwright</dt><dd>${sys.playwright ? '<span class="chip ok">نصب است</span>' : '<span class="chip err">نصب نیست</span>'}</dd>
            <dt>ONNX Runtime</dt><dd>${sys.onnxruntime ? `<span class="chip ok">${esc(sys.onnxruntime)}</span>` : '<span class="chip err">نصب نیست</span>'}</dd>
            <dt>کتابخانه‌ی rembg</dt><dd>${sys.rembg_lib ? '<span class="chip ok">نصب است</span>' : '<span class="chip info">موتور داخلی فعال است</span>'}</dd>
            <dt>داده‌ها</dt><dd class="ltr small">${esc(sys.data_dir)}</dd>
            <dt>مدل‌ها</dt><dd class="ltr small">${esc(sys.models_dir)}</dd>
          </dl>
          <div class="btns mt16"><button class="btn soft" data-act="checkbrowser">${icon('globe', 16)} آزمایش اجرای مرورگر</button><span class="small" id="cb"></span></div>
        </div></div>
      </div>
    </div>`;
  },
  mount(view) { bindAlign(view.querySelector('#s-align')); },
  act: {
    open: (el) => openPath(el.dataset.path),
    checkbrowser: async () => {
      const el = document.getElementById('cb');
      el.innerHTML = `${icon('loader', 15, 'spin')} در حال اجرا…`;
      const r = await api('/api/system/check-browser', { body: {} });
      el.innerHTML = r.ok ? `<span class="chip ok">مرورگر اجرا شد: ${esc(r.channel)}</span>` : `<span class="chip err">${esc(r.error)}</span>`;
    },
    save: async () => {
      const dict = {};
      document.getElementById('s-dict').value.split('\n').forEach((l) => { const [a, b] = l.split('='); if (a && b) dict[a.trim()] = b.trim(); });
      await api('/api/settings', { method: 'PUT', body: {
        output_root: document.getElementById('s-out').value.trim(), browser_channel: document.getElementById('s-browser').value,
        headless: document.getElementById('s-headless').value === '1', delay_min_ms: Number(document.getElementById('s-dmin').value),
        delay_max_ms: Number(document.getElementById('s-dmax').value), page_timeout_s: Number(document.getElementById('s-timeout').value),
        max_retries: Number(document.getElementById('s-retries').value), image_download_workers: Number(document.getElementById('s-workers').value),
        block_heavy_resources: document.getElementById('s-block').checked, rembg_model: document.getElementById('s-model').value,
        image_align: readAlign(document.getElementById('s-align')),
        user_agent: document.getElementById('s-ua').value.trim(), slug_dictionary: dict,
      } });
      await refreshBoot();
      okToast('تنظیمات ذخیره شد.');
    },
  },
};
