// Kennzahlen-Kacheln der Sitzungsseite: zwei Karten (Verbrauch/Ablauf) in der Befund-Karten-
// Optik (.gr/.g/.gk aus style.css) mit einem Spurenband je Runde (Kosten, Tool-Fehler,
// Subagent-Start, Rundendauer). Abnahmekriterium: Mockup Rev 3
// (_work/sitzungsbeleg-kacheln-final.html), SVG-Logik portiert aus
// scripts/_work_sitzungsbeleg/2026-08-27-baue-kacheln-mockup.py (balken_svg/linie_svg/
// ticks_svg). Werte kommen aus zwei Quellen: `kz` = dokument.kennzahlen (immer vorhanden),
// `kac` = zweiter Fetch /api/sitzung/{id}/kacheln (kann fehlschlagen -- dann Kacheln trotzdem
// mit den kz-Werten, Baender mit Hinweistext statt SVG).
import { escapeHtml, formatDauerLang } from "./format.js";
import { holeJSON } from "./api.js";

var SVG_W = 830;

// ================= Einstieg =================
export function renderKennzahlenKarten(id, kz) {
  document.getElementById("kennzahlen-karten").innerHTML = '<p class="ladehinweis">Lädt…</p>';
  document.getElementById("kennzahlen-fussnote").textContent = "";
  holeJSON("/api/sitzung/" + encodeURIComponent(id) + "/kacheln")
    .then(function (kac) { zeichneKarten(kz, kac); })
    .catch(function (e) { console.error("Kennzahl-Karten: Rundenverlauf nicht ladbar", e); zeichneKarten(kz, null); });
}

function zeichneKarten(kz, kac) {
  // n=0: Backend liefert das Benchmark-Objekt mit lauter null-Werten -> wie "kein Benchmark" behandeln.
  var b = (kac && kac.benchmark && kac.benchmark.n > 0) ? kac.benchmark : null;
  document.getElementById("kennzahlen-karten").innerHTML = verbrauchKarteHtml(kz, kac, b) + ablaufKarteHtml(kz, kac, b);
  document.getElementById("kennzahlen-fussnote").textContent = fussnoteText(b);
}

function fussnoteText(b) {
  if (!b) return "Ø = Median der letzten 30 Tage, gleiches Projekt und Quelle, ≥ 5 Runden — Vergleich nicht verfügbar.";
  return "Ø = Median der letzten 30 Tage, gleiches Projekt und Quelle, ≥ 5 Runden, n = " + b.n + " Sitzungen.";
}

// ================= Kleinbausteine (Delta-Chip, Kennzahl-Zeile, Hilfetext) =================
function deltaChip(klasse, text) {
  return '<span class="delta ' + klasse + '">' + escapeHtml(text) + "</span>";
}

// n < 10 (Vorgabe): keine Bewertung, nur der Stichprobenhinweis; n = 0: "kein Ø". Sonst
// grau innerhalb ±15 %, sonst rot/gruen je nach `hoeherSchlecht` (null = immer neutral).
function deltaHtml(wert, bench, hoeherSchlecht, n) {
  if (!n) return deltaChip("d-neutral", "kein Ø");
  if (n < 10) return deltaChip("d-neutral", "Ø (n=" + n + ", keine Bewertung)");
  if (bench === null || bench === undefined || wert === null || wert === undefined) return deltaChip("d-neutral", "kein Ø");
  var p = (wert - bench) / bench * 100;
  var klasse = Math.abs(p) <= 15 || hoeherSchlecht === null ? "d-neutral"
    : (hoeherSchlecht ? (p > 0 ? "d-hoch" : "d-tief") : (p > 0 ? "d-tief" : "d-hoch"));
  return deltaChip(klasse, (p >= 0 ? "+" : "") + p.toFixed(0) + " % vs Ø");
}

function kzHtml(label, wertHtml, delta, hilfeId, extraClass) {
  var btn = '<button type="button" class="hilfe-btn" aria-controls="' + hilfeId + '" aria-expanded="false" aria-label="Erklärung anzeigen">?</button>';
  return '<div class="kz' + (extraClass ? " " + extraClass : "") + '"><div class="kz-k"><span class="l">' + escapeHtml(label) + "</span>" + btn + "</div>"
    + '<div class="kz-w">' + wertHtml + (delta || "") + "</div></div>";
}

function hilfeHtml(id, berechnung, aussage) {
  return '<div class="hilfe-text" id="' + id + '" hidden><p><b>Berechnung:</b> ' + berechnung + "</p><p><b>Aussage:</b> " + aussage + "</p></div>";
}

function modelZeileHtml(modelle, einheit) {
  if (!modelle || !modelle.length) return '<span class="w">—</span>';
  return modelle.slice().sort(function (a, b) { return (b.aufrufe ?? b.agenten ?? 0) - (a.aufrufe ?? a.agenten ?? 0); })
    .map(function (m) {
      var n = m.aufrufe !== undefined ? m.aufrufe : m.agenten;
      return '<span class="w">' + escapeHtml(m.modell || "—") + " <small>×" + n + " " + einheit + "</small></span>";
    }).join("");
}

function formatMin(ms) { return ms === null || ms === undefined ? "—" : Math.round(ms / 60000) + " min"; }

// Bevorzugt den Wert aus /kacheln (kann sich vom kz-Wert unterscheiden, z. B. nach dem
// Doppelzaehlungs-Fix) -- lokale Berechnung nur als Rueckfallebene, falls der zweite Fetch fehlt.
function cacheAnteilProzent(kz, kac) {
  if (kac && kac.cache_anteil !== null && kac.cache_anteil !== undefined) return kac.cache_anteil * 100;
  var t = kz.token || {};
  var nenner = (t.input || 0) + (t.cache_write || 0) + (t.cache_read || 0);
  return nenner ? (t.cache_read / nenner * 100) : 0;
}

// ================= Runden-Hilfen (Positionen im Array, Rundennummern fuer Text) =================
function positionenVonRunden(runden, indizes) {
  // Backend liefert 0-basierte Array-Positionen (kacheln.top3_index / langsamste_index).
  var pos = new Set();
  (indizes || []).forEach(function (i) { if (i >= 0 && i < runden.length) pos.add(i); });
  return pos;
}
function compPositionen(runden) { var s = new Set(); runden.forEach(function (r, i) { if (r.compaction) s.add(i); }); return s; }
function timeoutPositionen(runden) { var s = new Set(); runden.forEach(function (r, i) { if (r.timeout) s.add(i); }); return s; }
function compRunden(runden) { return runden.filter(function (r) { return r.compaction; }).map(function (r) { return r.index; }); }
function timeoutRunden(runden) { return runden.filter(function (r) { return r.timeout; }).map(function (r) { return r.index; }); }
function rundenListeText(arr) { return arr.length ? " (Runde " + arr.join(", ") + ")" : ""; }

function median(werte) {
  if (!werte.length) return 0;
  var s = werte.slice().sort(function (a, b) { return a - b; });
  var mitte = Math.floor(s.length / 2);
  return s.length % 2 ? s[mitte] : (s[mitte - 1] + s[mitte]) / 2;
}

// ================= SVG-Bausteine (portiert aus baue-kacheln-mockup.py) =================
function round2(x) { return Math.round(x * 100) / 100; }
function xVonIndex(i, n, w) { return n > 1 ? round2(i * w / (n - 1)) : w / 2; }
function svgOpen(w, h) { return '<svg viewBox="0 0 ' + w + " " + h + '" role="img">'; }

function medianLinie(medianWert, mx, h, w) {
  if (!medianWert) return "";
  var y = h - Math.max(1, Math.round(medianWert / mx * (h - 4)));
  return '<line x1="0" x2="' + w + '" y1="' + y + '" y2="' + y + '" stroke="var(--text-muted)" stroke-width="1" stroke-dasharray="2 2"/>';
}

function balkenSvg(werte, h, akzentSet, medianWert) {
  var n = werte.length, w = SVG_W, mx = (werte.length ? Math.max.apply(null, werte) : 0) || 1;
  var bw = Math.max(1, (w - (n - 1)) / n);
  var teile = werte.map(function (v, i) {
    var bh = Math.max(1, Math.round(v / mx * (h - 4)));
    var f = akzentSet && akzentSet.has(i) ? "var(--fehler)" : "var(--primaer)";
    return '<rect x="' + round2(i * (bw + 1)) + '" y="' + (h - bh) + '" width="' + bw.toFixed(2) + '" height="' + bh + '" rx="1" fill="' + f + '"/>';
  }).join("");
  return svgOpen(w, h) + teile + medianLinie(medianWert, mx, h, w) + "</svg>";
}

function ticksSvg(werte, h, farbe) {
  var n = werte.length, w = SVG_W;
  var basis = '<line x1="0" x2="' + w + '" y1="' + (h - 1) + '" y2="' + (h - 1) + '" stroke="var(--rand-stark)" stroke-width="1"/>';
  var teile = werte.map(function (v, i) {
    if (!v) return "";
    var x = xVonIndex(i, n, w), hoehe = Math.min(v, 4) * 5;
    return '<rect x="' + (x - 1) + '" y="' + (h - 2 - hoehe) + '" width="2" height="' + hoehe + '" fill="' + farbe + '"/>';
  }).join("");
  return svgOpen(w, h) + basis + teile + "</svg>";
}

function kreisMarker(pts, menge, r, gefuellt) {
  if (!menge) return "";
  var teile = [];
  menge.forEach(function (i) {
    var p = pts[i];
    if (!p) return;
    var stil = gefuellt ? 'fill="var(--fehler)" stroke="var(--flaeche)" stroke-width="1"' : 'fill="none" stroke="var(--fehler)" stroke-width="1.5"';
    teile.push('<circle cx="' + p[0] + '" cy="' + p[1] + '" r="' + r + '" ' + stil + "/>");
  });
  return teile.join("");
}

function linieSvg(werte, h, peakSet, timeoutSet, medianWert) {
  var n = werte.length, w = SVG_W, mx = (werte.length ? Math.max.apply(null, werte) : 0) || 1;
  var pts = werte.map(function (v, i) { return [xVonIndex(i, n, w), round2(h - 2 - v / mx * (h - 6))]; });
  var pfad = '<path d="M' + pts.map(function (p) { return p[0] + "," + p[1]; }).join(" L")
    + '" fill="none" stroke="var(--primaer)" stroke-width="1.5" stroke-linejoin="round"/>';
  var inhalt = pfad + medianLinie(medianWert, mx, h, w) + kreisMarker(pts, peakSet, 3, true) + kreisMarker(pts, timeoutSet, 4.5, false);
  return svgOpen(w, h) + inhalt + "</svg>";
}

// Compaction als dunkle Doppellinie ueber die volle Spurhoehe (Entscheid, Rev 3): andere
// Farbe/Form als die Fehlerstriche, damit sie ohne Nachdenken unterscheidbar ist.
function mitCompaction(svg, n, compPositionenSet, h) {
  var w = SVG_W, teile = [];
  compPositionenSet.forEach(function (i) {
    var x = xVonIndex(i, n, w);
    teile.push('<line x1="' + (x - 1.5) + '" x2="' + (x - 1.5) + '" y1="0" y2="' + h + '" stroke="var(--text)" stroke-width="1.2"/>');
    teile.push('<line x1="' + (x + 1.5) + '" x2="' + (x + 1.5) + '" y1="0" y2="' + h + '" stroke="var(--text)" stroke-width="1.2"/>');
  });
  return svg.replace("</svg>", teile.join("") + "</svg>");
}

// ================= Karte "Verbrauch" =================
function verbrauchKopfHtml(kz, kac, b) {
  var gesamt = kz.kosten_gesamt !== null && kz.kosten_gesamt !== undefined ? kz.kosten_gesamt : kz.kosten;
  var n = kz.runden || 0;
  var kpr = n > 0 && gesamt !== null && gesamt !== undefined ? gesamt / n : null;
  var hero = gesamt !== null && gesamt !== undefined ? gesamt.toFixed(2).replace(".", ",") + " " + (kz.kosten_waehrung || "") : "—";
  var kurz = kac && kac.top3_anteil !== null && kac.top3_anteil !== undefined
    ? '<span class="kurz">teuerste 3 Runden = ' + (kac.top3_anteil * 100).toFixed(0) + " % der Kosten</span>" : "";
  return '<div class="gk"><span class="kern">Verbrauch</span><span class="hero">' + hero + "</span>"
    + deltaHtml(kpr, b && b.kosten_je_runde, true, b && b.n)
    + '<button type="button" class="hilfe-btn" aria-controls="h-kosten" aria-expanded="false" aria-label="Erklärung anzeigen">?</button>' + kurz + "</div>";
}

function verbrauchKostenPeakSatz(kac) {
  var runden = kac && kac.runden, top3 = kac && kac.top3_index;
  if (!runden || !top3 || !top3.length) return ". Auffällige Ausreißer sind der Prüfpunkt (Prozessbruch oder gewollter Subagent-Fan-out?).";
  var r = runden[top3[0]];
  if (!r) return ".";
  var med = kac.kosten_median_runde || median(runden.map(function (x) { return x.kosten || 0; }));
  var faktorTeil = med > 0 ? " = " + (r.kosten / med).toFixed(0) + "× der normalen Runde" : "";
  return ": Runde " + r.index + " kostete " + r.kosten.toFixed(0) + " $" + faktorTeil
    + " — solche Ausreißer sind der Prüfpunkt (Prozessbruch oder gewollter Subagent-Fan-out?).";
}

function verbrauchHilfeKostenHtml(kz, kac, b) {
  var n = kz.runden || 0;
  var gesamt = kz.kosten_gesamt !== null && kz.kosten_gesamt !== undefined ? kz.kosten_gesamt : kz.kosten;
  var kpr = n > 0 ? gesamt / n : 0;
  var benchTeil = b ? "Ø " + b.kosten_je_runde.toFixed(2) + " $" : "kein Ø verfügbar";
  var berechnung = "Summe über alle Modellaufrufe: Token × Listenpreis je Modell (Eingabe, Ausgabe, Cache-Lesen, "
    + "Cache-Schreiben; Preise aus <code>modelle.json</code>). Jeder Aufruf zählt einmal (je <code>message.id</code>). "
    + "Gesamt = Hauptagent + Subagenten (Aufteilung in der Zeile darunter). Der Vergleich Ø nimmt <b>Kosten je Runde</b> ("
    + kpr.toFixed(2) + " $ hier, " + benchTeil + "), damit lange und kurze Sitzungen vergleichbar sind.";
  var aussage = "Was die Sitzung an API-Listenpreis gekostet hätte. Die Balken zeigen, <i>wann</i> das Geld ausgegeben wurde"
    + verbrauchKostenPeakSatz(kac);
  return hilfeHtml("h-kosten", berechnung, aussage);
}

function verbrauchBandMarkup(kostenSvg, fehlerSvg, subSvg, n, compListe) {
  return '<div class="band">'
    + '<div class="spur"><span class="spur-l">Kosten / Runde</span>' + kostenSvg + "</div>"
    + '<div class="spur"><span class="spur-l">Tool-Fehler</span>' + fehlerSvg + "</div>"
    + '<div class="spur"><span class="spur-l">Subagent-Start</span>' + subSvg + "</div>"
    + '<div class="achse"><span>Runde 1</span><span>Runde ' + n + "</span></div>"
    + verbrauchLegendeHtml(compListe) + "</div>";
}

function verbrauchLegendeHtml(compListe) {
  return '<div class="legende">'
    + '<span><span class="lg"></span> Kosten je Runde</span>'
    + '<span><span class="lg lg-rot"></span> teuerste 3 Runden</span>'
    + '<span><span class="lg lg-dash"></span> Median dieser Sitzung</span>'
    + '<span><span class="lg lg-tick"></span> Tool-Fehler</span>'
    + '<span><span class="lg lg-tick lg-blau"></span> Subagent-Start</span>'
    + '<span><span class="lg lg-vline"></span> Compaction' + rundenListeText(compListe) + "</span></div>";
}

function verbrauchBandHtml(kac) {
  var runden = kac && kac.runden;
  if (!runden || !runden.length) return '<div class="band"><p class="caption">Verlauf je Runde nicht verfügbar.</p></div>';
  var n = runden.length;
  var kosten = runden.map(function (r) { return r.kosten || 0; });
  var fehler = runden.map(function (r) { return r.tool_fehler || 0; });
  var sub = runden.map(function (r) { return r.subagent_starts || 0; });
  var top3Pos = positionenVonRunden(runden, kac.top3_index);
  var compPos = compPositionen(runden);
  var med = kac.kosten_median_runde !== null && kac.kosten_median_runde !== undefined ? kac.kosten_median_runde : median(kosten);
  // 72 -> 62 (Nachtrag 2026-08-27 Punkt 10, Sichtung: Diagramme ~10-15% flacher).
  var kostenSvg = mitCompaction(balkenSvg(kosten, 62, top3Pos, med), n, compPos, 62);
  var fehlerSvg = mitCompaction(ticksSvg(fehler, 16, "var(--fehler)"), n, compPos, 16);
  var subSvg = mitCompaction(ticksSvg(sub, 16, "var(--primaer)"), n, compPos, 16);
  return verbrauchBandMarkup(kostenSvg, fehlerSvg, subSvg, n, compRunden(runden));
}

function verbrauchPaarTokenHtml(kz, kac, b) {
  var t = kz.token || {};
  var outK = (t.output || 0) / 1000, crM = (t.cache_read || 0) / 1e6;
  var proRunde = kz.runden ? (t.output || 0) / kz.runden : null;
  var w1 = '<span class="w">' + outK.toFixed(0) + "k</span>";
  var d1 = deltaHtml(proRunde, b && b.token_out_je_runde, true, b && b.n);
  var w2 = '<span class="w">' + crM.toFixed(1) + "M · " + cacheAnteilProzent(kz, kac).toFixed(0) + " % Cache</span>";
  var d2 = deltaChip("d-neutral", "Rabatt, kein Aufwand");
  return '<div class="paar">' + kzHtml("Token out", w1, d1, "h-out") + kzHtml("Cache-Read", w2, d2, "h-cache") + "</div>";
}

function verbrauchHilfeTokenHtml() {
  return hilfeHtml("h-out",
    "Summe der vom Modell erzeugten Token (Antworttext, Denken, Werkzeugaufrufe), einmal je Aufruf. Vergleich Ø je Runde.",
    "Wie viel das Modell geschrieben hat — der teuerste Token-Typ (Fable: 75 $/M). Hohe Werte bei wenigen Runden = lange Denk-/Schreibphasen.")
    + hilfeHtml("h-cache",
    "Cache-Read = Kontext-Token, die aus dem Prompt-Cache kamen (10 % des Eingabepreises). Cache-Anteil = Cache-Read ÷ (Eingabe + Cache-Schreiben + Cache-Read).",
    "Hoher Cache-Anteil ist gut: der Kontext wird wiederverwendet statt neu bezahlt. Sinkt er, wird jede Runde teurer (z. B. nach Compaction).");
}

function verbrauchPaarKostenHtml(kz, b) {
  var haupt = kz.kosten, sub = kz.kosten_subagenten || 0;
  var gesamt = kz.kosten_gesamt !== null && kz.kosten_gesamt !== undefined ? kz.kosten_gesamt : haupt;
  var prozent = gesamt ? (sub / gesamt * 100) : 0;
  var w1 = '<span class="w">' + (haupt !== null && haupt !== undefined ? haupt.toFixed(2) : "—") + " · " + sub.toFixed(2) + " " + (kz.kosten_waehrung || "") + "</span>";
  var d1 = deltaChip("d-neutral", prozent.toFixed(0) + " % delegiert");
  var w2 = '<span class="w">' + (kz.subagenten ?? 0) + " · Tiefe " + (kz.subagenten_max_tiefe ?? 1) + "</span>";
  var d2 = deltaHtml(kz.subagenten, b && b.subagenten, null, b && b.n);
  return '<div class="paar">' + kzHtml("Kosten Agent · Subagenten", w1, d1, "h-subk") + kzHtml("Subagenten", w2, d2, "h-sub") + "</div>";
}

function verbrauchPaarModelleHtml(kac) {
  var haupt = modelZeileHtml(kac && kac.modelle_haupt, "Aufrufe");
  var sub = modelZeileHtml(kac && kac.modelle_sub, "Agenten");
  return '<div class="paar">' + kzHtml("Modell Hauptagent", haupt, "", "h-modell", "kz-modelle")
    + kzHtml("Modelle Subagenten", sub, "", "h-modell-sub", "kz-modelle") + "</div>";
}

function verbrauchHilfeModelleHtml() {
  return hilfeHtml("h-modell",
    "Modellkennung je Antwortzeile der Hauptsitzung, gezählt je Aufruf. Wechseln Sie mitten in der Sitzung das Modell (z. B. Fable → Opus am Limit), stehen hier beide mit ihrer Aufrufzahl.",
    "Erklärt Kostenniveau und -sprünge: Fable kostet das 5-fache von Sonnet; ein Wechsel ist im Kostenverlauf als Stufe sichtbar.")
    + hilfeHtml("h-modell-sub",
    "Modell je Subagent aus dessen eigenem Transkript (volle Kennung), gruppiert und gezählt.",
    "Zeigt, ob delegiert wurde wie vorgesehen (Sonnet für Standard, Haiku für Mechanik) oder teure Modelle in Subagenten liefen.")
    + hilfeHtml("h-sub",
    "Anzahl der Unter-Agenten-Transkripte im Sitzungsordner; Tiefe = Verschachtelung (1 = direkt von der Hauptsitzung gestartet).",
    "Delegation kostet Geld und Zeit, spart aber Hauptkontext. Viele Starts in einer Runde erklären eine Kostenspitze (blaue Striche unter den Balken).");
}

function verbrauchHilfeSubkHtml(kz) {
  var gesamt = kz.kosten_gesamt !== null && kz.kosten_gesamt !== undefined ? kz.kosten_gesamt : kz.kosten;
  var prozent = gesamt ? ((kz.kosten_subagenten || 0) / gesamt * 100) : 0;
  return hilfeHtml("h-subk",
    "Hauptagent = Aufrufe der Hauptsitzung × Preis ihres Modells; Subagenten = Token jedes Subagent-Transkripts × Preis seines Modells. Summe = Hauptzahl oben.",
    "Wie viel vom Geld in Delegation floss. Hier " + prozent.toFixed(0) + " % des Gesamtbetrags.");
}

function verbrauchKarteHtml(kz, kac, b) {
  return '<div class="g kz-karte">' + verbrauchKopfHtml(kz, kac, b) + verbrauchHilfeKostenHtml(kz, kac, b)
    + verbrauchBandHtml(kac) + verbrauchPaarTokenHtml(kz, kac, b) + verbrauchHilfeTokenHtml()
    + verbrauchPaarKostenHtml(kz, b) + verbrauchPaarModelleHtml(kac)
    + verbrauchHilfeModelleHtml() + verbrauchHilfeSubkHtml(kz) + "</div>";
}

// ================= Karte "Ablauf" =================
function ablaufKopfHtml(kz, b) {
  var n = kz.runden || 0;
  var hero = n + " Runden · " + formatDauerLang(kz.dauer_ms);
  return '<div class="gk"><span class="kern">Ablauf</span><span class="hero">' + hero + "</span>"
    + deltaHtml(n, b && b.runden, null, b && b.n)
    + '<button type="button" class="hilfe-btn" aria-controls="h-runden" aria-expanded="false" aria-label="Erklärung anzeigen">?</button>'
    + '<span class="kurz">Wanduhr inkl. Pausen</span></div>';
}

function ablaufHilfeRundenHtml() {
  return hilfeHtml("h-runden",
    "Runden = Ihre Eingaben (jede Nutzerzeile, die kein reines Werkzeugergebnis ist). Dauer = Wanduhr vom ersten bis zum letzten inhaltlichen Turn, Pausen eingeschlossen.",
    "Wie lang und wie kleinteilig die Sitzung war. Kein Diagramm nötig — der Verlauf links zeigt den Ablauf.");
}

function ablaufLegendeHtml(compListe, timeoutListe) {
  return '<div class="legende">'
    + '<span><span class="lg lg-line"></span> Dauer je Runde</span>'
    + '<span><span class="lg lg-dot"></span> langsamste 3 Runden</span>'
    + '<span><span class="lg lg-ring"></span> Werkzeug-Timeout ≥ 120 s' + rundenListeText(timeoutListe) + "</span>"
    + '<span><span class="lg lg-dash"></span> Median</span>'
    + '<span><span class="lg lg-vline"></span> Compaction' + rundenListeText(compListe) + "</span></div>";
}

function ablaufBandHtml(kac) {
  var runden = kac && kac.runden;
  if (!runden || !runden.length) return '<div class="band"><p class="caption">Verlauf je Runde nicht verfügbar.</p></div>';
  var n = runden.length;
  var lat = runden.map(function (r) { return (r.dauer_ms || 0) / 1000; });
  var langsamPos = positionenVonRunden(runden, kac.langsamste_index);
  var timeoutPos = timeoutPositionen(runden);
  // 48 -> 42 (Nachtrag 2026-08-27 Punkt 10, Sichtung: Diagramme ~10-15% flacher).
  var svg = mitCompaction(linieSvg(lat, 42, langsamPos, timeoutPos, median(lat)), n, compPositionen(runden), 42);
  return '<div class="band"><div class="spur"><span class="spur-l">Rundendauer</span>' + svg + "</div>"
    + '<div class="achse"><span>Runde 1</span><span>Runde ' + n + "</span></div>"
    + ablaufLegendeHtml(compRunden(runden), timeoutRunden(runden)) + "</div>";
}

function ablaufPaarLatenzHtml(kz, b) {
  var w1 = '<span class="w">' + formatDauerLang(kz.latenz_p50_ms) + "</span>";
  var d1 = deltaHtml(kz.latenz_p50_ms, b && b.latenz_p50_ms, true, b && b.n);
  var w2 = '<span class="w">' + formatMin(kz.latenz_p95_ms) + " · max " + formatMin(kz.latenz_max_ms) + "</span>";
  var d2 = deltaHtml(kz.latenz_p95_ms, b && b.latenz_p95_ms, true, b && b.n);
  return '<div class="paar">' + kzHtml("Latenz p50", w1, d1, "h-p50") + kzHtml("Latenz p95", w2, d2, "h-p95") + "</div>";
}

function ablaufHilfeLatenzHtml(kz) {
  var p95min = Math.round((kz.latenz_p95_ms || 0) / 60000), p50s = Math.round((kz.latenz_p50_ms || 0) / 1000);
  return hilfeHtml("h-p50",
    "Alle Rundendauern (von Ihrer Eingabe bis zur Antwort) sortiert; p50 = der mittlere Wert: die Hälfte der Runden war schneller.",
    "Die typische Wartezeit. Eine Runde mit 30 s fühlt sich normal an, 3 min nicht.")
    + hilfeHtml("h-p95",
    "Dieselbe Sortierung; p95 = der Wert, unter dem 95 % aller Runden liegen — nur die langsamsten 5 % sind länger. max = die langsamste Runde.",
    "Wie schlimm die Ausreißer sind. Ein p95 von " + p95min + " min bei p50 von " + p50s + " s heißt: meist flott, aber einzelne Runden "
    + "(große Subagent-Aufträge, Timeouts) fressen die Zeit. Die roten Punkte im Verlauf zeigen, welche.");
}

function ablaufPaarToolsHtml(kz, b) {
  var proRunde = kz.runden ? (kz.tools || 0) / kz.runden : null;
  var quote = (kz.tool_fehlerquote || 0) * 100;
  var w1 = '<span class="w">' + (kz.tools ?? 0) + "</span>";
  var d1 = deltaHtml(proRunde, b && b.tools_je_runde, null, b && b.n);
  var w2 = '<span class="w">' + (kz.tool_fehler ?? 0) + " · " + quote.toFixed(1) + " %</span>";
  var d2 = deltaHtml(quote, b && b.tool_fehlerquote * 100, true, b && b.n);
  return '<div class="paar">' + kzHtml("Tools", w1, d1, "h-tools") + kzHtml("Tool-Fehler", w2, d2, "h-fehler") + "</div>";
}

function ablaufHilfeToolsHtml() {
  return hilfeHtml("h-tools",
    "Anzahl der Werkzeugaufrufe (Dateien lesen, Befehle, Suchen); Subagent-Starts zählen nicht mit. Vergleich Ø je Runde.",
    "Wie viel Handarbeit das Modell verrichtet hat. Weder gut noch schlecht — Kontext für die Fehlerquote.")
    + hilfeHtml("h-fehler",
    "Werkzeugaufrufe mit Fehlerergebnis ÷ alle Werkzeugaufrufe. Fehler = Befehl schlug fehl, Datei nicht gefunden, Guard hat blockiert.",
    "Der beste Prozess-Indikator: über Ø heißt, das Modell hat sich verrannt oder gegen Regeln gearbeitet. Rote Striche im Verbrauchsband zeigen, in welcher Runde.");
}

function ablaufPaarCompaktHtml(kz, kac) {
  var liste = compRunden((kac && kac.runden) || []);
  var w1 = '<span class="w">' + (kz.compactions ?? 0) + (liste.length ? " · Runde " + liste.join(", ") : "") + "</span>";
  var d1 = deltaChip("d-neutral", "Doppellinie oben");
  var kontext = kz.kontext_auslastung_max ? (kz.kontext_auslastung_max * 100).toFixed(0) + " %" : "nicht erfasst";
  var w2 = '<span class="w">' + kontext + "</span>";
  var d2 = deltaChip("d-neutral", "Fenster");
  return '<div class="paar">' + kzHtml("Compaction", w1, d1, "h-comp") + kzHtml("Kontext max", w2, d2, "h-ctx") + "</div>";
}

function ablaufHilfeKontextHtml() {
  return hilfeHtml("h-ctx",
    "Größter Kontextstand einer Runde (Eingabe + Cache) im Verhältnis zum Modellfenster.",
    "Wie nah die Sitzung an der Compaction war; nur belastbar, wenn die Quelle den Wert liefert.")
    + hilfeHtml("h-comp",
    "Zahl der Kontext-Verdichtungen (Claude Code fasst den Verlauf zusammen, wenn das Fenster voll ist) und in welcher Runde.",
    "Nach einer Compaction fehlt Detailwissen und der Cache ist leer — Kosten und Fehler steigen oft danach. Deshalb als Marker im Verbrauchsband.");
}

function ablaufKarteHtml(kz, kac, b) {
  return '<div class="g kz-karte">' + ablaufKopfHtml(kz, b) + ablaufHilfeRundenHtml()
    + ablaufBandHtml(kac) + ablaufPaarLatenzHtml(kz, b) + ablaufHilfeLatenzHtml(kz)
    + ablaufPaarToolsHtml(kz, b) + ablaufHilfeToolsHtml()
    + ablaufPaarCompaktHtml(kz, kac) + ablaufHilfeKontextHtml() + "</div>";
}
