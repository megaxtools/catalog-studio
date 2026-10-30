import { S, api, icon, esc, fa, num, toast, errToast, okToast, refreshBoot, go } from './core.js';
import { Dashboard, NewRun, Datasets, Dataset, resolveIncident } from './pages_main.js';
import { Exports, Bg, Mappings, Settings } from './pages_tools.js';
import { Logs } from './pages_logs.js';
import { Catalogs, CatalogDetail } from './pages_catalogs.js';
import { Sources, SourceEditor, Schemas, SchemaEditor } from './pages_config.js';
import { AIHub, ProfileEditor, Rules, Queue } from './pages_ai.js';
import { MCP } from './pages_mcp.js';
import './ai_assist.js';

const ROUTES = [
  [/^#?\/?$/, Dashboard],
  [/^#\/new$/, NewRun],
  [/^#\/new\/(ai)$/, NewRun, ['mode']],
  [/^#\/datasets$/, Datasets],
  [/^#\/datasets\/(\d+)$/, Dataset, ['id']],
  [/^#\/queue$/, Queue],
  [/^#\/ai$/, AIHub],
  [/^#\/ai\/profiles\/(\d+)$/, ProfileEditor, ['id']],
  [/^#\/rules$/, Rules],
  [/^#\/exports$/, Exports],
  [/^#\/catalogs$/, Catalogs],
  [/^#\/catalogs\/(\d+)$/, CatalogDetail, ['id']],
  [/^#\/bg$/, Bg],
  [/^#\/sources$/, Sources],
  [/^#\/sources\/(new|\d+)$/, SourceEditor, ['id']],
  [/^#\/schemas$/, Schemas],
  [/^#\/schemas\/(\d+)$/, SchemaEditor, ['id']],
  [/^#\/mappings$/, Mappings],
  [/^#\/mcp$/, MCP],
  [/^#\/logs$/, Logs],
  [/^#\/settings$/, Settings],
];

const NAV = [
  ['#/', 'dashboard', 'پیشخوان'],
  ['#/new', 'plusCircle', 'استخراج جدید'],
  ['#/datasets', 'database', 'بانک‌های داده', 'incidents'],
  ['#/queue', 'layers', 'صف و زمان‌بندی', 'queue'],
  ['#/exports', 'fileSheet', 'خروجی‌ساز'],
  ['#/catalogs', 'package', 'خروجی‌های نهایی'],
  ['#/bg', 'frame', 'پردازش تصاویر'],
  ['sec', 'پیکربندی'],
  ['#/sources', 'globe', 'منابع و اسکرپرها'],
  ['#/schemas', 'columns', 'اسکیماهای داده'],
  ['#/ai', 'sparkles', 'هوش مصنوعی', 'ai'],
  ['#/rules', 'filter', 'قواعد متن و فیلتر'],
  ['#/mappings', 'link', 'نگاشت برند و دسته'],
  ['sec', 'سیستم'],
  ['#/mcp', 'cpu', 'اتصال ایجنت‌ها (MCP)'],
  ['#/logs', 'scroll', 'گزارش‌ها و تاریخچه'],
  ['#/settings', 'settings', 'تنظیمات'],
];

function renderNav() {
  const h = location.hash || '#/';
  const inc = S.summary?.incidents?.length || 0;
  document.getElementById('nav').innerHTML = NAV.map((n) => {
    if (n[0] === 'sec') return `<div class="nav-sec">${n[1]}</div>`;
    const on = n[0] === '#/' ? (h === '#/' || h === '' || h === '#') : h.startsWith(n[0]);
    let badge = n[3] === 'incidents' && inc ? `<span class="badge">${fa(inc)}</span>` : '';
    const q = S.summary?.queue;
    if (n[3] === 'queue' && q) badge = q.active ? '<span class="chip run" style="height:20px;padding:0 7px;font-size:11px"><span class="dot"></span>اجرا</span>' : q.queued ? `<span class="tag" style="font-size:11px">${fa(q.queued)}</span>` : '';
    if (n[3] === 'ai' && S.summary?.ai_running) badge = '<span class="chip run" style="height:20px;padding:0 7px;font-size:11px"><span class="dot"></span>تولید</span>';
    return `<a href="${n[0]}" class="${on ? 'on' : ''}">${icon(n[1], 18)}<span>${n[2]}</span>${badge}</a>`;
  }).join('');
  const c = S.summary?.counts;
  document.getElementById('side-foot').innerHTML = c
    ? `<div class="flex between"><span>بانک‌های داده</span><b>${num(c.datasets)}</b></div><div class="flex between"><span>محصولات</span><b>${num(c.products)}</b></div><div class="flex between"><span>در حال اجرا</span><b>${num(c.running)}</b></div>`
    : '';
}

async function pollSummary() {
  try {
    const prev = S.summary?.incidents?.map((i) => i.id).join(',');
    S.summary = await api('/api/summary');
    renderNav();
    const now = S.summary.incidents.map((i) => i.id).join(',');
    if (now && now !== prev) {
      const inc = S.summary.incidents[0];
      toast(`نیاز به تصمیم شما: ${inc.title}`, 'err');
    }
  } catch (e) { /* سرور در دسترس نیست */ }
}

async function route() {
  S.timers.forEach(clearInterval);
  S.timers = [];
  if (S.page?.destroy) { try { S.page.destroy(); } catch (e) { /* */ } }
  const h = location.hash || '#/';
  let page = null; let params = {};
  for (const [rx, p, names] of ROUTES) {
    const m = h.match(rx);
    if (m) { page = p; (names || []).forEach((n, i) => { params[n] = m[i + 1]; }); break; }
  }
  if (!page) { go('#/'); return; }
  S.page = page; S.params = params;
  renderNav();
  const view = document.getElementById('view');
  document.getElementById('page-title').textContent = page.title || '';
  document.getElementById('crumb').textContent = page.crumb || 'استودیو کاتالوگ مگا';
  document.getElementById('top-actions').innerHTML = page.top ? page.top(params) : '';
  view.innerHTML = `<div class="card"><div class="card-b muted flex">${icon('loader', 18, 'spin')} در حال بارگذاری…</div></div>`;
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
};

document.addEventListener('click', (e) => dispatch('act', e));
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
  route();
})();

export { route, pollSummary };
