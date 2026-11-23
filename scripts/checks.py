"""Hand-check results for places on the map: data/checks/places_checks.csv (committed, curated by hand).

status values
  sells      checked: sells to people directly (farm shop, e-shop, markets, delivery, vending machine)
  wholesale  checked: only sells to processors, wholesalers or supermarkets -> taken off the map
  closed     checked: no longer operating -> taken off the map
  duplicate  same place as another entry (see note) -> taken off the map
  not_local  not local food: supplements, cosmetics, products from imported raw materials -> taken off the map
  unclear    looked, found nothing useful -> stays, with the "please verify" note
`how` is shown on the site in Slovak ("Predajňa na farme, e-shop"); website/phone fill gaps in the data. The product
words in `how` ("mlieko, syry, vajcia") also decide what the place is listed under in "Čo chcete kúpiť?".
Any place on the map can be checked, OSM shops and markets too: `set` adds the row when the id is not in the file yet.

  python3 scripts/checks.py init            add rows for BIO places not in the file yet (keeps what is filled in)
  python3 scripts/checks.py set < x.jsonl   update rows: one JSON object per line with "id" and the fields to set
  python3 scripts/checks.py stats           counts by status
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/checks/places_checks.csv"
FIELDS = ["id", "name", "kraj", "okres", "obec", "category", "products", "status", "how", "website", "phone",
          "source", "checked", "note"]
STATUSES = {"sells", "wholesale", "closed", "duplicate", "not_local", "unclear", ""}
KRAJ_ORDER = ["Bratislavský", "Trnavský", "Trenčiansky", "Nitriansky", "Žilinský", "Banskobystrický", "Prešovský",
              "Košický"]


def load():
    if not PATH.exists():
        return {}
    return {r["id"]: r for r in csv.DictReader(open(PATH, encoding="utf-8"))}


def save(rows):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(rows.values(), key=lambda r: (KRAJ_ORDER.index(r["kraj"]) if r["kraj"] in KRAJ_ORDER else 9,
                                                 r["okres"], r["name"]))
    with open(PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(order)


def init():
    rows = load()
    places = json.loads((ROOT / "site/data/places.geojson").read_text())["features"]
    added = 0
    for feat in places:
        p = feat["properties"]
        if not p.get("bio") or p["id"] in rows:
            continue
        rows[p["id"]] = {k: "" for k in FIELDS} | {
            "id": p["id"], "name": p["name"], "kraj": p.get("kraj", ""), "okres": p.get("okres", ""),
            "obec": p.get("obec", ""), "category": p.get("label") or p["category"],
            "products": (p.get("products") or "")[:160]}
        added += 1
    save(rows)
    print(f"{len(rows)} rows, {added} added")


def set_rows():
    rows = load()
    places = None
    n = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        upd = json.loads(line)
        rid = upd.pop("id")
        if rid not in rows:
            # any place on the map can be checked, OSM shops and markets too: add its row first
            places = places or {f["properties"]["id"]: f["properties"]
                                for f in json.loads((ROOT / "site/data/places.geojson").read_text())["features"]}
            p = places.get(rid)
            if not p:
                sys.exit(f"unknown id {rid}")
            rows[rid] = {k: "" for k in FIELDS} | {
                "id": rid, "name": p["name"], "kraj": p.get("kraj", ""), "okres": p.get("okres", ""),
                "obec": p.get("obec", ""), "category": p.get("label") or p["category"],
                "products": (p.get("products") or "")[:160]}
        if upd.get("status", "") not in STATUSES:
            sys.exit(f"bad status {upd['status']} for {rid}")
        rows[rid].update({k: str(v) for k, v in upd.items() if k in FIELDS})
        rows[rid]["checked"] = date.today().isoformat()
        n += 1
    save(rows)
    print(f"updated {n}")


def stats():
    rows = load()
    by = {}
    for r in rows.values():
        by.setdefault(r["status"] or "not checked yet", []).append(r)
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"{k}: {len(v)}")


if __name__ == "__main__":
    {"init": init, "set": set_rows, "stats": stats}[sys.argv[1]]()
