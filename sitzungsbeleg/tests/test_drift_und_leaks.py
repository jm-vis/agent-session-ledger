"""Stufe-2-Restliste: Feld-Drift je bekanntem Typ + Leak-Tests für verschachtelte Inhalte."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .. import leser_claude, leser_codex, redaktion


def _claude_datei(tmp: str, zeilen: list[dict]) -> str:
    pfad = Path(tmp) / "s1.jsonl"
    pfad.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8")
    return str(pfad)


def _user(content, **extra) -> dict:
    return {"type": "user", "timestamp": "2026-08-26T08:00:00Z", "sessionId": "s1",
            "message": {"role": "user", "content": content}, **extra}


class FeldDriftClaudeTest(unittest.TestCase):
    def test_neues_feld_in_user_zeile_wird_gemerkt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            beleg = leser_claude.lese_sitzung(_claude_datei(tmp, [_user("x", voellig_neu=1)]))
        self.assertIn("feld:user.voellig_neu", beleg.erfassung.unbekannt)

    def test_bekannte_metadaten_typen_sind_keine_drift(self) -> None:
        zeilen = [_user("x"), {"type": "ai-title", "aiTitle": "geheim", "sessionId": "s1"},
                  {"type": "last-prompt", "lastPrompt": "geheim", "sessionId": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            beleg = leser_claude.lese_sitzung(_claude_datei(tmp, zeilen))
        self.assertEqual(beleg.erfassung.unbekannt, [])
        self.assertNotIn("geheim", json.dumps(beleg.als_dict()))


class FeldDriftCodexTest(unittest.TestCase):
    def test_neues_payload_feld_und_neuer_toplevel_typ(self) -> None:
        zeilen = [
            {"timestamp": "2026-08-26T08:00:00Z", "type": "turn_context",
             "payload": {"model": "gpt-5.5", "neues_feld": True}},
            {"timestamp": "2026-08-26T08:00:01Z", "type": "ganz_neu", "payload": {}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "rollout-x.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8")
            beleg = leser_codex.lese_sitzung(str(pfad))
        self.assertIn("feld:turn_context.neues_feld", beleg.erfassung.unbekannt)
        self.assertIn("toplevel:ganz_neu", beleg.erfassung.unbekannt)


class LeakTest(unittest.TestCase):
    """Verschachtelte Inhalte (tool_result.content, toolUseResult) dürfen den Beleg nie erreichen."""

    def test_tool_result_content_bloecke_und_tooluseresult(self) -> None:
        geheim_pfad = "C:\\\\Users\\\\jemand\\\\_lokal\\\\geheim.txt"
        zeilen = [
            {"type": "assistant", "timestamp": "2026-08-26T08:00:00Z", "sessionId": "s1",
             "message": {"role": "assistant", "model": "claude-sonnet-5", "content": [
                 {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": geheim_pfad}}]}},
            _user([{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                    "content": [{"type": "text", "text": "Fehler: " + geheim_pfad + " sk-ABC"}]}],
                  toolUseResult={"file": {"filePath": geheim_pfad, "content": "sk-ABC geheim"}}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            beleg = leser_claude.lese_sitzung(_claude_datei(tmp, zeilen))
        text = json.dumps(beleg.als_dict())
        for verboten in ("geheim", "_lokal", "sk-ABC", "Users"):
            self.assertNotIn(verboten, text)
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])
        self.assertEqual(beleg.ereignisse[1].fehlerklasse, "tool_error")


if __name__ == "__main__":
    unittest.main()
