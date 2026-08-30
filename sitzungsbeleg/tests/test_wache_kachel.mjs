// Reine-Funktions-Test: die Wache-Kachel wurde am 2026-08-28 spaet WIEDER ENTFERNT
// (Sichtbefund: Kachel ohne Sitzungs-Drilldown wirkt kaputt; Meldungen bleiben als
// Verlauf-Marker in der Sitzungsansicht). Der Test sichert jetzt die Abwesenheit --
// Fixture-Querschnitt rein, erwartete Kachel-Liste raus, kein Browser noetig.
// Minimaler window/document-Stub VOR dem Import: start.js haengt ueber zustand.js/router.js
// transitiv an Modulen mit top-level `window.addEventListener` (fehlerbilder.js) -- ohne Stub
// bricht schon der Import mit "window is not defined" (Muster wie bei node --test ueblich fuer
// Seiten-Module, siehe Bericht). `baueKacheln` selbst greift nicht auf DOM zu.
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_wache_kachel.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

globalThis.window = globalThis.window || { addEventListener: function () {} };
globalThis.document = globalThis.document || { addEventListener: function () {}, getElementById: function () { return null; } };

const { baueKacheln } = await import("../static/js/start.js");

function fixtureQuerschnitt(overrides) {
  return Object.assign({
    wiederkehrende_fehler: { anzahl: 0, sitzung_ids: [], signaturen: [] },
    kosten_ausreisser: { anzahl: 0, sitzung_ids: [] },
    erfassungsluecken: { anzahl: 0, sitzung_ids: [] },
    dissens: { anzahl: 0, sitzung_ids: [] },
    unzugeordnet: { anzahl: 0, sitzung_ids: [] },
    pruefung_offen: { anzahl: 0, sitzung_ids: [] },
  }, overrides);
}

test("Keine Wache-Kachel mehr im Querschnitt (Entscheid 2026-08-28 spaet)", () => {
  var kacheln = baueKacheln(fixtureQuerschnitt({ wache: { anzahl: 7, offen_fragen: 2 } }));
  assert.equal(kacheln.filter(function (k) { return k.status === "Wache"; }).length, 0);
});

test("Kachel-Grundbestand bleibt: Fehler/2x Warnung/Kritisch/Pruefung offen", () => {
  var kacheln = baueKacheln(fixtureQuerschnitt({}));
  assert.deepEqual(kacheln.map(function (k) { return k.status; }),
    ["Fehler", "Warnung", "Warnung", "Kritisch", "Prüfung offen"]);
});

test("Unzugeordnet-Kachel erscheint nur bei Bestand > 0", () => {
  assert.equal(baueKacheln(fixtureQuerschnitt({})).filter(function (k) { return k.status === "Unzugeordnet"; }).length, 0);
  var mit = baueKacheln(fixtureQuerschnitt({ unzugeordnet: { anzahl: 2, sitzung_ids: [1, 2] } }));
  assert.equal(mit.filter(function (k) { return k.status === "Unzugeordnet"; }).length, 1);
});
