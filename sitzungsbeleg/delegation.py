"""Delegation als Kennzahl-Karte (Phase 1 C, Auftrag "Delegation", C5/C8 in CONTRACTS.md)
-- ``GET /api/delegation/{sitzung_id}``.

Fünf Quoten aus Plan `2026-08-27-sitzungsbeleg-prozesslogik-plan.md` Abschnitt 4.6, gegen den
echten Beleg der Referenzsitzung 1284 geprüft (Aufruf 31 %, Kosten 53 %, Output 31 %, Zeit 65 %,
Tools 87 %, 22/22 mit Beleg -- deckt sich exakt). Reine Funktionen auf ``Beleg`` (wie kacheln.py);
Division durch 0 -> 0.0 (Contract). Die Benchmark-SQL ist ein **eigener** Contract (nicht der
Kacheln-Benchmark, Codex-Fund 11): Median über dieselben fünf Quoten, letzte 30 Tage, gleiches
Projekt+Quelle, >= 1 Subagent-Start, ohne die angezeigte Sitzung.
"""
from __future__ import annotations

from .kacheln import modelle_sub
from .kennzahlen import segmentiere_runden
from .modell import ART_SUBAGENT, Beleg
from .speicher import sql_literal

# Antwort-Felder von `DelegationBenchmark` (contracts.py) -- KEINE tool_fehlerquote (C5: eigener
# Contract mit nur fünf Quoten im Benchmark, anders als die volle Delegation-Antwort).
BENCHMARK_FELDER = ("aufruf_quote", "kosten_quote", "output_quote", "zeit_quote", "tool_quote")


def _quote(zaehler: float, nenner: float) -> float:
    """Bruch 0..1 (oder > 1 bei zeit_quote) -- Nenner <= 0 -> 0.0 (Contract "Division durch 0")."""
    return (zaehler / nenner) if nenner else 0.0


def fanout_max(ereignisse: list) -> int:
    """Meiste gleichzeitig gestarteten Subagenten in einer Runde (max je Rundensegment)."""
    segmente = segmentiere_runden(ereignisse)
    zaehler = [sum(1 for e in segment if e.art == ART_SUBAGENT) for segment in segmente]
    return max(zaehler) if zaehler else 0


def _subagent_summen(subs: list[Subagent]) -> dict:
    """Summen über alle Subagenten -- geteilte Basis für mehrere Quoten in `werte()`."""
    return {
        "tools": sum(s.tools for s in subs),
        "fehler": sum(s.tool_fehler for s in subs),
        "dauer": sum(s.dauer_ms or 0 for s in subs),
        "output": sum(s.token.output for s in subs),
    }


def werte(beleg: Beleg) -> dict:
    """Alle Delegation-Felder außer `benchmark` -- SQL-unabhängig, ohne DB testbar."""
    k = beleg.kennzahlen
    subs = beleg.subagenten
    s = _subagent_summen(subs)
    return {
        "aufruf_quote": _quote(len(subs), k.runden),
        "fanout_max": fanout_max(beleg.ereignisse),
        "kosten_quote": _quote(k.kosten_subagenten or 0.0, k.kosten_gesamt or 0.0),
        "output_quote": _quote(s["output"], k.token.output + s["output"]),
        "zeit_quote": _quote(s["dauer"], k.dauer_ms),
        "tool_quote": _quote(s["tools"], k.tools + s["tools"]),
        "tool_fehlerquote": _quote(s["fehler"], s["tools"]),
        "mit_beleg": sum(1 for x in subs if x.beleg == "observed"),
        "starts": len(subs),
        "tiefe_max": k.subagenten_max_tiefe,
        "modelle": modelle_sub(subs),
    }


def _quote_sql(zaehler: str, nenner: str) -> str:
    """SQL-Pendant zu `_quote()`: Nenner <= 0/NULL -> 0 statt Division/NULL."""
    return f"CASE WHEN coalesce({nenner}, 0) > 0 THEN {zaehler} / {nenner} ELSE 0 END"


def _cte_subagenten(projekt: str, quelle: str, sitzung_id: int) -> str:
    """Subagenten-Summen (Tools/Dauer/Token-Output) je Sitzung -- LATERAL-Aggregation über
    `dokument->'subagenten'`, gefiltert auf den Benchmark-Ausschnitt (Codex-Fund 11)."""
    return f"""WITH sub AS (
  SELECT s.id, count(*) AS n_sub,
    coalesce(sum((sa->>'tools')::int), 0) AS sub_tools,
    coalesce(sum((sa->>'dauer_ms')::bigint), 0) AS sub_dauer,
    coalesce(sum((sa->'token'->>'output')::bigint), 0) AS sub_output
  FROM sitzung_aktuell s
  CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.dokument->'subagenten', '[]'::jsonb)) sa
  WHERE s.start > now() - interval '30 days'
    AND s.projekt = {sql_literal(projekt)} AND s.quelle = {sql_literal(quelle)}
    AND s.id <> {int(sitzung_id)}
  GROUP BY s.id
)"""


def _sql_quoten() -> str:
    """Die fünf Median-Ausdrücke -- gleiche Rechnung wie `werte()`, in SQL nachgebaut."""
    haupt_out = "coalesce((s.dokument->'kennzahlen'->'token'->>'output')::bigint, 0)"
    haupt_tools = "coalesce((s.dokument->'kennzahlen'->>'tools')::int, 0)"
    kosten_gesamt = "(s.dokument->'kennzahlen'->>'kosten_gesamt')::numeric"
    kosten_sub = "coalesce((s.dokument->'kennzahlen'->>'kosten_subagenten')::numeric, 0)"
    dauer_ms = "(s.dokument->'kennzahlen'->>'dauer_ms')::bigint"
    runden = "greatest((s.dokument->'kennzahlen'->>'runden')::int, 1)"
    return f"""count(*) AS n,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY sub.n_sub::numeric / {runden}) AS aufruf_quote,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY {_quote_sql(kosten_sub, kosten_gesamt)}) AS kosten_quote,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY
      {_quote_sql("sub.sub_output::numeric", f"(sub.sub_output + {haupt_out})")}) AS output_quote,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY {_quote_sql("sub.sub_dauer::numeric", dauer_ms)}) AS zeit_quote,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY
      {_quote_sql("sub.sub_tools::numeric", f"(sub.sub_tools + {haupt_tools})")}) AS tool_quote"""


def sql_benchmark(projekt: str, quelle: str, sitzung_id: int) -> str:
    """Median der fünf Quoten, letzte 30 Tage, gleiches Projekt+Quelle, >= 1 Subagent-Start,
    ohne die angezeigte Sitzung (Codex-Fund 11, eigener Contract -- nicht der Kacheln-Benchmark)."""
    return f"""{_cte_subagenten(projekt, quelle, sitzung_id)}
SELECT to_jsonb(t) FROM (
  SELECT {_sql_quoten()}
  FROM sitzung_aktuell s JOIN sub ON sub.id = s.id
  WHERE sub.n_sub >= 1
) t;"""


def benchmark_aus_zeile(zeile: dict | None) -> dict:
    """Roh-Ergebniszeile von `sql_benchmark` -> Antwort-Form: `n=0` erzwingt lauter `None`
    (Contract-Validator `DelegationBenchmark`), unabhängig davon, was die SQL zurückgibt."""
    z = zeile or {}
    n = int(z.get("n") or 0)
    ergebnis = {"n": n}
    ergebnis.update({feld: (z.get(feld) if n else None) for feld in BENCHMARK_FELDER})
    return ergebnis


def antwort(beleg: Beleg, benchmark_zeile: dict | None) -> dict:
    """Baut die vollständige `/api/delegation/{id}`-Antwort (contracts.Delegation)."""
    ergebnis = werte(beleg)
    ergebnis["benchmark"] = benchmark_aus_zeile(benchmark_zeile)
    return ergebnis
