import {
  S, api, icon, esc, attr, fa, num, jdate, chip, isLive, progress, toast, okToast, errToast, openLayer,
  confirmDlg, emptyState, every, go, refreshBoot, trunc, srcById, schemaById,
} from './core.js';
import { assist, busy, noProviderHint } from './ai_assist.js';

const KIND_LBL = { openai: 'سازگار با OpenAI', anthropic: 'Anthropic', gemini: 'Google Gemini' };
const IMG_MODE_LBL = { images_api: 'Images API (‎/images/generations‎)', chat_modalities: 'چت با خروجی تصویر (OpenRouter)', gemini: 'Gemini (خروجی تصویر)', none: 'بدون تولید تصویر' };
const AI_STATUS = { pending: ['idle', 'در صف'], running: ['run', 'در حال تولید'], paused: ['idle', 'متوقف'], completed: ['ok', 'تمام شد'], error: ['err', 'خطا'] };
const aiChip = (s) => { const [c, t] = AI_STATUS[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}</span>`; };

// ======================================================================
// مرکز هوش مصنوعی
// ======================================================================
const AH = { tab: 'providers', data: null };

export const AIHub = {
  title: 'هوش مصنوعی',
  crumb: 'اتصال به سرویس‌دهنده‌ها، قالب‌های تولید و اجراهای تولید',
  top: () => `<button class="btn primary" data-act="newprov">${icon('plus')} اتصال جدید</button>`,
  async render() {
    AH.tab = sessionStorage.getItem('ai-tab') || 'providers';
    return `
      <div class="alert p mb16">${icon('sparkles')}<div><b>تولید محتوا روی داده‌ی استخراج‌شده</b>خروجی هوش مصنوعی جدا از داده‌ی اصلی ذخیره می‌شود و هر وقت بخواهید با یک کلیک به داده‌ی استخراج‌شده برمی‌گردید. ویرایش دستی شما همیشه بر خروجی هوش مصنوعی مقدم است و قواعد متن روی خروجی هوش مصنوعی هم اعمال می‌شوند.</div></div>
      <div class="card"><div class="tabs" id="ah-tabs"></div><div id="ah-body"></div></div>`;
  },
  async mount() { await this.draw(); every(2000, () => { if (AH.tab === 'jobs') this.draw(true); }); },
  async draw(silent) {
    document.getElementById('ah-tabs').innerHTML = [['providers', 'link', 'اتصال‌ها'], ['profiles', 'wand', 'قالب‌های تولید'], ['jobs', 'zap', 'اجراهای تولید']]
      .map(([k, ic, l]) => `<button class="${AH.tab === k ? 'on' : ''}" data-act="tab" data-t="${k}">${icon(ic, 16)} ${l}</button>`).join('');
    const b = document.getElementById('ah-body');
    if (AH.tab === 'providers') b.innerHTML = await providersTab();
    else if (AH.tab === 'profiles') b.innerHTML = await profilesTab();
    else {
      const html = await jobsTab();
      if (!silent || b.dataset.sig !== html.length + '') { b.innerHTML = html; b.dataset.sig = html.length + ''; }
    }
  },
  act: {
    tab: (el) => { AH.tab = el.dataset.t; sessionStorage.setItem('ai-tab', AH.tab); AIHub.draw(); },
    newprov: () => providerForm(null),
    savedefaults: async () => {
      await api('/api/settings', { method: 'PUT', body: { ai_default_provider_id: Number(document.getElementById('df-p').value) || null,
        ai_default_model: document.getElementById('df-m').value.trim(), ai_default_image_provider_id: Number(document.getElementById('df-i').value) || null } });
      await refreshBoot();
      okToast('پیش‌فرض‌ها ذخیره شد.');
    },
    editprov: async (el) => providerForm(await api(`/api/ai/providers/${el.dataset.id}`)),
    delprov: async (el) => { if (!(await confirmDlg('حذف اتصال', 'این اتصال حذف شود؟ قالب‌هایی که از آن استفاده می‌کنند باید اتصال دیگری بگیرند.', 'حذف', true))) return; await api(`/api/ai/providers/${el.dataset.id}`, { method: 'DELETE' }); AIHub.draw(); },
    testprov: async (el) => {
      const out = document.getElementById(`pt-${el.dataset.id}`);
      out.innerHTML = `${icon('loader', 14, 'spin')} در حال آزمایش…`;
      const r = await api(`/api/ai/providers/${el.dataset.id}/test`, { body: {} });
      out.innerHTML = r.ok ? `<span class="chip ok">پاسخ داد · ${fa(r.ms)} میلی‌ثانیه</span>` : `<span class="chip err" title="${attr(r.error)}">${esc(trunc(r.error, 70))}</span>`;
    },
    testimg: async (el) => {
      const out = document.getElementById(`pt-${el.dataset.id}`);
      out.innerHTML = `${icon('loader', 14, 'spin')} در حال تولید تصویر…`;
      const r = await api(`/api/ai/providers/${el.dataset.id}/test-image`, { body: {} });
      out.innerHTML = r.ok ? `<img class="thumb" style="width:64px;height:64px" src="${r.image}">` : `<span class="chip err" title="${attr(r.error)}">${esc(trunc(r.error, 70))}</span>`;
    },
    newprof: async () => { const p = await api('/api/ai/profiles', { body: { name: 'قالب جدید' } }); await refreshBoot(); go(`#/ai/profiles/${p.id}`); },
    dupprof: async (el) => { const p = await api(`/api/ai/profiles/${el.dataset.id}/duplicate`, { body: {} }); await refreshBoot(); go(`#/ai/profiles/${p.id}`); },
    delprof: async (el) => { if (!(await confirmDlg('حذف قالب', 'این قالب تولید حذف شود؟', 'حذف', true))) return; await api(`/api/ai/profiles/${el.dataset.id}`, { method: 'DELETE' }); await refreshBoot(); AIHub.draw(); },
    jstop: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/stop`, { body: {} }); AIHub.draw(); },
    jresume: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/resume`, { body: {} }); AIHub.draw(); },
    jdel: async (el) => { await api(`/api/ai/jobs/${el.dataset.id}/delete`, { body: {} }); AIHub.draw(); },
  },
};

async function providersTab() {
  const r = await api('/api/ai/providers');
  AH.presets = r.presets;
  if (!r.providers.length) return emptyState('link', 'هنوز اتصالی نساخته‌اید', 'یک سرویس‌دهنده (OpenAI، Claude، Gemini، OpenRouter، AvalAI یا هر سرویس سازگار با OpenAI) را وصل کنید.', `<button class="btn primary" data-act="newprov">${icon('plus')} اتصال جدید</button>`);
  const st = await api('/api/settings');
  const opt = (sel, img) => `<option value="">نخستین اتصال</option>${r.providers.filter((p) => !img || p.image_mode !== 'none').map((p) => `<option value="${p.id}" ${String(sel) === String(p.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}`;
  const defaults = `<div class="ai-inline" style="margin:0 0 16px"><div class="flex wrap">
      <span style="color:var(--primary)">${icon('sparkles', 18)}</span><b class="grow">پیش‌فرض دستیار هوش مصنوعی در همه‌ی بخش‌ها</b>
      <label class="small">متن</label><select class="inp sm" style="width:auto" id="df-p">${opt(st.ai_default_provider_id)}</select>
      <input class="inp sm ltr" style="width:200px" id="df-m" data-noai value="${attr(st.ai_default_model || '')}" placeholder="مدل (خالی = مدل اتصال)">
      <label class="small">تصویر</label><select class="inp sm" style="width:auto" id="df-i">${opt(st.ai_default_image_provider_id, true)}</select>
      <button class="btn sm primary" data-act="savedefaults">${icon('save', 14)} ذخیره</button></div>
      <div class="hint mt8">دکمه‌ی ✨ کنار فیلدها، طراحی اسکیما، پیشنهاد اسلاگ و قاعده، تولید بانک داده و هر جای دیگری که اتصال مشخص نشده باشد از همین اتصال استفاده می‌کند.</div></div>`;
  return `<div class="card-b">${defaults}<div class="grid g2">${r.providers.map((p) => `
    <div class="fieldbox">
      <div class="flex"><div class="src-logo" style="width:40px;height:40px;font-size:15px">${icon('sparkles', 18)}</div>
        <div class="grow"><b style="color:var(--z-900)">${esc(p.name)}</b><div class="xs muted ltr" style="text-align:right">${esc(p.base_url)}</div></div>
        <span class="tag">${esc(KIND_LBL[p.kind] || p.kind)}</span></div>
      <dl class="kv mt12 small">
        <dt>مدل متن</dt><dd class="ltr">${esc(p.text_model || '—')}</dd>
        <dt>مدل تصویر</dt><dd class="ltr">${esc(p.image_model || '—')} <span class="xs muted">${esc(IMG_MODE_LBL[p.image_mode] || '')}</span></dd>
        <dt>کلید API</dt><dd class="ltr">${p.has_key ? esc(p.api_key_masked) : '<span class="muted">ندارد</span>'}</dd>
        ${p.proxy ? `<dt>پراکسی</dt><dd class="ltr">${esc(p.proxy)}</dd>` : ''}
      </dl>
      <div class="btns mt12"><button class="btn sm soft" data-act="testprov" data-id="${p.id}">${icon('zap', 14)} آزمایش اتصال</button>
        ${p.image_mode !== 'none' && p.kind !== 'anthropic' ? `<button class="btn sm ghost" data-act="testimg" data-id="${p.id}">${icon('image', 14)} آزمایش تصویر</button>` : ''}
        <button class="btn sm ghost" data-act="editprov" data-id="${p.id}">${icon('edit', 14)} ویرایش</button>
        <button class="btn sm ghost danger" data-act="delprov" data-id="${p.id}">${icon('trash', 14)}</button></div>
      <div class="mt8 small" id="pt-${p.id}"></div>
    </div>`).join('')}</div></div>`;
}

function providerForm(p) {
  const presets = AH.presets || [];
  const v = p || { kind: 'openai', image_mode: 'images_api', timeout_s: 90, headers: {} };
  const l = openLayer('modal', `
    <div class="card-h"><h3>${p ? 'ویرایش اتصال' : 'اتصال جدید به هوش مصنوعی'}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:70vh;overflow:auto">
      ${p ? '' : `<div class="lbl mb8">از یک پیش‌تنظیم شروع کنید</div><div class="flex wrap mb16" id="pf-presets">${presets.map((x) => `<button class="btn sm" data-preset="${x.id}">${esc(x.name)}</button>`).join('')}</div>`}
      <div class="form-grid">
        <div class="field"><label>نام اتصال</label><input class="inp" id="pf-name" value="${attr(v.name || '')}" placeholder="مثلاً OpenRouter کاری"></div>
        <div class="field"><label>نوع API</label><select class="inp" id="pf-kind">${Object.entries(KIND_LBL).map(([k, t]) => `<option value="${k}" ${v.kind === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="field full"><label>Base URL</label><input class="inp ltr" id="pf-base" value="${attr(v.base_url || '')}" placeholder="https://…/v1"><div class="hint" id="pf-hint">برای روترها و سرویس‌های سازگار با OpenAI، آدرس پایه را از مستندات همان سرویس وارد کنید.</div></div>
        <div class="field full"><label>کلید API</label><input class="inp ltr" id="pf-key" type="password" autocomplete="off" placeholder="${p ? (p.has_key ? 'بدون تغییر (' + attr(p.api_key_masked) + ')' : 'ندارد') : 'sk-…'}"><div class="hint">کلید فقط روی همین سیستم و در دیتابیس محلی استودیو ذخیره می‌شود.</div></div>
        <div class="field"><label>مدل متن</label><input class="inp ltr" id="pf-tm" list="pf-models" value="${attr(v.text_model || '')}" placeholder="نام مدل"></div>
        <div class="field"><label>مدل تصویر (اختیاری)</label><input class="inp ltr" id="pf-im" list="pf-models" value="${attr(v.image_model || '')}" placeholder="نام مدل تصویری"></div>
        <datalist id="pf-models"></datalist>
        <div class="field"><label>روش تولید تصویر</label><select class="inp" id="pf-imode">${Object.entries(IMG_MODE_LBL).map(([k, t]) => `<option value="${k}" ${v.image_mode === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="field"><label>مهلت پاسخ (ثانیه)</label><input class="inp" id="pf-to" type="number" value="${attr(v.timeout_s || 90)}"></div>
        <div class="field full"><label>پراکسی (اختیاری)</label><input class="inp ltr" id="pf-proxy" value="${attr(v.proxy || '')}" placeholder="http://127.0.0.1:10809"><div class="hint">اگر سرویس‌دهنده از ایران در دسترس نیست، آدرس پراکسی HTTP را بدهید. پراکسی SOCKS هم با قالب socks5h://… پشتیبانی می‌شود.</div></div>
        <div class="field full"><label>هدرهای اضافه (JSON، اختیاری)</label><textarea class="inp mono" id="pf-headers" rows="2">${esc(v.headers && Object.keys(v.headers).length ? JSON.stringify(v.headers) : '')}</textarea></div>
      </div>
      <div class="flex mt12"><button class="btn sm" id="pf-models-btn">${icon('download', 14)} دریافت فهرست مدل‌ها</button><span class="small" id="pf-msg"></span></div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="pf-save">${icon('save', 16)} ذخیره</button></div>`, { wide: true });
  const box = l.box;
  const $ = (id) => box.querySelector(id);
  box.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => {
    const x = presets.find((y) => y.id === b.dataset.preset);
    $('#pf-name').value = x.name; $('#pf-kind').value = x.kind; $('#pf-base').value = x.base_url; $('#pf-imode').value = x.image_mode;
    $('#pf-hint').textContent = x.hint || '';
    box.querySelectorAll('[data-preset]').forEach((y) => y.classList.toggle('soft', y === b));
  }));
  const body = () => {
    let headers = {};
    try { headers = $('#pf-headers').value.trim() ? JSON.parse($('#pf-headers').value) : {}; } catch (e) { throw new Error('هدرهای اضافه JSON معتبر نیست.'); }
    return { name: $('#pf-name').value.trim(), kind: $('#pf-kind').value, base_url: $('#pf-base').value.trim(), api_key: $('#pf-key').value.trim(),
      text_model: $('#pf-tm').value.trim(), image_model: $('#pf-im').value.trim(), image_mode: $('#pf-imode').value,
      timeout_s: Number($('#pf-to').value || 90), proxy: $('#pf-proxy').value.trim(), headers };
  };
  let saved = p;
  const save = async () => {
    const b = body();
    if (!b.base_url) throw new Error('Base URL را وارد کنید.');
    saved = saved ? await api(`/api/ai/providers/${saved.id}`, { method: 'PUT', body: b }) : await api('/api/ai/providers', { body: b });
    return saved;
  };
  $('#pf-models-btn').addEventListener('click', async () => {
    try {
      $('#pf-msg').innerHTML = `${icon('loader', 14, 'spin')} …`;
      const s = await save();
      const r = await api(`/api/ai/providers/${s.id}/models`, { body: {} });
      if (!r.ok) throw new Error(r.error);
      $('#pf-models').innerHTML = r.models.map((m) => `<option value="${attr(m)}">`).join('');
      $('#pf-msg').innerHTML = `<span class="chip ok">${fa(r.models.length)} مدل؛ از فهرست کشویی انتخاب کنید</span>`;
    } catch (e) { $('#pf-msg').innerHTML = `<span class="chip err">${esc(trunc(e.message, 90))}</span>`; }
  });
  $('#pf-save').addEventListener('click', async () => {
    try { await save(); await refreshBoot(); okToast('اتصال ذخیره شد.'); l.close(); AIHub.draw(); } catch (e) { errToast(e); }
  });
}

async function profilesTab() {
  const r = await api('/api/ai/profiles');
  const provs = (await api('/api/ai/providers')).providers;
  const pn = (id) => provs.find((p) => p.id === id)?.name;
  return `<div class="card-b"><div class="flex mb12"><span class="grow small muted">قالب تولید مشخص می‌کند کدام فیلدها، با چه حالتی (رفع نقص، بازنویسی یکتا، تولید از نو) و با چه دستوری تولید شوند.</span><button class="btn sm primary" data-act="newprof">${icon('plus', 14)} قالب جدید</button></div>
    <div class="grid g2">${r.profiles.map((p) => {
      const c = p.config;
      const fs = (c.fields || []).filter((f) => f.enabled);
      return `<div class="fieldbox"><div class="flex"><div class="src-logo" style="width:40px;height:40px">${icon('wand', 18)}</div><div class="grow"><b style="color:var(--z-900)">${esc(p.name)}</b><div class="xs muted">${esc(p.description || '')}</div></div></div>
        <div class="flex wrap mt12">${fs.map((f) => `<span class="tag">${esc(f.target)} · ${esc((r.modes[f.mode] || '').split(' ')[0] || f.mode)}</span>`).join('')}${c.images?.enabled ? `<span class="tag p">${icon('image', 12)} تصویر</span>` : ''}</div>
        <div class="xs muted mt8">اتصال: ${pn(c.provider_id) ? esc(pn(c.provider_id)) : '<span style="color:var(--err)">انتخاب نشده</span>'} · مدل: <span class="ltr">${esc(c.model || 'پیش‌فرض اتصال')}</span></div>
        <div class="btns mt12"><a class="btn sm soft" href="#/ai/profiles/${p.id}">${icon('edit', 14)} ویرایش و آزمایش</a><button class="btn sm ghost" data-act="dupprof" data-id="${p.id}">${icon('copy', 14)} کپی</button><button class="btn sm ghost danger" data-act="delprof" data-id="${p.id}">${icon('trash', 14)}</button></div></div>`;
    }).join('')}</div></div>`;
}

async function jobsTab() {
  const rows = await api('/api/ai/jobs');
  if (!rows.length) return emptyState('zap', 'هنوز تولیدی اجرا نشده', 'از صفحه‌ی هر بانک داده، دکمه‌ی «تولید با هوش مصنوعی» را بزنید.');
  return rows.map((r) => aiJobRow(r)).join('');
}

export function aiJobRow(r) {
  const live = ['running', 'pending'].includes(r.status);
  const pct = r.progress_total ? Math.round((r.progress_done / r.progress_total) * 100) : null;
  return `<div style="padding:14px 20px;border-bottom:1px solid var(--z-100)">
    <div class="flex wrap"><span class="src-logo" style="width:36px;height:36px;border-radius:12px">${icon('sparkles', 16)}</span>
      <div class="grow"><b style="color:var(--z-900)">${esc(r.profile?.name || 'قالب حذف‌شده')}</b><div class="xs muted">${r.dataset ? `<a href="#/datasets/${r.dataset.id}">${esc(trunc(r.dataset.title, 80))}</a>` : ''} · ${jdate(r.created_at)}</div></div>
      ${aiChip(r.status)}
      ${live ? `<button class="btn sm" data-act="jstop" data-id="${r.id}">${icon('pause', 14)} توقف</button>` : r.status !== 'completed' ? `<button class="btn sm soft" data-act="jresume" data-id="${r.id}">${icon('play', 14)} ادامه</button>` : ''}
      ${live ? '' : `<button class="btn sm icon ghost" data-act="jdel" data-id="${r.id}">${icon('trash', 14)}</button>`}</div>
    <div class="flex mt8"><div class="grow">${progress(pct, live)}</div><span class="small nowrap">${fa(r.progress_done)} از ${fa(r.progress_total)}${r.failed ? ` · <span style="color:var(--err)">${fa(r.failed)} ناموفق</span>` : ''} · ${num(r.tokens)} توکن</span></div>
    ${r.error ? `<div class="alert err mt8">${icon('alert')}<div>${esc(r.error)}</div></div>` : ''}
  </div>`;
}

// ======================================================================
// ویرایشگر قالب تولید
// ======================================================================
const PE = { p: null, schema: null, providers: [], modes: {} };

export const ProfileEditor = {
  title: 'قالب تولید',
  crumb: 'هوش مصنوعی',
  top: () => `<a class="btn ghost" href="#/ai">${icon('chevronRight', 16)} بازگشت</a><button class="btn primary" data-act="save">${icon('save', 16)} ذخیره‌ی قالب</button>`,
  async render(p) {
    await refreshBoot();
    PE.p = await api(`/api/ai/profiles/${p.id}`);
    const all = await api('/api/ai/profiles');
    PE.modes = all.modes;
    PE.providers = (await api('/api/ai/providers')).providers;
    const c = PE.p.config;
    PE.schema = schemaById(c.schema_id) || S.boot.schemas.find((s) => s.is_default) || S.boot.schemas[0];
    document.getElementById('page-title').textContent = `قالب: ${PE.p.name}`;
    const datasets = (await api('/api/datasets')).filter((d) => d.counts.done + d.counts.partial);
    return `
    <div class="grid g-side">
      <div class="stack">
        <div class="card"><div class="card-h"><h2>اتصال و مدل</h2></div><div class="card-b"><div class="form-grid">
          <div class="field"><label>نام قالب</label><input class="inp" id="pe-name" value="${attr(PE.p.name)}"></div>
          <div class="field"><label>توضیح</label><input class="inp" id="pe-desc" value="${attr(PE.p.description || '')}"></div>
          <div class="field"><label>اتصال هوش مصنوعی</label><select class="inp" id="pe-prov"><option value="">— انتخاب کنید —</option>${PE.providers.map((x) => `<option value="${x.id}" ${x.id === c.provider_id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select>
            ${PE.providers.length ? '' : `<div class="hint">ابتدا در <a href="#/ai">هوش مصنوعی ← اتصال‌ها</a> یک اتصال بسازید.</div>`}</div>
          <div class="field"><label>مدل متن</label><input class="inp ltr" id="pe-model" value="${attr(c.model || '')}" placeholder="خالی = مدل پیش‌فرض اتصال"></div>
          <div class="field"><label>خلاقیت (Temperature)</label><input class="inp" id="pe-temp" type="number" step="0.1" min="0" max="2" value="${attr(c.temperature)}"><div class="hint">۰٫۳ دقیق و یکنواخت، ۰٫۷ متعادل، ۱ خلاق‌تر</div></div>
          <div class="field"><label>بیشترین طول پاسخ (توکن)</label><input class="inp" id="pe-maxt" type="number" value="${attr(c.max_tokens)}"></div>
          <div class="field"><label>درخواست‌های هم‌زمان</label><input class="inp" id="pe-conc" type="number" min="1" max="8" value="${attr(c.concurrency)}"></div>
          <div class="field"><label class="check" style="height:42px"><input type="checkbox" id="pe-batch" ${c.batch ? 'checked' : ''}> همه‌ی فیلدها در یک درخواست (ارزان‌تر)</label><div class="hint">اگر مدل در تولید JSON چندفیلدی خطا داشت، این گزینه را خاموش کنید تا برای هر فیلد یک درخواست جدا ارسال شود.</div></div>
        </div></div></div>

        <div class="card"><div class="card-h"><h2>لحن، سئو و محدودیت‌ها</h2></div><div class="card-b"><div class="form-grid">
          <div class="field full"><label>دستور کلی (System Prompt)</label><textarea class="inp" id="pe-sys" rows="6">${esc(c.system_prompt)}</textarea></div>
          <div class="field"><label>کلیدواژه‌های سئو</label><textarea class="inp" id="pe-kw" rows="3" placeholder="مثلاً روغن موتور، تعویض روغن، روغن موتور بنزینی">${esc(c.seo_keywords || '')}</textarea></div>
          <div class="field"><label>واژه‌ها و عبارت‌های ممنوع</label><textarea class="inp" id="pe-ban" rows="3" placeholder="مثلاً نام رقبا، «ارزان‌ترین»، «بهترین»">${esc(c.banned_words || '')}</textarea><div class="hint">برای حذف قطعی، در «قواعد متن» هم قاعده بسازید.</div></div>
          <div class="field full"><label>توضیح تکمیلی (اختیاری)</label><textarea class="inp" id="pe-extra" rows="2" placeholder="مثلاً: مخاطب، صاحبان خودروهای سواری در تهران هستند.">${esc(c.extra_context || '')}</textarea></div>
        </div></div></div>

        <div class="card"><div class="card-h"><h2>فیلدهای تولید</h2><span class="sp"></span>
          <span class="small muted">ستون‌ها از اسکیمای</span><select class="inp sm" style="width:auto" id="pe-schema" data-change="schema">${S.boot.schemas.map((s) => `<option value="${s.id}" ${s.id === PE.schema.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
          <button class="btn sm soft" data-act="addf">${icon('plus', 14)} فیلد</button></div>
          <div class="card-b" id="pe-fields"></div></div>

        <div class="card"><div class="card-h"><h2>تولید تصویر</h2><span class="sp"></span><label class="check"><input type="checkbox" id="pe-img-on" ${c.images?.enabled ? 'checked' : ''}> فعال</label></div>
          <div class="card-b"><div class="alert warn mb12">${icon('alert')}<div>تصویر ساخته‌شده از روی عنوان، بسته‌بندی و برچسب واقعی محصول را دقیق بازسازی نمی‌کند. برای کالای برنددار «استفاده از تصویر استخراج‌شده به‌عنوان مرجع» را روشن بگذارید و برای کاتالوگ رسمی، تصویر واقعی را ترجیح دهید.</div></div>
          <div class="form-grid">
            <div class="field"><label>ستون مقصد</label><select class="inp" id="pe-img-target">${PE.schema.columns.filter((x) => ['image', 'images'].includes(x.input)).map((x) => `<option value="${x.key}" ${c.images?.target === x.key ? 'selected' : ''}>${esc(x.label || x.key)} (${x.key})</option>`).join('')}</select></div>
            <div class="field"><label>حالت</label><select class="inp" id="pe-img-mode">${[['fill_missing', 'فقط اگر تصویری نیست'], ['add', 'افزودن به تصاویر موجود (گالری)'], ['overwrite', 'جایگزینی کامل']].map(([k, l]) => `<option value="${k}" ${c.images?.mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <div class="field"><label>تعداد تصویر (برای گالری)</label><input class="inp" id="pe-img-n" type="number" min="1" max="6" value="${attr(c.images?.count || 1)}"></div>
            <div class="field"><label>اندازه</label><select class="inp" id="pe-img-size">${['1024x1024', '1536x1024', '1024x1536', '512x512'].map((s) => `<option ${c.images?.size === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
            <div class="field"><label>مدل تصویر</label><input class="inp ltr" id="pe-img-model" value="${attr(c.image_model || '')}" placeholder="خالی = مدل تصویر اتصال"></div>
            <div class="field"><label class="check" style="height:42px"><input type="checkbox" id="pe-img-ref" ${c.images?.use_reference ? 'checked' : ''}> استفاده از تصویر استخراج‌شده به‌عنوان مرجع</label></div>
            <div class="field full"><label>دستور تولید تصویر</label><textarea class="inp ltr" id="pe-img-prompt" rows="4">${esc(c.images?.prompt || '')}</textarea><div class="hint">متغیرها: <span class="kbd">{title}</span> <span class="kbd">{title_en}</span> <span class="kbd">{brand}</span> <span class="kbd">{category}</span> <span class="kbd">{specs}</span></div></div>
          </div></div></div>
      </div>

      <div class="stack" style="position:sticky;top:84px">
        <div class="card"><div class="card-h"><h3>آزمایش روی یک محصول</h3></div><div class="card-b">
          <div class="field"><label class="small">بانک داده</label><select class="inp sm" id="pe-ds" data-change="ds"><option value="">— انتخاب —</option>${datasets.map((d) => `<option value="${d.id}">${esc(trunc(d.title, 60))}</option>`).join('')}</select></div>
          <div class="field mt8"><label class="small">محصول</label><select class="inp sm" id="pe-item"></select></div>
          <label class="check small mt8"><input type="checkbox" id="pe-test-img"> تصویر هم تولید شود</label>
          <button class="btn primary mt12" style="width:100%" data-act="test">${icon('flask', 16)} تولید پیش‌نمایش</button>
          <div class="hint mt8">پیش‌نمایش با تنظیمات همین صفحه انجام می‌شود و چیزی ذخیره نمی‌کند.</div>
        </div></div>
        <div id="pe-result"></div>
      </div>
    </div>`;
  },
  mount() {
    // تصاویر چندستونی (images_list) هم در همین فهرست فیلدها ویرایش می‌شوند
    const c = PE.p.config;
    if ((c.images_list || []).length) {
      c.fields = [...(c.fields || []), ...c.images_list.map((x) => ({ target: x.target, enabled: x.enabled !== false, mode: x.mode, count: x.count, instruction: x.instruction || '' }))];
      c.images_list = [];
    }
    this.drawFields();
  },
  drawFields() {
    const cols = PE.schema.columns.filter((x) => x.kind !== 'auto' || !['source_url', 'source_name', 'dataset_code', 'scraped_at', 'product_key'].includes(x.generator || 'slug'));
    const isImg = (k) => ['image', 'images'].includes(cols.find((c) => c.key === k)?.input);
    const IMG_MODES = { fill_missing: 'فقط اگر تصویری نیست', add: 'افزودن به تصاویر موجود', overwrite: 'جایگزینی کامل' };
    const fs = PE.p.config.fields || [];
    document.getElementById('pe-fields').innerHTML = fs.length ? fs.map((f, i) => `
      <div class="fieldbox">
        <div class="flex wrap">
          <label class="check"><input type="checkbox" data-change="f" data-i="${i}" data-k="enabled" ${f.enabled !== false ? 'checked' : ''}></label>
          <select class="inp sm" style="width:auto;min-width:220px" data-change="f" data-i="${i}" data-k="target">${cols.map((c) => `<option value="${c.key}" ${c.key === f.target ? 'selected' : ''}>${esc(c.label || c.key)} (${c.key})</option>`).join('')}${cols.some((c) => c.key === f.target) ? '' : `<option selected value="${attr(f.target)}">${esc(f.target)} — در این اسکیما نیست</option>`}</select>
          <select class="inp sm" style="width:auto" data-change="f" data-i="${i}" data-k="mode">${Object.entries(isImg(f.target) ? IMG_MODES : PE.modes).map(([k, l]) => `<option value="${k}" ${f.mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
          ${isImg(f.target) ? `<span class="xs muted">${icon('image', 12)} تعداد تصویر</span><input class="inp sm" style="width:70px" type="number" min="1" max="6" data-input="f" data-i="${i}" data-k="count" value="${attr(f.count || 1)}">`
            : `<span class="xs muted">حداکثر نویسه</span><input class="inp sm" style="width:90px" type="number" data-input="f" data-i="${i}" data-k="max_chars" value="${attr(f.max_chars || '')}">`}
          <span class="grow"></span><button class="btn xs ghost danger" data-act="delf" data-i="${i}">${icon('trash', 13)}</button>
        </div>
        <textarea class="inp mt8" rows="2" data-input="f" data-i="${i}" data-k="instruction" placeholder="دستور تولید این فیلد">${esc(f.instruction || '')}</textarea>
      </div>`).join('') : '<div class="muted small">فیلدی تعریف نشده است.</div>';
  },
  collect() {
    const c = PE.p.config;
    const $ = (id) => document.getElementById(id);
    c.provider_id = Number($('pe-prov').value) || null;
    c.model = $('pe-model').value.trim();
    c.temperature = Number($('pe-temp').value || 0.7);
    c.max_tokens = Number($('pe-maxt').value || 3000);
    c.concurrency = Number($('pe-conc').value || 2);
    c.batch = $('pe-batch').checked;
    c.system_prompt = $('pe-sys').value;
    c.seo_keywords = $('pe-kw').value.trim();
    c.banned_words = $('pe-ban').value.trim();
    c.extra_context = $('pe-extra').value.trim();
    c.schema_id = PE.schema.id;
    c.image_model = $('pe-img-model').value.trim();
    c.images = { enabled: $('pe-img-on').checked, target: $('pe-img-target').value, mode: $('pe-img-mode').value,
      count: Number($('pe-img-n').value || 1), size: $('pe-img-size').value, use_reference: $('pe-img-ref').checked, prompt: $('pe-img-prompt').value };
    const imgKeys = new Set(PE.schema.columns.filter((x) => ['image', 'images'].includes(x.input)).map((x) => x.key));
    const all = c.fields || [];
    c.images_list = all.filter((f) => imgKeys.has(f.target)).map((f) => ({ enabled: f.enabled !== false, target: f.target, mode: ['fill_missing', 'add', 'overwrite'].includes(f.mode) ? f.mode : 'fill_missing',
      count: Number(f.count || 1), size: c.images.size, use_reference: c.images.use_reference, prompt: c.images.prompt, instruction: f.instruction || '' }));
    const cfg = { ...c, fields: all.filter((f) => !imgKeys.has(f.target)) };
    PE.p.config.fields = all;
    return { name: $('pe-name').value.trim() || PE.p.name, description: $('pe-desc').value.trim(), config: cfg };
  },
  change: {
    f: (el) => { const f = PE.p.config.fields[Number(el.dataset.i)]; f[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.value; if (el.dataset.k === 'target') ProfileEditor.drawFields(); },
    schema: (el) => { PE.schema = schemaById(Number(el.value)); ProfileEditor.drawFields(); },
    ds: async (el) => {
      const items = el.value ? await api(`/api/ai/sample-items?dataset_id=${el.value}`) : [];
      document.getElementById('pe-item').innerHTML = items.map((x) => `<option value="${x.id}">${esc(trunc(x.title, 70))}</option>`).join('');
    },
  },
  input: { f: (el) => { const f = PE.p.config.fields[Number(el.dataset.i)]; f[el.dataset.k] = el.type === 'number' ? Number(el.value) : el.value; } },
  act: {
    addf: () => { PE.p.config.fields.push({ target: PE.schema.columns[0].key, enabled: true, mode: 'fill_missing', instruction: '', max_chars: 0 }); ProfileEditor.drawFields(); },
    delf: (el) => { PE.p.config.fields.splice(Number(el.dataset.i), 1); ProfileEditor.drawFields(); },
    save: async () => { const b = ProfileEditor.collect(); PE.p = await api(`/api/ai/profiles/${PE.p.id}`, { method: 'PUT', body: b }); ProfileEditor.mount(); await refreshBoot(); okToast('قالب ذخیره شد.'); },
    test: async (el) => {
      const item = document.getElementById('pe-item').value;
      if (!item) { toast('یک بانک داده و محصول انتخاب کنید.', 'err'); return; }
      const b = ProfileEditor.collect();
      const box = document.getElementById('pe-result');
      el.disabled = true;
      box.innerHTML = `<div class="card"><div class="card-b flex">${icon('loader', 18, 'spin')} در حال تولید…</div></div>`;
      try {
        const r = await api('/api/ai/preview', { body: { config: b.config, item_id: Number(item), images: document.getElementById('pe-test-img').checked } });
        box.innerHTML = previewHtml(r);
      } catch (e) { box.innerHTML = `<div class="alert err">${icon('alert')}<div>${esc(e.message)}</div></div>`; }
      el.disabled = false;
    },
  },
};

function fmtVal(v) {
  if (v === null || v === undefined || v === '') return '<span class="muted">— خالی —</span>';
  if (Array.isArray(v) && v.length && String(v[0]).startsWith('data:image')) return `<div class="imgs">${v.map((u) => `<img src="${u}">`).join('')}</div>`;
  if (typeof v === 'string') return esc(v);
  if (typeof v === 'object' && !Array.isArray(v) && Object.values(v).every(Array.isArray)) {
    return Object.entries(v).map(([k, arr]) => `<b class="xs ltr">${esc(k)}</b><br>${arr.map((x) => '• ' + esc(x)).join('<br>')}`).join('<br>');
  }
  return `<span class="ltr">${esc(JSON.stringify(v, null, 1))}</span>`;
}

function previewHtml(r) {
  if (!r.ok) return `<div class="alert err">${icon('alert')}<div><b>تولید ناموفق بود</b>${esc(r.error)}</div></div>`;
  const keys = Object.keys(r.fields);
  return `<div class="card"><div class="card-h"><h3>پیش‌نمایش</h3><span class="sp"></span><span class="tag">${num(r.tokens)} توکن</span></div>
    <div class="card-b"><div class="small muted mb8">${esc(trunc(r.title, 90))}</div>
    ${keys.length ? keys.map((k) => `<div class="res-row" style="grid-template-columns:1fr"><div class="k">${esc(r.fields[k].label)} <small>${esc(k)}</small></div>
      <details><summary class="xs muted" style="cursor:pointer">مقدار فعلی</summary><div class="res-val small muted">${fmtVal(r.fields[k].before)}</div></details>
      <div class="res-val" style="max-height:260px">${fmtVal(r.fields[k].after)}</div></div>`).join('') : '<div class="alert info">چیزی برای تولید نبود؛ احتمالاً همه‌ی فیلدها در حالت «فقط اگر خالی است» مقدار دارند.</div>'}
    <details class="mt12"><summary class="xs muted" style="cursor:pointer">پرامپت ارسال‌شده</summary><div class="outbox small" style="max-height:260px;overflow:auto">${esc(r.prompt)}</div></details>
    </div></div>`;
}

// ======================================================================
// اجرای تولید روی بانک داده (مودال)
// ======================================================================
const KIND_FA = { scraped: 'استخراجی', manual: 'دستی', constant: 'ثابت', mapping: 'نگاشت', auto: 'خودکار', ai: 'هوش مصنوعی' };
const TXT_MODES = { fill_missing: 'فقط اگر خالی است', rewrite: 'بازنویسی یکتا', overwrite: 'تولید از نو' };
const IMG_MODES = { fill_missing: 'فقط اگر تصویری نیست', add: 'افزودن به تصاویر', overwrite: 'جایگزینی کامل' };

// پنجره‌ی تولید با هوش مصنوعی برای بانک داده: انتخاب هر ستون اسکیما (متن، اسلاگ، نگاشت، مشخصات، ابعاد، بولت‌ها، تصاویر…)
export async function openAIRun(ds, selected = []) {
  const [colsR, provsR] = await Promise.all([api(`/api/ai/columns?dataset_id=${ds.id}`), api('/api/ai/providers').catch(() => ({ providers: [] }))]);
  const cols = colsR.columns;
  const profs = S.boot.ai_profiles || [];
  const total = ds.counts.done + ds.counts.partial;
  const hasSchemaAI = cols.some((c) => c.schema_ai);
  const row = (c) => `<tr data-key="${attr(c.key)}" class="${c.capable ? '' : 'muted'}">
      <td><input type="checkbox" data-pick ${c.capable ? '' : 'disabled'} ${c.capable && c.schema_ai ? 'checked' : ''}></td>
      <td><b class="small" style="color:var(--z-900)">${esc(c.label)}</b><div class="xs muted ltr" style="text-align:right">${esc(c.key)}</div></td>
      <td class="nowrap"><span class="tag" style="font-size:11px"><span class="kind-dot k-${c.kind}"></span>${KIND_FA[c.kind] || c.kind}</span> <span class="xs muted">${esc(c.input)}</span></td>
      <td>${c.capable ? `<select class="inp sm" data-mode style="min-width:130px">${Object.entries(c.image ? IMG_MODES : TXT_MODES).map(([k, l]) => `<option value="${k}" ${c.mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`
        : '<span class="xs muted">مقدار سیستمی</span>'}</td>
      <td>${c.capable ? `<div class="flex" style="gap:6px"><input class="inp sm grow" data-instr value="${attr(c.instruction)}" style="min-width:220px">${c.image ? `<input class="inp sm" type="number" min="1" max="6" value="1" data-count title="تعداد تصویر" style="width:58px">` : ''}</div>` : ''}</td>
    </tr>`;
  const l = openLayer('modal', `
    <div class="card-h"><h3>${icon('sparkles', 18)} تولید با هوش مصنوعی</h3><span class="sub">${esc(trunc(ds.title, 60))}</span><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:72vh;overflow:auto">
      <div class="flex wrap mb12" style="gap:8px"><span class="lbl">۱. ستون‌هایی که تولید یا تکمیل شوند</span><span class="grow"></span>
        <div class="seg" id="ar-quick"><button data-q="all">همه</button><button data-q="text">متنی</button><button data-q="img">تصاویر</button>${hasSchemaAI ? '<button data-q="schema">ستون‌های AI اسکیما</button>' : ''}<button data-q="none">هیچ‌کدام</button></div>
        <button class="btn xs ghost" data-q="fill">${icon('crop', 12)} همه «فقط اگر خالی است»</button></div>
      <div class="tbl-wrap" style="border:1px solid var(--z-200);border-radius:14px;max-height:340px"><table class="tbl" id="ar-cols"><thead><tr><th></th><th>ستون</th><th>نوع مقدار</th><th>حالت</th><th>دستور تولید</th></tr></thead>
        <tbody>${cols.map(row).join('')}</tbody></table></div>
      <div class="hint mt8">هر ستونی را می‌توانید انتخاب کنید: متن‌ها، عنوان، اسلاگ و نگاشت برند/دسته، مشخصات، ابعاد، بولت‌ها، مقادیر ثابت و تصاویر. فقط مقادیر سیستمی (لینک منبع، شناسه‌ی بانک، زمان استخراج) با هوش مصنوعی ساخته نمی‌شوند. مقدارهایی که دستی ویرایش کرده‌اید دست نمی‌خورند.</div>
      <div class="form-grid mt16">
        <div class="field"><label>۲. محصولات</label><div class="seg" id="ar-scope">
          <button class="${selected.length ? '' : 'on'}" data-s="all">همه (${fa(total)})</button>
          ${selected.length ? `<button class="on" data-s="selected">انتخاب‌شده (${fa(selected.length)})</button>` : ''}
          ${ds.counts.partial ? `<button data-s="partial">فقط ناقص‌ها (${fa(ds.counts.partial)})</button>` : ''}</div></div>
        <div class="field"><label>لحن، سئو و اتصال (اختیاری)</label><select class="inp sm" id="ar-prof"><option value="">پیش‌فرض</option>${profs.map((p) => `<option value="${p.id}">قالب: ${esc(p.name)}</option>`).join('')}</select>
          <select class="inp sm mt8" id="ar-prov"><option value="">اتصال پیش‌فرض دستیار</option>${(provsR.providers || []).map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></div>
        <div class="field full"><label class="small">کلیدواژه‌های سئو (اختیاری)</label><input class="inp sm" id="ar-kw" placeholder="مثلاً روغن موتور، تعویض روغن" data-ai-format="keywords"></div>
      </div>
      <label class="check mt12"><input type="checkbox" id="ar-over"> خروجی‌های قبلی هوش مصنوعی هم دوباره تولید شوند</label>
      <div class="flex wrap mt12" style="gap:8px"><label class="check small grow"><input type="checkbox" id="ar-save"> ذخیره‌ی این انتخاب به‌عنوان قالب</label><input class="inp sm" id="ar-save-name" placeholder="نام قالب" style="max-width:240px"></div>
      <div id="ar-prev" class="mt12"></div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><span class="grow"></span>
      <button class="btn soft" id="ar-test">${icon('flask', 16)} پیش‌نمایش روی یک محصول</button>
      <button class="btn primary" id="ar-go">${icon('sparkles', 16)} شروع تولید</button></div>`, { wide: true });
  const b = l.box;
  let scope = selected.length ? 'selected' : 'all';
  b.querySelectorAll('[data-s]').forEach((x) => x.addEventListener('click', () => { scope = x.dataset.s; b.querySelectorAll('[data-s]').forEach((y) => y.classList.toggle('on', y === x)); }));
  b.querySelectorAll('[data-q]').forEach((x) => x.addEventListener('click', () => {
    const q = x.dataset.q;
    b.querySelectorAll('#ar-cols tbody tr').forEach((tr) => {
      const c = cols.find((y) => y.key === tr.dataset.key);
      const cb = tr.querySelector('[data-pick]');
      if (!c.capable) return;
      if (q === 'fill') { const m = tr.querySelector('[data-mode]'); if (m) m.value = 'fill_missing'; return; }
      cb.checked = q === 'all' || (q === 'text' && !c.image) || (q === 'img' && c.image) || (q === 'schema' && c.schema_ai);
    });
  }));
  const selections = () => [...b.querySelectorAll('#ar-cols tbody tr')].filter((tr) => tr.querySelector('[data-pick]')?.checked).map((tr) => ({
    key: tr.dataset.key, mode: tr.querySelector('[data-mode]').value, instruction: tr.querySelector('[data-instr]').value, count: Number(tr.querySelector('[data-count]')?.value || 1),
  }));
  const body = () => ({ dataset_id: ds.id, columns: selections(), profile_id: Number(b.querySelector('#ar-prof').value) || null,
    provider_id: Number(b.querySelector('#ar-prov').value) || null, seo_keywords: b.querySelector('#ar-kw').value.trim() });
  b.querySelector('#ar-test').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const bd = body();
    if (!bd.columns.length) { toast('دست‌کم یک ستون انتخاب کنید.', 'err'); return; }
    let item = selected[0];
    if (!item) { const r = await api(`/api/datasets/${ds.id}/items?size=1&status=done,partial`); item = r.items[0]?.id; }
    if (!item) { toast('محصولی برای پیش‌نمایش نیست.', 'err'); return; }
    btn.disabled = true;
    const box = b.querySelector('#ar-prev');
    box.innerHTML = `<div class="flex small muted">${icon('loader', 16, 'spin')} در حال تولید پیش‌نمایش…</div>`;
    try {
      const r = await api('/api/ai/preview', { body: { ...bd, item_id: item, images: bd.columns.some((c) => cols.find((x) => x.key === c.key)?.image) } });
      box.innerHTML = previewHtml(r);
      box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (e) { box.innerHTML = `<div class="alert err">${icon('alert')}<div>${esc(e.message)}</div></div>`; }
    btn.disabled = false;
  });
  b.querySelector('#ar-go').addEventListener('click', async () => {
    const bd = body();
    if (!bd.columns.length) { toast('دست‌کم یک ستون انتخاب کنید.', 'err'); return; }
    try {
      await api('/api/ai/jobs', { body: { ...bd, scope, item_ids: scope === 'selected' ? selected : [], overwrite_ai: b.querySelector('#ar-over').checked,
        images: true, save_as: b.querySelector('#ar-save').checked ? (b.querySelector('#ar-save-name').value.trim() || `تولید ${fa(bd.columns.length)} ستون`) : '' } });
      if (b.querySelector('#ar-save').checked) await refreshBoot();
      okToast(`تولید ${fa(bd.columns.length)} ستون با هوش مصنوعی آغاز شد.`);
      l.close();
    } catch (e) { errToast(e); }
  });
}

// ======================================================================
// قواعد متن
// ======================================================================
const RL = { data: null };
const TARGET_LBL = { '*': 'همه‌ی متن‌ها', title: 'عنوان', title_en: 'عنوان انگلیسی', brand: 'برند', brand_en: 'برند (انگلیسی)', category: 'دسته‌بندی', short_description: 'توضیح کوتاه', long_description: 'توضیح بلند', specifications: 'مشخصات', featured_image: 'تصویر شاخص', gallery: 'تصاویر گالری', breadcrumb: 'مسیر دسته' };

export const Rules = {
  title: 'قواعد متن و فیلتر',
  crumb: 'حذف یا افزودن کلمات و عبارت‌ها در داده‌ی استخراج‌شده و خروجی هوش مصنوعی',
  top: () => `<button class="btn soft" data-act="airules">${icon('sparkles')} ساخت قاعده با AI</button><button class="btn primary" data-act="new">${icon('plus')} قاعده‌ی جدید</button>`,
  async render() {
    RL.data = await api('/api/rules');
    return `
      <div class="alert p mb16">${icon('filter')}<div><b>اعمال خودکار و غیرمخرب</b>قاعده‌های فعال هنگام نمایش، پیش‌نمایش، تولید هوش مصنوعی و ساخت خروجی روی داده اعمال می‌شوند؛ داده‌ی اصلی استخراج‌شده تغییر نمی‌کند و با خاموش کردن یک قاعده، اثرش از همه‌جا برداشته می‌شود. قاعده‌ها به‌ترتیب فهرست اجرا می‌شوند.</div></div>
      <div class="card"><div id="rl-list"></div></div>
      <div class="card mt16"><div class="card-h"><h3>آزمایش قاعده‌های فعال</h3></div><div class="card-b"><div class="form-grid">
        <div class="field"><label>بخش</label><select class="inp" id="rt-target">${Object.entries(TARGET_LBL).filter(([k]) => k !== '*').map(([k, l]) => `<option value="${k}" ${k === 'long_description' ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="field"><label>منبع</label><select class="inp" id="rt-src"><option value="">همه</option>${S.boot.sources.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></div>
        <div class="field"><label>متن نمونه</label><textarea class="inp" id="rt-in" rows="4" data-input="sandbox">خرید روغن موتور از دیجی‌کالا با ارسال رایگان\nاین روغن برای موتورهای بنزینی مناسب است.</textarea></div>
        <div class="field"><label>خروجی</label><div class="outbox" id="rt-out"></div></div>
      </div></div></div>`;
  },
  async mount() { this.list(); this.input.sandbox(); },
  list() {
    const rows = RL.data.rules;
    document.getElementById('rl-list').innerHTML = rows.length ? `<table class="tbl"><thead><tr><th style="width:60px">فعال</th><th>نام</th><th>بخش</th><th>عملیات</th><th>عبارت / مقدار</th><th>منبع</th><th></th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td><label class="check"><input type="checkbox" data-change="toggle" data-id="${r.id}" ${r.enabled ? 'checked' : ''}></label></td>
        <td><b style="color:var(--z-900)">${esc(r.name)}</b></td><td><span class="tag">${esc(TARGET_LBL[r.target] || r.target)}</span></td>
        <td class="small">${esc(RL.data.actions[r.action] || r.action)}</td>
        <td class="small" style="max-width:340px">${r.find ? `<span class="kbd" style="direction:rtl">${esc(trunc(r.find, 80))}</span>` : ''}${r.value ? ` ← <span class="kbd" style="direction:rtl">${esc(trunc(r.value, 60))}</span>` : ''}</td>
        <td class="small">${r.source_id ? esc(r.source_name || '') : 'همه'}</td>
        <td class="nowrap"><button class="btn xs ghost" data-act="edit" data-id="${r.id}">${icon('edit', 13)}</button><button class="btn xs ghost danger" data-act="del" data-id="${r.id}">${icon('trash', 13)}</button></td></tr>`).join('')}</tbody></table>`
      : emptyState('filter', 'قاعده‌ای ندارید', 'مثلاً نام فروشگاه‌ها را از متن‌ها حذف کنید یا یک جمله‌ی ثابت به انتهای توضیح کوتاه اضافه کنید.');
  },
  async reload() { RL.data = await api('/api/rules'); this.list(); this.input.sandbox(); },
  change: {
    toggle: async (el) => { await api(`/api/rules/${el.dataset.id}`, { method: 'PUT', body: { enabled: el.checked } }); await Rules.reload(); },
  },
  input: {
    sandbox: debounce3(async () => {
      const el = document.getElementById('rt-in');
      if (!el) return;
      const r = await api('/api/rules/test', { body: { text: el.value, target: document.getElementById('rt-target').value, source_id: document.getElementById('rt-src').value || null } });
      document.getElementById('rt-out').textContent = typeof r.output === 'string' ? r.output : JSON.stringify(r.output);
    }),
  },
  act: {
    new: () => ruleForm(null),
    airules: () => aiRules(),
    edit: (el) => ruleForm(RL.data.rules.find((r) => r.id === Number(el.dataset.id))),
    del: async (el) => { if (!(await confirmDlg('حذف قاعده', 'این قاعده حذف شود؟', 'حذف', true))) return; await api(`/api/rules/${el.dataset.id}`, { method: 'DELETE' }); Rules.reload(); },
  },
};

function aiRules() {
  const l = openLayer('modal', `<div class="card-h"><h3>${icon('sparkles', 18)} ساخت قاعده با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:70vh;overflow:auto">
      <div class="field"><label>چه چیزی باید حذف، جایگزین یا اضافه شود؟</label>
        <textarea class="inp" rows="3" id="ar-d" placeholder="مثلاً: نام فروشگاه‌ها (دیجی‌کالا، اسنپ‌شاپ) و عبارت‌های تبلیغاتی مثل «ارسال رایگان» و «تخفیف ویژه» از همه‌ی متن‌ها حذف شود و کدهای کالا از مشخصات پاک شوند"></textarea></div>
      <button class="btn primary mt12" id="ar-go">${icon('sparkles', 16)} پیشنهاد قاعده‌ها</button>
      <div id="ar-res" class="mt12"></div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="ar-ok" disabled>${icon('check', 16)} افزودن قاعده‌های انتخاب‌شده</button></div>`, { wide: true });
  const b = l.box;
  let rules = [];
  b.querySelector('#ar-go').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const d = b.querySelector('#ar-d').value.trim();
    if (!d) { toast('توضیح را بنویسید.', 'err'); return; }
    busy(btn, true);
    try {
      rules = (await assist('rules', { description: d })).rules;
      b.querySelector('#ar-res').innerHTML = rules.length ? `<table class="tbl"><thead><tr><th></th><th>نام</th><th>عملیات</th><th>بخش</th><th>عبارت / مقدار</th></tr></thead><tbody>
        ${rules.map((r, i) => `<tr><td><input type="checkbox" data-ar="${i}" checked></td><td><b>${esc(r.name)}</b></td><td class="small">${esc(RL.data.actions[r.action] || r.action)}</td>
        <td><span class="tag">${esc(TARGET_LBL[r.target] || r.target)}</span></td><td class="small">${r.find ? `<span class="kbd" style="direction:rtl">${esc(trunc(r.find, 90))}</span>` : ''}${r.value ? ` ← <span class="kbd" style="direction:rtl">${esc(trunc(r.value, 60))}</span>` : ''}</td></tr>`).join('')}</tbody></table>
        <div class="hint mt8">قاعده‌ها فعال افزوده می‌شوند؛ بعداً می‌توانید ویرایش یا خاموششان کنید.</div>` : '<div class="muted small">قاعده‌ای پیشنهاد نشد.</div>';
      b.querySelector('#ar-ok').disabled = !rules.length;
    } catch (e) { noProviderHint(e); } finally { busy(btn, false); }
  });
  b.querySelector('#ar-ok').addEventListener('click', async () => {
    const pick = rules.filter((r, i) => b.querySelector(`[data-ar="${i}"]`)?.checked);
    for (const r of pick) await api('/api/rules', { body: { ...r, enabled: 1 } });
    okToast(`${fa(pick.length)} قاعده افزوده شد.`);
    l.close();
    Rules.reload();
  });
}

function debounce3(fn) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), 300); }; }

function ruleForm(r) {
  const v = r || { name: '', target: '*', action: 'remove', find: '', value: '', flags: { split: '|' }, enabled: 1, source_id: null };
  const l = openLayer('modal', `
    <div class="card-h"><h3>${r ? 'ویرایش قاعده' : 'قاعده‌ی جدید'}</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b"><div class="form-grid">
      <div class="field full"><label>نام</label><input class="inp" id="rf-name" value="${attr(v.name)}" placeholder="مثلاً حذف نام فروشگاه‌ها"></div>
      <div class="field"><label>عملیات</label><select class="inp" id="rf-action">${Object.entries(RL.data.actions).map(([k, t]) => `<option value="${k}" ${v.action === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="field"><label>بخش</label><select class="inp" id="rf-target">${Object.entries(TARGET_LBL).map(([k, t]) => `<option value="${k}" ${v.target === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="field full" id="rf-find-box"><label>عبارت</label><input class="inp" id="rf-find" value="${attr(v.find || '')}"><div class="hint" id="rf-find-hint">چند عبارت را با <span class="kbd">|</span> از هم جدا کنید.</div></div>
      <div class="field full" id="rf-value-box"><label id="rf-value-lbl">مقدار</label><input class="inp" id="rf-value" value="${attr(v.value || '')}"><div class="hint">برای رفتن به خط بعد از <span class="kbd">\\n</span> استفاده کنید.</div></div>
      <div class="field"><label>منبع</label><select class="inp" id="rf-src"><option value="">همه‌ی منابع</option>${S.boot.sources.map((s) => `<option value="${s.id}" ${v.source_id === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
      <div class="field"><label>گزینه‌ها</label><div class="flex wrap" style="height:42px"><label class="check small"><input type="checkbox" id="rf-ww" ${v.flags?.whole_word ? 'checked' : ''}> فقط کلمه‌ی کامل</label><label class="check small"><input type="checkbox" id="rf-cs" ${v.flags?.case_sensitive ? 'checked' : ''}> حساس به حروف بزرگ/کوچک</label></div></div>
      <div class="field"><label>متن آزمایشی</label><textarea class="inp" id="rf-test" rows="3">خرید روغن موتور از دیجی‌کالا با ارسال رایگان</textarea></div>
      <div class="field"><label>نتیجه</label><div class="outbox" id="rf-out"></div></div>
    </div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="rf-save">${icon('save', 16)} ذخیره</button></div>`, { wide: true });
  const $ = (id) => l.box.querySelector(id);
  const body = () => ({ name: $('#rf-name').value.trim() || RL.data.actions[$('#rf-action').value], action: $('#rf-action').value, target: $('#rf-target').value,
    find: $('#rf-find').value, value: $('#rf-value').value, source_id: Number($('#rf-src').value) || null,
    flags: { split: $('#rf-action').value === 'regex' ? '' : '|', whole_word: $('#rf-ww').checked, case_sensitive: $('#rf-cs').checked }, enabled: v.enabled ?? 1 });
  const sync = debounce3(async () => {
    const a = $('#rf-action').value;
    $('#rf-value-box').style.display = ['replace', 'regex', 'prepend', 'append'].includes(a) ? '' : 'none';
    $('#rf-find-box').style.display = ['prepend', 'append'].includes(a) ? 'none' : '';
    $('#rf-value-lbl').textContent = a === 'replace' || a === 'regex' ? 'جایگزین با' : 'متنی که اضافه شود';
    $('#rf-find-hint').innerHTML = a === 'regex' ? 'الگوی Regex پایتون؛ مثلاً <span class="kbd">\\s*کد\\s*\\d+</span>' : 'چند عبارت را با <span class="kbd">|</span> از هم جدا کنید.';
    if ((a === 'prepend' || a === 'append') && $('#rf-target').value === '*') $('#rf-target').value = 'short_description';
    const b = body();
    const tgt = b.target === '*' ? 'long_description' : b.target;
    let text = $('#rf-test').value;
    let input = text;
    if (a === 'drop_spec') input = [{ group: '', name: 'کد کالا', value: '123' }, { group: '', name: 'حجم', value: '4 لیتر' }];
    if (a === 'drop_image') input = ['https://cdn.example.com/banner-sale.jpg', 'https://cdn.example.com/product-1.jpg'];
    const r = await api('/api/rules/test', { body: { text: input, rule: b, target: a === 'drop_spec' ? 'specifications' : a === 'drop_image' ? 'gallery' : tgt } });
    $('#rf-out').textContent = typeof r.output === 'string' ? r.output : JSON.stringify(r.output, null, 1);
  });
  l.box.querySelectorAll('input,select,textarea').forEach((e) => e.addEventListener('input', sync));
  l.box.querySelectorAll('select,input[type=checkbox]').forEach((e) => e.addEventListener('change', sync));
  sync();
  $('#rf-save').addEventListener('click', async () => {
    try {
      if (r) await api(`/api/rules/${r.id}`, { method: 'PUT', body: body() }); else await api('/api/rules', { body: body() });
      okToast('قاعده ذخیره شد.'); l.close(); Rules.reload();
    } catch (e) { errToast(e); }
  });
}

// ======================================================================
// صف و زمان‌بندی
// ======================================================================
const Q_STATUS = { queued: ['idle', 'در انتظار'], running: ['run', 'در حال استخراج'], ai_running: ['run', 'در حال تولید AI'], done: ['ok', 'تمام شد'], failed: ['err', 'ناموفق'], skipped: ['idle', 'رد شد'], cancelled: ['idle', 'لغو شد'] };
const qChip = (s, extra = '') => { const [c, t] = Q_STATUS[s] || ['idle', s]; return `<span class="chip ${c}"><span class="dot"></span>${t}${extra}</span>`; };

export function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const Queue = {
  title: 'صف و زمان‌بندی',
  crumb: 'اجرای ترتیبی کارهای استخراج، زمان شروع و تکرار دوره‌ای',
  top: () => `<a class="btn soft" href="#/new/ai">${icon('sparkles')} تولید AI در صف</a><a class="btn primary" href="#/new">${icon('plus')} افزودن به صف</a>`,
  async render() {
    return `<div id="q-body"></div>`;
  },
  async mount() { await this.draw(); every(2500, () => this.draw(true)); },
  async draw(silent) {
    const r = await api('/api/queue');
    const el = document.getElementById('q-body');
    if (!el) return;
    const sig = JSON.stringify(r.jobs.map((j) => [j.id, j.status, j.position, j.dataset?.progress?.collected, j.ai_job?.progress_done, j.scheduled_at])) + r.enabled;
    if (silent && el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    const active = r.jobs.filter((j) => ['running', 'ai_running'].includes(j.status));
    const queued = r.jobs.filter((j) => j.status === 'queued');
    const hist = r.jobs.filter((j) => !['running', 'ai_running', 'queued'].includes(j.status));
    el.innerHTML = `
      <div class="card"><div class="card-b flex wrap">
        <div class="src-logo">${icon('layers', 20)}</div>
        <div class="grow"><b style="font-size:15px;color:var(--z-900)">صف ${r.enabled ? 'روشن است' : 'خاموش است'}</b>
          <div class="small muted">${r.enabled ? 'کارها به‌ترتیب و یکی‌یکی اجرا می‌شوند؛ هر کار پس از پایان کار قبلی و رسیدن زمان شروعش آغاز می‌شود.' : 'تا روشن کردن صف، هیچ کاری خودکار شروع نمی‌شود.'} صف فقط وقتی کار می‌کند که استودیو باز باشد.</div></div>
        <span class="kpi-line"><span>در انتظار <b>${fa(queued.length)}</b></span><span>در حال اجرا <b>${fa(active.length)}</b></span></span>
        <button class="btn ${r.enabled ? '' : 'primary'}" data-act="toggle" data-v="${r.enabled ? 0 : 1}">${icon(r.enabled ? 'pause' : 'play', 16)} ${r.enabled ? 'خاموش کردن صف' : 'روشن کردن صف'}</button>
      </div></div>
      ${active.map((j) => `<div class="card mt16" style="border-color:var(--primary-200)">${jobRow(j, 'active')}</div>`).join('')}
      <div class="card mt16"><div class="card-h"><h2>نوبت‌های بعدی</h2><span class="sub">${fa(queued.length)} کار</span></div>
        ${queued.length ? queued.map((j, i) => jobRow(j, 'queued', i + 1, queued.length)).join('') : `<div class="card-b">${emptyState('layers', 'صف خالی است', 'در «استخراج جدید» گزینه‌ی «افزودن به صف» را بزنید.', `<a class="btn soft" href="#/new">${icon('plus', 16)} افزودن کار</a>`)}</div>`}</div>
      ${hist.length ? `<div class="card mt16"><div class="card-h"><h2>کارهای انجام‌شده</h2></div>${hist.slice(0, 30).map((j) => jobRow(j, 'hist')).join('')}</div>` : ''}`;
  },
  act: {
    toggle: async (el) => { await api('/api/queue/toggle', { body: { enabled: el.dataset.v === '1' } }); Queue.draw(); },
    qa: async (el) => { await api(`/api/queue/${el.dataset.id}/${el.dataset.a}`, { body: {} }); Queue.draw(); },
    qdel: async (el) => { if (!(await confirmDlg('حذف از صف', 'این کار از صف حذف شود؟', 'حذف', true))) return; await api(`/api/queue/${el.dataset.id}`, { method: 'DELETE' }); Queue.draw(); },
    qskip: async (el) => { if (!(await confirmDlg('رد کردن کار', 'اجرای این کار متوقف و کار بعدی صف آغاز می‌شود. بانک داده‌ی آن باقی می‌ماند و بعداً می‌توانید ادامه‌اش دهید.', 'رد کردن'))) return; await api(`/api/queue/${el.dataset.id}/skip`, { body: {} }); Queue.draw(); },
    qedit: async (el) => editJob(Number(el.dataset.id)),
  },
};

function whenText(j) {
  const parts = [];
  if (j.scheduled_at) {
    const future = new Date(j.scheduled_at) > new Date();
    parts.push(`${icon('clock', 13)} ${future ? 'شروع در' : 'زمان شروع'} ${jdate(j.scheduled_at)}`);
  }
  if (j.repeat_hours) parts.push(`${icon('refresh', 13)} تکرار هر ${fa(j.repeat_hours)} ساعت`);
  return parts.join(' · ');
}

function jobRow(j, mode, n, total) {
  const d = j.dataset;
  const live = mode === 'active';
  const pct = j.status === 'ai_running' && j.ai_job ? (j.ai_job.progress_total ? Math.round(j.ai_job.progress_done / j.ai_job.progress_total * 100) : null) : d?.progress?.pct;
  return `<div style="padding:14px 20px;border-bottom:1px solid var(--z-100)">
    <div class="flex wrap">
      ${mode === 'queued' ? `<span class="n" style="width:30px;height:30px;border-radius:10px;background:var(--z-100);display:grid;place-items:center;font-weight:800;color:var(--z-600)">${fa(n)}</span>` : `<div class="src-logo" style="width:36px;height:36px;font-size:14px">${esc((j.source?.name || '?').slice(0, 1))}</div>`}
      <div class="grow" style="min-width:240px">
        <b style="color:var(--z-900)">${esc(j.title || (j.source?.name + ' · ' + (d?.category_label || decodeURIComponentSafe2(j.category_url).split('/').filter(Boolean).pop())))}</b>
        <div class="xs muted ltr ellipsis" style="text-align:right;max-width:520px">${esc(decodeURIComponentSafe2(j.category_url))}</div>
        <div class="flex wrap xs mt8">
          ${j.options?.ai_generate ? `<span class="tag p">${icon('sparkles', 12)} تولید با AI: ${esc(j.options.ai_generate.product_type || '')}</span>` : `<span class="tag">${esc(j.source?.name || '')}</span>`}
          <span class="tag">${j.item_limit ? fa(j.item_limit) + ' محصول' : 'همه‌ی محصولات'}</span>
          <span class="tag">${icon('columns', 12)} ${esc(j.schema?.name || 'اسکیمای پیش‌فرض')}</span>
          ${j.ai_profile ? `<span class="tag p">${icon('sparkles', 12)} ${esc(j.ai_profile.name)}</span>` : ''}
          ${whenText(j) ? `<span class="muted">${whenText(j)}</span>` : ''}
        </div>
      </div>
      ${qChip(j.status)}
      ${mode === 'queued' ? `<div class="btns" style="gap:4px">
          <button class="btn xs ghost" data-act="qa" data-a="up" data-id="${j.id}" ${n === 1 ? 'disabled' : ''} title="بالاتر">${icon('arrowUp', 14)}</button>
          <button class="btn xs ghost" data-act="qa" data-a="down" data-id="${j.id}" ${n === total ? 'disabled' : ''} title="پایین‌تر">${icon('arrowDown', 14)}</button>
          <button class="btn xs soft" data-act="qa" data-a="run-now" data-id="${j.id}" title="اول صف و بدون انتظار برای زمان شروع">${icon('play', 13)} اول صف</button>
          <button class="btn xs ghost" data-act="qedit" data-id="${j.id}">${icon('edit', 14)}</button>
          <button class="btn xs ghost danger" data-act="qdel" data-id="${j.id}">${icon('trash', 14)}</button></div>` : ''}
      ${live ? `<a class="btn sm" href="#/datasets/${j.dataset_id}">${icon('eye', 14)} مشاهده</a><button class="btn sm danger" data-act="qskip" data-id="${j.id}">${icon('chevronLeft', 14)} رد شدن</button>` : ''}
      ${mode === 'hist' ? `${j.dataset_id ? `<a class="btn sm ghost" href="#/datasets/${j.dataset_id}">${icon('database', 14)} بانک داده</a>` : ''}<button class="btn sm ghost" data-act="qa" data-a="requeue" data-id="${j.id}">${icon('refresh', 14)} دوباره در صف</button><button class="btn sm icon ghost" data-act="qdel" data-id="${j.id}">${icon('trash', 14)}</button>` : ''}
    </div>
    ${live ? `<div class="flex mt12"><div class="grow">${progress(pct, true)}</div><span class="small nowrap">${j.status === 'ai_running' ? `تولید AI: ${fa(j.ai_job?.progress_done || 0)} از ${fa(j.ai_job?.progress_total || 0)}` : `${num(d?.progress?.collected || 0)}${d?.progress?.target ? ' از ' + num(d.progress.target) : ''} محصول`}</span></div>
      <div class="xs muted mt8">${esc(j.status === 'ai_running' ? (j.ai_job?.step || '') : (d?.step || ''))}${d?.status === 'waiting' ? ` · <a href="#/datasets/${d.id}" style="color:var(--warn)">نیاز به تصمیم شما</a>` : ''}${d?.status === 'paused' ? ` · <span style="color:var(--warn)">بانک داده متوقف است؛ برای ادامه‌ی صف آن را ادامه دهید یا «رد شدن» را بزنید.</span>` : ''}</div>` : ''}
    ${mode === 'hist' && d ? `<div class="xs muted mt8">${esc(d.code)} · ${num(d.counts.done + d.counts.partial)} محصول · ${jdate(j.finished_at)}${j.error ? ` · <span style="color:var(--err)">${esc(j.error)}</span>` : ''}</div>` : ''}
  </div>`;
}

function decodeURIComponentSafe2(u) { try { return decodeURI(u); } catch (e) { return u; } }

async function editJob(id) {
  const r = await api('/api/queue');
  const j = r.jobs.find((x) => x.id === id);
  const l = openLayer('modal', `
    <div class="card-h"><h3>ویرایش کار صف</h3></div>
    <div class="card-b"><div class="form-grid">
      <div class="field full"><label>عنوان</label><input class="inp" id="qe-title" value="${attr(j.title || '')}"></div>
      <div class="field full"><label>لینک دسته‌بندی</label><input class="inp ltr" id="qe-url" value="${attr(j.category_url)}"></div>
      <div class="field"><label>تعداد محصول</label><input class="inp" id="qe-limit" type="number" value="${attr(j.item_limit || '')}" placeholder="همه"></div>
      <div class="field"><label>اسکیما</label><select class="inp" id="qe-schema">${S.boot.schemas.map((s) => `<option value="${s.id}" ${s.id === j.schema_id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
      <div class="field"><label>زمان شروع</label><input class="inp" id="qe-at" type="datetime-local" value="${toLocalInput(j.scheduled_at)}"><div class="hint">خالی = به‌محض رسیدن نوبت</div></div>
      <div class="field"><label>تکرار هر (ساعت)</label><input class="inp" id="qe-rep" type="number" min="0" step="0.5" value="${attr(j.repeat_hours || '')}" placeholder="بدون تکرار"></div>
      <div class="field full"><label>تولید هوش مصنوعی پس از استخراج</label><select class="inp" id="qe-ai"><option value="">ندارد</option>${(S.boot.ai_profiles || []).map((p) => `<option value="${p.id}" ${p.id === j.ai_profile_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
    </div></div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" id="qe-save">${icon('save', 16)} ذخیره</button></div>`);
  const $ = (s) => l.box.querySelector(s);
  $('#qe-save').addEventListener('click', async () => {
    try {
      const at = $('#qe-at').value;
      await api(`/api/queue/${id}`, { method: 'PUT', body: { title: $('#qe-title').value, category_url: $('#qe-url').value.trim(), limit: $('#qe-limit').value,
        schema_id: Number($('#qe-schema').value), scheduled_at: at ? new Date(at).toISOString() : '', repeat_hours: Number($('#qe-rep').value || 0),
        ai_profile_id: Number($('#qe-ai').value) || null } });
      okToast('ذخیره شد.'); l.close(); Queue.draw();
    } catch (e) { errToast(e); }
  });
}
