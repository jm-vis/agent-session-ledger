"""Tests fuer commits.py (Phase 3 I, CONTRACTS.md C10): echte `git`-Kommandos gegen ein
Temp-Repo -- kein Netzwerk, kein Docker. `git` ist eine harte Voraussetzung wie auf jedem
Entwicklerrechner."""
from __future__ import annotations

import ast
import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path

from .. import commits, redaktion


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(pfad: Path) -> None:
    _git(pfad, "init", "-q")
    _git(pfad, "config", "user.email", "test@example.com")
    _git(pfad, "config", "user.name", "Test")


def _commit(pfad: Path, dateiname: str, inhalt: str, betreff: str) -> str:
    (pfad / dateiname).write_text(inhalt, encoding="utf-8")
    _git(pfad, "add", dateiname)
    _git(pfad, "commit", "-q", "-m", betreff)
    return _git(pfad, "rev-parse", "HEAD").stdout.strip()


class RepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self._tmp.name)
        _init_repo(self.pfad)
        self._alt_cwd = commits.rohdatei.cwd_aus_transkript
        commits.rohdatei.cwd_aus_transkript = lambda quelle, sid: str(self.pfad)

    def tearDown(self) -> None:
        commits.rohdatei.cwd_aus_transkript = self._alt_cwd
        self._tmp.cleanup()


class ListeTest(RepoTest):
    def test_commit_im_zeitfenster_gefunden(self):
        commit_hash = _commit(self.pfad, "a.txt", "1", "erste Aenderung")
        treffer = commits.liste("claude", "s1", "", "")
        self.assertEqual(len(treffer), 1)
        self.assertEqual(treffer[0]["betreff"], "erste Aenderung")
        self.assertEqual(treffer[0]["hash"], commit_hash)

    def test_kein_repo_liefert_leere_liste_statt_fehler(self):
        commits.rohdatei.cwd_aus_transkript = lambda quelle, sid: ""
        self.assertEqual(commits.liste("claude", "s2", "", ""), [])

    def test_betreff_wird_redigiert(self):
        _commit(self.pfad, "b.txt", "1", "Kontakt person@example.invalid")
        treffer = commits.liste("claude", "s3", "", "")
        self.assertEqual(treffer[0]["betreff"], redaktion.REDIGIERT)

    def test_max_commits_gekappt(self):
        for i in range(commits.MAX_COMMITS + 5):
            _commit(self.pfad, f"f{i}.txt", str(i), f"commit {i}")
        treffer = commits.liste("claude", "s4", "", "")
        self.assertEqual(len(treffer), commits.MAX_COMMITS)

    def test_neueste_zuerst(self):
        _commit(self.pfad, "x.txt", "1", "alt")
        _commit(self.pfad, "y.txt", "1", "neu")
        treffer = commits.liste("claude", "s5", "", "")
        self.assertEqual([t["betreff"] for t in treffer], ["neu", "alt"])


class DiffTest(RepoTest):
    def setUp(self) -> None:
        super().setUp()
        self.commit_hash = _commit(self.pfad, "a.txt", "zeile1\n", "init")

    def test_diff_enthaelt_dateinamen(self):
        text = commits.diff("claude", "s1", self.commit_hash)
        self.assertIn("a.txt", text)

    def test_ungueltiger_hash_wirft_commitsfehler_statt_git_zu_verwirren(self):
        with self.assertRaises(commits.CommitsFehler):
            commits.diff("claude", "s1", "; rm -rf /")

    def test_geheimnis_im_diff_wird_redigiert(self):
        commit_hash = _commit(self.pfad, "b.txt", "sk-abcdefghijklmnop\n", "b")
        text = commits.diff("claude", "s1", commit_hash)
        self.assertNotIn("sk-abcdefghijklmnop", text)

    def test_kein_repo_wirft_commitsfehler(self):
        commits.rohdatei.cwd_aus_transkript = lambda quelle, sid: ""
        with self.assertRaises(commits.CommitsFehler):
            commits.diff("claude", "s1", self.commit_hash)


class GuardsTest(unittest.TestCase):
    def test_kein_schreibweg_ueber_speicher(self):
        """`commits.py` ruft `speicher.*` nie auf -- AST-Guard wie `test_rohdatei.py`."""
        baum = ast.parse(inspect.getsource(commits))
        namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)}
        importe = {
            alias.asname or alias.name
            for node in ast.walk(baum) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("speicher", namen | importe)
        self.assertFalse(hasattr(commits, "speicher"))


if __name__ == "__main__":
    unittest.main()


class KonsenloserDienstTest(unittest.TestCase):
    """Befund 2026-08-28: unter FreeConsole ist das geerbte Stdin ungueltig ([WinError 6]);
    jeder Kindprozess-Aufruf muss `stdin=DEVNULL` setzen, sonst liefert der Dienst leere Listen."""

    def test_git_aufruf_setzt_stdin_devnull(self):
        gesehen: dict = {}

        def laufer(argv, **kw):
            gesehen.update(kw)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        commits._git(".", "--version", laufer=laufer)
        self.assertIs(gesehen.get("stdin"), subprocess.DEVNULL)

    def test_ollama_aufruf_setzt_stdin_devnull(self):
        from .. import chat
        gesehen: dict = {}

        def laufer(argv, **kw):
            gesehen.update(kw)
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

        chat._ollama_lauf("list", laufer=laufer)
        self.assertIs(gesehen.get("stdin"), subprocess.DEVNULL)
