"""Tests für delegation.py -- Delegation als Kennzahl-Karte (Phase 1 C, CONTRACTS.md C5/C8).

Referenzwerte Sitzung 1284 (Plan 4.6): 31 % der Runden, 53 % der Kosten, 31 % der Output-Token,
65 % der Zeit, 87 % der Werkzeugaufrufe, 22/22 mit Beleg -- gegen den echten Beleg geprüft
(``test_werte_gegen_echte_sitzung_1284``, übersprungen ohne DB-Zugriff)."""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from .. import contracts, delegation, speicher, web
from ..modell import Beleg, Kopf, Subagent, Token
from .hilfen import baue_beleg, nutzer_runde, subagent_start

PREISE = {"claude-sonnet-5": {"input": 1, "output": 1}}


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


def _sub(agent_id: str, tools: int = 0, tool_fehler: int = 0, dauer_ms: int = 0,
         token_output: int = 0, beleg: str = "observed", tiefe: int = 1) -> Subagent:
    return Subagent(
        agent_id=agent_id, modell="claude-sonnet-5", tools=tools, tool_fehler=tool_fehler,
        dauer_ms=dauer_ms, token=Token(output=token_output), beleg=beleg, tiefe=tiefe,
    )


def _beleg_zwei_subagenten() -> Beleg:
    """Zwei Runden mit je einem Subagent-Start in Runde 1 -- Fan-out max = 1."""
    ereignisse = [nutzer_runde(), subagent_start(), nutzer_runde()]
    subagenten = [
        _sub("s1", tools=10, tool_fehler=1, dauer_ms=60_000, token_output=500),
        _sub("s2", tools=5, tool_fehler=0, dauer_ms=30_000, token_output=300, beleg="not_observed"),
    ]
    beleg = baue_beleg(ereignisse=ereignisse, subagenten=subagenten)
    k = beleg.kennzahlen
    k.runden = 2
    k.tools = 20
    k.dauer_ms = 300_000
    k.kosten = 1.0
    k.kosten_subagenten = 1.5
    k.kosten_gesamt = 2.5
    k.token.output = 1_000
    k.subagenten_max_tiefe = 1
    return beleg


class WerteTest(unittest.TestCase):
    def test_werte_liefert_alle_fuenf_quoten(self) -> None:
        beleg = _beleg_zwei_subagenten()
        w = delegation.werte(beleg)
        self.assertAlmostEqual(w["aufruf_quote"], 2 / 2)
        self.assertEqual(w["fanout_max"], 1)
        self.assertAlmostEqual(w["kosten_quote"], 1.5 / 2.5)
        self.assertAlmostEqual(w["output_quote"], 800 / 1800)
        self.assertAlmostEqual(w["zeit_quote"], 90_000 / 300_000)
        self.assertAlmostEqual(w["tool_quote"], 15 / 35)
        self.assertAlmostEqual(w["tool_fehlerquote"], 1 / 15)
        self.assertEqual(w["mit_beleg"], 1)
        self.assertEqual(w["starts"], 2)
        self.assertEqual(w["tiefe_max"], 1)
        self.assertEqual(w["modelle"], [{"modell": "claude-sonnet-5", "agenten": 2}])

    def test_werte_erfuellt_den_contract(self) -> None:
        beleg = _beleg_zwei_subagenten()
        antwort = delegation.antwort(beleg, None)
        contracts.validiere("delegation", antwort)  # wirft bei Verstoss

    def test_ohne_subagenten_ist_alles_null_division_0(self) -> None:
        beleg = baue_beleg()
        w = delegation.werte(beleg)
        self.assertEqual(w["aufruf_quote"], 0.0)
        self.assertEqual(w["fanout_max"], 0)
        self.assertEqual(w["kosten_quote"], 0.0)
        self.assertEqual(w["output_quote"], 0.0)
        self.assertEqual(w["zeit_quote"], 0.0)
        self.assertEqual(w["tool_quote"], 0.0)
        self.assertEqual(w["tool_fehlerquote"], 0.0)
        self.assertEqual(w["starts"], 0)
        self.assertEqual(w["modelle"], [])

    def test_zeit_quote_darf_ueber_1_liegen_bei_parallelen_subagenten(self) -> None:
        beleg = baue_beleg(subagenten=[_sub("s1", dauer_ms=500_000), _sub("s2", dauer_ms=500_000)])
        beleg.kennzahlen.dauer_ms = 300_000
        w = delegation.werte(beleg)
        self.assertAlmostEqual(w["zeit_quote"], 1_000_000 / 300_000)

    def test_fanout_max_zaehlt_je_runde_getrennt(self) -> None:
        ereignisse = [
            nutzer_runde(), subagent_start(), subagent_start(), subagent_start(),
            nutzer_runde(), subagent_start(),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        self.assertEqual(delegation.fanout_max(beleg.ereignisse), 3)


class BenchmarkSqlTest(unittest.TestCase):
    def test_sql_enthaelt_zeitraum_projekt_quelle_mindeststart_und_ausschluss(self) -> None:
        sql = delegation.sql_benchmark("00_Workspace", "claude", 1284)
        self.assertIn("FROM sitzung_aktuell s", sql)
        self.assertIn("interval '30 days'", sql)
        self.assertIn("s.projekt = '00_Workspace'", sql)
        self.assertIn("s.quelle = 'claude'", sql)
        self.assertIn("sub.n_sub >= 1", sql)
        self.assertIn("s.id <> 1284", sql)

    def test_benchmark_aus_zeile_n_0_heisst_alles_null(self) -> None:
        self.assertEqual(delegation.benchmark_aus_zeile(None), {
            "n": 0, "aufruf_quote": None, "kosten_quote": None, "output_quote": None,
            "zeit_quote": None, "tool_quote": None,
        })

    def test_benchmark_aus_zeile_gibt_zahlen_durch(self) -> None:
        zeile = {
            "n": 60, "aufruf_quote": 0.2, "kosten_quote": 0.4, "output_quote": 0.25,
            "zeit_quote": 0.5, "tool_quote": 0.7,
        }
        self.assertEqual(delegation.benchmark_aus_zeile(zeile), zeile)

    def test_benchmark_erzwingt_null_auch_bei_unsauberer_sql_zeile(self) -> None:
        """Contract-Garantie unabhaengig von der SQL: n=0 -> alle Quoten None, selbst wenn die
        (Fake-)Zeile faelschlich Zahlen mitliefert."""
        zeile = {"n": 0, "aufruf_quote": 0.9}
        ergebnis = delegation.benchmark_aus_zeile(zeile)
        self.assertTrue(all(ergebnis[f] is None for f in delegation.BENCHMARK_FELDER))


class DelegationEndpunktTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer

    def test_nicht_gefunden_liefert_404(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/delegation/999")
        self.assertEqual(antwort.status_code, 404)

    def test_endpunkt_liefert_contract_konforme_antwort(self) -> None:
        beleg = _beleg_zwei_subagenten()
        beleg.kopf = Kopf(quelle="claude", sitzung_id="deleg-test", projekt_name="TestProjekt",
                          start="2026-08-25T10:00:00Z", ende="2026-08-25T11:00:00Z")
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({
            "sitzung_aktuell WHERE logisch_ref = 3": "7",   # logische ID 3 -> juengste Version 7
            "FROM sitzung WHERE id = 7": json.dumps(dokument),
        }, default="null")

        antwort = self.client.get("/api/delegation/3")

        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        contracts.validiere("delegation", daten)
        self.assertAlmostEqual(daten["kosten_quote"], 1.5 / 2.5)
        self.assertEqual(daten["benchmark"]["n"], 0)
        self.assertIsNone(daten["benchmark"]["kosten_quote"])
        benchmark_sql = [s for s in web.LAUFER.aufrufe if "FROM sitzung_aktuell s" in s][0]
        self.assertIn("s.projekt = 'TestProjekt'", benchmark_sql)
        self.assertIn("s.quelle = 'claude'", benchmark_sql)
        self.assertIn("s.id <> 7", benchmark_sql)


class Sitzung1284Test(unittest.TestCase):
    """Referenzwerte gegen den echten Beleg (Plan 4.6) -- uebersprungen ohne DB-Zugriff."""

    def test_werte_gegen_echte_sitzung_1284(self) -> None:
        try:
            dokument = speicher.lade_dokument(1284)
        except Exception as fehler:  # pragma: no cover -- kein DB-Zugriff in CI
            self.skipTest(f"DB nicht erreichbar: {fehler}")
        from .. import __main__ as cli

        beleg = cli._beleg_aus_dict(dokument)
        w = delegation.werte(beleg)
        self.assertAlmostEqual(w["aufruf_quote"], 0.31, delta=0.01)
        self.assertAlmostEqual(w["kosten_quote"], 0.53, delta=0.01)
        self.assertAlmostEqual(w["output_quote"], 0.31, delta=0.01)
        self.assertAlmostEqual(w["zeit_quote"], 0.65, delta=0.01)
        self.assertAlmostEqual(w["tool_quote"], 0.87, delta=0.01)
        self.assertEqual(w["mit_beleg"], 22)
        self.assertEqual(w["starts"], 22)
        self.assertEqual(w["tiefe_max"], 1)
        self.assertEqual(w["fanout_max"], 4)
        contracts.validiere("delegation", delegation.antwort(beleg, None))


if __name__ == "__main__":
    unittest.main()
