"""Extract active Slovak farmers, bakeries and food producers from the RPO full snapshot.

Source: Register právnických osôb (MV SR), CC-BY 4.0. Reuses the snapshot downloaded by ../gastro-leads.
Output: data/out/rpo_producers.csv
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GASTRO = ROOT.parent / "gastro-leads"
sys.path.insert(0, str(GASTRO))
from rpo import iter_records  # noqa: E402

RAW = GASTRO / "data" / "raw"
OUT = ROOT / "data" / "out" / "rpo_producers.csv"

# SK NACE (4-digit main activity) -> category
NACE = {
    "011": "farm_crops", "012": "farm_crops", "013": "farm_crops", "014": "farm_livestock",
    "015": "farm_mixed", "0161": "farm_crops", "0162": "farm_livestock", "0311": "fish", "0322": "fish",
    "1071": "bakery", "1072": "bakery", "1082": "confectionery",
    "1051": "dairy", "1052": "dairy", "1011": "meat", "1012": "meat", "1013": "meat",
    "1031": "fruit_veg_processing", "1032": "fruit_veg_processing", "1039": "fruit_veg_processing",
    "1061": "mill", "1084": "condiments", "1089": "food_other", "1102": "wine", "1103": "cider", "1105": "beer",
    "4721": "shop_fruit_veg", "4722": "shop_meat", "4724": "shop_bakery", "4729": "shop_food_specialised",
    "4781": "market_stall_food",
}
# Trade-licence phrases that signal a food producer even when NACE says something else
TEXT = {
    "pekár": "bakery", "pekárensk": "bakery", "cukrár": "confectionery", "mäsiar": "meat", "údenár": "meat",
    "mliekar": "dairy", "syrár": "dairy", "mlynár": "mill", "včelár": "honey", "výroba vína": "wine",
    "pestovanie": "farm_crops", "chov ": "farm_livestock",
}
BUSINESS = {"101", "102", "105", "111", "112", "113", "121", "125", "205"}
REGIONS = {"SK010": "Bratislavský", "SK021": "Trnavský", "SK022": "Trenčiansky", "SK023": "Nitriansky",
           "SK031": "Žilinský", "SK032": "Banskobystrický", "SK041": "Prešovský", "SK042": "Košický"}


def cur(timed):
    c = [e for e in (timed or []) if not e.get("validTo")]
    return c[-1] if c else None


def nace_cat(code):
    for k in sorted(NACE, key=len, reverse=True):
        if code.startswith(k):
            return NACE[k]
    return None


def main():
    files = sorted(RAW.glob("init_*.json.gz"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = kept = 0
    with open(OUT, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["ico", "name", "legal_form", "is_person", "category", "match", "nace", "nace_label",
                    "street", "number", "postal", "municipality", "region", "established", "rpo_id"])
        for f in files:
            for r in iter_records(f):
                n += 1
                if r.get("termination") or any(not s.get("validTo") for s in r.get("legalStatuses") or []):
                    continue  # skip ended / in liquidation
                lf = (cur(r.get("legalForms")) or {}).get("value") or {}
                if lf.get("code") not in BUSINESS:
                    continue
                main_act = ((r.get("statisticalCodes") or {}).get("mainActivity") or {})
                code = main_act.get("code") or ""
                cat, match = nace_cat(code), "nace"
                if not cat:
                    acts = " | ".join((a.get("economicActivityDescription") or "").lower()
                                      for a in r.get("activities") or [] if not a.get("validTo"))
                    for k, v in TEXT.items():
                        if k in acts:
                            cat, match = v, "licence_text"
                            break
                if not cat:
                    continue
                a = cur(r.get("addresses")) or {}
                muni = a.get("municipality") or {}
                w.writerow([
                    (cur(r.get("identifiers")) or {}).get("value", ""),
                    (cur(r.get("fullNames")) or {}).get("value", ""),
                    lf.get("value", ""), lf.get("code") in {"101", "102", "105"}, cat, match, code,
                    main_act.get("value", ""), a.get("street") or "",
                    a.get("buildingNumber") or (a.get("regNumber") or ""), (a.get("postalCodes") or [""])[0],
                    muni.get("value", ""), REGIONS.get((muni.get("code") or "")[:5], ""),
                    r.get("establishment", ""), r.get("id"),
                ])
                kept += 1
            print(f"{f.name}: scanned {n:,}, kept {kept:,}", flush=True)


if __name__ == "__main__":
    main()
