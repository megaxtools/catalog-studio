// ماژول ویرایشگر تصویر: برش، چرخش، قرینه، پاک‌کن (حذف المان‌ها) و تنظیم رنگ — غیرمخرب
// خروجی ویرایشگر فقط «دستور ویرایش» است؛ سرور همان را روی نسخه‌ی اصلی اجرا می‌کند (فیلترها معادل CSS مرورگرند).
import { icon, esc, fa, openLayer, toast } from './core.js';

const EMPTY = () => ({ rotate: 0, flip_h: false, flip_v: false, erase: [], crop: null, adjust: { hue: 0, saturation: 100, brightness: 100, contrast: 100 }, bg: null });

function loadImg(url) {
  return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error('تصویر بارگذاری نشد.')); im.src = url; });
}

export function openImageEditor({ url, recipe, title = 'ویرایش تصویر' }) {
  const R = { ...EMPTY(), ...(recipe || {}), adjust: { ...EMPTY().adjust, ...((recipe || {}).adjust || {}) }, erase: [...((recipe || {}).erase || [])] };
  const redo = [];
  let tool = 'erase';
  let brush = 40;
  return new Promise((resolve) => {
    let done = false;
    const l = openLayer('modal', `<div class="card-h"><h3>${icon('palette', 18)} ${esc(title)}</h3><span class="sub">غیرمخرب؛ فایل اصلی دست نمی‌خورد</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
      <div class="ie">
        <div class="ie-tools">
          <div class="seg" id="ie-tool"><button data-t="erase" title="پاک‌کن: روی المان‌های اضافه بکشید">${icon('eraser', 15)} پاک‌کن</button><button data-t="crop" title="برش: یک کادر بکشید">${icon('crop', 15)} برش</button><button data-t="none" title="فقط پیش‌نمایش">${icon('eye', 15)}</button></div>
          <div class="flex wrap" style="gap:4px">
            <button class="btn sm icon" data-a="rotl" title="چرخش پادساعت‌گرد">${icon('undo', 15)}</button><button class="btn sm icon" data-a="rotr" title="چرخش ساعت‌گرد">${icon('rotate', 15)}</button>
            <button class="btn sm icon" data-a="fliph" title="قرینه‌ی افقی">${icon('flip', 15)}</button><button class="btn sm icon" data-a="flipv" title="قرینه‌ی عمودی" style="transform:rotate(90deg)">${icon('flip', 15)}</button>
            <button class="btn sm icon" data-a="undo" title="برگشت (پاک‌کن)">${icon('undo', 15)}</button><button class="btn sm icon" data-a="redo" title="دوباره">${icon('redo', 15)}</button></div>
          <label class="ie-sl" id="ie-brush"><span>اندازه‌ی پاک‌کن <b data-v="brush"></b></span><input type="range" min="4" max="400" value="40" data-s="brush"></label>
          <div class="ie-sep"></div>
          ${[['hue', 'رنگ (Hue)', -180, 180, '°'], ['saturation', 'اشباع رنگ', 0, 300, '٪'], ['brightness', 'روشنایی', 0, 300, '٪'], ['contrast', 'کنتراست', 0, 300, '٪']].map(([k, lab, a, b, u]) =>
            `<label class="ie-sl"><span>${lab} <b data-v="${k}"></b>${u}</span><input type="range" min="${a}" max="${b}" value="${R.adjust[k]}" data-s="${k}"></label>`).join('')}
          <div class="ie-sep"></div>
          <label class="check small"><input type="checkbox" id="ie-bgon" ${R.bg ? 'checked' : ''}> پس‌زمینه‌ی رنگی</label><input type="color" id="ie-bg" value="${R.bg || '#ffffff'}" class="inp sm" style="width:60px;padding:2px">
          <button class="btn sm ghost" data-a="nocrop">${icon('crop', 14)} حذف برش</button>
          <button class="btn sm ghost danger" data-a="resetall">${icon('refresh', 14)} حذف همه‌ی ویرایش‌ها</button>
        </div>
        <div class="ie-stage checker" id="ie-stage"><canvas id="ie-c"></canvas><div class="ie-msg muted small" id="ie-msg">در حال بارگذاری تصویر…</div></div>
      </div>
      <div class="drawer-f" style="border-radius:0 0 20px 20px"><span class="small muted" id="ie-info"></span><span class="grow"></span><button class="btn" data-close>انصراف</button><button class="btn primary" id="ie-save">${icon('save', 16)} ذخیره‌ی ویرایش</button></div>`,
    { wide: true, sticky: true, onClose: () => { if (!done) resolve(undefined); } });
    l.box.classList.add('xwide');
    const b = l.box;
    const cv = b.querySelector('#ie-c');
    const ctx = cv.getContext('2d');
    let src = null; let base = null; let erased = null; let scale = 1;
    let drag = null;

    const transformed = () => {
      const a = document.createElement('canvas');
      a.width = src.width; a.height = src.height;
      const ax = a.getContext('2d');
      ax.translate(R.flip_h ? a.width : 0, R.flip_v ? a.height : 0);
      ax.scale(R.flip_h ? -1 : 1, R.flip_v ? -1 : 1);
      ax.drawImage(src, 0, 0);
      const r = ((R.rotate % 360) + 360) % 360;
      if (!r) return a;
      const o = document.createElement('canvas');
      o.width = r === 180 ? a.width : a.height; o.height = r === 180 ? a.height : a.width;
      const ox = o.getContext('2d');
      if (r === 90) { ox.translate(o.width, 0); ox.rotate(Math.PI / 2); }
      if (r === 180) { ox.translate(o.width, o.height); ox.rotate(Math.PI); }
      if (r === 270) { ox.translate(0, o.height); ox.rotate(-Math.PI / 2); }
      ox.drawImage(a, 0, 0);
      return o;
    };
    const rebuild = () => {
      base = transformed();
      erased = document.createElement('canvas');
      erased.width = base.width; erased.height = base.height;
      const ex = erased.getContext('2d');
      ex.drawImage(base, 0, 0);
      ex.globalCompositeOperation = 'destination-out';
      ex.lineCap = 'round'; ex.lineJoin = 'round';
      for (const s of R.erase) stroke(ex, s);
      const stage = b.querySelector('#ie-stage');
      const maxW = Math.max(300, stage.clientWidth - 24); const maxH = Math.max(300, Math.min(window.innerHeight * 0.62, 640));
      scale = Math.min(maxW / base.width, maxH / base.height, 4);
      cv.width = Math.round(base.width * scale); cv.height = Math.round(base.height * scale);
      draw();
    };
    const stroke = (ex, s) => {
      ex.lineWidth = s.size;
      ex.beginPath();
      s.points.forEach((p, i) => (i ? ex.lineTo(p[0], p[1]) : ex.moveTo(p[0], p[1])));
      if (s.points.length === 1) ex.lineTo(s.points[0][0] + 0.01, s.points[0][1]);
      ex.stroke();
    };
    const filterCss = () => `hue-rotate(${R.adjust.hue}deg) saturate(${R.adjust.saturation}%) brightness(${R.adjust.brightness}%) contrast(${R.adjust.contrast}%)`;
    const draw = () => {
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.save();
      ctx.scale(scale, scale);
      if (R.bg) { ctx.fillStyle = R.bg; ctx.fillRect(0, 0, base.width, base.height); }
      ctx.filter = filterCss();
      ctx.drawImage(erased, 0, 0);
      ctx.filter = 'none';
      const c = drag?.crop || R.crop;
      if (c) {
        ctx.fillStyle = 'rgba(15,15,30,.55)';
        ctx.beginPath();
        ctx.rect(0, 0, base.width, base.height);
        ctx.rect(c.x, c.y, c.w, c.h);
        ctx.fill('evenodd');
        ctx.strokeStyle = '#4f39f6'; ctx.lineWidth = 2 / scale; ctx.setLineDash([8 / scale, 5 / scale]);
        ctx.strokeRect(c.x, c.y, c.w, c.h);
      }
      ctx.restore();
      b.querySelector('#ie-info').textContent = `${fa(base.width)}×${fa(base.height)} پیکسل${R.crop ? ` · برش ${fa(Math.round(R.crop.w))}×${fa(Math.round(R.crop.h))}` : ''} · ${fa(R.erase.length)} خط پاک‌کن`;
      ['hue', 'saturation', 'brightness', 'contrast'].forEach((k) => { b.querySelector(`[data-v="${k}"]`).textContent = fa(R.adjust[k]); });
      b.querySelector('[data-v="brush"]').textContent = fa(brush);
      b.querySelectorAll('#ie-tool button').forEach((x) => x.classList.toggle('on', x.dataset.t === tool));
      b.querySelector('#ie-brush').style.display = tool === 'erase' ? '' : 'none';
      cv.style.cursor = tool === 'none' ? 'default' : 'crosshair';
    };
    const pt = (e) => { const r = cv.getBoundingClientRect(); return [Math.max(0, Math.min(base.width, (e.clientX - r.left) / scale)), Math.max(0, Math.min(base.height, (e.clientY - r.top) / scale))]; };
    cv.addEventListener('pointerdown', (e) => {
      if (!base || tool === 'none') return;
      cv.setPointerCapture(e.pointerId);
      const p = pt(e);
      if (tool === 'erase') { drag = { stroke: { size: brush, points: [p.map((x) => Math.round(x * 10) / 10)] } }; }
      if (tool === 'crop') { drag = { start: p, crop: { x: p[0], y: p[1], w: 0, h: 0 } }; }
    });
    cv.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const p = pt(e);
      if (drag.stroke) {
        const last = drag.stroke.points[drag.stroke.points.length - 1];
        if (Math.hypot(p[0] - last[0], p[1] - last[1]) < 1.5) return;
        drag.stroke.points.push(p.map((x) => Math.round(x * 10) / 10));
        const ex = erased.getContext('2d');
        ex.globalCompositeOperation = 'destination-out'; ex.lineCap = 'round'; ex.lineJoin = 'round'; ex.lineWidth = drag.stroke.size;
        ex.beginPath(); ex.moveTo(last[0], last[1]); ex.lineTo(p[0], p[1]); ex.stroke();
        draw();
      }
      if (drag.crop) {
        const [sx, sy] = drag.start;
        drag.crop = { x: Math.min(sx, p[0]), y: Math.min(sy, p[1]), w: Math.abs(p[0] - sx), h: Math.abs(p[1] - sy) };
        draw();
      }
    });
    const end = () => {
      if (!drag) return;
      if (drag.stroke) { R.erase.push(drag.stroke); redo.length = 0; rebuild(); }
      if (drag.crop) { if (drag.crop.w > 6 && drag.crop.h > 6) R.crop = drag.crop; }
      drag = null;
      draw();
    };
    cv.addEventListener('pointerup', end);
    cv.addEventListener('pointercancel', end);
    const geom = (fn) => {
      if (R.erase.length || R.crop) toast('پاک‌کن و برش با چرخش یا قرینه جابه‌جا می‌شوند؛ برای همین پاک شدند. اول بچرخانید، بعد پاک‌کن و برش.');
      R.erase = []; R.crop = null; redo.length = 0;
      fn(); rebuild();
    };
    b.addEventListener('click', (e) => {
      const t = e.target.closest('[data-t]');
      if (t) { tool = t.dataset.t; draw(); return; }
      const a = e.target.closest('[data-a]')?.dataset.a;
      if (!a || !base) return;
      if (a === 'rotr') geom(() => { R.rotate = (R.rotate + 90) % 360; });
      if (a === 'rotl') geom(() => { R.rotate = (R.rotate + 270) % 360; });
      if (a === 'fliph') geom(() => { R.flip_h = !R.flip_h; });
      if (a === 'flipv') geom(() => { R.flip_v = !R.flip_v; });
      if (a === 'undo' && R.erase.length) { redo.push(R.erase.pop()); rebuild(); }
      if (a === 'redo' && redo.length) { R.erase.push(redo.pop()); rebuild(); }
      if (a === 'nocrop') { R.crop = null; draw(); }
      if (a === 'resetall') { Object.assign(R, EMPTY()); b.querySelectorAll('[data-s]').forEach((x) => { if (x.dataset.s !== 'brush') x.value = R.adjust[x.dataset.s]; }); rebuild(); }
    });
    b.addEventListener('input', (e) => {
      const s = e.target.closest('[data-s]');
      if (s) { if (s.dataset.s === 'brush') brush = Number(s.value); else R.adjust[s.dataset.s] = Number(s.value); draw(); }
      if (e.target.id === 'ie-bg' && b.querySelector('#ie-bgon').checked) { R.bg = e.target.value; draw(); }
    });
    b.querySelector('#ie-bgon').addEventListener('change', (e) => { R.bg = e.target.checked ? b.querySelector('#ie-bg').value : null; draw(); });
    b.querySelector('#ie-save').addEventListener('click', () => {
      const out = { ...R, crop: R.crop ? { x: Math.round(R.crop.x), y: Math.round(R.crop.y), w: Math.round(R.crop.w), h: Math.round(R.crop.h) } : null };
      done = true; l.close(); resolve({ recipe: out });
    });
    loadImg(url).then((im) => { src = im; b.querySelector('#ie-msg').remove(); rebuild(); }).catch((e) => { b.querySelector('#ie-msg').textContent = e.message; });
  });
}
