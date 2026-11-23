"""Call list for the hand-check that the web could not settle (private: data/out/call_list.csv).

Every certified producer still on the map that is not verified yet, with what we know, a phone number when one was
found, and what to ask. Ordered by region (Bratislava first, the launch area) and by how likely they are to sell
directly: processed food and fruit first, raw-milk and field-crop farms last.

After a call, record the answer with scripts/checks.py set (status sells / wholesale / closed / unclear, how, phone).
Run: python3 scripts/call_list.py
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KRAJ_ORDER = ["Bratislavský", "Trnavský", "Trenčiansky", "Nitriansky", "Žilinský", "Banskobystrický", "Prešovský",
              "Košický"]
ASK = ("Predávate priamo ľuďom (na farme, cez e-shop, na trhoch, rozvoz)? Kde a kedy? "
       "Môžeme vás s týmito údajmi uviesť na mape ALECO?")


def priority(p):
    label = (p.get("label") or "") + " " + p["category"]
    prods = (p.get("products") or "").lower()
    if p["category"] in ("producer", "bakery", "honey", "salas", "winery") or re.search(r"syr|mäso|údenin", label, re.I):
        return 1
    if re.search(r"jabl|hruš|sliv|arón|ríbez|čučor|jahod|orech|zelenin|cesnak|zemiak|byl|vajc|med\b", prods):
        return 1
    if "Mliečna farma" in label or re.search(r"surové|šošovic|tekvic|hrach|cícer", prods):
        return 3
    return 2


def main():
    checks = {r["id"]: r for r in csv.DictReader(open(ROOT / "data/checks/places_checks.csv", encoding="utf-8"))}
    feats = json.loads((ROOT / "site/data/places.geojson").read_text())["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        if not p.get("bio") or p.get("checked"):
            continue
        c = checks.get(p["id"], {})
        lon, lat = f["geometry"]["coordinates"]
        rows.append({
            "priority": priority(p), "kraj": p.get("kraj", ""), "okres": p.get("okres", ""), "obec": p.get("obec", ""),
            "name": p["name"], "type": p.get("label") or p["category"], "products": (p.get("products") or "")[:150],
            "phone": p.get("phone", ""), "website": p.get("website", ""), "status": c.get("status", "") or "not checked",
            "note": c.get("note", ""), "ask": ASK, "id": p["id"],
            "map": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}",
        })
    rows.sort(key=lambda r: (KRAJ_ORDER.index(r["kraj"]) if r["kraj"] in KRAJ_ORDER else 9, r["priority"], r["name"]))
    out = ROOT / "data/out/call_list.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by.setdefault((r["kraj"], r["priority"]), 0)
        by[(r["kraj"], r["priority"])] += 1
    print(f"{len(rows)} producers to call -> {out}")
    print(f"with a phone number already: {sum(1 for r in rows if r['phone'])}")
    for k in KRAJ_ORDER:
        print(f"  {k}: " + ", ".join(f"priority {p}: {by.get((k, p), 0)}" for p in (1, 2, 3)))


if __name__ == "__main__":
    main()
