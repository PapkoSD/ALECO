"""Extract local-food places and administrative boundaries from the Geofabrik Slovakia extract.

Why not Overpass: the public Overpass servers are often overloaded; a local extract is reproducible and fast.

Input : data/raw/osm/slovakia-latest.osm.pbf  (https://download.geofabrik.de/europe/slovakia.html, ODbL)
Output: data/raw/osm_sk.json        places, same shape as Overpass "out tags center" (type, id, tags, lat/lon|center)
        data/raw/osm/admin_sk.json  simplified polygons of kraje, okresy, obce for offline point lookups
Run   : uv run --no-project --with osmium python scripts/osm_extract.py
"""
import collections
import json
import re
import sys
import time
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
PBF = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/raw/osm/slovakia-latest.osm.pbf"

SHOPS = {"bakery", "farm", "organic", "health_food", "greengrocer", "butcher", "cheese", "dairy", "deli", "honey",
         "wine"}
CRAFTS = {"winery", "beekeeper", "cheese", "cheesemaker", "cheese_maker", "bakery", "oil_mill", "mill", "cider",
          "distillery"}
VENDING = re.compile(r"milk|egg|cheese|dairy|meat|potato|honey|bread|fruit|vegetable")
SALAS = re.compile(r"^sala[šs]", re.I)
FARMNAME = re.compile(r"farma|ranč", re.I)
ADMIN_LEVELS = {"4", "6", "8", "9", "10"}


def wanted(t):
    if t.get("shop") in SHOPS or t.get("organic") in ("yes", "only"):
        return True
    if VENDING.search(t.get("vending", "")) or t.get("amenity") == "marketplace":
        return True
    if t.get("craft") in CRAFTS or "produce" in t:
        return True
    if t.get("place") == "farm" and "name" in t:
        return True
    name = t.get("name", "")
    if name and ("amenity" in t or "tourism" in t or "shop" in t):
        if SALAS.search(name) or FARMNAME.search(name):
            return True
    return False


def edited(o):
    """Last edit date and version, to spot places nobody has looked at for years."""
    try:
        return {"timestamp": o.timestamp.strftime("%Y-%m-%d"), "version": o.version}
    except Exception:  # noqa: BLE001  (extract without metadata)
        return {}


def simplify(ring, tol=0.00018):
    """Radial-distance thinning (~15-20 m): keeps admin lookups exact enough and the file small."""
    out = [ring[0]]
    for p in ring[1:-1]:
        q = out[-1]
        if abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol:
            out.append(p)
    out.append(ring[-1])
    return out if len(out) >= 4 else ring


def main():
    t0 = time.time()
    places, admin = [], []
    levels = collections.Counter()
    fp = (osmium.FileProcessor(str(PBF))
          .with_locations()
          .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
          .with_filter(osmium.filter.EmptyTagFilter()))
    n = 0
    for o in fp:
        n += 1
        if n % 2_000_000 == 0:
            print(f"{n:,} objects, {len(places)} places, {len(admin)} admin areas, {time.time() - t0:.0f}s",
                  flush=True)
        if o.is_area():
            t = dict(o.tags)
            lvl = t.get("admin_level")
            if t.get("boundary") != "administrative" or lvl not in ADMIN_LEVELS:
                continue
            levels[lvl] += 1
            rings = []
            for outer in o.outer_rings():
                rings.append(simplify([(round(nd.lon, 6), round(nd.lat, 6)) for nd in outer]))
                for inner in o.inner_rings(outer):
                    rings.append(simplify([(round(nd.lon, 6), round(nd.lat, 6)) for nd in inner]))
            if not rings:
                continue
            xs = [p[0] for r in rings for p in r]
            ys = [p[1] for r in rings for p in r]
            admin.append({"osm": f"{'w' if o.from_way() else 'r'}{o.orig_id()}", "level": lvl,
                          "name": t.get("name", ""), "ref": t.get("ref", ""),
                          "lau": t.get("ref:lau", "") or t.get("lau", ""),
                          "population": t.get("population", ""),
                          "bbox": [min(xs), min(ys), max(xs), max(ys)], "rings": rings})
            continue
        if o.is_relation():
            continue
        t = dict(o.tags)
        if not wanted(t):
            continue
        if o.is_node():
            if not o.location.valid():
                continue
            places.append({"type": "node", "id": o.id, "lat": round(o.location.lat, 7),
                           "lon": round(o.location.lon, 7), "tags": t, **edited(o)})
        elif o.is_way():
            pts = [(nd.lon, nd.lat) for nd in o.nodes if nd.location.valid()]
            if not pts:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            places.append({"type": "way", "id": o.id, "tags": t, **edited(o),
                           "center": {"lat": round((min(ys) + max(ys)) / 2, 7),
                                      "lon": round((min(xs) + max(xs)) / 2, 7)}})

    ts = fp.header.get("osmosis_replication_timestamp") if hasattr(fp, "header") else ""
    (ROOT / "data/raw/osm_sk.json").write_text(json.dumps(
        {"source": "Geofabrik slovakia-latest.osm.pbf", "osm_base": ts, "elements": places}, ensure_ascii=False))
    (ROOT / "data/raw/osm/admin_sk.json").write_text(json.dumps(admin, ensure_ascii=False, separators=(",", ":")))
    print(f"done in {time.time() - t0:.0f}s: {len(places)} places, admin areas by level {dict(levels)}", flush=True)


if __name__ == "__main__":
    main()
