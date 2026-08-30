"""Kachel "Prüfung offen" (Phase 2 E, additiv) -- eigenes Modul + APIRouter, damit `web.py`
(schon > 800 Zeilen) nur eine `include_router`-Zeile braucht (CONTRACTS.md C7 Start-Kacheln:
"Fehlerbilder · Kostenspitzen (`cost:spike`) · Erfassungslücken · Dissens · Prüfung offen").

Zählt (sitzung_logisch, signatur)-Paare mit C2-Status `offen` unter den Auffälligkeiten der
AKTUELLEN Version je Sitzung im Zeitraum -- dieselbe Ableitung wie `pruefung.status_fuer`
(GET /api/sitzung), nur über viele Sitzungen hinweg statt einer.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter

from . import pruefung
from .speicher import psql, sql_literal

# Austauschbar für Tests (wie web.py: befund_kacheln.LAUFER = FakeLaufer(...)).
LAUFER = psql

router = APIRouter()


def _zeitraum(von: date, bis: date) -> str:
    spalte = "coalesce(s.ende, s.start, s.zeitstempel)"
    return (
        f"{spalte} >= {sql_literal(von.isoformat())}::date "
        f"AND {spalte} < ({sql_literal(bis.isoformat())}::date + 1)"
    )


def sql_offene_auffaelligkeiten(von: date, bis: date) -> str:
    """logisch_ref/signatur je Auffälligkeit der AKTUELLEN Version je Sitzung im Zeitraum
    (`sitzung_aktuell`, Migration 0004) -- gleiches Zeitraum-Muster wie `web._sql_ids_je_regel`."""
    return (
        "SELECT s.logisch_ref, af->>'signatur' FROM sitzung_aktuell s, "
        "jsonb_array_elements(s.dokument->'auffaelligkeiten') af "
        f"WHERE {_zeitraum(von, bis)} AND coalesce(af->>'signatur', '') <> '';"
    )


def sql_ereignisse(quelle: str, typ: str) -> str:
    """Alle `ereignis.detail`-Zeilen einer Quelle/Typ-Kombination -- wie `web._sql_ereignisse_quelle`,
    hier zusätzlich nach `typ` gefiltert (nur `gf/befund_entscheid` und `pruefung/lauf` gebraucht)."""
    return (
        "SELECT coalesce(jsonb_agg(detail), '[]'::jsonb) FROM ereignis "
        f"WHERE quelle = {sql_literal(quelle)} AND typ = {sql_literal(typ)};"
    )


def _zeilen(ausgabe: str) -> list[list[str]]:
    return [z.split("|") for z in ausgabe.splitlines() if z.strip()]


def _json(ausgabe: str) -> list:
    return json.loads(ausgabe) if ausgabe.strip() else []


def offene_paare(zeilen, entscheide: list[dict], laeufe: list[dict], laufend: list[dict]) -> set:
    """C2: (sitzung_logisch, signatur)-Paare mit Status `offen` -- reine Funktion (`zeilen` =
    Liste von (sitzung_logisch, signatur)), unabhängig von SQL/psql testbar."""
    offene = set()
    for sitzung_logisch, signatur in zeilen:
        befund = {"signatur": signatur, "sitzung_logisch": sitzung_logisch}
        if pruefung.status_fuer(befund, entscheide, laeufe, laufend) == "offen":
            offene.add((sitzung_logisch, signatur))
    return offene


def _auffaelligkeiten_zeilen(von: date, bis: date) -> list[tuple[int, str]]:
    roh = _zeilen(LAUFER(sql_offene_auffaelligkeiten(von, bis)))
    return [(int(s[0]), s[1]) for s in roh if len(s) == 2 and s[0].isdigit()]


def _laeufe_mit_legacy() -> list[dict]:
    """Nachtrag 2026-08-27 Punkt 1: Legacy-`vieraugen/review`-Ereignisse (C1 Regel 2) zaehlen wie
    `pruefung`-Laeufe in `status_fuer` -- sonst zeigt die Kachel Befunde als "offen", die ueber
    die alte Vier-Augen-Pruefung laengst ein Urteil haben."""
    laeufe = _json(LAUFER(sql_ereignisse("pruefung", "lauf")))
    vieraugen = _json(LAUFER(sql_ereignisse("vieraugen", "review")))
    return laeufe + pruefung.vieraugen_als_laeufe(vieraugen)


def kachel(von: date, bis: date) -> dict:
    """{"anzahl": Anzahl offener (sitzung_logisch,signatur)-Paare, "sitzung_ids": [...]}."""
    zeilen = _auffaelligkeiten_zeilen(von, bis)
    entscheide = _json(LAUFER(sql_ereignisse("gf", "befund_entscheid")))
    offene = offene_paare(zeilen, entscheide, _laeufe_mit_legacy(), pruefung.laufend_uebersicht())
    return {"anzahl": len(offene), "sitzung_ids": sorted({s for s, _ in offene})}


@router.get("/api/kacheln/pruefung-offen")
def api_pruefung_offen(von: date, bis: date) -> dict:
    return kachel(von, bis)
