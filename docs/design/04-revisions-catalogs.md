# کنترل نسخه و انتشار کاتالوگ

## ریویژن‌ها (`studio/revisions.py`)

```python
revisions.record(entity, entity_id, snapshot: dict, actor="ui", action="edit", note="", force=False)
```

- اگر snapshot با نسخه‌ی قبل فرقی نداشته باشد، نسخه‌ی تازه‌ای ثبت نمی‌شود، مگر با `force`.
- `changes` به‌صورت خودکار ساخته می‌شود. snapshot‌ها «تخت» می‌شوند: کلیدهای تودرتو با نقطه از هم جدا می‌شوند (مثل `values.short_description` یا `compat.items`) و فهرست‌ها برگ حساب می‌شوند.
- شماره‌ی نسخه برای هر موجودیت از ۱ شروع می‌شود.
- **بازگردانی:** `revisions.restore(entity, id, rev)` تابع بازگرداننده‌ی ثبت‌شده‌ی آن موجودیت را صدا می‌زند، بعد همان snapshot را با `action=restore` نسخه‌ی تازه می‌کند.

| موجودیت | snapshot | بازگرداننده |
|---|---|---|
| `product` | `title`، `slug`، `brand_id`، `category_id`، `compat`، `values`، `status`، `note`، `images` (بدون فایل) | `workbench._restore` |
| `schema` | `name`، `description`، `usage`، `columns`، `is_default` | `seed_v2._restore_schema` |
| `template` | `name`، `description`، `config` | `product_catalog._restore_tpl` |
| `catalog` | `title`، `slug`، `description`، `template_id`، `selection`، `state` | `product_catalog._restore_cat` |
| `ref_brand` / `ref_category` | فیلدهای فهرست | `refdata._restore` |
| `vehicle_brand` / `vehicle_model` / `vehicle_trim` | فیلدهای خودرو | `vehicles.service._restorer` |

**قاعده:** هر کدی که داده‌ی این موجودیت‌ها را تغییر می‌دهد باید از تابع ذخیره‌ی همان موجودیت عبور کند (مثلاً `workbench.update_product` یا `workbench._save`) تا ریویژن ثبت شود. هیچ‌جا `UPDATE` مستقیم روی این جدول‌ها، بدون ریویژن، ننویسید. تنها استثنا بازگرداننده‌هاست، که بعدشان خود `restore` نسخه ثبت می‌کند.

**فایل‌ها:** حذف تصویر از محصول فایل را پاک نمی‌کند، تا بازگردانی نسخه‌ی قبل تصویر را برگرداند. پاک‌سازی فایل‌های بی‌استفاده یک ابزار جداست (برای نسخه‌های بعد).

**API:**

| مسیر | کار |
|---|---|
| `GET /api/revisions?entity&entity_id` | خط زمانی |
| `GET /api/revisions?entity&page&actor` | تازه‌ترین‌ها |
| `GET /api/revisions/get?entity&entity_id&rev` | یک نسخه |
| `GET /api/revisions/compare?entity&entity_id&a&b` | مقایسه |
| `POST /api/revisions/restore` | بازگردانی |

## کیفیت (ماژول `quality`)

`score(product)` خروجی `{score, errors[], warnings[], min, ready}` دارد. امتیاز این‌طور محاسبه می‌شود: ۱۰۰ − ۱۵×خطا − ۵×هشدار.

- **خطاها:** عنوان کوتاه، اسلاگ نامعتبر، نبودن برند یا دسته (اگر اسکیما چنین ستونی داشته باشد)، نبودن تصویر، خالی بودن ستون اجباری.
- **هشدارها:** عنوان بلند، تصویر کوچک، نبودن گالری، سازگاری خودکار تأییدنشده، متن بلند کوتاه، واژه‌ی ممنوع.

تنظیمات در `settings.quality` است. امتیاز در هر `_save` محاسبه و در `wb_products.quality` ذخیره می‌شود.

**دروازه‌ها:**

- `status=approved` با خطای کیفیت رد می‌شود، مگر با `force`.
- کاتالوگ با `require_ready` و `min_quality` محصولات را فیلتر می‌کند.

## انتشار کاتالوگ (`studio/product_catalog.py`)

1. `select_products(catalog)`: بانک‌ها، وضعیت‌ها، برند و دسته، شامل و مستثنی، و دروازه‌ی کیفیت. محصولات کنارگذاشته با دلیل برگردانده می‌شوند.
2. کپی تصاویر نهایی به `fill(images.path, ctx)`. پیوند تصویرها (`img_map`) برای ستون‌های نقش `feature` و `gallery` ساخته می‌شود.
3. برای هر خروجی، `_records` ساخته می‌شود:
   - **محصولات:** `product_value` و بعد `structured`.
   - **برندها، دسته‌ها، خودروها، سازگاری:** از داده‌های مرجع و `compat.describe`.
   - بعد `_write` فایل JSON، CSV یا XLSX را می‌نویسد. Excel راست‌به‌چپ است و شیت `info` دارد.
   - اگر مسیر نشانه‌ی محصول داشته باشد، برای هر محصول یک فایل نوشته می‌شود.
4. `cat_release_items`: یک ردیف برای هر محصول با `uid`، `product_rev` و رکورد اولین خروجی محصولات.
5. **diff با آخرین انتشار کامل:** موارد تازه و حذف‌شده با `uid`، موارد تغییرکرده با `revisions.diff` روی رکوردها.
6. `manifest.json`، ZIP، و snapshot الگو، اسکیماها و انتخاب در `cat_releases.snapshot`.

انتشار تغییرناپذیر است: ویرایش الگو یا محصولات فقط روی انتشارهای بعدی اثر دارد. ساخت در یک thread پس‌زمینه انجام می‌شود (`RELEASES`). اگر استودیو حین ساخت بسته شود، انتشار نیمه‌کاره «خطا» علامت می‌خورد (`recover`).

## الگوی خروجی (`tpl_outputs.config`)

```json
{"root": "{catalog}-r{release}", "zip": true, "manifest": true,
 "images": {"enabled": true, "path": "images/{slug}/{name}.{ext}", "feature_name": "feature", "gallery_name": "gallery_{n}",
            "which": "all|feature", "link": "relative|prefix|source", "prefix": ""},
 "outputs": [{"id": "o1", "name": "محصولات", "kind": "products|brands|categories|vehicles|compatibility",
              "format": "json|xlsx|csv", "schema_id": 1, "path": "data/products.json", "fields": [...], "json_wrap": ""}]}
```

`normalize_config` و `validate_config` مسیرها را تمیز می‌کنند (بدون `..`) و این قاعده‌ها را بررسی می‌کنند:

- مسیر خروجی‌ها یکتا باشد.
- فایل جدا برای هر محصول فقط در خروجی JSON محصولات ممکن است.
- مسیر تصاویر `{slug}`، `{uid}` یا `{id}` داشته باشد.
- مسیر تصاویر `{name}` یا `{n}` داشته باشد.
