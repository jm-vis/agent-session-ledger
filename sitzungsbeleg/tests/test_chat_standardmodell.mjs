// Reine-Funktions-Test fuer chat.js `standardModell()` (Coordinator-Nachtrag: EINE Standard-
// Auswahllogik fuer alle drei Anbieter, mit Fixture-Listen, kein DOM/Browser noetig). Node hat
// keinen zusaetzlichen Testrunner im Repo -- `node:test`/`node:assert` sind Node-Stdlib (Node 24
// hier, kein neues Paket, YAGNI). Ausfuehren: `node scripts/sitzungsbeleg/tests/test_chat_standardmodell.mjs`
// (nicht Teil von `pytest` -- eigenstaendig, weil reines JS ohne Python-Bruecke).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  OPENROUTER_STANDARD_STATISCH, STANDARD_BEVORZUGT, setzeVicoStandards, standardModell,
} from "../static/js/chat.js";

function m(id, kontext) {
  return { id: id, kontext: kontext === undefined ? null : kontext };
}

test("claude: bevorzugtes Modell vorhanden -> gewinnt", () => {
  var liste = [m("claude-haiku-5"), m("claude-fable-5"), m("claude-sonnet-5")];
  assert.equal(standardModell("claude", liste), "claude-fable-5");
});

test("claude: bevorzugtes Modell fehlt -> erstes Modell der Liste", () => {
  var liste = [m("claude-haiku-5"), m("claude-sonnet-5")];
  assert.equal(standardModell("claude", liste), "claude-haiku-5");
});

// Ollama startet mit LEERER Praeferenzliste (Coordinator-Nachtrag, zweite Runde: der Standard
// kommt zur Laufzeit aus `scripts/modelle.json` `default_vico_ollama`, NICHT hartcodiert --
// `ladeModelle()` setzt `STANDARD_BEVORZUGT.ollama` genau so, wie es diese Tests hier simulieren).
test("ollama: STANDARD_BEVORZUGT.ollama startet leer (wird zur Laufzeit vom Backend befuellt)", () => {
  assert.deepEqual(STANDARD_BEVORZUGT.ollama, []);
});

test("ollama: leere Praeferenzliste -> erstes Modell der Liste", () => {
  var liste = [m("qwen3:14b"), m("mistral:7b")];
  assert.equal(standardModell("ollama", liste), "qwen3:14b");
});

test("ollama: von ladeModelle() befuellter Wert (default_vico_ollama) gewinnt, wenn vorhanden", () => {
  var alt = STANDARD_BEVORZUGT.ollama;
  try {
    STANDARD_BEVORZUGT.ollama = ["glm-5.2:cloud"]; // simuliert daten.ollama_standard aus dem Backend
    var liste = [m("qwen3:14b"), m("glm-5.2:cloud")];
    assert.equal(standardModell("ollama", liste), "glm-5.2:cloud");
  } finally {
    STANDARD_BEVORZUGT.ollama = alt;
  }
});

test("ollama: befuellter Standard fehlt im aktuellen Katalog -> erstes Modell der Liste", () => {
  var alt = STANDARD_BEVORZUGT.ollama;
  try {
    STANDARD_BEVORZUGT.ollama = ["glm-5.2:cloud"]; // Backend-Standard, aber gerade nicht geladen
    var liste = [m("qwen3:14b"), m("mistral:7b")];
    assert.equal(standardModell("ollama", liste), "qwen3:14b");
  } finally {
    STANDARD_BEVORZUGT.ollama = alt;
  }
});

// Ohne setzeVicoStandards() (kein Backend-Wert geladen) ist STANDARD_BEVORZUGT.openrouter nur
// die statische Restliste OPENROUTER_STANDARD_STATISCH -- deren erster Treffer gewinnt (auch
// ohne :free-Suffix, s. `minimax/minimax-m3`-Fall weiter unten).
test("openrouter: ohne Backend-Standard gewinnt der erste Treffer der statischen Liste", () => {
  var liste = [
    m("deepseek/deepseek-chat-v3-0324", 164000),
    m("z-ai/glm-5.2:free", 128000),
    m("minimax/minimax-m3", 1000000),
  ];
  assert.equal(standardModell("openrouter", liste), "z-ai/glm-5.2:free");
});

test("openrouter: keiner der bevorzugten vorhanden -> erstes :free-Modell", () => {
  var liste = [m("deepseek/deepseek-chat-v3-0324", 164000), m("mistralai/codestral-3:free", 32000)];
  assert.equal(standardModell("openrouter", liste), "mistralai/codestral-3:free");
});

test("openrouter: weder bevorzugt noch :free vorhanden -> erstes Modell ueberhaupt", () => {
  var liste = [m("deepseek/deepseek-chat-v3-0324", 164000), m("qwen/qwen3-max", 256000)];
  assert.equal(standardModell("openrouter", liste), "deepseek/deepseek-chat-v3-0324");
});

test("leere Liste -> null, egal welcher Anbieter", () => {
  assert.equal(standardModell("claude", []), null);
  assert.equal(standardModell("openrouter", []), null);
});

test("unbekannter Anbieter (nicht in STANDARD_BEVORZUGT) faellt sauber durch statt zu crashen", () => {
  var liste = [m("irgendein-modell:free"), m("anderes-modell")];
  assert.equal(standardModell("neuer-anbieter", liste), "irgendein-modell:free");
});

test("STANDARD_BEVORZUGT kennt alle vier ANBIETER-Ids", () => {
  assert.deepEqual(Object.keys(STANDARD_BEVORZUGT).sort(), ["claude", "ollama", "openrouter", "requesty"]);
});

// Requesty startet wie Ollama mit LEERER Praeferenzliste (Nachtrag 2026-08-28): der Standard
// kommt zur Laufzeit aus `scripts/modelle.json` `default_vico_requesty`, nicht hartcodiert.
test("requesty: STANDARD_BEVORZUGT.requesty startet leer (wird zur Laufzeit vom Backend befuellt)", () => {
  assert.deepEqual(STANDARD_BEVORZUGT.requesty, []);
});

test("requesty: leere Praeferenzliste -> erstes Modell der Liste", () => {
  var liste = [m("sference/glm-5.3-flash", 128000), m("sference/kimi-k3", 262144)];
  assert.equal(standardModell("requesty", liste), "sference/glm-5.3-flash");
});

test("requesty: von ladeModelle() befuellter Wert (default_vico_requesty) gewinnt, wenn vorhanden", () => {
  var alt = STANDARD_BEVORZUGT.requesty;
  try {
    STANDARD_BEVORZUGT.requesty = ["sference/kimi-k3"]; // simuliert daten.requesty_standard
    var liste = [m("sference/glm-5.3-flash", 128000), m("sference/kimi-k3", 262144)];
    assert.equal(standardModell("requesty", liste), "sference/kimi-k3");
  } finally {
    STANDARD_BEVORZUGT.requesty = alt;
  }
});

// Coordinator-Nachtrag (dritte Runde): setzeVicoStandards() ist die Bruecke zwischen der
// GET-/api/chat/modelle-Antwort und STANDARD_BEVORZUGT -- weder Ollama- noch OpenRouter-Standard
// sind hartcodiert, beide kommen aus `scripts/modelle.json` (`_vico_standard()` in chat.py).
function mitZurueckgesetztemStandard(fn) {
  var altOllama = STANDARD_BEVORZUGT.ollama, altOpenrouter = STANDARD_BEVORZUGT.openrouter,
      altRequesty = STANDARD_BEVORZUGT.requesty;
  try {
    fn();
  } finally {
    STANDARD_BEVORZUGT.ollama = altOllama;
    STANDARD_BEVORZUGT.openrouter = altOpenrouter;
    STANDARD_BEVORZUGT.requesty = altRequesty;
  }
}

test("setzeVicoStandards: alle drei Felder vorhanden -> ollama/requesty ersetzt, openrouter vorangestellt", () => {
  mitZurueckgesetztemStandard(() => {
    setzeVicoStandards({
      ollama_standard: "glm-5.2:cloud", openrouter_standard: "nvidia/nemotron-3-ultra-550b-a55b",
      requesty_standard: "sference/kimi-k3",
    });
    assert.deepEqual(STANDARD_BEVORZUGT.ollama, ["glm-5.2:cloud"]);
    assert.deepEqual(STANDARD_BEVORZUGT.openrouter, ["nvidia/nemotron-3-ultra-550b-a55b"].concat(OPENROUTER_STANDARD_STATISCH));
    assert.deepEqual(STANDARD_BEVORZUGT.requesty, ["sference/kimi-k3"]);
  });
});

test("setzeVicoStandards: alle Felder fehlen -> Fallback bleibt bestehen (leer/statisch)", () => {
  mitZurueckgesetztemStandard(() => {
    setzeVicoStandards({});
    assert.deepEqual(STANDARD_BEVORZUGT.ollama, []);
    assert.deepEqual(STANDARD_BEVORZUGT.openrouter, OPENROUTER_STANDARD_STATISCH);
    assert.deepEqual(STANDARD_BEVORZUGT.requesty, []);
  });
});

test("openrouter: vom Backend gesetzter Standard gewinnt vor der statischen Liste", () => {
  mitZurueckgesetztemStandard(() => {
    setzeVicoStandards({ openrouter_standard: "nvidia/nemotron-3-ultra-550b-a55b" });
    var liste = [m("z-ai/glm-5.2:free", 128000), m("nvidia/nemotron-3-ultra-550b-a55b", 1000000)];
    assert.equal(standardModell("openrouter", liste), "nvidia/nemotron-3-ultra-550b-a55b");
  });
});
