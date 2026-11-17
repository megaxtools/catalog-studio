// پنجره‌ی ورود فایل مشترک در همه‌ی بخش‌ها: راهنمای قالب (ستون‌ها)، دانلود فایل نمونه، تحلیل فایل و نگاشت سرستون‌ها (با AI)، و گزارش نتیجه
import { api, icon, esc, attr, fa, num, okToast, errToast, openLayer, toast, S } from './core.js';
import { busy } from './ai_assist.js';
import { fileToDataUrl } from './widgets.js';

const aiOn = () => (S.boot?.modules || {}).ai !== false;
let SPECS = null;
async function specs() { if (!SPECS) SPECS = await api('/api/import/specs'); return SPECS; }

const TARGETS = {
  brand: { url: '/api/ref/brand/import', label: 'برندها', update: true },
  category: { url: '/api/ref/category/import', label: 'دسته‌بندی‌ها', update: true },
  vehicles: { url: '/api/vehicles/import', label: 'خودروها' },
  raw: { url: '/api/datasets/import-file', label: 'داده‌ی خام محصولات' },
};

export function sampleLinks(kind, cls = 'btn sm') {
  return ['xlsx', 'csv', 'json'].map((f) => `<a class="${cls}" href="/api/import/sample/${kind}?format=${f}" download>${icon('download', 13)} نمونه‌ی ${f === 'xlsx' ? 'Excel' : f.toUpperCase()}</a>`).join('');
}

export function formatTable(sp) {
  return `<div class="tbl-wrap" style="max-height:260px"><table class="tbl"><thead><tr><th>سرستون (انگلیسی)</th><th>یا فارسی</th><th>توضیح</th><th>مثال</th></tr></thead><tbody>
    ${sp.columns.map((c) => `<tr><td class="ltr mono small nowrap">${esc(c.key)}${c.required ? ' <span class="tag err">اجباری</span>' : ''}</td><td class="small nowrap">${esc(c.header_fa)}</td>
      <td class="xs muted">${esc(c.desc)}</td><td class="xs ltr" style="max-width:220px;white-space:pre-wrap">${esc(String(c.example ?? ''))}</td></tr>`).join('')}</tbody></table></div>`;
}

/**
 * پنجره‌ی ورود. opts: {onDone(result), schemas (برای raw), title}
 */
export async function openImportDialog(kind, opts = {}) {
  const sp = (await specs())[kind];
  const tg = TARGETS[kind];
  const st = { file: null, dataUrl: '', an: null, mapping: {} };
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('upload', 18)} ورود ${esc(tg.label)} از فایل</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" id="im-body">
      <div class="alert info">${icon('info')}<div class="grow"><div class="small">${esc(sp.intro)}</div>
        <div class="xs muted mt4">قالب‌های قابل‌قبول: Excel (xlsx، فقط شیت اول)، CSV (UTF-8) و JSON (آرایه‌ای از اشیاء). سرستون‌ها می‌توانند انگلیسی یا فارسی باشند.</div></div></div>
      <div class="flex wrap mt12" style="gap:6px"><b class="small">فایل نمونه:</b>${sampleLinks(kind)}</div>
      <details class="mt12" ${kind === 'raw' ? '' : 'open'}><summary class="small" style="cursor:pointer"><b>ستون‌های فایل</b></summary><div class="mt8">${formatTable(sp)}</div></details>
      <div class="drop mt16" id="im-drop"><label class="btn primary">${icon('upload', 16)} انتخاب فایل<input type="file" accept="${sp.accept}" id="im-file" hidden></label>
        <span class="small muted" id="im-fname">یا فایل را این‌جا رها کنید</span></div>
      <div id="im-an"></div>
      ${kind === 'raw' ? `<div class="form-grid mt12" id="im-opts"><div class="field"><label>عنوان بانک داده</label><input class="inp" id="im-title" placeholder="مثلاً «روغن موتور — فایل تأمین‌کننده»"></div>
        <div class="field"><label>اسکیما</label><select class="inp" id="im-schema">${(opts.schemas || S.boot?.schemas || []).filter((s) => ['general', 'extract'].includes(s.usage || 'general')).map((s) => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
        <div class="field"><label>برچسب دسته‌بندی (اختیاری)</label><input class="inp" id="im-cat" placeholder="برای محصولاتی که ستون دسته ندارند"></div></div>` : ''}
      ${tg.update ? '<label class="check mt12"><input type="checkbox" id="im-upd" checked> موارد موجود (همان اسلاگ یا نام) به‌روز شوند</label>' : ''}
      <div id="im-res"></div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>بستن</button><button class="btn primary" id="im-go" disabled>${icon('upload', 16)} ورود</button></div>`, { wide: true });
  const b = l.box;
  const go = b.querySelector('#im-go');

  const drawMap = () => {
    const an = st.an;
    const opt = (h) => `<select class="inp sm" data-h="${attr(h)}"><option value="">— نادیده گرفته شود${kind === 'raw' ? ' (در داده‌ی خام می‌ماند)' : ''} —</option>
      ${sp.columns.map((c) => `<option value="${c.key}" ${st.mapping[h] === c.key ? 'selected' : ''}>${esc(c.header_fa)} (${c.key})</option>`).join('')}</select>`;
    const req = sp.columns.filter((c) => c.required).map((c) => c.key);
    const missing = req.filter((k) => !Object.values(st.mapping).includes(k));
    b.querySelector('#im-an').innerHTML = `<div class="card mt16"><div class="card-h"><h3>${icon('columns', 16)} ستون‌های فایل: ${fa(an.headers.length)} ستون، ${num(an.rows)} ردیف</h3><span class="sp"></span>
        ${aiOn() ? `<button class="btn sm soft" id="im-ai">${icon('sparkles', 14)} تطبیق ستون‌ها با AI</button>` : ''}</div>
      ${missing.length ? `<div class="alert err" style="margin:12px">${icon('alert')}<div>ستون اجباری «${missing.map((k) => esc(sp.columns.find((c) => c.key === k).header_fa)).join('، ')}» مشخص نشده است. آن را به یکی از ستون‌های فایل وصل کنید.</div></div>` : ''}
      <div class="tbl-wrap" style="max-height:300px"><table class="tbl"><thead><tr><th>سرستون در فایل</th><th>نمونه‌ی مقدار</th><th style="width:300px">فیلد استودیو</th></tr></thead><tbody>
      ${an.headers.map((h) => `<tr><td class="small"><b>${esc(h)}</b></td><td class="xs muted">${esc(String(an.preview[0]?.[h] ?? '')).slice(0, 80)}</td><td>${opt(h)}</td></tr>`).join('')}</tbody></table></div></div>`;
    go.disabled = missing.length > 0;
    b.querySelectorAll('[data-h]').forEach((s) => s.addEventListener('change', () => {
      const v = s.value;
      if (v) Object.keys(st.mapping).forEach((h) => { if (st.mapping[h] === v) st.mapping[h] = ''; });
      st.mapping[s.dataset.h] = v;
      drawMap();
    }));
    const ai = b.querySelector('#im-ai');
    if (ai) ai.addEventListener('click', async () => {
      busy(ai, true, 'در حال تطبیق…');
      try {
        const r = await api('/api/import/ai-map', { body: { kind, headers: an.headers, preview: an.preview } });
        let n = 0;
        Object.entries(r.mapping).forEach(([h, k]) => { if (k && st.mapping[h] !== k) { Object.keys(st.mapping).forEach((x) => { if (st.mapping[x] === k) st.mapping[x] = ''; }); st.mapping[h] = k; n++; } });
        okToast(n ? `${fa(n)} ستون با هوش مصنوعی تطبیق داده شد؛ بررسی کنید.` : 'تطبیق تازه‌ای پیشنهاد نشد.');
        drawMap();
      } catch (e) { errToast(e); busy(ai, false); }
    });
  };

  const pick = async (f) => {
    if (!f) return;
    st.file = f;
    b.querySelector('#im-fname').textContent = f.name;
    b.querySelector('#im-res').innerHTML = '';
    try {
      st.dataUrl = await fileToDataUrl(f);
      st.an = await api('/api/import/analyze', { body: { kind, data_url: st.dataUrl, name: f.name } });
      st.mapping = { ...st.an.mapping };
      if (!st.an.rows) { toast('فایل ردیفی ندارد.', 'err'); return; }
      if (kind === 'raw' && !b.querySelector('#im-title').value) b.querySelector('#im-title').value = f.name.replace(/\.\w+$/, '');
      drawMap();
    } catch (e) { errToast(e); }
  };
  b.querySelector('#im-file').addEventListener('change', (e) => pick(e.target.files[0]));
  const drop = b.querySelector('#im-drop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('on'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('on'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('on'); pick(e.dataTransfer.files[0]); });

  go.addEventListener('click', async () => {
    busy(go, true, 'در حال ورود…');
    try {
      const body = { data_url: st.dataUrl, name: st.file.name, mapping: st.mapping };
      if (tg.update) body.update = b.querySelector('#im-upd').checked;
      if (kind === 'raw') Object.assign(body, { title: b.querySelector('#im-title').value, schema_id: Number(b.querySelector('#im-schema').value) || null, category_label: b.querySelector('#im-cat').value });
      const r = await api(tg.url, { body });
      let msg;
      if (kind === 'raw') msg = `بانک داده‌ی «${r.title}» با ${fa(r.counts?.done ?? r.total_found)} محصول ساخته شد.`;
      else if (kind === 'vehicles') msg = `افزوده شد: ${fa(r.added.brand)} برند، ${fa(r.added.model)} مدل، ${fa(r.added.trim)} تیپ${r.updated ? `، ${fa(r.updated)} مورد تکمیل شد` : ''}.`;
      else msg = `${fa(r.added)} مورد افزوده و ${fa(r.updated)} مورد به‌روز شد${r.skipped ? `، ${fa(r.skipped)} مورد رد شد` : ''}.`;
      const errs = r.errors || [];
      b.querySelector('#im-res').innerHTML = `<div class="alert ${errs.length ? 'warn' : 'ok'} mt16">${icon(errs.length ? 'alert' : 'checkCircle')}<div class="grow"><b class="small">${esc(msg)}</b>
        ${errs.length ? `<ul class="xs mt4" style="margin:4px 16px 0">${errs.slice(0, 12).map((x) => `<li>${esc(typeof x === 'string' ? x : x.error)}</li>`).join('')}</ul>` : ''}</div></div>`;
      okToast(msg);
      go.disabled = true;
      busy(go, false);
      go.disabled = true;
      if (opts.onDone) opts.onDone(r);
      if (kind === 'raw' && r.id) { l.close(); location.hash = `#/datasets/${r.id}`; }
    } catch (e) { errToast(e); busy(go, false); }
  });
  return l;
}
