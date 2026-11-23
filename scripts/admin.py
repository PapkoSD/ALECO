"""Offline point -> kraj / okres / obec lookup using OSM boundary polygons (from osm_extract.py).

    from admin import Admin
    a = Admin()
    a.lookup(17.267, 48.289)  # {'kraj': 'Bratislavský', 'okres': 'Pezinok', 'obec': 'Pezinok', ...}
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CELL = 0.1  # grid cell size in degrees for the bbox index

CITY_OKRES = re.compile(r"^(Bratislava|Košice) [IV]+$")  # the city districts, not "Košice-okolie"
KRAJ_SLUG = {"Bratislavský": "ba", "Trnavský": "tt", "Trenčiansky": "tn", "Nitriansky": "nr", "Žilinský": "za",
             "Banskobystrický": "bb", "Prešovský": "po", "Košický": "ke"}


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _inside(x, y, ring):
    c = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


class Admin:
    def __init__(self, path=ROOT / "data/raw/osm/admin_sk.json"):
        areas = json.loads(Path(path).read_text())
        self.levels = {}
        for a in areas:
            self.levels.setdefault(a["level"], []).append(a)
        self.index = {}
        for lvl, items in self.levels.items():
            grid = {}
            for i, a in enumerate(items):
                x0, y0, x1, y1 = a["bbox"]
                for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
                    for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
                        grid.setdefault((gx, gy), []).append(i)
            self.index[lvl] = grid
        # admin levels in Slovak OSM: 4 kraj, 6 okres, 8 obec, 9 mestská časť (only Bratislava and Košice)
        self.cache = {}

    def area_at(self, lvl, x, y):
        items = self.levels.get(lvl, [])
        for i in self.index.get(lvl, {}).get((int(x // CELL), int(y // CELL)), []):
            a = items[i]
            x0, y0, x1, y1 = a["bbox"]
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            if sum(_inside(x, y, r) for r in a["rings"]) % 2 == 1:
                return a
        return None

    @staticmethod
    def contains(area, x, y):
        x0, y0, x1, y1 = area["bbox"]
        return x0 <= x <= x1 and y0 <= y <= y1 and sum(_inside(x, y, r) for r in area["rings"]) % 2 == 1

    def lookup(self, x, y):
        key = (round(x, 5), round(y, 5))
        if key in self.cache:
            return self.cache[key]
        kraj = self.area_at("4", x, y)
        okres = self.area_at("6", x, y)
        obec = self.area_at("8", x, y) or self.area_at("9", x, y)
        kraj_name = (kraj or {}).get("name", "").replace(" kraj", "").strip()
        okres_name = (okres or {}).get("name", "").replace("okres ", "").strip()
        obec_name = (obec or {}).get("name", "")
        display = obec_name
        city = CITY_OKRES.match(okres_name)
        if city and obec_name and not obec_name.startswith(city.group(1)):  # "Bratislava-Petržalka"
            display = f"{city.group(1)}-{obec_name}"
        res = {"kraj": kraj_name, "kraj_id": KRAJ_SLUG.get(kraj_name, ""), "okres": okres_name,
               "obec": display, "in_sk": kraj is not None,
               "town": bool(city) or (bool(obec_name) and obec_name == okres_name)}  # okres seat or city borough
        self.cache[key] = res
        return res
