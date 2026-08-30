"""Tests für reingest.py (SQL-Generator, Stufe 2 Auftrag 2026-08-27) — Fake-LAUFER wie
in test_speicher_querschnitt.py, keine echte DB nötig."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .. import __main__ as main_mod
from .. import redaktion, reingest, speicher
from ..modell import Kopf

from .hilfen import baue_beleg


class FakePsql:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else ""


class DollarQuoteTest(unittest.TestCase):
    def test_einfacher_text(self) -> None:
        self.assertEqual(speicher.dollar_quote("hallo"), "$j$hallo$j$")

    def test_tag_kollision_weicht_auf_naechstes_tag_aus(self) -> None:
        text = "enthaelt $j$ mittendrin"
        quotiert = speicher.dollar_quote(text)
        self.assertEqual(quotiert, f"$j1${text}$j1$")
        self.assertNotIn("$j$" + text, quotiert)  # kein vorzeitiges Ende

    def test_mehrfache_kollision_zaehlt_weiter(self) -> None:
        text = "$j$ und $j1$ beide drin"
        quotiert = speicher.dollar_quote(text)
        self.assertTrue(quotiert.startswith("$j2$"))
        self.assertTrue(quotiert.endswith("$j2$"))


class SqlAuffaelligkeitenSelectTest(unittest.TestCase):
    def test_reingest_und_sql_einfuegen_teilen_dieselbe_select_form(self) -> None:
        """Beide Schreibwege nutzen dieselbe Funktion -- Regressionsschutz gegen Duplizierung."""
        beleg = baue_beleg()
        insert_sql = speicher.sql_einfuegen(beleg.als_dict(), "pc")
        self.assertIn("jsonb_build_object('wert', x.wert, 'ref', x.ref)", insert_sql)
        reingest_sql = reingest.sql_reingest_zeile(beleg.als_dict(), 7)
        self.assertIn("jsonb_build_object('wert', x.wert, 'ref', x.ref)", reingest_sql)


class SqlReingestZeileTest(unittest.TestCase):
    def _dokument(self, start="2026-08-25T10:00:00Z", ende="2026-08-25T10:10:00Z"):
        kopf = Kopf(quelle="claude", sitzung_id="s1", start=start, ende=ende)
        return baue_beleg(kopf=kopf).als_dict()

    def test_update_setzt_dokument_schema_version_nicht_ende(self) -> None:
        """ende/start bleiben stehen: ende ist Teil des Unique-Schluessels (ROLLBACK 2026-08-27)."""
        sql = reingest.sql_reingest_zeile(self._dokument(), 42)
        self.assertIn("UPDATE sitzung SET dokument = ", sql)
        self.assertIn("WHERE id = 42;", sql)
        self.assertNotIn("ende =", sql)
        self.assertNotIn("start =", sql)
        self.assertIn("schema_version = 1", sql)

    def test_delete_und_insert_referenzieren_dieselbe_id(self) -> None:
        sql = reingest.sql_reingest_zeile(self._dokument(), 42)
        self.assertIn("DELETE FROM sitzung_auffaelligkeit WHERE sitzung_ref = 42;", sql)
        self.assertIn("INSERT INTO sitzung_auffaelligkeit", sql)
        self.assertIn("WHERE s.id = 42;", sql)

    def test_dollar_tag_kollidiert_nicht_mit_json_inhalt(self) -> None:
        """Ein absichtlich in einem redigierten Feld enthaltenes '$j$' darf das Quoting
        nicht vorzeitig beenden (Auftrag: pruefen, dass $j$ nicht im JSON vorkommt)."""
        dokument = self._dokument()
        dokument["kopf"]["projekt_name"] = "enthaelt $j$ literal"
        sql = reingest.sql_reingest_zeile(dokument, 1)
        self.assertIn("$j1$", sql)  # auf naechstes Tag ausgewichen
        self.assertIn("enthaelt $j$ literal", sql)  # Inhalt unangetastet uebernommen

    def test_id_bleibt_erhalten_kein_insert_in_sitzung(self) -> None:
        sql = reingest.sql_reingest_zeile(self._dokument(), 99)
        self.assertNotIn("INSERT INTO sitzung (", sql)


class BaueDateiTest(unittest.TestCase):
    def test_wrapt_in_eine_transaktion(self) -> None:
        text = reingest.baue_datei(["UPDATE sitzung SET x = 1 WHERE id = 1;"])
        self.assertIn("BEGIN;", text)
        self.assertIn("COMMIT;", text)
        self.assertLess(text.index("BEGIN;"), text.index("UPDATE sitzung"))
        self.assertLess(text.index("UPDATE sitzung"), text.index("COMMIT;"))

    def test_leere_liste_ohne_begin_commit(self) -> None:
        text = reingest.baue_datei([])
        self.assertNotIn("BEGIN;", text)
        self.assertNotIn("COMMIT;", text)


class FindeSitzungIdTest(unittest.TestCase):
    def test_liefert_id_wenn_vorhanden(self) -> None:
        fake = FakePsql(["17"])
        treffer = reingest.finde_sitzung_id("pc", "claude", "s1", fake)
        self.assertEqual(treffer, 17)
        self.assertIn("host = 'pc'", fake.sql[0])
        self.assertIn("quelle = 'claude'", fake.sql[0])
        self.assertIn("sitzung_id = 's1'", fake.sql[0])
        self.assertIn("sitzung_aktuell", fake.sql[0])

    def test_liefert_none_ohne_treffer(self) -> None:
        fake = FakePsql([""])
        self.assertIsNone(reingest.finde_sitzung_id("pc", "claude", "s1", fake))


class BefehlReingestSqlTest(unittest.TestCase):
    """Orchestrierung in __main__: Zaehlung + Redaktions-Sperre + Datei-Ausgabe, ohne echte DB
    oder echte Transkripte (beleg_erzeugen/_transkripte/finde_sitzung_id gefaked)."""

    def _args(self, out: str):
        return main_mod._parser().parse_args(["reingest-sql", "--tage", "5", "--out", out])

    def test_gefundene_id_wird_aktualisiert_fehlende_uebersprungen(self) -> None:
        beleg_a = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="a"))
        beleg_b = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="b"))
        with mock.patch.object(main_mod, "_transkripte", side_effect=lambda q, s: [Path("a.jsonl"), Path("b.jsonl")] if q == "claude" else []), \
             mock.patch.object(main_mod, "beleg_erzeugen", side_effect=[beleg_a, beleg_b]), \
             mock.patch.object(reingest, "finde_sitzung_id", side_effect=[5, None]):
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "reingest.sql")
                args = self._args(out)
                code = main_mod._befehl_reingest_sql(args)
                self.assertEqual(code, 0)
                text = Path(out).read_text(encoding="utf-8")
        self.assertIn("WHERE id = 5;", text)
        self.assertIn("BEGIN;", text)

    def test_redaktionsfehler_zaehlt_als_uebersprungen_bricht_lauf_nicht_ab(self) -> None:
        beleg_kaputt = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="x", host=r"C:\geheim\pfad"))
        with mock.patch.object(main_mod, "_transkripte", side_effect=lambda q, s: [Path("x.jsonl")] if q == "claude" else []), \
             mock.patch.object(main_mod, "beleg_erzeugen", return_value=beleg_kaputt), \
             mock.patch.object(redaktion, "pruefe_beleg", return_value=["kopf.host: pfad"]):
            with tempfile.TemporaryDirectory() as tmp:
                out = str(Path(tmp) / "reingest.sql")
                args = self._args(out)
                code = main_mod._befehl_reingest_sql(args)
                self.assertEqual(code, 0)
                text = Path(out).read_text(encoding="utf-8")
        self.assertNotIn("BEGIN;", text)  # nichts zu aktualisieren


if __name__ == "__main__":
    unittest.main()
