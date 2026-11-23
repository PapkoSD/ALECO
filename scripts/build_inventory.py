"""Merge OSM places, EU organic certificates and RPO register entries into one producer inventory.

Inputs : data/raw/osm_sk.json, data/out/organic_operators.csv, data/out/rpo_producers.csv
Outputs: data/out/osm_places.csv, data/out/inventory.csv, data/out/summary.json
"""
import collections
import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"

LEGAL = r"\b(s\.?\s?r\.?\s?o\.?|spol\.?|a\.?\s?s\.?|v\.?\s?o\.?\s?s\.?|k\.?\s?s\.?|druzstvo|pd|shr|ing\.?|mgr\.?|bc\.?|" \
        r"ing|mudr|phd|rndr|ekologicke|polnohospodarske|s\.r\.o|sro|as|spolocnost s rucenim obmedzenym)\b"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(LEGAL, " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def postal(s):
    return re.sub(r"\D", "", s or "")[:5]


TRACES_REGION = {"Region of Bratislava": "Bratislavský", "Region of Trnava": "Trnavský",
                 "Region of Trenčín": "Trenčiansky", "Region of Nitra": "Nitriansky",
                 "Region of Žilina": "Žilinský", "Region of Banská Bystrica": "Banskobystrický",
                 "Region of Prešov": "Prešovský", "Region of Košice": "Košický"}

OSM_CAT = {"bakery": "bakery", "butcher": "shop_meat", "greengrocer": "shop_fruit_veg", "farm": "farm_shop",
           "health_food": "shop_organic", "organic": "shop_organic", "cheese": "shop_dairy", "dairy": "shop_dairy",
           "deli": "shop_food_specialised"}

ORG_CAT = {"(a)": "plants", "(b)": "livestock", "(c)": "aquaculture", "(d)": "processed_food", "(e)": "feed",
           "(f)": "wine", "(g)": "other"}


def main():
    rpo = list(csv.DictReader(open(OUT / "rpo_producers.csv", encoding="utf-8")))
    org = list(csv.DictReader(open(OUT / "organic_operators.csv", encoding="utf-8")))
    osm = json.load(open(ROOT / "data/raw/osm_sk.json", encoding="utf-8"))["elements"]

    muni_region = {}
    for r in rpo:
        if r["region"]:
            muni_region.setdefault(norm(r["municipality"]), r["region"])

    rpo_by_name = collections.defaultdict(list)
    for r in rpo:
        rpo_by_name[norm(r["name"])].append(r)

    rows = []
    # 1) organic operators (authoritative "bio")
    org_names = {}
    for o in org:
        # TRACES category labels: (a) Unprocessed plants…, (b) Livestock…, (c) Algae and unprocessed aquaculture…,
        # (d) Processed agricultural products… for use as food, (e) Feed, (f) Wine, (g) Other products
        prefixes = {"unprocessed plants": "plants", "livestock": "livestock", "algae": "aquaculture",
                    "processed agricultural": "processed_food", "feed": "feed", "wine": "wine", "other": "other"}
        kinds = []
        for label in o["product_categories"].split(";"):
            label = label.strip().lower()
            kinds += [v for k, v in prefixes.items() if label.startswith(k)]
        producing = "Production" in o["activities"] or "Preparation" in o["activities"]
        consumer = producing and any(k in kinds for k in ("plants", "livestock", "processed_food", "wine"))
        match = None
        cands = rpo_by_name.get(norm(o["name"]), [])
        if cands:
            same = [c for c in cands if postal(c["postal"]) == postal(o["postal"])]
            match = (same or cands)[0]
        is_person = bool(re.search(r"\bSHR\b|samostatne hosp", o["name"], re.I)) or (
            match is not None and match["is_person"] == "True")
        row = dict(source="organic_eu", source_id=o["certificate"], name=o["name"],
                   category="organic_" + ("+".join(kinds) or "unknown"), organic="certified",
                   organic_cert=o["certificate"], organic_activities=o["activities"],
                   ico=match["ico"] if match else "", nace=match["nace_label"] if match else "",
                   street=o["street"], postal=postal(o["postal"]), municipality=o["city"],
                   region=TRACES_REGION.get(o["region"], o["region"]), lat="", lon="", website="", phone="",
                   opening_hours="", is_person=is_person, consumer_relevant=consumer,
                   confidence="high", link=o["certificate_url"])
        rows.append(row)
        org_names[norm(o["name"])] = o["certificate"]
        if match:
            match["_organic"] = o["certificate"]

    # 2) OSM places (public, located, often with contacts)
    osm_rows = []
    for e in osm:
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if "shop" in t:
            cat = OSM_CAT.get(t["shop"], "shop_" + t["shop"])
        elif "vending" in t:
            cat = "vending_milk_eggs"
        elif t.get("amenity") == "marketplace":
            cat = "marketplace"
        elif t.get("place") == "farm":
            cat = "farm"
        else:
            cat = "other"
        name = t.get("name") or t.get("brand") or ""
        organic = "osm_tag" if t.get("organic") in ("yes", "only") else ""
        if norm(name) and norm(name) in org_names:
            organic = "certified"
        city = t.get("addr:city") or t.get("addr:place") or ""
        r = dict(source="osm", source_id=f"{e['type']}/{e['id']}", name=name, category=cat, organic=organic,
                 organic_cert=org_names.get(norm(name), ""), organic_activities="", ico="", nace="",
                 street=" ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x),
                 postal=postal(t.get("addr:postcode")), municipality=city,
                 region=muni_region.get(norm(city), ""), lat=lat, lon=lon,
                 website=t.get("website") or t.get("contact:website") or "",
                 phone=t.get("phone") or t.get("contact:phone") or "", opening_hours=t.get("opening_hours", ""),
                 is_person=False,
                 consumer_relevant=cat not in ("shop_supermarket", "shop_convenience", "shop_chemist", "other")
                 and not (t.get("brand") and cat == "bakery" and t.get("brand") in ("Kaufland", "Lidl", "Tesco")),
                 confidence="high", link=f"https://www.openstreetmap.org/{e['type']}/{e['id']}")
        osm_rows.append(r)
    rows += osm_rows

    # 3) RPO register candidates (broad, needs filtering)
    low = {("farm_livestock", "licence_text"), ("farm_crops", "licence_text"), ("food_other", "nace")}
    for r in rpo:
        if r.get("_organic"):
            continue  # already represented by its organic certificate row
        conf = "low" if (r["category"], r["match"]) in low else "medium"
        big_agri = r["category"].startswith("farm") and r["legal_form"] in ("Akciová spoločnosť", "Družstvo")
        rows.append(dict(source="rpo", source_id=r["ico"], name=r["name"], category=r["category"], organic="",
                         organic_cert="", organic_activities="", ico=r["ico"], nace=r["nace_label"],
                         street=f"{r['street']} {r['number']}".strip(), postal=r["postal"],
                         municipality=r["municipality"], region=r["region"], lat="", lon="", website="", phone="",
                         opening_hours="", is_person=r["is_person"] == "True",
                         consumer_relevant=conf != "low" and not big_agri, confidence=conf,
                         link=f"https://www.orsr.sk/hladaj_ico.asp?ICO={r['ico']}&SID=0"))

    fields = list(rows[0].keys())
    with open(OUT / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(OUT / "osm_places.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(osm_rows)

    def count(filter_=lambda r: True, key="category"):
        return dict(collections.Counter(str(r[key]) for r in rows if filter_(r)).most_common())

    summary = {
        "total_rows": len(rows),
        "by_source": count(key="source"),
        "organic_operators": len(org),
        "organic_consumer_relevant": sum(1 for r in rows if r["source"] == "organic_eu" and r["consumer_relevant"]),
        "organic_matched_to_rpo_ico": sum(1 for r in rows if r["source"] == "organic_eu" and r["ico"]),
        "organic_by_kind": count(lambda r: r["source"] == "organic_eu"),
        "organic_by_region": count(lambda r: r["source"] == "organic_eu", "region"),
        "osm_by_category": count(lambda r: r["source"] == "osm"),
        "osm_with_contact": sum(1 for r in osm_rows if r["website"] or r["phone"]),
        "osm_matched_to_organic": sum(1 for r in osm_rows if r["organic"] == "certified"),
        "rpo_by_category": count(lambda r: r["source"] == "rpo"),
        "rpo_by_confidence": count(lambda r: r["source"] == "rpo", "confidence"),
        "consumer_relevant_by_region": count(lambda r: r["consumer_relevant"] is True, "region"),
        "sole_traders_rows (GDPR personal data)": sum(1 for r in rows if r["is_person"] is True),
        "bratislava_region_consumer_relevant": count(
            lambda r: r["consumer_relevant"] is True and r["region"] == "Bratislavský"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
