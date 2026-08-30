// Einstieg: verkabelt alle Seiten in der urspruenglichen Reihenfolge (vor der Modul-Aufteilung
// stand das als top-level Code in einer einzigen IIFE in index.html) und startet die
// Erstladung. Reine Zusammensetzung -- keine eigene Fachlogik.
import { initHilfen, initKopfHoehe } from "./hilfen.js";
import { initRouter, zeigeSeite } from "./router.js";
import { initZeitraum, zustand, aktualisiereDatumsanzeige } from "./zustand.js";
import { initStart } from "./start.js";
import { initSitzung } from "./sitzung.js";
import { initEinstellungen } from "./einstellungen.js";
import { initChat, setSichtQuelle } from "./chat.js";
import { initSkalierung } from "./skalierung.js";
import { heute, addTage, iso } from "./format.js";

initHilfen();
initRouter();
initZeitraum();
initStart();
initSitzung();
initEinstellungen();
// Nachtrag Sichtkontext (2026-08-28): chat.js bleibt ohne statischen Import von zustand.js
// (s. chat.js-Dateikopf) -- app.js verkabelt die echten Werte hier EINMAL als Getter.
setSichtQuelle(function () {
  return {
    von: zustand.von ? iso(zustand.von) : null, bis: zustand.bis ? iso(zustand.bis) : null,
    aktiveProjekte: zustand.aktiveProjekte, aktiveQuellen: zustand.aktiveQuellen,
    aktiveKontexte: zustand.aktiveKontexte, sitzungenCache: zustand.sitzungenCache,
  };
});
initChat();
initKopfHoehe();
initSkalierung();

// ================= Start =================
// Zeitraum direkt setzen (nicht ueber setzeModus, das faellig ladeAktuellePage()
// ausloest -- zeigeSeite() gleich danach laedt bereits, ein doppelter Fetch waere unnoetig).
zustand.modus = "7";
zustand.bis = heute();
zustand.von = addTage(zustand.bis, -6);
aktualisiereDatumsanzeige();
zeigeSeite();
