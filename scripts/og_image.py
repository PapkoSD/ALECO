"""Draw the link preview, site/og.png: every place as a dot in its colour, with today's count. Run it after a big data
update.  Run: uv run --no-project --with pillow --with fonttools --with brotli python scripts/og_image.py
"""
import io
import json
import re
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
S = 2  # drawn at twice the size, then scaled down for smooth edges
BG, INK, MUTED, LINE = "#eef1ea", "#17322a", "#56665e", "#d0d7cd"
W0, E0, N0, S0, X0, X1, Y0, Y1 = 16.83, 22.57, 49.62, 47.73, 521, 1160, 176, 496


def font(name, size, weight=None):
    f = TTFont(ROOT / "site/fonts" / name)  # the site's own woff2 files, unpacked for Pillow
    f.flavor = None
    buf = io.BytesIO()
    f.save(buf)
    buf.seek(0)
    out = ImageFont.truetype(buf, size * S)
    if weight:
        out.set_variation_by_axes([weight])
    return out


def xy(lon, lat):
    return (X0 + (lon - W0) / (E0 - W0) * (X1 - X0)) * S, (Y0 + (N0 - lat) / (N0 - S0) * (Y1 - Y0)) * S


def rings(node):
    """Every closed line of [lon, lat] points in a polygon, however deep it is nested."""
    if isinstance(node, list) and node and isinstance(node[0], (list, tuple)):
        if len(node[0]) == 2 and all(isinstance(v, (int, float)) for v in node[0]):
            yield node
        else:
            for n in node:
                yield from rings(n)


def main():
    js = (ROOT / "site/app.js").read_text()
    colour = dict(re.findall(r'\{ id: "(\w+)",\s+color: "(#\w+)" \}', js))
    group = dict(re.findall(r"(\w+): \"(\w+)\"", js[js.index("CAT_GROUP = {"):js.index("};", js.index("CAT_GROUP = {"))]))
    feats = json.loads((ROOT / "site/data/places.geojson").read_text())["features"]
    img = Image.new("RGB", (1200 * S, 630 * S), BG)
    d = ImageDraw.Draw(img)
    for a in json.loads((ROOT / "data/raw/osm/admin_sk.json").read_text()):
        if str(a["level"]) == "4":
            for key, v in a.items():
                if key not in ("osm", "level", "name"):
                    for ring in rings(v):
                        pts = [xy(*q) for q in ring]
                        d.line(pts + pts[:1], fill=LINE, width=2 * S, joint="curve")
    order = ["bakeries", "markets", "shops", "vending", "wine", "farms"]
    for f in sorted(feats, key=lambda f: order.index(group.get(f["properties"]["category"], "shops"))):
        x, y = xy(*f["geometry"]["coordinates"])
        r = 4 * S
        d.ellipse([x - r - S, y - r - S, x + r + S, y + r + S], fill="#ffffff")
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour[group.get(f["properties"]["category"], "shops")])
    sans, bold = "alegreya-sans-latin-e76bc7.woff2", "alegreya-sans-latin-80432f.woff2"
    count = f"{len(feats):,}".replace(",", " ") + " miest na mape"
    for text, fnt, colr, base in [("ALECO", font("vollkorn-latin-d823a3.woff2", 132, 700), INK, 276),
                                  ("Farmy a lokálne jedlo", font(sans, 47), INK, 355),
                                  ("na Slovensku", font(sans, 47), INK, 407),
                                  (count, font(bold, 30), MUTED, 470),
                                  ("papkosd.github.io/ALECO", font(sans, 29), MUTED, 563)]:
        d.text((76 * S, base * S), text, font=fnt, fill=colr, anchor="ls")
    img.resize((1200, 630), Image.LANCZOS).quantize(128).save(ROOT / "site/og.png", optimize=True)
    print("site/og.png:", count)


if __name__ == "__main__":
    main()
