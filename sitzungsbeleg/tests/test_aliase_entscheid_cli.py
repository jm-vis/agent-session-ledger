"""Tests für die CLI-Befehle `aliase --pruefen` und `entscheid` (Entscheid 2026-08-26).

`aliase --pruefen` ist die Python-Seite des Wächters `scripts/check-projekt-aliase.ps1`:
PowerShell liefert per stdin `<projekt>|<quelle>`-Zeilen (psql -qAt-Format), dieser Befehl
löst sie auf und meldet unzugeordnete Rohnamen (Exit 1).

`entscheid` ist das CLI-Gegenstück zu `POST /api/befund/entscheid` -- gleiche Validierung
(`befunde.entscheid_bauen`), damit VICO im Gespräch denselben Status setzen kann.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from .. import __main__ as main_mod
from .. import speicher


class AliasePruefenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = main_mod.projekte.lade_aliase
        main_mod.projekte.lade_aliase = lambda *a, **k: {
            "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
        }

    def tearDown(self) -> None:
        main_mod.projekte.lade_aliase = self.alt

    def _lauf(self, stdin_text: str) -> tuple[int, str]:
        puffer = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin_text)):
            with redirect_stdout(puffer):
                code = main_mod.main(["aliase", "--pruefen"])
        return code, puffer.getvalue()

    def test_alle_bekannt_exit_0_ohne_ausgabe(self) -> None:
        code, ausgabe = self._lauf("scripts|claude\n")
        self.assertEqual(code, 0)
        self.assertEqual(ausgabe.strip(), "")

    def test_unbekannter_rohname_exit_1_mit_vorschlag(self) -> None:
        code, ausgabe = self._lauf("selbsttest-xyz|claude\n")
        self.assertEqual(code, 1)
        self.assertIn("selbsttest-xyz", ausgabe)
        self.assertIn("?/arbeit", ausgabe)

    def test_gemischt_meldet_nur_die_unbekannten(self) -> None:
        code, ausgabe = self._lauf("scripts|claude\nneu-projekt-4711|codex\n")
        self.assertEqual(code, 1)
        self.assertIn("neu-projekt-4711", ausgabe)
        self.assertNotIn("scripts", ausgabe)

    def test_leere_eingabe_exit_0(self) -> None:
        code, ausgabe = self._lauf("")
        self.assertEqual(code, 0)

    def test_ohne_pruefen_flag_tut_nichts(self) -> None:
        code = main_mod._befehl_aliase(mock.Mock(pruefen=False))
        self.assertEqual(code, 0)

    def test_drittes_feld_ohne_unbekanntes_modell_bleibt_exit_0(self) -> None:
        code, ausgabe = self._lauf('scripts|claude|["claude-sonnet-5"]\n')
        self.assertEqual(code, 0)
        self.assertEqual(ausgabe.strip(), "")

    def test_unbekanntes_modell_meldet_exit_1(self) -> None:
        """Entscheid 2026-08-26, Auftrag 2: `aliase --pruefen` prüft zusätzlich, ob jedes
        Modell einer claude-Sitzung als Anthropic oder Ollama in der Registry geführt wird."""
        code, ausgabe = self._lauf('scripts|claude|["ein-ganz-neues-modell"]\n')
        self.assertEqual(code, 1)
        self.assertIn("modell ohne registry-herkunft: ein-ganz-neues-modell", ausgabe)

    def test_bekanntes_ollama_modell_bleibt_exit_0(self) -> None:
        code, ausgabe = self._lauf('scripts|claude|["glm-5.2:cloud"]\n')
        self.assertEqual(code, 0)
        self.assertEqual(ausgabe.strip(), "")

    def test_ohne_drittes_feld_bleibt_kompatibel(self) -> None:
        code, ausgabe = self._lauf("scripts|claude\n")
        self.assertEqual(code, 0)
        self.assertEqual(ausgabe.strip(), "")

    def test_unbekanntes_modell_und_unbekannter_rohname_meldet_beides(self) -> None:
        code, ausgabe = self._lauf(
            'selbsttest-xyz|claude|["ein-ganz-neues-modell"]\n'
        )
        self.assertEqual(code, 1)
        self.assertIn("selbsttest-xyz", ausgabe)
        self.assertIn("modell ohne registry-herkunft: ein-ganz-neues-modell", ausgabe)


class EntscheidBefehlTest(unittest.TestCase):
    def test_schreibt_ereignis_und_exit_0(self) -> None:
        gesehen = {}

        def fake_schreiben(quelle, typ, detail, host="pc", laufer=speicher.psql):
            gesehen.update(quelle=quelle, typ=typ, detail=detail, host=host)

        args = mock.Mock(
            signatur="error:recurring:abc", status="erledigt", vermerk="v", begruendung="b",
            sitzung=42, host="pc",
        )
        with mock.patch.object(speicher, "ereignis_schreiben", fake_schreiben):
            code = main_mod._befehl_entscheid(args)
        self.assertEqual(code, 0)
        self.assertEqual(gesehen["quelle"], "gf")
        self.assertEqual(gesehen["typ"], "befund_entscheid")
        self.assertEqual(gesehen["detail"]["status"], "erledigt")
        self.assertEqual(gesehen["detail"]["sitzung_ref"], 42)

    def test_fremder_status_exit_2_ohne_schreiben(self) -> None:
        args = mock.Mock(signatur="x", status="geloescht", vermerk="", begruendung="", sitzung=None, host="pc")
        with mock.patch.object(speicher, "ereignis_schreiben") as fake:
            code = main_mod._befehl_entscheid(args)
        self.assertEqual(code, 2)
        fake.assert_not_called()

    def test_speicherfehler_exit_2(self) -> None:
        args = mock.Mock(signatur="x", status="erledigt", vermerk="", begruendung="", sitzung=None, host="pc")

        def wirft(*a, **k):
            raise speicher.SpeicherFehler("kein docker")

        with mock.patch.object(speicher, "ereignis_schreiben", wirft):
            code = main_mod._befehl_entscheid(args)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
