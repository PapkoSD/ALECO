# Slovak local food hub: plan

Open source, free, non-commercial. Data inventory: see `DATA_INVENTORY.md`.

## Decisions (2026-11-19)

| Question | Decision |
|---|---|
| Launch area | **Whole Slovakia on the map** (changed the same evening, at Patrik's request). Hand-checking and launch outreach still start with Bratislava |
| Version 1 | Map + directory. Buyers contact producers directly. No ordering or payments |
| "Bio" | Show all local producers. Only EU-certified operators get the **BIO** badge, linked to their TRACES certificate; the rest are labelled "lokálne" |
| Team | Patrik + Claude, so the stack must stay simple enough for one person |

## Recommended stack (simple, free to run)

- **Data:** Python scripts (already here), output one `producers.geojson`
- **Site:** static site (Astro or plain HTML), map with **MapLibre** + free OSM-based tiles, search and filters in the browser. No backend, no database
- **Hosting:** GitHub Pages or Cloudflare Pages (free)
- **Adding and changing listings:** a form (e.g. a Tally/Google form at first) that goes to a review queue; Patrik approves and the data is updated with a script. Later, a GitHub-based edit flow
- **Licences:** code AGPL-3.0, data ODbL (required anyway because we use OSM)

## Data rules

1. **Public = checked + allowed.** Organic certificates (companies) and OSM places can be shown directly. Sole traders (SHR, živnostníci) from the registers are published **only after they agree**.
2. Every field keeps its source (`source`, `source_id`, link) so anyone can check it.
3. The BIO badge disappears automatically when a certificate expires: since 2026-11-21 the page checks the end date itself. Rebuild the data monthly so renewed certificates come back.
4. Give back: add checked farm shops, milk machines and markets to OpenStreetMap.

## Build steps

1. ~~Seed list for Bratislava region~~ → **done for all of Slovakia** (2026-11-19): OSM places from the Geofabrik extract, certified organic producers whose certificate lists food for people (products and farm addresses read from the certificate PDFs), kraj/okres/obec for every place from OSM boundaries. See `data/out/report.md`.
2. **Check by hand** (started 2026-11-20): every website on the map tested (54 dead or parked links dropped, 8 fixed), duplicates and stacked pins cleaned up, and all 218 certified producers looked up online. 14 verified as selling directly, 28 taken off as wholesale-only or not local food, 19 got a website or phone. **Next: the 175 producers the web could not settle need a phone call**, Bratislava first: `data/out/call_list.csv`. Record answers with `scripts/checks.py set`.
3. ~~Static map site v0~~ → **done**: map + list that follows the map, search by name, village or product, type and region filters, BIO filter, detail card with certificate PDF, directions and a share link. Still missing: our own "add or fix a listing" form.
4. **Producer outreach:** contact the checked producers, ask them to confirm their listing and add what they sell, where and when. This is also the consent step for sole traders.
5. **Launch:** publish, post in Bratislava community groups, partner with farmers' markets.
6. **Next:** RVPS "predaj z dvora" data (info request), ÚKSÚP winemakers dataset (needs a CÚR login now, so ask ÚKSÚP for open access), Ekotrend, static pages per okres for search engines, then decide whether ordering (Open Food Network) is worth adding.

## Open requests to send (Patrik)
- ekologia@uksup.sk: ask for the current organic register as a file
- ŠVPS: info request (zákon 211/2000) for registered direct-sale (priamy predaj) producers
- Ekotrend Slovakia: introduce the project, ask about partnership
