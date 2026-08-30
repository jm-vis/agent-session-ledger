// Reine-Funktions-Test fuer chat.js' Sichtkontext-Aufbau (Nachtrag 2026-08-28, Auftrag
// "Dashboard-Ansicht ist fuer mich nicht sichtbar") -- Muster test_chat_standardmodell.mjs:
// Fixture-Zustand rein, erwartetes Sichtpaket-JSON raus, kein DOM/Browser noetig.
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_chat_sicht.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { baueSichtObjekt, sichtZeileAus, sitzungenSichtbar } from "../static/js/chat.js";

function zeile(overrides) {
  return Object.assign({
    id: 1, projekt: "Demo", quelle: "Claude", kontext: "arbeit", start: "2026-08-28T09:00:00Z",
    dauer_ms: 720000, runden: 5, tools: 20, fehler: 0, kosten: 0.42, anzahl_befunde: 0, dissens: false,
  }, overrides);
}

function fixtureZustand(sitzungenCache) {
  return {
    von: "2026-08-22", bis: "2026-08-28",
    aktiveProjekte: new Set(["Demo"]), aktiveQuellen: new Set(["Claude"]), aktiveKontexte: new Set(["arbeit"]),
    sitzungenCache: sitzungenCache,
  };
}

test("sitzungenSichtbar: nur Zeilen, die alle drei aktiven Mengen treffen", () => {
  var sichtbar = zeile({ id: 1 });
  var falschesProjekt = zeile({ id: 2, projekt: "Anderes" });
  var falscheQuelle = zeile({ id: 3, quelle: "Codex" });
  var falscherKontext = zeile({ id: 4, kontext: "test" });
  var quelle = fixtureZustand([sichtbar, falschesProjekt, falscheQuelle, falscherKontext]);
  assert.deepEqual(sitzungenSichtbar(quelle).map((z) => z.id), [1]);
});

test("sitzungenSichtbar: unzugeordneter Kontext ist immer sichtbar (wie start.js)", () => {
  var quelle = fixtureZustand([zeile({ id: 9, kontext: "unzugeordnet" })]);
  assert.deepEqual(sitzungenSichtbar(quelle).map((z) => z.id), [9]);
});

test("sitzungenSichtbar: akzeptiert auch reine Arrays statt Sets (Fixture-Freundlichkeit)", () => {
  var quelle = {
    aktiveProjekte: ["Demo"], aktiveQuellen: ["Claude"], aktiveKontexte: ["arbeit"],
    sitzungenCache: [zeile({ id: 5 })],
  };
  assert.deepEqual(sitzungenSichtbar(quelle).map((z) => z.id), [5]);
});

test("sitzungenSichtbar: Zeile ohne umgebung-Feld ist immer sichtbar (Alt-Cache)", () => {
  var quelle = fixtureZustand([zeile({ id: 7 })]);
  quelle.aktiveUmgebungen = new Set(["betrieb"]); // enthaelt "entwicklung" nicht -- greift trotzdem nicht
  assert.deepEqual(sitzungenSichtbar(quelle).map((z) => z.id), [7]);
});

test("sitzungenSichtbar: C12 -- gesetzte umgebung filtert wie quelle/kontext", () => {
  var passt = zeile({ id: 1, umgebung: "entwicklung" });
  var falsch = zeile({ id: 2, umgebung: "abnahme" });
  var quelle = fixtureZustand([passt, falsch]);
  quelle.aktiveUmgebungen = new Set(["entwicklung"]);
  assert.deepEqual(sitzungenSichtbar(quelle).map((z) => z.id), [1]);
});

test("sichtZeileAus: baut eine SichtSitzungZeile mit Auffaelligkeiten-Tags", () => {
  var z = sichtZeileAus(zeile({ id: 666, fehler: 2, anzahl_befunde: 3, dissens: true }));
  assert.equal(z.nr, 666);
  assert.equal(z.quelle, "Claude");
  assert.equal(z.projekt, "Demo");
  assert.equal(z.dauer, "12m");
  assert.equal(z.usd, 0.42);
  assert.equal(z.status, "dissens");
  assert.deepEqual(z.auffaelligkeiten.sort(), ["befunde:3", "dissens", "werkzeug-fehler:2"].sort());
});

test("sichtZeileAus: ok-Status ohne Befunde/Dissens, leere Auffaelligkeiten-Liste", () => {
  var z = sichtZeileAus(zeile({ id: 1 }));
  assert.equal(z.status, "ok");
  assert.deepEqual(z.auffaelligkeiten, []);
});

test("baueSichtObjekt: ansicht=sitzung liefert nur sitzung/befund, keine Zeilenliste", () => {
  var sicht = baueSichtObjekt("sitzung", fixtureZustand([zeile({ id: 1 })]), { sitzung_logisch: 137, signatur: "rework:tool:Bash" });
  assert.deepEqual(sicht, {
    ansicht: "sitzung", zeitraum: null, filter: null, sitzungen: [],
    sitzung: 137, befund: "rework:tool:Bash",
  });
});

test("baueSichtObjekt: ansicht=start liefert Zeitraum/Filter/sichtbare Zeilen als erwartetes JSON", () => {
  var sicht = baueSichtObjekt("start", fixtureZustand([zeile({ id: 666 })]), { sitzung_logisch: null, signatur: null });
  assert.deepEqual(sicht, {
    ansicht: "start",
    zeitraum: { von: "2026-08-22", bis: "2026-08-28" },
    filter: { projekte: ["Demo"], quellen: ["Claude"], kontexte: ["arbeit"], umgebungen: [], personas: [] },
    sitzungen: [{
      nr: 666, zeit: "2026-08-28T09:00:00Z", quelle: "Claude", projekt: "Demo", dauer: "12m",
      runden: 5, tools: 20, fehler: 0, usd: 0.42, status: "ok", auffaelligkeiten: [],
    }],
    sitzung: null, befund: null,
  });
});

test("baueSichtObjekt: C12 -- aktiveUmgebungen landet als umgebungen im Filter", () => {
  var quelle = fixtureZustand([zeile({ id: 1 })]);
  quelle.aktiveUmgebungen = new Set(["entwicklung", "abnahme"]);
  var sicht = baueSichtObjekt("start", quelle, {});
  assert.deepEqual(sicht.filter.umgebungen.sort(), ["abnahme", "entwicklung"]);
});

test("baueSichtObjekt: kappt auf SICHT_MAX_SITZUNGEN (30) sichtbare Zeilen", () => {
  var viele = [];
  for (var i = 0; i < 40; i++) viele.push(zeile({ id: i }));
  var sicht = baueSichtObjekt("start", fixtureZustand(viele), {});
  assert.equal(sicht.sitzungen.length, 30);
});
