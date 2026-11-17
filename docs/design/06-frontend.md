# رابط کاربری

رابط با **JavaScript خالص و ES modules** نوشته شده و فرایند build ندارد. همه‌ی فایل‌ها در `studio/static/` هستند و به همان شکل سرو می‌شوند.

| فایل | نقش |
|---|---|
| `index.html`، `app.css` | قالب و همه‌ی سبک‌ها (توکن‌های رنگ در `:root`، فونت IRANYekanX، راست‌به‌چپ) |
| `js/core.js` | `api()`، `openLayer` و `closeLayers`، `confirmDlg` و `promptDlg`، `toast`، `every()`، `fa`/`num`/`jdate`، `fileUrl` |
| `js/app.js` | مسیریاب hash (`ROUTES`)، منو (`NAV` با بخش‌ها و شناسه‌ی ماژول)، نگاشت راهنما (`HELP`)، تور آشنایی، توزیع رویدادها |
| `js/widgets.js` | اجزای مشترک نسخه‌ی ۲: خط زمانی نسخه‌ها و مقایسه، انتخابگر برند و دسته، نمایش سازگاری، نشان کیفیت و وضعیت |
| `js/pages_editor.js` | بانک‌های تمیز، کشوی محصول، عملیات گروهی، صف بازبینی، تکراری‌ها |
| `js/pages_catalog2.js` | کاتالوگ‌ها، انتشارها، الگوهای خروجی |
| `js/pages_refdata.js` | برندها و دسته‌ها |
| `js/pages_system.js` | پیشخوان، ماژول‌ها، پشتیبان، کاربران، نسخه‌ها، راهنما (نمایش Markdown) |
| `js/mod_vehicles.js` | صفحه‌ی خودروها و `openCompatPicker` |
| `js/mod_image_editor.js` | ویرایشگر تصویر (`openImageEditor`) |
| `js/pages_main.js`، `pages_config.js`، `pages_tools.js`، `pages_ai.js`، `pages_mcp.js`، `pages_logs.js`، `pages_catalogs.js` | صفحه‌های نسخه‌ی ۱ (داده‌ی خام، منابع، اسکیماها، تنظیمات، AI، MCP، گزارش‌ها، خروجی‌های نسخه‌ی ۱) |

## الگوی صفحه

```js
export const MyPage = {
  title: 'عنوان', crumb: 'زیرعنوان',
  top: (params) => `<button data-act="x">…</button>`,   // دکمه‌های بالای صفحه
  async render(params) { return `<div>…</div>`; },       // HTML اولیه
  async mount(view, params) { … every(3000, () => …); },  // بارگذاری داده و تایمرها (خودکار پاک می‌شوند)
  act: { x: (el, ev) => {} },        // کلیک روی [data-act="x"]
  change: { y: (el) => {} },          // [data-change="y"]
  input: { z: (el) => {} },           // [data-input="z"]
};
```

- **ثبت صفحه:** در `app.js` با `lazy('./file.js', 'Name')` و یک ورودی در `ROUTES`. اگر صفحه به ماژولی تعلق دارد، شناسه‌ی ماژول را به‌عنوان عنصر چهارم بدهید.
- **مودال‌ها و کشوها:** با `openLayer('modal'|'drawer', html, {wide})` باز می‌شوند. با Escape یا تغییر صفحه بسته می‌شوند.
- **ویرایشگر فیلد بر اساس نوع ستون:** `colInput`، `readCol` و `writeCol` از `pages_main.js`. برای هر نوع ورودی تازه همین‌جا اضافه کنید.

## ظاهر

- **رنگ اصلی:** `--primary: #4f39f6`. پیام‌ها با `ok`، `warn`، `err` و `info` رنگ‌بندی می‌شوند.
- **اجزای رایج:**
  - `.card`، `.card-h`، `.card-b`
  - `.btn` با گونه‌های `primary`، `soft`، `ghost`، `danger` و اندازه‌های `sm`، `xs`، `icon`
  - `.chip`، `.tag`، `.seg`، `.chipbtn`
  - `.tbl` و `.pager`
  - `.alert`
  - `.pick-list` و `.pick`
  - `.kpi-line`، `.kpis`
  - `.grid2`، `.split`
- **آیکون‌ها:** در `icons.js` (سبک Lucide) با `icon(name, size)`.
- **فارسی:** اعداد با `fa()` و `num()`، تاریخ جلالی با `jdate()`. مسیرها، اسلاگ‌ها و کد با کلاس `ltr` و `mono`.

## پیش‌نمایش ویرایشگر تصویر

پیش‌نمایش روی `<canvas>` ساخته می‌شود و با خروجی سرور یکی است:

- ترتیب قرینه، چرخش، پاک‌کن و برش دقیقاً مثل سرور است.
- فیلتر رنگ با `ctx.filter = hue-rotate() saturate() brightness() contrast()` اعمال می‌شود. سرور در `image_editor.apply` همین ماتریس‌های CSS را پیاده کرده است.

اگر ابزار تازه‌ای به ویرایشگر اضافه می‌کنید، آن را در هر دو طرف پیاده کنید و ترتیب اجرا را حفظ کنید.
