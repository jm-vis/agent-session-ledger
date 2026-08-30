"""Regeltexte: Titel/Bedeutung/Was-tun je Regel (Abnahme "Block 4 Sitzungsdetail",
2026-08-26, Auftrag B.4)."""
from __future__ import annotations

import unittest

from .. import regeltexte

# Jede regel=...-Kennung, die eine Funktion in regeln.REGELN tatsaechlich vergibt (fest im
# Code, siehe regeln.py) -- Vollstaendigkeits-Check haengt an dieser Liste, nicht an einem
# Aufruf der Regeln selbst (die brauchen echte Treffer, ein leerer Beleg liefert nie welche).
REGELN_SIGNATUREN = {
    "tool:error_rate", "rework:file", "rework:tool", "subagent:failed",
    "subagent:unsupported_claim", "subagent:overdelegation", "latency:slow_turn",
    "latency:timeout", "capture:gap", "context:compaction_risk", "cost:spike",
}

# Querschnitts-/Redaktions-Regeln (querschnitt.py, redaktion.py) -- anderes Modul, gleiches
# Signatur-Vokabular.
WEITERE_SIGNATUREN = {"cost:outlier", "error:recurring", "privacy:metadata_leak"}


class RegeltexteTest(unittest.TestCase):
    def test_jede_regel_aus_regeln_hat_einen_eigenen_text(self) -> None:
        for regel in REGELN_SIGNATUREN:
            text = regeltexte.text_fuer(regel)
            self.assertNotEqual(text, regeltexte.STANDARD_TEXT, regel)
            self.assertTrue(text["titel"], regel)
            self.assertTrue(text["bedeutung"], regel)

    def test_querschnitts_und_redaktionsregeln_haben_einen_eigenen_text(self) -> None:
        for regel in WEITERE_SIGNATUREN:
            text = regeltexte.text_fuer(regel)
            self.assertNotEqual(text, regeltexte.STANDARD_TEXT, regel)

    def test_unbekannte_regel_liefert_standardtext(self) -> None:
        self.assertEqual(regeltexte.text_fuer("nie-gesehen"), regeltexte.STANDARD_TEXT)

    def test_standardtext_hat_leeres_was_tun(self) -> None:
        """Kein irrefuehrender Handlungshinweis fuer eine Regel, die niemand kennt."""
        self.assertEqual(regeltexte.STANDARD_TEXT["was_tun"], "")

    def test_jede_regel_hat_alle_pflicht_schluessel(self) -> None:
        """Mockup K2 (Ergaenzung 2026-08-27): jeder Eintrag traegt titel/bedeutung/kurz/
        was_tun/einheit -- die Karte greift auf alle fuenf zu, ein fehlender Schluessel wuerde
        erst im Browser als leere Zeile auffallen."""
        pflicht = {"titel", "bedeutung", "kurz", "was_tun", "einheit"}
        for regel, text in regeltexte.REGELTEXTE.items():
            self.assertEqual(set(text.keys()), pflicht, regel)
        self.assertEqual(set(regeltexte.STANDARD_TEXT.keys()), pflicht)


if __name__ == "__main__":
    unittest.main()
