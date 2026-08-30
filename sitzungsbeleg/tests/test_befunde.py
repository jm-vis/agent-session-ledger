"""Tests für befunde.py — Erledigt-Feature je Befund (Entscheid 2026-08-26, Auftrag 3)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from .. import befunde


class EntscheidBauenTest(unittest.TestCase):
    def test_baut_vollstaendiges_detail(self) -> None:
        jetzt = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        d = befunde.entscheid_bauen(
            "error:recurring:abc", "erledigt", "Fix in commit abc123", "behoben", 42, jetzt=jetzt
        )
        self.assertEqual(d["signatur"], "error:recurring:abc")
        self.assertEqual(d["status"], "erledigt")
        self.assertEqual(d["sitzung_ref"], 42)
        self.assertEqual(d["vermerk"], "Fix in commit abc123")
        self.assertEqual(d["begruendung"], "behoben")
        self.assertEqual(d["entschieden_von"], "Maintainer")
        self.assertTrue(d["entschieden_am"].startswith("2026-08-26"))

    def test_sitzung_ref_optional(self) -> None:
        d = befunde.entscheid_bauen("sig", "obsolet")
        self.assertIsNone(d["sitzung_ref"])

    def test_leere_signatur_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("", "erledigt")

    def test_fremder_status_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "geloescht")

    def test_status_offen_ist_gueltig(self) -> None:
        """Dritter Status (Entscheid B, 2026-08-26): `offen` = Wiedereröffnung, wird wie
        jeder andere Status als Entscheid-Ereignis geschrieben."""
        d = befunde.entscheid_bauen("sig", "offen")
        self.assertEqual(d["status"], "offen")

    def test_genau_drei_status_erlaubt(self) -> None:
        self.assertEqual(set(befunde.STATUS), {"erledigt", "obsolet", "offen"})

    def test_zu_langer_vermerk_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "erledigt", vermerk="x" * 501)

    def test_zu_lange_begruendung_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "erledigt", begruendung="x" * 501)

    def test_grenzwert_500_zeichen_geht_noch(self) -> None:
        d = befunde.entscheid_bauen("sig", "erledigt", vermerk="x" * 500)
        self.assertEqual(len(d["vermerk"]), 500)


class VerankerungParameterTest(unittest.TestCase):
    """C11: `entscheid_bauen(verankerung=...)` nimmt das Feld auf, normalisiert nur die
    Grundform (art/pfad Pflicht) -- die volle Feldpruefung macht `contracts.Verankerung`."""

    def test_ohne_verankerung_bleibt_das_feld_weg(self) -> None:
        d = befunde.entscheid_bauen("sig", "obsolet")
        self.assertNotIn("verankerung", d)

    def test_mit_verankerung_landet_normalisiert_im_detail(self) -> None:
        d = befunde.entscheid_bauen(
            "sig", "erledigt",
            verankerung={"art": " troubleshooting ", "pfad": " TROUBLESHOOTING.md ", "abschnitt": " X "},
        )
        self.assertEqual(
            d["verankerung"], {"art": "troubleshooting", "pfad": "TROUBLESHOOTING.md", "abschnitt": "X"}
        )

    def test_verankerung_ohne_abschnitt_bekommt_leerstring(self) -> None:
        d = befunde.entscheid_bauen("sig", "erledigt", verankerung={"art": "regel", "pfad": "CLAUDE.md"})
        self.assertEqual(d["verankerung"]["abschnitt"], "")

    def test_verankerung_ohne_pfad_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "erledigt", verankerung={"art": "regel", "pfad": ""})

    def test_verankerung_ohne_art_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "erledigt", verankerung={"pfad": "CLAUDE.md"})

    def test_verankerung_kein_objekt_wirft(self) -> None:
        with self.assertRaises(befunde.EntscheidFehler):
            befunde.entscheid_bauen("sig", "erledigt", verankerung="CLAUDE.md")


class JuengsterEntscheidTest(unittest.TestCase):
    def test_globaler_entscheid_gilt_fuer_jede_sitzung(self) -> None:
        entscheide = [
            {"signatur": "sig", "sitzung_ref": None, "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00"},
        ]
        self.assertEqual(befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 99)["status"], "erledigt")

    def test_sitzungsspezifischer_entscheid_gilt_nicht_fuer_andere_sitzung(self) -> None:
        entscheide = [
            {"signatur": "sig", "sitzung_ref": 5, "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00"},
        ]
        self.assertIsNone(befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 6))
        self.assertIsNotNone(befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 5))

    def test_juengster_gewinnt_bei_korrektur(self) -> None:
        entscheide = [
            {"signatur": "sig", "sitzung_ref": None, "status": "obsolet", "entschieden_am": "2026-08-20T10:00:00+00:00"},
            {"signatur": "sig", "sitzung_ref": None, "status": "erledigt", "entschieden_am": "2026-08-25T10:00:00+00:00"},
        ]
        ergebnis = befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 1)
        self.assertEqual(ergebnis["status"], "erledigt")

    def test_ohne_treffer_none(self) -> None:
        self.assertIsNone(befunde.juengster_je_signatur_und_sitzung([], "sig", 1))

    def test_andere_signatur_wird_ignoriert(self) -> None:
        entscheide = [{"signatur": "andere", "sitzung_ref": None, "status": "erledigt", "entschieden_am": "x"}]
        self.assertIsNone(befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 1))

    def test_offen_nach_erledigt_gewinnt_als_juengster(self) -> None:
        """Wiedereröffnung (Entscheid B, 2026-08-26): ein späterer `offen`-Entscheid
        schlägt einen früheren `erledigt` -- der Befund zählt wieder als offen."""
        entscheide = [
            {"signatur": "sig", "sitzung_ref": None, "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00"},
            {"signatur": "sig", "sitzung_ref": None, "status": "offen", "entschieden_am": "2026-08-25T10:00:00+00:00"},
        ]
        ergebnis = befunde.juengster_je_signatur_und_sitzung(entscheide, "sig", 1)
        self.assertEqual(ergebnis["status"], "offen")


class EntschiedeneSignaturenTest(unittest.TestCase):
    def test_globale_und_sitzungsspezifische_entscheide_zaehlen(self) -> None:
        entscheide = [
            {"signatur": "a", "sitzung_ref": None, "status": "erledigt"},
            {"signatur": "b", "sitzung_ref": 7, "status": "obsolet"},
        ]
        self.assertEqual(befunde.entschiedene_signaturen(entscheide, 7), {"a", "b"})
        self.assertEqual(befunde.entschiedene_signaturen(entscheide, 8), {"a"})

    def test_leere_liste(self) -> None:
        self.assertEqual(befunde.entschiedene_signaturen([], 1), set())

    def test_offen_nach_erledigt_zaehlt_wieder_als_offen(self) -> None:
        """Wiedereröffnung (Entscheid B, 2026-08-26): jüngster Entscheid `offen` nimmt die
        Signatur wieder aus der Ausschlussmenge -- der Befund zählt wieder mit."""
        entscheide = [
            {"signatur": "sig", "sitzung_ref": None, "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00"},
            {"signatur": "sig", "sitzung_ref": None, "status": "offen", "entschieden_am": "2026-08-25T10:00:00+00:00"},
        ]
        self.assertEqual(befunde.entschiedene_signaturen(entscheide, 1), set())


class StatusMitRueckfallTest(unittest.TestCase):
    """Rückfall-Erkennung (Entscheid 2026-08-26): eine Signatur mit jüngstem Entscheid
    erledigt/obsolet gilt als Rückfall, wenn sie NACH `entschieden_am` erneut auftritt."""

    def test_treffer_nach_entscheid_ist_rueckfall(self) -> None:
        entscheide = [{"signatur": "sig", "sitzung_ref": None, "status": "erledigt",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        sitzungen = [{"sitzung_id": 5, "zeit": "2026-08-21T09:00:00+00:00", "treffer": 3}]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", sitzungen)
        self.assertEqual(ergebnis["status"], "rueckfall")
        self.assertEqual(ergebnis["rueckfall_treffer"], 3)
        self.assertEqual(ergebnis["rueckfall_sitzungen"], {"anzahl": 1, "sitzung_ids": [5]})
        self.assertEqual(ergebnis["entschieden_am"], "2026-08-20T10:00:00+00:00")

    def test_treffer_nur_vor_entscheid_bleibt_erledigt(self) -> None:
        entscheide = [{"signatur": "sig", "sitzung_ref": None, "status": "erledigt",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        sitzungen = [{"sitzung_id": 4, "zeit": "2026-08-19T09:00:00+00:00", "treffer": 2}]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", sitzungen)
        self.assertEqual(ergebnis, {"status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00"})

    def test_offen_entscheid_danach_gewinnt_als_offen(self) -> None:
        entscheide = [
            {"signatur": "sig", "sitzung_ref": None, "status": "erledigt",
             "entschieden_am": "2026-08-20T10:00:00+00:00"},
            {"signatur": "sig", "sitzung_ref": None, "status": "offen",
             "entschieden_am": "2026-08-25T10:00:00+00:00"},
        ]
        sitzungen = [{"sitzung_id": 6, "zeit": "2026-08-26T09:00:00+00:00", "treffer": 1}]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", sitzungen)
        self.assertEqual(ergebnis, {"status": "offen"})

    def test_obsolet_ohne_neue_sitzung_bleibt_obsolet(self) -> None:
        entscheide = [{"signatur": "sig", "sitzung_ref": None, "status": "obsolet",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", [])
        self.assertEqual(ergebnis["status"], "obsolet")

    def test_obsolet_mit_neuer_sitzung_bleibt_obsolet_kein_rueckfall(self) -> None:
        """Nachtrag 2026-08-27 Punkt 4: C2 kennt Rückfall NUR für `erledigt` -- `obsolet` bleibt
        `obsolet`, auch wenn danach neue Treffer auftauchen (Fehlerbilder-Seite zeigte bisher
        faelschlich RUECKFALL fuer obsolet erklaerte Signaturen, live an Sitzung 137 verifiziert)."""
        entscheide = [{"signatur": "sig", "sitzung_ref": None, "status": "obsolet",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        sitzungen = [{"sitzung_id": 5, "zeit": "2026-08-21T09:00:00+00:00", "treffer": 3}]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", sitzungen)
        self.assertEqual(ergebnis, {"status": "obsolet", "entschieden_am": "2026-08-20T10:00:00+00:00"})

    def test_kein_entscheid_ist_offen(self) -> None:
        self.assertEqual(befunde.status_mit_rueckfall([], "sig", []), {"status": "offen"})

    def test_mehrere_rueckfall_sitzungen_summieren_treffer(self) -> None:
        entscheide = [{"signatur": "sig", "sitzung_ref": None, "status": "erledigt",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        sitzungen = [
            {"sitzung_id": 5, "zeit": "2026-08-21T09:00:00+00:00", "treffer": 3},
            {"sitzung_id": 7, "zeit": "2026-08-22T09:00:00+00:00", "treffer": 2},
            {"sitzung_id": 2, "zeit": "2026-08-19T09:00:00+00:00", "treffer": 9},  # vor Entscheid
        ]
        ergebnis = befunde.status_mit_rueckfall(entscheide, "sig", sitzungen)
        self.assertEqual(ergebnis["rueckfall_treffer"], 5)
        self.assertEqual(ergebnis["rueckfall_sitzungen"], {"anzahl": 2, "sitzung_ids": [5, 7]})

    def test_sitzungsspezifischer_entscheid_zaehlt_nicht_fuer_rueckfall_pruefung(self) -> None:
        """Nur GLOBALE Entscheide (sitzung_ref None) gelten für den Rückfall-Check -- die
        Signatur bleibt ohne globalen Entscheid schlicht `offen`."""
        entscheide = [{"signatur": "sig", "sitzung_ref": 3, "status": "erledigt",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        self.assertEqual(befunde.status_mit_rueckfall(entscheide, "sig", []), {"status": "offen"})


if __name__ == "__main__":
    unittest.main()
