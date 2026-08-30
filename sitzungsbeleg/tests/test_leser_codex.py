"""Tests für leser_codex — TDD, keine Mocks, echtes (anonymisiertes) Fixture.

Alle Vergleichswerte sind unabhängig vom Leser aus der Fixture-Datei
nachgezählt (siehe scratchpad-Zählskripte im Bau-Auftrag), nicht aus dem
Leser selbst abgeleitet.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from .. import leser_codex, modell

_FIXTURE = Path(__file__).parent / "fixtures" / "codex" / "rollout-beispiel.jsonl"


def _alle_strings(node):
    """Läuft rekursiv durch eine Struktur und liefert alle enthaltenen Strings."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _alle_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _alle_strings(v)


class TestLeserCodexFixture(unittest.TestCase):
    """Werte gegen die anonymisierte Beispieldatei (67 Zeilen, 1 echte Sitzung)."""

    @classmethod
    def setUpClass(cls):
        cls.beleg = leser_codex.lese_sitzung(str(_FIXTURE), host="test-host")

    def test_kopf(self):
        k = self.beleg.kopf
        self.assertEqual(k.quelle, "codex")
        self.assertEqual(k.sitzung_id, "01a0391c-dbb5-7021-912e-872c836f0e8d")
        self.assertEqual(k.version, "0.147.0")
        self.assertEqual(k.host, "test-host")
        self.assertEqual(k.modelle, ["gpt-5.5"])
        self.assertEqual(k.projekt_name, "Projekt")
        erwarteter_hash = hashlib.sha256("C:\\Beispiel\\Projekt".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(k.projekt_hash, erwarteter_hash)
        self.assertTrue(k.start)
        self.assertTrue(k.ende)

    def test_erfassung(self):
        e = self.beleg.erfassung
        self.assertEqual(e.token, "observed")
        self.assertEqual(e.dauer, "partial")
        self.assertEqual(e.kosten, "not_observed")
        self.assertEqual(e.inhalte, "redacted")
        self.assertEqual(e.subagenten, "not_recorded")
        self.assertEqual(e.compaction, "not_recorded")
        self.assertEqual(e.reasoning, "not_recorded")

    def test_runden_und_tools(self):
        art_zaehler = {}
        for ev in self.beleg.ereignisse:
            art_zaehler[ev.art] = art_zaehler.get(ev.art, 0) + 1
        # unabhängig aus der Fixture gezählt (response_item.message role user/assistant,
        # function_call, function_call_output, reasoning). F5: ART_TOOL_ERGEBNIS nur
        # bei Fehler — die Fixture enthaelt 0 Fehlschlaege (siehe
        # test_keine_tool_fehler_in_fixture), also 0 Ergebnis-Ereignisse.
        self.assertEqual(art_zaehler.get(modell.ART_NUTZER, 0), 2)
        self.assertEqual(art_zaehler.get(modell.ART_ASSISTENT, 0), 7)
        self.assertEqual(art_zaehler.get(modell.ART_TOOL, 0), 15)
        self.assertEqual(art_zaehler.get(modell.ART_TOOL_ERGEBNIS, 0), 0)

    def test_keine_tool_fehler_in_fixture(self):
        # alle Exit-Codes in der Fixture sind 0 oder nicht vorhanden (non-shell-Tools)
        fehler = [ev for ev in self.beleg.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS and ev.fehler]
        self.assertEqual(fehler, [])

    def test_reasoning_und_context_window_zaehlbar(self):
        reasoning_events = [
            ev for ev in self.beleg.ereignisse if ev.art == modell.ART_SYSTEM and ev.name == "reasoning"
        ]
        self.assertEqual(len(reasoning_events), 7)
        fenster_events = [
            ev
            for ev in self.beleg.ereignisse
            if ev.art == modell.ART_SYSTEM and ev.name == "context_window"
        ]
        # Fenstergröße bleibt über die Sitzung konstant -> genau ein Ereignis (dedupliziert)
        self.assertEqual(len(fenster_events), 1)
        self.assertEqual(fenster_events[0].ref, "258400")

    def test_token_summen(self):
        gesamt = modell.Token()
        for ev in self.beleg.ereignisse:
            if ev.art == modell.ART_ASSISTENT and ev.token is not None:
                gesamt.add(ev.token)
        # unabhängig aus den 7 token_count-Zeilen der Fixture aufsummiert
        self.assertEqual(gesamt.input, 184906)
        self.assertEqual(gesamt.output, 4602)
        self.assertEqual(gesamt.cache_write, 0)
        self.assertEqual(gesamt.cache_read, 153216)
        self.assertEqual(gesamt.thinking, 2263)

    def test_subagenten_und_kennzahlen_leer(self):
        self.assertEqual(self.beleg.subagenten, [])
        self.assertEqual(self.beleg.kennzahlen, modell.Kennzahlen())

    def test_keine_langen_strings_im_beleg(self):
        for s in _alle_strings(self.beleg.als_dict()):
            self.assertLessEqual(len(s), 80, msg=f"String zu lang: {s!r}")


class TestLeserCodexRobustheit(unittest.TestCase):
    """Defekte/unbekannte Zeilen dürfen nie zum Absturz führen."""

    def _temp_datei(self, zeilen: list[str]) -> str:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for z in zeilen:
            tmp.write(z + "\n")
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return tmp.name

    def test_defekte_zeile_ueberspringt_ohne_absturz(self):
        gueltige_zeilen = _FIXTURE.read_text(encoding="utf-8").splitlines()
        zeilen = gueltige_zeilen + ["{diese Zeile ist kein JSON"]
        pfad = self._temp_datei(zeilen)
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("defekte_zeilen:1", beleg.erfassung.unbekannt)
        # gültige Zeilen weiterhin korrekt ausgewertet
        n_nutzer = sum(1 for ev in beleg.ereignisse if ev.art == modell.ART_NUTZER)
        self.assertEqual(n_nutzer, 2)

    def test_unbekannter_toplevel_typ_landet_in_unbekannt(self):
        zeile = json.dumps({"timestamp": "2026-01-01T00:00:00Z", "type": "mystery_event", "payload": {}})
        pfad = self._temp_datei([zeile])
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("toplevel:mystery_event", beleg.erfassung.unbekannt)
        self.assertEqual(beleg.ereignisse, [])

    def test_unbekannter_response_item_payload_typ(self):
        zeile = json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "response_item",
                "payload": {"type": "neuartig_4711"},
            }
        )
        pfad = self._temp_datei([zeile])
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("response_item:neuartig_4711", beleg.erfassung.unbekannt)

    def test_unbekannter_event_msg_payload_typ(self):
        zeile = json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "event_msg",
                "payload": {"type": "neuartig_0815"},
            }
        )
        pfad = self._temp_datei([zeile])
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("event_msg:neuartig_0815", beleg.erfassung.unbekannt)

    def test_leere_datei_stuerzt_nicht_ab(self):
        pfad = self._temp_datei([])
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertEqual(beleg.ereignisse, [])
        self.assertEqual(beleg.erfassung.token, "not_observed")

    def test_liste_als_zeile_wird_uebersprungen(self):
        """F8: valides JSON, aber kein Dict -> struktur:<typ>, kein Absturz."""
        zeilen = _FIXTURE.read_text(encoding="utf-8").splitlines()
        zeilen.append(json.dumps([1, 2]))
        pfad = self._temp_datei(zeilen)
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("struktur:list", beleg.erfassung.unbekannt)

    def test_string_als_zeile_wird_uebersprungen(self):
        zeilen = _FIXTURE.read_text(encoding="utf-8").splitlines()
        zeilen.append(json.dumps("text"))
        pfad = self._temp_datei(zeilen)
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("struktur:str", beleg.erfassung.unbekannt)

    def test_payload_falscher_typ_wird_uebersprungen(self):
        zeile = json.dumps({
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "response_item",
            "payload": [1],
        })
        pfad = self._temp_datei([zeile])
        beleg = leser_codex.lese_sitzung(pfad)
        self.assertIn("struktur:list", beleg.erfassung.unbekannt)


class TestLeserCodexFehlerklassifikation(unittest.TestCase):
    """Exit-Code- und Timeout-Erkennung isoliert an synthetischen Zeilen."""

    def _sitzung_mit_tool(self, name: str, output: str) -> modell.Beleg:
        zeilen = [
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "type": "session_meta",
                    "payload": {"session_id": "s1", "cwd": "C:\\x\\y", "cli_version": "0.1.0"},
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:01Z",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": name, "call_id": "c1"},
                }
            ),
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:02Z",
                    "type": "response_item",
                    "payload": {"type": "function_call_output", "call_id": "c1", "output": output},
                }
            ),
        ]
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for z in zeilen:
            tmp.write(z + "\n")
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return leser_codex.lese_sitzung(tmp.name)

    def test_exit_nonzero(self):
        beleg = self._sitzung_mit_tool(
            "shell_command", "Exit code: 1\nWall time: 1.5 seconds\nOutput:\nirrelevant"
        )
        ergebnis = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS][0]
        self.assertTrue(ergebnis.fehler)
        self.assertEqual(ergebnis.fehlerklasse, "exit_nonzero")
        self.assertEqual(ergebnis.dauer_ms, 1500)
        self.assertEqual(len(ergebnis.signatur), 12)

    def test_timeout(self):
        beleg = self._sitzung_mit_tool(
            "shell_command", "command timed out after 10000ms"
        )
        ergebnis = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS][0]
        self.assertTrue(ergebnis.fehler)
        self.assertEqual(ergebnis.fehlerklasse, "timeout")

    def test_erfolg_erzeugt_kein_ergebnis_ereignis(self):
        """F5: ART_TOOL_ERGEBNIS entsteht nur bei Fehler, wie im Claude-Leser."""
        beleg = self._sitzung_mit_tool(
            "shell_command", "Exit code: 0\nWall time: 0.1 seconds\nOutput:\nok"
        )
        ergebnisse = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS]
        self.assertEqual(ergebnisse, [])

    def test_erfolg_traegt_wall_time_am_tool_ereignis(self) -> None:
        """F5: Wall-Time erfolgreicher Aufrufe landet als dauer_ms am ART_TOOL-Ereignis."""
        beleg = self._sitzung_mit_tool(
            "shell_command", "Exit code: 0\nWall time: 0.1 seconds\nOutput:\nok"
        )
        aufruf = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL][0]
        self.assertEqual(aufruf.dauer_ms, 100)

    def test_unsicherer_function_name_wird_gehasht(self):
        beleg = self._sitzung_mit_tool(
            "C:\\Users\\x\\evil-tool", "Exit code: 0\nWall time: 0.1 seconds\n"
        )
        aufruf = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL][0]
        self.assertTrue(aufruf.name.startswith("unbekannt:"))
        self.assertNotIn("Users", aufruf.name)

    def test_sicherer_function_name_bleibt_unveraendert(self):
        beleg = self._sitzung_mit_tool(
            "shell_command", "Exit code: 0\nWall time: 0.1 seconds\n"
        )
        aufruf = [ev for ev in beleg.ereignisse if ev.art == modell.ART_TOOL][0]
        self.assertEqual(aufruf.name, "shell_command")

    def test_signatur_deterministisch_und_gruppierend(self):
        b1 = self._sitzung_mit_tool("shell_command", "Exit code: 1\nWall time: 1 seconds\n")
        b2 = self._sitzung_mit_tool("shell_command", "Exit code: 1\nWall time: 99 seconds\n")
        s1 = [ev for ev in b1.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS][0].signatur
        s2 = [ev for ev in b2.ereignisse if ev.art == modell.ART_TOOL_ERGEBNIS][0].signatur
        # gleiche (name, fehlerklasse, exit_code) -> gleiche Signatur, unabhängig von der Dauer
        self.assertEqual(s1, s2)


class TestGitWurzelAlsProjektname(unittest.TestCase):
    """Auftrag A.3 (Sichtabnahme Block 1): künftige Ingests nutzen die Git-Wurzel statt
    des letzten Pfadteils -- vereint Sitzungen aus Unterordnern/Clones desselben Repos."""

    def _temp_datei(self, zeilen: list[str]) -> str:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        for z in zeilen:
            tmp.write(z + "\n")
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return tmp.name

    def _sitzung_mit_cwd(self, cwd: Path) -> str:
        zeile = json.dumps({
            "timestamp": "2026-01-01T00:00:00Z", "type": "session_meta",
            "payload": {"cwd": str(cwd), "session_id": "x"},
        })
        return self._temp_datei([zeile])

    def test_git_wurzel_statt_letztem_ordner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp) / "MeinRepo"
            unterordner = wurzel / "codex-workspace"
            unterordner.mkdir(parents=True)
            (wurzel / ".git").mkdir()
            beleg = leser_codex.lese_sitzung(self._sitzung_mit_cwd(unterordner))
        self.assertEqual(beleg.kopf.projekt_name, "MeinRepo")

    def test_ohne_git_bleibt_letzter_pfadteil(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ordner = Path(tmp) / "OhneGit" / "unterordner"
            ordner.mkdir(parents=True)
            beleg = leser_codex.lese_sitzung(self._sitzung_mit_cwd(ordner))
        self.assertEqual(beleg.kopf.projekt_name, "unterordner")

    def test_nicht_mehr_vorhandener_pfad_faellt_zurueck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            beleg = leser_codex.lese_sitzung(self._sitzung_mit_cwd(Path(tmp) / "verschwunden" / "unterordner"))
        self.assertEqual(beleg.kopf.projekt_name, "unterordner")


if __name__ == "__main__":
    unittest.main()
