"""Befund 2026-08-29: Entscheid aus dem Tiefenanalyse-Fluss (sitzung_ref = logische ID 245)
wurde von der Legacy-Leseregel `_mit_logischer_ref` als Versions-ID gedeutet und auf eine fremde
logische Sitzung (174) umgehaengt. Die Regel darf nur Eintraege VOR dem C1-Stichtag anfassen."""

from __future__ import annotations

import json
import unittest

from .. import web


class FakeLaufer:
    def __init__(self, antworten: dict[str, str], default: str = "[]"):
        self.antworten = antworten
        self.default = default

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        for muster, antwort in self.antworten.items():
            if muster in sql:
                return antwort
        return self.default


class LogischeRefTest(unittest.TestCase):
    def setUp(self) -> None:
        self._laufer = web.LAUFER
        # sitzung.id 245 ist eine alte Version der logischen Sitzung 174
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id IN": json.dumps([{"id": 245, "logisch_ref": 174}])})

    def tearDown(self) -> None:
        web.LAUFER = self._laufer

    def test_entscheid_nach_c1_behaelt_logische_ref(self) -> None:
        neu = {"signatur": "rework:tool:Bash", "sitzung_ref": 245, "entschieden_am": "2026-08-29T09:52:30+00:00"}
        self.assertEqual(web._mit_logischer_ref([neu])[0]["sitzung_ref"], 245)

    def test_alt_eintrag_vor_c1_wird_aufgeloest(self) -> None:
        alt = {"signatur": "rework:tool:Bash", "sitzung_ref": 245, "entschieden_am": "2026-08-20T10:00:00+00:00"}
        self.assertEqual(web._mit_logischer_ref([alt])[0]["sitzung_ref"], 174)


if __name__ == "__main__":
    unittest.main()
