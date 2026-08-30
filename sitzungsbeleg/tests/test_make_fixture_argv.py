"""Tests für die argv-Pflicht der Fixture-Generatoren (F11).

Kein harter (personenbezogener) Quellpfad mehr im Skript — die Quelldatei/
der Quellordner kommt als Pflichtargument sys.argv[1], mit Usage-Text und
Exit-Code 2 bei Fehlen.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from . import make_fixture_claude, make_fixture_codex


class MakeFixtureClaudeArgvTest(unittest.TestCase):
    def test_ohne_argv_zeigt_usage_und_exit_2(self) -> None:
        fehler = io.StringIO()
        with redirect_stderr(fehler):
            code = make_fixture_claude.main(["make_fixture_claude.py"])
        self.assertEqual(code, 2)
        self.assertIn("Usage", fehler.getvalue())


class MakeFixtureCodexArgvTest(unittest.TestCase):
    def test_ohne_argv_zeigt_usage_und_exit_2(self) -> None:
        fehler = io.StringIO()
        with redirect_stderr(fehler):
            code = make_fixture_codex.main(["make_fixture_codex.py"])
        self.assertEqual(code, 2)
        self.assertIn("Usage", fehler.getvalue())


if __name__ == "__main__":
    unittest.main()
