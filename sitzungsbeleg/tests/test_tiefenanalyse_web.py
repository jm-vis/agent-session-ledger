"""HTTP-Ebene der Tiefenanalyse + Commits (Phase 3 I, CONTRACTS.md C10) -- FakeLaufer, kein
echter psql/Docker/Subprozess. Der Hintergrund-Thread laeuft synchron (`SofortigerThread`), damit
die Tests deterministisch das geschriebene Ereignis pruefen koennen, ohne echte claude-/codex-
Prozesse zu starten (Muster: `tests/test_tiefenanalyse.py` testet `lauf_ausfuehren` direkt,
`tests/test_rohdatei.py` `RohdateiRouteTest` testet nur die synchrone HTTP-Schicht)."""
from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from .. import commits, contracts, tiefenanalyse, web
from ..modell import Auffaelligkeit, Kopf
from .hilfen import baue_beleg
from .test_web import FakeLaufer


class SofortigerThread:
    """Ersetzt `threading.Thread` im Test: `start()` ruft das Ziel synchron auf, damit der
    Hintergrund-Lauf VOR der Assertion fertig ist -- keine echten claude-/codex-Prozesse noetig,
    weil die Test-Faelle `web.TIEFENANALYSE_FRAGER_*` auf Fakes umbiegen."""

    def __init__(self, target, args=(), daemon=True):
        self._target, self._args = target, args

    def start(self) -> None:
        self._target(*self._args)


class TiefenanalyseRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_thread = web.threading.Thread
        self.alt_cloud = web.TIEFENANALYSE_FRAGER_CLOUD
        self.alt_lokal = web.TIEFENANALYSE_FRAGER_LOKAL
        self.alt_codex = web.TIEFENANALYSE_FRAGER_CODEX
        web.threading.Thread = SofortigerThread
        web.TIEFENANALYSE_FRAGER_CLOUD = lambda t, m: self._json_stufe1()
        web.TIEFENANALYSE_FRAGER_LOKAL = lambda t: self._json_stufe1()
        web.TIEFENANALYSE_FRAGER_CODEX = lambda t: self._json_stufe1()
        self.client = TestClient(web.app)
        tiefenanalyse._laufend.clear()

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        web.threading.Thread = self.alt_thread
        web.TIEFENANALYSE_FRAGER_CLOUD = self.alt_cloud
        web.TIEFENANALYSE_FRAGER_LOKAL = self.alt_lokal
        web.TIEFENANALYSE_FRAGER_CODEX = self.alt_codex
        tiefenanalyse._laufend.clear()

    @staticmethod
    def _json_stufe1() -> str:
        return ('{"ursache_kategorie": "Heredoc-Backslash", "befund": "b", "empfehlung": "e", '
                '"urteil": "ja", "komplexitaet": "einfach"}')

    def _aufloesung(self, logisch: int, dokument: dict) -> dict:
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(logisch),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([logisch]),
            f"FROM sitzung WHERE id = {logisch}": json.dumps(dokument),
        }

    def _beleg_mit_signatur(self, projekt_name: str = "x") -> dict:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s1", projekt_name=projekt_name))
        beleg.auffaelligkeiten.append(
            Auffaelligkeit(regel="rework:tool", schwere="hinweis", signatur="rework:tool:Bash")
        )
        return beleg.als_dict()

    def test_unbekannte_sitzung_404(self):
        web.LAUFER = FakeLaufer({"sitzung_aktuell WHERE logisch_ref = 9": "null"})
        antwort = self.client.post("/api/sitzung/9/tiefenanalyse", json={"signatur": "x", "position": 0})
        self.assertEqual(antwort.status_code, 404)

    def test_unbekannte_signatur_404(self):
        web.LAUFER = FakeLaufer(self._aufloesung(30, self._beleg_mit_signatur()))
        antwort = self.client.post(
            "/api/sitzung/30/tiefenanalyse", json={"signatur": "nicht-vorhanden", "position": 0}
        )
        self.assertEqual(antwort.status_code, 404)

    def test_erfolgreicher_lauf_202_und_ereignis_geschrieben(self):
        web.LAUFER = FakeLaufer(self._aufloesung(31, self._beleg_mit_signatur()))
        antwort = self.client.post(
            "/api/sitzung/31/tiefenanalyse", json={"signatur": "rework:tool:Bash", "position": 0}
        )
        self.assertEqual(antwort.status_code, 202)
        self.assertEqual(antwort.json(), {"gestartet": True})
        inserts = [a for a in web.LAUFER.aufrufe if "INSERT INTO ereignis" in a and "tiefenanalyse" in a]
        self.assertEqual(len(inserts), 1)

    def test_konflikt_409_bei_laufender_analyse(self):
        tiefenanalyse.registriere_lauf(32, "rework:tool:Bash")
        web.LAUFER = FakeLaufer(self._aufloesung(32, self._beleg_mit_signatur()))
        antwort = self.client.post(
            "/api/sitzung/32/tiefenanalyse", json={"signatur": "rework:tool:Bash", "position": 0}
        )
        self.assertEqual(antwort.status_code, 409)
        tiefenanalyse.freigeben(32, "rework:tool:Bash")

    def test_geschuetzt_laeuft_nur_lokal_codex_nie_aufgerufen(self):
        codex_aufrufe = []
        web.TIEFENANALYSE_FRAGER_CODEX = lambda t: codex_aufrufe.append(t) or self._json_stufe1()
        web.LAUFER = FakeLaufer(self._aufloesung(33, self._beleg_mit_signatur(projekt_name=r"x/_lokal/y")))
        antwort = self.client.post(
            "/api/sitzung/33/tiefenanalyse", json={"signatur": "rework:tool:Bash", "position": 0}
        )
        self.assertEqual(antwort.status_code, 202)
        self.assertEqual(codex_aufrufe, [])
        eingefuegt = [a for a in web.LAUFER.aufrufe if "tiefenanalyse" in a and "INSERT" in a][0]
        self.assertIn('"nur_lokal":true', eingefuegt.replace(" ", ""))

    def test_status_ohne_analyse(self):
        web.LAUFER = FakeLaufer({}, default="[]")
        antwort = self.client.get("/api/sitzung/40/tiefenanalyse", params={"signatur": "x"})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"laeuft": False, "seit": None, "ergebnis": None})

    def test_status_zeigt_laufend(self):
        tiefenanalyse.registriere_lauf(41, "sig")
        web.LAUFER = FakeLaufer({}, default="[]")
        antwort = self.client.get("/api/sitzung/41/tiefenanalyse", params={"signatur": "sig"})
        self.assertTrue(antwort.json()["laeuft"])
        tiefenanalyse.freigeben(41, "sig")

    def test_status_liefert_juengstes_ereignis(self):
        detail = {**contracts.BEISPIELE["tiefenanalyse"], "sitzung_logisch": 42}
        web.LAUFER = FakeLaufer({"quelle = 'tiefenanalyse'": json.dumps([detail])}, default="[]")
        antwort = self.client.get(
            "/api/sitzung/42/tiefenanalyse", params={"signatur": "rework:tool:Bash"}
        )
        self.assertEqual(antwort.json()["ergebnis"]["signatur"], "rework:tool:Bash")


class CommitsRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_liste = commits.liste
        self.alt_diff = commits.diff
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        commits.liste = self.alt_liste
        commits.diff = self.alt_diff

    def _aufloesung(self, logisch: int, dokument: dict) -> dict:
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(logisch),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([logisch]),
            f"FROM sitzung WHERE id = {logisch}": json.dumps(dokument),
        }

    def test_geschuetzte_sitzung_423(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", projekt_name=r"x/_lokal/y"))
        web.LAUFER = FakeLaufer(self._aufloesung(50, beleg.als_dict()))
        self.assertEqual(self.client.get("/api/sitzung/50/commits").status_code, 423)
        self.assertEqual(self.client.get("/api/sitzung/50/commits/abc1234").status_code, 423)

    def test_liste_und_diff_ok(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s"))
        web.LAUFER = FakeLaufer(self._aufloesung(51, beleg.als_dict()))
        commits.liste = lambda *a, **k: [{"hash": "abc1234", "zeit": "t", "betreff": "x"}]
        commits.diff = lambda *a, **k: "diff-text"
        antwort = self.client.get("/api/sitzung/51/commits")
        self.assertEqual(antwort.json(), {"commits": [{"hash": "abc1234", "zeit": "t", "betreff": "x"}]})
        antwort = self.client.get("/api/sitzung/51/commits/abc1234")
        self.assertEqual(antwort.json(), {"diff": "diff-text"})

    def test_ungueltiger_hash_404(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s"))
        web.LAUFER = FakeLaufer(self._aufloesung(52, beleg.als_dict()))

        def wirft(*a, **k):
            raise commits.CommitsFehler("ungueltiger Commit-Hash")

        commits.diff = wirft
        antwort = self.client.get("/api/sitzung/52/commits/xyz")
        self.assertEqual(antwort.status_code, 404)


if __name__ == "__main__":
    unittest.main()
