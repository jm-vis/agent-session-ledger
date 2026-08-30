"""Tests für kennzahlen.berechne() — synthetische Belege, keine echten Sitzungen."""
from __future__ import annotations

import unittest

from sitzungsbeleg import kennzahlen
from sitzungsbeleg.modell import Kopf, Subagent, Token

from .hilfen import (
    assistent,
    baue_beleg,
    compaction,
    nutzer_runde,
    runde_ende,
    subagent,
    tool,
    tool_ergebnis,
)


class RundenUndDauerTest(unittest.TestCase):
    def test_zaehlt_nutzer_runden(self):
        beleg = baue_beleg(ereignisse=[nutzer_runde(), nutzer_runde(), assistent()])
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.runden, 2)

    def test_dauer_ms_aus_kopf_mit_z_suffix(self):
        kopf = Kopf(
            quelle="claude", sitzung_id="s1",
            start="2026-08-25T10:00:00Z", ende="2026-08-25T10:10:00Z",
        )
        beleg = baue_beleg(kopf=kopf)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.dauer_ms, 600_000)

    def test_dauer_ms_aus_kopf_mit_offset(self):
        kopf = Kopf(
            quelle="claude", sitzung_id="s1",
            start="2026-08-25T10:00:00+02:00", ende="2026-08-25T10:05:00+02:00",
        )
        beleg = baue_beleg(kopf=kopf)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.dauer_ms, 300_000)

    def test_dauer_ms_ohne_zeiten_ist_null(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1")
        beleg = baue_beleg(kopf=kopf)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.dauer_ms, 0)

    def test_ungueltiger_zeitstempel_stuerzt_nicht_ab_und_ist_partial(self):
        """F7: kaputter Zeitstempel -> dauer_ms bleibt 0, erfassung.dauer='partial',
        kein Absturz."""
        kopf = Kopf(
            quelle="claude", sitzung_id="s1",
            start="kaputt", ende="2026-08-25T10:10:00Z",
        )
        beleg = baue_beleg(kopf=kopf)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.dauer_ms, 0)
        self.assertEqual(beleg.erfassung.dauer, "partial")

    def test_beide_zeitstempel_kaputt_ist_partial(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", start="kaputt", ende="auch-kaputt")
        beleg = baue_beleg(kopf=kopf)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.dauer_ms, 0)
        self.assertEqual(beleg.erfassung.dauer, "partial")

    def test_gueltige_zeitstempel_lassen_erfassung_dauer_unveraendert(self):
        beleg = baue_beleg()
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.erfassung.dauer, "not_observed")


class LatenzPerzentilTest(unittest.TestCase):
    def test_p50_p95_max_nearest_rank(self):
        ereignisse = [runde_ende(d) for d in (100, 200, 300, 400)]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.latenz_p50_ms, 200)
        self.assertEqual(beleg.kennzahlen.latenz_p95_ms, 400)
        self.assertEqual(beleg.kennzahlen.latenz_max_ms, 400)

    def test_ohne_runden_ende_alles_null(self):
        beleg = baue_beleg(ereignisse=[nutzer_runde()])
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.latenz_p50_ms, 0)
        self.assertEqual(beleg.kennzahlen.latenz_p95_ms, 0)
        self.assertEqual(beleg.kennzahlen.latenz_max_ms, 0)


class ToolZaehlungTest(unittest.TestCase):
    def test_fehlerzuordnung_ueber_ref_und_fallback(self):
        ereignisse = [
            tool("Edit", ref="t1"),
            tool_ergebnis(fehler=True, ref="t1"),   # ueber ref -> Edit
            tool("Read"),
            tool_ergebnis(fehler=True, ref=""),      # kein ref-Treffer -> letztes ART_TOOL (Read)
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        k = beleg.kennzahlen
        self.assertEqual(k.tools, 2)
        self.assertEqual(k.tool_fehler, 2)
        self.assertEqual(k.tools_je_typ, {"Edit": 1, "Read": 1})
        self.assertEqual(k.tool_fehler_je_typ, {"Edit": 1, "Read": 1})
        self.assertAlmostEqual(k.tool_fehlerquote, 1.0)

    def test_quote_null_ohne_tools(self):
        beleg = baue_beleg(ereignisse=[])
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.tool_fehlerquote, 0.0)


class TokenUndThinkingTest(unittest.TestCase):
    def test_token_summe_und_thinking_bloecke(self):
        ereignisse = [
            assistent(Token(input=100, output=50, thinking=0)),
            assistent(Token(input=200, output=100, thinking=30)),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        k = beleg.kennzahlen
        self.assertEqual(k.token.input, 300)
        self.assertEqual(k.token.output, 150)
        self.assertEqual(k.token.thinking, 30)
        self.assertEqual(k.thinking_bloecke, 1)


class CompactionTest(unittest.TestCase):
    def test_position_als_index_plus_eins_durch_laenge(self):
        """F6: Position ist (i+1)/n, nicht i/n — sonst zeigt eine Compaction als
        letztes Ereignis fälschlich < 100 % der Sitzung."""
        ereignisse = [nutzer_runde() for _ in range(8)] + [compaction(), nutzer_runde()]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        k = beleg.kennzahlen
        self.assertEqual(k.compactions, 1)
        self.assertEqual(len(k.compaction_positionen), 1)
        self.assertAlmostEqual(k.compaction_positionen[0], 0.9)

    def test_compaction_als_letztes_ereignis_ist_100_prozent(self):
        ereignisse = [nutzer_runde(), nutzer_runde(), compaction()]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertAlmostEqual(beleg.kennzahlen.compaction_positionen[0], 1.0)

    def test_compaction_als_einziges_ereignis_ist_100_prozent(self):
        beleg = baue_beleg(ereignisse=[compaction()])
        kennzahlen.berechne(beleg)
        self.assertAlmostEqual(beleg.kennzahlen.compaction_positionen[0], 1.0)

    def test_compaction_erstes_von_vier_ist_25_prozent(self):
        ereignisse = [compaction(), nutzer_runde(), nutzer_runde(), nutzer_runde()]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertAlmostEqual(beleg.kennzahlen.compaction_positionen[0], 0.25)


class SubagentTest(unittest.TestCase):
    def test_anzahl_und_max_tiefe(self):
        beleg = baue_beleg(
            subagenten=[subagent(tiefe=1), subagent(tiefe=3), subagent(tiefe=2)]
        )
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.subagenten, 3)
        self.assertEqual(beleg.kennzahlen.subagenten_max_tiefe, 3)

    def test_ohne_subagenten_tiefe_null(self):
        beleg = baue_beleg()
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.subagenten_max_tiefe, 0)


class ReworkDateienTest(unittest.TestCase):
    def test_nur_signaturen_ab_zwei_bezuegen(self):
        """F4/F10: rework_dateien gruppiert über signatur (Datei-Hash),
        nicht über ref (tool_use_id — je Aufruf eindeutig)."""
        ereignisse = [
            tool("Edit", ref="t1", signatur="a"),
            tool("Edit", ref="t2", signatur="a"),
            tool("Edit", ref="t3", signatur="a"),
            tool("Edit", ref="t4", signatur="b"),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.rework_dateien, {"a": 3})

    def test_eindeutige_refs_ohne_signatur_gruppieren_nicht(self):
        """Regressionsschutz: gleiche ref (frueher fälschlich als Datei-Schluessel
        genutzt) ohne signatur darf NICHT als eine Datei gezaehlt werden."""
        ereignisse = [tool("Edit", ref="a") for _ in range(3)]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.rework_dateien, {})

    def test_read_zaehlt_nicht_zu_rework_aenderungen(self):
        """F10: kennzahlen.REWORK_TYPEN (Aenderungen) enthaelt kein Read."""
        ereignisse = [
            tool("Read", ref="t1", signatur="a"),
            tool("Read", ref="t2", signatur="a"),
            tool("Read", ref="t3", signatur="a"),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.rework_dateien, {})

    def test_multiedit_zaehlt_zu_rework_aenderungen(self):
        ereignisse = [
            tool("MultiEdit", ref="t1", signatur="a"),
            tool("MultiEdit", ref="t2", signatur="a"),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertEqual(beleg.kennzahlen.rework_dateien, {"a": 2})


class KostenUndKontextTest(unittest.TestCase):
    def test_kosten_ohne_preise_not_observed(self):
        ereignisse = [assistent(Token(input=1_000_000, output=500_000))]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        self.assertIsNone(beleg.kennzahlen.kosten)
        self.assertEqual(beleg.erfassung.kosten, "not_observed")

    def test_kosten_mit_preisen_derived(self):
        ereignisse = [
            assistent(Token(input=1_000_000, output=500_000), name="claude-sonnet-5")
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {"claude-sonnet-5": {"input": 3, "output": 15}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 10.5)
        self.assertEqual(beleg.kennzahlen.kosten_waehrung, "USD")
        self.assertEqual(beleg.erfassung.kosten, "derived")

    def test_kosten_ohne_preise_hat_keine_waehrung(self):
        beleg = baue_beleg(ereignisse=[assistent(Token(input=10))])
        kennzahlen.berechne(beleg, None, waehrung="USD")
        self.assertEqual(beleg.kennzahlen.kosten_waehrung, "")

    def test_kontext_auslastung_max(self):
        ereignisse = [
            assistent(Token(input=500_000, cache_read=100_000), name="claude-sonnet-5")
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {
            "claude-sonnet-5": {"input": 3, "output": 15, "kontext_fenster": 1_000_000}
        }
        kennzahlen.berechne(beleg, preise)
        self.assertAlmostEqual(beleg.kennzahlen.kontext_auslastung_max, 0.6)


class KostenSubagentenTest(unittest.TestCase):
    """Auftrag 2026-08-27: Subagenten-Kosten getrennt von der Hauptsitzung ausgewiesen."""

    def _beleg_mit_subagent(self, modell: str, token: Token):
        sub = Subagent(agent_id="sub-1", modell=modell, token=token)
        ereignisse = [assistent(Token(input=1_000_000, output=500_000), name="claude-sonnet-5")]
        return baue_beleg(ereignisse=ereignisse, subagenten=[sub])

    def test_kosten_subagenten_eigenes_modell_getrennt_von_hauptsitzung(self):
        beleg = self._beleg_mit_subagent("glm-5.2", Token(input=1_000_000, output=1_000_000))
        preise = {
            "claude-sonnet-5": {"input": 3, "output": 15},
            "glm-5.2": {"input": 1, "output": 2},
        }
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 10.5)          # nur Hauptsitzung
        self.assertAlmostEqual(beleg.kennzahlen.kosten_subagenten, 3.0)  # 1*1 + 1*2
        self.assertAlmostEqual(beleg.kennzahlen.kosten_gesamt, 13.5)

    def test_kosten_subagenten_ohne_preise_not_observed(self):
        beleg = self._beleg_mit_subagent("glm-5.2", Token(input=10))
        kennzahlen.berechne(beleg, None)
        self.assertIsNone(beleg.kennzahlen.kosten_subagenten)
        self.assertIsNone(beleg.kennzahlen.kosten_gesamt)

    def test_kosten_subagenten_modell_ohne_preiseintrag_bleibt_none(self):
        beleg = self._beleg_mit_subagent("unbekanntes-modell", Token(input=10))
        preise = {"claude-sonnet-5": {"input": 3, "output": 15}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertIsNotNone(beleg.kennzahlen.kosten)
        self.assertIsNone(beleg.kennzahlen.kosten_subagenten)
        # kosten_gesamt zaehlt den bekannten Anteil (Hauptsitzung), nicht None
        self.assertAlmostEqual(beleg.kennzahlen.kosten_gesamt, beleg.kennzahlen.kosten)

    def test_kosten_gesamt_addiert_beide_teile(self):
        ereignisse = [assistent(Token(input=1_000_000), name="claude-sonnet-5")]
        sub = Subagent(agent_id="sub-1", modell="claude-sonnet-5", token=Token(input=1_000_000))
        beleg = baue_beleg(ereignisse=ereignisse, subagenten=[sub])
        preise = {"claude-sonnet-5": {"input": 3, "output": 15}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 3.0)
        self.assertAlmostEqual(beleg.kennzahlen.kosten_subagenten, 3.0)
        self.assertAlmostEqual(beleg.kennzahlen.kosten_gesamt, 6.0)


class OllamaCloudReferenzpreisTest(unittest.TestCase):
    """Entscheid 2026-08-27: Ollama-Cloud-Sitzungen (glm-5.2:cloud, ...) bekommen den
    OpenRouter-Referenzpreis -- Registry fuehrt ihn unter dem Basisnamen (ohne Tag), das
    Ereignis liefert das Modell teils MIT, teils OHNE Tag."""

    def test_kosten_mit_tag_im_ereignis_findet_basisnamen_in_der_registry(self):
        ereignisse = [assistent(Token(input=1_000_000, output=1_000_000), name="glm-5.2:cloud")]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {"glm-5.2": {"input": 1.19, "output": 3.74}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 1.19 + 3.74)
        self.assertEqual(beleg.erfassung.kosten, "derived")

    def test_kosten_ohne_tag_im_ereignis_trifft_denselben_eintrag(self):
        """Echter Sitzungswert ohne Tag (siehe quellen.py) -- exakter Treffer, keine
        Basisnamen-Suche noetig, aber dasselbe Ergebnis wie mit Tag."""
        ereignisse = [assistent(Token(input=1_000_000, output=1_000_000), name="glm-5.2")]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {"glm-5.2": {"input": 1.19, "output": 3.74}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 1.19 + 3.74)

    def test_ohne_preiseintrag_bleibt_not_observed(self):
        """Kein Eintrag in der Registry -- Frontend zeigt weiterhin 'Abo' (kein Fallback auf 0)."""
        ereignisse = [assistent(Token(input=1_000_000), name="qwen3-vl:235b-cloud")]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg, {"glm-5.2": {"input": 1.19, "output": 3.74}}, waehrung="USD")
        self.assertIsNone(beleg.kennzahlen.kosten)
        self.assertEqual(beleg.erfassung.kosten, "not_observed")

    def test_subagent_ollama_modell_mit_tag_findet_basisnamen(self):
        sub = Subagent(agent_id="sub-1", modell="minimax-m3:cloud", token=Token(input=1_000_000))
        ereignisse = [assistent(Token(input=1_000_000), name="claude-sonnet-5")]
        beleg = baue_beleg(ereignisse=ereignisse, subagenten=[sub])
        preise = {"claude-sonnet-5": {"input": 3, "output": 15}, "minimax-m3": {"input": 0.3, "output": 1.2}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten_subagenten, 0.3)

    def test_kosten_je_runde_nutzt_denselben_fallback(self):
        ereignisse = [
            nutzer_runde(),
            assistent(Token(input=1_000_000, output=1_000_000), name="glm-5.2:cloud"),
        ]
        preise = {"glm-5.2": {"input": 1.19, "output": 3.74}}
        runden = kennzahlen.kosten_je_runde(ereignisse, preise)
        self.assertAlmostEqual(runden[0], 1.19 + 3.74)


class RequestyMeldetAlsTest(unittest.TestCase):
    """Layout-Nachlese 2026-08-28 Punkt 6 (verifizierter Fund): Requesty meldet im Antwort-
    `model`-Feld das ECHTE Upstream-Modell (z. B. `moonshotai/Kimi-K3`), nicht die angefragte
    Requesty-Katalog-ID (`sference/kimi-k3`, so gefuehrt in modelle.json) -- ohne die dritte
    Stufe `meldet_als` in kennzahlen._preissatz() blieb `kosten_gesamt` fuer JEDE Requesty-
    Sitzung `None`, live an echten Requesty-Sitzungen nachgewiesen."""

    def test_kosten_ueber_meldet_als_alias_gefunden(self):
        ereignisse = [assistent(Token(input=1_000_000, output=1_000_000), name="moonshotai/Kimi-K3")]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {"sference/kimi-k3": {"input": 2.25, "output": 11.25, "meldet_als": ["moonshotai/Kimi-K3"]}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertAlmostEqual(beleg.kennzahlen.kosten, 2.25 + 11.25)
        self.assertEqual(beleg.erfassung.kosten, "derived")

    def test_ohne_passenden_alias_bleibt_not_observed(self):
        ereignisse = [assistent(Token(input=1_000_000), name="zai-org/GLM-5.3-Flash")]
        beleg = baue_beleg(ereignisse=ereignisse)
        preise = {"sference/kimi-k3": {"input": 2.25, "output": 11.25, "meldet_als": ["moonshotai/Kimi-K3"]}}
        kennzahlen.berechne(beleg, preise, waehrung="USD")
        self.assertIsNone(beleg.kennzahlen.kosten)
        self.assertEqual(beleg.erfassung.kosten, "not_observed")


if __name__ == "__main__":
    unittest.main()
