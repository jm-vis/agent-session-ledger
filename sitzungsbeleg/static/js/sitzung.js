// Seite: Sitzung -- Kennzahlen-Kacheln, Verlauf-Zeitleiste + Sprung, Befunde + Erledigt-
// Formular, Vier Augen + Dissens-Entscheid, Delegation/Subagenten-Tabelle, Aktionen-Dropdown +
// Zweitmeinung-Dialog + Polling.
import {
  escapeHtml, capitalize, quelleChipHtml,
  formatDauerKurz, formatDauerLang, formatUhrzeit, formatDeVoll, formatEntscheidDatum,
  statusBadgeText,
} from "./format.js";
import { holeJSON, zeigeFehler } from "./api.js";
import { setzeTabelleScrollt } from "./tabellen.js";
import { renderKennzahlenKarten } from "./kacheln.js";
import { renderDelegationsKarte } from "./delegation.js";
import { oeffneRohdateiPanel } from "./rohdatei.js";
import { oeffneTiefenanalysePanel } from "./tiefenanalyse.js";
import { verankerungChipHtml } from "./verankerung.js";
import { erledigtFormularEinfuegen } from "./erledigt.js";

var aktuelleSitzungId = null;
var aktuelleBefundEntscheide = {};
var aktuelleAuffaelligkeiten = [];
// Phase 2 E (Befund-Prozess): C5-Felder aus GET /api/sitzung -- Gruppenstatus je Regel, aktuell
// laufende Pruef-Laeufe dieser Sitzung, plus das ALTE Vier-Augen-Bundle (Fallback fuer Sitzungen,
// die noch keinen neuen `pruefung/lauf` haben -- pruefung.py liest die Alt-Ereignisse noch nicht
// mit, siehe Bericht "Contract-Konflikt").
var aktuelleGruppenStatus = {};
var aktuellePruefungLaeuft = [];
var aktuelleVieraugenAlt = null;
// C13-Nachtrag (Meldungsspur, Maintainer 2026-08-28 14:30): fuer den erneuten renderVerlauf()-Aufruf,
// sobald die (asynchron nachgeladenen) Wache-Meldungen da sind -- siehe _ladeWacheMeldungen.
var aktuelleEreignisse = [];
var aktuelleSubagentenAnzahl = 0;

// ================= Seite: Sitzung =================
export function ladeSitzung(id) {
  aktuelleSitzungId = id;
  _holeSitzungMitUebergang(id, true);
}

// C1 Regel 5 (Uebergangsroute): `#sitzung/<n>` kann noch eine ALTE Version-ID sein (Link von
// vor der Migration) -- ein 404 auf /api/sitzung/<n> probiert EINMAL .../version/<n>, schreibt
// den Hash auf die logische ID um (kein Reload) und laedt von dort neu; ein zweites 404 zeigt
// die normale Fehlkarte. Rohes fetch() statt holeJSON(): nur so ist der HTTP-Status (404 vs.
// jeder andere Fehler) ohne Aenderung an api.js unterscheidbar.
function _holeSitzungMitUebergang(id, ersterVersuch) {
  fetch("/api/sitzung/" + encodeURIComponent(id)).then(function (antwort) {
    if (antwort.status === 404 && ersterVersuch) return _versucheUebergang(id);
    if (!antwort.ok) throw new Error("Sitzung " + id + " nicht gefunden");
    return antwort.json().then(function (daten) { _sitzungGeladen(id, daten); });
  }).catch(function (e) { if (id === aktuelleSitzungId) zeigeFehler("sitzung-inhalt", e); });
}

function _versucheUebergang(id) {
  return fetch("/api/sitzung/version/" + encodeURIComponent(id)).then(function (antwort) {
    if (!antwort.ok) throw new Error("Sitzung " + id + " nicht gefunden");
    return antwort.json();
  }).then(function (d) {
    if (id !== aktuelleSitzungId) return;
    aktuelleSitzungId = d.sitzung_logisch;
    history.replaceState(null, "", "#sitzung/" + d.sitzung_logisch);
    return _holeSitzungMitUebergang(d.sitzung_logisch, false);
  });
}

// Wache-Meldungen (C13-Nachtrag): eigener Fetch NACH dem Hauptrender, wie _ladePruefungOffen
// in start.js -- ein Fehler hier darf die Sitzungsseite nicht mitreissen.
function _ladeWacheMeldungen(id) {
  holeJSON("/api/sitzung/" + encodeURIComponent(id) + "/wache").then(function (antwort) {
    if (id !== aktuelleSitzungId) return;
    renderVerlauf(aktuelleEreignisse, aktuelleSubagentenAnzahl, aktuelleAuffaelligkeiten, antwort.meldungen || []);
  }).catch(function () { /* Verlauf bleibt ohne Wache-Marker sichtbar */ });
}

function _sitzungGeladen(id, daten) {
  // Sitzungswechsel waehrend des Ladens (Fund C.1): verwirft veraltete Antworten.
  if (id !== aktuelleSitzungId) return;
  renderSitzung(id, daten);
  _ladeWacheMeldungen(id);
  // C5 `pruefung_laeuft` steht schon in `daten` (GET /api/sitzung) -- ein eigener Statusabruf
  // wie beim Alt-Endpunkt entfaellt. Laeuft fuer diese Sitzung schon ein Lauf (Reload waehrend
  // Pruefung, z. B. F5), nimmt das Polling ihn hier wieder auf.
  (daten.pruefung_laeuft || []).forEach(function (lauf) { pollePruefungLauf(id, lauf.lauf_id, 0); });
}

function renderSitzung(id, daten) {
  document.getElementById("sitzung-inhalt").innerHTML = "";
  // Neue Sitzung beginnt oben (Block 3, 2026-08-27): der Scroll-Container behielt sonst den
  // Stand der vorigen Ansicht und die Kennzahl-Karten lagen ausserhalb des Sichtfelds.
  var scrollBereich = document.querySelector(".detail-scroll");
  if (scrollBereich) scrollBereich.scrollTop = 0;
  var kopf = daten.dokument.kopf || {};
  var kz = daten.dokument.kennzahlen || {};
  var erf = daten.dokument.erfassung || {};
  // Kompaktzeile (Mockup B, Entscheid 2026-08-26): "Nr. N · Projekt · Quelle-Badge ·
  // Datum · Uhrzeit · Sitzungs-ID gekuerzt" -- Datum und Uhrzeit als getrennte Segmente
  // statt eines kombinierten Zeitstempels, "·" statt "/" als Trenner.
  var startDatum = new Date(kopf.start);
  document.getElementById("sitzung-breadcrumb").innerHTML =
    '<span class="mono">Nr. ' + escapeHtml(String(id)) + '</span> · <a href="#start">' + escapeHtml(kopf.projekt_name || "Sitzung") + "</a> · " + quelleChipHtml(daten.quelle_anzeige || capitalize(kopf.quelle))
    + " · " + escapeHtml(isNaN(startDatum) ? "—" : formatDeVoll(startDatum)) + " · " + escapeHtml(formatUhrzeit(kopf.start))
    + ' · <span class="aktuell">' + escapeHtml((kopf.sitzung_id || "").slice(0, 14)) + "…</span>";

  renderStempelzeile(erf);
  renderKennzahlenKarten(id, kz);
  // Dritte Kennzahl-Karte (Phase 1 C, Auftrag "Delegation"): ersetzt den alten Fliesstext-
  // Baum (frueher hier direkt nach den Kacheln gerendert, siehe renderSubagenten unten).
  renderDelegationsKarte(id, kz);
  // Reihenfolge wichtig (Abnahme 2026-08-26, Auftrag B.6): aktuelleAuffaelligkeiten muss
  // VOR renderVerlauf stehen, damit die Zeitleiste weiss, welche Eintraege einen Befund-
  // Marker bekommen.
  aktuelleAuffaelligkeiten = daten.dokument.auffaelligkeiten || [];
  aktuelleBefundEntscheide = daten.befund_entscheide || {};
  aktuelleGruppenStatus = daten.gruppen_status || {};
  aktuellePruefungLaeuft = daten.pruefung_laeuft || [];
  aktuelleVieraugenAlt = daten.vieraugen || null;
  aktuelleEreignisse = daten.dokument.ereignisse || [];
  aktuelleSubagentenAnzahl = (daten.dokument.subagenten || []).length;
  renderVerlauf(aktuelleEreignisse, aktuelleSubagentenAnzahl, aktuelleAuffaelligkeiten, []);
  renderBefunde(id, aktuelleAuffaelligkeiten, aktuelleBefundEntscheide);
  renderVierAugen(daten.vieraugen, aktuelleBefundEntscheide);
  renderSubagenten(id, daten.dokument.subagenten || []);
}

// Erfassungsehrlichkeit (observed/derived/not_recorded/not_copied) -- eigenstaendig, seit die
// Kennzahlen nicht mehr im festen Kopf stehen (Layout-Entscheid: Kacheln sind hoch, gehoeren als
// erster Abschnitt in .detail-scroll, die Stempelzeile bleibt an ihrem Platz).
function renderStempelzeile(erf) {
  var teile = [];
  Object.keys(erf).forEach(function (k) {
    if (k === "unbekannt") return;
    teile.push("<span>" + escapeHtml(k) + "=" + escapeHtml(String(erf[k])) + "</span>");
  });
  document.getElementById("stempelzeile-inhalt").innerHTML = teile.join("<span>·</span>");
}

function beschreibeEreignis(e, istEnde) {
  if (e.art === "nutzer") return { glyph: "▸", text: "Nutzer — Runde gestartet", klasse: "" };
  if (e.art === "subagent") return { glyph: "◆", text: "Subagent gestartet" + (e.name ? ": " + e.name : ""), klasse: "" };
  if (e.art === "compaction") return { glyph: "●", text: "Compaction", klasse: "" };
  if (e.art === "tool_ergebnis" && e.fehler) {
    var sigKurz = e.signatur ? " (" + e.signatur.slice(0, 12) + ")" : "";
    return { glyph: "✗", text: "Tool-Fehler" + (e.fehlerklasse ? ": " + e.fehlerklasse : "") + sigKurz, klasse: "st-fehler" };
  }
  if (e.art === "runde_ende" && e.dauer_ms && e.dauer_ms > 60000) return { glyph: "▸", text: "Langsame Runde (" + formatDauerLang(e.dauer_ms) + ")", klasse: "st-warnung" };
  if (istEnde) return { glyph: "◆", text: "Ende der Sitzung", klasse: "st-erfolg" };
  return { glyph: "▸", text: e.art, klasse: "" };
}

// markant: Tool-Fehler, Subagent-Start, Compaction, langsame Runde, Start (erstes) und Ende
// (letztes Ereignis) — verhindert eine Zeitleiste mit einem Eintrag je Runde (>60 bei langen
// Sitzungen). "Alle Runden anzeigen" zeigt zusätzlich jede Nutzer-Runde.
function istMarkant(e, istErstes, istLetztes) {
  if (istErstes || istLetztes) return true;
  if (e.art === "subagent" || e.art === "compaction") return true;
  if (e.art === "tool_ergebnis" && e.fehler) return true;
  if (e.art === "runde_ende" && e.dauer_ms && e.dauer_ms > 60000) return true;
  return false;
}

// Verlauf-Sortierung (Feedback 2026-08-27): Standard "neueste zuerst" (absteigend), per
// Kopf-Knopf umschaltbar, Wahl bleibt geraeteweise in localStorage erhalten (kein Server-State
// noetig -- reine Anzeige-Reihenfolge).
var VERLAUF_SORT_SCHLUESSEL = "sitzungsbeleg.verlauf.sortierung";

function holeVerlaufSortierung() {
  try { return localStorage.getItem(VERLAUF_SORT_SCHLUESSEL) === "asc" ? "asc" : "desc"; }
  catch (e) { return "desc"; }
}

function setzeVerlaufSortierung(wert) {
  try { localStorage.setItem(VERLAUF_SORT_SCHLUESSEL, wert); } catch (e) { /* z. B. privater Modus */ }
}

// Pfeil zeigt die AKTUELLE Reihenfolge (gleiche Optik wie der Tabellen-Sortierpfeil ▼/▲ in
// start.js), Tooltip nennt die Wirkung eines Klicks statt nur den Ist-Zustand.
function verlaufSortKnopfBeschriftung(sortierung) {
  return sortierung === "desc"
    ? { glyph: "▼", titel: "Neueste zuerst — klicken für älteste zuerst" }
    : { glyph: "▲", titel: "Älteste zuerst — klicken für neueste zuerst" };
}

function verlaufZeileHtml(e, istLetztes, index, markerJeIndex) {
  var b = beschreibeEreignis(e, istLetztes);
  var marker = (markerJeIndex[index] || []).map(function (titel) {
    return '<span class="zl-marker">' + escapeHtml(titel) + "</span>";
  }).join("");
  return '<li class="zl-eintrag ' + b.klasse + '" data-ereignis-index="' + index + '"><span class="zl-punkt" aria-hidden="true">' + b.glyph + '</span>'
    + '<div class="zl-zeit">' + formatUhrzeit(e.zeit) + '</div>'
    + '<div class="zl-text">' + escapeHtml(b.text) + marker + '</div></li>';
}

// Springt aus einer Befund-Karte in den Verlauf (Abnahme 2026-08-26, Auftrag B.6):
// schaltet noetigenfalls auf "Alle Runden anzeigen" (das Zielereignis ist nicht immer
// "markant"), scrollt zum Eintrag und hebt ihn kurz hervor. Von renderVerlauf je Aufruf neu
// gesetzt -- eine Befund-Karte kennt nur den Ereignis-Index, nicht die aktuelle Filterung.
var verlaufSpringeZu = function () {};

// Wache-Marker (C13-Nachtrag): Meldungen kennen keinen ereignis_index, nur `zeit` -- Marker
// landet beim letzten Ereignis nicht nach der Meldung (0, wenn keins passt).
export function wacheMarkerJeIndex(ereignisse, meldungen) {
  var markerJeIndex = {};
  (meldungen || []).forEach(function (m) {
    var idx = 0;
    for (var i = 0; i < ereignisse.length; i++) {
      if (ereignisse[i].zeit && ereignisse[i].zeit <= m.zeit) idx = i; else break;
    }
    (markerJeIndex[idx] = markerJeIndex[idx] || []).push(m.text);
  });
  return markerJeIndex;
}

function renderVerlauf(ereignisse, subagentenAnzahl, auffaelligkeiten, wacheMeldungen) {
  var n = ereignisse.length;
  var runden = ereignisse.filter(function (e) { return e.art === "nutzer"; }).length;
  var ul = document.getElementById("verlauf-liste");
  var btn = document.getElementById("verlauf-alle-btn");
  var sortBtn = document.getElementById("verlauf-sort-btn");
  var alleAnzeigen = false;
  var sortierung = holeVerlaufSortierung();

  var markerJeIndex = {};
  (auffaelligkeiten || []).forEach(function (a) {
    if (!a.position || a.position.ereignis_index === null || a.position.ereignis_index === undefined) return;
    var idx = a.position.ereignis_index;
    (markerJeIndex[idx] = markerJeIndex[idx] || []).push(a.titel || a.regel);
  });
  var wacheMarker = wacheMarkerJeIndex(ereignisse, wacheMeldungen);
  Object.keys(wacheMarker).forEach(function (idx) {
    markerJeIndex[idx] = (markerJeIndex[idx] || []).concat(wacheMarker[idx]);
  });

  function zeichne() {
    var liste = ereignisse.filter(function (e, i) {
      return alleAnzeigen || istMarkant(e, i === 0, i === n - 1);
    });
    var indizes = [];
    ereignisse.forEach(function (e, i) { if (alleAnzeigen || istMarkant(e, i === 0, i === n - 1)) indizes.push(i); });
    // Nur die Anzeige-Reihenfolge drehen (Feedback 2026-08-27) -- "erstes"/"letztes"
    // bleiben an den chronologischen Positionen haengen (data-ereignis-index unveraendert),
    // damit der Befund-Sprung und die Markant-Regeln unabhaengig von der Sortierung bleiben.
    if (sortierung === "desc") { liste = liste.slice().reverse(); indizes = indizes.slice().reverse(); }
    ul.innerHTML = liste.length
      ? liste.map(function (e, k) {
          var i = indizes[k];
          return verlaufZeileHtml(e, i === n - 1, i, markerJeIndex);
        }).join("")
      : '<li class="caption">Keine auffälligen Zeitleisten-Ereignisse.</li>';
    if (runden > 0) {
      btn.hidden = false;
      btn.textContent = alleAnzeigen ? "Nur markante Ereignisse anzeigen" : "Alle Runden anzeigen (" + runden + ")";
    } else {
      btn.hidden = true;
    }
  }
  btn.onclick = function () { alleAnzeigen = !alleAnzeigen; zeichne(); };
  sortBtn.onclick = function () {
    sortierung = sortierung === "desc" ? "asc" : "desc";
    setzeVerlaufSortierung(sortierung);
    zeichneSortKnopf();
    zeichne();
  };
  function zeichneSortKnopf() {
    var b = verlaufSortKnopfBeschriftung(sortierung);
    sortBtn.textContent = b.glyph;
    sortBtn.title = b.titel;
    sortBtn.setAttribute("aria-label", b.titel);
  }
  zeichneSortKnopf();
  zeichne();

  verlaufSpringeZu = function (index) {
    if (!alleAnzeigen) { alleAnzeigen = true; zeichne(); }
    var li = ul.querySelector('li[data-ereignis-index="' + index + '"]');
    if (!li) return;
    // Manuell statt scrollIntoView (Feedback 2026-08-26): .verlauf-scroll ist jetzt der
    // Scroll-Container -- scrollIntoView beruecksichtigt auch die Seite als Scroll-Vorfahre
    // und verschiebt sie mit, obwohl nur die Verlaufsliste springen soll.
    var container = document.getElementById("verlauf-scroll");
    var liRect = li.getBoundingClientRect();
    var contRect = container.getBoundingClientRect();
    var relativTop = liRect.top - contRect.top + container.scrollTop;
    var ziel = relativTop - container.clientHeight / 2 + li.offsetHeight / 2;
    container.scrollTo({ top: Math.max(0, ziel), behavior: "smooth" });
    li.classList.add("zl-hervorgehoben");
    setTimeout(function () { li.classList.remove("zl-hervorgehoben"); }, 2000);
  };

  document.getElementById("rail-fussnote").textContent = subagentenAnzahl
    ? "→ " + subagentenAnzahl + " Subagenten — Tabelle weiter unten" : "";
}

// ---- Erledigt-Feature je Befund: ausgelagert nach erledigt.js (Code-Masse, 2026-08-28) ----
// Wrapper haelt den lokalen Entscheide-Zwischenspeicher aktuell, bevor die Stelle neu rendert.
function erledigtEinfuegen(slot, sitzungId, signatur, aufErfolg) {
  erledigtFormularEinfuegen(slot, sitzungId, signatur, function (detail) {
    aktuelleBefundEntscheide[signatur] = detail;
    aufErfolg(detail);
  });
}

// Befunde gruppiert nach Regel (Variante C, Entscheid 2026-08-27 -- Mockup
// _mock-varianten.html Abschnitt C): behebt die Wiederholung, wenn dieselbe Regel mehrfach
// zuschlaegt (frueher eine Karte je Treffer mit demselben Titel/Satz). Reine Funktion --
// fasst die flache Auffaelligkeiten-Liste zu Gruppen {regel, titel, kurz, bedeutung, was_tun,
// schwere, treffer} zusammen, ohne DOM-Zugriff.
var SCHWEREGRAD_RANG = { hoch: 3, warnung: 2, hinweis: 1 };

function gruppiereBefunde(auff) {
  var jeRegel = {}, reihenfolge = [];
  auff.forEach(function (a, i) {
    var regel = a.regel || "";
    if (!jeRegel[regel]) {
      jeRegel[regel] = {
        regel: regel, titel: a.titel || regel, kurz: a.kurz || a.bedeutung || "",
        bedeutung: a.bedeutung || "", was_tun: a.was_tun || "", schwere: a.schwere,
        treffer: [], ersterIndex: i,
      };
      reihenfolge.push(regel);
    }
    var g = jeRegel[regel];
    if ((SCHWEREGRAD_RANG[a.schwere] || 0) > (SCHWEREGRAD_RANG[g.schwere] || 0)) g.schwere = a.schwere;
    g.treffer.push(a);
  });
  return reihenfolge.map(function (r) { return jeRegel[r]; }).sort(function (x, y) {
    var diff = (SCHWEREGRAD_RANG[y.schwere] || 0) - (SCHWEREGRAD_RANG[x.schwere] || 0);
    return diff !== 0 ? diff : x.ersterIndex - y.ersterIndex;
  });
}

function gruppenSchwereKlasse(schwere) {
  return schwere === "hoch" ? "st-fehler" : schwere === "warnung" ? "st-warnung" : "";
}

// ---- C2 Status-Pille + Prüfen-Knopf je Gruppe (Phase 2 E) ----
var PILLE_LABEL = {
  offen: "Offen", in_pruefung: "In Prüfung", bestaetigt: "Bestätigt", verworfen: "Verworfen",
  dissens: "Dissens", erledigt: "Erledigt", obsolet: "Obsolet", rueckfall: "Rückfall",
};

function statusPilleHtml(status) {
  var text = PILLE_LABEL[status] || status;
  return '<span class="pille" data-status="' + escapeHtml(status) + '">' + escapeHtml(text) + "</span>";
}

// Alle DISTINCTEN Signaturen einer Gruppe (eine Regel kann mehrere Signaturen buendeln, z. B.
// verschiedene Werkzeuge -- C2 "Gruppe = alle Befunde einer Regel").
function distinctSignaturen(treffer) {
  var gesehen = {}, liste = [];
  treffer.forEach(function (a) { if (a.signatur && !gesehen[a.signatur]) { gesehen[a.signatur] = true; liste.push(a.signatur); } });
  return liste;
}

// Laeuft schon ein Lauf, der (mind.) eine dieser Signaturen umfasst? (C5 `pruefung_laeuft`,
// wieder aufgenommen nach Reload -- siehe `pollePruefungLauf`.)
function laufIdFuerSignaturen(signaturen) {
  var treffer = aktuellePruefungLaeuft.filter(function (l) {
    return (l.signaturen || []).some(function (s) { return signaturen.indexOf(s) !== -1; });
  })[0];
  return treffer ? treffer.lauf_id : null;
}

function gruppenAktionenHtml(regel, signaturen) {
  var status = aktuelleGruppenStatus[regel] || "offen";
  var laufId = laufIdFuerSignaturen(signaturen);
  var knopf = '<button type="button" class="ghost-btn gruppe-pruefen-btn" data-regel="' + escapeHtml(regel)
    + '" data-signaturen=\'' + escapeHtml(JSON.stringify(signaturen)) + "'"
    + (laufId ? " disabled" : "") + ">" + (laufId ? "Prüfung läuft …" : "Prüfen (Claude + Codex)") + "</button>";
  return '<span class="gk-rechts">' + statusPilleHtml(status) + knopf + "</span>";
}

// Kartenkopf (.gk): Titel in Schweregrad-Farbe, Zaehler "×N" (nur bei mehr als einem Treffer,
// Pill wie im Mockup), Roh-Signatur mono, ?-Hilfe, Kurz-Bedeutung, rechts Status-Pille + Prüfen.
function gruppenKopfHtml(g, hilfeId) {
  var anzahl = g.treffer.length > 1 ? '<span class="anzahl">×' + g.treffer.length + "</span>" : "";
  var hilfeBtn = g.was_tun || g.bedeutung
    ? '<button type="button" class="hilfe-btn" aria-controls="' + hilfeId + '" aria-expanded="false" aria-label="Erklärung anzeigen">?</button>'
    : "";
  var kurz = g.kurz ? '<span class="kurz">' + escapeHtml(g.kurz) + "</span>" : "";
  return '<div class="gk"><span class="kern">' + escapeHtml(g.titel) + "</span>" + anzahl
    + '<span class="befund-roh mono">' + escapeHtml(g.regel) + "</span>" + hilfeBtn + kurz
    + gruppenAktionenHtml(g.regel, distinctSignaturen(g.treffer)) + "</div>";
}

// ?-Hilfe: volle Bedeutung zuerst (eigener Absatz), dann "was tun" -- die Kurzform steht schon
// sichtbar im Kartenkopf, hier bleibt Platz fuer den vollen Erklaertext.
function gruppenHilfeHtml(g, hilfeId) {
  if (!g.was_tun && !g.bedeutung) return "";
  var bedeutung = g.bedeutung ? "<p>" + escapeHtml(g.bedeutung) + "</p>" : "";
  var wasTun = g.was_tun ? "<p>" + escapeHtml(g.was_tun) + "</p>" : "";
  return '<div class="hilfe-text" id="' + hilfeId + '" hidden>' + bedeutung + wasTun + "</div>";
}

// ---- Vier-Augen inline je Gruppe (Phase 2 E, C7 "Befund-Karte") ----
// Quelle bevorzugt das NEUE `a.pruefung` (C5, aus `pruefung.py`); ohne das faellt es auf das
// ALTE Vier-Augen-Bundle zurueck (`daten.vieraugen`, quelle=vieraugen/review) -- siehe
// Contract-Konflikt im Bericht: `pruefung.anreichern` liest die Alt-Ereignisse noch nicht mit,
// ohne diesen Fallback zeigte jede bereits geprüfte Alt-Sitzung faelschlich "Offen".
function pruefungAusAlt(regel, signatur) {
  var b = ((aktuelleVieraugenAlt || {}).befunde || []).filter(function (x) {
    return signatur ? x.signatur === signatur : x.regel === regel;
  })[0];
  if (!b) return null;
  return {
    claude: b.claude, codex: b.codex, ergebnis: b.status === "unklar" ? "dissens" : b.status,
    zweitmeinung: "eingeholt", eskaliert: false, begruendung_codex: b.begruendung_codex,
  };
}

function pruefungFuerSignatur(g, signatur) {
  var treffer = g.treffer.filter(function (a) { return a.signatur === signatur && a.pruefung; })[0];
  return (treffer && treffer.pruefung) || pruefungAusAlt(g.regel, signatur);
}

function urteilInlineHtml(quelle, urteil) {
  var mark = urteil === "ja" ? '<span class="mark ok">✓</span>' : urteil === "nein" ? '<span class="mark nein">✗</span>' : '<span class="mark">?</span>';
  var wort = urteil === "ja" ? "bestätigt" : urteil === "nein" ? "verworfen" : "unklar";
  return '<span class="urteil-inline">' + mark + " " + quelle + " " + wort + "</span>";
}

// "Codex nachholen" (C3, Nachtrag 2026-08-27 Punkt 2): `p.lauf_id` (jetzt im Urteil, C4) baut
// echtes `{stufe:2, lauf_ref}` -- der Server erzwingt damit Stufe 2, auch wenn die Kleinfehler-
// Ausnahme sonst erneut greifen wuerde (frueher: ersatzweise ein normaler Lauf ohne Garantie).
function codexTeilHtml(signatur, p) {
  if (p.zweitmeinung !== "ausgelassen") return '<span class="pfeil">·</span>' + urteilInlineHtml("Codex", p.codex);
  return '<span class="kennzeichen">ohne Zweitmeinung</span>'
    + '<button type="button" class="link-btn codex-nachholen-btn" data-signatur="' + escapeHtml(signatur)
    + '" data-lauf-id="' + escapeHtml(p.lauf_id || "") + '">Codex nachholen</button>';
}

function vierAugenAktionHtml(signatur, p) {
  if (p.ergebnis !== "dissens") return "";
  var entscheid = aktuelleBefundEntscheide[signatur];
  if (entscheid) {
    return '<span class="aktion-rechts dissens-label">Entscheid Maintainer · ' + escapeHtml(entscheid.status)
      + " · " + formatEntscheidDatum(entscheid.entschieden_am) + "</span>";
  }
  return '<span class="aktion-rechts"><button type="button" class="outline-btn va-entscheiden-btn" data-signatur="'
    + escapeHtml(signatur) + '">Entscheiden…</button><span class="erledigt-formular-slot"></span></span>';
}

function vierAugenZeileHtml(g, signatur, mehrere) {
  var p = pruefungFuerSignatur(g, signatur);
  if (!p) return "";
  var sigLabel = mehrere ? '<span class="signatur-label mono">' + escapeHtml(signatur) + "</span>" : "";
  var eskaliert = p.eskaliert ? '<span class="kennzeichen kennzeichen-eskaliert">eskaliert</span>' : "";
  var ergebnisText = { bestaetigt: "BESTÄTIGT", verworfen: "VERWORFEN", dissens: "DISSENS" }[p.ergebnis] || p.ergebnis;
  return '<div class="va-inline">' + sigLabel + urteilInlineHtml("Claude", p.claude) + codexTeilHtml(signatur, p)
    + '<span class="pfeil">→</span><span class="ergebnis ' + escapeHtml(p.ergebnis) + '">' + escapeHtml(ergebnisText) + "</span>"
    + eskaliert + vierAugenAktionHtml(signatur, p) + "</div>";
}

// Eine Zeile je Signatur MIT Urteil (0..n) -- ohne Urteil (noch nicht geprueft) erscheint hier
// nichts, die Status-Pille im Kartenkopf traegt dann schon "Offen"/"In Prüfung".
function vierAugenInlineHtml(g) {
  var signaturen = distinctSignaturen(g.treffer);
  return signaturen.map(function (sig) { return vierAugenZeileHtml(g, sig, signaturen.length > 1); }).join("");
}

// Wert + Einheit, mono, rechtsbuendig (feste 110px-Spalte kommt aus dem CSS-Grid von .tr).
// `einheit` fehlt, falls der Server noch nicht neu gestartet wurde (Frontend-Fallback).
function trefferWertHtml(a) {
  var einheit = a.einheit ? "<small>" + escapeHtml(a.einheit) + "</small>" : "";
  return '<span class="befund-wert">' + escapeHtml(a.wert || "") + einheit + "</span>";
}

// "Rohdatei ▸" (Phase 3 H, C5 GET /api/rohdatei/{sitzung}) oeffnet das Panel unter dieser Karte
// (rohdatei.js) -- data-ereignis-index traegt den Query-Parameter `position`.
function trefferPositionHtml(a) {
  if (!a.position) return '<div class="befund-pos"><span class="caption">Sitzung gesamt</span></div>';
  var sigAttr = escapeHtml(a.signatur || "");
  var pos = '<button type="button" class="link-btn befund-position-btn" data-ereignis-index="' + a.position.ereignis_index + '">Runde ' + a.position.runde + " · " + formatUhrzeit(a.position.zeit) + "</button>";
  var rohdatei = '<button type="button" class="link-btn rohdatei-link" data-ereignis-index="' + a.position.ereignis_index + '">Rohdatei ▸</button>';
  var tiefenanalyse = a.signatur
    ? '<button type="button" class="link-btn tiefenanalyse-link" data-ereignis-index="' + a.position.ereignis_index
      + '" data-signatur="' + sigAttr + '">Tiefenanalyse ▸</button>'
    : "";
  return '<div class="befund-pos">' + pos + rohdatei + tiefenanalyse + "</div>";
}

// Erledigt-Zweig je Treffer (Status != offen/rueckfall, Entscheid 2026-08-26): Badge statt
// Knopf, Vermerk/Begründung als eigene .detail-Zeilen unter der Treffer-Zeile (Auftrag B.5).
function trefferErledigtHtml(a, entscheid, sigAttr) {
  var badge = escapeHtml(entscheid.status) + " · " + formatEntscheidDatum(entscheid.entschieden_am);
  var vermerk = entscheid.vermerk ? '<div class="detail">' + escapeHtml(entscheid.vermerk) + "</div>" : "";
  var begruendung = entscheid.begruendung ? '<div class="detail">' + escapeHtml(entscheid.begruendung) + "</div>" : "";
  return '<div class="tr st-erledigt" data-signatur="' + sigAttr + '">' + trefferWertHtml(a) + trefferPositionHtml(a)
    + '<div class="befund-aktion"><span class="befund-badge">' + badge + "</span>"
    + verankerungChipHtml(entscheid.verankerung) + "</div>"
    + vermerk + begruendung + "</div>";
}

// Offener Zweig je Treffer: "rueckfall" bekommt zusaetzlich ein rotes Rückfall-Badge
// (Entscheid 2026-08-26, Auftrag 1), sonst der normale Erledigt…-Knopf.
function trefferOffenHtml(a, entscheid, sigAttr) {
  var istRueckfall = entscheid && entscheid.status === "rueckfall";
  var rueckfallBadge = istRueckfall ? '<span class="befund-badge befund-badge-rueckfall">Rückfall</span>' : "";
  var rueckfallZeile = istRueckfall ? '<div class="detail">' + escapeHtml(statusBadgeText(entscheid)) + "</div>" : "";
  var erledigtBtn = a.signatur ? '<button type="button" class="ghost-btn erledigt-btn" data-signatur="' + sigAttr + '">Erledigt…</button>' : "";
  return '<div class="tr" data-signatur="' + sigAttr + '">' + trefferWertHtml(a) + trefferPositionHtml(a)
    + '<div class="befund-aktion">' + rueckfallBadge + erledigtBtn + "</div>"
    + rueckfallZeile + '<div class="erledigt-formular-slot"></div></div>';
}

// Status "offen" (Wiedereröffnung) und "rueckfall" zaehlen wie "kein Entscheid" (Entscheid
// 2026-08-26) -- Treffer bleibt dann im offenen Zweig.
function trefferHtml(a, entscheide) {
  var entscheid = entscheide[a.signatur];
  var sigAttr = escapeHtml(a.signatur || "");
  if (entscheid && entscheid.status !== "offen" && entscheid.status !== "rueckfall") {
    return trefferErledigtHtml(a, entscheid, sigAttr);
  }
  return trefferOffenHtml(a, entscheid, sigAttr);
}

// Karte gilt als erledigt (ganz gedaempft) nur, wenn ALLE Treffer erledigt sind -- eine Karte
// kann offene und erledigte Treffer mischen (Soll-Abgrenzung gegen die einzelne Zeile).
function gruppeIstErledigt(g, entscheide) {
  return g.treffer.every(function (a) {
    var e = entscheide[a.signatur];
    return e && e.status !== "offen" && e.status !== "rueckfall";
  });
}

function befundGruppeHtml(g, entscheide, index) {
  var hilfeId = "hilfe-gruppe-" + index;
  var klasse = gruppeIstErledigt(g, entscheide) ? "st-erledigt" : gruppenSchwereKlasse(g.schwere);
  var treffer = g.treffer.map(function (a) { return trefferHtml(a, entscheide); }).join("");
  return '<li class="g ' + klasse + '" data-regel="' + escapeHtml(g.regel) + '">'
    + gruppenKopfHtml(g, hilfeId) + gruppenHilfeHtml(g, hilfeId) + vierAugenInlineHtml(g) + treffer + "</li>";
}

function istOffenerTreffer(a, entscheide) {
  var e = entscheide[a.signatur];
  return !(e && e.status !== "offen" && e.status !== "rueckfall");
}

// "Alle offenen prüfen" (Kompaktzeile ueber der Liste, Mockup M2) -- scope='sitzung' mit leerer
// Signaturliste laesst den Server selbst ermitteln, was noch offen ist (C5).
function aktualisiereAlleOffenKnopf(sitzungId, auff, entscheide) {
  var offene = auff.filter(function (a) { return istOffenerTreffer(a, entscheide); });
  var btn = document.getElementById("alle-offen-pruefen-btn");
  var hinweis = document.getElementById("alle-offen-pruefen-hinweis");
  var laufId = laufIdFuerSignaturen(distinctSignaturen(offene));
  hinweis.textContent = "";
  btn.hidden = offene.length === 0;
  btn.disabled = !!laufId;
  btn.textContent = laufId ? "Prüfung läuft …" : "Alle offenen prüfen (" + offene.length + ")";
  btn.onclick = function () {
    btn.disabled = true; btn.textContent = "Startet …";
    starteLauf(sitzungId, "sitzung", [], {
      aufStart: function () { btn.textContent = "Prüfung läuft …"; },
      aufFehler: function (msg) { btn.disabled = false; btn.textContent = "Alle offenen prüfen (" + offene.length + ")"; hinweis.textContent = msg; },
    });
  };
}

function renderBefunde(sitzungId, auff, entscheide) {
  var ul = document.getElementById("befunde-liste");
  entscheide = entscheide || {};
  aktualisiereAlleOffenKnopf(sitzungId, auff, entscheide);
  if (!auff.length) { ul.innerHTML = '<li class="caption">Keine Auffälligkeiten.</li>'; return; }
  var gruppen = gruppiereBefunde(auff);
  ul.innerHTML = gruppen.map(function (g, i) { return befundGruppeHtml(g, entscheide, i); }).join("");
  _verkabeleErledigtUndPosition(sitzungId, ul);
  _verkabeleGruppePruefen(sitzungId, ul);
  _verkabeleVierAugenInline(sitzungId, ul);
}

function _verkabeleErledigtUndPosition(sitzungId, ul) {
  Array.prototype.forEach.call(ul.querySelectorAll(".erledigt-btn"), function (btn) {
    btn.addEventListener("click", function () { oeffneErledigtFormular(sitzungId, btn); });
  });
  Array.prototype.forEach.call(ul.querySelectorAll(".befund-position-btn"), function (btn) {
    btn.addEventListener("click", function () {
      verlaufSpringeZu(Number(btn.getAttribute("data-ereignis-index")));
    });
  });
  Array.prototype.forEach.call(ul.querySelectorAll(".rohdatei-link"), function (btn) {
    btn.addEventListener("click", function () {
      var karte = btn.closest("li.g");
      oeffneRohdateiPanel(sitzungId, karte, Number(btn.getAttribute("data-ereignis-index")));
    });
  });
  _verkabeleTiefenanalyseLinks(sitzungId, ul);
}

// "Tiefenanalyse ▸" (Phase 3 I, C10 POST/GET /api/sitzung/{id}/tiefenanalyse) oeffnet das Panel
// unter dieser Karte (tiefenanalyse.js) -- eigene Funktion, damit `renderBefunde(...)` als
// Entschieden-Callback nicht `_verkabeleErledigtUndPosition` aufblaeht (Waechter Funktion>20).
function _verkabeleTiefenanalyseLinks(sitzungId, ul) {
  Array.prototype.forEach.call(ul.querySelectorAll(".tiefenanalyse-link"), function (btn) {
    btn.addEventListener("click", function () {
      var karte = btn.closest("li.g");
      oeffneTiefenanalysePanel(
        sitzungId, karte, btn.getAttribute("data-signatur"), Number(btn.getAttribute("data-ereignis-index")),
        function () { renderBefunde(sitzungId, aktuelleAuffaelligkeiten, aktuelleBefundEntscheide); }
      );
    });
  });
}

function _verkabeleGruppePruefen(sitzungId, ul) {
  Array.prototype.forEach.call(ul.querySelectorAll(".gruppe-pruefen-btn"), function (btn) {
    btn.addEventListener("click", function () {
      var signaturen = JSON.parse(btn.getAttribute("data-signaturen"));
      btn.disabled = true; btn.textContent = "Startet …";
      starteLauf(sitzungId, "befund", signaturen, {
        aufStart: function (schonGelaufen) { btn.textContent = schonGelaufen ? "Läuft bereits …" : "Prüfung läuft …"; },
        aufFehler: function (msg) { btn.disabled = false; btn.textContent = "Prüfen (Claude + Codex)"; window.alert("Prüfung nicht gestartet: " + msg); },
      });
    });
  });
}

function _verkabeleVierAugenInline(sitzungId, ul) {
  Array.prototype.forEach.call(ul.querySelectorAll(".codex-nachholen-btn"), function (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true; btn.textContent = "Startet …";
      var laufRef = btn.getAttribute("data-lauf-id") || null;
      starteLauf(sitzungId, "befund", [btn.getAttribute("data-signatur")], {
        stufe: laufRef ? 2 : null, laufRef: laufRef,
        aufFehler: function (msg) { btn.disabled = false; btn.textContent = "Codex nachholen"; window.alert("Nicht gestartet: " + msg); },
      });
    });
  });
  Array.prototype.forEach.call(ul.querySelectorAll(".va-entscheiden-btn"), function (btn) {
    btn.addEventListener("click", function () {
      var slot = btn.parentElement.querySelector(".erledigt-formular-slot");
      var signatur = btn.getAttribute("data-signatur");
      erledigtEinfuegen(slot, sitzungId, signatur, function () {
        renderBefunde(sitzungId, aktuelleAuffaelligkeiten, aktuelleBefundEntscheide);
      });
    });
  });
}

function oeffneErledigtFormular(sitzungId, btn) {
  var slot = btn.closest("div.tr").querySelector(".erledigt-formular-slot");
  var signatur = btn.getAttribute("data-signatur");
  erledigtEinfuegen(slot, sitzungId, signatur, function () {
    renderBefunde(sitzungId, aktuelleAuffaelligkeiten, aktuelleBefundEntscheide);
  });
}

function statusText(s) { return { bestaetigt: "bestätigt", verworfen: "verworfen", unklar: "unklar" }[s] || s; }
function statusKlasse(s) { return s === "bestaetigt" ? "st-erfolg" : "st-warnung"; }
function urteilHtml(zustimmung, begruendung) {
  var mark = zustimmung === "ja" ? '<span class="mark ok">✓</span>' : zustimmung === "nein" ? '<span class="mark nein">✗</span>' : '<span class="mark">?</span>';
  return '<span class="urteil">' + mark + "<span>" + escapeHtml(begruendung || zustimmung || "unklar") + "</span></span>";
}

// Ergebnis-Zelle Dissens (Abnahme 2026-08-26, Auftrag C.8): ohne Signatur laesst sich kein
// Entscheid schreiben (die API verlangt eine) -- dann bleibt es beim reinen Hinweis-Chip.
// Mit Signatur wird der Chip ein Knopf, der dasselbe Entscheid-Formular oeffnet wie bei den
// Befunden. Liegt schon ein Entscheid vor, zeigt die Zelle "Entscheid Maintainer · Status · Datum"
// + Vermerk statt des Knopfs.
function dissensErgebnisHtml(b, entscheid, index) {
  if (entscheid) {
    var vermerk = entscheid.vermerk ? '<span class="vieraugen-entscheid-vermerk">' + escapeHtml(entscheid.vermerk) + "</span>" : "";
    return '<span class="ergebnis-zelle"><span class="dissens-label">Entscheid Maintainer · '
      + escapeHtml(entscheid.status) + " · " + formatEntscheidDatum(entscheid.entschieden_am)
      + vermerk + "</span></span>";
  }
  if (!b.signatur) {
    return '<span class="ergebnis-zelle"><span class="dissens-label">Dissens → Entscheid Maintainer</span></span>';
  }
  return '<span class="ergebnis-zelle">'
    + '<button type="button" class="dissens-label" data-signatur="' + escapeHtml(b.signatur) + '" data-vieraugen-index="' + index + '">Dissens → Entscheid Maintainer</button>'
    + '<div class="erledigt-formular-slot"></div></span>';
}

function renderVierAugen(vieraugen, entscheide) {
  entscheide = entscheide || {};
  var zahl = document.getElementById("vieraugen-dissens-zahl");
  var body = document.getElementById("vieraugen-body");
  if (!vieraugen) {
    zahl.textContent = "";
    body.innerHTML = '<p class="caption">Noch nicht geprüft.</p>';
    return;
  }
  zahl.textContent = "— Dissens: " + (vieraugen.dissens ?? 0);
  var zeilen = (vieraugen.befunde || []).map(function (b, i) {
    var dissens = b.status === "dissens";
    var ergebnis = dissens
      ? dissensErgebnisHtml(b, entscheide[b.signatur], i)
      : '<span class="status-pille ' + statusKlasse(b.status) + '">' + escapeHtml(statusText(b.status)) + "</span>";
    return '<tr class="' + (dissens ? "dissens-zeile" : "") + '"><td>' + escapeHtml(b.regel) + "</td>"
      + "<td>" + urteilHtml(b.claude, b.begruendung_claude) + "</td>"
      + "<td>" + urteilHtml(b.codex, b.begruendung_codex) + "</td>"
      + "<td>" + ergebnis + "</td></tr>";
  }).join("");
  body.innerHTML = '<div class="table-wrap" style="margin-top:12px;"><table class="vier-augen-tabelle">'
    + "<thead><tr><th>Befund</th><th>Claude</th><th>Codex</th><th>Ergebnis</th></tr></thead>"
    + "<tbody>" + (zeilen || '<tr><td colspan="4" class="caption">Keine Befunde.</td></tr>') + "</tbody></table></div>";
  Array.prototype.forEach.call(body.querySelectorAll(".dissens-label[data-signatur]"), function (btn) {
    btn.addEventListener("click", function () {
      var slot = btn.parentElement.querySelector(".erledigt-formular-slot");
      var signatur = btn.getAttribute("data-signatur");
      erledigtEinfuegen(slot, aktuelleSitzungId, signatur, function () {
        renderVierAugen(vieraugen, aktuelleBefundEntscheide);
      });
    });
  });
}

function subagentZeileHtml(id, s, i) {
  var auftrag = s.auftrag || "";
  return '<tr class="zeile-klickbar"><td><a href="#subagent/' + id + "/" + i + '" class="zeilen-link">' + escapeHtml(s.typ || "—") + "</a></td>"
    + '<td class="auftrag-zelle" title="' + escapeHtml(auftrag) + '">' + escapeHtml(auftrag || "–") + "</td>"
    + '<td class="mono">' + escapeHtml(s.modell || "—") + "</td>"
    + '<td class="num">' + formatDauerKurz(s.dauer_ms) + "</td>"
    + '<td class="num">' + (s.tool_fehler ?? 0) + "</td>"
    + '<td class="' + (s.beleg === "observed" ? "beleg-ok" : "beleg-warn") + '">' + (s.beleg === "observed" ? "✓" : "ohne Beleg") + "</td></tr>";
}

// Der frühere Fließtext-Baum ("22 × general-purpose · Tiefe 1 …") entfällt seit Phase 1 C: die
// Delegations-Kennzahl-Karte oben (delegation.js) fasst Umfang/Wirkung zusammen. Offener Punkt:
// die alte "Delegation"-Abschnittshülle in index.html (`#subagent-baum`) gehört einem anderen
// Arbeitspaket und wird hier nicht entfernt.
function renderSubagenten(id, subagenten) {
  document.getElementById("subagenten-titel").innerHTML = "Subagenten <span class=\"caption\">— " + subagenten.length + "</span>";
  var tbody = document.getElementById("subagenten-body");
  tbody.innerHTML = subagenten.map(function (s, i) { return subagentZeileHtml(id, s, i); }).join("")
    || '<tr><td colspan="6" class="caption">Keine Subagenten.</td></tr>';
  setzeTabelleScrollt("subagenten-gitter", subagenten.length);
}

// ---- Pruefen je Gruppe/Sitzung (Phase 2 E, C5 POST /api/pruefung + GET /api/pruefung/{lauf_id}) ----
// Ersetzt das alte Kopf-Dropdown ("Aktionen ▾" -> "Zweitmeinung einholen" -> Bestaetigungsdialog
// -> Alt-Endpunkt POST/GET .../pruefen): das neue Frontend nutzt nur noch den C5-Regelwerk-Pfad,
// startet direkt am Knopf (kein Dialog, siehe Mockup M2) und laedt nach Abschluss die Sitzung neu.
function starteLauf(sitzungId, scope, signaturen, opts) {
  opts = opts || {};
  // stufe/laufRef (Nachtrag 2026-08-27 Punkt 2, "Codex nachholen"): nur gesetzt, wenn der
  // Aufrufer sie mitgibt -- die anderen beiden Aufrufer (Gruppe/"Alle offenen") lassen sie weg,
  // der Server entscheidet dann normal ueber Stufe 1/2 (C3).
  var body = { scope: scope, sitzung_logisch: Number(sitzungId), signaturen: signaturen };
  if (opts.stufe) { body.stufe = opts.stufe; body.lauf_ref = opts.laufRef; }
  fetch("/api/pruefung", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(function (antwort) {
    return antwort.json().then(function (d) { return { status: antwort.status, d: d }; });
  }).then(function (r) {
    if (r.status !== 202 && r.status !== 409) throw new Error(r.d.detail || ("HTTP " + r.status));
    if (opts.aufStart) opts.aufStart(r.status === 409);
    pollePruefungLauf(sitzungId, r.d.lauf_id, 0);
  }).catch(function (e) { if (opts.aufFehler) opts.aufFehler(e.message); });
}

// Poll-Muster wie das alte pollePruefung (Feedback 2026-08-26, Punkt 3c): 10 s-Intervall,
// Deckel ~10 Minuten, Guard gegen Sitzungswechsel vor jedem Callback. Bei Abschluss (fertig ODER
// Fehler) wird die GANZE Sitzung neu geladen (Auftrag) -- das setzt Pillen/Vier-Augen/Knopf-
// Zustaende automatisch aus den frischen Server-Daten zurueck, ohne Sonderfaelle im Frontend.
function pollePruefungLauf(sitzungId, laufId, versuch) {
  if (versuch > 60 || sitzungId !== aktuelleSitzungId) return;
  setTimeout(function () {
    if (sitzungId !== aktuelleSitzungId) return;
    holeJSON("/api/pruefung/" + encodeURIComponent(laufId)).then(function (status) {
      if (sitzungId !== aktuelleSitzungId) return;
      if (status.laeuft) { pollePruefungLauf(sitzungId, laufId, versuch + 1); return; }
      holeJSON("/api/sitzung/" + encodeURIComponent(sitzungId)).then(function (daten) {
        if (sitzungId === aktuelleSitzungId) renderSitzung(sitzungId, daten);
      });
    }).catch(function () { pollePruefungLauf(sitzungId, laufId, versuch + 1); });
  }, 10000);
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist. Die neuen Pruefen-Knoepfe (Gruppe +
// "Alle offenen") verkabeln sich pro Render in renderBefunde/aktualisiereAlleOffenKnopf, weil
// sie bei jedem Sitzungswechsel neu im DOM stehen -- hier bleibt nichts Statisches mehr uebrig.
export function initSitzung() {}
