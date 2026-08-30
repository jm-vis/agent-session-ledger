"""Versionsquelle Sitzungsbeleg: eine eigene Version, unabhaengig vom umgebenden Repo -- EINE
Quelle, `web.py` ersetzt beim Ausliefern den Platzhalter `__VERSION__`, `GET /version` liefert
denselben Wert fuer den Rauchtest.

Datei `VERSION` (dieser Ordner, `scripts/sitzungsbeleg/VERSION`) ist die EINZIGE Quelle -- der
Code liest sie, er wiederholt sie nicht. Bump macht ein Mensch bei der naechsten Abnahme, kein
Skript hier.

Welche Stelle springt (SemVer aus NUTZERSICHT):
- **Minor (0.x.0)** = neue Funktion, die der Nutzer vorher nicht hatte (neue Maske, neue Aktion,
  neue Ansicht).
- **Patch (0.0.x)** = bestehende Funktion korrigiert oder verfeinert: richtiger sortiert, neu
  bewertet, Optik, Verdrahtung, Datenquelle getauscht -- auch wenn intern neue Felder/Spalten/
  Regeln entstehen, solange keine neue Maske dazukommt.
- Major bleibt 0, bis der Betrieb den Kunden-Rollout freigibt.
Zeitpunkt unveraendert: Bump erst nach Abnahme, EIN Sprung je Paket."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

PRODUKT = "sitzungsbeleg"
VERSION_DATEI = Path(__file__).resolve().parent / "VERSION"
PLATZHALTER = "__VERSION__"


def lade_version(pfad: Path = VERSION_DATEI) -> str:
    """Liest `VERSION` (UTF-8, BOM-tolerant, getrimmt); fehlt die Datei -> '0.0.0' (kein Absturz
    beim Start, aber sofort sichtbar falsch -- wie config.VERSION in voice/livekit)."""
    if not pfad.exists():
        return "0.0.0"
    return pfad.read_text(encoding="utf-8-sig").strip()


VERSION = lade_version()

router = APIRouter()


@router.get("/version")
def api_version() -> dict:
    """Welcher Stand laeuft -- Rauchtest/Fehlersuche ohne die Oberflaeche zu oeffnen."""
    return {"version": VERSION, "produkt": PRODUKT}


def html_mit_version(html: str) -> str:
    """Ersetzt JEDEN Platzhalter `__VERSION__` (Kopfzeile-Caption + jeder `?v=`-Cache-Stempel) --
    ein Wert fuer beides, wie ADR 0005 Punkt 1."""
    return html.replace(PLATZHALTER, VERSION)
