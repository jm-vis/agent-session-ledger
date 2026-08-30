"""Zentrale Pfad-/Umgebungsauflösung, die nicht an eine feste Repo-Lage gebunden sein darf --
dieses Paket wird sowohl eingebettet als auch als eigenstaendiger Checkout betrieben."""
from __future__ import annotations

from pathlib import Path

from . import schluessel


def modelle_pfad() -> Path:
    """Pfad zu `modelle.json`: `SITZUNGSBELEG_MODELLE` (Umgebung, sonst `scripts\\.env`) geht vor,
    sonst der Ordner UEBER dem Paket (eingebettetes Layout), sonst der Paket-Ordner selbst
    (eigenstaendiger Checkout). Liefert den ersten TATSAECHLICH existierenden Kandidaten; existiert
    keiner, den Paket-Elternordner (Alt-Default) -- Aufrufer behalten so ihr bestehendes
    "Datei fehlt"-Verhalten (leere Registry statt Absturz), statt hier selbst zu werfen."""
    eltern = Path(__file__).resolve().parents[1] / "modelle.json"
    kandidaten = []
    konfiguriert = schluessel.lese("SITZUNGSBELEG_MODELLE")
    if konfiguriert:
        kandidaten.append(Path(konfiguriert))
    kandidaten.append(eltern)
    kandidaten.append(Path(__file__).resolve().parent / "modelle.json")
    for kandidat in kandidaten:
        if kandidat.is_file():
            return kandidat
    return eltern
