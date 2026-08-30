// Chat-Spalte "Besprechung" (Phase 1 D -- CONTRACTS.md C4/C5/C7): Modellwahl, Senden, SSE-Client.
// Bewusst ohne geteilten Zustand mit sitzung.js/router.js -- Kontext kommt direkt aus der Route
// (location.hash), die Zulaessigkeit wird bei Bedarf separat nachgeladen (GET /api/sitzung/<id>).
// Phase 2 F ersetzt die Stub-Antwort in chat.py (echtes Streaming, gleicher SSE-Vertrag -- diese
// Datei blieb dafuer unveraendert) und rendert die Anbieter-Knopfleiste jetzt aus ANBIETER
// (Feedback 2026-08-27: eigene volle Zeile, datengetrieben statt zwei fest verdrahteter Knoepfe).
import { holeJSON } from "./api.js";
import { escapeHtml, formatDauerKurz } from "./format.js";
import { markdownZuHtml } from "./markdown.js";

// Phase 2 F (Feedback 2026-08-27): die Anbieter-Knopfleiste wird aus DIESER Liste gerendert,
// nicht aus fest verdrahtetem Markup -- ein weiterer Anbieter braucht nur einen weiteren Eintrag
// hier. OpenRouter (Nachtrag Phase 2) und Requesty (Nachtrag 2026-08-28) sind weitere
// Cloud-Anbieter wie Claude (C6). Vier Eintraege -> #chat-anbieter rendert sie 2x2 (style.css),
// nicht 4 gleich breite Spalten -- bei 440px Chat-Breite waere "OpenRouter" sonst zu knapp.
var ANBIETER = [
  { id: "claude", label: "Claude" },
  { id: "ollama", label: "Ollama" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "requesty", label: "Requesty" },
];

// Cloud-Anbieter, die bei "geschuetzt" (C6) gesperrt sind -- nur Ollama laeuft lokal.
var CLOUD_ANBIETER = ["claude", "openrouter", "requesty"];

// Statischer Rest der OpenRouter-Praeferenzliste (Coordinator-Nachtrag, dritte Runde): das ERSTE
// Element kommt dynamisch vom Backend (`default_vico_openrouter`, s. ladeModelle()) -- diese
// zwei bleiben Literal-Fallbacks, falls der Backend-Wert (gerade) nicht im Katalog steht.
// Reihenfolge gegen die echte /models/user-Antwort unter aktivem ZDR-Filter verifiziert
// (Endentscheid 2026-08-27): NICHT alle ":free" -- die ":free"-Variante von nemotron-3-ultra
// liefert unter ZDR 404 ("No endpoints available matching your guardrail restrictions and data
// policy"), die Bezahlvariante laeuft ueber BaseTen (~0,000026 USD je Mini-Aufruf); z-ai/
// glm-5.2:free bleibt unter ZDR erreichbar.
export var OPENROUTER_STANDARD_STATISCH = ["z-ai/glm-5.2:free", "minimax/minimax-m3"];

// Bevorzugte Standardmodelle je Anbieter -- gilt fuer alle drei, nicht nur OpenRouter (EINE
// editierbare Konstante statt eines Sonderfalls). Erster Treffer aus der jeweiligen Liste
// gewinnt, sonst (nur relevant bei OpenRouter) das erste ":free"-Modell, sonst das erste Modell
// ueberhaupt (standardModell()). `ollama`/`openrouter` starten mit dem Backend-unabhaengigen
// Fallback -- NICHT den eigentlichen Standard hartcodieren: `ladeModelle()` setzt `ollama`
// komplett und `openrouter`s erstes Element aus `daten.ollama_standard`/`daten.openrouter_standard`
// (Backend liest `scripts/modelle.json` `default_vico_ollama`/`default_vico_openrouter`); fehlt
// ein Wert, bleibt der jeweilige Fallback bestehen.
export var STANDARD_BEVORZUGT = {
  claude: ["claude-fable-5"],
  ollama: [],
  openrouter: OPENROUTER_STANDARD_STATISCH.slice(),
  requesty: [],
};

var els = {};
var modelle = { claude: [], ollama: [], openrouter: [], requesty: [] };
var anbieter = "claude";
// Requesty-Filterschalter (Auftrag 2026-08-28): Default zeigt nur EU-Modelle ohne
// Trainingsnutzung (Server-Filter), "alle zeigen" laedt den vollen Katalog nach -- reiner
// In-Memory-Merker wie eigeneModellwahl, kein `?alle=`-Fragment in der URL.
var requestyAlle = false;
var gespraechId = null;
var kontext = { sitzung_logisch: null, signatur: null, runde: null, analyse_id: null };
var schutz = "cloud-ok";
var strom = null;
// Fund 2026-08-27: die Besprechung kannte nur die Sitzungs-ID, kein Modell konnte
// Kennzahlenfragen beantworten -- der Server haengt seither einen Kennzahlen-Block an den
// Chat-Kontext (`GET /api/sitzung/<id>.kennzahlen_block`, CONTRACTS.md C7). Reiner Anzeige-Merker
// fuer den Chip-Tooltip, geht NICHT ins gesendete `kontext`-Objekt (der Server baut den Block
// serverseitig selbst neu, s. `chat.gespraech_starten`).
var kennzahlenBlock = "";
// Anzahl Befunde der aktuell offenen Sitzung (Nachtrag Sichtkontext 2026-08-28) -- fuer den
// Chip-Text "Sitzung 137 · Kennzahlen + 5 Befunde", gefuellt aus derselben `/api/sitzung/<id>`-
// Antwort wie kennzahlenBlock, nicht neu berechnet.
var sichtBefundeAnzahl = 0;

// Eigene Modellwahl je Anbieter fuer DIESE Seiten-Sitzung (Coordinator-Nachtrag): sobald der
// Nutzer das <select> selbst aendert, merkt initWiring() sie hier -- ein spaeterer Wechsel
// zurueck zu demselben Anbieter (renderModellOptionen()) stellt sie wieder her, statt erneut den
// Standard zu setzen. Reine In-Memory-Merker, keine Persistenz ueber einen Seiten-Reload hinaus.
var eigeneModellwahl = {};

// ================= Sichtkontext (Nachtrag 2026-08-28, Auftrag) =================
// Befund: der Chat antwortete "die Dashboard-Ansicht selbst ist fuer mich nicht sichtbar" --
// dieser Block baut das Sichtpaket (CONTRACTS.md C7 `contracts.Sicht`), das mit jeder Nachricht
// mitgeschickt wird. Bewusst KEIN statischer Import von zustand.js/start.js hier (chat.js bleibt
// wie am Dateikopf beschrieben ohne geteilten Zustand -- ausserdem zieht zustand.js ueber
// router.js den kompletten Seiten-Graph mit, der ohne echtes DOM/`window` nicht importierbar ist,
// s. tests/test_chat_sicht.mjs): `setSichtQuelle()` bekommt die echten Werte von app.js injiziert,
// die eigentliche Sicht-Logik bleibt eine reine, fixture-testbare Funktion.
export var SICHT_MAX_SITZUNGEN = 30;
var sichtQuelleGetter = function () { return {}; };

// app.js ruft das EINMAL bei der Verkabelung auf (nach zustand.js UND chat.js importiert sind) --
// `fn()` liefert bei jedem Aufruf den aktuellen Frontend-Zustand als reines Objekt.
export function setSichtQuelle(fn) {
  sichtQuelleGetter = fn;
}

function _alsArray(mengeOderListe) {
  if (!mengeOderListe) return [];
  return Array.isArray(mengeOderListe) ? mengeOderListe.slice() : Array.from(mengeOderListe);
}

function _enthaelt(mengeOderListe, wert) {
  if (!mengeOderListe) return false;
  return typeof mengeOderListe.has === "function" ? mengeOderListe.has(wert) : mengeOderListe.indexOf(wert) !== -1;
}

// Reine Funktion (Fixture-testbar, tests/test_chat_sicht.mjs): welche Zeilen aus `quelle.sitzungenCache`
// nach den aktiven Filtern sichtbar sind -- gleiche Mitgliedschaftsregel wie
// `start.js:gefilterteSitzungen()` (Drilldown bewusst ausgenommen, das ist ein Zusatzfilter der
// Startseite, keine Kernbedingung fuer "was ist gerade sichtbar").
export function sitzungenSichtbar(quelle) {
  var q = quelle || {};
  return (q.sitzungenCache || []).filter(function (z) {
    return _enthaelt(q.aktiveProjekte, z.projekt) && _enthaelt(q.aktiveQuellen, z.quelle)
      && (z.kontext === "unzugeordnet" || _enthaelt(q.aktiveKontexte, z.kontext))
      && (!z.umgebung || _enthaelt(q.aktiveUmgebungen, z.umgebung))
      && (!z.persona || _enthaelt(q.aktivePersonas, z.persona));
  });
}

// Eine Sitzungszeile aus `zustand.sitzungenCache` (start.js-Form) -> `contracts.SichtSitzungZeile`.
export function sichtZeileAus(z) {
  var tags = [];
  if (z.anzahl_befunde) tags.push("befunde:" + z.anzahl_befunde);
  if (z.dissens) tags.push("dissens");
  if (z.fehler) tags.push("werkzeug-fehler:" + z.fehler);
  return {
    nr: z.id, zeit: String(z.start || z.zeitstempel || ""), quelle: z.quelle || "", projekt: z.projekt || "",
    dauer: formatDauerKurz(z.dauer_ms), runden: z.runden || 0, tools: z.tools || 0, fehler: z.fehler || 0,
    usd: z.kosten != null ? Number(z.kosten) : null,
    status: z.dissens ? "dissens" : (z.anzahl_befunde ? "auffaellig" : "ok"),
    auffaelligkeiten: tags,
  };
}

// Reine Funktion (Fixture-testbar): baut das komplette Sichtpaket. `ansicht` kommt vom Aufrufer
// (Route/DOM, s. `aktuelleAnsicht()`), `quelle` ist ein Objekt wie `zustand` (oder eine Fixture
// im Test), `sitzungKontext` ist das lokale `kontext`-Objekt dieser Datei.
export function baueSichtObjekt(ansicht, quelle, sitzungKontext) {
  if (ansicht === "sitzung") {
    return {
      ansicht: "sitzung", zeitraum: null, filter: null, sitzungen: [],
      sitzung: (sitzungKontext && sitzungKontext.sitzung_logisch) || null,
      befund: (sitzungKontext && sitzungKontext.signatur) || null,
    };
  }
  var q = quelle || {};
  var zeilen = sitzungenSichtbar(q).slice(0, SICHT_MAX_SITZUNGEN).map(sichtZeileAus);
  return {
    ansicht: ansicht,
    zeitraum: { von: q.von || null, bis: q.bis || null },
    filter: {
      projekte: _alsArray(q.aktiveProjekte), quellen: _alsArray(q.aktiveQuellen),
      kontexte: _alsArray(q.aktiveKontexte), umgebungen: _alsArray(q.aktiveUmgebungen),
      personas: _alsArray(q.aktivePersonas),
    },
    sitzungen: zeilen, sitzung: null, befund: null,
  };
}

var SICHT_ANSICHT_LABEL = { start: "Start", fehlerbilder: "Fehlerbilder", produkt: "Produkt" };

// Welche Ansicht gerade offen ist -- aus der Route (wie `ausRouteSitzungId()`) plus einem
// DOM-Blick auf das Fehlerbilder-Panel der Startseite (kein Import von start.js noetig, das
// Panel traegt seinen offen/zu-Zustand ohnehin im `hidden`-Attribut).
function aktuelleAnsicht() {
  var teile = (location.hash || "#start").replace("#", "").split("/");
  if (teile[0] === "sitzung" && /^\d+$/.test(teile[1] || "")) return "sitzung";
  if (teile[0] === "produkt") return "produkt";
  var panel = document.getElementById("fehler-panel-abschnitt");
  if (panel && !panel.hidden) return "fehlerbilder";
  return "start";
}

function baueSicht() {
  return baueSichtObjekt(aktuelleAnsicht(), sichtQuelleGetter(), kontext);
}

function sichtTooltipText(sicht) {
  var kopf = SICHT_ANSICHT_LABEL[sicht.ansicht] || sicht.ansicht;
  var zeilen = (sicht.sitzungen || []).map(function (z) {
    return z.nr + " · " + z.quelle + " · " + z.projekt + " · " + z.status;
  });
  return [kopf].concat(zeilen).join("\n");
}

function jetztUhrzeit() {
  return new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

// Absender-Zeile in Assistent-Bubbles (R4, Test 2026-08-27 18:15): Quelle ist das zum
// Sendezeitpunkt gewaehlte Anbieter/Modell-Paar, nicht ein Feld aus dem SSE-"ende"-Ereignis
// (das traegt nur token_in/token_out/dauer_ms, C5) -- gemerkt in sendeNachricht(), durchgereicht
// bis empfangeStromEreignis(), dort beim "ende" an die fertige Bubble gehaengt.
function senderLabel(anb, modell) {
  if (modell) return modell;
  var eintrag = ANBIETER.filter(function (a) { return a.id === anb; })[0];
  return eintrag ? eintrag.label : anb;
}

function fuegeSenderZeileEin(bubble, sender) {
  var zeile = document.createElement("span");
  zeile.className = "chat-sender";
  zeile.textContent = senderLabel(sender.anbieter, sender.modell);
  bubble.insertBefore(zeile, bubble.firstChild);
  // Dezente Anbieterfarbe je Bubble (Nachtrag Phase 2 OpenRouter/Requesty): style.css faerbt nur
  // anbieter-claude/anbieter-openrouter/anbieter-requesty ein, anbieter-ollama bleibt bewusst neutral.
  bubble.classList.add("anbieter-" + sender.anbieter);
}

// Autoscroll nur, wenn der Nutzer schon nah am Ende war (Layout-Nachlese 2026-08-28 Punkt 4,
// Auftrag): bei langen Antworten will der Maintainer nach oben scrollen koennen, ohne dass jedes
// SSE-Delta ihn wieder ans Ende reisst. "Nah" = Abstand zum Ende <= 40px -- IMMER VOR der DOM-
// Mutation gemessen (scrollHeight aendert sich sonst schon durch die neue Bubble/das neue Delta).
function istNaheEnde() {
  var el = els.verlauf;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
}
function scrolleAnsEndeWennNah(warNah) {
  if (warNah) els.verlauf.scrollTop = els.verlauf.scrollHeight;
}

function anfuegenBubble(klasse, text) {
  var div = document.createElement("div");
  div.className = "bubble " + klasse;
  div.innerHTML = escapeHtml(text) + '<span class="zeit">' + jetztUhrzeit() + "</span>";
  var warNah = istNaheEnde();
  els.verlauf.appendChild(div);
  scrolleAnsEndeWennNah(warNah);
  return div;
}

function renderAnbieterKnoepfe() {
  els.anbieter.innerHTML = ANBIETER.map(function (a) {
    return '<button type="button" data-anbieter="' + a.id + '" aria-pressed="' +
      (a.id === anbieter) + '">' + escapeHtml(a.label) + "</button>";
  }).join("");
}

// Kurzform der Kontextlaenge (Coordinator-Nachtrag 2026-08-27 Punkt 2): 164000 -> "164k",
// 1000000 -> "1M" -- glatte Tausender/Millionen ohne Nachkommastelle, sonst eine Nachkommastelle.
function kurzKontext(n) {
  if (!n) return "";
  if (n >= 1e6) return (n % 1e6 === 0 ? n / 1e6 : (n / 1e6).toFixed(1)) + "M";
  if (n >= 1e3) return (n % 1e3 === 0 ? n / 1e3 : (n / 1e3).toFixed(1)) + "k";
  return String(n);
}

function openrouterOptionen(gruppe) {
  return gruppe.map(function (m) {
    var kurz = kurzKontext(m.kontext);
    var label = m.id + (kurz ? " · " + kurz : "");
    return '<option value="' + escapeHtml(m.id) + '">' + escapeHtml(label) + "</option>";
  }).join("");
}

// Standardauswahl je Anbieter (Coordinator-Nachtrag, gilt fuer alle drei): erster Treffer aus
// STANDARD_BEVORZUGT[anbieterId], sonst das erste ":free"-Modell (bei Claude/Ollama kommt das nie
// vor, faellt also durch), sonst das erste Modell ueberhaupt -- `null` nur wenn `liste` leer ist.
// Reine Funktion (keine DOM-/Modul-Zustandsberuehrung) -- Fixture-testbar, s. tests/.
export function standardModell(anbieterId, liste) {
  var ids = liste.map(function (m) { return m.id; });
  var bevorzugt = STANDARD_BEVORZUGT[anbieterId] || [];
  for (var i = 0; i < bevorzugt.length; i++) {
    if (ids.indexOf(bevorzugt[i]) !== -1) return bevorzugt[i];
  }
  var frei = liste.filter(function (m) { return m.id.indexOf(":free") !== -1; });
  if (frei[0]) return frei[0].id;
  return liste[0] ? liste[0].id : null;
}

// Wendet die Modellwahl auf `els.modell` an: die eigene Wahl des Nutzers fuer DEN AKTUELLEN
// Anbieter in dieser Seiten-Sitzung hat Vorrang vor dem Standard (Coordinator-Nachtrag) -- nur
// wenn sie noch in `liste` vorkommt (der Katalog kann sich zwischen zwei Ladevorgaengen aendern).
function wendeModellwahlAn(liste) {
  var ids = liste.map(function (m) { return m.id; });
  var eigene = eigeneModellwahl[anbieter];
  var vorgabe = (eigene && ids.indexOf(eigene) !== -1) ? eigene : standardModell(anbieter, liste);
  if (vorgabe) els.modell.value = vorgabe;
}

// OpenRouter hat mehrere Hundert Modelle (Coordinator-Nachtrag Punkt 2) -- eigene Gruppierung
// statt der flachen Liste unten: zuerst die kostenlosen (":free"), dann alle (beide alphabetisch,
// das Backend liefert die Liste bereits sortiert).
function renderOpenrouterOptionen() {
  var liste = modelle.openrouter || [];
  var frei = liste.filter(function (m) { return m.id.indexOf(":free") !== -1; });
  var html = "";
  if (frei.length) html += '<optgroup label="kostenlos (:free)">' + openrouterOptionen(frei) + "</optgroup>";
  html += '<optgroup label="alle Modelle">' + openrouterOptionen(liste) + "</optgroup>";
  els.modell.innerHTML = html;
  wendeModellwahlAn(liste);
}

// Requesty-Optionen (Nachtrag 2026-08-28): Label traegt Kontext + Preis (USD/1M Token) + Region
// -- eine flache Liste reicht (anders als OpenRouter mit mehreren Hundert Eintraegen), der
// Server hat den Default-Filter (EU, kein Training) bereits angewandt.
function requestyOptionen(liste) {
  return liste.map(function (m) {
    var teile = [];
    if (m.kontext) teile.push(kurzKontext(m.kontext));
    if (m.preis_in != null) teile.push(m.preis_in + "/" + m.preis_out + " $/M");
    if (m.region) teile.push(m.region);
    var label = m.id + (teile.length ? " · " + teile.join(" · ") : "");
    return '<option value="' + escapeHtml(m.id) + '">' + escapeHtml(label) + "</option>";
  }).join("");
}

function renderRequestyOptionen() {
  var liste = modelle.requesty || [];
  els.modell.innerHTML = requestyOptionen(liste);
  wendeModellwahlAn(liste);
}

function renderModellOptionen() {
  if (anbieter === "openrouter") { renderOpenrouterOptionen(); return; }
  if (anbieter === "requesty") { renderRequestyOptionen(); return; }
  var liste = modelle[anbieter] || [];
  els.modell.innerHTML = liste.map(function (m) {
    var zusatz = m.zustand ? " — " + m.zustand : "";
    return '<option value="' + escapeHtml(m.id) + '">' + escapeHtml(m.name) + zusatz + "</option>";
  }).join("");
  wendeModellwahlAn(liste);
}

function aktualisiereOpenrouterHinweis() {
  els.openrouterHinweis.hidden = anbieter !== "openrouter";
}

function aktualisiereRequestyHinweis() {
  els.requestyHinweis.hidden = anbieter !== "requesty";
}

function setzeAnbieter(neu) {
  anbieter = neu;
  gespraechId = null; // Anbieterwechsel = neue Hintergrund-Sitzung (Plan Abschn. 4.5)
  document.querySelectorAll("#chat-anbieter button").forEach(function (b) {
    b.setAttribute("aria-pressed", String(b.getAttribute("data-anbieter") === neu));
  });
  renderModellOptionen();
  aktualisiereOpenrouterHinweis();
  aktualisiereRequestyHinweis();
}

// Ollama/OpenRouter/Requesty-Standard kommen vom Backend (Coordinator-Nachtrag), nicht
// hartcodiert -- fehlt ein Wert, bleibt der jeweilige Fallback aus STANDARD_BEVORZUGT bestehen
// (leer bei Ollama/Requesty, OPENROUTER_STANDARD_STATISCH bei OpenRouter).
export function setzeVicoStandards(daten) {
  if (daten.ollama_standard) STANDARD_BEVORZUGT.ollama = [daten.ollama_standard];
  if (daten.requesty_standard) STANDARD_BEVORZUGT.requesty = [daten.requesty_standard];
  STANDARD_BEVORZUGT.openrouter = daten.openrouter_standard
    ? [daten.openrouter_standard].concat(OPENROUTER_STANDARD_STATISCH)
    : OPENROUTER_STANDARD_STATISCH.slice();
}

function ladeModelle() {
  holeJSON("/api/chat/modelle", { alle: requestyAlle ? "true" : "" }).then(function (daten) {
    modelle = daten;
    setzeVicoStandards(daten);
    renderModellOptionen();
  }).catch(function () { /* Modellliste optional -- Chat bleibt bedienbar */ });
}

// "Sitzung 137 · Kennzahlen + 5 Befunde" -- Tooltip bleibt der volle Kennzahlen-Block.
function sitzungChipHtml() {
  var stuecke = [];
  if (kennzahlenBlock) stuecke.push("Kennzahlen");
  if (sichtBefundeAnzahl) stuecke.push(sichtBefundeAnzahl + " Befund" + (sichtBefundeAnzahl === 1 ? "" : "e"));
  var text = "Sitzung " + kontext.sitzung_logisch + (stuecke.length ? " · " + stuecke.join(" + ") : "");
  var titel = kennzahlenBlock ? ' title="' + escapeHtml(kennzahlenBlock) + '"' : "";
  return '<span class="chip"' + titel + ">" + escapeHtml(text) + "</span>";
}

// "Start · 12 Sitzungen im Kontext" (bzw. Fehlerbilder/Produkt) -- Tooltip traegt den
// zusammengebauten Sichttext (Naeherung des Blocks, den `chat_bruecke._sicht_block()` server-
// seitig baut).
function sichtChipHtml() {
  var sicht = baueSicht();
  var anzahl = (sicht.sitzungen || []).length;
  var label = (SICHT_ANSICHT_LABEL[sicht.ansicht] || sicht.ansicht) + " · " + anzahl
    + " Sitzung" + (anzahl === 1 ? "" : "en") + " im Kontext";
  return '<span class="chip" title="' + escapeHtml(sichtTooltipText(sicht)) + '">' + escapeHtml(label) + "</span>";
}

function aktualisiereKontextChip() {
  var teile = [kontext.sitzung_logisch ? sitzungChipHtml() : sichtChipHtml()];
  if (kontext.signatur) teile.push('<span class="chip mono">' + escapeHtml(kontext.signatur) + "</span>");
  els.kontext.innerHTML = teile.join("");
}

function aktualisiereDatenschutzChip() {
  var geschuetzt = schutz === "geschuetzt";
  els.datenschutz.className = "chat-datenschutz " + (geschuetzt ? "geschuetzt" : "ok");
  els.datenschutzText.textContent = geschuetzt ? "geschützt → nur Ollama lokal" : "cloud-ok → Claude/OpenRouter/Requesty zulässig";
  // OpenRouter/Requesty sind wie Claude Cloud-Anbieter (C6) -- bei geschuetzt erzwingt auf Ollama.
  if (geschuetzt && CLOUD_ANBIETER.indexOf(anbieter) !== -1) setzeAnbieter("ollama");
}

function ausRouteSitzungId() {
  var teile = (location.hash || "").replace("#", "").split("/");
  return teile[0] === "sitzung" && /^\d+$/.test(teile[1] || "") ? Number(teile[1]) : null;
}

// Aktualisiert das Kontextpaket, wenn die Route auf eine (andere) Sitzung wechselt --
// unabhaengig von sitzung.js: nur die Sitzungs-ID aus dem Hash, kein geteilter Zustand.
function aktualisiereKontextAusRoute() {
  var id = ausRouteSitzungId();
  if (id === kontext.sitzung_logisch) return;
  kontext = { sitzung_logisch: id, signatur: null, runde: null, analyse_id: null };
  kennzahlenBlock = "";
  sichtBefundeAnzahl = 0;
  gespraechId = null;
  aktualisiereKontextChip();
  schutz = "cloud-ok";
  aktualisiereDatenschutzChip();
  if (!id) return;
  holeJSON("/api/sitzung/" + id).then(function (daten) {
    if (kontext.sitzung_logisch !== id) return;
    schutz = daten.zulaessigkeit === "geschuetzt" ? "geschuetzt" : "cloud-ok";
    aktualisiereDatenschutzChip();
    kennzahlenBlock = daten.kennzahlen_block || "";
    sichtBefundeAnzahl = ((daten.dokument || {}).auffaelligkeiten || []).length;
    aktualisiereKontextChip();
  }).catch(function () { /* Zulaessigkeit/Kennzahlen unbekannt -- Chat bleibt bedienbar */ });
}

function schliesseStrom() {
  if (strom) { strom.close(); strom = null; }
  els.eingabe.disabled = false;
  els.senden.disabled = false;
}

// "Fix umsetzen": der Hintergrund-Chat darf nur lesen/erklaeren (--allowedTools, chat_bruecke.py)
// -- schlaegt er einen konkreten Fix vor, markiert er den Absatz mit einer Zeile
// "FIX-VORSCHLAG:" (System-Prompt-Vorgabe). Der Knopf startet den konfigurierten Fix-Launcher
// (POST .../fix), NICHT die Umsetzung selbst hier.
var FIX_MARKER = "FIX-VORSCHLAG:";

function enthaeltFixVorschlag(text) {
  return text.split("\n").some(function (zeile) { return zeile.trim().indexOf(FIX_MARKER) === 0; });
}

function starteFix(gid, zeile) {
  var knopf = zeile.querySelector(".chat-fix-btn");
  var statusEl = zeile.querySelector(".chat-fix-status");
  knopf.disabled = true;
  statusEl.hidden = false;
  statusEl.textContent = "Öffnet Fix-Fenster …";
  fetch("/api/chat/" + encodeURIComponent(gid) + "/fix", { method: "POST" }).then(function (antwort) {
    if (!antwort.ok) return antwort.json().then(function (d) { throw new Error(d.detail || ("HTTP " + antwort.status)); });
    statusEl.textContent = "Fix-Fenster geöffnet.";
  }).catch(function (e) { statusEl.textContent = "Fehler: " + e.message; knopf.disabled = false; });
}

function fuegeFixKnopfEin(bubble, gid, rohtext) {
  if (!enthaeltFixVorschlag(rohtext)) return;
  var zeile = document.createElement("div");
  zeile.className = "chat-fix-zeile";
  zeile.innerHTML = '<button type="button" class="outline-btn chat-fix-btn">Fix umsetzen</button>'
    + '<span class="chat-fix-status caption" hidden></span>';
  bubble.appendChild(zeile);
  zeile.querySelector(".chat-fix-btn").addEventListener("click", function () { starteFix(gid, zeile); });
}

// `zustand.text` ist der gesammelte ROHE Modelltext (nie aus dem DOM zurueckgelesen) -- jedes
// Delta rendert `markdownZuHtml(zustand.text)` komplett neu in den Text-Container (erstes Kind
// vor .zeit). Getestet per Playwright (headless, simulierte Deltas): kein sichtbares Flackern
// bei satzweisen Deltas, da der Browser identische Teilstrings im innerHTML-Diff wiederverwendet.
// `enthaeltFixVorschlag` prueft `zustand.text` direkt, NICHT `textContent` der Bubble -- <br>
// aus einem gerenderten Zeilenumbruch traegt keinen "\n" mehr, split("\n") auf textContent haette
// den FIX-VORSCHLAG-Zeilenanfang sonst verloren.
function empfangeStromEreignis(bubble, sender, zustand, ereignis) {
  var warNah = istNaheEnde();
  var daten = JSON.parse(ereignis.data);
  if (daten.typ === "delta") {
    zustand.text += daten.text;
    bubble.firstChild.innerHTML = markdownZuHtml(zustand.text);
  } else if (daten.typ === "fehler") {
    bubble.className = "bubble fehler"; bubble.firstChild.textContent = daten.text; schliesseStrom();
  } else if (daten.typ === "ende") {
    schliesseStrom();
    fuegeSenderZeileEin(bubble, sender);
    fuegeFixKnopfEin(bubble, gespraechId, zustand.text);
  }
  scrolleAnsEndeWennNah(warNah);
}

function starteStrom(id, sender) {
  if (strom) strom.close();
  var bubble = anfuegenBubble("assistent", "");
  bubble.innerHTML = '<span></span><span class="zeit">' + jetztUhrzeit() + "</span>";
  var zustand = { text: "" };
  strom = new EventSource("/api/chat/" + encodeURIComponent(id) + "/strom");
  strom.onmessage = function (e) { empfangeStromEreignis(bubble, sender, zustand, e); };
  strom.onerror = function () { schliesseStrom(); };
}

function sendeNachricht(text) {
  anfuegenBubble("nutzer", text);
  els.eingabe.disabled = true;
  els.senden.disabled = true;
  // Sender-Snapshot (R4): merkt Anbieter/Modell zum Sendezeitpunkt -- ein spaeterer Wechsel der
  // Auswahl (naechste Nachricht) darf die Absender-Zeile DIESER Antwort nicht mehr aendern.
  var sender = { anbieter: anbieter, modell: els.modell.value || "" };
  var body = {
    gespraech_id: gespraechId, anbieter: sender.anbieter, modell: sender.modell, text: text,
    kontext: kontext, schutz: schutz, sicht: baueSicht(),
  };
  holeJSON("/api/chat", {}, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(function (antwort) { gespraechId = antwort.gespraech_id; starteStrom(gespraechId, sender); })
    .catch(function (fehler) { anfuegenBubble("fehler", fehler.message); schliesseStrom(); });
}

// Merkt eine eigene Modellwahl je Anbieter (Coordinator-Nachtrag) -- ".value ="-Zuweisungen aus
// wendeModellwahlAn() loesen KEIN "change" aus, nur echte Nutzerinteraktion tut das.
function initModellWahlWiring() {
  els.modell.addEventListener("change", function () {
    eigeneModellwahl[anbieter] = els.modell.value;
  });
}

// Requesty-Filterschalter (ausgelagert, Code-Masse-Grenze): "alle zeigen" laedt die Liste neu
// vom Server -- gleicher gecachter Rohtext, s. chat._requesty_modelle.
function initRequestyAlleWiring() {
  els.requestyAlle.addEventListener("change", function () {
    requestyAlle = els.requestyAlle.checked;
    ladeModelle();
  });
}

function initWiring() {
  // Delegation statt je-Knopf-Listener: die Knoepfe werden aus ANBIETER neu gerendert
  // (renderAnbieterKnoepfe), ein direkter Listener je Knopf wuerde beim naechsten Rendern verloren gehen.
  els.anbieter.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-anbieter]");
    if (b) setzeAnbieter(b.getAttribute("data-anbieter"));
  });
  initModellWahlWiring();
  initRequestyAlleWiring();
  els.formular.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = els.eingabe.value.trim();
    if (!text) return;
    els.eingabe.value = "";
    sendeNachricht(text);
  });
  window.addEventListener("hashchange", aktualisiereKontextAusRoute);
}

// DOM-Verkabelung (gleiches Muster wie initRouter()/initZeitraum() in app.js).
// Layout-Nachlese 2026-08-28 Punkt 5 (verifizierter Fund): aktualisiereKontextAusRoute()
// ueberspringt ihren Koerper (samt aktualisiereDatenschutzChip()), wenn `id === kontext.
// sitzung_logisch` -- auf der Startseite sind BEIDE zu Beginn `null`, der Vergleich ist also
// wahr und die Chip-Funktion wird beim allerersten Laden NIE aufgerufen. Der statische Text in
// index.html (Vor-JS-Fallback) blieb dadurch dauerhaft stehen -- ohne Requesty, waehrend die
// Sitzungsseite (echte, von null verschiedene ID) den Vergleich verfehlt und die Funktion
// regulaer aufruft. Der direkte Aufruf unten faengt genau den Startseiten-Fall ab, unabhaengig
// vom Routen-Vergleich.
export function initChat() {
  els = {
    formular: document.getElementById("chat-formular"), eingabe: document.getElementById("chat-eingabe-feld"),
    senden: document.getElementById("chat-senden-btn"), verlauf: document.getElementById("chat-verlauf"),
    modell: document.getElementById("chat-modell"), kontext: document.getElementById("chat-kontext"),
    datenschutz: document.getElementById("chat-datenschutz"), datenschutzText: document.getElementById("chat-datenschutz-text"),
    anbieter: document.getElementById("chat-anbieter"), openrouterHinweis: document.getElementById("chat-hinweis-openrouter"),
    requestyHinweis: document.getElementById("chat-hinweis-requesty"), requestyAlle: document.getElementById("chat-requesty-alle"),
  };
  renderAnbieterKnoepfe();
  initWiring();
  ladeModelle();
  aktualisiereDatenschutzChip();
  aktualisiereKontextAusRoute();
}
