"""Oeffentlichkeits-Haertung: dieses Paket ist der Quellstand eines oeffentlichen Extrakts
(`agent-session-ledger`) -- diese Tests halten interne Firmen-/Persona-/Infrastruktur-Annahmen aus
dem PRODUKTIVEN Code fern (Konfiguration statt Hartkodierung, keine Rechte-Umgehung, kein
Credential-Leak in der mitgelieferten Registry). Enthaelt absichtlich die verbotenen Begriffe als
Negativliste -- das ist der Zweck der Datei, keine Regression."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from .. import chat, chat_bruecke, fehlerbild_pruefung, konfig, web

PAKET_ORDNER = Path(__file__).resolve().parent.parent

VERBOTENE_BEGRIFFE = ("VISCONSULT", "VICO", "VICA", "CURA", "_lokal", "Host-Workspace")
CREDENTIAL_PRAEFIXE = ("sk-or-v1-", "sk-ant-", "ghp_", "github_pat_", "AKIA", "AIza", "xox")
VERBOTENE_WERKZEUGE = ("Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Bash(")
ERLAUBTES_BASH_PRAEFIX = "Bash(python -m sitzungsbeleg nachschlagen *)"


class ChatSystemPromptTest(unittest.TestCase):
    def test_enthaelt_keine_internen_begriffe(self):
        for begriff in VERBOTENE_BEGRIFFE:
            self.assertNotIn(begriff, chat_bruecke.CHAT_SYSTEM, f"'{begriff}' im System-Prompt")


class KeinShellUndKeinBypassTest(unittest.TestCase):
    """Harte Regel: `shell=True` und `bypassPermissions` duerfen NIRGENDS im Paketquelltext
    stehen -- auch nicht als Kommentar-Erwaehnung (Restrisiko/Missverstaendnis-Vermeidung)."""

    def test_paketquelltext_ohne_tests_ist_frei_von_shell_true_und_bypass(self):
        for pfad in sorted(PAKET_ORDNER.glob("*.py")):
            text = pfad.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text, f"shell=True in {pfad.name}")
            self.assertNotIn("bypassPermissions", text, f"bypassPermissions in {pfad.name}")


class ChatAllowedToolsTest(unittest.TestCase):
    def test_standard_kommando_ohne_permission_mode(self):
        cmd = chat_bruecke._standard_kommando("x")
        self.assertNotIn("--permission-mode", cmd)

    def test_allowed_tools_nur_lesewerkzeuge_plus_ein_bash_praefix(self):
        rest = chat_bruecke.CHAT_ALLOWED_TOOLS.replace(ERLAUBTES_BASH_PRAEFIX, "")
        for werkzeug in VERBOTENE_WERKZEUGE:
            self.assertNotIn(werkzeug, rest, f"'{werkzeug}' ausserhalb des erlaubten Bash-Praefixes")
        self.assertIn(ERLAUBTES_BASH_PRAEFIX, chat_bruecke.CHAT_ALLOWED_TOOLS)


class FixLauncherTest(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)

    def tearDown(self):
        os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = self._alt

    def test_leere_umgebung_wirft_fix_launcher_fehlt(self):
        with self.assertRaises(chat_bruecke.FixLauncherFehlt):
            chat_bruecke._fix_kommando("Stichwort")

    def test_gueltige_json_liste_ersetzt_handover_je_element(self):
        os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = json.dumps(
            ["powershell", "C:/pfad/Launcher.ps1", "-Handover", "{handover}", "-Fix", "{handover}"])
        cmd = chat_bruecke._fix_kommando("Sitzung 42")
        self.assertEqual(
            cmd, ["powershell", "C:/pfad/Launcher.ps1", "-Handover", "Sitzung 42", "-Fix", "Sitzung 42"])

    def test_ungueltiges_json_wirft_fix_launcher_fehlt(self):
        os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = "{nicht valide"
        with self.assertRaises(chat_bruecke.FixLauncherFehlt):
            chat_bruecke._fix_kommando("Stichwort")


class WebFixOhneLauncherTest(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)
        self.client = TestClient(web.app)
        chat._GESPRAECHE.clear()

    def tearDown(self):
        chat._GESPRAECHE.clear()
        os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = self._alt

    def test_post_fix_501_ohne_konfigurierten_launcher(self):
        kontext = {"sitzung_logisch": 1, "signatur": None, "runde": None, "analyse_id": None}
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", kontext)
        antwort = self.client.post(f"/api/chat/{gid}/fix")
        self.assertEqual(antwort.status_code, 501)
        self.assertIn("SITZUNGSBELEG_FIX_LAUNCHER", antwort.json()["detail"])


class ModellePfadTest(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("SITZUNGSBELEG_MODELLE", None)

    def tearDown(self):
        os.environ.pop("SITZUNGSBELEG_MODELLE", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_MODELLE"] = self._alt

    def test_honoriert_umgebungsvariable(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "eigene-modelle.json"
            pfad.write_text("{}", encoding="utf-8")
            os.environ["SITZUNGSBELEG_MODELLE"] = str(pfad)
            self.assertEqual(konfig.modelle_pfad(), pfad)

    def test_faellt_auf_paket_elternordner_zurueck(self):
        os.environ.pop("SITZUNGSBELEG_MODELLE", None)
        self.assertEqual(konfig.modelle_pfad(), PAKET_ORDNER.parent / "modelle.json")


class StandardisierungsdateiPfadTest(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.pop("SITZUNGSBELEG_WORK_DIR", None)

    def tearDown(self):
        os.environ.pop("SITZUNGSBELEG_WORK_DIR", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_WORK_DIR"] = self._alt

    def test_default_beginnt_mit_work(self):
        import datetime
        pfad = fehlerbild_pruefung._standardisierungsdatei_pfad("sig", datetime.datetime(2026, 1, 1))
        self.assertTrue(pfad.startswith("_work/"))

    def test_override_beginnt_mit_konfiguriertem_ordner(self):
        import datetime
        os.environ["SITZUNGSBELEG_WORK_DIR"] = "x/y"
        pfad = fehlerbild_pruefung._standardisierungsdatei_pfad("sig", datetime.datetime(2026, 1, 1))
        self.assertTrue(pfad.startswith("x/y/"))


class ModelleJsonCredentialLeakTest(unittest.TestCase):
    def test_keine_credential_praefixe_in_der_mitgelieferten_registry(self):
        pfad = PAKET_ORDNER.parent / "modelle.json"
        if not pfad.is_file():
            self.skipTest("modelle.json nicht vorhanden (kein Extrakt-Repo-Layout)")
        text = pfad.read_text(encoding="utf-8")
        for praefix in CREDENTIAL_PRAEFIXE:
            self.assertNotIn(praefix, text, f"Credential-Praefix '{praefix}' in modelle.json")


if __name__ == "__main__":
    unittest.main()
