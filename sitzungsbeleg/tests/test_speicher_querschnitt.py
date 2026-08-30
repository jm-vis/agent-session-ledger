"""Stufe 2: speicher.py + querschnitt.py mit Fake-psql (kein Docker in Unit-Tests)."""
from __future__ import annotations

import unittest

from .. import querschnitt, speicher
from ..modell import ART_TOOL_ERGEBNIS, Auffaelligkeit, Ereignis

from .hilfen import baue_beleg


class FakePsql:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else ""


class SpeichernTest(unittest.TestCase):
    def test_sql_traegt_dokument_und_auffaelligkeiten_in_einem_statement(self) -> None:
        beleg = baue_beleg()
        beleg.auffaelligkeiten.append(Auffaelligkeit(regel="r", schwere="hinweis", signatur="s", wert="1"))
        sql = speicher.sql_einfuegen(beleg.als_dict(), "pc")
        self.assertIn("INSERT INTO sitzung ", sql)
        self.assertIn("INSERT INTO sitzung_auffaelligkeit", sql)
        self.assertIn("ON CONFLICT DO NOTHING", sql)
        self.assertEqual(sql.count(";"), 1)

    def test_sql_einfuegen_legt_logische_sitzung_an_und_verdrahtet_logisch_ref(self) -> None:
        """C1 Regel 3: die CTE `l` legt/findet die logische Zeile, `s` (Version) und `a`
        (Auffaelligkeiten) tragen `logisch_ref` aus derselben `l`-Zeile."""
        beleg = baue_beleg()
        beleg.auffaelligkeiten.append(Auffaelligkeit(regel="r", schwere="hinweis", signatur="s", wert="1"))
        sql = speicher.sql_einfuegen(beleg.als_dict(), "pc")
        self.assertIn("INSERT INTO sitzung_logisch (host, quelle, sitzung_id, projekt)", sql)
        # Sequence-Fix (Maintainer 2026-08-28): erst SELECT (l0), Insert (li) nur bei Nichtvorhandensein,
        # ON CONFLICT DO NOTHING statt DO UPDATE -- kein Sequence-Verbrauch im Alltagsfall.
        self.assertIn("WHERE NOT EXISTS (SELECT 1 FROM l0)", sql)
        self.assertIn("ON CONFLICT (host, quelle, sitzung_id) DO NOTHING", sql)
        self.assertIn(", logisch_ref)", sql)  # sitzung-Insert traegt die Spalte
        self.assertIn("l.id", sql)
        self.assertIn("s.logisch_ref", sql)  # Auffaelligkeiten-SELECT liest sie aus der Version

    def test_sql_literal_escaped_apostroph(self) -> None:
        self.assertEqual(speicher.sql_literal("a'b"), "'a''b'")

    def test_speichern_liefert_id_oder_none(self) -> None:
        fake = FakePsql(["42", ""])
        self.assertEqual(speicher.speichern(baue_beleg(), "pc", fake), 42)
        self.assertIsNone(speicher.speichern(baue_beleg(), "pc", fake))

    def test_logisch_fuer_version_liefert_int_oder_none(self) -> None:
        fake = FakePsql(["512", ""])
        self.assertEqual(speicher.logisch_fuer_version(1284, fake), 512)
        self.assertIsNone(speicher.logisch_fuer_version(999999, fake))
        self.assertIn("WHERE id = 1284", fake.sql[0])

    def test_psql_fehler_wird_speicherfehler(self) -> None:
        alt = speicher.CONTAINER
        speicher.CONTAINER = "gibt-es-nicht-4711"
        try:
            with self.assertRaises(speicher.SpeicherFehler):
                speicher.psql("SELECT 1;", zeitlimit_s=8)
        finally:
            speicher.CONTAINER = alt

    def test_lade_dokument_parst_json(self) -> None:
        fake = FakePsql(['{"kopf": {"quelle": "claude"}}'])
        self.assertEqual(speicher.lade_dokument(7, fake)["kopf"]["quelle"], "claude")
        self.assertIn("WHERE id = 7", fake.sql[0])


class QuerschnittTest(unittest.TestCase):
    def _beleg_mit_fehlern(self):
        beleg = baue_beleg(ereignisse=[
            Ereignis(zeit="2026-08-26T08:00:00Z", art=ART_TOOL_ERGEBNIS, fehler=True, signatur="abc"),
            Ereignis(zeit="2026-08-26T08:00:01Z", art=ART_TOOL_ERGEBNIS, fehler=True, signatur="abc"),
            Ereignis(zeit="2026-08-26T08:00:02Z", art=ART_TOOL_ERGEBNIS, fehler=False, signatur="zzz"),
        ])
        return beleg

    def test_fehler_signaturen_nur_fehler_dedupliziert(self) -> None:
        self.assertEqual(querschnitt.fehler_signaturen(self._beleg_mit_fehlern()), ["abc"])

    def test_wiederkehrende_fehler_aus_db_antwort(self) -> None:
        fake = FakePsql(["abc|4"])
        treffer = querschnitt.wiederkehrende_fehler(self._beleg_mit_fehlern(), fake)
        self.assertEqual(treffer[0].signatur, "error:recurring:abc")
        self.assertIn("'abc'", fake.sql[0])
        self.assertIn(">= 3", fake.sql[0])

    def test_ohne_fehler_keine_abfrage(self) -> None:
        fake = FakePsql([])
        self.assertEqual(querschnitt.wiederkehrende_fehler(baue_beleg(), fake), [])
        self.assertEqual(fake.sql, [])

    def test_p95_sql_schliesst_aktuelle_sitzung_aus_und_nutzt_ende(self) -> None:
        sql = querschnitt.sql_kosten_p95(42)
        self.assertIn("id <> 42", sql)
        self.assertIn("coalesce(ende, start, zeitstempel)", sql)
        self.assertIn("count(DISTINCT s.id)", querschnitt.sql_wiederkehrende_fehler(["a"]))

    def test_kosten_ausreisser_erst_ab_zehn_sitzungen(self) -> None:
        beleg = baue_beleg()
        beleg.kennzahlen.kosten = 9.0
        self.assertEqual(querschnitt.kosten_ausreisser(beleg, FakePsql(["5.0|9"])), [])
        self.assertEqual(querschnitt.kosten_ausreisser(beleg, FakePsql(["5.0|10"]))[0].regel, "cost:outlier")
        self.assertEqual(querschnitt.kosten_ausreisser(beleg, FakePsql(["9.5|10"])), [])

    def test_pruefe_und_speichere_haengt_treffer_an(self) -> None:
        beleg = self._beleg_mit_fehlern()
        beleg.kennzahlen.kosten = None
        fake = FakePsql(["abc|3", ""])
        treffer = querschnitt.pruefe_und_speichere(beleg, 5, fake)
        self.assertEqual(len(treffer), 1)
        self.assertIn("INSERT INTO sitzung_auffaelligkeit", fake.sql[-1])
        self.assertIn("WHERE id = 5", fake.sql[-1])

    def test_pruefe_und_speichere_haengt_erfassungsluecken_an(self) -> None:
        """capture:gap steht schon in beleg.auffaelligkeiten (regeln.pruefe) — muss zusaetzlich
        in die flache Tabelle, sonst bleibt /api/querschnitt fuer diese Kachel immer leer."""
        beleg = baue_beleg()
        beleg.kennzahlen.kosten = None
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="capture:gap", schwere="hinweis", signatur="capture:gap:token", wert="token")
        ]
        fake = FakePsql([])
        treffer = querschnitt.pruefe_und_speichere(beleg, 7, fake)
        self.assertEqual(treffer, [])  # keine neue Sitzungs-Auffaelligkeit, nur die DB-Zeile
        self.assertEqual(len(fake.sql), 1)
        self.assertIn("INSERT INTO sitzung_auffaelligkeit", fake.sql[0])
        self.assertIn("capture:gap:token", fake.sql[0])
        self.assertIn("WHERE id = 7", fake.sql[0])

    def test_pruefe_und_speichere_ohne_erfassungsluecken_keine_zusaetzliche_zeile(self) -> None:
        beleg = baue_beleg()
        beleg.kennzahlen.kosten = None
        fake = FakePsql([])
        treffer = querschnitt.pruefe_und_speichere(beleg, 7, fake)
        self.assertEqual(treffer, [])
        self.assertEqual(fake.sql, [])


if __name__ == "__main__":
    unittest.main()
