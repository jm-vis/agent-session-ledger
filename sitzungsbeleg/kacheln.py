"""Kacheln: rundenweise Kennzahlen + Live-Benchmark für die Sitzungsseite
(Auftrag „Kacheln", 2026-08-27) -- ``GET /api/sitzung/{id}/kacheln``.

Reine Funktionen auf ``Beleg.ereignisse``/``Beleg.subagenten`` (Dataclass-Objekte, wie
kennzahlen.py) -- der Endpunkt selbst (web.py) lädt das Dokument, wandelt es über
``_beleg_aus_dict`` um und ruft nur ``antwort()`` auf. Die Benchmark-SQL wird hier gebaut
(``sql_benchmark``), ausgeführt wird sie wie überall sonst über ``web.LAUFER``.

Referenz: der abgenommene Mockup-Generator
``scripts/_work_sitzungsbeleg/2026-08-27-baue-kacheln-final.py`` (Funktionen ``runden_aus``,
``timeout_runden``, ``modell_zaehlung``, SQL in ``SQL``/``lade_benchmark``) -- gleiche Definitionen,
hier als getestete Produktfunktionen statt Einweg-Skript.
"""
from __future__ import annotations

import statistics

from .kennzahlen import kosten_je_runde, segmentiere_runden
from .modell import (
    ART_ASSISTENT,
    ART_COMPACTION,
    ART_RUNDE_ENDE,
    ART_SUBAGENT,
    ART_TOOL,
    ART_TOOL_ERGEBNIS,
    Ereignis,
    Subagent,
    Token,
)
from .speicher import sql_literal

TIMEOUT_MS = 120_000
MIN_RUNDEN_BENCHMARK = 5
BENCHMARK_FELDER = (
    "kosten_je_runde", "token_out_je_runde", "tools_je_runde", "runden",
    "latenz_p50_ms", "latenz_p95_ms", "tool_fehlerquote", "subagenten", "dauer_je_runde_ms",
)


def _eine_runde(index: int, segment: list[Ereignis], kosten: float) -> dict:
    """Eine Zeile der ``runden``-Liste: Kosten (von außen gereicht, geteilte Rechnung mit
    ``kennzahlen.kosten_je_runde``) plus Fehler/Subagenten/Compaction/Dauer/Timeout dieser Runde."""
    dauer_werte = [e.dauer_ms for e in segment if e.art == ART_RUNDE_ENDE and e.dauer_ms is not None]
    return {
        "index": index,
        "kosten": kosten,
        "tool_fehler": sum(1 for e in segment if e.art == ART_TOOL_ERGEBNIS and e.fehler),
        "subagent_starts": sum(1 for e in segment if e.art == ART_SUBAGENT),
        "compaction": any(e.art == ART_COMPACTION for e in segment),
        "dauer_ms": max(dauer_werte) if dauer_werte else 0,
        "timeout": any(e.art == ART_TOOL and (e.dauer_ms or 0) >= TIMEOUT_MS for e in segment),
    }


def runden(ereignisse: list[Ereignis], preise: dict | None) -> list[dict]:
    """Rundenserie: 1-basierter Index je Runde (``art == 'nutzer'`` startet eine neue Runde,
    Ereignisse davor entfallen -- ``kennzahlen.segmentiere_runden``)."""
    segmente = segmentiere_runden(ereignisse)
    kosten = kosten_je_runde(ereignisse, preise)
    return [_eine_runde(i + 1, segment, kosten[i]) for i, segment in enumerate(segmente)]


def kosten_median_runde(runden_liste: list[dict]) -> float | None:
    """Median der Runden mit Kosten > 0 -- ``None`` ohne eine solche Runde."""
    werte = [r["kosten"] for r in runden_liste if r["kosten"] > 0]
    return statistics.median(werte) if werte else None


def top3_index(runden_liste: list[dict]) -> list[int]:
    """0-basierte Indizes der bis zu 3 teuersten Runden, absteigend nach Kosten."""
    geordnet = sorted(range(len(runden_liste)), key=lambda i: runden_liste[i]["kosten"], reverse=True)
    return geordnet[:3]


def top3_anteil(runden_liste: list[dict], index: list[int]) -> float | None:
    """Anteil der ``index``-Runden an der Gesamtsumme -- ``None`` bei Gesamtsumme 0."""
    gesamt = sum(r["kosten"] for r in runden_liste)
    if gesamt <= 0:
        return None
    return sum(runden_liste[i]["kosten"] for i in index) / gesamt


def langsamste_index(runden_liste: list[dict]) -> list[int]:
    """0-basierte Indizes der bis zu 3 längsten Runden, absteigend nach Dauer."""
    geordnet = sorted(range(len(runden_liste)), key=lambda i: runden_liste[i]["dauer_ms"], reverse=True)
    return geordnet[:3]


def modelle_haupt(ereignisse: list[Ereignis]) -> list[dict]:
    """Aufrufe je Modell der Hauptsitzung (``assistent``-Ereignisse mit Token), absteigend."""
    zaehler: dict[str, int] = {}
    for e in ereignisse:
        if e.art == ART_ASSISTENT and e.token is not None:
            name = e.name or "?"
            zaehler[name] = zaehler.get(name, 0) + 1
    return [{"modell": m, "aufrufe": n} for m, n in sorted(zaehler.items(), key=lambda kv: -kv[1])]


def modelle_sub(subagenten: list[Subagent]) -> list[dict]:
    """Anzahl Subagenten je Modell, absteigend."""
    zaehler: dict[str, int] = {}
    for s in subagenten:
        modell = s.modell or "?"
        zaehler[modell] = zaehler.get(modell, 0) + 1
    return [{"modell": m, "agenten": n} for m, n in sorted(zaehler.items(), key=lambda kv: -kv[1])]


def cache_anteil(token: Token) -> float | None:
    """Cache-Read ÷ (Eingabe + Cache-Schreiben + Cache-Read) -- ``None`` bei Nenner 0."""
    nenner = token.input + token.cache_write + token.cache_read
    return (token.cache_read / nenner) if nenner else None


def sql_benchmark(projekt: str, quelle: str, sitzung_id: int) -> str:
    """Median der letzten 30 Tage, gleiches Projekt+Quelle, >= 5 Runden, ohne die angezeigte
    Sitzung selbst -- abgenommene Benchmark-Definition (Mockup-Generator ``SQL``/
    ``lade_benchmark``). Ein Aggregat ohne Treffer liefert genau eine Zeile mit ``n = 0`` und
    lauter ``null``-Werten (kein leeres Ergebnis)."""
    je_runde = "greatest((s.dokument->'kennzahlen'->>'runden')::int, 1)"
    return f"""SELECT to_jsonb(t) FROM (
  SELECT count(*) AS n,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY coalesce((s.dokument->'kennzahlen'->>'kosten_gesamt')::numeric, (s.dokument->'kennzahlen'->>'kosten')::numeric) / {je_runde}) AS kosten_je_runde,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->'token'->>'output')::bigint / {je_runde}) AS token_out_je_runde,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'tools')::int / {je_runde}) AS tools_je_runde,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'runden')::int) AS runden,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'latenz_p50_ms')::int) AS latenz_p50_ms,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'latenz_p95_ms')::int) AS latenz_p95_ms,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'tool_fehlerquote')::numeric) AS tool_fehlerquote,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'subagenten')::int) AS subagenten,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY (s.dokument->'kennzahlen'->>'dauer_ms')::bigint / {je_runde}) AS dauer_je_runde_ms
  FROM sitzung_aktuell s
  WHERE s.start > now() - interval '30 days'
    AND s.projekt = {sql_literal(projekt)}
    AND s.quelle = {sql_literal(quelle)}
    AND (s.dokument->'kennzahlen'->>'runden')::int >= {MIN_RUNDEN_BENCHMARK}
    AND s.id <> {int(sitzung_id)}
) t;"""


def benchmark_aus_zeile(zeile: dict | None) -> dict:
    """Roh-Ergebniszeile von ``sql_benchmark`` (oder ``None``, falls ``_wert`` nichts liefert)
    -> Antwort-Form: ``n`` immer ein int, alle anderen Felder ``None`` bei ``n = 0``."""
    z = zeile or {}
    ergebnis = {"n": int(z.get("n") or 0)}
    ergebnis.update({feld: z.get(feld) for feld in BENCHMARK_FELDER})
    return ergebnis


def antwort(beleg, preise: dict | None, benchmark_zeile: dict | None) -> dict:
    """Baut die vollständige ``/api/sitzung/{id}/kacheln``-Antwort aus einem bereits geladenen
    ``Beleg`` und der rohen Benchmark-Ergebniszeile (SQL-Ausführung bleibt Sache des Aufrufers)."""
    runden_liste = runden(beleg.ereignisse, preise)
    top3 = top3_index(runden_liste)
    return {
        "runden": runden_liste,
        "kosten_median_runde": kosten_median_runde(runden_liste),
        "top3_index": top3,
        "top3_anteil": top3_anteil(runden_liste, top3),
        "langsamste_index": langsamste_index(runden_liste),
        "modelle_haupt": modelle_haupt(beleg.ereignisse),
        "modelle_sub": modelle_sub(beleg.subagenten),
        "cache_anteil": cache_anteil(beleg.kennzahlen.token),
        "benchmark": benchmark_aus_zeile(benchmark_zeile),
    }
