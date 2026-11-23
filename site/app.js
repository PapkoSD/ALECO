/* ALECO: open map of local food in Slovakia, in Slovak and English. No build step and no cookies; visits are counted
   anonymously with GoatCounter. */
(() => {
  "use strict";

  /* Colours belong to place groups, so the map stays readable with a dozen place types. The legend sits on the map. */
  const GROUPS = [
    { id: "farms",    color: "#2e6b45" },
    { id: "wine",     color: "#7a2343" },
    { id: "bakeries", color: "#b8862b" },
    { id: "vending",  color: "#2f6db5" },
    { id: "markets",  color: "#b24a2c" },
    { id: "shops",    color: "#3e8e86" },
  ];
  const CAT_GROUP = {
    farm: "farms", producer: "farms", honey: "farms", salas: "farms", winery: "wine", bakery: "bakeries",
    vending: "vending", market: "markets", organic_shop: "shops", dairy: "shops", deli: "shops", butcher: "shops",
    greengrocer: "shops",
  };
  const GROUP_COLOR = Object.fromEntries(GROUPS.map((g) => [g.id, g.color]));
  const SK_BOUNDS = [[16.83, 47.73], [22.57, 49.62]];
  const PAGE = 40;
  const RADII = [10, 25, 50, 0];  // km around the chosen place, as in the select; 0 = all of Slovakia, nearest first
  const CERT_PDF = (ref) => `https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/${encodeURIComponent(ref)}.pdf`;
  // who runs the site and where people ask to add, fix or remove a place; the address is put together here rather
  // than written into the page, so simple address harvesters miss it
  const OPERATOR = "Patrik Mihal";
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
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  /* ---------- language: Slovak for Slovak and Czech browsers, English for everyone else; "SK | EN" switches ---------- */
  const START = new URL(location.href).searchParams;  // what the visitor arrived with, read before it is rewritten
  const LANG = (() => {
    const asked = START.get("lang");
    if (asked === "sk" || asked === "en") return asked;
    try { const saved = localStorage.getItem("aleco-lang"); if (saved === "sk" || saved === "en") return saved; } catch { /* storage blocked */ }
    const prefs = (navigator.languages || [navigator.language || ""]).map((l) => String(l).slice(0, 2).toLowerCase());
    return !prefs[0] || prefs.some((l) => l === "sk" || l === "cs") ? "sk" : "en";
  })();
  const EN = LANG === "en";
  const plural = (n, one, few, many) => (n === 1 ? one : n > 1 && n < 5 ? few : many);
  const fmtNum = (n) => n.toLocaleString(EN ? "en-GB" : "sk-SK");
  const fmtKm = (d) => (d < 10 ? (EN ? d.toFixed(1) : d.toFixed(1).replace(".", ",")) : Math.round(d)) + " km";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (iso) => { const [y, m, d] = iso.slice(0, 10).split("-"); return EN ? `${+d} ${MONTHS[+m - 1]} ${y}` : `${+d}. ${+m}. ${y}`; };
  const DAYS_SK = { Mo: "Po", Tu: "Ut", We: "St", Th: "Št", Fr: "Pi", Sa: "So", Su: "Ne", PH: "sviatky", off: "zatvorené" };
  const DAYS_EN = { PH: "public holidays", off: "closed" };
  const fmtHours = (h) => h.replace(/\b(Mo|Tu|We|Th|Fr|Sa|Su|PH|off)\b/g, (m) => (EN ? DAYS_EN[m] || m : DAYS_SK[m])).replace(/;\s*/g, "\n");
  const KRAJ_EN = { "Bratislavský": "Bratislava", "Trnavský": "Trnava", "Trenčiansky": "Trenčín", "Nitriansky": "Nitra",
    "Žilinský": "Žilina", "Banskobystrický": "Banská Bystrica", "Prešovský": "Prešov", "Košický": "Košice" };
  // type labels that come with the data (from the build), in English
  const LABELS_EN = {
    "Farmársky obchod": "Farm shop", "Mliečny automat": "Milk vending machine", "Mliečna farma": "Dairy farm",
    "Zdravá výživa": "Health food shop", "Syry a mliečne výrobky": "Cheese and dairy", "Samozber": "Pick your own",
    "Mäso a údeniny": "Meat and smoked meats", "Automat na mliečne výrobky": "Dairy vending machine",
    "Automat na med": "Honey vending machine", "Automat na mäso": "Meat vending machine", "Rybárstvo": "Fish farm",
    "Automat na vajcia": "Egg vending machine", "Olejáreň": "Oil mill", "Automat na ovocie a zeleninu": "Fruit and veg vending machine",
    "Automat na mlieko a vajcia": "Milk and egg vending machine", "Automat na zemiaky": "Potato vending machine",
    "Automat na pečivo": "Bread vending machine", "Automat na potraviny": "Food vending machine", "Syráreň": "Cheese dairy",
    "Muštáreň": "Juice and cider press",
  };

  const STR = {
    sk: {
      title: "ALECO: lokálne jedlo na Slovensku",
      groups: { farms: "Farmy", wine: "Vinárstva", bakeries: "Pekárne", vending: "Automaty", markets: "Trhy", shops: "Obchody" },
      cats: { farm: "Farma", producer: "Výrobca potravín", honey: "Včelár", salas: "Salaš", winery: "Vinárstvo", bakery: "Pekáreň",
        vending: "Mliečny automat", market: "Trh", organic_shop: "Bio obchod", dairy: "Mliečne výrobky a syry", deli: "Lahôdky",
        butcher: "Mäsiarstvo", greengrocer: "Ovocie a zelenina" },
      buy: { mlieko: ["Mlieko", "s mliekom"], syr: ["Syry", "so syrmi"], vajcia: ["Vajcia", "s vajciami"], maso: ["Mäso", "s mäsom"],
        med: ["Med", "s medom"], ovocie: ["Ovocie", "s ovocím"], zelenina: ["Zelenina", "so zeleninou"], pecivo: ["Pečivo", "s pečivom"],
        vino: ["Víno", "s vínom"] },
      all: "Všetko", bioLegend: "BIO",
      places: (n) => plural(n, "miesto", "miesta", "miest"),
      from: (loc) => (loc.me ? "vás" : loc.addr ? `miesta „${esc(loc.name)}“` : `obce ${esc(loc.name)}`),
      to: (loc) => (loc.me ? "vám" : loc.addr ? `miestu „${esc(loc.name)}“` : `obci ${esc(loc.name)}`),
      within: (r, loc) => ` do ${r} km od ${STR.sk.from(loc)}`,
      nearest: (loc) => `, najbližšie k ${STR.sk.to(loc)}`,
      overview: " na celom Slovensku, najprv overené a tie, kde poznáme kontakt",
      mapCentre: ", najbližšie k stredu mapy",
      hint: (n, N, more, near) => (n === 1
        ? `Pri jednom${more ? " ďalšom" : ""} mieste${near ? " v okolí" : ""} nevieme, čo presne predáva. Nájdete ho pod`
        : `Pri${more ? " ďalších" : ""} ${N} miestach${near ? " v okolí" : ""} nevieme, čo presne predávajú, napríklad pri trhoch. Nájdete ich pod`),
      nothingNear: (r, loc, what) => `Do ${r} km od ${STR.sk.from(loc)} sme nenašli nič${what}.`,
      searchWithin: (r) => `Hľadať do ${r} km`, searchAll: "Hľadať na celom Slovensku",
      nothing: "Takému výberu nič nezodpovedá. Skúste iný produkt alebo vypnite filter BIO.",
      laterHead: "Pekárne a trhy",
      bioTitle: "Certifikovaná ekologická výroba", verified: "overené", verifiedTitle: "Overili sme, že predávajú priamo",
      more: (a, b) => `Zobraziť ďalšie (${a} z ${b})`,
      stampRing: "EKOLOGICKÁ VÝROBA · REGISTER EÚ ·", stampAria: (c) => `Certifikát ekologickej výroby ${c} v registri EÚ`,
      approxVillage: "poloha na mape je stred obce, nie presná adresa", approxPostcode: "poloha na mape je len približná (podľa PSČ)",
      region: (k) => `${k} kraj`, okres: (o) => `okres ${o}`,
      fWhere: "Kde", fDistance: "Vzdialenosť", fSales: "Predaj", fCert: "Certifikát BIO", fCertProducts: "Certifikované produkty",
      fOldCertProducts: "Produkty podľa certifikátu", fOffer: "Ponuka", fPremises: "Prevádzky", fHours: "Otvorené", fPhone: "Telefón", fWeb: "Web",
      distance: (d, loc) => `${d} od ${STR.sk.from(loc)}`,
      checkedOn: (date) => `Overené ${date} na ich stránke`,
      certExpired: (link, date) => `${link} platil do ${date}. Novší sme zatiaľ nenačítali.`,
      noContactOsm: "Kontakt ani otváracie hodiny zatiaľ nepoznáme.", noContact: "Kontakt zatiaľ nepoznáme.",
      certNoSale: "Z certifikátu nevieme, či predávajú aj priamo, preto si to pred návštevou overte.",
      webDead: "Ich webová stránka už nefunguje, miesto mohlo zaniknúť. Pred cestou si to overte.",
      stale: (y) => `Údaje v OpenStreetMap sú naposledy upravené v roku ${y}, pred cestou si overte, či miesto ešte funguje.`,
      source: "Zdroj", and: "a", register: "EÚ register ekologických certifikátov", registerTraces: "EÚ register ekologických certifikátov (TRACES)",
      editOsm: "Mapujete v OpenStreetMap?", editOsmLink: "Upravte miesto tam",
      produce: "Vyrábajú", canBuy: "Kúpite tu",
      reportBody: (name, obec, link) => `Dobrý deň,\n\nmiesto: ${name}${obec ? `, ${obec}` : ""}\n${link}\n\nČo treba opraviť alebo odstrániť:\n`,
      back: "Späť na zoznam", navigate: "Navigovať", call: "Zavolať", share: "Zdieľať", report: "Nahlásiť chybu",
      certificate: (link, until) => `Certifikát ${link}${until ? `<br>platí do ${until}` : ""}`,
      copied: "Odkaz skopírovaný", copyFailed: "Odkaz sa nepodarilo skopírovať", shareSearch: "Zdieľať výber",
      town: "obec", product: "produkt", nearby: "okolie", address: "adresa", addrSearching: "Hľadám adresy…",
      combo: (label, name) => `<strong>${label}</strong> v okolí obce <strong>${name}</strong>`,
      okresSmall: (o) => `, okres ${o}`,
      noneFound: (q) => `Nenašli sme obec, produkt ani miesto „${q}“.`,
      myLocation: "Moja poloha", locating: "Zisťujem…", noGeo: "Nedá sa zistiť", geoFailed: "Poloha nedostupná", yourLocation: "Vaša poloha",
      mailAddSubject: "ALECO: pridať alebo opraviť miesto",
      mailAddBody: "Dobrý deň,\n\nchcem pridať / opraviť / odstrániť miesto.\n\nNázov:\nObec:\nČo predávate a kedy:\nTelefón alebo web:\n",
      mailOr: (c) => `alebo na adresu ${c}`,
      updated: (date) => `Aktualizované ${date}.`,
      stats: (n, b) => `${n} miest, z toho ${b} s certifikátom BIO.`,
      loadFailed: "Údaje sa nepodarilo načítať. Skontrolujte pripojenie a obnovte stránku.",
    },
    en: {
      title: "ALECO: local food in Slovakia",
      groups: { farms: "Farms", wine: "Wineries", bakeries: "Bakeries", vending: "Vending machines", markets: "Markets", shops: "Shops" },
      cats: { farm: "Farm", producer: "Food producer", honey: "Beekeeper", salas: "Salaš (sheep farm)", winery: "Winery", bakery: "Bakery",
        vending: "Milk vending machine", market: "Market", organic_shop: "Organic shop", dairy: "Cheese and dairy shop", deli: "Deli",
        butcher: "Butcher", greengrocer: "Greengrocer" },
      buy: { mlieko: ["Milk", "selling milk"], syr: ["Cheese", "selling cheese"], vajcia: ["Eggs", "selling eggs"], maso: ["Meat", "selling meat"],
        med: ["Honey", "selling honey"], ovocie: ["Fruit", "selling fruit"], zelenina: ["Vegetables", "selling vegetables"],
        pecivo: ["Bread", "selling bread"], vino: ["Wine", "selling wine"] },
      all: "All", bioLegend: "Organic",
      places: (n) => (n === 1 ? "place" : "places"),
      from: (loc) => (loc.me ? "you" : esc(loc.name)),
      to: (loc) => (loc.me ? "you" : esc(loc.name)),
      within: (r, loc) => ` within ${r} km of ${STR.en.from(loc)}`,
      nearest: (loc) => `, nearest to ${STR.en.to(loc)}`,
      overview: " in all of Slovakia, verified places and those with contact details first",
      mapCentre: ", nearest to the map centre",
      hint: (n, N, more, near) => (n === 1
        ? `For one${more ? " more" : ""} place${near ? " nearby" : ""} we don't know exactly what it sells. You'll find it under`
        : `For ${N}${more ? " more" : ""} places${near ? " nearby" : ""} we don't know exactly what they sell, for example markets. You'll find them under`),
      nothingNear: (r, loc, what) => `No places${what} within ${r} km of ${STR.en.from(loc)}.`,
      searchWithin: (r) => `Search within ${r} km`, searchAll: "Search all of Slovakia",
      nothing: "Nothing matches. Try another product or turn off the organic filter.",
      laterHead: "Bakeries and markets",
      bioTitle: "Certified organic", verified: "verified", verifiedTitle: "We checked that they sell directly",
      more: (a, b) => `Show more (${a} of ${b})`,
      stampRing: "CERTIFIED ORGANIC · EU REGISTER ·", stampAria: (c) => `Organic certificate ${c} in the EU register`,
      approxVillage: "the pin is the village centre, not the exact address", approxPostcode: "the pin is only approximate (by postcode)",
      region: (k) => `${KRAJ_EN[k] || k} region`, okres: (o) => `${o} district`,
      fWhere: "Where", fDistance: "Distance", fSales: "How they sell", fCert: "Organic certificate", fCertProducts: "Certified products",
      fOldCertProducts: "Products on the certificate", fOffer: "Offer", fPremises: "Premises", fHours: "Opening hours", fPhone: "Phone", fWeb: "Website",
      distance: (d, loc) => `${d} from ${STR.en.from(loc)}`,
      checkedOn: (date) => `Checked ${date} on their website`,
      certExpired: (link, date) => `${link} was valid until ${date}. We haven't loaded a newer one yet.`,
      noContactOsm: "We don't know their contact details or opening hours yet.", noContact: "We don't know their contact details yet.",
      certNoSale: "The certificate doesn't say whether they also sell directly, so check before you go.",
      webDead: "Their website no longer works, so the place may have closed. Check before you go.",
      stale: (y) => `The OpenStreetMap data was last edited in ${y}; check that the place is still open before you go.`,
      source: "Source", and: "and", register: "the EU register of organic certificates", registerTraces: "EU register of organic certificates (TRACES)",
      editOsm: "Do you map in OpenStreetMap?", editOsmLink: "Edit the place there",
      produce: "They produce", canBuy: "You can buy",
      reportBody: (name, obec, link) => `Hello,\n\nplace: ${name}${obec ? `, ${obec}` : ""}\n${link}\n\nWhat should be fixed or removed:\n`,
      back: "Back to the list", navigate: "Directions", call: "Call", share: "Share", report: "Report a problem",
      certificate: (link, until) => `Certificate ${link}${until ? `<br>valid until ${until}` : ""}`,
      copied: "Link copied", copyFailed: "Couldn't copy the link", shareSearch: "Share this search",
      town: "town", product: "product", nearby: "nearby", address: "address", addrSearching: "Looking up addresses…",
      combo: (label, name) => `<strong>${label}</strong> around <strong>${name}</strong>`,
      okresSmall: (o) => `, ${o} district`,
      noneFound: (q) => `No town, product or place called “${q}”.`,
      myLocation: "My location", locating: "Locating…", noGeo: "Not available", geoFailed: "Location unavailable", yourLocation: "Your location",
      mailAddSubject: "ALECO: add or fix a place",
      mailAddBody: "Hello,\n\nI'd like to add / fix / remove a place.\n\nName:\nVillage or town:\nWhat is sold and when:\nPhone or website:\n",
      mailOr: (c) => `or write to ${c}`,
      updated: (date) => `Updated ${date}.`,
      stats: (n, b) => `${n} places, ${b} of them certified organic.`,
      loadFailed: "Couldn't load the data. Check your connection and reload the page.",
      // the page's own texts (Slovak is written in index.html)
      page: {
        panel: "List of places",
        tagline: "Farms and local food in Slovakia",
        lede: "Farms, salaše (sheep farms), bakeries, milk vending machines and markets all over Slovakia. Buy straight from the people who make the food.",
        where: "Where are you looking?", placeholder: "Village, town, address or place name", myLocation: "My location", howFar: "How far",
        r10: "within 10 km", r25: "within 25 km", r50: "within 50 km", r0: "all of Slovakia", clearLoc: "Clear place",
        what: "What do you want to buy?", bioOnly: "Certified organic only", shareSearch: "Share this search",
        addBtn: "Missing a place, or something wrong?", aboutBtn: "Where the data comes from", privacyBtn: "Privacy and terms",
        footSmall: `An open project with no ads, no commission and no cookies. Data: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> (ODbL), the <a href="https://webgate.ec.europa.eu/tracesnt/directory/publication/organic-operator/index">EU register of organic certificates</a> and <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0).`,
        map: "Map", legend: "Colours of the points on the map",
        addTitle: "Add, fix or remove a place",
        add1: "Do you sell food you make yourself, or is a place you know missing? Send us its name, village or town, what is sold and when. We'll check it and add it to the map.",
        add2: "If something about a place is wrong, or you're on the map and don't want to be, write to us. We'll fix it or remove the data.",
        mailAdd: "Write an e-mail",
        add3: "Do you map in OpenStreetMap? You can add the place there too; it will appear on ALECO with the next update.",
        close: "Close",
        aboutTitle: "Where the data comes from",
        about1: "<strong>Shops, markets, vending machines, bakeries and wineries</strong> come from OpenStreetMap, the open map anyone can edit. We leave out chains and supermarkets.",
        about2: "<strong>The BIO stamp</strong> means a valid organic certificate in the European Commission's register (TRACES). Products are listed from the certificate. We only show producers whose certificate lists food for people, such as honey, cheese, fruit or vegetables; farms that only grow grain or feed for processors are not on the map. A certificate doesn't say whether the producer also sells directly, so check before you go.",
        about3: "<strong>The location</strong> of certified producers is the address on the certificate: the premises if listed, otherwise the registered office. If the office is in a big city, we leave the producer off the map until we know where they actually farm.",
        about4: "Individual farmers (sole traders) from the certificate register are only published with their consent.",
        about5: `The data is open (ODbL): you can reuse it freely with attribution, as a <a href="data/places.csv" download>CSV table</a> or <a href="data/places.geojson" download>GeoJSON</a>.`,
        privacyTitle: "Privacy and terms", opLabel: "Operator:", opNote: "ALECO is a non-commercial project.",
        priv1: "<strong>Data about places.</strong> We publish the name, location, address, contact details, opening hours and offer of places that sell food straight from the producer. It comes from public sources: OpenStreetMap, the EU register of organic certificates and the sellers' own websites. Where a place is run by an individual, this is personal data. We process it on the basis of a legitimate interest in informing the public about direct food sales (Art. 6(1)(f) GDPR), and only to the extent the seller has published it. Individual farmers (sole traders) from the certificate register are only published with their consent.",
        priv2: `<strong>Your rights.</strong> You can ask for access to the data, for it to be corrected or erased, and object to its publication: just write to the e-mail above. We will correct or remove the data from the map and the open data without undue delay. You can also complain to the <a href="https://dataprotection.gov.sk/" target="_blank" rel="noopener">Slovak Data Protection Authority</a>.`,
        priv3: `<strong>Visitors.</strong> The site uses no cookies. Visits and what people do on the site (which towns and products they look for, which places they open, clicks on Navigate, Call, Website and Share) are counted anonymously with <a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a>, which does not store IP addresses. If you switch the language, your browser remembers the choice (localStorage); it is not sent anywhere. If you type an address or a place that isn't a town, the text is sent to the <a href="https://photon.komoot.io/" target="_blank" rel="noopener">Photon</a> service (komoot, Germany), which looks it up in OpenStreetMap. The site is hosted by GitHub Pages (<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" target="_blank" rel="noopener">GitHub, USA</a>) and the base map comes from OpenFreeMap; these services technically process your IP address when the page loads. Your location, if you allow it, is only used in your browser to sort the list, and never goes into links.`,
        priv4: "<strong>Disclaimer.</strong> The data comes from public sources and may be incomplete or out of date. Check opening hours and what's on offer with the seller before you go. The BIO stamp means the producer holds a valid certificate in the EU register; ALECO does not certify anything.",
        priv5: `<strong>Licences.</strong> Code: AGPL-3.0, <a href="https://github.com/PapkoSD/ALECO" target="_blank" rel="noopener">GitHub</a>. Data: ODbL (© OpenStreetMap contributors), the European Commission's register of organic certificates, GeoNames (CC BY 4.0).`,
      },
    },
  };
  const T = STR[LANG];

  // the page is written in Slovak; English replaces its texts before anything else reads them (the title too)
  if (EN) {
    document.documentElement.lang = "en";
    document.title = T.title;
    for (const el of document.querySelectorAll("[data-t]")) if (T.page[el.dataset.t] !== undefined) el.textContent = T.page[el.dataset.t];
    for (const el of document.querySelectorAll("[data-t-html]")) if (T.page[el.dataset.tHtml] !== undefined) el.innerHTML = T.page[el.dataset.tHtml];
    for (const el of document.querySelectorAll("[data-t-placeholder]")) el.placeholder = T.page[el.dataset.tPlaceholder];
    for (const el of document.querySelectorAll("[data-t-aria]")) el.setAttribute("aria-label", T.page[el.dataset.tAria]);
  }
  for (const b of document.querySelectorAll(".lang [data-lang]")) {
    b.setAttribute("aria-pressed", b.dataset.lang === LANG);
    b.addEventListener("click", () => {
      if (b.dataset.lang === LANG) return;
      try { localStorage.setItem("aleco-lang", b.dataset.lang); } catch { /* the link below carries the choice anyway */ }
      track(`jazyk/${b.dataset.lang}`);
      const url = new URL(location.href);  // same search and map view, other language
      url.searchParams.set("lang", b.dataset.lang);
      location.href = url.href;
    });
  }

  const catOf = (p) => ({ label: T.cats[p.category] || p.category, group: CAT_GROUP[p.category] || "shops" });
  const labelOf = (p) => (p.label ? (EN ? LABELS_EN[p.label] || p.label : p.label) : catOf(p).label);
  const labelSk = (p) => p.label || STR.sk.cats[p.category] || p.category;  // for spotting generic names, whatever the language
  // "Šamorín, okres Dunajská Streda"; no okres when it only repeats the town ("Bratislava-Petržalka", "Nitra")
  const sameTown = (obec, okres) => obec === okres || (/^(Bratislava|Košice) [IV]+$/.test(okres) && obec.startsWith(okres.split(" ")[0]));
  const okresOf = (p) => (p.okres && p.obec && !sameTown(p.obec, p.okres) ? T.okres(p.okres) : "");
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
    const generic = junk || GENERIC.has(fold(n)) || fold(n) === fold(labelSk(p));
    return { name: generic && p.obec ? `${n} ${p.obec}` : n, generic };
  }

  /* Zoomed out to all of Slovakia, "nearest to the map centre" means nothing: checked places and places with contacts go first */
  const OVERVIEW_ZOOM = 7.5;
  const GROUP_RANK = { farms: 0, vending: 1, shops: 2, wine: 3, markets: 4, bakeries: 5 };
  const rankOf = (p) => (p.checked ? 0 : (p.phone || p.website) && p.hours ? 1 : p.phone || p.website || p.hours ? 2 : 3) * 10
    + (GROUP_RANK[p.group] ?? 6);

  /* What you can buy. The ids match BUY in scripts/build_seed.py, which tags every place with them ("buy");
     `words` (Slovak and English) let people type a product into the search box: "bryndza" or "cheese" offers Syry. */
  const BUY = [
    { id: "mlieko",   words: "mlieko mlieka mliečne mliekomat jogurt tvaroh maslo kefír smotana milk dairy yogurt butter cream" },
    { id: "syr",      words: "syr syry syra syrov bryndza bryndze oštiepok parenica korbáčiky žinčica cheese cheeses" },
    { id: "vajcia",   words: "vajcia vajec vajíčka vajíčok vajce eggs egg" },
    { id: "maso",     words: "mäso mäsa údeniny klobása klobásy slanina šunka ryby rýb pstruh hovädzie bravčové jahňacie meat sausages bacon ham fish trout beef pork lamb" },
    { id: "med",      words: "med medu medovina propolis honey mead" },
    { id: "ovocie",   words: "ovocie ovocia jablká jabĺk hrušky slivky marhule čerešne jahody maliny ríbezle čučoriedky orechy samozber fruit apples pears plums apricots cherries strawberries raspberries berries nuts" },
    { id: "zelenina", words: "zelenina zeleniny zemiaky zemiakov mrkva cibuľa cesnak kapusta paradajky paprika uhorky špargľa huby vegetables veg potatoes carrots onions garlic tomatoes peppers asparagus mushrooms" },
    { id: "pecivo",   words: "pečivo pečiva chlieb chleba rožky koláče pekáreň kváskový bread bakery pastry" },
    { id: "vino",     words: "víno vína vínom vinárstvo vinár wine winery" },
  ].map((b) => ({ ...b, label: T.buy[b.id][0], with: T.buy[b.id][1], fw: fold(b.words).split(" ") }));
  // around towns the many bakeries and plain markets ("Trh Brezno") would fill the first page: they come after the rest
  const laterTier = (p) => p.group === "bakeries" || (p.group === "markets" && p._generic);
  const BUY_BY_ID = Object.fromEntries(BUY.map((b) => [b.id, b]));

  const state = {
    all: [], byId: new Map(), buy: "all", bioOnly: false,
    loc: null,                     // the chosen place: { name, okres, c: [lon, lat], me: true for "Moja poloha" }
    radius: 25, dist: new Map(),   // km from loc to every place, by id
    shown: PAGE, selected: null, matches: [], counts: {}, unknown: 0,
    obce: null, suggest: [], addrPending: false,
  };

  /* ---------- map ---------- */
  // the map view sits in the address bar (#mapa=zoom/lat/lon), so a reload or a copied link keeps it; not while the
  // map is centred on the visitor's own position or a typed address, which never go into a link
  const hashView = location.hash.match(/mapa=([\d.]+)\/(-?[\d.]+)\/(-?[\d.]+)/);
  const linkHadMapView = !!hashView;
  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/positron",
    ...(hashView ? { zoom: +hashView[1], center: [+hashView[3], +hashView[2]] }
      : { bounds: SK_BOUNDS, fitBoundsOptions: { padding: 16 } }),
    attributionControl: { compact: true },
    dragRotate: false,
    pitchWithRotate: false,
  });
  map.touchZoomRotate.disableRotation();
  map.on("moveend", () => {
    const url = new URL(location.href);
    const c = map.getCenter();
    url.hash = state.loc && (state.loc.me || state.loc.addr) ? ""
      : `mapa=${map.getZoom().toFixed(2)}/${c.lat.toFixed(4)}/${c.lng.toFixed(4)}`;
    history.replaceState(history.state, "", url);
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  const colorExpr = ["match", ["get", "group"], ...Object.entries(GROUP_COLOR).flat(), "#17322a"];

  function localLabels() {
    // base map labels in the page's language where OSM has them ("Maďarsko" / "Hungary"), otherwise the local name
    for (const l of map.getStyle().layers) {
      const tf = l.type === "symbol" && l.layout && l.layout["text-field"];
      if (tf && /name/.test(JSON.stringify(tf))) {
        map.setLayoutProperty(l.id, "text-field", ["coalesce", ["get", EN ? "name:en" : "name:sk"], ["get", "name"]]);
      }
    }
  }

  function addLayers() {
    localLabels();
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
    // "more" only when the list shows some places already
    $("#hint").innerHTML = !n ? "" : T.hint(n, fmtNum(n), state.matches.length > 0, !!(state.loc && state.radius))
      + ` <button type="button" class="link-btn" data-buy="all">${T.all}</button>.`;
    $("#hint").hidden = !n || !!state.selected;
  }

  function emptyMessage(what) {
    if (state.loc && state.radius) {
      const next = RADII[RADII.indexOf(state.radius) + 1];
      return `<li class="empty">${T.nothingNear(state.radius, state.loc, what)}
        <button type="button" class="link-btn" data-radius="${next}">${next ? T.searchWithin(next) : T.searchAll}</button></li>`;
    }
    return `<li class="empty">${T.nothing}</li>`;
  }

  function renderList() {
    const rows = state.matches;
    const n = rows.length;
    const loc = state.loc;
    const overview = !loc && map.getZoom() < OVERVIEW_ZOOM;
    const what = state.buy === "all" ? "" : ` ${BUY_BY_ID[state.buy].with}`;
    const where = loc ? (state.radius ? T.within(state.radius, loc) : T.nearest(loc)) : overview ? T.overview : T.mapCentre;
    $("#count").innerHTML = n ? `<strong>${fmtNum(n)}</strong> ${T.places(n)}${what}${where}` : "";
    $("#shareSearch").hidden = !n || !((state.loc && !state.loc.me && !state.loc.addr) || state.buy !== "all" || state.bioOnly);
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
      const head = tiered && r === 1 && !headed && (headed = true) && i > 0 ? `<li class="group-head">${T.laterHead}</li>` : "";
      return `${head}<li><button class="item" data-id="${esc(p.id)}" style="--c:${GROUP_COLOR[p.group] || "#17322a"}">
        <span class="dot" aria-hidden="true"></span>
        <span class="name">${esc(p._n)}${p.bio ? `<span class="bio-mini" title="${T.bioTitle}">BIO</span>` : ""}${p.checked ? `<span class="ok-mini" title="${T.verifiedTitle}">${T.verified}</span>` : ""}</span>
        ${loc ? `<span class="km">${fmtKm(d)}</span>` : "<span></span>"}
        <span class="meta">${esc([label, where].filter(Boolean).join(", "))}</span>
      </button></li>`;
    }).join("") + (n > state.shown
      ? `<li class="more"><button type="button" class="btn ghost" id="more">${T.more(fmtNum(Math.min(PAGE, n - state.shown)), fmtNum(n - state.shown))}</button></li>`
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
  // our own sign for "holds a certificate in the EU register"; deliberately not the EU organic logo, which only
  // certified products may carry
  function stampSvg(p) {
    return `<svg class="stamp" viewBox="0 0 120 120" role="img" aria-label="${esc(T.stampAria(p.cert))}">
      <defs><path id="ring" d="M60,60 m-44,0 a44,44 0 1,1 88,0 a44,44 0 1,1 -88,0"/></defs>
      <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="3"/>
      <circle cx="60" cy="60" r="33" fill="none" stroke="currentColor" stroke-width="1.5"/>
      <text font-size="10.5" font-weight="700"><textPath href="#ring" startOffset="0" textLength="268" lengthAdjust="spacing">${T.stampRing}</textPath></text>
      <text class="big" x="60" y="72" text-anchor="middle">BIO</text>
    </svg>`;
  }

  function showDetail(f) {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    const web = safeUrl(p.website);
    const approx = p.precision === "village" ? T.approxVillage : p.precision === "postcode" ? T.approxPostcode : "";
    const area = p.address && p.obec && fold(p.address).includes(fold(p.obec))
      ? (p.okres && !sameTown(p.obec, p.okres) ? T.okres(p.okres) : "") : place(p);
    const where = [p.address, area].filter(Boolean).join(", ");
    const tel = p.phone ? p.phone.replace(/[^\d+]/g, "") : "";
    const certLink = p.cert ? `<a href="${CERT_PDF(p.cert)}" target="_blank" rel="noopener">${esc(p.cert)}</a>` : "";
    const facts = [
      where && [T.fWhere, esc(where) + (p.kraj ? `<br><span class="small">${esc(T.region(p.kraj))}</span>` : "") + (approx ? `<br><span class="small">${approx}</span>` : "")],
      state.loc && [T.fDistance, T.distance(fmtKm(state.dist.get(p.id) ?? km(state.loc.c, f.geometry.coordinates)), state.loc)],
      p.how && [T.fSales, esc(p.how) + `<br><span class="small">${T.checkedOn(fmtDate(p.checked))}</span>`],
      p.bioExpired && [T.fCert, T.certExpired(certLink, fmtDate(p.cert_expires))],
      p.products && [p.bio ? T.fCertProducts : p.bioExpired ? T.fOldCertProducts : T.fOffer, esc(p.products)],
      p.premises && [T.fPremises, esc(p.premises).replace(/; /g, "<br>")],
      p.hours && [T.fHours, esc(fmtHours(p.hours)).replace(/\n/g, "<br>")],
      tel && [T.fPhone, `<a href="tel:${esc(tel)}" data-track="zavolat">${esc(p.phone)}</a>`],
      web && [T.fWeb, `<a href="${esc(web)}" target="_blank" rel="noopener" data-track="web">${esc(web.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))}</a>`],
    ].filter(Boolean);
    const edited = p.osm_edited ? +p.osm_edited.slice(0, 4) : 0;
    const stale = edited && edited <= new Date().getFullYear() - 5;
    const noContact = !p.phone && !web && !p.hours;
    const note = [
      noContact && (p.source === "osm" ? T.noContactOsm : T.noContact),
      p.cert && !p.checked && p.source !== "osm" && T.certNoSale,
      p.web_dead && T.webDead,
      stale && T.stale(edited),
    ].filter(Boolean).join(" ");
    const osm = p.id.startsWith("osm-") ? p.id.slice(4) : "";
    const osmType = { n: "node", w: "way", r: "relation" }[osm[0]];
    const osmUrl = osm ? `https://www.openstreetmap.org/${osmType}/${osm.slice(1)}` : "";
    const editUrl = osm ? `https://www.openstreetmap.org/edit?${osmType}=${osm.slice(1)}` : "";
    const source = p.source === "osm"
      ? `<a href="${osmUrl}" target="_blank" rel="noopener">OpenStreetMap</a>${p.cert ? ` ${T.and} <a href="${CERT_PDF(p.cert)}" target="_blank" rel="noopener">${T.register}</a>` : ""}`
      : `<a href="${CERT_PDF(p.cert)}" target="_blank" rel="noopener">${T.registerTraces}</a>`;

    // what the place is listed under in "Čo chcete kúpiť?"; a certificate only says what they make, not that they sell it
    const buys = (p.buy || []).map((k) => BUY_BY_ID[k]?.label).filter(Boolean);
    const buyLine = buys.length ? `<p class="buys">${p.cert && !p.checked && p.source !== "osm" ? T.produce : T.canBuy}: `
      + buys.map((l) => `<span class="tag">${l}</span>`).join(" ") + "</p>" : "";
    // "Nahlásiť chybu": an e-mail with the place filled in, which anyone can send (the OSM editor needs an account)
    const link = `${location.origin}${location.pathname}?miesto=${encodeURIComponent(p.id)}`;
    const report = mailto(`ALECO: ${p._n}`, T.reportBody(p._n, p.obec, link));
    // "Navigovať": places from OpenStreetMap were mapped where they are, so Google gets that point. Certified producers
    // are placed from their certificate address, often only at the village centre, so Google gets the address itself
    // ("Páleničné 815/20, 976 52 Čierny Balog") and finds the house.
    const navTo = p.source !== "osm" && p.address
      ? [p.address, [p.postcode, p.city || p.obec].filter(Boolean).join(" "), "Slovensko"].filter(Boolean).join(", ")
      : `${lat},${lon}`;
    const navUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(navTo)}`;

    // the buttons come right after the name, so on a phone "Navigovať" is visible without scrolling
    $("#detail").innerHTML = `
      <p class="back"><button type="button" class="link-btn" id="back">${T.back}</button></p>
      <h2>${esc(p._n)}</h2>
      <p class="kind" style="--c:${GROUP_COLOR[p.group] || "#17322a"}"><span class="dot" aria-hidden="true"></span>${esc(labelOf(p))}</p>
      ${buyLine}
      <div class="actions">
        <a class="btn" href="${esc(navUrl)}" target="_blank" rel="noopener" data-track="navigovat">${T.navigate}</a>
        ${tel ? `<a class="btn ghost" href="tel:${esc(tel)}" data-track="zavolat">${T.call}</a>` : ""}
        <button type="button" class="btn ghost" id="share">${T.share}</button>
        <a class="btn ghost" href="${esc(report)}" data-track="nahlasit-chybu">${T.report}</a>
      </div>
      ${p.bio ? `<div class="stamp-wrap">${stampSvg(p)}
        <p>${T.certificate(certLink, p.cert_expires ? fmtDate(p.cert_expires) : "")}</p></div>` : ""}
      <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      ${note ? `<p class="note">${note}</p>` : ""}
      <p class="source">${T.source}: ${source}${editUrl ? `. ${T.editOsm} <a href="${editUrl}" target="_blank" rel="noopener">${T.editOsmLink}</a>` : ""}</p>`;
    $("#back").addEventListener("click", deselect);
    $("#share").addEventListener("click", () => share(p));
  }

  // the phone's share sheet where there is one, otherwise the link is copied
  async function shareLink(btn, data, label) {
    try {
      if (navigator.share && (!navigator.canShare || navigator.canShare(data))) {
        try { await navigator.share(data); return; } catch (e) { if (e.name === "AbortError") return; }  // closed it
      }
      await navigator.clipboard.writeText(data.url);
      btn.textContent = T.copied;
    } catch {
      btn.textContent = T.copyFailed;
    }
    setTimeout(() => { if (btn.isConnected) btn.textContent = label; }, 2500);
  }

  function share(p) {
    const url = new URL(location.href);
    url.hash = "";
    url.searchParams.set("miesto", p.id);
    track("zdielat-miesto", p._n);
    shareLink($("#share"), { title: p._n, url: url.href }, T.share);
  }

  // the address bar always holds the current search, so it can be copied and shared: ?kde=Pezinok&co=syr&km=10
  // (a chosen language stays in it as ?lang=en)
  function syncUrl() {
    const url = new URL(location.href);
    const set = (k, v) => (v ? url.searchParams.set(k, v) : url.searchParams.delete(k));
    // never put the visitor's own position or a typed address into a link
    const loc = state.loc && !state.loc.me && !state.loc.addr ? state.loc : null;
    set("kde", loc?.name);
    set("okres", loc && state.obce && state.obce.filter((o) => o.name === loc.name).length > 1 ? loc.okres : "");  // two Haniskas
    set("km", loc && state.radius !== 25 ? String(state.radius) : "");
    set("co", state.buy !== "all" ? state.buy : "");
    set("bio", state.bioOnly ? "1" : "");
    set("miesto", state.selected);
    history.replaceState(null, "", url);
  }

  function shareSearch() {
    const url = new URL(location.href);
    url.hash = "";  // the link sets the area itself
    url.searchParams.delete("miesto");
    track("zdielat-vyber");
    shareLink($("#shareSearch"), { title: "ALECO", text: $("#count").textContent.trim(), url: url.href }, T.shareSearch);
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
    if (loc && !loc.me && !loc.addr) track(`obec/${loc.name}`, loc.name);  // which villages and towns people look for
    if (loc && loc.addr) track("adresa");  // that an address was used, never which one
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
    "predaj", "cerstve", "domace", "bio", "in", "near", "around", "at", "buy", "fresh", "local", "the", "of", "from"]);
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

  /* Addresses, streets and landmarks ("Obchodná 5, Bratislava", "Eurovea") come from OpenStreetMap through Photon
     (komoot). It is only asked when the text looks like an address or nothing of ours matches, so a plain town
     search never leaves the site; never with the visitor's own position. */
  const PHOTON = "https://photon.komoot.io/api/";
  const looksLikeAddress = (fq) => /\d/.test(fq) || fq.includes(",") || /(^| )(ul|ulica|nam|namestie|cesta|trieda|nabrezie|street|square)( |\.|$)/.test(fq);
  const addrCache = new Map();
  let addrAbort = null;
  // "Eurovea, Pribinova, Bratislava", "Obchodná 5, Bratislava": name, street and number, town, without repeats
  function addrLabel(p) {
    const town = p.city || p.town || p.village || p.district || p.county || "";
    const street = p.street ? `${p.street}${p.housenumber ? ` ${p.housenumber}` : ""}` : "";
    const parts = [p.name, street, town].filter(Boolean);
    return parts.filter((x, i) => !parts.slice(0, i).some((y) => fold(y).includes(fold(x)))).join(", ");
  }
  async function findAddresses(q) {
    const key = fold(q.trim());
    if (addrCache.has(key)) return addrCache.get(key);
    addrAbort?.abort();
    addrAbort = new AbortController();
    const bias = state.loc?.me ? null : state.loc ? state.loc.c : map.getCenter().toArray();
    const url = `${PHOTON}?q=${encodeURIComponent(q.trim())}&limit=10&bbox=${SK_BOUNDS.flat().join(",")}`
      + (bias ? `&lat=${bias[1].toFixed(1)}&lon=${bias[0].toFixed(1)}` : "") + (EN ? "&lang=en" : "");
    try {
      const r = await fetch(url, { signal: addrAbort.signal });
      if (!r.ok) return [];
      const out = [];
      for (const f of (await r.json()).features || []) {
        const p = f.properties || {};
        if (p.countrycode !== "SK" || p.osm_key === "place" || p.osm_key === "boundary") continue;  // towns are ours
        const label = addrLabel(p), head = p.name || label, c = f.geometry.coordinates;
        // one landmark is often several map objects (building, entrance, bike racks): keep the first one nearby
        if (!label || out.some((a) => a.label === label || (a.head === head && km(a.c, c) < 0.5))) continue;
        out.push({ label, head, c });
        if (out.length === 4) break;
      }
      addrCache.set(key, out);
      return out;
    } catch {
      return [];  // offline, blocked or replaced by a newer search: just no addresses
    }
  }
  const lookupAddresses = debounce(async (q) => {
    const fq = fold(q.trim()).replace(/\s+/g, " ");
    if ($("#q").value !== q || fq.length < 4) return;
    if (!looksLikeAddress(fq) && state.suggest.length) return;  // a town, product or place of ours matched
    state.addrPending = true;
    renderSuggest();
    const found = await findAddresses(q);
    state.addrPending = false;
    if ($("#q").value !== q) return;
    state.suggest = buildSuggest(q, found);
    renderSuggest();
  }, 350);

  function buildSuggest(q, addrs = []) {
    const fq = fold(q.trim()).replace(/\s+/g, " ");
    if (fq.length < 3) return [];
    const villages = findObce(q);
    const words = fq.split(" ").filter((w) => w.length >= 3);
    const isProductWord = (b, w) => w.length >= 3 && b.fw.some((x) => x.startsWith(w));
    const products = BUY.filter((b) => words.some((w) => isProductWord(b, w)));
    // a product and a town in one go: "vajcia bratislava", "syr pri pezinku", "cheese pezinok"
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
    const addrFirst = looksLikeAddress(fq);  // "Hlavná 12": the addresses are what was meant
    const addrItems = addrs.map((a) => ({ kind: "addr", a }));
    return [
      ...combos,
      ...(addrFirst ? addrItems : []),
      ...villages.filter((v) => v.f === fq).map((v) => ({ kind: "obec", v })),
      ...products.map((b) => ({ kind: "buy", b })),
      ...villages.filter((v) => v.f !== fq).map((v) => ({ kind: "obec", v })),
      ...places.map(({ f }) => ({ kind: "place", f })),
      ...(addrFirst ? [] : addrItems),
    ].slice(0, 8);
  }

  const suggestItem = (i, icon, style, main, kind) => `<button type="button" class="suggest-item" data-i="${i}">
      <span class="${icon}"${style ? ` style="${style}"` : ""} aria-hidden="true"></span><span class="main">${main}</span><span class="go">${kind}</span></button>`;

  function renderSuggest() {
    const q = $("#q").value.trim();
    const html = state.suggest.map((x, i) => {
      if (x.kind === "obec") {
        const okres = x.v.okres && x.v.okres !== x.v.name ? `<span class="small">${esc(T.okresSmall(x.v.okres))}</span>` : "";
        return suggestItem(i, "pin", "", `<strong>${esc(x.v.name)}</strong>${okres}`, T.town);
      }
      if (x.kind === "buy") return suggestItem(i, "basket", "", `<strong>${x.b.label}</strong>`, T.product);
      if (x.kind === "combo") return suggestItem(i, "basket", "", T.combo(x.b.label, esc(x.v.name)), T.nearby);
      if (x.kind === "addr") return suggestItem(i, "pin", "", `<strong>${esc(x.a.label)}</strong>`, T.address);
      const p = x.f.properties;
      return suggestItem(i, "dot", `--c:${GROUP_COLOR[p.group] || "#17322a"}`,
        `<strong>${esc(p._n)}</strong>${p.obec && !p._generic ? `<span class="small">, ${esc(p.obec)}</span>` : ""}`, esc(labelOf(p)));
    }).join("") || (state.addrPending ? `<p class="suggest-none">${T.addrSearching}</p>`
      : state.obce && fold(q).length >= 3 ? `<p class="suggest-none">${T.noneFound(esc(q))}</p>` : "");
    $("#suggest").innerHTML = html;
    $("#suggest").hidden = !html;
  }

  function showSuggestFor(q) {
    state.suggest = buildSuggest(q);
    renderSuggest();
    if (!state.obce) loadObce().then(() => { if ($("#q").value === q) { state.suggest = buildSuggest(q); renderSuggest(); lookupAddresses(q); } });
    else lookupAddresses(q);
  }

  function hideSuggest() {
    state.suggest = [];
    $("#suggest").hidden = true;
  }

  function pick(x) {
    hideSuggest();
    if (x.kind === "addr") {
      $("#q").value = x.a.label;
      $("#q").blur();
      setLoc({ name: x.a.label, c: x.a.c, addr: true });
      return;
    }
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
  $("#chips").innerHTML = [{ id: "all", label: T.all }, ...BUY].map((b) =>
    `<button type="button" class="chip" data-buy="${b.id}" aria-pressed="${b.id === "all"}">${b.label} <span class="n"></span></button>`).join("");
  $("#legend").innerHTML = GROUPS.map((g) => `<li><span class="dot" style="--c:${g.color}" aria-hidden="true"></span>${T.groups[g.id]}</li>`).join("")
    + `<li><span class="dot bio" aria-hidden="true"></span>${T.bioLegend}</li>`;

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
    const reset = (text) => { btn.textContent = text; setTimeout(() => (btn.textContent = T.myLocation), 3000); };
    if (!navigator.geolocation) { reset(T.noGeo); return; }
    btn.textContent = T.locating;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        btn.textContent = T.myLocation;
        hideSuggest();
        q.value = T.yourLocation;  // the box speaks to the visitor, like "do 25 km od vás"
        setLoc({ name: T.yourLocation, c: [pos.coords.longitude, pos.coords.latitude], me: true });
        track("moja-poloha");  // only that the button was used, never where
      },
      () => reset(T.geoFailed),
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
  $("#mailAdd").href = mailto(T.mailAddSubject, T.mailAddBody);
  $("#mailText").textContent = T.mailOr(CONTACT);
  for (const a of document.querySelectorAll("#privacyDialog .mail")) { a.href = `mailto:${CONTACT}`; a.textContent = CONTACT; }
  for (const s of document.querySelectorAll("#privacyDialog .operator")) s.textContent = OPERATOR ? `${OPERATOR}, ` : "";
  $("#addBtn").addEventListener("click", () => $("#addDialog").showModal());
  $("#mailAdd").addEventListener("click", () => track("napisat-email"));
  // directions, calls, websites and error reports from a place card: the clearest sign the map was useful
  $("#detail").addEventListener("click", (e) => {
    const a = e.target.closest("[data-track]");
    if (a && state.selected) track(a.dataset.track, state.byId.get(state.selected)?.properties._n);
  });
  $("#aboutBtn").addEventListener("click", () => $("#aboutDialog").showModal());
  $("#privacyBtn").addEventListener("click", () => $("#privacyDialog").showModal());
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
    if (m.generated) $("#generated").textContent = T.updated(fmtDate(m.generated));
    const bio = d.features.filter((f) => f.properties.bio).length;
    $("#stats").textContent = T.stats(fmtNum(d.features.length), fmtNum(bio));
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
    $("#list").innerHTML = `<li class="empty">${T.loadFailed}</li>`;
  });
  Promise.all([dataReady, mapReady]).then(() => {
    addLayers();
    filter();
    drawArea();
    if (state.selected) map.getSource("sel").setData(fc([state.byId.get(state.selected)]));
  }).catch((e) => console.error("map setup failed:", e));
})();
