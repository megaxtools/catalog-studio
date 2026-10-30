// مقدار پیش‌فرض ستون‌های اسکیما: ویرایشگر متناسب با نوع ورودی (یک‌خطی، چندخطی، بولت، گروه بولت‌ها، کلید/مقدار، JSON…)
import { icon, esc, attr, fa, trunc, openLayer, toast } from './core.js';
import { colInput, readCol } from './pages_main.js';

export const DEF_MODES = [
  ['fill', 'اگر خالی بود', 'فقط وقتی منبع، ورود دستی و هوش مصنوعی مقداری نداشتند.'],
  ['always', 'همیشه همین', 'استخراج و هوش مصنوعی نادیده گرفته می‌شوند؛ فقط ویرایش دستی هر محصول جایش را می‌گیرد.'],
  ['prepend', 'افزودن به ابتدا', 'پیش از مقدار استخراجی یا هوش مصنوعی می‌آید (موارد تکراری حذف می‌شوند).'],
  ['append', 'افزودن به انتها', 'پس از مقدار استخراجی یا هوش مصنوعی می‌آید (موارد تکراری حذف می‌شوند).'],
];
const MERGEABLE = ['text', 'longtext', 'bullets', 'bullet_groups', 'images', 'specs'];
const modeLabel = (m) => (DEF_MODES.find((x) => x[0] === (m || 'fill')) || DEF_MODES[0])[1];

const INPUT_LBL = { text: 'متن کوتاه', longtext: 'متن بلند', bullets: 'بولت', bullet_groups: 'گروه بولت‌ها', group: 'گروه کلید/مقدار', specs: 'مشخصات', image: 'تصویر', images: 'چند تصویر', json: 'JSON', bool: 'بله/خیر', number: 'عدد' };
const FORMAT_HINT = {
  text: 'متن یک‌خطی.',
  longtext: 'متن چندخطی یا چند پاراگراف؛ خط‌ها و پاراگراف‌ها همان‌طور که می‌نویسید در خروجی می‌آیند.',
  bullets: 'هر خط یک بولت.',
  bullet_groups: 'برای هر بخش جدا بنویسید؛ هر خط یک بولت.',
  group: 'هر کلید جدا؛ کلیدهای خالی پیش‌فرض ندارند.',
  specs: 'آرایه‌ی JSON؛ هر ردیف {"group": "…", "name": "…", "value": "…"}.',
  json: 'مقدار JSON (شیء، آرایه یا متن).',
  images: 'هر خط لینک یک تصویر.',
  image: 'لینک یا مسیر تصویر.',
  number: 'یک عدد.',
  bool: 'بله یا خیر.',
};

export function isEmptyVal(v) {
  if (v === null || v === undefined) return true;
  if (typeof v === 'string') return !v.trim();
  if (Array.isArray(v)) return v.every(isEmptyVal);
  if (typeof v === 'object') return Object.values(v).every(isEmptyVal);
  return false;
}

// نمایش کوتاه مقدار پیش‌فرض در ردیف ستون
export function defPreview(col, v) {
  if (isEmptyVal(v)) return '';
  const inp = col.input || 'text';
  if (inp === 'bullet_groups' && typeof v === 'object' && !Array.isArray(v)) {
    const lbl = Object.fromEntries((col.groups || []).map((g) => [g.key, g.label]));
    return Object.entries(v).filter(([, x]) => !isEmptyVal(x)).map(([k, x]) => `${lbl[k] || k}: ${fa((Array.isArray(x) ? x : String(x).split('\n').filter(Boolean)).length)} خط`).join(' · ');
  }
  if (inp === 'group' && typeof v === 'object') return Object.entries(v).filter(([, x]) => !isEmptyVal(x)).map(([k, x]) => `${k}=${x}`).join('، ');
  if (Array.isArray(v)) return `${fa(v.length)} مورد: ${trunc(typeof v[0] === 'object' ? JSON.stringify(v[0]) : v[0], 40)}`;
  if (typeof v === 'object') return trunc(JSON.stringify(v), 60);
  const s = String(v);
  const lines = s.split('\n').filter((x) => x.trim()).length;
  return `${trunc(s.split('\n')[0], 55)}${lines > 1 ? ` (${fa(lines)} خط)` : ''}`;
}

// چیپ پیش‌فرض در ویرایشگر اسکیما
export function defaultChip(c, i) {
  if (c.kind === 'constant') return '';
  const pv = defPreview(c, c.default);
  return `<span class="xs muted">${icon('edit', 12)} پیش‌فرض:</span>
    <button class="btn xs ${pv ? 'soft' : 'ghost'}" data-act="coldef" data-i="${i}" title="تعیین مقدار پیش‌فرض این ستون (یک‌خطی، چندخطی، بولت…)" style="max-width:420px">
      ${pv ? `<span class="ellipsis">${esc(pv)}</span><span class="tag" style="font-size:10.5px;padding:0 6px">${esc(modeLabel(c.default_mode))}</span>` : 'ندارد — تعیین'}</button>`;
}

// ویرایشگر؛ خروجی: {value, mode} یا null (انصراف)، و {value: null} برای حذف
export function openDefaultEditor(col, { constant = false } = {}) {
  const inp = col.input || 'text';
  const editCol = { ...col, kind: col.kind === 'constant' ? 'constant' : 'manual' };
  const cur = constant ? col.value : col.default;
  const curMode = col.default_mode || 'fill';
  const canMerge = MERGEABLE.includes(inp);
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('edit', 18)} ${constant ? 'مقدار ثابت' : 'مقدار پیش‌فرض'} «${esc(col.label || col.key)}»</h3><span class="sub ltr">${esc(col.key)}</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="card-b" style="max-height:72vh;overflow:auto">
        ${constant ? '<div class="hint mb12">این ستون برای همه‌ی محصولات همین مقدار را می‌گیرد (مگر برای محصولی دستی ویرایش شود).</div>' : `
        <div class="lbl mb8">چه زمانی اعمال شود؟</div>
        <div class="def-modes">${DEF_MODES.map(([k, t, d]) => {
          const off = (k === 'prepend' || k === 'append') && !canMerge;
          return `<label class="def-mode ${off ? 'off' : ''}"><input type="radio" name="dm" value="${k}" ${curMode === k ? 'checked' : ''} ${off ? 'disabled' : ''}><b>${t}</b><span class="xs muted">${d}</span></label>`;
        }).join('')}</div>`}
        <div class="field mt16" data-col="${attr(col.key)}"><label class="lbl">${constant ? 'مقدار' : 'مقدار پیش‌فرض'}</label>${inp === 'bool' ? `<select class="inp" data-text style="max-width:220px"><option value="">${constant ? '—' : 'بدون پیش‌فرض'}</option><option value="true" ${String(cur) === 'true' ? 'selected' : ''}>بله (true)</option><option value="false" ${String(cur) === 'false' ? 'selected' : ''}>خیر (false)</option></select>` : colInput(editCol, cur ?? null, {})}</div>
        <div class="hint mt8">${icon('info', 12)} نوع ورودی این ستون: <b>${esc(INPUT_LBL[inp] || inp)}</b> — ${FORMAT_HINT[inp] || ''} برای متن چندخطی، نوع ورودی ستون را «متن بلند» و برای فهرست، «بولت» یا «گروه بولت‌ها» بگذارید.</div>
      </div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px">
        ${!isEmptyVal(cur) ? `<button class="btn ghost danger" data-clear>${icon('trash', 16)} حذف ${constant ? 'مقدار' : 'پیش‌فرض'}</button>` : ''}
        <span class="grow"></span><button class="btn" data-close>انصراف</button><button class="btn primary" data-ok>${icon('check', 16)} ثبت</button></div>`, { wide: ['bullet_groups', 'group', 'specs', 'longtext', 'json'].includes(inp), onClose: () => { if (!done) resolve(null); } });
    const b = l.box;
    const fin = (r) => { done = true; l.close(); resolve(r); };
    b.querySelector('[data-clear]')?.addEventListener('click', () => fin({ value: null, mode: 'fill' }));
    b.querySelector('[data-ok]').addEventListener('click', () => {
      let v;
      try { v = readCol(b.querySelector('[data-col]'), editCol); } catch (e) { toast(e.message, 'err'); return; }
      if (inp === 'group' && v && typeof v === 'object') v = Object.fromEntries(Object.entries(v).filter(([, x]) => !isEmptyVal(x)));
      const mode = constant ? undefined : (b.querySelector('[name="dm"]:checked')?.value || 'fill');
      fin({ value: isEmptyVal(v) ? null : v, mode });
    });
    setTimeout(() => b.querySelector('[data-col] textarea, [data-col] input')?.focus(), 60);
  });
}
