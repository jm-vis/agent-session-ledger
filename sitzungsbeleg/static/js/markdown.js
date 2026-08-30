// Kleiner Markdown-Renderer fuer Chat-Bubbles (Auftrag 2026-08-28): Modelle wie Nemotron
// liefern **fett**, Listen, Codebloecke roh -- chat.js zeigte das bisher als Stern-/Raute-Text
// an (escapeHtml auf den Rohtext). Sicherheitsprinzip: ERST escapeHtml auf den GESAMTEN Rohtext
// (markdownZuHtml() unten), danach werden NUR die hier aufgezaehlten Muster in Tags umgesetzt --
// kein rohes HTML aus einer Modellantwort erreicht je den DOM. Bewusst KEINE Links (`<a>`): eine
// URL im Modelltext bleibt Text, kein Klickziel aus ungeprueften Modellausgaben. Node-Tests:
// tests/test_markdown.mjs.
import { escapeHtml } from "./format.js";

var CODEBLOCK_MUSTER = /```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g;

// Steuerzeichen als Platzhalter-Klammer (KEIN Ziffern-Muster!) -- ein echter Chattext enthaelt
// sie nie, im Gegensatz zu Ziffern (Sitzungsnummern etc.), die beim Zuruecktauschen sonst
// faelschlich erneut getroffen wuerden. Zwei verschiedene Zeichen fuer Inline-Code vs.
// Codebloecke, damit sich beide Ebenen nicht gegenseitig verwechseln koennen.
var INLINE_KLAMMER = "";
var BLOCK_KLAMMER = "";
function platzhalter(klammer, index) {
  return klammer + index + klammer;
}

// `inhalt` ist bereits escaped (escapeHtml lief in markdownZuHtml() ueber den Gesamttext, bevor
// dieses Muster greift) -- hier bewusst KEIN inlineFormat(), Code bleibt woertlich.
function codeBlockHtml(_ganz, _sprache, inhalt) {
  return "<pre><code>" + inhalt.replace(/\n$/, "") + "</code></pre>";
}

// Inline-Code zuerst aus dem Text loesen (Platzhalter), damit **/*/_ INNERHALB von `code` nicht
// als Fett/Kursiv missverstanden werden -- danach Fett vor Kursiv (sonst friesse das Kursiv-
// Muster die Sterne eines **fett**-Paars an), zuletzt die Platzhalter zurueck in <code>.
function inlineFormat(text) {
  var codes = [];
  var ohneCode = text.replace(/`([^`\n]+)`/g, function (_, inhalt) {
    return platzhalter(INLINE_KLAMMER, codes.push(inhalt) - 1);
  });
  var formatiert = ohneCode
    .replace(/\*\*([^\n*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^\n*]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^\n_]+)_(?!_)/g, "$1<em>$2</em>");
  var muster = new RegExp(INLINE_KLAMMER + "(\\d+)" + INLINE_KLAMMER, "g");
  return formatiert.replace(muster, function (_, i) {
    return "<code>" + codes[Number(i)] + "</code>";
  });
}

function istListenZeile(zeile) {
  return /^(-|\*|\d+\.) /.test(zeile);
}

function listeHtml(zeilen) {
  var tag = /^\d+\. /.test(zeilen[0]) ? "ol" : "ul";
  var items = zeilen.map(function (z) {
    return "<li>" + inlineFormat(z.replace(/^(-|\*|\d+\.) /, "")) + "</li>";
  }).join("");
  return "<" + tag + ">" + items + "</" + tag + ">";
}

// Ein Absatz = durch Leerzeile getrennter Textblock. Eine einzelne "### "-Zeile wird zur
// <strong>-Zeile (keine echten <h1..6>, Vorgabe), eine Zeilengruppe aus reinen Listenzeilen
// zur <ul>/<ol>, alles andere zum <p> mit <br> zwischen einfachen Zeilenumbruechen.
function absatzHtml(absatz) {
  // Ein Absatz, der NUR aus einem Codeblock-Platzhalter besteht, bekommt kein umschliessendes
  // <p> -- ein <pre> gehoert nicht als Kind in einen Absatz (sonst schliesst der Browser das <p>
  // beim Einfuegen automatisch vorzeitig, unvorhersehbar fuer den Rest des Markups).
  var getrimmt = absatz.trim();
  if (new RegExp("^" + BLOCK_KLAMMER + "\\d+" + BLOCK_KLAMMER + "$").test(getrimmt)) return getrimmt;
  var zeilen = absatz.split("\n").filter(function (z) { return z.length > 0; });
  if (!zeilen.length) return "";
  if (zeilen.length === 1 && /^### /.test(zeilen[0])) {
    return "<p><strong>" + inlineFormat(zeilen[0].replace(/^### /, "")) + "</strong></p>";
  }
  if (zeilen.every(istListenZeile)) return listeHtml(zeilen);
  return "<p>" + zeilen.map(inlineFormat).join("<br>") + "</p>";
}

// Isoliert jede "### "-Zeile in ihren eigenen Absatz (doppelter Zeilenumbruch davor/danach),
// auch wenn das Modell keine Leerzeile drumherum geliefert hat -- sonst landet sie in
// absatzHtml() nur als normale Textzeile mitten im laufenden <p>.
function isolierteUeberschriften(text) {
  return text.split("\n").map(function (zeile) {
    return /^### /.test(zeile) ? "\n" + zeile + "\n" : zeile;
  }).join("\n");
}

export function markdownZuHtml(text) {
  var escaped = escapeHtml(text);
  var codeBloecke = [];
  var ohneCode = escaped.replace(CODEBLOCK_MUSTER, function (ganz, sprache, inhalt) {
    return platzhalter(BLOCK_KLAMMER, codeBloecke.push(codeBlockHtml(ganz, sprache, inhalt)) - 1);
  });
  var bloeckeAbsaetze = isolierteUeberschriften(ohneCode).split(/\n{2,}/).map(absatzHtml).join("");
  var muster = new RegExp(BLOCK_KLAMMER + "(\\d+)" + BLOCK_KLAMMER, "g");
  return bloeckeAbsaetze.replace(muster, function (_, i) { return codeBloecke[Number(i)]; });
}
