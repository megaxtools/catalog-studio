// پیشخوان نسخه‌ی ۲، ماژول‌ها، پشتیبان‌گیری، کاربران، نسخه‌ها (ریویژن) و راهنما
import { S, api, icon, esc, attr, fa, num, jdate, toast, okToast, errToast, openLayer, confirmDlg, emptyState, every, go, trunc, fileUrl, openPath, refreshBoot } from './core.js';
import { busy } from './ai_assist.js';
import { ACTOR, ACTOR_IC, fieldName, fileToDataUrl, revisionsPanel } from './widgets.js';

// ======================================================================
// پیشخوان
// ======================================================================
export const Home = {
  title: 'پیشخوان',
  crumb: 'استودیو کاتالوگ مگا · از داده‌ی خام تا کاتالوگ نهایی مگا کارز',
  top: () => `<button class="btn ghost" data-act="tour">${icon('help', 16)} تور آشنایی</button>`,
  async render() {
    const [ov, sm] = await Promise.all([api('/api/overview'), api('/api/summary')]);
    const banks = await api('/api/wb/banks');
    const cats = await api('/api/cat/catalogs');
    const pipe = (n, ic, title, big, sub, links, last) => `<div class="pipe"><span class="src-logo">${icon(ic, 20)}</span><h3>${fa(n)}. ${title}</h3>
      <div class="n">${big}</div><div class="small muted">${sub}</div><div class="btns mt12">${links}</div>${last ? '' : `<span class="pipe-arrow">${icon('chevronLeft', 26)}</span>`}</div>`;
    return `${sm.incidents.length ? `<div class="alert warn mb12">${icon('alert')}<div class="grow"><b>${fa(sm.incidents.length)} استخراج منتظر تصمیم شماست.</b>${esc(sm.incidents[0].title)}</div><a class="btn sm" href="#/datasets/${sm.incidents[0].dataset_id}">بررسی</a></div>` : ''}
      <div class="pipeline">
        ${pipe(1, 'database', 'داده‌های خام', num(ov.raw.items), `محصول خام در ${fa(ov.raw.datasets)} بانک داده`, `<a class="btn sm primary" href="#/new">${icon('plus', 14)} استخراج جدید</a><a class="btn sm" href="#/datasets">بانک‌ها</a>`)}
        ${pipe(2, 'inbox', 'ویرایشگر داده‌ها', num(ov.editor.products), `محصول تمیز · ${fa(ov.editor.approved)} تأییدشده · ${fa(ov.editor.review)} در انتظار بازبینی`, `<a class="btn sm primary" href="#/editor">${icon('edit', 14)} ویرایش</a><a class="btn sm" href="#/editor/review">صف بازبینی</a>`)}
        ${pipe(3, 'rocket', 'کاتالوگ محصولات', num(ov.catalog.releases), `انتشار از ${fa(ov.catalog.catalogs)} کاتالوگ`, `<a class="btn sm primary" href="#/catalog">${icon('rocket', 14)} کاتالوگ‌ها</a><a class="btn sm" href="#/templates">الگوها</a>`, true)}
      </div>
      <div class="grid2 mt16"><div class="card"><div class="card-h"><h3>${icon('inbox', 16)} بانک‌های تمیز</h3><span class="sp"></span><a class="btn sm ghost" href="#/editor">همه</a></div>
        <div class="card-b">${banks.slice(0, 5).map((b) => `<a href="#/editor/${b.id}" class="flex" style="padding:8px 0;border-bottom:1px solid var(--z-100);color:inherit"><b class="small grow">${esc(b.title)}</b>
          <span class="xs muted">${fa(b.counts.total)} محصول · ${fa(b.counts.approved)} تأییدشده</span>${b.quality_avg !== null ? `<span class="tag">${icon('star', 11)} ${fa(b.quality_avg)}</span>` : ''}</a>`).join('') || '<div class="muted small">هنوز بانک تمیزی نیست. از یک بانک خام شروع کنید.</div>'}</div></div>
        <div class="card"><div class="card-h"><h3>${icon('rocket', 16)} آخرین انتشارها</h3><span class="sp"></span><a class="btn sm ghost" href="#/catalog">همه</a></div>
        <div class="card-b">${cats.filter((c) => c.last_release).slice(0, 5).map((c) => `<a href="#/catalog/release/${c.last_release.id}" class="flex" style="padding:8px 0;border-bottom:1px solid var(--z-100);color:inherit"><b class="small grow">${esc(c.title)}</b>
          <span class="tag">r${fa(c.last_release.number)}</span><span class="xs muted">${jdate(c.last_release.created_at)}</span></a>`).join('') || '<div class="muted small">هنوز انتشاری نیست.</div>'}</div></div></div>
      <div class="grid3 mt16">
        <a class="card" href="#/vehicles" style="color:inherit"><div class="card-b flex"><span class="src-logo">${icon('car', 18)}</span><div><b>خودروها</b><div class="xs muted">بانک مرجع سازگاری</div></div></div></a>
        <a class="card" href="#/ref/brands" style="color:inherit"><div class="card-b flex"><span class="src-logo">${icon('tag', 18)}</span><div><b>${fa(ov.ref.brands)} برند · ${fa(ov.ref.categories)} دسته</b><div class="xs muted">فهرست‌های مرجع مگا کارز</div></div></div></a>
        <a class="card" href="#/help" style="color:inherit"><div class="card-b flex"><span class="src-logo">${icon('help', 18)}</span><div><b>راهنما و آموزش</b><div class="xs muted">از صفر تا انتشار، قدم‌به‌قدم</div></div></div></a></div>
      <div class="mt16"><a class="small" href="#/raw">${icon('gauge', 13)} پیشخوان قدیمی داده‌های خام (اجراهای فعال و هشدارها)</a></div>`;
  },
};

// ======================================================================
// ماژول‌ها
// ======================================================================
export const Modules = {
  title: 'ماژول‌ها',
  crumb: 'سیستم · هر قابلیت جانبی یک ماژول است؛ با خاموش کردنش بقیه‌ی استودیو بدون مشکل کار می‌کند',
  async render() {
    const list = await api('/api/modules');
    const byId = Object.fromEntries(list.map((m) => [m.id, m]));
    const card = (m) => `<div class="mod-card"><span class="src-logo" style="${m.status !== 'ok' ? 'background:var(--err-bg);color:var(--err)' : ''}">${icon(m.core ? 'shield' : 'puzzle', 18)}</span>
      <div class="grow"><div class="flex wrap" style="gap:6px"><b>${esc(m.name)}</b><span class="xs muted ltr">${esc(m.id)} · v${esc(m.version)}</span>${m.core ? '<span class="tag">هسته</span>' : ''}
          ${m.status !== 'ok' ? `<span class="chip err">خطا</span>` : m.enabled ? '<span class="chip ok"><span class="dot"></span>فعال</span>' : '<span class="chip idle">غیرفعال</span>'}</div>
        <div class="small muted mt4">${esc(m.description)}</div>
        ${m.error ? `<div class="xs mt4" style="color:var(--err)">${esc(m.error)}</div>` : ''}${m.health ? `<div class="xs mt4" style="color:${m.healthy ? 'var(--ok)' : 'var(--warn)'}">${esc(m.health)}</div>` : ''}
        ${m.requires.length ? `<div class="xs muted mt4">نیاز به: ${m.requires.map((r) => esc(byId[r]?.name || r)).join('، ')}</div>` : ''}
        ${m.tables.length ? `<div class="xs muted mt4 ltr" style="text-align:right">جدول‌ها: ${m.tables.map(esc).join(', ')}</div>` : ''}</div>
      ${m.core ? '' : `<label class="switch" title="روشن/خاموش"><input type="checkbox" data-change="toggle" data-id="${m.id}" ${m.switch ? 'checked' : ''} ${m.status !== 'ok' ? 'disabled' : ''}><span></span></label>`}</div>`;
    return `<div class="alert info">${icon('info')}<div>خاموش کردن یک ماژول داده‌ای را پاک نمی‌کند؛ فقط صفحه‌ها، مسیرهای API و ابزارهای ایجنتِ آن غیرفعال می‌شوند. اگر ماژولی هنگام شروع خطا بدهد، خودکار کنار گذاشته می‌شود و بقیه کار می‌کنند.</div></div>
      <div class="card mt16"><div class="card-h"><h3>ماژول‌های قابل خاموش کردن</h3></div>${list.filter((m) => !m.core).map(card).join('')}</div>
      <div class="card mt16"><div class="card-h"><h3>بخش‌های هسته</h3></div>${list.filter((m) => m.core).map(card).join('')}</div>`;
  },
  change: {
    toggle: async (el) => {
      try {
        await api(`/api/modules/${el.dataset.id}`, { method: 'PUT', body: { enabled: el.checked } });
        await refreshBoot();
        okToast(el.checked ? 'ماژول فعال شد.' : 'ماژول غیرفعال شد.');
      } catch (e) { el.checked = !el.checked; errToast(e); }
      const v = document.getElementById('view');
      v.innerHTML = await Modules.render();
    },
  },
};

// ======================================================================
// پشتیبان‌گیری
// ======================================================================
export const Backups = {
  title: 'پشتیبان‌گیری',
  crumb: 'سیستم · پشتیبان پایگاه داده‌ی استودیو و بازگردانی آن',
  top: () => `<label class="btn">${icon('upload', 16)} بارگذاری پشتیبان<input type="file" accept=".zip" data-change="upload" hidden></label><button class="btn primary" data-act="create">${icon('archive', 16)} پشتیبان تازه</button>`,
  async render() {
    const r = await api('/api/backups');
    const st = S.boot?.settings || {};
    return `${r.pending_restore ? `<div class="alert warn">${icon('alert')}<div class="grow"><b>یک پشتیبان برای بازگردانی آماده است.</b>استودیو را ببندید و دوباره اجرا کنید تا جایگزین شود (قبلش از وضعیت فعلی هم نسخه‌ی پشتیبان گرفته می‌شود).</div><button class="btn sm" data-act="cancel">لغو</button></div>` : ''}
      <div class="card ${r.pending_restore ? 'mt16' : ''}"><div class="card-b flex wrap"><label class="check"><input type="checkbox" data-change="auto" ${st.backup_auto !== false ? 'checked' : ''}> پشتیبان خودکار روزانه هنگام شروع استودیو</label>
        <span class="small">نگه‌داشتن آخرین</span><input class="inp sm" type="number" min="1" max="100" value="${st.backup_keep || 10}" data-change="keep" style="width:70px"><span class="small">پشتیبان خودکار</span>
        <span class="grow"></span><button class="btn sm ghost" data-act="folder" data-path="${attr(r.dir)}">${icon('folder', 14)} پوشه‌ی پشتیبان‌ها</button></div></div>
      <div class="card mt16"><div class="tbl-wrap">${r.backups.length ? `<table class="tbl"><thead><tr><th>فایل</th><th>زمان</th><th>نسخه‌ی استودیو</th><th>حجم</th><th>یادداشت</th><th></th></tr></thead><tbody>
        ${r.backups.map((b) => `<tr><td class="small ltr" style="text-align:right">${esc(b.name)}${b.auto ? ' <span class="tag">خودکار</span>' : ''}${b.with_images ? ' <span class="tag">با تصاویر</span>' : ''}</td><td class="xs">${jdate(b.created_at)}</td><td class="xs">${esc(b.version || '')}</td>
          <td class="xs">${fa((b.size / 1048576).toFixed(1))} مگابایت</td><td class="xs muted">${esc(b.note)}</td>
          <td class="nowrap"><a class="btn xs soft" href="${fileUrl(b.path, true)}">${icon('download', 12)}</a> <button class="btn xs ghost" data-act="restore" data-name="${attr(b.name)}">${icon('undo', 12)} بازگردانی</button> <button class="btn xs ghost danger" data-act="del" data-name="${attr(b.name)}">${icon('trash', 12)}</button></td></tr>`).join('')}</tbody></table>`
        : `<div class="card-b">${emptyState('archive', 'هنوز پشتیبانی نیست', 'پشتیبان شامل همه‌ی داده‌ها، تنظیمات، اسکیماها، محصولات تمیز، ریویژن‌ها و کاتالوگ‌هاست.')}</div>`}</div></div>`;
  },
  async rerender() { document.getElementById('view').innerHTML = await this.render(); },
  act: {
    create: async () => {
      const l = openLayer('modal', `<div class="card-h"><h3>پشتیبان تازه</h3></div><div class="card-b"><div class="field"><label>یادداشت (اختیاری)</label><input class="inp" id="bk-n" placeholder="مثلاً: پیش از تغییر اسکیما"></div>
        <label class="check mt12"><input type="checkbox" id="bk-i"> تصاویر ویرایشگر هم ذخیره شوند (حجم زیاد)</label></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="bk-ok">${icon('archive', 16)} ساخت</button></div>`);
      l.box.querySelector('#bk-ok').addEventListener('click', async (ev) => {
        busy(ev.currentTarget, true, 'در حال ساخت…');
        try { await api('/api/backups', { body: { note: l.box.querySelector('#bk-n').value, with_images: l.box.querySelector('#bk-i').checked } }); okToast('پشتیبان ساخته شد.'); l.close(); Backups.rerender(); } catch (e) { errToast(e); }
      });
    },
    restore: async (el) => {
      if (!(await confirmDlg('بازگردانی پشتیبان', `پایگاه داده با «${esc(el.dataset.name)}» جایگزین شود؟ این کار در شروع بعدی استودیو انجام می‌شود و پیش از آن از وضعیت فعلی هم یک نسخه نگه داشته می‌شود.`, 'آماده‌سازی بازگردانی', true))) return;
      const r = await api('/api/backups/restore', { body: { name: el.dataset.name } }); okToast(r.message); Backups.rerender();
    },
    cancel: async () => { await api('/api/backups/cancel-restore', { body: {} }); Backups.rerender(); },
    del: async (el) => { if (!(await confirmDlg('حذف پشتیبان', 'این فایل پشتیبان حذف شود؟', 'حذف', true))) return; await api(`/api/backups/${encodeURIComponent(el.dataset.name)}`, { method: 'DELETE' }); Backups.rerender(); },
    folder: (el) => openPath(el.dataset.path),
  },
  change: {
    auto: async (el) => { await api('/api/settings', { method: 'PUT', body: { backup_auto: el.checked } }); await refreshBoot(); okToast('ذخیره شد.'); },
    keep: async (el) => { await api('/api/settings', { method: 'PUT', body: { backup_keep: Number(el.value) } }); await refreshBoot(); okToast('ذخیره شد.'); },
    upload: async (el) => { const f = el.files[0]; if (!f) return; await api('/api/backups/upload', { body: { data_url: await fileToDataUrl(f), name: f.name } }); okToast('پشتیبان بارگذاری شد.'); Backups.rerender(); },
  },
};

// ======================================================================
// کاربران
// ======================================================================
export const Users = {
  title: 'کاربران و نقش‌ها',
  crumb: 'سیستم · دو نقش: مدیر و اپراتور',
  async render() {
    const list = await api('/api/users');
    return `<div class="alert info">${icon('info')}<div><b>در نسخه‌ی ۲ استودیو فقط در اختیار مدیر است.</b>ساختار نقش‌ها آماده است: هر تغییر و هر نسخه به نام کاربر ثبت می‌شود. ورود اپراتورها با نام کاربری و محدودیت دسترسی‌ها در نسخه‌های بعدی فعال می‌شود.</div></div>
      <div class="card mt16"><div class="card-h"><h3>کاربران</h3><span class="sp"></span><button class="btn sm soft" data-act="add">${icon('plus', 14)} کاربر</button></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>نام</th><th>نام کاربری</th><th>نقش</th><th>وضعیت</th><th>نسخه‌های ثبت‌شده</th><th></th></tr></thead><tbody>
      ${list.map((u) => `<tr><td><b class="small">${esc(u.name)}</b>${u.current ? ' <span class="tag p">شما</span>' : ''}</td><td class="small ltr" style="text-align:right">${esc(u.username)}</td>
        <td><select class="inp sm" data-change="role" data-id="${u.id}" style="width:auto" ${u.id === 1 ? 'disabled' : ''}><option value="admin" ${u.role === 'admin' ? 'selected' : ''}>مدیر</option><option value="operator" ${u.role === 'operator' ? 'selected' : ''}>اپراتور</option></select></td>
        <td>${u.active ? '<span class="chip ok">فعال</span>' : '<span class="chip idle">غیرفعال</span>'}</td><td class="small">${num(u.revisions)}</td>
        <td>${u.id !== 1 ? `<button class="btn xs ghost" data-act="toggle" data-id="${u.id}" data-on="${u.active ? 0 : 1}">${u.active ? 'غیرفعال' : 'فعال'}</button>` : ''}</td></tr>`).join('')}</tbody></table></div></div>
      <div class="card mt16"><div class="card-h"><h3>سطوح دسترسی (طراحی برای نسخه‌های بعد)</h3></div><div class="card-b small" style="line-height:2.1">
        <b>مدیر:</b> همه‌ی بخش‌ها؛ ماژول‌ها، پشتیبان‌گیری، کاربران، اسکیماها و الگوها، اتصال‌های هوش مصنوعی، تأیید نهایی محصولات و ساخت انتشار.<br>
        <b>اپراتور:</b> استخراج، ویرایش محصولات تمیز، ویرایش تصاویر، پیشنهاد سازگاری و ارسال برای بازبینی؛ بدون حذف بانک‌ها، تغییر تنظیمات سیستم و انتشار کاتالوگ.</div></div>`;
  },
  async rerender() { document.getElementById('view').innerHTML = await this.render(); },
  act: {
    add: () => {
      const l = openLayer('modal', `<div class="card-h"><h3>کاربر تازه</h3></div><div class="card-b form-grid"><div class="field"><label>نام</label><input class="inp" id="u-n"></div><div class="field"><label>نام کاربری (انگلیسی)</label><input class="inp ltr" id="u-u"></div>
        <div class="field"><label>نقش</label><select class="inp" id="u-r"><option value="operator">اپراتور</option><option value="admin">مدیر</option></select></div></div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="u-ok">افزودن</button></div>`);
      l.box.querySelector('#u-ok').addEventListener('click', async () => {
        try { await api('/api/users', { body: { name: l.box.querySelector('#u-n').value, username: l.box.querySelector('#u-u').value, role: l.box.querySelector('#u-r').value } }); l.close(); Users.rerender(); } catch (e) { errToast(e); }
      });
    },
    toggle: async (el) => { await api(`/api/users/${el.dataset.id}`, { method: 'PUT', body: { active: el.dataset.on === '1' } }); Users.rerender(); },
  },
  change: { role: async (el) => { try { await api(`/api/users/${el.dataset.id}`, { method: 'PUT', body: { role: el.value } }); okToast('ذخیره شد.'); } catch (e) { errToast(e); } } },
};

// ======================================================================
// نسخه‌ها (ریویژن‌ها)
// ======================================================================
const RV = { entity: '', page: 1, q: '', actor: '' };
const ENT = { '': 'همه', product: 'محصولات تمیز', raw_item: 'محصولات خام', schema: 'اسکیماها', template: 'الگوهای خروجی', catalog: 'کاتالوگ‌ها', ref_brand: 'برندها', ref_category: 'دسته‌ها', vehicle_model: 'خودروها' };
export const Revisions = {
  title: 'نسخه‌ها (ریویژن)',
  crumb: 'سیستم · هر تغییر داده یک نسخه‌ی کامل با مقدار قبل و بعد؛ قابل مقایسه و بازگردانی',
  async render() {
    return `<div class="card"><div class="flex wrap" style="padding:14px 16px;border-bottom:1px solid var(--z-100)">
      <div class="seg">${Object.entries(ENT).map(([k, v]) => `<button class="${RV.entity === k ? 'on' : ''}" data-act="ent" data-v="${k}">${v}</button>`).join('')}</div>
      <select class="inp sm" style="width:auto" data-change="actor"><option value="">همه‌ی کننده‌ها</option>${Object.entries(ACTOR).map(([k, v]) => `<option value="${k}" ${RV.actor === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <span class="grow"></span></div><div class="tbl-wrap" id="rv-list"></div><div class="pager" id="rv-pager"></div></div>`;
  },
  async mount() { await this.load(); },
  async load() {
    const qs = new URLSearchParams({ page: RV.page, size: 60 });
    if (RV.entity) qs.set('entity', RV.entity);
    if (RV.actor) qs.set('actor', RV.actor);
    const r = await api(`/api/revisions?${qs}`);
    document.getElementById('rv-list').innerHTML = r.rows.length ? `<table class="tbl"><thead><tr><th>زمان</th><th>موجودیت</th><th>نسخه</th><th>عمل</th><th>کننده</th><th>فیلدها</th><th></th></tr></thead><tbody>
      ${r.rows.map((x) => `<tr><td class="xs nowrap">${jdate(x.created_at)}</td><td class="small">${esc(x.entity_label)} <span class="xs muted">#${fa(x.entity_id)}</span></td><td><b>${fa(x.rev)}</b></td>
        <td class="small">${esc(x.action_label)}${x.note ? `<div class="xs muted">${esc(trunc(x.note, 60))}</div>` : ''}</td><td class="xs">${icon(ACTOR_IC[x.actor] || 'users', 11)} ${esc(ACTOR[x.actor] || x.actor)}</td>
        <td><div class="flex wrap" style="gap:3px">${x.fields.slice(0, 6).map((f) => `<span class="tag" style="font-size:10.5px">${fieldName(f)}</span>`).join('')}</div></td>
        <td><button class="btn xs ghost" data-act="open" data-e="${x.entity}" data-id="${x.entity_id}">${icon('branch', 12)} همه‌ی نسخه‌ها</button></td></tr>`).join('')}</tbody></table>`
      : `<div class="card-b">${emptyState('branch', 'نسخه‌ای ثبت نشده', '')}</div>`;
    const pages = Math.max(1, Math.ceil(r.total / 60));
    document.getElementById('rv-pager').innerHTML = `<button class="btn sm" data-act="pg" data-p="${RV.page - 1}" ${RV.page <= 1 ? 'disabled' : ''}>قبلی</button><span class="small">${num(r.total)} نسخه</span><button class="btn sm" data-act="pg" data-p="${RV.page + 1}" ${RV.page >= pages ? 'disabled' : ''}>بعدی</button>`;
  },
  act: {
    ent: (el) => { RV.entity = el.dataset.v; RV.page = 1; el.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === el)); Revisions.load(); },
    pg: (el) => { RV.page = Number(el.dataset.p); Revisions.load(); },
    open: (el) => {
      const l = openLayer('modal', `<div class="card-h"><h3>${icon('branch', 18)} نسخه‌ها</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><div class="card-b" id="rvp" style="max-height:72vh;overflow:auto"></div>`, { wide: true });
      revisionsPanel(l.box.querySelector('#rvp'), el.dataset.e, Number(el.dataset.id), () => { l.close(); Revisions.load(); });
    },
  },
  change: { actor: (el) => { RV.actor = el.value; RV.page = 1; Revisions.load(); } },
};

// ======================================================================
// راهنما و مستندات
// ======================================================================
export function md(src) {
  const lines = src.replace(/\r/g, '').split('\n');
  let out = ''; let i = 0;
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*([^*]+)\*/g, '<i>$1</i>')
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img alt="$1" src="$2">')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, h) => `<a href="${h.endsWith('.md') && !h.startsWith('http') ? '#/help/' + h.replace(/^\.\.\//, '').replace(/^\.\//, '') : h}" ${h.startsWith('http') ? 'target="_blank"' : ''}>${t}</a>`);
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith('```')) { let code = ''; i++; while (i < lines.length && !lines[i].startsWith('```')) { code += esc(lines[i]) + '\n'; i++; } out += `<pre><code>${code}</code></pre>`; i++; continue; }
    const h = l.match(/^(#{1,4}) (.*)/);
    if (h) { out += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; i++; continue; }
    if (l.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) { rows.push(lines[i]); i++; }
      const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      out += `<table><thead><tr>${cells(rows[0]).map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(2).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
      continue;
    }
    if (/^\s*[-*] /.test(l)) { out += '<ul>'; while (i < lines.length && /^\s*[-*] /.test(lines[i])) { out += `<li>${inline(lines[i].replace(/^\s*[-*] /, ''))}</li>`; i++; } out += '</ul>'; continue; }
    if (/^\d+\. /.test(l)) { out += '<ol>'; while (i < lines.length && /^\d+\. /.test(lines[i])) { out += `<li>${inline(lines[i].replace(/^\d+\. /, ''))}</li>`; i++; } out += '</ol>'; continue; }
    if (l.startsWith('> ')) { let q = ''; while (i < lines.length && lines[i].startsWith('> ')) { q += inline(lines[i].slice(2)) + '<br>'; i++; } out += `<blockquote>${q}</blockquote>`; continue; }
    if (!l.trim()) { i++; continue; }
    let p = '';
    while (i < lines.length && lines[i].trim() && !/^(#|```|\||\s*[-*] |\d+\. |> )/.test(lines[i])) { p += inline(lines[i]) + ' '; i++; }
    out += `<p>${p}</p>`;
  }
  return out;
}

export const Help = {
  title: 'راهنما و آموزش',
  crumb: 'راهنمای اپراتور و مدیر، و مستندات طراحی و توسعه',
  top: () => `<button class="btn ghost" data-act="tour">${icon('play', 16)} تور آشنایی</button>`,
  async render(p) {
    const groups = await api('/api/docs');
    const cur = p.doc || groups[0]?.docs[0]?.path;
    if (!cur) return `<div class="card"><div class="card-b">${emptyState('help', 'مستندات پیدا نشد', 'پوشه‌ی docs در کنار برنامه نیست.')}</div></div>`;
    let doc;
    try { doc = await api(`/api/docs/${cur}`); } catch (e) { doc = { title: 'پیدا نشد', content: '# سند پیدا نشد' }; }
    return `<div class="split" style="grid-template-columns:280px 1fr"><div class="card"><div class="card-b help-nav">${groups.map((g) => `<div class="lbl mt12 mb8">${esc(g.label)}</div>${g.docs.map((d) => `<a href="#/help/${d.path}" class="${d.path === cur ? 'on' : ''}">${esc(d.title)}</a>`).join('')}`).join('')}</div></div>
      <div class="card"><div class="card-b md">${md(doc.content)}</div></div></div>`;
  },
};

go; every; toast; // eslint-disable-line no-unused-expressions
