"""Check that every website on the map still answers, and catch parked or expired domains.

Output: data/checks/websites.csv  (url, ok, status, final_url, title, reason, checked)
The build drops websites marked ok=0, so the map never links to a dead or parked domain.
Run: python3 scripts/check_websites.py        (8 parallel requests, 20 s timeout, one GET per site)
"""
import concurrent.futures as cf
import csv
import json
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/checks/websites.csv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; open-local-food-map/0.1; link check)",
      "Accept-Language": "sk,cs;q=0.8,en;q=0.5"}
PARKED = re.compile(r"doména (je )?na predaj|domain (is )?for sale|this domain|parked|parking|buy this domain|"
                    r"domena na prodej|registrácia domén|websupport\.sk - |coming soon|under construction|"
                    r"stránka sa pripravuje|pripravujeme|account suspended|index of /|default web site page|"
                    r"it works!|plesk|cpanel|hostcreators|domény a hosting", re.I)


def norm_url(u):
    u = u.strip().split(";")[0].strip()
    if not re.match(r"https?://", u, re.I):
        u = "https://" + u
    return u


def fetch(url, insecure=False):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        body = r.read(65536).decode("utf-8", "replace")
        return r.status, r.geturl(), body


def check(url):
    res = {"url": url, "ok": 0, "status": "", "final_url": "", "title": "", "reason": "",
           "checked": date.today().isoformat()}
    for attempt, insecure in ((1, False), (2, True)):
        try:
            status, final, body = fetch(url, insecure)
            m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
            title = " ".join((m.group(1) if m else "").split())[:120]
            res.update(status=status, final_url=final, title=title)
            text = title + " " + re.sub(r"<[^>]+>", " ", body)[:4000]
            if PARKED.search(title) or (not title and len(re.sub(r"\s+", "", text)) < 200
                                        and "<script" not in body.lower()):
                res["reason"] = "parked or empty page"
            else:
                res["ok"] = 1
                res["reason"] = "insecure certificate" if insecure else ""
            return res
        except urllib.error.HTTPError as e:
            res.update(status=e.code, reason=f"HTTP {e.code}")
            if e.code in (401, 403, 429, 503):  # alive, just blocking robots
                res["ok"] = 1
            return res
        except ssl.SSLError as e:
            res["reason"] = f"SSL: {str(e)[:60]}"
            continue
        except Exception as e:  # noqa: BLE001
            msg = str(getattr(e, "reason", e))
            if "CERTIFICATE" in msg.upper() and not insecure:
                res["reason"] = "SSL certificate problem"
                continue
            res["reason"] = msg[:80]
            if url.startswith("https://") and not insecure:  # some small sites only speak http
                try:
                    status, final, body = fetch("http://" + url[8:])
                    res.update(ok=1, status=status, final_url=final, reason="http only")
                except Exception:  # noqa: BLE001
                    pass
            return res
    return res


def curl_status(url):
    """Second opinion from curl: some small sites fail Python's TLS checks but work in every browser."""
    try:
        out = subprocess.run(["curl", "-sL", "-m", "20", "-A", UA["User-Agent"], "-o", "/dev/null",
                              "-w", "%{http_code} %{url_effective}", url], capture_output=True, text=True, timeout=30)
        code, _, final = out.stdout.partition(" ")
        return int(code or 0), final
    except Exception:  # noqa: BLE001
        return 0, ""


def recheck(res):
    if res["ok"] or res["reason"] == "parked or empty page":
        return res
    if "nodename nor servname" in res["reason"] or "Name or service not known" in res["reason"]:
        res["reason"] = "domain does not exist"
        return res
    code, final = curl_status(res["url"])
    if 200 <= code < 400:
        res.update(ok=1, status=code, final_url=final, reason="ok in curl (" + res["reason"][:40] + ")")
        return res
    parts = urllib.parse.urlsplit(res["url"])
    if parts.path not in ("", "/"):  # a deep link that moved: fall back to the home page
        root = f"{parts.scheme}://{parts.netloc}/"
        code, final = curl_status(root)
        if 200 <= code < 400:
            res.update(ok=1, status=code, final_url=root, reason="page gone, home page works: use " + root)
    return res


def main():
    places = json.loads((ROOT / "site/data/places.geojson").read_text())["features"]
    urls = sorted({norm_url(f["properties"]["website"]) for f in places if f["properties"].get("website")})
    checks = ROOT / "data/checks/places_checks.csv"
    if checks.exists():
        urls = sorted(set(urls) | {norm_url(r["website"]) for r in csv.DictReader(open(checks, encoding="utf-8"))
                                   if r["website"]})
    print(f"checking {len(urls)} websites", flush=True)
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(check, urls))
        results = list(ex.map(recheck, results))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)} ok, {len(bad)} dead or parked", flush=True)
    for r in bad[:40]:
        print("  ", r["url"], "|", r["status"], "|", r["reason"], "|", r["title"][:50])


if __name__ == "__main__":
    main()
