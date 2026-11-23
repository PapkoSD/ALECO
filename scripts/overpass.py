"""Small Overpass API client: tries several public mirrors, retries, and never hammers one server.

Usage as a script:  python3 scripts/overpass.py scripts/osm_query.overpassql data/raw/osm_sk.json
"""
import json
import sys
import time
import urllib.parse
import urllib.request

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HDR = {"User-Agent": "open-local-food-map/0.1 (non-commercial open-data project)"}


def query(ql, timeout=360, rounds=3):
    body = urllib.parse.urlencode({"data": ql}).encode()
    last = None
    for rnd in range(rounds):
        for url in MIRRORS:
            try:
                req = urllib.request.Request(url, data=body, headers=HDR)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                data = json.loads(raw)
                remark = data.get("remark", "")
                if "runtime error" in remark or "timed out" in remark:
                    raise RuntimeError(remark[:200])
                print(f"overpass ok: {url} ({len(raw) // 1024} KB, {len(data.get('elements', []))} elements)",
                      file=sys.stderr, flush=True)
                return data
            except Exception as e:  # noqa: BLE001
                last = e
                print(f"overpass failed: {url}: {str(e)[:160]}", file=sys.stderr, flush=True)
                time.sleep(3)
        time.sleep(20 * (rnd + 1))
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    data = query(open(src, encoding="utf-8").read())
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
