"""Stufe 2: Vier-Augen-Abgleich mit Fake-Fragern (kein claude/codex-Prozess im Test)."""
from __future__ import annotations

import json
import unittest

from .. import redaktion, vieraugen
from ..modell import Auffaelligkeit, Ereignis, ART_TOOL

from .hilfen import baue_beleg, subagent


def _beleg():
    beleg = baue_beleg(subagenten=[subagent("a1")])
    beleg.auffaelligkeiten = [
        Auffaelligkeit(regel="tool:error_rate", schwere="warnung", signatur="tool:error_rate", wert="25 %"),
        Auffaelligkeit(regel="context:compaction_risk", schwere="warnung",
                       signatur="context:compaction_risk", wert="82 %"),
    ]
    return beleg


class DokumentTest(unittest.TestCase):
    def test_kompakt_ohne_ereignisse_und_agent_ids(self) -> None:
        beleg = _beleg()
        beleg.ereignisse.append(Ereignis(zeit="2026-08-26T08:00:00Z", art=ART_TOOL, name="Bash"))
        dok = vieraugen.dokument_kompakt(beleg)
        self.assertNotIn("ereignisse", dok)
        self.assertNotIn("agent_id", dok["subagenten"][0])
        self.assertEqual(len(dok["auffaelligkeiten"]), 2)

    def test_prompt_enthaelt_schema_und_dokument(self) -> None:
        text = vieraugen.prompt(vieraugen.dokument_kompakt(_beleg()))
        self.assertIn('"zustimmung": "ja|nein|unklar"', text)
        self.assertIn("tool:error_rate", text)


class UrteileParsenTest(unittest.TestCase):
    def test_json_in_zaun_und_kuerzung(self) -> None:
        text = "Hier:\n```json\n" + json.dumps([
            {"regel": "tool:error_rate", "zustimmung": "JA", "begruendung": "x" * 500}
        ]) + "\n```"
        urteile = vieraugen.urteile_aus_text(text)
        self.assertEqual(urteile[0]["zustimmung"], "ja")
        self.assertEqual(len(urteile[0]["begruendung"]), 80)

    def test_unsinn_liefert_leer(self) -> None:
        self.assertEqual(vieraugen.urteile_aus_text("keine liste"), [])
        self.assertEqual(vieraugen.urteile_aus_text("[nicht json"), [])
        self.assertEqual(vieraugen.urteile_aus_text('[{"zustimmung": "vielleicht"}]')[0]["zustimmung"], "unklar")


class AbgleichTest(unittest.TestCase):
    def test_bestaetigt_verworfen_dissens(self) -> None:
        beleg = _beleg()
        claude = [{"regel": "tool:error_rate", "signatur": "tool:error_rate", "zustimmung": "ja",
                   "schwere": "", "begruendung": "c", "vorschlag": ""},
                  {"regel": "context:compaction_risk", "signatur": "", "zustimmung": "nein",
                   "schwere": "", "begruendung": "", "vorschlag": ""}]
        codex = [{"regel": "tool:error_rate", "signatur": "tool:error_rate", "zustimmung": "ja",
                  "schwere": "", "begruendung": "x", "vorschlag": ""}]
        befunde = vieraugen.vergleiche(beleg, claude, codex)
        self.assertEqual(befunde[0]["status"], "bestaetigt")
        self.assertEqual(befunde[1]["status"], "dissens")  # nein vs. unklar (fehlt)

    def test_review_mit_fragerfehler_bleibt_berichtsfaehig(self) -> None:
        def claude_ok(_text):
            return '[{"regel": "tool:error_rate", "signatur": "tool:error_rate", "zustimmung": "nein"},' \
                   ' {"regel": "zusatz:latenz", "zustimmung": "ja", "begruendung": "lang"}]'

        def codex_kaputt(_text):
            raise RuntimeError("codex: offline")

        ergebnis = vieraugen.review(_beleg(), frager_claude=claude_ok, frager_codex=codex_kaputt)
        self.assertIn("codex", ergebnis["fehler"])
        self.assertEqual(ergebnis["zusatz"][0]["regel"], "zusatz:latenz")
        self.assertEqual(ergebnis["dissens"], 1)
        text = vieraugen.als_markdown(ergebnis)
        self.assertIn("**dissens**", text)
        self.assertIn("Nicht befragt", text)

    def test_ergebnis_ist_redaktionssicher(self) -> None:
        """Modellantworten koennten Pfade enthalten — der Markdown-Bericht darf sie nicht tragen."""
        def frager(_text):
            return '[{"regel": "tool:error_rate", "signatur": "tool:error_rate", "zustimmung": "ja",' \
                   ' "begruendung": "Datei C:\\\\Users\\\\x\\\\geheim.txt"}]'

        ergebnis = vieraugen.review(_beleg(), frager_claude=frager, frager_codex=frager)
        text = vieraugen.als_markdown(ergebnis)
        self.assertNotIn("geheim", text)
        self.assertNotIn("C:\\\\", text)


if __name__ == "__main__":
    unittest.main()
