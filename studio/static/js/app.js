import { S, api, icon, esc, fa, num, toast, errToast, okToast, refreshBoot, go, openLayer, closeLayers } from './core.js';
import { Dashboard, NewRun, Datasets, Dataset, resolveIncident } from './pages_main.js';
import { Exports, Bg, Mappings, Settings } from './pages_tools.js';
import { Sources, SourceEditor, Schemas, SchemaEditor } from './pages_config.js';
import { AIHub, ProfileEditor, Rules, Queue } from './pages_ai.js';
import { MCP } from './pages_mcp.js';
import { Logs } from './pages_logs.js';
import { Catalogs, CatalogDetail } from './pages_catalogs.js';
import './ai_assist.js';

// صفحه‌های نسخه‌ی ۲ و ماژول‌ها به‌صورت تنبل بارگذاری می‌شوند؛ اگر فایل یک ماژول خطا داشته باشد، فقط همان صفحه خطا می‌دهد
const lazy = (file, name) => ({ lazy: () => import(file).then((m) => m[name]) });
const P = {
  Banks: lazy('./pages_editor.js', 'Banks'), Bank: lazy('./pages_editor.js', 'Bank'), Review: lazy('./pages_editor.js', 'Review'),
  Dupes: lazy('./pages_editor.js', 'Dupes'), CatalogsV2: lazy('./pages_catalog2.js', 'CatalogsV2'), CatalogV2: lazy('./pages_catalog2.js', 'CatalogV2'),
  Templates: lazy('./pages_catalog2.js', 'Templates'), TemplateEditor: lazy('./pages_catalog2.js', 'TemplateEditor'),
  Release: lazy('./pages_catalog2.js', 'Release'), Brands: lazy('./pages_refdata.js', 'Brands'), Categories: lazy('./pages_refdata.js', 'Categories'),
  Vehicles: lazy('./mod_vehicles.js', 'Vehicles'), Modules: lazy('./pages_system.js', 'Modules'), Backups: lazy('./pages_system.js', 'Backups'),
  Users: lazy('./pages_system.js', 'Users'), Help: lazy('./pages_system.js', 'Help'), Revisions: lazy('./pages_system.js', 'Revisions'),
  Home: lazy('./pages_system.js', 'Home'),
};

const ROUTES = [
  [/^#?\/?$/, P.Home],
  [/^#\/raw$/, Dashboard],
  [/^#\/new$/, NewRun, null, 'scraper'],
  [/^#\/new\/(ai)$/, NewRun, ['mode'], 'ai'],
  [/^#\/datasets$/, Datasets],
  [/^#\/datasets\/(\d+)$/, Dataset, ['id']],
  [/^#\/queue$/, Queue, null, 'queue'],
  [/^#\/sources$/, Sources, null, 'scraper'],
  [/^#\/sources\/(new|\d+)$/, SourceEditor, ['id'], 'scraper'],
  [/^#\/editor$/, P.Banks],
  [/^#\/editor\/review$/, P.Review],
  [/^#\/editor\/dupes$/, P.Dupes, null, 'dedup'],
  [/^#\/editor\/(\d+)$/, P.Bank, ['id']],
  [/^#\/bg$/, Bg],
  [/^#\/catalog$/, P.CatalogsV2],
  [/^#\/catalog\/(\d+)$/, P.CatalogV2, ['id']],
  [/^#\/catalog\/release\/(\d+)$/, P.Release, ['id']],
  [/^#\/exports$/, Exports, null, 'legacy_export'],
  [/^#\/catalogs$/, Catalogs, null, 'legacy_export'],
  [/^#\/catalogs\/(\d+)$/, CatalogDetail, ['id'], 'legacy_export'],
  [/^#\/schemas$/, Schemas],
  [/^#\/schemas\/(\d+)$/, SchemaEditor, ['id']],
  [/^#\/templates$/, P.Templates],
  [/^#\/templates\/(new|\d+)$/, P.TemplateEditor, ['id']],
  [/^#\/rules$/, Rules],
  [/^#\/mappings$/, Mappings],
  [/^#\/ref\/brands$/, P.Brands],
  [/^#\/ref\/categories$/, P.Categories],
  [/^#\/vehicles$/, P.Vehicles, null, 'vehicles'],
  [/^#\/ai$/, AIHub, null, 'ai'],
  [/^#\/ai\/profiles\/(\d+)$/, ProfileEditor, ['id'], 'ai'],
  [/^#\/mcp$/, MCP, null, 'mcp'],
  [/^#\/logs$/, Logs],
  [/^#\/revisions$/, P.Revisions],
  [/^#\/modules$/, P.Modules],
  [/^#\/backups$/, P.Backups],
  [/^#\/users$/, P.Users],
  [/^#\/help(?:\/(.+))?$/, P.Help, ['doc']],
  [/^#\/settings$/, Settings],
];

// [نشانی، آیکون، برچسب، نشان، ماژول]
const NAV = [
  ['#/', 'dashboard', 'پیشخوان'],
  ['sec', 'داده‌های خام', 'database'],
  ['#/new', 'plusCircle', 'استخراج جدید', null, 'scraper'],
  ['#/datasets', 'database', 'بانک‌های داده‌ی خام', 'incidents'],
  ['#/queue', 'layers', 'صف و زمان‌بندی', 'queue', 'queue'],
  ['#/sources', 'globe', 'منابع و اسکرپرها', null, 'scraper'],
  ['sec', 'ویرایشگر داده‌ها', 'edit'],
  ['#/editor', 'inbox', 'بانک‌های تمیز', 'editor'],
  ['#/editor/review', 'checkCircle', 'صف بازبینی', 'review'],
  ['#/editor/dupes', 'merge', 'محصولات تکراری', 'dupes', 'dedup'],
  ['#/bg', 'frame', 'پردازش پوشه‌ی تصاویر'],
  ['sec', 'کاتالوگ محصولات', 'package'],
  ['#/catalog', 'rocket', 'کاتالوگ‌ها و انتشارها', 'catalog'],
  ['#/exports', 'fileSheet', 'خروجی مستقیم (نسخه‌ی ۱)', null, 'legacy_export'],
  ['#/catalogs', 'package', 'خروجی‌های نسخه‌ی ۱', null, 'legacy_export'],
  ['sec', 'الگوها و اسکیماها', 'layout'],
  ['#/schemas', 'columns', 'اسکیماها'],
  ['#/templates', 'tree', 'الگوهای خروجی و درخت فایل'],
  ['#/rules', 'filter', 'قواعد متن و فیلتر'],
  ['#/mappings', 'link', 'نگاشت برند و دسته'],
  ['sec', 'داده‌های مرجع', 'tag'],
  ['#/vehicles', 'car', 'خودروها', null, 'vehicles'],
  ['#/ref/brands', 'tag', 'برندها'],
  ['#/ref/categories', 'tree', 'دسته‌بندی‌ها'],
  ['sec', 'سیستم', 'settings'],
  ['#/ai', 'sparkles', 'هوش مصنوعی', 'ai', 'ai'],
  ['#/revisions', 'branch', 'نسخه‌ها (ریویژن)'],
  ['#/logs', 'scroll', 'گزارش‌ها و تاریخچه'],
  ['#/modules', 'puzzle', 'ماژول‌ها'],
  ['#/backups', 'archive', 'پشتیبان‌گیری'],
  ['#/users', 'users', 'کاربران و نقش‌ها'],
  ['#/mcp', 'cpu', 'اتصال ایجنت‌ها (MCP)', null, 'mcp'],
  ['#/settings', 'settings', 'تنظیمات'],
  ['#/help', 'help', 'راهنما و آموزش'],
];

// راهنمای مرتبط با هر صفحه (دکمه‌ی «؟» بالای صفحه)
const HELP = [
  [/^#\/(new|datasets|queue|sources|raw)/, 'guide/02-raw-data.md'], [/^#\/editor/, 'guide/03-editor.md'], [/^#\/bg/, 'guide/04-images.md'],
  [/^#\/(catalog|exports|catalogs)/, 'guide/06-catalogs.md'], [/^#\/(schemas|templates|rules|mappings)/, 'guide/07-schemas-templates.md'],
  [/^#\/(vehicles|ref)/, 'guide/05-vehicles-reference.md'], [/^#\/(modules|backups|users|settings|revisions|logs|ai|mcp)/, 'guide/08-admin.md'],
  [/^#?\/?$/, 'guide/01-start-here.md'],
];

const modOn = (m) => !m || (S.boot?.modules || {})[m] !== false;

function renderNav() {
  const h = location.hash || '#/';
  const inc = S.summary?.incidents?.length || 0;
  const ov = S.overview || {};
  const items = NAV.filter((n) => n[0] === 'sec' || modOn(n[4]));
  const chip = (t) => `<span class="chip run" style="height:20px;padding:0 7px;font-size:11px"><span class="dot"></span>${t}</span>`;
  document.getElementById('nav').innerHTML = items.map((n, i) => {
    if (n[0] === 'sec') {
      const next = items[i + 1];
      if (!next || next[0] === 'sec') return '';
      return `<div class="nav-sec">${icon(n[2], 13)} ${n[1]}</div>`;
    }
    const on = n[0] === '#/' ? (h === '#/' || h === '' || h === '#') : (h === n[0] || h.startsWith(n[0] + '/'));
    let badge = n[3] === 'incidents' && inc ? `<span class="badge">${fa(inc)}</span>` : '';
    const q = S.summary?.queue;
    if (n[3] === 'queue' && q) badge = q.active ? chip('اجرا') : q.queued ? `<span class="tag" style="font-size:11px">${fa(q.queued)}</span>` : '';
    if (n[3] === 'ai' && S.summary?.ai_running) badge = chip('تولید');
    if (n[3] === 'review' && ov.editor?.review) badge = `<span class="tag" style="font-size:11px">${fa(ov.editor.review)}</span>`;
    if (n[3] === 'dupes' && ov.editor?.dupes) badge = `<span class="badge">${fa(ov.editor.dupes)}</span>`;
    if (n[3] === 'editor' && ov.editor?.running) badge = chip('ورود');
    if (n[3] === 'catalog' && ov.catalog?.building) badge = chip('ساخت');
    return `<a href="${n[0]}" class="${on && !(n[0] === '#/editor' && h.startsWith('#/editor/') && !/^#\/editor\/\d/.test(h)) ? 'on' : ''}">${icon(n[1], 18)}<span>${n[2]}</span>${badge}</a>`;
  }).join('');
  const c = S.summary?.counts;
  document.getElementById('side-foot').innerHTML = c
    ? `<div class="flex between"><span>محصولات خام</span><b>${num(c.products)}</b></div><div class="flex between"><span>محصولات تمیز</span><b>${num(ov.editor?.products)}</b></div>
       <div class="flex between"><span>تأییدشده</span><b>${num(ov.editor?.approved)}</b></div><div class="flex between"><span>انتشارها</span><b>${num(ov.catalog?.releases)}</b></div>
       <div class="xs muted mt8" style="text-align:center">نسخه‌ی ${fa(S.boot?.app?.version || '')} · ${esc(S.boot?.user?.name || '')}</div>`
    : '';
}

async function pollSummary() {
  try {
    const prev = S.summary?.incidents?.map((i) => i.id).join(',');
    [S.summary, S.overview] = await Promise.all([api('/api/summary'), api('/api/overview')]);
    if (S.overview?.modules && S.boot) S.boot.modules = S.overview.modules;
    renderNav();
    const now = S.summary.incidents.map((i) => i.id).join(',');
    if (now && now !== prev) {
      const inc = S.summary.incidents[0];
      toast(`نیاز به تصمیم شما: ${inc.title}`, 'err');
    }
  } catch (e) { /* سرور در دسترس نیست */ }
}

async function route() {
  closeLayers();
  S.timers.forEach(clearInterval);
  S.timers = [];
  if (S.page?.destroy) { try { S.page.destroy(); } catch (e) { /* */ } }
  const h = location.hash || '#/';
  let page = null; const params = {}; let mod = null;
  for (const [rx, p, names, m] of ROUTES) {
    const mm = h.match(rx);
    if (mm) { page = p; mod = m; (names || []).forEach((n, i) => { params[n] = mm[i + 1]; }); break; }
  }
  if (!page) { go('#/'); return; }
  const view = document.getElementById('view');
  if (!modOn(mod)) {
    renderNav();
    document.getElementById('page-title').textContent = 'ماژول غیرفعال';
    document.getElementById('top-actions').innerHTML = '';
    view.innerHTML = `<div class="alert warn">${icon('puzzle')}<div><b>این بخش متعلق به یک ماژول غیرفعال است.</b>از «سیستم ← ماژول‌ها» آن را فعال کنید. <a href="#/modules">رفتن به ماژول‌ها</a></div></div>`;
    return;
  }
  view.innerHTML = `<div class="card"><div class="card-b muted flex">${icon('loader', 18, 'spin')} در حال بارگذاری…</div></div>`;
  if (page.lazy) {
    try { page = await page.lazy(); } catch (e) {
      view.innerHTML = `<div class="alert err">${icon('alert')}<div><b>فایل این بخش بارگذاری نشد.</b>${esc(e.message)}<div class="xs mt8">بقیه‌ی بخش‌های استودیو کار می‌کنند.</div></div></div>`;
      return;
    }
  }
  S.page = page; S.params = params;
  renderNav();
  document.getElementById('page-title').textContent = page.title || '';
  document.getElementById('crumb').textContent = page.crumb || 'استودیو کاتالوگ مگا';
  const help = HELP.find(([rx]) => rx.test(h));
  document.getElementById('top-actions').innerHTML = (page.top ? page.top(params) : '') +
    (help ? `<a class="btn icon ghost" href="#/help/${help[1]}" title="راهنمای این بخش">${icon('help', 18)}</a>` : '');
  try {
    view.innerHTML = await page.render(params);
    if (page.mount) await page.mount(view, params);
  } catch (e) {
    view.innerHTML = `<div class="alert err">${icon('alert')}<div><b>بارگذاری این صفحه ممکن نشد.</b>${esc(e.message)}</div></div>`;
  }
  window.scrollTo(0, 0);
}

function dispatch(kind, ev) {
  const el = ev.target.closest(`[data-${kind}]`);
  if (!el) return;
  const name = el.dataset[kind];
  const page = S.page;
  const table = page && page[kind === 'act' ? 'act' : kind];
  if (table && table[name]) {
    if (kind === 'act' && el.tagName === 'A' && !el.getAttribute('href')?.startsWith('#')) ev.preventDefault();
    Promise.resolve(table[name](el, ev)).catch(errToast);
    return;
  }
  if (kind === 'act' && GLOBAL[name]) { Promise.resolve(GLOBAL[name](el, ev)).catch(errToast); }
}

const GLOBAL = {
  resolve: async (el) => {
    const card = el.closest('[data-incident]');
    const all = card?.querySelector('[data-applyall]')?.checked;
    await resolveIncident(Number(el.dataset.id), el.dataset.action, all);
    await pollSummary();
    if (S.page?.refresh) S.page.refresh(); else route();
  },
  nav: (el) => go(el.dataset.href),
  tour: () => tour(true),
};

// ---------------------------------------------------------------- تور آشنایی (اولین اجرا)
const TOUR = [
  ['dashboard', 'به استودیو کاتالوگ مگا خوش آمدید', 'استودیو در سه مرحله کار می‌کند: <b>داده‌ی خام</b> (استخراج از سایت‌ها) ← <b>ویرایشگر داده‌ها</b> (تمیز کردن، تصاویر، برند، دسته و سازگاری با خودرو) ← <b>کاتالوگ محصولات</b> (ساخت فایل‌های نهایی برای مگا کارز).'],
  ['database', '۱. داده‌های خام', 'لینک صفحه‌ی دسته‌بندی یک فروشگاه را در «استخراج جدید» بدهید. محصولات در یک «بانک داده‌ی خام» جمع می‌شوند. داده‌ی خام دست نمی‌خورد و نسخه‌ی صفر هر محصول است.'],
  ['inbox', '۲. ویرایشگر داده‌ها', 'از بانک خام یک «بانک تمیز» بسازید. هر محصول را اصلاح کنید: متن‌ها، برند و دسته از فهرست مرجع، خودروهای سازگار و تصاویر (حذف پس‌زمینه، برش، پاک‌کن، رنگ). بعد برای بازبینی بفرستید و تأیید کنید.'],
  ['rocket', '۳. کاتالوگ و انتشار', 'یک کاتالوگ بسازید، محصولات تأییدشده را انتخاب کنید و «انتشار» بزنید. فایل‌ها طبق «الگوی خروجی» ساخته می‌شوند و هر انتشار شماره‌دار و تغییرناپذیر است.'],
  ['branch', 'همه‌چیز نسخه‌دار است', 'هر تغییر یک «نسخه» می‌سازد: می‌بینید چه کسی، کی و چه چیزی را عوض کرده و با یک کلیک به نسخه‌ی قبل برمی‌گردید.'],
  ['help', 'راهنما همیشه در دسترس است', 'دکمه‌ی ؟ بالای هر صفحه راهنمای همان بخش را باز می‌کند. راهنمای کامل در «سیستم ← راهنما و آموزش» است.'],
];

function tour(force = false) {
  if (!force && S.boot?.settings?.tour_done) return;
  let i = 0;
  const l = openLayer('modal', '<div id="tour"></div>', { sticky: true, onClose: () => api('/api/settings', { method: 'PUT', body: { tour_done: true } }).catch(() => {}) });
  const draw = () => {
    const [ic, t, b] = TOUR[i];
    l.box.querySelector('#tour').innerHTML = `<div class="card-b" style="padding:28px">
      <div class="flex"><span class="src-logo" style="width:46px;height:46px">${icon(ic, 22)}</span><h3 style="margin:0">${t}</h3></div>
      <div class="mt16" style="line-height:2">${b}</div>
      <div class="flex mt24"><span class="xs muted">${fa(i + 1)} از ${fa(TOUR.length)}</span><span class="grow"></span>
        <button class="btn ghost" data-close>رد کردن</button>${i > 0 ? '<button class="btn" data-prev>قبلی</button>' : ''}
        <button class="btn primary" data-next>${i === TOUR.length - 1 ? 'شروع کار' : 'بعدی'}</button></div></div>`;
    l.box.querySelector('[data-next]').onclick = () => { if (i === TOUR.length - 1) l.close(); else { i++; draw(); } };
    const pv = l.box.querySelector('[data-prev]');
    if (pv) pv.onclick = () => { i--; draw(); };
  };
  draw();
}

document.addEventListener('click', (e) => {
  // منوهای کشویی (.ddmenu): دکمه‌ی [data-dd] باز و بسته می‌کند؛ کلیک بیرون یا روی یک گزینه می‌بندد
  const dd = e.target.closest('[data-dd]');
  document.querySelectorAll('.ddmenu.open').forEach((m) => { if (!dd || m !== dd.closest('.ddmenu')) m.classList.remove('open'); });
  if (dd) { dd.closest('.ddmenu').classList.toggle('open'); return; }
  dispatch('act', e);
});
document.addEventListener('change', (e) => dispatch('change', e));
document.addEventListener('input', (e) => dispatch('input', e));
window.addEventListener('hashchange', route);

(async function init() {
  window.__studioReady = true;
  for (let i = 0; ; i++) {
    try { await refreshBoot(); break; } catch (e) {
      // استودیو ممکن است هنوز در حال آماده‌سازی باشد؛ به‌جای خطای ثابت، خودکار دوباره تلاش می‌شود
      document.getElementById('view').innerHTML = `<div class="alert ${i > 10 ? 'err' : 'info'}">${icon(i > 10 ? 'alert' : 'loader', 18, i > 10 ? '' : 'spin')}<div><b>${i > 10 ? 'استودیو پاسخ نمی‌دهد.' : 'در حال اتصال به استودیو…'}</b>${esc(e.message)} — تلاش ${fa(i + 1)}</div></div>`;
      await new Promise((r) => setTimeout(r, Math.min(5000, 800 + i * 400)));
    }
  }
  await pollSummary();
  setInterval(pollSummary, 4000);
  await route();
  tour();
})();

export { route, pollSummary, okToast };
