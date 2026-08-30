// Seite "Fehlerbilder & Entscheide" (Phase 2 G) -- eine Zeile je Signatur ueber den gewaehlten
// Zeitraum (Regeltext, Sitzungen/Projekte, Status-Verteilung, Entscheid, Rueckfall), Zeile
// klick -> Drilldown (betroffene Sitzungen + "Fehlerbild pruefen" ueber alle Sitzungen + letzter
// Lauf). `querschnitt.js` ruft `renderFehlerbilderSeite()` von hier auf (dessen `ladeQuerschnitt`
// bleibt der Seiten-Einstieg, wie von `router.js` erwartet).
import { escapeHtml, formatZeitpunktLang, formatDeKurz, formatUhrzeit } from "./format.js";
import { holeJSON } from "./api.js";
import { setzeTabelleScrollt, passeTabelleHoeheAn } from "./tabellen.js";
import { verankerungAusFormular, verankerungChipHtml, verankerungFormularHtml, verankerungSichtbarSchalten } from "./verankerung.js";

var ENTSCHEID_TEXT = { erledigt: "Erledigt", obsolet: "Obsolet", offen: "Offen" };
var EINORDNUNG_TEXT = { sauber: "sauber gelöst", abgewichen: "abgewichen", halluziniert: "halluziniert" };
var offeneZeile = null; // Signatur der aktuell aufgeklappten Drilldown-Zeile (nur eine gleichzeitig)
var zeitraum = { von: null, bis: null }; // von ladeFehlerbilderSeite() gesetzt, Drilldown braucht denselben Zeitraum

function pilleHtml(status, text) {
  return '<span class="pille" data-status="' + escapeHtml(status) + '">' + escapeHtml(text || status) + "</span>";
}

function verteilungHtml(verteilung) {
  return Object.keys(verteilung).sort().map(function (st) {
    return pilleHtml(st, verteilung[st] + " " + st);
  }).join(" ");
}

function entscheidZelleHtml(e) {
  if (!e) return '<span class="caption">—</span>';
  var vermerk = e.vermerk ? '<div class="detail zwei-zeilen">' + escapeHtml(e.vermerk) + "</div>" : "";
  return '<div>' + escapeHtml(ENTSCHEID_TEXT[e.status] || e.status) + " " + verankerungChipHtml(e.verankerung) + "</div>" + vermerk;
}

// Nachtrag 2026-08-27 Punkt 4: `status_verteilung` traegt "rueckfall" schon als eigenen Eintrag
// (verteilungHtml zeigt dann z.B. "5 RUECKFALL") -- ein zusaetzliches "RÜCKFALL"-Badge daneben war
// eine Dopplung derselben Information, entfernt statt verdoppelt.
function zeileHtml(z) {
  var sig = escapeHtml(z.signatur);
  return '<tr class="fb-zeile" data-signatur="' + sig + '">'
    + "<td><div>" + escapeHtml(z.regeltext.titel) + '</div><span class="caption mono">' + sig + "</span></td>"
    + '<td class="num">' + z.anzahl_sitzungen + "</td>"
    + "<td>" + escapeHtml(z.projekte.join(", ")) + "</td>"
    + '<td class="mono">' + escapeHtml(formatZeitpunktLang(z.juengstes_vorkommen)) + "</td>"
    + "<td>" + verteilungHtml(z.status_verteilung) + "</td>"
    + '<td class="fb-entscheid-zelle">' + entscheidZelleHtml(z.gf_entscheid) + "</td>"
    + '<td><button type="button" class="link-btn fb-details-btn">Details</button></td>'
    + "</tr>"
    + '<tr class="fb-drilldown-zeile" hidden><td colspan="7"></td></tr>';
}

// Tabelle fuellt seit Layout-Reste R3 (2026-08-27) die Restflaeche bis zur Unterkante von
// .detail-mitte statt die Seite als Ganzes wachsen zu lassen -- gleiches Muster wie
// start.js renderSitzungenTabelle()/#sitzungen-koerper (tabellen.js passeTabelleHoeheAn()).
function renderTabelle(zeilen) {
  var tbody = document.getElementById("fehlerbild-body");
  if (!zeilen.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="caption" style="padding:16px;">Keine Fehlerbilder im gewählten Zeitraum.</td></tr>';
    passeTabelleHoeheAn("fehlerbild-koerper");
    setzeTabelleScrollt("fehlerbild-gitter", 0);
    return;
  }
  tbody.innerHTML = zeilen.map(zeileHtml).join("");
  Array.prototype.forEach.call(tbody.querySelectorAll(".fb-zeile"), function (tr) {
    tr.querySelector(".fb-details-btn").addEventListener("click", function () {
      oeffneDrilldown(tr.getAttribute("data-signatur"), tr.nextElementSibling);
    });
  });
  // zeilen.length zaehlt nur die sichtbaren .fb-zeile-Basiszeilen -- die zugehoerige
  // .fb-drilldown-zeile je Fehlerbild ist per [hidden] ohne Hoehe, bis sie aufgeklappt wird.
  var passendeZeilen = passeTabelleHoeheAn("fehlerbild-koerper");
  setzeTabelleScrollt("fehlerbild-gitter", zeilen.length, passendeZeilen);
}

function sitzungZeileHtml(s) {
  return '<li><a href="#sitzung/' + s.sitzung_logisch + '">' + s.sitzung_logisch + "</a> · "
    + escapeHtml(s.projekt) + " · " + escapeHtml(formatDeKurz(new Date(s.zeit))) + " "
    + escapeHtml(formatUhrzeit(s.zeit)) + " " + pilleHtml(s.status) + "</li>";
}

function tabelleZeileHtml(t) {
  return "<tr><td>" + '<a href="#sitzung/' + t.sitzung_logisch + '">' + t.sitzung_logisch + "</a></td><td>"
    + pilleHtml(t.einordnung, EINORDNUNG_TEXT[t.einordnung] || t.einordnung) + "</td></tr>";
}

function letzterLaufHtml(lauf) {
  if (!lauf) return '<p class="caption">Noch nicht über alle Sitzungen geprüft.</p>';
  var zeilen = (lauf.tabelle || []).map(tabelleZeileHtml).join("");
  var datei = lauf.datei ? '<p class="caption">Standardisierungsvorschlag: <span class="mono">' + escapeHtml(lauf.datei) + "</span></p>" : "";
  var fehler = lauf.fehler ? '<p class="fehlerhinweis">' + escapeHtml(lauf.fehler) + "</p>" : "";
  return '<p class="caption">Letzter sitzungsübergreifender Lauf: ' + escapeHtml(formatZeitpunktLang(lauf.gestartet)) + "</p>"
    + fehler
    + (zeilen ? '<table class="fb-ergebnis-tabelle"><thead><tr><th>Sitzung</th><th>Ergebnis</th></tr></thead><tbody>' + zeilen + "</tbody></table>" : "")
    + datei;
}

function drilldownHtml(d) {
  var sitzungen = d.sitzungen_liste.map(sitzungZeileHtml).join("");
  return '<div class="fb-drilldown">'
    + "<h4>Betroffene Sitzungen (" + d.sitzungen_liste.length + ")</h4>"
    + '<ul class="fb-sitzungen-liste">' + sitzungen + "</ul>"
    + "<h4>Über alle Sitzungen geprüft</h4>"
    + '<div class="fb-letzter-lauf">' + letzterLaufHtml(d.letzter_fehlerbild_lauf) + "</div>"
    + '<button type="button" class="outline-btn fb-pruefen-btn">Fehlerbild prüfen (alle Sitzungen)</button>'
    + '<p class="fb-pruefen-status caption" hidden></p>'
    + entscheidFormularHtml()
    + "</div>";
}

// Gleiche Klassen wie sitzung.js `erledigtFormularHtml()`/start.js `fehlerbildErledigtFormularHtml()`
// (`.erledigt-formular`, `.zeile`, `.erledigt-fehler` -- schon in style.css gestylt, siehe Bericht:
// eine dritte Kopie statt Import, wie start.js es fuer sein eigenes Fehlerbild-Formular auch haelt).
function entscheidFormularHtml() {
  return '<div class="erledigt-formular">'
    + '<label>Status<select class="fb-ef-status"><option value="erledigt">erledigt</option>'
    + '<option value="obsolet">obsolet</option><option value="offen">offen (Wiedereröffnung)</option></select></label>'
    + '<label>Vermerk<input type="text" class="fb-ef-vermerk" maxlength="500"></label>'
    + '<label>Begründung<input type="text" class="fb-ef-begruendung" maxlength="500"></label>'
    + verankerungFormularHtml()
    + '<p class="erledigt-fehler" hidden></p>'
    + '<div class="zeile"><button type="button" class="outline-btn fb-ef-absenden" data-verankerung-knopf>Speichern</button></div>'
    + "</div>";
}

// Entscheid gilt GLOBAL fuer die Signatur (sitzung_ref: null) -- ein Fehlerbild fasst ALLE
// Sitzungen zusammen, wie start.js `sendeFehlerbildErledigt` fuer die Start-Kachel.
function _entscheidBody(signatur, zelle) {
  return {
    signatur: signatur, status: zelle.querySelector(".fb-ef-status").value,
    vermerk: zelle.querySelector(".fb-ef-vermerk").value, begruendung: zelle.querySelector(".fb-ef-begruendung").value,
    sitzung_ref: null, verankerung: verankerungAusFormular(zelle),
  };
}

function sendeEntscheid(signatur, zelle) {
  var fehlerEl = zelle.querySelector(".erledigt-fehler");
  var knopf = zelle.querySelector(".fb-ef-absenden");
  fehlerEl.hidden = true;
  knopf.disabled = true;
  fetch("/api/befund/entscheid", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(_entscheidBody(signatur, zelle)),
  }).then(function (antwort) {
    if (!antwort.ok) return antwort.json().then(function (d) { throw new Error(d.detail || ("HTTP " + antwort.status)); });
    return antwort.json();
  }).then(function () { ladeFehlerbilderSeite(zeitraum.von, zeitraum.bis); }).catch(function (e) {
    fehlerEl.textContent = e.message;
    fehlerEl.hidden = false;
    knopf.disabled = false;
  });
}

// Polling wie beim bestehenden Vier-Augen-Muster (`GET /api/sitzung/{id}/pruefen`), hier gegen
// `GET /api/pruefung/{lauf_id}` (C5) -- 1,5 s Takt, bis `laeuft: false`.
function pollePruefung(lauf_id, zelle) {
  var statusEl = zelle.querySelector(".fb-pruefen-status");
  holeJSON("/api/pruefung/" + lauf_id, {}).then(function (antwort) {
    if (antwort.laeuft) { setTimeout(function () { pollePruefung(lauf_id, zelle); }, 1500); return; }
    statusEl.hidden = true;
    zelle.querySelector(".fb-letzter-lauf").innerHTML = letzterLaufHtml(antwort.ergebnis);
    zelle.querySelector(".fb-pruefen-btn").disabled = false;
  }).catch(function (e) { statusEl.textContent = "Fehler: " + e.message; });
}

function starteFehlerbildPruefung(signatur, zelle) {
  var knopf = zelle.querySelector(".fb-pruefen-btn");
  var statusEl = zelle.querySelector(".fb-pruefen-status");
  knopf.disabled = true;
  statusEl.hidden = false;
  statusEl.textContent = "Prüfung läuft…";
  fetch("/api/pruefung", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope: "fehlerbild", sitzung_logisch: null, signaturen: [signatur] }),
  }).then(function (antwort) {
    if (!antwort.ok) return antwort.json().then(function (d) { throw new Error(d.detail || ("HTTP " + antwort.status)); });
    return antwort.json();
  }).then(function (start) { pollePruefung(start.lauf_id, zelle); }).catch(function (e) {
    statusEl.textContent = "Fehler: " + e.message;
    knopf.disabled = false;
  });
}

function verkabeleDrilldown(signatur, zelle) {
  zelle.querySelector(".fb-pruefen-btn").addEventListener("click", function () {
    starteFehlerbildPruefung(signatur, zelle);
  });
  verankerungSichtbarSchalten(zelle, zelle.querySelector(".fb-ef-status").value);
  zelle.querySelector(".fb-ef-status").addEventListener("change", function () { verankerungSichtbarSchalten(zelle, this.value); });
  zelle.querySelector(".v-pfad").addEventListener("input", function () {
    verankerungSichtbarSchalten(zelle, zelle.querySelector(".fb-ef-status").value);
  });
  zelle.querySelector(".fb-ef-absenden").addEventListener("click", function () {
    sendeEntscheid(signatur, zelle);
  });
}

function oeffneDrilldown(signatur, zeile) {
  var zelle = zeile.querySelector("td");
  if (offeneZeile === signatur) {
    zeile.hidden = true;
    offeneZeile = null;
    return;
  }
  offeneZeile = signatur;
  document.querySelectorAll(".fb-drilldown-zeile").forEach(function (z) { z.hidden = true; });
  zelle.innerHTML = '<p class="ladehinweis">Lädt…</p>';
  zeile.hidden = false;
  holeJSON("/api/fehlerbild/" + encodeURIComponent(signatur), zeitraum).then(function (d) {
    zelle.innerHTML = drilldownHtml(d);
    verkabeleDrilldown(signatur, zelle);
  }).catch(function (e) {
    zelle.innerHTML = '<p class="fehlerhinweis">Fehler beim Laden: ' + escapeHtml(e.message) + "</p>";
  });
}

export function ladeFehlerbilderSeite(von, bis) {
  zeitraum = { von: von, bis: bis };
  offeneZeile = null;
  holeJSON("/api/fehlerbilder", zeitraum)
    .then(renderTabelle)
    .catch(function (e) {
      document.getElementById("fehlerbild-body").innerHTML =
        '<tr><td colspan="7" class="fehlerhinweis">Fehler beim Laden.</td></tr>';
      passeTabelleHoeheAn("fehlerbild-koerper");
      console.error(e);
    });
}

// Resize (Layout-Reste R3, 2026-08-27, gleiches Debounce-Muster wie start.js
// planeHoeheAnpassen()): die passende Zeilenzahl haengt von der Fensterhoehe ab. Laeuft
// unabhaengig davon, ob die Seite gerade aktiv ist -- harmlos (naechster Seitenaufruf misst neu),
// gleiches Vorgehen wie der bestehende globale Resize-Listener der Startseite.
var hoeheAnpassenTimer = null;
window.addEventListener("resize", function () {
  clearTimeout(hoeheAnpassenTimer);
  hoeheAnpassenTimer = setTimeout(function () {
    var koerper = document.getElementById("fehlerbild-koerper");
    if (!koerper) return;
    var anzahlZeilen = koerper.querySelectorAll("tbody tr.fb-zeile").length;
    var passendeZeilen = passeTabelleHoeheAn("fehlerbild-koerper");
    setzeTabelleScrollt("fehlerbild-gitter", anzahlZeilen, passendeZeilen);
  }, 150);
});
