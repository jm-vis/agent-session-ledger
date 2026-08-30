// Seite: Einstellungen -- Schalter "Ausgeblendete Projekte zeigen" (wirkt auf die Start-
// Filterliste in start.js) plus die Preistabelle im Katalog-Look (reine Funktionen in
// preistabelle.js, DOM-frei und node-testbar; hier nur Zustand + Verdrahtung).
import { holeJSON, zeigeFehler } from "./api.js";
import { zeigeAusgeblendeteProjekte, setzeZeigeAusgeblendeteProjekte } from "./zustand.js";
import { renderFilterPanel, renderSitzungenTabelle, letzteProjekteRoh } from "./start.js";
import { ladeModellkatalog, initModellkatalog, katalogSnapshot } from "./katalog.js";
import { bauePreisEintraege, sortierePreise, preisZeileHtml } from "./preistabelle.js";

var ausgeblendeteCheckbox;
var preisRoh = null;           // Antwort von /api/preise (unveraendert)
var preisSort = { spalte: "modell", richtung: 1 };

function renderPreistabelle() {
  var body = document.getElementById("preistabelle-body");
  if (!body || !preisRoh) return;
  var snapshot = katalogSnapshot();
  var rows = sortierePreise(
    bauePreisEintraege(preisRoh.preise, snapshot.alle, snapshot.personaWege, preisRoh.stand),
    preisSort.spalte, preisSort.richtung);
  markierePreisSort();
  body.innerHTML = rows.length
    ? rows.map(preisZeileHtml).join("")
    : '<tr><td colspan="8" class="caption">Keine Preistabelle hinterlegt.</td></tr>';
  passePreisHoeheAn();
}

// Hoehe des Tabellenkoerpers EXAKT bis zur Unterkante der festen Mittelspalte (Maintainer 2026-08-30
// Nachtrag 2, zweimal nachgefragt "bis unten buendig wie rechts und links"): der Inhalt
// scrollt innen, darum ist eine angeschnittene letzte Zeile am unteren Rand hier bewusst
// kein Fehler (anders als der Befund 2026-08-28 beim Katalog, wo die Tabelle UNTER den
// Viewport lief). Bezugskante = Unterkante von .detail-mitte, nicht die Seite.
function passePreisHoeheAn() {
  var koerper = document.getElementById("preistabelle-koerper");
  if (!koerper || !koerper.offsetParent) return;   // versteckter Abschnitt
  var mitte = document.querySelector("#page-einstellungen .hauptspalte");
  if (!mitte) return;
  var verfuegbar = mitte.getBoundingClientRect().bottom - koerper.getBoundingClientRect().top - 1;
  // skalierung.js zoomt die Wurzel (z. B. 0,981 bei 1845px): getBoundingClientRect liefert
  // Post-zoom-Pixel, style.maxHeight erwartet Pre-zoom-CSS-Pixel (Live-Befund 2026-08-30:
  // Koerper 13px zu kurz) -- darum durch den Faktor teilen, wie die Katalog-Hoehenrechnung
  // es still ueber window.innerHeight macht.
  var zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  koerper.style.maxHeight = Math.max(100, Math.floor(verfuegbar / zoom)) + "px";
}

function markierePreisSort() {
  var gitter = document.getElementById("preistabelle-gitter");
  if (!gitter) return;
  gitter.querySelectorAll(".th-sort").forEach(function (knopf) {
    var th = knopf.closest("th"), pfeil = knopf.querySelector(".sort-arrow");
    if (knopf.getAttribute("data-col") === preisSort.spalte) {
      th.setAttribute("aria-sort", preisSort.richtung === 1 ? "ascending" : "descending");
      pfeil.textContent = preisSort.richtung === 1 ? "▲" : "▼";
    } else {
      th.setAttribute("aria-sort", "none");
      pfeil.textContent = "";
    }
  });
}

function wirePreisSort() {
  var gitter = document.getElementById("preistabelle-gitter");
  if (!gitter) return;
  gitter.querySelectorAll(".th-sort").forEach(function (knopf) {
    knopf.addEventListener("click", function () {
      var spalte = knopf.getAttribute("data-col");
      preisSort.richtung = preisSort.spalte === spalte ? preisSort.richtung * -1 : 1;
      preisSort.spalte = spalte;
      renderPreistabelle();
      var koerper = document.getElementById("preistabelle-koerper");
      if (koerper) koerper.scrollTop = 0;  // Snap nach oben wie in katalog.js/start.js
    });
  });
}

export function ladeEinstellungen() {
  ausgeblendeteCheckbox.checked = zeigeAusgeblendeteProjekte();
  ladeModellkatalog();
  holeJSON("/api/preise").then(function (daten) {
    document.getElementById("preistabelle-waehrung").textContent = daten.waehrung || "—";
    preisRoh = daten;
    renderPreistabelle();
  }).catch(function (e) { zeigeFehler("preistabelle-body", e); });
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist.
export function initEinstellungen() {
  initModellkatalog();
  ausgeblendeteCheckbox = document.getElementById("einst-ausgeblendete-zeigen");
  ausgeblendeteCheckbox.checked = zeigeAusgeblendeteProjekte();
  ausgeblendeteCheckbox.addEventListener("change", function () {
    setzeZeigeAusgeblendeteProjekte(ausgeblendeteCheckbox.checked);
    if (letzteProjekteRoh.length) {
      renderFilterPanel({ projekte: letzteProjekteRoh });
      renderSitzungenTabelle();
    }
  });
  wirePreisSort();
  // "pt-aktualisieren-btn" wird nicht hier verdrahtet: katalog.js wireAktualisieren()
  // fasst alle [data-aktualisieren-btn] -- EINE Kette fuer beide Sichten (Vorgabe
  // 2026-08-30 Nachtrag). Katalog-Reload (auch durch den Update-Knopf) -> Preistabelle
  // neu matchen/rendern.
  document.addEventListener("katalog:geladen", renderPreistabelle);
  // Abschnitt wurde erst nach dem Rendern eingeblendet -> versteckte Boxes haben
  // offsetParent null, die Hoehe blieb auf dem CSS-Fallback (Fund 2026-08-30).
  document.addEventListener("einst:abschnitt", renderPreistabelle);
  window.addEventListener("resize", passePreisHoeheAn);
}
