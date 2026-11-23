"""Download all valid Slovak organic operator certificates from the EU TRACES public directory.

Source: European Commission, TRACES NT public directory of organic operator certificates.
Output: data/raw/traces_sk_organic.json (raw) and data/out/organic_operators.csv
"""
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/for/query"
HDR = {"User-Agent": "open-local-food-research/0.1", "Accept": "application/json"}
PAGE = 100


def fetch(offset):
    q = urllib.parse.urlencode({"max": PAGE, "offset": offset, "query": "SK-BIO", "sort": "-issuedOn",
                                "states": "ISSUED"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{URL}?{q}", headers=HDR), timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print("retry", offset, e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed at offset {offset}")


def main():
    items, offset = [], 0
    while True:
        page = fetch(offset)
        items += page
        print(f"offset {offset}: +{len(page)} (total {len(items)})", flush=True)
        if len(page) < PAGE:
            break
        offset += PAGE
        time.sleep(1)
    (ROOT / "data/raw/traces_sk_organic.json").write_text(json.dumps(items, ensure_ascii=False))

    out = ROOT / "data/out/organic_operators.csv"
    seen = {}
    for c in items:
        op = c.get("operator") or {}
        a = op.get("address") or {}
        city = a.get("cityReference") or {}
        if (city.get("country") or {}).get("code") != "SK":
            continue
        key = c.get("operatorIdentifier") or c["reference"]
        regions = [r["name"] for r in city.get("hierarchicalRegions") or [] if r.get("code")]
        row = {
            "operator_id": key, "name": op.get("name", ""),
            "street": ((a.get("street") or {}).get("value") or "").rstrip(", "),
            "postal": city.get("postalCode", ""), "city": city.get("name", ""),
            "region": regions[0] if regions else "",
            "activities": "; ".join(x["translation"] for x in c.get("activities") or []),
            "product_categories": "; ".join(
                (x.get("translation") or x.get("id") or "") for x in c.get("categoriesOfProduct") or []),
            "control_body": (c.get("issuingBody") or {}).get("code", ""),
            "certificate": c["reference"], "issued": (c.get("issuedOn") or "")[:10],
            "expires": (c.get("expiresOn") or "")[:10],
            "certificate_url": "https://webgate.ec.europa.eu/tracesnt/directory/publication/" + c.get("relativeUrl", ""),
        }
        # keep the newest certificate per operator (list is sorted newest first)
        seen.setdefault(key, row)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(seen.values())).keys()))
        w.writeheader()
        w.writerows(seen.values())
    print(f"{len(items)} certificates -> {len(seen)} operators -> {out}")


if __name__ == "__main__":
    main()
