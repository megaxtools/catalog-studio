"""مانیفست ماژول‌های داخلی: بخش‌های هسته (همیشه فعال) و قابلیت‌هایی که کدشان در هسته است ولی قابل خاموش کردن‌اند."""
from __future__ import annotations

from .. import db
from . import Module, register

# ---------------------------------------------------------------------------
# جدول‌های هسته‌ی نسخه‌ی ۲ (افزایشی؛ جدول‌های نسخه‌ی ۱ دست نمی‌خورند)
# ---------------------------------------------------------------------------
CORE_V2 = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    rev INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT 'edit',
    snapshot TEXT NOT NULL,
    changes TEXT NOT NULL DEFAULT '[]',
    actor TEXT NOT NULL DEFAULT 'ui',
    user_id INTEGER,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (entity, entity_id, rev)
);
CREATE INDEX IF NOT EXISTS idx_revisions_entity ON revisions(entity, entity_id);
CREATE TABLE IF NOT EXISTS ref_brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    slug TEXT UNIQUE NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    country TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    slug TEXT UNIQUE NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    sort INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wb_banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    schema_id INTEGER,
    dataset_ids TEXT NOT NULL DEFAULT '[]',
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    step TEXT DEFAULT '',
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    error TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS wb_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id INTEGER NOT NULL,
    uid TEXT UNIQUE NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    slug TEXT NOT NULL DEFAULT '',
    brand_id INTEGER,
    category_id INTEGER,
    compat TEXT NOT NULL DEFAULT '{"all": true}',
    values_json TEXT NOT NULL DEFAULT '{}',
    images TEXT NOT NULL DEFAULT '[]',
    flags TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    quality INTEGER,
    quality_detail TEXT NOT NULL DEFAULT '{}',
    sources TEXT NOT NULL DEFAULT '[]',
    merged_into INTEGER,
    rev INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wb_products_bank ON wb_products(bank_id, seq);
CREATE INDEX IF NOT EXISTS idx_wb_products_status ON wb_products(status);
CREATE TABLE IF NOT EXISTS tpl_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cat_catalogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    template_id INTEGER,
    selection TEXT NOT NULL DEFAULT '{}',
    options TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cat_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    step TEXT DEFAULT '',
    progress_done INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    error TEXT DEFAULT '',
    root TEXT DEFAULT '',
    files TEXT NOT NULL DEFAULT '{}',
    stats TEXT NOT NULL DEFAULT '{}',
    diff TEXT NOT NULL DEFAULT '{}',
    snapshot TEXT NOT NULL DEFAULT '{}',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (catalog_id, number)
);
CREATE TABLE IF NOT EXISTS cat_release_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id INTEGER NOT NULL,
    product_id INTEGER,
    uid TEXT NOT NULL,
    product_rev INTEGER,
    title TEXT DEFAULT '',
    record TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cat_release_items ON cat_release_items(release_id)
"""


def _core_v2_schemas(c):
    cols = {r[1] for r in c.execute("PRAGMA table_info(schemas)").fetchall()}
    if "usage" not in cols:
        c.execute("ALTER TABLE schemas ADD COLUMN usage TEXT NOT NULL DEFAULT 'general'")
    if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        c.execute("INSERT INTO users(id, username, name, role, active, created_at) VALUES(1, 'admin', 'مدیر', 'admin', 1, ?)", [db.now()])


def _seed_core():
    from .. import seed_v2
    seed_v2.run()


register(Module(
    id="core", name="هسته", core=True, builtin=True, version="2.0.0",
    description="پایگاه داده، تنظیمات، کاربران، ریویژن‌ها، گزارش‌ها، پشتیبان‌گیری و رابط کاربری.",
    migrations=[(1, CORE_V2), (2, _core_v2_schemas),
                (3, "ALTER TABLE ref_brands ADD COLUMN category_ids TEXT NOT NULL DEFAULT '[]';"
                    "ALTER TABLE ref_brands ADD COLUMN description TEXT DEFAULT '';"
                    "ALTER TABLE ref_categories ADD COLUMN description TEXT DEFAULT ''")], init=_seed_core,
    tables=["settings", "users", "revisions", "activity", "history", "logs", "schema_migrations"],
))
register(Module(id="raw", name="داده‌های خام", core=True, builtin=True,
                description="بانک‌های داده‌ی خام (حاصل استخراج یا تولید) و محصولات خام؛ داده‌ی خام نسخه‌ی صفر هر محصول است.",
                tables=["datasets", "items", "incidents"]))
register(Module(id="editor", name="ویرایشگر داده‌ها", core=True, builtin=True,
                description="بانک‌های تمیز: اصلاح فیلدها، برند، دسته، سازگاری با خودرو، تصاویر، بازبینی و تأیید محصولات.",
                tables=["wb_banks", "wb_products"]))
register(Module(id="catalog", name="کاتالوگ محصولات", core=True, builtin=True,
                description="کاتالوگ‌ها و انتشارهای نسخه‌دار با الگوی خروجی (درخت فایل، قالب و اسکیمای هر خروجی).",
                tables=["cat_catalogs", "cat_releases", "cat_release_items"]))
register(Module(id="templates", name="الگوها و اسکیماها", core=True, builtin=True,
                description="اسکیماها با کاربرد مشخص، الگوهای خروجی و درخت فایل، قواعد متن و نگاشت‌ها.",
                tables=["schemas", "tpl_outputs", "text_rules", "mappings"]))
register(Module(id="refdata", name="داده‌های مرجع", core=True, builtin=True,
                description="فهرست‌های کنترل‌شده‌ی برندها و دسته‌بندی‌های مگا کارز.",
                tables=["ref_brands", "ref_categories"]))

# ---------------------------------------------------------------------------
# قابلیت‌های قابل خاموش کردن
# ---------------------------------------------------------------------------
register(Module(
    id="scraper", name="استخراج از وب", builtin=True,
    description="منابع و اسکرپرها، آزمایش زنده، کاوشگر داده و شروع استخراج از صفحه‌ی دسته‌بندی.",
    tables=["sources"],
    paths=[(("POST",), r"^/api/datasets$"), (None, r"^/api/sources/(detect|\{id:int\}/(explore|test-listing|test-product))"),
           (("POST",), r"^/api/datasets/\{id:int\}/do/\{action:str\}$"), (("POST",), r"^/api/items/\{id:int\}/rescrape$")],
))
register(Module(id="queue", name="صف و زمان‌بندی", builtin=True, requires=("scraper",),
                description="صف استخراج‌ها با زمان‌بندی و اجرای خودکار.", tables=["queue_jobs"],
                paths=[(None, r"^/api/queue")]))
register(Module(
    id="ai", name="هوش مصنوعی", builtin=True,
    description="اتصال به سرویس‌های هوش مصنوعی، تولید محتوا و تصویر، دستیار همه‌جا، بانک داده‌ی تولیدی.",
    tables=["ai_providers", "ai_profiles", "ai_jobs", "ai_calls"],
    paths=[(None, r"^/api/ai/"), (("POST",), r"/ai(-add|-column|-clear)?$"), (("POST",), r"/generate-image$"),
           (("POST",), r"/images/generate$"), (("POST",), r"/ai-suggest$")],
))
register(Module(id="rembg", name="حذف پس‌زمینه", builtin=True,
                description="حذف پس‌زمینه‌ی تصاویر با مدل‌های ONNX (rembg).", paths=[(None, r"^/api/models")]))
register(Module(id="align", name="ترازبندی تصاویر", builtin=True,
                description="حذف فضای خالی دور سوژه و قرار دادنش با حاشیه‌ی ثابت روی بوم یکسان.", paths=[(None, r"^/api/align/")]))


def _mcp_toggle(on: bool):
    db.set_settings({"mcp_enabled": bool(on)})


register(Module(id="mcp", name="اتصال ایجنت‌ها (MCP)", builtin=True, on_toggle=_mcp_toggle,
                description="سرور MCP برای Claude، ChatGPT و دیگر ایجنت‌ها.", paths=[(("POST",), r"^/api/mcp/")]))
register(Module(id="legacy_export", name="خروجی مستقیم (روش نسخه‌ی ۱)", builtin=True,
                description="خروجی‌ساز قدیمی (مستقیم از داده‌ی خام) و «خروجی‌های نهایی» نسخه‌ی ۱.۶ با امکان تبدیل به بانک تمیز.",
                tables=["exports", "export_rows"], paths=[(None, r"^/api/exports"), (None, r"^/api/catalogs")]))
