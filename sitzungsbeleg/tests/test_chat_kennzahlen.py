"""Tests für chat_kennzahlen.baue_block() — Fixture-Kennzahlen, keine DB (Fund 2026-08-27: die
Besprechungs-Spalte kannte nur die Sitzungs-ID, kein Modell konnte Kennzahlenfragen beantworten)."""
from __future__ import annotations

import unittest

from sitzungsbeleg import chat_kennzahlen, kennzahlen, quellen
from sitzungsbeleg.modell import Kopf, Token

from .hilfen import assistent, baue_beleg, nutzer_runde, tool, tool_ergebnis


def _antwort(auffaelligkeiten=None, vieraugen=None, kopf=None) -> dict:
    """Baut eine `_sitzung()`-foermige Antwort aus einem echten, verdichteten Beleg (dieselbe
    `kennzahlen.berechne()` wie die Detailseite -- kein Sonderpfad nur fuer diese Tests)."""
    beleg = baue_beleg(
        kopf=kopf,
        ereignisse=[
            nutzer_runde(), assistent(token=Token(input=100, output=50, cache_read=10)),
            tool("Read"), tool_ergebnis(),
        ],
    )
    kennzahlen.berechne(beleg, preise={"claude-sonnet-5": {"input": 3, "output": 15}}, waehrung="USD")
    dokument = beleg.als_dict()
    dokument["auffaelligkeiten"] = auffaelligkeiten or []
    return {"sitzung_logisch": 137, "dokument": dokument, "vieraugen": vieraugen}


class BlockInhaltTest(unittest.TestCase):
    def test_enthaelt_kopf_und_kennzahlen(self):
        block = chat_kennzahlen.baue_block(_antwort())
        self.assertIn("Sitzung 137", block)
        self.assertIn("Quelle claude", block)
        self.assertIn("Runden 1", block)
        self.assertIn("Tools 1", block)
        self.assertIn("Token ein 100", block)
        self.assertIn("Kosten ", block)
        self.assertIn("Latenz p50", block)
        self.assertIn("Compactions 0", block)
        self.assertIn("Subagenten 0", block)

    def test_ohne_befunde_zeigt_keine(self):
        block = chat_kennzahlen.baue_block(_antwort())
        self.assertIn("Befunde: keine", block)

    def test_befund_traegt_regel_status_titel(self):
        befund = {"regel": "rework:tool", "status": "bestaetigt", "titel": "Werkzeug-Nacharbeit", "signatur": "s1"}
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=[befund]))
        self.assertIn("rework:tool [bestaetigt] Werkzeug-Nacharbeit", block)

    def test_befund_traegt_vier_augen_urteil_wenn_vorhanden(self):
        befund = {
            "regel": "cost:spike", "status": "dissens", "titel": "Kostenspitze",
            "pruefung": {"claude": "ja", "codex": "nein"},
        }
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=[befund]))
        self.assertIn("Claude=ja Codex=nein", block)

    def test_hoechstens_zwoelf_befunde(self):
        befunde = [{"regel": f"r{i}", "status": "offen", "titel": f"Titel {i}"} for i in range(20)]
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=befunde))
        self.assertEqual(block.count("[offen]"), chat_kennzahlen.MAX_BEFUNDE)

    def test_vieraugen_altlauf_zeile_nur_wenn_vorhanden(self):
        ohne = chat_kennzahlen.baue_block(_antwort())
        self.assertNotIn("Vier-Augen", ohne)
        mit = chat_kennzahlen.baue_block(_antwort(vieraugen={"dissens": 2}))
        self.assertIn("Vier-Augen (Altlauf): dissens 2", mit)

    def test_erfassung_stempel_enthalten(self):
        block = chat_kennzahlen.baue_block(_antwort())
        self.assertIn("Erfassung: token=", block)

    def test_kosten_unbekannt_ohne_preise(self):
        beleg = baue_beleg(ereignisse=[nutzer_runde(), assistent()])
        kennzahlen.berechne(beleg)  # keine Preise -> kosten_gesamt bleibt None
        antwort = {"sitzung_logisch": 1, "dokument": beleg.als_dict(), "vieraugen": None}
        block = chat_kennzahlen.baue_block(antwort)
        self.assertIn("Kosten unbekannt", block)

    def test_dauer_und_latenz_in_menschenlesbaren_einheiten(self):
        """Fund 2026-08-27 (Coordinator-Nachtrag): rohe Millisekunden sind fuer eine Besprechung
        unlesbar -- reuse `ausgabe.dauer_lesbar()` statt eigener Millisekunden-Ausgabe. Werte aus
        der echten Sitzung 137 (Dauer 31654532 ms, Latenz p50 62616 ms)."""
        kopf = Kopf(quelle="claude", sitzung_id="s1", start="2026-08-25T10:00:00Z", ende="2026-08-25T18:47:34Z")
        beleg = baue_beleg(kopf=kopf, ereignisse=[nutzer_runde(), assistent()])
        kennzahlen.berechne(beleg)  # dauer_ms aus kopf.start/ende; keine ART_RUNDE_ENDE -> Latenzen 0
        beleg.kennzahlen.latenz_p50_ms = 62_616
        beleg.kennzahlen.latenz_p95_ms = 1_500_000
        antwort = {"sitzung_logisch": 137, "dokument": beleg.als_dict(), "vieraugen": None}
        block = chat_kennzahlen.baue_block(antwort)
        self.assertIn("Dauer 8 h 47 min", block)
        self.assertIn("Latenz p50 1 min 2 s", block)
        self.assertIn("p95 25 min 0 s", block)  # ausgabe.dauer_lesbar() reused verbatim (< 1 h -> "min s")
        self.assertNotIn(" ms", block)

    def test_token_mit_tausendertrennung_und_cache_kompakt(self):
        beleg = baue_beleg(ereignisse=[
            nutzer_runde(),
            assistent(token=Token(input=74_976, output=426_292, cache_read=78_000_000, cache_write=422_789)),
        ])
        kennzahlen.berechne(beleg)
        antwort = {"sitzung_logisch": 137, "dokument": beleg.als_dict(), "vieraugen": None}
        block = chat_kennzahlen.baue_block(antwort)
        self.assertIn("Token ein 74.976, aus 426.292", block)
        self.assertIn("cache 78,4M", block)

    def test_synthetisches_platzhaltermodell_faellt_aus_der_liste(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=[quellen.SYNTHETISCH, "claude-fable-5"])
        block = chat_kennzahlen.baue_block(_antwort(kopf=kopf))
        self.assertIn("Modell claude-fable-5", block)
        self.assertNotIn(quellen.SYNTHETISCH, block)


class RedaktionUndDeckelungTest(unittest.TestCase):
    def test_eingeschmuggelter_pfad_im_titel_redigiert_ganzen_block(self):
        befund = {"regel": "r1", "status": "offen", "titel": r"C:\Users\alice\geheim"}
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=[befund]))
        self.assertEqual(block, "<redigiert>")

    def test_eingeschmuggelte_email_im_titel_redigiert_ganzen_block(self):
        befund = {"regel": "r1", "status": "offen", "titel": "kontakt person@example.invalid"}
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=[befund]))
        self.assertEqual(block, "<redigiert>")

    def test_lokal_wort_redigiert_ganzen_block(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", projekt_name="20_Journal_lokal")
        block = chat_kennzahlen.baue_block(_antwort(kopf=kopf))
        self.assertEqual(block, "<redigiert>")

    def test_deckelung_auf_maximal_1500_zeichen(self):
        befunde = [
            {"regel": f"regel:{i}", "status": "offen", "titel": "x" * 80}
            for i in range(chat_kennzahlen.MAX_BEFUNDE)
        ]
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=befunde))
        self.assertLessEqual(len(block), chat_kennzahlen.MAX_ZEICHEN)

    def test_regeltitel_mit_woertlichem_schraegstrich_loest_keine_redaktion_aus(self):
        """Live an Sitzung 137 verifiziert: der feste Regeltitel "Langsame Runde/Werkzeug"
        (regeltexte.py, keine Transkript-/Nutzerdaten) hat bisher den GANZEN Block redigiert,
        weil C3 jeden Schraegstrich als Pfadverdacht wertet -- muss lesbar durchgehen."""
        befund = {"regel": "latency:slow_turn", "status": "bestaetigt", "titel": "Langsame Runde/Werkzeug"}
        block = chat_kennzahlen.baue_block(_antwort(auffaelligkeiten=[befund]))
        self.assertNotEqual(block, "<redigiert>")
        self.assertIn("Langsame Runde bzw. Werkzeug", block)

    def test_kein_schraegstrich_im_unredigierten_block(self):
        """Eigene Formatierung darf C3 (jeder Schraegstrich = Pfadverdacht) nicht selbst
        ausloesen -- sonst waere der Block IMMER redigiert (Regressionsschutz fuer das eigene
        Format, nicht fuer Nutzdaten)."""
        block = chat_kennzahlen.baue_block(_antwort())
        self.assertNotEqual(block, "<redigiert>")
        self.assertNotIn("/", block)


class NachschlageTextTest(unittest.TestCase):
    """`python -m sitzungsbeleg nachschlagen` (Nachtrag Sichtkontext 2026-08-28) --
    Kennzahlen-Block + volle Befundliste mit Status und Vier-Augen-Urteil."""

    def _befunde(self):
        return [
            {"regel": "rework:tool", "signatur": "rework:tool:Bash", "status": "bestaetigt",
             "titel": "Werkzeug-Nacharbeit", "pruefung": {"claude": "ja", "codex": "ja", "ergebnis": "bestaetigt"}},
            {"regel": "cost:spike", "signatur": "cost:spike:single", "status": "offen", "titel": "Kostenspitze"},
        ]

    def test_enthaelt_kennzahlen_block_und_volle_befundliste(self):
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=self._befunde()))
        self.assertIn("Sitzung 137", text)
        self.assertIn("rework:tool:Bash [bestaetigt] Werkzeug-Nacharbeit", text)
        self.assertIn("Claude=ja Codex=ja Ergebnis=bestaetigt", text)
        self.assertIn("cost:spike:single [offen] Kostenspitze -- keine Pruefung", text)

    def test_mehr_als_zwoelf_befunde_stehen_alle_drin(self):
        """Anders als der knappe Chat-Kontext-Block (`MAX_BEFUNDE=12`) -- dieses Werkzeug ist eine
        gezielte Nachfrage, keine Dauerlast im Kontextfenster: die 20. Signatur (weit ueber dem
        Deckel des Kontext-Blocks) muss trotzdem in der vollen Befundliste stehen."""
        befunde = [{"regel": f"r{i}", "signatur": f"s{i}", "status": "offen", "titel": f"Titel {i}"}
                   for i in range(20)]
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=befunde))
        self.assertIn("s19 [offen] Titel 19", text)

    def test_ohne_befunde_meldet_keine(self):
        text = chat_kennzahlen.baue_nachschlage_text(_antwort())
        self.assertIn("Befunde: keine", text)

    def test_befund_filter_zeigt_nur_die_gesuchte_signatur(self):
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=self._befunde()), befund="cost:spike:single")
        self.assertIn("cost:spike:single", text)
        self.assertNotIn("rework:tool:Bash", text)

    def test_unbekannte_signatur_meldet_nicht_gefunden(self):
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=self._befunde()), befund="unbekannt:xyz")
        self.assertIn("Befund unbekannt:xyz: nicht gefunden", text)

    def test_deckelung_auf_maximal_dreitausend_zeichen(self):
        befunde = [{"regel": f"regel:{i}", "signatur": f"s{i}", "status": "offen", "titel": "x" * 80}
                   for i in range(40)]
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=befunde))
        self.assertLessEqual(len(text), chat_kennzahlen.MAX_NACHSCHLAGE_ZEICHEN)

    def test_pfad_im_befundtitel_redigiert_den_ganzen_text(self):
        befund = {"regel": "r1", "signatur": "s1", "status": "offen", "titel": r"C:\Users\alice\geheim"}
        text = chat_kennzahlen.baue_nachschlage_text(_antwort(auffaelligkeiten=[befund]))
        self.assertEqual(text, "<redigiert>")


if __name__ == "__main__":
    unittest.main()
