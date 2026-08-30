"""Tests für leser_claude — TDD, keine Mocks, echte (redigierte) Fixture-Daten.

Zwei Ebenen:
  1. Die große, anonymisierte Fixture (tests/fixtures/claude/...) prüft, dass
     echte Sitzungsform ohne Absturz gelesen wird und die strukturellen
     Zählungen (Runden/Tools/Fehler/Compactions/Subagenten) stimmen — mit
     Werten, die unabhängig von leser_claude.py aus derselben Fixture-Datei
     ermittelt und hier hart kodiert wurden (siehe make_fixture_claude.py-Lauf
     vom 2026-08-25).
  2. Kleine, selbst geschriebene synthetische JSONL-Schnipsel prüfen die
     inhaltsabhängigen Klassifikationen (Task-Notification-Ausschluss,
     blocked-Präfixe, Datei:Zeile/Backtick/Test-Muster) gezielt — die große
     Fixture kann das NICHT leisten, weil ihr Text vollständig redigiert ist
     (<redigiert:N> trifft absichtlich auf keines dieser Muster).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .. import leser_claude
from .. import modell

FIXTURE_ORDNER = Path(__file__).parent / "fixtures" / "claude"
FIXTURE_SITZUNG = FIXTURE_ORDNER / "d6e0c778-0fa7-40a7-a1cb-df93c23ecd42.jsonl"

# Unabhängig aus der Fixture ermittelt (siehe Docstring oben) — NICHT aus
# leser_claude.py abgeleitet.
ERWARTET_RUNDEN = 7  # inkl. 3 Compaction-Fortsetzungszeilen, die als Runde zählen
ERWARTET_TOOLS = 8          # tool_use ohne name=="Agent"
ERWARTET_TOOL_FEHLER = 0    # is_error=True in dieser Fixture-Auswahl
ERWARTET_COMPACTIONS = 3
ERWARTET_SUBAGENTEN = 2


class TestFixtureZaehlungen(unittest.TestCase):
    """Strukturelle Zählungen gegen die echte (redigierte) Fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.beleg = leser_claude.lese_sitzung(str(FIXTURE_SITZUNG), host="testhost")

    def test_runden(self) -> None:
        runden = [e for e in self.beleg.ereignisse if e.art == modell.ART_NUTZER]
        self.assertEqual(len(runden), ERWARTET_RUNDEN)

    def test_tools(self) -> None:
        tools = [e for e in self.beleg.ereignisse if e.art == modell.ART_TOOL]
        self.assertEqual(len(tools), ERWARTET_TOOLS)

    def test_tool_fehler(self) -> None:
        fehler = [e for e in self.beleg.ereignisse if e.art == modell.ART_TOOL_ERGEBNIS and e.fehler]
        self.assertEqual(len(fehler), ERWARTET_TOOL_FEHLER)

    def test_compactions(self) -> None:
        compactions = [e for e in self.beleg.ereignisse if e.art == modell.ART_COMPACTION]
        self.assertEqual(len(compactions), ERWARTET_COMPACTIONS)

    def test_subagenten_anzahl(self) -> None:
        self.assertEqual(len(self.beleg.subagenten), ERWARTET_SUBAGENTEN)

    def test_subagenten_felder_plausibel(self) -> None:
        for sub in self.beleg.subagenten:
            self.assertTrue(sub.agent_id)
            self.assertIn(sub.ergebnis, ("ok", "fehler", "leer"))
            self.assertGreaterEqual(sub.tools, 0)
            self.assertGreaterEqual(sub.tool_fehler, 0)

    def test_subagenten_modell_volle_kennung_aus_transkript(self) -> None:
        # Beide Fixture-Subagenten haben eine "claude-sonnet-5"-assistant-Zeile im eigenen
        # Transkript -- die volle Kennung muss die meta.json-Kurzform ("sonnet") verdraengen.
        for sub in self.beleg.subagenten:
            self.assertEqual(sub.modell, "claude-sonnet-5")

    def test_subagenten_auftrag_aus_meta_description(self) -> None:
        auftraege = {sub.agent_id: sub.auftrag for sub in self.beleg.subagenten}
        self.assertEqual(auftraege["a5131335208a184a1"], "Testauftrag Recherche kurz")
        # > 80 Zeichen in meta.json -> auf 80 gekuerzt, mit "…" markiert.
        lang = auftraege["a458c8c55a0caff54"]
        self.assertEqual(len(lang), 80)
        self.assertTrue(lang.endswith("…"))
        self.assertTrue(lang.startswith("Testauftrag Format-Erkundung"))

    def test_kopf_gefuellt(self) -> None:
        kopf = self.beleg.kopf
        self.assertEqual(kopf.quelle, "claude")
        self.assertEqual(kopf.sitzung_id, "d6e0c778-0fa7-40a7-a1cb-df93c23ecd42")
        self.assertEqual(kopf.host, "testhost")
        self.assertEqual(kopf.git_branch, "main")
        self.assertTrue(kopf.version)
        self.assertTrue(kopf.start)
        self.assertTrue(kopf.ende)
        self.assertIn("claude-fable-5", kopf.modelle)

    def test_projekt_hash_ist_kein_pfad(self) -> None:
        kopf = self.beleg.kopf
        self.assertNotIn("Beispiel", kopf.projekt_hash)
        self.assertNotIn("\\", kopf.projekt_hash)
        self.assertEqual(len(kopf.projekt_hash), 12)
        self.assertEqual(kopf.projekt_name, "Projekt")

    def test_erfassung_werte(self) -> None:
        erfassung = self.beleg.erfassung
        self.assertEqual(erfassung.token, "observed")
        self.assertEqual(erfassung.dauer, "observed")
        self.assertEqual(erfassung.kosten, "not_observed")
        self.assertEqual(erfassung.inhalte, "redacted")
        self.assertEqual(erfassung.subagenten, "observed")
        self.assertEqual(erfassung.compaction, "observed")
        self.assertEqual(erfassung.reasoning, "partial")

    def test_unbekannte_typen_erfasst(self) -> None:
        # Metadaten-Typen (atis-latch/ai-title/...) und alle Felder der Fixture
        # (Stand 2.1.245) sind bekannt -> keine Drift. Synthetische Drift: test_drift_und_leaks.
        self.assertEqual(self.beleg.erfassung.unbekannt, [])
        # bekannte Typen dürfen NICHT auftauchen
        self.assertNotIn("user", self.beleg.erfassung.unbekannt)
        self.assertNotIn("assistant", self.beleg.erfassung.unbekannt)

    def test_keine_langen_strings_in_ereignissen(self) -> None:
        for e in self.beleg.ereignisse:
            for feld in (e.name, e.ref, e.fehlerklasse, e.signatur):
                self.assertLessEqual(len(feld), 80, msg=f"zu lang: {feld!r} in {e.art}")

    def test_kein_inhalt_in_ereignissen(self) -> None:
        # Stichprobe: kein Ereignisname/-ref enthält den Redaktionsmarker
        # (der dürfte nirgends in Ereignis-Feldern auftauchen, weil wir nie
        # Rohtext übernehmen).
        for e in self.beleg.ereignisse:
            self.assertNotIn("redigiert", e.name)
            self.assertNotIn("redigiert", e.ref)

    def test_thinking_bloecke_gezaehlt(self) -> None:
        self.assertGreater(self.beleg.kennzahlen.thinking_bloecke, 0)


class TestKaputteZeile(unittest.TestCase):
    """Fixture-Kopie mit einer kaputten JSON-Zeile: darf nie crashen."""

    def test_kaputte_zeile_wird_gezaehlt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / FIXTURE_SITZUNG.name
            text = FIXTURE_SITZUNG.read_text(encoding="utf-8")
            zeilen = text.splitlines()
            zeilen.insert(5, "{diese Zeile ist kein gueltiges JSON")
            zeilen.insert(10, "{ebenfalls kaputt: kein json")
            ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

            beleg = leser_claude.lese_sitzung(str(ziel))

        self.assertEqual(beleg.kopf.sitzung_id, FIXTURE_SITZUNG.stem)
        kaputte_funde = [
            a for a in beleg.auffaelligkeiten if a.regel == "format:kaputte_zeile"
        ]
        self.assertEqual(len(kaputte_funde), 1)
        self.assertEqual(int(kaputte_funde[0].wert), 2)


class TestFormatDrift(unittest.TestCase):
    """F8: valides JSON, aber falscher Strukturtyp (Liste/String statt Dict,
    oder message mit falschem Typ) -> nie AttributeError, Zeile wird
    übersprungen und als 'struktur:<typ>' in erfassung.unbekannt gezählt."""

    def test_liste_und_string_zeilen_werden_uebersprungen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / FIXTURE_SITZUNG.name
            text = FIXTURE_SITZUNG.read_text(encoding="utf-8")
            zeilen = text.splitlines()
            zeilen.append(json.dumps([1, 2]))
            zeilen.append(json.dumps("text"))
            ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

            beleg = leser_claude.lese_sitzung(str(ziel))

        self.assertIn("struktur:list", beleg.erfassung.unbekannt)
        self.assertIn("struktur:str", beleg.erfassung.unbekannt)

    def test_message_falscher_typ_wird_uebersprungen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / FIXTURE_SITZUNG.name
            text = FIXTURE_SITZUNG.read_text(encoding="utf-8")
            zeilen = text.splitlines()
            zeilen.append(json.dumps({
                "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                "message": "kein dict",
            }))
            ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

            beleg = leser_claude.lese_sitzung(str(ziel))

        self.assertIn("struktur:str", beleg.erfassung.unbekannt)


class TestEndeNurInhaltlich(unittest.TestCase):
    """Buchhaltungszeilen (queue-operation, file-history-*, cost-state) verschieben start/ende
    NICHT (Befund 2026-08-27: Beleg 1324 = Phantom-Version von 1284 mit 18h39 Dauer, weil ein
    queue-operation-Eintrag 9 h nach dem letzten Turn in die alte Datei geschrieben wurde)."""

    def test_queue_operation_nach_letztem_turn_verschiebt_ende_nicht(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "sitzung.jsonl"
            zeilen = [
                {"type": "queue-operation", "timestamp": "2026-08-26T10:00:00.000Z"},
                {"type": "user", "timestamp": "2026-08-26T10:54:59.000Z", "cwd": "C:\\Beispiel",
                 "message": {"content": "Hallo"}},
                {"type": "assistant", "timestamp": "2026-08-26T20:25:03.000Z",
                 "message": {"content": [{"type": "text", "text": "Fertig."}]}},
                {"type": "queue-operation", "timestamp": "2026-08-27T05:33:38.000Z"},
            ]
            ziel.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(ziel))
        self.assertEqual(beleg.kopf.start, "2026-08-26T10:54:59.000Z")
        self.assertEqual(beleg.kopf.ende, "2026-08-26T20:25:03.000Z")


class TestUsageEinmalJeMessageId(unittest.TestCase):
    """Claude Code schreibt je Inhaltsblock (thinking/text/tool_use) eine eigene assistant-Zeile
    mit derselben message.id und identischer usage -- Token zaehlen nur einmal je id
    (Befund 2026-08-27: 704 Zeilen, 384 ids, Token out 507k statt 212k)."""

    def _beleg(self, zeilen):
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "sitzung.jsonl"
            ziel.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            return leser_claude.lese_sitzung(str(ziel))

    def test_wiederholte_usage_zaehlt_einmal(self) -> None:
        usage = {"input_tokens": 2, "output_tokens": 176, "cache_read_input_tokens": 1000}
        zeilen = [
            {"type": "user", "timestamp": "2026-08-26T10:00:00.000Z", "message": {"content": "Hallo"}},
            {"type": "assistant", "timestamp": "2026-08-26T10:00:01.000Z",
             "message": {"id": "msg_1", "model": "m", "usage": usage, "content": [{"type": "thinking", "thinking": "x"}]}},
            {"type": "assistant", "timestamp": "2026-08-26T10:00:02.000Z",
             "message": {"id": "msg_1", "model": "m", "usage": usage, "content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]}},
            {"type": "assistant", "timestamp": "2026-08-26T10:00:05.000Z",
             "message": {"id": "msg_2", "model": "m", "usage": usage, "content": [{"type": "text", "text": "ok"}]}},
        ]
        beleg = self._beleg(zeilen)
        assistent = [e for e in beleg.ereignisse if e.art == modell.ART_ASSISTENT]
        self.assertEqual(len(assistent), 2)
        self.assertEqual(sum(e.token.output for e in assistent), 352)


class TestUnbekannterTyp(unittest.TestCase):
    """Ein bisher nie gesehener type-Wert darf nicht crashen, landet in unbekannt."""

    def test_neuer_typ_landet_in_unbekannt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "sitzung.jsonl"
            zeilen = [
                {"type": "irgendein-ganz-neuer-typ", "timestamp": "2026-08-25T10:00:00.000Z"},
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": "Hallo"},
                },
            ]
            ziel.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")

            beleg = leser_claude.lese_sitzung(str(ziel))

        self.assertIn("irgendein-ganz-neuer-typ", beleg.erfassung.unbekannt)


class TestInhaltsabhaengigeKlassifikation(unittest.TestCase):
    """Synthetische (nicht aus echten Transkripten stammende) Schnipsel für
    Logik, die die redigierte Fixture nicht mehr prüfen kann."""

    def _sitzung_aus_zeilen(self, zeilen: list[dict], tmp: str) -> str:
        pfad = Path(tmp) / "sitzung.jsonl"
        pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
        return str(pfad)

    def test_task_notification_zaehlt_nicht_als_runde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": "<task-notification>\n<task-id>x</task-id>\n</task-notification>"},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": "Echte Nutzerfrage"},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        runden = [e for e in beleg.ereignisse if e.art == modell.ART_NUTZER]
        self.assertEqual(len(runden), 1)

    def test_ismeta_zaehlt_nicht_als_runde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "isMeta": True,
                    "message": {"content": "Caveat: system reminder"},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        runden = [e for e in beleg.ereignisse if e.art == modell.ART_NUTZER]
        self.assertEqual(len(runden), 0)

    def test_tool_result_ohne_weiteren_block_zaehlt_nicht_als_runde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok", "is_error": False},
                    ]},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        runden = [e for e in beleg.ereignisse if e.art == modell.ART_NUTZER]
        self.assertEqual(len(runden), 0)

    def test_blocked_praefix_klassifikation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "x"}},
                    ]},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1",
                         "content": "Permission to use Bash denied", "is_error": True},
                    ]},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        fehler = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL_ERGEBNIS]
        self.assertEqual(len(fehler), 1)
        self.assertEqual(fehler[0].fehlerklasse, "blocked")
        self.assertEqual(fehler[0].name, "Bash")

    def test_sonstiger_fehler_klassifikation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "x"}},
                    ]},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_2",
                         "content": "Exit code 1\nsome unrelated failure", "is_error": True},
                    ]},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        fehler = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL_ERGEBNIS]
        self.assertEqual(fehler[0].fehlerklasse, "tool_error")

    def test_datei_signatur_gesetzt_ref_ist_tool_use_id(self) -> None:
        """F4: Datei-Hash liegt in signatur, ref bleibt tool_use_id."""
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_3", "name": "Edit",
                         "input": {"file_path": "C:\\Beispiel\\datei.py", "old_string": "a", "new_string": "b"}},
                    ]},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        tools = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].ref, "toolu_3")
        self.assertTrue(tools[0].signatur)
        self.assertNotIn("Beispiel", tools[0].signatur)
        self.assertEqual(len(tools[0].signatur), 12)

    def test_parallele_tool_use_fehler_ref_zeigt_auf_richtiges_tool(self) -> None:
        """F4: zwei parallele tool_use A,B (beide vor jedem Ergebnis offen);
        das Fehler-Ergebnis traegt tool_use_id B -> ref des erzeugten
        ART_TOOL_ERGEBNIS-Ereignisses zeigt auf B, nicht auf A."""
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_A", "name": "Edit",
                         "input": {"file_path": "C:\\Beispiel\\a.py", "old_string": "a", "new_string": "b"}},
                        {"type": "tool_use", "id": "toolu_B", "name": "Edit",
                         "input": {"file_path": "C:\\Beispiel\\b.py", "old_string": "a", "new_string": "b"}},
                    ]},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_B",
                         "content": "kaputt", "is_error": True},
                    ]},
                },
            ]
            beleg = leser_claude.lese_sitzung(self._sitzung_aus_zeilen(zeilen, tmp))
        tools = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL]
        fehler = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL_ERGEBNIS]
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0].ref, "toolu_A")
        self.assertEqual(tools[1].ref, "toolu_B")
        self.assertNotEqual(tools[0].signatur, tools[1].signatur)
        self.assertEqual(len(fehler), 1)
        self.assertEqual(fehler[0].ref, "toolu_B")


class TestSubagentBelegKlassifikation(unittest.TestCase):
    """Synthetische Subagenten-Transkripte für beleg/ergebnis-Zweige."""

    def _baue_sitzung_mit_subagent(self, tmp: str, subagent_zeilen: list[dict], meta: dict) -> str:
        sitzung_pfad = Path(tmp) / "sitzung.jsonl"
        sitzung_pfad.write_text(json.dumps({
            "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
            "message": {"content": "Start"},
        }), encoding="utf-8")
        sub_ordner = Path(tmp) / "sitzung" / "subagents"
        sub_ordner.mkdir(parents=True)
        (sub_ordner / "agent-x1.jsonl").write_text(
            "\n".join(json.dumps(z) for z in subagent_zeilen), encoding="utf-8"
        )
        (sub_ordner / "agent-x1.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return str(sitzung_pfad)

    def test_beleg_observed_bei_dateizeile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                    "message": {"model": "sonnet", "content": [
                        {"type": "text", "text": "Fehler behoben in leser.py:42"},
                    ]},
                },
            ]
            pfad = self._baue_sitzung_mit_subagent(
                tmp, zeilen, {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(len(beleg.subagenten), 1)
        self.assertEqual(beleg.subagenten[0].beleg, "observed")
        self.assertEqual(beleg.subagenten[0].ergebnis, "ok")

    def test_beleg_not_observed_ohne_muster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                    "message": {"model": "sonnet", "content": [
                        {"type": "text", "text": "Alles erledigt, keine Details"},
                    ]},
                },
            ]
            pfad = self._baue_sitzung_mit_subagent(
                tmp, zeilen, {"agentType": "Explore", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].beleg, "not_observed")

    def test_ergebnis_leer_ohne_assistant_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                    "message": {"model": "sonnet", "content": [
                        {"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {"command": "x"}},
                    ]},
                },
            ]
            pfad = self._baue_sitzung_mit_subagent(
                tmp, zeilen, {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].ergebnis, "leer")
        self.assertEqual(beleg.subagenten[0].beleg, "not_observed")

    def test_ergebnis_fehler_wenn_letztes_tool_result_fehler_ohne_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                    "message": {"model": "sonnet", "content": [
                        {"type": "text", "text": "Starte Test 1"},
                        {"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {"command": "x"}},
                    ]},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_9", "content": "kaputt", "is_error": True},
                    ]},
                },
            ]
            pfad = self._baue_sitzung_mit_subagent(
                tmp, zeilen, {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].ergebnis, "fehler")

    def test_modell_bevorzugt_volle_kennung_aus_transkript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z",
                    "message": {"model": "claude-sonnet-5", "content": [
                        {"type": "text", "text": "Erledigt"},
                    ]},
                },
            ]
            pfad = self._baue_sitzung_mit_subagent(
                tmp, zeilen, {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].modell, "claude-sonnet-5")

    def test_modell_faellt_auf_meta_kurzform_zurueck_ohne_transkript_modell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Kein assistant-Zeile mit "model" im Subagent-Transkript (z. B. leeres/fehlendes
            # Transkript) -> meta.json "model" (Kurzform) bleibt der einzige Wert.
            pfad = self._baue_sitzung_mit_subagent(
                tmp, [], {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].modell, "sonnet")

    def test_auftrag_aus_meta_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = self._baue_sitzung_mit_subagent(
                tmp, [], {
                    "agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1,
                    "description": "Kurzauftrag Testfall",
                }
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].auftrag, "Kurzauftrag Testfall")

    def test_auftrag_leer_ohne_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = self._baue_sitzung_mit_subagent(
                tmp, [], {"agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1}
            )
            beleg = leser_claude.lese_sitzung(pfad)
        self.assertEqual(beleg.subagenten[0].auftrag, "")

    def test_auftrag_wird_auf_80_zeichen_gekuerzt(self) -> None:
        lang = "x" * 100
        with tempfile.TemporaryDirectory() as tmp:
            pfad = self._baue_sitzung_mit_subagent(
                tmp, [], {
                    "agentType": "general-purpose", "model": "sonnet", "spawnDepth": 1,
                    "description": lang,
                }
            )
            beleg = leser_claude.lese_sitzung(pfad)
        auftrag = beleg.subagenten[0].auftrag
        self.assertEqual(len(auftrag), 80)
        self.assertTrue(auftrag.endswith("…"))
        self.assertEqual(auftrag[:-1], "x" * 79)


class TestSichererBezeichnerAufToolnamen(unittest.TestCase):
    """F3: unsichere Tool-/tool_result-Namen werden gehasht, saubere bleiben."""

    def test_unsicherer_tool_use_name_wird_gehasht(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_1",
                         "name": "mcp__srv__C:\\Users\\x\\tool", "input": {}},
                    ]},
                },
            ]
            pfad = Path(tmp) / "sitzung.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        tools = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL]
        self.assertEqual(len(tools), 1)
        self.assertTrue(tools[0].name.startswith("unbekannt:"))
        self.assertNotIn("Users", tools[0].name)

    def test_sicherer_mcp_tool_use_name_bleibt_unveraendert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_1",
                         "name": "mcp__claude-in-chrome__navigate", "input": {}},
                    ]},
                },
            ]
            pfad = Path(tmp) / "sitzung.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        tools = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL]
        self.assertEqual(tools[0].name, "mcp__claude-in-chrome__navigate")

    def test_unsicherer_tool_result_name_wird_gehasht(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "assistant", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "message": {"model": "m", "content": [
                        {"type": "tool_use", "id": "toolu_1",
                         "name": "mcp__srv__C:\\Users\\x\\tool", "input": {}},
                    ]},
                },
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:01.000Z", "cwd": "C:\\Beispiel",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1",
                         "content": "boom", "is_error": True},
                    ]},
                },
            ]
            pfad = Path(tmp) / "sitzung.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        fehler = [e for e in beleg.ereignisse if e.art == modell.ART_TOOL_ERGEBNIS]
        self.assertEqual(len(fehler), 1)
        self.assertTrue(fehler[0].name.startswith("unbekannt:"))

    def test_unsicherer_git_branch_wird_gehasht(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "gitBranch": "C:\\Users\\x\\evil-branch",
                    "message": {"content": "Hallo"},
                },
            ]
            pfad = Path(tmp) / "sitzung.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        self.assertTrue(beleg.kopf.git_branch.startswith("unbekannt:"))

    def test_sicherer_git_branch_bleibt_unveraendert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zeilen = [
                {
                    "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                    "gitBranch": "main",
                    "message": {"content": "Hallo"},
                },
            ]
            pfad = Path(tmp) / "sitzung.jsonl"
            pfad.write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        self.assertEqual(beleg.kopf.git_branch, "main")

    def test_unsicherer_subagent_typ_wird_gehasht(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sitzung_pfad = Path(tmp) / "sitzung.jsonl"
            sitzung_pfad.write_text(json.dumps({
                "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": "C:\\Beispiel",
                "message": {"content": "Start"},
            }), encoding="utf-8")
            sub_ordner = Path(tmp) / "sitzung" / "subagents"
            sub_ordner.mkdir(parents=True)
            (sub_ordner / "agent-x1.jsonl").write_text("", encoding="utf-8")
            (sub_ordner / "agent-x1.meta.json").write_text(json.dumps({
                "agentType": "C:\\Users\\x\\evil-typ", "model": "sonnet", "spawnDepth": 1,
            }), encoding="utf-8")

            beleg = leser_claude.lese_sitzung(str(sitzung_pfad))
        self.assertEqual(len(beleg.subagenten), 1)
        self.assertTrue(beleg.subagenten[0].typ.startswith("unbekannt:"))


class TestGitWurzelAlsProjektname(unittest.TestCase):
    """Auftrag A.3 (Sichtabnahme Block 1): künftige Ingests nutzen die Git-Wurzel statt
    des letzten Pfadteils -- vereint Sitzungen aus Unterordnern desselben Repos."""

    def _sitzung_mit_cwd(self, tmp: str, cwd: Path) -> str:
        pfad = Path(tmp) / "sitzung.jsonl"
        pfad.write_text(json.dumps({
            "type": "user", "timestamp": "2026-08-25T10:00:00.000Z", "cwd": str(cwd),
            "message": {"content": "Hallo"},
        }), encoding="utf-8")
        return str(pfad)

    def test_git_wurzel_statt_letztem_ordner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp) / "MeinRepo"
            unterordner = wurzel / "scripts"
            unterordner.mkdir(parents=True)
            (wurzel / ".git").mkdir()
            beleg = leser_claude.lese_sitzung(self._sitzung_mit_cwd(tmp, unterordner))
        self.assertEqual(beleg.kopf.projekt_name, "MeinRepo")

    def test_ohne_git_bleibt_letzter_pfadteil(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ordner = Path(tmp) / "OhneGit" / "unterordner"
            ordner.mkdir(parents=True)
            beleg = leser_claude.lese_sitzung(self._sitzung_mit_cwd(tmp, ordner))
        self.assertEqual(beleg.kopf.projekt_name, "unterordner")

    def test_nicht_mehr_vorhandener_pfad_faellt_zurueck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            beleg = leser_claude.lese_sitzung(
                self._sitzung_mit_cwd(tmp, Path(tmp) / "verschwunden" / "unterordner")
            )
        self.assertEqual(beleg.kopf.projekt_name, "unterordner")


if __name__ == "__main__":
    unittest.main()
