"""Pick the house a certificate address means, from the candidates scripts/osm_addresses.py took from OSM."""
import math
import re
import unicodedata

NUM = re.compile(r"^(?P<st>.*?)(?:[\s,]+|^)(?:(?:č|c|čd)\.?\s*(?:d\.\s*)?)?(?P<a>\d+[a-zA-Z]?)(?:\s*/\s*(?P<b>\d*[a-zA-Z]?\d*))?\s*$", re.I)
ABBR = [(r"\bul\b|\bulica\b", ""), (r"\bnam\b", "namestie"), (r"\bsidl\b", "sidlisko"), (r"\bsv\b", "svateho"), (r"\bgen\b", "generala")]


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def street(s):
    s = fold(s)
    for a, b in ABBR:
        s = re.sub(a, b, s)
    return " ".join(s.split())


def parse(address):
    """'Švermova 279/14' -> ('svermova', '279', '14'); 'Proč 101' -> ('proc', '101', '')."""
    m = NUM.match((address or "").strip())
    return (street(m["st"]), m["a"].lower(), (m["b"] or "").lower()) if m else (street(address), "", "")


def dist(a, b):
    return math.hypot((a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 110574)


def town(s):
    return " ".join(re.sub(r"\bmestska cast\b", " ", fold(s)).split())


def same_town(o, t):
    return bool(o and t) and (o == t or o.startswith(t + " ") or t.startswith(o + " "))


class AddressPoints:
    def __init__(self, data, admin):
        self.want, self.admin, self._obec = data.get("want", {}), admin, {}
        self.places, self.settlements = data.get("places", []), set(data.get("settlements", []))

    def area(self, h):
        k = (h[0], h[1])
        if k not in self._obec:
            a = self.admin.lookup(h[1], h[0])
            self._obec[k] = (fold(a["obec"] or ""), a["kraj"])
        return self._obec[k]

    def obec(self, h):
        return self.area(h)[0]

    def points(self, name, kraj):
        """OSM's points for a village, town or hamlet of that name in the region."""
        return [(p[1], p[2]) for p in self.places if p[0] == name and p[3] != "locality" and self.area((p[1], p[2]))[1] == kraj]

    def village(self, address, city, kraj):
        """Centre of the settlement the address names, else of the town: for addresses whose house is not mapped."""
        s, t = parse(address)[0], town(city)
        centre = self.points(t, kraj)
        if len(centre) > 1:
            return None
        if s and s != t and s in self.settlements:
            part = [q for q in self.points(s, kraj) if centre and dist(q, centre[0]) < 8000]
            if len(part) == 1:
                return part[0]
        return centre[0] if centre else None

    def find(self, pid, address, city, kraj, at, precision):
        """(lat, lon, how) of the house, or None. how: street | settlement | number"""
        w = self.want.get(pid)
        if not w or w["address"] != address:
            return None
        s, a, b = parse(address)
        if not a:
            return None
        t = town(city)

        def number_ok(h):
            cn, sn, hn = h[3:6]
            if b:
                return hn == f"{a}/{b}" or (cn == a and sn in ("", b)) or (sn == b and not cn)
            return a in (cn, sn, hn)
        centre = self.points(t, kraj)
        # same region, and not a same-named village far from the town on the certificate
        hits = [h for h in w["c"] if number_ok(h) and self.area(h)[1] == kraj
                and (not centre or min(dist(h, c) for c in centre) < 12_000)]
        # a settlement named in the address ("Malé Leváre 229", "Rakovo - Lehotka 119") decides the village
        named = [x for x in ([s] if s in self.settlements else s.split()) if x in self.settlements and x != t] if s else []
        levels = []
        if s and s != t:
            levels.append(("street", [h for h in hits if street(h[2]) and (street(h[2]) == s or street(h[2]).endswith(" " + s) or s.endswith(" " + street(h[2])))
                                      and (same_town(self.obec(h), t) or fold(h[6]) == t)]))
        if not s or s == t or s in self.settlements:
            place = s if s and s != t else t
            levels.append(("settlement", [h for h in hits if (self.obec(h) == place or fold(h[6]) == place or (place == t and same_town(self.obec(h), t)))
                                          and (h[3] == a or (h[5] == a and not h[2]))]))
            if s in self.settlements and s != t:  # a part of the town with the town's own house numbers ("Húšky 602")
                part = [q for q in self.points(s, kraj) if not centre or dist(q, centre[0]) < 12_000]
                p0 = part[0] if len(part) == 1 else None
                levels.append(("settlement", [h for h in hits if same_town(self.obec(h), t) and not h[2] and a in (h[3], h[5])
                                              and p0 and dist(h, p0) < 4000]))
        elif not named and a.isdigit() and (int(a) >= 100 or b):
            # house numbers are unique in a municipality and many address points carry no street name; only believe the
            # number alone when the house stands by the street (or in the locality) the certificate names
            spots = [(p[1], p[2]) for p in self.places if p[0] == s]
            levels.append(("number", [h for h in hits if same_town(self.obec(h), t) and not h[2] and a in (h[3], h[5])
                                      and ((len(h) > 7 and h[7] is not None and h[7] <= 200) or any(dist(h, q) < 1500 for q in spots))]))
        for how, hs in levels:
            if not hs:
                continue
            hs = sorted(hs, key=lambda h: dist(h, at))
            exact = [h for h in hs if self.obec(h) == t] or hs
            if max(dist(x, y) for x in exact for y in exact) <= 150:
                return exact[0][0], exact[0][1], how
            if precision == "street" and dist(hs[0], at) <= 100:
                return hs[0][0], hs[0][1], how
            return None
        return None
