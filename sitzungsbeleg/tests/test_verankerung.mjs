// Reine-Funktions-/Mini-DOM-Test fuer verankerung.js (C11, Entscheid 2026-08-28). Kein jsdom
// im Projekt (Muster wie test_markdown.mjs/test_tiefenanalyse_panel.mjs) -- die drei DOM-
// nahen Funktionen bekommen darum ein handgebautes Fake-Element, das nur `querySelector` plus
// die paar Felder liefert, die das Modul tatsaechlich liest/setzt (`.value`, `.hidden`, `.disabled`).
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_verankerung.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  VERANKERUNG_ARTEN, verankerungAusFormular, verankerungChipHtml, verankerungFormularHtml,
  verankerungSichtbarSchalten,
} from "../static/js/verankerung.js";

function fakeInput(value) {
  return { value: value };
}

function fakeEl(felder) {
  return { querySelector: function (sel) { return Object.prototype.hasOwnProperty.call(felder, sel) ? felder[sel] : null; } };
}

test("verankerungFormularHtml: enthaelt die drei Felder, standardmaessig verborgen", () => {
  var html = verankerungFormularHtml();
  assert.match(html, /class="verankerung-felder" hidden/);
  assert.match(html, /class="v-art"/);
  assert.match(html, /class="v-pfad"/);
  assert.match(html, /class="v-abschnitt"/);
  assert.match(html, /<datalist/);
});

test("verankerungFormularHtml: zwei Aufrufe erzeugen verschiedene Datalist-IDs", () => {
  var a = verankerungFormularHtml();
  var b = verankerungFormularHtml();
  var idA = a.match(/id="(verankerung-ziele-\d+)"/)[1];
  var idB = b.match(/id="(verankerung-ziele-\d+)"/)[1];
  assert.notEqual(idA, idB);
  assert.match(a, new RegExp('list="' + idA + '"'));
});

test("verankerungAusFormular: leerer Pfad -> null (kein Objekt fuer obsolet/offen)", () => {
  var el = fakeEl({ ".v-pfad": fakeInput("   ") });
  assert.equal(verankerungAusFormular(el), null);
});

test("verankerungAusFormular: mit Pfad -> getrimmtes Objekt", () => {
  var el = fakeEl({
    ".v-art": fakeInput("adr"), ".v-pfad": fakeInput(" docs/adr/x.md "),
    ".v-abschnitt": fakeInput(" Mein Abschnitt "),
  });
  assert.deepEqual(verankerungAusFormular(el), {
    art: "adr", pfad: "docs/adr/x.md", abschnitt: "Mein Abschnitt",
  });
});

test("verankerungAusFormular: ohne Art-Feld faellt auf die erste bekannte Art zurueck", () => {
  var el = fakeEl({ ".v-pfad": fakeInput("CLAUDE.md") });
  assert.equal(verankerungAusFormular(el).art, VERANKERUNG_ARTEN[0]);
});

test("verankerungSichtbarSchalten: Felder nur bei erledigt sichtbar (hidden umgeschaltet)", () => {
  var wrap = { hidden: true };
  var elErledigt = fakeEl({ ".verankerung-felder": wrap, ".v-pfad": fakeInput("x.md") });
  verankerungSichtbarSchalten(elErledigt, "erledigt");
  assert.equal(wrap.hidden, false);

  var wrap2 = { hidden: false };
  var elObsolet = fakeEl({ ".verankerung-felder": wrap2, ".v-pfad": fakeInput("") });
  verankerungSichtbarSchalten(elObsolet, "obsolet");
  assert.equal(wrap2.hidden, true);
});

test("verankerungSichtbarSchalten: Knopf gesperrt wenn erledigt UND pfad leer", () => {
  var knopf = { disabled: false };
  var el = fakeEl({
    ".verankerung-felder": { hidden: false }, ".v-pfad": fakeInput(""), "[data-verankerung-knopf]": knopf,
  });
  var erlaubt = verankerungSichtbarSchalten(el, "erledigt");
  assert.equal(knopf.disabled, true);
  assert.equal(erlaubt, false);
});

test("verankerungSichtbarSchalten: Knopf frei sobald pfad gefuellt ist", () => {
  var knopf = { disabled: true };
  var el = fakeEl({
    ".verankerung-felder": { hidden: false }, ".v-pfad": fakeInput("x.md"), "[data-verankerung-knopf]": knopf,
  });
  var erlaubt = verankerungSichtbarSchalten(el, "erledigt");
  assert.equal(knopf.disabled, false);
  assert.equal(erlaubt, true);
});

test("verankerungSichtbarSchalten: bei obsolet/offen ist der Knopf NIE wegen Verankerung gesperrt", () => {
  var knopf = { disabled: true };
  var el = fakeEl({
    ".verankerung-felder": { hidden: false }, ".v-pfad": fakeInput(""), "[data-verankerung-knopf]": knopf,
  });
  var erlaubt = verankerungSichtbarSchalten(el, "obsolet");
  assert.equal(knopf.disabled, false);
  assert.equal(erlaubt, true);
});

test("verankerungChipHtml: ohne Verankerung leerer String", () => {
  assert.equal(verankerungChipHtml(null), "");
  assert.equal(verankerungChipHtml({}), "");
});

test("verankerungChipHtml: art und pfad im Chip, abschnitt als Tooltip", () => {
  var html = verankerungChipHtml({ art: "troubleshooting", pfad: "TROUBLESHOOTING.md", abschnitt: "Sitzungsbeleg" });
  assert.match(html, /class="verankerung-chip"/);
  assert.match(html, /title="Sitzungsbeleg"/);
  assert.match(html, /troubleshooting · TROUBLESHOOTING\.md/);
});

test("verankerungChipHtml: ohne abschnitt kein title-Attribut", () => {
  var html = verankerungChipHtml({ art: "regel", pfad: "CLAUDE.md" });
  assert.doesNotMatch(html, /title=/);
});

test("verankerungChipHtml: escaped HTML-Sonderzeichen (kein XSS aus Pfad/Abschnitt)", () => {
  var html = verankerungChipHtml({ art: "regel", pfad: "<b>x</b>.md", abschnitt: "<i>y</i>" });
  assert.doesNotMatch(html, /<b>/);
  assert.doesNotMatch(html, /<i>y<\/i>"/);
});
