// Reine-Funktions-Test fuer die Modellkatalog-Seite (Paket L, CONTRACTS.md C15) --
// Muster tests/test_persona.mjs: reine Funktionen rein, kein DOM/Browser noetig.
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_katalog.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatPreisZahl, standDatumText, tooltipPreise, filtereModelle, sortiereModelle,
  kartenZaehlerText, standardHinweiseJeModell, quelleAnzeigeName, preisLeistungKennzahl,
  gruppiereWegeNachEbene, lokalZeileHtml, personaWegZeileHtml,
} from "../static/js/katalog.js";

test("formatPreisZahl: Zahl auf eine Nachkommastelle, Komma statt Punkt", () => {
  assert.equal(formatPreisZahl(0.5), "0,5");
  assert.equal(formatPreisZahl(15), "15,0");
  assert.equal(formatPreisZahl(2.34), "2,3");
});

test("formatPreisZahl: null/undefined -- 'lokal' statt erfundener Zahl, 0 bleibt 0,0", () => {
  assert.equal(formatPreisZahl(null), "On-Prem");
  assert.equal(formatPreisZahl(undefined), "On-Prem");
  assert.equal(formatPreisZahl(0), "0,0");
});

test("standDatumText: TT.MM.JJJJ aus ISO-Datum, leer bei fehlendem Wert", () => {
  assert.equal(standDatumText("2026-08-28"), "28.08.2026");
  assert.equal(standDatumText(null), "—");
  assert.equal(standDatumText(undefined), "—");
});

test("tooltipPreise: aufsteigend sortiert, Anzeige-Namen, nur ab zwei Preisen", () => {
  var anbieter = [
    { name: "ollama", ausgabe_usd: 2.5 }, { name: "requesty", ausgabe_usd: 2.3 }, { name: "openrouter", ausgabe_usd: 2.4 },
  ];
  assert.equal(tooltipPreise(anbieter, "ausgabe_usd"), "Requesty 2,3 · OpenRouter 2,4 · Ollama 2,5");
});

test("tooltipPreise: einziger Anbieter -- kein Tooltip (leerer String)", () => {
  assert.equal(tooltipPreise([{ name: "claude", ausgabe_usd: 15 }], "ausgabe_usd"), "");
});

test("tooltipPreise: fehlende Preise werden aus dem Tooltip ausgeschlossen", () => {
  var anbieter = [{ name: "ollama", ausgabe_usd: null }, { name: "openrouter", ausgabe_usd: 2 }, { name: "requesty", ausgabe_usd: 1.5 }];
  assert.equal(tooltipPreise(anbieter, "ausgabe_usd"), "Requesty 1,5 · OpenRouter 2,0");
});

function modell(id, ueberschreibungen) {
  return Object.assign({
    id: id, hersteller: "Anthropic", herkunft: "US", kontext_k: 200, aa_index: 70, coding_index: 70,
    anbieter: [{ name: "claude", eingabe_usd: 2, ausgabe_usd: 10, stand: "2026-08-20" }],
    preis_min: { eingabe_usd: 2, ausgabe_usd: 10, anbieter: "claude" }, stand_juengster: "2026-08-20",
  }, ueberschreibungen);
}

test("filtereModelle: Suche greift auf id UND hersteller, case-insensitiv", () => {
  var liste = [modell("claude-sonnet-5"), modell("deepseek-v4", { hersteller: "DeepSeek" })];
  assert.deepEqual(filtereModelle(liste, { suchtext: "DEEPSEEK" }).map((m) => m.id), ["deepseek-v4"]);
  assert.deepEqual(filtereModelle(liste, { suchtext: "sonnet" }).map((m) => m.id), ["claude-sonnet-5"]);
});

test("filtereModelle: Herkunft-Set schliesst nicht enthaltene Werte aus", () => {
  var liste = [modell("a", { herkunft: "US" }), modell("b", { herkunft: "CN" })];
  var gefiltert = filtereModelle(liste, { herkunftAktiv: new Set(["CN"]) });
  assert.deepEqual(gefiltert.map((m) => m.id), ["b"]);
});

test("filtereModelle: leere Herkunft-Auswahl = Vollansicht (Umkehr 2026-08-28)", () => {
  var liste = [modell("a", { herkunft: "US" }), modell("b", { herkunft: "CN" })];
  assert.deepEqual(filtereModelle(liste, { herkunftAktiv: new Set() }).map((m) => m.id), ["a", "b"]);
});

test("filtereModelle: Modelle ohne Herkunft laufen ueber den \"\"-Chip statt still zu verschwinden", () => {
  var liste = [modell("a", { herkunft: "US" }), modell("b", { herkunft: null })];
  assert.deepEqual(filtereModelle(liste, { herkunftAktiv: new Set(["US", ""]) }).map((m) => m.id), ["a", "b"]);
  assert.deepEqual(filtereModelle(liste, { herkunftAktiv: new Set(["US"]) }).map((m) => m.id), ["a"]);
});

test("filtereModelle: Anbieter-Set prueft ueberlappung mit der Anbieterliste des Modells", () => {
  var liste = [modell("a", { anbieter: [{ name: "claude" }] }), modell("b", { anbieter: [{ name: "ollama" }] })];
  var gefiltert = filtereModelle(liste, { anbieterAktiv: new Set(["ollama"]) });
  assert.deepEqual(gefiltert.map((m) => m.id), ["b"]);
});

// C15 v2 Punkt 3/6: zwei neutrale Zusatzfilter -- ausgeschaltet wirkungslos, eingeschaltet lassen
// sie ein Modell ohne das Flag (bzw. mit dem Flag = false) NICHT durch.
test("filtereModelle: nurLokal laesst nur modell.lokal===true durch, ausgeschaltet neutral", () => {
  var liste = [modell("a", { lokal: true }), modell("b", { lokal: false }), modell("c", {})];
  assert.deepEqual(filtereModelle(liste, { nurLokal: true }).map((m) => m.id), ["a"]);
  assert.deepEqual(filtereModelle(liste, { nurLokal: false }).map((m) => m.id), ["a", "b", "c"]);
});

test("filtereModelle: nurLokal an + Feld fehlt am Modell -- laesst NICHTS durch (kein stilles 'als ob')", () => {
  var liste = [modell("a", {})];
  assert.deepEqual(filtereModelle(liste, { nurLokal: true }).map((m) => m.id), []);
});

test("filtereModelle: euOhneTraining laesst nur modell.eu_ohne_training===true durch, ausgeschaltet neutral", () => {
  var liste = [modell("a", { eu_ohne_training: true }), modell("b", {})];
  assert.deepEqual(filtereModelle(liste, { euOhneTraining: true }).map((m) => m.id), ["a"]);
  assert.deepEqual(filtereModelle(liste, {}).map((m) => m.id), ["a", "b"]);
});

// "nur Latest" (Auftrag 2026-08-30, Korrektur -- kein STAND-Dropdown, dritte Checkbox neben
// nurLokal/euOhneTraining): angehakt blendet status==="legacy" aus, "bewertet"+"latest" bleiben.
test("filtereModelle: nurLatest blendet nur status=legacy aus, ausgeschaltet neutral", () => {
  var liste = [
    modell("a", { status: "bewertet" }), modell("b", { status: "latest" }), modell("c", { status: "legacy" }),
  ];
  assert.deepEqual(filtereModelle(liste, { nurLatest: true }).map((m) => m.id), ["a", "b"]);
  assert.deepEqual(filtereModelle(liste, { nurLatest: false }).map((m) => m.id), ["a", "b", "c"]);
  assert.deepEqual(filtereModelle(liste, {}).map((m) => m.id), ["a", "b", "c"]);
});

test("sortiereModelle: numerisch nach coding_index absteigend, fehlende Werte zuletzt", () => {
  var liste = [modell("a", { coding_index: 60 }), modell("b", { coding_index: null }), modell("c", { coding_index: 80 })];
  assert.deepEqual(sortiereModelle(liste, "coding_index", -1).map((m) => m.id), ["c", "a", "b"]);
});

test("sortiereModelle: text (id) alphabetisch, Original-Array bleibt unveraendert", () => {
  var liste = [modell("z-modell"), modell("a-modell")];
  var sortiert = sortiereModelle(liste, "id", 1);
  assert.deepEqual(sortiert.map((m) => m.id), ["a-modell", "z-modell"]);
  assert.equal(liste[0].id, "z-modell"); // Original unveraendert (keine In-Place-Mutation)
});

// C15 v2 Punkt 1/3: neue Eignung-Sortierspalten (Agentic/Geschwindigkeit) -- gleiche
// Nulls-ans-Ende-Logik wie coding_index/aa_index oben.
test("sortiereModelle: agentic_index absteigend, fehlende Werte zuletzt", () => {
  var liste = [modell("a", { agentic_index: 40 }), modell("b", { agentic_index: null }), modell("c", { agentic_index: 90 })];
  assert.deepEqual(sortiereModelle(liste, "agentic_index", -1).map((m) => m.id), ["c", "a", "b"]);
});

test("sortiereModelle: tempo_tok_s absteigend, fehlende Werte zuletzt", () => {
  var liste = [modell("a", { tempo_tok_s: 50 }), modell("b", {}), modell("c", { tempo_tok_s: 120 })];
  assert.deepEqual(sortiereModelle(liste, "tempo_tok_s", -1).map((m) => m.id), ["c", "a", "b"]);
});

test("preisLeistungKennzahl: aa_index geteilt durch Mischpreis (3*eingabe+ausgabe)/4", () => {
  var m = modell("a", { aa_index: 80, preis_min: { eingabe_usd: 1, ausgabe_usd: 5 } });
  // Mischpreis = (3*1 + 5) / 4 = 2 -> 80 / 2 = 40
  assert.equal(preisLeistungKennzahl(m), 40);
});

test("preisLeistungKennzahl: fehlt aa_index ODER ein Preis -- null statt erfundener Zahl", () => {
  assert.equal(preisLeistungKennzahl(modell("a", { aa_index: null, preis_min: { eingabe_usd: 1, ausgabe_usd: 5 } })), null);
  assert.equal(preisLeistungKennzahl(modell("a", { aa_index: 80, preis_min: { eingabe_usd: null, ausgabe_usd: 5 } })), null);
  assert.equal(preisLeistungKennzahl(modell("a", { aa_index: 80, preis_min: { eingabe_usd: 1, ausgabe_usd: null } })), null);
});

test("sortiereModelle: preisleistung absteigend ueber die Kennzahl, Modelle ohne Kennzahl zuletzt", () => {
  var liste = [
    modell("teuer", { aa_index: 80, preis_min: { eingabe_usd: 10, ausgabe_usd: 30 } }), // (30+30)/4=15 -> 80/15=5.33
    modell("guenstig", { aa_index: 70, preis_min: { eingabe_usd: 1, ausgabe_usd: 2 } }), // (3+2)/4=1.25 -> 70/1.25=56
    modell("lokal", { aa_index: 60, preis_min: { eingabe_usd: null, ausgabe_usd: null } }),
  ];
  assert.deepEqual(sortiereModelle(liste, "preisleistung", -1).map((m) => m.id), ["guenstig", "teuer", "lokal"]);
});

test("kartenZaehlerText: Modelle/Anbieter-Zaehler + Stand je Quelle", () => {
  var liste = [modell("a", { anbieter: [{ name: "claude" }] }), modell("b", { anbieter: [{ name: "ollama" }] })];
  var text = kartenZaehlerText(liste, { claude: "2026-08-20", ollama: "2026-08-28" });
  assert.match(text, /^2 Modelle · 2 Anbieter · Stand /);
  assert.match(text, /Claude 20\.08\.2026/);
  assert.match(text, /Ollama 28\.08\.2026/);
});

test("kartenZaehlerText: leerer Katalog -- Hinweis auf katalog-update statt '0 Anbieter'", () => {
  assert.match(kartenZaehlerText([], {}), /katalog-update/);
});

// C15 v2 Punkt 1/4 (Attributionspflicht): "artificial_analysis" im stand-Block haengt als eigener
// Satzteil an, laeuft NICHT durch die generische Anbieter-Stand-Liste.
test("kartenZaehlerText: stand.artificial_analysis haengt Attributionstext an", () => {
  var liste = [modell("a", { anbieter: [{ name: "claude" }] })];
  var text = kartenZaehlerText(liste, { claude: "2026-08-20", artificial_analysis: "2026-08-28" });
  assert.match(text, /Claude 20\.08\.2026/);
  assert.doesNotMatch(text, /Artificial_analysis|Artificial-analysis/);
  assert.match(text, /Indizes Artificial Analysis 28\.08\.2026$/);
});

test("kartenZaehlerText: stand.artificial_analysis fehlt/null -- rendert wie heute, kein Anhang", () => {
  var liste = [modell("a", { anbieter: [{ name: "claude" }] })];
  assert.doesNotMatch(kartenZaehlerText(liste, { claude: "2026-08-20" }), /Artificial Analysis/);
  assert.doesNotMatch(kartenZaehlerText(liste, { claude: "2026-08-20", artificial_analysis: null }), /Artificial Analysis/);
});

test("standardHinweiseJeModell: primaerer Weg markiert das Modell, nicht-primaere nicht", () => {
  var wege = {
    vico: { wege: [{ quelle: "claude", modell: "claude-sonnet-5", primaer: true }, { quelle: "ollama", modell: "glm-5.2:cloud", primaer: false }] },
  };
  var karten = standardHinweiseJeModell(wege);
  assert.deepEqual(karten["claude-sonnet-5"], ["VICO primär (Claude)"]);
  assert.equal(karten["glm-5.2:cloud"], undefined);
});

// C15 v2 Punkt 5: `ebene` ("offen"|"geschuetzt") ersetzt das aeltere freie `gruppe`-Textfeld.
test("standardHinweiseJeModell: ebene (z. B. CURA 'geschuetzt') haengt klein an", () => {
  var wege = { cura: { wege: [{ quelle: "ollama", modell: "qwen3.5:9b", primaer: true, ebene: "geschuetzt" }] } };
  assert.deepEqual(standardHinweiseJeModell(wege)["qwen3.5:9b"], ["CURA (geschuetzt) primär (Ollama)"]);
});

test("standardHinweiseJeModell: ebene fehlt -- kein Klammerzusatz (fehlend = offen)", () => {
  var wege = { cura: { wege: [{ quelle: "ollama", modell: "minimax-m3:cloud", primaer: true }] } };
  assert.deepEqual(standardHinweiseJeModell(wege)["minimax-m3:cloud"], ["CURA primär (Ollama)"]);
});

test("standardHinweiseJeModell: fehlender/leerer Block -- leeres Objekt", () => {
  assert.deepEqual(standardHinweiseJeModell({}), {});
  assert.deepEqual(standardHinweiseJeModell(undefined), {});
});

test("quelleAnzeigeName: bekannte Codes -- Anzeige-Name, Ollama neutral wie ueberall sonst", () => {
  assert.equal(quelleAnzeigeName("claude"), "Claude");
  assert.equal(quelleAnzeigeName("ollama"), "Ollama");
  assert.equal(quelleAnzeigeName("openrouter"), "OpenRouter");
  assert.equal(quelleAnzeigeName("requesty"), "Requesty");
});

// Nachtrag VICO-Abnahme 2026-08-28: persona_wege kommt aus modelle.json als FLACHE Liste
// je Persona (Backend 24b8df9) -- der Renderer muss beide Formen lesen.
import { personaWegeListe } from "../static/js/katalog.js";

test("personaWegeListe: flache Liste (Backend-Form) wird durchgereicht", () => {
  const liste = [{ quelle: "claude", modell: "claude-fable-5", primaer: true }];
  assert.deepEqual(personaWegeListe(liste), liste);
});

test("personaWegeListe: Objektform {wege} und Leerfaelle", () => {
  const wege = [{ quelle: "ollama", modell: "glm-5.2:cloud", primaer: true }];
  assert.deepEqual(personaWegeListe({ rolle: "Academy", wege }), wege);
  assert.deepEqual(personaWegeListe(undefined), []);
  assert.deepEqual(personaWegeListe({}), []);
});

test("standardHinweiseJeModell: flache Backend-Form liefert Pin-Hinweise", () => {
  const hin = standardHinweiseJeModell({ vico: [{ quelle: "claude", modell: "claude-fable-5", primaer: true }] });
  assert.equal(hin["claude-fable-5"].length, 1);
  assert.match(hin["claude-fable-5"][0], /VICO/);
});

// ================= CURA-Ebenen-Gruppierung (C15 v2 Punkt 5) =================

test("gruppiereWegeNachEbene: kein geschuetzter Weg -- EINE Gruppe ohne Titel (VICO/VICA unveraendert)", () => {
  const wege = [{ quelle: "claude", modell: "claude-sonnet-5", primaer: true }];
  assert.deepEqual(gruppiereWegeNachEbene(wege), [{ titel: null, wege }]);
});

test("gruppiereWegeNachEbene: Mix aus offen (fehlend) und geschuetzt -- Titel 'Offen'/'Nur lokal', Reihenfolge offen zuerst", () => {
  const offenWeg = { quelle: "ollama", modell: "minimax-m3:cloud", primaer: true };
  const geschuetztWeg = { quelle: "ollama", modell: "qwen3.5:9b", primaer: true, ebene: "geschuetzt" };
  assert.deepEqual(gruppiereWegeNachEbene([offenWeg, geschuetztWeg]), [
    { titel: "Offen", wege: [offenWeg] },
    { titel: "Nur On-Premise", wege: [geschuetztWeg] },
  ]);
});

test("gruppiereWegeNachEbene: explizites ebene:'offen' zaehlt wie fehlend zur 'Offen'-Gruppe", () => {
  const offenWeg = { quelle: "ollama", modell: "minimax-m3:cloud", primaer: true, ebene: "offen" };
  const geschuetztWeg = { quelle: "ollama", modell: "qwen3.5:9b", primaer: true, ebene: "geschuetzt" };
  const gruppen = gruppiereWegeNachEbene([offenWeg, geschuetztWeg]);
  assert.equal(gruppen[0].titel, "Offen");
  assert.deepEqual(gruppen[0].wege, [offenWeg]);
});

test("gruppiereWegeNachEbene: leere/fehlende Liste -- eine leere Gruppe ohne Titel", () => {
  assert.deepEqual(gruppiereWegeNachEbene([]), [{ titel: null, wege: [] }]);
  assert.deepEqual(gruppiereWegeNachEbene(undefined), [{ titel: null, wege: [] }]);
});

// ================= LOKAL-Karte: Pin-Renderer (C15 v2 Punkt 5) =================

test("lokalZeileHtml: cura_primaer===true rendert li.primaer + Zusatztext, wenn nicht schon im Kommentar", () => {
  const html = lokalZeileHtml({ modellname: "qwen3.5:9b", sterne: 3, kommentar: "CURA-Kandidat", cura_primaer: true });
  assert.match(html, /<li class="primaer">/);
  assert.match(html, /CURA geschützt primär/);
  assert.equal((html.match(/CURA geschützt primär/g) || []).length, 1);
});

test("lokalZeileHtml: aelteres Feld 'primaer' funktioniert weiter (Backend-Uebergang)", () => {
  const html = lokalZeileHtml({ modellname: "qwen3.5:9b", sterne: 3, primaer: true });
  assert.match(html, /<li class="primaer">/);
  assert.match(html, /CURA geschützt primär/);
});

test("lokalZeileHtml: Backend liefert Zusatztext bereits im Kommentar -- kein Duplikat", () => {
  const html = lokalZeileHtml({ modellname: "qwen3.5:9b", sterne: 3, kommentar: "CURA geschützt primär", cura_primaer: true });
  assert.equal((html.match(/CURA geschützt primär/g) || []).length, 1);
});

test("lokalZeileHtml: nicht-primaere Zeile -- kein li.primaer, kein Zusatztext", () => {
  const html = lokalZeileHtml({ modellname: "nomic-embed-text", sterne: null, kommentar: "Embeddings" });
  assert.doesNotMatch(html, /class="primaer"/);
  assert.doesNotMatch(html, /CURA geschützt primär/);
  assert.match(html, /Embeddings/);
});

// ================= Panels: keine Flagge/Pin/HF-Abzeichen mehr (Abnahme 2026-08-30 Fix 2) ====

test("lokalZeileHtml: hf.co-Modell zeigt NUR den Modellnamen (kein Org/Quant) im sichtbaren Text, voller Pfad bleibt im Tooltip", () => {
  const html = lokalZeileHtml({ modellname: "hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M", sterne: null, kommentar: "" });
  assert.match(html, />DeepSeek-R1-0528-Qwen3-8B</);  // sichtbarer Text: reiner Modellname
  assert.doesNotMatch(html, /Qwen3-8B · Q4_K_M/);      // KEIN Org/Quant-Anhang wie in der Tabelle
  assert.match(html, /title="hf\.co\/unsloth\/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M"/);  // voller Pfad im Tooltip
  assert.doesNotMatch(html, /hf-quelle/);
  assert.doesNotMatch(html, /🤗/);
});

test("lokalZeileHtml: gruener Erreichbarkeits-Punkt vor dem Namen (Entscheid 2026-08-30 Nachtrag 6)", () => {
  const html = lokalZeileHtml({ modellname: "qwen3.5:9b", sterne: null, kommentar: "" });
  assert.match(html, /erreichbar-punkt/);
});

test("lokalZeileHtml: kurzes Fach-Tag (<=3 Woerter) wird angezeigt", () => {
  const html = lokalZeileHtml({ modellname: "nomic-embed-text", sterne: null, kommentar: "Embedding" });
  assert.match(html, /Embedding/);
  assert.doesNotMatch(html, /title="Embedding"/);
});

test("lokalZeileHtml: langer Kommentar (>3 Woerter) nur im Tooltip, nicht im sichtbaren Text", () => {
  const html = lokalZeileHtml({
    modellname: "nomic-embed-text", sterne: null,
    kommentar: "Dieser Kommentar ist deutlich zu lang fuer die Zeile",
  });
  assert.doesNotMatch(html, /<span class="sterne">/);
  assert.match(html, /title="Dieser Kommentar ist deutlich zu lang fuer die Zeile"/);
});

test("personaWegZeileHtml: kein Flaggen-SVG, kein Pin-Text, kein HF-Abzeichen -- nur Chip + Erreichbarkeits-Punkt", () => {
  const html = personaWegZeileHtml({ quelle: "claude", modell: "claude-fable-5", primaer: true });
  assert.doesNotMatch(html, /flagge-svg/);
  assert.doesNotMatch(html, /herkunft-fallback/);
  assert.doesNotMatch(html, /📌/);
  assert.doesNotMatch(html, /hf-quelle/);
  assert.match(html, /erreichbar-punkt/);
  assert.match(html, /claude-fable-5/);
});

test("personaWegZeileHtml: hf.co-Modell zeigt NUR den Modellnamen (kein Org/Quant) im sichtbaren Text, voller Pfad bleibt im Tooltip", () => {
  const html = personaWegZeileHtml({ quelle: "ollama", modell: "hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M" });
  assert.match(html, />DeepSeek-R1-0528-Qwen3-8B</);
  assert.doesNotMatch(html, /Qwen3-8B · Q4_K_M/);
  assert.match(html, /title="hf\.co\/unsloth\/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M"/);
  assert.doesNotMatch(html, /hf-quelle/);
  assert.doesNotMatch(html, /🤗/);
});

import { kurzeWegId } from "../static/js/katalog.js";
import { modellZeileHtml } from "../static/js/katalog.js";

test("kurzeWegId: Anbieter-Praefix und Varianten-Zusaetze fallen weg (Maintainer 2026-08-28)", () => {
  assert.equal(kurzeWegId("nvidia/nemotron-3-ultra-550b-a55b"), "nemotron-3-ultra-550b-a55b");
  assert.equal(kurzeWegId("sference/kimi-k3"), "kimi-k3");
  assert.equal(kurzeWegId("bedrock/claude-haiku-4-5@eu-central-1"), "claude-haiku-4-5");
  assert.equal(kurzeWegId("z-ai/glm-5.3-flash:batch"), "glm-5.3-flash");
});

test("kurzeWegId: Ollama-Tags wie :cloud bleiben stehen", () => {
  assert.equal(kurzeWegId("glm-5.2:cloud"), "glm-5.2:cloud");
  assert.equal(kurzeWegId("qwen3.5:9b"), "qwen3.5:9b");
});

// ---------- Automatische Katalog-Sterne v2 (Entscheid 2026-08-30 Nachtrag 6) ----------
import {
  gesamtSterneText, sterneTooltipText, latestChipHtml, sterneZaehlung, fuenfSterneHtml,
} from "../static/js/katalog.js";

test("gesamtSterneText: halbe Sterne als Zahl mit einer Nachkommastelle", () => {
  assert.equal(gesamtSterneText({ gesamt: 4.5 }), "4,5 ★");
  assert.equal(gesamtSterneText({ gesamt: 5 }), "5,0 ★");
  assert.equal(gesamtSterneText({ gesamt: 0.5 }), "0,5 ★");
});

test("gesamtSterneText: unbewertet (gesamt null/fehlend) zeigt Gedankenstrich, keine erfundene Zahl", () => {
  assert.equal(gesamtSterneText({ gesamt: null }), "–");
  assert.equal(gesamtSterneText({}), "–");
  assert.equal(gesamtSterneText(undefined), "–");
});

// ---------- Fuenf-Sterne-Widget (Abnahme 2026-08-30: immer 5 Sterne, keine Zahl davor) -----
test("sterneZaehlung: korrekte Anzahl voll/halb/leer bei 0, 0,5, 2,5 und 5", () => {
  assert.deepEqual(sterneZaehlung(0), { voll: 0, halb: 0, leer: 5 });
  assert.deepEqual(sterneZaehlung(0.5), { voll: 0, halb: 1, leer: 4 });
  assert.deepEqual(sterneZaehlung(2.5), { voll: 2, halb: 1, leer: 2 });
  assert.deepEqual(sterneZaehlung(5), { voll: 5, halb: 0, leer: 0 });
});

test("sterneZaehlung: unbewertet (null/undefined) wie 0 -- 5 leere Sterne, kein Absturz", () => {
  assert.deepEqual(sterneZaehlung(null), { voll: 0, halb: 0, leer: 5 });
  assert.deepEqual(sterneZaehlung(undefined), { voll: 0, halb: 0, leer: 5 });
});

test("fuenfSterneHtml: immer genau 5 Sterne-SVGs, Anzahl voll/halb/leer stimmt mit sterneZaehlung", () => {
  [0, 0.5, 2.5, 5].forEach((gesamt) => {
    const html = fuenfSterneHtml(gesamt, "modell-x");
    const treffer = html.match(/<svg class="mk-stern"/g) || [];
    assert.equal(treffer.length, 5, `gesamt=${gesamt} liefert 5 Sterne`);
    const z = sterneZaehlung(gesamt);
    assert.equal((html.match(/class="mk-stern-voll" d=/g) || []).length, z.voll);
    assert.equal((html.match(/class="mk-stern-leer" d=/g) || []).length, z.leer);
    assert.equal((html.match(/<linearGradient/g) || []).length, z.halb);
  });
});

test("fuenfSterneHtml: kein Zahlenpraefix -- kein sichtbarer Ziffern-/Kommatext im Markup", () => {
  [0, 0.5, 2.5, 5].forEach((gesamt) => {
    const html = fuenfSterneHtml(gesamt, "modell-x");
    // einzige Ziffern im Markup sind SVG-Koordinaten/viewBox/Gradient-Offsets, keine sichtbare
    // Bewertungszahl -- pruefen ueber den fuer den Nutzer sichtbaren Text (alles ausserhalb von
    // Tags), der muss komplett leer sein.
    const sichtbarerText = html.replace(/<[^>]*>/g, "").trim();
    assert.equal(sichtbarerText, "");
  });
});

test("fuenfSterneHtml: Gradient-IDs sind eindeutig je Modell (kein Kollisionsrisiko im DOM)", () => {
  const htmlA = fuenfSterneHtml(2.5, "claude-opus-5");
  const htmlB = fuenfSterneHtml(2.5, "claude-haiku-4-5");
  const idA = htmlA.match(/id="([^"]+)"/)[1];
  const idB = htmlB.match(/id="([^"]+)"/)[1];
  assert.notEqual(idA, idB);
});

// Zusatz 2026-08-30: der eine Pfad, der den Halbstern per Gradient fuellt, traegt jetzt
// zusaetzlich `mk-stern-halb`, damit style.css eine duenne Kontur (--rand-stark) ziehen kann,
// ohne die vollen (goldenen) Sterne anzufassen -- Regressionsschutz fuer die Klasse selbst.
test("fuenfSterneHtml: der Halbstern-Pfad traegt mk-stern-halb (Kontur-Anschluss fuer style.css)", () => {
  const html = fuenfSterneHtml(2.5, "modell-x");
  assert.match(html, /<path class="mk-stern-halb" fill="url\(#[^)]+\)"/);
  const htmlOhneHalb = fuenfSterneHtml(5, "modell-x");
  assert.doesNotMatch(htmlOhneHalb, /mk-stern-halb/);
});

test("sterneTooltipText: Score/AA/Coding/Bild-Aufschluesselung, unbewertet als Strich", () => {
  const text = sterneTooltipText({ sterne: { score: 70.5, gesamt: 5 }, aa_index: 63, coding_index: 78, vision: true });
  assert.equal(text, "Score 70,5 · AA 63 · Coding 78 · Bild ja");
});

test("sterneTooltipText: fehlende Werte zeigen Strich, Bild-Flag kennt drei Zustaende", () => {
  assert.equal(sterneTooltipText({ sterne: {}, aa_index: null, coding_index: null, vision: false }),
    "Score – · AA – · Coding – · Bild nein");
  assert.equal(sterneTooltipText({ sterne: {}, vision: null }), "Score – · AA – · Coding – · Bild unbekannt");
});

test("sterneTooltipText: manuelle Registry-Sterne haengen als 'eigener Test' an, nicht als Basis", () => {
  const text = sterneTooltipText({
    sterne: {
      score: 60, gesamt: 4,
      manuell: { coding: 3, reasoning: 3, gesamt: 5, kommentar: "graphify-Test 2026-06-14" },
    },
    aa_index: 60, coding_index: 60, vision: null,
  });
  assert.match(text, /eigener Test: Coding ⭐⭐⭐ \| Reasoning ⭐⭐⭐ \| Gesamt ⭐⭐⭐⭐⭐/);
  assert.match(text, /graphify-Test 2026-06-14/);
});

test("sterneTooltipText: ohne manuellen Eintrag kein 'eigener Test'-Zusatz", () => {
  const text = sterneTooltipText({ sterne: { score: 40, gesamt: 2, manuell: null }, aa_index: 40, coding_index: 40 });
  assert.doesNotMatch(text, /eigener Test/);
});

test("latestChipHtml: 'Latest'-Text", () => {
  assert.match(latestChipHtml(), />Latest</);
});

test("latestChipHtml: traegt mk-sterne (gleiche Zellenbreite) + mk-latest-chip (Kontrast-Klasse)", () => {
  assert.match(latestChipHtml(), /class="mk-sterne mk-latest-chip"/);
});

// ---------- Legacy-Chip (Entscheid 2026-08-30 C) ----------
import { legacyChipHtml } from "../static/js/katalog.js";

test("legacyChipHtml: 'Legacy'-Text, Tooltip nennt den Nachfolger", () => {
  const html = legacyChipHtml("claude-opus-5");
  assert.match(html, />Legacy</);
  assert.match(html, /title="Nachfolger: claude-opus-5"/);
});

test("legacyChipHtml: traegt mk-sterne (gleiche Zellenbreite) + mk-legacy-chip", () => {
  assert.match(legacyChipHtml("claude-opus-5"), /class="mk-sterne mk-legacy-chip"/);
});

test("legacyChipHtml: escaped HTML-Sonderzeichen im Nachfolgernamen", () => {
  const html = legacyChipHtml('"><script>');
  assert.doesNotMatch(html, /<script>/);
});

// ---------- Modellname-Kurzform + hf.co-Kurzform (Entscheid 2026-08-30 D) ----------
import { hfCoTeile, modellAnzeigeName, modellNameHtml, herkunftFlaggeHtml } from "../static/js/format.js";

test("modellAnzeigeName: :cloud/-cloud/:latest fallen weg", () => {
  assert.equal(modellAnzeigeName("glm-5.3:cloud"), "glm-5.3");
  assert.equal(modellAnzeigeName("gpt-oss:20b-cloud"), "gpt-oss:20b");
  assert.equal(modellAnzeigeName("nomic-embed-text:latest"), "nomic-embed-text");
});

test("modellAnzeigeName: Anbieter-Praefix/@region/:flex-batch-free fallen weg (wie kurzeWegId)", () => {
  assert.equal(modellAnzeigeName("nvidia/nemotron-3-ultra-550b-a55b"), "nemotron-3-ultra-550b-a55b");
  assert.equal(modellAnzeigeName("bedrock/claude-haiku-4-5@eu-central-1"), "claude-haiku-4-5");
  assert.equal(modellAnzeigeName("z-ai/glm-5.3-flash:batch"), "glm-5.3-flash");
});

test("hfCoTeile: parst Organisation/Modell/Quantisierung aus der hf.co-ID", () => {
  assert.deepEqual(hfCoTeile("hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M"),
    { org: "unsloth", modell: "DeepSeek-R1-0528-Qwen3-8B", quant: "Q4_K_M" });
  assert.equal(hfCoTeile("glm-5.2:cloud"), null);
});

test("modellAnzeigeName: hf.co-IDs als '<Modell> · <Quant> · <Org>', Org bleibt erhalten", () => {
  assert.equal(modellAnzeigeName("hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M"),
    "DeepSeek-R1-0528-Qwen3-8B · Q4_K_M · unsloth");
  assert.equal(modellAnzeigeName("hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q4_K_M"),
    "EuroLLM-9B-Instruct-2512 · Q4_K_M · mradermacher");
});

test("modellAnzeigeName: nurModellname=true zeigt bei hf.co-IDs NUR den Modellnamen (Entscheid 2026-08-30 Nachtrag 6)", () => {
  assert.equal(modellAnzeigeName("hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M", true),
    "DeepSeek-R1-0528-Qwen3-8B");
});

test("modellAnzeigeName: nurModellname aendert nichts an Nicht-hf.co-IDs", () => {
  assert.equal(modellAnzeigeName("glm-5.3:cloud", true), "glm-5.3");
});

test("modellNameHtml: Tooltip zeigt die volle Roh-ID, hf.co-Treffer bekommt das HF-Kennzeichen", () => {
  const normal = modellNameHtml("glm-5.3:cloud", "name");
  assert.match(normal, /title="glm-5\.3:cloud"/);
  assert.match(normal, />glm-5\.3</);
  assert.doesNotMatch(normal, /hf-quelle/);
  const hf = modellNameHtml("hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M");
  assert.match(hf, /hf-quelle/);
  assert.match(hf, /HF-Quelle, lokal gespeichert/);
});

test("modellNameHtml: mitBadge=false unterdrueckt das HF-Abzeichen (Abnahme 2026-08-30 Fix 2, Panels)", () => {
  const html = modellNameHtml("hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M", "modell", false);
  assert.doesNotMatch(html, /hf-quelle/);
  assert.match(html, />DeepSeek-R1-0528-Qwen3-8B · Q4_K_M · unsloth</);
});

test("herkunftFlaggeHtml: bekannter Code -> SVG-Flagge, unbekannter Code -> Kuerzel-Fallback, leer -> nichts", () => {
  assert.match(herkunftFlaggeHtml("US"), /<svg class="flagge-svg"/);
  assert.match(herkunftFlaggeHtml("zz"), /herkunft-fallback/);
  assert.equal(herkunftFlaggeHtml(null), "");
});

// Maintainer 2026-08-30 (Status-Zone unten, revidiert die Zweizeilen-Regel vom selben Tag): Zeile 1 =
// nur der Name ueber die VOLLE Breite (keine rechte Spur -- Sterne oben kollidierten mit langen
// Namen); Zeile 2 = Hersteller links + EINE Status-Zone rechts: Legacy-Chip ODER Sterne
// (bewertet) ODER Latest-Chip -- genau ein Zustand je Modell.
test("modellZeileHtml: Status-Zone unten rechts -- Chip ODER Sterne, Name oben ohne Nebenspur", () => {
  const legacy = modellZeileHtml({
    id: "glm-5.2", hersteller: "Zhipu AI", herkunft: "CN", kontext_k: 131,
    anbieter: [{ name: "openrouter", eingabe_usd: 1.19, ausgabe_usd: 3.74 }],
    preis_min: { eingabe_usd: 1.19, ausgabe_usd: 3.74, anbieter: "openrouter" },
    status: "legacy", nachfolger: "glm-5.3",
    aa_index: 50, coding_index: 50, stand_juengster: "2026-08-30", sterne: {},
  }, {});
  assert.match(legacy, /class="mz-top"/);
  assert.match(legacy, /class="mz-chip"/);
  assert.match(legacy, /Legacy/);
  // Reihenfolge im Markup: Name (oben, volle Breite) -> Hersteller (unten) -> Status-Zone
  assert.ok(legacy.indexOf("mz-top") < legacy.indexOf("hersteller"));
  assert.ok(legacy.indexOf("hersteller") < legacy.indexOf("mz-chip"));
  assert.doesNotMatch(legacy, /mz-sterne/);                   // obere Sterne-Zone entfaellt
  assert.doesNotMatch(legacy, /<span class="mk-sterne"/);     // legacy: keine Sterne

  const bewertet = modellZeileHtml({
    id: "glm-5.3", hersteller: "Zhipu AI", herkunft: "CN", kontext_k: 1311,
    anbieter: [{ name: "openrouter", eingabe_usd: 1.4, ausgabe_usd: 4.4 }],
    preis_min: { eingabe_usd: 1.4, ausgabe_usd: 4.4, anbieter: "openrouter" },
    status: "bewertet", aa_index: 60, coding_index: 75,
    stand_juengster: "2026-08-30", sterne: { score: 67.5, gesamt: 4.0, manuell: null },
  }, {});
  assert.match(bewertet, /<span class="mk-sterne"/);          // Sterne in der Status-Zone
  assert.ok(bewertet.indexOf("hersteller") < bewertet.indexOf("mz-chip"));  // unten rechts
  assert.doesNotMatch(bewertet, /mz-sterne/);
  assert.doesNotMatch(bewertet, /mk-legacy-chip|mk-latest-chip/);

  const latest = modellZeileHtml({
    id: "gpt-oss:20b-cloud", hersteller: "OpenAI", herkunft: "US", kontext_k: 131,
    anbieter: [{ name: "ollama", eingabe_usd: 0, ausgabe_usd: 0 }],
    preis_min: { eingabe_usd: 0, ausgabe_usd: 0, anbieter: "ollama" },
    status: "latest", aa_index: null, coding_index: null,
    stand_juengster: "2026-08-30", sterne: {},
  }, {});
  assert.match(latest, /mk-latest-chip/);
  assert.doesNotMatch(latest, /<span class="mk-sterne"/);     // latest ohne Score: keine Sterne
});
