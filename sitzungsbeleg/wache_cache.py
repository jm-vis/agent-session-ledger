"""C13 · Entscheide-Cache fuer die Wache: DB (nur SELECT) -> `_work_sitzungsbeleg/wache-
entscheide.json`. Der Hook (`wache.py`, ein Prozess je Werkzeugaufruf) liest den Cache nur --
kein DB-Zugriff im Hook (Budget). Schreiber: der Dashboard-Dienst (`web.py` Startup, danach
alle 10 min ueber `starte_hintergrund()`) und der CLI-Befehl `python -m sitzungsbeleg
wache-cache` (Instanzen ohne Dienst, z. B. Aufgabenplaner). Nur erledigte/obsolete Entscheide
der letzten 180 Tage, KEIN Freitext (Vermerk/Begruendung bleiben aussen vor -- CONTRACTS.md C13)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .speicher import SpeicherFehler, psql

CACHE_PFAD = Path(__file__).resolve().parent.parent / "_work_sitzungsbeleg" / "wache-entscheide.json"
TAGE = 180
INTERVALL_S = 600

# Austauschbar fuer Tests (wache_cache.LAUFER = FakeLaufer(...)), wie speicher/web/befund_kacheln.
LAUFER = psql


def _sql_projekt_hash_lateral() -> str:
    """Projekt-Hash der Sitzung, auf die ein Entscheid zeigt (leer bei globalem Entscheid) --
    juengste Version je logischer Sitzung (`sitzung.dokument->kopf->projekt_hash`)."""
    return (
        "LEFT JOIN LATERAL (\n"
        "  SELECT s.dokument->'kopf'->>'projekt_hash' AS projekt_hash FROM sitzung s\n"
        "  WHERE s.logisch_ref = (e.detail->>'sitzung_ref')::bigint ORDER BY s.id DESC LIMIT 1\n"
        ") ph ON e.detail->>'sitzung_ref' IS NOT NULL"
    )


def sql_entscheide(tage: int = TAGE) -> str:
    """Erledigte/obsolete `gf/befund_entscheid`-Ereignisse der letzten `tage` Tage, je Zeile
    ergaenzt um den Projekt-Hash der referenzierten Sitzung (leer bei globalem Entscheid)."""
    felder = (
        "'signatur', e.detail->>'signatur', 'sitzung_ref', (e.detail->>'sitzung_ref')::bigint,\n"
        "  'projekt_hash', coalesce(ph.projekt_hash, ''), 'status', e.detail->>'status',\n"
        "  'entschieden_am', e.detail->>'entschieden_am', 'verankerung', e.detail->'verankerung'"
    )
    return (
        f"SELECT coalesce(jsonb_agg(jsonb_build_object(\n  {felder}\n)), '[]'::jsonb)\n"
        f"FROM ereignis e\n{_sql_projekt_hash_lateral()}\n"
        "WHERE e.quelle = 'gf' AND e.typ = 'befund_entscheid'\n"
        "  AND e.detail->>'status' IN ('erledigt', 'obsolet')\n"
        f"  AND (e.detail->>'entschieden_am')::timestamptz >= now() - interval '{int(tage)} days';"
    )


def baue_cache(jetzt: datetime | None = None) -> dict:
    """DB -> Cache-Dict (nur SELECT); wirft `SpeicherFehler` bei DB-Problemen (Aufrufer faengt)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    ausgabe = LAUFER(sql_entscheide())
    entscheide = json.loads(ausgabe) if ausgabe.strip() else []
    return {"stand": jetzt.isoformat(), "entscheide": entscheide}


def schreibe_cache(pfad: Path | None = None, jetzt: datetime | None = None) -> dict:
    """Baut + schreibt den Cache atomar (Temp-Datei + `Path.replace`, kein halb geschriebener
    Stand fuer den lesenden Hook). `pfad=None` -> `CACHE_PFAD` ZUR AUFRUFZEIT gelesen (nicht als
    Default-Parameter gebunden) -- Tests koennen `wache_cache.CACHE_PFAD` monkeypatchen."""
    pfad = pfad or CACHE_PFAD
    cache = baue_cache(jetzt)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(pfad)
    return cache


def befehl_wache_cache(args) -> int:
    """CLI `wache-cache`: baut den Cache einmal (fuer Instanzen ohne Dashboard-Dienst)."""
    try:
        cache = schreibe_cache()
    except SpeicherFehler as fehler:
        print(f"wache-cache: nicht geschrieben — {fehler}")
        return 2
    print(f"wache-cache: {len(cache['entscheide'])} Entscheide -> {CACHE_PFAD}")
    return 0


_timer: threading.Timer | None = None


def _tick() -> None:
    global _timer
    try:
        schreibe_cache()
    except SpeicherFehler:
        pass  # Dienst laeuft weiter, der naechste Tick versucht es erneut
    _timer = threading.Timer(INTERVALL_S, _tick)
    _timer.daemon = True
    _timer.start()


def starte_hintergrund() -> None:
    """Dashboard-Startup (`web.py`): schreibt den Cache sofort, danach alle 10 min (`_tick`)."""
    _tick()
