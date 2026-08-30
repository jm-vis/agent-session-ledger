"""Kachel "Prüfung offen" (Phase 2 E) -- reine Aggregation (`offene_paare`) + Endpunkt-Verkabelung
über `web.app` (das Modul haengt sein Router in web.py per `include_router` ein)."""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from .. import befund_kacheln, pruefung, web
from .test_web import FakeLaufer


def _entscheid(status: str, sitzung_ref=None, signatur: str = "sig") -> dict:
    return {"signatur": signatur, "sitzung_ref": sitzung_ref, "status": status, "entschieden_am": "2026-08-20T10:00:00+00:00"}


def _lauf(sitzung_logisch: int, signatur: str, ergebnis: str, gestartet: str = "2026-08-21T10:00:00+00:00") -> dict:
    return {
        "sitzung_logisch": sitzung_logisch, "gestartet": gestartet,
        "urteile": [{"signatur": signatur, "ergebnis": ergebnis}],
    }


class OffenePaareTest(unittest.TestCase):
    """Reine Funktion -- kein SQL, kein FastAPI (C2-Ableitung wie in `pruefung.status_fuer`)."""

    def test_befund_ohne_historie_zaehlt_als_offen(self) -> None:
        offene = befund_kacheln.offene_paare([(512, "rework:tool:Bash")], [], [], [])
        self.assertEqual(offene, {(512, "rework:tool:Bash")})

    def test_entschiedener_befund_zaehlt_nicht(self) -> None:
        entscheide = [_entscheid("erledigt", signatur="rework:tool:Bash")]
        offene = befund_kacheln.offene_paare([(512, "rework:tool:Bash")], entscheide, [], [])
        self.assertEqual(offene, set())

    def test_bereits_geprueft_bestaetigt_zaehlt_nicht(self) -> None:
        laeufe = [_lauf(512, "rework:tool:Bash", "bestaetigt")]
        offene = befund_kacheln.offene_paare([(512, "rework:tool:Bash")], [], laeufe, [])
        self.assertEqual(offene, set())

    def test_laufender_lauf_zaehlt_nicht_als_offen(self) -> None:
        laufend = [{"sitzung_logisch": 512, "signaturen": ["rework:tool:Bash"], "scope": "befund"}]
        offene = befund_kacheln.offene_paare([(512, "rework:tool:Bash")], [], [], laufend)
        self.assertEqual(offene, set())

    def test_wiedereroeffnung_zaehlt_wieder_als_offen(self) -> None:
        entscheide = [
            _entscheid("erledigt", signatur="x", ),
            {"signatur": "x", "sitzung_ref": None, "status": "offen", "entschieden_am": "2026-08-22T10:00:00+00:00"},
        ]
        offene = befund_kacheln.offene_paare([(512, "x")], entscheide, [], [])
        self.assertEqual(offene, {(512, "x")})

    def test_mehrere_sitzungen_gemischt(self) -> None:
        entscheide = [_entscheid("erledigt", signatur="a")]
        zeilen = [(1, "a"), (2, "b"), (3, "a")]
        # "a" ist GLOBAL entschieden (sitzung_ref=None) -> gilt fuer sitzung 1 UND 3 nicht mehr offen.
        offene = befund_kacheln.offene_paare(zeilen, entscheide, [], [])
        self.assertEqual(offene, {(2, "b")})


class SqlBausteineTest(unittest.TestCase):
    def test_sql_offene_auffaelligkeiten_enthaelt_zeitraum_und_view(self) -> None:
        import datetime as dt
        sql = befund_kacheln.sql_offene_auffaelligkeiten(dt.date(2026, 8, 20), dt.date(2026, 8, 26))
        self.assertIn("sitzung_aktuell", sql)
        self.assertIn("2026-08-20", sql)
        self.assertIn("2026-08-26", sql)

    def test_sql_ereignisse_filtert_quelle_und_typ(self) -> None:
        sql = befund_kacheln.sql_ereignisse("gf", "befund_entscheid")
        self.assertIn("quelle = 'gf'", sql)
        self.assertIn("typ = 'befund_entscheid'", sql)


class EndpunktTest(unittest.TestCase):
    """Verkabelung web.app -> befund_kacheln.router (include_router, web.py Dateiende)."""

    def setUp(self) -> None:
        self.alt = befund_kacheln.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        befund_kacheln.LAUFER = self.alt

    def test_endpunkt_liefert_anzahl_und_sitzung_ids(self) -> None:
        # FakeLaufer antwortet nach erstem Substring-Treffer -- Zeilenformat "id|signatur"
        # (psql -A -F'|', wie `speicher.psql`).
        fake = FakeLaufer({"sitzung_aktuell": "512|rework:tool:Bash", "quelle = 'gf'": "[]", "quelle = 'pruefung'": "[]"})
        befund_kacheln.LAUFER = fake
        antwort = self.client.get("/api/kacheln/pruefung-offen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"anzahl": 1, "sitzung_ids": [512]})

    def test_legacy_vieraugen_urteil_zaehlt_nicht_als_offen(self) -> None:
        """Nachtrag 2026-08-27 Punkt 1: dieselbe Legacy-Vieraugen-Bruecke wie `pruefung.anreichern`
        muss auch fuer die Kachel gelten, sonst zaehlt ein laengst geprueftes Alt-Urteil mit."""
        vieraugen = [{"sitzung_logisch": 512, "befunde": [{"signatur": "rework:tool:Bash", "status": "bestaetigt"}]}]
        fake = FakeLaufer({
            "sitzung_aktuell": "512|rework:tool:Bash", "quelle = 'gf'": "[]",
            "quelle = 'pruefung'": "[]", "quelle = 'vieraugen'": json.dumps(vieraugen),
        })
        befund_kacheln.LAUFER = fake
        antwort = self.client.get("/api/kacheln/pruefung-offen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.json(), {"anzahl": 0, "sitzung_ids": []})

    def test_endpunkt_ohne_treffer_liefert_null(self) -> None:
        befund_kacheln.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/kacheln/pruefung-offen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"anzahl": 0, "sitzung_ids": []})


if __name__ == "__main__":
    unittest.main()
