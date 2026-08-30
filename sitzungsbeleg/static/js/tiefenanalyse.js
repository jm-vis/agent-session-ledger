// Tiefenanalyse-Panel (Phase 3 I, C10 GET/POST /api/sitzung/{id}/tiefenanalyse): oeffnet direkt
// unter der Befund-Karte wie rohdatei.js (gleiches Andock-Muster). Beim Oeffnen wird zuerst nach
// einer VORHANDENEN Analyse gefragt (Status-Endpunkt); ohne Treffer startet ein neuer Lauf.
import { escapeHtml } from "./format.js";
import { verankerungAusFormular, verankerungFormularHtml, verankerungSichtbarSchalten } from "./verankerung.js";

var AKTUELLES_PANEL = null; // { sitzungId, karte, signatur, position, element, aufEntschieden }
var PILLE_TEXT = { uebereinstimmend: "übereinstimmend", dissens: "Dissens", ohne_zweitmeinung: "ohne Zweitmeinung" };
var KLARTEXT_STATUS = {
  uebereinstimmend: "Bestätigt (Claude + Codex einig)", dissens: "Entscheidung offen",
  ohne_zweitmeinung: "Nur Claude (ohne Zweitmeinung)",
};

function seiteHtml(quelle, label, seite) {
  if (!seite) return "";
  return '<div class="ta-spalte"><div class="ta-spalte-kopf"><span class="quelle-chip quelle-' + quelle + '">'
    + label + "</span></div>"
    + '<div class="ta-block"><span class="ta-label">Ursache-Kategorie</span><span class="ta-wert mono">'
    + escapeHtml(seite.ursache_kategorie) + "</span></div>"
    + '<div class="ta-block"><span class="ta-label">Befund</span><span class="ta-wert">'
    + escapeHtml(seite.befund) + "</span></div>"
    + '<div class="ta-block"><span class="ta-label">Empfehlung</span><span class="ta-wert">'
    + escapeHtml(seite.empfehlung) + "</span></div></div>";
}

function klartextZeileHtml(label, wert) {
  return '<div class="ta-block"><span class="ta-label">' + escapeHtml(label) + '</span><span class="ta-wert">'
    + escapeHtml(wert) + "</span></div>";
}

// Top-Level-Felder sind immer Claudes Stufe-1-Sicht (C10) -- bei Dissens zeigt "Status" das
// Signal "Entscheidung offen", die beiden Modell-Spalten darunter tragen die Details.
function klartextHtml(d) {
  return '<div class="ta-klartext">'
    + klartextZeileHtml("Was ist passiert", d.befund)
    + klartextZeileHtml("Ursache", d.ursache_kategorie)
    + klartextZeileHtml("Empfehlung", d.empfehlung)
    + klartextZeileHtml("Status", KLARTEXT_STATUS[d.urteil] || d.urteil) + "</div>";
}

// C11: dieser Entscheid ist IMMER `status=erledigt` (eine Tiefenanalyse-Entscheidung behebt den
// Befund), die Verankerungsfelder stehen darum immer sichtbar da -- keine Status-Auswahl noetig.
function entscheidHtml() {
  return '<div class="ta-entscheid"><div class="entscheid-radios">'
    + '<label><input type="radio" name="ta-entscheid" value="Claude folgen" checked>Claude folgen</label>'
    + '<label><input type="radio" name="ta-entscheid" value="Codex folgen">Codex folgen</label>'
    + '<label><input type="radio" name="ta-entscheid" value="eigene Einschätzung">eigene Einschätzung</label></div>'
    + '<input type="text" class="entscheid-vermerk" placeholder="Vermerk (optional)…">'
    + verankerungFormularHtml()
    + '<button type="button" class="primaer-btn ta-entscheiden-btn" data-verankerung-knopf>Entscheiden</button>'
    + '<p class="ta-entscheid-fehler fehlerhinweis" hidden></p></div>';
}

function commitZeileHtml(c) {
  return '<li><button type="button" class="link-btn ta-commit-btn" data-hash="' + escapeHtml(c.hash) + '">'
    + '<span class="mono">' + escapeHtml(c.hash.slice(0, 8)) + "</span> " + escapeHtml(c.betreff) + "</button></li>";
}

function commitsHtml(liste) {
  var inhalt = liste.length
    ? '<ul class="ta-commits-liste">' + liste.map(commitZeileHtml).join("") + "</ul>"
    : '<p class="caption">Keine Commits im Zeitfenster.</p>';
  return '<div class="ta-commits"><h4>Commits im Zeitfenster</h4>' + inhalt + '<div class="ta-commit-diff" hidden></div></div>';
}

// Exportiert fuer den reinen Rendering-Test (test_tiefenanalyse_panel.mjs, B1/B2-Fixtures) --
// kein DOM/Browser noetig, wie chat.js' baueSichtObjekt/sichtZeileAus.
export function panelInhaltHtml(d, commitListe) {
  var pille = '<span class="pille" data-status="' + escapeHtml(d.urteil) + '">'
    + escapeHtml(PILLE_TEXT[d.urteil] || d.urteil) + "</span>";
  var kopf = '<div class="ta-kopf"><h3>Tiefenanalyse · Runde ' + (d.runde || "–") + " · "
    + '<span class="mono">' + escapeHtml(d.signatur) + "</span></h3>" + pille + "</div>";
  var grid = '<div class="ta-grid">' + seiteHtml("claude", "Claude", d.positionen.claude)
    + seiteHtml("codex", "Codex", d.positionen.codex) + "</div>";
  var entscheid = d.urteil === "dissens" ? entscheidHtml() : "";
  return kopf + klartextHtml(d) + grid + entscheid + commitsHtml(commitListe || [])
    + '<div class="rohdatei-aktionen"><button type="button" class="ghost-btn ta-neu-btn">Neu laufen lassen</button>'
    + '<button type="button" class="ghost-btn ta-schliessen-btn">Schließen</button></div>';
}

function laeuftHtml() {
  return '<p class="caption">Tiefenanalyse läuft …</p>';
}

function fehlerHtml(meldung) {
  return '<p class="fehlerhinweis">Tiefenanalyse nicht geladen: ' + escapeHtml(meldung || "unbekannter Fehler") + "</p>";
}

function diffZeileHtml(zeile) {
  var minus = zeile.charAt(0) === "-" && zeile.slice(0, 3) !== "---";
  var plus = zeile.charAt(0) === "+" && zeile.slice(0, 3) !== "+++";
  var klasse = minus ? " diff-minus" : plus ? " diff-plus" : "";
  return '<div class="diff-zeile' + klasse + '">' + escapeHtml(zeile) + "</div>";
}

function ladeDiff(panel, hash, container) {
  container.hidden = false;
  container.innerHTML = '<p class="caption">Lade Diff …</p>';
  var url = "/api/sitzung/" + encodeURIComponent(panel.sitzungId) + "/commits/" + encodeURIComponent(hash);
  fetch(url).then(function (a) { return a.json().then(function (d) { return { status: a.status, d: d }; }); })
    .then(function (r) {
      if (!container.isConnected) return;
      container.innerHTML = r.status === 200
        ? r.d.diff.split("\n").map(diffZeileHtml).join("")
        : '<p class="fehlerhinweis">' + escapeHtml(r.d.detail || "Diff nicht geladen") + "</p>";
    }).catch(function (e) { if (container.isConnected) container.innerHTML = fehlerHtml(e.message); });
}

function entscheidVermerk(el) {
  var gewaehlt = el.querySelector('input[name="ta-entscheid"]:checked');
  var vermerkFeld = el.querySelector(".entscheid-vermerk");
  return [(gewaehlt && gewaehlt.value) || "eigene Einschätzung", vermerkFeld.value].filter(Boolean).join(" — ");
}

function sendeEntscheid(panel) {
  var el = panel.element;
  var fehlerEl = el.querySelector(".ta-entscheid-fehler");
  var knopf = el.querySelector(".ta-entscheiden-btn");
  fehlerEl.hidden = true; knopf.disabled = true;
  fetch("/api/befund/entscheid", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      signatur: panel.signatur, status: "erledigt", vermerk: entscheidVermerk(el),
      begruendung: "Tiefenanalyse", sitzung_ref: Number(panel.sitzungId),
      verankerung: verankerungAusFormular(el),
    }),
  }).then(function (a) {
    if (!a.ok) return a.json().then(function (d) { throw new Error(d.detail || ("HTTP " + a.status)); });
    return a.json();
  }).then(function (detail) {
    if (panel.aufEntschieden) panel.aufEntschieden(detail);
    schliessePanel();
  }).catch(function (e) { fehlerEl.textContent = e.message; fehlerEl.hidden = false; knopf.disabled = false; });
}

function verkabelePanel(panel) {
  var el = panel.element;
  var neu = el.querySelector(".ta-neu-btn");
  if (neu) neu.addEventListener("click", function () { starteLauf(panel); });
  var schliessen = el.querySelector(".ta-schliessen-btn");
  if (schliessen) schliessen.addEventListener("click", schliessePanel);
  var entscheiden = el.querySelector(".ta-entscheiden-btn");
  if (entscheiden) {
    verankerungSichtbarSchalten(el, "erledigt"); // C11: hier immer sichtbar, Knopf initial gate
    el.querySelector(".v-pfad").addEventListener("input", function () { verankerungSichtbarSchalten(el, "erledigt"); });
    entscheiden.addEventListener("click", function () { sendeEntscheid(panel); });
  }
  Array.prototype.forEach.call(el.querySelectorAll(".ta-commit-btn"), function (btn) {
    btn.addEventListener("click", function () {
      ladeDiff(panel, btn.getAttribute("data-hash"), el.querySelector(".ta-commit-diff"));
    });
  });
}

function ladeCommitsUndZeige(panel, ergebnis) {
  var url = "/api/sitzung/" + encodeURIComponent(panel.sitzungId) + "/commits";
  fetch(url).then(function (a) { return a.ok ? a.json() : { commits: [] }; }).then(function (r) {
    if (!panel.element.isConnected) return;
    panel.element.innerHTML = panelInhaltHtml(ergebnis, r.commits);
    verkabelePanel(panel);
  }).catch(function () {
    if (panel.element.isConnected) { panel.element.innerHTML = panelInhaltHtml(ergebnis, []); verkabelePanel(panel); }
  });
}

function holeStatus(panel) {
  var url = "/api/sitzung/" + encodeURIComponent(panel.sitzungId) + "/tiefenanalyse?signatur="
    + encodeURIComponent(panel.signatur);
  return fetch(url).then(function (a) { return a.json(); });
}

function pollStatus(panel, versuch) {
  if (!panel.element.isConnected || versuch > 100) return;
  setTimeout(function () {
    if (!panel.element.isConnected) return;
    holeStatus(panel).then(function (status) {
      if (!panel.element.isConnected) return;
      if (status.laeuft) { pollStatus(panel, versuch + 1); return; }
      if (!status.ergebnis) { panel.element.innerHTML = fehlerHtml("keine Analyse erhalten"); return; }
      ladeCommitsUndZeige(panel, status.ergebnis);
    }).catch(function (e) { if (panel.element.isConnected) panel.element.innerHTML = fehlerHtml(e.message); });
  }, 3000);
}

function starteLauf(panel) {
  panel.element.innerHTML = laeuftHtml();
  var url = "/api/sitzung/" + encodeURIComponent(panel.sitzungId) + "/tiefenanalyse";
  fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signatur: panel.signatur, position: panel.position }),
  }).then(function (a) { return a.json().then(function (d) { return { status: a.status, d: d }; }); })
    .then(function (r) {
      if (r.status !== 202 && r.status !== 409) throw new Error(r.d.detail || ("HTTP " + r.status));
      pollStatus(panel, 0);
    }).catch(function (e) { if (panel.element.isConnected) panel.element.innerHTML = fehlerHtml(e.message); });
}

function schliessePanel() {
  if (AKTUELLES_PANEL) AKTUELLES_PANEL.element.remove();
  AKTUELLES_PANEL = null;
}

// Oeffnet/schliesst das Panel direkt unter der Befund-Karte `karte` -- ein zweiter Klick auf
// dieselbe Signatur schliesst es wieder (Toggle wie rohdatei.js). `aufEntschieden(detail)`
// bekommt den geschriebenen Befund-Entscheid, damit sitzung.js die Karten neu rendert.
export function oeffneTiefenanalysePanel(sitzungId, karte, signatur, position, aufEntschieden) {
  var warKarte = AKTUELLES_PANEL && AKTUELLES_PANEL.karte === karte && AKTUELLES_PANEL.signatur === signatur;
  schliessePanel();
  if (warKarte || !karte) return;
  var li = document.createElement("li");
  li.className = "ta-panel-item";
  li.innerHTML = '<p class="caption">Lade Tiefenanalyse …</p>';
  karte.insertAdjacentElement("afterend", li);
  var panel = {
    sitzungId: sitzungId, karte: karte, signatur: signatur, position: position, element: li,
    aufEntschieden: aufEntschieden,
  };
  AKTUELLES_PANEL = panel;
  holeStatus(panel).then(function (status) {
    if (!panel.element.isConnected) return;
    if (status.ergebnis && !status.laeuft) { ladeCommitsUndZeige(panel, status.ergebnis); return; }
    starteLauf(panel);
  }).catch(function () { if (panel.element.isConnected) starteLauf(panel); });
}
