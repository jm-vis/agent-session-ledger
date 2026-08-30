// Verankerungs-Formularfeld (C11, Entscheid 2026-08-28): EIN Modul fuer alle vier Entscheid-
// Formulare (sitzung.js Erledigt je Befund, start.js Fehlerbild-Kachel, fehlerbilder.js Register,
// tiefenanalyse.js Entscheid-Block) -- "gleiche Signatur, gleiche API" wie schon beim Erledigt-
// Feature selbst (Abnahme 2026-08-26, Auftrag C.8), hier fuer das neue Pflichtfeld bei
// `status=erledigt`. Node-Test: tests/test_verankerung.mjs.
import { escapeHtml } from "./format.js";

// CONTRACTS.md C11: Gattung des Ortes + gaengige Ziele (Datalist-Vorschlaege, kein Zwang).
export var VERANKERUNG_ARTEN = ["troubleshooting", "adr", "runbook", "playbook", "hook", "skill", "regel", "vorhaben"];
export var VERANKERUNG_ZIELE = [
  "TROUBLESHOOTING.md", "HANDOFF.md", "docs/adr/", "docs/runbooks/",
  "docs/playbooks/", ".claude/hooks/", ".claude/skills/", "CLAUDE.md",
];

var zaehler = 0;

// Eigene Datalist-ID je Aufruf (mehrere Formulare koennen gleichzeitig offen sein, z. B. zwei
// Befund-Karten -- doppelte IDs waeren ungueltiges HTML und das `list`-Attribut faende die falsche).
export function verankerungFormularHtml() {
  zaehler += 1;
  var listeId = "verankerung-ziele-" + zaehler;
  var artOptionen = VERANKERUNG_ARTEN.map(function (a) {
    return '<option value="' + a + '">' + a + "</option>";
  }).join("");
  var zielOptionen = VERANKERUNG_ZIELE.map(function (z) {
    return '<option value="' + escapeHtml(z) + '">';
  }).join("");
  return '<div class="verankerung-felder" hidden>'
    + '<label>Verankerung: Art<select class="v-art">' + artOptionen + "</select></label>"
    + '<label>Verankerung: Pfad<input type="text" class="v-pfad" list="' + listeId
    + '" maxlength="300" placeholder="z. B. TROUBLESHOOTING.md"></label>'
    + '<datalist id="' + listeId + '">' + zielOptionen + "</datalist>"
    + '<label>Verankerung: Abschnitt<input type="text" class="v-abschnitt" maxlength="200" '
    + 'placeholder="Ueberschrift/Stichwort in der Datei"></label>'
    + "</div>";
}

// `el` ist der Formular-Wurzelknoten (enthaelt `.v-art`/`.v-pfad`/`.v-abschnitt`) -- `null` ohne
// Pfad (Status obsolet/offen brauchen keine Verankerung, ein leeres Objekt waere trotzdem ein
// Contract-Fehler, s. CONTRACTS.md C11 "pfad ... min_length=1").
export function verankerungAusFormular(el) {
  var pfadEl = el.querySelector(".v-pfad");
  var pfad = pfadEl && pfadEl.value ? pfadEl.value.trim() : "";
  if (!pfad) return null;
  var artEl = el.querySelector(".v-art");
  var abschnittEl = el.querySelector(".v-abschnitt");
  return {
    art: (artEl && artEl.value) || VERANKERUNG_ARTEN[0],
    pfad: pfad,
    abschnitt: abschnittEl && abschnittEl.value ? abschnittEl.value.trim() : "",
  };
}

// Blendet `.verankerung-felder` nur bei `status="erledigt"` ein UND sperrt den mit
// `[data-verankerung-knopf]` markierten Sende-Knopf, solange erledigt + Pfad leer ist (CONTRACTS.md
// C11: "der Server lehnt erledigt ohne Verankerung ab; das Frontend zeigt die Felder nur bei
// erledigt und blockt den Knopf ohne Pfad"). Liefert `true`, wenn absenden erlaubt ist.
export function verankerungSichtbarSchalten(el, status) {
  var wrap = el.querySelector(".verankerung-felder");
  var erledigt = status === "erledigt";
  if (wrap) wrap.hidden = !erledigt;
  var pfadEl = el.querySelector(".v-pfad");
  var pfadWert = pfadEl && pfadEl.value ? pfadEl.value.trim() : "";
  var gesperrt = erledigt && !pfadWert;
  var knopf = el.querySelector("[data-verankerung-knopf]");
  if (knopf) knopf.disabled = gesperrt;
  return !gesperrt;
}

// Anzeige-Chip fuer einen bereits geschriebenen Entscheid (sitzung.js/fehlerbilder.js) -- leerer
// String ohne Verankerung (Legacy-Entscheide vor C11).
export function verankerungChipHtml(v) {
  if (!v || !v.pfad) return "";
  var titel = v.abschnitt ? ' title="' + escapeHtml(v.abschnitt) + '"' : "";
  return '<span class="verankerung-chip"' + titel + ">" + escapeHtml(v.art) + " · " + escapeHtml(v.pfad) + "</span>";
}
