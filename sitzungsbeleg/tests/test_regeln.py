"""Tests für regeln.pruefe() — Stufe-1-Regelsatz, Grenzwerte beider Seiten."""
from __future__ import annotations

import unittest

from sitzungsbeleg import kennzahlen, regeln
from sitzungsbeleg.modell import Erfassung, Token

from .hilfen import assistent, baue_beleg, nutzer_runde, subagent, subagent_start, tool, tool_ergebnis


class ToolFehlerquoteTest(unittest.TestCase):
    def _beleg_mit_quote(self, quote: float, tool_fehler: int) -> object:
        beleg = baue_beleg()
        beleg.kennzahlen.tool_fehlerquote = quote
        beleg.kennzahlen.tool_fehler = tool_fehler
        return beleg

    def test_unter_schwelle_keine_auffaelligkeit(self):
        beleg = self._beleg_mit_quote(0.19, 3)
        treffer = regeln.regel_tool_fehlerquote(beleg)
        self.assertEqual(treffer, [])

    def test_auf_schwelle_warnung(self):
        beleg = self._beleg_mit_quote(0.20, 3)
        treffer = regeln.regel_tool_fehlerquote(beleg)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0].regel, "tool:error_rate")
        self.assertEqual(treffer[0].schwere, "warnung")
        self.assertEqual(treffer[0].wert, "20.0 %")

    def test_hohe_quote_aber_zu_wenig_fehler_keine_auffaelligkeit(self):
        beleg = self._beleg_mit_quote(0.50, 2)
        treffer = regeln.regel_tool_fehlerquote(beleg)
        self.assertEqual(treffer, [])


class ReworkDateiTest(unittest.TestCase):
    def _ereignisse(self, bezuege: int, fehllaeufe: int, signatur: str = "x") -> list:
        """Baut `bezuege` Datei-Tool-Aufrufe (je eigene tool_use_id, gleiche
        signatur = gleiche Datei) plus `fehllaeufe` Fehler-Ergebnisse, deren
        ref auf einen der Aufrufe zeigt (F4: ref = tool_use_id)."""
        ereignisse = [
            tool("Edit", ref=f"t{i}", signatur=signatur) for i in range(bezuege)
        ]
        for i in range(fehllaeufe):
            ziel_ref = f"t{i % bezuege}" if bezuege else ""
            ereignisse.append(tool_ergebnis(fehler=True, ref=ziel_ref))
        return ereignisse

    def test_fuenf_bezuege_zwei_fehllaeufe_warnung(self):
        beleg = baue_beleg(ereignisse=self._ereignisse(5, 2))
        treffer = regeln.regel_rework_datei(beleg)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0].signatur, "rework:file:x")
        self.assertEqual(treffer[0].ref, "x")

    def test_vier_bezuege_keine_auffaelligkeit(self):
        beleg = baue_beleg(ereignisse=self._ereignisse(4, 2))
        self.assertEqual(regeln.regel_rework_datei(beleg), [])

    def test_ein_fehllauf_keine_auffaelligkeit(self):
        beleg = baue_beleg(ereignisse=self._ereignisse(5, 1))
        self.assertEqual(regeln.regel_rework_datei(beleg), [])

    def test_read_zaehlt_zu_bezuegen(self):
        """F10: regeln.regel_rework_datei nutzt BEZUG_TYPEN (inkl. Read)."""
        ereignisse = [tool("Read", ref=f"t{i}", signatur="x") for i in range(5)]
        ereignisse += [
            tool_ergebnis(fehler=True, ref="t0"),
            tool_ergebnis(fehler=True, ref="t1"),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        treffer = regeln.regel_rework_datei(beleg)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0].ref, "x")

    def test_unterschiedliche_refs_ohne_signatur_gruppieren_nicht(self):
        """Regressionsschutz: fünf Aufrufe ohne signatur (kein Datei-Tool oder
        Datei-Hash fehlt) dürfen nicht fälschlich als eine Datei gezählt werden."""
        ereignisse = [tool("Edit", ref=f"t{i}") for i in range(5)]
        ereignisse += [
            tool_ergebnis(fehler=True, ref="t0"),
            tool_ergebnis(fehler=True, ref="t1"),
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        self.assertEqual(regeln.regel_rework_datei(beleg), [])


class SubagentFehlgeschlagenTest(unittest.TestCase):
    def test_fehler_und_leer_werden_gemeldet(self):
        beleg = baue_beleg(
            subagenten=[
                subagent(agent_id="s1", ergebnis="fehler"),
                subagent(agent_id="s2", ergebnis="leer"),
                subagent(agent_id="s3", ergebnis="ok"),
            ]
        )
        treffer = regeln.regel_subagent_fehlgeschlagen(beleg)
        refs = {a.ref for a in treffer}
        self.assertEqual(refs, {"s1", "s2"})
        self.assertTrue(all(a.schwere == "warnung" for a in treffer))

    def test_alle_ok_keine_auffaelligkeit(self):
        beleg = baue_beleg(subagenten=[subagent(ergebnis="ok")])
        self.assertEqual(regeln.regel_subagent_fehlgeschlagen(beleg), [])


class CompactionRisikoTest(unittest.TestCase):
    def test_position_ab_75_prozent_warnung(self):
        beleg = baue_beleg()
        beleg.kennzahlen.compaction_positionen = [0.5, 0.8]
        treffer = regeln.regel_compaction_risiko(beleg)
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0].wert, "80.0 %")

    def test_alle_unter_schwelle_keine_auffaelligkeit(self):
        beleg = baue_beleg()
        beleg.kennzahlen.compaction_positionen = [0.5, 0.7]
        self.assertEqual(regeln.regel_compaction_risiko(beleg), [])


class ErfassungsLueckeTest(unittest.TestCase):
    def test_not_recorded_kanaele_werden_gemeldet(self):
        beleg = baue_beleg(erfassung=Erfassung(token="not_recorded", dauer="not_recorded"))
        treffer = regeln.regel_erfassungsluecke(beleg)
        signaturen = {a.signatur for a in treffer}
        self.assertEqual(signaturen, {"capture:gap:token", "capture:gap:dauer"})
        self.assertTrue(all(a.schwere == "hinweis" for a in treffer))

    def test_observed_keine_auffaelligkeit(self):
        beleg = baue_beleg(erfassung=Erfassung(token="observed", dauer="observed"))
        self.assertEqual(regeln.regel_erfassungsluecke(beleg), [])


class PruefeSetztAuffaelligkeitenTest(unittest.TestCase):
    def test_pruefe_setzt_beleg_auffaelligkeiten(self):
        beleg = baue_beleg(subagenten=[subagent(ergebnis="fehler")])
        treffer = regeln.pruefe(beleg)
        self.assertEqual(beleg.auffaelligkeiten, treffer)
        self.assertTrue(len(treffer) >= 1)

    def test_pruefe_verwendet_berechnete_kennzahlen(self):
        ereignisse = [tool("Edit", ref=f"t{i}", signatur="x") for i in range(5)] + [
            tool_ergebnis(fehler=True, ref="t0"), tool_ergebnis(fehler=True, ref="t1")
        ]
        beleg = baue_beleg(ereignisse=ereignisse)
        kennzahlen.berechne(beleg)
        treffer = regeln.pruefe(beleg)
        signaturen = {a.signatur for a in treffer}
        self.assertIn("rework:file:x", signaturen)


class ReworkToolTest(unittest.TestCase):
    def test_vier_fehlversuche_gleiches_tool_warnung(self):
        beleg = baue_beleg()
        beleg.kennzahlen.tool_fehler_je_typ = {"Bash": 4, "Edit": 3}
        treffer = regeln.regel_rework_tool(beleg)
        self.assertEqual([t.signatur for t in treffer], ["rework:tool:Bash"])
        self.assertEqual(treffer[0].wert, "4")


class SubagentOhneBelegTest(unittest.TestCase):
    def test_ok_ohne_beleg_wird_gemeldet(self):
        ohne = subagent("a1", ergebnis="ok")
        ohne.beleg = "not_observed"
        mit = subagent("a2", ergebnis="ok")
        mit.beleg = "observed"
        fehler = subagent("a3", ergebnis="fehler")
        beleg = baue_beleg(subagenten=[ohne, mit, fehler])
        treffer = regeln.regel_subagent_ohne_beleg(beleg)
        self.assertEqual([t.ref for t in treffer], ["a1"])


class UeberdelegationTest(unittest.TestCase):
    def test_tiefe_drei_meldet(self):
        beleg = baue_beleg()
        beleg.kennzahlen.subagenten = 2
        beleg.kennzahlen.subagenten_max_tiefe = 3
        self.assertEqual(len(regeln.regel_ueberdelegation(beleg)), 1)

    def test_neunzehn_subagenten_tiefe_eins_meldet_nicht(self):
        beleg = baue_beleg()
        beleg.kennzahlen.subagenten = 19
        beleg.kennzahlen.subagenten_max_tiefe = 1
        self.assertEqual(regeln.regel_ueberdelegation(beleg), [])

    def test_sechsundzwanzig_subagenten_meldet_fuenfundzwanzig_nicht(self):
        beleg = baue_beleg()
        beleg.kennzahlen.subagenten = 25
        self.assertEqual(regeln.regel_ueberdelegation(beleg), [])
        beleg.kennzahlen.subagenten = 26
        self.assertEqual(regeln.regel_ueberdelegation(beleg)[0].regel, "subagent:overdelegation")


class LatenzTest(unittest.TestCase):
    def test_p95_ueber_60s_und_langsames_tool(self):
        langsam = tool("Bash", ref="t1")
        langsam.dauer_ms = 130_000
        langsam2 = tool("Bash", ref="t3")
        langsam2.dauer_ms = 121_000
        schnell = tool("Bash", ref="t2")
        schnell.dauer_ms = 5_000
        beleg = baue_beleg(ereignisse=[langsam, langsam2, schnell])
        beleg.kennzahlen.latenz_p95_ms = 61_000
        treffer = regeln.regel_latenz(beleg)
        self.assertEqual([t.signatur for t in treffer],
                         ["latency:slow_turn:runde", "latency:slow_turn:tool:Bash"])
        self.assertEqual(treffer[1].wert, "2 Aufrufe > 120 s")  # gebündelt, nicht je Aufruf

    def test_unter_schwellen_nichts(self):
        beleg = baue_beleg(ereignisse=[tool("Bash")])
        beleg.kennzahlen.latenz_p95_ms = 60_000
        self.assertEqual(regeln.regel_latenz(beleg), [])


class RegistryTest(unittest.TestCase):
    def test_neun_sitzungsregeln_registriert(self):
        self.assertEqual(len(regeln.REGELN), 9)

    def test_compaction_risiko_nicht_in_registry(self):
        """B (Maintainer 2026-08-26): abgeschaltet, Position ist kein Füllstand."""
        self.assertNotIn(regeln.regel_compaction_risiko, regeln.REGELN)


class CompactionRisikoAbgeschaltetTest(unittest.TestCase):
    def test_pruefe_meldet_compaction_trotz_hoher_position_nicht(self):
        beleg = baue_beleg()
        beleg.kennzahlen.compaction_positionen = [0.9]
        treffer = regeln.pruefe(beleg)
        signaturen = {a.signatur for a in treffer}
        self.assertNotIn("context:compaction_risk", signaturen)


PREISE = {"m": {"input": 1}}


def _runden_ereignisse(kosten_liste: list[float], subagenten_je_runde: dict[int, int] | None = None) -> list:
    """Baut je Wert in ``kosten_liste`` eine Runde (Nutzer + ein Assistent-Ereignis, dessen
    Input-Token-Zahl mit PREISE={"m": {"input": 1}} genau ``kosten`` Dollar ergibt), optional mit
    Subagent-Start-Ereignissen in einzelnen Runden (0-basierter Index -> Anzahl)."""
    subagenten_je_runde = subagenten_je_runde or {}
    ereignisse = []
    for i, kosten in enumerate(kosten_liste):
        ereignisse.append(nutzer_runde())
        ereignisse.append(assistent(Token(input=int(kosten * 1_000_000)), name="m"))
        ereignisse.extend(subagent_start() for _ in range(subagenten_je_runde.get(i, 0)))
    return ereignisse


class KostenspitzeTest(unittest.TestCase):
    def test_einzelspitze_meldet_warnung(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 10]))
        treffer = regeln.regel_kostenspitze(beleg, PREISE)
        single = [t for t in treffer if t.signatur == "cost:spike:single"]
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0].regel, "cost:spike")
        self.assertEqual(single[0].schwere, "warnung")
        self.assertEqual(single[0].ref, "6")
        self.assertEqual(single[0].wert, "Runde 6: 10.0x Median, 67 %")

    def test_delegationsspitze_senkt_schwere_auf_hinweis(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 10], {5: 3}))
        treffer = regeln.regel_kostenspitze(beleg, PREISE)
        delegation = [t for t in treffer if t.signatur == "cost:spike:delegation"]
        self.assertEqual(len(delegation), 1)
        self.assertEqual(delegation[0].regel, "cost:spike")
        self.assertEqual(delegation[0].schwere, "hinweis")
        self.assertEqual([t for t in treffer if t.signatur == "cost:spike:single"], [])

    def test_cluster_meldet_hinweis(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 4, 4, 4]))
        treffer = regeln.regel_kostenspitze(beleg, PREISE)
        cluster = [t for t in treffer if t.signatur == "cost:spike:cluster"]
        self.assertEqual(len(cluster), 1)
        self.assertEqual(cluster[0].schwere, "hinweis")
        self.assertEqual(cluster[0].wert, "letzte 3 Runden 4.0x Median")

    def test_top3_meldet_hinweis(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([3, 3, 3, 1, 1, 1, 1, 1, 1, 1]))
        treffer = regeln.regel_kostenspitze(beleg, PREISE)
        top3 = [t for t in treffer if t.signatur == "cost:spike:top3"]
        self.assertEqual(len(top3), 1)
        self.assertEqual(top3[0].schwere, "hinweis")
        self.assertEqual(top3[0].wert, "Top 3 = 56 %")
        self.assertEqual([t for t in treffer if t.signatur == "cost:spike:single"], [])

    def test_ohne_preise_keine_auffaelligkeit(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 10]))
        self.assertEqual(regeln.regel_kostenspitze(beleg, None), [])
        self.assertEqual(regeln.regel_kostenspitze(beleg), [])

    def test_unter_fuenf_runden_mit_kosten_keine_auffaelligkeit(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 10]))
        self.assertEqual(regeln.regel_kostenspitze(beleg, PREISE), [])

    def test_pruefe_ohne_preise_hat_keinen_cost_spike(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 10]))
        treffer = regeln.pruefe(beleg)
        self.assertFalse(any(t.regel == "cost:spike" for t in treffer))

    def test_pruefe_mit_preisen_liefert_cost_spike(self):
        beleg = baue_beleg(ereignisse=_runden_ereignisse([1, 1, 1, 1, 1, 10]))
        treffer = regeln.pruefe(beleg, PREISE)
        self.assertTrue(any(t.regel == "cost:spike" for t in treffer))


class LatenzTimeoutTest(unittest.TestCase):
    def test_zwei_timeouts_und_ein_slow_turn_getrennt_gebuendelt(self):
        timeout1 = tool("Bash", ref="t1")
        timeout1.dauer_ms = 120_000
        timeout2 = tool("Bash", ref="t2")
        timeout2.dauer_ms = 120_000
        langsam = tool("Bash", ref="t3")
        langsam.dauer_ms = 130_000
        beleg = baue_beleg(ereignisse=[timeout1, timeout2, langsam])
        treffer = regeln.regel_latenz(beleg)
        timeout_treffer = [t for t in treffer if t.signatur == "latency:timeout:tool:Bash"]
        slow_treffer = [t for t in treffer if t.signatur == "latency:slow_turn:tool:Bash"]
        self.assertEqual(len(timeout_treffer), 1)
        self.assertEqual(timeout_treffer[0].regel, "latency:timeout")
        self.assertEqual(timeout_treffer[0].schwere, "hinweis")
        self.assertEqual(timeout_treffer[0].wert, "2")
        self.assertEqual(len(slow_treffer), 1)
        self.assertEqual(slow_treffer[0].wert, "1 Aufrufe > 120 s")


if __name__ == "__main__":
    unittest.main()
