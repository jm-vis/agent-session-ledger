// Reine-Funktions-Tests fuer die Preistabelle (Einstellungen, Auftrag 2026-08-30 Nachtrag):
// Katalog-Look ohne Doppelwelt -- Zeilen aus /api/preise (modelle.json, Abrechnungswahrheit),
// Anzeige-Anreicherung (Kontext, Herkunft-Land) aus dem bereits geladenen Katalog-Snapshot.
// Match-Regel (Zwischenstand, Backend-Projection folgt, Plan docs/plans/
// preistabelle-master-sicht-plan.md): exakt -> Kurzname (nach letztem "/") -> Basisname vor
// ":" -- mehrere Treffer = "mehrdeutig" und NICHTS wird angezeigt (nichts raten, Codex-
// Einwand 2026-08-30). Kein jsdom (Projektmuster). Ausfuehren:
// node scripts/sitzungsbeleg/tests/test_einstellungen.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  kurzName, anbieterChip, findeKatalogMatch, verwendetAusPins,
  sortierePreise, preisZeileHtml, bauePreisEintraege,
} from "../static/js/preistabelle.js";

const ROH = {
  "claude-fable-5": { input: 10, output: 50, cache_write: 12.5, cache_read: 1, herkunft: "anthropic", stand: "2026-08-25" },
  "gpt-5.5": { input: 5, output: 30, cache_write: null, cache_read: 0.5, herkunft: "openai", stand: "2026-08-26" },
  "sference/kimi-k3": { input: 2.25, output: 11.25, cache_write: 0, cache_read: 0, herkunft: "requesty", stand: "2026-08-28" },
  "glm-5.2": { input: 1.19, output: 3.74, cache_write: 0, cache_read: 0, herkunft: "ollama", preis_art: "referenz", stand: "2026-08-27" },
};

const KATALOG = [
  { id: "claude-fable-5", kontext_k: 1000, herkunft: "US", hersteller: "Anthropic" },
  { id: "kimi-k3", kontext_k: 256, herkunft: "CN", hersteller: "Moonshot AI" },
  { id: "gpt-5.5", kontext_k: 400, herkunft: "US", hersteller: "OpenAI" },
];

test("kurzName: letztes Pfadsegment, sonst der Name selbst", () => {
  assert.equal(kurzName("sference/kimi-k3"), "kimi-k3");
  assert.equal(kurzName("claude-fable-5"), "claude-fable-5");
  assert.equal(kurzName("glm-5.2:cloud"), "glm-5.2");
});

test("anbieterChip: anthropic wird zum Claude-Chip, Rest neutral/gefärbt", () => {
  assert.match(anbieterChip("anthropic"), /quelle-chip quelle-claude">Anthropic</);
  assert.match(anbieterChip("openrouter"), /quelle-chip quelle-openrouter">OpenRouter</);
  assert.match(anbieterChip("requesty"), /quelle-chip quelle-requesty">Requesty</);
  assert.match(anbieterChip("ollama"), /quelle-chip">Ollama</);
  // Maintainer 2026-08-30: herkunft openai = Codex-Kostenaequivalent -> Codex-Chip im Start-Grün
  assert.match(anbieterChip("openai"), /quelle-chip quelle-codex">Codex</);
});

test("findeKatalogMatch: exakter Key gewinnt vor Kurzname", () => {
  var m = findeKatalogMatch("claude-fable-5", KATALOG);
  assert.equal(m.status, "exakt");
  assert.equal(m.modell.id, "claude-fable-5");
});

test("findeKatalogMatch: Anbieter-Praefix wird ueber Kurzname aufgeloest (alias)", () => {
  var m = findeKatalogMatch("sference/kimi-k3", KATALOG);
  assert.equal(m.status, "alias");
  assert.equal(m.modell.id, "kimi-k3");
});

test("findeKatalogMatch: kein Treffer -> kein_match, KEIN Anzeigewert wird geraten", () => {
  var m = findeKatalogMatch("glm-5.2", KATALOG);
  assert.equal(m.status, "kein_match");
  assert.equal(m.modell, null);
});

test("findeKatalogMatch: Datums-Suffix (-20251001) wird vor dem Match abgezogen", () => {
  var m = findeKatalogMatch("claude-haiku-4-5-20251001", [{ id: "claude-haiku-4-5", herkunft: "US" }]);
  assert.equal(m.status, "alias");
  assert.equal(m.modell.id, "claude-haiku-4-5");
});

test("preisZeileHtml: Persona-Chips tragen ihre Farbklasse", () => {
  var [eintrag] = bauePreisEintraege({ "claude-fable-5": ROH["claude-fable-5"] }, KATALOG, {
    vico: [{ quelle: "claude", modell: "claude-fable-5", primaer: true }],
  });
  assert.match(preisZeileHtml(eintrag), /verwendet-chip persona-vico/);
  assert.match(preisZeileHtml(eintrag), /verwendet-chip"[^>]*>Abrechnung/);  // neutral, keine Farbe
});

test("findeKatalogMatch: mehrere Treffer -> mehrdeutig, modell null", () => {
  var m = findeKatalogMatch("x/kimi-k3", [...KATALOG, { id: "x/kimi-k3" }]);
  // exakter Key "x/kimi-k3" UND kurz "kimi-k3" existieren -> exakt gewinnt deterministisch
  assert.equal(m.status, "exakt");
  var doppelt = findeKatalogMatch("fremd/kimi", [{ id: "kimi" }, { id: "kimi", herkunft: "EU" }]);
  assert.equal(doppelt.status, "mehrdeutig");
  assert.equal(doppelt.modell, null);
});

test("verwendetAusPins: Persona-Chip NUR wenn Modell UND Anbieter zum Weg passen", () => {
  // Fund 2026-08-30 Screenshot-Runde: VICA/CURA liefen faelschlich am Requesty-Preis
  // (sference/glm-5.3-flash), obwohl sie ueber OLLAMA gepinnt sind -- "keine Interpretation,
  // die tatsaechliche Verdrahtung". anthropic entspricht Pin-Quelle "claude".
  var pins = {
    vico: [{ quelle: "claude", modell: "claude-fable-5", primaer: true },
           { quelle: "ollama", modell: "kimi-k3:cloud", primaer: false }],
    cura: { rolle: "Administration", wege: [{ quelle: "ollama", modell: "glm-5.3-flash:cloud", primaer: true }] },
  };
  assert.deepEqual(verwendetAusPins("claude-fable-5", pins, "anthropic"), ["vico"]);
  assert.deepEqual(verwendetAusPins("kimi-k3", pins, "ollama"), ["vico"]);       // Referenz-Preiszeile
  assert.deepEqual(verwendetAusPins("sference/kimi-k3", pins, "requesty"), []);  // VICO nutzt NICHT requesty
  assert.deepEqual(verwendetAusPins("glm-5.3-flash", pins, "ollama"), ["cura"]);
  assert.deepEqual(verwendetAusPins("sference/glm-5.3-flash", pins, "requesty"), []);
  assert.deepEqual(verwendetAusPins("gpt-5.5", pins, "openai"), []);             // kein Pin via OpenAI-Direkt
});

test("sortierePreise: Modell alphabetisch, Zahlen auf/ab, fehlende Werte ans Ende", () => {
  var rows = bauePreisEintraege(ROH, KATALOG, {});
  var namen = sortierePreise(rows, "modell", 1).map((e) => e.name);
  assert.deepEqual(namen, ["claude-fable-5", "glm-5.2", "gpt-5.5", "sference/kimi-k3"]);
  assert.deepEqual(sortierePreise(rows, "eingabe", -1)[0].name, "claude-fable-5");
  var mitNull = sortierePreise(rows, "kontext", -1).map((e) => e.name);
  assert.deepEqual(mitNull[mitNull.length - 1], "glm-5.2");  // kein Katalog-Match -> kontext null -> hinten
  assert.deepEqual(sortierePreise(rows, "kontext", 1).map((e) => e.name).pop(), "glm-5.2");
});

test("preisZeileHtml: Kurzname oben, voller Key drunter, Chips, Zahlen deutsch", () => {
  var [eintrag] = bauePreisEintraege({ "sference/kimi-k3": ROH["sference/kimi-k3"] }, KATALOG, {
    vico: [{ quelle: "requesty", modell: "sference/kimi-k3", primaer: true }],
  });
  var html = preisZeileHtml(eintrag);
  assert.match(html, /class="name"><span class="mono">kimi-k3<\/span>/);
  assert.match(html, /class="hersteller">Moonshot AI</);         // Hersteller wie im Katalog vorn
  assert.match(html, /title="sference\/kimi-k3"/);               // voller Key als Tooltip
  assert.match(html, /quelle-requesty/);
  assert.match(html, /<td class="num">2,3<\/td>/);
  assert.match(html, /<td class="num">256<\/td>/);               // Kontext aus Katalog
  assert.match(html, /VICO/);                                    // Verwendet-Chip
});

test("preisZeileHtml: Unterzeile = Hersteller (vorrangig), ohne Match der Kanal", () => {
  var [eintrag] = bauePreisEintraege({ "claude-fable-5": ROH["claude-fable-5"] }, KATALOG, {});
  assert.match(preisZeileHtml(eintrag), /class="hersteller">Anthropic</);  // Hersteller aus Katalog
  var [ohne] = bauePreisEintraege({ "glm-5.2": ROH["glm-5.2"] }, KATALOG, {});
  assert.match(preisZeileHtml(ohne), /class="hersteller">Ollama</);        // kein Match -> Kanal-Name
});

test("preisZeileHtml: kein Katalog-Match -> Kontext/Herkunft Gedankenstrich, Abrechnung-Chip immer", () => {
  var [eintrag] = bauePreisEintraege({ "glm-5.2": ROH["glm-5.2"] }, KATALOG, {});
  assert.equal(eintrag.matchStatus, "kein_match");
  var html = preisZeileHtml(eintrag);
  assert.match(html, /<td class="num">—<\/td>/);                 // Kontext ohne Match
  assert.match(html, /herkunft-zelle">—</);                      // Land ohne Match
  assert.match(html, /Abrechnung/);                              // diese Liste IST die Kostenquelle
});

test("bauePreisEintraege: Server-Anreicherung schlaegt Client-Match (Screenshot-Runde 3)", () => {
  var preise = { "nvidia/nemotron-3-ultra-550b-a55b": {
    input: 0.5, output: 2.2, herkunft: "openrouter",
    katalog: { kontext_k: 262, herkunft: "US", match: "alias" } } };
  var [e] = bauePreisEintraege(preise, [], {});
  assert.equal(e.kontext, 262);            // Client-Match haette kein_modell geliefert
  assert.equal(e.herkunftLand, "US");
  assert.equal(e.matchStatus, "alias");
});

test("preisZeileHtml: Status-Zone unten -- Legacy-Chip ODER Sterne ODER Latest-Chip", () => {
  var [e] = bauePreisEintraege({ "glm-5.2": { input: 1.19, output: 3.74, herkunft: "ollama",
    katalog: { kontext_k: 1049, herkunft: "CN", hersteller: "Zhipu AI", match: "exakt",
               status: "legacy", nachfolger: "glm-5.3", sterne_gesamt: null } } }, [], {});
  var html = preisZeileHtml(e);
  assert.match(html, /class="mz-chip"><span class="mk-sterne mk-legacy-chip"/);
  assert.match(html, /Nachfolger: glm-5.3/);
  assert.doesNotMatch(html, /mz-sterne|mk-sterne"(?! mk-legacy)/);  // keine obere Sterne-Zone mehr
  var [aktuell] = bauePreisEintraege({ "x": { input: 1, output: 2, herkunft: "ollama",
    katalog: { kontext_k: 1, herkunft: "CN", hersteller: "X", match: "exakt",
               status: "latest", nachfolger: null, sterne_gesamt: null } } }, [], {});
  assert.match(preisZeileHtml(aktuell), /mk-latest-chip/);
  // Maintainer 2026-08-30 (Status-Zone): bewertete Modelle zeigen die STERNE auch in der
  // Preistabelle (server-Anreicherung liefert sterne_gesamt) -- unten rechts, kein Chip.
  var [bewertet] = bauePreisEintraege({ "glm-5.3": { input: 1.4, output: 4.4, herkunft: "ollama",
    katalog: { kontext_k: 1049, herkunft: "CN", hersteller: "Zhipu AI", match: "exakt",
               status: "bewertet", nachfolger: null, sterne_gesamt: 4.0 } } }, [], {});
  assert.equal(bewertet.status, "bewertet");
  var htmlB = preisZeileHtml(bewertet);
  assert.match(htmlB, /<span class="mk-sterne"/);
  assert.ok(htmlB.indexOf("hersteller") < htmlB.indexOf("mk-sterne"));  // unten, nicht oben
  assert.doesNotMatch(htmlB, /mk-legacy-chip|mk-latest-chip/);
});

test("bauePreisEintraege: Stand-Fallback auf Block-Stand, herkunftLand nur bei Match", () => {
  var rows = bauePreisEintraege({ "ohne-stand": { input: 1, output: 2, cache_write: 0, cache_read: 0, herkunft: "openai" } },
    [], {}, "2026-08-26");
  assert.equal(rows[0].stand, "2026-08-26");
  assert.equal(rows[0].herkunftLand, null);
});
