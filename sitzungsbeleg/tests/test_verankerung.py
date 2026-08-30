"""Tests fuer verankerung.py (C11-Waechter) -- pruefe() ist reine Python-Logik mit einem
Tempdir statt einer echten Vault, erledigte_entscheide() nur mit einem FakePsql (Muster
test_retention.py). CLI-Wiring: main_mod._befehl_verankerung_pruefen (Muster
test_aliase_entscheid_cli.py)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from .. import __main__ as main_mod
from .. import speicher, verankerung


class FakePsql:
    def __init__(self, antwort: str):
        self.antwort = antwort
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antwort


def _entscheid(signatur="sig", sitzung_ref=1, verankerung_feld=None):
    d = {"signatur": signatur, "sitzung_ref": sitzung_ref, "status": "erledigt"}
    if verankerung_feld is not None:
        d["verankerung"] = verankerung_feld
    return d


class ErledigteEntscheideTest(unittest.TestCase):
    def test_leere_antwort_gibt_leere_liste(self) -> None:
        self.assertEqual(verankerung.erledigte_entscheide(verankerung.date(2026, 1, 1), FakePsql("")), [])

    def test_liest_json_array_und_filtert_in_sql_auf_erledigt(self) -> None:
        laufer = FakePsql(json.dumps([_entscheid()]))
        ergebnis = verankerung.erledigte_entscheide(verankerung.date(2026, 1, 1), laufer)
        self.assertEqual(ergebnis, [_entscheid()])
        self.assertIn("status' = 'erledigt'", laufer.sql[0])
        self.assertIn("2026-01-01", laufer.sql[0])


class PruefeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _schreibe(self, relpfad: str, inhalt: str) -> None:
        ziel = self.repo / relpfad
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(inhalt, encoding="utf-8")

    def test_existierender_pfad_ohne_abschnitt_ist_ok(self) -> None:
        self._schreibe("TROUBLESHOOTING.md", "irgendwas")
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "troubleshooting", "pfad": "TROUBLESHOOTING.md"})],
            self.repo,
        )[0]
        self.assertTrue(befund.ok)
        self.assertFalse(befund.legacy)

    def test_fehlender_pfad_ist_rot(self) -> None:
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "regel", "pfad": "nicht-da.md"})], self.repo
        )[0]
        self.assertFalse(befund.ok)
        self.assertIn("fehlt", befund.grund)

    def test_abschnitt_vorhanden_ist_ok(self) -> None:
        self._schreibe("CLAUDE.md", "Vorher\n## Mein Abschnitt\nNachher")
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "regel", "pfad": "CLAUDE.md", "abschnitt": "Mein Abschnitt"})],
            self.repo,
        )[0]
        self.assertTrue(befund.ok)

    def test_abschnitt_gross_kleinschreibung_ist_egal(self) -> None:
        self._schreibe("CLAUDE.md", "## MEIN ABSCHNITT")
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "regel", "pfad": "CLAUDE.md", "abschnitt": "mein abschnitt"})],
            self.repo,
        )[0]
        self.assertTrue(befund.ok)

    def test_abschnitt_fehlt_ist_rot(self) -> None:
        self._schreibe("CLAUDE.md", "etwas ganz anderes")
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "regel", "pfad": "CLAUDE.md", "abschnitt": "Mein Abschnitt"})],
            self.repo,
        )[0]
        self.assertFalse(befund.ok)
        self.assertIn("Abschnitt nicht gefunden", befund.grund)

    def test_ohne_verankerungsfeld_ist_legacy_nicht_rot(self) -> None:
        befund = verankerung.pruefe([_entscheid()], self.repo)[0]
        self.assertTrue(befund.legacy)
        self.assertTrue(befund.ok)  # legacy zaehlt nicht als ROT (siehe rote_befunde())
        self.assertNotIn(befund, verankerung.rote_befunde([befund]))

    def test_nur_lange_abschnitte_werden_auf_40_zeichen_gekuerzt_verglichen(self) -> None:
        self._schreibe("CLAUDE.md", "## " + "x" * 40)
        lang = "x" * 40 + " -- Rest, der nicht mehr im Dokument steht"
        befund = verankerung.pruefe(
            [_entscheid(verankerung_feld={"art": "regel", "pfad": "CLAUDE.md", "abschnitt": lang})], self.repo
        )[0]
        self.assertTrue(befund.ok)


class AusgabeTest(unittest.TestCase):
    def test_alle_ok_zeigt_ok_zeile(self) -> None:
        befunde = [verankerung.VerankerungsBefund("a", 1, "x.md", True, False)]
        self.assertEqual(verankerung.ausgabe_text(befunde), "OK 1 geprüft")

    def test_ein_roter_befund_zeigt_rot_und_details(self) -> None:
        befunde = [verankerung.VerankerungsBefund("a", 1, "x.md", False, False, "Datei fehlt: x.md")]
        text = verankerung.ausgabe_text(befunde)
        self.assertTrue(text.startswith("ROT"))
        self.assertIn("a · 1 · x.md · Datei fehlt: x.md", text)

    def test_legacy_zeile_ist_nur_hinweis_kein_rot(self) -> None:
        befunde = [
            verankerung.VerankerungsBefund("a", 1, "x.md", True, False),
            verankerung.VerankerungsBefund("b", None, None, True, True, "legacy: kein Verankerungsfeld"),
        ]
        text = verankerung.ausgabe_text(befunde)
        self.assertTrue(text.startswith("OK 1 geprüft"))
        self.assertIn("Hinweis: 1 Legacy-Entscheid(e)", text)

    def test_als_json_zaehlt_rot_und_legacy_getrennt(self) -> None:
        befunde = [
            verankerung.VerankerungsBefund("a", 1, "x.md", False, False, "Datei fehlt: x.md"),
            verankerung.VerankerungsBefund("b", None, None, True, True, "legacy"),
        ]
        d = verankerung.als_json(befunde)
        self.assertEqual(d["status"], "rot")
        self.assertEqual(d["geprueft"], 1)
        self.assertEqual(d["legacy"], 1)
        self.assertEqual(len(d["rot"]), 1)


class BefehlVerankerungPruefenTest(unittest.TestCase):
    """CLI-Wiring `verankerung-pruefen` (Muster test_aliase_entscheid_cli.py)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _lauf(self, argv: list[str], antwort: str) -> tuple[int, str]:
        puffer = io.StringIO()
        with mock.patch.object(verankerung, "erledigte_entscheide", lambda seit, laufer=speicher.psql: json.loads(antwort)):
            with redirect_stdout(puffer):
                code = main_mod.main(["verankerung-pruefen", "--repo", str(self.repo), *argv])
        return code, puffer.getvalue()

    def test_ok_gibt_exit_0(self) -> None:
        self._schreibe("CLAUDE.md", "x")
        code, ausgabe = self._lauf([], json.dumps([_entscheid(verankerung_feld={"art": "regel", "pfad": "CLAUDE.md"})]))
        self.assertEqual(code, 0)
        self.assertIn("OK 1 geprüft", ausgabe)

    def test_fehlender_pfad_gibt_exit_1(self) -> None:
        code, ausgabe = self._lauf([], json.dumps([_entscheid(verankerung_feld={"art": "regel", "pfad": "fehlt.md"})]))
        self.assertEqual(code, 1)
        self.assertIn("ROT", ausgabe)

    def test_json_flag_gibt_gueltiges_json(self) -> None:
        code, ausgabe = self._lauf(["--json"], json.dumps([_entscheid(verankerung_feld={"art": "regel", "pfad": "fehlt.md"})]))
        self.assertEqual(code, 1)
        d = json.loads(ausgabe)
        self.assertEqual(d["status"], "rot")

    def test_ohne_entscheide_gibt_exit_0(self) -> None:
        code, ausgabe = self._lauf([], "[]")
        self.assertEqual(code, 0)
        self.assertIn("OK 0 geprüft", ausgabe)

    def test_stdin_flag_liest_json_statt_db(self) -> None:
        """ADR 0004: deterministischer Selftest ohne echte DB (Muster `aliase --pruefen`)."""
        puffer = io.StringIO()
        stdin_text = json.dumps([_entscheid(verankerung_feld={"art": "regel", "pfad": "fehlt.md"})])
        with mock.patch("sys.stdin", io.StringIO(stdin_text)):
            with redirect_stdout(puffer):
                code = main_mod.main(["verankerung-pruefen", "--repo", str(self.repo), "--stdin"])
        self.assertEqual(code, 1)
        self.assertIn("ROT", puffer.getvalue())

    def test_speicherfehler_gibt_exit_2(self) -> None:
        puffer = io.StringIO()
        with mock.patch.object(verankerung, "erledigte_entscheide", side_effect=speicher.SpeicherFehler("kein docker")):
            with redirect_stdout(puffer):
                code = main_mod.main(["verankerung-pruefen", "--repo", str(self.repo)])
        self.assertEqual(code, 2)

    def _schreibe(self, relpfad: str, inhalt: str) -> None:
        (self.repo / relpfad).write_text(inhalt, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
