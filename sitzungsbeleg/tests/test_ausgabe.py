"""Tests für ausgabe.als_markdown()/als_json() — keine Inhalte, keine Überlängen."""
from __future__ import annotations

import json
import unittest

from sitzungsbeleg import ausgabe, kennzahlen, redaktion, regeln
from sitzungsbeleg.modell import SCHEMA_VERSION, Kopf

from .hilfen import assistent, baue_beleg, subagent, tool, tool_ergebnis


def _voller_beleg():
    kopf = Kopf(
        quelle="claude", sitzung_id="s-ausgabe",
        start="2026-08-25T10:00:00Z", ende="2026-08-25T10:10:00Z",
    )
    ereignisse = [
        assistent(name="claude-sonnet-5"),
        tool("Edit", ref="x"),
        tool_ergebnis(fehler=True, ref="x"),
    ]
    subagenten = [subagent(agent_id="sub-1", ergebnis="fehler")]
    beleg = baue_beleg(kopf=kopf, ereignisse=ereignisse, subagenten=subagenten)
    kennzahlen.berechne(beleg)
    regeln.pruefe(beleg)
    redaktion.bereinige(beleg)
    return beleg


class AlsMarkdownTest(unittest.TestCase):
    def test_enthaelt_schlusszeile(self):
        text = ausgabe.als_markdown(_voller_beleg())
        self.assertIn(
            "Dieser Beleg enthält keine Inhalte. Rohdaten liegen nur lokal.", text
        )

    def test_kein_wort_ueber_80_zeichen(self):
        text = ausgabe.als_markdown(_voller_beleg())
        for wort in text.split():
            self.assertLessEqual(len(wort), 80, msg=f"zu langes Wort: {wort!r}")

    def test_enthaelt_erfassungszeile(self):
        text = ausgabe.als_markdown(_voller_beleg())
        self.assertIn("Erfassung: tokens=", text)
        self.assertIn("inhalte=redacted", text)

    def test_enthaelt_subagenten_tabelle_mit_ergebnis(self):
        text = ausgabe.als_markdown(_voller_beleg())
        self.assertIn("## Subagenten", text)
        self.assertIn("fehler", text)

    def test_leerer_beleg_zeigt_keine_subagenten(self):
        beleg = baue_beleg()
        kennzahlen.berechne(beleg)
        regeln.pruefe(beleg)
        text = ausgabe.als_markdown(beleg)
        self.assertIn("## Subagenten\n\nKeine.", text)

    def test_auffaelligkeiten_werden_gelistet(self):
        text = ausgabe.als_markdown(_voller_beleg())
        self.assertIn("subagent:failed", text)


class AlsJsonTest(unittest.TestCase):
    def test_liefert_gueltiges_json_mit_schema_version(self):
        text = ausgabe.als_json(_voller_beleg())
        daten = json.loads(text)
        self.assertEqual(daten["schema_version"], SCHEMA_VERSION)
        self.assertIn("kennzahlen", daten)
        self.assertIn("kopf", daten)


if __name__ == "__main__":
    unittest.main()
