"""Seite "Fehlerbilder & Entscheide" (Phase 2 G): Aggregat + Drilldown, Fake-Laufer wie test_web.py."""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from .. import fehlerbilder, web
from .test_web import FakeLaufer


class FehlerbilderAggregatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = fehlerbilder.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        fehlerbilder.LAUFER = self.alt

    def test_gruppiert_vorkommen_je_signatur_ueber_sitzungen(self) -> None:
        vorkommen = [
            {"signatur": "rework:tool:Bash", "regel": "rework:tool", "sitzung_logisch": 1,
             "projekt": "00_Workspace", "zeit": "2026-08-20T10:00:00+00:00"},
            {"signatur": "rework:tool:Bash", "regel": "rework:tool", "sitzung_logisch": 2,
             "projekt": "00_Workspace", "zeit": "2026-08-25T10:00:00+00:00"},
            {"signatur": "cost:spike", "regel": "cost:spike", "sitzung_logisch": 3,
             "projekt": "Beispielprojekt", "zeit": "2026-08-22T10:00:00+00:00"},
        ]
        fehlerbilder.LAUFER = FakeLaufer({
            "FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s": json.dumps(vorkommen),
        }, default="[]")
        antwort = self.client.get("/api/fehlerbilder", params={"von": "2026-08-19", "bis": "2026-08-26"})
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(len(daten), 2)
        bash = next(z for z in daten if z["signatur"] == "rework:tool:Bash")
        self.assertEqual(bash["anzahl_sitzungen"], 2)
        self.assertEqual(bash["projekte"], ["00_Workspace"])
        self.assertEqual(bash["juengstes_vorkommen"], "2026-08-25T10:00:00+00:00")
        self.assertEqual(bash["regeltext"]["titel"], "Werkzeug-Nacharbeit")
        self.assertEqual(bash["gruppenstatus"], "offen")
        self.assertEqual(bash["status_verteilung"], {"offen": 2})
        self.assertFalse(bash["rueckfall"])
        self.assertIsNone(bash["gf_entscheid"])
        # Sortiert nach Anzahl Sitzungen absteigend -- Bash (2) vor cost:spike (1).
        self.assertEqual(daten[0]["signatur"], "rework:tool:Bash")

    def test_legacy_vieraugen_urteil_treibt_gruppenstatus(self) -> None:
        """Nachtrag 2026-08-27 Punkt 1: die Fehlerbilder-Seite aggregiert ueber viele Sitzungen --
        derselbe Legacy-Vieraugen-Fix wie bei `pruefung.anreichern` muss hier ebenso greifen."""
        vorkommen = [
            {"signatur": "rework:tool:Bash", "regel": "rework:tool", "sitzung_logisch": 1,
             "projekt": "00_Workspace", "zeit": "2026-08-20T10:00:00+00:00"},
        ]
        vieraugen = {"sitzung_logisch": 1, "befunde": [{"signatur": "rework:tool:Bash", "status": "bestaetigt"}]}
        fehlerbilder.LAUFER = FakeLaufer({
            "FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s": json.dumps(vorkommen),
            "quelle = 'vieraugen'": json.dumps([vieraugen]),
        }, default="[]")
        antwort = self.client.get("/api/fehlerbilder", params={"von": "2026-08-19", "bis": "2026-08-26"})
        zeile = antwort.json()[0]
        self.assertEqual(zeile["gruppenstatus"], "bestaetigt")
        self.assertEqual(zeile["status_verteilung"], {"bestaetigt": 1})

    def test_leer_wenn_keine_vorkommen_im_zeitraum(self) -> None:
        fehlerbilder.LAUFER = FakeLaufer({}, default="[]")
        antwort = self.client.get("/api/fehlerbilder", params={"von": "2026-08-19", "bis": "2026-08-26"})
        self.assertEqual(antwort.json(), [])

    def test_globaler_entscheid_nach_neuer_sitzung_ist_rueckfall(self) -> None:
        """C2 Ableitungsregel Schritt 1 Ausnahme: eine Sitzung NACH einem globalen `erledigt`-
        Entscheid zaehlt als Rueckfall, nicht als erledigt."""
        vorkommen = [
            {"signatur": "abc", "regel": "error:recurring", "sitzung_logisch": 5,
             "projekt": "00_Workspace", "zeit": "2026-08-25T10:00:00+00:00"},
        ]
        entscheid = {
            "signatur": "abc", "sitzung_ref": None, "status": "erledigt",
            "entschieden_am": "2026-08-20T00:00:00+00:00",
        }
        fehlerbilder.LAUFER = FakeLaufer({
            "FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s": json.dumps(vorkommen),
            "typ = 'befund_entscheid'": json.dumps([entscheid]),
        }, default="[]")
        antwort = self.client.get("/api/fehlerbilder", params={"von": "2026-08-19", "bis": "2026-08-26"})
        zeile = antwort.json()[0]
        self.assertEqual(zeile["gruppenstatus"], "rueckfall")
        self.assertTrue(zeile["rueckfall"])
        self.assertEqual(zeile["gf_entscheid"]["status"], "erledigt")


class FehlerbildDrilldownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = fehlerbilder.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        fehlerbilder.LAUFER = self.alt

    def test_drilldown_liefert_sitzungen_mit_status_und_letzten_lauf(self) -> None:
        vorkommen = [
            {"signatur": "rework:tool:Bash", "regel": "rework:tool", "sitzung_logisch": 1,
             "projekt": "00_Workspace", "zeit": "2026-08-20T10:00:00+00:00"},
            {"signatur": "rework:tool:Bash", "regel": "rework:tool", "sitzung_logisch": 2,
             "projekt": "00_Workspace", "zeit": "2026-08-25T10:00:00+00:00"},
        ]
        lauf = {
            "schema": 1, "lauf_id": "p-20260826-120000-abcd", "scope": "fehlerbild",
            "sitzung_logisch": None, "signaturen": ["rework:tool:Bash"], "stufe_max": 2,
            "modell_stufe1": "claude-sonnet-5", "modell_stufe2": "gpt-5.5",
            "gestartet": "2026-08-26T12:00:00+00:00", "dauer_ms": 1000, "urteile": [],
            "sitzungen": [1, 2],
            "tabelle": [{"sitzung_logisch": 1, "einordnung": "sauber"},
                        {"sitzung_logisch": 2, "einordnung": "abgewichen"}],
            "datei": "_work/2026-08-26-standardisierung-rework-tool-bash.md",
            "fehler": None,
        }
        fehlerbilder.LAUFER = FakeLaufer({
            "FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s": json.dumps(vorkommen),
            "scope' = 'fehlerbild'": json.dumps(lauf),
        }, default="[]")
        antwort = self.client.get(
            "/api/fehlerbild/rework:tool:Bash", params={"von": "2026-08-19", "bis": "2026-08-26"}
        )
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(len(daten["sitzungen_liste"]), 2)
        # neueste zuerst
        self.assertEqual(daten["sitzungen_liste"][0]["sitzung_logisch"], 2)
        self.assertEqual(daten["sitzungen_liste"][0]["status"], "offen")
        self.assertEqual(daten["letzter_fehlerbild_lauf"]["tabelle"][1]["einordnung"], "abgewichen")
        self.assertEqual(daten["letzter_fehlerbild_lauf"]["datei"], lauf["datei"])

    def test_drilldown_ohne_lauf_liefert_null(self) -> None:
        vorkommen = [
            {"signatur": "cost:spike", "regel": "cost:spike", "sitzung_logisch": 9,
             "projekt": "00_Workspace", "zeit": "2026-08-22T10:00:00+00:00"},
        ]
        fehlerbilder.LAUFER = FakeLaufer({
            "FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s": json.dumps(vorkommen),
            # kein Treffer -> psql liefert 0 Zeilen (leere Ausgabe), nicht "null" (das waere
            # eine Zeile mit einem NULL-Wert) -- `_wert` macht daraus None.
            "scope' = 'fehlerbild'": "",
        }, default="[]")
        antwort = self.client.get(
            "/api/fehlerbild/cost:spike", params={"von": "2026-08-19", "bis": "2026-08-26"}
        )
        self.assertIsNone(antwort.json()["letzter_fehlerbild_lauf"])

    def test_drilldown_unbekannte_signatur_404(self) -> None:
        fehlerbilder.LAUFER = FakeLaufer({}, default="[]")
        antwort = self.client.get(
            "/api/fehlerbild/unbekannt", params={"von": "2026-08-19", "bis": "2026-08-26"}
        )
        self.assertEqual(antwort.status_code, 404)


if __name__ == "__main__":
    unittest.main()
