// داده‌های مرجع: برندها و دسته‌بندی‌های مگا کارز (فهرست‌های کنترل‌شده با اسلاگ انگلیسی)
// نسخه‌ی ۲.۱: درخت دسته‌ها، دسته‌های هر برند، انتخاب چندتایی و عملیات گروهی، خروجی، ورود با راهنما و نمونه، و هوش مصنوعی
import { api, icon, esc, attr, fa, num, okToast, errToast, openLayer, confirmDlg, promptDlg, emptyState, debounce, toast, S } from './core.js';
import { openRefPicker, revisionsPanel } from './widgets.js';
import { busy, noProviderHint } from './ai_assist.js';
import { openImportDialog } from './import_ui.js';

const aiOn = () => (S.boot?.modules || {}).ai !== false;
const FIELD_FA = { name_en: 'نام انگلیسی', slug: 'اسلاگ', aliases: 'نام‌های دیگر', description: 'توضیح', categories: 'دسته‌ها', country: 'کشور', parent: 'والد' };

// ---------------------------------------------------------------- انتخاب چند دسته (درختی)
export function pickCategories(selected = [], title = 'انتخاب دسته‌بندی‌ها') {
  return new Promise((resolve) => {
    let done = false;
    const sel = new Set(selected);
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('tree', 18)} ${esc(title)}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="card-b"><input class="inp" id="pc-q" placeholder="جست‌وجوی دسته…"><div class="xs muted mt8">برند در دسته‌ی انتخاب‌شده، زیرشاخه‌هایش و دسته‌های بالاترش نمایش داده می‌شود.</div>
        <div id="pc-tree" class="ctree mt8" style="max-height:52vh;overflow:auto"></div></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><span class="small muted" id="pc-n"></span><span class="grow"></span><button class="btn" data-close>انصراف</button><button class="btn primary" id="pc-ok">${icon('check', 16)} ثبت</button></div>`,
    { onClose: () => { if (!done) resolve(undefined); } });
    const b = l.box;
    let tree = [];
    const node = (n) => `<li><div class="cnode"><label class="check grow"><input type="checkbox" data-c="${n.id}" ${sel.has(n.id) ? 'checked' : ''}> <b class="small">${esc(n.name)}</b> <span class="xs muted ltr">${esc(n.slug)}</span></label></div>
      ${n.nodes.length ? `<ul>${n.nodes.map(node).join('')}</ul>` : ''}</li>`;
    const draw = async () => {
      tree = await api(`/api/ref/category/tree?q=${encodeURIComponent(b.querySelector('#pc-q').value.trim())}`);
      b.querySelector('#pc-tree').innerHTML = tree.length ? `<ul>${tree.map(node).join('')}</ul>` : '<div class="muted small">دسته‌ای پیدا نشد. اول در «دسته‌بندی‌ها» دسته بسازید.</div>';
      b.querySelector('#pc-n').textContent = `${fa(sel.size)} دسته انتخاب شده`;
    };
    draw();
    b.querySelector('#pc-q').addEventListener('input', debounce(draw, 200));
    b.querySelector('#pc-tree').addEventListener('change', (e) => {
      const c = e.target.closest('[data-c]');
      if (!c) return;
      if (c.checked) sel.add(Number(c.dataset.c)); else sel.delete(Number(c.dataset.c));
      b.querySelector('#pc-n').textContent = `${fa(sel.size)} دسته انتخاب شده`;
    });
    b.querySelector('#pc-ok').addEventListener('click', () => { done = true; l.close(); resolve([...sel]); });
  });
}

function catChips(cats, max = 4) {
  if (!cats?.length) return '<span class="xs muted">—</span>';
  return `<div class="cat-chips">${cats.slice(0, max).map((c) => `<span class="tag" title="${attr(c.path)}">${esc(c.name)}</span>`).join('')}${cats.length > max ? `<span class="xs muted">+${fa(cats.length - max)}</span>` : ''}</div>`;
}

// ---------------------------------------------------------------- بازبینی پیشنهادهای هوش مصنوعی
function showValue(k, v, p) {
  if (k === 'categories') return esc((p.categories_label || []).join('، '));
  if (k === 'parent') return esc(p.parent_label || '');
  if (Array.isArray(v)) return esc(v.join('، '));
  return esc(v ?? '');
}

function reviewProposals(kind, res, onDone, current = {}) {
  const label = kind === 'brand' ? 'برند' : 'دسته';
  const items = res.items || [];
  if (!items.length) { toast('هوش مصنوعی پیشنهاد تازه‌ای نداد؛ احتمالاً فیلدها پر هستند. «فقط خالی‌ها» را خاموش کنید.', 'err'); return; }
  const keys = (res.fields || []).filter((f) => items.some((x) => x.proposal[f] !== undefined || (f === 'categories' && x.proposal.category_ids) || (f === 'parent' && x.proposal.parent_id)));
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} پیشنهادهای هوش مصنوعی (${fa(items.length)} ${label})</h3><span class="sub">موارد را بررسی و انتخاب کنید؛ ذخیره نسخه‌دار است</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="tbl-wrap" style="max-height:64vh"><table class="tbl"><thead><tr><th style="width:34px"><input type="checkbox" id="rp-all" checked></th><th>${label}</th>${keys.map((k) => `<th>${FIELD_FA[k] || k}</th>`).join('')}</tr></thead><tbody>
    ${items.map((x, i) => `<tr><td><input type="checkbox" data-i="${i}" checked></td><td><b class="small">${esc(x.name)}</b></td>
      ${keys.map((k) => {
    const has = x.proposal[k] !== undefined || (k === 'categories' && x.proposal.category_ids) || (k === 'parent' && x.proposal.parent_id);
    const cur = current[x.id]?.[k];
    return `<td class="xs">${has ? `${cur ? `<div class="muted" style="text-decoration:line-through">${esc(Array.isArray(cur) ? cur.join('، ') : cur)}</div>` : ''}<span class="prop-new ${k === 'slug' || k === 'name_en' ? 'ltr' : ''}">${showValue(k, x.proposal[k], x.proposal)}</span>` : '<span class="muted">—</span>'}</td>`;
  }).join('')}</tr>`).join('')}</tbody></table></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="rp-ok">${icon('save', 16)} ذخیره‌ی انتخاب‌شده‌ها</button></div>`, { wide: true });
  const b = l.box;
  b.querySelector('#rp-all').addEventListener('change', (e) => b.querySelectorAll('[data-i]').forEach((c) => { c.checked = e.target.checked; }));
  b.querySelector('#rp-ok').addEventListener('click', async () => {
    const pick = [...b.querySelectorAll('[data-i]:checked')].map((c) => items[Number(c.dataset.i)]);
    if (!pick.length) { toast('موردی انتخاب نشده است.', 'err'); return; }
    const body = pick.map((x) => {
      const o = { id: x.id, ...x.proposal };
      delete o.categories_label; delete o.parent_label;
      return o;
    });
    try {
      const r = await api(`/api/ref/${kind}/apply`, { body: { items: body } });
      okToast(`${fa(r.updated + r.added)} ${label} ذخیره شد${r.errors.length ? `؛ ${fa(r.errors.length)} خطا` : ''}.`);
      if (r.errors.length) toast(r.errors.slice(0, 3).map((e) => `${e.name}: ${e.error}`).join('؛ '), 'err');
      l.close(); onDone && onDone();
    } catch (e) { errToast(e); }
  });
}

function makePage(kind) {
  const label = kind === 'brand' ? 'برند' : 'دسته‌بندی';
  const plural = kind === 'brand' ? 'برندها' : 'دسته‌بندی‌ها';
  const R = { q: '', items: [], sel: new Set(), view: 'tree', cat: '', inherit: true, closed: new Set() };
  const page = {
    title: plural,
    crumb: `داده‌های مرجع · محصولات تمیز فقط به ${label}‌های همین فهرست وصل می‌شوند (اسلاگ‌ها انگلیسی)`,
    top: () => `<div class="ddmenu"><button class="btn" data-dd>${icon('upload', 16)} ورود و خروج ${icon('chevronDown', 14)}</button><div class="ddm">
        <button data-act="import">${icon('upload', 15)} ورود از فایل (Excel، CSV، JSON)…</button>
        <a href="/api/import/sample/${kind}?format=xlsx" download>${icon('fileSheet', 15)} دانلود فایل نمونه (Excel)</a><hr>
        <a href="/api/ref/${kind}/export?format=xlsx" download>${icon('download', 15)} خروجی همه — Excel</a>
        <a href="/api/ref/${kind}/export?format=csv" download>${icon('download', 15)} خروجی همه — CSV</a>
        <a href="/api/ref/${kind}/export?format=json" download>${icon('download', 15)} خروجی همه — JSON</a></div></div>
      ${aiOn() ? `<div class="ddmenu"><button class="btn soft" data-dd>${icon('sparkles', 16)} هوش مصنوعی ${icon('chevronDown', 14)}</button><div class="ddm">
        <button data-act="aiall">${icon('wand', 15)} تکمیل فیلدهای خالی همه‌ی ${plural}</button>
        <button data-act="aigen">${icon('sparkles', 15)} ${kind === 'brand' ? 'پیشنهاد فهرست برند' : 'پیشنهاد درخت دسته‌بندی'}…</button>
        <button data-act="aimatch">${icon('link', 15)} تطبیق نام‌های خام بدون ${label}</button></div></div>` : ''}
      <button class="btn primary" data-act="add">${icon('plus', 16)} ${label}</button>`,
    async render() {
      R.sel.clear();
      const catFilter = kind === 'brand' ? `<select class="inp sm" style="max-width:240px" data-change="cat"><option value="">همه‌ی دسته‌ها</option></select>
        <label class="check xs" title="برندهای دسته‌های بالاتر و زیرشاخه‌ها هم نمایش داده شوند"><input type="checkbox" data-change="inherit" ${R.inherit ? 'checked' : ''}> با زیرشاخه و والدها</label>` : '';
      const viewSeg = kind === 'category' ? `<div class="seg"><button class="${R.view === 'tree' ? 'on' : ''}" data-act="view" data-v="tree">${icon('tree', 13)} درخت</button><button class="${R.view === 'table' ? 'on' : ''}" data-act="view" data-v="table">${icon('list', 13)} جدول</button></div>` : '';
      return `<div id="rf-un"></div><div id="rf-bulk"></div><div class="card mt16"><div class="card-h"><input class="inp sm" style="width:260px" placeholder="جست‌وجو در نام، نام انگلیسی، اسلاگ…" data-input="q">
        ${catFilter}${viewSeg}<span class="sp"></span>${kind === 'category' && R.view === 'tree' ? `<button class="btn xs ghost" data-act="expand">باز کردن همه</button><button class="btn xs ghost" data-act="collapse">بستن همه</button>` : ''}<span class="small muted" id="rf-count"></span></div>
        <div class="tbl-wrap" id="rf-list" style="max-height:none"></div></div>`;
    },
    async mount() {
      if (kind === 'brand') {
        const cats = await api('/api/ref/category');
        const sel = document.querySelector('[data-change="cat"]');
        sel.innerHTML += cats.map((c) => `<option value="${c.id}" ${String(R.cat) === String(c.id) ? 'selected' : ''}>${esc(c.path)}</option>`).join('');
      }
      await this.load();
    },
    async load() {
      const qs = kind === 'brand' && R.cat ? `?category_id=${R.cat}&inherit=${R.inherit ? 1 : 0}` : '';
      R.items = await api(`/api/ref/${kind}${qs}`);
      if (kind === 'category' && R.view === 'tree') R.tree = await api('/api/ref/category/tree');
      const ids = new Set(R.items.map((x) => x.id));
      [...R.sel].forEach((i) => { if (!ids.has(i)) R.sel.delete(i); });
      this.draw();
      const un = await api(`/api/ref/${kind}/unmatched`);
      const box = document.getElementById('rf-un');
      if (!box) return;
      box.innerHTML = un.length ? `<div class="card"><div class="card-h"><h3>${icon('alert', 16)} نام‌های خام بدون ${label} (${fa(un.length)})</h3><span class="sub">در محصولات تمیز با هیچ ${label}ی تطبیق داده نشدند</span><span class="sp"></span>
          ${aiOn() ? `<button class="btn sm soft" data-act="aimatch">${icon('sparkles', 14)} تطبیق با AI</button>` : ''}<button class="btn sm soft" data-act="addsel">${icon('plus', 14)} افزودن انتخاب‌شده‌ها به فهرست</button></div>
        <div class="tbl-wrap" style="max-height:320px"><table class="tbl"><thead><tr><th style="width:34px"></th><th>نام در داده‌ی خام</th><th>محصولات</th><th>اسلاگ پیشنهادی</th><th></th></tr></thead><tbody>
        ${un.map((u, i) => `<tr data-un="${i}"><td><input type="checkbox" data-sel></td><td><b class="small">${esc(u.name)}</b></td><td class="small">${num(u.count)}</td>
          <td><input class="inp sm ltr mono" data-slug value="${attr(u.slug)}" style="max-width:220px"></td>
          <td><button class="btn xs soft" data-act="link" data-name="${attr(u.name)}">${icon('link', 12)} وصل به ${label} موجود</button></td></tr>`).join('')}</tbody></table></div></div>` : '';
      box._un = un;
    },
    filtered() {
      const q = R.q.toLowerCase();
      return R.items.filter((x) => !q || [x.name, x.name_en, x.slug, x.path, x.description, ...(x.aliases || [])].join(' ').toLowerCase().includes(q));
    },
    draw() {
      const rows = this.filtered();
      document.getElementById('rf-count').textContent = `${fa(rows.length)} ${label}`;
      const list = document.getElementById('rf-list');
      if (!R.items.length) {
        list.innerHTML = `<div class="card-b">${emptyState(kind === 'brand' ? 'tag' : 'tree', R.cat ? `در این دسته ${label}ی نیست` : `${label}ی ثبت نشده`,
          `${label}‌های مگا کارز را دستی اضافه کنید، از فایل وارد کنید${aiOn() ? ' یا با هوش مصنوعی پیشنهاد بگیرید' : ''}.`,
          `<button class="btn soft" data-act="import">${icon('upload', 15)} ورود از فایل</button>${aiOn() ? ` <button class="btn soft" data-act="aigen">${icon('sparkles', 15)} پیشنهاد با AI</button>` : ''}`)}</div>`;
      } else if (kind === 'category' && R.view === 'tree' && !R.q) {
        list.innerHTML = `<div class="ctree">${this.treeHtml(R.tree)}</div>`;
      } else {
        const all = rows.length && rows.every((x) => R.sel.has(x.id));
        list.innerHTML = `<table class="tbl"><thead><tr><th style="width:34px"><input type="checkbox" data-change="selall" ${all ? 'checked' : ''}></th><th>نام</th><th>نام انگلیسی</th><th>اسلاگ</th>
          ${kind === 'brand' ? '<th>دسته‌ها</th>' : '<th>برندها</th>'}<th>نام‌های دیگر</th><th>محصولات</th><th></th></tr></thead><tbody>
          ${rows.map((x) => `<tr class="${R.sel.has(x.id) ? 'selrow' : ''}"><td><input type="checkbox" data-change="sel" data-id="${x.id}" ${R.sel.has(x.id) ? 'checked' : ''}></td>
            <td><b class="small">${esc(kind === 'category' ? x.path : x.name)}</b>${x.active ? '' : ' <span class="tag">غیرفعال</span>'}${x.description ? `<div class="xs muted">${esc(x.description).slice(0, 90)}</div>` : ''}</td>
            <td class="small ltr">${esc(x.name_en || '')}</td><td class="small ltr mono">${esc(x.slug)}</td>
            <td>${kind === 'brand' ? catChips(x.categories) : `<span class="small">${num(x.brands)}</span>`}</td>
            <td class="xs muted">${esc((x.aliases || []).join('، '))}</td><td class="small">${num(x.products)}</td>
            <td class="nowrap">${this.rowActs(x)}</td></tr>`).join('')}</tbody></table>`;
      }
      this.drawBulk();
    },
    rowActs(x) {
      return `${kind === 'category' ? `<button class="btn xs ghost" data-act="addchild" data-id="${x.id}" title="زیرشاخه">${icon('plus', 12)}</button>` : ''}
        <button class="btn xs ghost" data-act="edit" data-id="${x.id}" title="ویرایش">${icon('edit', 12)}</button><button class="btn xs ghost" data-act="revs" data-id="${x.id}" title="نسخه‌ها">${icon('branch', 12)}</button>
        <button class="btn xs ghost danger" data-act="del" data-id="${x.id}" title="حذف">${icon('trash', 12)}</button>`;
    },
    treeHtml(nodes) {
      const li = (n) => `<li class="${R.closed.has(n.id) ? 'closed' : ''}"><div class="cnode ${R.sel.has(n.id) ? 'sel' : ''} ${n.active ? '' : 'off'}">
          <button class="tg ${n.nodes.length ? '' : 'leaf'}" data-act="toggle" data-id="${n.id}">${icon(R.closed.has(n.id) ? 'chevronLeft' : 'chevronDown', 14)}</button>
          <input type="checkbox" data-change="sel" data-id="${n.id}" ${R.sel.has(n.id) ? 'checked' : ''}>
          <b class="small">${esc(n.name)}</b><span class="xs muted ltr mono">${esc(n.slug)}</span>${n.active ? '' : '<span class="tag">غیرفعال</span>'}
          <span class="grow"></span><span class="xs muted" title="محصولات (با زیرشاخه‌ها) و برندهای وصل‌شده">${num(n.products_total)} محصول، ${num(n.brands)} برند</span>
          <span class="acts">${this.rowActs(n)}</span></div>
        ${n.nodes.length ? `<ul>${n.nodes.map(li).join('')}</ul>` : ''}</li>`;
      return `<ul>${(nodes || []).map(li).join('')}</ul>`;
    },
    drawBulk() {
      const box = document.getElementById('rf-bulk');
      if (!box) return;
      const n = R.sel.size;
      box.innerHTML = n ? `<div class="bulkbar"><b>${fa(n)} ${label} انتخاب شده</b>
        <button class="btn xs" data-act="bulk" data-a="activate">${icon('check', 12)} فعال</button><button class="btn xs" data-act="bulk" data-a="deactivate">${icon('x', 12)} غیرفعال</button>
        ${kind === 'brand' ? `<button class="btn xs" data-act="bulkcat" data-a="add_categories">${icon('tree', 12)} افزودن دسته</button><button class="btn xs" data-act="bulkcat" data-a="remove_categories">برداشتن دسته</button><button class="btn xs" data-act="bulkcat" data-a="set_categories">تعیین دسته‌ها</button>`
    : `<button class="btn xs" data-act="bulkparent">${icon('tree', 12)} تعیین والد</button>`}
        <button class="btn xs" data-act="bulkalias">${icon('plus', 12)} نام دیگر</button>
        <a class="btn xs" href="/api/ref/${kind}/export?format=xlsx&ids=${[...R.sel].join(',')}" download>${icon('download', 12)} خروجی Excel</a>
        ${aiOn() ? `<button class="btn xs" data-act="aisel">${icon('sparkles', 12)} تکمیل با AI</button>` : ''}
        <button class="btn xs danger" data-act="bulk" data-a="delete">${icon('trash', 12)} حذف</button><span class="grow"></span><button class="btn xs" data-act="clearsel">لغو انتخاب</button></div>` : '';
    },
    async bulk(action, value, confirmText) {
      if (confirmText && !(await confirmDlg('عملیات گروهی', confirmText, 'تأیید', action === 'delete'))) return;
      try {
        const r = await api(`/api/ref/${kind}/bulk`, { body: { ids: [...R.sel], action, value } });
        okToast(`${fa(r.done)} از ${fa(r.total)} ${label} انجام شد.`);
        if (r.errors.length) toast(r.errors.slice(0, 4).map((e) => `${e.name || e.id}: ${e.error}`).join('؛ '), 'err');
        if (action === 'delete') R.sel.clear();
        page.load();
      } catch (e) { errToast(e); }
    },
    async aiComplete(ids, el) {
      const fields = kind === 'brand' ? ['name_en', 'slug', 'aliases', 'description', 'categories', 'country'] : ['name_en', 'slug', 'aliases', 'description', 'parent'];
      busy(el, true, 'هوش مصنوعی در حال پیشنهاد…');
      try {
        const res = await api(`/api/ref/${kind}/ai-complete`, { body: { ids, fields, only_empty: true } });
        const cur = {};
        R.items.forEach((x) => { cur[x.id] = { name_en: x.name_en, slug: x.slug, description: x.description, country: x.country }; });
        reviewProposals(kind, res, () => page.load(), cur);
      } catch (e) { noProviderHint(e); } finally { busy(el, false); }
    },
    act: {
      add: () => edit(null),
      addchild: (el) => edit(null, Number(el.dataset.id)),
      import: () => openImportDialog(kind, { onDone: () => page.load() }),
      view: (el) => { R.view = el.dataset.v; page.refreshPage(); },
      toggle: (el) => { const id = Number(el.dataset.id); if (R.closed.has(id)) R.closed.delete(id); else R.closed.add(id); page.draw(); },
      expand: () => { R.closed.clear(); page.draw(); },
      collapse: () => { R.items.forEach((x) => { if (x.children) R.closed.add(x.id); }); page.draw(); },
      clearsel: () => { R.sel.clear(); page.draw(); },
      edit: (el) => edit(R.items.find((x) => x.id === Number(el.dataset.id))),
      del: async (el) => {
        if (!(await confirmDlg('حذف', `این ${label} حذف شود؟ اگر محصولی به آن وصل باشد${kind === 'category' ? ' یا زیرشاخه داشته باشد' : ''} حذف نمی‌شود.`, 'حذف', true))) return;
        try { await api(`/api/ref/${kind}/${el.dataset.id}`, { method: 'DELETE' }); okToast('حذف شد.'); page.load(); } catch (e) { errToast(e); }
      },
      revs: (el) => {
        const l = openLayer('modal', `<div class="card-h"><h3>${icon('branch', 18)} نسخه‌ها</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div><div class="card-b" id="rv"></div>`, { wide: true });
        revisionsPanel(l.box.querySelector('#rv'), `ref_${kind}`, Number(el.dataset.id), () => { l.close(); page.load(); });
      },
      bulk: (el) => {
        const a = el.dataset.a;
        page.bulk(a, null, a === 'delete' ? `${fa(R.sel.size)} ${label} حذف شود؟ مواردی که محصول${kind === 'category' ? ' یا زیرشاخه' : ''} دارند حذف نمی‌شوند. حذف از «نسخه‌ها» قابل ردگیری است.` : null);
      },
      bulkcat: async (el) => {
        const ids = await pickCategories([], el.dataset.a === 'remove_categories' ? 'دسته‌هایی که برداشته شوند' : el.dataset.a === 'set_categories' ? 'دسته‌های این برندها (جایگزین فعلی)' : 'دسته‌هایی که افزوده شوند');
        if (ids === undefined) return;
        page.bulk(el.dataset.a, ids);
      },
      bulkparent: async () => {
        const id = await openRefPicker('category', null);
        if (id === undefined) return;
        page.bulk('set_parent', id);
      },
      bulkalias: async () => {
        const v = await promptDlg('افزودن نام دیگر', 'نام‌های دیگر (جدا با ویرگول)', '', 'برای تطبیق خودکار با داده‌ی خام');
        if (v) page.bulk('add_aliases', v);
      },
      aisel: (el) => page.aiComplete([...R.sel], el),
      aiall: (el) => page.aiComplete([], el.closest('.ddmenu').querySelector('[data-dd]')),
      aigen: () => aiGenerate(),
      aimatch: async (el) => {
        const btn = el.closest('.ddmenu')?.querySelector('[data-dd]') || el;
        busy(btn, true, 'در حال تطبیق…');
        try {
          const res = await api(`/api/ref/${kind}/ai-match`, { body: {} });
          if (!res.items.length) { toast(`نام خام بدون ${label}ی نیست.`, 'ok'); return; }
          reviewMatches(res.items);
        } catch (e) { noProviderHint(e); } finally { busy(btn, false); }
      },
      link: async (el) => {
        const id = await openRefPicker(kind, null, el.dataset.name);
        if (!id) return;
        const r = await api(`/api/ref/${kind}/link`, { body: { name: el.dataset.name, id } });
        okToast(`${fa(r.linked)} محصول وصل شد و «${el.dataset.name}» به نام‌های دیگر افزوده شد.`); page.load();
      },
      addsel: async () => {
        const box = document.getElementById('rf-un');
        const items = [...box.querySelectorAll('tr[data-un]')].filter((tr) => tr.querySelector('[data-sel]').checked)
          .map((tr) => ({ name: box._un[Number(tr.dataset.un)].name, slug: tr.querySelector('[data-slug]').value.trim() }));
        if (!items.length) { toast('موردی انتخاب نشده است.', 'err'); return; }
        try {
          const r = await api(`/api/ref/${kind}/add-unmatched`, { body: { items } });
          okToast(`${fa(r.created.length)} ${label} افزوده و ${fa(r.created.reduce((a, x) => a + x.linked, 0))} محصول وصل شد.`); page.load();
        } catch (e) { errToast(e); }
      },
    },
    change: {
      sel: (el) => { const id = Number(el.dataset.id); if (el.checked) R.sel.add(id); else R.sel.delete(id); page.draw(); },
      selall: (el) => { page.filtered().forEach((x) => (el.checked ? R.sel.add(x.id) : R.sel.delete(x.id))); page.draw(); },
      cat: (el) => { R.cat = el.value; page.load(); },
      inherit: (el) => { R.inherit = el.checked; if (R.cat) page.load(); },
    },
    input: { q: debounce((el) => { R.q = el.value.trim(); page.draw(); }, 200) },
    async refreshPage() {
      const view = document.getElementById('view');
      view.innerHTML = await this.render();
      await this.mount();
    },
  };

  // ---------------------------------------------------------------- پیشنهاد فهرست/درخت با AI
  async function aiGenerate() {
    const cats = kind === 'category' ? await api('/api/ref/category') : [];
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} ${kind === 'brand' ? 'پیشنهاد فهرست برند با هوش مصنوعی' : 'پیشنهاد درخت دسته‌بندی با هوش مصنوعی'}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="card-b"><div class="field"><label>چه ${kind === 'brand' ? 'برندهایی' : 'دسته‌هایی'} لازم است؟</label><textarea class="inp" id="ag-p" rows="3" data-noai placeholder="${kind === 'brand' ? 'مثلاً «برندهای معتبر روغن موتور و فیلتر در بازار ایران»' : 'مثلاً «دسته‌بندی کامل لوازم برقی و باتری خودرو»'}"></textarea></div>
        <div class="form-grid mt12"><div class="field"><label>حداکثر تعداد</label><input class="inp" type="number" id="ag-n" value="15" min="1" max="80"></div>
        ${kind === 'category' ? `<div class="field"><label>زیر دسته‌ی</label><select class="inp" id="ag-parent"><option value="">— ریشه —</option>${cats.map((c) => `<option value="${c.id}">${esc(c.path)}</option>`).join('')}</select></div>` : ''}</div>
        <div class="hint mt8">${kind === 'brand' ? 'دسته‌های هر برند فقط از دسته‌های موجود انتخاب می‌شوند.' : 'دسته‌های موجود تکرار نمی‌شوند.'} پیشنهادها پیش از ذخیره نمایش داده می‌شوند.</div>
        <div id="ag-res"></div></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>بستن</button><button class="btn soft" id="ag-go">${icon('sparkles', 16)} پیشنهاد بگیر</button><button class="btn primary" id="ag-ok" disabled>${icon('save', 16)} ذخیره‌ی انتخاب‌شده‌ها</button></div>`, { wide: true });
    const b = l.box;
    let items = [];
    b.querySelector('#ag-go').addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      busy(btn, true, 'در حال پیشنهاد…');
      try {
        const r = await api(`/api/ref/${kind}/ai-generate`, { body: { prompt: b.querySelector('#ag-p').value, count: Number(b.querySelector('#ag-n').value), parent_id: b.querySelector('#ag-parent')?.value || null } });
        items = r.items;
        b.querySelector('#ag-res').innerHTML = items.length ? `<div class="tbl-wrap mt16" style="max-height:44vh"><table class="tbl"><thead><tr><th style="width:34px"></th><th>نام</th><th>نام انگلیسی</th><th>اسلاگ</th><th>${kind === 'brand' ? 'دسته‌ها' : 'والد'}</th><th></th></tr></thead><tbody>
          ${items.map((x, i) => `<tr><td><input type="checkbox" data-i="${i}" ${x.exists ? '' : 'checked'}></td><td><b class="small">${esc(x.name)}</b></td><td class="small ltr">${esc(x.name_en)}</td><td class="small ltr mono">${esc(x.slug)}</td>
            <td class="xs">${kind === 'brand' ? esc((x.categories_label || []).join('، ')) : `<span class="ltr mono">${esc(x.parent || '—')}</span>`}</td><td>${x.exists ? '<span class="tag">موجود است (به‌روز می‌شود)</span>' : '<span class="tag p">تازه</span>'}</td></tr>`).join('')}</tbody></table></div>`
          : '<div class="muted small mt12">پیشنهادی برنگشت.</div>';
        b.querySelector('#ag-ok').disabled = !items.length;
      } catch (e) { noProviderHint(e); } finally { busy(btn, false); }
    });
    b.querySelector('#ag-ok').addEventListener('click', async () => {
      const pick = [...b.querySelectorAll('#ag-res [data-i]:checked')].map((c) => items[Number(c.dataset.i)]);
      if (!pick.length) { toast('موردی انتخاب نشده است.', 'err'); return; }
      const body = pick.map((x) => {
        const o = { name: x.name, name_en: x.name_en, slug: x.slug, aliases: x.aliases };
        if (x.exists) o.id = x.existing_id;
        if (kind === 'brand') { o.category_ids = x.category_ids; o.country = x.country; } else if (x.parent) o.parent = x.parent;
        return o;
      });
      try {
        const r = await api(`/api/ref/${kind}/apply`, { body: { items: body } });
        okToast(`${fa(r.added)} مورد افزوده و ${fa(r.updated)} مورد به‌روز شد${r.errors.length ? `؛ ${fa(r.errors.length)} خطا` : ''}.`);
        if (r.errors.length) toast(r.errors.slice(0, 3).map((e) => `${e.name}: ${e.error}`).join('؛ '), 'err');
        l.close(); page.load();
      } catch (e) { errToast(e); }
    });
  }

  // ---------------------------------------------------------------- تطبیق نام‌های خام با AI
  function reviewMatches(items) {
    const ACT = { link: 'وصل به موجود', new: `${label} تازه`, skip: 'نادیده' };
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} تطبیق نام‌های خام با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="tbl-wrap" style="max-height:62vh"><table class="tbl"><thead><tr><th style="width:34px"></th><th>نام خام</th><th>پیشنهاد</th><th>مقصد</th><th>دلیل</th></tr></thead><tbody>
      ${items.map((x, i) => `<tr><td><input type="checkbox" data-i="${i}" ${x.action === 'skip' ? '' : 'checked'} ${x.action === 'skip' ? 'disabled' : ''}></td><td><b class="small">${esc(x.raw)}</b></td>
        <td><span class="tag ${x.action === 'link' ? 'p' : x.action === 'new' ? 'ok' : ''}">${ACT[x.action]}</span></td>
        <td class="small">${x.action === 'link' ? esc(x.target) : x.action === 'new' ? `${esc(x.name)} <span class="xs muted ltr">${esc(x.name_en)} · ${esc(x.slug)}</span>` : '—'}</td><td class="xs muted">${esc(x.reason || '')}</td></tr>`).join('')}</tbody></table></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="mt-ok">${icon('check', 16)} اعمال انتخاب‌شده‌ها</button></div>`, { wide: true });
    l.box.querySelector('#mt-ok').addEventListener('click', async (ev) => {
      const pick = [...l.box.querySelectorAll('[data-i]:checked')].map((c) => items[Number(c.dataset.i)]);
      busy(ev.currentTarget, true, 'در حال اعمال…');
      let linked = 0;
      try {
        for (const x of pick.filter((p) => p.action === 'link')) linked += (await api(`/api/ref/${kind}/link`, { body: { name: x.raw, id: x.id } })).linked;
        const news = pick.filter((p) => p.action === 'new').map((x) => ({ name: x.raw, name_fa: x.name, name_en: x.name_en, slug: x.slug }));
        let created = 0;
        if (news.length) { const r = await api(`/api/ref/${kind}/add-unmatched`, { body: { items: news } }); created = r.created.length; linked += r.created.reduce((a, y) => a + y.linked, 0); }
        okToast(`${fa(created)} ${label} تازه، ${fa(linked)} محصول وصل شد.`);
        l.close(); page.load();
      } catch (e) { errToast(e); busy(ev.currentTarget, false); }
    });
  }

  // ---------------------------------------------------------------- افزودن و ویرایش
  async function edit(x, parentId = null) {
    const cats = kind === 'category' ? await api('/api/ref/category') : [];
    let catIds = [...(x?.category_ids || [])];
    const allCats = kind === 'brand' ? await api('/api/ref/category') : [];
    const catLabel = () => catIds.length ? allCats.filter((c) => catIds.includes(c.id)).map((c) => `<span class="tag" title="${attr(c.path)}">${esc(c.name)}</span>`).join('') : '<span class="xs muted">بدون دسته — در همه‌ی دسته‌ها نمایش داده نمی‌شود</span>';
    const pid = x ? x.parent_id : parentId;
    const l = openLayer('modal', `<div class="card-h"><h3>${x ? 'ویرایش' : 'افزودن'} ${label}</h3><span class="sp"></span>${aiOn() ? `<button class="btn sm soft" id="e-ai" title="فیلدهای خالی با هوش مصنوعی پر شوند">${icon('sparkles', 14)} تکمیل با AI</button>` : ''}</div><div class="card-b">
      <div class="form-grid"><div class="field"><label>نام فارسی</label><input class="inp" id="e-n" value="${attr(x?.name || '')}" data-noai></div>
        <div class="field"><label>نام انگلیسی</label><input class="inp ltr" id="e-e" value="${attr(x?.name_en || '')}" data-ai="1" data-ai-format="english" data-ai-label="نام انگلیسی ${label}"></div>
        <div class="field"><label>اسلاگ (انگلیسی)</label><input class="inp ltr mono" id="e-s" value="${attr(x?.slug || '')}" placeholder="خودکار از نام انگلیسی" data-ai="1" data-ai-format="slug" data-ai-label="اسلاگ ${label}"></div>
        ${kind === 'category' ? `<div class="field"><label>دسته‌ی والد</label><select class="inp" id="e-p"><option value="">— ریشه —</option>${cats.filter((c) => c.id !== x?.id).map((c) => `<option value="${c.id}" ${pid === c.id ? 'selected' : ''}>${esc(c.path)}</option>`).join('')}</select></div>
          <div class="field"><label>ترتیب نمایش</label><input class="inp" type="number" id="e-o" value="${attr(x?.sort || 0)}"></div>`
    : `<div class="field"><label>کشور (اختیاری)</label><input class="inp" id="e-c" value="${attr(x?.country || '')}" data-noai></div>`}</div>
      ${kind === 'brand' ? `<div class="field mt12"><label>دسته‌بندی‌هایی که این برند در آن‌ها نمایش داده می‌شود</label><div class="flex wrap" style="gap:6px"><div class="cat-chips" id="e-cats">${catLabel()}</div><button class="btn xs soft" id="e-catbtn">${icon('tree', 12)} انتخاب دسته‌ها</button></div>
        <div class="hint">انتخاب یک دسته، برند را در زیرشاخه‌ها و دسته‌های بالاتر آن هم نمایش می‌دهد.</div></div>` : ''}
      <div class="field mt12"><label>توضیح کوتاه</label><textarea class="inp" id="e-d" rows="2" data-ai-label="توضیح ${label}">${esc(x?.description || '')}</textarea></div>
      <div class="field mt12"><label>نام‌های دیگر (هر خط یکی؛ برای تطبیق خودکار با داده‌ی خام)</label><textarea class="inp" id="e-a" rows="3" data-noai>${esc((x?.aliases || []).join('\n'))}</textarea></div>
      <label class="check mt12"><input type="checkbox" id="e-act" ${x?.active === 0 ? '' : 'checked'}> فعال</label></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="e-ok">${icon('save', 16)} ذخیره</button></div>`);
    const b = l.box;
    const cb = b.querySelector('#e-catbtn');
    if (cb) cb.addEventListener('click', async () => { const ids = await pickCategories(catIds); if (ids !== undefined) { catIds = ids; b.querySelector('#e-cats').innerHTML = catLabel(); } });
    const form = () => {
      const body = { name: b.querySelector('#e-n').value, name_en: b.querySelector('#e-e').value, slug: b.querySelector('#e-s').value, aliases: b.querySelector('#e-a').value,
        description: b.querySelector('#e-d').value, active: b.querySelector('#e-act').checked };
      if (kind === 'category') { body.parent_id = b.querySelector('#e-p').value || null; body.sort = Number(b.querySelector('#e-o').value) || 0; } else { body.country = b.querySelector('#e-c').value; body.category_ids = catIds; }
      return body;
    };
    const ai = b.querySelector('#e-ai');
    if (ai) ai.addEventListener('click', async () => {
      const f = form();
      if (!f.name.trim()) { toast('اول نام فارسی را بنویسید.', 'err'); return; }
      busy(ai, true, 'در حال تکمیل…');
      try {
        const item = { ...f, id: x?.id, aliases: f.aliases.split('\n').map((s) => s.trim()).filter(Boolean), parent_id: f.parent_id ? Number(f.parent_id) : null };
        const res = await api(`/api/ref/${kind}/ai-complete`, { body: { items: [item], only_empty: true } });
        const p = res.items[0]?.proposal || {};
        const filled = [];
        if (p.name_en) { b.querySelector('#e-e').value = p.name_en; filled.push('نام انگلیسی'); }
        if (p.slug) { b.querySelector('#e-s').value = p.slug; filled.push('اسلاگ'); }
        if (p.description) { b.querySelector('#e-d').value = p.description; filled.push('توضیح'); }
        if (p.aliases) { b.querySelector('#e-a').value = p.aliases.join('\n'); filled.push('نام‌های دیگر'); }
        if (p.country && b.querySelector('#e-c')) { b.querySelector('#e-c').value = p.country; filled.push('کشور'); }
        if (p.category_ids && kind === 'brand') { catIds = p.category_ids; b.querySelector('#e-cats').innerHTML = catLabel(); filled.push('دسته‌ها'); }
        if (p.parent_id && kind === 'category') { b.querySelector('#e-p').value = String(p.parent_id); filled.push('والد'); }
        okToast(filled.length ? `پر شد: ${filled.join('، ')} — پیش از ذخیره بررسی کنید.` : 'فیلد خالی‌ای برای تکمیل نبود.');
      } catch (e) { noProviderHint(e); } finally { busy(ai, false); }
    });
    b.querySelector('#e-ok').addEventListener('click', async () => {
      try {
        await api(x ? `/api/ref/${kind}/${x.id}` : `/api/ref/${kind}`, { method: x ? 'PUT' : 'POST', body: form() });
        okToast('ذخیره شد.'); l.close(); page.load();
      } catch (e) { errToast(e); }
    });
  }
  return page;
}

export const Brands = makePage('brand');
export const Categories = makePage('category');
