/* ALECO: open map of local food in Slovakia. No build step, no tracking, no cookies. */
(() => {
  "use strict";

  /* Colours belong to place groups, so the map stays readable with a dozen place types. The legend sits on the map. */
  const GROUPS = [
    { id: "farms",    label: "Farmy",     color: "#2e6b45" },
    { id: "wine",     label: "Vinárstva", color: "#7a2343" },
    { id: "bakeries", label: "Pekárne",   color: "#b8862b" },
    { id: "vending",  label: "Automaty",  color: "#2f6db5" },
    { id: "markets",  label: "Trhy",      color: "#b24a2c" },
    { id: "shops",    label: "Obchody",   color: "#3e8e86" },
  ];
  const CATS = {
    farm:         { label: "Farma",                  group: "farms" },
    producer:     { label: "Výrobca potravín",       group: "farms" },
    honey:        { label: "Včelár",                 group: "farms" },
    salas:        { label: "Salaš",                  group: "farms" },
    winery:       { label: "Vinárstvo",              group: "wine" },
    bakery:       { label: "Pekáreň",                group: "bakeries" },
    vending:      { label: "Mliečny automat",        group: "vending" },
    market:       { label: "Trh",                    group: "markets" },
    organic_shop: { label: "Bio obchod",             group: "shops" },
    dairy:        { label: "Mliečne výrobky a syry", group: "shops" },
    deli:         { label: "Lahôdky",                group: "shops" },
    butcher:      { label: "Mäsiarstvo",             group: "shops" },
    greengrocer:  { label: "Ovocie a zelenina",      group: "shops" },
  };
  const GROUP_COLOR = Object.fromEntries(GROUPS.map((g) => [g.id, g.color]));
  const SK_BOUNDS = [[16.83, 47.73], [22.57, 49.62]];
  const PAGE = 40;
  const RADII = [10, 25, 50, 0];  // km around the chosen place, as in the select; 0 = all of Slovakia, nearest first
  const CERT_PDF = (ref) => `https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/${encodeURIComponent(ref)}.pdf`;
  // where people ask to add, fix or remove a place; put together here rather than written into the page,
  // so simple address harvesters miss it
  const CONTACT = ["patrikmihal.dev", "gmail.com"].join("@");
  const mailto = (subject, body) => `mailto:${CONTACT}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  // anonymous counts of what people use, so we can tell whether the map helps (GoatCounter: no cookies, no IP
  // addresses stored). Never the visitor's own position. count.js loads after this script, so early counts wait for it.
  const pendingCounts = [];
  function track(path, title) {
    const gc = window.goatcounter;
    if (gc && gc.count) {
      try { gc.count({ path, title: title || path, event: true }); } catch { /* counting must never break the map */ }
    } else if (pendingCounts.length < 20) {
      pendingCounts.push([path, title]);
    }
  }
  window.addEventListener("load", () => { if (window.goatcounter?.count) pendingCounts.splice(0).forEach(([p, t]) => track(p, t)); });

  const $ = (s) => document.querySelector(s);
  const fc = (feats) => ({ type: "FeatureCollection", features: feats });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fold = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const safeUrl = (u) => {
    if (!u) return "";
    const url = /^https?:\/\//i.test(u) ? u : `https://${u}`;
    try { const p = new URL(url); return /^https?:$/.test(p.protocol) ? p.href : ""; } catch { return ""; }
  };
  const km = ([lo1, la1], [lo2, la2]) => {
    const r = Math.PI / 180, dLa = (la2 - la1) * r, dLo = (lo2 - lo1) * r;
    const h = Math.sin(dLa / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dLo / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
  };
  const fmtKm = (d) => (d < 10 ? d.toFixed(1).replace(".", ",") : Math.round(d)) + " km";
  const fmtNum = (n) => n.toLocaleString("sk-SK");
  const fmtDate = (iso) => { const [y, m, d] = iso.split("-"); return `${+d}. ${+m}. ${y}`; };
  const plural = (n, one, few, many) => (n === 1 ? one : n > 1 && n < 5 ? few : many);
  const DAYS = { Mo: "Po", Tu: "Ut", We: "St", Th: "Št", Fr: "Pi", Sa: "So", Su: "Ne", PH: "sviatky", off: "zatvorené" };
  const fmtHours = (h) => h.replace(/\b(Mo|Tu|We|Th|Fr|Sa|Su|PH|off)\b/g, (m) => DAYS[m]).replace(/;\s*/g, "\n");
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const catOf = (p) => CATS[p.category] || { label: p.category, group: "shops" };
  const labelOf = (p) => p.label || catOf(p).label;
  // "Šamorín, okres Dunajská Streda"; no okres when it only repeats the town ("Bratislava-Petržalka", "Nitra")
  const sameTown = (obec, okres) => obec === okres || (/^(Bratislava|Košice) [IV]+$/.test(okres) && obec.startsWith(okres.split(" ")[0]));
  const okresOf = (p) => (p.okres && p.obec && !sameTown(p.obec, p.okres) ? `okres ${p.okres}` : "");
  const place = (p) => [p.obec, okresOf(p)].filter(Boolean).join(", ");
  // today in the visitor's time zone ("2026-11-28"); a certificate is valid through its end date
  const TODAY = (() => { const d = new Date(); return [d.getFullYear(), d.getMonth() + 1, d.getDate()].map((n) => String(n).padStart(2, "0")).join("-"); })();

  /* OSM names that only say what a place is ("Trh", "Mliekomat") get the town added: "Trh Brezno" */
  const GENERIC = new Set(["trh", "trhovisko", "trznica", "farmarsky trh", "mliekomat", "mliecny automat", "automat na mlieko",
    "salas", "pekaren", "farma", "vinarstvo", "vcelarstvo", "potraviny", "farmarsky obchod", "obchod", "predajna", "bio obchod",
    "masiarstvo", "syraren", "ovocie a zelenina", "zelovoc"]);
  // a lower-case name that starts with an ordinary word is a typo, not brand styling: "salaš Obrubovanec" (but "emBIO" stays)
  const PLAIN_START = new Set(["salas", "automat", "trh", "trhovisko", "ovocie", "farma", "farmarsky", "pekaren", "mliecny",
    "mliekomat", "vcelarstvo", "vinarstvo", "stary", "predajna", "obchod", "potraviny"]);
  function displayName(p) {
    let n = p.name.trim();
    const junk = n.replace(/[^\p{L}]/gu, "").length < 2;  // "M" is a mapping mistake, not a name
    if (junk) n = labelOf(p);
    else if (n[0] !== n[0].toUpperCase() && PLAIN_START.has(fold(n.split(/\s+/)[0]))) n = n[0].toUpperCase() + n.slice(1);
    const generic = junk || GENERIC.has(fold(n)) || fold(n) === fold(labelOf(p));
    return { name: generic && p.obec ? `${n} ${p.obec}` : n, generic };
  }

  /* Zoomed out to all of Slovakia, "nearest to the map centre" means nothing: checked places and places with contacts go first */
  const OVERVIEW_ZOOM = 7.5;
  const GROUP_RANK = { farms: 0, vending: 1, shops: 2, wine: 3, markets: 4, bakeries: 5 };
  const rankOf = (p) => (p.checked ? 0 : (p.phone || p.website) && p.hours ? 1 : p.phone || p.website || p.hours ? 2 : 3) * 10
    + (GROUP_RANK[p.group] ?? 6);

  /* What you can buy. The ids match BUY in scripts/build_seed.py, which tags every place with them ("buy");
     `words` let people type a product into the search box: "bryndza" offers Syry. */
  const BUY = [
    { id: "mlieko",   label: "Mlieko",   with: "s mliekom",    words: "mlieko mlieka mliečne mliekomat jogurt tvaroh maslo kefír smotana" },
    { id: "syr",      label: "Syry",     with: "so syrmi",     words: "syr syry syra syrov bryndza bryndze oštiepok parenica korbáčiky žinčica" },
    { id: "vajcia",   label: "Vajcia",   with: "s vajciami",   words: "vajcia vajec vajíčka vajíčok vajce" },
    { id: "maso",     label: "Mäso",     with: "s mäsom",      words: "mäso mäsa údeniny klobása klobásy slanina šunka ryby rýb pstruh hovädzie bravčové jahňacie" },
    { id: "med",      label: "Med",      with: "s medom",      words: "med medu medovina propolis" },
    { id: "ovocie",   label: "Ovocie",   with: "s ovocím",     words: "ovocie ovocia jablká jabĺk hrušky slivky marhule čerešne jahody maliny ríbezle čučoriedky orechy samozber" },
    { id: "zelenina", label: "Zelenina", with: "so zeleninou", words: "zelenina zeleniny zemiaky zemiakov mrkva cibuľa cesnak kapusta paradajky paprika uhorky špargľa huby" },
    { id: "pecivo",   label: "Pečivo",   with: "s pečivom",    words: "pečivo pečiva chlieb chleba rožky koláče pekáreň kváskový" },
    { id: "vino",     label: "Víno",     with: "s vínom",      words: "víno vína vínom vinárstvo vinár" },
  ].map((b) => ({ ...b, fw: fold(b.words).split(" ") }));
  // around towns the many bakeries and plain markets ("Trh Brezno") would fill the first page: they come after the rest
  const laterTier = (p) => p.group === "bakeries" || (p.group === "markets" && p._generic);
  const BUY_BY_ID = Object.fromEntries(BUY.map((b) => [b.id, b]));

  const state = {
    all: [], byId: new Map(), buy: "all", bioOnly: false,
    loc: null,                     // the chosen place: { name, okres, c: [lon, lat], me: true for "Moja poloha" }
    radius: 25, dist: new Map(),   // km from loc to every place, by id
    shown: PAGE, selected: null, matches: [], counts: {}, unknown: 0,
    obce: null, suggest: [],
  };

  /* ---------- map ---------- */
  const linkHadMapView = location.hash.includes("mapa=");  // read before MapLibre writes its own #mapa=
  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/positron",
    bounds: SK_BOUNDS,
    fitBoundsOptions: { padding: 16 },
    hash: "mapa",
    attributionControl: { compact: true },
    dragRotate: false,
    pitchWithRotate: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  const colorExpr = ["match", ["get", "group"], ...Object.entries(GROUP_COLOR).flat(), "#17322a"];

  function slovakLabels() {
    // base map labels in Slovak where OSM has a Slovak name ("Maďarsko", "Viedeň"), otherwise the local name
    for (const l of map.getStyle().layers) {
      const tf = l.type === "symbol" && l.layout && l.layout["text-field"];
      if (tf && /name/.test(JSON.stringify(tf))) {
        map.setLayoutProperty(l.id, "text-field", ["coalesce", ["get", "name:sk"], ["get", "name"]]);
      }
    }
  }

  function addLayers() {
    slovakLabels();
    // the search area: a faint disc around the chosen place
    map.addSource("area", { type: "geojson", data: fc([]) });
    map.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#17322a", "fill-opacity": 0.05 } });
    map.addLayer({ id: "area-line", type: "line", source: "area",
      paint: { "line-color": "#17322a", "line-width": 1.5, "line-opacity": 0.55, "line-dasharray": [3, 2] } });
    map.addSource("places", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 38, clusterMaxZoom: 11 });
    map.addLayer({ id: "clusters", type: "circle", source: "places", filter: ["has", "point_count"],
      paint: { "circle-color": "#17322a", "circle-opacity": 0.88, "circle-stroke-color": "#fff", "circle-stroke-width": 2,
               "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 50, 23, 200, 28] } });
    map.addLayer({ id: "cluster-count", type: "symbol", source: "places", filter: ["has", "point_count"],
      layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 13, "text-font": ["Noto Sans Bold"] },
      paint: { "text-color": "#fff" } });
    map.addLayer({ id: "points", type: "circle", source: "places", filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": colorExpr,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4.5, 14, 9],
        "circle-opacity": ["case", ["==", ["get", "approx"], true], 0.6, 1],
        "circle-stroke-color": ["case", ["==", ["get", "bio"], true], "#2e6b45", "#ffffff"],
        "circle-stroke-width": ["case", ["==", ["get", "bio"], true], 3, 1.5],
      } });
    // the open place has its own source, so it shows even when the filters hide it (picked by name, far away)
    map.addSource("sel", { type: "geojson", data: fc([]) });
    map.addLayer({ id: "sel-dot", type: "circle", source: "sel",
      paint: { "circle-radius": 8, "circle-color": colorExpr, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
    map.addLayer({ id: "selected", type: "circle", source: "sel",
      paint: { "circle-radius": 15, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#17322a", "circle-stroke-width": 3 } });
    // the chosen village (white) or the visitor's own position (blue)
    map.addSource("loc", { type: "geojson", data: fc([]) });
    map.addLayer({ id: "loc", type: "circle", source: "loc",
      paint: { "circle-radius": 7, "circle-color": ["case", ["get", "me"], "#2f6db5", "#ffffff"],
               "circle-stroke-color": ["case", ["get", "me"], "#ffffff", "#17322a"], "circle-stroke-width": 3 } });

    map.on("click", "clusters", (e) => {
      const f = e.features[0];
      map.getSource("places").getClusterExpansionZoom(f.properties.cluster_id).then((z) =>
        map.easeTo({ center: f.geometry.coordinates, zoom: z }));
    });
    map.on("click", "points", (e) => select(e.features[0].properties.id, false));
    for (const l of ["clusters", "points"]) {
      map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", l, () => (map.getCanvas().style.cursor = ""));
    }
    // without a chosen place the list follows the map
    map.on("moveend", debounce(() => { if (!state.loc && !state.selected) { state.shown = PAGE; renderList(); } }, 200));
  }

  /* ---------- filtering: where (place + distance), BIO, then what to buy ---------- */
  function filter() {
    const r = state.loc ? state.radius : 0;
    const base = state.all.filter((f) => (!state.bioOnly || f.properties.bio) && (!r || state.dist.get(f.properties.id) <= r));
    const counts = { all: base.length };
    let unknown = 0;
    for (const f of base) {
      const buy = f.properties.buy;
      if (!buy) unknown++;
      else for (const k of buy) counts[k] = (counts[k] || 0) + 1;
    }
    state.counts = counts;
    state.unknown = state.buy === "all" ? 0 : unknown;
    state.matches = state.buy === "all" ? base : base.filter((f) => f.properties.buy?.includes(state.buy));
    if (map.getSource("places")) map.getSource("places").setData(fc(state.matches));
  }

  function renderChips() {
    for (const b of document.querySelectorAll("#chips .chip")) {
      const n = state.counts[b.dataset.buy] || 0;
      const on = b.dataset.buy === state.buy;
      b.setAttribute("aria-pressed", on);
      b.disabled = !n && !on;  // nothing of that kind in the chosen area
      b.querySelector(".n").textContent = fmtNum(n);
    }
  }

  // with a product chosen, say how many places nearby may sell it too but do not tell us what they sell
  function renderHint() {
    const n = state.unknown;
    const near = state.loc && state.radius ? " v okolí" : "";
    const more = state.matches.length ? (n === 1 ? " ďalšom" : " ďalších") : "";  // "more" only when the list shows some
    $("#hint").innerHTML = !n ? "" : (n === 1
      ? `Pri jednom${more} mieste${near} nevieme, čo presne predáva. Nájdete ho pod`
      : `Pri${more} ${fmtNum(n)} miestach${near} nevieme, čo presne predávajú, napríklad pri trhoch. Nájdete ich pod`)
      + ` <button type="button" class="link-btn" data-buy="all">Všetko</button>.`;
    $("#hint").hidden = !n || !!state.selected;
  }

  const fromLoc = (to) => (state.loc.me ? (to ? "vám" : "vás") : `${to ? "obci" : "obce"} ${esc(state.loc.name)}`);

  function emptyMessage(what) {
    if (state.loc && state.radius) {
      const next = RADII[RADII.indexOf(state.radius) + 1];
      return `<li class="empty">Do ${state.radius} km od ${fromLoc(false)} sme nenašli nič${what}.
        <button type="button" class="link-btn" data-radius="${next}">${next ? `Hľadať do ${next} km` : "Hľadať na celom Slovensku"}</button></li>`;
    }
    return `<li class="empty">Takému výberu nič nezodpovedá. Skúste iný produkt alebo vypnite filter BIO.</li>`;
  }

  function renderList() {
    const rows = state.matches;
    const n = rows.length;
    const loc = state.loc;
    const overview = !loc && map.getZoom() < OVERVIEW_ZOOM;
    const what = state.buy === "all" ? "" : ` ${BUY_BY_ID[state.buy].with}`;
    const where = loc
      ? (state.radius ? ` do ${state.radius} km od ${fromLoc(false)}` : `, najbližšie k ${fromLoc(true)}`)
      : overview ? " na celom Slovensku, najprv overené a tie, kde poznáme kontakt" : ", najbližšie k stredu mapy";
    $("#count").innerHTML = n ? `<strong>${fmtNum(n)}</strong> ${plural(n, "miesto", "miesta", "miest")}${what}${where}` : "";
    $("#shareSearch").hidden = !n || !((state.loc && !state.loc.me) || state.buy !== "all" || state.bioOnly);
    const list = $("#list");
    if (!n) {
      list.innerHTML = emptyMessage(what);
      return;
    }
    const o = loc ? loc.c : map.getCenter().toArray();
    const tiered = state.buy === "all" && !overview;  // the overview has its own order
    const sorted = rows.map((f) => ({ f, d: loc ? state.dist.get(f.properties.id) : km(o, f.geometry.coordinates),
      r: overview ? f.properties._r : tiered && laterTier(f.properties) ? 1 : 0 }))
      .sort((a, b) => a.r - b.r || a.d - b.d);
    const page = sorted.slice(0, state.shown);
    let headed = false;
    list.innerHTML = page.map(({ f, d, r }, i) => {
      const p = f.properties;
      // "Trh Brezno" already names the town and "Farma Beckov" already says it is a farm
      const label = fold(p._n).startsWith(fold(labelOf(p))) ? "" : labelOf(p);
      const where = p._generic ? p.address || okresOf(p) : place(p) || p.address;
      const head = tiered && r === 1 && !headed && (headed = true) && i > 0 ? `<li class="group-head">Pekárne a trhy</li>` : "";
      return `${head}<li><button class="item" data-id="${esc(p.id)}" style="--c:${GROUP_COLOR[p.group] || "#17322a"}">
        <span class="dot" aria-hidden="true"></span>
        <span class="name">${esc(p._n)}${p.bio ? '<span class="bio-mini" title="Certifikovaná ekologická výroba">BIO</span>' : ""}${p.checked ? '<span class="ok-mini" title="Overili sme, že predávajú priamo">overené</span>' : ""}</span>
        ${loc ? `<span class="km">${fmtKm(d)}</span>` : "<span></span>"}
        <span class="meta">${esc([label, where].filter(Boolean).join(", "))}</span>
      </button></li>`;
    }).join("") + (n > state.shown
      ? `<li class="more"><button type="button" class="btn ghost" id="more">Zobraziť ďalšie (${fmtNum(Math.min(PAGE, n - state.shown))} z ${fmtNum(n - state.shown)})</button></li>`
      : "");
  }

  function render() {
    filter();
    renderChips();
    renderHint();
    state.shown = PAGE;
    renderList();
  }

  /* ---------- detail ---------- */
  function stampSvg(p) {
    return `<svg class="stamp" viewBox="0 0 120 120" role="img" aria-label="Certifikovaná ekologická výroba, certifikát ${esc(p.cert)}">
      <defs><path id="ring" d="M60,60 m-44,0 a44,44 0 1,1 88,0 a44,44 0 1,1 -88,0"/></defs>
      <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="3"/>
      <circle cx="60" cy="60" r="33" fill="none" stroke="currentColor" stroke-width="1.5"/>
      <text font-size="10.5" font-weight="700" letter-spacing="1.2"><textPath href="#ring" startOffset="0">EKOLOGICKÁ POĽNOHOSPODÁRSKA VÝROBA · EÚ ·</textPath></text>
      <text class="big" x="60" y="72" text-anchor="middle">BIO</text>
    </svg>`;
  }

  function showDetail(f) {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    const web = safeUrl(p.website);
    const approx = p.precision === "village" ? "poloha na mape je stred obce, nie presná adresa"
      : p.precision === "postcode" ? "poloha na mape je len približná (podľa PSČ)" : "";
    const area = p.address && p.obec && fold(p.address).includes(fold(p.obec))
      ? (p.okres && !sameTown(p.obec, p.okres) ? `okres ${p.okres}` : "") : place(p);
    const where = [p.address, area].filter(Boolean).join(", ");
    const tel = p.phone ? p.phone.replace(/[^\d+]/g, "") : "";
    const certLink = p.cert ? `<a href="${CERT_PDF(p.cert)}" target="_blank" rel="noopener">${esc(p.cert)}</a>` : "";
    const facts = [
      where && ["Kde", esc(where) + (p.kraj ? `<br><span class="small">${esc(p.kraj)} kraj</span>` : "") + (approx ? `<br><span class="small">${approx}</span>` : "")],
      state.loc && ["Vzdialenosť", `${fmtKm(state.dist.get(p.id) ?? km(state.loc.c, f.geometry.coordinates))} od ${fromLoc(false)}`],
      p.how && ["Predaj", esc(p.how) + `<br><span class="small">Overené ${fmtDate(p.checked)} na ich stránke</span>`],
      p.bioExpired && ["Certifikát BIO", `${certLink} platil do ${fmtDate(p.cert_expires)}. Novší sme zatiaľ nenačítali.`],
      p.products && [p.bio ? "Certifikované produkty" : p.bioExpired ? "Produkty podľa certifikátu" : "Ponuka", esc(p.products)],
      p.premises && ["Prevádzky", esc(p.premises).replace(/; /g, "<br>")],
      p.hours && ["Otvorené", esc(fmtHours(p.hours)).replace(/\n/g, "<br>")],
      tel && ["Telefón", `<a href="tel:${esc(tel)}" data-track="zavolat">${esc(p.phone)}</a>`],
      web && ["Web", `<a href="${esc(web)}" target="_blank" rel="noopener" data-track="web">${esc(web.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))}</a>`],
    ].filter(Boolean);
    const edited = p.osm_edited ? +p.osm_edited.slice(0, 4) : 0;
    const stale = edited && edited <= new Date().getFullYear() - 5;
    const noContact = !p.phone && !web && !p.hours;
    const note = [
      noContact && (p.source === "osm" ? "Kontakt ani otváracie hodiny zatiaľ nepoznáme." : "Kontakt zatiaľ nepoznáme."),
      p.cert && !p.checked && p.source !== "osm" && "Z certifikátu nevieme, či predávajú aj priamo, preto si to pred návštevou overte.",
      stale && `Údaje v OpenStreetMap sú naposledy upravené v roku ${edited}, pred cestou si overte, či miesto ešte funguje.`,
    ].filter(Boolean).join(" ");
    const osm = p.id.startsWith("osm-") ? p.id.slice(4) : "";
    const osmType = { n: "node", w: "way", r: "relation" }[osm[0]];
    const osmUrl = osm ? `https://www.openstreetmap.org/${osmType}/${osm.slice(1)}` : "";
    const editUrl = osm ? `https://www.openstreetmap.org/edit?${osmType}=${osm.slice(1)}` : "";
    const source = p.source === "osm"
      ? `<a href="${osmUrl}" target="_blank" rel="noopener">OpenStreetMap</a>${p.cert ? ' a <a href="' + CERT_PDF(p.cert) + '" target="_blank" rel="noopener">EÚ register ekologických certifikátov</a>' : ""}`
      : `<a href="${CERT_PDF(p.cert)}" target="_blank" rel="noopener">EÚ register ekologických certifikátov (TRACES)</a>`;

    // what the place is listed under in "Čo chcete kúpiť?"; a certificate only says what they make, not that they sell it
    const buys = (p.buy || []).map((k) => BUY_BY_ID[k]?.label).filter(Boolean);
    const buyLine = buys.length ? `<p class="buys">${p.cert && !p.checked && p.source !== "osm" ? "Vyrábajú" : "Kúpite tu"}: `
      + buys.map((l) => `<span class="tag">${l}</span>`).join(" ") + "</p>" : "";
    // "Nahlásiť chybu": an e-mail with the place filled in, which anyone can send (the OSM editor needs an account)
    const link = `${location.origin}${location.pathname}?miesto=${encodeURIComponent(p.id)}`;
    const report = mailto(`ALECO: ${p._n}`,
      `Dobrý deň,\n\nmiesto: ${p._n}${p.obec ? `, ${p.obec}` : ""}\n${link}\n\nČo treba opraviť alebo odstrániť:\n`);

    // the buttons come right after the name, so on a phone "Navigovať" is visible without scrolling
    $("#detail").innerHTML = `
      <p class="back"><button type="button" class="link-btn" id="back">Späť na zoznam</button></p>
      <h2>${esc(p._n)}</h2>
      <p class="kind" style="--c:${GROUP_COLOR[p.group] || "#17322a"}"><span class="dot" aria-hidden="true"></span>${esc(labelOf(p))}</p>
      ${buyLine}
      <div class="actions">
        <a class="btn" href="https://www.google.com/maps/dir/?api=1&amp;destination=${lat}%2C${lon}" target="_blank" rel="noopener" data-track="navigovat">Navigovať</a>
        ${tel ? `<a class="btn ghost" href="tel:${esc(tel)}" data-track="zavolat">Zavolať</a>` : ""}
        <button type="button" class="btn ghost" id="share">Zdieľať</button>
        <a class="btn ghost" href="${esc(report)}" data-track="nahlasit-chybu">Nahlásiť chybu</a>
      </div>
      ${p.bio ? `<div class="stamp-wrap">${stampSvg(p)}
        <p>Certifikát ${certLink}${p.cert_expires ? `<br>platí do ${fmtDate(p.cert_expires)}` : ""}</p></div>` : ""}
      <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      ${note ? `<p class="note">${note}</p>` : ""}
      <p class="source">Zdroj: ${source}${editUrl ? `. Mapujete v OpenStreetMap? <a href="${editUrl}" target="_blank" rel="noopener">Upravte miesto tam</a>` : ""}</p>`;
    $("#back").addEventListener("click", deselect);
    $("#share").addEventListener("click", () => share(p));
  }

  async function share(p) {
    const url = new URL(location.href);
    url.hash = "";
    url.searchParams.set("miesto", p.id);
    const btn = $("#share");
    track("zdielat-miesto", p._n);
    try {
      if (navigator.share) { await navigator.share({ title: p._n, url: url.href }); return; }
      await navigator.clipboard.writeText(url.href);
      btn.textContent = "Odkaz skopírovaný";
    } catch {
      btn.textContent = "Odkaz sa nepodarilo skopírovať";
    }
    setTimeout(() => { if (btn.isConnected) btn.textContent = "Zdieľať"; }, 2500);
  }

  // the address bar always holds the current search, so it can be copied and shared: ?kde=Pezinok&co=syr&km=10
  const START = new URL(location.href).searchParams;  // what the visitor arrived with, read before it is rewritten
  function syncUrl() {
    const url = new URL(location.href);
    const set = (k, v) => (v ? url.searchParams.set(k, v) : url.searchParams.delete(k));
    const loc = state.loc && !state.loc.me ? state.loc : null;  // never put the visitor's own position into a link
    set("kde", loc?.name);
    set("okres", loc && state.obce && state.obce.filter((o) => o.name === loc.name).length > 1 ? loc.okres : "");  // two Haniskas
    set("km", loc && state.radius !== 25 ? String(state.radius) : "");
    set("co", state.buy !== "all" ? state.buy : "");
    set("bio", state.bioOnly ? "1" : "");
    set("miesto", state.selected);
    history.replaceState(null, "", url);
  }

  async function shareSearch() {
    const btn = $("#shareSearch");
    const url = new URL(location.href);
    url.hash = "";  // the link sets the area itself
    url.searchParams.delete("miesto");
    track("zdielat-vyber");
    try {
      if (navigator.share) { await navigator.share({ title: "ALECO", text: $("#count").textContent.trim(), url: url.href }); return; }
      await navigator.clipboard.writeText(url.href);
      btn.textContent = "Odkaz skopírovaný";
    } catch {
      btn.textContent = "Odkaz sa nepodarilo skopírovať";
    }
    setTimeout(() => { btn.textContent = "Zdieľať výber"; }, 2500);
  }

  function select(id, fly = true) {
    const f = state.byId.get(id);
    if (!f) return;
    state.selected = id;
    showDetail(f);
    $("#list").hidden = true;
    $("#countRow").hidden = true;
    $("#hint").hidden = true;
    $("#detail").hidden = false;
    // the card starts at the top of the panel; on phones it would otherwise open below the search and filters
    $("#detail").scrollIntoView({ block: "start" });
    if (map.getSource("sel")) map.getSource("sel").setData(fc([f]));
    if (fly) map.flyTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 13), essential: true });
    syncUrl();
    track(`miesto/${id}`, f.properties._n);
    document.title = `${f.properties._n}: ALECO`;
    $("#back").focus({ preventScroll: true });
  }

  function deselect() {
    const id = state.selected;
    state.selected = null;
    $("#detail").hidden = true;
    $("#list").hidden = false;
    $("#countRow").hidden = false;
    if (map.getSource("sel")) map.getSource("sel").setData(fc([]));
    syncUrl();
    document.title = TITLE;
    renderHint();
    renderList();
    if (state.loc) fitArea();  // back to the chosen area, also after opening a place far away by name
    document.querySelector(`.item[data-id="${CSS.escape(id || "")}"]`)?.focus();
  }
  const TITLE = document.title;

  /* ---------- where: a village, a town or the visitor's own position ---------- */
  function circle([x, y], r) {
    const dy = r / 111.32, dx = dy / Math.cos((y * Math.PI) / 180);
    const ring = Array.from({ length: 65 }, (_, i) => {
      const a = (i / 64) * 2 * Math.PI;
      return [x + dx * Math.cos(a), y + dy * Math.sin(a)];
    });
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: {} };
  }

  function drawArea() {
    if (!map.getSource("loc")) return;
    const loc = state.loc;
    map.getSource("loc").setData(fc(loc ? [{ type: "Feature", geometry: { type: "Point", coordinates: loc.c }, properties: { me: !!loc.me } }] : []));
    map.getSource("area").setData(fc(loc && state.radius ? [circle(loc.c, state.radius)] : []));
  }

  function fitArea() {
    const loc = state.loc;
    if (!loc) { map.fitBounds(SK_BOUNDS, { padding: 16 }); return; }
    const [x, y] = loc.c;
    if (state.radius) {
      const dy = state.radius / 111.32, dx = dy / Math.cos((y * Math.PI) / 180);
      map.fitBounds([[x - dx, y - dy], [x + dx, y + dy]], { padding: 16 });
      return;
    }
    // all of Slovakia, nearest first: show the place together with the five nearest matches, however far they are
    const near = state.matches.map((f) => f.geometry.coordinates).sort((a, b) => km(loc.c, a) - km(loc.c, b)).slice(0, 5);
    const xs = [x, ...near.map((c) => c[0])], ys = [y, ...near.map((c) => c[1])];
    map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]], { padding: 56, maxZoom: 13 });
  }

  function setLoc(loc) {
    state.loc = loc;
    state.dist = new Map(loc ? state.all.map((f) => [f.properties.id, km(loc.c, f.geometry.coordinates)]) : []);
    $("#nearRow").hidden = !loc;
    if (state.selected) deselect();
    render();
    drawArea();
    fitArea();
    syncUrl();
    if (loc && !loc.me) track(`obec/${loc.name}`, loc.name);  // which villages and towns people look for
  }

  function setRadius(r) {
    state.radius = r;
    $("#radius").value = String(r);
    if (state.selected) deselect();
    render();
    drawArea();
    fitArea();
    syncUrl();
  }

  function setBuy(id) {
    state.buy = id;
    if (state.selected) deselect();
    render();
    syncUrl();
    if (id !== "all") track(`produkt/${id}`, BUY_BY_ID[id].label);
  }

  /* ---------- search box: villages and towns first, then products and places by name ---------- */
  // ~2,900 municipalities, loaded the first time someone uses the search box
  let obceLoading = null;
  function loadObce() {
    obceLoading ??= fetch("data/obce.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : [])).catch(() => [])
      .then((rows) => (state.obce = rows.map(([name, okres, lon, lat]) => {
        const f = fold(name);
        return { name, okres, c: [lon, lat], f, w: f.split(/[\s-]+/) };
      })));
    return obceLoading;
  }

  function findObce(q) {
    const fq = fold(q.trim()).replace(/\s+/g, " ");
    if (!state.obce || fq.length < 3) return [];
    const exact = [], start = [], word = [];
    for (const o of state.obce) {
      if (o.f === fq) exact.push(o);
      else if (o.f.startsWith(fq)) start.push(o);
      else if (o.w.some((w) => w.startsWith(fq))) word.push(o);
    }
    const shortFirst = (a, b) => a.f.length - b.f.length || a.f.localeCompare(b.f);
    return [...exact, ...start.sort(shortFirst), ...word.sort(shortFirst)].slice(0, 4);
  }

  // "v Bratislave", "pri Pezinku", "okolo Pezinka", "v Senci", "blízko Bratislavy", "v Košiciach": the usual Slovak
  // endings, back to the town's own name
  const TOWN_ENDINGS = [[/e$/, "a"], [/ku$/, "ok"], [/ka$/, "ok"], [/ci$/, "ec"], [/ca$/, "ec"], [/iach$/, "e"], [/ic$/, "ice"],
    [/ach$/, "y"], [/ove$/, "ov"], [/y$/, "a"], [/e$/, ""], [/a$/, ""], [/i$/, "a"]];
  const FILLER = new Set(["v", "vo", "pri", "okolo", "okolie", "blizko", "z", "zo", "na", "do", "pre", "a", "kde", "kupit",
    "predaj", "cerstve", "domace", "bio"]);
  function findTown(text) {
    const words = text.split(" ").filter((w) => w && !FILLER.has(w));
    if (!words.length) return null;
    const last = words.pop();
    const head = words.length ? words.join(" ") + " " : "";
    for (const form of [last, ...TOWN_ENDINGS.map(([re, to]) => last.replace(re, to))]) {
      const hit = state.obce.find((o) => o.f === head + form);
      if (hit) return hit;
    }
    return findObce(head + last)[0] || null;  // still typing: "vajcia brat"
  }

  function buildSuggest(q) {
    const fq = fold(q.trim()).replace(/\s+/g, " ");
    if (fq.length < 3) return [];
    const villages = findObce(q);
    const words = fq.split(" ").filter((w) => w.length >= 3);
    const isProductWord = (b, w) => w.length >= 3 && b.fw.some((x) => x.startsWith(w));
    const products = BUY.filter((b) => words.some((w) => isProductWord(b, w)));
    // a product and a town in one go: "vajcia bratislava", "syr pri pezinku"
    const combos = [];
    if (state.obce && products.length) {
      const b = products[0];
      const rest = fq.split(" ").filter((w) => !isProductWord(b, w)).join(" ");
      const v = rest.replace(/[^a-z]/g, "").length >= 3 ? findTown(rest) : null;
      if (v) combos.push({ kind: "combo", b, v });
    }
    const o = state.loc ? state.loc.c : map.getCenter().toArray();
    // places by their own name; "Trh Ružinov" style names would only repeat the towns above
    const places = state.all.filter((f) => !f.properties._generic && f.properties._f.includes(fq))
      .map((f) => ({ f, s: f.properties._f.startsWith(fq) ? 0 : 1, d: km(o, f.geometry.coordinates) }))
      .sort((a, b) => a.s - b.s || a.d - b.d).slice(0, 4);
    return [
      ...combos,
      ...villages.filter((v) => v.f === fq).map((v) => ({ kind: "obec", v })),
      ...products.map((b) => ({ kind: "buy", b })),
      ...villages.filter((v) => v.f !== fq).map((v) => ({ kind: "obec", v })),
      ...places.map(({ f }) => ({ kind: "place", f })),
    ].slice(0, 8);
  }

  const suggestItem = (i, icon, style, main, kind) => `<button type="button" class="suggest-item" data-i="${i}">
      <span class="${icon}"${style ? ` style="${style}"` : ""} aria-hidden="true"></span><span class="main">${main}</span><span class="go">${kind}</span></button>`;

  function renderSuggest() {
    const q = $("#q").value.trim();
    const html = state.suggest.map((x, i) => {
      if (x.kind === "obec") {
        const okres = x.v.okres && x.v.okres !== x.v.name ? `<span class="small">, okres ${esc(x.v.okres)}</span>` : "";
        return suggestItem(i, "pin", "", `<strong>${esc(x.v.name)}</strong>${okres}`, "obec");
      }
      if (x.kind === "buy") return suggestItem(i, "basket", "", `<strong>${x.b.label}</strong>`, "produkt");
      if (x.kind === "combo") return suggestItem(i, "basket", "", `<strong>${x.b.label}</strong> v okolí obce <strong>${esc(x.v.name)}</strong>`, "okolie");
      const p = x.f.properties;
      return suggestItem(i, "dot", `--c:${GROUP_COLOR[p.group] || "#17322a"}`,
        `<strong>${esc(p._n)}</strong>${p.obec && !p._generic ? `<span class="small">, ${esc(p.obec)}</span>` : ""}`, esc(labelOf(p)));
    }).join("") || (state.obce && fold(q).length >= 3 ? `<p class="suggest-none">Nenašli sme obec, produkt ani miesto „${esc(q)}“.</p>` : "");
    $("#suggest").innerHTML = html;
    $("#suggest").hidden = !html;
  }

  function showSuggestFor(q) {
    state.suggest = buildSuggest(q);
    renderSuggest();
    if (!state.obce) loadObce().then(() => { if ($("#q").value === q) { state.suggest = buildSuggest(q); renderSuggest(); } });
  }

  function hideSuggest() {
    state.suggest = [];
    $("#suggest").hidden = true;
  }

  function pick(x) {
    hideSuggest();
    if (x.kind === "obec" || x.kind === "combo") {
      if (x.kind === "combo") state.buy = x.b.id;  // setLoc below renders both
      $("#q").value = x.v.name;
      $("#q").blur();  // closes the keyboard on phones
      setLoc({ name: x.v.name, okres: x.v.okres, c: x.v.c });
      return;
    }
    // put the chosen place back and leave the box, so the next click selects it and typing replaces it
    $("#q").value = state.loc ? state.loc.name : "";
    $("#q").blur();
    if (x.kind === "buy") setBuy(x.b.id);
    else select(x.f.properties.id);
  }

  /* ---------- controls ---------- */
  $("#chips").innerHTML = [{ id: "all", label: "Všetko" }, ...BUY].map((b) =>
    `<button type="button" class="chip" data-buy="${b.id}" aria-pressed="${b.id === "all"}">${b.label} <span class="n"></span></button>`).join("");
  $("#legend").innerHTML = GROUPS.map((g) => `<li><span class="dot" style="--c:${g.color}" aria-hidden="true"></span>${g.label}</li>`).join("")
    + `<li><span class="dot bio" aria-hidden="true"></span>BIO</li>`;

  $("#chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (b && !b.disabled) setBuy(b.dataset.buy);
  });
  $("#hint").addEventListener("click", (e) => {
    const b = e.target.closest("[data-buy]");
    if (b) setBuy(b.dataset.buy);
  });
  $("#radius").addEventListener("change", (e) => setRadius(+e.target.value));
  $("#clearLoc").addEventListener("click", () => {
    $("#q").value = "";
    setLoc(null);
  });
  $("#bioOnly").addEventListener("change", (e) => { state.bioOnly = e.target.checked; if (state.selected) deselect(); render(); syncUrl(); });
  $("#shareSearch").addEventListener("click", shareSearch);

  const q = $("#q");
  q.addEventListener("focus", () => {
    loadObce();
    if (state.loc && q.value === state.loc.name) q.select();  // typing replaces the chosen place
    else if (q.value.trim()) showSuggestFor(q.value);
  });
  q.addEventListener("input", () => {
    if (!q.value.trim()) {  // emptied (or the × in the box): back to all of Slovakia
      hideSuggest();
      if (state.loc) setLoc(null);
      return;
    }
    showSuggestFor(q.value);
  });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (state.suggest[0]) pick(state.suggest[0]);
    } else if (e.key === "ArrowDown") {
      const first = $("#suggest .suggest-item");
      if (first) { e.preventDefault(); first.focus(); }
    } else if (e.key === "Escape") {
      e.preventDefault();  // a search box empties itself on Escape, which would also drop the chosen place
      hideSuggest();
      if (state.loc) q.value = state.loc.name;
    }
  });
  // leaving the box without choosing puts the chosen place's name back
  q.addEventListener("blur", () => setTimeout(() => {
    const a = document.activeElement;
    if (a === q || a?.closest?.("#suggest")) return;
    hideSuggest();
    if (state.loc && q.value !== state.loc.name) q.value = state.loc.name;
  }, 150));
  $("#suggest").addEventListener("click", (e) => {
    const b = e.target.closest(".suggest-item");
    if (b) pick(state.suggest[+b.dataset.i]);
  });
  $("#suggest").addEventListener("keydown", (e) => {
    const items = [...document.querySelectorAll("#suggest .suggest-item")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[Math.min(i + 1, items.length - 1)]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (i <= 0 ? q : items[i - 1]).focus(); }
    else if (e.key === "Escape") { hideSuggest(); q.focus(); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".where, #suggest")) hideSuggest(); });

  $("#locate").addEventListener("click", () => {
    const btn = $("#locate");
    const reset = (text) => { btn.textContent = text; setTimeout(() => (btn.textContent = "Moja poloha"), 3000); };
    if (!navigator.geolocation) { reset("Nedá sa zistiť"); return; }
    btn.textContent = "Zisťujem…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        btn.textContent = "Moja poloha";
        hideSuggest();
        q.value = "Vaša poloha";  // the box speaks to the visitor, like "do 25 km od vás"
        setLoc({ name: "Vaša poloha", c: [pos.coords.longitude, pos.coords.latitude], me: true });
        track("moja-poloha");  // only that the button was used, never where
      },
      () => reset("Poloha nedostupná"),
      { timeout: 10000, maximumAge: 300000 });
  });

  $("#list").addEventListener("click", (e) => {
    if (e.target.id === "more") {
      const first = state.shown;
      state.shown += PAGE;
      renderList();
      $("#list").querySelectorAll(".item")[first]?.focus();  // keep keyboard users where the new items start
      return;
    }
    const r = e.target.closest("[data-radius]");
    if (r) { setRadius(+r.dataset.radius); return; }
    const b = e.target.closest(".item");
    if (b) select(b.dataset.id);
  });
  $("#mailAdd").href = mailto("ALECO: pridať alebo opraviť miesto",
    "Dobrý deň,\n\nchcem pridať / opraviť / odstrániť miesto.\n\nNázov:\nObec:\nČo predávate a kedy:\nTelefón alebo web:\n");
  $("#mailText").textContent = `alebo na adresu ${CONTACT}`;
  $("#mailAbout").href = `mailto:${CONTACT}`;
  $("#mailAbout").textContent = CONTACT;
  $("#addBtn").addEventListener("click", () => $("#addDialog").showModal());
  $("#mailAdd").addEventListener("click", () => track("napisat-email"));
  // directions, calls, websites and error reports from a place card: the clearest sign the map was useful
  $("#detail").addEventListener("click", (e) => {
    const a = e.target.closest("[data-track]");
    if (a && state.selected) track(a.dataset.track, state.byId.get(state.selected)?.properties._n);
  });
  $("#aboutBtn").addEventListener("click", () => $("#aboutDialog").showModal());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.selected && !document.querySelector("dialog[open]")) deselect(); });

  /* ---------- load ---------- */
  // revalidate on every visit: the data changes with each rebuild, and a stale copy would hide fixes
  const dataReady = fetch("data/places.geojson", { cache: "no-cache" }).then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });
  // add our layers as soon as the style is parsed; "load" alone waits for every base-map tile, which can take long
  const mapReady = new Promise((res) => { map.once("style.load", res); map.once("load", res); });

  dataReady.then((d) => {
    for (const f of d.features) {
      const p = f.properties;
      p.group = catOf(p).group;
      // the BIO badge goes as soon as the certificate ends, even if the data has not been rebuilt since
      if (p.bio && p.cert_expires && p.cert_expires < TODAY) { p.bio = false; p.bioExpired = true; }
      const shown = displayName(p);
      p._n = shown.name;
      p._generic = shown.generic;
      p._f = fold(shown.name);
      p._r = rankOf(p);
      state.byId.set(p.id, f);
    }
    state.all = d.features;
    const m = d.metadata || {};
    if (m.generated) $("#generated").textContent = `Aktualizované ${fmtDate(m.generated)}.`;
    const bio = d.features.filter((f) => f.properties.bio).length;
    $("#stats").textContent = `${fmtNum(d.features.length)} miest, z toho ${fmtNum(bio)} s certifikátom BIO.`;
    // a shared search: ?kde=Pezinok&okres=Pezinok&km=10&co=syr&bio=1&miesto=<id>
    const co = START.get("co"), radius = START.get("km"), kde = START.get("kde"), id = START.get("miesto");
    if (kde || co || radius !== null || START.get("bio")) track("odkaz/hladanie");  // arrived through a shared search
    if (id) track("odkaz/miesto");
    if (BUY_BY_ID[co]) state.buy = co;
    if (START.get("bio") === "1") { state.bioOnly = true; $("#bioOnly").checked = true; }
    if (radius !== null && RADII.includes(+radius)) { state.radius = +radius; $("#radius").value = String(+radius); }
    render();
    const openPlace = () => { if (id && state.byId.has(id)) select(id, !linkHadMapView); };
    if (!kde) { openPlace(); return; }
    loadObce().then(() => {
      const okres = START.get("okres");
      const o = state.obce.find((x) => x.f === fold(kde) && (!okres || x.okres === okres));
      if (o) { q.value = o.name; setLoc({ name: o.name, okres: o.okres, c: o.c }); }
      openPlace();
    });
  }).catch(() => {
    $("#list").innerHTML = `<li class="empty">Údaje sa nepodarilo načítať. Skontrolujte pripojenie a obnovte stránku.</li>`;
  });
  Promise.all([dataReady, mapReady]).then(() => {
    addLayers();
    filter();
    drawArea();
    if (state.selected) map.getSource("sel").setData(fc([state.byId.get(state.selected)]));
  }).catch((e) => console.error("map setup failed:", e));
})();
