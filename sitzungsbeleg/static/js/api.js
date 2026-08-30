// Fetch-Hilfe: einziger Ort, der /api/* aufruft, plus gemeinsame Fehleranzeige.
import { escapeHtml } from "./format.js";

// `fetchOptionen` optional (Fund C.5): erlaubt method/headers/body fuer POST-Aufrufe, ohne dass
// Aufrufer die Fehlerbehandlung (HTTP-Status + Server-`detail`) selbst nachbauen muessen.
export function holeJSON(pfad, params, fetchOptionen) {
  var url = new URL(pfad, location.origin);
  Object.keys(params || {}).forEach(function (k) {
    var v = params[k];
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });
  return fetch(url, fetchOptionen).then(function (antwort) {
    if (antwort.ok) return antwort.json();
    return antwort.json().catch(function () { return {}; }).then(function (d) {
      throw new Error(d.detail || (pfad + ": HTTP " + antwort.status));
    });
  });
}
export function zeigeFehler(elementId, fehler) {
  var el = document.getElementById(elementId);
  if (el) el.innerHTML = '<p class="fehlerhinweis">Fehler beim Laden: ' + escapeHtml(fehler.message) + "</p>";
}
