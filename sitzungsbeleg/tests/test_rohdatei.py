"""Tests für rohdatei.py (Phase 3 H, CONTRACTS.md C5) -- reine Modul-Logik + die Guards aus dem
Arbeitsauftrag: kein Schreibweg über `speicher`, Rohtext landet nie in einem Log, die Antwort
enthält nie ein unredigiertes Muster der Redaktions-Allowlist."""
from __future__ import annotations

import ast
import inspect
import json
import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from .. import __main__ as cli
from .. import redaktion, rohdatei, web
from ..modell import Kopf
from .hilfen import baue_beleg


def _schreibe_jsonl(pfad: Path, zeilen: list[dict]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8")


class TranskriptOrdnerTest(unittest.TestCase):
    """Verlegt CLAUDE_PROJEKTE/CODEX_SITZUNGEN je Test in ein Temp-Verzeichnis -- wie
    `web.LAUFER = self.alt` in test_web.py, nur für die Datei-Suche aus __main__.py."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._alt_claude = cli.CLAUDE_PROJEKTE
        self._alt_codex = cli.CODEX_SITZUNGEN
        cli.CLAUDE_PROJEKTE = Path(self._tmp.name) / "claude"
        cli.CODEX_SITZUNGEN = Path(self._tmp.name) / "codex"

    def tearDown(self) -> None:
        cli.CLAUDE_PROJEKTE = self._alt_claude
        cli.CODEX_SITZUNGEN = self._alt_codex
        self._tmp.cleanup()

    def _claude_datei(self, sitzung_id: str) -> Path:
        return cli.CLAUDE_PROJEKTE / "proj-hash" / f"{sitzung_id}.jsonl"


class ZielIndexTest(unittest.TestCase):
    def test_zeit_findet_naechste_zeile(self):
        rohzeilen = [{"timestamp": "10:00"}, {"timestamp": "10:01"}, {"timestamp": "10:02"}]
        self.assertEqual(rohdatei._ziel_index(rohzeilen, "10:01", 999), 1)

    def test_zeit_ueber_letzter_zeile_faellt_auf_letzte(self):
        rohzeilen = [{"timestamp": "10:00"}, {"timestamp": "10:01"}]
        self.assertEqual(rohdatei._ziel_index(rohzeilen, "23:00", 999), 1)

    def test_ohne_zeit_faellt_auf_position_als_rohindex_zurueck(self):
        rohzeilen = [{}] * 5
        self.assertEqual(rohdatei._ziel_index(rohzeilen, None, 3), 3)
        self.assertEqual(rohdatei._ziel_index(rohzeilen, None, 99), 4)  # gekappt

    def test_leere_datei(self):
        self.assertEqual(rohdatei._ziel_index([], "10:00", 3), 0)


class PfadAnzeigeTest(unittest.TestCase):
    def test_ersetzt_heimverzeichnis_durch_tilde(self):
        pfad = Path.home() / ".claude" / "projects" / "x" / "s.jsonl"
        anzeige = rohdatei._pfad_anzeige(pfad)
        self.assertTrue(anzeige.startswith("~/"))
        self.assertNotIn(str(Path.home()), anzeige)
        self.assertNotIn("\\", anzeige)


class ZeileVerdichtenTest(unittest.TestCase):
    def test_claude_text_block(self):
        obj = {"type": "user", "message": {"content": "Hallo Welt"}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 5)
        self.assertEqual(zeile, {"index": 5, "typ": "user", "text": "Hallo Welt"})

    def test_claude_tool_use_block_wird_verdichtet(self):
        obj = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}},
        ]}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 1)
        self.assertEqual(zeile["typ"], "assistant")
        self.assertIn("tool_use:Bash", zeile["text"])

    def test_claude_pfad_im_text_wird_ganz_redigiert(self):
        obj = {"type": "user", "message": {"content": "siehe C:\\Users\\x\\geheim.txt"}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 0)
        self.assertEqual(zeile["text"], redaktion.REDIGIERT)

    def test_claude_secret_wird_ganz_redigiert(self):
        obj = {"type": "user", "message": {"content": "key ist sk-abcdefghijklmnop"}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 0)
        self.assertEqual(zeile["text"], redaktion.REDIGIERT)

    def test_claude_email_wird_ganz_redigiert(self):
        obj = {"type": "user", "message": {"content": "Kontakt: person@example.invalid"}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 0)
        self.assertEqual(zeile["text"], redaktion.REDIGIERT)

    def test_claude_lokal_wort_wird_ganz_redigiert(self):
        obj = {"type": "user", "message": {"content": "Datei liegt unter 99_Analytics_and_Reporting/_lokal"}}
        zeile = rohdatei._zeile_verdichten("claude", obj, 0)
        self.assertEqual(zeile["text"], redaktion.REDIGIERT)

    def test_kaputte_zeile_liefert_leeren_text_und_typ_unbekannt(self):
        zeile = rohdatei._zeile_verdichten("claude", {}, 2)
        self.assertEqual(zeile, {"index": 2, "typ": "unbekannt", "text": ""})

    def test_codex_message_payload(self):
        obj = {"timestamp": "t", "type": "response_item",
               "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Frage"}]}}
        zeile = rohdatei._zeile_verdichten("codex", obj, 0)
        self.assertEqual(zeile["typ"], "response_item:message")
        self.assertEqual(zeile["text"], "Frage")

    def test_codex_function_call_payload(self):
        obj = {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}}
        zeile = rohdatei._zeile_verdichten("codex", obj, 0)
        self.assertIn("tool_call:shell", zeile["text"])

    def test_codex_pfad_wird_ganz_redigiert(self):
        obj = {"type": "response_item", "payload": {"type": "function_call_output", "output": "/home/x/geheim"}}
        zeile = rohdatei._zeile_verdichten("codex", obj, 0)
        self.assertEqual(zeile["text"], redaktion.REDIGIERT)


class BaueAntwortTest(TranskriptOrdnerTest):
    def test_fenster_um_zeit_zentriert(self):
        # Zeitstempel wie ISO-8601 fest zweistellig -- "t10" waere lexikalisch kleiner als "t9"
        # (kein Zero-Padding), das passiert echten Timestamps nie (siehe rohdatei.py Moduldoc).
        zeilen = [{"timestamp": f"t{i:02d}", "type": "user", "message": {"content": f"z{i}"}} for i in range(20)]
        _schreibe_jsonl(self._claude_datei("s1"), zeilen)
        antwort = rohdatei.baue_antwort("claude", "s1", "t10", 999, 2)
        self.assertEqual([z["index"] for z in antwort["zeilen"]], [8, 9, 10, 11, 12])
        self.assertEqual(antwort["position"], 999)
        self.assertEqual(antwort["umfang"], 2)
        self.assertEqual(antwort["redaktion_version"], redaktion.REDAKTION_VERSION)
        self.assertEqual(antwort["warnung"], rohdatei.WARNUNG)
        self.assertTrue(antwort["pfad_anzeige"].endswith("s1.jsonl"))

    def test_umfang_wird_auf_maximum_gekappt(self):
        zeilen = [{"timestamp": f"t{i}", "type": "user", "message": {"content": "x"}} for i in range(5)]
        _schreibe_jsonl(self._claude_datei("s2"), zeilen)
        antwort = rohdatei.baue_antwort("claude", "s2", "t2", 2, 999)
        self.assertEqual(antwort["umfang"], rohdatei.MAX_UMFANG)

    def test_umfang_wird_auf_minimum_angehoben(self):
        zeilen = [{"timestamp": "t0", "type": "user", "message": {"content": "x"}}]
        _schreibe_jsonl(self._claude_datei("s3"), zeilen)
        antwort = rohdatei.baue_antwort("claude", "s3", "t0", 0, 0)
        self.assertEqual(antwort["umfang"], 1)

    def test_fehlendes_transkript_wirft_rohdateifehler(self):
        with self.assertRaises(rohdatei.RohdateiFehler):
            rohdatei.baue_antwort("claude", "existiert-nicht", "t0", 0, 5)

    def test_codex_datei_wird_ueber_rollout_muster_gefunden(self):
        pfad = cli.CODEX_SITZUNGEN / "2026" / "08" / "28" / "rollout-20260828-abc123.jsonl"
        _schreibe_jsonl(pfad, [{"timestamp": "t0", "type": "session_meta", "payload": {}}])
        antwort = rohdatei.baue_antwort("codex", "abc123", "t0", 0, 5)
        self.assertTrue(antwort["pfad_anzeige"].endswith("rollout-20260828-abc123.jsonl"))


class GuardsTest(unittest.TestCase):
    def test_kein_schreibweg_ueber_speicher(self):
        """(a) rohdatei.py ruft `speicher.*` nie auf -- weder importiert noch als Code-Bezeichner
        vorhanden. Geprueft ueber den AST statt eines Substring-Checks, der an Docstring-Prosa
        ("das Modul ruft `speicher.*` nie auf") oder deutschen Woertern wie "gespeichert"
        (enthaelt "speicher" ohne Wortgrenze) faelschlich anschlagen wuerde."""
        baum = ast.parse(inspect.getsource(rohdatei))
        namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)}
        importe = {
            alias.asname or alias.name
            for node in ast.walk(baum) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("speicher", namen | importe)
        self.assertFalse(hasattr(rohdatei, "speicher"))

    def test_log_capture_bleibt_leer(self):
        """(b) kein Rohtext (oder ueberhaupt irgendetwas) landet in einem Log-Record."""
        with tempfile.TemporaryDirectory() as tmp:
            alt = cli.CLAUDE_PROJEKTE
            cli.CLAUDE_PROJEKTE = Path(tmp) / "claude"
            try:
                _schreibe_jsonl(
                    Path(tmp) / "claude" / "proj" / "geheim.jsonl",
                    [{"timestamp": "t0", "type": "user", "message": {"content": "sk-abcdefghijklmnop"}}],
                )
                with self.assertLogs(level="DEBUG") as protokoll:
                    logging.getLogger("wächter-anker").debug("anker")  # assertLogs braucht >=1 Eintrag
                    rohdatei.baue_antwort("claude", "geheim", "t0", 0, 5)
                fund = [z for z in protokoll.output if "sk-abcdefghijklmnop" in z]
                self.assertEqual(fund, [])
            finally:
                cli.CLAUDE_PROJEKTE = alt

    def test_antwort_enthaelt_nie_ein_redaktions_muster(self):
        """(c) jede `zeilen[].text` ist entweder sauber oder komplett '<redigiert>' -- nie ein
        Secret/Pfad/E-Mail/Schutzordner-Token roh in der Antwort (wie test_redaktion.py)."""
        with tempfile.TemporaryDirectory() as tmp:
            alt = cli.CLAUDE_PROJEKTE
            cli.CLAUDE_PROJEKTE = Path(tmp) / "claude"
            try:
                zeilen = [
                    {"timestamp": "t0", "type": "user", "message": {"content": "sk-abcdefghijklmnop"}},
                    {"timestamp": "t1", "type": "user", "message": {"content": r"C:\Users\aliceim\geheim"}},
                    {"timestamp": "t2", "type": "user", "message": {"content": "person@example.invalid"}},
                    {"timestamp": "t3", "type": "user", "message": {"content": "Pfad _work/_lokal/x"}},
                    {"timestamp": "t4", "type": "user", "message": {"content": "sauberer Text ohne Verstoss"}},
                ]
                _schreibe_jsonl(Path(tmp) / "claude" / "proj" / "s.jsonl", zeilen)
                antwort = rohdatei.baue_antwort("claude", "s", "t2", 2, 5)
                for zeile in antwort["zeilen"]:
                    verstoss = redaktion._pruefe_freitext(zeile["text"])
                    if verstoss:
                        self.assertEqual(zeile["text"], redaktion.REDIGIERT, zeile)
                self.assertIn(redaktion.REDIGIERT, [z["text"] for z in antwort["zeilen"]])
                self.assertIn("sauberer Text ohne Verstoss", [z["text"] for z in antwort["zeilen"]])
            finally:
                cli.CLAUDE_PROJEKTE = alt


class FakeLaufer:
    """Wie in test_web.py: antwortet nach dem ersten passenden Substring, Reihenfolge egal."""

    def __init__(self, antworten: dict[str, str], default: str = "[]"):
        self.antworten = antworten
        self.default = default

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        for muster, antwort in self.antworten.items():
            if muster in sql:
                return antwort
        return self.default


class RohdateiRouteTest(TranskriptOrdnerTest):
    """C5 `GET /api/rohdatei/{sitzung_logisch}` -- HTTP-Ebene (404/423) ueber `web.py`."""

    def setUp(self) -> None:
        super().setUp()
        self.alt_laufer = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        super().tearDown()

    def _aufloesung(self, logisch: int, dokument: dict) -> dict:
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(logisch),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([logisch]),
            f"FROM sitzung WHERE id = {logisch}": json.dumps(dokument),
        }

    def test_unbekannte_sitzung_404(self):
        web.LAUFER = FakeLaufer({"sitzung_aktuell WHERE logisch_ref = 9": "null",
                                   "jsonb_agg(id ORDER BY id DESC)": "[]"})
        antwort = self.client.get("/api/rohdatei/9")
        self.assertEqual(antwort.status_code, 404)

    def test_geschuetzte_sitzung_423(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s-geschuetzt", projekt_name=r"x/_lokal/y"))
        web.LAUFER = FakeLaufer(self._aufloesung(20, beleg.als_dict()))
        antwort = self.client.get("/api/rohdatei/20")
        self.assertEqual(antwort.status_code, 423)

    def test_fehlendes_transkript_404_mit_hinweis(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="datei-fehlt"))
        web.LAUFER = FakeLaufer(self._aufloesung(21, beleg.als_dict()))
        antwort = self.client.get("/api/rohdatei/21")
        self.assertEqual(antwort.status_code, 404)
        self.assertIn("Transkript nicht mehr vorhanden", antwort.json()["detail"])

    def test_erfolgreicher_abruf(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s-ok"))
        _schreibe_jsonl(
            self._claude_datei("s-ok"),
            [{"timestamp": "2026-08-25T10:00:00Z", "type": "user", "message": {"content": "hallo"}}],
        )
        web.LAUFER = FakeLaufer(self._aufloesung(22, beleg.als_dict()))
        antwort = self.client.get("/api/rohdatei/22", params={"position": 0, "umfang": 3})
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(daten["zeilen"][0]["text"], "hallo")
        self.assertTrue(daten["pfad_anzeige"].endswith("s-ok.jsonl"))

    def test_negative_position_wird_gekappt_statt_response_model_fehler(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s-negativ"))
        _schreibe_jsonl(
            self._claude_datei("s-negativ"),
            [{"timestamp": "2026-08-25T10:00:00Z", "type": "user", "message": {"content": "x"}}],
        )
        web.LAUFER = FakeLaufer(self._aufloesung(24, beleg.als_dict()))
        antwort = self.client.get("/api/rohdatei/24", params={"position": -5})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json()["position"], 0)

    def test_umfang_default_und_maximum_ueber_die_route(self):
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s-umfang"))
        _schreibe_jsonl(
            self._claude_datei("s-umfang"),
            [{"timestamp": "2026-08-25T10:00:00Z", "type": "user", "message": {"content": "x"}}],
        )
        web.LAUFER = FakeLaufer(self._aufloesung(23, beleg.als_dict()))
        antwort = self.client.get("/api/rohdatei/23", params={"umfang": 999})
        self.assertEqual(antwort.json()["umfang"], rohdatei.MAX_UMFANG)


if __name__ == "__main__":
    unittest.main()
