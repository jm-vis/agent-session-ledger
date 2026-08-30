// Generische Tabellen-Helfer: Scroll-Regel (feste 10-Zeilen-Schwelle oder dynamisch angepasste
// Hoehe) + Sortier-Wertparser. Reine Funktionen ohne Bindung an eine bestimmte Tabelle --
// start.js (Sitzungen/Fehlerbilder) und sitzung.js (Subagenten) rufen setzeTabelleScrollt je
// eigener Tabelle auf.

// Tabellen-Scroll-Standard (Korrektur 2026-08-26, `schwelle`-Parameter Feedback
// 2026-08-27): die Hoehe kommt normalerweise per CSS aus max-height = 10 * feste Zeilenhoehe
// (.tg-zeile-40/.tg-zeile-48, siehe style.css) -- hier wird nur noch die Klasse .tg-scrollt
// gesetzt/entfernt, die dem Kopf denselben Balken-Gutter reserviert wie dem tatsaechlich
// scrollenden Koerper (sonst verschieben sich die Spalten von Kopf und Koerper zueinander,
// sobald ein Balken auftaucht). `schwelle` ist optional (Default 10) -- die Sitzungstabelle auf
// der Startseite hat ihre Hoehe/Zeilenzahl seit Feedback 2026-08-27 nicht mehr fest, sondern
// per passeTabelleHoeheAn() an die Restflaeche angepasst; ihr Aufrufer reicht die so berechnete
// Zeilenzahl als Schwelle durch, statt hart 10 anzunehmen.
export function setzeTabelleScrollt(gitterId, anzahlZeilen, schwelle) {
  var gitter = document.getElementById(gitterId);
  if (gitter) gitter.classList.toggle("tg-scrollt", anzahlZeilen > (schwelle || 10));
}

// Zeilenhoehe aus der Klasse tg-zeile-NN lesen statt hart zu kodieren (Feedback 2026-08-27) --
// .tg-zeile-40 (Subagenten) bzw. .tg-zeile-48 (Sitzungen/Fehlerbilder), siehe style.css.
function holeZeilenHoehe(koerper) {
  var treffer = Array.prototype.filter.call(koerper.classList, function (c) {
    return /^tg-zeile-\d+$/.test(c);
  })[0];
  return treffer ? parseInt(treffer.slice("tg-zeile-".length), 10) : 48;
}

// Layout-Reste R2 (2026-08-27, 1600/1366px): skalierung.js verkleinert die Wurzel per CSS
// `zoom` unter 1880px (C7) -- getBoundingClientRect() liefert dabei bereits VISUELL skalierte
// Pixel, waehrend eine Zuweisung an style.maxHeight/-width als LOGISCHE (Vor-Zoom-)Laenge
// interpretiert und vom Browser ERNEUT skaliert wird. Ohne Ruecktransformation waere die
// zugewiesene Hoehe bei z. B. 1600px (Faktor 0.851) sichtbar kleiner als gemessen -- live
// nachgewiesen (Testseite mit `zoom`, `getBoundingClientRect` nach `style.height = <gemessen>`
// liefert wieder den kleineren, ein zweites Mal skalierten Wert).
function holeZoomFaktor() {
  var z = parseFloat(document.documentElement.style.zoom);
  return z && z > 0 ? z : 1;
}

// Passt die Hoehe eines Tabellenkoerpers dynamisch an die Restflaeche bis zur Unterkante der
// Mittelspalte (.start-mitte/.detail-mitte) an -- IMMER nur ganze Zeilen fuer die Scroll-
// Schwelle (kein abgeschnittener Zeilenrest unten wird als eigene Zeile gezaehlt), mindestens
// `mindestZeilen` (Default 5). Feedback 2026-08-27, Startseite: die Sitzungstabelle soll die
// verfuegbare Hoehe fuellen statt fix 10 Zeilen/480px zu zeigen (siehe #sitzungen-koerper
// style.css). Gemessen wird bei scrollTop=0 des umgebenden .start-scroll/.detail-scroll (sonst
// verschiebt ein bereits gescrolltes Fehler-Panel das Mass) -- danach wird die Scrollposition
// zurueckgesetzt, es handelt sich nur um eine kurze Messung, kein sichtbarer Sprung.
// Rueckgabe = berechnete Zeilenzahl, damit der Aufrufer daraus die .tg-scrollt-Schwelle setzt
// (anders als die feste 10-Zeilen-Schwelle der uebrigen Tabellen).
// height statt nur max-height (Layout-Reste R2, 2026-08-27, live per Test-HTML nachgewiesen):
// max-height ist ein OBERES Limit, erzwingt aber NIE eine Mindesthoehe -- bei weniger Zeilen als
// verfuegbar blieb die Box bei ihrer natuerlichen (kleineren) Inhaltshoehe stehen und die Luecke
// zur Seitenleiste/zum Chat bestand weiter (Kern des Auftrags: "Restraum bleibt INNERHALB des
// Containers, nie als Luecke aussen"). `koerper.style.height` erzwingt die Zielhoehe wirklich;
// max-height bleibt zusaetzlich gesetzt (identischer Wert, ueberschreibt die CSS-Fallback-Grenze
// aus style.css) und greift, wenn tatsaechlich MEHR Zeilen vorhanden sind als Platz ist --
// `.tabelle-koerper { overflow-y: auto }` scrollt dann intern, die Box bleibt exakt so hoch.
// Ausgelagert, sonst reisst passeTabelleHoeheAn() die 20-Zeilen-Funktionsgrenze (Code-Masse-
// Waechter). -1: unterer Rand von .tabelle-gitter (1px) muss ebenfalls in die Mittelspalte
// passen. / holeZoomFaktor(): Rueckrechnung von visuellen (post-Zoom) auf logische Pixel, siehe
// Kommentar an holeZoomFaktor().
function gemesseneVerfuegbareHoehe(koerper, mitte) {
  var scrollBereich = koerper.closest(".start-scroll, .detail-scroll");
  var vorherScrollTop = scrollBereich ? scrollBereich.scrollTop : 0;
  if (scrollBereich) scrollBereich.scrollTop = 0;
  var mitteUnten = mitte.getBoundingClientRect().bottom;
  var koerperOben = koerper.getBoundingClientRect().top;
  if (scrollBereich) scrollBereich.scrollTop = vorherScrollTop;
  return (mitteUnten - koerperOben - 1) / holeZoomFaktor();
}

export function passeTabelleHoeheAn(koerperId, mindestZeilen) {
  var koerper = document.getElementById(koerperId);
  if (!koerper) return 0;
  var mitte = koerper.closest(".start-mitte, .detail-mitte");
  if (!mitte) return 0;
  var zeilenHoehe = holeZeilenHoehe(koerper);
  var verfuegbar = gemesseneVerfuegbareHoehe(koerper, mitte);
  var zeilen = Math.max(mindestZeilen || 5, Math.floor(verfuegbar / zeilenHoehe));
  var zielHoehe = Math.max(zeilen * zeilenHoehe, verfuegbar) + "px";
  koerper.style.height = zielHoehe;
  koerper.style.maxHeight = zielHoehe;
  return zeilen;
}

export function parseDauerText(text) {
  text = text.trim();
  if (text === "—" || text === "") return NaN;
  var hM = text.match(/^(\d+)h(\d+)?$/);
  if (hM) return parseInt(hM[1], 10) * 60 + (hM[2] ? parseInt(hM[2], 10) : 0);
  var mM = text.match(/^(\d+)m$/);
  if (mM) return parseInt(mM[1], 10);
  return NaN;
}
export function parseZahlText(text) {
  text = text.trim();
  if (text === "—" || text === "") return NaN;
  return parseFloat(text.replace(",", "."));
}
export function holeSortWert(tr, spalte, typ, sortSpalte) {
  if (spalte === "zeit") return parseFloat(tr.getAttribute("data-zeit"));
  var td = tr.children[sortSpalte[spalte]];
  var text = td.textContent.trim();
  if (typ === "dauer") return parseDauerText(text);
  if (typ === "num" || typ === "euro") return parseZahlText(text);
  return text.toLowerCase();
}
