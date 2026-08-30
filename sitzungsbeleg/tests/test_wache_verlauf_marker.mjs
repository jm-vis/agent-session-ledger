// Reine-Funktions-Test fuer sitzung.js' Wache-Marker in der Verlauf-Zeitleiste (C13-Nachtrag,
// Maintainer 2026-08-28 14:30) -- Ereignisliste + Meldungsspur-Zeilen rein, erwarteter Index->Marker-Map
// raus, kein DOM noetig (`wacheMarkerJeIndex` greift nicht auf document/window zu).
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_wache_verlauf_marker.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { wacheMarkerJeIndex } from "../static/js/sitzung.js";

function ereignis(zeit) {
  return { zeit: zeit, art: "tool" };
}

function meldung(zeit, text) {
  return { zeit: zeit, text: text };
}

test("Marker landet beim letzten Ereignis nicht nach der Meldungszeit", () => {
  var ereignisse = [ereignis("10:00"), ereignis("10:05"), ereignis("10:10")];
  var marker = wacheMarkerJeIndex(ereignisse, [meldung("10:06", "Wache: X — 4.")]);
  assert.deepEqual(marker, { 1: ["Wache: X — 4."] });
});

test("Meldung vor dem ersten Ereignis landet auf Index 0", () => {
  var ereignisse = [ereignis("10:00"), ereignis("10:05")];
  var marker = wacheMarkerJeIndex(ereignisse, [meldung("09:00", "Wache: frueh")]);
  assert.deepEqual(marker, { 0: ["Wache: frueh"] });
});

test("Mehrere Meldungen am selben Index sammeln sich in einer Liste", () => {
  var ereignisse = [ereignis("10:00"), ereignis("10:05")];
  var marker = wacheMarkerJeIndex(ereignisse, [
    meldung("10:06", "Wache: eins"), meldung("10:07", "Wache: zwei"),
  ]);
  assert.deepEqual(marker, { 1: ["Wache: eins", "Wache: zwei"] });
});

test("Keine Meldungen -> leere Map", () => {
  assert.deepEqual(wacheMarkerJeIndex([ereignis("10:00")], []), {});
  assert.deepEqual(wacheMarkerJeIndex([ereignis("10:00")], undefined), {});
});
