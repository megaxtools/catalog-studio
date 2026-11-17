// کاتالوگ محصولات: کاتالوگ‌ها، انتشارهای نسخه‌دار و الگوهای خروجی (درخت فایل)
import { S, api, icon, esc, attr, fa, num, jdate, toast, okToast, errToast, openLayer, confirmDlg, emptyState, every, go, trunc, fileUrl, openPath, debounce } from './core.js';
import { busy, noProviderHint } from './ai_assist.js';
import { revisionsPanel, statusChip, diffTable } from './widgets.js';

const META = { v: null };
const meta = async () => (META.v ||= await api('/api/cat/meta'));
const RSTAT = { pending: ['wait', 'در صف'], running: ['run', 'در حال ساخت'], completed: ['ok', 'آماده'], error: ['err', 'خطا'] };
const rchip = (s) => { const [c, t] = RSTAT[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}</span>`; };
const size = (n) => (n > 1048576 ? `${fa((n / 1048576).toFixed(1))} مگابایت` : `${fa(Math.max(1, Math.round(n / 1024)))} کیلوبایت`);

// ======================================================================
// فهرست کاتالوگ‌ها
// ======================================================================
export const CatalogsV2 = {
  title: 'کاتالوگ‌ها و انتشارها',
  crumb: 'کاتالوگ محصولات · محصولات تأییدشده را با الگوی خروجی به فایل‌های نهایی مگا کارز تبدیل کنید',
  top: () => `<a class="btn" href="#/templates">${icon('tree', 16)} الگوهای خروجی</a><button class="btn primary" data-act="new">${icon('plus', 16)} کاتالوگ جدید</button>`,
  async render() { return '<div id="cl"></div>'; },
  async mount() {
    await this.load();
    const bank = new URLSearchParams(location.hash.split('?')[1] || '').get('bank');
    if (bank) openCatalogForm(null, { bank_ids: [Number(bank)] });
    every(4000, () => this.load(true));
  },
  async load(silent) {
    const list = await api('/api/cat/catalogs');
    const el = document.getElementById('cl');
    if (!el) return;
    const sig = JSON.stringify(list.map((c) => [c.id, c.updated_at, c.last_release?.status, c.last_release?.progress_done]));
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    el.innerHTML = list.length ? `<div class="grid2">${list.map((c) => `<div class="card"><div class="card-b">
      <div class="flex top"><span class="src-logo">${icon('rocket', 18)}</span><div class="grow"><a href="#/catalog/${c.id}"><b style="font-size:15px;color:var(--z-900)">${esc(c.title)}</b></a>
        <div class="xs muted ltr" style="text-align:right">${esc(c.slug)}</div><div class="xs muted">الگو: ${esc(c.template?.name || '—')} · ${fa(c.releases)} انتشار</div></div><span class="tag">${esc(c.state_label)}</span></div>
      ${c.last_release ? `<div class="flex mt12"><span class="small">آخرین انتشار: <b>r${fa(c.last_release.number)}</b></span>${rchip(c.last_release.status)}<span class="xs muted">${jdate(c.last_release.created_at)}</span>
        ${c.last_release.stats?.products ? `<span class="small">${num(c.last_release.stats.products)} محصول</span>` : ''}</div>` : '<div class="small muted mt12">هنوز انتشاری ندارد.</div>'}
      <div class="btns mt12"><a class="btn sm primary" href="#/catalog/${c.id}">${icon('rocket', 14)} مدیریت و انتشار</a></div></div></div>`).join('')}</div>`
      : `<div class="card"><div class="card-b">${emptyState('rocket', 'هنوز کاتالوگی ندارید', 'کاتالوگ مشخص می‌کند کدام محصولات تأییدشده با کدام الگو به فایل تبدیل شوند.', `<button class="btn primary" data-act="new">${icon('plus', 16)} کاتالوگ جدید</button>`)}</div></div>`;
  },
  act: { new: () => openCatalogForm(null) },
};

async function openCatalogForm(cat, preset = {}) {
  const [tpls, banks, brands, cats, m] = await Promise.all([api('/api/cat/templates'), api('/api/wb/banks'), api('/api/ref/brand'), api('/api/ref/category'), meta()]);
  const sel = { statuses: ['approved'], bank_ids: [], brand_ids: [], category_ids: [], require_ready: true, min_quality: null, ...(cat?.selection || {}), ...preset };
  const qon = (S.boot?.modules || {}).quality !== false;
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('rocket', 18)} ${cat ? 'تنظیمات کاتالوگ' : 'کاتالوگ جدید'}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:74vh;overflow:auto">
      <div class="form-grid"><div class="field"><label>عنوان</label><input class="inp" id="cf-t" value="${attr(cat?.title || '')}" placeholder="مثلاً: روغن‌های موتور مگا کارز"></div>
        <div class="field"><label>شناسه‌ی انگلیسی (در نام پوشه‌ها)</label><input class="inp ltr mono" id="cf-s" value="${attr(cat?.slug || '')}" placeholder="engine-oils"></div>
        <div class="field"><label>الگوی خروجی</label><select class="inp" id="cf-tpl">${tpls.map((t) => `<option value="${t.id}" ${(cat?.template_id || (t.is_default && !cat)) === t.id || (cat?.template_id === t.id) ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select><div class="hint">درخت فایل، قالب‌ها و اسکیمای هر خروجی. <a href="#/templates">مدیریت الگوها</a></div></div>
        <div class="field"><label>وضعیت</label><select class="inp" id="cf-st">${Object.entries(m.states).map(([k, v]) => `<option value="${k}" ${(cat?.state || 'draft') === k ? 'selected' : ''}>${v}</option>`).join('')}</select></div></div>
      <div class="field mt12"><label>توضیح</label><input class="inp" id="cf-d" value="${attr(cat?.description || '')}"></div>
      <div class="sec-title">${icon('filter', 16)} انتخاب محصولات <span class="line"></span></div>
      <div class="lbl mb8">بانک‌های تمیز (خالی = همه)</div>
      <div class="flex wrap" style="gap:8px">${banks.map((b) => `<label class="chipbtn ${sel.bank_ids.includes(b.id) ? 'on' : ''}"><input type="checkbox" data-bank="${b.id}" ${sel.bank_ids.includes(b.id) ? 'checked' : ''} hidden> ${esc(b.title)} <span class="xs muted">(${fa(b.counts.approved)} تأییدشده)</span></label>`).join('') || '<span class="muted small">بانک تمیزی نیست.</span>'}</div>
      <div class="lbl mt16 mb8">وضعیت محصولات</div>
      <div class="flex wrap" style="gap:8px">${Object.entries(m.statuses).filter(([k]) => ['draft', 'review', 'approved', 'rejected'].includes(k)).map(([k, v]) => `<label class="chipbtn ${sel.statuses.includes(k) ? 'on' : ''}"><input type="checkbox" data-stt="${k}" ${sel.statuses.includes(k) ? 'checked' : ''} hidden> ${v}</label>`).join('')}</div>
      ${qon ? `<div class="flex wrap mt16"><label class="check"><input type="checkbox" id="cf-ready" ${sel.require_ready ? 'checked' : ''}> فقط محصولات بدون خطای کیفیت</label>
        <span class="small">حداقل امتیاز کیفیت</span><input class="inp sm" type="number" id="cf-mq" min="0" max="100" value="${sel.min_quality ?? ''}" placeholder="پیش‌فرض تنظیمات" style="width:150px"></div>` : ''}
      <details class="mt16"><summary class="lbl" style="cursor:pointer">محدود به برندها یا دسته‌های خاص (اختیاری)</summary>
        <div class="split2 mt8"><select class="inp" id="cf-br" multiple size="6">${brands.map((b) => `<option value="${b.id}" ${sel.brand_ids.includes(b.id) ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select>
          <select class="inp" id="cf-ct" multiple size="6">${cats.map((c) => `<option value="${c.id}" ${sel.category_ids.includes(c.id) ? 'selected' : ''}>${esc(c.path)}</option>`).join('')}</select></div></details>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="cf-ok">${icon('save', 16)} ذخیره</button></div>`, { wide: true });
  const b = l.box;
  b.querySelectorAll('.chipbtn input').forEach((x) => x.addEventListener('change', () => x.closest('.chipbtn').classList.toggle('on', x.checked)));
  b.querySelector('#cf-ok').addEventListener('click', async () => {
    const body = { title: b.querySelector('#cf-t').value, slug: b.querySelector('#cf-s').value, slug_hint: b.querySelector('#cf-t').value, description: b.querySelector('#cf-d').value,
      template_id: Number(b.querySelector('#cf-tpl').value), state: b.querySelector('#cf-st').value,
      selection: { bank_ids: [...b.querySelectorAll('[data-bank]:checked')].map((x) => Number(x.dataset.bank)), statuses: [...b.querySelectorAll('[data-stt]:checked')].map((x) => x.dataset.stt),
        require_ready: b.querySelector('#cf-ready')?.checked ?? false, min_quality: b.querySelector('#cf-mq')?.value || null,
        brand_ids: [...b.querySelector('#cf-br').selectedOptions].map((o) => Number(o.value)), category_ids: [...b.querySelector('#cf-ct').selectedOptions].map((o) => Number(o.value)),
        exclude_ids: cat?.selection?.exclude_ids || [], include_ids: cat?.selection?.include_ids || [] } };
    try {
      const r = await api(cat ? `/api/cat/catalogs/${cat.id}` : '/api/cat/catalogs', { method: cat ? 'PUT' : 'POST', body });
      okToast('ذخیره شد.'); l.close();
      if (cat) CatalogV2.refresh(); else go(`#/catalog/${r.id}`);
    } catch (e) { errToast(e); }
  });
}

// ======================================================================
// یک کاتالوگ
// ======================================================================
const C = { id: 0, cat: null };
export const CatalogV2 = {
  title: 'کاتالوگ',
  crumb: 'کاتالوگ محصولات',
  top: () => `<a class="btn ghost" href="#/catalog">${icon('chevronRight', 16)} همه‌ی کاتالوگ‌ها</a>`,
  async render(p) {
    C.id = Number(p.id);
    C.cat = await api(`/api/cat/catalogs/${C.id}`);
    document.getElementById('page-title').textContent = C.cat.title;
    return `<div id="cv-head"></div><div class="grid2 mt16" style="grid-template-columns:1fr 1fr"><div class="card"><div class="card-h"><h3>${icon('filter', 16)} محصولاتی که وارد انتشار بعدی می‌شوند</h3><span class="sp"></span><button class="btn sm ghost" data-act="prev">${icon('refresh', 14)}</button></div><div class="card-b" id="cv-prev"></div></div>
      <div class="card"><div class="card-h"><h3>${icon('tree', 16)} درخت فایل انتشار</h3><span class="sp"></span><a class="btn sm ghost" href="#/templates/${C.cat.template_id}">${icon('edit', 14)} ویرایش الگو</a></div><div class="card-b" id="cv-tree"></div></div></div>
      <div class="card mt16"><div class="card-h"><h3>${icon('rocket', 16)} انتشارها</h3><span class="sub">هر انتشار تغییرناپذیر است؛ فایل‌ها و ریویژن هر محصول در لحظه‌ی انتشار ثبت می‌شود</span></div><div id="cv-rels"></div></div>`;
  },
  async mount() {
    this.head(); this.preview(); this.tree(); await this.releases();
    every(2500, () => this.releases(true));
  },
  async refresh() { C.cat = await api(`/api/cat/catalogs/${C.id}`); this.head(); this.preview(); this.tree(); this.releases(); },
  head() {
    const c = C.cat;
    const s = c.selection || {};
    document.getElementById('cv-head').innerHTML = `<div class="card"><div class="card-b"><div class="flex top wrap"><span class="src-logo">${icon('rocket', 20)}</span>
      <div class="grow"><b style="font-size:17px">${esc(c.title)}</b> <span class="tag">${esc(c.state_label)}</span><div class="xs muted ltr" style="text-align:right">${esc(c.slug)}</div>
        <div class="small mt8">${esc(c.description || '')}</div>
        <div class="flex wrap mt8" style="gap:6px"><span class="tag">${icon('tree', 11)} ${esc(c.template?.name || '—')}</span><span class="tag">وضعیت: ${(s.statuses || []).map((x) => ({ approved: 'تأییدشده', review: 'بازبینی', draft: 'پیش‌نویس', rejected: 'ردشده' }[x] || x)).join('، ')}</span>
          ${s.bank_ids?.length ? `<span class="tag">${fa(s.bank_ids.length)} بانک تمیز</span>` : '<span class="tag">همه‌ی بانک‌ها</span>'}${s.require_ready ? '<span class="tag">بدون خطای کیفیت</span>' : ''}${s.min_quality != null ? `<span class="tag">کیفیت ≥ ${fa(s.min_quality)}</span>` : ''}</div></div>
      <div class="btns"><button class="btn" data-act="edit">${icon('settings', 16)} تنظیمات</button><button class="btn ghost" data-act="revs">${icon('branch', 16)}</button>
        <button class="btn primary" data-act="release">${icon('rocket', 16)} انتشار تازه</button><button class="btn icon ghost danger" data-act="del">${icon('trash', 16)}</button></div></div></div></div>`;
  },
  async preview() {
    const box = document.getElementById('cv-prev');
    box.innerHTML = `<div class="muted small">${icon('loader', 14, 'spin')} در حال محاسبه…</div>`;
    const p = await api(`/api/cat/catalogs/${C.id}/preview`);
    box.innerHTML = `<div class="kpi-line"><span>وارد می‌شوند <b>${num(p.count)}</b></span><span>کنار گذاشته <b style="color:${p.skipped_count ? 'var(--warn)' : 'inherit'}">${num(p.skipped_count)}</b></span></div>
      <div class="pick-list mt12" style="max-height:220px">${p.sample.map((x) => `<div class="small" style="padding:4px 0;border-bottom:1px solid var(--z-100)">${esc(trunc(x.title, 80))} <span class="xs muted ltr">${esc(x.slug)}</span></div>`).join('')}</div>
      ${p.skipped_count ? `<details class="mt12"><summary class="small" style="cursor:pointer;color:var(--warn)">${icon('alert', 13)} چرا ${fa(p.skipped_count)} محصول کنار گذاشته شد؟</summary><div class="pick-list mt8" style="max-height:220px">${p.skipped.map((x) => `<div class="xs" style="padding:4px 0;border-bottom:1px solid var(--z-100)"><b>${esc(trunc(x.title, 60))}</b> — ${esc(x.why)}</div>`).join('')}</div></details>` : ''}`;
  },
  async tree() {
    const t = await api(`/api/cat/templates/${C.cat.template_id}`);
    document.getElementById('cv-tree').innerHTML = treeHtml(t.tree, C.cat.slug);
  },
  async releases(silent) {
    const list = await api(`/api/cat/catalogs/${C.id}/releases`);
    const el = document.getElementById('cv-rels');
    if (!el) return;
    const sig = JSON.stringify(list.map((r) => [r.id, r.status, r.progress_done, r.step]));
    if (silent && el.dataset.sig === sig) return;
    const wasRunning = el.dataset.running === '1';
    el.dataset.sig = sig;
    el.dataset.running = list.some((r) => ['running', 'pending'].includes(r.status)) ? '1' : '0';
    if (wasRunning && el.dataset.running === '0') this.preview();
    el.innerHTML = list.length ? `<table class="tbl"><thead><tr><th>انتشار</th><th>وضعیت</th><th>زمان</th><th>محصولات</th><th>تغییر نسبت به قبلی</th><th>یادداشت</th><th></th></tr></thead><tbody>
      ${list.map((r) => `<tr class="click" data-act="openrel" data-id="${r.id}"><td><b>r${fa(r.number)}</b></td><td>${rchip(r.status)}${['running', 'pending'].includes(r.status) ? `<div class="xs muted">${esc(r.step || '')}</div>` : ''}${r.status === 'error' ? `<div class="xs" style="color:var(--err)">${esc(trunc(r.error, 120))}</div>` : ''}</td>
        <td class="xs">${jdate(r.created_at)}</td><td class="small">${num(r.stats?.products)}</td>
        <td class="xs">${r.diff?.previous ? `<span style="color:var(--ok)">+${fa(r.stats.added)}</span> · <span style="color:var(--err)">−${fa(r.stats.removed)}</span> · <span style="color:var(--warn)">~${fa(r.stats.changed)}</span>` : r.status === 'completed' ? 'اولین انتشار' : ''}</td>
        <td class="xs muted">${esc(trunc(r.note || '', 40))}</td>
        <td class="nowrap">${r.files?.zip ? `<a class="btn xs soft" href="${fileUrl(r.files.zip, true)}">${icon('download', 12)} ZIP</a>` : ''}${icon('chevronLeft', 14)}</td></tr>`).join('')}</tbody></table>`
      : `<div class="card-b">${emptyState('rocket', 'هنوز انتشاری نیست', 'با «انتشار تازه» فایل‌های نهایی ساخته می‌شوند.')}</div>`;
  },
  act: {
    edit: () => openCatalogForm(C.cat),
    prev: () => CatalogV2.preview(),
    revs: () => {
      const l = openLayer('modal', `<div class="card-h"><h3>${icon('branch', 18)} نسخه‌های تنظیمات کاتالوگ</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><div class="card-b" id="rv"></div>`, { wide: true });
      revisionsPanel(l.box.querySelector('#rv'), 'catalog', C.id, () => { l.close(); CatalogV2.refresh(); });
    },
    release: async () => {
      const l = openLayer('modal', `<div class="card-h"><h3>${icon('rocket', 18)} انتشار تازه</h3></div><div class="card-b"><div class="small">یک انتشار تازه با محصولات فعلی و الگوی «${esc(C.cat.template?.name || '')}» ساخته می‌شود. انتشارهای قبلی دست نمی‌خورند.</div>
        <div class="field mt12"><label>یادداشت انتشار (اختیاری)</label><input class="inp" id="rl-n" placeholder="مثلاً: اصلاح عنوان‌ها و افزودن ۱۲ محصول"></div></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="rl-ok">${icon('rocket', 16)} ساخت انتشار</button></div>`);
      l.box.querySelector('#rl-ok').addEventListener('click', async () => {
        try { await api(`/api/cat/catalogs/${C.id}/release`, { body: { note: l.box.querySelector('#rl-n').value } }); okToast('ساخت انتشار آغاز شد.'); l.close(); CatalogV2.releases(); } catch (e) { errToast(e); }
      });
    },
    openrel: (el, ev) => { if (ev.target.closest('a')) return; go(`#/catalog/release/${el.dataset.id}`); },
    del: async () => {
      const l = openLayer('modal', `<div class="card-h"><h3>حذف کاتالوگ</h3></div><div class="card-b">کاتالوگ و فهرست انتشارهایش از استودیو حذف شود؟ محصولات تمیز دست نمی‌خورند.
        <label class="check mt12"><input type="checkbox" id="dl-f"> فایل‌های انتشارها هم از دیسک حذف شوند</label></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn danger" id="dl-ok">${icon('trash', 16)} حذف</button></div>`);
      l.box.querySelector('#dl-ok').addEventListener('click', async () => { await api(`/api/cat/catalogs/${C.id}?files=${l.box.querySelector('#dl-f').checked ? 1 : 0}`, { method: 'DELETE' }); l.close(); okToast('حذف شد.'); go('#/catalog'); });
    },
  },
};

function treeHtml(tree, catalog = 'mega-catalog') {
  return `<div class="tree-view">${tree.map((f) => `<div>${esc(f.path.replace('mega-catalog', catalog))} <span class="lbl2"># ${esc(f.label)}</span></div>`).join('')}</div>
    <div class="hint mt8">نمونه با دو محصول فرضی و انتشار شماره‌ی ۳.</div>`;
}

// ======================================================================
// یک انتشار
// ======================================================================
export const Release = {
  title: 'انتشار',
  crumb: 'کاتالوگ محصولات',
  async render(p) {
    const r = await api(`/api/cat/releases/${p.id}`);
    const c = await api(`/api/cat/catalogs/${r.catalog_id}`);
    this.r = r;
    document.getElementById('page-title').textContent = `${c.title} — انتشار r${fa(r.number)}`;
    document.getElementById('top-actions').innerHTML = `<a class="btn ghost" href="#/catalog/${c.id}">${icon('chevronRight', 16)} کاتالوگ</a>`;
    const files = r.files?.list || [];
    const data = files.filter((f) => f.kind !== 'image');
    const imgs = files.filter((f) => f.kind === 'image');
    const d = r.diff || {};
    return `<div class="card"><div class="card-b"><div class="flex wrap">${rchip(r.status)}<span class="small">${jdate(r.created_at)}</span><span class="tag">${icon('tree', 11)} ${esc(r.snapshot?.template?.name || '')}</span>${r.note ? `<span class="small muted">${esc(r.note)}</span>` : ''}
        <span class="grow"></span>${r.files?.zip ? `<a class="btn primary" href="${fileUrl(r.files.zip, true)}">${icon('download', 16)} دانلود ZIP</a>` : ''}${r.root ? `<button class="btn" data-act="folder">${icon('folder', 16)} پوشه</button>` : ''}
        <button class="btn icon ghost danger" data-act="del">${icon('trash', 16)}</button></div>
      ${r.status === 'error' ? `<div class="alert err mt12">${icon('alert')}<div>${esc(r.error)}</div></div>` : ''}
      <div class="kpi-line mt12"><span>محصولات <b>${num(r.stats?.products)}</b></span><span>فایل‌ها <b>${num(r.stats?.files)}</b></span><span>تصاویر <b>${num(r.stats?.images)}</b></span><span>کنار گذاشته <b>${num(r.stats?.skipped)}</b></span></div></div></div>
      <div class="grid2 mt16" style="grid-template-columns:1fr 1fr"><div class="card"><div class="card-h"><h3>${icon('fileSheet', 16)} فایل‌های داده</h3></div><div class="tbl-wrap"><table class="tbl"><tbody>
        ${data.map((f) => `<tr><td class="ltr small mono" style="text-align:left">${esc(f.path)}</td><td class="xs muted">${f.rows != null ? `${num(f.rows)} ردیف · ` : ''}${size(f.size)}</td><td><a class="btn xs soft" href="${fileUrl(r.root + '/' + f.path, true)}">${icon('download', 12)}</a></td></tr>`).join('')}</tbody></table></div>
        ${imgs.length ? `<div class="card-b small muted">${num(imgs.length)} تصویر در مسیرهای الگو (داخل ZIP)</div>` : ''}</div>
      <div class="card"><div class="card-h"><h3>${icon('diff', 16)} تفاوت با انتشار قبلی</h3></div><div class="card-b">${d.previous ? `<div class="kpi-line"><span>قبلی <b>r${fa(d.previous)}</b></span><span>تازه <b style="color:var(--ok)">${num(d.added?.length)}</b></span><span>حذف‌شده <b style="color:var(--err)">${num(d.removed?.length)}</b></span><span>تغییرکرده <b style="color:var(--warn)">${num(d.changed?.length)}</b></span><span>بدون تغییر <b>${num(d.unchanged)}</b></span></div>
        <div class="pick-list mt12" style="max-height:300px">${(d.changed || []).map((x) => `<div class="small" style="padding:6px 0;border-bottom:1px solid var(--z-100)"><b>${esc(trunc(x.title, 70))}</b> <span class="xs muted">نسخه‌ی ${fa(x.from_rev)} ← ${fa(x.to_rev)}</span><div class="flex wrap mt4" style="gap:4px">${x.fields.map((f) => `<span class="tag" style="font-size:10.5px">${esc(f)}</span>`).join('')}</div></div>`).join('')}
          ${(d.added || []).map((x) => `<div class="small" style="padding:4px 0;color:var(--ok)">+ ${esc(trunc(x.title, 80))}</div>`).join('')}${(d.removed || []).map((x) => `<div class="small" style="padding:4px 0;color:var(--err)">− ${esc(trunc(x.title, 80))}</div>`).join('')}</div>
        <button class="btn sm ghost mt12" data-act="cmp">${icon('layers', 14)} مقایسه با انتشار دیگر</button>` : '<div class="muted small">اولین انتشار این کاتالوگ است.</div>'}</div></div></div>
      <div class="card mt16"><div class="card-h"><h3>${icon('list', 16)} محصولات این انتشار</h3><span class="sp"></span><input class="inp sm" style="width:240px" placeholder="جست‌وجو…" data-input="q"></div><div class="tbl-wrap" id="rl-items"></div></div>
      ${r.snapshot?.skipped?.length ? `<div class="card mt16"><div class="card-h"><h3>محصولات کنار گذاشته</h3></div><div class="card-b">${r.snapshot.skipped.map((x) => `<div class="xs" style="padding:4px 0;border-bottom:1px solid var(--z-100)"><b>${esc(trunc(x.title, 70))}</b> — ${esc(x.why)}</div>`).join('')}</div></div>` : ''}`;
  },
  async mount() { await this.items(''); },
  async items(q) {
    const r = await api(`/api/cat/releases/${this.r.id}/items?q=${encodeURIComponent(q)}&size=200`);
    document.getElementById('rl-items').innerHTML = `<table class="tbl"><thead><tr><th>محصول</th><th>شناسه</th><th>نسخه‌ی محصول</th><th></th></tr></thead><tbody>${r.rows.map((x) => `<tr><td class="small">${esc(trunc(x.title, 90))}</td><td class="xs ltr muted">${esc(x.uid)}</td><td class="small">${fa(x.product_rev)}</td>
      <td><button class="btn xs ghost" data-act="rec" data-rec="${attr(JSON.stringify(x.record))}">${icon('code', 12)} رکورد</button></td></tr>`).join('')}</tbody></table>`;
  },
  act: {
    folder: () => openPath(Release.r.root),
    rec: (el) => openLayer('modal', `<div class="card-h"><h3>رکورد اصلی محصول در این انتشار</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><pre class="pathbox" style="margin:16px;max-height:70vh;overflow:auto;white-space:pre-wrap;direction:ltr;text-align:left">${esc(JSON.stringify(JSON.parse(el.dataset.rec), null, 2))}</pre>`, { wide: true }),
    del: async () => {
      if (!(await confirmDlg('حذف انتشار', 'این انتشار و فایل‌هایش حذف شود؟', 'حذف', true))) return;
      await api(`/api/cat/releases/${Release.r.id}`, { method: 'DELETE' }); okToast('حذف شد.'); go(`#/catalog/${Release.r.catalog_id}`);
    },
    cmp: async () => {
      const list = (await api(`/api/cat/catalogs/${Release.r.catalog_id}/releases`)).filter((x) => x.status === 'completed' && x.id !== Release.r.id);
      const l = openLayer('modal', `<div class="card-h"><h3>مقایسه‌ی انتشارها</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><div class="card-b"><select class="inp" id="cm-a">${list.map((x) => `<option value="${x.id}">r${fa(x.number)} — ${jdate(x.created_at)}</option>`).join('')}</select><div id="cm-r" class="mt12"></div></div>`, { wide: true });
      const run = async () => {
        const res = await api(`/api/cat/releases/compare?a=${l.box.querySelector('#cm-a').value}&b=${Release.r.id}`);
        l.box.querySelector('#cm-r').innerHTML = `<div class="kpi-line"><span>تازه <b>${num(res.added.length)}</b></span><span>حذف‌شده <b>${num(res.removed.length)}</b></span><span>تغییرکرده <b>${num(res.changed.length)}</b></span></div>
          ${res.changed.map((x) => `<details class="mt8"><summary class="small" style="cursor:pointer"><b>${esc(x.title)}</b> (${fa(x.changes.length)} تغییر)</summary>${diffTable(x.changes)}</details>`).join('')}`;
      };
      l.box.querySelector('#cm-a').addEventListener('change', run);
      if (list.length) run(); else l.box.querySelector('#cm-r').innerHTML = '<div class="muted small">انتشار دیگری نیست.</div>';
    },
  },
  input: { q: debounce((el) => Release.items(el.value.trim()), 300) },
};

// ======================================================================
// الگوهای خروجی
// ======================================================================
export const Templates = {
  title: 'الگوهای خروجی و درخت فایل',
  crumb: 'الگوها و اسکیماها · چه فایل‌هایی، با چه قالب و اسکیمایی، در کدام پوشه ساخته شوند',
  top: () => `<a class="btn primary" href="#/templates/new">${icon('plus', 16)} الگوی جدید</a>`,
  async render() {
    const list = await api('/api/cat/templates');
    return `<div class="grid2">${list.map((t) => `<div class="card"><div class="card-b"><div class="flex top"><span class="src-logo">${icon('tree', 18)}</span><div class="grow"><a href="#/templates/${t.id}"><b style="font-size:15px;color:var(--z-900)">${esc(t.name)}</b></a>${t.is_default ? ' <span class="tag p">پیش‌فرض</span>' : ''}
        <div class="xs muted">${esc(t.description || '')}</div><div class="xs muted mt4">${fa(t.config.outputs.length)} خروجی · ${t.config.images.enabled ? 'با تصاویر' : 'بدون تصاویر'} · در ${fa(t.used_by)} کاتالوگ</div></div></div>
      <div class="tree-view mt12" style="max-height:200px">${t.tree.slice(0, 12).map((f) => `<div>${esc(f.path)}</div>`).join('')}${t.tree.length > 12 ? '<div class="lbl2">…</div>' : ''}</div>
      <div class="btns mt12"><a class="btn sm primary" href="#/templates/${t.id}">${icon('edit', 14)} ویرایش</a><button class="btn sm ghost" data-act="dup" data-id="${t.id}">${icon('copy', 14)} کپی</button>
        <button class="btn sm icon ghost danger" data-act="del" data-id="${t.id}">${icon('trash', 14)}</button></div></div></div>`).join('')}</div>`;
  },
  act: {
    dup: async (el) => { const t = await api(`/api/cat/templates/${el.dataset.id}`); const r = await api('/api/cat/templates', { body: { name: `${t.name} (کپی)`, description: t.description, config: t.config } }); go(`#/templates/${r.id}`); },
    del: async (el) => { if (!(await confirmDlg('حذف الگو', 'این الگو حذف شود؟', 'حذف', true))) return; await api(`/api/cat/templates/${el.dataset.id}`, { method: 'DELETE' }); okToast('حذف شد.'); go('#/templates'); location.reload(); },
  },
};

const T = { id: null, t: null };
export const TemplateEditor = {
  title: 'الگوی خروجی',
  crumb: 'الگوها و اسکیماها · الگوهای خروجی',
  top: () => `<a class="btn ghost" href="#/templates">${icon('chevronRight', 16)} بازگشت</a>${T.id ? `<button class="btn ghost" data-act="revs">${icon('branch', 16)} نسخه‌ها</button>` : ''}${(S.boot?.modules || {}).ai !== false ? `<button class="btn soft" data-act="aidesign">${icon('sparkles', 16)} طراحی با AI</button>` : ''}<button class="btn primary" data-act="save">${icon('save', 16)} ذخیره‌ی الگو</button>`,
  async render(p) {
    const m = await meta();
    const schemas = await api('/api/schemas');
    T.schemas = schemas;
    T.m = m;
    T.id = p.id === 'new' ? null : Number(p.id);
    T.t = T.id ? await api(`/api/cat/templates/${T.id}`) : { name: '', description: '', is_default: false, config: { root: '{catalog}-r{release}', outputs: [{ kind: 'products', format: 'json', schema_id: schemas.find((s) => s.is_default)?.id, path: 'products.json', name: 'محصولات' }], images: { enabled: true, path: 'images/{slug}/{name}.{ext}', feature_name: 'feature', gallery_name: 'gallery_{n}', which: 'all', link: 'relative', prefix: '' }, zip: true, manifest: true } };
    if (T.t.name) document.getElementById('page-title').textContent = T.t.name;
    return `<div class="split" style="grid-template-columns:1fr 420px"><div>
      <div class="card"><div class="card-b"><div class="form-grid"><div class="field"><label>نام الگو</label><input class="inp" id="te-n" value="${attr(T.t.name)}"></div>
          <div class="field"><label>پوشه‌ی هر انتشار</label><input class="inp ltr mono" id="te-root" value="${attr(T.t.config.root)}" data-input="pv"><div class="hint">{catalog} شناسه‌ی کاتالوگ · {release} شماره‌ی انتشار · {date}</div></div></div>
        <div class="field mt12"><label>توضیح</label><input class="inp" id="te-d" value="${attr(T.t.description || '')}"></div>
        <div class="flex wrap mt12"><label class="check"><input type="checkbox" id="te-def" ${T.t.is_default ? 'checked' : ''}> الگوی پیش‌فرض کاتالوگ‌های تازه</label><label class="check"><input type="checkbox" id="te-zip" ${T.t.config.zip ? 'checked' : ''} data-change="pv"> بسته‌ی ZIP</label><label class="check"><input type="checkbox" id="te-man" ${T.t.config.manifest ? 'checked' : ''} data-change="pv"> شناسنامه‌ی انتشار (manifest.json)</label></div></div></div>
      <div class="card mt16"><div class="card-h"><h3>${icon('fileSheet', 16)} خروجی‌های داده</h3><span class="sp"></span><button class="btn sm soft" data-act="addout">${icon('plus', 14)} خروجی</button></div><div class="card-b" id="te-outs"></div></div>
      <div class="card mt16"><div class="card-h"><h3>${icon('image', 16)} تصاویر</h3></div><div class="card-b" id="te-img"></div></div></div>
      <div><div class="card" style="position:sticky;top:12px"><div class="card-h"><h3>${icon('tree', 16)} پیش‌نمایش درخت فایل</h3></div><div class="card-b"><div id="te-err"></div><div id="te-tree"></div></div></div></div></div>`;
  },
  async mount() { this.drawOuts(); this.drawImg(); await this.preview(); },
  drawOuts() {
    const m = T.m;
    document.getElementById('te-outs').innerHTML = T.t.config.outputs.map((o, i) => `<div class="out-row" data-o="${i}">
      <div class="flex wrap"><input class="inp sm" data-k="name" value="${attr(o.name || '')}" placeholder="نام" style="max-width:180px">
        <select class="inp sm" data-k="kind" style="max-width:190px">${Object.entries(m.kinds).map(([k, v]) => `<option value="${k}" ${o.kind === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
        <select class="inp sm" data-k="format" style="max-width:130px">${Object.entries(m.formats).map(([k, v]) => `<option value="${k}" ${o.format === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
        ${o.kind === 'products' ? `<select class="inp sm" data-k="schema_id" style="max-width:240px">${T.schemas.filter((s) => ['general', 'catalog'].includes(s.usage || 'general')).map((s) => `<option value="${s.id}" ${Number(o.schema_id) === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>` : ''}
        <span class="grow"></span><button class="btn xs ghost" data-act="mvout" data-i="${i}" data-d="-1">${icon('chevronUp', 12)}</button><button class="btn xs ghost danger" data-act="delout" data-i="${i}">${icon('trash', 12)}</button></div>
      <div class="flex"><span class="xs muted nowrap">مسیر فایل</span><input class="inp sm ltr mono grow" data-k="path" value="${attr(o.path)}" placeholder="data/products.json"></div>
      ${o.kind !== 'products' ? `<div class="flex wrap" style="gap:8px"><span class="xs muted">ستون‌ها:</span>${(m.kind_fields[o.kind] || []).map((f) => `<label class="check xs"><input type="checkbox" data-field="${f}" ${(o.fields || m.kind_fields[o.kind]).includes(f) ? 'checked' : ''}> ${f}</label>`).join('')}</div>` : `<div class="xs muted">${o.format === 'json' ? 'آرایه‌ای از اشیای ساخت‌یافته. اگر مسیر {slug} داشته باشد (مثلاً products/{slug}.json) برای هر محصول یک فایل جدا ساخته می‌شود.' : 'هر محصول یک ردیف؛ ستون‌های گروهی طبق تنظیم «قالب خروجی» هر ستون در اسکیما.'}</div>`}
    </div>`).join('') || '<div class="muted small">خروجی داده‌ای ندارد (فقط تصاویر).</div>';
  },
  drawImg() {
    const im = T.t.config.images;
    document.getElementById('te-img').innerHTML = `<label class="check"><input type="checkbox" id="ti-on" ${im.enabled ? 'checked' : ''} data-change="pv"> کپی تصاویر نهایی محصولات در انتشار</label>
      <div class="field mt12"><label>مسیر و نام هر تصویر</label><input class="inp ltr mono" id="ti-path" value="${attr(im.path)}" data-input="pv"><div class="hint">{slug} {uid} {brand_slug} {category_slug} · {name} نام تصویر · {ext} پسوند · {n} شماره‌ی تصویر (۰ = شاخص)</div></div>
      <div class="form-grid mt12"><div class="field"><label>نام تصویر شاخص</label><input class="inp ltr mono" id="ti-f" value="${attr(im.feature_name)}" data-input="pv"></div>
        <div class="field"><label>نام تصاویر گالری</label><input class="inp ltr mono" id="ti-g" value="${attr(im.gallery_name)}" data-input="pv"><div class="hint">{n} شماره‌ی گالری (۱، ۲، …)</div></div>
        <div class="field"><label>کدام تصاویر</label><select class="inp" id="ti-w" data-change="pv"><option value="all" ${im.which === 'all' ? 'selected' : ''}>شاخص و گالری</option><option value="feature" ${im.which === 'feature' ? 'selected' : ''}>فقط شاخص</option></select></div>
        <div class="field"><label>پیوند تصویر در فایل‌های داده</label><select class="inp" id="ti-l" data-change="pv"><option value="relative" ${im.link === 'relative' ? 'selected' : ''}>مسیر نسبی داخل انتشار</option><option value="prefix" ${im.link === 'prefix' ? 'selected' : ''}>پیشوند دلخواه (CDN)</option><option value="source" ${im.link === 'source' ? 'selected' : ''}>لینک اصلی منبع</option></select></div></div>
      <input class="inp ltr mt8" id="ti-p" value="${attr(im.prefix || '')}" placeholder="https://cdn.megacars.ir/catalog/" data-input="pv">`;
  },
  collect() {
    const c = T.t.config;
    c.root = document.getElementById('te-root').value;
    c.zip = document.getElementById('te-zip').checked;
    c.manifest = document.getElementById('te-man').checked;
    document.querySelectorAll('#te-outs [data-o]').forEach((row) => {
      const o = c.outputs[Number(row.dataset.o)];
      row.querySelectorAll('[data-k]').forEach((x) => { o[x.dataset.k] = x.dataset.k === 'schema_id' ? Number(x.value) : x.value; });
      if (o.kind !== 'products') o.fields = [...row.querySelectorAll('[data-field]:checked')].map((x) => x.dataset.field);
    });
    c.images = { enabled: document.getElementById('ti-on').checked, path: document.getElementById('ti-path').value, feature_name: document.getElementById('ti-f').value,
      gallery_name: document.getElementById('ti-g').value, which: document.getElementById('ti-w').value, link: document.getElementById('ti-l').value, prefix: document.getElementById('ti-p').value };
    return c;
  },
  async preview() {
    const r = await api('/api/cat/templates/preview', { body: { config: this.collect() } });
    document.getElementById('te-tree').innerHTML = treeHtml(r.tree);
    document.getElementById('te-err').innerHTML = r.errors.length ? `<div class="alert err mb12">${icon('alert')}<div>${r.errors.map(esc).join('<br>')}</div></div>` : '';
  },
  act: {
    aidesign: async (el) => {
      const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} طراحی الگو با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
        <div class="card-b"><div class="field"><label>خروجی چه ساختاری داشته باشد؟</label><textarea class="inp" id="ad-p" rows="4" data-noai placeholder="مثلاً «برای هر محصول یک فایل JSON با عنوان و تصاویر در پوشه‌ی items، تصاویر در پوشه‌ی هر برند، و فهرست برندها در Excel»"></textarea></div>
          <div class="hint mt8">پیشنهاد هوش مصنوعی جایگزین تنظیمات فعلی این صفحه می‌شود؛ پیش از ذخیره می‌توانید همه‌چیز را ببینید و تغییر دهید.</div></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ad-go">${icon('sparkles', 16)} طراحی کن</button></div>`);
      const go2 = l.box.querySelector('#ad-go');
      go2.addEventListener('click', async () => {
        busy(go2, true, 'در حال طراحی…');
        try {
          const r = await api('/api/cat/templates/ai', { body: { prompt: l.box.querySelector('#ad-p').value } });
          T.t.config = r.config;
          const n = document.getElementById('te-n');
          if (!n.value.trim()) n.value = r.name;
          const d = document.getElementById('te-d');
          if (!d.value.trim()) d.value = r.description;
          document.getElementById('te-root').value = r.config.root;
          document.getElementById('te-zip').checked = !!r.config.zip;
          document.getElementById('te-man').checked = !!r.config.manifest;
          TemplateEditor.drawOuts(); TemplateEditor.drawImg(); await TemplateEditor.preview();
          l.close();
          okToast(r.errors.length ? 'الگو پیشنهاد شد ولی ایراد دارد؛ پیام‌های پیش‌نمایش را ببینید.' : 'الگو طراحی شد؛ بررسی و ذخیره کنید.');
        } catch (e) { noProviderHint(e); busy(go2, false); }
      });
    },
    addout: () => { TemplateEditor.collect(); T.t.config.outputs.push({ kind: 'brands', format: 'xlsx', path: 'brands.xlsx', name: 'برندها' }); TemplateEditor.drawOuts(); TemplateEditor.preview(); },
    delout: (el) => { TemplateEditor.collect(); T.t.config.outputs.splice(Number(el.dataset.i), 1); TemplateEditor.drawOuts(); TemplateEditor.preview(); },
    mvout: (el) => { TemplateEditor.collect(); const i = Number(el.dataset.i); const o = T.t.config.outputs; if (i > 0) [o[i - 1], o[i]] = [o[i], o[i - 1]]; TemplateEditor.drawOuts(); TemplateEditor.preview(); },
    revs: () => {
      const l = openLayer('modal', `<div class="card-h"><h3>${icon('branch', 18)} نسخه‌های الگو</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><div class="card-b" id="rv"></div>`, { wide: true });
      revisionsPanel(l.box.querySelector('#rv'), 'template', T.id, () => { l.close(); location.reload(); });
    },
    save: async () => {
      const body = { name: document.getElementById('te-n').value, description: document.getElementById('te-d').value, is_default: document.getElementById('te-def').checked, config: TemplateEditor.collect() };
      try {
        const r = await api(T.id ? `/api/cat/templates/${T.id}` : '/api/cat/templates', { method: T.id ? 'PUT' : 'POST', body });
        okToast('الگو ذخیره شد (نسخه‌ی تازه ثبت شد). فقط انتشارهای بعدی از آن استفاده می‌کنند.');
        if (!T.id) go(`#/templates/${r.id}`);
      } catch (e) { errToast(e); }
    },
  },
  change: {
    pv: () => TemplateEditor.preview(),
  },
  input: { pv: debounce(() => TemplateEditor.preview(), 300) },
};

// تغییر نوع/قالب خروجی → بازسازی ردیف
document.addEventListener('change', (e) => {
  const k = e.target.closest('#te-outs [data-k]');
  if (k && (k.dataset.k === 'kind' || k.dataset.k === 'format' || k.dataset.k === 'schema_id' || k.dataset.k === 'path')) {
    TemplateEditor.collect();
    if (k.dataset.k === 'kind' || k.dataset.k === 'format') {
      const o = T.t.config.outputs[Number(k.closest('[data-o]').dataset.o)];
      if (k.dataset.k === 'kind') { o.fields = null; if (o.kind === 'products' && !o.schema_id) o.schema_id = T.schemas.find((s) => s.is_default)?.id; }
      o.path = o.path.replace(/\.(json|xlsx|csv)$/i, '') + '.' + o.format;
      TemplateEditor.drawOuts();
    }
    TemplateEditor.preview();
  }
  if (e.target.closest('#te-outs [data-field]')) TemplateEditor.preview();
});
document.addEventListener('input', (e) => { if (e.target.closest('#te-outs [data-k="path"]')) { TemplateEditor.collect(); debounce(() => TemplateEditor.preview(), 300)(); } });

statusChip; // eslint-disable-line no-unused-expressions
