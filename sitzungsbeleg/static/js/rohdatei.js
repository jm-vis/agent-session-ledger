// Rohdatei-Panel (Phase 3 H, C5 GET /api/rohdatei/{sitzung}): letzter, lokaler Blick auf den
// Original-Transkriptausschnitt direkt unter der Befund-Karte (Mockup M3). Nichts wird hier
// zwischengespeichert -- jeder Klick auf "mehr" fragt den Server erneut, so fluechtig wie die
// Antwort selbst (C5: "nie in DB, nie in Logs").
import { escapeHtml } from "./format.js";

var AKTUELLES_PANEL = null; // { sitzungId, karte, index, umfang, element }

function zeileHtml(z) {
  return '<div class="rohdatei-zeile"><span class="rohdatei-index mono">#' + z.index + "</span>"
    + '<span class="rohdatei-typ">' + escapeHtml(z.typ) + "</span>"
    + '<span class="rohdatei-text mono">' + escapeHtml(z.text) + "</span></div>";
}

function panelInhaltHtml(daten) {
  var zeilen = daten.zeilen.map(zeileHtml).join("") || '<p class="caption">Keine Zeilen im Ausschnitt.</p>';
  return '<div class="warnbanner"><span aria-hidden="true">⚠</span><span>' + escapeHtml(daten.warnung) + "</span></div>"
    + '<p class="rohdatei-pfad mono">' + escapeHtml(daten.pfad_anzeige) + "</p>"
    + '<div class="rohdatei-zeilen">' + zeilen + "</div>"
    + '<div class="rohdatei-aktionen">'
    + '<button type="button" class="ghost-btn rohdatei-mehr-btn">±' + daten.umfang + " mehr</button>"
    + '<button type="button" class="ghost-btn rohdatei-schliessen-btn">Schließen</button></div>';
}

function fehlerHtml(status, meldung) {
  if (status === 423) {
    return '<div class="warnbanner warnbanner-gesperrt"><span aria-hidden="true">🔒</span>'
      + "<span>Geschützte Sitzung, Rohdatei nur lokal per Terminal.</span></div>";
  }
  return '<p class="fehlerhinweis">Rohdatei nicht geladen: ' + escapeHtml(meldung || "unbekannter Fehler") + "</p>";
}

function ladeUndZeige(panel) {
  var url = "/api/rohdatei/" + encodeURIComponent(panel.sitzungId)
    + "?position=" + encodeURIComponent(panel.index) + "&umfang=" + encodeURIComponent(panel.umfang);
  fetch(url).then(function (antwort) {
    return antwort.json().then(function (d) { return { status: antwort.status, d: d }; });
  }).then(function (r) {
    if (!panel.element.isConnected) return;
    panel.element.innerHTML = r.status === 200 ? panelInhaltHtml(r.d) : fehlerHtml(r.status, r.d.detail);
    if (r.status === 200) _verkabelePanel(panel);
  }).catch(function (e) {
    if (panel.element.isConnected) panel.element.innerHTML = fehlerHtml(0, e.message);
  });
}

function _verkabelePanel(panel) {
  var mehr = panel.element.querySelector(".rohdatei-mehr-btn");
  if (mehr) mehr.addEventListener("click", function () {
    panel.umfang = Math.min(50, panel.umfang + 5);
    ladeUndZeige(panel);
  });
  var schliessen = panel.element.querySelector(".rohdatei-schliessen-btn");
  if (schliessen) schliessen.addEventListener("click", schliessePanel);
}

function schliessePanel() {
  if (AKTUELLES_PANEL) AKTUELLES_PANEL.element.remove();
  AKTUELLES_PANEL = null;
}

// Oeffnet/schliesst das Panel direkt unter der Befund-Karte `karte` (`<li class="g">`) -- ein
// zweiter Klick auf denselben Treffer schliesst es wieder (Toggle), ein Klick auf einen anderen
// Treffer ersetzt es. `ereignisIndex` ist `a.position.ereignis_index` (C5 Query-Parameter `position`).
export function oeffneRohdateiPanel(sitzungId, karte, ereignisIndex) {
  var warKarte = AKTUELLES_PANEL && AKTUELLES_PANEL.karte === karte && AKTUELLES_PANEL.index === ereignisIndex;
  schliessePanel();
  if (warKarte || !karte) return;
  var li = document.createElement("li");
  li.className = "rohdatei-panel-item";
  li.innerHTML = '<p class="caption">Lade Rohdatei …</p>';
  karte.insertAdjacentElement("afterend", li);
  AKTUELLES_PANEL = { sitzungId: sitzungId, karte: karte, index: ereignisIndex, umfang: 5, element: li };
  ladeUndZeige(AKTUELLES_PANEL);
}
