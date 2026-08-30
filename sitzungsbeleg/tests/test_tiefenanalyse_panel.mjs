// Reine-Funktions-Test fuer tiefenanalyse.js' Panel-Rendering (Phase 3 I, C10) -- Fixture-JSON
// rein, erwartetes HTML-Fragment raus, kein DOM/Browser noetig (Muster test_chat_sicht.mjs).
// Deckt die B1/B2-Zustaende aus dem Mockup ab (sitzungsbeleg-chat-mockup.html Teil B).
// Ausfuehren: `node scripts/sitzungsbeleg/tests/test_tiefenanalyse_panel.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { panelInhaltHtml } from "../static/js/tiefenanalyse.js";

function seite(overrides) {
  return Object.assign({
    ursache_kategorie: "Heredoc-Backslash", befund: "Der Bash-Aufruf brach mit Exit 1 ab.",
    empfehlung: "Heredocs kuenftig ueber eine Vorlage erzeugen.", urteil: "ja", komplexitaet: "einfach",
  }, overrides);
}

function b1Fixture() {
  return {
    schema: 1, scope: "befund", signatur: "rework:tool:Bash", sitzung_logisch: 1284, position: 41,
    runde: 11, stufe: 2, ursache_kategorie: "Heredoc-Backslash",
    befund: "Der Bash-Aufruf brach mit Exit 1 ab.", empfehlung: "Heredocs kuenftig ueber eine Vorlage erzeugen.",
    urteil: "uebereinstimmend",
    positionen: { claude: seite({}), codex: seite({ ursache_kategorie: "Heredoc-Backslash" }) },
    modell: "claude-sonnet-5", modell_stufe2: "gpt-5.5", redaktion_version: "2026-08-28",
    zeitstempel: "2026-08-28T14:30:12+02:00", dauer_ms: 4200, commits: ["a1b2c3d"], nur_lokal: false,
    fehler: null,
  };
}

function b2Fixture() {
  return {
    ...b1Fixture(), urteil: "dissens",
    positionen: {
      claude: seite({ ursache_kategorie: "Heredoc-Backslash", urteil: "ja" }),
      codex: seite({ ursache_kategorie: "Gewollte Retry-Logik Fan-out", urteil: "nein", komplexitaet: null }),
    },
  };
}

function ohneZweitmeinungFixture() {
  return { ...b1Fixture(), urteil: "ohne_zweitmeinung", positionen: { claude: seite({}), codex: null } };
}

test("B1 uebereinstimmend: Pille, beide Spalten, KEIN Entscheid-Block", () => {
  var html = panelInhaltHtml(b1Fixture(), [{ hash: "a1b2c3d", zeit: "t", betreff: "fix heredoc" }]);
  assert.match(html, /data-status="uebereinstimmend"/);
  assert.match(html, /übereinstimmend/);
  assert.equal((html.match(/ta-spalte-kopf/g) || []).length, 2);
  assert.doesNotMatch(html, /ta-entscheid/);
});

test("B1: Klartext-Karte zeigt Konsens-Status, kein 'Entscheidung offen'", () => {
  var html = panelInhaltHtml(b1Fixture(), []);
  assert.doesNotMatch(html, /Entscheidung offen/);
  assert.match(html, /Bestätigt \(Claude \+ Codex einig\)/);
});

test("B2 dissens: Pille, beide Spalten mit abweichender Ursache, Entscheid-Block vorhanden", () => {
  var html = panelInhaltHtml(b2Fixture(), []);
  assert.match(html, /data-status="dissens"/);
  assert.match(html, /Dissens/);
  assert.match(html, /Heredoc-Backslash/);
  assert.match(html, /Gewollte Retry-Logik Fan-out/);
  assert.match(html, /ta-entscheid/);
  assert.match(html, /Entscheidung offen/);
  assert.match(html, /Claude folgen/);
  assert.match(html, /Codex folgen/);
});

test("ohne_zweitmeinung: nur eine Modellspalte, kein Entscheid-Block", () => {
  var html = panelInhaltHtml(ohneZweitmeinungFixture(), []);
  assert.match(html, /data-status="ohne_zweitmeinung"/);
  assert.match(html, /ohne Zweitmeinung/);
  assert.equal((html.match(/ta-spalte-kopf/g) || []).length, 1);
  assert.doesNotMatch(html, /ta-entscheid/);
});

test("Commit-Liste wird gerendert, leere Liste zeigt Hinweis", () => {
  var mitCommits = panelInhaltHtml(b1Fixture(), [{ hash: "a1b2c3d4", zeit: "t", betreff: "fix heredoc" }]);
  assert.match(mitCommits, /a1b2c3d/);
  assert.match(mitCommits, /fix heredoc/);
  var ohneCommits = panelInhaltHtml(b1Fixture(), []);
  assert.match(ohneCommits, /Keine Commits im Zeitfenster/);
});

test("Runde und Signatur stehen im Kopf", () => {
  var html = panelInhaltHtml(b1Fixture(), []);
  assert.match(html, /Runde 11/);
  assert.match(html, /rework:tool:Bash/);
});
