// Seite: Einstellungen -> Unteransicht "Modellkatalog" (Paket L, CONTRACTS.md C15).
// Persona-Kacheln (Standardmodelle je VICO/VICA/CURA + LOKAL-Bestand) + sortier-/filterbare
// Katalogtabelle (GET /api/modellkatalog). Filter/Sortierung laufen komplett client-seitig auf
// dem einmal geladenen Array -- reine Funktionen unten sind Node-testbar (tests/test_katalog.mjs,
// Muster tests/test_persona.mjs), DOM-Verkabelung (ladeModellkatalog/initModellkatalog) nicht.
import {
  escapeHtml, quelleChipHtml, ausIso, formatDeVoll,
  modellAnzeigeName, modellNameHtml, herkunftFlaggeHtml,
} from "./format.js";
import { holeJSON, zeigeFehler } from "./api.js";

var ANBIETER_ANZEIGE = { claude: "Claude", ollama: "Ollama", openrouter: "OpenRouter", requesty: "Requesty" };
var PERSONA_REIHENFOLGE = ["vico", "vica", "cura"];
// LOKAL-Piktogramm (Haus, Entscheid Runde 7 des Mockups): stroke=currentColor, kein Fuellton --
// wortgleiche Pfaddaten aus sitzungsbeleg-modellkatalog-mockup.html, hier einmalig als Konstante
// statt je Render-Aufruf neu zu bauen.
var LOKAL_ICON_SVG = '<svg class="lokal-icon" viewBox="0 0 40 40" aria-hidden="true">'
  + '<path d="M6 20 L20 8 L34 20"/><path d="M10 18 V33 H30 V18"/>'
  + '<line x1="15" y1="24" x2="25" y2="24"/><line x1="15" y1="28" x2="25" y2="28"/></svg>';
// Beschriftung Entscheid 2026-08-30 (Nachtrag): sichtbarer Text "lokal" -> "On-Premise"/
// "On-Prem" bei Ollama-Chip-Tooltips. Interne Feldnamen (m.lokal, nurLokal, mk-nur-lokal,
// LOKAL_ICON_SVG, .lokal-*-Klassen) bleiben unveraendert -- nur die Anzeige aendert sich.
var ON_PREM_TOOLTIP = "läuft auf dieser Maschine, keine Datenübertragung";

export function quelleAnzeigeName(code) {
  return ANBIETER_ANZEIGE[code] || (code ? code.charAt(0).toUpperCase() + code.slice(1) : "—");
}

// ================= Reine Formatierungs-/Aggregations-Helfer (Node-testbar) =================

// Contract C15: Preisspalten immer einstellig gerundet ("0,5"/"15,0" im Mockup); `null`
// (kein Tokenpreis, z. B. reine Lokal-Modelle) zeigt "lokal" statt einer erfundenen Zahl.
export function formatPreisZahl(usd) {
  if (usd === null || usd === undefined) return "On-Prem";
  return Number(usd).toFixed(1).replace(".", ",");
}

export function standDatumText(isoDatum) {
  if (!isoDatum) return "—";
  return formatDeVoll(ausIso(isoDatum));
}

// Tooltip mit ALLEN Anbieterpreisen einer Spalte (C15: "Preisspalten zeigen den guenstigsten
// Anbieterpreis, alle Anbieterpreise im Tooltip") -- aufsteigend sortiert, nur bei >=2 Preisen
// ueberhaupt sinnvoll (sonst leerer String, kein redundantes Tooltip mit nur einem Eintrag).
export function tooltipPreise(anbieterListe, feld) {
  var mitPreis = (anbieterListe || []).filter(function (a) { return a[feld] !== null && a[feld] !== undefined; });
  if (mitPreis.length < 2) return "";
  mitPreis.sort(function (a, b) { return a[feld] - b[feld]; });
  return mitPreis.map(function (a) { return quelleAnzeigeName(a.name) + " " + formatPreisZahl(a[feld]); }).join(" · ");
}

// Filter: Suche (Modell-ID/Hersteller), Herkunft-Chips, Anbieter-Checkboxen -- alle UND-verknuepft.
// Herkunft = AUSWAHL-Logik (Umkehr 2026-08-28): leeres Set/null = Vollansicht, ein Klick
// waehlt NUR dieses Land, weitere ergaenzen. Anbieter bleibt Checkbox-ABWAHL-Logik: dort
// bedeutet ein leeres Set "alles abgewaehlt" = leere Liste (bewusst verschieden).
// C15 v2 Punkt 3/6: zwei weitere, NEUTRALE Checkbox-Filter -- "nur lokal" (m.lokal===true) und
// "nur EU-Region ohne Training" (m.eu_ohne_training===true). Ausgeschaltet = keine Wirkung
// (Rueckwaertskompatibel: bestehende Aufrufer ohne die neuen zustand-Felder filtern wie bisher).
// Fehlt das Feld am Modell UND die Checkbox ist an, laesst der Filter das Modell NICHT durch --
// kein stillschweigendes "als ob lokal", solange das Backend das Feld noch nicht liefert.
// "nur Latest" (Auftrag 2026-08-30, Korrektur -- kein STAND-Dropdown, dritte Checkbox in
// derselben Reihe): angehakt laesst nur `status !== "legacy"` durch (also "bewertet"+"latest"),
// ausgeschaltet = Vollansicht. Anders als nurLokal/euOhneTraining braucht `status` keinen
// Fehlt-Fall -- katalog_sicht.py liefert es an JEDEM Modell, ein fehlender Wert ist darum einfach
// "nicht legacy" statt eines eigenen Sperrpfads.
export function filtereModelle(modelle, zustand) {
  var suche = ((zustand && zustand.suchtext) || "").trim().toLowerCase();
  var herkunftAktiv = zustand && zustand.herkunftAktiv;
  var anbieterAktiv = zustand && zustand.anbieterAktiv;
  var nurLokal = zustand && zustand.nurLokal;
  var euOhneTraining = zustand && zustand.euOhneTraining;
  var nurLatest = zustand && zustand.nurLatest;
  return (modelle || []).filter(function (m) {
    if (suche && m.id.toLowerCase().indexOf(suche) === -1
        && (m.hersteller || "").toLowerCase().indexOf(suche) === -1) return false;
    if (herkunftAktiv && herkunftAktiv.size && !herkunftAktiv.has(m.herkunft || "")) return false;
    if (anbieterAktiv && !m.anbieter.some(function (a) { return anbieterAktiv.has(a.name); })) return false;
    if (nurLokal && !m.lokal) return false;
    if (euOhneTraining && !m.eu_ohne_training) return false;
    if (nurLatest && m.status === "legacy") return false;
    return true;
  });
}

// Preis-Leistung-Kennzahl (Eignung-Sortierpreset "Preis-Leistung", CONTRACTS.md C15 v2 Punkt 6):
// AA-Index geteilt durch einen Mischpreis, Eingabe 3-fach staerker gewichtet als Ausgabe
// (3*eingabe + ausgabe) / 4 -- fehlt der Index ODER einer der beiden Preise (reine Lokal-Modelle
// ohne Tokenpreis, noch nicht AA-angereicherte Modelle), gibt es KEINE Kennzahl (null) statt einer
// erfundenen Zahl; sortiereModelle haengt null-Werte ohnehin ans Ende, unabhaengig der Richtung.
export function preisLeistungKennzahl(m) {
  var aa = m.aa_index;
  var preis = m.preis_min || {};
  var eingabe = preis.eingabe_usd, ausgabe = preis.ausgabe_usd;
  if (aa === null || aa === undefined) return null;
  if (eingabe === null || eingabe === undefined || ausgabe === null || ausgabe === undefined) return null;
  var mischpreis = (3 * eingabe + ausgabe) / 4;
  if (!(mischpreis > 0)) return null; // 0 vermeidet Division-durch-0 statt Infinity anzuzeigen
  return aa / mischpreis;
}

// ---------- Automatische Katalog-Sterne v2 (Entscheid 2026-08-30 Nachtrag 6) ----------
// katalog_sicht.py liefert je Modell `sterne: {score, gesamt, manuell}` -- `score` ist das Mittel
// aus aa_index/coding_index (oder der einzelne Wert, fehlt einer), `gesamt` sind die halben
// Sterne 0,5..5,0 (oder `null`, unbewertet). `status` (additiv, TOP-LEVEL am Modell, NICHT in
// `sterne`) ist "bewertet"|"latest"|"legacy" -- ersetzt die reine `nachfolger`-Pruefung von vorher
// als Anzeige-Weiche. `manuell` bleibt der Registry-Tooltip-Zusatz (eigener Test aus
// modelle.json, keine Basis der Katalog-Sterne). Reine Funktionen, in tests/test_katalog.mjs
// getestet.
export function gesamtSterneText(sterne) {
  var g = (sterne || {}).gesamt;
  return g === null || g === undefined ? "–" : Number(g).toFixed(1).replace(".", ",") + " ★";
}

// ---------- Fuenf-Sterne-Widget (Abnahme 2026-08-30): keine Zahl mehr vor dem Stern --
// IMMER 5 kleine Sterne, gefuellt nach `gesamt` (0..5, 0,5-Schritte). Der numerische Wert bleibt
// ausschliesslich im Tooltip (sterneTooltipText) + aria-label (gesamtSterneText) -- nie
// sichtbarer Text neben den Sternen. Halbe Sterne per SVG-linearGradient (50% Sternfarbe/50%
// gedaempft, mittig abgeschnitten) statt CSS `overflow:hidden` auf geklontem Textinhalt -- der
// design_waechter haertet "clipped-overflow-container"/"text-overflow" sonst gegen genau dieses
// Muster (design_waechter/regeln.json "hart").
export var STERN_PFAD = "M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-4.297" +
  "-7.416 4.297 1.48-8.279-6.064-5.828 8.332-1.151z";

// Anzahl volle/halbe/leere Sterne fuer `gesamt` -- reine Funktion, Basis fuer Rendering UND
// Node-Test (tests/test_katalog.mjs).
export function sterneZaehlung(gesamt) {
  var wert = gesamt === null || gesamt === undefined ? 0 : Math.max(0, Math.min(5, Number(gesamt)));
  var voll = Math.floor(wert);
  var halb = wert - voll >= 0.5 ? 1 : 0;
  return { voll: voll, halb: halb, leer: 5 - voll - halb };
}

// Ein einzelner Stern -- `fuellgrad` 0/50/100. Bei 0/100 reicht eine einfarbige Fuellung (kein
// Gradient noetig); nur der halbe Stern braucht die geteilte Farbe. Farben kommen ausschliesslich
// aus style.css (.mk-stern-voll/.mk-stern-leer, `fill`/`stop-color` auf denselben Klassen wie
// .lokal-icon/currentColor-Konvention) -- die Markup-Strings hier tragen keine Inline-Farbwerte.
// `gradientId` muss seitenweit eindeutig sein (SVG-`id` ist global), darum der `schluessel`-
// Parameter in fuenfSterneHtml statt eines globalen Zaehlers -- bleibt reine/deterministische
// Funktion.
// Zusatz 2026-08-30: leere Sternanteile waren mit --text-muted zu dunkel -- Halbsterne wirkten
// nicht als "halb" erkennbar. Der halbe Stern traegt jetzt zusaetzlich `mk-stern-halb` (eigene
// Klasse auf dem EINEN Pfad, der per Gradient beide Haelften fuellt), damit style.css eine duenne
// Kontur (--rand-stark) auf genau diesem Pfad ziehen kann, ohne die vollen (goldenen) Sterne
// anzufassen.
function sternSvgHtml(fuellgrad, gradientId) {
  if (fuellgrad === 0) {
    return '<svg class="mk-stern" viewBox="0 0 24 24" aria-hidden="true">'
      + '<path class="mk-stern-leer" d="' + STERN_PFAD + '"/></svg>';
  }
  if (fuellgrad === 100) {
    return '<svg class="mk-stern" viewBox="0 0 24 24" aria-hidden="true">'
      + '<path class="mk-stern-voll" d="' + STERN_PFAD + '"/></svg>';
  }
  return '<svg class="mk-stern" viewBox="0 0 24 24" aria-hidden="true"><defs>'
    + '<linearGradient id="' + gradientId + '" x1="0" y1="0" x2="1" y2="0">'
    + '<stop class="mk-stern-voll" offset="50%"/>'
    + '<stop class="mk-stern-leer" offset="50%"/>'
    + "</linearGradient></defs>"
    + '<path class="mk-stern-halb" fill="url(#' + gradientId + ')" d="' + STERN_PFAD + '"/></svg>';
}

export function fuenfSterneHtml(gesamt, schluessel) {
  var z = sterneZaehlung(gesamt);
  var safe = String(schluessel || "x").replace(/[^A-Za-z0-9_-]/g, "-");
  var html = "";
  var i;
  for (i = 0; i < z.voll; i++) html += sternSvgHtml(100);
  for (i = 0; i < z.halb; i++) html += sternSvgHtml(50, "mk-grad-" + safe + "-" + i);
  for (i = 0; i < z.leer; i++) html += sternSvgHtml(0);
  return html;
}

// Legacy-Chip (Entscheid 2026-08-30 C): `nachfolger` (katalog_sicht.py) ersetzt die
// Sterne-Spalte durch einen neutralen Chip statt einer erfundenen Bewertung fuer eine Version,
// die keine eigenen Sterne mehr traegt -- bewusst Englisch ("Legacy"), gleiche Zellenbreite wie
// die Sterne (dieselbe "mk-sterne"-Klasse traegt die Breite/den Abstand).
export function legacyChipHtml(nachfolgerId) {
  return '<span class="mk-sterne mk-legacy-chip" title="Nachfolger: ' + escapeHtml(nachfolgerId) + '">Legacy</span>';
}

// Latest-Chip (Entscheid 2026-08-30 Nachtrag 6): aktuelle Version OHNE berechenbaren Score
// (weder aa_index noch coding_index bekannt) -- dezenter Info-Chip statt erfundener Sterne,
// gleiche Zelle/Breite wie Sterne/Legacy (`.mk-latest-chip`, Hausfarbe abgetont, s. style.css).
export function latestChipHtml() {
  return '<span class="mk-sterne mk-latest-chip" title="Aktuell, noch keine Bewertung (AA-Index fehlt)">Latest</span>';
}

// Maintainer 2026-08-30 (Status-Zone unten, revidiert die Drittel-/Zweispuren-Regel vom selben Tag):
// die Zelle traegt GENAU EINEN Zustand unten rechts -- Legacy-Chip ODER Sterne (bewertet)
// ODER Latest-Chip. Oben steht nur der Name ueber die volle Breite (Sterne oben kollidierten
// mit langen Modellnamen). Wird vom Modellkatalog UND der Preistabelle genutzt (eine Logik).
export function statusZoneHtml(m) {
  if (m.status === "legacy") return legacyChipHtml(m.nachfolger);
  if (m.status === "bewertet") return sterneHtmlNur(m);
  if (m.status === "latest") return latestChipHtml();
  return "";
}

function sterneHtmlNur(m) {
  return '<span class="mk-sterne" role="img" aria-label="' + escapeHtml(gesamtSterneText(m.sterne))
    + '" title="' + escapeHtml(sterneTooltipText(m)) + '">'
    + fuenfSterneHtml((m.sterne || {}).gesamt, m.id) + "</span>";
}

// Tooltip: Score, AA-/Coding-Index, Bild-Faehigkeit (Entscheid 2026-08-30 Nachtrag 6 --
// ersetzt die Intelligenz/Coding/Kontext-Aufschluesselung aus Nachtrag 2, kein Kontext-Bonus
// mehr in der Formel). `m` ist der GANZE Modelleintrag (nicht nur `sterne`), weil `aa_index`/
// `coding_index`/`vision` top-level am Modell stehen.
export function sterneTooltipText(m) {
  var mod = m || {};
  var s = mod.sterne || {};
  var bild = mod.vision === true ? "ja" : mod.vision === false ? "nein" : "unbekannt";
  var text = ["Score " + (s.score != null ? Number(s.score).toFixed(1).replace(".", ",") : "–"),
              "AA " + (mod.aa_index != null ? mod.aa_index : "–"),
              "Coding " + (mod.coding_index != null ? mod.coding_index : "–"),
              "Bild " + bild].join(" · ");
  var manuell = s.manuell;
  if (manuell && (manuell.coding != null || manuell.reasoning != null || manuell.gesamt != null)) {
    var teile = [];
    if (manuell.coding != null) teile.push("Coding " + "⭐".repeat(Math.max(0, manuell.coding)));
    if (manuell.reasoning != null) teile.push("Reasoning " + "⭐".repeat(Math.max(0, manuell.reasoning)));
    if (manuell.gesamt != null) teile.push("Gesamt " + "⭐".repeat(Math.max(0, manuell.gesamt)));
    text += " — eigener Test: " + teile.join(" | ") + (manuell.kommentar ? " (" + manuell.kommentar + ")" : "");
  }
  return text;
}

var SORT_WERT = {
  id: function (m) { return m.id.toLowerCase(); },
  herkunft: function (m) { return m.herkunft || ""; },
  anbieter: function (m) { return m.anbieter.map(function (a) { return a.name; }).sort().join(","); },
  kontext_k: function (m) { return m.kontext_k; },
  eingabe_usd: function (m) { return m.preis_min.eingabe_usd; },
  ausgabe_usd: function (m) { return m.preis_min.ausgabe_usd; },
  aa_index: function (m) { return m.aa_index; },
  coding_index: function (m) { return m.coding_index; },
  stand: function (m) { return m.stand_juengster || ""; },
  // C15 v2 Punkt 1/3: Zusatzfelder aus der Artificial-Analysis-Anreicherung, NULL-faehig wie
  // aa_index/coding_index oben -- gleiche Nulls-ans-Ende-Behandlung unten in sortiereModelle.
  agentic_index: function (m) { return m.agentic_index; },
  tempo_tok_s: function (m) { return m.tempo_tok_s; },
  preisleistung: preisLeistungKennzahl,
};
// Fehlende Werte (NULL-faehige Spalten) landen immer am Ende, unabhaengig von der Richtung --
// gleiche Erwartung wie die uebrigen Tabellen dieses Dashboards (tabellen.js:holeSortWert).
export function sortiereModelle(modelle, spalte, richtung) {
  var hole = SORT_WERT[spalte] || SORT_WERT.id;
  var kopie = (modelle || []).slice();
  kopie.sort(function (a, b) {
    var va = hole(a), vb = hole(b);
    var aFehlt = va === null || va === undefined, bFehlt = vb === null || vb === undefined;
    if (aFehlt && bFehlt) return 0;
    if (aFehlt) return 1;
    if (bFehlt) return -1;
    if (typeof va === "string") return richtung * va.localeCompare(vb, "de");
    return richtung * (va - vb);
  });
  return kopie;
}

// "artificial_analysis" ist KEIN Bezugsweg-Anbieter, sondern die Attributionspflicht der AA-
// Indexanreicherung (CONTRACTS.md C15 v2 Punkt 1) -- eigener Schluessel im `stand`-Block, laeuft
// darum NICHT ueber die generische Anbieter-Stand-Liste, sondern haengt als eigener Satzteil an.
var AA_STAND_SCHLUESSEL = "artificial_analysis";
export function kartenZaehlerText(alleModelle, standJeAnbieter) {
  if (!alleModelle || !alleModelle.length) return "0 Modelle -- noch nicht befuellt (katalog-update ausfuehren)";
  var anbieterSet = {};
  alleModelle.forEach(function (m) { m.anbieter.forEach(function (a) { anbieterSet[a.name] = true; }); });
  var stand = standJeAnbieter || {};
  var standTeile = Object.keys(stand).filter(function (k) { return k !== AA_STAND_SCHLUESSEL && stand[k]; }).sort()
    .map(function (k) { return quelleAnzeigeName(k) + " " + standDatumText(stand[k]); });
  var text = alleModelle.length + " Modelle · " + Object.keys(anbieterSet).length + " Anbieter"
    + (standTeile.length ? " · Stand " + standTeile.join(" · ") : "");
  if (stand[AA_STAND_SCHLUESSEL]) text += " · Indizes Artificial Analysis " + standDatumText(stand[AA_STAND_SCHLUESSEL]);
  return text;
}

// persona_wege-Normalisierung: modelle.json liefert je Persona eine FLACHE Liste
// [{quelle, modell, primaer}] (Backend-Stand 24b8df9); aeltere Entwuerfe ein Objekt
// {rolle, wege: [...]}. Beide Formen lesbar; Rollen-Beschriftung kommt aus der Karte.
var PERSONA_ROLLEN = { vico: "Consulting", vica: "Academy", cura: "Administration" };
export function personaWegeListe(eintrag) {
  if (Array.isArray(eintrag)) return eintrag;
  return (eintrag && eintrag.wege) || [];
}

// modell_id -> ["VICO primär (Claude)", ...] aus persona_wege (C15-Zusatzfeld) -- markiert die
// Tabellenzeile als Standardmodell (Mockup: .zeile-standard, 📌-Marker + Tooltip auf der Zeile).
// C15 v2 Punkt 5: `weg.ebene` ("offen"|"geschuetzt", fehlend = offen) haengt bei Bedarf klein an
// (z. B. "CURA (geschuetzt) primär") -- ersetzt das aeltere freie `weg.gruppe`-Textfeld.
export function standardHinweiseJeModell(personaWege) {
  var karten = {};
  Object.keys(personaWege || {}).forEach(function (key) {
    var wege = personaWegeListe(personaWege[key]);
    wege.forEach(function (weg) {
      if (!weg.primaer) return;
      var ebenenteil = weg.ebene ? " (" + weg.ebene + ")" : "";
      (karten[weg.modell] = karten[weg.modell] || []).push(
        key.toUpperCase() + ebenenteil + " primär (" + quelleAnzeigeName(weg.quelle) + ")");
    });
  });
  return karten;
}

// CURA-Karte (C15 v2 Punkt 5): Wege nach `ebene` gruppieren. Nur wenn mindestens EIN Weg
// "geschuetzt" ist, entstehen zwei Gruppen mit Titeln "Offen"/"Nur lokal" (Mockup-Wortlaut) --
// Karten ohne geschuetzten Weg (VICO/VICA) liefern weiterhin EINE Gruppe ohne Titel, damit sich
// an deren Optik nichts aendert.
export function gruppiereWegeNachEbene(wege) {
  var liste = wege || [];
  if (!liste.some(function (w) { return w.ebene === "geschuetzt"; })) return [{ titel: null, wege: liste }];
  var offen = liste.filter(function (w) { return w.ebene !== "geschuetzt"; });
  var geschuetzt = liste.filter(function (w) { return w.ebene === "geschuetzt"; });
  var gruppen = [];
  if (offen.length) gruppen.push({ titel: "Offen", wege: offen });
  if (geschuetzt.length) gruppen.push({ titel: "Nur On-Premise", wege: geschuetzt });
  return gruppen;
}

// ================= HTML-Bausteine (DOM-nah, nicht Node-getestet) =================

function herkunftZelleHtml(code) {
  if (!code) return '<td class="herkunft-zelle">—</td>';
  return '<td class="herkunft-zelle" title="' + escapeHtml(code) + '">' + herkunftFlaggeHtml(code) + "</td>";
}

function aaZelleHtml(zahl) {
  if (zahl === null || zahl === undefined) return "<td><span class=\"caption\">—</span></td>";
  var breite = Math.max(0, Math.min(100, zahl));
  return "<td><div class=\"aa-zelle\"><span class=\"aa-zahl\">" + escapeHtml(zahl)
    + '</span><span class="aa-bar"><span style="width:' + breite + '%"></span></span></div></td>';
}

export function modellZeileHtml(m, standardHinweise) {
  var hinweise = standardHinweise[m.id];
  var trAttr = hinweise ? ' class="zeile-standard" title="Standardmodell: ' + escapeHtml(hinweise.join("; ")) + '"' : "";
  // Nachtrag Ollama-live: Ollama-Chip zeigt lokal/cloud als Tooltip (m.lokal aus katalog_sicht,
  // C15 v2 Punkt 3) -- keine neue Spalte, minimale Sichtbarkeit fuer die vorhandene Unterscheidung.
  var anbieterChips = m.anbieter.map(function (a) {
    var titel = a.name === "ollama" && typeof m.lokal === "boolean" ? (m.lokal ? ON_PREM_TOOLTIP : "cloud") : null;
    return quelleChipHtml(quelleAnzeigeName(a.name), titel);
  }).join("");
  var eingabeTooltip = tooltipPreise(m.anbieter, "eingabe_usd");
  var ausgabeTooltip = tooltipPreise(m.anbieter, "ausgabe_usd");
  // Zelle zweizeilig (Maintainer 2026-08-30, Status-Zone unten -- revidiert die Regel vom selben
  // Tag): Zeile 1 = Modellname ueber die VOLLE Breite (keine rechte Nebenspur, Sterne oben
  // kollidierten mit langem Namen); Zeile 2 = Hersteller links + EINE Status-Zone rechts
  // (Legacy-Chip ODER Sterne ODER Latest-Chip, s. statusZoneHtml).
  return "<tr" + trAttr + ">"
    + '<td><div class="modell-zelle mz2">'
    + '<span class="mz-top"><span class="name mono">' + modellNameHtml(m.id) + "</span></span>"
    + '<span class="hersteller">' + escapeHtml(m.hersteller || "—") + "</span>"
    + '<div class="mz-chip">' + statusZoneHtml(m) + "</div>"
    + "</div></td>"
    + herkunftZelleHtml(m.herkunft)
    + '<td><div class="wege-zellen">' + anbieterChips + "</div></td>"
    + '<td class="num">' + (m.kontext_k ?? "—") + "</td>"
    + '<td class="num"' + (eingabeTooltip ? ' title="' + escapeHtml(eingabeTooltip) + '"' : "") + ">"
    + formatPreisZahl(m.preis_min.eingabe_usd) + "</td>"
    + '<td class="num preis-guenstig"' + (ausgabeTooltip ? ' title="' + escapeHtml(ausgabeTooltip) + '"' : "") + ">"
    + formatPreisZahl(m.preis_min.ausgabe_usd) + "</td>"
    + aaZelleHtml(m.aa_index) + aaZelleHtml(m.coding_index)
    + '<td><div class="stand-zelle"><span class="stand-datum">' + standDatumText(m.stand_juengster) + "</span></div></td>"
    + "</tr>";
}

// Gleiche Verkuerzung wie die Katalogtabelle (Maintainer 2026-08-28: "nvidia/" und "sference/" in den
// Kacheln abgeschnitten statt gekuerzt): Teil nach dem letzten Schraegstrich, @Region- und
// :flex/:batch/:free-Zusaetze weg -- Ollama-Tags wie :cloud bleiben (eigene Modellvariante).
export function kurzeWegId(modellId) {
  var kern = String(modellId).split("/").pop().split("@")[0];
  return kern.replace(/:(flex|batch|free)$/i, "");
}

// Panel-Vereinheitlichung mit der Katalogtabelle (Entscheid 2026-08-30 D, entschlackt per
// Abnahme 2026-08-30 Fix 2): Name UND Lokal/Cloud-Tooltip auf dem Quelle-Chip kommen aus
// DEMSELBEN Katalog-Eintrag wie die Tabellenzeile -- Nachschlag ueber
// `katalogEintragFuerAnzeige()` (gleiche `daten.modelle`-Liste, s. `ladeModellkatalog`). Keine
// Herkunft-Flagge, kein HF-Abzeichen, kein Pin-Symbol mehr im Panel (nur Anzeigename, Chip,
// gruener Erreichbarkeits-Punkt) -- Kein Treffer (Modell noch nicht im Katalog-Bestand) laesst
// den Chip wie bisher ohne Zusatz, kein Fehler.
export function personaWegZeileHtml(weg) {
  var eintrag = katalogEintragFuerAnzeige(weg.modell);
  var chipTitel = weg.quelle === "ollama" && eintrag && typeof eintrag.lokal === "boolean"
    ? (eintrag.lokal ? ON_PREM_TOOLTIP : "cloud") : null;
  return '<div class="persona-weg' + (weg.primaer ? " primaer" : "") + '">'
    + quelleChipHtml(quelleAnzeigeName(weg.quelle), chipTitel)
    + '<span class="erreichbar-punkt" title="Erreichbar"></span>'
    + modellNameHtml(weg.modell, "modell", false, true) + "</div>";
}

function personaKoerperHtml(wege) {
  if (!wege || !wege.length) return '<p class="caption">Noch kein Weg hinterlegt.</p>';
  return gruppiereWegeNachEbene(wege).map(function (gruppe) {
    var titel = gruppe.titel ? '<p class="persona-unterteil-titel">' + escapeHtml(gruppe.titel) + "</p>" : "";
    return titel + gruppe.wege.map(personaWegZeileHtml).join("");
  }).join("");
}

function personaKarteHtml(key, eintrag) {
  return '<div class="persona-karte"><div class="persona-kopf persona-kopf--marke">'
    + '<svg class="mini-orb mini-orb--' + key + ' mini-orb-44" viewBox="0 0 16 16" aria-hidden="true"><use href="#orb-mesh"></use></svg>'
    + '<span class="persona-kopf-titel persona-kopf-titel--' + key + '">' + key.toUpperCase() + "</span>"
    + '<span class="persona-kopf-rolle">' + escapeHtml((eintrag && eintrag.rolle) || PERSONA_ROLLEN[key] || "") + "</span></div>"
    + '<div class="persona-koerper">' + personaKoerperHtml(personaWegeListe(eintrag)) + "</div></div>";
}

// Zeilen-Renderer der LOKAL-Karte -- pure Funktion (kein DOM-Zugriff), darum exportiert und in
// tests/test_katalog.mjs Node-testbar. C15 v2 Punkt 5: `cura_primaer` ist der neue API-Feldname
// fuer die hervorgehobene Zeile, `primaer` bleibt als Fallback lesbar (aelterer Backend-Stand);
// der Zusatztext "CURA geschützt primär" wird ergaenzt, falls das Backend ihn noch nicht in
// `kommentar` mitliefert (kein doppelter Text, wenn er schon enthalten ist). Kein Pin-Symbol mehr
// (Abnahme 2026-08-30 Fix 2) -- die Hervorhebung ist reine Farb-/Fett-Optik per CSS `.primaer`.
var CURA_PRIMAER_ZUSATZ = "CURA geschützt primär";
// Kurzes Fach-Tag darf unter der Zeile stehen (Entscheid 2026-08-30 Nachtrag 6, Punkt 4):
// hoechstens 3 Woerter (z. B. "Embedding", "Übersetzungs-Spezialist") -- ein laengerer Kommentar
// aus modelle.json wuerde einen zweiten Umbruch erzwingen und bleibt darum NUR im Tooltip.
var FACHTAG_WORTGRENZE = 3;
function istKurzesFachTag(text) {
  return Boolean(text) && text.trim().split(/\s+/).length <= FACHTAG_WORTGRENZE;
}

// Keine Sterne mehr im Panel (Entscheid 2026-08-30 D: "Keine Sterne in den Panels", Platzgrund)
// -- Kommentar + Primaer-Zusatz bleiben, jetzt mit demselben gruenen Erreichbarkeits-Punkt wie die
// Persona-Kacheln (Entscheid 2026-08-30 Nachtrag 6, Punkt 4) und dem reinen Einzeiler-Namen
// (`nurModellname=true` -- hf.co-IDs zeigen NUR `<Modell>`, Org+Quant bleiben im Tooltip, anders
// als die Katalog-TABELLE). Name kommt aus der gemeinsamen `modellNameHtml()` (format.js), ohne
// HF-Abzeichen (`mitBadge=false`, Abnahme 2026-08-30 Fix 2: nur der Einzeiler-Name im Panel).
export function lokalZeileHtml(e) {
  var istPrimaer = Boolean(e.cura_primaer || e.primaer);
  var kommentar = e.kommentar || "";
  var fachtag = istKurzesFachTag(kommentar) ? kommentar : "";
  var teile = [fachtag].filter(Boolean);
  if (istPrimaer && teile.join(" · ").indexOf(CURA_PRIMAER_ZUSATZ) === -1) teile.push(CURA_PRIMAER_ZUSATZ);
  var nebentext = teile.join(" · ");
  // Laengerer Kommentar (kein kurzes Fach-Tag) landet als Tooltip auf der Zeile statt angezeigt
  // zu werden -- "Tooltip ok" (Task-Vorgabe), kein zweiter Umbruch im sichtbaren Text.
  var zeileTitel = kommentar && !fachtag ? ' title="' + escapeHtml(kommentar) + '"' : "";
  return "<li" + (istPrimaer ? ' class="primaer"' : "") + zeileTitel + ">"
    + '<span class="modellname">'
    + '<span class="erreichbar-punkt" title="Erreichbar"></span>'
    + modellNameHtml(e.modellname, null, false, true) + "</span>"
    + (nebentext ? '<span class="sterne">' + escapeHtml(nebentext) + "</span>" : "") + "</li>";
}

function lokalKarteHtml(liste) {
  var zeilen = (liste || []).map(lokalZeileHtml).join("") || '<li class="caption">Kein lokales Modell hinterlegt.</li>';
  return '<div class="persona-karte"><div class="persona-kopf persona-kopf--lokal"><div class="persona-kopf-zeile">'
    + '<span class="lokal-titel-gruppe">' + LOKAL_ICON_SVG + '<span class="persona-kopf-titel">ON-PREMISE</span></span>'
    + '</div></div><div class="persona-koerper"><ul class="lokal-liste">' + zeilen + "</ul></div></div>";
}

// ================= Zustand + DOM-Verkabelung =================

var katalogState = {
  alle: [], standJeAnbieter: {}, standardHinweise: {}, suchtext: "",
  herkunftAktiv: null, anbieterAktiv: new Set(["claude", "ollama", "openrouter", "requesty"]),
  nurLokal: false, euOhneTraining: false, nurLatest: false, katalogNachName: {},
  personaWegeRoh: {},
  sortSpalte: "id", sortRichtung: 1,
};

// Auftrag 2026-08-30 Nachtrag (Preistabelle im Katalog-Look): die Preistabelle im selben
// Abschnitt liest den geladenen Katalog als Snapshot (Kontext/Herkunft/Persona-Pins), statt
// /api/modellkatalog doppelt zu holen. Nach jedem Laden feuert "katalog:geladen", damit sie
// sich neu rendert (Frontend-Zwischenstand; Backend-Projection folgt, Plan
// docs/plans/preistabelle-master-sicht-plan.md).
export function katalogSnapshot() {
  return { alle: katalogState.alle, personaWege: katalogState.personaWegeRoh };
}

function markiereSortPfeile() {
  var gitter = document.getElementById("modellkatalog-gitter");
  if (!gitter) return;
  gitter.querySelectorAll(".th-sort").forEach(function (knopf) {
    var th = knopf.closest("th"), pfeil = knopf.querySelector(".sort-arrow");
    if (knopf.getAttribute("data-col") === katalogState.sortSpalte) {
      th.setAttribute("aria-sort", katalogState.sortRichtung === 1 ? "ascending" : "descending");
      pfeil.textContent = katalogState.sortRichtung === 1 ? "▲" : "▼";
    } else {
      th.setAttribute("aria-sort", "none");
      pfeil.textContent = "";
    }
  });
}

function renderTabelle() {
  var body = document.getElementById("modellkatalog-body");
  var zaehler = document.getElementById("modellkatalog-zaehler");
  if (zaehler) zaehler.textContent = kartenZaehlerText(katalogState.alle, katalogState.standJeAnbieter);
  if (!body) return;
  if (!katalogState.alle.length) {
    setFilterZaehler(0, 0);
    body.innerHTML = '<tr><td colspan="9" class="ladehinweis">Der Modellkatalog wurde noch nicht befüllt -- '
      + '<code class="mono">katalog-update</code> ausführen.</td></tr>';
    return;
  }
  var gefiltert = sortiereModelle(filtereModelle(katalogState.alle, katalogState), katalogState.sortSpalte, katalogState.sortRichtung);
  setFilterZaehler(gefiltert.length, katalogState.alle.length);
  if (!gefiltert.length) {
    body.innerHTML = '<tr><td colspan="9" class="ladehinweis">Keine Modelle für diese Filter.</td></tr>';
    return;
  }
  body.innerHTML = gefiltert.map(function (m) { return modellZeileHtml(m, katalogState.standardHinweise); }).join("");
  passeKatalogHoeheAn();
}

// Hoehe des Tabellenkoerpers auf GANZE Zeilen bis zur Fensterunterkante (Maintainer 2026-08-28: die
// Tabelle endete mitten in einer Zeile und lief unter den Viewport -- Vorbild
// tabellen.js:passeTabelleHoeheAn(), hier ohne .start-mitte-Anker: die Einstellungen-Seite
// scrollt als Ganzes, Bezugskante ist die Fensterunterkante bei Scrollstand 0. Die feste
// 46px-Zeilenhoehe (style.css .mk-koerper td) macht die Ganzzeilen-Rechnung erst exakt.
function passeKatalogHoeheAn() {
  var koerper = document.getElementById("modellkatalog-koerper");
  if (!koerper || !koerper.offsetParent) return;
  var zeile = koerper.querySelector("tbody tr");
  if (!zeile) return;
  var zeilenHoehe = zeile.getBoundingClientRect().height;
  if (!zeilenHoehe) return;
  var obenBeiScroll0 = koerper.getBoundingClientRect().top + window.scrollY;
  var verfuegbar = window.innerHeight - obenBeiScroll0 - 25;
  var zeilen = Math.max(5, Math.floor(verfuegbar / zeilenHoehe));
  // Wie passeTabelleHoeheAn() der Startseite: der Ganzzeilen-Rest bleibt INNERHALB der Box
  // (Karte endet buendig mit dem Seitenraster, keine Aussenluecke; intern scrollt es ohnehin).
  var ziel = Math.max(zeilen * zeilenHoehe, verfuegbar) + "px";
  koerper.style.height = ziel;
  koerper.style.maxHeight = ziel;
}

// Treffer-Zaehler unten in der Filter-Seitenleiste ("38 von 214 Modellen" im Mockup).
function setFilterZaehler(anzahl, gesamt) {
  var ziel = document.getElementById("mk-filter-zaehler");
  if (ziel) ziel.textContent = gesamt ? anzahl + " von " + gesamt + " Modellen" : "";
}

function renderHerkunftChips() {
  var container = document.getElementById("mk-herkunft");
  if (!container) return;
  // "" = Modelle ohne Herkunftsangabe -- eigener "?"-Chip wie das "Unbekannt" der Startseite,
  // sonst fielen sie still aus der Standardansicht (Sichtabnahme: "Alle" muss alle zeigen).
  var codes = Array.from(new Set(katalogState.alle.map(function (m) { return m.herkunft || ""; }))).sort();
  // Auswahl-Logik (Maintainer 2026-08-28): Start = leere Auswahl = Vollansicht, kein Chip gedimmt.
  if (katalogState.herkunftAktiv === null) katalogState.herkunftAktiv = new Set();
  container.classList.toggle("auswahl-aktiv", katalogState.herkunftAktiv.size > 0);
  container.innerHTML = codes.map(function (code) {
    var aktiv = katalogState.herkunftAktiv.has(code);
    var titel = code === "" ? "Ohne Herkunftsangabe" : code;
    return '<button type="button" class="herkunft-chip" data-herkunft="' + escapeHtml(code)
      + '" aria-pressed="' + aktiv + '" title="' + escapeHtml(titel) + '">' + (code === "" ? "?" : escapeHtml(code)) + "</button>";
  }).join("");
}

// Nachschlag Panel-Modell -> Katalog-Eintrag (Entscheid 2026-08-30 D), Schluessel ist der
// kanonische Anzeigename (gleiche Kappung wie die Tabelle, s. `modellAnzeigeName`), damit
// "glm-5.2:cloud" (Persona-Weg) denselben Katalog-Eintrag trifft wie die Tabellenzeile "glm-5.2".
function katalogEintragFuerAnzeige(modellId) {
  return katalogState.katalogNachName[modellAnzeigeName(modellId).toLowerCase()] || null;
}

function baueKatalogNachName(alle) {
  var ergebnis = {};
  (alle || []).forEach(function (m) { ergebnis[modellAnzeigeName(m.id).toLowerCase()] = m; });
  return ergebnis;
}

function renderPersonaKacheln(personaWege, lokalListe) {
  var container = document.getElementById("persona-kacheln");
  if (!container) return;
  var karten = PERSONA_REIHENFOLGE.filter(function (key) { return personaWege[key]; })
    .map(function (key) { return personaKarteHtml(key, personaWege[key]); });
  var hinweis = karten.length ? "" : '<p class="caption">Noch keine Standardmodelle hinterlegt (persona_wege fehlt in modelle.json).</p>';
  container.innerHTML = hinweis + karten.join("") + lokalKarteHtml(lokalListe);
}

// Eignung (Artificial Analysis) v2 (CONTRACTS.md C15 v2 Punkt 1/3/6): alle fuenf Mockup-Presets
// plus "Alle" (Bestandssortierung nach id) -- jetzt moeglich, weil katalog_sicht.py agentic_index/
// tempo_tok_s mitliefert und preisleistung sich aus aa_index + preis_min errechnet (s.
// preisLeistungKennzahl oben).
var EIGNUNG_SORT = {
  alle: { spalte: "id", richtung: 1 },
  coding: { spalte: "coding_index", richtung: -1 },
  reasoning: { spalte: "aa_index", richtung: -1 },
  agentic: { spalte: "agentic_index", richtung: -1 },
  preisleistung: { spalte: "preisleistung", richtung: -1 },
  geschwindigkeit: { spalte: "tempo_tok_s", richtung: -1 },
};

function wireEignung() {
  var gruppe = document.getElementById("mk-eignung");
  if (!gruppe) return;
  gruppe.addEventListener("click", function (ev) {
    var knopf = ev.target.closest("button[data-eignung]");
    if (!knopf) return;
    gruppe.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b === knopf)); });
    var sort = EIGNUNG_SORT[knopf.getAttribute("data-eignung")] || EIGNUNG_SORT.alle;
    katalogState.sortSpalte = sort.spalte;
    katalogState.sortRichtung = sort.richtung;
    markiereSortPfeile();
    renderTabelle();
  });
}

function wireHerkunftUndAnbieter() {
  var herkunft = document.getElementById("mk-herkunft");
  if (herkunft) herkunft.addEventListener("click", function (ev) {
    var knopf = ev.target.closest("button[data-herkunft]");
    if (!knopf) return;
    var code = knopf.getAttribute("data-herkunft"), aktiv = knopf.getAttribute("aria-pressed") === "true";
    if (aktiv) katalogState.herkunftAktiv.delete(code); else katalogState.herkunftAktiv.add(code);
    renderHerkunftChips();
    renderTabelle();
  });
  var anbieter = document.getElementById("mk-anbieter");
  if (anbieter) anbieter.addEventListener("change", function (ev) {
    var box = ev.target.closest("input[data-anbieter]");
    if (!box) return;
    if (box.checked) katalogState.anbieterAktiv.add(box.getAttribute("data-anbieter"));
    else katalogState.anbieterAktiv.delete(box.getAttribute("data-anbieter"));
    renderTabelle();
  });
}

// Drei neutrale Zusatzfilter (C15 v2 Punkt 3/6 + Auftrag 2026-08-30 "nur Latest") --
// Checkbox-IDs bewusst mit Bindestrich ("nur-lokal"/"eu-ohne-training"/"nur-latest"), s. Kommentar
// an der Markup-Stelle in index.html.
function wireZusatzFilter() {
  var nurLokal = document.getElementById("mk-nur-lokal");
  if (nurLokal) nurLokal.addEventListener("change", function () { katalogState.nurLokal = nurLokal.checked; renderTabelle(); });
  var euOhneTraining = document.getElementById("mk-eu-ohne-training");
  if (euOhneTraining) euOhneTraining.addEventListener("change", function () {
    katalogState.euOhneTraining = euOhneTraining.checked;
    renderTabelle();
  });
  var nurLatest = document.getElementById("mk-nur-latest");
  if (nurLatest) nurLatest.addEventListener("change", function () { katalogState.nurLatest = nurLatest.checked; renderTabelle(); });
}

function wireSuche() {
  var suche = document.getElementById("mk-suche");
  if (suche) suche.addEventListener("input", function () { katalogState.suchtext = suche.value; renderTabelle(); });
}

// Einstellungen-Untermenue (C15 v2 Punkt 6, verschaerft durch Live-Feedback 2026-08-28
// Zwischenstand): EIN Klick ist ein Unterseiten-Wechsel, KEIN scrollIntoView in einer langen
// Liste -- der geklickte Hauptpunkt wird "aktiv" (li-Klasse, uebernimmt Optik + zeigt seinen
// Filter-Block per CSS), alle ".einst-abschnitt"-Bloecke der Mittelspalte werden ausgeblendet
// bis auf den zum Klick gehoerenden. Exportiert, damit initModellkatalog() den Ausgangszustand
// (Modellkatalog aktiv) auch dann garantiert herstellt, wenn ein spaeterer Markup-Stand einmal
// vom HTML-Default abweicht.
export function zeigeEinstAbschnitt(zielId) {
  document.querySelectorAll(".einst-nav > li").forEach(function (li) {
    var link = li.querySelector("a[data-einst-ziel]");
    li.classList.toggle("aktiv", Boolean(link) && link.getAttribute("data-einst-ziel") === zielId);
  });
  document.querySelectorAll(".einst-abschnitt").forEach(function (abschnitt) {
    abschnitt.hidden = abschnitt.id !== zielId;
  });
  if (zielId === "modellkatalog-abschnitt") passeKatalogHoeheAn();
  // Fund 2026-08-30: die Preistabelle mass ihren Koerper bei Verstecktem Abschnitt
  // frueh aus (offsetParent null) und blieb auf dem CSS-Fallback stehen -- das Event
  // laesst einstellungen.js nach dem Einblenden die Ganzzeilen-Hoehe nachziehen.
  document.dispatchEvent(new CustomEvent("einst:abschnitt", { detail: zielId }));
}

function wireEinstNav() {
  var nav = document.getElementById("einst-nav");
  if (!nav) return;
  nav.addEventListener("click", function (ev) {
    var link = ev.target.closest("a[data-einst-ziel]");
    if (!link) return;
    ev.preventDefault();
    zeigeEinstAbschnitt(link.getAttribute("data-einst-ziel"));
  });
  zeigeEinstAbschnitt("modellkatalog-abschnitt");
}

function wireTabellenSort() {
  var gitter = document.getElementById("modellkatalog-gitter");
  if (!gitter) return;
  gitter.querySelectorAll(".th-sort").forEach(function (knopf) {
    knopf.addEventListener("click", function () {
      var spalte = knopf.getAttribute("data-col");
      katalogState.sortRichtung = katalogState.sortSpalte === spalte ? katalogState.sortRichtung * -1 : 1;
      katalogState.sortSpalte = spalte;
      markiereSortPfeile();
      renderTabelle();
      // Gleiches Snap-Ruecksnappen wie in start.js sortiereTabelle: nach Sortierung nach oben.
      var koerperEl = document.getElementById("modellkatalog-koerper");
      if (koerperEl) koerperEl.scrollTop = 0;
    });
  });
}

// ---------- "Jetzt aktualisieren" (CONTRACTS.md C15 v2 Punkt 4) ----------
// Muster wie fehlerbilder.js:pollePruefung (POST startet, GET pollt bis das Backend fertig
// meldet) -- hier 3 s Takt statt 1,5 s, weil der Katalog-Lauf mehrere externe APIs abfragt.
var AKTUALISIEREN_POLL_MS = 3000;

function setzeAktualisierenLaeuft(laeuft) {
  // Beide Knoepfe derselben Kette (Maintainer 2026-08-30 Nachtrag): Katalog UND Preistabelle tragen
  // data-aktualisieren-btn und schalten gemeinsam um -- es laeuft ohnehin nur EIN Lauf.
  document.querySelectorAll("[data-aktualisieren-btn]").forEach(function (knopf) {
    knopf.disabled = laeuft;
    knopf.textContent = laeuft ? "Aktualisiert…" : "Jetzt aktualisieren";
  });
}

function zeigeAktualisierenHinweis(text) {
  var hinweis = document.getElementById("mk-aktualisieren-hinweis");
  if (!hinweis) return;
  hinweis.textContent = text || "";
  hinweis.hidden = !text;
}

function pollAktualisierenStatus() {
  holeJSON("/api/modellkatalog/aktualisieren").then(function (status) {
    if (status.status === "laeuft") { setTimeout(pollAktualisierenStatus, AKTUALISIEREN_POLL_MS); return; }
    setzeAktualisierenLaeuft(false);
    if (status.status === "fehler") { zeigeAktualisierenHinweis(status.detail || "Aktualisierung fehlgeschlagen."); return; }
    zeigeAktualisierenHinweis("");
    if (status.status === "fertig") ladeModellkatalog();
  }).catch(function (fehler) {
    setzeAktualisierenLaeuft(false);
    zeigeAktualisierenHinweis(fehler.message);
  });
}

// Exportiert (Maintainer 2026-08-30 Nachtrag): der Preistabellen-Knopf startet dieselbe Kette --
// ein Lauf aktualisiert beide Sichten (keine doppelte Aktualisierungswelt, Vorgabe).
export function starteAktualisieren() {
  setzeAktualisierenLaeuft(true);
  zeigeAktualisierenHinweis("");
  holeJSON("/api/modellkatalog/aktualisieren", {}, { method: "POST" }).then(function () {
    setTimeout(pollAktualisierenStatus, AKTUALISIEREN_POLL_MS);
  }).catch(function (fehler) {
    setzeAktualisierenLaeuft(false);
    zeigeAktualisierenHinweis(fehler.message);
  });
}

function wireAktualisieren() {
  document.querySelectorAll("[data-aktualisieren-btn]").forEach(function (knopf) {
    knopf.addEventListener("click", starteAktualisieren);
  });
}

// DOM-Verkabelung (von app.js einmalig aufgerufen, wie initEinstellungen).
export function initModellkatalog() {
  wireSuche();
  wireEignung();
  wireHerkunftUndAnbieter();
  wireZusatzFilter();
  wireTabellenSort();
  wireEinstNav();
  wireAktualisieren();
  window.addEventListener("resize", passeKatalogHoeheAn);
}

// Datenladen (von einstellungen.js bei jedem Seitenaufruf aufgerufen, wie die Preistabelle).
export function ladeModellkatalog() {
  holeJSON("/api/modellkatalog").then(function (daten) {
    katalogState.alle = daten.modelle || [];
    katalogState.standJeAnbieter = daten.stand || {};
    katalogState.standardHinweise = standardHinweiseJeModell(daten.persona_wege || {});
    katalogState.katalogNachName = baueKatalogNachName(katalogState.alle);
    katalogState.personaWegeRoh = daten.persona_wege || {};
    katalogState.herkunftAktiv = null;
    renderHerkunftChips();
    renderTabelle();
    renderPersonaKacheln(daten.persona_wege || {}, daten.lokal_liste || []);
    passeKatalogHoeheAn();
    document.dispatchEvent(new CustomEvent("katalog:geladen"));
  }).catch(function (fehler) {
    zeigeFehler("modellkatalog-body", fehler);
    zeigeFehler("persona-kacheln", fehler);
  });
  // Reload-Fall: ein vorheriger "Jetzt aktualisieren"-Lauf koennte noch laufen -- Endpunkt ist
  // Teil des parallelen Backend-Baus, darum fail-soft (leerer catch) statt eines Fehlerhinweises.
  holeJSON("/api/modellkatalog/aktualisieren").then(function (status) {
    if (status.status === "laeuft") { setzeAktualisierenLaeuft(true); pollAktualisierenStatus(); }
  }).catch(function () {});
}
