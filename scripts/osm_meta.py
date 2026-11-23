"""When a person (not a bot) last touched each OpenStreetMap place, and whether anyone reported it closed.

The Geofabrik extract only has each element's latest timestamp. Bots and mass edits bump that date without anyone
looking at the shop: in May 2026 a bot changed http:// websites to https://, so Farma Tuška (surveyed in 2015, closed
since) looked freshly edited and its card showed no "old data" warning. This asks the OSM API, one request per second,
and caches everything in data/raw/osm_meta.json (re-runs only fetch what is missing):

  1. the current version of every OSM place on the map (bulk, 200 ids per request). Deleted since the extract,
     or retagged (e.g. shop=farm -> disused:shop=farm), means the place is gone.
  2. the changesets of those versions (bulk, 100 per request). A changeset is mechanical when it is tagged bot=yes,
     comes from a bot account, or touches more than 1000 objects.
  3. the history of every element whose latest edit is mechanical, to find the last edit made by a person.
  4. open OSM notes in Slovakia; those within 60 m of a place that say it closed or moved are kept.

  python3 scripts/osm_meta.py            fetch what is missing, then print a summary
  python3 scripts/osm_meta.py --notes    also re-fetch the open notes
"""
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/raw/osm_meta.json"
API = "https://api.openstreetmap.org/api/0.6"
UA = {"User-Agent": "open-local-food-map/0.1 (non-commercial open-data project)"}
BOT_USER = re.compile(r"(?:^|[^a-z])bot(?:$|[^a-z])|bot$", re.I)
CLOSED = re.compile(r"zatvor|zrusen|neexist|nefung|zanik|zavren|uzavret|nie je tu|uz tu nie|uz neni|prestahov|"
                    r"presunul|presunut|closed|permanent|no longer|not exist|doesn ?t exist|moved|vacant|out of business|"
                    r"geschlossen|bezart|megszunt", re.I)
SK_BBOX = "16.83,47.73,22.57,49.62"
_last = [0.0]


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def get(path):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{path}", headers=UA), timeout=90) as r:
        return json.load(r)


def fetch_current(kind, ids, out):
    """Bulk-fetch current versions; a 404/410 for one id fails the whole request, so split until it is found."""
    try:
        data = get(f"{kind}s.json?{kind}s={','.join(map(str, ids))}")
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            raise
        if len(ids) == 1:
            out[f"{kind[0]}{ids[0]}"] = {"deleted": True}
            return
        mid = len(ids) // 2
        fetch_current(kind, ids[:mid], out)
        fetch_current(kind, ids[mid:], out)
        return
    for e in data["elements"]:
        out[f"{e['type'][0]}{e['id']}"] = {"v": e["version"], "ts": e["timestamp"], "cs": e["changeset"],
                                           "deleted": e.get("visible") is False, "tags": e.get("tags", {})}


def fetch_changesets(ids, cache):
    todo = sorted({int(i) for i in ids if str(i) not in cache})
    for k in range(0, len(todo), 100):
        batch = todo[k:k + 100]
        for c in get(f"changesets.json?changesets={','.join(map(str, batch))}&limit=100")["changesets"]:
            t = c.get("tags", {})
            cache[str(c["id"])] = {
                "mech": bool(t.get("bot") == "yes" or BOT_USER.search(c.get("user", ""))
                             or c.get("changes_count", 0) > 1000
                             or re.search(r"mechanical|automated edit", t.get("comment", ""), re.I)),
                "n": c.get("changes_count", 0), "editor": t.get("created_by", "")[:40]}
        for i in batch:  # changesets the API did not return (should not happen): treat as human
            cache.setdefault(str(i), {"mech": False, "n": 0, "editor": ""})


def metres(a, b):
    dx = (a[0] - b[0]) * 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot(dx, (a[1] - b[1]) * 110_574)


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cur, cs, hist = (cache.setdefault(k, {}) for k in ("current", "changesets", "history"))

    def save():
        CACHE.write_text(json.dumps(cache, ensure_ascii=False))

    places = [f for f in json.loads((ROOT / "site/data/places.geojson").read_text())["features"]
              if f["properties"]["source"] == "osm"]
    ids = [f["properties"]["id"][4:] for f in places]  # "n3415130907"
    for kind in ("node", "way", "relation"):
        todo = [int(i[1:]) for i in ids if i[0] == kind[0] and i not in cur]
        for k in range(0, len(todo), 200):
            fetch_current(kind, todo[k:k + 200], cur)
            save()
    print(f"current versions: {len(cur)}", flush=True)
    fetch_changesets([c["cs"] for c in cur.values() if "cs" in c], cs)
    save()
    mech = [i for i in ids if cur.get(i, {}).get("cs") and cs[str(cur[i]["cs"])]["mech"]]
    print(f"latest edit mechanical: {len(mech)}; fetching their history", flush=True)
    for n, i in enumerate(x for x in mech if x not in hist):
        kind = {"n": "node", "w": "way", "r": "relation"}[i[0]]
        hist[i] = [{"v": e["version"], "ts": e["timestamp"], "cs": e["changeset"]}
                   for e in get(f"{kind}/{i[1:]}/history.json")["elements"]]
        if n % 25 == 0:
            save()
    fetch_changesets([v["cs"] for i in mech for v in hist[i]], cs)
    for i in ids:
        c = cur.get(i)
        if not c or c.get("deleted"):
            continue
        if i in hist:
            versions = sorted(hist[i], key=lambda v: -v["v"])
            c["human"] = next((v["ts"] for v in versions if not cs[str(v["cs"])]["mech"]), versions[-1]["ts"])
        else:
            c["human"] = c["ts"]
    save()

    if "--notes" in sys.argv or "notes" not in cache:
        data = get(f"notes.json?bbox={SK_BBOX}&limit=10000&closed=0")
        cache["notes_all"] = len(data["features"])
        notes = {}
        for nf in data["features"]:
            text = " / ".join(c.get("text", "") for c in nf["properties"].get("comments", []))
            if not CLOSED.search(fold(text)):
                continue
            pt = nf["geometry"]["coordinates"]
            for f in places:
                if metres(pt, f["geometry"]["coordinates"]) <= 60:
                    notes.setdefault(f["properties"]["id"][4:], []).append(
                        {"id": nf["properties"]["id"], "date": nf["properties"]["date_created"][:10], "text": text[:300]})
        cache["notes"] = notes
        save()

    # summary
    gone = [i for i in ids if cur.get(i, {}).get("deleted")]
    print(f"deleted in OSM since the extract: {len(gone)} {gone[:20]}")
    years = Counter((cur[i].get("human") or "")[:4] for i in ids if i in cur and not cur[i].get("deleted"))
    print("last edit by a person, by year:", sorted(years.items()))
    moved = Counter((cur[i]["ts"][:4], cur[i]["human"][:4]) for i in mech if cur[i].get("human"))
    print("mechanical latest edits, (latest year, person year):", sorted(moved.items()))
    print(f"open notes in the bbox: {cache.get('notes_all')}; places with a 'closed/moved' note nearby: "
          f"{len(cache['notes'])}")


if __name__ == "__main__":
    main()
