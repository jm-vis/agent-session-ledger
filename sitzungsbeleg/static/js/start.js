// Seite: Start -- Filter-Seitenleiste (Projekte/Quellen/Personas/Kontexte), Sitzungen-Tabelle
// (inkl. Sortierung), Querschnitt-Kacheln (renderQuerschnitt wird von querschnitt.js
// wiederverwendet), Drilldown-Banner und der zweistufige Fehler-Drilldown (Kachel -> Panel ->
// Sitzungsliste).
import { zustand, zeigeAusgeblendeteProjekte, periodenSuffix } from "./zustand.js";
import {
  escapeHtml, quelleChipHtml, umgebungChipHtml, umgebungBlockSichtbar, personaZelleHtml,
  formatDauerKurz, formatKosten, fehlerbildLabel, statusBadgeHtml, formatZeitSpalte, iso,
} from "./format.js";
import { holeJSON, zeigeFehler } from "./api.js";
import { setzeTabelleScrollt, parseDauerText, parseZahlText, holeSortWert, passeTabelleHoeheAn } from "./tabellen.js";
import { verankerungAusFormular, verankerungFormularHtml, verankerungSichtbarSchalten } from "./verankerung.js";

// ================= Filter-Panel (Projekte/Quellen) =================
export var letzteProjekte = [];
export var letzteProjekteRoh = [];
var tabelleSitzungen, tbodySitzungen;

// setzeProjektAktiv() baute bis C14 zusaetzlich die AKTIV-Chip-Zeile neu (baueChips()) -- die
// Chips entfielen ersatzlos (Entscheid 2026-08-28: sie doppelten die Haekchenliste), die
// Funktion setzt seither nur noch die Checkbox und rendert die Tabelle neu.
function setzeProjektAktiv(name, aktiv) {
  if (aktiv) zustand.aktiveProjekte.add(name); else zustand.aktiveProjekte.delete(name);
  var cb = document.querySelector('input[data-projekt="' + CSS.escape(name) + '"]');
  if (cb) cb.checked = aktiv;
  renderSitzungenTabelle();
}
function setzeQuelleAktiv(name, aktiv) {
  if (aktiv) zustand.aktiveQuellen.add(name); else zustand.aktiveQuellen.delete(name);
  renderSitzungenTabelle();
}
function setzeKontextAktiv(name, aktiv) {
  if (aktiv) zustand.aktiveKontexte.add(name); else zustand.aktiveKontexte.delete(name);
  renderSitzungenTabelle();
}
function setzeUmgebungAktiv(name, aktiv) {
  if (aktiv) zustand.aktiveUmgebungen.add(name); else zustand.aktiveUmgebungen.delete(name);
  renderSitzungenTabelle();
}
// Achse Persona (C14, Entscheid 2026-08-28): gleiches Muster wie setzeUmgebungAktiv.
function setzePersonaAktiv(name, aktiv) {
  if (aktiv) zustand.aktivePersonas.add(name); else zustand.aktivePersonas.delete(name);
  renderSitzungenTabelle();
}

function projektZeileHtml(p) {
  var checked = zustand.aktiveProjekte.has(p.name) ? "checked" : "";
  var id = "pj-" + p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return '<li class="filter-zeile" data-projekt-name="' + escapeHtml(p.name.toLowerCase()) + '">'
    + '<input type="checkbox" id="' + id + '" data-projekt="' + escapeHtml(p.name) + '" ' + checked + '>'
    + '<label for="' + id + '">' + escapeHtml(p.name) + '</label><span class="count">' + p.anzahl + '</span></li>';
}

export function renderFilterPanel(daten) {
  letzteProjekteRoh = daten.projekte;
  letzteProjekte = zeigeAusgeblendeteProjekte()
    ? letzteProjekteRoh
    : letzteProjekteRoh.filter(function (p) { return !p.ausgeblendet; });
  var namen = letzteProjekte.map(function (p) { return p.name; });
  if (!zustand.projektInitialisiert) {
    zustand.aktiveProjekte = new Set(namen);
    zustand.projektInitialisiert = true;
  } else {
    namen.forEach(function (n) { if (!zustand.projektBekannt.has(n)) zustand.aktiveProjekte.add(n); });
  }
  zustand.projektBekannt = new Set(namen);

  // Alle 6 Quellen (inkl. "Unbekannt") stehen IMMER in der Leiste -- auch wenn eine Quelle im
  // gewaehlten Zeitraum nicht vorkommt (Entscheid 2026-08-28, ersetzt Auftrag 2 vom
  // 2026-08-26, der "Unbekannt" bei 0 Treffern versteckte). Kein Ein-/Ausblenden mehr noetig:
  // die Zeile steht fest in index.html, "Unbekannt" ist Teil des Start-Zustands (zustand.js).

  if (daten.umgebungen) aktualisiereUmgebungBlock(daten.umgebungen);

  var top = letzteProjekte.slice(0, 5);
  var rest = letzteProjekte.slice(5).slice().sort(function (a, b) { return a.name.localeCompare(b.name, "de"); });
  document.getElementById("projekt-liste-aktiv").innerHTML = top.map(projektZeileHtml).join("") || '<li class="caption">Keine Projekte im Zeitraum.</li>';
  document.getElementById("projekt-liste-weitere").innerHTML = rest.map(projektZeileHtml).join("");
  document.getElementById("weitere-anzahl").textContent = String(rest.length);
  passeSeitenleisteHoeheAn();
}

// Block "Umgebung" (C12, Maintainer 2026-08-28 12:45): ganze Gruppe bleibt versteckt, solange im
// Zeitraum weniger als zwei Werte vorkommen (format.js:umgebungBlockSichtbar, reine Funktion,
// Node-testbar) -- innerhalb der Gruppe bleiben ausserdem einzelne Zeilen mit anzahl=0
// versteckt. (Anders als die KI-Quellen-Leiste, die seit Entscheid 2026-08-28 fest steht.)
function aktualisiereUmgebungBlock(umgebungen) {
  var gruppe = document.getElementById("filter-gruppe-umgebung");
  if (!gruppe) return;
  gruppe.hidden = !umgebungBlockSichtbar(umgebungen);
  var vorkommend = {};
  umgebungen.forEach(function (u) { vorkommend[u.name] = u.anzahl > 0; });
  ["entwicklung", "abnahme", "betrieb"].forEach(function (name) {
    var zeile = document.getElementById("u-" + name + "-zeile");
    if (zeile) zeile.hidden = !vorkommend[name];
  });
}

// ================= Sidebar-Sektionen: eigener Innenscroll statt einem Aussenscroll =================
// Auftrag 2026-08-27 (Nachtrag C): #filter-panel bekommt KEINEN eigenen Scrollbalken mehr
// (style.css: overflow:hidden) -- ZULETZT-AKTIV/KONTEXT scrollen stattdessen einzeln.
// Reines CSS-Flex scheiterte (Chromiums automatische Mindesthoehe eines verschachtelten
// Flex-Containers rechnet das min-height eines Enkelkinds nicht ein, Messlauf 2026-08-27) --
// gleiches Muster wie tabellen.js:passeTabelleHoeheAn(): live messen, Restflaeche berechnen,
// per style.height zuweisen. clientHeight/offsetHeight sind IMMER logische (Vor-Zoom-)Pixel
// (anders als getBoundingClientRect) -- hier reicht das direkt, keine Zoom-Ruecktransformation.
// Zielwert 4 Zeilen (21px Zeile + 8px Abstand, .projekt-liste/.filter-gruppe ul) = 108px --
// gilt, WENN genug Platz da ist. Reicht er nicht (z. B. 1366x768 mit vielen aktiven Projekten in
// ZULETZT AKTIV), weicht die Formel bewusst NACH UNTEN ab, statt die feste Aussenhoehe zu sprengen --
// eine kleinere, weiterhin per Innenscroll erreichbare Liste ist besser als ein abgeschnittener
// Rahmen oder ein verbotener Aussen-Scrollbalken (siehe Bericht fuer die gemessenen Werte je Breite).
function randOben(el) { return parseFloat(getComputedStyle(el).marginTop) || 0; }
// Fixhoehe = alles ausser den zwei wachsenden Listen: Rest der Projekte-/Kontext-Gruppe (deren
// eigene offsetHeight minus der aktuellen Listenhoehe -- funktioniert unabhaengig davon, welche
// Hoehe die Liste gerade hat) PLUS die komplett fixen Quellen-Bloecke PLUS deren margin-top-
// Trenner (.filter-gruppe + .filter-gruppe, siehe style.css) -- ohne die Trenner passte alles
// zusammen 168px zu hoch in den Rahmen (Messlauf 2026-08-27).
// Layout-Nachlese 2026-08-28 Punkt 3 (Auftrag): QUELLEN ist jetzt ZWEI Bloecke ("KI-
// Plattformen" + "Produkt" als eigener .filter-gruppe, siehe index.html) statt einem --
// `quellenGruppen` ist deshalb ein Array, dessen offsetHoehen aufsummiert werden; nur der ERSTE
// Block traegt den margin-top-Trenner zur Projekte-Gruppe (der zweite Block traegt seinen
// eigenen, ueber dessen eigene offsetHeight bereits erfasst).
function fixHoeheAusserListen(projGruppe, kontGruppe, quellenGruppen, projListe, kontextListe) {
  // offsetHeight traegt NIE die eigene margin-top (Box-Modell) -- jeder Quellen-Block braucht
  // seinen randOben() einzeln, auch der zweite ("Produkt"), nicht nur der erste (Bugfix
  // Layout-Nachlese 2026-08-28: der urspruengliche Kommentar nahm faelschlich an, offsetHeight
  // des zweiten Blocks schluesse dessen eigenen Trenner zur "KI-Plattformen"-Gruppe ein).
  // Versteckte Gruppen (Umgebung unter 2 Werten, hidden -> display:none) nehmen keinen Platz,
  // getComputedStyle liefert ihr margin-top aber trotzdem -- ohne den Guard zaehlte die Formel
  // 20px Phantom-Trenner und quetschte ZULETZT AKTIV zu frueh (Live-Messung 2026-08-28, C14).
  var quellenHoehe = quellenGruppen.reduce(function (summe, g) { return summe + g.offsetHeight + (g.offsetHeight ? randOben(g) : 0); }, 0);
  return (projGruppe.offsetHeight - projListe.offsetHeight)
    + (kontGruppe.offsetHeight - kontextListe.offsetHeight)
    + quellenHoehe + randOben(kontGruppe);
}
// Korrektur 2026-08-27: KONTEXT bleibt IMMER auf natuerlicher Hoehe (alle Eintraege voll
// sichtbar, kein Scroll) -- NUR Zuletzt-aktiv nimmt/gibt die Restflaeche. Kontext scrollt nur
// als Notbremse, falls seine natuerliche Groesse (kuenftig mehr Kontexte) den Rahmen sprengen
// wuerde -- Zuletzt-aktiv geht dafuer zuerst auf 0, nicht Kontext.
// Rundet IMMER auf ganze Zeilen ab (nie eine halb abgeschnittene Zeile, Korrektur
// 2026-08-27) -- 21px Zeile + 8px Abstand, wie .projekt-liste/.filter-gruppe ul (gleiches
// Prinzip wie tabellen.js:passeTabelleHoeheAn() fuer Tabellenzeilen).
function aufZeilenAbrunden(budgetPx) {
  var n = Math.floor((budgetPx + 8) / 29);
  return Math.max(0, n * 29 - 8);
}
// Reihenfolge in #filter-panel (index.html): [0] Projekte, [1] Anbieter, [2] Personas (C14, immer
// sichtbar), [3] Umgebung (C12, hidden ausser bei >= 2 Werten -- offsetHeight zaehlt dann 0 mit),
// [4] Kontext -- seit C14 fuenf statt vier .filter-gruppe-Bloecke.
// Notbremse im else-Zweig (Korrektur 2026-08-27, PRUEFERGEBNIS Layout-Nachlese 2026-08-28
// Punkt 3): "KONTEXT + alle QUELLEN-Bloecke immer sichtbar" ist bei 1366x768 rechnerisch NICHT
// in jedem Fall erreichbar (s. Bericht -- selbst mit 1-4 aktiven Projekten und ZULETZT AKTIV auf
// 0px fehlen noch ~110px, mit mehr aktiven Projekten mehr). KONTEXT behaelt darum seine eigene
// interne Scrollbar als Ausweichstufe -- #filter-panel bleibt overflow:hidden (kein Aussen-
// Scrollbalken), ein NICHT schrumpfendes KONTEXT wuerde sonst stillschweigend am unteren
// Panelrand abgeschnitten UND unerreichbar. Math.max(29, ...) haelt mindestens 1 Zeile sichtbar
// -- eine Ueberschrift ganz ohne Zeile darunter waere schlechter als eine kleine, weiterhin
// scrollbare Liste; der letzte Rest-Ueberlauf (s. Bericht) bleibt dadurch bewusst bestehen.
function passeSeitenleisteHoeheAn() {
  var panel = document.getElementById("filter-panel");
  var gruppen = panel ? panel.querySelectorAll(".filter-gruppe") : [];
  var projListe = document.getElementById("projekt-liste-aktiv");
  var kontextGruppe = gruppen.length === 5 && gruppen[4];
  var kontextListe = kontextGruppe && kontextGruppe.querySelector("ul");
  if (gruppen.length !== 5 || !projListe || !kontextListe) return;
  kontextListe.style.height = ""; // erst natuerlich messen (kein Rest von einem frueheren Lauf)
  var cs = getComputedStyle(panel);
  var verfuegbar = panel.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  var fix = fixHoeheAusserListen(gruppen[0], kontextGruppe, [gruppen[1], gruppen[2], gruppen[3]], projListe, kontextListe);
  var kontextNatuerlich = kontextListe.scrollHeight;
  var restFuerZuletztAktiv = verfuegbar - fix - kontextNatuerlich;
  if (restFuerZuletztAktiv >= 0) {
    projListe.style.height = aufZeilenAbrunden(restFuerZuletztAktiv) + "px";
  } else {
    projListe.style.height = "0px";
    kontextListe.style.height = Math.max(29, aufZeilenAbrunden(kontextNatuerlich + restFuerZuletztAktiv)) + "px";
  }
}

// ================= Sitzungen-Tabelle =================
// `unzugeordnet` ist keiner der fuenf gepflegten Kontexte -- die Checkboxen gelten nur fuer
// die fuenf, unzugeordnete Sitzungen bleiben immer sichtbar (sonst waere die Unzugeordnet-
// Kachel ein Drilldown ins Leere).
function effektiveDrilldownIds() {
  if (!zustand.drilldownIds) return null;
  if (!zustand.zeigeErledigteImDrilldown || !zustand.drilldownErledigtIds) return zustand.drilldownIds;
  var vereint = new Set(zustand.drilldownIds);
  zustand.drilldownErledigtIds.forEach(function (id) { vereint.add(id); });
  return vereint;
}
function gefilterteSitzungen() {
  var ids = effektiveDrilldownIds();
  return zustand.sitzungenCache.filter(function (z) {
    return zustand.aktiveProjekte.has(z.projekt)
      && zustand.aktiveQuellen.has(z.quelle)
      && (z.kontext === "unzugeordnet" || zustand.aktiveKontexte.has(z.kontext))
      && (!z.umgebung || zustand.aktiveUmgebungen.has(z.umgebung))
      && zustand.aktivePersonas.has(z.persona || "vico")
      && (!ids || ids.has(z.id));
  });
}

function statusZelleHtml(z) {
  if (z.quelle === "Produkt") return '<span class="produkt-status">Produkt-Ereignis</span>';
  var teile = [];
  if (z.anzahl_befunde > 0) {
    var klasse = z.fehler > 0 ? "st-fehler" : "st-warnung";
    teile.push('<span class="status-pille ' + klasse + '">' + z.anzahl_befunde + " Auffälligkeit" + (z.anzahl_befunde === 1 ? "" : "en") + "</span>");
  } else {
    teile.push('<span class="status-pille st-erfolg">ok</span>');
  }
  if (z.dissens) teile.push('<span class="status-pille st-fehler">Dissens</span>');
  return teile.join(" ");
}

function baueSitzungZeile(z) {
  var tr = document.createElement("tr");
  tr.className = "zeile-klickbar";
  tr.setAttribute("data-projekt", z.projekt);
  // Spalte Zeit = Sitzungsbeginn (z.start), nicht Erfassungszeit (Befund 2026-08-27:
  // "08:36" war der Ingest-Lauf, nicht der Start). zeitstempel bleibt Fallback fuer Altbelege.
  var zeit = z.start || z.zeitstempel;
  tr.setAttribute("data-zeit", String(new Date(zeit).getTime()));
  var kontextText = z.kontext ? " <span class=\"caption\">· " + escapeHtml(z.kontext) + "</span>" : "";
  // projekt-zelle clippt per Ellipsis statt in die Quelle-Spalte zu laufen (Befund 2026-08-27,
  // Nr. 535); title traegt den vollen Text, "· Kontext" steht zuletzt und kuerzt darum zuerst weg.
  var projektTitel = z.projekt + (z.kontext ? " · " + z.kontext : "");
  tr.innerHTML = ""
    + '<td class="num">' + z.id + "</td>"
    + '<td><a href="#sitzung/' + z.id + '" class="zeilen-link">' + formatZeitSpalte(zeit, zustand.von, zustand.bis) + "</a></td>"
    + '<td class="projekt-zelle" title="' + escapeHtml(projektTitel) + '">' + escapeHtml(z.projekt) + umgebungChipHtml(z.umgebung) + kontextText + "</td>"
    + "<td>" + quelleChipHtml(z.quelle) + "</td>"
    + '<td class="num">' + formatDauerKurz(z.dauer_ms) + "</td>"
    + '<td class="num">' + (z.runden ?? "—") + "</td>"
    + '<td class="num">' + (z.tools ?? "—") + "</td>"
    + '<td class="num">' + (z.fehler ?? "—") + "</td>"
    + '<td class="num">' + formatKosten(z.kosten, z.quelle) + "</td>"
    + '<td class="status-zelle">' + statusZelleHtml(z) + "</td>"
    + "<td>" + personaZelleHtml(z.persona, z.kanal) + "</td>"
    + '<td class="num spalte-treffer">' + (zustand.drilldownTreffer && zustand.drilldownTreffer[z.id] !== undefined ? zustand.drilldownTreffer[z.id] : "—") + "</td>";
  return tr;
}

// Sitzungstabelle fuellt seit Feedback 2026-08-27 die Restflaeche bis zur Unterkante von
// .start-mitte statt fix 10 Zeilen zu zeigen -- passeTabelleHoeheAn() (tabellen.js) misst live
// und liefert die dazu passende Zeilenzahl, die HIER als .tg-scrollt-Schwelle dient (statt der
// festen 10 der uebrigen Tabellen).
export function renderSitzungenTabelle() {
  var zeilen = gefilterteSitzungen();
  tbodySitzungen.innerHTML = "";
  if (!zeilen.length) {
    tbodySitzungen.innerHTML = '<tr><td colspan="12" class="caption" style="padding:16px;">Keine Sitzungen im gewählten Zeitraum/Filter.</td></tr>';
    passeTabelleHoeheAn("sitzungen-koerper");
    setzeTabelleScrollt("sitzungen-gitter", 0);
    return;
  }
  zeilen.forEach(function (z) { tbodySitzungen.appendChild(baueSitzungZeile(z)); });
  var passendeZeilen = passeTabelleHoeheAn("sitzungen-koerper");
  setzeTabelleScrollt("sitzungen-gitter", zeilen.length, passendeZeilen);
}

// ---- Sortierbare Spalten ----
var sortSpalte = { nr: 0, zeit: 1, projekt: 2, quelle: 3, dauer: 4, runden: 5, tools: 6, fehler: 7, euro: 8, status: 9, persona: 10, treffer: 11 };
var aktuellerSort = { spalte: "zeit", richtung: -1 };

function sortiereTabelle(spalte, typ) {
  var richtung = aktuellerSort.spalte === spalte ? aktuellerSort.richtung * -1 : (spalte === "zeit" ? -1 : 1);
  aktuellerSort = { spalte: spalte, richtung: richtung };
  var zeilen = Array.prototype.slice.call(tbodySitzungen.querySelectorAll("tr"));
  zeilen.sort(function (a, b) {
    var va = holeSortWert(a, spalte, typ, sortSpalte), vb = holeSortWert(b, spalte, typ, sortSpalte);
    if (typ === "text") return richtung * String(va).localeCompare(String(vb), "de");
    var aN = isNaN(va), bN = isNaN(vb);
    if (aN && bN) return 0;
    if (aN) return 1;
    if (bN) return -1;
    return richtung * (va - vb);
  });
  zeilen.forEach(function (tr) { tbodySitzungen.appendChild(tr); });
  // Nach dem Umsortieren an den Tabellenkopf: scroll-snap "mandatory" snappt sonst auf die
  // alte Ankerzeile zurueck, die nach der neuen Ordnung mitten in der Tabelle liegt
  // (live gemessen 2026-08-28: scrollTop 6576 nach zwei USD-Klicks, Nutzer sieht Tabellenmitte).
  var koerperEl = tbodySitzungen.closest(".tabelle-koerper");
  if (koerperEl) koerperEl.scrollTop = 0;
  tabelleSitzungen.querySelectorAll("thead th").forEach(function (th) {
    var knopf = th.querySelector(".th-sort");
    if (!knopf) return;
    var pfeil = knopf.querySelector(".sort-arrow");
    if (knopf.getAttribute("data-col") === spalte) {
      th.setAttribute("aria-sort", richtung === 1 ? "ascending" : "descending");
      pfeil.textContent = richtung === 1 ? "▲" : "▼";
    } else {
      th.setAttribute("aria-sort", "none");
      pfeil.textContent = "";
    }
  });
}

// ================= Querschnitt-Kacheln =================
// `titel` (Nachtrag 2026-08-27 Punkt 9b, Sichtung): Detailtext als natives Tooltip statt
// zweiter Zeile im Label -- die Fehler-Kachel wurde durch "haeufigstes: Bash · tool_error (91)"
// zweizeilig und kostete eine ganze Sitzungszeile Hoehe (Ziel: mind. eine Zeile mehr sichtbar).
function kachelHtml(k) {
  var titel = k.titel ? ' title="' + escapeHtml(k.titel) + '"' : "";
  return '<button type="button" class="kachel-alert ' + k.klasse + '"' + titel + '>'
    + '<span class="kachel-zahl">' + escapeHtml(k.zahl) + '</span>'
    + '<span class="kachel-status">' + escapeHtml(k.status) + '</span>'
    + '<span class="kachel-label">' + escapeHtml(k.label) + '</span></button>';
}

// Feste Reihenfolge (Mockup): Fehler / Kosten / Erfassungslücke / Dissens -- plus Unzugeordnet
// additiv, NUR wenn N>0 (Namenskonvention Projekt+Kontext, Entscheid 2026-08-26).
export function baueKacheln(daten) {
  var f = daten.wiederkehrende_fehler || {
    anzahl: 0, top_signatur: "", top_anzahl_sitzungen: 0, top_werkzeug: "", top_fehlerklasse: "",
    top_treffer_gesamt: 0, sitzung_ids: [], signaturen: [],
  };
  var k = daten.kosten_ausreisser || { anzahl: 0, sitzung_ids: [] };
  var l = daten.erfassungsluecken || { anzahl: 0, sitzung_ids: [] };
  var d = daten.dissens || { anzahl: 0, sitzung_ids: [] };
  var u = daten.unzugeordnet || { anzahl: 0, sitzung_ids: [] };
  // Fuenfte Kachel (Phase 2 E, CONTRACTS.md C7): Befunde ohne Vier-Augen-Urteil (C2-Status
  // "offen"), additiv befuellt aus dem neuen Endpunkt GET /api/kacheln/pruefung-offen
  // (`befund_kacheln.py`) -- die vier Kacheln oben bleiben unveraendert (Phase 1/andere Pakete).
  var p = daten.pruefung_offen || { anzahl: 0, sitzung_ids: [] };
  // "7 Fehlerbilder in >= 3 Sitzungen, haeufigstes: Bash · tool_error (174)" -- die Kachel
  // zaehlt Fehlerbilder (Signaturen), nicht Sitzungen; der Klick oeffnet darum ein Panel mit
  // allen Fehlerbildern statt direkt in eine (irrefuehrende) Vereinigungs-Sitzungsliste zu
  // springen (Umbau 2026-08-26, Befund: „7 Fehler" wirkte wie 7 Sitzungen).
  // Nachtrag 2026-08-27 Punkt 9b: das "haeufigstes: ..."-Detail zieht ins Tooltip (`titel`),
  // das Label selbst bleibt einzeilig.
  var fehlerLabel = f.anzahl > 0 ? "Fehlerbilder in ≥ 3 Sitzungen" : "Keine wiederkehrenden Fehler";
  var fehlerTitel = f.anzahl > 0
    ? "Häufigstes: " + (f.top_werkzeug || "—") + " · " + (f.top_fehlerklasse || "—") + " (" + f.top_treffer_gesamt + ")"
    : "";
  var kacheln = [
    { klasse: "st-fehler", zahl: String(f.anzahl), status: "Fehler", label: fehlerLabel, titel: fehlerTitel,
      istFehlerKachel: true, fehlerDaten: f },
    { klasse: "st-warnung", zahl: String(k.anzahl), status: "Warnung", label: "Kosten-Ausreißer", ids: k.sitzung_ids,
      erledigtIds: k.sitzung_ids_erledigt || [], banner: "Kosten-Ausreißer — " + k.anzahl },
    { klasse: "st-warnung", zahl: String(l.anzahl), status: "Warnung", label: "Erfassungslücke", ids: l.sitzung_ids,
      erledigtIds: l.sitzung_ids_erledigt || [], banner: "Erfassungslücke — " + l.anzahl },
    { klasse: "st-kritisch", zahl: String(d.anzahl), status: "Kritisch", label: "Dissens Vier-Augen", ids: d.sitzung_ids,
      erledigtIds: [], banner: "Dissens Vier-Augen — " + d.anzahl },
  ];
  kacheln.push({ klasse: "st-neutral", zahl: String(p.anzahl), status: "Prüfung offen", label: "Befunde ohne Vier-Augen-Urteil",
    ids: p.sitzung_ids, erledigtIds: [], banner: "Prüfung offen — " + p.anzahl + " Befunde" });
  // Wache-Kachel entfernt (Sichtbefund 2026-08-28 spaet): ohne Sitzungs-Drilldown wirkte
  // die Kachel kaputt (Klick zeigte unten nichts). Wache-Meldungen bleiben als Marker im
  // Sitzungsverlauf sichtbar; eine eigene Ansicht ist ein Folge-Entscheid.
  if (u.anzahl > 0) {
    kacheln.push({ klasse: "st-neutral", zahl: String(u.anzahl), status: "Unzugeordnet", label: "Unzugeordnet",
      ids: u.sitzung_ids, erledigtIds: [], banner: "Unzugeordnet — " + u.anzahl });
  }
  return kacheln;
}

export function renderQuerschnitt(daten, containerId) {
  var el = document.getElementById(containerId);
  var kacheln = baueKacheln(daten);
  el.innerHTML = kacheln.map(kachelHtml).join("");
  Array.prototype.forEach.call(el.querySelectorAll(".kachel-alert"), function (btn, i) {
    btn.addEventListener("click", function () {
      if (kacheln[i].istFehlerKachel) { oeffneFehlerPanelUndSpringe(kacheln[i].fehlerDaten); return; }
      schliesseFehlerPanel();
      drilldownZuSitzungen(kacheln[i].ids, kacheln[i].banner, kacheln[i].signatur, kacheln[i].erledigtIds);
    });
  });
}

function setzeTrefferSpalteSichtbar(sichtbar) {
  document.body.classList.toggle("zeigt-treffer", !!sichtbar);
}

function drilldownZuSitzungen(ids, banner, signatur, erledigtIds) {
  zustand.drilldownIds = new Set(ids);
  zustand.drilldownBanner = banner || null;
  zustand.drilldownTreffer = null;
  zustand.drilldownErledigtIds = erledigtIds && erledigtIds.length ? new Set(erledigtIds) : null;
  zustand.zeigeErledigteImDrilldown = false;
  setzeTrefferSpalteSichtbar(false);
  if (location.hash.replace("#", "").split("/")[0] === "start") { renderSitzungenTabelle(); zeigeFilterBanner(); }
  else location.hash = "#start";
  // Banner einblenden OHNE zu scrollen (Feedback 2026-08-26, Punkt 2: ein Kachel-Klick
  // darf die Scrollposition nicht veraendern -- nur der Inhalt unter den Kacheln wechselt).
  setTimeout(function () { zeigeFilterBanner(); }, 0);
  // Fehler-Drilldown: zusätzlicher Fetch mit `signatur=` fürs Treffer je Zeile (B.2).
  if (signatur) {
    holeJSON("/api/sitzungen", { von: iso(zustand.von), bis: iso(zustand.bis), signatur: signatur })
      .then(function (zeilen) {
        var treffer = {};
        zeilen.forEach(function (z) { treffer[z.id] = z.treffer || 0; });
        zustand.drilldownTreffer = treffer;
        setzeTrefferSpalteSichtbar(true);
        renderSitzungenTabelle();
      })
      .catch(function () { /* Treffer-Spalte bleibt aus, Drilldown funktioniert trotzdem */ });
  }
}

function zeigeFilterBanner() {
  var banner = document.getElementById("filter-banner");
  var erledigtZeile = document.getElementById("filter-banner-erledigt-zeile");
  var erledigtCheckbox = document.getElementById("filter-banner-erledigt");
  if (zustand.drilldownIds) {
    banner.hidden = false;
    document.getElementById("filter-banner-text").textContent =
      zustand.drilldownBanner || ("Gefiltert aus Querschnitt: " + zustand.drilldownIds.size + " Sitzung(en).");
    erledigtZeile.hidden = !zustand.drilldownErledigtIds;
    erledigtCheckbox.checked = zustand.zeigeErledigteImDrilldown;
  } else {
    banner.hidden = true;
    erledigtZeile.hidden = true;
  }
}

// ================= Fehler-Panel (zweistufiger Drilldown, Umbau 2026-08-26) =================
// Stufe 1: Kachel-Klick -> dieses Panel mit EINER Zeile je Fehlerbild (Signatur). Stufe 2:
// Knopf "Sitzungen" in einer Zeile -> normaler Drilldown (drilldownZuSitzungen), aber immer nur
// für GENAU diese Signatur -- Treffer-Spalte und Sitzungsliste passen darum immer zusammen
// (der alte Bug: Klick zeigte die Vereinigung ALLER Signaturen, Treffer zählte nur die Top-Signatur).
var fehlerPanelOffen = false;
var fehlerPanelZeilen = [];
var fehlerPanelSort = { spalte: "anzahl_sitzungen", richtung: -1 };
// Panel-Zeile, deren "Sitzungen"-Knopf zuletzt geklickt wurde (Entscheid 2026-08-26,
// Auftrag 2 -- bleibt bis "Filter aufheben" oder neuem Panel-Öffnen markiert).
var fehlerPanelAusgewaehlt = null;

// Klick auf eine andere Querschnitt-Kachel klappt das Fehlerbild-Panel wieder zu
// (Sichtbefund 2026-08-28: es blieb sonst unter der neuen Auswahl stehen).
function schliesseFehlerPanel() {
  fehlerPanelOffen = false;
  var abschnitt = document.getElementById("fehler-panel-abschnitt");
  if (abschnitt) { abschnitt.hidden = true; }
}

function oeffneFehlerPanelUndSpringe(f) {
  fehlerPanelZeilen = f.signaturen || [];
  fehlerPanelAusgewaehlt = null;
  fehlerPanelOffen = true;
  document.getElementById("fehler-panel-abschnitt").hidden = false;
  renderFehlerbilderTabelle();
  // Kein scrollIntoView mehr (Feedback 2026-08-26, Punkt 2): die Seite bleibt an ihrer
  // Scrollposition stehen, nur der Inhalt unter den Kacheln wechselt. Der Hash-Wechsel bleibt
  // noetig, wenn die Kachel von einer ANDEREN Seite (z. B. Querschnitt) aus geklickt wurde --
  // das Panel existiert nur im DOM der Start-Seite.
  if (location.hash.replace("#", "").split("/")[0] !== "start") { location.hash = "#start"; }
}

function fehlerbildErledigtFormularHtml() {
  return '<div class="erledigt-formular">'
    + '<label>Status<select class="ef-status"><option value="erledigt">erledigt</option><option value="obsolet">obsolet</option><option value="offen">offen (Wiedereröffnung)</option></select></label>'
    + '<label>Vermerk<input type="text" class="ef-vermerk" maxlength="500" placeholder="z. B. TROUBLESHOOTING Abschn. X, Commit-Hash"></label>'
    + '<label>Begründung<input type="text" class="ef-begruendung" maxlength="500"></label>'
    + verankerungFormularHtml()
    + '<p class="erledigt-fehler" hidden></p>'
    + '<div class="zeile"><button type="button" class="link-btn fef-abbrechen">Abbrechen</button>'
    + '<button type="button" class="outline-btn fef-absenden" data-verankerung-knopf>Speichern</button></div></div>';
}

function fehlerbildBannerText(z, ids) {
  return "Gefiltert: Fehlerbild " + fehlerbildLabel(z) + " — " + ids.length
    + " Sitzungen, Spalte Treffer = Vorkommen je Sitzung";
}

function fehlerbildZeileHtml(z) {
  var sigAttr = escapeHtml(z.signatur || "");
  var ausgewaehlt = fehlerPanelAusgewaehlt === z.signatur;
  return '<tr data-signatur="' + sigAttr + '" aria-selected="' + (ausgewaehlt ? "true" : "false") + '">'
    + '<td class="fehlerbild-zelle"><span class="zwei-zeilen">' + escapeHtml(fehlerbildLabel(z)) + "</span></td>"
    + '<td class="fehlerbild-zelle"><span class="zwei-zeilen">' + escapeHtml(z.werkzeug || "—") + "</span></td>"
    + '<td class="fehlerbild-zelle"><span class="zwei-zeilen">' + escapeHtml(z.fehlerklasse || "—") + "</span></td>"
    + '<td class="num">' + z.anzahl_sitzungen + "</td>"
    + '<td class="num">' + z.treffer_gesamt + "</td>"
    + "<td>" + statusBadgeHtml(z) + "</td>"
    + '<td class="fp-aktionen-zelle"><div class="fp-aktionen">'
    + '<button type="button" class="ghost-btn fp-sitzungen-btn">Sitzungen</button>'
    + '<button type="button" class="ghost-btn fp-erledigt-btn">Erledigt…</button>'
    + "</div></td></tr>"
    + '<tr class="fp-formular-zeile" hidden><td class="fp-formular-zelle" colspan="7"></td></tr>';
}

function renderFehlerbilderTabelle() {
  var zeitraumEl = document.getElementById("fehler-panel-zeitraum");
  if (zeitraumEl) zeitraumEl.textContent = periodenSuffix();
  var tbody = document.getElementById("fehlerbilder-body");
  if (!fehlerPanelZeilen.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="caption" style="padding:16px;">Keine wiederkehrenden Fehler im Zeitraum.</td></tr>';
    setzeTabelleScrollt("fehlerbilder-gitter", 0);
    return;
  }
  var richtung = fehlerPanelSort.richtung, spalte = fehlerPanelSort.spalte;
  var zeilen = fehlerPanelZeilen.slice().sort(function (a, b) {
    var va = spalte === "fehlerbild" ? fehlerbildLabel(a) : a[spalte];
    var vb = spalte === "fehlerbild" ? fehlerbildLabel(b) : b[spalte];
    if (typeof va === "string") return richtung * String(va).localeCompare(String(vb), "de");
    return richtung * (va - vb);
  });
  tbody.innerHTML = zeilen.map(fehlerbildZeileHtml).join("");
  Array.prototype.forEach.call(tbody.querySelectorAll("tr[data-signatur]"), function (tr) {
    var z = zeilen.filter(function (x) { return x.signatur === tr.getAttribute("data-signatur"); })[0];
    tr.querySelector(".fp-sitzungen-btn").addEventListener("click", function () {
      // Rückfall filtert nur auf die Sitzungen SEIT dem Entscheid (Entscheid 2026-08-26,
      // Auftrag 1) -- alle anderen Status nehmen weiterhin die volle Sitzungsliste.
      var ids = z.status === "rueckfall" ? z.rueckfall_sitzungen.sitzung_ids : z.sitzung_ids;
      fehlerPanelAusgewaehlt = z.signatur;
      renderFehlerbilderTabelle();
      drilldownZuSitzungen(ids, fehlerbildBannerText(z, ids), z.signatur, null);
    });
    tr.querySelector(".fp-erledigt-btn").addEventListener("click", function () {
      oeffneFehlerbildErledigtFormular(z, tr);
    });
  });
  setzeTabelleScrollt("fehlerbilder-gitter", zeilen.length);
}

function oeffneFehlerbildErledigtFormular(z, tr) {
  var formZeile = tr.nextElementSibling;
  var zelle = formZeile.querySelector(".fp-formular-zelle");
  if (zelle.querySelector(".erledigt-formular")) { zelle.innerHTML = ""; formZeile.hidden = true; return; }
  zelle.innerHTML = fehlerbildErledigtFormularHtml();
  formZeile.hidden = false;
  verankerungSichtbarSchalten(zelle, zelle.querySelector(".ef-status").value);
  zelle.querySelector(".ef-status").addEventListener("change", function () { verankerungSichtbarSchalten(zelle, this.value); });
  zelle.querySelector(".v-pfad").addEventListener("input", function () {
    verankerungSichtbarSchalten(zelle, zelle.querySelector(".ef-status").value);
  });
  zelle.querySelector(".fef-abbrechen").addEventListener("click", function () { zelle.innerHTML = ""; formZeile.hidden = true; });
  zelle.querySelector(".fef-absenden").addEventListener("click", function () { sendeFehlerbildErledigt(z, zelle); });
}

// Entscheid gilt GLOBAL fuer die Signatur (sitzung_ref: null) -- anders als das Erledigt-
// Formular auf der Sitzungsseite (dort je Sitzung), weil eine Panel-Zeile ein Fehlerbild ueber
// ALLE Sitzungen zusammenfasst, nicht eine einzelne Sitzung.
function sendeFehlerbildErledigt(z, zelle) {
  var status = zelle.querySelector(".ef-status").value;
  var vermerk = zelle.querySelector(".ef-vermerk").value;
  var begruendung = zelle.querySelector(".ef-begruendung").value;
  var fehlerEl = zelle.querySelector(".erledigt-fehler");
  var knopf = zelle.querySelector(".fef-absenden");
  fehlerEl.hidden = true;
  knopf.disabled = true;
  fetch("/api/befund/entscheid", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      signatur: "error:recurring:" + z.signatur, status: status, vermerk: vermerk,
      begruendung: begruendung, sitzung_ref: null, verankerung: verankerungAusFormular(zelle),
    }),
  }).then(function (antwort) {
    if (!antwort.ok) return antwort.json().then(function (d) { throw new Error(d.detail || ("HTTP " + antwort.status)); });
    return antwort.json();
  }).then(function () {
    z.status = status === "offen" ? "offen" : "erledigt";
    zelle.innerHTML = "";
    zelle.closest("tr").hidden = true;
    renderFehlerbilderTabelle();
  }).catch(function (e) {
    fehlerEl.textContent = e.message;
    fehlerEl.hidden = false;
    knopf.disabled = false;
  });
}

// ================= Seite: Start =================
// Sequenznummer (Fund C.4): ein schneller Zeitraum-/Filterwechsel kann eine neue ladeStart()
// auslösen, bevor die vorige Antwort da ist -- nur die JÜNGSTE Sequenz darf noch rendern.
var ladeSequenz = 0;

// Eigene Funktion statt Inline-Callback (haelt ladeStart() unter der 20-Zeilen-Grenze).
function _renderStartErgebnisse(ergebnisse) {
  // `umgebungen` kommt aus /api/querschnitt (C12), nicht aus /api/projekte -- renderFilterPanel
  // bekommt beide Quellen zusammengefuehrt, wie schon die Fehler-Kachel den Umweg ueber ergebnisse[3] geht.
  renderFilterPanel(Object.assign({}, ergebnisse[0], { umgebungen: ergebnisse[1].umgebungen }));
  var querschnittDaten = Object.assign({}, ergebnisse[1], { pruefung_offen: ergebnisse[3], wache: ergebnisse[4] });
  renderQuerschnitt(querschnittDaten, "querschnitt-grid");
  zustand.sitzungenCache = ergebnisse[2];
  zeigeFilterBanner();
  renderSitzungenTabelle();
  // Panel offen (z. B. Rueckkehr aus Querschnitt-Seite oder nach Erledigt-Entscheid) --
  // mit frischen Daten neu befuellen, offen lassen.
  if (fehlerPanelOffen) {
    fehlerPanelZeilen = (ergebnisse[1].wiederkehrende_fehler || {}).signaturen || [];
    renderFehlerbilderTabelle();
  }
}

// Fuenfte Kachel (Phase 2 E) ueber einen EIGENEN Endpunkt -- ein Fehler dort (z. B. Server noch
// nicht neu gestartet) darf die restliche Startseite nicht mitreissen, darum eigener Catch mit
// neutralem Leerwert statt im gemeinsamen Promise.all zu haengen.
function _ladePruefungOffen(von, bis) {
  return holeJSON("/api/kacheln/pruefung-offen", { von: von, bis: bis })
    .catch(function () { return { anzahl: 0, sitzung_ids: [] }; });
}

// Wache-Kachel (C13-Nachtrag): eigener Endpunkt, gleiches Fail-safe-Muster wie _ladePruefungOffen.
function _ladeWache(von, bis) {
  return holeJSON("/api/wache/meldungen", { von: von, bis: bis })
    .catch(function () { return { anzahl: 0, offen_fragen: 0, meldungen: [] }; });
}

export function ladeStart() {
  var meineSequenz = ++ladeSequenz;
  var von = iso(zustand.von), bis = iso(zustand.bis);
  Promise.all([
    holeJSON("/api/projekte", { von: von, bis: bis }),
    holeJSON("/api/querschnitt", { von: von, bis: bis }),
    holeJSON("/api/sitzungen", { von: von, bis: bis }),
    _ladePruefungOffen(von, bis),
    _ladeWache(von, bis),
  ]).then(function (ergebnisse) {
    if (meineSequenz === ladeSequenz) _renderStartErgebnisse(ergebnisse);
  }).catch(function (e) { if (meineSequenz === ladeSequenz) zeigeFehler("querschnitt-grid", e); });
}

// DOM-Verkabelung (frueher top-level in der IIFE) -- von app.js in der urspruenglichen
// Reihenfolge aufgerufen, nachdem das DOM geparst ist.
function _initFilterPanelWiring() {
  document.getElementById("filter-panel").addEventListener("change", function (e) {
    var cbProjekt = e.target.closest("input[type=checkbox][data-projekt]");
    if (cbProjekt) { setzeProjektAktiv(cbProjekt.getAttribute("data-projekt"), cbProjekt.checked); return; }
    var cbQuelle = e.target.closest("input[type=checkbox][data-quelle]");
    if (cbQuelle) { setzeQuelleAktiv(cbQuelle.getAttribute("data-quelle"), cbQuelle.checked); return; }
    var cbKontext = e.target.closest("input[type=checkbox][data-kontext]");
    if (cbKontext) { setzeKontextAktiv(cbKontext.getAttribute("data-kontext"), cbKontext.checked); return; }
    var cbUmgebung = e.target.closest("input[type=checkbox][data-umgebung]");
    if (cbUmgebung) { setzeUmgebungAktiv(cbUmgebung.getAttribute("data-umgebung"), cbUmgebung.checked); return; }
    var cbPersona = e.target.closest("input[type=checkbox][data-persona]");
    if (cbPersona) setzePersonaAktiv(cbPersona.getAttribute("data-persona"), cbPersona.checked);
  });

  document.getElementById("proj-alle").addEventListener("click", function () {
    zustand.aktiveProjekte = new Set(letzteProjekte.map(function (p) { return p.name; }));
    document.querySelectorAll("#projekt-liste-aktiv input, #projekt-liste-weitere input").forEach(function (cb) { cb.checked = true; });
    renderSitzungenTabelle();
  });
  document.getElementById("proj-keine").addEventListener("click", function () {
    zustand.aktiveProjekte.clear();
    document.querySelectorAll("#projekt-liste-aktiv input, #projekt-liste-weitere input").forEach(function (cb) { cb.checked = false; });
    renderSitzungenTabelle();
  });
  document.getElementById("projekt-suche").addEventListener("input", function (e) {
    var q = e.target.value.trim().toLowerCase();
    var treffer = false;
    document.querySelectorAll("#projekt-liste-weitere .filter-zeile").forEach(function (li) {
      var passt = !q || li.getAttribute("data-projekt-name").indexOf(q) !== -1;
      li.style.display = passt ? "" : "none";
      if (passt && q) treffer = true;
    });
    document.querySelectorAll("#projekt-liste-aktiv .filter-zeile").forEach(function (li) {
      li.style.display = (!q || li.getAttribute("data-projekt-name").indexOf(q) !== -1) ? "" : "none";
    });
    if (q && treffer) document.querySelector(".weitere-projekte").open = true;
  });
}

// Hilfe-Text-Toggle (hilfen.js, document-Listener) und "Weitere"-Ausklappen aendern die
// Fixhoehe der Gruppen -- Restflaeche neu verteilen. setTimeout: hilfen.js schaltet `hidden`
// im selben Klick-Bubbling nach diesem Listener um (Ziel liegt naeher an `document`). Eigene
// Funktion statt Anhang an _initFilterPanelWiring (die reisst sonst die 20-Zeilen-Funktions-
// grenze, Code-Masse-Waechter).
function _initSeitenleisteHoeheWiring() {
  document.getElementById("filter-panel").addEventListener("click", function (e) {
    if (e.target.closest(".hilfe-btn")) setTimeout(passeSeitenleisteHoeheAn, 0);
  });
  document.querySelector(".weitere-projekte").addEventListener("toggle", passeSeitenleisteHoeheAn);
}

function _initSortierungWiring() {
  tabelleSitzungen.querySelectorAll(".th-sort").forEach(function (knopf) {
    knopf.addEventListener("click", function () { sortiereTabelle(knopf.getAttribute("data-col"), knopf.getAttribute("data-type")); });
  });
}

function _initFilterBannerWiring() {
  document.getElementById("filter-banner-erledigt").addEventListener("change", function (e) {
    zustand.zeigeErledigteImDrilldown = e.target.checked;
    renderSitzungenTabelle();
  });
  document.getElementById("filter-banner-aufheben").addEventListener("click", function () {
    zustand.drilldownIds = null;
    zustand.drilldownBanner = null;
    zustand.drilldownTreffer = null;
    zustand.drilldownErledigtIds = null;
    zustand.zeigeErledigteImDrilldown = false;
    setzeTrefferSpalteSichtbar(false);
    zeigeFilterBanner();
    renderSitzungenTabelle();
    // Panel-Zeilenmarkierung + Treffer-Kopf-Hervorhebung mit aufheben (Entscheid 2026-08-26,
    // Auftrag 2).
    if (fehlerPanelAusgewaehlt !== null) {
      fehlerPanelAusgewaehlt = null;
      if (fehlerPanelOffen) renderFehlerbilderTabelle();
    }
  });
}

function _initFehlerPanelWiring() {
  document.getElementById("fehler-panel-schliessen").addEventListener("click", function () {
    fehlerPanelOffen = false;
    document.getElementById("fehler-panel-abschnitt").hidden = true;
  });

  document.querySelectorAll(".fp-sort").forEach(function (knopf) {
    knopf.addEventListener("click", function () {
      var spalte = knopf.getAttribute("data-col");
      fehlerPanelSort.richtung = fehlerPanelSort.spalte === spalte ? fehlerPanelSort.richtung * -1 : 1;
      fehlerPanelSort.spalte = spalte;
      document.querySelectorAll("#tabelle-fehlerbilder thead th").forEach(function (th) {
        var k = th.querySelector(".fp-sort");
        if (!k) return;
        var pfeil = k.querySelector(".sort-arrow");
        if (k.getAttribute("data-col") === spalte) {
          th.setAttribute("aria-sort", fehlerPanelSort.richtung === 1 ? "ascending" : "descending");
          pfeil.textContent = fehlerPanelSort.richtung === 1 ? "▲" : "▼";
        } else {
          th.setAttribute("aria-sort", "none");
          pfeil.textContent = "";
        }
      });
      renderFehlerbilderTabelle();
    });
  });
}

// Resize (debounced, Feedback 2026-08-27): die passende Zeilenzahl der Sitzungstabelle
// haengt von der Fensterhoehe ab (.start-mitte ist volle Viewport-Hoehe minus Kopf) -- ohne
// Nachmessen bliebe die beim letzten Rendern berechnete Hoehe nach einem Resize stehen. 150ms
// Debounce reicht, damit ein Zieh-Resize nicht bei jedem Pixel neu misst.
var hoeheAnpassenTimer = null;
function planeHoeheAnpassen() {
  clearTimeout(hoeheAnpassenTimer);
  hoeheAnpassenTimer = setTimeout(function () {
    var passendeZeilen = passeTabelleHoeheAn("sitzungen-koerper");
    setzeTabelleScrollt("sitzungen-gitter", gefilterteSitzungen().length, passendeZeilen);
    passeSeitenleisteHoeheAn();
  }, 150);
}

export function initStart() {
  // Kopf (nur thead) und Koerper (nur tbody) sind seit dem Tabellen-Scroll-Standard
  // (Korrektur 2026-08-26) zwei getrennte Tabellen -- tabelleSitzungen bleibt die
  // Kopf-Tabelle (thead-Zugriff fuer die Sortierpfeile), tbodySitzungen zeigt jetzt auf den
  // <tbody> der Koerper-Tabelle.
  tabelleSitzungen = document.getElementById("tabelle-sitzungen");
  tbodySitzungen = document.getElementById("sitzungen-body");

  _initFilterPanelWiring();
  _initSeitenleisteHoeheWiring();
  _initSortierungWiring();
  _initFilterBannerWiring();
  _initFehlerPanelWiring();
  window.addEventListener("resize", planeHoeheAnpassen);
}
