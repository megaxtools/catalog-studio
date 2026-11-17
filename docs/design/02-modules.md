# ماژول‌ها و راهنمای ساخت ماژول تازه

## چارچوب

چارچوب ماژول‌ها در `studio/modules/__init__.py` است. هر ماژول یک `Module` است:

```python
Module(
    id="vehicles", name="خودروها و سازگاری", version="1.0.0",
    description="…",
    core=False,                 # هسته قابل خاموش کردن نیست
    default_enabled=True,
    requires=("ai",),           # وابستگی‌ها
    migrations=[(1, "CREATE TABLE …; CREATE INDEX …"), (2, callable)],
    init=seed_fn,               # پس از مهاجرت‌ها (داده‌ی اولیه)
    health=lambda: (True, "۱۸۶ برند"),
    tables=["veh_brands", …],   # برای مستندات و صفحه‌ی ماژول‌ها
    paths=[(("POST",), r"^/api/…")],  # فقط برای ماژول‌های داخلی قدیمی: نسبت دادن مسیرهای موجود
    on_toggle=fn,               # هنگام روشن/خاموش شدن
)
```

### چرخه‌ی بارگذاری (`modules.load_all`، در `create_app`)

1. ثبت مانیفست ماژول‌های داخلی (`modules/builtin.py`): هسته، داده‌ی خام، ویرایشگر، کاتالوگ، الگوها، داده‌ی مرجع، استخراج، صف، AI، حذف پس‌زمینه، ترازبندی، MCP و خروجی نسخه‌ی ۱.
2. پیمایش زیرپوشه‌های `studio/modules/` و import هرکدام. اگر import خطا بدهد، ماژول با `status=error` ثبت می‌شود و بقیه ادامه می‌دهند.
3. اجرای مهاجرت‌های اجرانشده‌ی هر ماژول در یک تراکنش. نسخه‌های اجراشده در `schema_migrations(module, version)` ثبت می‌شوند. اگر مهاجرتی خطا بدهد، فقط همان ماژول غیرفعال می‌شود.
4. اجرای `init` هر ماژول سالم.

### دروازه‌ها

- **مسیرهای HTTP:** `web.route(path, methods, module="id")`. اگر ماژول غیرفعال یا خراب باشد، پاسخ ۵۰۳ با پیام فارسی برمی‌گردد. مسیرهای ماژول‌های داخلی قدیمی با الگوهای `paths` به ماژولشان نسبت داده می‌شوند (`modules.module_for_path`).
- **کد هسته:** `modules.is_enabled("id")` برای رفتار اختیاری، و `modules.require("id")` برای خطای فارسی.
- **رابط:** هر مسیر و منو در `app.js` شناسه‌ی ماژول دارد و با `S.boot.modules` پنهان می‌شود. صفحه‌های ماژول‌ها تنبل import می‌شوند، پس اگر فایل JS یک ماژول خراب باشد فقط همان صفحه خطا می‌دهد.
- **ارتباط هسته با ماژول‌ها فقط از رابط‌های نازک:** مثلاً `studio/compat.py` برای خودروها. اگر ماژول خاموش یا حذف باشد، رفتار پیش‌فرض امن است («همه‌ی خودروها»).

### وضعیت روشن/خاموش

وضعیت در `settings.modules = {id: bool}` ذخیره می‌شود. API آن `GET /api/modules` و `PUT /api/modules/{id}` است و صفحه‌اش «سیستم ← ماژول‌ها». خاموش کردن داده‌ای را پاک نمی‌کند.

## ماژول‌های موجود

| شناسه | نوع | جدول‌ها | نکته |
|---|---|---|---|
| `vehicles` | بسته‌ای | `veh_brands`، `veh_models`، `veh_trims` | `service.py`: بانک، سازگاری، تطبیق متن، AI. داده‌ی اولیه `data/cars-db.json` |
| `image_editor` | بسته‌ای | — | `apply(img, recipe)` معادل فیلترهای CSS؛ رابط: `static/js/mod_image_editor.js` |
| `quality` | بسته‌ای | — (امتیاز در `wb_products.quality`) | `score(product)` و تنظیمات `settings.quality` |
| `dedup` | بسته‌ای | `dup_pairs` | `scan`، `merge` |
| `scraper`، `queue`، `ai`، `rembg`، `align`، `mcp`، `legacy_export` | داخلی | جدول‌های نسخه‌ی ۱ | دروازه با الگوی مسیر |

## ساخت ماژول تازه (مثال: ویرایشگر ویدیو)

1. پوشه‌ی `studio/modules/video_editor/` با `__init__.py` بسازید:

```python
from ... import db
from ...web import route, pid, actor_of
from .. import Module

MIGRATIONS = [(1, """
CREATE TABLE IF NOT EXISTS vid_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,           -- ارجاع نرم (بدون کلید خارجی) تا حذف ماژول چیزی را نشکند
    path TEXT NOT NULL,
    recipe TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
)
""")]

MODULE = Module(id="video_editor", name="ویرایشگر ویدیو", migrations=MIGRATIONS, requires=(),
                description="برش و ویرایش ویدیوی محصولات", tables=["vid_assets"])

@route("/api/video/{id:int}", module="video_editor")
async def get_video(request, body):
    return db.q1("SELECT * FROM vid_assets WHERE id=?", [pid(request)])
```

2. **رابط:** فایل `static/js/mod_video_editor.js` با یک شیء صفحه (`title`، `render`، `mount`، `act`، …). در `app.js` یک ورودی `lazy` در `P`، یک مسیر با شناسه‌ی ماژول در `ROUTES` و در صورت نیاز یک منو در `NAV` بیفزایید.
3. **MCP:** در `mcp_core.py` ابزار با `@tool(…, module="video_editor")` تعریف کنید تا با خاموش بودن ماژول در فهرست ابزارها نیاید.
4. **مستندات:** یک بخش در `docs/guide` و جدول بالا.
5. **تست:** یک بخش در `tests/e2e_v2.py` یا فایل تازه، شامل روشن، خاموش و مسیرهای ۵۰۳.

### قواعد

- جدول‌ها پیشوند ماژول دارند (`vid_`، `veh_`، `dup_`).
- ارجاع به جدول‌های هسته **نرم** است (شناسه بدون FOREIGN KEY).
- هسته هرگز مستقیم جدول یک ماژول را نمی‌خواند؛ اگر لازم شد، یک رابط نازک مثل `compat.py` بسازید.
- مهاجرت‌ها فقط افزایشی‌اند و هر نسخه فقط یک بار اجرا می‌شود؛ برای تغییر، نسخه‌ی تازه اضافه کنید.
- هر تغییر داده‌ای که ماژول انجام می‌دهد باید با `revisions.record(entity, id, snapshot, actor, action)` ثبت شود و برای موجودیت تازه `revisions.register_restorer` تعریف شود.
