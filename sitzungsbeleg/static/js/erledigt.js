// Erledigt-Formular je Befund (Entscheid 2026-08-26, Auftrag 3; aus sitzung.js ausgelagert
// 2026-08-28, Code-Masse-Waechter: sitzung.js war ueber 800 Zeilen). Gemeinsam fuer
// Befunde-Karten UND die Vier-Augen-Tabelle ("gleiche Signatur, gleiche API").
// C11: erledigt verlangt eine Verankerung (Art + Pfad) -- Felder/Sperre via verankerung.js.
import { verankerungAusFormular, verankerungFormularHtml, verankerungSichtbarSchalten } from "./verankerung.js";

function erledigtFormularHtml() {
  return '<div class="erledigt-formular">'
    + '<label>Status<select class="ef-status"><option value="erledigt">erledigt</option><option value="obsolet">obsolet</option><option value="offen">offen (Wiedereröffnung)</option></select></label>'
    + '<label>Vermerk<input type="text" class="ef-vermerk" maxlength="500" placeholder="z. B. TROUBLESHOOTING Abschn. X, Commit-Hash"></label>'
    + '<label>Begründung<input type="text" class="ef-begruendung" maxlength="500"></label>'
    + verankerungFormularHtml()
    + '<p class="erledigt-fehler" hidden></p>'
    + '<div class="zeile"><button type="button" class="link-btn ef-abbrechen">Abbrechen</button>'
    + '<button type="button" class="outline-btn ef-absenden" data-verankerung-knopf>Speichern</button></div></div>';
}

// C11: Sichtbarkeit/Sperre bei jeder Statusaenderung UND jeder Pfad-Eingabe neu bewerten
// (verankerungSichtbarSchalten liest beides live aus dem DOM).
function verankerungFormularVerkabeln(slot) {
  verankerungSichtbarSchalten(slot, slot.querySelector(".ef-status").value);
  slot.querySelector(".ef-status").addEventListener("change", function () {
    verankerungSichtbarSchalten(slot, this.value);
  });
  slot.querySelector(".v-pfad").addEventListener("input", function () {
    verankerungSichtbarSchalten(slot, slot.querySelector(".ef-status").value);
  });
}

// `aufErfolg(detail)` bekommt den geschriebenen Entscheid und entscheidet selbst, was neu
// gerendert wird (die Stellen zeigen unterschiedliche Daten).
export function erledigtFormularEinfuegen(slot, sitzungId, signatur, aufErfolg) {
  if (slot.querySelector(".erledigt-formular")) { slot.innerHTML = ""; return; }
  slot.innerHTML = erledigtFormularHtml();
  verankerungFormularVerkabeln(slot);
  slot.querySelector(".ef-abbrechen").addEventListener("click", function () { slot.innerHTML = ""; });
  slot.querySelector(".ef-absenden").addEventListener("click", function () {
    sendeEntscheid(sitzungId, signatur, slot, aufErfolg);
  });
}

function sendeEntscheid(sitzungId, signatur, slot, aufErfolg) {
  var fehlerEl = slot.querySelector(".erledigt-fehler");
  var knopf = slot.querySelector(".ef-absenden");
  fehlerEl.hidden = true;
  knopf.disabled = true;
  fetch("/api/befund/entscheid", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      signatur: signatur, status: slot.querySelector(".ef-status").value,
      vermerk: slot.querySelector(".ef-vermerk").value,
      begruendung: slot.querySelector(".ef-begruendung").value,
      sitzung_ref: Number(sitzungId), verankerung: verankerungAusFormular(slot),
    }),
  }).then(function (antwort) {
    if (!antwort.ok) return antwort.json().then(function (d) { throw new Error(d.detail || ("HTTP " + antwort.status)); });
    return antwort.json();
  }).then(function (detail) {
    aufErfolg(detail);
  }).catch(function (e) {
    fehlerEl.textContent = e.message;
    fehlerEl.hidden = false;
    knopf.disabled = false;
  });
}
