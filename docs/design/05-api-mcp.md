# API و MCP

همه‌ی مسیرها با `web.route` ثبت می‌شوند.

- **بدنه‌ی درخواست:** JSON است و به‌صورت `body` به تابع می‌رسد.
- **خطاها:** `ValueError` ← ۴۰۰ با پیام فارسی؛ `PermissionError` ← ۴۰۳؛ ماژول غیرفعال ← ۵۰۳.
- **هدر `X-Studio-Client`** کانال درخواست را مشخص می‌کند: `ui`، `mcp` یا `api`. همین در گزارش‌ها و ریویژن‌ها ثبت می‌شود. تابع کمکی‌اش `web.actor_of(request)` است.
- **کار سنگین** با `run_in_threadpool` اجرا می‌شود. کارهای طولانی (ورود بانک، کار AI، انتشار) در thread پس‌زمینه انجام می‌شوند و وضعیتشان در جدول ثبت است.

## مسیرهای نسخه‌ی ۲ (`studio/api_v2.py` و ماژول‌ها)

| گروه | مسیرها |
|---|---|
| عمومی | `GET /api/overview` · `GET /api/modules` · `PUT /api/modules/{id}` · `GET/POST /api/users` · `PUT /api/users/{id}` |
| ریویژن | `GET /api/revisions` · `GET /api/revisions/get` · `GET /api/revisions/compare` · `POST /api/revisions/restore` |
| مرجع | `GET/POST /api/ref/{brand,category}` (`?category_id&inherit` برای برندهای یک دسته) · `GET/PUT/DELETE /api/ref/{kind}/{id}` · `GET /api/ref/category/tree` · `POST …/bulk` (`ids`, `action`, `value`) · `POST …/apply` (`items`) · `GET …/export?format=xlsx\|csv\|json&ids` · `GET …/unmatched` · `POST …/link` · `POST …/add-unmatched` · `POST …/import` (`data_url`, `name`, `mapping`) |
| خودروها | `GET /api/vehicles/stats` · `…/brands` · `…/brands/{id}/tree` · `…/search` · `POST …/describe` · `POST …/normalize` · `POST …/suggest` (`ai: true`) · `POST …/import` · `GET …/export?format=xlsx` · `POST …/ai-english` · `POST/GET/PUT/DELETE /api/vehicles/{brand,model,trim}/{id}` |
| ویرایشگر | `GET/POST /api/wb/banks` · `GET/PUT/DELETE /api/wb/banks/{id}` · `POST …/add-datasets` · `POST …/do/{stop,resume,rescore}` · `POST …/ai` · `GET /api/wb/products` (فیلترها: `bank_id`، `status`، `filter`، `q`، `brand_id`، `category_id`، `sort`، `page`، `size`، `ids`) · `GET/PUT/DELETE /api/wb/products/{id}` · `POST /api/wb/products/bulk` · `POST /api/wb/products/bulk-images` · `POST …/{id}/images/{upload,url,generate,delete,make_feature,move,edit,reset_edit,rembg,reprocess}` · `POST …/{id}/ai` · `POST …/{id}/compat-suggest` · `GET …/{id}/sources` · `POST /api/wb/from-legacy/{export_id}` |
| کیفیت | `GET /api/quality/products/{id}` · `POST /api/quality/rescore` · `GET/PUT /api/quality/settings` |
| تکراری | `GET /api/dupes` · `POST /api/dupes/scan` · `POST /api/dupes/{id}/dismiss` · `POST /api/dupes/merge` |
| کاتالوگ | `GET /api/cat/meta` · `GET/POST /api/cat/templates` · `POST /api/cat/templates/preview` · `GET/PUT/DELETE /api/cat/templates/{id}` · `GET/POST /api/cat/catalogs` · `GET/PUT/DELETE /api/cat/catalogs/{id}` · `GET …/{id}/preview` · `POST …/{id}/release` · `GET …/{id}/releases` · `GET/DELETE /api/cat/releases/{id}` · `GET …/{id}/items` · `GET /api/cat/releases/compare?a&b` |
| پشتیبان | `GET/POST /api/backups` · `POST /api/backups/restore` · `POST /api/backups/cancel-restore` · `POST /api/backups/upload` · `DELETE /api/backups/{name}` |
| ورود فایل | `GET /api/import/specs` · `GET /api/import/sample/{brand,category,vehicles,raw}?format=xlsx\|csv\|json` · `POST /api/import/analyze` · `POST /api/datasets/import-file` |
| هوش مصنوعی (ماژول ai) | `POST /api/ref/{kind}/ai-complete` · `…/ai-match` · `…/ai-generate` · `POST /api/cat/templates/ai` · `POST /api/dupes/{id}/ai` · `POST /api/import/ai-map` |
| راهنما | `GET /api/docs` · `GET /api/docs/{path}` |

### عملیات گروهی محصولات (`POST /api/wb/products/bulk`)

انتخاب محصولات:

- `ids: [..]`، یا
- `filter: {bank_id, status, q, filter, brand_id, category_id}`.

عملیات‌ها (قابل ترکیب):

| کلید | شکل |
|---|---|
| `set` | `{key: value}` |
| `find_replace` | `{key, find, replace, regex}` |
| `prepend` / `append` | `{key: text}` |
| `apply_default` | `[keys]` و `default_mode` |
| `brand` / `category` | شناسه یا `null` |
| `compat` | `{mode: set\|add\|remove, value}` |
| `status` / `note` | مقدار |

خروجی: `{updated, total, errors[{id, error}]}`.

## MCP (`studio/mcp_core.py`)

- **دکوراتور:** `@tool(name, description, props, required, write=, destructive=, module=)`. با `module` ابزار وقتی ماژولش خاموش است در `tools/list` نمی‌آید و فراخوانی‌اش خطا می‌دهد.
- **ابزارها کلاینت همان HTTP API هستند** (`StudioAPI`، با هدر `X-Studio-Client: mcp`). پس منطق فقط یک جا نوشته می‌شود.
- **`INSTRUCTIONS`** روند کار را برای ایجنت‌ها توضیح می‌دهد. با هر قابلیت تازه به‌روزش کنید.
- **ابزارهای نسخه‌ی ۲:**
  - ماژول‌ها
  - داده‌ی مرجع
  - خودروها و سازگاری
  - بانک‌های تمیز و محصولات (خواندن، ویرایش، گروهی، تصاویر، AI)
  - کیفیت و تکراری
  - الگو، کاتالوگ و انتشار
  - ریویژن‌ها
  - پشتیبان

### هوش مصنوعی در بخش‌های مرجع و کمکی (`studio/ai_tasks.py`)

همه‌ی این کارها فقط **پیشنهاد** برمی‌گردانند و چیزی ذخیره نمی‌کنند؛ ذخیره با مسیرهای معمولی (`/apply`، `/link`، ذخیره‌ی الگو، ادغام) و با ریویژن انجام می‌شود. پرامپت‌ها با `TASK: <name>` شروع می‌شوند (سرویس ساختگی آزمون‌ها بر همین اساس پاسخ می‌دهد) و هر درخواست با `set_context` برچسب می‌خورد. خطای سرویس AI (`AIError`) در `web.route` به ۴۰۰ با پیام خوانا تبدیل می‌شود.
