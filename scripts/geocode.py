"""Geocode Slovak addresses: Nominatim for street addresses, GeoNames offline for villages and postcodes.

Precision levels returned:
  street   - house or street found by Nominatim
  village  - centre of the municipality (offline GeoNames, or Nominatim)
  postcode - centre of the postcode area (offline GeoNames)

Nominatim usage policy: one request per second, results cached in data/raw/geocode_cache_v2.json.
GeoNames data (CC BY 4.0): data/raw/geonames/{places,postal}/SK.txt
"""
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data/raw/geocode_cache_v2.json"
UA = {"User-Agent": "open-local-food-map/0.1 (non-commercial open-data project)"}
_last = [0.0]


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


class Gazetteer:
    def __init__(self):
        self.obce = {}  # folded name -> [(lat, lon, admin1, admin2, name)]
        for line in open(ROOT / "data/raw/geonames/places/SK.txt", encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if f[7] not in ("ADM3", "PPLA", "PPLA2", "PPLC"):
                continue
            for n in {fold(f[1]), fold(f[2])}:
                self.obce.setdefault(n, []).append((float(f[4]), float(f[5]), f[10], f[11], f[1]))
        self.postal = {}  # "97401" -> [(place, okres, lat, lon)]
        for line in open(ROOT / "data/raw/geonames/postal/SK.txt", encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if len(f) < 11 or not f[9]:
                continue
            self.postal.setdefault(f[1].replace(" ", ""), []).append((f[2], f[5], float(f[9]), float(f[10])))

    def village(self, name, pc=""):
        """Coordinates of a municipality by name, using the postcode to pick between same-named villages."""
        key = fold(name)
        if not key:
            return None
        rows = [r for r in self.postal.get(pc, []) if fold(r[0]) == key]
        if rows:
            return rows[0][2], rows[0][3]
        cands = self.obce.get(key, [])
        if len(cands) == 1:
            return cands[0][0], cands[0][1]
        if cands and pc in self.postal:  # several villages share the name: take the one nearest the postcode area
            plat = sum(r[2] for r in self.postal[pc]) / len(self.postal[pc])
            plon = sum(r[3] for r in self.postal[pc]) / len(self.postal[pc])
            best = min(cands, key=lambda c: (c[0] - plat) ** 2 + (c[1] - plon) ** 2)
            return best[0], best[1]
        return None

    def postcode(self, pc):
        rows = self.postal.get(pc, [])
        if not rows:
            return None
        return sum(r[2] for r in rows) / len(rows), sum(r[3] for r in rows) / len(rows)

    def is_village(self, name):
        return fold(name) in self.obce


class Geocoder:
    def __init__(self, admin=None):
        self.cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
        self.gaz = Gazetteer()
        self.admin = admin
        self.requests = 0

    def save(self):
        CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False))

    def nominatim(self, params):
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        if key in self.cache:
            return self.cache[key]
        wait = 1.1 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        q = urllib.parse.urlencode({**params, "countrycodes": "sk", "format": "jsonv2", "limit": 1,
                                    "addressdetails": 1, "accept-language": "sk"})
        res = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        f"https://nominatim.openstreetmap.org/search?{q}", headers=UA), timeout=40) as r:
                    data = json.load(r)
                if data:
                    d = data[0]
                    a = d.get("address", {})
                    res = {"lat": float(d["lat"]), "lon": float(d["lon"]), "class": d.get("category") or d.get("class"),
                           "type": d.get("type"), "addresstype": d.get("addresstype"),
                           "house": bool(a.get("house_number")), "road": a.get("road", ""),
                           "place": a.get("village") or a.get("town") or a.get("city") or a.get("municipality", "")}
                break
            except Exception as e:  # noqa: BLE001
                print("nominatim retry", params, e, flush=True)
                time.sleep(5 * (attempt + 1))
        _last[0] = time.time()
        self.requests += 1
        self.cache[key] = res
        if self.requests % 20 == 0:
            self.save()
        return res

    def _ok(self, lat, lon, kraj):
        if not self.admin:
            return True
        hit = self.admin.lookup(lon, lat)
        return hit["in_sk"] and (not kraj or hit["kraj"] == kraj)

    def locate(self, street, postal, city, kraj=""):
        """Return (lat, lon, precision) or (None, None, None). kraj (e.g. 'Prešovský') rejects wrong-region hits."""
        street = " ".join((street or "").replace(" ", " ").split()).strip(" ,-")
        pc = re.sub(r"\D", "", postal or "")[:5]
        district = (city or "").startswith("District of ")
        city = re.sub(r"^District of ", "", city or "").strip()
        city = re.sub(r"\s*-\s*mestská časť\s*", "-", city)  # "Košice - mestská časť Staré Mesto" -> "Košice-Staré Mesto"
        # villages without street names: "Hostovice 177" -> village "Hostovice"
        m = re.match(r"^(?P<v>[^\d,]+?)\s*(č\.\s*)?\d+[\w/.-]*$", street)
        village = m.group("v").strip(" ,-") if m and self.gaz.is_village(m.group("v")) else ""
        if not village and not district and self.gaz.is_village(city):
            village = city
        town = village or city
        attempts = []
        if street and re.search(r"\d", street):
            attempts.append(("street", {"q": f"{street}, {pc[:3]} {pc[3:]} {town}".strip()}))
            if district or (village and village != city):
                attempts.append(("street", {"q": f"{street}, {pc[:3]} {pc[3:]}".strip()}))
        # "Hostovice 177" has no street name: only a house match counts, a road match would be a guess
        has_street = bool(street) and not (village and fold(street).startswith(fold(village)))
        for precision, params in attempts:
            r = self.nominatim(params)
            if not r or not self._ok(r["lat"], r["lon"], kraj):
                continue
            road_ok = (r["class"] == "highway" and has_street
                       and r["type"] not in ("motorway", "trunk", "motorway_link", "trunk_link", "primary"))
            if r["house"] or (r["class"] in ("building", "place") and r["type"] in ("house", "building")) or road_ok:
                return r["lat"], r["lon"], "street"
            if r["addresstype"] in ("village", "town", "city", "municipality", "hamlet", "suburb", "neighbourhood"):
                break  # Nominatim fell back to the municipality: the offline centroid is as good
        for name in [village, city]:
            pt = self.gaz.village(name, pc) if name else None
            if pt and self._ok(pt[0], pt[1], kraj):
                return pt[0], pt[1], "village"
        pt = self.gaz.postcode(pc)
        if pt and self._ok(pt[0], pt[1], kraj):
            return pt[0], pt[1], "postcode"
        if town:
            r = self.nominatim({"city": town, "postalcode": f"{pc[:3]} {pc[3:]}"} if pc else {"city": town})
            if r and self._ok(r["lat"], r["lon"], kraj):
                return r["lat"], r["lon"], "village"
        return None, None, None
