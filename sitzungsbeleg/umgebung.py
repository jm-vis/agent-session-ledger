"""Achse Umgebung (C12, Auftrag 2026-08-28): wo lief die Anwendung, die den Beleg schreibt --
`entwicklung` (Default) · `abnahme` · `betrieb`. Quelle ist der Stop-Hook (`SITZUNGSBELEG_UMGEBUNG`,
siehe `__main__._umgebung_aus_env`), der neue Belege damit befuellt. Reine Funktionen wie
`quellen.py` -- kein SQL hier: `wert()` normalisiert einen bereits geladenen Rohwert (Dual-Reader
fuer Alt-Belege ohne das Feld / kaputte Werte), `kuerzel()` liefert den Projekt-Zellen-Chip,
`verteilung()` zaehlt fuer `GET /api/querschnitt` (`umgebungen: [{name, anzahl}]`)."""
from __future__ import annotations

from . import contracts

STANDARD = "entwicklung"
# Kuerzel-Chip in der Projekt-Zelle (Maintainer: keine neue Spalte) -- 'entwicklung' zeigt bewusst nichts.
KUERZEL = {"abnahme": "Abn.", "betrieb": "Betrieb"}


def wert(roh: str | None) -> str:
    """Dual-Reader: fehlender/leerer/unbekannter Rohwert faellt auf `entwicklung` zurueck --
    deckt sowohl Alt-Belege ohne das Feld als auch kaputte/fremde Werte ab."""
    return roh if roh in contracts.UMGEBUNGEN else STANDARD


def kuerzel(umgebung: str) -> str:
    """Chip-Kuerzel fuer die Anzeige, leer bei `entwicklung` (kein Chip)."""
    return KUERZEL.get(umgebung, "")


def verteilung(werte: list[str]) -> list[dict]:
    """{name, anzahl} je vorkommendem (bereits `wert()`-normalisiertem) Wert, alphabetisch --
    Grundlage fuer `GET /api/querschnitt` `umgebungen` und den Seitenleisten-Block (Frontend
    zeigt ihn erst ab zwei Werten mit anzahl > 0)."""
    zaehler: dict[str, int] = {}
    for w in werte:
        zaehler[w] = zaehler.get(w, 0) + 1
    return [{"name": n, "anzahl": a} for n, a in sorted(zaehler.items())]
