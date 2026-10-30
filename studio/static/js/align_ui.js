// ویرایشگر و پیش‌نمایش ترازبندی تصاویر (مشترک بین «پردازش تصاویر»، «خروجی‌ساز» و «تنظیمات»)
import { api, icon, esc, attr, fa, errToast } from './core.js';

export const ALIGN_DEFAULT = {
  canvas_w: 1280, canvas_h: 1280, margin: 60, per_side: false, margin_top: 60, margin_right: 60, margin_bottom: 60, margin_left: 60,
  trim: 'auto', alpha_threshold: 10, color_tolerance: 18, despeckle: 2, upscale: true, background: 'auto', format: 'png', quality: 92,
};
const PRESETS = [0, 40, 60, 80, 100, 120, 160];
const TRIM = [['auto', 'خودکار (شفافیت، وگرنه رنگ پس‌زمینه)'], ['alpha', 'فقط پیکسل‌های شفاف'], ['color', 'رنگ یکدست پس‌زمینه (گوشه‌ها)'], ['none', 'بدون تریم']];
const SIDES = [['top', 'بالا'], ['right', 'راست'], ['bottom', 'پایین'], ['left', 'چپ']];

export function fullAlign(o) {
  const a = { ...ALIGN_DEFAULT, ...(o || {}) };
  SIDES.forEach(([s]) => { if (!a.per_side || a[`margin_${s}`] === undefined || a[`margin_${s}`] === null) a[`margin_${s}`] = a.margin; });
  return a;
}

function bgKind(bg) { return ['auto', 'transparent'].includes(bg) ? bg : bg === '#ffffff' ? 'white' : 'custom'; }

export function alignEditor(o, opts = {}) {
  const a = fullAlign(o);
  const bk = bgKind(a.background);
  return `<div class="align-ed" data-align-root>
    <div class="al-top">
      <div class="grow">
        <label class="lbl">فاصله‌ی سوژه تا لبه‌های تصویر نهایی</label>
        <div class="flex wrap mt8" style="gap:6px">
          <div class="seg" data-al-presets>${PRESETS.map((p) => `<button type="button" data-al-preset="${p}" class="${!a.per_side && a.margin === p ? 'on' : ''}">${fa(p)}</button>`).join('')}</div>
          <div class="inp-unit"><input class="inp sm" type="number" min="0" data-al="margin" value="${a.margin}" style="width:90px"><span>پیکسل</span></div>
        </div>
        <label class="check small mt12"><input type="checkbox" data-al="per_side" ${a.per_side ? 'checked' : ''}> فاصله‌ی جداگانه برای هر لبه</label>
        <div class="al-sides mt8 ${a.per_side ? '' : 'hidden'}">${SIDES.map(([s, l]) => `<div class="field"><span class="xs">${l}</span><input class="inp sm" type="number" min="0" data-al="margin_${s}" value="${a[`margin_${s}`]}"></div>`).join('')}</div>
        <div class="flex wrap mt12" style="gap:8px"><span class="small">اندازه‌ی بوم نهایی</span>
          <input class="inp sm" type="number" min="16" data-al="canvas_w" value="${a.canvas_w}" style="width:92px"><span class="muted">×</span>
          <input class="inp sm" type="number" min="16" data-al="canvas_h" value="${a.canvas_h}" style="width:92px"><span class="xs muted">پیکسل (عرض × ارتفاع)</span></div>
      </div>
      <div class="al-diag-wrap" data-al-diag>${diagram(a)}</div>
    </div>
    <details class="mt12" ${opts.openAdvanced ? 'open' : ''}><summary class="lbl" style="cursor:pointer">${icon('crop', 15)} تشخیص فضای خالی، پس‌زمینه و فرمت</summary>
      <div class="form-grid mt12">
        <div class="field"><label class="small">روش تشخیص فضای خالی (تریم)</label><select class="inp sm" data-al="trim">${TRIM.map(([k, l]) => `<option value="${k}" ${a.trim === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="field"><label class="small">آستانه‌ی شفافیت (۰ تا ۲۵۴)</label><input class="inp sm" type="number" min="0" max="254" data-al="alpha_threshold" value="${a.alpha_threshold}">
          <div class="hint">سایه‌ها و هاله‌های کم‌رنگ‌تر از این مقدار جزو فضای خالی حساب می‌شوند.</div></div>
        <div class="field"><label class="small">تلورانس رنگ پس‌زمینه (۰ تا ۱۰۰)</label><input class="inp sm" type="number" min="0" max="100" data-al="color_tolerance" value="${a.color_tolerance}">
          <div class="hint">برای تصاویر بدون شفافیت (مثلاً پس‌زمینه‌ی سفید JPG).</div></div>
        <div class="field"><label class="small">نادیده گرفتن لکه‌های ریز (پیکسل)</label><input class="inp sm" type="number" min="0" max="20" data-al="despeckle" value="${a.despeckle}">
          <div class="hint">نقطه‌ها و نویزهای جدا از سوژه که از این کوچک‌ترند، مرز سوژه را جابه‌جا نمی‌کنند. ۰ = خاموش.</div></div>
        <div class="field"><label class="small">پس‌زمینه‌ی تصویر نهایی</label>
          <div class="flex" style="gap:6px"><select class="inp sm" data-al="bgkind"><option value="auto" ${bk === 'auto' ? 'selected' : ''}>خودکار (شفاف؛ یا همان رنگ پس‌زمینه‌ی اصلی)</option><option value="transparent" ${bk === 'transparent' ? 'selected' : ''}>شفاف</option><option value="white" ${bk === 'white' ? 'selected' : ''}>سفید</option><option value="custom" ${bk === 'custom' ? 'selected' : ''}>رنگ دلخواه</option></select>
            <input type="color" data-al="bgcolor" value="${bk === 'custom' ? a.background : '#f4f4f5'}" class="${bk === 'custom' ? '' : 'hidden'}" style="width:42px;height:36px;border:0;background:none"></div></div>
        <div class="field"><label class="small">فرمت فایل</label><div class="flex" style="gap:6px"><select class="inp sm" data-al="format"><option value="png" ${a.format === 'png' ? 'selected' : ''}>PNG (با شفافیت)</option><option value="webp" ${a.format === 'webp' ? 'selected' : ''}>WebP</option><option value="jpg" ${a.format === 'jpg' ? 'selected' : ''}>JPG (بدون شفافیت)</option></select>
          <input class="inp sm ${a.format === 'png' ? 'hidden' : ''}" type="number" min="40" max="100" data-al="quality" value="${a.quality}" style="width:80px" title="کیفیت"></div></div>
      </div>
      <label class="check small mt12"><input type="checkbox" data-al="upscale" ${a.upscale ? 'checked' : ''}> سوژه‌های کوچک هم بزرگ شوند تا به همان فاصله برسند (پیشنهادی؛ اگر خاموش باشد، سوژه‌ی کوچک فقط وسط بوم قرار می‌گیرد)</label>
    </details>
  </div>`;
}

function diagram(a) {
  const W = a.canvas_w, H = a.canvas_h;
  const t = a.per_side ? a.margin_top : a.margin, r = a.per_side ? a.margin_right : a.margin, b = a.per_side ? a.margin_bottom : a.margin, l = a.per_side ? a.margin_left : a.margin;
  const aw = Math.max(0, W - l - r), ah = Math.max(0, H - t - b);
  const bad = aw < 8 || ah < 8;
  const pct = (v, d) => `${(v / d) * 100}%`;
  // یک سوژه‌ی نمونه‌ی عمودی (نسبت ۱ به ۲٫۲) که با قاعده جا داده شده است
  const sw = 1, sh = 2.2;
  const sc = Math.min(aw / sw, ah / sh);
  const pw = sw * sc, ph = sh * sc;
  return `<div class="al-diag checker" style="aspect-ratio:${W}/${H}">
      <div class="al-inner ${bad ? 'bad' : ''}" style="top:${pct(t, H)};right:${pct(r, W)};bottom:${pct(b, H)};left:${pct(l, W)}"></div>
      ${bad ? '' : `<div class="al-subj" style="width:${pct(pw, W)};height:${pct(ph, H)};left:${pct(l + (aw - pw) / 2, W)};top:${pct(t + (ah - ph) / 2, H)}"></div>`}
      <span class="al-m" style="top:${pct(t / 2, H)};left:50%">${fa(t)}</span><span class="al-m" style="bottom:${pct(b / 2, H)};left:50%;transform:translate(-50%,50%)">${fa(b)}</span>
      <span class="al-m" style="top:50%;left:${pct(l / 2, W)}">${fa(l)}</span><span class="al-m" style="top:50%;right:${pct(r / 2, W)};transform:translate(50%,-50%)">${fa(r)}</span>
    </div>
    <div class="xs muted mt8" style="text-align:center">${bad ? '<span style="color:var(--err)">حاشیه‌ها از بوم بزرگ‌ترند</span>' : `بوم ${fa(W)}×${fa(H)} · ناحیه‌ی سوژه ${fa(aw)}×${fa(ah)}`}</div>`;
}

export function readAlign(root) {
  const g = (k) => root.querySelector(`[data-al="${k}"]`);
  const n = (k) => Number(g(k)?.value || 0);
  const o = {
    canvas_w: n('canvas_w') || 1280, canvas_h: n('canvas_h') || 1280, margin: n('margin'), per_side: g('per_side').checked,
    trim: g('trim').value, alpha_threshold: n('alpha_threshold'), color_tolerance: n('color_tolerance'), despeckle: n('despeckle'),
    upscale: g('upscale').checked, format: g('format').value, quality: n('quality') || 92,
  };
  SIDES.forEach(([s]) => { o[`margin_${s}`] = o.per_side ? n(`margin_${s}`) : o.margin; });
  const bk = g('bgkind').value;
  o.background = bk === 'white' ? '#ffffff' : bk === 'custom' ? g('bgcolor').value : bk;
  return o;
}

export function bindAlign(root, onChange) {
  const ed = root.querySelector('[data-align-root]') || root;
  const redraw = () => {
    const o = readAlign(ed);
    ed.querySelector('[data-al-diag]').innerHTML = diagram(o);
    ed.querySelectorAll('[data-al-preset]').forEach((b) => b.classList.toggle('on', !o.per_side && Number(b.dataset.alPreset) === o.margin));
    ed.querySelector('.al-sides').classList.toggle('hidden', !o.per_side);
    ed.querySelector('[data-al="bgcolor"]').classList.toggle('hidden', ed.querySelector('[data-al="bgkind"]').value !== 'custom');
    ed.querySelector('[data-al="quality"]').classList.toggle('hidden', o.format === 'png');
    if (onChange) onChange(o);
  };
  ed.addEventListener('click', (e) => {
    const p = e.target.closest('[data-al-preset]');
    if (!p) return;
    ed.querySelector('[data-al="margin"]').value = p.dataset.alPreset;
    if (ed.querySelector('[data-al="per_side"]').checked) {
      SIDES.forEach(([s]) => { ed.querySelector(`[data-al="margin_${s}"]`).value = p.dataset.alPreset; });
    }
    redraw();
  });
  ed.addEventListener('input', (e) => {
    if (e.target.dataset.al === 'margin' && ed.querySelector('[data-al="per_side"]').checked) {
      SIDES.forEach(([s]) => { ed.querySelector(`[data-al="margin_${s}"]`).value = e.target.value; });
    }
    if (e.target.closest('[data-al]')) redraw();
  });
  ed.addEventListener('change', (e) => { if (e.target.closest('[data-al]')) redraw(); });
  return () => readAlign(ed);
}

// ------------------------------------------------------------------ پیش‌نمایش
export async function runPreview(box, body) {
  box.innerHTML = `<div class="card-b muted flex">${icon('loader', 16, 'spin')} در حال ساخت پیش‌نمایش…</div>`;
  try {
    const r = await api('/api/align/preview', { body });
    if (!r.ok) throw new Error(r.error);
    box.innerHTML = previewGrid(r.samples, r.options);
  } catch (e) { box.innerHTML = `<div class="card-b"><div class="alert err">${icon('alert')}<div>${esc(e.message)}</div></div></div>`; }
}

const LIM = { width: 'عرض', height: 'ارتفاع' };
const TRIMLBL = { alpha: 'شفافیت', color: 'رنگ پس‌زمینه', none: 'بدون تریم' };

export function previewGrid(samples, o) {
  if (!samples.length) return '<div class="card-b muted small">تصویری در این مسیر پیدا نشد.</div>';
  const W = o.canvas_w, H = o.canvas_h;
  const inner = `top:${(o.margin_top / H) * 100}%;right:${(o.margin_right / W) * 100}%;bottom:${(o.margin_bottom / H) * 100}%;left:${(o.margin_left / W) * 100}%`;
  return `<div class="al-grid">${samples.map((s) => {
    if (s.error) return `<div class="al-card"><div class="xs ltr ellipsis">${esc(s.name)}</div><div class="alert err mt8">${icon('alert')}<div>${esc(s.error)}</div></div></div>`;
    const i = s.info;
    const bb = i.bbox_pct;
    return `<div class="al-card">
      <div class="xs ltr ellipsis muted" title="${attr(s.name)}" style="text-align:right">${esc(s.name)}</div>
      <div class="al-pair mt8">
        <figure><div class="al-img checker"><img src="${s.before}"><div class="al-bbox" style="right:auto;left:${bb[0]}%;top:${bb[1]}%;width:${bb[2]}%;height:${bb[3]}%"></div></div><figcaption>قبل · ${fa(i.source_size[0])}×${fa(i.source_size[1])}</figcaption></figure>
        <span class="al-arrow">${icon('chevronLeft', 18)}</span>
        <figure><div class="al-img checker" style="aspect-ratio:${W}/${H}"><img src="${s.after}"><div class="al-guide" style="${inner}"></div></div><figcaption>بعد · ${fa(W)}×${fa(H)}</figcaption></figure>
      </div>
      <div class="flex wrap xs mt8" style="gap:6px">
        <span class="tag">${icon('crop', 11)} تریم با ${TRIMLBL[i.trim] || i.trim}: ${fa(i.trimmed[0])}×${fa(i.trimmed[1])} px حذف شد</span>
        <span class="tag">مقیاس ×${fa(Number(i.scale).toFixed(2))}</span><span class="tag">تعیین‌کننده: ${LIM[i.limited_by]}</span>
        ${i.low_res ? `<span class="tag" style="color:var(--warn)">${icon('alert', 11)} بزرگ‌نمایی زیاد؛ ممکن است تار شود</span>` : ''}
        ${i.empty ? `<span class="tag" style="color:var(--warn)">پس‌زمینه‌ی جدایی پیدا نشد؛ کل تصویر سوژه حساب شد</span>` : ''}
      </div></div>`;
  }).join('')}</div>`;
}

export function fileToDataUrl(file) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
}

export { errToast };
