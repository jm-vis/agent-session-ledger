// Proportionale Skalierung des 1880px-Rasters (CONTRACTS.md C7, Entscheid 6): drei Spalten
// bleiben auf jedem Rechner-Bildschirm sichtbar, nichts klappt auf/zu, kein horizontales
// Scrollen -- statt einzelne Spalten zu quetschen, wird die ganze Wurzel per CSS zoom (Fallback
// transform: scale) verkleinert. Unter 1280px greift die bestehende Handy-Regel (@media
// max-width: 768px u.a.) unveraendert -- diese Datei tut dort nichts.
var ENTWURFSBREITE = 1880;
var UNTERGRENZE = 1280;
var timer = null;

function faktorFuer(breite) {
  return Math.min(1, breite / ENTWURFSBREITE);
}

function zuruecksetzen() {
  var wurzel = document.documentElement;
  wurzel.style.zoom = "";
  wurzel.style.transform = "";
  wurzel.style.transformOrigin = "";
  wurzel.style.width = "";
}

function anwenden(faktor) {
  var wurzel = document.documentElement;
  if ("zoom" in wurzel.style) {
    wurzel.style.zoom = String(faktor);
    return;
  }
  // Fallback (Firefox/Safari ohne CSS-zoom): transform: scale an der Wurzel, Breite kompensiert
  // die Skalierung, damit kein horizontaler Scrollbalken durch die verkleinerte Bounding-Box entsteht.
  wurzel.style.transformOrigin = "top left";
  wurzel.style.transform = "scale(" + faktor + ")";
  wurzel.style.width = (100 / faktor) + "%";
}

function skaliere() {
  var breite = window.innerWidth;
  if (breite < UNTERGRENZE) { zuruecksetzen(); return; }
  anwenden(faktorFuer(breite));
}

function planeSkalierung() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(skaliere, 80);
}

// DOM-Verkabelung (gleiches Muster wie initRouter()/initZeitraum() in app.js).
export function initSkalierung() {
  skaliere();
  window.addEventListener("resize", planeSkalierung);
}
