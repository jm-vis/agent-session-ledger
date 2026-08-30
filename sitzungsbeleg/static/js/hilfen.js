// Seitenübergreifend: Darstellungs-Umschalter (Theme-Toggle), ?-Hilfe-Icons (Event-Delegation)
// und die reale Kopfhöhe (--kopf-hoehe), die .seitenleiste/.rail-spalte/.start-mitte/
// .detail-mitte für ihr sticky-Verhalten brauchen.

// ================= Darstellungs-Umschalter (dreiteiliges Icon-Segment, Mockup A) ==================
var STORAGE_KEY = "sitzungsbeleg-theme";
var themeGueltig = ["system", "light", "dark"];
var root = document.documentElement;
var themeSegs;

function liesGespeichertesTheme() {
  try {
    var wert = localStorage.getItem(STORAGE_KEY);
    if (wert && themeGueltig.indexOf(wert) !== -1) return wert;
  } catch (e) { /* localStorage nicht verfuegbar */ }
  return "system";
}
function setzeTheme(modus) {
  if (modus === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", modus);
  themeSegs.forEach(function (seg) {
    seg.setAttribute("aria-pressed", String(seg.getAttribute("data-theme-val") === modus));
  });
  try { localStorage.setItem(STORAGE_KEY, modus); } catch (e) { /* stumm */ }
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist.
export function initHilfen() {
  themeSegs = document.querySelectorAll(".theme-seg");
  setzeTheme(liesGespeichertesTheme());
  themeSegs.forEach(function (seg) {
    seg.addEventListener("click", function () { setzeTheme(seg.getAttribute("data-theme-val")); });
  });

  // ================= Hilfe-Icons =================
  // Event-Delegation statt Direkt-Bindung (Abnahme 2026-08-26, Auftrag B.4): Befunde-Karten
  // und die Vier-Augen-Tabelle erzeugen ihre eigenen ?-Knöpfe erst zur Laufzeit -- eine
  // einmalige querySelectorAll beim Laden fände die noch nicht.
  document.addEventListener("click", function (e) {
    var hb = e.target.closest(".hilfe-btn");
    if (!hb) return;
    var ziel = document.getElementById(hb.getAttribute("aria-controls"));
    if (!ziel) return;
    var offen = hb.getAttribute("aria-expanded") === "true";
    hb.setAttribute("aria-expanded", String(!offen));
    ziel.hidden = offen;
  });
}

// ================= Sticky Kopf: reale Hoehe messen (Feedback 2026-08-26, Zusatzpunkt 4) =====
// .seitenleiste/.rail-spalte haengen top/Hoehe an --kopf-hoehe -- der :root-Fallback (110px)
// gilt nur vor dem ersten Layout-Pass bzw. wenn dieses Skript aus irgendeinem Grund nicht
// laeuft. Bei Resize neu messen (Zeile 1 kann bei schmalen Fenstern umbrechen -> hoeher).
export function setzeKopfHoehe() {
  var kopf = document.querySelector(".kopf");
  if (!kopf) return;
  document.documentElement.style.setProperty("--kopf-hoehe", kopf.getBoundingClientRect().height + "px");
}

export function initKopfHoehe() {
  setzeKopfHoehe();
  window.addEventListener("resize", setzeKopfHoehe);
}
