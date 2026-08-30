// Reine-Funktions-Test fuer markdown.js `markdownZuHtml()` (Auftrag 2026-08-28: Chat-Bubbles
// rendern **fett**/Listen/Code statt Sternchen-Rohtext). Kein DOM noetig -- reiner String-Test,
// Muster wie tests/test_chat_standardmodell.mjs. Ausfuehren:
// `node scripts/sitzungsbeleg/tests/test_markdown.mjs`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { markdownZuHtml } from "../static/js/markdown.js";

test("einfacher Text ohne Markdown -> ein <p>", () => {
  assert.equal(markdownZuHtml("Hallo Welt"), "<p>Hallo Welt</p>");
});

test("**fett** -> <strong>", () => {
  assert.equal(markdownZuHtml("Das ist **wichtig**."), "<p>Das ist <strong>wichtig</strong>.</p>");
});

test("*kursiv* -> <em>", () => {
  assert.equal(markdownZuHtml("Das ist *kursiv*."), "<p>Das ist <em>kursiv</em>.</p>");
});

test("_kursiv_ -> <em>", () => {
  assert.equal(markdownZuHtml("Das ist _kursiv_."), "<p>Das ist <em>kursiv</em>.</p>");
});

test("snake_case_wort wird NICHT kursiv (Unterstrich mitten im Wort)", () => {
  var html = markdownZuHtml("Nutze snake_case_variable im Code.");
  assert.ok(!html.includes("<em>"), html);
  assert.ok(html.includes("snake_case_variable"));
});

test("Inline-`code` -> <code>", () => {
  assert.equal(markdownZuHtml("Ruf `foo()` auf."), "<p>Ruf <code>foo()</code> auf.</p>");
});

test("Fett und Inline-Code im selben Satz stoeren sich nicht", () => {
  assert.equal(
    markdownZuHtml("**fett** und `code`"),
    "<p><strong>fett</strong> und <code>code</code></p>",
  );
});

test("Codeblock ``` -> <pre><code>, kein <p> drumherum", () => {
  var html = markdownZuHtml("Vorher\n\n```js\nconst a = 1;\n```\n\nNachher");
  assert.equal(html, "<p>Vorher</p><pre><code>const a = 1;</code></pre><p>Nachher</p>");
});

test("Codeblock-Inhalt bleibt woertlich (kein Markdown/HTML darin ausgewertet)", () => {
  var html = markdownZuHtml("```\n**kein fett** <b>kein tag</b>\n```");
  assert.equal(html, "<pre><code>**kein fett** &lt;b&gt;kein tag&lt;/b&gt;</code></pre>");
});

test("- Liste -> <ul><li>", () => {
  assert.equal(
    markdownZuHtml("- eins\n- zwei\n- drei"),
    "<ul><li>eins</li><li>zwei</li><li>drei</li></ul>",
  );
});

test("* Liste (Stern statt Bindestrich) -> ebenfalls <ul><li>", () => {
  assert.equal(markdownZuHtml("* eins\n* zwei"), "<ul><li>eins</li><li>zwei</li></ul>");
});

test("1. Liste -> <ol><li>", () => {
  assert.equal(markdownZuHtml("1. eins\n2. zwei"), "<ol><li>eins</li><li>zwei</li></ol>");
});

test("### Ueberschrift -> <strong>-Zeile, kein echtes <h3>", () => {
  assert.equal(markdownZuHtml("### Titel"), "<p><strong>Titel</strong></p>");
});

test("### Ueberschrift mitten im Text wird isoliert (eigener Absatz)", () => {
  assert.equal(
    markdownZuHtml("Vorher\n### Titel\nNachher"),
    "<p>Vorher</p><p><strong>Titel</strong></p><p>Nachher</p>",
  );
});

test("Leerzeile trennt zwei Absaetze in zwei <p>", () => {
  assert.equal(
    markdownZuHtml("Erster Absatz.\n\nZweiter Absatz."),
    "<p>Erster Absatz.</p><p>Zweiter Absatz.</p>",
  );
});

test("einfacher Zeilenumbruch innerhalb eines Absatzes -> <br>", () => {
  assert.equal(markdownZuHtml("Zeile eins\nZeile zwei"), "<p>Zeile eins<br>Zeile zwei</p>");
});

test("XSS: <script> im Rohtext bleibt Text, wird nie zu einem echten Tag", () => {
  var html = markdownZuHtml("<script>alert(1)</script>");
  assert.equal(html, "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>");
  assert.ok(!html.includes("<script>"));
});

test("XSS: Event-Handler-Attribut im Rohtext bleibt Text", () => {
  var html = markdownZuHtml('<img src=x onerror="alert(1)">');
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});

test("keine Links: eine URL im Text bleibt reiner Text, kein <a>", () => {
  var html = markdownZuHtml("Siehe http://example.com/x fuer mehr.");
  assert.ok(!html.includes("<a"));
  assert.ok(html.includes("http://example.com/x"));
});

test("leerer Text -> leerer String", () => {
  assert.equal(markdownZuHtml(""), "");
});
