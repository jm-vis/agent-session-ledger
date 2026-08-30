"""Tests fuer chat_bruecke.py (Phase 2 F -- echte Kindprozess-Bruecke). Der echte `claude`-Aufruf
wird ueber `chat_bruecke.KOMMANDO_BAUEN` durch `tests/fake_claude.py` ersetzt (kein Mock-
Framework, kein echter Anthropic-Zugriff) -- Muster wie `chat._ollama_lauf` in test_chat.py."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from .. import chat_bruecke

FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


def _kommando(modus: str):
    return lambda modell: [sys.executable, str(FAKE_CLAUDE), modus]


class ChatProzessTest(unittest.TestCase):
    def setUp(self):
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        self._timeout_alt = chat_bruecke.TURN_TIMEOUT_S
        self._prozesse: list[chat_bruecke.ChatProzess] = []

    def tearDown(self):
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt
        chat_bruecke.TURN_TIMEOUT_S = self._timeout_alt
        for prozess in self._prozesse:
            prozess.beenden()  # kein Hintergrundprozess bleibt nach dem Test uebrig

    def _neuer_prozess(self, modus: str, kontext=None) -> chat_bruecke.ChatProzess:
        chat_bruecke.KOMMANDO_BAUEN = _kommando(modus)
        prozess = chat_bruecke.ChatProzess("claude", "irrelevant-im-fake", kontext)
        self._prozesse.append(prozess)
        return prozess

    def test_normal_turn_liefert_zwei_deltas_und_ende_mit_usage(self):
        prozess = self._neuer_prozess("normal")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual([e[0] for e in ereignisse], ["delta", "delta", "ende"])
        self.assertEqual("".join(e[1] for e in ereignisse[:2]), "Hallo, das ist die Fake-Antwort.")
        self.assertEqual(ereignisse[-1][1], {"token_in": 12, "token_out": 7})

    def test_prozess_wird_ueber_zwei_turns_wiederverwendet(self):
        prozess = self._neuer_prozess("normal")
        list(prozess.turn("Erste Frage"))
        erster_proc = prozess.proc
        list(prozess.turn("Zweite Frage"))
        self.assertIs(prozess.proc, erster_proc)  # kein Respawn zwischen zwei gesunden Turns

    def test_kontext_zeile_nur_im_ersten_turn(self):
        kontext = {"sitzung_logisch": 512, "signatur": None, "runde": None, "analyse_id": None}
        prozess = self._neuer_prozess("echo", kontext)
        erster = list(prozess.turn("Warum lief Runde 11 spaet?"))[0][1]
        self.assertIn("Sitzung 512", erster)
        self.assertIn("Warum lief Runde 11 spaet?", erster)
        zweiter = list(prozess.turn("Und jetzt?"))[0][1]
        self.assertEqual(zweiter, "Und jetzt?")  # keine Kontextzeile mehr im zweiten Turn

    def test_kennzahlen_block_geht_in_die_kontextzeile_des_ersten_turns(self):
        """Fund 2026-08-27: die Besprechung kannte nur die Sitzungs-ID, kein Modell konnte
        Kennzahlenfragen beantworten -- `chat.gespraech_starten` haengt seither einen Block an
        `kontext['kennzahlen_block']` (`chat_kennzahlen.baue_block`), der hier in der ersten
        Nachricht an den Kindprozess ankommen muss."""
        kontext = {
            "sitzung_logisch": 137, "signatur": None, "runde": None, "analyse_id": None,
            "kennzahlen_block": "Sitzung 137, Projekt demo, Quelle claude, Runden 3, Kosten 0.0500 USD",
        }
        prozess = self._neuer_prozess("echo", kontext)
        erster = list(prozess.turn("Was faellt dir an den Kennzahlen auf?"))[0][1]
        self.assertIn("Kennzahlen dieser Sitzung", erster)
        self.assertIn("Kosten 0.0500 USD", erster)

    def test_crash_liefert_fehler_und_naechster_turn_spawnt_neu(self):
        prozess = self._neuer_prozess("crash")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(ereignisse[0], ("delta", "Angebrochen"))
        self.assertEqual(ereignisse[-1][0], "fehler")
        self.assertIsNone(prozess.proc)  # Registry-Zustand aufgeraeumt
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")  # naechster Turn: gesunder Prozess
        ereignisse2 = list(prozess.turn("Neuer Versuch"))
        self.assertEqual([e[0] for e in ereignisse2], ["delta", "delta", "ende"])

    def test_thinking_delta_verlaengert_deadline_kein_faelschliches_zeitlimit(self):
        """Live-Test 2026-08-28 (Requesty/GLM-5.3-flash): das Modell liefert erst einen
        laengeren Denk-Block (thinking_delta), danach Text. Mit TURN_TIMEOUT_S=0.3s und zwei
        Denk-Pausen von je 0.2s (zusammen 0.4s > 0.3s) darf die Bruecke NICHT faelschlich
        Zeitlimit melden, wenn jedes Denk-Ereignis die Deadline verlaengert."""
        chat_bruecke.TURN_TIMEOUT_S = 0.3
        prozess = self._neuer_prozess("thinking_lang")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual([e[0] for e in ereignisse], ["delta", "ende"])
        self.assertEqual(ereignisse[0][1], "Text nach dem Denken.")

    def test_zeitlimit_ohne_delta_liefert_fehler(self):
        chat_bruecke.TURN_TIMEOUT_S = 0.3
        prozess = self._neuer_prozess("hang")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(ereignisse, [("fehler", "Zeitlimit (0.3s) ohne Antwort")])
        self.assertIsNone(prozess.proc)

    def test_zeitlimit_haengt_stderr_zeilen_an_die_fehlermeldung(self):
        """Fund 2026-08-27 (BEFUNDE.md): `stderr=DEVNULL` verschluckte Warnungen wie
        'unrecognized_model' spurlos -- seit `_stderr_reader`/`_mit_stderr` landen sie in der
        'fehler'-Meldung, damit ein kuenftiges Zeitlimit nicht wieder blind diagnostiziert
        werden muss."""
        chat_bruecke.TURN_TIMEOUT_S = 0.5
        prozess = self._neuer_prozess("hang_stderr")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(ereignisse, [
            ("fehler", "Zeitlimit (0.5s) ohne Antwort -- stderr: warn: irgendein hinweis"),
        ])

    def test_kommando_nicht_gefunden_liefert_fehler_ohne_absturz(self):
        def wirft(modell):
            raise chat_bruecke.ChatBrueckeFehler("claude.exe nicht gefunden")

        chat_bruecke.KOMMANDO_BAUEN = wirft
        prozess = chat_bruecke.ChatProzess("claude", "irrelevant")
        self._prozesse.append(prozess)
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(len(ereignisse), 1)
        self.assertEqual(ereignisse[0][0], "fehler")
        self.assertIn("nicht gestartet", ereignisse[0][1])


class StandardKommandoTest(unittest.TestCase):
    """Hintergrund-Chat darf nur lesen -- kein Rueckfrage-loser Vollzugriffsmodus, stattdessen
    `--allowedTools` read-only."""

    def setUp(self):
        self._exe_alt = chat_bruecke._claude_exe
        chat_bruecke._claude_exe = lambda: "claude.exe"

    def tearDown(self):
        chat_bruecke._claude_exe = self._exe_alt

    def test_kein_permission_mode_aber_allowedtools_readonly(self):
        cmd = chat_bruecke._standard_kommando("irgendein-modell")
        self.assertNotIn("--permission-mode", cmd)
        self.assertIn("--allowedTools", cmd)
        allowed = cmd[cmd.index("--allowedTools") + 1]
        self.assertIn("Read,Grep,Glob", allowed)
        # Nachtrag Sichtkontext (2026-08-28): das Nachschlage-Werkzeug ist nur EIN Bash-Praefix,
        # kein voller Shell-Zugriff -- Praefix-Syntax `Bash(<praefix> *)` wie im Repo ueblich.
        self.assertIn("Bash(python -m sitzungsbeleg nachschlagen *)", allowed)

    def test_system_prompt_traegt_fix_vorschlag_konvention(self):
        cmd = chat_bruecke._standard_kommando("irgendein-modell")
        prompt = cmd[cmd.index("--append-system-prompt") + 1]
        self.assertIn("FIX-VORSCHLAG:", prompt)


class FixKommandoTest(unittest.TestCase):
    """"Fix umsetzen": baut den konfigurierten Fix-Launcher (`SITZUNGSBELEG_FIX_LAUNCHER`), nie
    Nachrichtentext im Handover."""

    def setUp(self):
        # `schluessel.ZENTRALE_DATEI` ist testweit auf einen nicht existierenden Pfad umgebogen
        # (autouse-Fixture in conftest.py) -- hier reicht die reine Umgebungsvariable.
        self._env_alt = os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)

    def tearDown(self):
        os.environ.pop("SITZUNGSBELEG_FIX_LAUNCHER", None)
        if self._env_alt is not None:
            os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = self._env_alt

    def test_kommando_ersetzt_handover_in_jedem_element(self):
        os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = json.dumps(
            ["powershell", "C:/pfad/Launcher.ps1", "-To", "assistent", "-Handover", "{handover}"])
        cmd = chat_bruecke._fix_kommando("Sitzung 137, Befund rework:tool:Bash, Chat c-1")
        self.assertEqual(cmd, ["powershell", "C:/pfad/Launcher.ps1", "-To", "assistent",
                                "-Handover", "Sitzung 137, Befund rework:tool:Bash, Chat c-1"])

    def test_kommando_wirft_fix_launcher_fehlt_wenn_nicht_konfiguriert(self):
        with self.assertRaises(chat_bruecke.FixLauncherFehlt) as ctx:
            chat_bruecke._fix_kommando("Stichwort")
        self.assertIn("SITZUNGSBELEG_FIX_LAUNCHER", str(ctx.exception))

    def test_kommando_wirft_fix_launcher_fehlt_bei_kaputtem_json(self):
        os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = "{kaputt"
        with self.assertRaises(chat_bruecke.FixLauncherFehlt):
            chat_bruecke._fix_kommando("Stichwort")

    def test_oeffne_fix_fenster_startet_injizierten_starter(self):
        os.environ["SITZUNGSBELEG_FIX_LAUNCHER"] = json.dumps(["echo", "{handover}"])
        aufrufe = []
        chat_bruecke.oeffne_fix_fenster("Stichwort", starter=lambda cmd: aufrufe.append(cmd))
        self.assertEqual(len(aufrufe), 1)
        self.assertIn("Stichwort", aufrufe[0])


class OpenRouterUmgebungTest(unittest.TestCase):
    """Nachtrag Phase 2 OpenRouter: Schluessel-Reihenfolge Umgebungsvariable vor
    `scripts\\.env.openrouter`, klare Fehlermeldung ohne Schluessel-Leak bei beidem fehlend."""

    def setUp(self):
        self._datei_alt = chat_bruecke._OPENROUTER_ENV_DATEI
        self._env_alt = os.environ.pop("OPENROUTER_API_KEY", None)

    def tearDown(self):
        chat_bruecke._OPENROUTER_ENV_DATEI = self._datei_alt
        chat_bruecke.schluessel.ZENTRALE_DATEI = chat_bruecke.schluessel.SCRIPTS_DIR / ".env"
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._env_alt is not None:
            os.environ["OPENROUTER_API_KEY"] = self._env_alt

    def test_schluessel_aus_umgebungsvariable_hat_vorrang(self, tmp_path=None):
        os.environ["OPENROUTER_API_KEY"] = "sk-or-aus-env"
        chat_bruecke._OPENROUTER_ENV_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.schluessel.ZENTRALE_DATEI = Path("nicht-vorhanden.env")  # Datei wuerde anders lauten
        env = chat_bruecke._umgebung("openrouter")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-or-aus-env")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")

    def test_schluessel_aus_datei_wenn_keine_umgebungsvariable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / ".env.openrouter"
            datei.write_text("# Kommentar\nOPENROUTER_API_KEY = sk-or-aus-datei \n", encoding="utf-8")
            chat_bruecke._OPENROUTER_ENV_DATEI = datei
            env = chat_bruecke._umgebung("openrouter")
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-or-aus-datei")

    def test_fehlender_schluessel_liefert_klare_fehlermeldung_ohne_leak(self):
        chat_bruecke._OPENROUTER_ENV_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.schluessel.ZENTRALE_DATEI = Path("nicht-vorhanden.env")
        with self.assertRaises(chat_bruecke.OpenRouterSchluesselFehler) as ctx:
            chat_bruecke._umgebung("openrouter")
        self.assertIn(r"scripts\.env.openrouter", str(ctx.exception))

    def test_turn_meldet_fehler_statt_zu_crashen_wenn_schluessel_fehlt(self):
        chat_bruecke._OPENROUTER_ENV_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.schluessel.ZENTRALE_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")  # wird gar nicht erst aufgerufen
        prozess = chat_bruecke.ChatProzess("openrouter", "irgendein-modell")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(len(ereignisse), 1)
        self.assertEqual(ereignisse[0][0], "fehler")
        self.assertIn(r"scripts\.env.openrouter", ereignisse[0][1])
        self.assertNotIn("sk-or", ereignisse[0][1])  # kein Schluessel-Leak
        self.assertIsNone(prozess.proc)  # nie gespawnt


class RequestyUmgebungTest(unittest.TestCase):
    """Nachtrag Phase 2 Requesty: Schluessel-Reihenfolge Umgebungsvariable vor
    `scripts\\.env.requesty`, klare Fehlermeldung ohne Schluessel-Leak bei beidem fehlend --
    Muster `OpenRouterUmgebungTest`."""

    def setUp(self):
        self._datei_alt = chat_bruecke._REQUESTY_ENV_DATEI
        self._env_alt = os.environ.pop("REQUESTY_API_KEY", None)

    def tearDown(self):
        chat_bruecke._REQUESTY_ENV_DATEI = self._datei_alt
        os.environ.pop("REQUESTY_API_KEY", None)
        if self._env_alt is not None:
            os.environ["REQUESTY_API_KEY"] = self._env_alt

    def test_schluessel_aus_umgebungsvariable_hat_vorrang(self):
        os.environ["REQUESTY_API_KEY"] = "rq-aus-env"
        chat_bruecke._REQUESTY_ENV_DATEI = Path("nicht-vorhanden.env")
        env = chat_bruecke._umgebung("requesty")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://router.eu.requesty.ai")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "rq-aus-env")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")

    def test_schluessel_aus_datei_wenn_keine_umgebungsvariable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            datei = Path(tmp) / ".env.requesty"
            datei.write_text("# Kommentar\nREQUESTY_API_KEY = rq-aus-datei \n", encoding="utf-8")
            chat_bruecke._REQUESTY_ENV_DATEI = datei
            env = chat_bruecke._umgebung("requesty")
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "rq-aus-datei")

    def test_fehlender_schluessel_liefert_klare_fehlermeldung_ohne_leak(self):
        chat_bruecke._REQUESTY_ENV_DATEI = Path("nicht-vorhanden.env")
        with self.assertRaises(chat_bruecke.RequestySchluesselFehler) as ctx:
            chat_bruecke._umgebung("requesty")
        self.assertIn(r"scripts\.env.requesty", str(ctx.exception))

    def test_turn_meldet_fehler_statt_zu_crashen_wenn_schluessel_fehlt(self):
        chat_bruecke._REQUESTY_ENV_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")  # wird gar nicht erst aufgerufen
        prozess = chat_bruecke.ChatProzess("requesty", "irgendein-modell")
        ereignisse = list(prozess.turn("Frage?"))
        self.assertEqual(len(ereignisse), 1)
        self.assertEqual(ereignisse[0][0], "fehler")
        self.assertIn(r"scripts\.env.requesty", ereignisse[0][1])
        self.assertNotIn("rq-", ereignisse[0][1])  # kein Schluessel-Leak
        self.assertIsNone(prozess.proc)  # nie gespawnt


class SichtBlockTest(unittest.TestCase):
    """Nachtrag Sichtkontext (2026-08-28, Auftrag "Dashboard-Ansicht ist fuer mich nicht
    sichtbar"): `_sicht_block()`/`_kontext_zeile()` bauen den Block SICHT fuer die erste
    Kindprozess-Nachricht."""

    def _sicht(self, **overrides):
        basis = {
            "ansicht": "start", "zeitraum": {"von": "2026-08-22", "bis": "2026-08-28"},
            "filter": {"projekte": ["Demo"], "quellen": ["Claude"], "kontexte": ["arbeit"]},
            "sitzungen": [{"nr": 666, "zeit": "2026-08-28T09:00", "quelle": "Claude", "projekt": "Demo",
                            "dauer": "12m", "runden": 5, "tools": 20, "fehler": 1, "usd": 0.42,
                            "status": "auffaellig", "auffaelligkeiten": ["rework:tool"]}],
            "sitzung": None, "befund": None,
        }
        basis.update(overrides)
        return basis

    def test_block_traegt_ansicht_zeitraum_filter_und_zeile(self):
        text = chat_bruecke._sicht_block(self._sicht())
        self.assertIn("SICHT:", text)
        self.assertIn("Startseite", text)
        self.assertIn("22.08.-28.08.", text)
        self.assertIn("Projekte Demo", text)
        self.assertIn("666", text)
        self.assertIn("rework:tool", text)
        self.assertIn("1 Sitzung(en) sichtbar", text)

    def test_ansicht_sitzung_zeigt_die_sitzungsnummer(self):
        text = chat_bruecke._sicht_block(self._sicht(ansicht="sitzung", sitzung=137, sitzungen=[]))
        self.assertIn("Sitzung 137", text)

    def test_ohne_sitzungen_bleibt_kompakt_ohne_tabelle(self):
        text = chat_bruecke._sicht_block(self._sicht(sitzungen=[]))
        self.assertNotIn("Nr | Zeit", text)

    def test_kuerzt_erst_die_auffaelligkeiten_spalte_dann_zeilen(self):
        viele = [
            {"nr": n, "zeit": "2026-08-28T09:00", "quelle": "Claude", "projekt": "Demo-Projekt-" + str(n),
             "dauer": "12m", "runden": 5, "tools": 20, "fehler": 1, "usd": 0.42, "status": "auffaellig",
             "auffaelligkeiten": ["rework:tool:Bash", "cost:spike:single", "latency:slow_turn"]}
            for n in range(40)
        ]
        text = chat_bruecke._sicht_block(self._sicht(sitzungen=viele))
        self.assertLessEqual(len(text), chat_bruecke.SICHT_MAX_ZEICHEN + 2)  # +2 fuer die Klammern

    def test_kontext_zeile_haengt_sicht_block_an_ohne_kontext(self):
        zeile = chat_bruecke._kontext_zeile(None, self._sicht())
        self.assertIn("SICHT:", zeile)
        self.assertTrue(zeile.endswith("\n\n"))

    def test_kontext_zeile_traegt_beides_wenn_beides_da_ist(self):
        kontext = {"sitzung_logisch": 512, "signatur": None, "runde": None, "analyse_id": None}
        zeile = chat_bruecke._kontext_zeile(kontext, self._sicht())
        self.assertIn("Sitzung 512", zeile)
        self.assertIn("SICHT:", zeile)

    def test_kontext_zeile_ohne_sicht_bleibt_wie_vorher(self):
        kontext = {"sitzung_logisch": 512, "signatur": None, "runde": None, "analyse_id": None}
        zeile = chat_bruecke._kontext_zeile(kontext)
        self.assertNotIn("SICHT:", zeile)
        self.assertIn("Sitzung 512", zeile)

    def test_ohne_kontext_und_sicht_bleibt_leer(self):
        self.assertEqual(chat_bruecke._kontext_zeile(None), "")
        self.assertEqual(chat_bruecke._kontext_zeile(None, None), "")


class SichtProzessIntegrationTest(unittest.TestCase):
    """`sicht` geht wie `kontext` NUR im ersten Turn an den Kindprozess."""

    def setUp(self):
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        self._prozesse: list[chat_bruecke.ChatProzess] = []

    def tearDown(self):
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt
        for prozess in self._prozesse:
            prozess.beenden()

    def test_sicht_block_nur_im_ersten_turn(self):
        chat_bruecke.KOMMANDO_BAUEN = _kommando("echo")
        sicht = {"ansicht": "start", "sitzungen": [], "sitzung": None, "befund": None}
        prozess = chat_bruecke.ChatProzess("claude", "irrelevant-im-fake", None, sicht)
        self._prozesse.append(prozess)
        erster = list(prozess.turn("Was ist gerade offen?"))[0][1]
        self.assertIn("SICHT: Startseite", erster)
        zweiter = list(prozess.turn("Und jetzt?"))[0][1]
        self.assertEqual(zweiter, "Und jetzt?")


class KindprozessCwdTest(unittest.TestCase):
    """Nachtrag Sichtkontext (2026-08-28): `python -m sitzungsbeleg nachschlagen` loest nur auf,
    wenn der Kindprozess in `scripts/` steht (das Paket ist nicht installiert)."""

    def setUp(self):
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        self._prozesse: list[chat_bruecke.ChatProzess] = []

    def tearDown(self):
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt
        for prozess in self._prozesse:
            prozess.beenden()

    def test_scripts_dir_ist_ordner_ueber_dem_paket(self):
        # Layout-neutral (Host-Workspace: scripts/, Extrakt: Repo-Wurzel): tragend ist allein,
        # dass `python -m sitzungsbeleg` von SCRIPTS_DIR aus aufloest.
        self.assertTrue((chat_bruecke.SCRIPTS_DIR / "sitzungsbeleg" / "__main__.py").is_file())

    def test_kindprozess_startet_mit_scripts_dir_als_arbeitsverzeichnis(self):
        cwd_datei = Path(__file__).resolve().parent / "fake_cwd.py"
        chat_bruecke.KOMMANDO_BAUEN = lambda modell: [sys.executable, str(cwd_datei)]
        prozess = chat_bruecke.ChatProzess("claude", "irrelevant")
        self._prozesse.append(prozess)
        ereignisse = list(prozess.turn("Frage?"))
        gemeldet = [e[1] for e in ereignisse if e[0] == "delta"][0]
        self.assertEqual(Path(gemeldet).resolve(), chat_bruecke.SCRIPTS_DIR.resolve())


class TesteAnbieterTest(unittest.TestCase):
    """`anbieter-test` (CLI, Auftrag Requesty): fasst Umgebungsfehler UND einen erfolgreichen
    Lauf in einem Berichtstext zusammen -- nie ein Absturz."""

    def test_umgebungsfehler_wird_gemeldet(self):
        alt = chat_bruecke._REQUESTY_ENV_DATEI
        chat_bruecke._REQUESTY_ENV_DATEI = Path("nicht-vorhanden.env")
        try:
            bericht = chat_bruecke.teste_anbieter("requesty", "irgendein-modell")
        finally:
            chat_bruecke._REQUESTY_ENV_DATEI = alt
        self.assertIn("Umgebung nicht aufgebaut", bericht)
        self.assertIn(r"scripts\.env.requesty", bericht)

    def setUp(self):
        # _claude_exe sucht die echte CLI -- auf Linux-CI gibt es keine; der Test prueft
        # den Berichtstext, nicht die Installation.
        self._exe_alt = chat_bruecke._claude_exe
        chat_bruecke._claude_exe = lambda: "claude-fake"

    def tearDown(self):
        chat_bruecke._claude_exe = self._exe_alt

    def test_erfolgreicher_lauf_meldet_exitcode_und_ausgabe(self):
        class FakeLauf:
            returncode = 0
            stdout = "ok"
            stderr = ""

        aufrufe = []
        bericht = chat_bruecke.teste_anbieter(
            "claude", "irgendein-modell", laufzeit=lambda *a, **kw: (aufrufe.append((a, kw)), FakeLauf())[1]
        )
        self.assertIn("exit=0", bericht)
        self.assertIn("stdout: ok", bericht)
        self.assertEqual(len(aufrufe), 1)

    def test_startfehler_wird_gemeldet_statt_zu_crashen(self):
        def wirft(*a, **kw):
            raise OSError("claude.exe nicht gefunden")

        bericht = chat_bruecke.teste_anbieter("claude", "irgendein-modell", laufzeit=wirft)
        self.assertIn("Lauf fehlgeschlagen", bericht)

    def test_fehlende_cli_liefert_bericht_statt_absturz(self):
        # Deterministisch statt umgebungsabhaengig: die CLI-Suche wirft (wie auf Linux-CI).
        def fehlt():
            raise chat_bruecke.ChatBrueckeFehler("claude.exe nicht gefunden")
        chat_bruecke._claude_exe = fehlt
        def nie(*a, **kw):
            raise AssertionError("laufzeit darf ohne CLI nicht erreicht werden")
        bericht = chat_bruecke.teste_anbieter("claude", "irgendein-modell", laufzeit=nie)
        self.assertIn("Lauf fehlgeschlagen", bericht)
        self.assertIn("claude.exe nicht gefunden", bericht)


if __name__ == "__main__":
    unittest.main()
