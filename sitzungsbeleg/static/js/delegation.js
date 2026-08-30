// Karte "Delegation": dritte Kennzahl-Karte neben Verbrauch/Ablauf, gleiche Optik (.gr/.g/.gk/
// .paar/.kz aus style.css, Muster kacheln.js) -- Werte aus GET /api/delegation/<id>
// (delegation.py, CONTRACTS.md C5). Eigener Benchmark (nicht der Kacheln-Benchmark): Median
// derselben fünf Quoten, n < 10 = keine Bewertung, n = 0 = kein Ø (dieselben Regeln wie
// kacheln.js -- hier dupliziert, kacheln.js exportiert sie nicht).
// Haengt die Karte an #kennzahlen-karten an: der Container wird von kacheln.js komplett per
// innerHTML überschrieben (Ladehinweis, dann die zwei Karten) -- ein MutationObserver wartet
// darauf, statt sich mit dem zweiten Fetch in ein Zeitrennen zu begeben (Abnahme-Lektion
// "?v=-Stempel"-Cache; hier: Reihenfolge zweier unabhaengiger Promises).
import { escapeHtml } from "./format.js";
import { holeJSON } from "./api.js";

var aktuelleId = null;

export function renderDelegationsKarte(id, kz) {
  aktuelleId = id;
  var container = document.getElementById("kennzahlen-karten");
  if (!container) return;
  holeJSON("/api/delegation/" + encodeURIComponent(id))
    .then(function (del) { anhaengenWennBereit(container, id, karteHtml(del, kz)); })
    .catch(function (e) {
      console.error("Delegations-Karte: nicht ladbar", e);
      anhaengenWennBereit(container, id, fehlerKarteHtml(e));
    });
}

// Wartet, bis kacheln.js seine zwei Karten gerendert hat (erkennbar an `.kz-karte`), egal ob das
// vor oder nach dem Delegation-Fetch passiert -- danach einmalig anhängen, Beobachter trennen.
function anhaengenWennBereit(container, id, html) {
  if (id !== aktuelleId) return;
  if (container.querySelector(".kz-karte")) { container.insertAdjacentHTML("beforeend", html); return; }
  var beobachter = new MutationObserver(function () {
    if (id !== aktuelleId) { beobachter.disconnect(); return; }
    if (container.querySelector(".kz-karte")) {
      beobachter.disconnect();
      container.insertAdjacentHTML("beforeend", html);
    }
  });
  beobachter.observe(container, { childList: true });
}

function fehlerKarteHtml(fehler) {
  return '<div class="g kz-karte"><div class="gk"><span class="kern">Delegation</span></div>'
    + '<p class="caption" style="margin:6px 14px;">Nicht ladbar: ' + escapeHtml(fehler.message) + "</p></div>";
}

// ================= Kleinbausteine (dieselben Regeln wie kacheln.js -- dort nicht exportiert) ====
function deltaChip(klasse, text) {
  return '<span class="delta ' + klasse + '">' + escapeHtml(text) + "</span>";
}

function deltaHtml(wert, bench, hoeherSchlecht, n) {
  if (!n) return deltaChip("d-neutral", "kein Ø");
  if (n < 10) return deltaChip("d-neutral", "Ø (n=" + n + ", keine Bewertung)");
  if (bench === null || bench === undefined || wert === null || wert === undefined) return deltaChip("d-neutral", "kein Ø");
  var p = (wert - bench) / bench * 100;
  var klasse = Math.abs(p) <= 15 || hoeherSchlecht === null ? "d-neutral"
    : (hoeherSchlecht ? (p > 0 ? "d-hoch" : "d-tief") : (p > 0 ? "d-tief" : "d-hoch"));
  return deltaChip(klasse, (p >= 0 ? "+" : "") + p.toFixed(0) + " % vs Ø");
}

function kzHtml(label, wertHtml, delta, hilfeId) {
  var btn = hilfeId
    ? '<button type="button" class="hilfe-btn" aria-controls="' + hilfeId + '" aria-expanded="false" aria-label="Erklärung anzeigen">?</button>'
    : "";
  return '<div class="kz"><div class="kz-k"><span class="l">' + escapeHtml(label) + "</span>" + btn + "</div>"
    + '<div class="kz-w">' + wertHtml + (delta || "") + "</div></div>";
}

function hilfeHtml(id, berechnung, aussage) {
  return '<div class="hilfe-text" id="' + id + '" hidden><p><b>Berechnung:</b> ' + berechnung + "</p><p><b>Aussage:</b> " + aussage + "</p></div>";
}

function modellZeileHtml(modelle) {
  if (!modelle || !modelle.length) return '<span class="w">—</span>';
  return modelle.map(function (m) {
    return '<span class="w">' + escapeHtml(m.modell || "—") + " <small>×" + m.agenten + "</small></span>";
  }).join("");
}

function pct0(x) { return x === null || x === undefined ? "—" : Math.round(x * 100) + " %"; }
function pct1(x) { return x === null || x === undefined ? "—" : (x * 100).toFixed(1).replace(".", ",") + " %"; }
function benchPct(b, feld) { return b && b[feld] !== null && b[feld] !== undefined ? b[feld] * 100 : null; }

// ================= Zeilen der Karte =================
function kopfHtml(del) {
  var hero = del.starts + " Subagenten · " + pct0(del.kosten_quote) + " der Kosten";
  return '<div class="gk"><span class="kern">Delegation</span><span class="hero">' + hero + "</span></div>";
}

function aufrufZeileHtml(del, b) {
  var w1 = '<span class="w">' + del.starts + " Starts · " + pct0(del.aufruf_quote) + " der Runden</span>";
  var d1 = deltaHtml(del.aufruf_quote * 100, benchPct(b, "aufruf_quote"), null, b && b.n);
  var w2 = '<span class="w">max. ' + del.fanout_max + "</span>";
  return '<div class="paar">' + kzHtml("Aufrufe", w1, d1, "h-del-aufruf") + kzHtml("Fan-out", w2, "", null) + "</div>"
    + hilfeHtml("h-del-aufruf",
      "Subagent-Starts ÷ Runden. Fan-out = meiste gleichzeitig gestartete Subagenten in einer Runde.",
      "Wie oft die Sitzung delegiert hat statt selbst zu arbeiten, und wie gebündelt (mehrere Subagenten in derselben Runde).");
}

function kostenZeileHtml(del, kz, b) {
  var haupt = kz.kosten, sub = kz.kosten_subagenten || 0;
  var w1 = '<span class="w">' + (haupt !== null && haupt !== undefined ? haupt.toFixed(2) : "—") + " · " + sub.toFixed(2) + " " + (kz.kosten_waehrung || "") + "</span>";
  var d1 = deltaChip("d-neutral", pct0(del.kosten_quote) + " delegiert");
  var w2 = '<span class="w">' + pct0(del.output_quote) + " des Output</span>";
  var d2 = deltaHtml(del.output_quote * 100, benchPct(b, "output_quote"), null, b && b.n);
  return '<div class="paar">' + kzHtml("Kosten Hauptagent · Subagenten", w1, d1, "h-del-kosten")
    + kzHtml("Output-Anteil Subagenten", w2, d2, "h-del-output") + "</div>"
    + hilfeHtml("h-del-kosten",
      "Kosten Subagenten ÷ Kosten gesamt (Hauptagent + Subagenten, Token × Preis je eigenem Modell).",
      "Wie viel vom Sitzungspreis in Delegation floss.")
    + hilfeHtml("h-del-output",
      "Output-Token aller Subagenten ÷ (Output Hauptagent + Output Subagenten).",
      "Wie viel vom geschriebenen Text aus Subagenten statt der Hauptsitzung kam.");
}

function zeitToolsZeileHtml(del, b) {
  var w1 = '<span class="w">' + pct0(del.zeit_quote) + " der Sitzungsdauer</span>";
  var d1 = del.zeit_quote > 1 ? deltaChip("d-neutral", "parallel möglich") : deltaHtml(del.zeit_quote * 100, benchPct(b, "zeit_quote"), null, b && b.n);
  var w2 = '<span class="w">' + pct0(del.tool_quote) + " der Werkzeuge</span>";
  var d2 = deltaChip("d-neutral", pct1(del.tool_fehlerquote) + " Fehlerquote");
  return '<div class="paar">' + kzHtml("Zeit Subagenten / Sitzung", w1, d1, "h-del-zeit")
    + kzHtml("Werkzeuge Subagenten", w2, d2, "h-del-tools") + "</div>"
    + hilfeHtml("h-del-zeit",
      "Summe der Subagent-Laufzeiten ÷ Sitzungsdauer. Über 100 % heißt: Subagenten liefen gemeinsam länger, als die Sitzung dauerte (Parallelität).",
      "Subagenten laufen parallel zur Hauptsitzung -- ein hoher Wert kostet keine Wanduhr-Zeit, wenn wirklich parallel gearbeitet wurde.")
    + hilfeHtml("h-del-tools",
      "Werkzeugaufrufe der Subagenten ÷ alle Werkzeugaufrufe (Haupt + Sub). Fehlerquote = fehlgeschlagene Subagent-Werkzeugaufrufe ÷ Subagent-Werkzeugaufrufe.",
      "Wie viel Handarbeit bei den Subagenten statt der Hauptsitzung lag, und wie sauber sie dabei arbeiteten.");
}

function ergebnisZeileHtml(del) {
  var vollstaendig = del.mit_beleg === del.starts && del.starts > 0;
  var d1 = del.starts === 0 ? deltaChip("d-neutral", "keine Subagenten")
    : vollstaendig ? deltaChip("d-tief", "vollständig") : deltaChip("d-hoch", (del.starts - del.mit_beleg) + " ohne Beleg");
  var w1 = '<span class="w">' + del.mit_beleg + "/" + del.starts + " mit Beleg · Tiefe " + del.tiefe_max + "</span>";
  var w2 = modellZeileHtml(del.modelle);
  return '<div class="paar">' + kzHtml("Ergebnis", w1, d1, null) + kzHtml("Modelle Subagenten", w2, "", null) + "</div>";
}

function fussnoteHtml(b) {
  var text = !b
    ? "Ø = Median der letzten 30 Tage, gleiches Projekt und Quelle, ≥ 1 Subagent-Start — Vergleich nicht verfügbar."
    : "Ø = Median der letzten 30 Tage, gleiches Projekt und Quelle, ≥ 1 Subagent-Start, n = " + b.n + " Sitzungen.";
  return '<p class="caption" style="margin:6px 14px 8px;">' + escapeHtml(text) + "</p>";
}

function karteHtml(del, kz) {
  var b = del.benchmark && del.benchmark.n > 0 ? del.benchmark : null;
  return '<div class="g kz-karte">' + kopfHtml(del) + aufrufZeileHtml(del, b)
    + kostenZeileHtml(del, kz, b) + zeitToolsZeileHtml(del, b) + ergebnisZeileHtml(del)
    + fussnoteHtml(b) + "</div>";
}
