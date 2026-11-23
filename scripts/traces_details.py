"""Read product lists and farm premises from the public EU organic certificate PDFs.

The TRACES list API gives only product *categories*. The certificate PDF (public, no login) has Part II with
  II.1 Directory of products   -> what the operator actually produces, in Slovak ("Med kvetový", "Jablká", ...)
  II.4 List of premises        -> where they produce (only some control bodies fill it in)
Both are optional, so many certificates have neither.

Input : data/out/inventory.csv (consumer-relevant organic operators), data/out/organic_operators.csv
Output: data/raw/traces_pdf/<certificate>.pdf (cache), data/out/organic_details.json
Run   : python3 scripts/traces_details.py --download-only          (at most 1 PDF per second, cached)
        uv run --no-project --with pypdf python scripts/traces_details.py --parse-only
"""
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "data/raw/traces_pdf"
PDF_URL = "https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/{}.pdf"
HDR = {"User-Agent": "open-local-food-map/0.1 (non-commercial open-data project)"}

ACTIVITIES = ["Production", "Preparation", "Distribution/Placing on the market", "Storing", "Import", "Export"]
METHOD = r"(Organic|In-conversion|Conversion|Non-organic|In conversion)"
# category tags the control bodies append to product names, e.g. "(potraviny / foodstuffs)"
TAG = re.compile(r"\((?:[^()]*?/\s*)?(potraviny|foodstuffs|živočíšna výroba|livestock production|rastlinná výroba|"
                 r"plant production|krmivá|feed|víno|wine|osivo|seeds?|ostatné|other)[^()]*\)", re.I)
NOTE = re.compile(r"\((?:Obmedzenie|Restriction)[^()]*\)", re.I)


def download(refs):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    todo = [r for r in refs if not (PDF_DIR / f"{r}.pdf").exists()]
    print(f"{len(refs)} certificates, {len(todo)} to download", flush=True)
    for i, ref in enumerate(todo):
        for attempt in range(4):
            try:
                req = urllib.request.Request(PDF_URL.format(ref), headers=HDR)
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = r.read()
                if not data.startswith(b"%PDF"):
                    raise ValueError("not a PDF")
                (PDF_DIR / f"{ref}.pdf").write_bytes(data)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", ref, e, flush=True)
                time.sleep(10 * (attempt + 1))
        time.sleep(1.0)
        if i % 50 == 0:
            print(f"downloaded {i}/{len(todo)}", flush=True)


def section(text, start, end):
    a = text.find(start)
    if a < 0:
        return ""
    b = text.find(end, a)
    return text[a:b if b > 0 else None]


def clean_product(s):
    tags = [m.group(1).lower() for m in TAG.finditer(s)]
    s = NOTE.sub(" ", TAG.sub(" ", s))
    s = re.sub(r"\b\d{4}(\s?\d{2}){0,3}\b", " ", s)  # CN codes
    s = re.sub(r"^\s*(BIO|EKO|ECO)\b[\s:-]*", "", s.strip(), flags=re.I)
    s = " ".join(s.split()).strip(" ,;.-–")
    # long branded descriptions: keep the first sentence
    first = re.split(r"(?<=[a-zá-ž]{3})\.\s", s)[0]
    if len(first) > 70:
        first = first[:67].rsplit(" ", 1)[0] + "…"
    return first, tags


def parse_products(text):
    sec = section(text, "II.1 Directory of products", "II.2 Quantity")
    if not sec:
        return []
    sec = re.sub(r"^.*?Regulation \(EU\) 2018/848\s*", "", sec, count=1, flags=re.S)  # drop the column header
    sec = sec.replace("II.1 Directory of products", " ")
    # skip page furniture that can land inside the section
    sec = re.sub(r"Certificate pursuant to Article 35\(1\).*?Part II: Specific optional elements", " ", sec, flags=re.S)
    parts = re.split(rf"\s{METHOD}\s*(?:\n|$)", sec)
    out = []
    for chunk in parts[::2]:  # odd items are the captured method words
        chunk = " ".join(chunk.split())
        if len(chunk) < 2:
            continue
        name, tags = clean_product(chunk)
        if name and not re.match(r"(Produkty z ekologick|Products from organic)", name, re.I):
            out.append({"name": name, "tags": tags})
    return out


ACT_RE = "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in ACTIVITIES)
PREMISE = re.compile(rf"(?P<label>.*?)\s-\s*(?P<street>[^,]*?),?\s*(?P<pc>\d{{3}}\s?\d{{2}})\s+(?P<city>.+?)\s+"
                     rf"(?P<act>{ACT_RE})\b")
DESCR = re.compile(r"^(výroba|spracovanie|príprava|distribúcia\s*/\s*umiestnenie na trh|skladovanie|dovoz|vývoz|"
                   r"production|preparation|storing|import|export|\s|,)+", re.I)


def parse_premises(text):
    sec = section(text, "II.4 List of premises", "II.5 Information")
    if not sec:
        return []
    sec = re.sub(r"^.*?Description of the activity or activities as referred to in point\s+5 of part I", "", sec,
                 count=1, flags=re.S)
    sec = " ".join(sec.split())
    out = []
    for m in PREMISE.finditer(sec):
        label = DESCR.sub("", m.group("label")).strip(" -,")
        out.append({"label": label, "street": m.group("street").strip(" -,"),
                    "postal": re.sub(r"\s", "", m.group("pc")), "city": m.group("city").strip(),
                    "activity": " ".join(m.group("act").split())})
    return out


def parse(path):
    import pypdf  # noqa: PLC0415  (only needed for parsing)
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return {"products": parse_products(text), "premises": parse_premises(text)}


def main():
    inv = [r for r in csv.DictReader(open(ROOT / "data/out/inventory.csv", encoding="utf-8"))
           if r["source"] == "organic_eu" and r["consumer_relevant"] == "True"]
    refs = [r["source_id"] for r in inv]
    if "--parse-only" not in sys.argv:
        download(refs)
    if "--download-only" in sys.argv:
        return
    details = {}
    for i, ref in enumerate(refs):
        p = PDF_DIR / f"{ref}.pdf"
        if not p.exists():
            continue
        try:
            details[ref] = parse(p)
        except Exception as e:  # noqa: BLE001
            print("parse error", ref, e, flush=True)
            details[ref] = {"products": [], "premises": [], "error": str(e)}
    (ROOT / "data/out/organic_details.json").write_text(json.dumps(details, ensure_ascii=False, indent=0))
    with_products = sum(1 for d in details.values() if d["products"])
    with_premises = sum(1 for d in details.values() if d["premises"])
    print(f"parsed {len(details)}: {with_products} with products, {with_premises} with premises", flush=True)


if __name__ == "__main__":
    main()
