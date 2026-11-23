"""Build the national map data: public GeoJSON for the site + private lists for outreach and review.

Public map  : site/data/places.geojson  (OSM places + certified organic COMPANIES that make food for people)
              site/data/kraje.geojson   (simplified region outlines for the region filter)
Private     : data/out/outreach_slovakia.csv  (sole traders, office addresses, register candidates; GDPR, never publish)
              data/out/organic_review.csv     (every certified company with the decision taken and why)
              data/out/report.md              (counts for the README and for hand-checking)

Rules (see PLAN.md):
  - no supermarket or convenience chains; generic butchers/greengrocers only when they say farm/bio
  - sole traders are not published until they agree
  - BIO badge only for a valid EU organic certificate
  - certified operators whose certificate lists only crops for processors (grain, fodder, grassland) or live
    animals stay off the map: buyers cannot do anything with them
  - pins at registered offices mislead buyers, so shared addresses and city-office farms go to outreach instead
"""
import collections
import csv
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from admin import KRAJ_SLUG, Admin, fold  # noqa: E402
from build_inventory import norm  # noqa: E402
from geocode import Geocoder  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today().isoformat()
TRACES_KRAJ = {"Region of Bratislava": "Bratislavský", "Region of Trnava": "Trnavský",
               "Region of Trenčín": "Trenčiansky", "Region of Nitra": "Nitriansky", "Region of Žilina": "Žilinský",
               "Region of Banská Bystrica": "Banskobystrický", "Region of Prešov": "Prešovský",
               "Region of Košice": "Košický"}
COMPANY = re.compile(r"s\.\s?r\.\s?o|spol\.|a\.\s?s\.|družstvo|v\.\s?o\.\s?s|k\.\s?s\.|o\.\s?z\.|n\.\s?o\.|"
                     r"\bs\.r\.o\b|\bsro\b|z\.\s?s\.|ltd|gmbh|\bs\. ?r\. ?o\b", re.I)

# ---------------------------------------------------------------- OSM ----------------------------------------------
GENERIC_NAMES = {"pekaren", "pekarstvo", "mlieko", "mliecny automat", "automat", "potraviny", "maso", "masiarstvo",
                 "farmarsky obchod", "farmarska predajna", "predaj z dvora", "farmarske potraviny",
                 "ovocie zelenina", "ovocie a zelenina", "zelenina", "trh", "trhovisko", "trznica", "farma", "syry",
                 "lahodky", "zdrava vyziva", "bio", "vinarstvo", "vino", "med", "vcelar", "salas"}
NOT_FOOD_MARKET = re.compile(r"bleš|blsi|second|burz|auto|ázij|azij|asia|čínsk|vietnam|outlet|textil|kvet|poľsk|polsk|"
                             r"nábyt|stavebn|vianočn|vianocn|potravin|copy|fax|bufet|bistro|reštaur|pizz|kebab|obuv|"
                             r"mobil|drogéri|tabak|trafik", re.I)
FARMISH = re.compile(r"farm|bio|eko|z dvora|dvor|domác|ranč|salaš|gazdov|roľn|rodinn|záhrad|sad\b|pestovateľ|samozber",
                     re.I)
WINERY_NAME = re.compile(r"vinárst|vinarst|vinárs|vinohrad|pivnica|winery|wines\b|vinica\b|rodinné víno", re.I)
PRODUCE_SK = {"apple": "jablká", "apples": "jablká", "fish": "ryby", "blackcurrant": "čierne ríbezle",
              "honey": "med", "potato": "zemiaky", "potatoes": "zemiaky", "mushrooms": "huby",
              "gingerbread": "medovníky", "tomato": "paradajky", "tomatoes": "paradajky", "walnut": "vlašské orechy",
              "eggs": "vajcia", "egg": "vajcia", "gaštan": "gaštany", "grapes": "hrozno", "berries": "bobuľové ovocie",
              "milk": "mlieko", "cheese": "syr", "meat": "mäso", "vegetables": "zelenina", "fruit": "ovocie",
              "strawberries": "jahody", "strawberry": "jahody", "cherries": "čerešne", "plums": "slivky",
              "pears": "hrušky", "pumpkin": "tekvice", "herbs": "bylinky", "wine": "víno", "lavender": "levanduľa"}
NOT_FOOD_PRODUCE = re.compile(r"tree|christmas|flower|plant|seedling|wood|timber|hay|straw|sod|turf", re.I)
FARM_STRONG = re.compile(r"farm|statok|medáreň|medaren|včel|vcel|z dvora|gazdov|salaš|mliekáreň|syráreň", re.I)
LOCAL_SHOP = re.compile(r"farm|bio\b|bio[a-zá-ž]|eko\b|eko[a-zá-ž]|z dvora|dvor|domác|ranč|salaš|gazdov|roľn|rodinn|"
                        r"záhrad|sad\b|pestovateľ|regionál|slovensk|syr|včel|\bmed\b|mliek|mäsiar", re.I)


def vending_label(v):
    v = v.lower()
    has = {k: k in v for k in ("milk", "egg", "cheese", "dairy", "meat", "potato", "honey", "bread", "fruit",
                               "vegetable")}
    if has["milk"] and has["egg"]:
        return "Automat na mlieko a vajcia"
    if has["milk"]:
        return "Mliečny automat"
    if has["egg"]:
        return "Automat na vajcia"
    if has["cheese"] or has["dairy"]:
        return "Automat na mliečne výrobky"
    if has["meat"]:
        return "Automat na mäso"
    if has["potato"]:
        return "Automat na zemiaky"
    if has["honey"]:
        return "Automat na med"
    if has["bread"]:
        return "Automat na pečivo"
    return "Automat na ovocie a zeleninu" if has["fruit"] or has["vegetable"] else "Automat na potraviny"


def osm_category(t):
    """Return (category, label override or '') or (None, reason) for an OSM tag dict."""
    shop, craft, amenity, name = t.get("shop"), t.get("craft"), t.get("amenity"), t.get("name", "")
    vending = t.get("vending", "")
    if amenity == "vending_machine" or (vending and not shop):
        if re.search(r"milk|egg|cheese|dairy|meat|potato|honey|bread|fruit|vegetable", vending):
            return "vending", vending_label(vending)
        return None, "vending: not farm food"
    if amenity == "marketplace":
        return (None, "market: not food") if NOT_FOOD_MARKET.search(name) else ("market", "")
    if re.match(r"sala[šs]\b", name, re.I):
        return "salas", ""
    if craft == "winery" or (shop == "wine" and WINERY_NAME.search(name)):
        return "winery", ""
    if craft == "beekeeper" or shop == "honey" or (shop == "farm" and re.search(r"včel|vcel|\bmed\b|medáreň", name, re.I)):
        return "honey", ""
    if re.search(r"samozber", name, re.I) and (shop or "produce" in t):
        return "farm", "Samozber"
    if shop == "farm":
        return "farm", "Farmársky obchod" if not re.search(r"farm|ranč|dvor", name, re.I) else ""
    if craft in ("cheese", "cheesemaker", "cheese_maker"):
        return "producer", "Syráreň"
    if craft == "oil_mill":
        return "producer", "Olejáreň"
    if craft == "cider":
        return "producer", "Muštáreň"
    if shop == "bakery" or craft == "bakery":
        return "bakery", ""
    if shop in ("cheese", "dairy"):
        return "dairy", ""
    if shop == "organic":
        return "organic_shop", ""
    if shop == "health_food":  # mostly supplements and dried goods; keep the ones that say bio/farm/local
        return ("organic_shop", "Zdravá výživa") if LOCAL_SHOP.search(name) else (None, "health_food: not local")
    if shop == "deli":  # "lahôdky" are mostly cafés and salad bars; keep farm and regional food shops
        return ("deli", "") if LOCAL_SHOP.search(name) else (None, "deli: not local")
    if shop in ("butcher", "greengrocer"):
        if t.get("organic") in ("yes", "only") or FARMISH.search(name):
            return shop, ""
        return None, f"{shop}: generic shop"
    if shop in ("convenience", "supermarket", "general", "herbalist", "alcohol") and FARM_STRONG.search(name):
        return ("honey", "") if re.search(r"medáreň|medaren|včel|vcel", name, re.I) else ("farm", "Farmársky obchod")
    if t.get("landuse") == "aquaculture" and re.search(r"rybárstv|rybářstv|sádky|pstruh|predaj", name, re.I):
        return "farm", "Rybárstvo"
    if NOT_FOOD_PRODUCE.search(t.get("produce", "")):
        return None, "produce: not food"
    if "produce" in t and name and not ({"amenity", "tourism", "landuse"} & set(t)):
        return "farm", ""
    if t.get("place") == "farm":
        if any(k in t for k in ("website", "contact:website", "phone", "contact:phone", "opening_hours", "produce")):
            return "farm", ""
        return None, "place=farm: only a place name"
    if re.search(r"farma|ranč", name, re.I) and (t.get("tourism") in ("attraction", "farm") or "produce" in t):
        return "farm", ""
    return None, "not a food seller"


SPREAD_OUT_TYPES = {"salas", "farm", "winery", "market", "vending", "dairy", "honey"}


def metres(a, b):
    return math.hypot((a[0] - b[0]) * 73_000, (a[1] - b[1]) * 111_000)  # good enough at Slovak latitudes


def osm_people_dates():
    """Per element, what scripts/osm_meta.py found in the OSM API: the last edit made by a person (bot runs and mass
    edits do not count, so a shop surveyed in 2015 keeps its 2015 date), and whether it was deleted or retagged since
    the extract. Empty when the script has not been run: then the extract's own timestamp is used."""
    path = ROOT / "data/raw/osm_meta.json"
    return json.loads(path.read_text()).get("current", {}) if path.exists() else {}


def osm_features(stats):
    raw = json.load(open(ROOT / "data/raw/osm_sk.json", encoding="utf-8"))["elements"]
    meta = osm_people_dates()
    # chain detection: how many distinct places (more than ~1 km apart) of a food-selling kind share a name
    names, seen_at = collections.Counter(), collections.defaultdict(list)
    for e in raw:
        t = e.get("tags", {})
        n = norm(t.get("name", ""))
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if not n or lat is None or not osm_category(t)[0]:
            continue
        if any(abs(lon - a) < 0.015 and abs(lat - b) < 0.01 for a, b in seen_at[n]):
            continue
        seen_at[n].append((lon, lat))
        names[n] += 1
    feats = []
    for e in raw:
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None:
            continue
        cat, label = osm_category(t)
        if not cat:
            stats["osm_skipped"][label] += 1
            continue
        m = meta.get(f"{e['type'][0]}{e['id']}", {})
        if m.get("deleted") or (m.get("v", 0) > e.get("version", 0) and not osm_category(m.get("tags", {}))[0]):
            stats["osm_skipped"]["deleted or retagged in OSM since the extract"] += 1
            continue
        # a person's last edit, or a survey date someone recorded on the spot (StreetComplete sets check_date)
        surveyed = [v[:10] for k, v in t.items() if k in ("check_date", "survey:date", "survey_date")
                    and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", v[:10])]
        edited = max([m.get("human") or e.get("timestamp", "")] + surveyed)
        name = t.get("name", "").strip()
        key = norm(name)
        # a brand tag on a farm or winery is usually the producer's own brand ("Dobrý ježko"), not a chain
        branded = bool(t.get("brand") or t.get("brand:wikidata")) and cat not in ("farm", "winery")
        chain = branded or (name and names[key] >= 4 and key not in GENERIC_NAMES and cat not in ("farm", "winery"))
        if names[key] >= 6 and cat == "winery" and key not in GENERIC_NAMES:
            chain = True  # big wine-shop chains; a winery's own 2-3 shops stay
        if names[key] >= 5 and cat == "farm" and key not in GENERIC_NAMES:
            chain = True  # shop chains with "farm" in the name ("Farmfoods"); growers' own 2-3 stands stay
        if chain and cat in ("bakery", "butcher", "greengrocer", "organic_shop", "dairy", "deli", "honey", "winery",
                             "farm"):
            stats["osm_skipped"][f"{cat}: chain"] += 1
            continue
        if not name and cat not in ("vending", "market", "farm"):
            stats["osm_skipped"][f"{cat}: no name"] += 1
            continue
        if not name:
            name = label or {"market": "Trh", "farm": "Farma"}.get(cat, "Farma")
        street = t.get("addr:street") or t.get("addr:place", "")
        addr = " ".join(x for x in [street, t.get("addr:housenumber") or t.get("addr:conscriptionnumber", "")] if x)
        produce = [PRODUCE_SK.get(v.strip().lower(), "") for v in t.get("produce", "").split(";")]
        products = t.get("description", "") or ", ".join(dict.fromkeys(x for x in produce if x)).capitalize()
        feats.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "id": f"osm-{e['type'][0]}{e['id']}", "name": name, "category": cat,
                **({"label": label} if label else {}),
                "bio": False, "address": addr, "addr_city": t.get("addr:city", ""),
                "hours": t.get("opening_hours", ""), "phone": t.get("phone") or t.get("contact:phone", ""),
                "website": t.get("website") or t.get("contact:website") or t.get("url", ""),
                "products": products[:300], "precision": "exact", "source": "osm",
                "_operator": t.get("operator", ""),
                "osm_edited": edited,
            }})
        stats["osm_kept"][cat] += 1
    # the same place mapped twice: a point inside its building, the same salaš or winery drawn twice nearby,
    # or a generic "Trh" sitting on top of a named market. Keep the richest entry (hours, phone, web), nodes first.
    def richness(f):
        p = f["properties"]
        return sum(bool(p.get(k)) for k in ("hours", "phone", "website", "address", "products"))

    feats.sort(key=lambda f: (-richness(f), f["properties"]["id"][4] != "n", f["properties"]["id"]))
    kept = []
    for f in feats:
        p = f["properties"]
        key, x, y = norm(p["name"]), *f["geometry"]["coordinates"]
        generic = key in GENERIC_NAMES or key == norm(p.get("label", ""))
        dup = None
        for g in kept:
            q = g["properties"]
            d = metres((x, y), g["geometry"]["coordinates"])
            if d > 400:
                continue
            same_name = key and key == norm(q["name"])
            if (same_name and d <= 150) or (same_name and p["category"] in SPREAD_OUT_TYPES) or \
                    (generic and p["category"] == q["category"] and d <= 60):
                dup = g
                break
        if dup:
            stats["osm_skipped"]["duplicate entry"] += 1
            stats["osm_kept"][p["category"]] -= 1
            continue
        kept.append(f)
    return kept


# ------------------------------------------------------------- organic ---------------------------------------------
FOOD_STEMS = (
    "med medov vcel propolis pel materske".split()
    + "ovoc jablk jablc hrus slivk marhul broskyn nektar cersn visn jahod malin cucoried brusnic ribez egres hrozn "
      "orech liesk gastan mandl aroni rakytnik bazov drien sipk must dzus stav kdoul melon".split()
    + "zelenin zemiak mrkv cibul cesnak kapust paradaj paprik uhork tekvic cuket salat spenat petrzlen zeler cvikl "
      "fazul sosovic cicer brokolic karfiol redkov chren pasknak batat sparg rebarbor pazit kopor bylin caj mata "
      "medovk levandul materin rumanc harmanc nechtik hub hliv sampin shiitake".split()
    + "mliek mliec syr bryndz ostiep parenic korbac tvaroh jogurt masl smotan kefir zincic cmar srvatk camembert "
      "vajc vajic maso masov klobas salam slanin udenin pastet jahnac teleci bravc kurac ryby ryba pstruh kapor".split()
    + "chlieb chleb pecivo kvas muka muky krupy krupic vlocky cestovin pohankove kolac susienk pernik oblat musli "
      "granol olej dzem lekvar sirup kompot sterilizovan nakladan ocot pyre cider vino palenk destilat".split()
)
RAW_STEMS = ("obilnin psenic jacmen ovos raz tritikal kukuric repk slnecnic soj krmovin krmiv travn trav pasien luk "
             "lucn seno senaz silaz lucern datelin osiv sadb strukovin olejnin horcic konop lan dobytok hovadzi ovce "
             "kozy osipan kone hydina zvierat chov porast orna ttp lesn drevo slama repa cirok proso pohanka hrach "
             "bob vika facelia mak rasca koriander kmin luskovin travin teliat jalovic baran").split()
FOOD_PHRASES = ("kukurica cukrova", "hovadzie maso", "bravcove maso", "baranie maso", "jahnacie maso",
                "ovcie mlieko", "kozie mlieko", "kravske mlieko", "pohankove krupy", "ovsene vlocky")
NAME_FOOD = re.compile(r"farm|včel|vcel|\bmed|syr|mliek|ovoc|sad\b|záhrad|bylin|vinár|vino|víno|pekár|mlyn|salaš|"
                       r"ranč|kozí|ovčí|jahod|hub|rybn|pstruh|bio|eko", re.I)


def tokens(s):
    return fold(s).replace("-", " ").split()


MEAT_WORDS = {"maso", "masa", "mase", "masom", "masovy", "masove", "masovych", "masa"}
STRONG_FOOD = ("mliek", "syr", "bryndz", "ostiep", "vajc", "vajic", "slanin", "klobas", "salam", "udenin", "chlieb")


def is_food(product):
    name, tags = product["name"], product.get("tags", [])
    f = " ".join(tokens(name))
    if any(t in ("potraviny", "foodstuffs", "víno", "wine") for t in tags):
        return True
    if any(p in f for p in FOOD_PHRASES):
        return True
    toks = f.split()
    if any(t in MEAT_WORDS for t in toks) or any(t.startswith(s) for t in toks for s in STRONG_FOOD):
        return True
    raw = any(t.startswith(s) for t in toks for s in RAW_STEMS)
    food = any(t.startswith(s) for t in toks for s in FOOD_STEMS)
    return food and not raw


def nice(s):
    s = re.sub(r"\s*\((?:[^()]*[A-Z][a-z]+ [a-z]+[^()]*|balenie[^()]*|príprava[^()]*|voľný zber[^()]*)\)", "", s)
    s = re.split(r"\s+/\s+|/\s*(?=Organic|Bio |BIO |Organická)", s)[0]
    s = re.sub(r"\s*[–-]\s*odrod[ay]\b.*$|,\s*odrod[ay]\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s*\([^)]*$", "", s)  # bracket cut off by the 70-character limit
    s = " ".join(s.split()).strip(" ,;-–/")
    if s.isupper() and len(s) > 3:
        s = s.capitalize()
    return s[0].upper() + s[1:] if s else s


def summarize_products(products):
    seen, out = set(), []
    for p in products:
        n = nice(p["name"])
        k = fold(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    if len(out) > 10:
        return ", ".join(out[:10]) + f" a ďalšie ({len(out) - 10})"
    return ", ".join(out)


TYPE_STEMS = [  # first match wins; used for the place category and to drop importers
    ("import", "kav coffee kaka cocoa cokol chocolat chopollen ryz rice banan kokos quino chia protein spirulin "
               "chlorel matcha kurkum zazvor skoric vanil datl kesu pistac goji acai maca agav korenie seasoning spice "
               "superfood citron lemon pomaranc limet grep mango ananas arasid mandl mungo adzuki trstin".split()),
    ("honey", "med medov vcel propolis pel materske".split()),
    ("wine", "vino vina vinny hrozn rizling veltlin frankovk cabernet chardonnay muskat tokaj".split()),
    ("dairy", "mliek mliec syr bryndz ostiep parenic korbac tvaroh jogurt masl smotan kefir zincic cmar srvatk "
              "camembert".split()),
    ("bakery", "chlieb chleb pecivo kvas rozok bagety kolac pernik susienk oblat".split()),
    ("meat", "maso masov klobas salam slanin udenin pastet".split()),
]


def product_type(product):
    toks = tokens(product["name"])
    for typ, stems in TYPE_STEMS:
        if any(t.startswith(s) for t in toks for s in stems):
            return typ
    return "other"


INDUSTRIAL = re.compile(r"kapsul|capsul|extrakt|extract|prášok|prasok|powder|protein|proteín|tablet|"
                        r"billa|lidl|tesco|kaufland|jumbo|kruidvat|rossmann|nature.s promise|"
                        r"gym ?beam|happylife|fabio|private label", re.I)
GENERIC_CN = re.compile(r"^(spracované a konzervované|rastlinné a živočíšne oleje|mliečne výrobky a zmrzlina|"
                        r"výrobky mlynského|škroby|ostatné potravinárske|hotové jedlá|nápoje|"
                        r"potraviny z ekologickej|produkty z ekologickej|osivá z ekologickej|krmivá z ekologickej|"
                        r"balenie|doplnky stravy)", re.I)


def classify(r, products, kinds, activities):
    """'food' = makes something people can buy; 'raw' = only crops/animals for processors;
    'import' / 'industrial' / 'trader' = not local food sold by its maker; 'unknown' = no product list, no hint."""
    if "Import" in activities and "Production" not in activities:
        return "trader", []
    if products:
        n = len(products)
        if sum(1 for p in products if GENERIC_CN.search(p["name"])) * 2 >= n:
            return "trader", []
        imported = sum(1 for p in products if product_type(p) == "import")
        if imported * 2 >= n or ("Production" not in activities and imported * 4 >= n):
            return "import", []
        if sum(1 for p in products if INDUSTRIAL.search(p["name"])) * 2 >= n:
            return "industrial", []
    food = [p for p in products if is_food(p)]
    if food:
        return "food", food
    if products:
        return ("raw", []) if not ({"processed_food", "wine"} & set(kinds)) else ("food", [])
    if {"processed_food", "wine"} & set(kinds):
        return "food", []
    return ("unknown", []) if not NAME_FOOD.search(r["name"]) else ("food", [])


PROCESSED = ("stava", "dzem", "sirup", "tofu", "tempeh", "muka", "muky", "vlocky", "cestovin", "chlieb", "chleb",
             "pecivo", "syr", "bryndz", "ostiep", "uden", "slanin", "klobas", "salam", "pyre", "must", "olej", "caj",
             "ocot", "susen", "lekvar", "kompot", "ajvar", "natierk", "sterilizovan", "nakladan", "bujon", "krekr",
             "grissini", "susienk", "pastet", "vino", "destilat", "gin", "palenk", "limonad", "jogurt", "tvaroh")


def organic_category(name, kinds, food):
    n = fold(name)
    types = collections.Counter(product_type(p) for p in food)
    top = types.most_common(1)[0][0] if types else ""
    processed = sum(1 for p in food if any(t.startswith(s) for t in tokens(p["name"]) for s in PROCESSED))
    if re.search(r"\bsalas", n):
        return "salas", ""
    if re.search(r"wine|vinar|vinic|\bvino\b|vinohrad|vinne", n) or top == "wine" or kinds == ["wine"]:
        return "winery", ""
    if re.search(r"vcelar|vceli\b|vcelia|vcelstv|\bmed\b|apis\b|apiar|medar", n) or top == "honey":
        return "honey", ""
    if re.search(r"pekar|pekarn", n) or top == "bakery":
        return "bakery", ""
    if top == "dairy":
        cheese = any(re.search(r"syr|bryndz|ostiep|jogurt|tvaroh|masl|zincic|kefir|smotan", fold(p["name"])) for p in food)
        return ("producer", "Syry a mliečne výrobky") if cheese else ("farm", "Mliečna farma")
    if top == "meat":
        return "producer", "Mäso a údeniny"
    if food and processed * 2 >= len(food):
        return "producer", ""
    if not food and "processed_food" in kinds and not ({"plants", "livestock"} & set(kinds)):
        return "producer", ""
    return "farm", ""


def organic_features(geo, admin, outreach, review, stats, only_with_details=False):
    details = json.loads((ROOT / "data/out/organic_details.json").read_text()) \
        if (ROOT / "data/out/organic_details.json").exists() else {}
    inv = [r for r in csv.DictReader(open(ROOT / "data/out/inventory.csv", encoding="utf-8"))
           if r["source"] == "organic_eu" and r["consumer_relevant"] == "True"]
    orgs = {o["certificate"]: o for o in csv.DictReader(open(ROOT / "data/out/organic_operators.csv", encoding="utf-8"))}
    feats = []
    for i, r in enumerate(inv):
        o = orgs[r["source_id"]]
        if o["expires"] and o["expires"] < TODAY:
            stats["organic"]["expired"] += 1
            continue
        if only_with_details and r["source_id"] not in details:
            continue
        d = details.get(r["source_id"], {})
        products, premises = d.get("products", []), d.get("premises", [])
        kinds = r["category"].removeprefix("organic_").split("+")
        cls, food = classify(r, products, kinds, o["activities"])
        kraj = TRACES_KRAJ.get(o["region"], "")
        person = r["is_person"] == "True" or not COMPANY.search(r["name"])
        cat, label = organic_category(r["name"], kinds, food)
        if cls == "food" and re.search(r"\ba\.\s?s\.", r["name"]) and cat in ("producer", "bakery"):
            cls = "industrial"  # joint-stock dairies, bakeries and drinks makers sell through shops, not directly
        product_text = summarize_products(food or products)
        base = dict(name=r["name"], category=cat, kraj=kraj, products=product_text, ico=r["ico"],
                    source=f"https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/{o['certificate']}.pdf")
        if person and cls != "food":
            stats["organic"][f"sole trader, not on map anyway: {cls}"] += 1
            continue
        if person:
            stats["organic"]["sole trader"] += 1
            outreach.append(dict(base, kind="certified organic (sole trader)",
                                 address=f"{o['street']}, {r['postal']} {o['city']}", km="",
                                 note="Publish only after they agree"))
            continue
        if cls != "food":
            stats["organic"][f"not on map: {cls}"] += 1
            review.append(dict(base, decision=f"not on map ({cls})", address=f"{o['street']}, {r['postal']} {o['city']}",
                               location="", precision="", premises=len(premises)))
            continue
        # where: a production premise from the certificate if there is one, else the registered address
        prod = [p for p in premises if p["activity"] in ("Production", "Preparation")]
        loc_src, street, postal_, city = "registered", o["street"], r["postal"], o["city"]
        if prod:
            p0 = prod[0]
            loc_src, street, postal_, city = "premises", p0["street"] or p0["label"], p0["postal"], p0["city"]
        lat, lon, precision = geo.locate(street, postal_, city, kraj)
        if lat is None and loc_src == "premises":
            loc_src, street, postal_, city = "registered", o["street"], r["postal"], o["city"]
            lat, lon, precision = geo.locate(street, postal_, city, kraj)
        if lat is None:
            stats["organic"]["not geocoded"] += 1
            review.append(dict(base, decision="not on map (address not found)",
                               address=f"{o['street']}, {r['postal']} {o['city']}", location="", precision="",
                               premises=len(premises)))
            continue
        city_clean = re.sub(r"^District of ", "", city)
        premise_text = "; ".join(f"{p['label']}, {p['street']}, {p['postal'][:3]} {p['postal'][3:]} {p['city']}".replace(", , ", ", ")
                                 for p in prod[:6]) if len(prod) > 1 else ""
        feats.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "id": f"bio-{o['operator_id']}", "name": r["name"], "category": cat,
                **({"label": label} if label else {}), "bio": True,
                "address": street, "postcode": f"{postal_[:3]} {postal_[3:5]}" if re.fullmatch(r"\d{5}", postal_ or "") else "",
                "addr_city": city_clean, "hours": "", "phone": "", "website": "",
                "products": product_text, "premises": premise_text,
                "cert": o["certificate"], "cert_expires": o["expires"], "precision": precision, "source": "traces",
                "_loc": loc_src, "_kraj_cert": kraj, "_ico": r["ico"],
            }})
        stats["organic"][f"geocoded {precision} ({loc_src})"] += 1
        if i % 50 == 0:
            print(f"organic {i}/{len(inv)} (nominatim requests so far: {geo.requests})", flush=True)
    geo.save()
    return feats


# --------------------------------------------------------------- main ----------------------------------------------
def register_outreach(outreach):
    """Register candidates for outreach only (no coordinates)."""
    for r in csv.DictReader(open(ROOT / "data/out/inventory.csv", encoding="utf-8")):
        if (r["source"] == "rpo" and r["consumer_relevant"] == "True"
                and r["category"] in ("bakery", "confectionery", "dairy", "meat", "farm_mixed", "farm_livestock",
                                      "fruit_veg_processing", "honey", "mill", "wine", "shop_bakery")):
            outreach.append(dict(name=r["name"], kind="register candidate", category=r["category"], kraj=r["region"],
                                 address=f"{r['street']}, {r['postal']} {r['municipality']}", ico=r["ico"], km="",
                                 products="", source=r["link"], note="Check first: activity code may be wrong"))


MERGE_GENERIC = {"farma", "farm", "agro", "bio", "vinarstvo", "pivnica", "salas", "druzstvo", "polnohospodarske",
                 "rolnicke", "winery", "vineyards", "wines", "pince", "rodinne", "sady", "predajna", "obchod", "trh",
                 # wine regions and common words that many unrelated businesses share
                 "tokaj", "tokajske", "tokajsky", "tokajska", "vino", "vina", "wine", "family", "vinohrad",
                 "vinohradnictvo", "malokarpatske", "slovensko", "slovakia", "slovak", "dvor", "statok", "pekaren"}


# which OSM place types a certified operator of each type can be the same business as (a farm is not the village bakery)
COMPATIBLE = {"winery": {"winery"}, "bakery": {"bakery"}, "honey": {"honey", "farm"},
              "salas": {"salas", "farm", "dairy"}, "farm": {"farm", "dairy", "salas", "honey", "vending", "butcher",
                                                             "greengrocer", "organic_shop"},
              "producer": {"producer", "dairy", "farm", "deli", "organic_shop"}}


def distinctive(name):
    """Words that identify a business: 'Tajna Vineyards & Winery' -> {'tajna'}; 'Pivnica Kövesd Pince' -> {'kovesd'}."""
    return {w for w in norm(name).split() if len(w) >= 4 and w not in MERGE_GENERIC}


def apply_checks(feats, stats):
    """Hand-check results (data/checks/places_checks.csv) and the website check (data/checks/websites.csv)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from check_websites import norm_url  # noqa: PLC0415
    path = ROOT / "data/checks/places_checks.csv"
    checks = {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))} if path.exists() else {}
    wpath = ROOT / "data/checks/websites.csv"
    sites = {r["url"]: r for r in csv.DictReader(open(wpath, encoding="utf-8"))} if wpath.exists() else {}
    out = []
    for f in feats:
        p = f["properties"]
        c = checks.get(p["id"]) or next((checks[i] for i in p.get("_bio_ids", []) if i in checks), None)
        if c and p["source"] == "osm" and c["status"] in ("wholesale", "not_local"):
            c = None  # the certificate holder sells wholesale, but this OSM place is a shop people can visit
        if c and c["status"] in ("wholesale", "closed", "duplicate", "not_local"):
            stats["checks"][f"removed: {c['status']}"] += 1
            continue
        if c and c["status"] == "sells":
            p["checked"], p["how"] = c["checked"], c["how"]
            stats["checks"]["verified: sells directly"] += 1
        if c and c["status"] in ("sells", "unclear"):
            for k in ("website", "phone"):
                if c[k] and not p.get(k):
                    p[k] = c[k]
                    stats["checks"][f"{k} added from check"] += 1
        if p.get("website"):
            r = sites.get(norm_url(p["website"]))
            if r and r["ok"] == "0":
                stats["checks"]["dead website removed"] += 1
                del p["website"]
                p["web_dead"] = True  # the card warns that the place may have closed
            elif r and r["reason"].startswith("page gone"):
                p["website"] = r["final_url"]
                stats["checks"]["broken deep link replaced by home page"] += 1
        out.append(f)
    return out


def spread_stacked(feats, stats, radius=14):
    """Places at (almost) the same spot, e.g. sister companies on one farmyard: put them on a small circle so each
    pin can be clicked."""
    groups, seen = [], set()
    for i, f in enumerate(feats):
        if i in seen:
            continue
        grp = [i] + [j for j in range(i + 1, len(feats)) if j not in seen
                     and metres(f["geometry"]["coordinates"], feats[j]["geometry"]["coordinates"]) < 8]
        seen.update(grp)
        if len(grp) > 1:
            groups.append(grp)
    for grp in groups:
        cx = sum(feats[i]["geometry"]["coordinates"][0] for i in grp) / len(grp)
        cy = sum(feats[i]["geometry"]["coordinates"][1] for i in grp) / len(grp)
        for k, i in enumerate(sorted(grp, key=lambda i: feats[i]["properties"]["id"])):
            a = 2 * math.pi * k / len(grp)
            feats[i]["geometry"]["coordinates"] = [round(cx + radius * math.cos(a) / 73_000, 6),
                                                   round(cy + radius * math.sin(a) / 111_000, 6)]
    stats["checks"]["stacked pins spread out (groups)"] = len(groups)


def obce_json(admin):
    """Municipalities for the village search on the site: [name, okres, lon, lat], the point at the village centre.

    Names and outlines come from OSM (obce, and the city parts of Bratislava and Košice); the point is the GeoNames
    village centre inside the outline when there is one, otherwise the middle of the outline."""
    gaz = {}
    for line in open(ROOT / "data/raw/geonames/places/SK.txt", encoding="utf-8"):
        g = line.rstrip("\n").split("\t")
        if g[7] in ("PPL", "PPLA", "PPLA2", "PPLC", "PPLX", "ADM3"):
            gaz.setdefault(fold(g[1]), []).append((float(g[5]), float(g[4]), g[7] == "ADM3"))
    rows, seen = [], set()
    for lvl in ("8", "9"):
        for a in admin.levels.get(lvl, []):
            if not a["name"]:
                continue
            short = a["name"].split("-", 1)[-1] if lvl == "9" else a["name"]  # "Bratislava-Petržalka" -> Petržalka
            pts = sorted(gaz.get(fold(short), []), key=lambda p: p[2])  # populated place before admin point
            point = next(((x, y) for x, y, _ in pts if Admin.contains(a, x, y)), None)
            if not point:
                ring = max(a["rings"], key=len)
                point = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
                if not Admin.contains(a, *point):
                    x0, y0, x1, y1 = a["bbox"]
                    point = ((x0 + x1) / 2, (y0 + y1) / 2)
            info = admin.lookup(*point)
            if not info["in_sk"]:
                continue
            name = info["obec"] or a["name"]
            if (name, info["okres"]) in seen:
                continue
            seen.add((name, info["okres"]))
            rows.append([name, info["okres"], round(point[0], 5), round(point[1], 5)])
    rows += [["Bratislava", "", 17.10674, 48.14816], ["Košice", "", 21.25808, 48.71395]]  # the cities as a whole
    return sorted(rows, key=lambda r: (fold(r[0]), r[1]))


def kraje_geojson(admin):
    feats = []
    for a in admin.levels.get("4", []):
        name = a["name"].replace(" kraj", "").strip()
        rings = []
        for ring in a["rings"]:
            thin = [ring[0]]
            for p in ring[1:-1]:
                if abs(p[0] - thin[-1][0]) > 0.004 or abs(p[1] - thin[-1][1]) > 0.004:
                    thin.append(p)
            thin.append(ring[-1])
            if len(thin) >= 4:
                rings.append([[round(x, 4), round(y, 4)] for x, y in thin])
        feats.append({"type": "Feature", "properties": {"id": KRAJ_SLUG.get(name, ""), "name": name},
                      "geometry": {"type": "MultiLineString", "coordinates": rings}})
    return {"type": "FeatureCollection", "features": feats}


# --------------------------------------------------------- what you can buy ----------------------------------------
# Product groups for the site's "Čo chcete kúpiť?" filter (keys must match BUY in site/app.js). A place gets a group when
#  - its type sells it by definition (a bakery sells bread, a salaš cheese), or
#  - a stem starts a word in its type label, product list or hand-check note, or
#  - a safer, shorter stem starts a word in its name (names also carry village names: "Hruštín", "Včelince").
# Places whose offer we do not know (most markets and farm shops) get no group and only show under "Všetko".
BUY = {
    "mlieko": (r"mliek|mliec|milk|kefir|jogurt|tvaroh|maslo|masla|smotan|cmar|zakys", r"mliek|mliec", {"dairy"}),
    "syr": (r"syr|bryndz|ostiep|parenic|korbac|cheese|zincic|camembert|mliecne vyrobky", r"syr|bryndz",
            {"salas", "dairy"}),
    "vajcia": (r"vajc|vajic|egg|hydinar|slepac|nosnic", r"vajc|vajic|hydinar", set()),  # hydináreň: a poultry farm
    "maso": (r"maso|masov|masiar|klobas|salam[ay]\b|salami\b|slanin|udenin|pastet|sunk|ryby|ryba\b|rybar|pstruh|kapor|"
             r"meat|fish|zverin|divin", r"maso|masiar|udenin|rybar|pstruh", {"butcher"}),
    "med": (r"med\b|medu\b|medy\b|medovin|medar|medomat|vcelar|vcelie produkt|vcelstv|propolis|honey",
            r"med\b|medar|medomat|vcelar", {"honey"}),
    "ovocie": (r"ovoc|jablk|jablc|hrusk|slivk|marhul|broskyn|nektarin|cersn|jahod|malin|cucoried|brusnic|ribez|egres|"
               r"orech|liesk|gastan|aroni|rakytnik|bazov|drien|sipk|kdoul|melon|samozber|sad\b|sady\b|apple|fruit|berr",
               r"ovoc|sad\b|sady\b|samozber|jablk|cucoried|berry", {"greengrocer"}),
    "zelenina": (r"zelenin|zemiak|mrkv|cibul|cesnak|kapust|paradaj|paprik|uhork|cuket|salat|spenat|petrzlen|zeler|cvikl|"
                 r"brokolic|karfiol|redkov|chren|sparg|rebarbor|huby\b|hliv|sampin|potato|tomato|vegetabl|mushroom",
                 r"zelenin|zemiak", {"greengrocer"}),
    "pecivo": (r"chlieb|chleb|peciv|pekar|kolac|bread|bakery|kvasok", r"peka|chlieb", {"bakery"}),
    "vino": (r"vino\b|vina\b|vinar|wine", r"vino\b|vinar|vinic|winery|wine", {"winery"}),
}
BUY_RX = {k: (re.compile(rf"\b(?:{text})"), re.compile(rf"\b(?:{name})")) for k, (text, name, _) in BUY.items()}


def buy_groups(p):
    text = fold(" ".join([p.get("label", ""), p.get("products", ""), p.get("how", "")]))
    name = fold(p.get("name", ""))
    return [k for k, (_, _, cats) in BUY.items()
            if p["category"] in cats or BUY_RX[k][0].search(text) or BUY_RX[k][1].search(name)]


def main():
    stats = {"osm_kept": collections.Counter(), "osm_skipped": collections.Counter(),
             "organic": collections.Counter(), "checks": collections.Counter()}
    admin = Admin()
    geo = Geocoder(admin)
    outreach, review = [], []
    feats = osm_features(stats)
    bio = organic_features(geo, admin, outreach, review, stats)

    # admin areas for everything
    for f in feats + bio:
        x, y = f["geometry"]["coordinates"]
        a = admin.lookup(x, y)
        f["properties"].update(obec=a["obec"], okres=a["okres"], kraj=a["kraj"], kraj_id=a["kraj_id"], _town=a["town"])
    feats = [f for f in feats if f["properties"]["kraj"]]  # drop the few OSM points just across the border
    city_salas = [f for f in feats if f["properties"]["category"] == "salas"
                  and re.match(r"(Bratislava|Košice)-", f["properties"]["obec"])]
    stats["osm_skipped"]["salas: restaurant in Bratislava/Košice"] += len(city_salas)
    feats = [f for f in feats if f not in city_salas]

    # Certificate addresses can be registered offices, not the farm:
    #  - the same address used by 2+ operators in a town is a virtual office or an accountant
    #    (in a village it is usually sister companies on one farmyard, which is the right place)
    #  - a farm, vineyard or apiary registered in Bratislava or Košice city is almost always an office
    addr_count = collections.Counter(norm(f"{f['properties']['address']} {f['properties']['addr_city']}") for f in bio)
    kept = []
    for f in bio:
        p = f["properties"]
        shared = addr_count[norm(f"{p['address']} {p['addr_city']}")] > 1 and p["_town"]
        city_office = (p["_loc"] == "registered" and p["category"] in ("farm", "winery", "honey", "salas")
                       and re.match(r"(Bratislava|Košice)", p["obec"] or ""))
        if shared or city_office:
            why = "shared address" if shared else "city office"
            stats["organic"][f"to outreach: {why}"] += 1
            outreach.append(dict(name=p["name"], kind=f"certified organic (office address: {why})",
                                 category=p["category"], kraj=p["kraj"], address=f"{p['address']}, {p['addr_city']}",
                                 ico=p["_ico"], km="", products=p["products"],
                                 source=f"https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/{p['cert']}.pdf",
                                 note="Address is a registered office; find where they farm and sell"))
            review.append(dict(name=p["name"], category=p["category"], kraj=p["kraj"], products=p["products"],
                               ico=p["_ico"], source=p["cert"], decision=f"outreach ({why})",
                               address=f"{p['address']}, {p['addr_city']}", location=p["_loc"],
                               precision=p["precision"], premises=p["premises"].count(";") + 1 if p["premises"] else 0))
        else:
            kept.append(f)
            review.append(dict(name=p["name"], category=p["category"], kraj=p["kraj"], products=p["products"],
                               ico=p["_ico"], source=p["cert"], decision="on map", address=f"{p['address']}, {p['addr_city']}",
                               location=p["_loc"], precision=p["precision"],
                               premises=p["premises"].count(";") + 1 if p["premises"] else 0))
    bio = kept

    # OSM places that belong to a certified operator: merge (keep the OSM location, add the certificate)
    bio_by_name = {}
    for f in bio:
        bio_by_name.setdefault(norm(f["properties"]["name"]), []).append(f)
    merged = set()
    for f in feats:
        keys = {norm(f["properties"]["name"]), norm(f["properties"].get("_operator", ""))}
        cands = [b for k in keys if len(k) >= 5 for b in bio_by_name.get(k, [])]
        ftok = distinctive(f["properties"]["name"]) | distinctive(f["properties"].get("_operator", ""))
        cands += [b for b in bio if b not in cands and ftok & distinctive(b["properties"]["name"])
                  and f["properties"]["category"] in COMPATIBLE.get(b["properties"]["category"], set())
                  and metres(b["geometry"]["coordinates"], f["geometry"]["coordinates"]) < 600]  # "Tajna" / "Tajna Vineyards"
        for b in cands:
            bx, by = b["geometry"]["coordinates"]
            fx, fy = f["geometry"]["coordinates"]
            if abs(bx - fx) < 0.6 and abs(by - fy) < 0.4:  # same business, roughly within 40 km
                bp = b["properties"]
                osm_text = f["properties"]["products"]
                f["properties"].update(bio=True, cert=bp["cert"], cert_expires=bp["cert_expires"],
                                       products=bp["products"] if len(bp["products"]) > len(osm_text) else osm_text,
                                       _bio_ids=f["properties"].get("_bio_ids", []) + [bp["id"]])
                merged.add(bp["id"])
    stats["organic"]["merged into OSM place"] = len(merged)
    feats += [b for b in bio if b["properties"]["id"] not in merged]

    feats = apply_checks(feats, stats)
    spread_stacked(feats, stats)

    # tidy public properties
    for f in feats:
        p = f["properties"]
        p["buy"] = buy_groups(p) or None
        for k in [k for k in p if k.startswith("_")]:
            del p[k]
        if not p.get("address") and p.get("addr_city"):
            p["address"] = ""
        city = p.pop("addr_city", None)
        if p["source"] == "traces" and city:
            p["city"] = city  # the certificate's town: "Navigovať" sends Google "street, postcode town"
        p["approx"] = p["precision"] in ("village", "postcode")
        for k in [k for k, v in p.items() if v in ("", None) and k not in ("name",)]:
            del p[k]

    feats.sort(key=lambda f: f["properties"]["id"])
    meta = {"generated": TODAY, "count": len(feats), "bio": sum(1 for f in feats if f["properties"]["bio"]),
            "attribution": ["© prispievatelia OpenStreetMap (ODbL)",
                            "EÚ register ekologických certifikátov TRACES, Európska komisia",
                            "GeoNames (CC BY 4.0)"]}
    (ROOT / "site/data/places.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "metadata": meta, "features": feats}, ensure_ascii=False, separators=(",", ":")))
    with open(ROOT / "site/data/places.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["id", "name", "category", "label", "bio", "obec", "okres", "kraj", "address", "postcode", "city", "lat", "lon",
                "products",
                "buy", "hours", "phone", "website", "cert", "cert_expires", "precision", "source"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for f in feats:
            p = f["properties"]
            w.writerow({**p, "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
                        "bio": "áno" if p.get("bio") else "", "buy": ";".join(p.get("buy", []))})
    obce = obce_json(admin)
    (ROOT / "site/data/obce.json").write_text(json.dumps(obce, ensure_ascii=False, separators=(",", ":")))
    (ROOT / "site/data/kraje.geojson").write_text(json.dumps(kraje_geojson(admin), ensure_ascii=False,
                                                             separators=(",", ":")))

    register_outreach(outreach)
    with open(ROOT / "data/out/outreach_slovakia.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["kraj", "name", "kind", "category", "products", "address", "ico", "km",
                                          "source", "note"], extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(outreach, key=lambda o: (o.get("kraj", ""), o["kind"], o["name"])))
    with open(ROOT / "data/out/organic_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["decision", "kraj", "name", "category", "products", "address", "location",
                                          "precision", "premises", "ico", "source"], extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(review, key=lambda o: (o["decision"], o.get("kraj", ""), o["name"])))

    by_cat = collections.Counter(f["properties"]["category"] for f in feats)
    by_kraj = collections.Counter(f["properties"]["kraj"] for f in feats)
    bio_kraj = collections.Counter(f["properties"]["kraj"] for f in feats if f["properties"]["bio"])
    prec = collections.Counter(f["properties"]["precision"] for f in feats)
    lines = [f"# Map data report ({TODAY})", "",
             f"Public map: **{len(feats)} places**, {meta['bio']} with a BIO certificate.", "",
             "| Kraj | Places | BIO |", "|---|---:|---:|"]
    lines += [f"| {k} | {by_kraj[k]} | {bio_kraj[k]} |" for k in sorted(by_kraj, key=lambda k: -by_kraj[k])]
    lines += ["", "| Category | Places |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in by_cat.most_common()]
    by_buy = collections.Counter(k for f in feats for k in f["properties"].get("buy", []))
    lines += ["", "What you can buy (site filter): " + ", ".join(f"{k} {by_buy[k]}" for k in BUY)
              + f"; offer unknown: {sum(1 for f in feats if not f['properties'].get('buy'))}"]
    lines += ["", "Location precision: " + ", ".join(f"{k} {v}" for k, v in prec.most_common()), "",
              "## Certified organic operators", ""] + [f"- {k}: {v}" for k, v in sorted(stats["organic"].items())]
    lines += ["", "## Hand-check and link check", ""] + [f"- {k}: {v}" for k, v in sorted(stats["checks"].items())]
    lines += ["", "## OpenStreetMap", "", "Kept: " + ", ".join(f"{k} {v}" for k, v in stats["osm_kept"].most_common()),
              "", "Skipped: " + ", ".join(f"{k} {v}" for k, v in stats["osm_skipped"].most_common()), "",
              f"Private outreach list: {len(outreach)} rows "
              + str(dict(collections.Counter(o['kind'].split(':')[0] for o in outreach))),
              f"Nominatim requests this run: {geo.requests}"]
    (ROOT / "data/out/report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
