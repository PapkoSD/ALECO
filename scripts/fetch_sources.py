"""Download the open datasets the map is built from (everything lands in data/raw/, which is not committed).

  - Geofabrik Slovakia extract of OpenStreetMap (ODbL), checked against its MD5 file  (~350 MB)
  - GeoNames Slovakia places and postcodes (CC BY 4.0), used for offline village and postcode geocoding

Run: python3 scripts/fetch_sources.py            (skips files that are already there; --force to refresh)
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
UA = {"User-Agent": "open-local-food-map/0.1 (non-commercial open-data project)"}
PBF = "https://download.geofabrik.de/europe/slovakia-latest.osm.pbf"
GEONAMES = {"places": "https://download.geonames.org/export/dump/SK.zip",
            "postal": "https://download.geonames.org/export/zip/SK.zip"}


def get(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    print(f"downloaded {url} -> {dest} ({dest.stat().st_size // 1024} KB)", flush=True)


def main():
    force = "--force" in sys.argv
    pbf = RAW / "osm/slovakia-latest.osm.pbf"
    if force or not pbf.exists():
        get(PBF, pbf)
        get(PBF + ".md5", pbf.with_suffix(".pbf.md5"))
        want = pbf.with_suffix(".pbf.md5").read_text().split()[0]
        h = hashlib.md5()
        with open(pbf, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        if h.hexdigest() != want:
            sys.exit(f"MD5 mismatch for {pbf}: delete it and run again")
        print("md5 ok", flush=True)
    for name, url in GEONAMES.items():
        target = RAW / "geonames" / name / "SK.txt"
        if force or not target.exists():
            z = RAW / "geonames" / f"SK_{name}.zip"
            get(url, z)
            with zipfile.ZipFile(z) as zf:
                zf.extract("SK.txt", target.parent)
            print(f"unpacked {target}", flush=True)


if __name__ == "__main__":
    main()
