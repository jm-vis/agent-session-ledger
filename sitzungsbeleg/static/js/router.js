// Hash-Routing: welche <section id="page-*"> aktiv ist + welche lade*()-Funktion pro Seite laeuft.
import { ladeStart } from "./start.js";
import { ladeSitzung } from "./sitzung.js";
import { ladeSubagent } from "./subagent.js";
import { ladeQuerschnitt } from "./querschnitt.js";
import { ladeProdukt } from "./produkt.js";
import { ladeEinstellungen } from "./einstellungen.js";

var seiten, seitenNavSichtbar;

function markiereNav(name) {
  document.querySelectorAll(".seiten-nav button").forEach(function (b) {
    b.setAttribute("aria-pressed", String(b.getAttribute("data-seite") === name));
  });
}

// Fund B: IDs aus dem Hash strikt numerisch pruefen, bevor sie in Attribute/Text landen (sonst
// liesse sich ueber #sitzung/<payload> ungepruefter Text in die Seite schmuggeln) -- ungueltige
// IDs fallen auf die Start-Seite zurueck, gleiche Logik wie der bestehende Seitenname-Fallback.
var GANZZAHL = /^\d+$/;

export function zeigeSeite() {
  var teile = (location.hash || "#start").replace("#", "").split("/");
  var name = seiten[teile[0]] ? teile[0] : "start";
  if (name === "sitzung" && !GANZZAHL.test(teile[1] || "")) name = "start";
  if (name === "subagent" && (!GANZZAHL.test(teile[1] || "") || !GANZZAHL.test(teile[2] || ""))) name = "start";
  Object.keys(seiten).forEach(function (n) { seiten[n].classList.toggle("aktiv", n === name); });
  if (seitenNavSichtbar.indexOf(name) !== -1) markiereNav(name);
  window.scrollTo(0, 0);
  if (name === "start") ladeStart();
  else if (name === "sitzung") ladeSitzung(teile[1]);
  else if (name === "subagent") ladeSubagent(teile[1], Number(teile[2]));
  else if (name === "querschnitt") ladeQuerschnitt();
  else if (name === "produkt") ladeProdukt();
  else if (name === "einstellungen") ladeEinstellungen();
}

function aktivesSeitenName() {
  return Object.keys(seiten).filter(function (n) { return seiten[n].classList.contains("aktiv"); })[0] || "start";
}
export function ladeAktuellePage() {
  var name = aktivesSeitenName();
  if (name === "start") ladeStart();
  else if (name === "querschnitt") ladeQuerschnitt();
  else if (name === "produkt") ladeProdukt();
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist.
export function initRouter() {
  seiten = {
    start: document.getElementById("page-start"),
    sitzung: document.getElementById("page-sitzung"),
    subagent: document.getElementById("page-subagent"),
    querschnitt: document.getElementById("page-querschnitt"),
    produkt: document.getElementById("page-produkt"),
    einstellungen: document.getElementById("page-einstellungen"),
  };
  seitenNavSichtbar = ["start", "querschnitt", "produkt", "einstellungen"];

  document.querySelectorAll(".seiten-nav button").forEach(function (b) {
    b.addEventListener("click", function () { location.hash = "#" + b.getAttribute("data-seite"); });
  });
  window.addEventListener("hashchange", zeigeSeite);
}
