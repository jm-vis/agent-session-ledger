"""Zentrale `.env` (2026-08-28): Reihenfolge Umgebung > scripts/.env > Alt-Datei."""
import os
import tempfile
import unittest
from pathlib import Path

from sitzungsbeleg import schluessel


class SchluesselTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zentral_alt = schluessel.ZENTRALE_DATEI
        schluessel.ZENTRALE_DATEI = Path(self.tmp.name) / ".env"
        os.environ.pop("TEST_KEY_X", None)

    def tearDown(self):
        schluessel.ZENTRALE_DATEI = self.zentral_alt
        os.environ.pop("TEST_KEY_X", None)
        self.tmp.cleanup()

    def test_umgebung_schlaegt_dateien(self):
        schluessel.ZENTRALE_DATEI.write_text("TEST_KEY_X=datei\n", encoding="utf-8")
        os.environ["TEST_KEY_X"] = "env"
        self.assertEqual(schluessel.lese("TEST_KEY_X"), "env")

    def test_zentrale_datei_schlaegt_alt_datei(self):
        alt = Path(self.tmp.name) / ".env.alt"
        alt.write_text("TEST_KEY_X=alt\n", encoding="utf-8")
        schluessel.ZENTRALE_DATEI.write_text("# Kommentar\nTEST_KEY_X=\"zentral\"\n", encoding="utf-8")
        self.assertEqual(schluessel.lese("TEST_KEY_X", alt), "zentral")

    def test_alt_datei_als_rueckfall(self):
        alt = Path(self.tmp.name) / ".env.alt"
        alt.write_text("TEST_KEY_X=alt\n", encoding="utf-8")
        self.assertEqual(schluessel.lese("TEST_KEY_X", alt), "alt")

    def test_nirgends_gesetzt_liefert_none(self):
        self.assertIsNone(schluessel.lese("TEST_KEY_X", Path(self.tmp.name) / "fehlt"))

    def test_leerer_wert_zaehlt_nicht(self):
        schluessel.ZENTRALE_DATEI.write_text("TEST_KEY_X=\n", encoding="utf-8")
        self.assertIsNone(schluessel.lese("TEST_KEY_X"))
