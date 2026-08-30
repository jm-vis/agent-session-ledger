// Reine-Funktions-Test fuer die Achse Umgebung (C12, Auftrag 2026-08-28 12:45): Projekt-
// Zellen-Chip (kein Chip bei entwicklung, Kuerzel bei Abweichung) + Sichtbarkeitsregel des
// Seitenleisten-Blocks ("erscheint nur, wenn im Zeitraum >= 2 Werte vorkommen") -- Muster
// test_chat_sicht.mjs: reine Funktionen rein, kein DOM/Browser noetig.
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_umgebung.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { umgebungChipHtml, umgebungBlockSichtbar } from "../static/js/format.js";

test("umgebungChipHtml: kein Chip bei entwicklung", () => {
  assert.equal(umgebungChipHtml("entwicklung"), "");
});

test("umgebungChipHtml: kein Chip bei fehlendem/unbekanntem Wert", () => {
  assert.equal(umgebungChipHtml(""), "");
  assert.equal(umgebungChipHtml(undefined), "");
  assert.equal(umgebungChipHtml("staging"), "");
});

test("umgebungChipHtml: Kuerzel Abn. bei abnahme", () => {
  var html = umgebungChipHtml("abnahme");
  assert.match(html, /umgebung-chip umgebung-abnahme/);
  assert.match(html, />Abn\.</);
});

test("umgebungChipHtml: Kuerzel Betrieb bei betrieb", () => {
  var html = umgebungChipHtml("betrieb");
  assert.match(html, /umgebung-chip umgebung-betrieb/);
  assert.match(html, />Betrieb</);
});

test("umgebungBlockSichtbar: ein Wert im Zeitraum -> Block bleibt versteckt", () => {
  assert.equal(umgebungBlockSichtbar([{ name: "entwicklung", anzahl: 12 }]), false);
});

test("umgebungBlockSichtbar: zwei Werte im Zeitraum -> Block sichtbar", () => {
  assert.equal(
    umgebungBlockSichtbar([{ name: "entwicklung", anzahl: 12 }, { name: "abnahme", anzahl: 3 }]),
    true,
  );
});

test("umgebungBlockSichtbar: ein Wert mit anzahl=0 zaehlt nicht mit", () => {
  assert.equal(
    umgebungBlockSichtbar([{ name: "entwicklung", anzahl: 12 }, { name: "betrieb", anzahl: 0 }]),
    false,
  );
});

test("umgebungBlockSichtbar: leere/fehlende Liste -> versteckt", () => {
  assert.equal(umgebungBlockSichtbar([]), false);
  assert.equal(umgebungBlockSichtbar(undefined), false);
});
