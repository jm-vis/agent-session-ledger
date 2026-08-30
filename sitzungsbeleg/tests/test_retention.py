"""Tests fuer retention.py (CLI `retention-sql`, CONTRACTS.md Abschnitt "Retention") --
Fake-LAUFER wie in test_reingest.py/test_speicher_querschnitt.py, keine echte DB noetig."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .. import __main__ as main_mod
from .. import quellen, retention


class FakePsql:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else ""


REGISTRY = {
    "preise": {"modelle": {"claude-sonnet-5": {"herkunft": "anthropic"}}},
    "modelle": {"glm-5.2:cloud": {"herkunft": "ollama"}},
}


class PruefeArgumenteTest(unittest.TestCase):
    def test_aelter_als_unter_mindest_wird_abgelehnt(self) -> None:
        with self.assertRaises(retention.RetentionFehler):
            retention.pruefe_argumente(6, "alle")

    def test_aelter_als_genau_mindest_ist_erlaubt(self) -> None:
        self.assertEqual(retention.pruefe_argumente(7, "alle"), "alle")

    def test_fehlende_quelle_wird_abgelehnt_mit_hinweis(self) -> None:
        with self.assertRaises(retention.RetentionFehler) as ctx:
            retention.pruefe_argumente(30, None)
        self.assertIn("alle", str(ctx.exception))

    def test_leere_quelle_wird_abgelehnt(self) -> None:
        with self.assertRaises(retention.RetentionFehler):
            retention.pruefe_argumente(30, "")

    def test_unbekannte_quelle_wird_abgelehnt(self) -> None:
        with self.assertRaises(retention.RetentionFehler):
            retention.pruefe_argumente(30, "sonstwas")

    def test_alle_bekannten_quellen_sind_gueltig(self) -> None:
        for q in ("alle", "claude", "codex", "ollama", "openrouter", "requesty"):
            self.assertEqual(retention.pruefe_argumente(30, q), q)


class BetroffeneSitzungenTest(unittest.TestCase):
    def _antwort(self, zeilen: list[dict]) -> FakePsql:
        return FakePsql([json.dumps(zeilen)])

    def test_leere_antwort_liefert_leere_liste(self) -> None:
        fake = FakePsql([""])
        treffer = retention.betroffene_sitzungen("pc", "alle", 30, fake)
        self.assertEqual(treffer, [])

    def test_frische_sitzung_wird_nicht_erfasst(self) -> None:
        from datetime import datetime, timedelta, timezone

        frisch = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        fake = self._antwort([{"logisch_ref": 1, "beginn": frisch, "quelle": "claude", "modelle": []}])
        treffer = retention.betroffene_sitzungen("pc", "alle", 30, fake)
        self.assertEqual(treffer, [])

    def test_alte_sitzung_wird_erfasst(self) -> None:
        from datetime import datetime, timedelta, timezone

        alt = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        fake = self._antwort([{"logisch_ref": 7, "beginn": alt, "quelle": "claude", "modelle": []}])
        treffer = retention.betroffene_sitzungen("pc", "alle", 30, fake)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0]["logisch_ref"], 7)
        self.assertEqual(treffer[0]["quelle_anzeige"], quellen.CLAUDE)

    def test_quelle_filter_laesst_andere_anzeige_quellen_weg(self) -> None:
        from datetime import datetime, timedelta, timezone

        alt = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        fake = self._antwort([
            {"logisch_ref": 1, "beginn": alt, "quelle": "claude", "modelle": []},
            {"logisch_ref": 2, "beginn": alt, "quelle": "codex", "modelle": ["gpt-5.5"]},
            {"logisch_ref": 3, "beginn": alt, "quelle": "claude", "modelle": ["glm-5.2:cloud"]},
        ])
        treffer = retention.betroffene_sitzungen("pc", "ollama", 30, fake, registry=REGISTRY)
        self.assertEqual([t["logisch_ref"] for t in treffer], [3])

    def test_backend_requesty_wird_ueber_quelle_filter_gefunden(self) -> None:
        """Nachtrag Requesty: `backend` (Stop-Hook-Hostklasse) muss aus der SQL-Zeile bis in
        `quelle_fuer` durchgereicht werden -- eine `claude`-Zeile mit `backend=requesty` zaehlt
        als Requesty, nicht als Claude."""
        from datetime import datetime, timedelta, timezone

        alt = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        fake = self._antwort([
            {"logisch_ref": 1, "beginn": alt, "quelle": "claude", "modelle": ["claude-sonnet-5"]},
            {"logisch_ref": 2, "beginn": alt, "quelle": "claude", "modelle": ["claude-sonnet-5"],
             "backend": "requesty"},
        ])
        treffer = retention.betroffene_sitzungen("pc", "requesty", 30, fake, registry=REGISTRY)
        self.assertEqual([t["logisch_ref"] for t in treffer], [2])

    def test_alle_nimmt_jede_anzeige_quelle(self) -> None:
        from datetime import datetime, timedelta, timezone

        alt = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        fake = self._antwort([
            {"logisch_ref": 1, "beginn": alt, "quelle": "claude", "modelle": []},
            {"logisch_ref": 2, "beginn": alt, "quelle": "codex", "modelle": ["gpt-5.5"]},
        ])
        treffer = retention.betroffene_sitzungen("pc", "alle", 30, fake, registry=REGISTRY)
        self.assertEqual({t["logisch_ref"] for t in treffer}, {1, 2})

    def test_sql_filtert_auf_host_und_liest_sitzung_aktuell(self) -> None:
        fake = FakePsql([""])
        retention.betroffene_sitzungen("orb", "alle", 30, fake)
        self.assertIn("host = 'orb'", fake.sql[0])
        self.assertIn("sitzung_aktuell", fake.sql[0])


class BaueDateiTest(unittest.TestCase):
    def test_keine_treffer_erzeugt_keine_transaktion(self) -> None:
        text = retention.baue_datei([], 30, "alle")
        self.assertNotIn("BEGIN;", text)
        self.assertNotIn("DELETE FROM", text)
        self.assertIn("\\set ON_ERROR_STOP on", text)

    def test_treffer_erzeugen_transaktion_in_fk_reihenfolge(self) -> None:
        text = retention.baue_datei(
            [{"logisch_ref": 5, "beginn": "2026-01-01T00:00:00+00:00", "quelle_anzeige": "Claude"}],
            30, "claude",
        )
        self.assertIn("BEGIN;", text)
        self.assertIn("COMMIT;", text)
        self.assertIn("\\set ON_ERROR_STOP on", text)
        self.assertIn("RAISE NOTICE", text)
        reihenfolge = [
            "DELETE FROM chat",
            "DELETE FROM ereignis",
            "DELETE FROM sitzung_auffaelligkeit",
            "DELETE FROM sitzung ",
            "DELETE FROM sitzung_logisch",
        ]
        positionen = [text.index(teil) for teil in reihenfolge]
        self.assertEqual(positionen, sorted(positionen))
        for teil in reihenfolge:
            self.assertIn("5", text[text.index(teil):text.index(teil) + 200])

    def test_ids_stehen_in_jeder_delete_zeile(self) -> None:
        text = retention.baue_datei(
            [
                {"logisch_ref": 5, "beginn": "x", "quelle_anzeige": "Claude"},
                {"logisch_ref": 9, "beginn": "x", "quelle_anzeige": "Claude"},
            ],
            30, "claude",
        )
        for zeile in text.splitlines():
            if zeile.startswith("DELETE FROM sitzung_logisch"):
                self.assertIn("5", zeile)
                self.assertIn("9", zeile)


class BefehlRetentionSqlTest(unittest.TestCase):
    """Orchestrierung in __main__: Guard + Datei-Ausgabe/--zaehlen/--vorschau, ohne echte DB
    (retention.betroffene_sitzungen gefaked wie beleg_erzeugen in test_reingest.py)."""

    def _args(self, extra: list[str]):
        return main_mod._parser().parse_args(["retention-sql", *extra])

    def test_guard_verstoss_gibt_exit_2_ohne_datei(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "r.sql")
            args = self._args(["--aelter-als", "3", "--quelle", "alle", "--out", out])
            code = main_mod._befehl_retention_sql(args)
            self.assertEqual(code, 2)
            self.assertFalse(Path(out).exists())

    def test_fehlende_quelle_gibt_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "r.sql")
            args = self._args(["--aelter-als", "30", "--out", out])
            code = main_mod._befehl_retention_sql(args)
            self.assertEqual(code, 2)

    def test_zaehlen_gibt_nur_anzahl_aus_schreibt_keine_datei(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "r.sql")
            args = self._args(["--aelter-als", "30", "--quelle", "alle", "--out", out, "--zaehlen"])
            with mock.patch.object(retention, "betroffene_sitzungen", return_value=[{"logisch_ref": 1}]):
                with mock.patch("builtins.print") as mock_print:
                    code = main_mod._befehl_retention_sql(args)
            self.assertEqual(code, 0)
            self.assertFalse(Path(out).exists())
            gedrucktes = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("1", gedrucktes)

    def test_vorschau_listet_ids_schreibt_keine_datei(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "r.sql")
            args = self._args(["--aelter-als", "30", "--quelle", "alle", "--out", out, "--vorschau"])
            treffer = [{"logisch_ref": 42, "beginn": "2026-01-01T00:00:00+00:00", "quelle_anzeige": "Claude"}]
            with mock.patch.object(retention, "betroffene_sitzungen", return_value=treffer):
                with mock.patch("builtins.print") as mock_print:
                    code = main_mod._befehl_retention_sql(args)
            self.assertEqual(code, 0)
            self.assertFalse(Path(out).exists())
            gedrucktes = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("42", gedrucktes)

    def test_normaler_lauf_schreibt_datei_und_druckt_ausfuehr_befehl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "r.sql")
            args = self._args(["--aelter-als", "30", "--quelle", "alle", "--out", out])
            treffer = [{"logisch_ref": 42, "beginn": "2026-01-01T00:00:00+00:00", "quelle_anzeige": "Claude"}]
            with mock.patch.object(retention, "betroffene_sitzungen", return_value=treffer):
                with mock.patch("builtins.print") as mock_print:
                    code = main_mod._befehl_retention_sql(args)
            self.assertEqual(code, 0)
            self.assertTrue(Path(out).exists())
            text = Path(out).read_text(encoding="utf-8")
            self.assertIn("DELETE FROM sitzung_logisch", text)
            gedrucktes = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
            self.assertIn("ledger_admin", gedrucktes)
            self.assertIn(out, gedrucktes)

    def test_default_out_pfad_traegt_datum_und_work_ordner(self) -> None:
        args = self._args(["--aelter-als", "30", "--quelle", "alle"])
        self.assertIn("_work_sitzungsbeleg", args.out)
        self.assertTrue(args.out.endswith("-retention.sql"))


if __name__ == "__main__":
    unittest.main()
