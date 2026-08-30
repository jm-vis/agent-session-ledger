"""C11-Waechter: prueft, ob jeder `erledigt`-Entscheid an einem Ort VERANKERT ist, den die
naechste Sitzung liest (CONTRACTS.md Abschnitt "C11 · Verankerung eines Entscheids"). Claude/
Codex lesen nie die Datenbank -- ein Entscheid ohne Datei/Abschnitt wiederholt den Fehler.

Nur lesend (wie `_befehl_nachschlagen`), Grundlage fuer `scripts\\check-verankerung.ps1`:
`erledigte_entscheide()` fragt Postgres, `pruefe()` ist reine Python-Logik (Pfad-Existenz +
Abschnitt-Stichwort), testbar mit einem Tempdir statt einer echten Vault.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import speicher
from .speicher import sql_literal

STANDARD_TAGE = 90
ABSCHNITT_LAENGE = 40  # CONTRACTS.md C11: "erste 40 Zeichen"
# scripts/sitzungsbeleg/verankerung.py -> scripts/sitzungsbeleg -> scripts -> Repo-Wurzel.
REPO_WURZEL = Path(__file__).resolve().parent.parent.parent


@dataclass
class VerankerungsBefund:
    """Ein geprueftes `erledigt`-Detail. `legacy=True` (kein `verankerung`-Feld, Bestand vor
    C11) zaehlt NIE als ROT -- nur ein Hinweis, wie viele Alt-Entscheide uebersprungen wurden."""

    signatur: str
    sitzung_ref: int | None
    pfad: str | None
    ok: bool
    legacy: bool
    grund: str = ""


def sql_erledigte_entscheide(seit: date) -> str:
    """Alle `gf/befund_entscheid`-Details mit `status=erledigt`, deren Ereigniszeile seit
    `seit` liegt (Zeitstempel der Zeile, nicht `entschieden_am` im JSON -- konsistent mit
    `_sql_befund_entscheide` in web.py)."""
    return (
        "SELECT coalesce(jsonb_agg(detail), '[]'::jsonb) FROM ereignis "
        "WHERE quelle = 'gf' AND typ = 'befund_entscheid' "
        f"AND zeitstempel >= {sql_literal(seit.isoformat())}::date "
        "AND detail->>'status' = 'erledigt';"
    )


def erledigte_entscheide(seit: date, laufer=speicher.psql) -> list[dict]:
    """Rein lesend -- `laufer` austauschbar fuer Tests (FakePsql wie in test_retention.py)."""
    ausgabe = laufer(sql_erledigte_entscheide(seit))
    return json.loads(ausgabe) if ausgabe.strip() else []


def _pfad_grund(pfad: str, abschnitt: str, repo_wurzel: Path) -> str:
    """Leerer Text = ok, sonst der ROT-Grund. `pfad` ist repo-relativ (Contract erzwingt das
    schon beim Schreiben); hier zaehlt nur noch, ob die Datei WIRKLICH existiert."""
    ziel = repo_wurzel / pfad
    if not ziel.is_file():
        return f"Datei fehlt: {pfad}"
    if not abschnitt:
        return ""
    stichwort = abschnitt.strip()[:ABSCHNITT_LAENGE].lower()
    text = ziel.read_text(encoding="utf-8", errors="replace").lower()
    if stichwort and stichwort not in text:
        return f"Abschnitt nicht gefunden: {abschnitt[:ABSCHNITT_LAENGE]!r} nicht in {pfad}"
    return ""


def _befund_fuer(entscheid: dict, repo_wurzel: Path) -> VerankerungsBefund:
    signatur = str(entscheid.get("signatur", ""))
    sitzung_ref = entscheid.get("sitzung_ref")
    verankerung = entscheid.get("verankerung")
    if not verankerung:
        return VerankerungsBefund(signatur, sitzung_ref, None, True, True, "legacy: kein Verankerungsfeld")
    pfad = str(verankerung.get("pfad", ""))
    grund = _pfad_grund(pfad, str(verankerung.get("abschnitt", "")), repo_wurzel)
    return VerankerungsBefund(signatur, sitzung_ref, pfad, not grund, False, grund)


def pruefe(entscheide: list[dict], repo_wurzel: Path = REPO_WURZEL) -> list[VerankerungsBefund]:
    """Reine Funktion (kein I/O ausser Dateipruefung) -- Grundlage sowohl fuer die CLI als auch
    fuer Tests mit einem Tempdir-Repo (existierend/fehlend/Abschnitt fehlt/legacy)."""
    return [_befund_fuer(e, repo_wurzel) for e in entscheide]


def rote_befunde(befunde: list[VerankerungsBefund]) -> list[VerankerungsBefund]:
    return [b for b in befunde if not b.legacy and not b.ok]


def ausgabe_text(befunde: list[VerankerungsBefund]) -> str:
    """`OK n geprüft` oder `ROT` + Liste (signatur · sitzung_ref · pfad · Grund); Legacy-Zahl
    als eigene Hinweiszeile (CONTRACTS.md C11: "Hinweiszeile, nicht rot")."""
    rote = rote_befunde(befunde)
    legacy = [b for b in befunde if b.legacy]
    geprueft = len(befunde) - len(legacy)
    if rote:
        zeilen = ["ROT"] + [
            f"{b.signatur} · {b.sitzung_ref} · {b.pfad} · {b.grund}" for b in rote
        ]
    else:
        zeilen = [f"OK {geprueft} geprüft"]
    if legacy:
        zeilen.append(f"Hinweis: {len(legacy)} Legacy-Entscheid(e) ohne Verankerung uebersprungen.")
    return "\n".join(zeilen)


def als_json(befunde: list[VerankerungsBefund]) -> dict:
    rote = rote_befunde(befunde)
    legacy = [b for b in befunde if b.legacy]
    return {
        "status": "rot" if rote else "ok",
        "geprueft": len(befunde) - len(legacy),
        "legacy": len(legacy),
        "rot": [
            {"signatur": b.signatur, "sitzung_ref": b.sitzung_ref, "pfad": b.pfad, "grund": b.grund}
            for b in rote
        ],
    }
