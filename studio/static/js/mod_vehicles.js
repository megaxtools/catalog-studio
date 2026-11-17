// ماژول خودروها: بانک مرجع خودروها (برند ← مدل ← تیپ) و انتخابگر «سازگاری با خودرو»
import { api, icon, esc, attr, fa, num, okToast, errToast, openLayer, confirmDlg, emptyState, toast, debounce, S } from './core.js';
import { busy, noProviderHint } from './ai_assist.js';
import { fileToDataUrl } from './widgets.js';

const LV = { brand: 'برند', model: 'مدل', trim: 'تیپ' };
const V = { brands: [], sel: null, q: '' };

export const Vehicles = {
  title: 'خودروها',
  crumb: 'داده‌های مرجع · بانک خودروها؛ سازگاری محصولات فقط از همین فهرست انتخاب می‌شود',
  top: () => `<button class="btn" data-act="export">${icon('download', 16)} خروجی Excel</button>
    <button class="btn" data-act="importdlg">${icon('upload', 16)} ورود از فایل</button>
    ${(S.boot?.modules || {}).ai !== false ? `<button class="btn soft" data-act="aien">${icon('sparkles', 16)} نام انگلیسی با AI</button>` : ''}
    <button class="btn primary" data-act="addbrand">${icon('plus', 16)} برند</button>`,
  async render() {
    const st = await api('/api/vehicles/stats');
    return `<div class="kpis">
        <div class="kpi"><span>برندها</span><b>${num(st.brands)}</b></div><div class="kpi"><span>مدل‌ها</span><b>${num(st.models)}</b></div>
        <div class="kpi"><span>تیپ‌ها</span><b>${num(st.trims)}</b></div><div class="kpi"><span>نام انگلیسی خودکار (نیاز به بازبینی)</span><b>${num(st.auto_en)}</b></div></div>
      <div class="split mt16"><div class="card"><div class="card-h"><input class="inp sm" placeholder="جست‌وجوی برند…" data-input="bq" style="width:100%"></div><div id="vb-list" class="pick-list" style="max-height:70vh;padding:8px"></div></div>
        <div><div class="card"><div class="card-b"><input class="inp" placeholder="جست‌وجو در همه‌ی خودروها (مثلاً «۲۰۶ تیپ ۲» یا peugeot)…" data-input="gq"></div><div id="vg-res"></div></div>
          <div class="card mt16" id="vb-detail">${emptyState('car', 'یک برند انتخاب کنید', 'مدل‌ها و تیپ‌های هر برند این‌جا نمایش داده می‌شود؛ نام، نام انگلیسی و اسلاگ هر مورد قابل ویرایش است.')}</div></div></div>`;
  },
  async mount() { await this.load(); },
  async load() {
    V.brands = await api('/api/vehicles/brands');
    this.drawBrands();
    if (V.sel) this.open(V.sel);
  },
  drawBrands() {
    const q = V.q.toLowerCase();
    const el = document.getElementById('vb-list');
    if (!el) return;
    el.innerHTML = V.brands.filter((b) => !q || `${b.name} ${b.name_en} ${b.slug}`.toLowerCase().includes(q)).map((b) =>
      `<button class="pick ${V.sel === b.id ? 'on' : ''}" data-act="brand" data-id="${b.id}"><b>${esc(b.name)}</b><span class="xs muted ltr">${esc(b.name_en)}</span>
        <span class="grow"></span><span class="xs muted">${fa(b.models)} مدل</span>${b.auto_en ? `<span class="edot" title="نام انگلیسی خودکار"></span>` : ''}${b.active ? '' : '<span class="tag">غیرفعال</span>'}</button>`).join('');
  },
  async open(id) {
    V.sel = id;
    this.drawBrands();
    const b = await api(`/api/vehicles/brands/${id}/tree`);
    const row = (lv, x, extra = '') => `<div class="vrow ${lv}" data-lv="${lv}" data-id="${x.id}">
      <span class="tag" style="font-size:10.5px">${LV[lv]}</span>
      <input class="inp sm" data-f="name" value="${attr(x.name)}" style="max-width:220px">
      <input class="inp sm ltr" data-f="name_en" data-ai="1" data-ai-format="english" data-ai-label="نام انگلیسی خودرو" value="${attr(x.name_en)}" placeholder="English" style="max-width:200px">
      <input class="inp sm ltr mono" data-f="slug" value="${attr(x.slug)}" style="max-width:180px">
      ${x.auto_en ? '<span class="xs" style="color:var(--warn)" title="نام انگلیسی خودکار ساخته شده؛ بازبینی کنید">خودکار</span>' : ''}
      <label class="check xs"><input type="checkbox" data-f="active" ${x.active ? 'checked' : ''}> فعال</label>
      <button class="btn xs soft" data-act="vsave">${icon('save', 12)}</button>${extra}
      <button class="btn xs ghost danger" data-act="vdel">${icon('trash', 12)}</button></div>`;
    document.getElementById('vb-detail').innerHTML = `<div class="card-h"><h3>${esc(b.name)}</h3><span class="sub ltr">${esc(b.slug)} · ${fa(b.models.length)} مدل</span><span class="sp"></span>
        <button class="btn sm soft" data-act="addmodel" data-brand="${b.id}">${icon('plus', 14)} مدل</button></div>
      <div class="card-b">${row('brand', b)}
        <div class="mt12">${b.models.map((m) => `<div class="vmodel">${row('model', m, `<button class="btn xs ghost" data-act="addtrim" data-model="${m.id}">${icon('plus', 12)} تیپ</button>`)}
          ${m.trims.map((t) => row('trim', t)).join('')}</div>`).join('') || '<div class="muted small">مدلی ثبت نشده است.</div>'}</div>
        <div class="hint mt12">اسلاگ‌ها فقط انگلیسی‌اند و در خروجی کاتالوگ استفاده می‌شوند (مثل peugeot/206/type-2). برای نام‌های خودکار، «نام انگلیسی با AI» را بزنید یا دستی اصلاح کنید.</div></div>`;
  },
  act: {
    importdlg: async () => (await import("./import_ui.js")).openImportDialog("vehicles", { onDone: () => Vehicles.load() }),
    brand: (el) => Vehicles.open(Number(el.dataset.id)),
    vsave: async (el) => {
      const r = el.closest('.vrow');
      const body = {};
      r.querySelectorAll('[data-f]').forEach((x) => { body[x.dataset.f] = x.type === 'checkbox' ? x.checked : x.value.trim(); });
      await api(`/api/vehicles/${r.dataset.lv}/${r.dataset.id}`, { method: 'PUT', body });
      okToast('ذخیره شد (نسخه‌ی تازه ثبت شد).');
      Vehicles.load();
    },
    vdel: async (el) => {
      const r = el.closest('.vrow');
      if (!(await confirmDlg('حذف', 'این مورد از بانک خودروها حذف شود؟ اگر محصولی به آن وصل باشد حذف نمی‌شود؛ به‌جایش «غیرفعال» کنید.', 'حذف', true))) return;
      await api(`/api/vehicles/${r.dataset.lv}/${r.dataset.id}`, { method: 'DELETE' });
      okToast('حذف شد.');
      if (r.dataset.lv === 'brand') V.sel = null;
      Vehicles.load();
    },
    addbrand: () => addItem('brand', {}),
    addmodel: (el) => addItem('model', { brand_id: Number(el.dataset.brand) }),
    addtrim: (el) => addItem('trim', { model_id: Number(el.dataset.model) }),
    export: () => { location.href = '/api/vehicles/export?format=xlsx'; },
    aien: async (el) => {
      if (!(await confirmDlg('نام انگلیسی با هوش مصنوعی', 'برای مواردی که نام انگلیسی‌شان خودکار ساخته شده (حداکثر ۴۰۰ مورد در هر سطح)، نام رسمی انگلیسی پیشنهاد و ذخیره می‌شود. اسلاگ‌ها هم به‌روز شوند؟<div class="hint mt8">اسلاگ‌های تازه فقط در انتشارهای بعدی کاتالوگ اثر دارند.</div>', 'شروع'))) return;
      busy(el, true, 'در حال تکمیل…');
      try {
        const r = await api('/api/vehicles/ai-english', { body: { levels: ['brand', 'model', 'trim'], update_slugs: true } });
        okToast(`به‌روز شد: ${fa(r.brand?.updated || 0)} برند، ${fa(r.model?.updated || 0)} مدل، ${fa(r.trim?.updated || 0)} تیپ.`);
        Vehicles.load();
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    gpick: (el) => { V.sel = Number(el.dataset.brand); Vehicles.open(V.sel); },
  },
  change: {
    import: async (el) => {
      const f = el.files[0];
      if (!f) return;
      const r = await api('/api/vehicles/import', { body: { data_url: await fileToDataUrl(f), name: f.name } });
      okToast(`افزوده شد: ${fa(r.added.brand)} برند، ${fa(r.added.model)} مدل، ${fa(r.added.trim)} تیپ (موارد تکراری نادیده گرفته شدند).`);
      Vehicles.load();
    },
  },
  input: {
    bq: (el) => { V.q = el.value.trim(); Vehicles.drawBrands(); },
    gq: debounce(async (el) => {
      const q = el.value.trim();
      const box = document.getElementById('vg-res');
      if (!q) { box.innerHTML = ''; return; }
      const r = await api(`/api/vehicles/search?q=${encodeURIComponent(q)}&limit=30`);
      box.innerHTML = `<div class="pick-list" style="padding:0 12px 12px">${r.map((p) => `<button class="pick" data-act="gpick" data-brand="${brandIdOf(p)}"><span class="tag" style="font-size:10.5px">${LV[p.t]}</span><b>${esc(p.label)}</b><span class="xs muted ltr">${esc(p.slug_path)}</span></button>`).join('') || '<div class="muted small">چیزی پیدا نشد.</div>'}</div>`;
    }, 300),
  },
};

function brandIdOf(p) {
  const b = V.brands.find((x) => x.slug === p.brand_slug);
  return b ? b.id : '';
}

function addItem(level, parent) {
  const l = openLayer('modal', `<div class="card-h"><h3>افزودن ${LV[level]}</h3></div><div class="card-b form-grid">
      <div class="field"><label>نام فارسی</label><input class="inp" id="ai-n"></div><div class="field"><label>نام انگلیسی (اختیاری)</label><input class="inp ltr" id="ai-e" data-ai="1" data-ai-format="english" data-ai-label="نام انگلیسی خودرو"></div>
      <div class="field"><label>اسلاگ (اختیاری)</label><input class="inp ltr mono" id="ai-s" placeholder="خودکار"></div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ai-ok">${icon('plus', 16)} افزودن</button></div>`);
  l.box.querySelector('#ai-ok').addEventListener('click', async () => {
    try {
      await api(`/api/vehicles/${level}`, { body: { ...parent, name: l.box.querySelector('#ai-n').value, name_en: l.box.querySelector('#ai-e').value, slug: l.box.querySelector('#ai-s').value } });
      okToast(`${LV[level]} افزوده شد.`); l.close(); Vehicles.load();
    } catch (e) { errToast(e); }
  });
}

// ---------------------------------------------------------------------------------------------------------------- انتخابگر سازگاری
// خروجی: مقدار سازگاری ({all:true} یا {all:false, items}) یا undefined (انصراف)
export function openCompatPicker(value, opts = {}) {
  let items = (value && !value.all && value.items) ? value.items.map((x) => ({ ...x })) : [];
  let all = !items.length;
  const labels = new Map();
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('car', 18)} سازگاری با خودرو</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="card-b" style="max-height:74vh;overflow:auto">
        <div class="seg mb12" id="cp-mode"><button data-m="all">سازگار با همه‌ی خودروها</button><button data-m="some">فقط خودروهای مشخص</button></div>
        ${opts.suggestion?.labels?.length ? `<div class="alert info mb12">${icon('sparkles')}<div class="grow"><b>پیشنهاد از روی متن محصول:</b> ${opts.suggestion.labels.map(esc).join('، ')}</div><button class="btn sm soft" id="cp-sug">اعمال</button></div>` : ''}
        <div id="cp-some">
          <div class="lbl mb8">انتخاب‌شده‌ها</div><div id="cp-sel" class="flex wrap" style="gap:6px;min-height:34px"></div>
          <div class="split2 mt16"><div><input class="inp" id="cp-q" placeholder="جست‌وجو: پژو ۲۰۶، سمند سورن، peugeot…"><div id="cp-res" class="pick-list mt8" style="max-height:44vh"></div></div>
            <div><input class="inp" id="cp-bq" placeholder="مرور برندها…"><div id="cp-tree" class="pick-list mt8" style="max-height:44vh"></div></div></div>
          <div class="hint mt8">انتخاب برند یعنی همه‌ی مدل‌ها و تیپ‌هایش؛ انتخاب مدل یعنی همه‌ی تیپ‌هایش. فقط خودروهای «بانک خودروها» قابل انتخاب‌اند.</div></div>
      </div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><span class="small muted" id="cp-sum"></span><span class="grow"></span><button class="btn" data-close>انصراف</button><button class="btn primary" id="cp-ok">${icon('check', 16)} ثبت</button></div>`,
    { wide: true, onClose: () => { if (!done) resolve(undefined); } });
    const b = l.box;
    let brands = [];
    let openBrand = null;
    const has = (t, id) => items.some((x) => x.t === t && x.id === id);
    const toggle = (t, id, label) => {
      if (has(t, id)) items = items.filter((x) => !(x.t === t && x.id === id));
      else { items.push({ t, id }); if (label) labels.set(`${t}:${id}`, label); }
      all = !items.length ? all : false;
      draw();
    };
    const drawSel = async () => {
      const box = b.querySelector('#cp-sel');
      if (!items.length) { box.innerHTML = '<span class="muted small">هنوز خودرویی انتخاب نشده است.</span>'; return; }
      const missing = items.filter((x) => !labels.has(`${x.t}:${x.id}`));
      if (missing.length) {
        try {
          const d = await api('/api/vehicles/describe', { body: { value: { items } } });
          d.items.forEach((x) => labels.set(`${x.t}:${x.id}`, x.display || x.label));
        } catch (e) { /* */ }
      }
      box.innerHTML = items.map((x) => `<span class="tag p">${icon('car', 11)} ${esc(labels.get(`${x.t}:${x.id}`) || `${x.t} ${x.id}`)} <button class="btn xs icon ghost" data-rm="${x.t}:${x.id}">${icon('x', 11)}</button></span>`).join('');
    };
    const drawTree = async () => {
      const q = b.querySelector('#cp-bq').value.trim().toLowerCase();
      const box = b.querySelector('#cp-tree');
      if (openBrand) {
        const t = openBrand;
        box.innerHTML = `<button class="pick" data-back>${icon('chevronRight', 14)} همه‌ی برندها</button>
          <label class="pick ${has('brand', t.id) ? 'on' : ''}"><input type="checkbox" data-tg="brand:${t.id}" data-lab="${attr(t.name + ' (همه‌ی مدل‌ها)')}" ${has('brand', t.id) ? 'checked' : ''}> <b>همه‌ی مدل‌های ${esc(t.name)}</b></label>
          ${t.models.map((m) => `<label class="pick ${has('model', m.id) ? 'on' : ''}" style="padding-right:22px"><input type="checkbox" data-tg="model:${m.id}" data-lab="${attr(`${t.name} ${m.name}${m.trims.length ? ' (همه‌ی تیپ‌ها)' : ''}`)}" ${has('model', m.id) || has('brand', t.id) ? 'checked' : ''} ${has('brand', t.id) ? 'disabled' : ''}> ${esc(m.name)} <span class="xs muted ltr">${esc(m.slug)}</span></label>
            ${m.trims.map((tr) => `<label class="pick" style="padding-right:44px"><input type="checkbox" data-tg="trim:${tr.id}" data-lab="${attr(`${t.name} ${m.name} ${tr.name}`)}" ${has('trim', tr.id) || has('model', m.id) || has('brand', t.id) ? 'checked' : ''} ${has('model', m.id) || has('brand', t.id) ? 'disabled' : ''}> <span class="small">${esc(tr.name)}</span></label>`).join('')}`).join('')}`;
        return;
      }
      box.innerHTML = brands.filter((x) => !q || `${x.name} ${x.name_en} ${x.slug}`.toLowerCase().includes(q)).slice(0, 250)
        .map((x) => `<button class="pick ${has('brand', x.id) ? 'on' : ''}" data-ob="${x.id}"><b>${esc(x.name)}</b><span class="xs muted ltr">${esc(x.name_en)}</span><span class="grow"></span>${icon('chevronLeft', 14)}</button>`).join('');
    };
    const draw = () => {
      b.querySelectorAll('#cp-mode button').forEach((x) => x.classList.toggle('on', (x.dataset.m === 'all') === all));
      b.querySelector('#cp-some').style.display = all ? 'none' : '';
      b.querySelector('#cp-sum').textContent = all ? 'همه‌ی خودروها' : `${fa(items.length)} مورد انتخاب شده`;
      drawSel();
      drawTree();
    };
    b.querySelector('#cp-mode').addEventListener('click', (e) => { const x = e.target.closest('[data-m]'); if (x) { all = x.dataset.m === 'all'; draw(); } });
    b.querySelector('#cp-sug')?.addEventListener('click', () => {
      const v = opts.suggestion.value;
      if (v.all) { all = true; items = []; } else { all = false; items = v.items.map((x) => ({ ...x })); }
      draw();
    });
    b.addEventListener('click', async (e) => {
      const rm = e.target.closest('[data-rm]');
      if (rm) { const [t, id] = rm.dataset.rm.split(':'); toggle(t, Number(id)); return; }
      const ob = e.target.closest('[data-ob]');
      if (ob) { openBrand = await api(`/api/vehicles/brands/${ob.dataset.ob}/tree`); drawTree(); return; }
      if (e.target.closest('[data-back]')) { openBrand = null; drawTree(); return; }
      const sr = e.target.closest('[data-sr]');
      if (sr) { const [t, id] = sr.dataset.sr.split(':'); toggle(t, Number(id), sr.dataset.lab); }
    });
    b.addEventListener('change', (e) => {
      const tg = e.target.closest('[data-tg]');
      if (tg) { const [t, id] = tg.dataset.tg.split(':'); toggle(t, Number(id), tg.dataset.lab); }
    });
    const search = debounce(async () => {
      const q = b.querySelector('#cp-q').value.trim();
      const box = b.querySelector('#cp-res');
      if (!q) { box.innerHTML = '<div class="muted small">نام برند، مدل یا تیپ را بنویسید.</div>'; return; }
      const r = await api(`/api/vehicles/search?q=${encodeURIComponent(q)}&limit=40`);
      box.innerHTML = r.map((p) => `<button class="pick ${has(p.t, p.id) ? 'on' : ''}" data-sr="${p.t}:${p.id}" data-lab="${attr(p.label + (p.t === 'brand' ? ' (همه‌ی مدل‌ها)' : p.t === 'model' ? ' (همه‌ی تیپ‌ها)' : ''))}"><span class="tag" style="font-size:10.5px">${LV[p.t]}</span><b>${esc(p.label)}</b><span class="xs muted ltr">${esc(p.slug_path)}</span></button>`).join('') || '<div class="muted small">پیدا نشد.</div>';
    }, 250);
    b.querySelector('#cp-q').addEventListener('input', search);
    b.querySelector('#cp-bq').addEventListener('input', () => { openBrand = null; drawTree(); });
    b.querySelector('#cp-ok').addEventListener('click', async () => {
      if (!all && !items.length) { toast('خودرویی انتخاب نشده؛ یا «همه‌ی خودروها» را بزنید.', 'err'); return; }
      try {
        const r = await api('/api/vehicles/normalize', { body: { value: all ? { all: true } : { items } } });
        done = true; l.close(); resolve(r.value);
      } catch (e) { errToast(e); }
    });
    api('/api/vehicles/brands').then((r) => { brands = r; drawTree(); });
    search();
    draw();
  });
}
