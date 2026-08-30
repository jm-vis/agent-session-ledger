// Globaler Zustand (Filter-Auswahl, Drilldown, Sitzungscache), Zeitraum-Steuerung (Tag/7/30/
// Popover) und die beiden localStorage-Schluessel, die keiner Einzelseite gehoeren (Theme hat
// seinen eigenen Schluessel in hilfen.js). ladeAktuellePage() lebt in router.js -- setzeModus()
// und die Zeitraum-Uebernehmen-Aktion loesen darueber einen Seiten-Reload aus.
import { heute, addTage, iso, ausIso, formatDeKurz, formatDeVoll } from "./format.js";
import { ladeAktuellePage } from "./router.js";

export var KONTEXTE = ["arbeit", "voice", "review", "bewertung", "test"];
// Achse Umgebung (C12, Maintainer 2026-08-28 12:45): fester Wertevorrat wie KONTEXTE -- welche
// Checkboxen der Seitenleisten-Block ueberhaupt zeigen kann, unabhaengig davon, ob er im
// aktuellen Zeitraum ueberhaupt sichtbar ist (start.js:umgebungBlockSichtbar).
export var UMGEBUNGEN = ["entwicklung", "abnahme", "betrieb"];
export var zustand = {
  modus: "7",
  von: null, bis: null,
  aktiveProjekte: new Set(),
  aktiveQuellen: new Set(["Claude", "Codex", "Ollama", "OpenRouter", "Requesty", "Unbekannt"]),
  aktiveKontexte: new Set(KONTEXTE),
  aktiveUmgebungen: new Set(UMGEBUNGEN),
  // Achse Persona (C14, Entscheid 2026-08-28): fester Wertevorrat wie bei den anderen Achsen --
  // die Filtergruppe ist IMMER sichtbar (kein umgebungBlockSichtbar-Aequivalent noetig).
  aktivePersonas: new Set(["vico", "vica", "cura"]),
  drilldownIds: null,
  drilldownBanner: null,
  drilldownTreffer: null,
  drilldownErledigtIds: null,
  zeigeErledigteImDrilldown: false,
  sitzungenCache: [],
  projektInitialisiert: false,
  projektBekannt: new Set(),
};
var aktuellerTag = heute();

// ================= Ausgeblendete Projekte (Einstellungen-Schalter) =================
var AUSGEBLENDET_KEY = "sitzungsbeleg-zeige-ausgeblendete";
export function zeigeAusgeblendeteProjekte() {
  try { return localStorage.getItem(AUSGEBLENDET_KEY) === "1"; } catch (e) { return false; }
}
export function setzeZeigeAusgeblendeteProjekte(wert) {
  try { localStorage.setItem(AUSGEBLENDET_KEY, wert ? "1" : "0"); } catch (e) { /* stumm */ }
}

// ================= Zeitraum-Steuerung =================
export function periodenSuffix() {
  if (!zustand.von || !zustand.bis) return "";
  if (zustand.modus === "tag") return "— " + formatDeVoll(zustand.von);
  if (zustand.modus === "7") return "— 7 Tage";
  if (zustand.modus === "30") return "— 30 Tage";
  return "— " + formatDeKurz(zustand.von) + "–" + formatDeVoll(zustand.bis);
}

export function aktualisiereDatumsanzeige() {
  var anzeige = document.getElementById("datum-anzeige");
  if (!zustand.von || !zustand.bis) return;
  anzeige.textContent = (iso(zustand.von) === iso(zustand.bis))
    ? formatDeVoll(zustand.von)
    : formatDeKurz(zustand.von) + "–" + formatDeVoll(zustand.bis);
  var suffix = periodenSuffix();
  ["querschnitt-zeitraum-start", "querschnitt-zeitraum-seite", "fehler-panel-zeitraum"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.textContent = suffix;
  });
}

export function setzeModus(modus) {
  zustand.modus = modus;
  var h = heute();
  if (modus === "tag") { zustand.von = aktuellerTag; zustand.bis = aktuellerTag; }
  else if (modus === "7") { zustand.bis = h; zustand.von = addTage(h, -6); }
  else if (modus === "30") { zustand.bis = h; zustand.von = addTage(h, -29); }
  document.querySelectorAll(".segmented button[data-modus]").forEach(function (b) {
    b.setAttribute("aria-pressed", String(b.getAttribute("data-modus") === modus));
  });
  aktualisiereDatumsanzeige();
  ladeAktuellePage();
}

// ---- Zeitraum-Popover ----
var zrBtn, zrPopover, zrVon, zrBis;

function schliesseZeitraumPopover() {
  zrPopover.hidden = true;
  zrBtn.setAttribute("aria-expanded", "false");
}

function _initTagUndModusWiring() {
  document.querySelectorAll(".segmented button[data-modus]").forEach(function (b) {
    b.addEventListener("click", function () { setzeModus(b.getAttribute("data-modus")); });
  });
  document.getElementById("tag-zurueck").addEventListener("click", function () {
    aktuellerTag = addTage(aktuellerTag, -1); setzeModus("tag");
  });
  document.getElementById("tag-vor").addEventListener("click", function () {
    aktuellerTag = addTage(aktuellerTag, 1); setzeModus("tag");
  });
}

function _initZeitraumPopoverWiring() {
  zrBtn = document.getElementById("zeitraum-btn");
  zrPopover = document.getElementById("zeitraum-popover");
  zrVon = document.getElementById("zr-von");
  zrBis = document.getElementById("zr-bis");

  zrBtn.addEventListener("click", function () {
    var offen = zrBtn.getAttribute("aria-expanded") === "true";
    zrBtn.setAttribute("aria-expanded", String(!offen));
    zrPopover.hidden = offen;
    if (!offen) { zrVon.value = iso(zustand.von); zrBis.value = iso(zustand.bis); }
  });
  document.addEventListener("click", function (e) {
    if (!zrPopover.hidden && !zrPopover.contains(e.target) && e.target !== zrBtn) schliesseZeitraumPopover();
  });
  document.querySelectorAll(".popover-schnellwahl button").forEach(function (b) {
    b.addEventListener("click", function () {
      var h = heute();
      var art = b.getAttribute("data-quick");
      var von, bis;
      if (art === "woche") { var wt = (h.getDay() + 6) % 7; von = addTage(h, -wt); bis = h; }
      else if (art === "monat") { von = new Date(h.getFullYear(), h.getMonth(), 1); bis = h; }
      else { von = new Date(h.getFullYear(), h.getMonth() - 1, 1); bis = new Date(h.getFullYear(), h.getMonth(), 0); }
      zrVon.value = iso(von); zrBis.value = iso(bis);
    });
  });
  document.getElementById("zr-uebernehmen").addEventListener("click", function () {
    if (!zrVon.value || !zrBis.value) return;
    var von = ausIso(zrVon.value), bis = ausIso(zrBis.value);
    if (von > bis) { var tausch = von; von = bis; bis = tausch; }
    zustand.modus = "custom";
    zustand.von = von;
    zustand.bis = bis;
    document.querySelectorAll(".segmented button[data-modus]").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
    aktualisiereDatumsanzeige();
    schliesseZeitraumPopover();
    ladeAktuellePage();
  });
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist.
export function initZeitraum() {
  _initTagUndModusWiring();
  _initZeitraumPopoverWiring();
}
