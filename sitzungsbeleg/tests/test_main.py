"""Tests für __main__._ausgeben() — zentrale Ausgabefunktion mit Pflicht-Redaktion.

F1: `report` rendert vor dieser Fixung gespeichertes JSON ohne Redaktion —
`_ausgeben()` muss IMMER redaktion.bereinige + redaktion.pruefe_beleg vor jeder
Ausgabe ausführen (egal ob ingest oder report), bei Restverstoss Exit 2 ohne
jede Ausgabe.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .. import __main__ as main_mod
from .. import chat_kennzahlen, redaktion, web
from ..modell import ART_TOOL, Auffaelligkeit, Ereignis, Kopf

from .hilfen import baue_beleg
from .test_web import FakeLaufer


class ReportBereinigtVorAusgabeTest(unittest.TestCase):
    def test_report_bereinigt_eingeschleusten_pfad_und_ueberlaenge(self) -> None:
        kopf = Kopf(quelle="claude", sitzung_id="s1", host=r"C:\Beispiel\person\geheim")
        beleg = baue_beleg(kopf=kopf)
        beleg.ereignisse.append(
            Ereignis(zeit="2026-08-25T10:00:00Z", art=ART_TOOL, name="x" * 200)
        )

        with tempfile.TemporaryDirectory() as tmp:
            json_pfad = Path(tmp) / "beleg.json"
            json_pfad.write_text(
                json.dumps(beleg.als_dict(), ensure_ascii=False), encoding="utf-8"
            )

            with mock.patch("builtins.print") as mock_print:
                code = main_mod.main(["report", "--json", str(json_pfad)])

        self.assertEqual(code, 0)
        gedrucktes = "\n".join(
            str(anruf.args[0]) for anruf in mock_print.call_args_list if anruf.args
        )
        self.assertNotIn("geheim", gedrucktes)
        self.assertNotIn("x" * 200, gedrucktes)


class AusgebenExitCodeTest(unittest.TestCase):
    def test_exit_2_und_keine_ausgabe_bei_restverstoss(self) -> None:
        beleg = baue_beleg()
        with mock.patch.object(redaktion, "pruefe_beleg", return_value=["kopf.host: pfad"]):
            with mock.patch("builtins.print") as mock_print:
                code = main_mod._ausgeben(beleg, None, None)
        self.assertEqual(code, 2)
        mock_print.assert_not_called()

    def test_exit_2_schreibt_keine_dateien(self) -> None:
        beleg = baue_beleg()
        with tempfile.TemporaryDirectory() as tmp:
            json_pfad = Path(tmp) / "beleg.json"
            md_pfad = Path(tmp) / "beleg.md"
            with mock.patch.object(redaktion, "pruefe_beleg", return_value=["x: pfad"]):
                code = main_mod._ausgeben(beleg, str(json_pfad), str(md_pfad))
            self.assertEqual(code, 2)
            self.assertFalse(json_pfad.exists())
            self.assertFalse(md_pfad.exists())

    def test_sauberer_beleg_exit_0_und_datei_geschrieben(self) -> None:
        beleg = baue_beleg()
        with tempfile.TemporaryDirectory() as tmp:
            json_pfad = Path(tmp) / "beleg.json"
            code = main_mod._ausgeben(beleg, str(json_pfad), None)
            self.assertEqual(code, 0)
            self.assertTrue(json_pfad.exists())


class SpeichernErstNachRedaktionTest(unittest.TestCase):
    """C1 (Codex Stufe 2): der DB-Insert darf nie einen unbereinigten Beleg sehen."""

    def test_speichern_sieht_nur_bereinigten_beleg(self) -> None:
        from .. import speicher
        kopf = Kopf(quelle="claude", sitzung_id="s1", git_branch=r"C:\geheim\zweig")
        beleg = baue_beleg(kopf=kopf)
        gesehen = {}

        def fake_speichern(b, host):
            gesehen["branch"] = b.kopf.git_branch
            return None  # Konflikt -> kein Querschnitt

        with mock.patch.object(speicher, "speichern", fake_speichern):
            status = main_mod._speichern_mit_querschnitt(beleg, "pc")
        self.assertEqual(status, "vorhanden")
        self.assertEqual(gesehen["branch"], redaktion.REDIGIERT)

    def test_restverstoss_sperrt_speichern(self) -> None:
        from .. import speicher
        beleg = baue_beleg()
        with mock.patch.object(redaktion, "pruefe_beleg", return_value=["kopf.host: pfad"]):
            with mock.patch.object(speicher, "speichern") as sp:
                with self.assertRaises(main_mod.RedaktionsFehler):
                    main_mod._speichern_mit_querschnitt(beleg, "pc")
        sp.assert_not_called()


class BackendAusEnvTest(unittest.TestCase):
    """Auftrag Requesty 2026-08-28: der Stop-Hook liest `ANTHROPIC_BASE_URL` (im Prozess von
    `claude` geerbt) und klassifiziert nur die Hostklasse -- nie URL/Token im Beleg."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("ANTHROPIC_BASE_URL", None)

    def tearDown(self) -> None:
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        if self._alt is not None:
            os.environ["ANTHROPIC_BASE_URL"] = self._alt

    def test_leer_ist_anthropic(self) -> None:
        self.assertEqual(main_mod._backend_aus_env(), "anthropic")

    def test_localhost_ist_ollama(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:11434"
        self.assertEqual(main_mod._backend_aus_env(), "ollama")

    def test_openrouter_host_ist_openrouter(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://openrouter.ai/api"
        self.assertEqual(main_mod._backend_aus_env(), "openrouter")

    def test_requesty_host_ist_requesty(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://router.requesty.ai"
        self.assertEqual(main_mod._backend_aus_env(), "requesty")

    def test_requesty_eu_host_ist_ebenfalls_requesty(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://router.eu.requesty.ai"
        self.assertEqual(main_mod._backend_aus_env(), "requesty")

    def test_anthropic_host_ist_anthropic(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"
        self.assertEqual(main_mod._backend_aus_env(), "anthropic")

    def test_fremder_host_ist_unbekannt(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://irgendein-proxy.example.com"
        self.assertEqual(main_mod._backend_aus_env(), "unbekannt")


class UmgebungAusEnvTest(unittest.TestCase):
    """C12 (Auftrag 2026-08-28 12:45): der Stop-Hook liest `SITZUNGSBELEG_UMGEBUNG` --
    unbekannter Wert faellt auf `entwicklung` zurueck und meldet sich nur auf stderr, nie Abbruch."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("SITZUNGSBELEG_UMGEBUNG", None)

    def tearDown(self) -> None:
        os.environ.pop("SITZUNGSBELEG_UMGEBUNG", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_UMGEBUNG"] = self._alt

    def test_leer_ist_entwicklung(self) -> None:
        self.assertEqual(main_mod._umgebung_aus_env(), "entwicklung")

    def test_gesetzter_bekannter_wert_wird_uebernommen(self) -> None:
        os.environ["SITZUNGSBELEG_UMGEBUNG"] = "abnahme"
        self.assertEqual(main_mod._umgebung_aus_env(), "abnahme")

    def test_betrieb_wird_uebernommen(self) -> None:
        os.environ["SITZUNGSBELEG_UMGEBUNG"] = "betrieb"
        self.assertEqual(main_mod._umgebung_aus_env(), "betrieb")

    def test_unbekannter_wert_faellt_auf_entwicklung_zurueck_und_warnt(self) -> None:
        os.environ["SITZUNGSBELEG_UMGEBUNG"] = "staging"
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(main_mod._umgebung_aus_env(), "entwicklung")
        gewarnt = "".join(str(c.args[0]) for c in stderr.write.call_args_list if c.args)
        self.assertIn("staging", gewarnt)


class IngestHookSchreibtUmgebungTest(unittest.TestCase):
    """`_ingest_hook` setzt `beleg.kopf.umgebung` VOR dem Speichern (wie `kopf.backend`) --
    fail-open bleibt unangetastet."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("SITZUNGSBELEG_UMGEBUNG", None)

    def tearDown(self) -> None:
        os.environ.pop("SITZUNGSBELEG_UMGEBUNG", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_UMGEBUNG"] = self._alt

    def test_hook_schreibt_umgebung_aus_env_in_den_beleg(self) -> None:
        import io

        os.environ["SITZUNGSBELEG_UMGEBUNG"] = "abnahme"
        beleg = baue_beleg()
        gesehen = {}

        def fake_speichern_mit_querschnitt(b, host):
            gesehen["umgebung"] = b.kopf.umgebung
            return "vorhanden"

        args = argparse_namespace(preise=None, host="pc")
        with mock.patch.object(main_mod, "beleg_erzeugen", return_value=beleg), \
             mock.patch.object(main_mod, "_speichern_mit_querschnitt", fake_speichern_mit_querschnitt), \
             mock.patch("sys.stdin", io.StringIO(json.dumps({"transcript_path": "x.jsonl"}))):
            code = main_mod._ingest_hook(args)
        self.assertEqual(code, 0)
        self.assertEqual(gesehen["umgebung"], "abnahme")


class IngestHookSchreibtBackendTest(unittest.TestCase):
    """`_ingest_hook` setzt `beleg.kopf.backend` VOR dem Speichern -- Fail-open bleibt
    unangetastet (jeder Fehler landet weiterhin nur auf stderr, Exit 0)."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("ANTHROPIC_BASE_URL", None)

    def tearDown(self) -> None:
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        if self._alt is not None:
            os.environ["ANTHROPIC_BASE_URL"] = self._alt

    def test_hook_schreibt_backend_aus_env_in_den_beleg(self) -> None:
        import io

        os.environ["ANTHROPIC_BASE_URL"] = "https://router.requesty.ai"
        beleg = baue_beleg()
        gesehen = {}

        def fake_speichern_mit_querschnitt(b, host):
            gesehen["backend"] = b.kopf.backend
            return "vorhanden"

        args = argparse_namespace(preise=None, host="pc")
        with mock.patch.object(main_mod, "beleg_erzeugen", return_value=beleg), \
             mock.patch.object(main_mod, "_speichern_mit_querschnitt", fake_speichern_mit_querschnitt), \
             mock.patch("sys.stdin", io.StringIO(json.dumps({"transcript_path": "x.jsonl"}))):
            code = main_mod._ingest_hook(args)
        self.assertEqual(code, 0)
        self.assertEqual(gesehen["backend"], "requesty")


def argparse_namespace(**kw):
    import argparse
    return argparse.Namespace(**kw)


class PersonaAusEnvTest(unittest.TestCase):
    """C14 (Maintainer 2026-08-28): Persona aus `CLAUDE_CONFIG_DIR` -- VICA/CURA haben ein eigenes
    Konfigurationsverzeichnis, VICO nutzt das globale `~/.claude` (kein `.vico`-Ordner)."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def tearDown(self) -> None:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        if self._alt is not None:
            os.environ["CLAUDE_CONFIG_DIR"] = self._alt

    def test_leer_ist_vico(self) -> None:
        self.assertEqual(main_mod._persona_aus_env(), "vico")

    def test_vica_verzeichnis_ist_vica(self) -> None:
        os.environ["CLAUDE_CONFIG_DIR"] = r"C:\Users\x\.vica"
        self.assertEqual(main_mod._persona_aus_env(), "vica")

    def test_cura_verzeichnis_ist_cura(self) -> None:
        os.environ["CLAUDE_CONFIG_DIR"] = "/home/x/.cura"
        self.assertEqual(main_mod._persona_aus_env(), "cura")

    def test_anderer_pfad_ist_vico(self) -> None:
        os.environ["CLAUDE_CONFIG_DIR"] = r"C:\Users\x\.claude"
        self.assertEqual(main_mod._persona_aus_env(), "vico")

    def test_trailing_slash_wird_ignoriert(self) -> None:
        os.environ["CLAUDE_CONFIG_DIR"] = "/home/x/.vica/"
        self.assertEqual(main_mod._persona_aus_env(), "vica")


class KanalAusEnvTest(unittest.TestCase):
    """C14 (Maintainer 2026-08-28): `SITZUNGSBELEG_KANAL` -- leer bleibt `terminal`, die Orb-Bruecke
    setzt `orb`; ein unbekannter Wert faellt wie bei `_umgebung_aus_env` auf `terminal` zurueck."""

    def setUp(self) -> None:
        self._alt = os.environ.pop("SITZUNGSBELEG_KANAL", None)

    def tearDown(self) -> None:
        os.environ.pop("SITZUNGSBELEG_KANAL", None)
        if self._alt is not None:
            os.environ["SITZUNGSBELEG_KANAL"] = self._alt

    def test_leer_ist_terminal(self) -> None:
        self.assertEqual(main_mod._kanal_aus_env(), "terminal")

    def test_orb_wird_uebernommen(self) -> None:
        os.environ["SITZUNGSBELEG_KANAL"] = "orb"
        self.assertEqual(main_mod._kanal_aus_env(), "orb")

    def test_unbekannter_wert_faellt_auf_terminal_zurueck_und_warnt(self) -> None:
        os.environ["SITZUNGSBELEG_KANAL"] = "app"
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(main_mod._kanal_aus_env(), "terminal")
        gewarnt = "".join(str(c.args[0]) for c in stderr.write.call_args_list if c.args)
        self.assertIn("app", gewarnt)


class IngestHookSchreibtPersonaUndKanalTest(unittest.TestCase):
    """`_ingest_hook` setzt `beleg.kopf.persona` und `beleg.kopf.kanal` VOR dem Speichern
    (wie `kopf.backend`/`kopf.umgebung`) -- fail-open bleibt unangetastet."""

    def setUp(self) -> None:
        self._alt_persona = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self._alt_kanal = os.environ.pop("SITZUNGSBELEG_KANAL", None)

    def tearDown(self) -> None:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        os.environ.pop("SITZUNGSBELEG_KANAL", None)
        if self._alt_persona is not None:
            os.environ["CLAUDE_CONFIG_DIR"] = self._alt_persona
        if self._alt_kanal is not None:
            os.environ["SITZUNGSBELEG_KANAL"] = self._alt_kanal

    def test_hook_schreibt_persona_und_kanal_aus_env_in_den_beleg(self) -> None:
        import io

        os.environ["CLAUDE_CONFIG_DIR"] = r"C:\Users\x\.vica"
        os.environ["SITZUNGSBELEG_KANAL"] = "orb"
        beleg = baue_beleg()
        gesehen = {}

        def fake_speichern_mit_querschnitt(b, host):
            gesehen["persona"] = b.kopf.persona
            gesehen["kanal"] = b.kopf.kanal
            return "vorhanden"

        args = argparse_namespace(preise=None, host="pc")
        with mock.patch.object(main_mod, "beleg_erzeugen", return_value=beleg), \
             mock.patch.object(main_mod, "_speichern_mit_querschnitt", fake_speichern_mit_querschnitt), \
             mock.patch("sys.stdin", io.StringIO(json.dumps({"transcript_path": "x.jsonl"}))):
            code = main_mod._ingest_hook(args)
        self.assertEqual(code, 0)
        self.assertEqual(gesehen["persona"], "vica")
        self.assertEqual(gesehen["kanal"], "orb")


class IngestSpoolTest(unittest.TestCase):
    """`ingest-spool <verzeichnis>` (C14-Nachtrag Server-Spool, CONTRACTS.md): persona/kanal
    kommen je Eintrag aus `meta.jsonl`, nicht aus Env -- ein Spool kann mehrere Personas mischen.
    `beleg_erzeugen` wird gemockt (wie bei den `_ingest_hook`-Tests oben), damit die Tests ohne
    echte Transkriptdateien laufen; die Kopf-Felder werden am zurueckgegebenen Beleg geprueft."""

    def _schreibe_meta(self, tmp: str, zeilen: list[dict]) -> Path:
        verzeichnis = Path(tmp)
        meta = verzeichnis / "meta.jsonl"
        meta.write_text(
            "\n".join(json.dumps(z, ensure_ascii=False) for z in zeilen), encoding="utf-8"
        )
        return verzeichnis

    def _fake_beleg_erzeugen(self, gesehen: list):
        def fake(quelle, datei, preise, host):
            if "kaputt" in datei:
                raise ValueError("Transkript nicht lesbar")
            beleg = baue_beleg()
            beleg.kopf.sitzung_id = Path(datei).stem
            gesehen.append(beleg)
            return beleg
        return fake

    def test_persona_und_kanal_aus_meta_zeile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verzeichnis = self._schreibe_meta(
                tmp, [{"session_id": "s1", "datei": "s1.jsonl", "kanal": "orb", "persona": "vica"}]
            )
            gesehen: list = []
            args = argparse_namespace(verzeichnis=str(verzeichnis), db=False, host="pc", preise=None)
            with mock.patch.object(main_mod, "beleg_erzeugen", self._fake_beleg_erzeugen(gesehen)):
                code = main_mod._befehl_ingest_spool(args)
        self.assertEqual(code, 0)
        self.assertEqual(len(gesehen), 1)
        self.assertEqual(gesehen[0].kopf.persona, "vica")
        self.assertEqual(gesehen[0].kopf.kanal, "orb")

    def test_unbekannte_persona_faellt_auf_vico_zurueck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verzeichnis = self._schreibe_meta(
                tmp, [{"session_id": "s1", "datei": "s1.jsonl", "kanal": "terminal", "persona": "unbekannt"}]
            )
            gesehen: list = []
            args = argparse_namespace(verzeichnis=str(verzeichnis), db=False, host="pc", preise=None)
            with mock.patch.object(main_mod, "beleg_erzeugen", self._fake_beleg_erzeugen(gesehen)):
                main_mod._befehl_ingest_spool(args)
        self.assertEqual(gesehen[0].kopf.persona, "vico")

    def test_typ_zeile_wird_uebersprungen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verzeichnis = self._schreibe_meta(
                tmp, [
                    {"typ": "cura_zugriffsversuch", "zeit": "2026-08-28T10:00:00Z"},
                    {"session_id": "s1", "datei": "s1.jsonl", "kanal": "orb", "persona": "vico"},
                ]
            )
            gesehen: list = []
            args = argparse_namespace(verzeichnis=str(verzeichnis), db=False, host="pc", preise=None)
            with mock.patch.object(main_mod, "beleg_erzeugen", self._fake_beleg_erzeugen(gesehen)):
                main_mod._befehl_ingest_spool(args)
        self.assertEqual(len(gesehen), 1)
        self.assertEqual(gesehen[0].kopf.sitzung_id, "s1")

    def test_fehlendes_meta_jsonl_ist_exit_0_mit_meldung(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse_namespace(verzeichnis=tmp, db=False, host="pc", preise=None)
            with mock.patch("builtins.print") as mock_print:
                code = main_mod._befehl_ingest_spool(args)
        self.assertEqual(code, 0)
        gedrucktes = "\n".join(str(a.args[0]) for a in mock_print.call_args_list if a.args)
        self.assertIn("ingest-spool", gedrucktes)

    def test_kaputte_transkript_datei_bricht_andere_nicht_ab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verzeichnis = self._schreibe_meta(
                tmp, [
                    {"session_id": "kaputt", "datei": "kaputt.jsonl", "kanal": "orb", "persona": "vico"},
                    {"session_id": "s2", "datei": "s2.jsonl", "kanal": "orb", "persona": "vica"},
                ]
            )
            gesehen: list = []
            args = argparse_namespace(verzeichnis=str(verzeichnis), db=False, host="pc", preise=None)
            with mock.patch.object(main_mod, "beleg_erzeugen", self._fake_beleg_erzeugen(gesehen)), \
                 mock.patch("sys.stderr"):
                code = main_mod._befehl_ingest_spool(args)
        self.assertEqual(code, 0)
        self.assertEqual(len(gesehen), 1)
        self.assertEqual(gesehen[0].kopf.sitzung_id, "s2")


class AnbieterTestBefehlTest(unittest.TestCase):
    """CLI `anbieter-test <anbieter>` (Auftrag Requesty): Modell aus --modell oder
    modelle.json default_vico_<anbieter>, sonst klarer Exit-2-Hinweis statt Absturz."""

    def test_modell_aus_registry_wenn_kein_modell_angegeben(self) -> None:
        from .. import chat_bruecke

        gesehen = {}

        def fake_teste(anbieter, modell):
            gesehen["anbieter"], gesehen["modell"] = anbieter, modell
            return "exit=0"

        args = argparse_namespace(anbieter="requesty", modell=None)
        with mock.patch.object(main_mod, "MODELLE_PFAD", Path(__file__).resolve().parent.parent.parent / "modelle.json"), \
             mock.patch.object(chat_bruecke, "teste_anbieter", fake_teste):
            code = main_mod._befehl_anbieter_test(args)
        self.assertEqual(code, 0)
        self.assertEqual(gesehen["anbieter"], "requesty")
        self.assertEqual(gesehen["modell"], "xai/grok-4.6")

    def test_kein_modell_und_kein_registry_eintrag_gibt_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leer = Path(tmp) / "modelle.json"
            leer.write_text("{}", encoding="utf-8")
            args = argparse_namespace(anbieter="requesty", modell=None)
            with mock.patch.object(main_mod, "MODELLE_PFAD", leer):
                code = main_mod._befehl_anbieter_test(args)
        self.assertEqual(code, 2)


class ProjektnameAllowlistTest(unittest.TestCase):
    def test_projektname_mit_leerzeichen_wird_gehasht(self) -> None:
        from .. import redaktion as r
        self.assertTrue(r.sicherer_bezeichner("Max Mueller Kuendigung").startswith("unbekannt:"))
        self.assertEqual(r.sicherer_bezeichner("00_Workspace"), "00_Workspace")


class NachschlagenBefehlTest(unittest.TestCase):
    """CLI `nachschlagen <nr> [--befund <signatur>]` (Nachtrag Sichtkontext 2026-08-28, Auftrag
    "Dashboard-Ansicht ist fuer mich nicht sichtbar") -- ruft denselben `web._sitzung()` wie die
    Detailseite, Fake-Laufer statt echtem psql (Muster test_web.py:SitzungDetailTest)."""

    def setUp(self) -> None:
        self.alt = web.LAUFER

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def _aufloesung(self, logisch: int) -> dict:
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(logisch),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([logisch]),
        }

    def _gedrucktes(self, mock_print) -> str:
        return " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)

    def test_bekannte_sitzung_gibt_kennzahlen_und_befunde_aus(self) -> None:
        dokument = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc")).als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(137), "FROM sitzung WHERE id = 137": json.dumps(dokument)})
        args = argparse_namespace(nr=137, befund=None)
        with mock.patch("builtins.print") as mock_print:
            code = main_mod._befehl_nachschlagen(args)
        self.assertEqual(code, 0)
        self.assertIn("Sitzung 137", self._gedrucktes(mock_print))

    def test_unbekannte_sitzung_meldet_nicht_gefunden_exit_0(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        args = argparse_namespace(nr=999, befund=None)
        with mock.patch("builtins.print") as mock_print:
            code = main_mod._befehl_nachschlagen(args)
        self.assertEqual(code, 0)
        self.assertEqual(self._gedrucktes(mock_print), "Sitzung 999 nicht gefunden")

    def test_db_fehler_meldet_nicht_gefunden_ohne_rohtext_zu_leaken(self) -> None:
        def wirft(sql, zeitlimit_s=8):
            raise RuntimeError("Verbindung zu Postgres abgebrochen: geheimes-verbindungsdetail")

        web.LAUFER = wirft
        args = argparse_namespace(nr=42, befund=None)
        with mock.patch("builtins.print") as mock_print:
            code = main_mod._befehl_nachschlagen(args)
        self.assertEqual(code, 0)
        gedrucktes = self._gedrucktes(mock_print)
        self.assertEqual(gedrucktes, "Sitzung 42 nicht gefunden")
        self.assertNotIn("geheimes-verbindungsdetail", gedrucktes)

    def test_befund_filter_wird_durchgereicht(self) -> None:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"))
        beleg.auffaelligkeiten = [Auffaelligkeit(regel="cost:spike", schwere="warnung", signatur="cost:spike:single")]
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(21), "FROM sitzung WHERE id = 21": json.dumps(dokument)})
        args = argparse_namespace(nr=21, befund="cost:spike:single")
        with mock.patch("builtins.print") as mock_print:
            main_mod._befehl_nachschlagen(args)
        self.assertIn("cost:spike:single", self._gedrucktes(mock_print))


class NachschlagenGuardTest(unittest.TestCase):
    """Guard (Muster test_rohdatei.py:GuardsTest): das Nachschlage-Werkzeug schreibt nie --
    weder `_befehl_nachschlagen` noch `chat_kennzahlen.py` rufen einen `speicher.*`-Schreibweg
    auf. AST statt Substring-Check, damit deutsche Woerter wie "gespeichert" nicht anschlagen."""

    def _namen_und_importe(self, quelltext: str) -> set[str]:
        baum = ast.parse(quelltext)
        namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)}
        importe = {
            alias.asname or alias.name
            for node in ast.walk(baum) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        return namen | importe

    def test_chat_kennzahlen_modul_hat_keinen_speicher_bezug(self) -> None:
        self.assertNotIn("speicher", self._namen_und_importe(inspect.getsource(chat_kennzahlen)))
        self.assertFalse(hasattr(chat_kennzahlen, "speicher"))

    def test_befehl_nachschlagen_ruft_keinen_speicher_schreibweg_auf(self) -> None:
        quelltext = inspect.getsource(main_mod._befehl_nachschlagen)
        self.assertNotIn("speicher", self._namen_und_importe(quelltext))


if __name__ == "__main__":
    unittest.main()
