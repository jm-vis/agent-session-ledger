"""Klartext je Regel (Abnahme "Block 4 Sitzungsdetail", 2026-08-26, Auftrag B.4):
Titel/Bedeutung/Was-tun je Regel, damit ein Befund auf der Sitzungsseite nicht nur die rohe
Signatur zeigt. Keyed über ``Auffaelligkeit.regel`` -- das Feld ist stabil über alle
Auspraegungen einer Regel (die zusammengesetzte ``signatur`` traegt nur die Gruppierung,
z. B. ``rework:tool:Bash``), ein Eintrag hier deckt darum jede Auspraegung ab.

Deckt alle Signaturen aus ``regeln.REGELN`` ab, plus die Querschnitts-/Redaktions-Regeln
(``cost:outlier``, ``error:recurring`` aus ``querschnitt.py``, ``privacy:metadata_leak`` aus
``redaktion.py``) -- die leben in anderen Modulen, tauchen aber im selben Signatur-Vokabular
auf (Fehler-Panel, Befund-Entscheide-Tabelle, ggf. ``beleg.auffaelligkeiten``).

``einheit``/``kurz`` (Ergaenzung 2026-08-27, Mockup K2 -- Befund-Karten kompakt): ``einheit``
ist das kurze Plural-Wort, das der Wert-Chip hinter die Zahl schreibt (z. B. "Nacharbeiten"),
leer wenn ``wert`` die Einheit schon selbst traegt (z. B. "p95 2215 s", "20.5 %"). ``kurz`` ist
die Kurzform von ``bedeutung`` fuer Zeile 2 der Karte (max. ~70 Zeichen, ein Satz, ohne
"Zahl = …"-Erklaerung -- das uebernimmt jetzt die Einheit); die volle ``bedeutung`` bleibt in
der ?-Hilfe."""
from __future__ import annotations

REGELTEXTE: dict[str, dict[str, str]] = {
    "tool:error_rate": {
        "titel": "Hohe Fehlerquote",
        "bedeutung": "Mindestens 3 Werkzeugaufrufe sind fehlgeschlagen, und das bei "
                     ">= 20 % aller Aufrufe dieser Sitzung.",
        "kurz": "Werkzeugaufrufe schlagen ungewöhnlich oft fehl.",
        "einheit": "",
        "was_tun": "Fehlerklassen im Verlauf prüfen -- häufig ein falscher Pfad, "
                   "eine fehlende Berechtigung oder ein kaputtes Kommando.",
    },
    "rework:file": {
        "titel": "Datei-Nacharbeit",
        "bedeutung": "Eine einzelne Datei wurde mindestens 5-mal angefasst "
                     "(Edit/Write/MultiEdit/Read), UND mindestens 2 dieser Aufrufe schlugen fehl.",
        "kurz": "Dieselbe Datei wurde mehrfach angefasst, mehrere Aufrufe schlugen fehl.",
        "einheit": "Bearbeitungen",
        "was_tun": "Prüfen, ob die Datei mehrfach in unterschiedliche Richtungen bearbeitet "
                   "wurde (Hin und Her) statt einmal sauber.",
    },
    "rework:tool": {
        "titel": "Werkzeug-Nacharbeit",
        "bedeutung": "Ein Werkzeugaufruf schlug fehl und wurde wiederholt -- Zahl = Anzahl "
                     "der Nacharbeiten mit demselben Werkzeug.",
        "kurz": "Werkzeugaufruf schlug fehl und wurde mit demselben Werkzeug wiederholt.",
        "einheit": "Nacharbeiten",
        "was_tun": "Log-Ausschnitt zum Werkzeug ansehen: liegt ein wiederkehrendes Muster vor "
                   "(z. B. immer derselbe Syntaxfehler)?",
    },
    "subagent:failed": {
        "titel": "Subagent fehlgeschlagen",
        "bedeutung": "Ein Subagent lieferte kein verwertbares Ergebnis (Status fehler oder leer).",
        "kurz": "Subagent lieferte kein verwertbares Ergebnis.",
        "einheit": "",
        "was_tun": "Subagent-Beleg öffnen und prüfen, woran der Auftrag scheiterte -- ggf. "
                   "Auftrag präzisieren.",
    },
    "subagent:unsupported_claim": {
        "titel": "Behauptung ohne Beleg",
        "bedeutung": "Ein Subagent meldet Ergebnis 'ok', aber sein Transkript fehlt -- die "
                     "Zahlen stammen nur aus der Hauptsitzung, nicht aus einem eigenen "
                     "geprüften Beleg.",
        "kurz": "Ergebnis ohne eigenes geprüftes Beleg-Transkript.",
        "einheit": "",
        "was_tun": "Nicht ungeprüft übernehmen: Behauptung stichprobenartig gegen den "
                   "tatsächlichen Stand (Datei/Test/Befehl) verifizieren.",
    },
    "subagent:overdelegation": {
        "titel": "Überdelegation",
        "bedeutung": "Mehr als 25 Subagenten in dieser Sitzung, oder eine Delegationstiefe "
                     "von 3 oder mehr (Subagent delegiert an Subagent).",
        "kurz": "Viele Subagenten oder tiefe Verschachtelung in dieser Sitzung.",
        "einheit": "",
        "was_tun": "Prüfen, ob die Aufgabe wirklich so viel Verzweigung brauchte, oder ob ein "
                   "direkterer Weg schneller gewesen wäre.",
    },
    "latency:slow_turn": {
        "titel": "Langsame Runde/Werkzeug",
        "bedeutung": "Entweder liegt die Runden-Latenz (p95) über 60 Sekunden, oder ein "
                     "Werkzeug brauchte wiederholt über 120 Sekunden.",
        "kurz": "Runden-Latenz p95 über 60 s oder ein Werkzeug wiederholt über 120 s.",
        "einheit": "",
        "was_tun": "Bei Werkzeug-Bezug prüfen, ob ein Netzwerk-/Docker-/Modell-Aufruf "
                   "regelmäßig hängt.",
    },
    "latency:timeout": {
        "titel": "Zeitüberschreitung",
        "bedeutung": "Ein Werkzeugaufruf endete exakt bei 120 000 ms -- das ist der "
                     "Bash-Standard-Timeout, also vermutlich abgebrochen statt fertig.",
        "kurz": "Werkzeugaufruf endete exakt beim Bash-Standard-Timeout von 120 s.",
        "einheit": "Zeitüberschreitungen",
        "was_tun": "Befehl mit explizitem, höherem Timeout erneut laufen lassen oder in den "
                   "Hintergrund verschieben.",
    },
    "capture:gap": {
        "titel": "Erfassungslücke",
        "bedeutung": "Ein Kanal (Token oder Dauer) liefert diese Quelle strukturell nicht -- "
                     "keine Aussage über die Sitzung selbst, nur über die Meßbarkeit.",
        "kurz": "Dieser Kanal liefert für diese Quelle strukturell keine Daten.",
        "einheit": "",
        "was_tun": "Kein Handlungsbedarf an der Sitzung; nur relevant, wenn dieser Kanal für "
                   "Auswertungen gebraucht wird.",
    },
    "context:compaction_risk": {
        "titel": "Kontext-Kompaktierung spät",
        "bedeutung": "Eine Kontext-Kompaktierung geschah erst spät in der Sitzung "
                     "(>= 75 % der Laufzeit) -- das ist eine Positionsangabe, kein Füllstand.",
        "kurz": "Kontext-Kompaktierung geschah spät in der Sitzung.",
        "einheit": "",
        "was_tun": "Derzeit deaktiviert (Entscheid 2026-08-26) -- reaktiviert erst mit "
                   "einer echten Füllstand-Kennzahl.",
    },
    "privacy:metadata_leak": {
        "titel": "Redaktion griff",
        "bedeutung": "Das Redaktions-Sicherheitsnetz hat vor dem Speichern Inhalte "
                     "entfernt/ersetzt (Pfade, Secrets, E-Mails, lange Freitexte) -- Zahl = "
                     "Anzahl der Fundstellen.",
        "kurz": "Redaktions-Netz hat vor dem Speichern Inhalte entfernt oder ersetzt.",
        "einheit": "Fundstellen",
        "was_tun": "Kein Handlungsbedarf -- das Netz hat funktioniert. Nur bei sehr hoher Zahl "
                   "lohnt ein Blick, ob die Quelle systematisch zu viel Rohtext liefert.",
    },
    "cost:spike": {
        "titel": "Kostenspitze",
        "bedeutung": "Eine einzelne Runde kostete ein Vielfaches (>= 5x) des Rundenmedians UND "
                     ">= 15 % der Gesamtkosten, ODER die letzten 3 Runden lagen im Schnitt >= 4x "
                     "über dem Median, ODER die drei teuersten Runden trugen >= 50 % der "
                     "Gesamtkosten. Median = Median aller Runden mit Kosten > 0, ab 5 solchen "
                     "Runden.",
        "kurz": "Eine oder mehrere Runden kosteten ungewöhnlich viel im Vergleich zum Rest.",
        "einheit": "",
        "was_tun": "Kosten-Kachel je Runde ansehen: viele Subagent-Starts erklären die Spitze "
                   "meist (gewollter Fan-out) -- sonst prüfen, ob ein teures Modell oder ein "
                   "übergroßer Kontext die Runde aufgebläht hat.",
    },
    "cost:outlier": {
        "titel": "Kosten-Ausreißer",
        "bedeutung": "Die Kosten dieser Sitzung liegen über dem 95-Perzentil der letzten 30 "
                     "Tage (ab 10 Sitzungen mit Kosten) -- ein Querschnitts-Vergleich, kein "
                     "Einzelbefund dieser Sitzung allein.",
        "kurz": "Kosten liegen über dem 95-Perzentil der letzten 30 Tage.",
        "einheit": "",
        "was_tun": "Token-Kacheln prüfen: ungewöhnlich viele Input-/Cache-Write-Token, oder "
                   "ein teures Modell für eine einfache Aufgabe?",
    },
    "error:recurring": {
        "titel": "Wiederkehrender Fehler",
        "bedeutung": "Dieselbe Fehlersignatur (Werkzeug + Fehlerart + Hash) trat in mehreren "
                     "Sitzungen der letzten 7 Tage auf -- ein Querschnitts-Vergleich, kein "
                     "Einzelbefund dieser Sitzung allein.",
        "kurz": "Gleiche Fehlersignatur trat in mehreren Sitzungen der letzten 7 Tage auf.",
        "einheit": "",
        "was_tun": "Fehlerbild im Querschnitt öffnen, betroffene Sitzungen ansehen -- meist "
                   "eine strukturelle Ursache (falsche Umgebungsvariable, kaputtes Setup).",
    },
}

STANDARD_TEXT: dict[str, str] = {
    "titel": "Unbekannte Regel",
    "bedeutung": "Für diese Signatur liegt noch kein Klartext vor.",
    "kurz": "",
    "einheit": "",
    "was_tun": "",
}


def text_fuer(regel: str) -> dict[str, str]:
    """Titel/Bedeutung/Kurz/Was-tun/Einheit je Regel -- Fallback für unbekannte/neue Signaturen."""
    return REGELTEXTE.get(regel, STANDARD_TEXT)
