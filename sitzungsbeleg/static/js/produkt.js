// Seite: Produkt -- Platzhalter-Seite, füllt sich automatisch sobald ein Produkt-Kanal
// (z. B. Beispielprojekt) Ereignisse liefert.
import { zustand } from "./zustand.js";
import { iso } from "./format.js";
import { holeJSON, zeigeFehler } from "./api.js";

export function ladeProdukt() {
  holeJSON("/api/sitzungen", { von: iso(zustand.von), bis: iso(zustand.bis), quelle: "Produkt" })
    .then(function (zeilen) {
      document.getElementById("produkt-inhalt").innerHTML = zeilen.length
        ? "<p>" + zeilen.length + " Produkt-Sitzung(en) im gewählten Zeitraum. Volle Auswertung folgt, sobald ein Produkt-Kanal (z. B. Beispielprojekt) anbindet.</p>"
        : '<p class="caption">Noch keine Produkt-Sitzungen im gewählten Zeitraum. Diese Seite füllt sich automatisch, sobald ein Produkt-Kanal Ereignisse liefert.</p>';
    }).catch(function (e) { zeigeFehler("produkt-inhalt", e); });
}
