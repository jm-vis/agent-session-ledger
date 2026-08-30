// Reine-Funktions-Test fuer die Achse Persona (C14, Entscheid 2026-08-28): Persona-Zelle der
// Sitzungstabelle (Orb + Name, optionaler Kanal-Zusatz) -- Muster test_umgebung.mjs: reine
// Funktionen rein, kein DOM/Browser noetig.
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_persona.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { personaZelleHtml } from "../static/js/format.js";

test("personaZelleHtml: vico ohne kanal -- kein Kanal-Zusatz, Name VICO, mini-orb--vico", () => {
  var html = personaZelleHtml("vico", undefined);
  assert.match(html, /mini-orb mini-orb--vico/);
  assert.match(html, /<span class="name">VICO<\/span>/);
  assert.doesNotMatch(html, /· Orb/);
});

test("personaZelleHtml: vica mit kanal orb -- Kanal-Zusatz sichtbar", () => {
  var html = personaZelleHtml("vica", "orb");
  assert.match(html, /mini-orb mini-orb--vica/);
  assert.match(html, /<span class="name">VICA<\/span>/);
  assert.match(html, /<span class="kanal">· Orb<\/span>/);
});

test("personaZelleHtml: unbekannte/fehlende Persona faellt auf vico zurueck", () => {
  assert.match(personaZelleHtml("unbekannt", undefined), /mini-orb--vico/);
  assert.match(personaZelleHtml("unbekannt", undefined), /VICO/);
  assert.match(personaZelleHtml(undefined, undefined), /mini-orb--vico/);
  assert.match(personaZelleHtml("", undefined), /mini-orb--vico/);
});

test("personaZelleHtml: cura terminal (kein Kanal-Zusatz bei kanal!=orb)", () => {
  var html = personaZelleHtml("cura", "terminal");
  assert.match(html, /mini-orb mini-orb--cura/);
  assert.match(html, /<span class="name">CURA<\/span>/);
  assert.doesNotMatch(html, /· Orb/);
});
