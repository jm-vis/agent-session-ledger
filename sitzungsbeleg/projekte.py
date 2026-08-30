"""Projekt-Alias: Rohnamen (letzter Pfadteil/Git-Wurzel je cwd) auf {projekt, kontext}
abbilden -- fürs Lesen im Dashboard (web.py).

Belege sind append-only (nie ein UPDATE auf gespeicherte Rohnamen) -- der Alias gilt nur
beim Lesen: Anzeige ersetzt, Zählungen zusammengeführt, Filter `projekt=`/`kontext=`
akzeptieren die aufgelösten Werte.

Kontext ist eine feste Fünf-Werte-Menge (arbeit/voice/review/bewertung/test); ein Rohname
ganz ohne Eintrag löst auf Kontext `unzugeordnet` auf -- kein sechster gepflegter Wert,
sondern das Signal für den Wächter `scripts/check-projekt-aliase.ps1`.

Hand-gepflegte Datei `projekt-aliase.json` neben diesem Modul. Fail-open: fehlt sie oder
ist sie kaputt (JSON-Fehler), gilt kein Alias -- der Rohname bleibt unverändert (kein
Absturz, kein Datenverlust). Konvention: `docs/Benennung.md` Abschnitt
„Sitzungsbeleg: Projekt + Kontext".
"""
from __future__ import annotations

import json
from pathlib import Path

ALIAS_DATEI = Path(__file__).resolve().parent / "projekt-aliase.json"

KONTEXTE = ("arbeit", "voice", "review", "bewertung", "test")
UNZUGEORDNET = "unzugeordnet"
CODEX_PRAEFIX = "codex-"


def lade_aliase(pfad: Path = ALIAS_DATEI) -> dict[str, dict]:
    """Rohname/`<rohname>@<quelle>` -> {"projekt": str, "kontext": str, ...}.

    Fail-open: fehlt/kaputt/kein Objekt -> {} (kein Absturz). Einträge ohne `projekt`
    oder mit Kommentar-Präfix (`_hinweis`) werden übersprungen.
    """
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(roh, dict):
        return {}
    ergebnis: dict[str, dict] = {}
    for schluessel, eintrag in roh.items():
        if schluessel.startswith("_") or not isinstance(eintrag, dict):
            continue
        if "projekt" not in eintrag:
            continue
        ergebnis[schluessel] = eintrag
    return ergebnis


def aufloesen(rohname: str, quelle: str, aliase: dict | None = None) -> tuple[str, str, bool]:
    """(projekt, kontext, ausgeblendet) für einen rohen Sitzungs-Projektnamen.

    Reihenfolge: 1) Schlüssel `<rohname>@<quelle>` (quellenabhängige Aufloesung) 2)
    Schlüssel `<rohname>` 3) `codex-<x>`-Automatik: Projekt = Alias von `<x>` (falls
    ein Eintrag für `<x>` existiert) sonst `<x>` selbst, Kontext immer `review` 4) ganz
    ohne Treffer: Projekt bleibt der Rohname, Kontext `unzugeordnet`.
    """
    aliase = lade_aliase() if aliase is None else aliase
    eintrag = aliase.get(f"{rohname}@{quelle}") or aliase.get(rohname)
    if eintrag:
        return (
            str(eintrag.get("projekt", rohname)),
            str(eintrag.get("kontext", UNZUGEORDNET)),
            bool(eintrag.get("ausgeblendet", False)),
        )
    if rohname.startswith(CODEX_PRAEFIX):
        rest = rohname[len(CODEX_PRAEFIX):]
        ziel = aliase.get(rest)
        projekt = str(ziel.get("projekt", rest)) if ziel else rest
        return projekt, "review", False
    return rohname, UNZUGEORDNET, False


def roh_eintraege_fuer_projekt(projekt: str, aliase: dict | None = None) -> list[tuple[str, str | None]]:
    """(rohname, quelle-oder-None) für alle Alias-Einträge, die auf `projekt` zeigen, plus
    (projekt, None) selbst -- Daten können schon unter dem kanonischen Namen liegen. Nur
    aus expliziten Alias-Einträgen (statische Datei); die `codex-<x>`-Automatik für nicht
    gelistete Rohnamen ist hier bewusst nicht rückwärts aufgelöst (Grenze dokumentiert in
    docs/Benennung.md)."""
    aliase = lade_aliase() if aliase is None else aliase
    treffer: set[tuple[str, str | None]] = {(projekt, None)}
    for schluessel, eintrag in aliase.items():
        if eintrag.get("projekt") != projekt:
            continue
        if "@" in schluessel:
            roh, quelle = schluessel.split("@", 1)
            treffer.add((roh, quelle))
        else:
            treffer.add((schluessel, None))
    return sorted(treffer, key=lambda t: (t[0], t[1] or ""))
