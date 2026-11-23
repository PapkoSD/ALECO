"""Find the websites of certified producers and look for signs that they sell to people directly.

For every BIO place in data/checks/places_checks.csv that has no website and no check yet, try the obvious
domains (fermentina.sk, janove-sady.sk, ...), keep a site only if it is clearly the same company (its name,
village or IČO is on the page), and scan it for: e-shop, farm shop, opening hours, markets, delivery,
wholesale-only wording, and a phone number.

Output: data/checks/web_discovery.csv, to review by hand before anything goes into places_checks.csv.
Run: python3 scripts/find_websites.py      (8 parallel lookups, one or two GETs per candidate domain)
"""
import concurrent.futures as cf
import csv
import json
import re
import socket
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_websites import fetch  # noqa: E402
from geocode import Gazetteer  # noqa: E402

VILLAGES = {k.replace(" ", "") for k in Gazetteer().obce}  # "kuty.sk" is the village's site, not the cooperative's

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/checks/web_discovery.csv"
socket.setdefaulttimeout(15)

LEGAL = {"s", "r", "o", "sro", "spol", "as", "a", "k", "v", "druzstvo", "pd", "shr", "ing", "mgr", "bc", "rndr",
         "spolocnost", "ruceni", "rucenim", "obmedzenym", "prevadzka", "c", "sk", "slovakia", "slovensko", "group",
         "trade", "trading", "company", "plus", "the", "and", "na", "pod", "u", "zo", "od", "pri", "pre", "z", "ltd",
         "gmbh", "kft", "vos", "ks", "nadacia", "zdruzenie"}
GENERIC = {"agro", "farma", "farm", "bio", "eko", "eco", "organic", "polnohospodarske", "rolnicke", "podielnicke",
           "vlastnikov", "druzstvo", "agrofarma", "agrodruzstvo", "vinarstvo", "rodinna", "rodinne", "sady", "sad",
           "food", "foods", "real", "invest", "service", "services", "slovak", "products", "produkt", "mlyn",
           "hospodarstvo", "skolske", "ekologicke", "zahrada", "zahradnictvo", "rodinny", "dvor", "statok"}
SIGNALS = {
    "e-shop": r"e-?shop|do kosika|pridat do kosika|nakupny kosik|\bkosik\b|objednat online|objednavkovy formular",
    "predajňa": r"predajn|predaj z dvora|predaj na farme|predaj priamo|priamy predaj|farmarsky obchod|"
                r"otvaracie hodiny|predajne hodiny|kupite u nas",
    "trhy": r"farmarsk\w* trh|na trhoch|trhovisk|trznic",
    "rozvoz": r"rozvoz|dovoz (domov|az)|dorucenie|dorucujeme|bedniciek|bednick|debnick",
    "degustácie": r"degustac|vinoteka|vinna pivnica|ochutnavk",
    "automat": r"mliecny automat|mliekomat|automat na mlieko|automat na vajcia",
    "samozber": r"samozber",
    "veľkoobchod": r"velkoobchod|\bb2b\b|pre obchodnych partnerov|odberatelia|vykup\b|pre spracovatelov",
}
PHONE = re.compile(r"(?:\+|00)421[\s/.-]?\d{2,3}[\s/.-]?\d{3}[\s/.-]?\d{3,4}|\b0\d{2,3}[\s/.-]?\d{3}[\s/.-]?\d{3,4}\b")


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def words(name):
    return [w for w in re.split(r"[^a-z0-9]+", fold(name)) if w and w not in LEGAL]


def candidates(name):
    ws = words(name)
    distinct = [w for w in ws if w not in GENERIC and len(w) >= 4 and not w.isdigit()]
    cands = []
    if 1 < len(ws) <= 4:
        cands += ["".join(ws), "-".join(ws)]
    if distinct:
        cands.append(distinct[0])
        if len(distinct) > 1:
            cands += ["".join(distinct[:2]), "-".join(distinct[:2])]
    if ws and ws[0] in ("farma", "vinarstvo", "biofarma", "ekofarma") and distinct:
        cands += [ws[0] + distinct[0], f"{ws[0]}-{distinct[0]}"]
    # cooperatives use initials: "Poľnohospodárske družstvo Kúty" -> pdkuty.sk, "Roľnícke družstvo" -> rd...
    initials = "".join(w[0] for w in re.split(r"[^a-z0-9]+", fold(name)) if w in GENERIC | {"druzstvo"})
    if distinct and 2 <= len(initials) <= 4:
        cands += [initials + distinct[0], f"{initials}-{distinct[0]}"]
    out = []
    for c in cands:
        if 4 <= len(c) <= 30 and c not in out and c.replace("-", "") not in VILLAGES:
            out.append(c)
    hosts = [f"{c}.sk" for c in out[:6]]
    # distinctive names are sometimes on .eu or .com (nutgrove.eu)
    hosts += [f"{c}.{tld}" for c in out[:3] if len(c) >= 6 for tld in ("eu", "com")]
    return hosts


def resolves(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def page_text(url):
    status, final, body = fetch(url)
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return final, " ".join((title.group(1) if title else "").split())[:120], " ".join(text.split())


def phones(text):
    out = []
    for m in PHONE.findall(text):
        digits = re.sub(r"\D", "", m)
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("421"):
            digits = "0" + digits[3:]
        if len(digits) == 10 and digits not in out:
            out.append(digits)
    return [f"+421 {d[1:4]} {d[4:7]} {d[7:]}" if d.startswith("09") else f"+421 {d[1:]}" for d in out[:2]]


def probe(row):
    name, obec = row["name"], row["obec"]
    distinct = [w for w in words(name) if w not in GENERIC and len(w) >= 4]
    for host in candidates(name):
        for h in (host, "www." + host):
            if not resolves(h):
                continue
            for scheme in ("https://", "http://"):
                try:
                    final, title, text = page_text(scheme + h)
                    break
                except Exception:  # noqa: BLE001
                    final = None
            if not final:
                continue
            ftext = fold(title + " " + text)
            ob = fold(obec.split("-")[-1]) if obec else ""
            name_hit = fold(" ".join(words(name))) in " ".join(re.split(r"[^a-z0-9]+", ftext))
            evidence = []
            if name_hit:
                evidence.append("name")
            if ob and len(ob) >= 4 and ob in ftext:
                evidence.append("village")
            if distinct and all(d in ftext for d in distinct[:2]):
                evidence.append("words")
            single_word = "-" not in host and host.rsplit(".", 1)[0] in distinct
            if not (name_hit or ("village" in evidence and "words" in evidence and not single_word)):
                continue
            # contact page often has the phone and the shop hours
            if not phones(text):
                for path in ("/kontakt", "/kontakty", "/contact"):
                    try:
                        _, _, t2 = page_text(final.rstrip("/") + path)
                        text += " " + t2
                        break
                    except Exception:  # noqa: BLE001
                        continue
            ftext = fold(title + " " + text)
            sig = [k for k, rx in SIGNALS.items() if re.search(rx, ftext)]
            return {"id": row["id"], "name": name, "obec": obec, "url": final, "title": title,
                    "evidence": "+".join(evidence), "signals": ", ".join(sig), "phones": " / ".join(phones(text))}
    return {"id": row["id"], "name": name, "obec": obec, "url": "", "title": "", "evidence": "", "signals": "",
            "phones": ""}


def main():
    rows = [r for r in csv.DictReader(open(ROOT / "data/checks/places_checks.csv", encoding="utf-8"))
            if not r["status"]]
    places = {f["properties"]["id"]: f["properties"]
              for f in json.loads((ROOT / "site/data/places.geojson").read_text())["features"]}
    todo = [r for r in rows if not places.get(r["id"], {}).get("website")]
    print(f"{len(rows)} unchecked, {len(todo)} without a website: probing", flush=True)
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(probe, todo))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    found = [r for r in results if r["url"]]
    print(f"found {len(found)} websites", flush=True)


if __name__ == "__main__":
    main()
