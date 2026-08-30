"""Tests für kacheln.py -- rundenweise Kennzahlen + Live-Benchmark der Sitzungsseite
(Auftrag „Kacheln", 2026-08-27)."""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from .. import __main__ as cli
from .. import kacheln, kennzahlen, web
from ..modell import Beleg, Kopf, Subagent, Token
from .hilfen import assistent, baue_beleg, compaction, nutzer_runde, runde_ende, subagent_start, tool, tool_ergebnis

PREISE = {"claude-fable-5": {"input": 1}, "claude-opus-5": {"input": 1}}


class FakeLaufer:
    """Wie in test_web.py: antwortet nach dem ersten passenden Substring, Reihenfolge egal."""

    def __init__(self, antworten: dict[str, str], default: str = "[]"):
        self.antworten = antworten
        self.default = default
        self.aufrufe: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.aufrufe.append(sql)
        for muster, antwort in self.antworten.items():
            if muster in sql:
                return antwort
        return self.default


def _beleg_mit_vier_runden() -> Beleg:
    """Vier Runden: Modellwechsel Haupt (fable -> opus), eine Compaction, ein Werkzeug-Timeout
    (>= 120 s), ein Subagent-Start, ein Tool-Fehler; Subagenten sonnet + haiku."""
    timeout_tool = tool("Bash", ref="t1")
    timeout_tool.dauer_ms = 130_000
    subagenten = [
        Subagent(agent_id="s1", modell="claude-sonnet-5", token=Token()),
        Subagent(agent_id="s2", modell="claude-haiku-5", token=Token()),
    ]
    ereignisse = [
        nutzer_runde(),
        assistent(Token(input=1_000_000), name="claude-fable-5"),
        runde_ende(30_000),
        nutzer_runde(),
        assistent(Token(input=2_000_000), name="claude-fable-5"),
        timeout_tool,
        runde_ende(40_000),
        nutzer_runde(),
        compaction(),
        assistent(Token(input=3_000_000), name="claude-opus-5"),
        subagent_start(),
        runde_ende(20_000),
        nutzer_runde(),
        assistent(Token(input=4_000_000), name="claude-opus-5"),
        tool_ergebnis(fehler=True),
        runde_ende(10_000),
    ]
    beleg = baue_beleg(
        ereignisse=ereignisse,
        subagenten=subagenten,
        kopf=Kopf(quelle="claude", sitzung_id="kacheln-test", projekt_name="TestProjekt",
                  start="2026-08-25T10:00:00Z", ende="2026-08-25T11:00:00Z"),
    )
    kennzahlen.berechne(beleg, PREISE, "USD")
    return beleg


class RundenTest(unittest.TestCase):
    def test_runden_traegt_alle_felder_je_runde(self) -> None:
        beleg = _beleg_mit_vier_runden()
        r = kacheln.runden(beleg.ereignisse, PREISE)
        self.assertEqual([x["index"] for x in r], [1, 2, 3, 4])
        self.assertEqual([x["kosten"] for x in r], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual([x["compaction"] for x in r], [False, False, True, False])
        self.assertEqual([x["timeout"] for x in r], [False, True, False, False])
        self.assertEqual([x["subagent_starts"] for x in r], [0, 0, 1, 0])
        self.assertEqual([x["tool_fehler"] for x in r], [0, 0, 0, 1])
        self.assertEqual([x["dauer_ms"] for x in r], [30_000, 40_000, 20_000, 10_000])

    def test_runden_vor_erster_nutzerzeile_werden_ignoriert(self) -> None:
        vorlauf = tool("Bash")
        ereignisse = [vorlauf, nutzer_runde(), assistent(Token(input=1_000_000), name="claude-fable-5")]
        beleg = baue_beleg(ereignisse=ereignisse)
        r = kacheln.runden(beleg.ereignisse, PREISE)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["kosten"], 1.0)

    def test_kosten_median_runde(self) -> None:
        beleg = _beleg_mit_vier_runden()
        r = kacheln.runden(beleg.ereignisse, PREISE)
        self.assertEqual(kacheln.kosten_median_runde(r), 2.5)

    def test_kosten_median_runde_ohne_positive_kosten_ist_none(self) -> None:
        self.assertIsNone(kacheln.kosten_median_runde([{"kosten": 0}, {"kosten": 0}]))

    def test_top3_index_und_anteil(self) -> None:
        beleg = _beleg_mit_vier_runden()
        r = kacheln.runden(beleg.ereignisse, PREISE)
        idx = kacheln.top3_index(r)
        self.assertEqual(idx, [3, 2, 1])
        self.assertAlmostEqual(kacheln.top3_anteil(r, idx), 0.9)

    def test_top3_anteil_ohne_kosten_ist_none(self) -> None:
        self.assertIsNone(kacheln.top3_anteil([{"kosten": 0}], [0]))

    def test_langsamste_index(self) -> None:
        beleg = _beleg_mit_vier_runden()
        r = kacheln.runden(beleg.ereignisse, PREISE)
        self.assertEqual(kacheln.langsamste_index(r), [1, 0, 2])

    def test_modelle_haupt_zeigt_wechsel_fable_zu_opus(self) -> None:
        beleg = _beleg_mit_vier_runden()
        self.assertEqual(
            kacheln.modelle_haupt(beleg.ereignisse),
            [{"modell": "claude-fable-5", "aufrufe": 2}, {"modell": "claude-opus-5", "aufrufe": 2}],
        )

    def test_modelle_sub_zeigt_sonnet_und_haiku(self) -> None:
        beleg = _beleg_mit_vier_runden()
        self.assertEqual(
            kacheln.modelle_sub(beleg.subagenten),
            [{"modell": "claude-sonnet-5", "agenten": 1}, {"modell": "claude-haiku-5", "agenten": 1}],
        )

    def test_cache_anteil(self) -> None:
        beleg = baue_beleg(
            ereignisse=[assistent(Token(input=100, cache_write=100, cache_read=800), name="m")]
        )
        kennzahlen.berechne(beleg, {"m": {"input": 1, "output": 1}})
        self.assertAlmostEqual(kacheln.cache_anteil(beleg.kennzahlen.token), 0.8)

    def test_cache_anteil_ohne_nenner_ist_none(self) -> None:
        self.assertIsNone(kacheln.cache_anteil(Token()))


class BenchmarkSqlTest(unittest.TestCase):
    def test_sql_enthaelt_zeitraum_projekt_quelle_mindestrunden_und_ausschluss(self) -> None:
        sql = kacheln.sql_benchmark("00_Workspace", "claude", 1284)
        self.assertIn("FROM sitzung_aktuell s", sql)
        self.assertIn("interval '30 days'", sql)
        self.assertIn("s.projekt = '00_Workspace'", sql)
        self.assertIn("s.quelle = 'claude'", sql)
        self.assertIn(">= 5", sql)
        self.assertIn("s.id <> 1284", sql)

    def test_benchmark_aus_zeile_liefert_none_werte_bei_leerer_zeile(self) -> None:
        self.assertEqual(kacheln.benchmark_aus_zeile(None), {
            "n": 0, "kosten_je_runde": None, "token_out_je_runde": None, "tools_je_runde": None,
            "runden": None, "latenz_p50_ms": None, "latenz_p95_ms": None, "tool_fehlerquote": None,
            "subagenten": None, "dauer_je_runde_ms": None,
        })

    def test_benchmark_aus_zeile_gibt_zahlen_durch(self) -> None:
        zeile = {
            "n": 12, "kosten_je_runde": 2.5, "token_out_je_runde": 1000.0, "tools_je_runde": 4.0,
            "runden": 20.0, "latenz_p50_ms": 30000.0, "latenz_p95_ms": 90000.0,
            "tool_fehlerquote": 0.05, "subagenten": 2.0, "dauer_je_runde_ms": 120000.0,
        }
        self.assertEqual(kacheln.benchmark_aus_zeile(zeile), zeile)


class KachelnEndpunktTest(unittest.TestCase):
    """Der Endpunkt lädt Preise live über ``__main__._lade_preise`` (wie ``api_preise`` --
    Vertrag: aktuelle Listenpreise, nicht die zum Ingest-Zeitpunkt gültigen). Für reproduzierbare
    Kosten in diesen Tests wird das auf die feste ``PREISE``-Tabelle umgebogen."""

    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_preise = cli._lade_preise
        cli._lade_preise = lambda pfad: (PREISE, "USD")
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        cli._lade_preise = self.alt_preise

    def test_kacheln_nicht_gefunden_liefert_404(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/sitzung/999/kacheln")
        self.assertEqual(antwort.status_code, 404)

    def test_kacheln_liefert_erwartete_antwortform(self) -> None:
        beleg = _beleg_mit_vier_runden()
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({
            "sitzung_aktuell WHERE logisch_ref = 7": "7",
            "FROM sitzung WHERE id = 7": json.dumps(dokument),
        }, default="null")

        antwort = self.client.get("/api/sitzung/7/kacheln")

        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(len(daten["runden"]), 4)
        self.assertEqual(daten["top3_index"], [3, 2, 1])
        self.assertAlmostEqual(daten["top3_anteil"], 0.9)
        self.assertEqual(daten["kosten_median_runde"], 2.5)
        self.assertEqual(daten["langsamste_index"], [1, 0, 2])
        self.assertEqual(len(daten["modelle_haupt"]), 2)
        self.assertEqual(len(daten["modelle_sub"]), 2)
        self.assertEqual(daten["benchmark"]["n"], 0)
        self.assertIsNone(daten["benchmark"]["kosten_je_runde"])
        # Benchmark-SQL nutzt Projekt/Quelle aus dem geladenen Dokument, nicht der Kacheln-Antwort:
        benchmark_sql = [s for s in web.LAUFER.aufrufe if "FROM sitzung_aktuell s" in s][0]
        self.assertIn("s.projekt = 'TestProjekt'", benchmark_sql)
        self.assertIn("s.quelle = 'claude'", benchmark_sql)
        self.assertIn("s.id <> 7", benchmark_sql)


if __name__ == "__main__":
    unittest.main()
