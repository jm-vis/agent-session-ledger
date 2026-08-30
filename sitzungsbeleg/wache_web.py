"""C13-Nachtrag (Entscheid 2026-08-28 14:30): Meldungsspur der Wache lesbar machen --
`GET /api/wache/meldungen` (Zeitraum-Uebersicht fuer die Start-Kachel) und
`GET /api/sitzung/{id}/wache` (Meldungen EINER Sitzung, fuer die Verlauf-Zeitleiste).

Eigenes APIRouter (Muster fehlerbilder.py/befund_kacheln.py) -- `web.py` bekommt nur eine
`include_router`-Zeile. Liest NUR die JSONL-Spool-Datei, die `wache.py` (Hook-Prozess, ein
eigener Prozess je Werkzeugaufruf) schreibt -- kein DB-Zugriff hier. 30 s Prozess-Cache: die
Spool-Datei kann waehrend einer laufenden Sitzung oft wachsen, ein Datei-Read je Dashboard-
Request waere unnoetig teuer bei mehreren offenen Tabs."""
from __future__ import annotations

import json
import time
from datetime import date, datetime

from fastapi import APIRouter

from .wache import SPOOL_PFAD

router = APIRouter()
CACHE_S = 30
# Austauschbar/ruecksetzbar fuer Tests (wache_web._cache = {"stand": 0.0, "zeilen": []}).
_cache: dict = {"stand": 0.0, "zeilen": []}


def _lade_zeilen() -> list[dict]:
    """Alle Spool-Zeilen, `CACHE_S` Sekunden gecacht (Modul-globaler Zustand, EIN Server-
    Prozess -- wie web.LAUFER/befund_kacheln.LAUFER austauschbar, hier aber eine Zeit-Kachel
    statt einer Funktion)."""
    jetzt = time.monotonic()
    if jetzt - _cache["stand"] < CACHE_S:
        return _cache["zeilen"]
    zeilen = []
    if SPOOL_PFAD.exists():
        for roh in SPOOL_PFAD.read_text(encoding="utf-8").splitlines():
            if not roh.strip():
                continue
            try:
                zeilen.append(json.loads(roh))
            except json.JSONDecodeError:
                continue
    _cache["stand"], _cache["zeilen"] = jetzt, zeilen
    return zeilen


def _im_zeitraum(zeile: dict, von: date, bis: date) -> bool:
    try:
        tag = datetime.fromisoformat(str(zeile.get("zeit", ""))).date()
    except ValueError:
        return False
    return von <= tag <= bis


@router.get("/api/wache/meldungen")
def api_wache_meldungen(von: date, bis: date) -> dict:
    treffer = [z for z in _lade_zeilen() if _im_zeitraum(z, von, bis)]
    return {
        "anzahl": len(treffer),
        "offen_fragen": sum(1 for z in treffer if z.get("stufe") == "fragen"),
        "meldungen": treffer,
    }


@router.get("/api/sitzung/{sitzung_id}/wache")
def api_sitzung_wache(sitzung_id: int) -> dict:
    """Meldungen EINER Sitzung -- ueber die claude-`session_id` in `kopf.sitzung_id` (wie
    `wache.py` sie in `daten["session_id"]` vom PreToolUse-Hook bekommt), nicht ueber die
    Dashboard-interne `sitzung_logisch`-ID."""
    from .web import _sitzung  # spaeter Import: vermeidet Zirkularitaet (Muster web._sitzung)

    antwort = _sitzung(sitzung_id)
    session_id = antwort["dokument"].get("kopf", {}).get("sitzung_id", "")
    meldungen = [z for z in _lade_zeilen() if z.get("session_id") == session_id]
    return {"meldungen": meldungen}
