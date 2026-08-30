"""Sequence-Fix (Auftrag 2026-08-28): `_sql_logisch_cte` macht erst SELECT (`l0`), dann
INSERT (`li`) -- der Alltagsfall (Sitzung existiert schon) darf keinen Wert aus
`sitzung_logisch_id_seq` mehr verbrennen. Fake-laufer statt echter DB, wie
test_speicher_querschnitt.py."""
from __future__ import annotations

import unittest

from .. import speicher

from .hilfen import baue_beleg


class FakePsql:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else ""


class SqlLogischCteSequenceTest(unittest.TestCase):
    def _sql(self) -> str:
        return speicher.sql_einfuegen(baue_beleg().als_dict(), "pc")

    def test_select_kommt_vor_insert(self) -> None:
        """Reihenfolge im WITH-Statement: erst l0 (SELECT), dann li (INSERT) -- sonst
        verbrennt der Alltagsfall (Sitzung existiert schon) weiterhin einen Sequence-Wert."""
        sql = self._sql()
        pos_l0 = sql.index("l0 AS (")
        pos_select = sql.index("SELECT sl.id FROM sitzung_logisch sl, dok")
        pos_li = sql.index("li AS (")
        pos_insert = sql.index("INSERT INTO sitzung_logisch")
        pos_l = sql.index("l AS (SELECT id FROM l0 UNION ALL SELECT id FROM li)")
        self.assertLess(pos_l0, pos_select)
        self.assertLess(pos_select, pos_li)
        self.assertLess(pos_li, pos_insert)
        self.assertLess(pos_insert, pos_l)

    def test_insert_nur_bei_fehlender_zeile(self) -> None:
        sql = self._sql()
        self.assertIn("WHERE NOT EXISTS (SELECT 1 FROM l0)", sql)

    def test_kein_do_update_mehr_fuer_sitzung_logisch(self) -> None:
        """Das alte `DO UPDATE SET host = EXCLUDED.host` existierte nur, damit RETURNING auch
        im Konfliktfall liefert -- das uebernimmt jetzt l0. Die sitzung-CTE behaelt ihr eigenes
        `ON CONFLICT DO NOTHING` (Beleg-Ebene), das bleibt unberuehrt."""
        sql = self._sql()
        self.assertNotIn("DO UPDATE", sql)
        self.assertIn("ON CONFLICT (host, quelle, sitzung_id) DO NOTHING", sql)  # sitzung_logisch
        self.assertIn("ON CONFLICT DO NOTHING", sql)  # sitzung (Beleg-Ebene, unveraendert)

    def test_l_cte_bleibt_eine_einzige_quelle_mit_spalte_id(self) -> None:
        """Aufrufer (sql_einfuegen -> s-CTE) erwartet weiterhin genau eine CTE `l` mit `id`."""
        sql = self._sql()
        self.assertIn("l AS (SELECT id FROM l0 UNION ALL SELECT id FROM li)", sql)
        self.assertIn("FROM dok, l", sql)  # s-CTE liest weiterhin aus l.id
        self.assertEqual(sql.count(";"), 1)  # weiterhin ein einziges Statement

    def test_speichern_unveraendert_id_oder_none(self) -> None:
        fake = FakePsql(["42", ""])
        self.assertEqual(speicher.speichern(baue_beleg(), "pc", fake), 42)
        self.assertIsNone(speicher.speichern(baue_beleg(), "pc", fake))


if __name__ == "__main__":
    unittest.main()
