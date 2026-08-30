"""Zentrale Schluesselablage (Entscheid 2026-08-28): EINE Datei `scripts\\.env` fuer alle Anbieter-
Schluessel (`NAME=wert` je Zeile, `#`-Kommentare), statt je Anbieter eine `.env.<anbieter>`.

Reihenfolge je Schluessel: Umgebungsvariable > `scripts\\.env` > Alt-Datei `.env.<anbieter>` (Rueckfall,
damit nichts bricht, bis der Maintainer die Inhalte zusammengefuehrt hat). Werte werden nie geloggt oder
zurueckgegeben, ausser an den Aufrufer, der sie in eine Kindprozess-Umgebung legt.
"""
from __future__ import annotations

import os
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
ZENTRALE_DATEI = SCRIPTS_DIR / ".env"


def _aus_datei(datei: Path, name: str) -> str | None:
    if not datei.is_file():
        return None
    for zeile in datei.read_text(encoding="utf-8-sig").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        if schluessel.strip() == name:
            return wert.strip().strip('"').strip("'") or None
    return None


def lese(name: str, alt_datei: Path | None = None) -> str | None:
    """Umgebungsvariable > zentrale `.env` > Alt-Datei. `None`, wenn nirgends gesetzt."""
    wert = os.environ.get(name)
    if wert:
        return wert
    wert = _aus_datei(ZENTRALE_DATEI, name)
    if wert:
        return wert
    return _aus_datei(alt_datei, name) if alt_datei is not None else None
