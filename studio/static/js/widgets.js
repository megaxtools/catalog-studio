// اجزای مشترک نسخه‌ی ۲: نسخه‌ها (ریویژن) و مقایسه، انتخابگر داده‌ی مرجع، نمایش سازگاری
import { api, icon, esc, attr, fa, jdate, okToast, errToast, openLayer, confirmDlg, trunc, toast } from './core.js';

export const ACTOR = { ui: 'کاربر', mcp: 'ایجنت', ai: 'هوش مصنوعی', api: 'API', system: 'سیستم' };
export const ACTOR_IC = { ui: 'users', mcp: 'cpu', ai: 'sparkles', api: 'code', system: 'settings' };

export function pretty(v, max = 600) {
  if (v === null || v === undefined || v === '') return '<span class="muted">—</span>';
  if (typeof v === 'object') return `<pre class="diff-pre">${esc(trunc(JSON.stringify(v, null, 2), max))}</pre>`;
  return `<span class="diff-txt">${esc(trunc(String(v), max)).replace(/\n/g, '<br>')}</span>`;
}

const FIELD_FA = { title: 'عنوان', slug: 'اسلاگ', brand_id: 'برند', category_id: 'دسته‌بندی', compat: 'سازگاری با خودرو', status: 'وضعیت', note: 'یادداشت',
  images: 'تصاویر', name: 'نام', name_en: 'نام انگلیسی', aliases: 'نام‌های دیگر', columns: 'ستون‌ها', config: 'پیکربندی', selection: 'انتخاب محصولات' };
export function fieldName(f) {
  const parts = String(f).split('.');
  if (parts[0] === 'values') return `<span class="ltr">${esc(parts.slice(1).join('.'))}</span>`;
  return esc(FIELD_FA[parts[0]] || parts[0]) + (parts.length > 1 ? ` <span class="xs muted ltr">${esc(parts.slice(1).join('.'))}</span>` : '');
}

export function diffTable(changes) {
  if (!changes?.length) return '<div class="muted small" style="padding:12px">تفاوتی نیست.</div>';
  return `<table class="tbl diff"><thead><tr><th style="width:22%">فیلد</th><th>قبل</th><th>بعد</th></tr></thead><tbody>
    ${changes.map((c) => `<tr><td class="small">${fieldName(c.field)}</td><td class="d-old">${pretty(c.old)}</td><td class="d-new">${pretty(c.new)}</td></tr>`).join('')}</tbody></table>`;
}

// خط زمانی نسخه‌های یک موجودیت + مقایسه و بازگردانی
export async function revisionsPanel(box, entity, id, onRestore) {
  const rows = await api(`/api/revisions?entity=${entity}&entity_id=${id}`);
  if (!rows.length) { box.innerHTML = '<div class="muted small">هنوز نسخه‌ای ثبت نشده است.</div>'; return; }
  const cur = rows[0].rev;
  box.innerHTML = `<div class="timeline">${rows.map((r) => `<div class="tl-item">
      <span class="tl-dot ${r.rev === cur ? 'on' : ''}">${fa(r.rev)}</span>
      <div class="grow"><div class="flex wrap" style="gap:6px"><b class="small">${esc(r.action_label)}</b>${r.rev === cur ? '<span class="tag p">نسخه‌ی فعلی</span>' : ''}
          <span class="xs muted">${icon(ACTOR_IC[r.actor] || 'users', 11)} ${esc(ACTOR[r.actor] || r.actor)}${r.user ? ' · ' + esc(r.user) : ''} · ${jdate(r.created_at)}</span></div>
        ${r.note ? `<div class="xs muted">${esc(r.note)}</div>` : ''}
        ${r.fields?.length ? `<div class="flex wrap mt4" style="gap:4px">${r.fields.slice(0, 10).map((f) => `<span class="tag" style="font-size:10.5px">${fieldName(f)}</span>`).join('')}${r.fields.length > 10 ? `<span class="xs muted">+${fa(r.fields.length - 10)}</span>` : ''}</div>` : ''}</div>
      <div class="flex" style="gap:2px">${r.rev > 1 ? `<button class="btn xs ghost" data-rv-diff="${r.rev}" title="تغییرات این نسخه نسبت به نسخه‌ی قبل">${icon('diff', 12)} تغییرات</button>` : ''}
        ${r.rev !== cur ? `<button class="btn xs ghost" data-rv-cmp="${r.rev}" title="مقایسه با نسخه‌ی فعلی">${icon('layers', 12)}</button><button class="btn xs soft" data-rv-restore="${r.rev}" title="بازگردانی به این نسخه">${icon('undo', 12)} بازگردانی</button>` : ''}</div>
    </div>`).join('')}</div>`;
  box.onclick = async (ev) => {
    const d = ev.target.closest('[data-rv-diff]');
    const c = ev.target.closest('[data-rv-cmp]');
    const rs = ev.target.closest('[data-rv-restore]');
    try {
      if (d || c) {
        const rev = Number((d || c).dataset[d ? 'rvDiff' : 'rvCmp']);
        const [a, b] = d ? [rev - 1, rev] : [rev, cur];
        const res = await api(`/api/revisions/compare?entity=${entity}&entity_id=${id}&a=${a}&b=${b}`);
        openLayer('modal', `<div class="card-h"><h3>${icon('diff', 18)} مقایسه‌ی نسخه‌ی ${fa(a)} با ${fa(b)}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
          <div class="tbl-wrap" style="max-height:70vh">${diffTable(res.changes)}</div>`, { wide: true });
      }
      if (rs) {
        const rev = Number(rs.dataset.rvRestore);
        if (!(await confirmDlg('بازگردانی نسخه', `محتوای نسخه‌ی ${fa(rev)} به‌عنوان یک نسخه‌ی تازه ذخیره شود؟ هیچ نسخه‌ای پاک نمی‌شود.`, 'بازگردانی'))) return;
        await api('/api/revisions/restore', { body: { entity, entity_id: id, rev } });
        okToast(`به نسخه‌ی ${fa(rev)} بازگردانده شد.`);
        if (onRestore) onRestore(); else revisionsPanel(box, entity, id, onRestore);
      }
    } catch (e) { errToast(e); }
  };
}

// انتخاب برند یا دسته از فهرست مرجع (با جست‌وجو و امکان افزودن)
export function openRefPicker(kind, current, hint = '') {
  const label = kind === 'brand' ? 'برند' : 'دسته‌بندی';
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `<div class="card-h"><h3>${icon(kind === 'brand' ? 'tag' : 'tree', 18)} انتخاب ${label}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="card-b"><input class="inp" id="rp-q" placeholder="جست‌وجوی نام، نام انگلیسی یا اسلاگ…" value="${attr(hint)}">
        <div id="rp-list" class="pick-list mt12"></div>
        <details class="mt12"><summary class="small" style="cursor:pointer">${icon('plus', 13)} ${label} در فهرست نیست؟ افزودن مورد تازه</summary>
          <div class="form-grid mt8"><input class="inp" id="rp-name" placeholder="نام فارسی" value="${attr(hint)}"><input class="inp ltr" id="rp-en" placeholder="English name"></div>
          <button class="btn sm soft mt8" id="rp-add">${icon('plus', 14)} افزودن و انتخاب</button></details></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn ghost danger" id="rp-clear">${icon('x', 14)} بدون ${label}</button><span class="grow"></span><button class="btn" data-close>انصراف</button></div>`,
    { onClose: () => { if (!done) resolve(undefined); } });
    const b = l.box;
    let items = [];
    const draw = () => {
      const q = b.querySelector('#rp-q').value.trim().toLowerCase();
      const f = items.filter((x) => !q || [x.name, x.name_en, x.slug, x.path, ...(x.aliases || [])].join(' ').toLowerCase().includes(q)).slice(0, 200);
      b.querySelector('#rp-list').innerHTML = f.map((x) => `<button class="pick ${x.id === current ? 'on' : ''}" data-id="${x.id}"><b>${esc(kind === 'category' ? x.path || x.name : x.name)}</b>
        <span class="xs muted ltr">${esc(x.slug)}</span>${x.active ? '' : '<span class="tag">غیرفعال</span>'}</button>`).join('') || '<div class="muted small">موردی پیدا نشد.</div>';
    };
    api(`/api/ref/${kind}`).then((r) => { items = r; draw(); });
    b.querySelector('#rp-q').addEventListener('input', draw);
    b.querySelector('#rp-list').addEventListener('click', (e) => { const x = e.target.closest('[data-id]'); if (x) { done = true; l.close(); resolve(Number(x.dataset.id)); } });
    b.querySelector('#rp-clear').addEventListener('click', () => { done = true; l.close(); resolve(null); });
    b.querySelector('#rp-add').addEventListener('click', async () => {
      try {
        const r = await api(`/api/ref/${kind}`, { body: { name: b.querySelector('#rp-name').value, name_en: b.querySelector('#rp-en').value } });
        okToast(`«${r.name}» به فهرست ${label}‌ها افزوده شد.`);
        done = true; l.close(); resolve(r.id);
      } catch (e) { errToast(e); }
    });
    setTimeout(() => b.querySelector('#rp-q').focus(), 60);
  });
}

export function compatChips(info, max = 6) {
  if (!info) return '';
  if (info.all) return `<span class="tag">${icon('car', 12)} همه‌ی خودروها</span>`;
  const it = info.items || [];
  if (!it.length) return `<span class="tag">${esc(info.label)}</span>`;
  return it.slice(0, max).map((x) => `<span class="tag p" title="${attr(x.slug_path)}">${icon('car', 11)} ${esc(x.display || x.label)}</span>`).join(' ') + (it.length > max ? ` <span class="xs muted">+${fa(it.length - max)}</span>` : '');
}

export async function compatPicker(value) {
  try {
    const m = await import('./mod_vehicles.js');
    return await m.openCompatPicker(value);
  } catch (e) {
    toast('ماژول «خودروها» در دسترس نیست؛ فقط «همه‌ی خودروها» ممکن است.', 'err');
    return undefined;
  }
}

export function qualityBadge(q, min = 70) {
  if (q === null || q === undefined) return '<span class="xs muted">—</span>';
  const cls = q >= min ? 'ok' : q >= 40 ? 'wait' : 'err';
  return `<span class="chip ${cls}" title="امتیاز کیفیت">${icon('star', 11)} ${fa(q)}</span>`;
}

export const STATUS = { draft: ['idle', 'پیش‌نویس'], review: ['wait', 'در انتظار بازبینی'], approved: ['ok', 'تأییدشده'], rejected: ['err', 'ردشده'], archived: ['idle', 'بایگانی'], merged: ['idle', 'ادغام‌شده'] };
export const statusChip = (s) => { const [c, t] = STATUS[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}</span>`; };

export function fileToDataUrl(file) {
  return new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(file); });
}
