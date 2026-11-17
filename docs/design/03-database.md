# پایگاه داده

SQLite در حالت WAL است و هر thread اتصال خودش را دارد (`db.conn()`). JSON در ستون‌های متنی ذخیره می‌شود و با `db.jload` و `db.jdump` خوانده و نوشته می‌شود.

## مهاجرت

- **جدول‌های نسخه‌ی ۱:** `SCHEMA_SQL` در `db.py` (`CREATE … IF NOT EXISTS`) و چند `ALTER` در `db.init()`.
- **نسخه‌ی ۲ به بعد:** فقط از مهاجرت‌های نسخه‌دار ماژول‌ها (`schema_migrations`). هسته خودش ماژول `core` است:
  - `core:1`: جدول‌های تازه.
  - `core:2`: ستون `schemas.usage` و کاربر مدیر.
  - `core:3` (نسخه‌ی ۲.۱): `ref_brands.category_ids`، `ref_brands.description`، `ref_categories.description`.
- پس از مهاجرت، `seed_v2.run()` این کارها را انجام می‌دهد:
  - تبدیل نگاشت‌های برند و دسته‌ی نسخه‌ی ۱ به فهرست مرجع (فقط اگر فهرست خالی باشد).
  - افزودن ستون «خودروهای سازگار» به اسکیمای مگا کارز (یک بار).
  - ساخت الگوهای خروجی پیش‌فرض.

هیچ داده‌ای حذف یا بازنویسی نمی‌شود. نصب نسخه‌ی ۱.۶ با همه‌ی بانک‌ها و اسکیماهایش مستقیم بالا می‌آید.

## جدول‌های نسخه‌ی ۲ (هسته)

| جدول | نقش | ستون‌های مهم |
|---|---|---|
| `users` | کاربران | `role` (`admin`، `operator`)، `active` |
| `revisions` | نسخه‌ها | `entity`، `entity_id`، `rev` (یکتا با هم)، `snapshot` (JSON کامل)، `changes` (فهرست `{field, old, new}`)، `actor` (`ui`، `ai`، `mcp`، `api`، `system`)، `user_id`، `action`، `note` |
| `ref_brands` | برندهای مرجع | `name`، `name_en`، `slug` (یکتا)، `aliases`، `country`، `description`، `active`، `category_ids` (JSON؛ دسته‌هایی که برند در آن‌ها نمایش داده می‌شود — `core:3`) |
| `ref_categories` | دسته‌های مرجع | به‌علاوه‌ی `parent_id`، `sort` و `description` (`core:3`) |
| `wb_banks` | بانک‌های تمیز | `schema_id`، `dataset_ids`، `options` (`rembg`، `align`، `max_images`، `compat_suggest`، …)، وضعیت و پیشرفت ورود |
| `wb_products` | محصولات تمیز | `uid` (یکتا)، `title`، `slug`، `brand_id`، `category_id`، `compat`، `values_json`، `images`، `flags`، `status`، `quality` و `quality_detail`، `sources`، `merged_into`، `rev`، `meta` (`brand_raw`، `compat_suggest`، `edited`، …) |
| `tpl_outputs` | الگوهای خروجی | `config`: `root`، `outputs[]`، `images`، `zip`، `manifest` |
| `cat_catalogs` | کاتالوگ‌ها | `slug`، `template_id`، `selection`، `state` |
| `cat_releases` | انتشارها | `number` (یکتا در کاتالوگ)، وضعیت و پیشرفت، `root`، `files`، `stats`، `diff`، `snapshot` (الگو و اسکیماهای همان لحظه) |
| `cat_release_items` | اقلام هر انتشار | `uid`، `product_rev`، `record` (رکورد اصلی) |
| `schema_migrations` | مهاجرت‌ها | `module`، `version` |

## جدول‌های ماژول‌ها

| ماژول | جدول | نکته |
|---|---|---|
| `vehicles` | `veh_brands` | اسلاگ یکتای سراسری |
| | `veh_models` | `brand_id`، اسلاگ یکتا در برند |
| | `veh_trims` | `model_id`، اسلاگ یکتا در مدل؛ `auto_en` یعنی نام انگلیسی خودکار و نیازمند بازبینی |
| `dedup` | `dup_pairs` | `a_id`، `b_id`، `score`، `reasons`، `status` (`open`، `merged`، `dismissed`) |

## ساختارهای JSON

**سازگاری** (`wb_products.compat`):

```json
{"all": true}
{"all": false, "items": [{"t": "brand", "id": 3}, {"t": "model", "id": 51}, {"t": "trim", "id": 120}]}
```

`vehicles.service.normalize` اعتبار سنجی می‌کند (فقط شناسه‌های موجود در بانک). مواردی را که زیرمجموعه‌ی یک انتخاب بالاتر باشند حذف می‌کند و لیست خالی را به `{"all": true}` تبدیل می‌کند.

**تصاویر محصول** (`wb_products.images`): آرایه‌ای که عضو اولش تصویر شاخص است.

```json
{"id": 3, "src": "https://…", "origin": "source|upload|url|ai|legacy", "raw": "bank-1/P1-…/img-3_raw.jpg",
 "rembg": "…_raw_rembg.png", "edit": "…_edit.png", "final": "…/img-3.png", "recipe": {…}|null, "use_rembg": true, "w": 1280, "h": 1280}
```

**دستور ویرایش تصویر** (`recipe`):

```json
{"rotate": 90, "flip_h": false, "flip_v": false, "erase": [{"size": 40, "points": [[x, y], …]}],
 "crop": {"x": 10, "y": 10, "w": 200, "h": 300}, "adjust": {"hue": 0, "saturation": 100, "brightness": 100, "contrast": 100}, "bg": "#ffffff"|null}
```

ترتیب اجرا: قرینه ← چرخش ← پاک‌کن ← برش ← رنگ ← پس‌زمینه. مختصات پاک‌کن و برش در فضای تصویر پس از چرخش است.

## آماده برای داده‌ی پیچیده‌تر

- **فیلد تازه برای محصولات** نیازی به تغییر جدول ندارد: یک ستون در اسکیما کافی است و مقدار در `values_json` ذخیره می‌شود.
- **موجودیت تازه** (ویدیو، قیمت‌گذاری، موجودی، …): در یک ماژول با جدول‌های پیشوندی و ارجاع نرم ساخته می‌شود. با حذف ماژول، جدول‌ها بی‌استفاده می‌مانند و هسته آسیبی نمی‌بیند.
- **ریویژن‌ها** عمومی‌اند: هر موجودیتی با `revisions.record` نسخه‌دار می‌شود.
- **مهاجرت به پایگاه داده‌ی دیگر** (مثلاً PostgreSQL برای چندکاربره شدن): همه‌ی دسترسی‌ها از توابع `db.q`، `db.q1`، `db.ex`، `db.update` و `db.val` می‌گذرند و جای تغییر در یک لایه متمرکز است.

## پشتیبان

`backup.create` از API پشتیبان‌گیری SQLite استفاده می‌کند؛ نتیجه حتی وسط کار سازگار است. بازگردانی در شروع بعدی انجام می‌شود (`backup.apply_pending`، پیش از `db.init`).

## نمایش برند در دسته (نسخه‌ی ۲.۱)

`refdata.related_categories(cid)` = خود دسته + والدها + زیرشاخه‌ها. برندی که `category_ids` آن با این مجموعه اشتراک داشته باشد در آن دسته نمایش داده می‌شود (`GET /api/ref/brand?category_id=N&inherit=1`؛ با `inherit=0` فقط وصل مستقیم). حذف دسته آن را از `category_ids` برندها هم برمی‌دارد (با ریویژن).

## داده‌ی خام از فایل (نسخه‌ی ۲.۱)

`raw_import.import_file` یک بانک داده‌ی خام با منبع مجازی `file-import` می‌سازد. هر ردیف یک `items` با `status=done` و `data` به کلیدهای استاندارد (`title`، `brand`، `category`، `breadcrumb`، `specifications`، `featured_image`، `gallery`، …) است. ستون‌های ناشناخته با همان سرستون در `data` می‌مانند. مشخصات ستون‌ها و فایل نمونه در `import_specs.SPECS` تعریف شده و راهنما، نمونه و خواندن فایل از همین یک منبع ساخته می‌شوند.
