import {
  S, api, icon, esc, attr, fa, num, jdate, jtime, ago, chip, isLive, progress, toast, okToast, errToast,
  openLayer, confirmDlg, promptDlg, vals, sourceLogo, emptyState, every, go, srcById, schemaById, trunc, refreshBoot, fileUrl,
} from './core.js';
import { openAIRun, aiJobRow } from './pages_ai.js';
import { assist, busy, noProviderHint } from './ai_assist.js';

export const imgSrc = (u) => (/^(https?:|data:)/.test(String(u)) ? String(u) : fileUrl(String(u).replace(/^file:\/\//, '')) + '&any=1');

// ======================================================================
// تصمیم در خطا (مشترک)
// ======================================================================
export async function resolveIncident(id, action, applyAll) {
  await api(`/api/incidents/${id}/resolve`, { body: { action, apply_all: !!applyAll } });
  okToast('تصمیم ثبت شد؛ اجرا ادامه پیدا می‌کند.');
}

export function incidentCard(inc, opts = {}) {
  const options = inc.options || [];
  return `
  <div class="incident" data-incident="${inc.id}">
    <div class="head">
      <div class="ib">${icon(inc.kind === 'network' ? 'wifiOff' : 'alert', 22)}</div>
      <div class="grow">
        <div class="flex wrap"><h3>${esc(inc.title)}</h3><span class="chip wait"><span class="dot"></span>نیازمند تصمیم</span>
        ${opts.dataset ? `<a class="small" href="#/datasets/${inc.dataset_id}">${esc(trunc(inc.dataset_title || '', 70))}</a>` : ''}</div>
        <div class="mt8">${esc(inc.message)}</div>
        ${inc.url ? `<div class="pathbox mt8">${esc(decodeURIComponentSafe(inc.url))}</div>` : ''}
        ${inc.detail ? `<details class="mt8"><summary class="small muted" style="cursor:pointer">جزئیات فنی</summary><pre class="pathbox mt8" style="white-space:pre-wrap;max-height:160px;overflow:auto">${esc(inc.detail)}</pre></details>` : ''}
      </div>
    </div>
    <div class="choices">
      ${options.map((o) => `<button class="choice" data-act="resolve" data-id="${inc.id}" data-action="${o.action}"><b>${esc(o.label)}</b><span>${esc(o.hint)}</span></button>`).join('')}
    </div>
    <label class="check mt12 small"><input type="checkbox" data-applyall> همین تصمیم برای خطاهای مشابه در ادامه‌ی این اجرا خودکار اعمال شود</label>
  </div>`;
}

export function decodeURIComponentSafe(u) { try { return decodeURI(u); } catch (e) { return u; } }

// ======================================================================
// پیشخوان
// ======================================================================
export const Dashboard = {
  title: 'پیشخوان',
  crumb: 'نمای کلی استودیو',
  top: () => `<a class="btn primary" href="#/new">${icon('plus')} استخراج جدید</a>`,
  async render() {
    const s = await api('/api/summary');
    S.summary = s;
    const c = s.counts;
    const stat = (ic, cls, v, t) => `<div class="card stat"><div class="bub ${cls}">${icon(ic, 22)}</div><div><b>${num(v)}</b><span>${t}</span></div></div>`;
    return `
      <div class="grid g4">
        ${stat('database', '', c.datasets, 'بانک داده')}
        ${stat('box', 'green', c.products, 'محصول استخراج‌شده')}
        ${stat('zap', 'amber', c.running, 'اجرای فعال')}
        ${stat('fileSheet', 'zinc', c.exports, 'خروجی ساخته‌شده')}
      </div>
      <div id="dash-inc" class="stack mt16">${s.incidents.map((i) => incidentCard(i, { dataset: true })).join('')}</div>
      <div class="grid g-side mt16">
        <div class="card">
          <div class="card-h"><h2>بانک‌های داده‌ی اخیر</h2><span class="sp"></span><a class="btn sm ghost" href="#/datasets">همه‌ی بانک‌ها ${icon('chevronLeft', 16)}</a></div>
          <div id="dash-active">${activeList(s.active)}</div>
        </div>
        <div class="stack">
          <a class="card" href="#/queue" style="display:block;text-decoration:none;color:inherit">
            <div class="card-b flex"><div class="stat" style="padding:0"><div class="bub ${s.queue.active ? '' : 'zinc'}">${icon('layers', 22)}</div></div>
              <div class="grow"><b style="color:var(--z-900)">صف استخراج ${s.queue.enabled ? '' : '(خاموش)'}</b>
              <div class="small muted">${s.queue.active ? 'در حال اجرا: ' + esc(s.queue.active.title || 'کار شماره‌ی ' + fa(s.queue.active.id)) : 'کاری در حال اجرا نیست'} · ${fa(s.queue.queued)} کار در انتظار</div></div>${icon('chevronLeft', 18)}</div>
          </a>
          <div class="card">
            <div class="card-h"><h3>شروع سریع</h3></div>
            <div class="card-b">
              <ol class="small" style="margin:0;padding-inline-start:18px;line-height:2.2">
                <li>در <a href="#/sources">منابع</a> هر منبع را با «آزمایش زنده» روی سیستم خودتان کالیبره کنید.</li>
                <li>از <a href="#/new">استخراج جدید</a> لینک صفحه‌ی دسته‌بندی و تعداد را بدهید.</li>
                <li>در بانک داده، فیلدهای دستی (بایدها/نبایدها و توضیحات کسب‌وکار) را تکمیل کنید.</li>
                <li>با <a href="#/exports">خروجی‌ساز</a> فایل Excel/CSV و پوشه‌ی تصاویر را بسازید.</li>
              </ol>
            </div>
          </div>
          <div class="card">
            <div class="card-h"><h3>خروجی‌های اخیر</h3></div>
            <div class="card-b">${s.recent_exports.length ? s.recent_exports.map((e) => `
              <div class="dl-row"><span>${icon('fileSheet', 18)}</span><div class="grow"><div class="ellipsis ltr small"><b>${esc(e.name)}</b></div><div class="xs muted">${jdate(e.created_at)}</div></div>${chip(e.status)}</div>`).join('') : '<div class="muted small">هنوز خروجی‌ای ساخته نشده است.</div>'}</div>
          </div>
        </div>
      </div>`;
  },
  mount() {
    every(2500, async () => {
      const s = await api('/api/summary').catch(() => null);
      if (!s) return;
      const a = document.getElementById('dash-active');
      if (a) a.innerHTML = activeList(s.active);
      const ids = s.incidents.map((i) => i.id).join(',');
      const box = document.getElementById('dash-inc');
      if (box && box.dataset.ids !== ids) { box.dataset.ids = ids; box.innerHTML = s.incidents.map((i) => incidentCard(i, { dataset: true })).join(''); }
    });
  },
  act: {
    ctl: async (el) => { await api(`/api/datasets/${el.dataset.id}/do/${el.dataset.do}`, { body: {} }); },
  },
};

function activeList(list) {
  if (!list.length) return emptyState('database', 'هنوز اجرایی ثبت نشده', 'برای شروع، لینک یک صفحه‌ی دسته‌بندی بدهید.', `<a class="btn primary" href="#/new">${icon('plus')} استخراج جدید</a>`);
  return `<div>${list.map((d) => runRow(d)).join('')}</div>`;
}

function runRow(d) {
  const live = isLive(d.status);
  return `
    <div style="padding:14px 20px;border-bottom:1px solid var(--z-100)">
      <div class="flex">
        <div class="src-logo" style="width:38px;height:38px;font-size:15px;border-radius:12px">${sourceLogo(d.source?.name)}</div>
        <div class="grow">
          <a href="#/datasets/${d.id}"><b class="ellipsis" style="display:block;color:var(--z-900)">${esc(d.title)}</b></a>
          <div class="xs muted ellipsis">${esc(d.step || '')}</div>
        </div>
        ${chip(d.status)}
        ${ctlButtons(d, true)}
      </div>
      <div class="flex mt8"><div class="grow">${progress(d.progress.pct, live)}</div><span class="small nowrap">${num(d.progress.collected)}${d.progress.target ? ' از ' + num(d.progress.target) : ''}</span></div>
    </div>`;
}

function ctlButtons(d, small = false) {
  const sz = small ? 'sm' : '';
  if (isLive(d.status)) {
    return `<button class="btn ${sz}" data-act="ctl" data-id="${d.id}" data-do="pause">${icon('pause', 16)} توقف</button>`;
  }
  if (d.status === 'completed') return '';
  return `<button class="btn ${sz} soft" data-act="ctl" data-id="${d.id}" data-do="resume">${icon('play', 16)} ${d.started_at ? 'ادامه' : 'شروع'}</button>`;
}

// ======================================================================
// استخراج جدید
// ======================================================================
const POLICY_LABEL = { ask: 'از من بپرس', retry: 'تکرار خودکار', reload: 'بارگذاری مجدد', continue_partial: 'ادامه با اطلاعات ناقص', skip: 'رد کردن محصول', pause: 'توقف اجرا' };

const MODE_SWITCH = (ai) => `
    <div class="mode-switch mb16">
      <a class="pick ${ai ? '' : 'on'}" href="#/new"><div class="src-logo">${icon('globe', 20)}</div><div class="grow"><b>استخراج از سایت</b><div class="xs muted">لینک صفحه‌ی دسته‌بندی یک منبع را بدهید</div></div></a>
      <a class="pick ${ai ? 'on' : ''}" href="#/new/ai"><div class="src-logo" style="background:var(--primary);color:#fff">${icon('sparkles', 20)}</div><div class="grow"><b>تولید با هوش مصنوعی</b><div class="xs muted">بدون اسکرپ؛ فقط نوع محصول و تعداد</div></div></a>
    </div>`;

export const NewRun = {
  title: 'استخراج جدید',
  crumb: 'ساخت بانک داده از صفحه‌ی دسته‌بندی یا با هوش مصنوعی',
  state: { source: null, ai: false },
  async render(params = {}) {
    const b = await refreshBoot();
    this.state.source = null;
    this.state.ai = params.mode === 'ai';
    document.getElementById('page-title').textContent = this.state.ai ? 'تولید بانک داده با هوش مصنوعی' : 'استخراج جدید';
    if (this.state.ai) return MODE_SWITCH(true) + await renderAIForm(b);
    const kinds = b.errors.kinds;
    return `${MODE_SWITCH(false)}
    <div class="grid g-side">
      <div class="card">
        <div class="card-h"><h2>مشخصات اجرا</h2></div>
        <div class="card-b">
          <div class="field">
            <label>لینک صفحه‌ی دسته‌بندی محصولات</label>
            <input class="inp ltr" id="cat-url" placeholder="https://www.digikala.com/search/category-engine-oil/" data-input="detect" autocomplete="off">
            <div class="hint">ورودی، لینک صفحه‌ی دسته‌بندی است، نه صفحه‌ی یک محصول. منبع از روی دامنه تشخیص داده می‌شود.</div>
          </div>
          <div class="field mt16">
            <label>منبع</label>
            <div class="grid g2" id="src-picks">${b.sources.filter((s) => !s.config.virtual).map((s) => `
              <div class="pick" data-act="pick" data-id="${s.id}">
                <div class="src-logo">${sourceLogo(s.name)}</div>
                <div class="grow"><b>${esc(s.name)}</b><div class="xs muted ltr" style="text-align:right">${esc((s.config.domains || []).join('، '))}</div></div>
                <span class="xs muted">${modeLabel(s.config)}</span>
              </div>`).join('')}</div>
          </div>
          <div class="form-grid mt16">
            <div class="field">
              <label>تعداد محصول</label>
              <input class="inp" id="limit" type="number" min="1" placeholder="خالی = همه‌ی محصولات قابل‌دسترسی">
              <div class="hint">اگر خالی بماند، استخراج تا پایان محصولات دسته ادامه پیدا می‌کند.</div>
            </div>
            <div class="field">
              <label>اسکیمای داده</label>
              <select class="inp" id="schema">${b.schemas.map((s) => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
              <div class="hint">فیلدهای اجباری و فیلدهای دستی از همین اسکیما خوانده می‌شوند.</div>
            </div>
            <div class="field">
              <label>عنوان دسته‌بندی (اختیاری)</label>
              <input class="inp" id="cat-label" placeholder="خودکار از صفحه خوانده می‌شود">
            </div>
            <div class="field">
              <label>محصولات تکراری</label>
              <select class="inp" id="dups">
                <option value="skip">رد شوند (فقط محصولات جدید)</option>
                <option value="reuse">از داده‌ی قبلی استفاده شود</option>
                <option value="rescrape">دوباره استخراج شوند</option>
              </select>
              <div class="hint">محصولی که در اجراهای قبلی همین منبع استخراج شده، تکراری حساب می‌شود.</div>
            </div>
          </div>
          <div class="ai-inline mt16"><div class="flex wrap" style="gap:10px"><span style="color:var(--primary)">${icon('sparkles', 18)}</span><b class="grow">پس از استخراج، تولید با هوش مصنوعی</b>
            <select class="inp sm" style="width:auto;max-width:300px" id="q-ai"><option value="">ندارد</option><option value="schema">ستون‌های AI اسکیما</option><option value="empty">همه‌ی ستون‌های خالی</option>${(b.ai_profiles || []).map((p) => `<option value="p:${p.id}">قالب: ${esc(p.name)}</option>`).join('')}</select>
            <select class="inp sm" style="width:auto" id="q-ai-scope"><option value="all">برای همه‌ی محصولات</option><option value="partial">فقط محصولات ناقص</option></select></div>
            <div class="hint mt8">«ستون‌های AI اسکیما» ستون‌هایی است که در <a href="#/schemas">اسکیما</a> برایشان «هوش مصنوعی» روشن است (هر نوع مقداری: متن، اسلاگ، نگاشت، مشخصات، ابعاد، بولت‌ها، تصاویر). «همه‌ی ستون‌های خالی» هر ستونی را که پس از استخراج خالی مانده تکمیل می‌کند.</div></div>
          <details class="mt16" id="q-details">
            <summary class="lbl" style="cursor:pointer">${icon('layers', 15)} صف و زمان‌بندی</summary>
            <div class="hint mt8">با «افزودن به صف»، این استخراج پس از پایان کارهای قبلی صف (و رسیدن زمان شروع) خودکار اجرا می‌شود.</div>
            <div class="form-grid mt12">
              <div class="field"><label class="small">عنوان کار (اختیاری)</label><input class="inp sm" id="q-title" placeholder="مثلاً روغن موتور — نوبت صبح"></div>
              <div class="field"><label class="small">زمان شروع (اختیاری)</label><input class="inp sm" id="q-at" type="datetime-local" data-input="qat"><div class="hint" id="q-at-hint">خالی = به‌محض رسیدن نوبت</div></div>
              <div class="field"><label class="small">تکرار هر (ساعت)</label><input class="inp sm" id="q-rep" type="number" min="0" step="0.5" placeholder="بدون تکرار"><div class="hint">برای به‌روزرسانی دوره‌ای؛ با «رد شدن تکراری‌ها» فقط محصولات تازه استخراج می‌شوند.</div></div>

            </div>
          </details>
          <details class="mt16">
            <summary class="lbl" style="cursor:pointer">رفتار در برابر خطا (پیشرفته)</summary>
            <div class="hint mt8">پیش‌فرض برای همه‌ی خطاها «از من بپرس» است: اجرا می‌ایستد و گزینه‌های ادامه را می‌بینید. خطاهای شبکه و زمان‌بر، پیش از پرسیدن چند بار خودکار تکرار می‌شوند.</div>
            <div class="form-grid mt12" id="policies">${Object.entries(kinds).map(([k, v]) => `
              <div class="field"><label class="small">${esc(v.title)}</label>
              <select class="inp sm" data-policy="${k}"><option value="ask">${POLICY_LABEL.ask}</option>${v.actions.filter((a) => POLICY_LABEL[a] && a !== 'pause').map((a) => `<option value="${a}">${POLICY_LABEL[a]}</option>`).join('')}<option value="pause">${POLICY_LABEL.pause}</option></select></div>`).join('')}
            </div>
            <label class="check mt12"><input type="checkbox" id="show-browser"> مرورگر در حین استخراج نمایش داده شود (برای دیدن روند یا حل کپچا)</label>
          </details>
        </div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px">
          <button class="btn ghost" data-act="create" data-start="0">${icon('save', 16)} فقط ساخت بانک</button>
          <button class="btn soft" data-act="enqueue">${icon('layers', 16)} افزودن به صف</button>
          <button class="btn primary" data-act="create" data-start="1">${icon('play', 16)} شروع استخراج</button>
        </div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h3>نام‌گذاری بانک داده</h3></div>
          <div class="card-b small">
            <div>هر اجرا یک شناسه‌ی یکتا و نامی گویا می‌گیرد که منبع، دسته، تعداد و زمان در آن پیداست:</div>
            <div class="pathbox mt8" id="name-preview">digikala__engine-oil__48items__1405-08-05_1843</div>
            <div class="hint mt8">تعداد محصولات در پایان اجرا در نام به‌روز می‌شود. همین نام، نام فایل Excel و پوشه‌ی تصاویر خروجی خواهد بود.</div>
          </div>
        </div>
        <div class="card"><div class="card-h"><h3>در طول اجرا</h3></div>
          <div class="card-b small" style="line-height:2.1">
            <div class="flex">${icon('pause', 16)} هر لحظه می‌توانید متوقف کنید و بعداً دقیقاً از همان نقطه ادامه دهید.</div>
            <div class="flex">${icon('shield', 16)} محصولات تکراری و صفحات خوانده‌شده دوباره بررسی نمی‌شوند.</div>
            <div class="flex">${icon('alert', 16)} در خطا، نوع خطا و گزینه‌های ادامه به شما نشان داده می‌شود.</div>
            <div class="flex">${icon('link', 16)} لینک مستقیم صفحه‌ی هر محصول در خروجی ثبت می‌شود.</div>
          </div>
        </div>
      </div>
    </div>`;
  },
  input: {
    qat: (el) => { document.getElementById('q-at-hint').textContent = el.value ? `شروع: ${jdate(new Date(el.value).toISOString())}` : 'خالی = به‌محض رسیدن نوبت'; },
    detect: async (el) => {
      const u = el.value.trim();
      if (!/^https?:\/\//.test(u)) return;
      const r = await api(`/api/sources/detect?url=${encodeURIComponent(u)}`);
      if (r.source) NewRun.pick(r.source.id);
      NewRun.preview();
    },
  },
  pick(id) {
    this.state.source = id;
    document.querySelectorAll('#src-picks .pick').forEach((p) => p.classList.toggle('on', Number(p.dataset.id) === id));
    this.preview();
  },
  preview() {
    const s = srcById(this.state.source);
    const u = document.getElementById('cat-url')?.value || '';
    let seg = 'category';
    try {
      const parts = decodeURIComponent(new URL(u).pathname).split('/').filter(Boolean).filter((x) => !['category', 'search', 'city', 'tehran'].includes(x) && !/^\d+$/.test(x));
      seg = (parts.pop() || 'category').replace(/^category-/, '');
    } catch (e) { /* */ }
    const el = document.getElementById('name-preview');
    if (el) el.textContent = `${s ? s.key : 'source'}__${/^[\x00-\x7F]+$/.test(seg) ? seg.toLowerCase() : 'category'}__Nitems__<تاریخ>_<ساعت>`;
  },
  act: {
    aiCreate: (el) => aiCreate(el),
    aiEnqueue: (el) => aiEnqueue(el),
    aiSuggest: (el) => aiSuggestSpec(el),
    pick: (el) => NewRun.pick(Number(el.dataset.id)),
    enqueue: async (el) => {
      const url = document.getElementById('cat-url').value.trim();
      if (!url) { toast('لینک صفحه‌ی دسته‌بندی را وارد کنید.', 'err'); return; }
      const policies = {};
      document.querySelectorAll('[data-policy]').forEach((s) => { policies[s.dataset.policy] = s.value; });
      const at = document.getElementById('q-at').value;
      el.disabled = true;
      try {
        await api('/api/queue', { body: {
          category_url: url, source_id: NewRun.state.source, limit: document.getElementById('limit').value,
          schema_id: Number(document.getElementById('schema').value), duplicates: document.getElementById('dups').value,
          category_label: document.getElementById('cat-label').value.trim(), policies, show_browser: document.getElementById('show-browser').checked,
          title: document.getElementById('q-title').value.trim(), scheduled_at: at ? new Date(at).toISOString() : '',
          repeat_hours: Number(document.getElementById('q-rep').value || 0), ai_after: aiAfterSpec(),
        } });
        okToast('به صف اضافه شد.');
        go('#/queue');
      } finally { el.disabled = false; }
    },
    create: async (el) => {
      const url = document.getElementById('cat-url').value.trim();
      if (!url) { toast('لینک صفحه‌ی دسته‌بندی را وارد کنید.', 'err'); return; }
      const policies = {};
      document.querySelectorAll('[data-policy]').forEach((s) => { policies[s.dataset.policy] = s.value; });
      el.disabled = true;
      try {
        const d = await api('/api/datasets', {
          body: {
            category_url: url, source_id: NewRun.state.source, limit: document.getElementById('limit').value,
            schema_id: Number(document.getElementById('schema').value), duplicates: document.getElementById('dups').value,
            category_label: document.getElementById('cat-label').value.trim(), policies,
            show_browser: document.getElementById('show-browser').checked, start: el.dataset.start === '1', ai_after: aiAfterSpec(),
          },
        });
        okToast(el.dataset.start === '1' ? 'استخراج آغاز شد.' : 'بانک داده ساخته شد.');
        go(`#/datasets/${d.id}`);
      } finally { el.disabled = false; }
    },
  },
};

// ---------------------------------------------------------------- تولید با هوش مصنوعی
async function renderAIForm(b) {
  const provs = (await api('/api/ai/providers').catch(() => ({}))).providers || [];
  const st = b.settings || {};
  const pOpts = (sel, img = false) => `<option value="">پیش‌فرض استودیو</option>${provs.filter((p) => !img || p.image_mode !== 'none').map((p) => `<option value="${p.id}" ${String(sel) === String(p.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}`;
  const warn = provs.length ? '' : `<div class="alert warn mb16">${icon('alert')}<div><b>هنوز اتصال هوش مصنوعی ندارید.</b> ابتدا در <a href="#/ai">هوش مصنوعی ← اتصال‌ها</a> یک اتصال (OpenAI، Gemini، OpenRouter، AvalAI، …) بسازید.</div></div>`;
  return `${warn}
    <div class="grid g-side">
      <div class="card">
        <div class="card-h"><h2>${icon('sparkles', 18)} مشخصات محصولات</h2><span class="sp"></span>
          <button class="btn sm soft" data-act="aiSuggest">${icon('wand', 14)} تکمیل فرم با AI</button></div>
        <div class="card-b" id="aig">
          <div class="form-grid">
            <div class="field"><label>نوع محصول <span style="color:var(--err)">*</span></label>
              <input class="inp" id="g-type" name="product_type" placeholder="مثلاً: روغن موتور خودرو، لنت ترمز جلو، فیلتر هوا" data-ai-label="نوع محصول"></div>
            <div class="field"><label>دسته‌بندی (اختیاری)</label>
              <input class="inp" id="g-cat" name="category_label" placeholder="مثلاً: روغن موتور" data-ai-label="عنوان دسته‌بندی"></div>
            <div class="field"><label>تعداد محصول</label><input class="inp" id="g-count" name="count" type="number" min="1" max="1000" value="10">
              <div class="hint">عنوان‌ها یکتا و غیرتکراری برنامه‌ریزی می‌شوند.</div></div>
            <div class="field"><label>اسکیمای داده</label>
              <select class="inp" id="g-schema">${b.schemas.map((s) => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
              <div class="hint">همه‌ی ستون‌های اسکیما (حتی دستی‌ها) پر می‌شوند.</div></div>
            <div class="field"><label>برندها (اختیاری)</label><input class="inp" id="g-brands" name="brands" placeholder="مثلاً: بهران، ایرانول، کاسترول، توتال" data-ai-label="برندهای پیشنهادی" data-ai-format="keywords"></div>
            <div class="field"><label>کلیدواژه‌های سئو (اختیاری)</label><input class="inp" id="g-seo" name="seo_keywords" placeholder="مثلاً: خرید روغن موتور، روغن موتور ۱۰w40" data-ai-format="keywords"></div>
          </div>
          <div class="field mt16"><label>توضیحات و قیدهای تکمیلی (اختیاری)</label>
            <textarea class="inp" id="g-notes" name="notes" rows="3" placeholder="مثلاً: فقط محصولات مناسب خودروهای سواری ایرانی؛ حجم‌های ۴ و ۵ لیتری؛ لحن رسمی" data-ai-label="توضیحات تکمیلی برای تولید محصولات"></textarea></div>
          <div class="ai-inline mt16">
            <div class="flex wrap"><label class="check grow"><input type="checkbox" id="g-img" checked> برای هر محصول تصویر هم ساخته شود</label>
              <span class="small">تعداد تصویر</span><input class="inp sm" id="g-img-n" type="number" min="1" max="4" value="1" style="width:70px">
              <select class="inp sm" id="g-img-p" style="width:auto">${pOpts(st.ai_default_image_provider_id, true)}</select></div>
            <div class="hint">تصویر اول «feature» و بقیه گالری با زاویه‌های متفاوت ساخته می‌شوند؛ اتصال باید تولید تصویر را پشتیبانی کند.</div>
          </div>
          <details class="mt16"><summary class="lbl" style="cursor:pointer">${icon('cpu', 15)} مدل و صف (پیشرفته)</summary>
            <div class="form-grid mt12">
              <div class="field"><label class="small">اتصال متن</label><select class="inp sm" id="g-prov">${pOpts(st.ai_default_provider_id)}</select></div>
              <div class="field"><label class="small">مدل (اختیاری)</label><input class="inp sm ltr" id="g-model" data-noai placeholder="${attr(st.ai_default_model || 'مدل پیش‌فرض اتصال')}"></div>
              <div class="field"><label class="small">هم‌زمانی</label><input class="inp sm" id="g-conc" type="number" min="1" max="8" value="3"></div>
              <div class="field"><label class="small">عنوان کار صف (اختیاری)</label><input class="inp sm" id="g-qtitle" data-noai></div>
              <div class="field"><label class="small">زمان شروع در صف (اختیاری)</label><input class="inp sm" id="g-qat" type="datetime-local"></div>
            </div>
          </details>
        </div>
        <div class="drawer-f" style="border-radius:0 0 20px 20px">
          <button class="btn ghost" data-act="aiCreate" data-start="0">${icon('save', 16)} فقط ساخت بانک</button>
          <button class="btn soft" data-act="aiEnqueue">${icon('layers', 16)} افزودن به صف</button>
          <button class="btn primary" data-act="aiCreate" data-start="1">${icon('sparkles', 16)} شروع تولید</button>
        </div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h3>چه چیزی ساخته می‌شود؟</h3></div>
          <div class="card-b small" style="line-height:2.1">
            <div class="flex">${icon('list', 16)} فهرست N محصول یکتا با برند و مدل واقع‌نما</div>
            <div class="flex">${icon('edit', 16)} عنوان فارسی/انگلیسی، توضیح کوتاه و کامل، مشخصات فنی و ابعاد</div>
            <div class="flex">${icon('columns', 16)} همه‌ی ستون‌های دستی اسکیما (بایدها/نبایدها، یادداشت فروشنده، …)</div>
            <div class="flex">${icon('image', 16)} تصویر شاخص و گالری</div>
            <div class="flex">${icon('link', 16)} اسلاگ، نگاشت برند و دسته، و خروجی Excel مثل هر بانک دیگر</div>
          </div></div>
        <div class="card"><div class="card-h"><h3>نکته</h3></div>
          <div class="card-b small muted" style="line-height:2">
            محصولات تولیدی با برچسب «AI» علامت می‌خورند و لینک منبع ندارند. می‌توانید بعداً همین بانک را با محصولات استخراج‌شده ترکیب کنید،
            محصول بیشتر اضافه کنید یا هر محصول را جداگانه دوباره بسازید.</div></div>
      </div>
    </div>`;
}

function aiSpec() {
  const g = (id) => document.getElementById(id);
  const spec = {
    product_type: g('g-type').value.trim(), category_label: g('g-cat').value.trim(), count: Number(g('g-count').value || 10),
    schema_id: Number(g('g-schema').value), brands: g('g-brands').value.trim(), seo_keywords: g('g-seo').value.trim(), notes: g('g-notes').value.trim(),
    provider_id: Number(g('g-prov').value) || null, model: g('g-model').value.trim(), concurrency: Number(g('g-conc').value || 3),
    images: { enabled: g('g-img').checked, count: Number(g('g-img-n').value || 1), provider_id: Number(g('g-img-p').value) || null },
  };
  if (!spec.product_type) { toast('نوع محصول را بنویسید.', 'err'); g('g-type').focus(); return null; }
  return spec;
}

async function aiCreate(el) {
  const spec = aiSpec();
  if (!spec) return;
  spec.start = el.dataset.start === '1';
  busy(el, true, 'در حال ساخت…');
  try {
    const d = await api('/api/ai/datasets', { body: spec });
    okToast(spec.start ? 'تولید محصولات با هوش مصنوعی آغاز شد.' : 'بانک داده ساخته شد.');
    go(`#/datasets/${d.id}`);
  } finally { busy(el, false); }
}

async function aiEnqueue(el) {
  const spec = aiSpec();
  if (!spec) return;
  const at = document.getElementById('g-qat').value;
  busy(el, true, 'افزودن…');
  try {
    await api('/api/queue', { body: { ai_generate: spec, limit: spec.count, schema_id: spec.schema_id, category_label: spec.category_label,
      title: document.getElementById('g-qtitle').value.trim() || `تولید AI: ${spec.count} × ${spec.product_type}`, scheduled_at: at ? new Date(at).toISOString() : '' } });
    okToast('به صف اضافه شد.');
    go('#/queue');
  } finally { busy(el, false); }
}

async function aiSuggestSpec(el) {
  const g = (id) => document.getElementById(id);
  const seed = g('g-type').value.trim() || g('g-cat').value.trim();
  if (!seed) { toast('حداقل نوع محصول یا دسته را بنویسید تا بقیه پیشنهاد شود.', 'err'); return; }
  busy(el, true);
  try {
    const one = (label, fmt, instruction) => assist('text', { label, format: fmt, instruction, context: { product_type: seed, category: g('g-cat').value }, temperature: 0.5 });
    const [cat, brands, seo, notes] = await Promise.all([
      g('g-cat').value ? null : one('عنوان دسته‌بندی', 'text', `یک عنوان کوتاه فارسی برای دسته‌بندی محصولات «${seed}» در فروشگاه لوازم خودرو بنویس (۱ تا ۳ کلمه).`),
      g('g-brands').value ? null : one('برندها', 'keywords', `۶ تا ۸ برند معتبر و رایج در بازار ایران برای «${seed}» نام ببر.`),
      g('g-seo').value ? null : one('کلیدواژه‌های سئو', 'keywords', `۵ کلیدواژه‌ی پرجست‌وجوی فارسی برای «${seed}».`),
      g('g-notes').value ? null : one('توضیحات تکمیلی', 'text', `در ۲ جمله، قیدهای مفید برای تولید کاتالوگ «${seed}» بنویس (تنوع مدل/سایز، سازگاری با خودروهای رایج ایران، لحن).`),
    ]);
    if (cat) g('g-cat').value = cat.value;
    if (brands) g('g-brands').value = brands.value;
    if (seo) g('g-seo').value = seo.value;
    if (notes) g('g-notes').value = notes.value;
    okToast('فرم تکمیل شد؛ بررسی و ویرایش کنید.');
  } catch (e) { noProviderHint(e); } finally { busy(el, false); }
}

function aiAfterSpec() {
  const v = document.getElementById('q-ai')?.value;
  if (!v) return null;
  const scope = document.getElementById('q-ai-scope').value;
  return v.startsWith('p:') ? { mode: 'profile', profile_id: Number(v.slice(2)), scope } : { mode: v, scope };
}

function modeLabel(cfg) {
  const l = cfg.listing?.mode, p = cfg.product?.mode;
  if (l === 'api' || p === 'api') return 'API';
  return 'مرورگر';
}

// ======================================================================
// فهرست بانک‌های داده
// ======================================================================
export const Datasets = {
  title: 'بانک‌های داده',
  crumb: 'همه‌ی اجراهای استخراج و تولید',
  top: () => `<a class="btn soft" href="#/new/ai">${icon('sparkles')} تولید با هوش مصنوعی</a><a class="btn primary" href="#/new">${icon('plus')} استخراج جدید</a>`,
  async render() {
    const list = await api('/api/datasets');
    if (!list.length) return `<div class="card">${emptyState('database', 'هنوز بانک داده‌ای ندارید', 'با یک لینک صفحه‌ی دسته‌بندی، اولین بانک داده را بسازید.', `<a class="btn primary" href="#/new">${icon('plus')} استخراج جدید</a>`)}</div>`;
    return `<div class="card"><div class="tbl-wrap" style="border-radius:20px"><table class="tbl" id="ds-table">${this.rows(list)}</table></div></div>`;
  },
  rows(list) {
    return `<thead><tr><th>بانک داده</th><th>منبع</th><th>وضعیت</th><th style="width:220px">پیشرفت</th><th>کامل / ناقص</th><th>ساخته‌شده</th><th></th></tr></thead><tbody>
      ${list.map((d) => `<tr class="click" data-act="open" data-id="${d.id}">
        <td><b style="color:var(--z-900)">${esc(trunc(d.title, 70))}</b><div class="xs muted ltr" style="text-align:right">${esc(d.code)} · ${esc(d.name)}</div></td>
        <td class="nowrap">${esc(d.source?.name || '')}</td>
        <td>${chip(d.status)}${d.open_incident ? ' <span class="badge">!</span>' : ''}</td>
        <td><div class="flex"><div class="grow">${progress(d.progress.pct, isLive(d.status))}</div><span class="xs nowrap">${num(d.progress.collected)}${d.progress.target ? '/' + num(d.progress.target) : ''}</span></div></td>
        <td class="nowrap">${num(d.counts.done)} / ${num(d.counts.partial)}</td>
        <td class="nowrap small">${jdate(d.created_at)}</td>
        <td class="nowrap">${ctlButtons(d, true)}</td>
      </tr>`).join('')}</tbody>`;
  },
  mount() {
    every(3000, async () => {
      const list = await api('/api/datasets').catch(() => null);
      const t = document.getElementById('ds-table');
      if (list && t) t.innerHTML = this.rows(list);
    });
  },
  act: {
    open: (el, ev) => { if (ev.target.closest('button')) return; go(`#/datasets/${el.dataset.id}`); },
    ctl: async (el, ev) => { ev.stopPropagation(); await api(`/api/datasets/${el.dataset.id}/do/${el.dataset.do}`, { body: {} }); },
  },
};

// ======================================================================
// جزئیات بانک داده
// ======================================================================
const IT = { tab: 'items', page: 1, status: '', q: '', sel: new Set(), lastLog: 0, ds: null, items: null };

export const Dataset = {
  title: 'بانک داده',
  crumb: 'جزئیات اجرا و محصولات',
  async render(p) {
    IT.tab = 'items'; IT.page = 1; IT.status = ''; IT.q = ''; IT.sel = new Set(); IT.lastLog = 0;
    const d = await api(`/api/datasets/${p.id}`);
    IT.ds = d;
    document.getElementById('page-title').textContent = 'بانک داده';
    return `
      <div id="ds-head">${this.head(d)}</div>
      <div id="ds-inc" class="mt16">${d.open_incident ? incidentCard(d.open_incident) : ''}</div>
      <div id="ds-ai"></div>
      <div class="card mt16">
        <div class="tabs" id="ds-tabs">${this.tabs()}</div>
        <div id="ds-tab"></div>
      </div>`;
  },
  tabs() {
    const t = [['items', 'list', 'محصولات'], ['log', 'scroll', 'گزارش اجرا'], ['incidents', 'alert', 'خطاها و تصمیم‌ها'], ['preview', 'fileSheet', 'پیش‌نمایش خروجی'], ['settings', 'settings', 'تنظیمات اجرا']];
    return t.map(([k, ic, l]) => `<button class="${IT.tab === k ? 'on' : ''}" data-act="tab" data-tab="${k}">${icon(ic, 16)} ${l}</button>`).join('');
  },
  head(d) {
    const live = isLive(d.status);
    const isAI = !!d.options?.ai_only;
    const verb = isAI ? 'تولید' : 'استخراج';
    const c = d.counts;
    const dupS = d.cursor?.duplicates_skipped || 0;
    return `
    <div class="card">
      <div class="card-b">
        <div class="flex top">
          <div class="src-logo">${sourceLogo(d.source?.name)}</div>
          <div class="grow">
            <div class="flex wrap"><h2 style="margin:0;font-size:18px;color:var(--z-900)">${esc(d.title)}</h2>${chip(d.status)}</div>
            <div class="flex wrap small muted mt8">
              <span class="tag ltr">${esc(d.code)}</span>
              <span class="tag ltr" title="نام فایل خروجی">${icon('fileSheet', 13)} ${esc(d.name)}</span>
              ${isAI ? `<span class="tag p">${icon('sparkles', 13)} تولید با هوش مصنوعی · ${esc(d.options.ai_generate?.product_type || '')}</span>` : `<a class="tag" href="${attr(d.category_url)}" target="_blank" rel="noopener">${icon('external', 13)} صفحه‌ی دسته‌بندی</a>`}
              <span>${jdate(d.created_at)}</span>
            </div>
          </div>
          <div class="btns">
            ${live ? `<button class="btn" data-act="ctl" data-do="pause">${icon('pause', 16)} توقف</button><button class="btn danger" data-act="ctl" data-do="stop">${icon('stop', 16)} پایان</button>`
              : `<button class="btn primary" data-act="ctl" data-do="${d.started_at ? 'resume' : 'start'}">${icon('play', 16)} ${d.started_at ? (d.status === 'completed' ? (isAI ? 'ادامه / تکمیل' : 'ادامه / بررسی دوباره') : 'ادامه از آخرین نقطه') : 'شروع ' + verb}</button>`}
            <div class="menu-wrap"><button class="btn soft" data-act="aimenu">${icon('sparkles', 16)} هوش مصنوعی ${icon('chevronDown', 14)}</button>
              <div class="menu hidden" id="ai-menu">
                <button data-act="airun">${icon('wand', 15)}<span><b>تولید ستون‌ها با AI</b><small>هر ستون دلخواه (متن، اسلاگ، مشخصات، ابعاد، تصاویر…) برای همه یا انتخاب‌شده‌ها</small></span></button>
                <button data-act="aicol">${icon('columns', 15)}<span><b>تولید یک ستون</b><small>فقط یک ستون اسکیما با دستور دلخواه</small></span></button>
                <button data-act="aiadd">${icon('plus', 15)}<span><b>افزودن محصول با AI</b><small>بدون اسکرپ؛ N محصول جدید به همین بانک</small></span></button>
              </div></div>
            <a class="btn" href="#/exports?ds=${d.id}" data-act="export">${icon('download', 16)} خروجی</a>
            <button class="btn icon ghost" title="ویرایش نام" data-act="rename">${icon('edit', 16)}</button>
            ${live ? '' : `<button class="btn icon ghost danger" title="حذف بانک" data-act="del">${icon('trash', 16)}</button>`}
          </div>
        </div>
        <div class="flex mt16"><div class="grow">${progress(d.progress.pct, live)}</div>
          <b class="nowrap">${num(d.progress.collected)}${d.progress.target ? ' از ' + num(d.progress.target) : ''} محصول ${d.progress.pct !== null && d.progress.pct !== undefined ? '· ' + fa(d.progress.pct) + '٪' : ''}</b></div>
        <div class="flex mt8 small">${live ? icon('loader', 15, 'spin') : icon('info', 15)}<span class="grow">${esc(d.step || '—')}</span></div>
        <hr class="sep" style="margin:14px 0">
        <div class="kpi-line">
          <span>کامل <b>${num(c.done)}</b></span><span>ناقص <b>${num(c.partial)}</b></span><span>در صف <b>${num(c.queued)}</b></span>
          <span>رد شده <b>${num(c.skipped)}</b></span><span>لینک یافت‌شده <b>${num(d.total_found)}</b></span>
          ${d.total_expected ? `<span>کل محصولات دسته <b>${num(d.total_expected)}</b></span>` : ''}
          ${dupS ? `<span>تکراری ردشده <b>${num(dupS)}</b></span>` : ''}
          <span>سقف <b>${d.item_limit ? num(d.item_limit) : 'همه'}</b></span>
          <span>اسکیما <b>${esc(d.schema?.name || '—')}</b></span>
        </div>
      </div>
    </div>`;
  },
  async mount(root, p) {
    await this.renderTab();
    every(1500, () => this.tick(p.id));
  },
  async tick(id) {
    const d = await api(`/api/datasets/${id}`).catch(() => null);
    if (!d || S.params.id !== String(id)) return;
    const prevStatus = IT.ds?.status;
    const prevInc = IT.ds?.open_incident?.id;
    IT.ds = d;
    const h = document.getElementById('ds-head');
    if (h && !h.querySelector('.menu:not(.hidden)')) h.innerHTML = this.head(d);
    if ((d.open_incident?.id || null) !== (prevInc || null)) {
      document.getElementById('ds-inc').innerHTML = d.open_incident ? incidentCard(d.open_incident) : '';
    }
    if (IT.tab === 'log') this.appendLog();
    this.aiJobs(id);
    const changed = prevStatus !== d.status;
    if (IT.tab === 'items' && (isLive(d.status) || changed)) {
      IT._n = (IT._n || 0) + 1;
      if (IT._n % 2 === 0 || changed) this.loadItems(true);
    }
  },
  refresh() { this.tick(S.params.id); },
  async aiJobs(id) {
    const box = document.getElementById('ds-ai');
    if (!box) return;
    const rows = (await api(`/api/ai/jobs?dataset_id=${id}`).catch(() => [])).filter((r) => ['running', 'pending', 'paused', 'error'].includes(r.status)).slice(0, 2);
    const html = rows.length ? `<div class="card mt16">${rows.map(aiJobRow).join('')}</div>` : '';
    const live = rows.some((r) => r.status === 'running');
    if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
    if (live && IT.tab === 'items') { IT._ai = (IT._ai || 0) + 1; if (IT._ai % 3 === 0) this.loadItems(true); }
    else if (IT._wasAi && !live) this.loadItems(true);
    IT._wasAi = live;
  },
  async renderTab() {
    const el = document.getElementById('ds-tab');
    document.getElementById('ds-tabs').innerHTML = this.tabs();
    if (IT.tab === 'items') { el.innerHTML = this.itemsShell(); await this.loadItems(); }
    else if (IT.tab === 'log') { IT.lastLog = 0; el.innerHTML = `<div class="log" id="ds-log"></div>`; await this.appendLog(); }
    else if (IT.tab === 'incidents') el.innerHTML = await this.incidentsTab();
    else if (IT.tab === 'preview') el.innerHTML = await this.previewTab();
    else if (IT.tab === 'settings') el.innerHTML = this.settingsTab();
  },
  // ---------- محصولات ----------
  itemsShell() {
    const sts = [['', 'همه'], ['done', 'کامل'], ['partial', 'ناقص'], ['queued', 'در صف'], ['skipped', 'رد شده']];
    return `
      <div class="flex wrap" style="padding:14px 16px;border-bottom:1px solid var(--z-100)">
        <div class="seg">${sts.map(([k, l]) => `<button class="${IT.status === k ? 'on' : ''}" data-act="fstatus" data-s="${k}">${l}</button>`).join('')}</div>
        <div style="position:relative;width:260px"><input class="inp sm" placeholder="جست‌وجو در عنوان، برند، لینک…" data-input="search" value="${attr(IT.q)}"></div>
        <span class="grow"></span>
        <span class="small muted" id="sel-count"></span>
        <button class="btn sm soft" data-act="bulk">${icon('edit', 15)} تکمیل گروهی فیلدهای دستی</button>
        <div class="btns" id="sel-actions"></div>
      </div>
      <div class="tbl-wrap" id="items-wrap"></div>
      <div class="pager" id="items-pager"></div>`;
  },
  async loadItems(silent = false) {
    const id = S.params.id;
    const qs = new URLSearchParams({ page: IT.page, size: 50 });
    if (IT.status) qs.set('status', IT.status);
    if (IT.q) qs.set('q', IT.q);
    const r = await api(`/api/datasets/${id}/items?${qs}`);
    IT.items = r;
    const wrap = document.getElementById('items-wrap');
    if (!wrap) return;
    if (!r.items.length) {
      wrap.innerHTML = emptyState('box', 'محصولی برای نمایش نیست', isLive(IT.ds?.status) ? 'به‌محض استخراج، محصولات این‌جا ظاهر می‌شوند.' : 'فیلتر را تغییر دهید یا استخراج را شروع کنید.');
      document.getElementById('items-pager').innerHTML = '';
      this.updateSel();
      return;
    }
    wrap.innerHTML = `<table class="tbl"><thead><tr>
      <th style="width:36px"><input type="checkbox" data-change="selall" ${r.items.every((i) => IT.sel.has(i.id)) ? 'checked' : ''}></th>
      <th style="width:40px">#</th><th style="width:56px"></th><th>عنوان محصول</th><th>برند</th><th>مشخصات</th><th>تصویر</th><th>وضعیت</th><th>تکمیل دستی</th><th></th></tr></thead><tbody>
      ${r.items.map((it) => `<tr class="click ${IT.sel.has(it.id) ? 'sel' : ''}" data-act="item" data-id="${it.id}">
        <td><input type="checkbox" data-change="sel" data-id="${it.id}" ${IT.sel.has(it.id) ? 'checked' : ''}></td>
        <td class="muted small">${fa(it.seq)}</td>
        <td>${it.image ? `<img class="thumb" loading="lazy" src="${attr(imgSrc(it.image))}" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb ph',innerHTML:'—'}))">` : `<div class="thumb ph">${icon('image', 18)}</div>`}</td>
        <td><b style="color:var(--z-900)">${esc(trunc(it.title || (it.status === 'queued' ? '(در انتظار استخراج)' : '(بدون عنوان)'), 90))}</b>${/^ai-generated:/.test(it.url) ? `<div class="xs" style="color:var(--primary)">${icon('sparkles', 11)} ساخته‌شده با هوش مصنوعی</div>` : `<div class="xs muted ltr ellipsis" style="max-width:420px;text-align:right">${esc(decodeURIComponentSafe(it.url))}</div>`}
          ${it.missing?.length ? `<div class="xs" style="color:var(--warn)">${icon('alert', 12)} خالی: ${esc(it.missing.join('، '))}</div>` : ''}
          ${it.error && it.status !== 'done' ? `<div class="xs" style="color:var(--err)">${esc(trunc(it.error, 90))}</div>` : ''}</td>
        <td class="small">${esc(it.brand || '—')}</td>
        <td class="small nowrap">${it.specs_count ? fa(it.specs_count) + ' ویژگی' : '—'}</td>
        <td class="small nowrap">${it.image ? '۱ + ' + fa(it.gallery_count) : '—'}</td>
        <td>${chip(it.status)}</td>
        <td>${it.has_manual ? `<span class="tag p">${icon('check', 12)} دارد</span>` : '<span class="xs muted">—</span>'}${it.has_overrides ? ' <span class="tag" title="ویرایش دستی روی داده‌ی استخراج‌شده">ویرایش‌شده</span>' : ''}${it.has_ai ? ` <span class="tag p" title="فیلدهای تولیدشده با هوش مصنوعی">${icon('sparkles', 12)} AI</span>` : ''}${it.ai_error ? ` <span class="tag" style="color:var(--err)" title="${attr(it.ai_error)}">${icon('alert', 12)} AI</span>` : ''}</td>
        <td>${/^https?:/.test(it.url) ? `<a class="btn xs ghost" href="${attr(it.url)}" target="_blank" rel="noopener" title="صفحه‌ی منبع">${icon('external', 14)}</a>` : ''}</td>
      </tr>`).join('')}</tbody></table>`;
    const pages = Math.max(1, Math.ceil(r.total / r.size));
    document.getElementById('items-pager').innerHTML = `
      <button class="btn sm" data-act="pg" data-p="${IT.page - 1}" ${IT.page <= 1 ? 'disabled' : ''}>${icon('chevronRight', 16)} قبلی</button>
      <span class="small">صفحه ${fa(IT.page)} از ${fa(pages)} · ${num(r.total)} محصول</span>
      <button class="btn sm" data-act="pg" data-p="${IT.page + 1}" ${IT.page >= pages ? 'disabled' : ''}>بعدی ${icon('chevronLeft', 16)}</button>`;
    this.updateSel();
  },
  updateSel() {
    const n = IT.sel.size;
    const c = document.getElementById('sel-count');
    if (c) c.textContent = n ? `${fa(n)} محصول انتخاب شده` : '';
    const a = document.getElementById('sel-actions');
    if (a) a.innerHTML = n ? `<button class="btn sm soft" data-act="selai">${icon('sparkles', 15)} تولید AI</button><button class="btn sm" data-act="selaiclear" title="بازگشت به داده‌ی استخراج‌شده">${icon('eraser', 15)} حذف خروجی AI</button><button class="btn sm" data-act="selrescrape">${icon('refresh', 15)} استخراج دوباره</button><button class="btn sm danger" data-act="seldel">${icon('trash', 15)} حذف</button><button class="btn sm ghost" data-act="selclear">${icon('x', 15)}</button>` : '';
  },
  // ---------- لاگ ----------
  async appendLog() {
    const box = document.getElementById('ds-log');
    if (!box) return;
    const rows = await api(`/api/datasets/${S.params.id}/logs?after=${IT.lastLog}`);
    if (!rows.length) { if (!IT.lastLog) box.innerHTML = emptyState('scroll', 'هنوز رویدادی ثبت نشده', ''); return; }
    if (!IT.lastLog) box.innerHTML = '';
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    box.insertAdjacentHTML('beforeend', rows.map(logRow).join(''));
    IT.lastLog = rows[rows.length - 1].id;
    if (atBottom) box.scrollTop = box.scrollHeight;
  },
  async incidentsTab() {
    const rows = await api(`/api/datasets/${S.params.id}/incidents`);
    if (!rows.length) return emptyState('shield', 'خطایی ثبت نشده', 'هر خطایی که نیاز به تصمیم شما داشته باشد این‌جا با تصمیم گرفته‌شده ثبت می‌شود.');
    const lbl = S.boot.errors.actions;
    return `<table class="tbl"><thead><tr><th>زمان</th><th>نوع خطا</th><th>پیام</th><th>تصمیم</th><th>وضعیت</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="small nowrap">${jdate(r.created_at)}</td><td><b>${esc(r.title)}</b></td><td class="small">${esc(r.message)}<div class="xs muted ltr ellipsis" style="max-width:360px">${esc(decodeURIComponentSafe(r.url || ''))}</div></td>
      <td class="small">${r.decision ? esc(lbl[r.decision]?.label || r.decision) + (r.apply_all ? ' <span class="tag">برای همه</span>' : '') : '—'}</td>
      <td>${r.status === 'open' ? chip('waiting') : r.status === 'resolved' ? '<span class="chip ok">ثبت شد</span>' : '<span class="chip idle">بی‌اثر شد</span>'}</td></tr>`).join('')}</tbody></table>`;
  },
  async previewTab() {
    const d = IT.ds;
    const schemas = S.boot.schemas;
    const r = await api(`/api/datasets/${d.id}/preview`, { body: { schema_id: d.schema_id } });
    if (!r.rows.length) return emptyState('fileSheet', 'هنوز داده‌ای برای پیش‌نمایش نیست', 'پس از استخراج چند محصول، ستون‌های خروجی این‌جا دیده می‌شوند.');
    const unm = r.warnings.filter((w) => w.flag === 'unmapped');
    return `
      <div style="padding:14px 16px" class="flex wrap">
        <span class="small muted">۳۰ ردیف نخست با اسکیمای «${esc(schemaById(d.schema_id)?.name || '')}»</span><span class="grow"></span>
        ${unm.length ? `<a class="tag" style="color:var(--warn)" href="#/mappings">${icon('alert', 13)} ${fa(new Set(unm.map((w) => w.column)).size)} ستون نگاشت‌نشده — تکمیل نگاشت‌ها</a>` : ''}
      </div>
      <div class="tbl-wrap" style="max-height:560px"><table class="tbl"><thead><tr>${r.headers.map((h) => `<th class="ltr">${esc(h)}</th>`).join('')}</tr></thead>
      <tbody>${r.rows.map((row) => `<tr>${row.map((v) => `<td class="small" style="max-width:280px"><div style="max-height:84px;overflow:hidden;white-space:pre-wrap">${esc(trunc(typeof v === 'string' ? v : JSON.stringify(v), 260))}</div></td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  },
  settingsTab() {
    const d = IT.ds;
    const kinds = S.boot.errors.kinds;
    return `<div class="card-b">
      <div class="form-grid">
        <div class="field"><label>عنوان نمایشی</label><input class="inp" id="st-title" value="${attr(d.title)}"></div>
        <div class="field"><label>نام فایل (خروجی)</label><input class="inp ltr" id="st-name" value="${attr(d.name)}"><div class="hint">پس از ویرایش دستی، نام دیگر خودکار به‌روز نمی‌شود.</div></div>
        <div class="field"><label>عنوان دسته‌بندی (برای نگاشت category_slug)</label><input class="inp" id="st-cat" value="${attr(d.category_label)}"></div>
        <div class="field"><label>سقف تعداد محصول</label><input class="inp" id="st-limit" type="number" value="${d.item_limit || ''}" placeholder="همه"><div class="hint">با افزایش سقف و زدن «ادامه»، استخراج از همان نقطه ادامه پیدا می‌کند.</div></div>
        <div class="field"><label>اسکیما</label><select class="inp" id="st-schema">${S.boot.schemas.map((s) => `<option value="${s.id}" ${s.id === d.schema_id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
        <div class="field"><label>محصولات تکراری</label><select class="inp" id="st-dups">${[['skip', 'رد شوند'], ['reuse', 'استفاده از داده‌ی قبلی'], ['rescrape', 'استخراج دوباره']].map(([k, l]) => `<option value="${k}" ${d.options.duplicates === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
      </div>
      <div class="lbl mt24">رفتار در برابر خطا</div>
      <div class="form-grid mt8">${Object.entries(kinds).map(([k, v]) => `<div class="field"><label class="small">${esc(v.title)}</label><select class="inp sm" data-pol="${k}">
        <option value="ask">${POLICY_LABEL.ask}</option>${v.actions.filter((a) => POLICY_LABEL[a]).map((a) => `<option value="${a}" ${d.policies[k] === a ? 'selected' : ''}>${POLICY_LABEL[a]}</option>`).join('')}</select></div>`).join('')}</div>
      <label class="check mt16"><input type="checkbox" id="st-show" ${d.options.show_browser ? 'checked' : ''}> نمایش مرورگر در حین استخراج</label>
      <div class="field mt16" style="max-width:520px"><label>${icon('sparkles', 14)} پس از پایان استخراج، تولید با هوش مصنوعی</label>
        <select class="inp" id="st-aiafter">${(() => { const a = d.options.ai_after; const cur = !a ? '' : a.mode === 'profile' ? `p:${a.profile_id}` : (a.mode || a);
          return [['', 'ندارد'], ['schema', 'ستون‌های AI اسکیما'], ['empty', 'همه‌ی ستون‌های خالی'], ...(S.boot.ai_profiles || []).map((p) => [`p:${p.id}`, `قالب: ${p.name}`])]
            .map(([k, l]) => `<option value="${k}" ${String(cur) === k ? 'selected' : ''}>${esc(l)}</option>`).join(''); })()}</select>
        <div class="hint">با «ادامه» یا استخراج دوباره، پس از پایان، ستون‌های انتخاب‌شده خودکار تولید یا تکمیل می‌شوند.</div></div>
      <div class="btns mt24"><button class="btn primary" data-act="savesettings">${icon('save', 16)} ذخیره‌ی تنظیمات</button>
        <button class="btn" data-act="ctl" data-do="retry-failed">${icon('refresh', 16)} صف‌کردن دوباره‌ی محصولات ردشده</button>
        <button class="btn" data-act="ctl" data-do="rediscover">${icon('search', 16)} بازخوانی فهرست دسته</button></div>
    </div>`;
  },
  act: {
    tab: (el) => { IT.tab = el.dataset.tab; Dataset.renderTab(); },
    ctl: async (el) => {
      if (el.dataset.do === 'stop' && !(await confirmDlg('پایان اجرا', 'اجرا متوقف می‌شود و وضعیتش «پایان‌یافته» ثبت می‌شود. بعداً هم می‌توانید از همین نقطه ادامه دهید.', 'پایان اجرا'))) return;
      await api(`/api/datasets/${S.params.id}/do/${el.dataset.do}`, { body: {} });
      Dataset.tick(S.params.id);
    },
    export: (el, ev) => { ev.preventDefault(); sessionStorage.setItem('export-ds', S.params.id); go('#/exports'); },
    rename: async () => {
      const v = await promptDlg('ویرایش عنوان', 'عنوان نمایشی بانک داده', IT.ds.title);
      if (v) { await api(`/api/datasets/${S.params.id}`, { method: 'PUT', body: { title: v } }); Dataset.tick(S.params.id); }
    },
    del: async () => {
      if (!(await confirmDlg('حذف بانک داده', `بانک «${esc(IT.ds.title)}» با همه‌ی محصولات و گزارش‌هایش حذف می‌شود. فایل‌های خروجی ساخته‌شده روی دیسک حذف نمی‌شوند.`, 'حذف', true))) return;
      await api(`/api/datasets/${S.params.id}`, { method: 'DELETE' });
      okToast('حذف شد.'); go('#/datasets');
    },
    fstatus: (el) => { IT.status = el.dataset.s; IT.page = 1; document.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b === el)); Dataset.loadItems(); },
    pg: (el) => { IT.page = Number(el.dataset.p); Dataset.loadItems(); },
    item: (el, ev) => { if (ev.target.closest('input,a,button')) return; openItem(Number(el.dataset.id)); },
    selclear: () => { IT.sel.clear(); Dataset.loadItems(); },
    seldel: async () => {
      if (!(await confirmDlg('حذف محصولات', `${fa(IT.sel.size)} محصول از این بانک حذف شود؟`, 'حذف', true))) return;
      await api('/api/items/bulk', { body: { ids: [...IT.sel], delete: true } });
      IT.sel.clear(); Dataset.loadItems();
    },
    selrescrape: async () => {
      await api('/api/items/bulk', { body: { ids: [...IT.sel], status: 'queued' } });
      IT.sel.clear();
      await api(`/api/datasets/${S.params.id}/do/resume`, { body: {} });
      okToast('محصولات انتخاب‌شده در صف استخراج دوباره قرار گرفتند.');
      Dataset.loadItems();
    },
    bulk: () => openBulk(),
    airun: () => { closeMenus(); openAIRun(IT.ds, [...IT.sel]); },
    aimenu: (el, ev) => { ev.stopPropagation(); const m = document.getElementById('ai-menu'); const was = m.classList.contains('hidden'); closeMenus(); if (was) m.classList.remove('hidden'); },
    aicol: () => { closeMenus(); openAIColumn(IT.ds, [...IT.sel]); },
    aiadd: () => { closeMenus(); openAIAdd(IT.ds); },
    selai: () => openAIRun(IT.ds, [...IT.sel]),
    selaiclear: async () => {
      if (!(await confirmDlg('حذف خروجی هوش مصنوعی', `خروجی‌های هوش مصنوعی ${fa(IT.sel.size)} محصول حذف و داده‌ی استخراج‌شده جایگزین شود؟`, 'حذف خروجی AI', true))) return;
      await api('/api/items/ai-clear', { body: { ids: [...IT.sel] } });
      okToast('خروجی‌های هوش مصنوعی حذف شد.');
      Dataset.loadItems(true);
    },
    savesettings: async () => {
      const pol = {};
      document.querySelectorAll('[data-pol]').forEach((s) => { pol[s.dataset.pol] = s.value; });
      const body = {
        title: document.getElementById('st-title').value, name: document.getElementById('st-name').value,
        category_label: document.getElementById('st-cat').value, item_limit: document.getElementById('st-limit').value,
        schema_id: Number(document.getElementById('st-schema').value), policies: pol,
        options: { duplicates: document.getElementById('st-dups').value, show_browser: document.getElementById('st-show').checked,
          ai_after: (() => { const v = document.getElementById('st-aiafter').value; return !v ? null : v.startsWith('p:') ? { mode: 'profile', profile_id: Number(v.slice(2)) } : { mode: v }; })() },
      };
      IT.ds = await api(`/api/datasets/${S.params.id}`, { method: 'PUT', body });
      okToast('تنظیمات ذخیره شد.');
      Dataset.tick(S.params.id);
    },
  },
  change: {
    sel: (el) => { const id = Number(el.dataset.id); el.checked ? IT.sel.add(id) : IT.sel.delete(id); el.closest('tr').classList.toggle('sel', el.checked); Dataset.updateSel(); },
    selall: (el) => { (IT.items?.items || []).forEach((i) => (el.checked ? IT.sel.add(i.id) : IT.sel.delete(i.id))); Dataset.loadItems(); },
  },
  input: {
    search: debounceInput((el) => { IT.q = el.value.trim(); IT.page = 1; Dataset.loadItems(); }),
  },
};

function debounceInput(fn) { let t; return (el) => { clearTimeout(t); t = setTimeout(() => fn(el), 350); }; }

export function logRow(r) {
  const ic = { warning: 'alert', error: 'alert', success: 'checkCircle', info: 'info', debug: 'code' }[r.level] || 'info';
  return `<div class="log-row"><span class="t">${jtime(r.ts)}</span><span class="lv ${r.level}">${icon(ic, 15)}</span>
    <div><div>${esc(r.message)}${r.item_id ? ` <span class="xs muted">· محصول ${fa(r.item_id)}</span>` : ''}</div>
    ${r.detail ? `<details><summary>جزئیات</summary><pre>${esc(r.detail)}</pre></details>` : ''}</div></div>`;
}

// ======================================================================
// ویرایشگر محصول (کشو)
// ======================================================================
async function openItem(id) {
  const it = await api(`/api/items/${id}`);
  const ids = (IT.items?.items || []).map((i) => i.id);
  const idx = ids.indexOf(id);
  const d = it.data || {};
  const layer = openLayer('drawer', `
    <div class="drawer-h">
      <h3 class="ellipsis">${esc(d.title || 'محصول')}</h3>${chip(it.status)}
      <button class="btn sm icon ghost" data-nav="${ids[idx - 1] || ''}" ${idx <= 0 ? 'disabled' : ''} title="قبلی">${icon('chevronRight', 16)}</button>
      <button class="btn sm icon ghost" data-nav="${ids[idx + 1] || ''}" ${idx < 0 || idx >= ids.length - 1 ? 'disabled' : ''} title="بعدی">${icon('chevronLeft', 16)}</button>
      <button class="btn sm icon ghost" data-close>${icon('x', 16)}</button>
    </div>
    <div class="drawer-b" id="item-body">${itemBody(it)}</div>
    <div class="drawer-f">
      ${/^https?:/.test(it.url) ? `<a class="btn" href="${attr(it.url)}" target="_blank" rel="noopener">${icon('external', 16)} صفحه‌ی منبع</a>` : ''}
      <button class="btn" data-rescrape>${icon('refresh', 16)} ${/^ai-generated:/.test(it.url) ? 'ساخت دوباره با AI' : 'استخراج دوباره'}</button>
      <select class="inp sm" style="width:auto;max-width:220px" data-aiprof><option value="empty">همه‌ی ستون‌های خالی</option><option value="schema">ستون‌های AI اسکیما</option>${(S.boot.ai_profiles || []).map((p) => `<option value="${p.id}">قالب: ${esc(p.name)}</option>`).join('')}</select><button class="btn soft" data-aigen>${icon('sparkles', 16)} تولید AI</button>
      <span class="grow"></span>
      <button class="btn" data-close>بستن</button>
      <button class="btn primary" data-save>${icon('save', 16)} ذخیره</button>
    </div>`);
  const box = layer.box;
  box.querySelectorAll('[data-nav]').forEach((b) => b.addEventListener('click', async () => {
    const n = Number(b.dataset.nav); if (!n) return; layer.close(); openItem(n);
  }));
  box.addEventListener('click', (ev) => {
    const r = ev.target.closest('[data-reset]');
    if (r) { r.closest('[data-col]').dataset.reset = '1'; r.closest('[data-col]').style.opacity = '.5'; toast('پس از ذخیره، مقدار استخراج‌شده بازگردانده می‌شود.'); }
    const fa2 = ev.target.closest('[data-aifield]');
    if (fa2) fieldAI(fa2, it, layer);
    const ar = ev.target.closest('[data-aireset]');
    if (ar) { ar.closest('[data-col]').dataset.aireset = '1'; ar.closest('[data-col]').style.opacity = '.5'; toast('پس از ذخیره، خروجی هوش مصنوعی این فیلد حذف می‌شود.'); }
  });
  const aiBtn = box.querySelector('[data-aigen]');
  if (aiBtn) aiBtn.addEventListener('click', async () => {
    aiBtn.disabled = true;
    aiBtn.innerHTML = `${icon('loader', 16, 'spin')} در حال تولید…`;
    const pv = box.querySelector('[data-aiprof]').value;
    const r = await api(`/api/items/${id}/ai`, { body: pv === 'empty' ? { all_empty: true } : pv === 'schema' ? { use_schema: true } : { profile_id: Number(pv) } }).catch((e) => ({ ok: false, error: e.message }));
    if (!r.ok) { errToast(new Error(r.error)); aiBtn.disabled = false; aiBtn.innerHTML = `${icon('sparkles', 16)} تولید AI`; return; }
    okToast(r.generated.length ? `${fa(r.generated.length)} فیلد تولید شد.` : 'فیلدی برای تولید نبود.');
    layer.close(); openItem(id); Dataset.loadItems(true);
  });
  box.querySelector('[data-save]').addEventListener('click', async () => {
    try {
      const payload = collectItem(box, it);
      await api(`/api/items/${id}`, { method: 'PUT', body: payload });
      okToast('ذخیره شد.');
      layer.close();
      Dataset.loadItems(true);
    } catch (e) { errToast(e); }
  });
  box.querySelector('[data-rescrape]').addEventListener('click', async (ev) => {
    ev.target.disabled = true;
    ev.target.innerHTML = `${icon('loader', 16, 'spin')} ${/^ai-generated:/.test(it.url) ? 'در حال تولید…' : 'در حال استخراج…'}`;
    try {
      await api(`/api/items/${id}/rescrape`, { body: {} });
      layer.close(); openItem(id); Dataset.loadItems(true);
    } catch (e) { errToast(e); ev.target.disabled = false; }
  });
}

function colValue(it, col) { return it.preview?.[col.key]?.value; }

function itemBody(it) {
  const d = it.data || {};
  const cols = it.schema?.columns || [];
  const imgCols = cols.filter((c) => ['image', 'images'].includes(c.input));
  let imgs = [];
  if (imgCols.length) imgCols.forEach((c) => { const v = colValue(it, c); imgs.push(...(Array.isArray(v) ? v : v ? [v] : [])); });
  else imgs = [d.featured_image, ...(d.gallery || [])];
  imgs = imgs.filter(Boolean);
  const kindLbl = { scraped: 'استخراجی', manual: 'دستی', constant: 'ثابت', mapping: 'نگاشت', auto: 'خودکار', ai: 'هوش مصنوعی' };
  let html = `
    <div class="sec-title">${icon('image', 16)} تصاویر <span class="line"></span><span class="xs muted">${fa(imgs.length)} تصویر</span></div>
    <div class="imgs">${imgs.map((u, i) => `<a href="${attr(imgSrc(u))}" target="_blank" rel="noopener" title="${i ? 'gallery_' + i : 'feature'}${/^https?:/.test(u) ? '' : ' · تولید هوش مصنوعی'}" style="position:relative">${/^https?:/.test(u) ? '' : `<span class="tag p" style="position:absolute;top:4px;right:4px;font-size:10px;padding:0 5px">AI</span>`}<img src="${attr(imgSrc(u))}" referrerpolicy="no-referrer" loading="lazy"></a>`).join('') || '<span class="muted small">تصویری استخراج نشده است.</span>'}</div>
    <div class="sec-title">${icon('columns', 16)} فیلدهای اسکیما <span class="line"></span></div>`;
  for (const col of cols) {
    if (col.include === false) continue;
    const v = colValue(it, col);
    const flag = it.preview?.[col.key]?.flag;
    const hasOv = col.key in (it.overrides || {});
    const head = `<div class="flex"><label class="lbl ltr" style="text-align:right">${esc(col.label || col.key)} <span class="xs muted">(${esc(col.key)})</span></label>
      <span class="tag" style="font-size:11px"><span class="kind-dot k-${col.kind}"></span>${kindLbl[col.kind] || col.kind}</span>
      ${flag === 'unmapped' ? `<span class="tag" style="color:var(--warn)">نگاشت‌نشده — مقدار پیشنهادی</span>` : ''}
      ${flag === 'missing' ? `<span class="tag" style="color:var(--err)">خالی</span>` : ''}
      ${col.kind !== 'constant' && col.default !== undefined && col.default !== null && col.default !== '' ? `<span class="tag" title="مقدار پیش‌فرض اسکیما — ${attr({ fill: 'اگر خالی بود', always: 'همیشه همین', prepend: 'افزودن به ابتدا', append: 'افزودن به انتها' }[col.default_mode || 'fill'])}">${icon('edit', 11)} پیش‌فرض اسکیما · ${({ fill: 'اگر خالی بود', always: 'همیشه', prepend: 'ابتدا', append: 'انتها' })[col.default_mode || 'fill']}</span>` : ''}
      ${hasOv ? `<span class="tag p">ویرایش‌شده</span><button class="btn xs ghost" data-reset title="بازگردانی به مقدار استخراج‌شده">${icon('refresh', 12)}</button>` : ''}
      <span class="grow"></span><button class="btn xs soft" data-aifield="${attr(col.key)}" title="تولید یا بازنویسی این فیلد با هوش مصنوعی">${icon('sparkles', 12)} ${['image', 'images'].includes(col.input) ? 'ساخت تصویر' : 'AI'}</button>
      ${col.key in (it.ai || {}) ? `<span class="tag p" title="${attr((it.ai[col.key].model || '') + ' · ' + (it.ai[col.key].mode || ''))}">${icon('sparkles', 11)} هوش مصنوعی${hasOv ? ' (کنار گذاشته شده)' : ''}</span><button class="btn xs ghost" data-aireset title="حذف خروجی هوش مصنوعی و بازگشت به داده‌ی استخراج‌شده">${icon('eraser', 12)}</button>` : ''}</div>`;
    html += `<div class="field mt16" data-col="${attr(col.key)}">${head}${colInput(col, v, it)}</div>`;
  }
  html += `
    <div class="sec-title">${icon('list', 16)} مشخصات استخراج‌شده <span class="line"></span><span class="xs muted">${fa((d.specifications || []).length)} ردیف</span></div>
    ${specsTable(d.specifications || [])}
    <details class="mt16"><summary class="lbl" style="cursor:pointer">داده‌ی خام استخراج‌شده (JSON)</summary><pre class="pathbox mt8" style="max-height:340px;overflow:auto;white-space:pre-wrap">${esc(JSON.stringify(d, null, 2))}</pre></details>`;
  return html;
}

export function specsTable(specs) {
  if (!specs.length) return '<div class="muted small">مشخصاتی استخراج نشده است.</div>';
  let g = null; let rows = '';
  for (const s of specs) {
    if (s.group && s.group !== g) { g = s.group; rows += `<tr class="g"><td colspan="2">${esc(g)}</td></tr>`; }
    rows += `<tr><td>${esc(s.name)}</td><td>${esc(s.value)}</td></tr>`;
  }
  return `<div style="border:1px solid var(--z-200);border-radius:14px;overflow:hidden"><table class="spec-tbl">${rows}</table></div>`;
}

export function toLines(v) { if (Array.isArray(v)) return v.join('\n'); return v ?? ''; }

export function colInput(col, v, it) {
  const inp = col.input || 'text';
  const k = attr(col.key);
  if (inp === 'bullet_groups') {
    const val = (v && typeof v === 'object') ? v : {};
    return `<div class="bullets-grid">${(col.groups || []).map((g) => `<div class="field"><span class="small"><b>${esc(g.label)}</b> <span class="xs muted ltr">${esc(g.key)}</span></span>
      <textarea class="inp" rows="5" data-bg="${attr(g.key)}" placeholder="هر خط یک بولت">${esc(toLines(val[g.key]))}</textarea></div>`).join('')}</div><div class="hint">هر خط یک بولت جداگانه است. در خروجی، هر بخش در ستون جدای خودش قرار می‌گیرد.</div>`;
  }
  if (inp === 'group') {
    const val = (v && typeof v === 'object') ? v : {};
    const lbl = { item_weight: 'وزن محصول (گرم)', item_width: 'عرض محصول', item_length: 'طول محصول', item_height: 'ارتفاع محصول', packaging_weight: 'وزن بسته (گرم)', packaging_width: 'عرض بسته', packaging_length: 'طول بسته', packaging_height: 'ارتفاع بسته' };
    return `<div class="dims-grid">${(col.subkeys || []).map((s) => `<div class="field"><span class="xs">${esc(lbl[s] || s)}</span><input class="inp sm ltr" data-sub="${attr(s)}" value="${attr(val[s] ?? '')}" inputmode="decimal"></div>`).join('')}</div><div class="hint">وزن به گرم و ابعاد به سانتی‌متر. موارد خالی را می‌توانید دستی تکمیل کنید.</div>`;
  }
  if (inp === 'specs') return `<textarea class="inp mono" rows="6" data-json>${esc(v ? JSON.stringify(v, null, 2) : '')}</textarea><div class="hint">فهرست مشخصات به‌شکل JSON؛ هر ردیف شامل group، name و value.</div>`;
  if (inp === 'json') return `<textarea class="inp mono" rows="3" data-json>${esc(v === undefined || v === null || v === '' ? '' : JSON.stringify(v, null, 2))}</textarea>`;
  if (inp === 'images') return `<textarea class="inp mono" rows="4" data-lines>${esc(toLines(v))}</textarea><div class="hint">هر خط، لینک یک تصویر گالری.</div>`;
  if (inp === 'image') return `<input class="inp mono" data-text value="${attr(v ?? '')}">`;
  if (inp === 'bool') return `<select class="inp" data-text><option value="false" ${String(v) !== 'true' ? 'selected' : ''}>false</option><option value="true" ${String(v) === 'true' ? 'selected' : ''}>true</option></select>`;
  if (inp === 'longtext' || inp === 'bullets') return `<textarea class="inp" rows="${inp === 'bullets' ? 4 : 5}" data-text>${esc(toLines(v))}</textarea>`;
  const ltr = col.kind === 'auto' || col.kind === 'mapping' || col.kind === 'constant';
  return `<input class="inp ${ltr ? 'ltr' : ''}" data-text value="${attr(typeof v === 'object' && v !== null ? JSON.stringify(v) : (v ?? ''))}">`;
}

export function readCol(el, col) {
  const inp = col.input || 'text';
  if (inp === 'bullet_groups') {
    const out = {};
    el.querySelectorAll('[data-bg]').forEach((t) => { out[t.dataset.bg] = t.value.split('\n').map((x) => x.replace(/^[•\-*]\s*/, '').trim()).filter(Boolean); });
    return out;
  }
  if (inp === 'group') {
    const out = {};
    el.querySelectorAll('[data-sub]').forEach((t) => { out[t.dataset.sub] = t.value.trim(); });
    return out;
  }
  const j = el.querySelector('[data-json]');
  if (j) {
    if (!j.value.trim()) return '';
    try { return JSON.parse(j.value); } catch (e) { throw new Error(`JSON ستون «${col.key}» معتبر نیست.`); }
  }
  const l = el.querySelector('[data-lines]');
  if (l) return l.value.split('\n').map((x) => x.trim()).filter(Boolean);
  const t = el.querySelector('[data-text]');
  return t ? t.value : '';
}

function same(a, b) { return JSON.stringify(a ?? '') === JSON.stringify(b ?? ''); }

function collectItem(box, it) {
  const aiClear = [];
  const aiSet = {};
  const overrides = { ...(it.overrides || {}) };
  const manual = { ...(it.manual || {}) };
  for (const col of it.schema.columns) {
    const el = box.querySelector(`[data-col="${CSS.escape(col.key)}"]`);
    if (!el) continue;
    if (el.dataset.aireset === '1') { aiClear.push(col.key); continue; }
    if (el.dataset.reset === '1') { delete overrides[col.key]; continue; }
    const v = readCol(el, col);
    if (el.dataset.aifilled === '1' && same(v, el._aiValue)) { aiSet[col.key] = v; delete overrides[col.key]; delete manual[col.key]; continue; }
    const orig = colValue(it, col);
    if (col.kind === 'manual') { if (!same(v, orig)) manual[col.key] = v; continue; }  // مقدار نمایش‌داده‌شده ممکن است پیش‌فرض اسکیما باشد
    if (!same(v, orig)) overrides[col.key] = v;
  }
  const out = { overrides, manual };
  if (aiClear.length) out.ai_clear = aiClear;
  if (Object.keys(aiSet).length) out.ai_set = aiSet;
  return out;
}

// ======================================================================
// تکمیل گروهی
// ======================================================================
async function openBulk() {
  const ds = IT.ds;
  const schema = schemaById(ds.schema_id) || S.boot.schemas[0];
  const manualCols = schema.columns.filter((c) => ['manual', 'ai'].includes(c.kind));
  const ovCols = schema.columns.filter((c) => ['mapping', 'constant'].includes(c.kind) || (c.input === 'group'));
  const n = IT.sel.size;
  const total = ds.counts.done + ds.counts.partial;
  const layer = openLayer('modal', `
    <div class="card-h"><h3>تکمیل گروهی فیلدهای دستی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b" style="max-height:66vh;overflow:auto">
      <div class="seg mb12" id="bulk-scope">
        <button class="${n ? 'on' : ''}" data-scope="sel" ${n ? '' : 'disabled'}>${fa(n)} محصول انتخاب‌شده</button>
        <button class="${n ? '' : 'on'}" data-scope="all">همه‌ی ${fa(total)} محصول این بانک</button>
      </div>
      <div class="hint mb12">فقط فیلدهایی که پر کنید اعمال می‌شوند؛ فیلدهای خالی تغییری در محصولات ایجاد نمی‌کنند.</div>
      ${manualCols.map((c) => `<div class="field mt16" data-col="${attr(c.key)}"><label class="lbl">${esc(c.label)} <span class="xs muted ltr">(${esc(c.key)})</span></label>${colInput(c, null, {})}</div>`).join('')}
      ${ovCols.length ? `<div class="sec-title mt24">جایگزینی مقدار ستون‌ها <span class="line"></span></div>` : ''}
      ${ovCols.map((c) => `<div class="field mt12" data-ovcol="${attr(c.key)}"><label class="lbl">${esc(c.label)} <span class="xs muted ltr">(${esc(c.key)})</span></label>${colInput(c, null, {})}</div>`).join('')}
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px">
      <button class="btn" data-close>انصراف</button><button class="btn primary" data-apply>${icon('check', 16)} اعمال</button>
    </div>`, { wide: true });
  const box = layer.box;
  let scope = n ? 'sel' : 'all';
  box.querySelectorAll('[data-scope]').forEach((b) => b.addEventListener('click', () => {
    scope = b.dataset.scope; box.querySelectorAll('[data-scope]').forEach((x) => x.classList.toggle('on', x === b));
  }));
  box.querySelector('[data-apply]').addEventListener('click', async () => {
    try {
      const manual = {};
      for (const c of manualCols) {
        const v = readCol(box.querySelector(`[data-col="${CSS.escape(c.key)}"]`), c);
        const empty = v === '' || (typeof v === 'object' && Object.values(v).every((x) => !x || (Array.isArray(x) && !x.length)));
        if (!empty) manual[c.key] = v;
      }
      const overrides = {};
      for (const c of ovCols) {
        const v = readCol(box.querySelector(`[data-ovcol="${CSS.escape(c.key)}"]`), c);
        if (c.input === 'group') { const nonEmpty = Object.fromEntries(Object.entries(v).filter(([, x]) => x)); if (Object.keys(nonEmpty).length) overrides[c.key] = nonEmpty; }
        else if (v !== '') overrides[c.key] = v;
      }
      let ids = [...IT.sel];
      if (scope === 'all') {
        const all = await api(`/api/datasets/${ds.id}/items?size=200&status=done,partial`);
        ids = all.items.map((i) => i.id);
        let p = 2;
        while (ids.length < all.total) { const more = await api(`/api/datasets/${ds.id}/items?size=200&status=done,partial&page=${p++}`); ids.push(...more.items.map((i) => i.id)); if (!more.items.length) break; }
      }
      if (!Object.keys(manual).length && !Object.keys(overrides).length) { toast('هیچ فیلدی پر نشده است.', 'err'); return; }
      if (Object.keys(overrides).some((k) => ovCols.find((c) => c.key === k)?.input === 'group')) {
        // ادغام زیرکلیدهای ابعاد با مقدار فعلی هر محصول
        for (const id of ids) {
          const it = await api(`/api/items/${id}`);
          const ov = { ...overrides };
          for (const c of ovCols.filter((c) => c.input === 'group' && overrides[c.key])) {
            ov[c.key] = { ...(it.preview?.[c.key]?.value || {}), ...overrides[c.key] };
          }
          await api('/api/items/bulk', { body: { ids: [id], manual, overrides: ov } });
        }
      } else {
        await api('/api/items/bulk', { body: { ids, manual, overrides } });
      }
      okToast(`روی ${fa(ids.length)} محصول اعمال شد.`);
      layer.close();
      Dataset.loadItems(true);
    } catch (e) { errToast(e); }
  });
}

// ======================================================================
// هوش مصنوعی در بانک داده و کشوی محصول (نسخه‌ی ۱.۳)
// ======================================================================
function closeMenus() { document.querySelectorAll('.menu').forEach((m) => m.classList.add('hidden')); }
document.addEventListener('click', (e) => { if (!e.target.closest('.menu-wrap')) closeMenus(); });

export function writeCol(el, col, v) {
  const inp = col.input || 'text';
  if (inp === 'bullet_groups') { el.querySelectorAll('[data-bg]').forEach((t) => { t.value = toLines((v || {})[t.dataset.bg]); }); return; }
  if (inp === 'group') { el.querySelectorAll('[data-sub]').forEach((t) => { const x = (v || {})[t.dataset.sub]; if (x !== undefined && x !== '') t.value = x; }); return; }
  const j = el.querySelector('[data-json]');
  if (j) { j.value = v === '' || v === null || v === undefined ? '' : JSON.stringify(v, null, 2); return; }
  const l = el.querySelector('[data-lines]');
  if (l) { l.value = toLines(v); return; }
  const t = el.querySelector('[data-text]');
  if (t) t.value = typeof v === 'object' && v !== null ? (Array.isArray(v) ? v.join('\n') : JSON.stringify(v)) : (v ?? '');
}

async function fieldAI(btn, it, layer) {
  const key = btn.dataset.aifield;
  const col = it.schema.columns.find((c) => c.key === key);
  const el = btn.closest('[data-col]');
  const isImg = ['image', 'images'].includes(col.input);
  const old = el.querySelector('.ai-inline');
  if (old) { old.remove(); return; }
  el.insertAdjacentHTML('beforeend', `<div class="ai-inline">
    <div class="flex wrap" style="gap:6px">
      ${isImg ? '' : `<div class="seg" data-mode><button class="on" data-m="rewrite">بازنویسی</button><button data-m="fill_missing">فقط جاهای خالی</button><button data-m="overwrite">از نو</button></div>`}
      <input class="inp sm grow" data-noai data-ins placeholder="${isImg ? 'توضیح تصویر (اختیاری) — مثلاً: نمای جانبی روی پس‌زمینه‌ی سفید' : 'دستور اختیاری — مثلاً: کوتاه‌تر و با تأکید بر سازگاری'}" style="min-width:200px">
      <button class="btn sm primary" data-go>${icon('sparkles', 14)} ${isImg ? 'ساخت تصویر' : 'تولید'}</button>
    </div><div class="xs muted mt8" data-st>${isImg ? 'تصویر ساخته و مستقیم به محصول افزوده می‌شود.' : 'نتیجه در فیلد قرار می‌گیرد؛ با «ذخیره» ثبت می‌شود.'}</div></div>`);
  const box = el.querySelector('.ai-inline');
  let mode = 'rewrite';
  box.querySelectorAll('[data-m]').forEach((b) => b.addEventListener('click', () => { mode = b.dataset.m; box.querySelectorAll('[data-m]').forEach((x) => x.classList.toggle('on', x === b)); }));
  const go_ = box.querySelector('[data-go]');
  go_.addEventListener('click', async () => {
    busy(go_, true, isImg ? 'در حال ساخت…' : 'در حال تولید…');
    try {
      const r = await assist('field', { item_id: it.id, column: key, mode, instruction: box.querySelector('[data-ins]').value, save: false });
      if (isImg) { okToast('تصویر ساخته شد.'); layer.close(); openItem(it.id); Dataset.loadItems(true); return; }
      writeCol(el, col, r.value);
      el.dataset.aifilled = '1';
      el._aiValue = readCol(el, col);
      box.querySelector('[data-st]').innerHTML = `${icon('check', 12)} تولید شد (${esc(r.provider)}). برای ثبت، «ذخیره» را بزنید.`;
    } catch (e) { noProviderHint(e); } finally { busy(go_, false); }
  });
  box.querySelector('[data-ins]').focus();
}

function aiProvSelect(provs, id = 'ai-prov') {
  return `<select class="inp sm" id="${id}"><option value="">اتصال پیش‌فرض</option>${provs.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>`;
}

async function openAIColumn(ds, sel) {
  const schema = schemaById(ds.schema_id) || S.boot.schemas[0];
  const cols = schema.columns.filter((c) => c.include !== false && !['auto'].includes(c.kind));
  const provs = (await api('/api/ai/providers').catch(() => ({}))).providers || [];
  const layer = openLayer('modal', `
    <div class="card-h"><h3>${icon('sparkles', 18)} تولید یک ستون با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b">
      <div class="form-grid">
        <div class="field"><label>ستون</label><select class="inp" id="ac-col">${cols.map((c) => `<option value="${attr(c.key)}">${esc(c.label || c.key)} (${esc(c.key)})</option>`).join('')}</select></div>
        <div class="field"><label>حالت</label><select class="inp" id="ac-mode"><option value="fill_missing">فقط محصولاتی که این ستون را خالی دارند</option><option value="rewrite">بازنویسی یکتا بر اساس مقدار فعلی</option><option value="overwrite">تولید از نو برای همه</option></select></div>
        <div class="field"><label>محدوده</label><select class="inp" id="ac-scope">${sel.length ? `<option value="selected">${fa(sel.length)} محصول انتخاب‌شده</option>` : ''}<option value="all">همه‌ی محصولات کامل و ناقص</option><option value="partial">فقط محصولات ناقص</option></select></div>
        <div class="field"><label>اتصال</label>${aiProvSelect(provs)}</div>
      </div>
      <div class="field mt16"><label>دستور (اختیاری)</label><textarea class="inp" id="ac-ins" rows="3" placeholder="مثلاً: توضیح کوتاه در یک جمله با ذکر کاربرد اصلی و خودروهای سازگار" data-ai-label="دستور تولید ستون"></textarea></div>
      <div class="hint mt8">کار در پس‌زمینه انجام و پیشرفتش بالای فهرست محصولات نمایش داده می‌شود. برای ستون‌های تصویری، تصویر ساخته می‌شود.</div>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" data-go>${icon('sparkles', 16)} شروع</button></div>`);
  const b = layer.box;
  b.querySelector('[data-go]').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    busy(btn, true, 'ثبت…');
    try {
      const scope = b.querySelector('#ac-scope').value;
      await api(`/api/datasets/${ds.id}/ai-column`, { body: { column: b.querySelector('#ac-col').value, mode: b.querySelector('#ac-mode').value,
        instruction: b.querySelector('#ac-ins').value, scope: scope === 'selected' ? 'all' : scope, item_ids: scope === 'selected' ? sel : null,
        provider_id: Number(b.querySelector('#ai-prov').value) || null } });
      okToast('تولید ستون آغاز شد.');
      layer.close();
      Dataset.aiJobs(ds.id);
    } catch (e) { noProviderHint(e); busy(btn, false); }
  });
}

async function openAIAdd(ds) {
  const spec = ds.options?.ai_generate || {};
  const provs = (await api('/api/ai/providers').catch(() => ({}))).providers || [];
  const layer = openLayer('modal', `
    <div class="card-h"><h3>${icon('sparkles', 18)} افزودن محصول با هوش مصنوعی</h3><span class="sp"></span><button class="btn sm icon ghost" data-close>${icon('x', 16)}</button></div>
    <div class="card-b">
      <div class="hint mb12">محصولات جدید بدون اسکرپ و بر اساس اسکیمای همین بانک ساخته می‌شوند و با محصولات فعلی تکراری نخواهند بود.</div>
      <div class="form-grid">
        <div class="field"><label>نوع محصول</label><input class="inp" id="aa-type" value="${attr(spec.product_type || ds.category_label || '')}" data-ai-label="نوع محصول"></div>
        <div class="field"><label>تعداد</label><input class="inp" id="aa-n" type="number" min="1" max="500" value="5"></div>
        <div class="field"><label>برندها (اختیاری)</label><input class="inp" id="aa-brands" value="${attr(spec.brands || '')}" data-ai-format="keywords"></div>
        <div class="field"><label>اتصال</label>${aiProvSelect(provs)}</div>
      </div>
      <div class="field mt16"><label>توضیحات تکمیلی (اختیاری)</label><textarea class="inp" id="aa-notes" rows="2" data-ai-label="توضیحات تکمیلی برای تولید محصولات">${esc(spec.notes || '')}</textarea></div>
      <label class="check mt12"><input type="checkbox" id="aa-img" ${spec.images?.enabled === false ? '' : 'checked'}> ساخت تصویر برای هر محصول</label>
    </div>
    <div class="drawer-f" style="border-radius:0 0 20px 20px"><button class="btn" data-close>انصراف</button><button class="btn primary" data-go>${icon('sparkles', 16)} افزودن</button></div>`);
  const b = layer.box;
  b.querySelector('[data-go]').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const type = b.querySelector('#aa-type').value.trim();
    if (!type) { toast('نوع محصول را بنویسید.', 'err'); return; }
    busy(btn, true, 'ثبت…');
    try {
      await api(`/api/datasets/${ds.id}/ai-add`, { body: { product_type: type, count: Number(b.querySelector('#aa-n').value || 5), brands: b.querySelector('#aa-brands').value.trim(),
        notes: b.querySelector('#aa-notes').value.trim(), provider_id: Number(b.querySelector('#ai-prov').value) || null,
        images: { ...(spec.images || {}), enabled: b.querySelector('#aa-img').checked, count: spec.images?.count || 1 } } });
      okToast('تولید محصولات جدید آغاز شد.');
      layer.close();
      Dataset.tick(ds.id);
    } catch (e) { noProviderHint(e); busy(btn, false); }
  });
}
