"""ساخت نام انگلیسی و اسلاگ برای برند، مدل و تیپ خودروها (اسلاگ‌ها فقط انگلیسی‌اند و همگی قابل ویرایش‌اند)."""
from __future__ import annotations

import re

from ...textutil import normalize_fa, slugify, to_latin_digits

BRANDS = {
    "آئودی": "Audi", "آرتابان (ای ام جی)": "Artaban", "آریا": "Aria", "آریا کلاسیک": "Aria Classic", "آریسان": "Arisan",
    "آلفارومئو": "Alfa Romeo", "آمیکو": "Amico", "آی ام موتورز": "IM Motors", "اتوبیانکی": "Autobianchi", "اس دبلیو ام": "SWM",
    "استین": "Estin", "اسمارت": "Smart", "اسکای ول": "Skywell", "اشکودا": "Skoda", "اطلس": "Atlas", "الدزمبیل": "Oldsmobile",
    "ام جی": "MG", "ام وی ام": "MVM", "اوتار": "Avatr", "اوشان": "Oshan", "اونترا": "Ontra", "اپل": "Opel", "اکستریم": "Extreme",
    "ایرس": "Iris", "ایسوزو": "Isuzu", "اینرودز": "Inroads", "اینفینیت": "Infinit", "اینفینیتی": "Infiniti", "اینوی": "Envy",
    "ایویکو": "Iveco", "ایکس پنگ": "XPeng", "ب ام و": "BMW", "بایک": "BAIC", "برلیانس": "Brilliance", "بسترن": "Besturn",
    "بستیون": "Bestune", "بنتلی": "Bentley", "بنز": "Mercedes-Benz", "بورگوارد": "Borgward", "بوفوری": "Bufori",
    "بوگاتی": "Bugatti", "بی ای دبلیو (BAW)": "BAW", "بی ای سی": "BEC", "بی وای دی": "BYD", "بیجینگ": "Beijing", "بیسو": "Bisu",
    "بیوک": "Buick", "تارا": "Tara", "تانک": "Tank", "تریومف": "Triumph", "تویوتا": "Toyota", "تیبا": "Tiba", "تیگارد": "Tigard",
    "جتا": "Jetta", "جنسیس": "Genesis", "جوی لانگ": "Joylong", "جِی ام سی (JMC)": "JMC", "جک": "JAC", "جگوار": "Jaguar",
    "جی ام سی (GMC)": "GMC", "جی ای سی": "GAC", "جیلی": "Geely", "جین بی": "Jinbei", "جیپ": "Jeep", "داتسون": "Datsun",
    "دامای": "Damai", "دانگ فنگ": "Dongfeng", "داچیا": "Dacia", "دایهاتسو": "Daihatsu", "دایون": "Dayun", "دنا": "Dena",
    "دوج": "Dodge", "دوو": "Daewoo", "دی اس": "DS", "دیگنیتی": "Dignity", "رامبلر": "Rambler", "رانا": "Runna", "راین": "Rayen",
    "رنو": "Renault", "روئوه": "Roewe", "رولز رویس": "Rolls-Royce", "روور": "Rover", "ری را": "Rira", "ریسپکت": "Respect",
    "ریگان": "Rigan", "زامیاد": "Zamyad", "زد ایکس اتو": "ZX Auto", "زوتی": "Zotye", "سئات": "SEAT", "ساب": "Saab",
    "سانگ یانگ (KGM)": "SsangYong", "ساینا": "Saina", "سمند": "Samand", "سهند": "Sahand", "سوئیست": "Soueast", "سوبارو": "Subaru",
    "سوزوکی": "Suzuki", "سی ام سی": "CMC", "سیتروئن": "Citroen", "سیمرغ": "Simorgh", "سیناد": "Sinad", "شاهین": "Shahin",
    "شوال": "Cheval", "شورولت": "Chevrolet", "فانگ چنگ بائو": "Fangchengbao", "فاو": "FAW", "فراری": "Ferrari", "فردا": "Farda",
    "فوتون": "Foton", "فورد": "Ford", "فولکس": "Volkswagen", "فونیکس": "Fownix", "فیات": "Fiat", "فیدلیتی": "Fidelity",
    "لئوپارد": "Leopaard", "لادا": "Lada", "لاماری": "Lamari", "لاماکو": "Lamaco", "لامبورگینی": "Lamborghini", "لانچیا": "Lancia",
    "لندرور": "Land Rover", "لندمارک": "Landmark", "لوبو": "Lubo", "لوتوس": "Lotus", "لونا": "Luna", "لوکانو": "Lucano",
    "لوکسژن": "Luxgen", "لکسوس": "Lexus", "لیفان": "Lifan", "لینکلن": "Lincoln", "لیپ موتور": "Leapmotor", "مارس": "Mars",
    "مازراتی": "Maserati", "مرکوری": "Mercury", "مزدا": "Mazda", "مورگان": "Morgan", "مک لارن": "McLaren", "مکث موتور": "Maxmotor",
    "مکسوس": "Maxus", "میتسوبیشی": "Mitsubishi", "مینی": "MINI", "نامی": "Nami", "نوو": "Novo", "نیسان": "Nissan", "هامر": "Hummer",
    "هاوال": "Haval", "هایما": "Haima", "هن تنگ": "Hanteng", "هولدن": "Holden", "هوندا": "Honda", "هونگچی": "Hongqi",
    "هیلمن": "Hillman", "هیوسو": "Hyosow", "هیوندای": "Hyundai", "واکس هال": "Vauxhall", "وست فیلد": "Westfield", "ولوو": "Volvo",
    "ونوسیا": "Venucia", "وویا": "Voyah", "پادرا موتور": "Padra Motor", "پارس نوآ": "Pars Noa", "پاژن": "Pazhan", "پراید": "Pride",
    "پروتون": "Proton", "پلیموت": "Plymouth", "پورشه": "Porsche", "پونتیاک": "Pontiac", "پژو": "Peugeot", "پیکان": "Paykan",
    "چانگان": "Changan", "چانگهه": "Changhe", "چری": "Chery", "کادیلاک": "Cadillac", "کارا": "Kara", "کاپرا": "Capra", "کاکی": "Kaki",
    "کرایسلر": "Chrysler", "کونیگزگ": "Koenigsegg", "کوییک": "Quick", "کی ام سی": "KMC", "کی وای سی": "KYC", "کیا": "Kia",
    "کینگ لانگ": "King Long", "گاز": "GAZ", "گریت وال": "Great Wall", "یوآز": "UAZ",
}

PHRASES = [  # پیش از تبدیل واژه‌به‌واژه
    ("سایر مدل‌ها", "Other Models"), ("سایر مدل ها", "Other Models"), ("دنده ای", "Manual"), ("دنده‌ای", "Manual"),
    ("دوگانه سوز", "Bi-Fuel"), ("دو دیفرانسیل", "4WD"), ("تک دیفرانسیل", "2WD"), ("چهار چرخ محرک", "AWD"), ("تک کابین", "Single Cab"),
    ("دو کابین", "Double Cab"), ("دوکابین", "Double Cab"), ("هاچ بک", "Hatchback"), ("هاچبک", "Hatchback"), ("صندوق دار", "Sedan"),
    ("صندوقدار", "Sedan"), ("اسپرت بک", "Sportback"), ("ایکس تریل", "X-Trail"), ("جی‌ران", "Jiran"), ("کیلو وات", "kW"),
    ("دو در", "2-Door"), ("چهار در", "4-Door"), ("پنج در", "5-Door"), ("سه در", "3-Door"), ("رنج روور", "Range Rover"),
]

WORDS = {
    "لیتر": "L", "کلاس": "Class", "توربو": "Turbo", "سری": "Series", "اتوماتیک": "Automatic", "دنده": "Manual", "کوپه": "Coupe",
    "پلاس": "Plus", "سیلندر": "Cylinder", "مونتاژ": "Assembled", "مونتاژی": "Assembled", "هیبرید": "Hybrid", "تیپ": "Type",
    "دیفرانسیل": "Diff", "کروک": "Convertible", "سدان": "Sedan", "کابین": "Cab", "ساده": "Base", "اسپرت": "Sport", "وانت": "Pickup",
    "پرو": "Pro", "ون": "Van", "کمری": "Camry", "لاکچری": "Luxury", "اکسلنت": "Excellent", "تیگو": "Tiggo", "وارداتی": "Imported",
    "مکس": "Max", "گرن": "Gran", "لندکروز": "Land Cruiser", "لندکروزر": "Land Cruiser", "کرولا": "Corolla", "لاین": "Line",
    "آکورد": "Accord", "آریزو": "Arrizo", "کراس": "Cross", "اوتلندر": "Outlander", "بنزینی": "Gasoline", "بنزین": "Gasoline",
    "نیو": "New", "سراتو": "Cerato", "پاترول": "Patrol", "کیلووات": "kW", "پارس": "Pars", "الیت": "Elite", "نامشخص": "Unknown",
    "گرند": "Grand", "گراند": "Grand", "تندر": "Tondar", "سوناتا": "Sonata", "تیوولی": "Tivoli", "کوراندو": "Korando",
    "ویتارا": "Vitara", "اسپایدر": "Spider", "پرمیوم": "Premium", "پریمیوم": "Premium", "پرادو": "Prado", "راوفور": "RAV4",
    "امگرند": "Emgrand", "پرایم": "Prime", "مگان": "Megane", "سورن": "Soren", "رنجرور": "Range Rover", "پانوراما": "Panorama",
    "هایلوکس": "Hilux", "نفره": "Seater", "وینگل": "Wingle", "قشقایی": "Qashqai", "آسترا": "Astra", "کورسا": "Corsa",
    "اولترا": "Ultra", "ادیشن": "Edition", "اسکای": "Sky", "استیشن": "Station", "کاین": "Cayenne", "پریوس": "Prius",
    "داستر": "Duster", "ساندرو": "Sandero", "اکتیون": "Actyon", "اسپورتیج": "Sportage", "پاجرو": "Pajero", "لنسر": "Lancer",
    "پیکاپ": "Pickup", "دیزاین": "Design", "سیویک": "Civic", "النترا": "Elantra", "توسان": "Tucson", "کلاسیک": "Classic",
    "کنتینانتال": "Continental", "کنتیننتال": "Continental", "باکستر": "Boxster", "هایس": "Hiace", "یاریس": "Yaris",
    "پرستیژ": "Prestige", "اسکالا": "Scala", "سفران": "Safrane", "رکستون": "Rexton", "موسو": "Musso", "تونلند": "Tunland",
    "گلف": "Golf", "اپتیما": "Optima", "ریو": "Rio", "تیانا": "Teana", "سیلفی": "Sylphy", "ماکسیما": "Maxima", "مورانو": "Murano",
    "سانتافه": "Santa Fe", "رودستر": "Roadster", "پانامرا": "Panamera", "اکو": "Eco", "ونزا": "Venza", "جلو": "Front",
    "پاتریوت": "Patriot", "سایپا": "Saipa", "آپشنال": "Optional", "چارجر": "Charger", "رم": "Ram", "سیمبل": "Symbol",
    "فلوئنس": "Fluence", "آریو": "Ario", "جیمنی": "Jimny", "زانتیا": "Xantia", "کوروت": "Corvette", "پیور": "Pure",
    "تیگوان": "Tiguan", "پنج": "5", "هفت": "7", "هشت": "8", "چهار": "4", "دو": "2", "تک": "Single", "دویل": "Doblo",
    "سلتوس": "Seltos", "سورنتو": "Sorento", "ولار": "Velar", "کواتروپورته": "Quattroporte", "توریسمو": "Turismo", "کبریو": "Cabrio",
    "قدیم": "Old", "کانتری": "Country", "کوپر": "Cooper", "جوک": "Juke", "اکسنت": "Accent", "آراز": "Araz", "امگا": "Omega",
    "موکا": "Mokka", "فور": "Four", "اوکتاویا": "Octavia", "کاتلاس": "Cutlass", "سیرا": "Sierra", "نیوفیس": "New Face",
    "کامفورت": "Comfort", "گیربکس": "Gearbox", "اکسپلورر": "Explorer", "آلتیمیت": "Ultimate", "لجند": "Legend", "دلفین": "Dolphin",
    "اسپشیال": "Special", "لیموزین": "Limousine", "کررا": "Carrera", "آوالون": "Avalon", "کروز": "Cruze", "فرچونر": "Fortuner",
    "فررانر": "4Runner", "لیمیتد": "Limited", "پلاتینیوم": "Platinum", "دیزل": "Diesel", "هایلندر": "Highlander", "بلند": "Long",
    "کوتاه": "Short", "تمام": "Full", "فول": "Full", "ریفاین": "Refine", "سابربن": "Suburban", "سوپر": "Super", "تالیسمان": "Talisman",
    "کولیوس": "Koleos", "لاگونا": "Laguna", "فانتوم": "Phantom", "اکسکلوسیو": "Exclusive", "رویال": "Royal", "اکستند": "Extend",
    "لگاسی": "Legacy", "کیزاشی": "Kizashi", "بلیزر": "Blazer", "کوگر": "Cougar", "بیتل": "Beetle", "دوکاتو": "Ducato",
    "موهاوی": "Mohave", "اونتادور": "Aventador", "گالاردو": "Gallardo", "مورسیه": "Murcielago", "هوراکان": "Huracan",
    "ایووک": "Evoque", "الیزه": "Elise", "لوانته": "Levante", "استار": "Star", "اکلیپس": "Eclipse", "گالانت": "Galant",
    "آلتیما": "Altima", "تریل": "Trail", "ناوارا": "Navara", "آنلاین": "Online", "آزرا": "Azera", "گرنجور": "Grandeur",
    "آوانته": "Avante", "پالیسید": "Palisade", "ورنا": "Verna", "کواترو": "Quattro", "جولیتا": "Giulietta", "میتو": "MiTo",
    "اینسیگنیا": "Insignia", "رکورد": "Rekord", "زافیرا": "Zafira", "فرانترا": "Frontera", "کاپیتان": "Kapitan",
    "کالیبرا": "Calibra", "وکترا": "Vectra", "سوپرب": "Superb", "کاروک": "Karoq", "تروپر": "Trooper", "دیلی": "Daily",
    "ویانو": "Viano", "ویرون": "Veyron", "الکترا": "Electra", "رگال": "Regal", "ریویرا": "Riviera", "سنچری": "Century",
    "لسابر": "LeSabre", "استاندارد": "Standard", "لانگ": "Long", "پارتنر": "Partner", "کیمن": "Cayman", "ماکان": "Macan",
    "فایربرد": "Firebird", "کاتالینا": "Catalina", "آئوریس": "Auris", "آوانزا": "Avanza", "آیگو": "Aygo", "اینووا": "Innova",
    "پریویا": "Previa", "ترسل": "Tercel", "توندرا": "Tundra", "سکویا": "Sequoia", "سلیکا": "Celica", "سوپرا": "Supra",
    "سولارا": "Solara", "کارینا": "Carina", "کراون": "Crown", "کرونا": "Corona", "کریسیدا": "Cressida", "آکادیا": "Acadia",
    "یوکان": "Yukon", "چروکی": "Cherokee", "رنگلر": "Wrangler", "کامپس": "Compass", "لیبرتی": "Liberty", "واگونیر": "Wagoneer",
    "شهباز": "Shahbaz", "صحرا": "Sahara", "گلدن": "Golden", "اسپورت": "Sport", "مدل": "Model", "موتور": "Motor", "جن": "Gen",
    "کلت": "Colt", "فلکس": "Flex", "المرا": "Almera", "ویلیز": "Willys", "ایگل": "Eagle", "گرندکاروان": "Grand Caravan",
    "غزال": "Gazelle", "ایران": "Iran", "خودرو": "Khodro", "کاروان": "Caravan", "آهو": "Ahoo", "فری": "Free", "اسپرو": "Espero",
    "ایما": "Eama", "تروی": "Trumpchi", "چین": "Qin", "گونو": "Gono", "کیا": "Kia", "پراید": "Pride", "سمند": "Samand",
    "سورنتو": "Sorento", "اسپورتیج": "Sportage", "مزدا": "Mazda", "پژو": "Peugeot", "رانا": "Runna", "دنا": "Dena",
    "دار": "", "در": "Door", "ای": "",
}
LETTERS = {"ای": "E", "بی": "B", "سی": "C", "دی": "D", "اف": "F", "جی": "G", "اچ": "H", "آی": "I", "جی‌": "G", "کی": "K", "ال": "L",
           "ام": "M", "ان": "N", "او": "O", "پی": "P", "کیو": "Q", "آر": "R", "اس": "S", "تی": "T", "یو": "U", "وی": "V",
           "دبلیو": "W", "ایکس": "X", "وای": "Y", "زد": "Z", "زی": "Z"}


def english_name(fa: str, kind: str = "model") -> str:
    """نام انگلیسی پیشنهادی (برای اسلاگ و نمایش)؛ کاربر یا هوش مصنوعی می‌تواند اصلاحش کند."""
    s = normalize_fa(to_latin_digits(str(fa or ""))).strip()
    if kind == "brand" and s in BRANDS:
        return BRANDS[s]
    if not re.search(r"[؀-ۿ]", s):
        return s
    for a, b in PHRASES:
        s = s.replace(a, f" {b} ")
    tokens = re.findall(r"[A-Za-z0-9.+\-/]+|[؀-ۿ‌]+|\(|\)", s)
    out: list[str] = []
    letters_run: list[str] = []

    def flush():
        if letters_run:
            out.append("".join(letters_run))
            letters_run.clear()

    for i, t in enumerate(tokens):
        if t in ("(", ")"):
            flush()
            continue
        nxt_is_letter = i + 1 < len(tokens) and tokens[i + 1] in LETTERS
        prev_is_letter = bool(letters_run)
        if t in LETTERS and (nxt_is_letter or prev_is_letter or t not in WORDS):
            letters_run.append(LETTERS[t])
            continue
        flush()
        if re.match(r"[A-Za-z0-9]", t):
            out.append(t)
        elif t in WORDS:
            if WORDS[t]:
                out.append(WORDS[t])
        else:
            flat = t.replace("‌", "")
            if flat in WORDS:
                if WORDS[flat]:
                    out.append(WORDS[flat])
            else:
                out.append(slugify(t).replace("-", " ").title())
    flush()
    name = re.sub(r"\s+", " ", " ".join(x for x in out if x)).strip()
    return name


def make_slug(name_en: str, fallback_fa: str = "") -> str:
    s = slugify(name_en or "") or slugify(fallback_fa or "")
    return s or "item"
