import { icon } from './icons.js';
export { icon };

// ---------------------------------------------------------------- وضعیت سراسری
export const S = { boot: null, page: null, params: {}, timers: [], summary: null };

// ---------------------------------------------------------------- API
export async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), headers: { 'X-Studio-Client': 'ui' } };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
  let res;
  try { res = await fetch(path, init); }
  catch (e) { throw new Error('ارتباط با استودیو قطع است. پنجره‌ی اجرای برنامه باز است؟'); }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw new Error((data && data.error) || `خطای ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- متن
const FA = '۰۱۲۳۴۵۶۷۸۹';
export const fa = (v) => String(v ?? '').replace(/\d/g, (d) => FA[d]);
export const num = (n) => (n === null || n === undefined || n === '') ? '—' : fa(Number(n).toLocaleString('en-US'));
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const attr = esc;
export const trunc = (s, n = 80) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

function g2j(gy, gm, gd) {
  const gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days = 355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) + gd + gdm[gm - 1];
  let jy = -1595 + 33 * Math.floor(days / 12053); days %= 12053;
  jy += 4 * Math.floor(days / 1461); days %= 1461;
  if (days > 365) { jy += Math.floor((days - 1) / 365); days = (days - 1) % 365; }
  const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
  const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
  return [jy, jm, jd];
}
const MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
export function jdate(iso, withTime = true) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  const [y, m, dd] = g2j(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return fa(`${dd} ${MONTHS[m - 1]} ${y}${withTime ? '، ' + t : ''}`);
}
export function jtime(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}
export function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'لحظاتی پیش';
  if (s < 3600) return fa(Math.floor(s / 60)) + ' دقیقه پیش';
  if (s < 86400) return fa(Math.floor(s / 3600)) + ' ساعت پیش';
  return jdate(iso, false);
}

// ---------------------------------------------------------------- وضعیت‌ها
export const STATUS = {
  pending: ['idle', 'در صف'], starting: ['run', 'در حال آماده‌سازی'], running: ['run', 'در حال اجرا'],
  waiting: ['wait', 'نیازمند تصمیم'], paused: ['idle', 'متوقف (قابل ادامه)'], stopped: ['idle', 'پایان‌یافته (قابل ادامه)'],
  completed: ['ok', 'تکمیل شد'], error: ['err', 'خطا'], cancelled: ['idle', 'لغو شد'],
  queued: ['idle', 'در صف'], done: ['ok', 'کامل'], partial: ['wait', 'ناقص'], failed: ['err', 'ناموفق'], skipped: ['idle', 'رد شده'],
};
export function chip(status, extra = '') {
  const [c, t] = STATUS[status] || ['idle', status];
  return `<span class="chip ${c}"><span class="dot"></span>${t}${extra}</span>`;
}
export const isLive = (s) => ['running', 'starting', 'waiting'].includes(s);

export function progress(pct, live = false) {
  if (pct === null || pct === undefined) return `<div class="prog ${live ? 'indet live' : ''}"><i style="width:${live ? 35 : 0}%"></i></div>`;
  return `<div class="prog ${live ? 'live' : ''}"><i style="width:${Math.max(2, Math.min(100, pct))}%"></i></div>`;
}

// ---------------------------------------------------------------- اعلان
export function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === 'err' ? 'alert' : type === 'ok' ? 'checkCircle' : 'info', 18)}<div>${esc(msg)}</div>`;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity .3s'; el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, type === 'err' ? 6500 : 3800);
}
export const okToast = (m) => toast(m, 'ok');
export const errToast = (e) => toast(e?.message || String(e), 'err');

// ---------------------------------------------------------------- مودال و کشو
let layerStack = [];
export function openLayer(kind, html, opts = {}) {
  const ov = document.createElement('div');
  ov.className = 'overlay';
  const box = document.createElement('div');
  box.className = kind === 'drawer' ? 'drawer' : `modal ${opts.wide ? 'wide' : ''}`;
  box.innerHTML = html;
  document.body.append(ov, box);
  const close = () => { ov.remove(); box.remove(); layerStack = layerStack.filter((l) => l.box !== box); opts.onClose && opts.onClose(); };
  ov.addEventListener('click', () => { if (!opts.sticky) close(); });
  box.addEventListener('click', (ev) => {
    const t = ev.target.closest('[data-close]');
    if (t) close();
  });
  const layer = { box, close };
  layerStack.push(layer);
  return layer;
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && layerStack.length) layerStack[layerStack.length - 1].close(); });

export function confirmDlg(title, body, okText = 'تأیید', danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `
      <div class="card-h"><h3>${esc(title)}</h3></div>
      <div class="card-b">${body}</div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px">
        <button class="btn" data-close>انصراف</button>
        <button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(okText)}</button>
      </div>`, { onClose: () => { if (!done) resolve(false); } });
    l.box.querySelector('[data-ok]').addEventListener('click', () => { done = true; l.close(); resolve(true); });
  });
}

export function promptDlg(title, label, value = '', hint = '') {
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `
      <div class="card-h"><h3>${esc(title)}</h3></div>
      <div class="card-b"><div class="field"><label>${esc(label)}</label><input class="inp" data-v value="${attr(value)}">${hint ? `<div class="hint">${hint}</div>` : ''}</div></div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" data-ok>ذخیره</button></div>`,
      { onClose: () => { if (!done) resolve(null); } });
    const inp = l.box.querySelector('[data-v]');
    inp.focus(); inp.select();
    const ok = () => { done = true; const v = inp.value; l.close(); resolve(v); };
    l.box.querySelector('[data-ok]').addEventListener('click', ok);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
  });
}

// ---------------------------------------------------------------- فرم
export function vals(root) {
  const out = {};
  root.querySelectorAll('[name]').forEach((el) => {
    const n = el.getAttribute('name');
    if (el.type === 'checkbox') out[n] = el.checked;
    else if (el.type === 'radio') { if (el.checked) out[n] = el.value; }
    else out[n] = el.value;
  });
  return out;
}

export const sourceLogo = (name) => {
  const t = String(name || '?').replace(/[‌\s]/g, '');
  return esc(t.slice(0, 1));
};

export function emptyState(ic, title, text, action = '') {
  return `<div class="empty"><div class="em-ic">${icon(ic, 28)}</div><h3>${esc(title)}</h3><div>${text}</div>${action ? `<div class="mt16">${action}</div>` : ''}</div>`;
}

export function debounce(fn, ms = 300) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function every(ms, fn) {
  const id = setInterval(fn, ms);
  S.timers.push(id);
  return id;
}

export function go(hash) { location.hash = hash; }

export async function openPath(path) {
  try { await api('/api/open-folder', { body: { path } }); }
  catch (e) { errToast(e); }
}

export function fileUrl(path, download = false) {
  return `/api/file?path=${encodeURIComponent(path)}${download ? '&download=1' : ''}`;
}

export async function refreshBoot() {
  S.boot = await api('/api/bootstrap');
  return S.boot;
}

export function srcById(id) { return (S.boot?.sources || []).find((s) => s.id === id); }
export function schemaById(id) { return (S.boot?.schemas || []).find((s) => s.id === id); }
export function fieldLabel(key) {
  const f = (S.boot?.canonical_fields || []).find((x) => x.key === key);
  return f ? f.label : key;
}
