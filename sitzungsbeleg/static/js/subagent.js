// Seite: Subagent -- Detailseite eines einzelnen Subagenten (Kennzahlen-Kacheln), erreichbar
// aus der Delegation/Subagenten-Tabelle der Sitzungsseite (sitzung.js).
import { escapeHtml, formatK, formatDauerKurz, kzKachel } from "./format.js";
import { holeJSON, zeigeFehler } from "./api.js";

export function ladeSubagent(sitzungId, index) {
  document.getElementById("subagent-zurueck").setAttribute("href", "#sitzung/" + encodeURIComponent(sitzungId));
  holeJSON("/api/sitzung/" + encodeURIComponent(sitzungId) + "/subagent/" + index).then(function (daten) {
    renderSubagentDetail(sitzungId, index, daten.subagent);
  }).catch(function (e) { zeigeFehler("subagent-details", e); });
}

function renderSubagentDetail(sitzungId, index, s) {
  document.getElementById("subagent-breadcrumb").innerHTML =
    '<a href="#start">Start</a> / <a href="#sitzung/' + escapeHtml(sitzungId) + '">Sitzung ' + escapeHtml(sitzungId) + '</a> / <span class="aktuell">' + escapeHtml(s.typ || "Subagent") + "</span>";
  var t = s.token || {};
  document.getElementById("subagent-details").innerHTML = '<div class="kennzahlen-leiste" role="group" aria-label="Kennzahlen des Subagenten">'
    + kzKachel(s.typ || "—", "Typ", true)
    + kzKachel(s.auftrag || "–", "Auftrag", true)
    + kzKachel(s.modell || "—", "Modell", true)
    + kzKachel(String(s.tiefe ?? 1), "Tiefe")
    + kzKachel(formatDauerKurz(s.dauer_ms), "Dauer")
    + kzKachel(String(s.runden ?? 0), "Runden")
    + kzKachel(String(s.tools ?? 0), "Tools", false, (s.tool_fehler ?? 0) + " Fehler")
    + kzKachel(formatK(t.input), "Token in")
    + kzKachel(formatK(t.output), "Token out")
    + kzKachel(s.beleg || "—", "Beleg", true)
    + kzKachel(s.ergebnis || "—", "Ergebnis", true)
    + "</div>";
}
