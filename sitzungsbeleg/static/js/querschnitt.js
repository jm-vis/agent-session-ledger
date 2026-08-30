// Seite "Fehlerbilder & Entscheide" (bisher "Querschnitt", umgewidmet Phase 2 G, Plan Abschn. 3
// Nr. 3 -- die Seite wiederholte bis dahin nur die Start-Kacheln, Plan Abschn. 1 Beobachtung 1).
// Reine Weiterleitung an fehlerbilder.js (dort die eigentliche Fach-/Renderlogik) -- diese Datei
// bleibt der von router.js erwartete Seiten-Einstieg (`ladeQuerschnitt`, Name unveraendert, damit
// router.js/app.js nicht angefasst werden muessen).
import { zustand } from "./zustand.js";
import { iso } from "./format.js";
import { ladeFehlerbilderSeite } from "./fehlerbilder.js";

export function ladeQuerschnitt() {
  ladeFehlerbilderSeite(iso(zustand.von), iso(zustand.bis));
}
