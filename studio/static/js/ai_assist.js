// دستیار هوش مصنوعی شناور: کنار هر فیلد متنی در همه‌ی صفحه‌ها
import { api, icon, esc, attr, fa, toast, errToast } from './core.js';

const SKIP_INPUT = new Set(['search', 'filter', 'detect', 'preview']);
const SKIP_ID = new Set(['cat-url', 't-cat', 't-prod', 'ex-root', 'bg-in', 'bg-out', 's-out', 'pf-base', 'pf-key', 'pf-proxy', 'pf-tm', 'pf-im',
  'q-at', 'imp', 'se-json', 'pe-model', 'pe-img-model', 'rf-test', 'rt-in']);
const QUICK = [
  ['تولید', 'یک مقدار کامل و حرفه‌ای برای این فیلد بنویس.'],
  ['بهبود و بازنویسی', 'متن فعلی را حرفه‌ای‌تر، روان‌تر و یکتا بازنویسی کن؛ معنا را حفظ کن.'],
  ['سئو', 'متن را برای سئو بهینه کن: کلیدواژه‌ی اصلی در ابتدا، جمله‌های روشن و طبیعی، بدون تکرار افراطی.'],
  ['کوتاه‌تر', 'کوتاه‌تر و موجزتر بنویس.'],
  ['بلندتر', 'کامل‌تر و با جزئیات بیشتر بنویس.'],
  ['اصلاح نگارش', 'فقط غلط‌های نگارشی و فاصله‌گذاری (نیم‌فاصله) را اصلاح کن.'],
  ['انگلیسی', 'به انگلیسی ترجمه کن.'],
];

let btn = null;
let pop = null;
let target = null;
let hideT = null;

function eligible(el) {
  if (!el || !el.matches) return false;
  if (!el.matches('textarea.inp, input.inp')) return false;
  if (el.matches('[type=number],[type=checkbox],[type=radio],[type=datetime-local],[type=password],[type=date],[data-noai],[readonly],[disabled]')) return false;
  if (el.dataset.ai) return true;
  if (SKIP_INPUT.has(el.dataset.input) || SKIP_ID.has(el.id)) return false;
  if (el.closest('[data-noai]')) return false;
  if (el.matches('.mono') || el.dataset.kind === 'json' || el.dataset.json !== undefined || el.dataset.lines !== undefined) return false;
  if (el.matches('.ltr') && !el.closest('[data-col]')) return false;
  return true;
}

function labelOf(el) {
  const f = el.closest('.field, [data-col], .fieldbox');
  const l = f?.querySelector('label, .lbl, b');
  return (el.dataset.aiLabel || l?.textContent || el.placeholder || 'متن').replace(/\s+/g, ' ').trim().slice(0, 80);
}

function contextOf(el) {
  const ctx = {};
  ctx.page = document.getElementById('page-title')?.textContent || '';
  const dr = el.closest('.drawer');
  if (dr) ctx.item = dr.querySelector('.drawer-h h3')?.textContent || '';
  const card = el.closest('.card, .modal, .fieldbox');
  const h = card?.querySelector('.card-h h2, .card-h h3, .fh b');
  if (h) ctx.section = h.textContent;
  const near = [];
  (el.closest('.card-b, .drawer-b, .modal') || document).querySelectorAll('input.inp, textarea.inp, select.inp').forEach((x) => {
    if (x === el || near.length > 12) return;
    const v = x.tagName === 'SELECT' ? x.options[x.selectedIndex]?.text : x.value;
    if (v && String(v).length < 300) near.push(`${labelOf(x)}: ${v}`);
  });
  if (near.length) ctx.nearby = near;
  return ctx;
}

function formatOf(el, label) {
  if (el.dataset.aiFormat) return el.dataset.aiFormat;
  if (/اسلاگ|slug/i.test(label)) return 'slug';
  if (/کلیدواژه|keyword/i.test(label)) return 'keywords';
  if (el.dataset.kind === 'list') return 'keywords';
  if (el.matches('.ltr')) return 'english';
  return 'text';
}

function place(b, el) {
  const r = el.getBoundingClientRect();
  b.style.top = `${Math.max(4, r.top + 6)}px`;
  b.style.left = `${r.left + 6}px`;
}

function ensureBtn() {
  if (btn) return btn;
  btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ai-fab';
  btn.title = 'دستیار هوش مصنوعی';
  btn.innerHTML = icon('sparkles', 15);
  btn.addEventListener('mousedown', (e) => e.preventDefault());
  btn.addEventListener('click', () => openPop(target));
  document.body.appendChild(btn);
  return btn;
}

function hideBtn() { if (btn) btn.style.display = 'none'; }

document.addEventListener('focusin', (e) => {
  const el = e.target;
  if (!eligible(el)) return;
  clearTimeout(hideT);
  target = el;
  const b = ensureBtn();
  b.style.display = 'grid';
  place(b, el);
});
document.addEventListener('focusout', () => { hideT = setTimeout(() => { if (!pop) hideBtn(); }, 180); });
window.addEventListener('scroll', () => { if (btn && target && btn.style.display !== 'none') place(btn, target); if (pop && target) placePop(); }, true);

function placePop() {
  const r = target.getBoundingClientRect();
  const w = Math.min(420, window.innerWidth - 24);
  let left = r.left;
  if (left + w > window.innerWidth - 12) left = window.innerWidth - w - 12;
  pop.style.width = `${w}px`;
  pop.style.left = `${Math.max(12, left)}px`;
  const below = r.bottom + 8;
  const h = pop.offsetHeight || 320;
  pop.style.top = `${below + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 8) : below}px`;
}

function closePop() { if (pop) { pop.remove(); pop = null; } hideBtn(); }

function openPop(el) {
  if (!el) return;
  closePop();
  const label = labelOf(el);
  const fmt = formatOf(el, label);
  pop = document.createElement('div');
  pop.className = 'ai-pop';
  pop.innerHTML = `
    <div class="flex" style="margin-bottom:8px"><span style="color:var(--primary)">${icon('sparkles', 16)}</span><b class="grow ellipsis">${esc(label)}</b>
      <button class="btn xs ghost" data-x>${icon('x', 14)}</button></div>
    <div class="flex wrap" style="gap:6px">${QUICK.map(([t, ins], i) => `<button class="btn xs ${i === 0 ? 'soft' : ''}" data-q="${attr(ins)}">${t}</button>`).join('')}</div>
    <textarea class="inp mt8" data-noai rows="2" placeholder="یا دستور دلخواه خودتان را بنویسید… (مثلاً: لحن صمیمی‌تر و دو جمله)"></textarea>
    <div class="flex mt8"><button class="btn sm primary" data-go>${icon('sparkles', 14)} تولید</button><span class="xs muted grow" data-st></span></div>
    <div data-res class="hidden">
      <textarea class="inp mt8" data-noai rows="5" data-out></textarea>
      <div class="flex mt8"><button class="btn sm primary" data-apply>${icon('check', 14)} جایگزینی</button><button class="btn sm" data-append>${icon('plus', 14)} افزودن</button>
        <button class="btn sm ghost" data-again>${icon('refresh', 14)} دوباره</button></div>
    </div>`;
  document.body.appendChild(pop);
  placePop();
  const ins = pop.querySelector('textarea');
  const st = pop.querySelector('[data-st]');
  let lastInstr = '';
  const run = async (instruction) => {
    lastInstr = instruction;
    st.innerHTML = `${icon('loader', 13, 'spin')} در حال تولید…`;
    try {
      const r = await api('/api/ai/assist', { body: { task: 'text', label, current: el.value, instruction, context: contextOf(el), format: fmt, page: document.getElementById('page-title')?.textContent } });
      if (!r.ok) throw new Error(r.error);
      const v = Array.isArray(r.value) ? r.value.join('\n') : (typeof r.value === 'object' ? JSON.stringify(r.value) : String(r.value ?? ''));
      pop.querySelector('[data-res]').classList.remove('hidden');
      pop.querySelector('[data-out]').value = v;
      st.textContent = `${r.provider} · ${fa(r.tokens || 0)} توکن`;
      placePop();
    } catch (e) { st.innerHTML = `<span style="color:var(--err)">${esc(e.message)}</span>`; }
  };
  pop.addEventListener('mousedown', (e) => { if (!e.target.matches('textarea')) e.preventDefault(); });
  pop.querySelector('[data-x]').addEventListener('click', closePop);
  pop.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', () => run(b.dataset.q + (ins.value ? ' ' + ins.value : ''))));
  pop.querySelector('[data-go]').addEventListener('click', () => run(ins.value || QUICK[0][1]));
  pop.querySelector('[data-again]').addEventListener('click', () => run(lastInstr || QUICK[0][1]));
  const apply = (append) => {
    const v = pop.querySelector('[data-out]').value;
    el.value = append && el.value ? `${el.value}${el.tagName === 'TEXTAREA' ? '\n' : ' '}${v}` : v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.closest('[data-col]')?.setAttribute('data-touched', '1');
    closePop();
    el.focus();
  };
  pop.querySelector('[data-apply]').addEventListener('click', () => apply(false));
  pop.querySelector('[data-append]').addEventListener('click', () => apply(true));
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pop) { closePop(); e.stopPropagation(); } }, true);
document.addEventListener('mousedown', (e) => { if (pop && !pop.contains(e.target) && e.target !== btn && !btn?.contains(e.target)) closePop(); });
window.addEventListener('hashchange', closePop);

// --------------------------------------------------------------- کمک‌تابع‌ها برای سایر صفحه‌ها
export async function assist(task, body) {
  const r = await api('/api/ai/assist', { body: { task, ...body } });
  if (!r.ok) throw new Error(r.error);
  return r;
}

export function aiBtn(act, label = 'هوش مصنوعی', extra = '', cls = 'soft') {
  return `<button class="btn sm ${cls}" data-act="${act}" ${extra}>${icon('sparkles', 14)} ${label}</button>`;
}

export function busy(el, on, text = 'در حال تولید…') {
  if (!el) return;
  if (on) { el.dataset.html = el.innerHTML; el.disabled = true; el.innerHTML = `${icon('loader', 14, 'spin')} ${text}`; }
  else { el.disabled = false; if (el.dataset.html) el.innerHTML = el.dataset.html; }
}

export function noProviderHint(e) {
  if (/اتصال هوش مصنوعی ندارید/.test(e.message)) toast('ابتدا در «هوش مصنوعی ← اتصال‌ها» یک اتصال بسازید.', 'err');
  else errToast(e);
}
