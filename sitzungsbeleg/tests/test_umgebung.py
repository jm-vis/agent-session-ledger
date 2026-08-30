"""Achse Umgebung (C12): reine Funktionen `wert`/`kuerzel`/`verteilung`. Kein SQL/DB hier --
das deckt tests/test_web.py (API-Filter/Distribution) und tests/test_main.py (Stop-Hook-Ableitung)."""
from __future__ import annotations

import unittest

from .. import umgebung


class WertTest(unittest.TestCase):
    def test_bekannter_wert_bleibt_unveraendert(self) -> None:
        self.assertEqual(umgebung.wert("abnahme"), "abnahme")
        self.assertEqual(umgebung.wert("betrieb"), "betrieb")
        self.assertEqual(umgebung.wert("entwicklung"), "entwicklung")

    def test_fehlender_wert_ist_entwicklung(self) -> None:
        self.assertEqual(umgebung.wert(None), "entwicklung")
        self.assertEqual(umgebung.wert(""), "entwicklung")

    def test_unbekannter_wert_faellt_auf_entwicklung_zurueck(self) -> None:
        self.assertEqual(umgebung.wert("staging"), "entwicklung")


class KuerzelTest(unittest.TestCase):
    def test_entwicklung_zeigt_keinen_chip(self) -> None:
        self.assertEqual(umgebung.kuerzel("entwicklung"), "")

    def test_abnahme_zeigt_abn(self) -> None:
        self.assertEqual(umgebung.kuerzel("abnahme"), "Abn.")

    def test_betrieb_zeigt_betrieb(self) -> None:
        self.assertEqual(umgebung.kuerzel("betrieb"), "Betrieb")

    def test_unbekannter_wert_zeigt_keinen_chip(self) -> None:
        self.assertEqual(umgebung.kuerzel("irgendwas"), "")


class VerteilungTest(unittest.TestCase):
    def test_zaehlt_je_wert_alphabetisch(self) -> None:
        self.assertEqual(
            umgebung.verteilung(["entwicklung", "abnahme", "entwicklung"]),
            [{"name": "abnahme", "anzahl": 1}, {"name": "entwicklung", "anzahl": 2}],
        )

    def test_leere_liste_bleibt_leer(self) -> None:
        self.assertEqual(umgebung.verteilung([]), [])
