// Preistabelle (Einstellungen) -- reine, DOM-freie Funktionen (node-testbar,
// tests/test_einstellungen.mjs; Muster tiefenanalyse.js/verankerung.js).
//
// Auftrag 2026-08-30 Nachtrag: Primärzeilen = scharf geschaltete Abrechnungsliste aus
// modelle.json (/api/preise) -- daraus rechnet kennzahlen._preissatz die Sitzungskosten,
// diese Liste IST die Kostenquelle (darum "Abrechnung"-Chip je Zeile). Anzeige-Anreicherung
// (Kontext k, Herkunft-Land) kommt aus dem bereits geladenen Katalog-Snapshot. Match-Regel
// (Zwischenstand, Backend-Projection folgt -- Plan docs/plans/
// preistabelle-master-sicht-plan.md): exakt -> Kurzname -> Basisname vor ":"; mehrere
// Treffer = "mehrdeutig" und nichts wird angezeigt (nichts raten, Codex-Review 2026-08-30).
// Die Abrechnung selbst bleibt unberuehrt: sie liest weiter nur die gespeicherten Keys.
import { escapeHtml, herkunftFlaggeHtml, formatDeVoll, ausIso } from "./format.js";
import { statusZoneHtml } from "./katalog.js";

var ANBIETER_CHIP = {
  anthropic: ["Anthropic", "quelle-claude"],
  // Maintainer 2026-08-30: herkunft "openai" sind die KOSTENAEQUIVALENT-Tarife fuer Codex-Sessions
  // (Codex meldet je Ereignis das echte Modell) -- Anzeige heisst darum "Codex" im
  // Start-Grün (quelle-codex), nicht "OpenAI". Direkt angebunden ist OpenAI nie.
  openai: ["Codex", "quelle-codex"],
  ollama: ["Ollama", ""],
  openrouter: ["OpenRouter", "quelle-openrouter"],
  requesty: ["Requesty", "quelle-requesty"],
};
var PERSONA_REIHENFOLGE = ["vico", "vica", "cura"];

export function kurzName(name) {
  return name.split("/").pop().split(":")[0];
}

export function anbieterChip(herkunft) {
  var paar = ANBIETER_CHIP[herkunft] || [herkunft ? herkunft.charAt(0).toUpperCase() + herkunft.slice(1) : "—", ""];
  var klasse = paar[1] ? " " + paar[1] : "";
  return '<span class="quelle-chip' + klasse + '">' + escapeHtml(paar[0]) + "</span>";
}

// Match des Abrechnungs-Keys gegen den Katalog. Reihenfolge deterministisch; mehrere
// Kandidaten = "mehrdeutig" mit modell null (Codex-Einwand: falscher Match ist schlimmer
// als keiner -- dann bleiben Kontext/Herkunft bewusst leer).
export function findeKatalogMatch(key, alle) {
  var exakt = (alle || []).filter(function (m) { return m.id === key; });
  if (exakt.length) return { status: "exakt", modell: exakt[0] };
  // Datums-Snapshots (claude-haiku-4-5-20251001) vor dem Alias-Match abstreifen (Fund
  // 2026-08-30 im Screenshot: die Zeile blieb ohne Flagge/Kontext, obwohl der Katalog den
  // Stamm kennt). Entspricht katalog.py's Snapshot-Regel (Datum != Version).
  var stamm = key.replace(/-\d{8}$/, "");
  var kurz = kurzName(stamm);
  var basis = stamm.split(":", 1)[0];
  var kandidaten = (alle || []).filter(function (m) {
    return m.id === kurz || m.id === basis || m.id === stamm;
  });
  if (kandidaten.length === 1) return { status: "alias", modell: kandidaten[0] };
  if (kandidaten.length > 1) return { status: "mehrdeutig", modell: null };
  return { status: "kein_match", modell: null };
}

// persona_wege (roh: flache Liste ODER {rolle, wege}) -> Persona-Liste, in der das Modell
// UEBER DIESE PREIS-HERKUNFT gepinnt ist (Maintainer 2026-08-30 Screenshot-Runde: "keine
// Interpretation, die tatsaechliche Verdrahtung" -- VICA/CURA liefen sonst am Requesty-
// Preis, obwohl sie ueber Ollama laufen). herkunft->Pin-Quelle: anthropic=="claude",
// openai hat keinen Weg (kein Pin). exakt oder Kurzform (":cloud"-Pins matchen den
// Referenz-Basisnamen).
var HERKUNFT_ZU_QUELLE = { claude: "claude", anthropic: "claude",
                           ollama: "ollama", openrouter: "openrouter", requesty: "requesty" };

export function verwendetAusPins(key, pins, herkunft) {
  var quelle = HERKUNFT_ZU_QUELLE[herkunft] || null;
  if (!quelle) return [];
  var kurz = kurzName(key);
  var treffer = [];
  Object.keys(pins || {}).forEach(function (persona) {
    var block = pins[persona];
    var wege = Array.isArray(block) ? block : (block && block.wege) || [];
    var hat = wege.some(function (weg) {
      return weg.quelle === quelle && (weg.modell === key || kurzName(weg.modell) === kurz);
    });
    if (hat) treffer.push(persona);
  });
  return treffer.sort(function (a, b) {
    return PERSONA_REIHENFOLGE.indexOf(a) - PERSONA_REIHENFOLGE.indexOf(b);
  });
}

export function bauePreisEintraege(preiseMap, katalogAlle, personaPins, blockStand) {
  return Object.keys(preiseMap || {}).map(function (key) {
    var satz = preiseMap[key] || {};
    // Serverseitige Anreicherung (katalog.kanonische_id-Match, web.py /api/preise) hat
    // Vorrang vor dem provisorischen Client-Match (Screenshot-Runde 3, Maintainer 2026-08-30).
    var server = satz.katalog || null;
    var match = server ? null : findeKatalogMatch(key, katalogAlle);
    return {
      name: key,
      kurz: kurzName(key),
      herkunft: satz.herkunft || null,
      eingabe: satz.input ?? null,
      ausgabe: satz.output ?? null,
      kontext: server ? server.kontext_k : (match.modell ? match.modell.kontext_k ?? null : null),
      herkunftLand: server ? server.herkunft : (match.modell ? match.modell.herkunft ?? null : null),
      hersteller: server ? server.hersteller ?? null : (match.modell ? match.modell.hersteller ?? null : null),
      matchStatus: server ? server.match : match.status,
      // Katalog-Status (Maintainer 2026-08-30, Status-Zone unten): die Preistabelle traegt dieselbe
      // Zone wie der Katalog vorn -- Latest-/Legacy-Chip ODER die Sterne, denn der Server
      // reicht seit heute auch sterne_gesamt durch (gleiche Regel, eine Logik).
      status: server ? server.status ?? null : (match.modell ? match.modell.status ?? null : null),
      nachfolger: server ? server.nachfolger ?? null : (match.modell ? match.modell.nachfolger ?? null : null),
      sterneGesamt: server ? server.sterne_gesamt ?? null
                           : (match.modell ? (match.modell.sterne || {}).gesamt ?? null : null),
      stand: satz.stand || blockStand || null,
      verwendet: verwendetAusPins(key, personaPins, satz.herkunft || null),
    };
  });
}

var SORT_WERT = {
  modell: function (e) { return e.kurz; },
  herkunft: function (e) { return e.herkunftLand; },
  anbieter: function (e) { return e.herkunft; },
  kontext: function (e) { return e.kontext; },
  eingabe: function (e) { return e.eingabe; },
  ausgabe: function (e) { return e.ausgabe; },
  stand: function (e) { return e.stand; },
  verwendet: function (e) { return e.verwendet.join(","); },
};

// Gleiche Erwartung wie sortiereModelle (katalog.js): fehlende Werte immer ans Ende,
// unabhaengig von der Richtung.
export function sortierePreise(eintraege, spalte, richtung) {
  var hole = SORT_WERT[spalte] || SORT_WERT.modell;
  var kopie = (eintraege || []).slice();
  kopie.sort(function (a, b) {
    var va = hole(a), vb = hole(b);
    var aFehlt = va === null || va === undefined, bFehlt = vb === null || vb === undefined;
    if (aFehlt && bFehlt) return 0;
    if (aFehlt) return 1;
    if (bFehlt) return -1;
    if (typeof va === "string") return richtung * va.localeCompare(vb, "de");
    return richtung * (va - vb);
  });
  return kopie;
}

function preisText(usd) {
  return usd === null || usd === undefined ? "—" : Number(usd).toFixed(1).replace(".", ",");
}

function verwendetChipsHtml(verwendet) {
  // Persona-Chips in ihrer Farbe (Maintainer 2026-08-30): Toene wortgleich den mini-orb
  // Klassen -- vico #2f8fd8, vica #b07fe0, cura #4fd09a (style.css .persona-vico/...).
  var chips = verwendet.map(function (persona) {
    var klasse = PERSONA_REIHENFOLGE.indexOf(persona) !== -1 ? " persona-" + persona : "";
    return '<span class="verwendet-chip' + klasse + '">' + escapeHtml(persona.toUpperCase()) + "</span>";
  });
  chips.push('<span class="verwendet-chip" title="Diese Liste ist die Kostenquelle der Beleg-Abrechnung">Abrechnung</span>');
  return '<div class="verwendet-chips">' + chips.join("") + "</div>";
}

export function preisZeileHtml(e) {
  var land = e.herkunftLand
    ? '<td class="herkunft-zelle" title="' + escapeHtml(e.herkunftLand) + '">' + herkunftFlaggeHtml(e.herkunftLand) + "</td>"
    : '<td class="herkunft-zelle">—</td>';
  var stand = e.stand ? formatDeVoll(ausIso(e.stand)) : "—";
  // Unterzeile (Maintainer 2026-08-30, Screenshot-Runde 4): der HERSTELLER wie vorne im Modellkatalog
  // („egal ueber welchen Anbieter, dort steht der Hersteller"), nicht der anbieterbezogene
  // Key. Der volle Abrechnungs-Key bleibt als Tooltip am Namen erhalten; ohne Katalog-Match
  // ehrlich "—" statt geraten.
  var unter = e.hersteller || (ANBIETER_CHIP[e.herkunft] || [e.herkunft || "—"])[0];
  // Status-Zone (Maintainer 2026-08-30, revidiert unten): GENAU EIN Zustand unten rechts, dieselbe
  // Logik wie der Katalog vorn (statusZoneHtml) -- Legacy-Chip ODER Sterne (bewertet) ODER
  // Latest-Chip. Oben nur der Name ueber die volle Breite. Adapter: die Preisliste kennt
  // nur sterne_gesamt, Details bleiben im Tooltip ehrlich "–".
  var zone = statusZoneHtml({
    id: e.name, status: e.status, nachfolger: e.nachfolger,
    sterne: { gesamt: e.sterneGesamt, score: null, manuell: null },
    vision: null, aa_index: null, coding_index: null,
  });
  return "<tr>"
    + '<td><div class="modell-zelle mz2" title="' + escapeHtml(e.name) + '">'
    + '<span class="mz-top"><span class="name"><span class="mono">' + escapeHtml(e.kurz) + "</span></span></span>"
    + '<span class="hersteller">' + escapeHtml(unter) + "</span>"
    + '<div class="mz-chip">' + zone + "</div></div></td>"
    + land
    + "<td>" + anbieterChip(e.herkunft) + "</td>"
    + '<td class="num">' + (e.kontext === null || e.kontext === undefined ? "—" : escapeHtml(String(e.kontext))) + "</td>"
    + '<td class="num">' + preisText(e.eingabe) + "</td>"
    + '<td class="num">' + preisText(e.ausgabe) + "</td>"
    + "<td>" + stand + "</td>"
    + "<td>" + verwendetChipsHtml(e.verwendet) + "</td>"
    + "</tr>";
}
