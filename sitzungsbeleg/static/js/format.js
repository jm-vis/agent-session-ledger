// Reine Formatierungs-/Darstellungs-Helfer: Datum, Zahlen, Kosten, escapeHtml, Status-Badges.
// Keine DOM-Wirkung (kein getElementById/addEventListener), keine Abhaengigkeiten zu anderen
// Modulen (Fund F: frueher zirkulaerer Import mit zustand.js) -- formatZeitSpalte bekommt die
// Zeitraum-Mehrtaegigkeit jetzt als Parameter statt sie selbst aus `zustand` zu lesen.

export function heute() { var d = new Date(); d.setHours(0, 0, 0, 0); return d; }
export function addTage(d, n) { var r = new Date(d); r.setDate(r.getDate() + n); return r; }
export function zweistellig(n) { return String(n).length < 2 ? "0" + n : String(n); }
export function iso(d) { return d.getFullYear() + "-" + zweistellig(d.getMonth() + 1) + "-" + zweistellig(d.getDate()); }
export function formatDeKurz(d) { return zweistellig(d.getDate()) + "." + zweistellig(d.getMonth() + 1) + "."; }
export function formatDeVoll(d) { return zweistellig(d.getDate()) + "." + zweistellig(d.getMonth() + 1) + "." + d.getFullYear(); }
export function ausIso(text) { var t = text.split("-"); return new Date(Number(t[0]), Number(t[1]) - 1, Number(t[2])); }

// Reine String-Ersetzung statt DOM-Umweg (Fund A): escaped & < > " ' -- sicher sowohl fuer
// Text-Knoten als auch fuer HTML-Attributwerte (Anfuehrungszeichen brachen zuvor das Attribut auf).
var ESCAPE_ZEICHEN = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export function escapeHtml(wert) {
  var text = wert === null || wert === undefined ? "" : String(wert);
  return text.replace(/[&<>"']/g, function (z) { return ESCAPE_ZEICHEN[z]; });
}
export function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
// Quelle-Badge-Optik je Anbieter (Feedback 2026-08-26, Zusatzpunkt 4; OpenRouter ergaenzt
// 2026-08-27, Requesty ergaenzt 2026-08-28): CSS-Klassensuffix aus der Anzeige-Quelle
// (Claude/Codex/Ollama/OpenRouter/Requesty/Produkt/Unbekannt aus quellen.quelle_fuer) -- Ollama
// bekommt bewusst keinen Modifier (bleibt Schwarz-Weiß, .quelle-chip-Basisfarben).
// `titel` optional (Nachtrag Modellkatalog: Ollama-Chip zeigt lokal/cloud als Tooltip) --
// bestehende Aufrufer ohne zweites Argument bleiben unveraendert.
export function quelleChipHtml(quelle, titel) {
  var name = quelle || "Unbekannt";
  var klasse = {
    Claude: "quelle-claude", Codex: "quelle-codex", OpenRouter: "quelle-openrouter",
    Requesty: "quelle-requesty", Produkt: "quelle-produkt", Unbekannt: "quelle-unbekannt",
  }[name] || "";
  var titelAttr = titel ? ' title="' + escapeHtml(titel) + '"' : "";
  return '<span class="quelle-chip' + (klasse ? " " + klasse : "") + '"' + titelAttr + ">" + escapeHtml(name) + "</span>";
}
// ---------- Modellname-Kurzform + Herkunft-Flagge (Entscheid 2026-08-30 D) ----------
// EINE Regel fuer Tabelle UND Panels (Persona-Kacheln, Lokal-Panel, katalog.js) -- kanonischer
// Anzeigename ohne :cloud/-cloud/:latest (reine Bezugsvarianten, keine Modellunterscheidung).
// hf.co-IDs (Ollama-Registry-Konvention `hf.co/<org>/<modell>-GGUF:<quant>`) sind die Ausnahme:
// der letzte Schraegstrich-Teil wuerde die Organisation verlieren, darum eigene Kurzform
// "<modell> · <quant> · <org>" VOR der generischen Kappung (katalog.py:anzeige_kurzform() haelt
// dafuer den vollen hf.co-Pfad in der API-`id` bereit, statt wie sonst nur den letzten Teil).
var HF_CO_RE = /^hf\.co\/([^/]+)\/(.+)-GGUF:(.+)$/i;
var CLOUD_ODER_LATEST_RE = /(:cloud|-cloud|:latest)$/i;

export function hfCoTeile(modellId) {
  var treffer = HF_CO_RE.exec(String(modellId || "").trim());
  return treffer ? { org: treffer[1], modell: treffer[2], quant: treffer[3] } : null;
}

// `nurModellname` (Entscheid 2026-08-30 Nachtrag 6, Punkt 4): Persona-/LOKAL-Panels zeigen bei
// hf.co-IDs NUR den Modellnamen (kein Org/Quant-Zusatz, "reiner Modellname als Einzeiler") --
// Org+Quant bleiben im Tooltip (volle Roh-ID, `modellNameHtml`) UND in der Katalog-TABELLE
// sichtbar (Quant unterscheidet Modelle dort, Default-Aufruf ohne den Parameter unveraendert).
export function modellAnzeigeName(modellId, nurModellname) {
  var hf = hfCoTeile(modellId);
  if (hf) return nurModellname ? hf.modell : hf.modell + " · " + hf.quant + " · " + hf.org;
  var kern = String(modellId || "").split("/").pop().split("@")[0];
  return kern.replace(/:(flex|batch|free)$/i, "").replace(CLOUD_ODER_LATEST_RE, "");
}

// HTML-Baustein fuer den Modellnamen -- `klasse` optional (Aufrufer setzt z. B. "name mono",
// "modell", "modellname" je nach Stelle), Tooltip zeigt immer die volle Roh-ID. hf.co-Treffer
// bekommen zusaetzlich das Kennzeichen "HF-Quelle, lokal gespeichert" (Task-Vorgabe) -- AUSSER
// `mitBadge===false` (Abnahme 2026-08-30 Fix 2: Persona-/LOKAL-Panels zeigen keine Abzeichen
// mehr, nur den Einzeiler-Namen + Tooltip; die Tabelle ruft ohne dritten Parameter unveraendert
// mit Badge). `nurModellname` (Entscheid 2026-08-30 Nachtrag 6) reicht an `modellAnzeigeName`
// durch -- Panels rufen mit `true`, die Tabelle ruft unveraendert ohne vierten Parameter.
export function modellNameHtml(modellId, klasse, mitBadge, nurModellname) {
  var hf = hfCoTeile(modellId);
  var klasseAttr = klasse ? ' class="' + klasse + '"' : "";
  var badge = hf && mitBadge !== false ? ' <span class="hf-quelle" title="🤗 HF-Quelle, lokal gespeichert">🤗</span>' : "";
  return '<span' + klasseAttr + ' title="' + escapeHtml(String(modellId || "")) + '">'
    + escapeHtml(modellAnzeigeName(modellId, nurModellname)) + "</span>" + badge;
}

// Herkunft-Flagge (verschoben aus katalog.js, C15 v2 Punkt 6 + Panel-Vereinheitlichung D):
// Tabelle UND Panels teilen sich dasselbe Markup, nur die umgebende Zelle unterscheidet sich
// (katalog.js:herkunftZelleHtml wrappt in <td>, Panels haengen es inline an).
var FLAGGEN_SYMBOL = { US: "fl-us", CN: "fl-cn", EU: "fl-eu", CA: "fl-ca", IL: "fl-il", JP: "fl-jp", KR: "fl-kr" };
export function herkunftFlaggeHtml(code) {
  if (!code) return "";
  var symbol = FLAGGEN_SYMBOL[code.toUpperCase()];
  return symbol
    ? '<svg class="flagge-svg" width="18" height="12" viewBox="0 0 18 12" aria-hidden="true"><use href="#' + symbol + '"></use></svg>'
    : '<span class="herkunft-fallback mono">' + escapeHtml(code) + "</span>";
}

// Achse Umgebung (C12, Maintainer 2026-08-28 12:45): Kuerzel-Chip rechts vom Projektnamen NUR bei
// Abweichung -- 'entwicklung' (Default) und jeder unbekannte/fehlende Wert zeigen bewusst
// nichts (Maintainer: "keine neue Spalte, alles gestaucht genug").
export function umgebungChipHtml(umgebung) {
  var kuerzel = { abnahme: "Abn.", betrieb: "Betrieb" }[umgebung];
  if (!kuerzel) return "";
  return ' <span class="umgebung-chip umgebung-' + umgebung + '">' + kuerzel + "</span>";
}
// Reine Funktion (Node-testbar, tests/test_umgebung.mjs): der Seitenleisten-Block "Umgebung"
// erscheint nur, wenn im Zeitraum mindestens zwei unterschiedliche Werte vorkommen (C12) --
// Werte mit anzahl=0 zaehlen nicht mit.
export function umgebungBlockSichtbar(umgebungen) {
  return (umgebungen || []).filter(function (u) { return u.anzahl > 0; }).length >= 2;
}
// C14 P1 (Entscheid: Orb + Name; "· Orb" nur bei Cloud-/Bruecken-Sitzungen): Persona-Zelle der
// Sitzungstabelle -- Mini-Orb (svg use auf #orb-mesh, index.html) + Anzeigename in Grossschreibung,
// optionaler gedaempfter Kanal-Zusatz. Unbekannte/fehlende Persona faellt auf "vico" zurueck (das
// Backend liefert das Feld erst schrittweise, s. CONTRACTS.md). Reine Funktion (Node-testbar,
// tests/test_persona.mjs).
export function personaZelleHtml(persona, kanal) {
  var p = ["vico", "vica", "cura"].indexOf(persona) !== -1 ? persona : "vico";
  var name = p.toUpperCase();
  var kanalTeil = kanal === "orb" ? '<span class="kanal">· Orb</span>' : "";
  return '<div class="persona-zelle"><svg class="mini-orb mini-orb--' + p + '" viewBox="0 0 16 16" aria-hidden="true"><use href="#orb-mesh"></use></svg><span class="name">' + name + '</span>' + kanalTeil + '</div>';
}
// Fehlerbild = Werkzeug + Fehlerart + Signatur-Hash (Kurzform fuers Label, Umbau 2026-08-26).
export function kurzHash(sig) { return sig ? sig.slice(0, 4) + "…" : ""; }
export function fehlerbildLabel(z) {
  return (z.werkzeug || "—") + " · " + (z.fehlerklasse || "—") + " (" + kurzHash(z.signatur) + ")";
}

export function formatK(n) {
  if (n === null || n === undefined) return "—";
  var abs = Math.abs(n);
  if (abs >= 1e6) return (n / 1e6).toFixed(1).replace(".0", "").replace(".", ",") + "M";
  if (abs >= 1e3) return Math.round(n / 1e3) + "k";
  return String(n);
}
export function formatEuro(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toFixed(2).replace(".", ",");
}
// Ollama-Sitzungen haben keine API-Kosten (Abo-Nutzung, kein preise-Eintrag in modelle.json)
// -- "Abo" statt "—" macht den Unterschied zu "nicht erfasst" sichtbar (Entscheid 2026-08-26).
export function formatKosten(n, quelleAnzeige) {
  if (n !== null && n !== undefined) return formatEuro(n);
  return quelleAnzeige === "Ollama" ? "Abo" : "—";
}
export function formatDauerKurz(ms) {
  if (ms === null || ms === undefined) return "—";
  var min = Math.round(ms / 60000);
  var h = Math.floor(min / 60), m = min % 60;
  return h > 0 ? h + "h" + zweistellig(m) : m + "m";
}
export function formatDauerLang(ms) {
  if (ms === null || ms === undefined) return "—";
  var s = Math.floor(ms / 1000);
  if (s < 60) return s + " s";
  if (s < 3600) return Math.floor(s / 60) + " min " + (s % 60) + " s";
  return Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " min";
}
export function formatUhrzeit(isoStr) {
  var d = new Date(isoStr);
  return isNaN(d) ? "—" : zweistellig(d.getHours()) + ":" + zweistellig(d.getMinutes());
}
export function formatZeitpunktLang(isoStr) {
  var d = new Date(isoStr);
  if (!isoStr || isNaN(d)) return "—";
  return formatDeVoll(d) + " " + zweistellig(d.getHours()) + ":" + zweistellig(d.getMinutes());
}
// Sitzungsliste: Datum-Präfix nur bei Mehrtages-Zeitraum, sonst reine Uhrzeit wie im Mockup.
// `von`/`bis` als Parameter statt aus `zustand` gelesen (Fund F: kein Import aus zustand.js mehr).
export function formatZeitSpalte(isoStr, von, bis) {
  var d = new Date(isoStr);
  if (isNaN(d)) return "—";
  var mehrtaegig = von && bis && iso(von) !== iso(bis);
  return mehrtaegig ? formatDeKurz(d) + " " + formatUhrzeit(isoStr) : formatUhrzeit(isoStr);
}

export function formatEntscheidDatum(isoStr) {
  var d = new Date(isoStr);
  return isNaN(d) ? "" : formatDeVoll(d);
}

// Status-Badge (offen/erledigt/obsolet/rueckfall) -- gemeinsam fürs Fehler-Panel (start.js) und
// die Befund-Karten der Sitzungsseite (sitzung.js), darum hier zentral (Entscheid 2026-08-26,
// Rückfall-Erkennung + Auftrag 2).
export function statusBadgeText(z) {
  if (z.status !== "rueckfall") return z.status;
  return "Rückfall · " + z.rueckfall_treffer + " neue Treffer seit " + formatEntscheidDatum(z.entschieden_am);
}
export function statusBadgeKlasseAllgemein(status) {
  if (status === "rueckfall") return "st-fehler";
  if (status === "erledigt" || status === "obsolet") return "st-erfolg";
  return "st-warnung";
}
export function statusBadgeHtml(z) {
  return '<span class="status-pille ' + statusBadgeKlasseAllgemein(z.status) + '">'
    + escapeHtml(statusBadgeText(z)) + "</span>";
}

// kzKachel: Kennzahl-Kachel-Baustein, gemeinsam fuer sitzung.js (renderKennzahlen) und
// subagent.js (renderSubagentDetail).
export function kzKachel(zahl, label, text, neben) {
  return '<div class="kz-kachel"><span class="kz-zahl' + (text ? " text" : "") + '">' + escapeHtml(zahl) + "</span>"
    + '<span class="kz-label">' + escapeHtml(label) + "</span>"
    + (neben ? '<span class="kz-nebenwert">' + escapeHtml(neben) + "</span>" : "") + "</div>";
}
