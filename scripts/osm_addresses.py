"""House numbers and village points from the OSM extract for the certified producers' addresses.

Certificates give an address, but Nominatim only finds about a third of the houses, so most pins used to sit in the
village centre. The extract has 1.6 million Slovak house numbers. This reads it once and keeps, for every certified
producer on the map, the houses with the same number within 15 km, plus all named villages, hamlets and town parts
(GeoNames has some in the wrong place: Vyšné Valice was 22 km off). scripts/address_points.py picks the right one.

Input : data/raw/osm/slovakia-latest.osm.pbf, site/data/places.geojson (run build_seed.py first)
Output: data/raw/osm_addresses.json
Run   : uv run --no-project --with osmium python scripts/osm_addresses.py      (about 80 s), then build_seed.py again
"""
import json
import math
import sys
import time
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from address_points import fold, parse, street  # noqa: E402

PBF = ROOT / "data/raw/osm/slovakia-latest.osm.pbf"
OUT = ROOT / "data/raw/osm_addresses.json"
PLACES = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter", "isolated_dwelling", "locality"}


def dist(a, b):
    return math.hypot((a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 110574)


def to_segment(p, a, b):
    k = math.cos(math.radians(p[0])) * 111320
    ax, ay, bx, by, px, py = a[1] * k, a[0] * 110574, b[1] * k, b[0] * 110574, p[1] * k, p[0] * 110574
    sq = (bx - ax) ** 2 + (by - ay) ** 2
    t = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / sq)) if sq else 0
    return math.hypot(px - ax - t * (bx - ax), py - ay - t * (by - ay))


def main():
    want, numbers = {}, {}
    for f in json.loads((ROOT / "site/data/places.geojson").read_text())["features"]:
        p = f["properties"]
        if p["source"] != "traces" or not p.get("address"):
            continue
        lon, lat = f["geometry"]["coordinates"]
        s, a, b = parse(p["address"])
        w = {"address": p["address"], "city": p.get("city", ""), "at": [lat, lon], "names": {fold(p.get("city", "")), s}, "num": [a, b], "c": []}
        want[p["id"]] = w
        for x in {a, b} - {""}:
            numbers.setdefault(x, []).append(p["id"])
    objs, places, roads, t0, n = [], [], {}, time.time(), 0
    streets = {parse(w["address"])[0] for w in want.values()} - {""}

    def keep(tags, lat, lon):
        hn = tags.get("addr:housenumber", "").lower().replace(" ", "")
        cn, sn = tags.get("addr:conscriptionnumber", "").lower(), tags.get("addr:streetnumber", "").lower()
        if "/" in hn:
            x, _, y = hn.partition("/")
            cn, sn = cn or x, sn or y
        ids = {i for k in (cn, sn, hn) if k for i in numbers.get(k, ())}
        if ids:
            objs.append((ids, [round(lat, 6), round(lon, 6), tags.get("addr:street", ""), cn, sn, hn,
                               tags.get("addr:city") or tags.get("addr:place") or ""]))

    for o in osmium.FileProcessor(str(PBF)).with_locations():
        t = o.tags
        if o.is_node() and t.get("place") in PLACES and "name" in t:
            places.append([fold(t["name"]), round(o.location.lat, 6), round(o.location.lon, 6), t["place"]])
        if o.is_way() and "highway" in t and "name" in t and street(t["name"]) in streets:
            pts = [(x.location.lat, x.location.lon) for x in o.nodes if x.location.valid()]
            roads.setdefault(street(t["name"]), []).extend(zip(pts, pts[1:]))
        if "addr:housenumber" in t or "addr:conscriptionnumber" in t or "addr:streetnumber" in t:
            n += 1
            if o.is_node():
                keep(t, o.location.lat, o.location.lon)
            elif o.is_way():
                pts = [(x.location.lat, x.location.lon) for x in o.nodes if x.location.valid()]
                if pts:
                    keep(t, sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts))
    # look around today's pin and around every place that bears the town's or the settlement's name
    for w in want.values():
        w["centres"] = [w["at"]] + [[la, lo] for nm, la, lo, _ in places if nm and nm in w["names"]]
    for ids, h in objs:
        for i in ids:
            if any(dist(h, c) < 15_000 for c in want[i]["centres"]) and h not in want[i]["c"]:
                want[i]["c"].append(h)
    # many address points carry no street name: note how far each is from the street the certificate names
    for w in want.values():
        segs = roads.get(parse(w["address"])[0], [])
        for h in w["c"]:
            near = [to_segment(h, a, b) for a, b in segs if abs(a[0] - h[0]) < 0.03 and abs(a[1] - h[1]) < 0.04]
            h.append(round(min(near)) if near else None)
    names = {x for w in want.values() for x in w["names"]}
    OUT.write_text(json.dumps({
        "want": {i: {"address": w["address"], "city": w["city"], "c": w["c"]} for i, w in want.items()},
        "places": [p for p in places if p[0] in names or any(p[0] in x.split() for x in names)],
        "settlements": sorted({p[0] for p in places if p[3] in ("city", "town", "village", "hamlet", "suburb")})},
        ensure_ascii=False))
    print(f"{n} house numbers read in {time.time() - t0:.0f} s; {sum(1 for w in want.values() if w['c'])} of {len(want)} "
          f"producers have candidates; {len(places)} named places")


if __name__ == "__main__":
    main()
