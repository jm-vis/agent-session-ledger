"""Tests fuer chat.py (echte Bruecke) + Chat-Endpunkte (CONTRACTS.md C4/C5, Phase 2 F).

Der Kindprozess ist ueberall `tests/fake_claude.py` (per `chat_bruecke.KOMMANDO_BAUEN`
injiziert) -- kein Mock-Framework, kein echter `claude`/Anthropic-Aufruf noetig."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from .. import chat, chat_bruecke, contracts, redaktion, speicher, web

FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"

KONTEXT_LEER = {"sitzung_logisch": None, "signatur": None, "runde": None, "analyse_id": None}
KONTEXT_SITZUNG = {"sitzung_logisch": 512, "signatur": None, "runde": None, "analyse_id": None}


def _kommando(modus: str):
    return lambda modell: [sys.executable, str(FAKE_CLAUDE), modus]


def _aufraeumen_prozesse() -> None:
    """Kein Hintergrundprozess bleibt nach einem Test uebrig (Auftrag F)."""
    for prozess in chat._PROZESSE.values():
        prozess.beenden()
    chat._PROZESSE.clear()

REGISTRY_FIXTURE = {
    "default_vico_ollama": "glm-5.2:cloud",  # Realitaetstreu (echte modelle.json hat dieses Feld)
    "default_vico_openrouter": "nvidia/nemotron-3-ultra-550b-a55b",  # -- keine Warnung in diesen Tests
    "default_vico_requesty": "sference/kimi-k3",  # -- keine Warnung in diesen Tests
    "preise": {"modelle": {
        "claude-sonnet-5": {"herkunft": "anthropic"},
        "gpt-5.5": {"herkunft": "openai"},
    }},
    "modelle": {
        "glm-5.2:cloud": {"typ": "cloud", "herkunft": "ollama"},
        "qwen3:14b": {"typ": "lokal", "herkunft": "ollama"},
    },
}

# OpenRouter-Fixture (Nachtrag Phase 2, Coordinator-Punkt 2): kein Netz in Tests -- `chat.modelle()`
# ruft seit diesem Nachtrag IMMER auch `_openrouter_modelle()` auf, darum stubben ALLE Tests, die
# `chat.modelle()`/`GET /api/chat/modelle` beruehren, `chat.OPENROUTER_HOLEN` (Muster `_ollama_lauf`).
OPENROUTER_FIXTURE_JSON = json.dumps({"data": [
    {"id": "z-ai/glm-5.2:free", "context_length": 128000},
    {"id": "deepseek/deepseek-chat-v3-0324", "context_length": 164000},
    {"id": "minimax/minimax-m3:free"},
]})


def _openrouter_stub_start() -> tuple:
    """Setzt `chat.OPENROUTER_HOLEN` auf die Fixture und `chat._openrouter_anfrage` auf eine
    feste (url, headers) -- Modellisten-Tests bleiben so unabhaengig von einem echten Schluessel/
    einer echten `scripts\\.env.openrouter` auf der Maschine (die `_openrouter_anfrage()`-Logik
    selbst hat ihre eigenen Tests in `OpenRouterAnfrageTest`). Rueckgabe dient
    `_openrouter_stub_stop()` zum Wiederherstellen (kein Test hinterlaesst Zustand)."""
    alt = (chat.OPENROUTER_HOLEN, chat._openrouter_anfrage, dict(chat._openrouter_cache))
    chat.OPENROUTER_HOLEN = lambda url, headers: OPENROUTER_FIXTURE_JSON
    chat._openrouter_anfrage = lambda: (chat.OPENROUTER_MODELLE_URL, {})
    chat._openrouter_cache["ergebnis"], chat._openrouter_cache["zeit"] = None, 0.0
    return alt


def _openrouter_stub_stop(alt: tuple) -> None:
    chat.OPENROUTER_HOLEN, chat._openrouter_anfrage = alt[0], alt[1]
    chat._openrouter_cache.update(alt[2])


# Requesty-Fixture (Nachtrag Phase 2, 2026-08-28): kein Netz in Tests -- `chat.modelle()` ruft
# seit diesem Nachtrag IMMER auch `_requesty_modelle()` auf, darum stubben ALLE Tests, die
# `chat.modelle()`/`GET /api/chat/modelle` beruehren, `chat.REQUESTY_HOLEN` (Muster OpenRouter).
# EU + kein Training (Default-Filter) nur bei "sference/kimi-k3"; die anderen beiden fallen im
# Default-Filter raus (US-Region bzw. Training erlaubt), tauchen aber mit `alle=True` auf.
REQUESTY_FIXTURE_JSON = json.dumps({"data": [
    {"id": "sference/kimi-k3", "context_window": 262144, "input_price": 0.00000225,
     "output_price": 0.00001125, "geolocation": "eu", "data_used_for_training": False},
    {"id": "sference/glm-5.3-flash", "context_window": 128000, "input_price": 0.0000002,
     "output_price": 0.0000005, "geolocation": "eu", "data_used_for_training": False},
    {"id": "vertex/claude-sonnet-5@us", "context_window": 200000, "input_price": 0.000002,
     "output_price": 0.00001, "geolocation": "us", "data_used_for_training": True},
]})


def _requesty_stub_start() -> tuple:
    alt = (chat.REQUESTY_HOLEN, dict(chat._requesty_cache))
    chat.REQUESTY_HOLEN = lambda: REQUESTY_FIXTURE_JSON
    chat._requesty_cache["roh"], chat._requesty_cache["zeit"] = None, 0.0
    return alt


def _requesty_stub_stop(alt: tuple) -> None:
    chat.REQUESTY_HOLEN = alt[0]
    chat._requesty_cache.update(alt[1])


class SammelLaufer:
    """Sammelt geschriebene SQL-Statements, liefert `[]` fuer jede Abfrage (Fake wie test_web.py)."""

    def __init__(self):
        self.aufrufe: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.aufrufe.append(sql)
        return "[]"


class ModelleTest(unittest.TestCase):
    """C5 GET /api/chat/modelle -- Registry aus Fixture, kein echtes `ollama` noetig."""

    def setUp(self):
        self._registry_alt = chat._registry
        self._ollama_lauf_alt = chat._ollama_lauf
        self._openrouter_alt = _openrouter_stub_start()
        self._requesty_alt = _requesty_stub_start()
        chat._registry = lambda: REGISTRY_FIXTURE

    def tearDown(self):
        chat._registry = self._registry_alt
        chat._ollama_lauf = self._ollama_lauf_alt
        _openrouter_stub_stop(self._openrouter_alt)
        _requesty_stub_stop(self._requesty_alt)

    def test_claude_nur_anthropic_herkunft(self):
        chat._ollama_lauf = lambda *a: ""
        ergebnis = chat.modelle()
        self.assertEqual(ergebnis["claude"], [{"id": "claude-sonnet-5", "name": "claude-sonnet-5"}])

    def test_modelle_traegt_alle_drei_vico_standards(self):
        """Coordinator-Nachtrag (dritte Runde) + Nachtrag Requesty: `ollama_standard`/
        `openrouter_standard`/`requesty_standard` kommen aus `scripts/modelle.json`, nicht aus
        chat.js hartcodiert."""
        chat._ollama_lauf = lambda *a: ""
        ergebnis = chat.modelle()
        self.assertEqual(ergebnis["ollama_standard"], "glm-5.2:cloud")
        self.assertEqual(ergebnis["openrouter_standard"], "nvidia/nemotron-3-ultra-550b-a55b")
        self.assertEqual(ergebnis["requesty_standard"], "sference/kimi-k3")

    def test_requesty_liste_gefiltert_auf_eu_ohne_training(self):
        chat._ollama_lauf = lambda *a: ""
        ergebnis = chat.modelle()
        self.assertEqual(
            ergebnis["requesty"],
            [{"id": "sference/glm-5.3-flash", "kontext": 128000, "preis_in": 0.2, "preis_out": 0.5,
              "region": "eu"},
             {"id": "sference/kimi-k3", "kontext": 262144, "preis_in": 2.25, "preis_out": 11.25,
              "region": "eu"}],
        )
        self.assertNotIn("requesty_hinweis", ergebnis)

    def test_requesty_liste_alle_zeigt_ungefiltert(self):
        chat._ollama_lauf = lambda *a: ""
        ergebnis = chat.modelle(requesty_alle=True)
        ids = [m["id"] for m in ergebnis["requesty"]]
        self.assertIn("vertex/claude-sonnet-5@us", ids)
        self.assertEqual(len(ids), 3)

    def test_ollama_ohne_laufendes_ollama_zeigt_nur_cloud_registry(self):
        chat._ollama_lauf = lambda *a: ""  # simuliert "ollama nicht installiert/erreichbar"
        ergebnis = chat.modelle()
        self.assertEqual(
            ergebnis["ollama"], [{"id": "glm-5.2:cloud", "name": "glm-5.2:cloud", "zustand": "cloud"}]
        )

    def test_ollama_geladen_und_verfuegbar_aus_ps_und_list(self):
        def fake_lauf(*argv):
            if argv[0] == "ps":
                return "NAME\nqwen3:14b\n"
            return "NAME\nqwen3:14b\nmistral:7b\n"

        chat._ollama_lauf = fake_lauf
        zustaende = {z["id"]: z["zustand"] for z in chat.modelle()["ollama"]}
        self.assertEqual(zustaende["qwen3:14b"], "geladen")
        self.assertEqual(zustaende["mistral:7b"], "verfuegbar")
        self.assertEqual(zustaende["glm-5.2:cloud"], "cloud")

    def test_openrouter_liste_aus_fixture_ohne_netz(self):
        chat._ollama_lauf = lambda *a: ""
        ergebnis = chat.modelle()
        self.assertEqual(
            ergebnis["openrouter"],
            [{"id": "deepseek/deepseek-chat-v3-0324", "kontext": 164000},
             {"id": "minimax/minimax-m3:free", "kontext": None},
             {"id": "z-ai/glm-5.2:free", "kontext": 128000}],
        )
        self.assertNotIn("openrouter_hinweis", ergebnis)

    def test_ollama_lauf_liefert_leer_bei_fehlendem_kommando(self):
        def wirft(*a, **kw):
            raise FileNotFoundError("kein ollama installiert")

        alt = chat.subprocess.run
        chat.subprocess.run = wirft
        try:
            self.assertEqual(chat._ollama_lauf("ps"), "")
        finally:
            chat.subprocess.run = alt


class VicoStandardTest(unittest.TestCase):
    """Coordinator-Nachtrag (dritte Runde): EIN Leser (`chat._vico_standard`) fuer
    `default_vico_ollama`/`default_vico_openrouter` aus einer ECHTEN `scripts/modelle.json` auf
    Platte (injizierbarer Pfad `chat.MODELLE_PFAD`, Muster wie `chat_bruecke._OPENROUTER_ENV_DATEI`)
    -- keine Fixture-Lambda hier, sondern die echte Datei-Lese-/Parse-Logik von `_registry()`."""

    def setUp(self):
        self._pfad_alt = chat.MODELLE_PFAD
        self._warnung_alt = dict(chat._VICO_STANDARD_WARNUNG_GEZEIGT)
        chat._VICO_STANDARD_WARNUNG_GEZEIGT["getan"] = False

    def tearDown(self):
        chat.MODELLE_PFAD = self._pfad_alt
        chat._VICO_STANDARD_WARNUNG_GEZEIGT.update(self._warnung_alt)

    def _schreibe_registry(self, tmp: str, inhalt: dict) -> None:
        chat.MODELLE_PFAD = Path(tmp) / "modelle.json"
        chat.MODELLE_PFAD.write_text(json.dumps(inhalt), encoding="utf-8")

    def test_beide_felder_aus_echter_datei_ohne_warnung(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._schreibe_registry(tmp, {"default_vico_ollama": "glm-5.2:cloud",
                                           "default_vico_openrouter": "nvidia/nemotron-3-ultra-550b-a55b"})
            registry = chat._registry()
            puffer = io.StringIO()
            with contextlib.redirect_stdout(puffer):
                ollama = chat._vico_standard(registry, "default_vico_ollama")
                openrouter = chat._vico_standard(registry, "default_vico_openrouter")
        self.assertEqual(ollama, "glm-5.2:cloud")
        self.assertEqual(openrouter, "nvidia/nemotron-3-ultra-550b-a55b")
        self.assertEqual(puffer.getvalue(), "")  # kein Feld fehlt -> keine Warnung

    def test_fehlende_felder_warnen_genau_einmal_fuer_beide(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._schreibe_registry(tmp, {"irrelevant": True})
            registry = chat._registry()
            puffer = io.StringIO()
            with contextlib.redirect_stdout(puffer):
                self.assertIsNone(chat._vico_standard(registry, "default_vico_ollama"))
                self.assertIsNone(chat._vico_standard(registry, "default_vico_openrouter"))
                self.assertIsNone(chat._vico_standard(registry, "default_vico_ollama"))  # dritter Aufruf
        self.assertEqual(puffer.getvalue().count("[chat] modelle.json:"), 1)  # EINE Warnung, nicht drei

    def test_datei_fehlt_liefert_leere_registry_ohne_crash(self):
        chat.MODELLE_PFAD = Path("C:/nicht-vorhanden/modelle.json")
        registry = chat._registry()
        self.assertEqual(registry, {})
        self.assertIsNone(chat._vico_standard(registry, "default_vico_ollama"))

    def test_kaputtes_json_liefert_leere_registry_ohne_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat.MODELLE_PFAD = Path(tmp) / "modelle.json"
            chat.MODELLE_PFAD.write_text("{kaputt", encoding="utf-8")
            self.assertEqual(chat._registry(), {})


class OpenRouterModelleTest(unittest.TestCase):
    """Nachtrag Phase 2 OpenRouter (Coordinator-Punkt 2): Parser + 10-Minuten-Prozesscache,
    kein Netz -- `chat.OPENROUTER_HOLEN` ist injizierbar (Muster `KOMMANDO_BAUEN`)."""

    DUPLIKAT_FIXTURE = json.dumps({"data": [
        {"id": "z-ai/glm-5.2:free", "context_length": 128000},
        {"id": "deepseek/deepseek-chat-v3-0324", "context_length": 164000},
        {"id": "minimax/minimax-m3:free"},  # keine context_length -> kontext None
        {"id": "z-ai/glm-5.2:free", "context_length": 999},  # doppelte id -> ein Eintrag
    ]})

    def setUp(self):
        self._holen_alt = chat.OPENROUTER_HOLEN
        self._anfrage_alt = chat._openrouter_anfrage
        self._cache_alt = dict(chat._openrouter_cache)
        # Parser-/Cache-/Fehler-Tests hier pruefen NICHT die Schluessel-Logik (eigene Klasse
        # OpenRouterAnfrageTest) -- feste (url, headers), unabhaengig von einem echten Schluessel.
        chat._openrouter_anfrage = lambda: (chat.OPENROUTER_MODELLE_URL, {})
        chat._openrouter_cache["ergebnis"], chat._openrouter_cache["zeit"] = None, 0.0

    def tearDown(self):
        chat.OPENROUTER_HOLEN = self._holen_alt
        chat._openrouter_anfrage = self._anfrage_alt
        chat._openrouter_cache.update(self._cache_alt)

    def test_parser_sortiert_dedupliziert_und_traegt_kontext(self):
        eintraege = chat._openrouter_modell_eintraege(self.DUPLIKAT_FIXTURE)
        self.assertEqual(
            [e["id"] for e in eintraege],
            ["deepseek/deepseek-chat-v3-0324", "minimax/minimax-m3:free", "z-ai/glm-5.2:free"],
        )
        by_id = {e["id"]: e["kontext"] for e in eintraege}
        self.assertEqual(by_id["deepseek/deepseek-chat-v3-0324"], 164000)
        self.assertIsNone(by_id["minimax/minimax-m3:free"])

    def test_holen_nur_einmal_dank_zehn_minuten_cache(self):
        aufrufe = []
        chat.OPENROUTER_HOLEN = lambda url, headers: (aufrufe.append(1), OPENROUTER_FIXTURE_JSON)[1]
        chat._openrouter_modelle()
        chat._openrouter_modelle()
        self.assertEqual(len(aufrufe), 1)

    def test_cache_laeuft_ab(self):
        chat.OPENROUTER_HOLEN = lambda url, headers: OPENROUTER_FIXTURE_JSON
        chat._openrouter_modelle()
        chat._openrouter_cache["zeit"] -= chat.OPENROUTER_CACHE_S + 1  # simuliert Ablauf
        aufrufe = []
        chat.OPENROUTER_HOLEN = lambda url, headers: (aufrufe.append(1), OPENROUTER_FIXTURE_JSON)[1]
        chat._openrouter_modelle()
        self.assertEqual(len(aufrufe), 1)

    def test_fehler_liefert_leere_liste_und_hinweis_ohne_crash(self):
        def wirft(url, headers):
            raise OSError("kein Netz")

        chat.OPENROUTER_HOLEN = wirft
        ergebnis, hinweis = chat._openrouter_modelle()
        self.assertEqual(ergebnis, [])
        self.assertIn("OpenRouter-Modelle nicht geladen", hinweis)

    def test_kaputtes_json_liefert_leere_liste_statt_crash(self):
        chat.OPENROUTER_HOLEN = lambda url, headers: "kein json"
        ergebnis, hinweis = chat._openrouter_modelle()
        self.assertEqual(ergebnis, [])
        self.assertTrue(hinweis)


class RequestyModelleTest(unittest.TestCase):
    """Nachtrag Phase 2 Requesty: Parser + Default-Filter (EU, kein Training) + 10-Minuten-
    Prozesscache auf dem ROHEN Fetch, kein Netz -- `chat.REQUESTY_HOLEN` ist injizierbar."""

    def setUp(self):
        self._alt = _requesty_stub_start()

    def tearDown(self):
        _requesty_stub_stop(self._alt)

    def test_parser_filtert_sortiert_und_rechnet_preise_auf_usd_je_million_um(self):
        eintraege = chat._requesty_modell_eintraege(REQUESTY_FIXTURE_JSON, alle=False)
        self.assertEqual([e["id"] for e in eintraege],
                          ["sference/glm-5.3-flash", "sference/kimi-k3"])
        kimi = eintraege[1]
        self.assertEqual(kimi["preis_in"], 2.25)
        self.assertEqual(kimi["preis_out"], 11.25)
        self.assertEqual(kimi["region"], "eu")

    def test_alle_true_ueberspringt_den_filter(self):
        eintraege = chat._requesty_modell_eintraege(REQUESTY_FIXTURE_JSON, alle=True)
        self.assertEqual(len(eintraege), 3)

    def test_holen_nur_einmal_dank_zehn_minuten_cache_unabhaengig_vom_schalter(self):
        aufrufe = []
        chat.REQUESTY_HOLEN = lambda: (aufrufe.append(1), REQUESTY_FIXTURE_JSON)[1]
        chat._requesty_modelle(alle=False)
        chat._requesty_modelle(alle=True)  # anderer Schalter, gleicher gecachter Rohtext
        self.assertEqual(len(aufrufe), 1)

    def test_cache_laeuft_ab(self):
        chat.REQUESTY_HOLEN = lambda: REQUESTY_FIXTURE_JSON
        chat._requesty_modelle()
        chat._requesty_cache["zeit"] -= chat.REQUESTY_CACHE_S + 1
        aufrufe = []
        chat.REQUESTY_HOLEN = lambda: (aufrufe.append(1), REQUESTY_FIXTURE_JSON)[1]
        chat._requesty_modelle()
        self.assertEqual(len(aufrufe), 1)

    def test_fehler_liefert_leere_liste_und_hinweis_ohne_crash(self):
        def wirft():
            raise OSError("kein Netz")

        chat.REQUESTY_HOLEN = wirft
        ergebnis, hinweis = chat._requesty_modelle()
        self.assertEqual(ergebnis, [])
        self.assertIn("Requesty-Modelle nicht geladen", hinweis)

    def test_kaputtes_json_liefert_leere_liste_statt_crash(self):
        chat.REQUESTY_HOLEN = lambda: "kein json"
        ergebnis, hinweis = chat._requesty_modelle()
        self.assertEqual(ergebnis, [])
        self.assertTrue(hinweis)


class OpenRouterAnfrageTest(unittest.TestCase):
    """Coordinator-Nachtrag (Konto-Datenschutzeinstellungen wie ZDR): mit Schluessel
    authentifiziert `/models/user` (zeigt nur, was das Konto tatsaechlich aufrufen kann), ohne
    Schluessel oeffentlich `/models` (ungefiltert). Isoliert von einer echten
    `scripts\\.env.openrouter` auf der Maschine -- zeigt auf einen nicht existenten Pfad."""

    def setUp(self):
        self._datei_alt = chat_bruecke._OPENROUTER_ENV_DATEI
        self._env_alt = os.environ.pop("OPENROUTER_API_KEY", None)
        chat_bruecke._OPENROUTER_ENV_DATEI = Path("nicht-vorhanden.env")
        chat_bruecke.schluessel.ZENTRALE_DATEI = Path("nicht-vorhanden.env")

    def tearDown(self):
        chat_bruecke._OPENROUTER_ENV_DATEI = self._datei_alt
        chat_bruecke.schluessel.ZENTRALE_DATEI = chat_bruecke.schluessel.SCRIPTS_DIR / ".env"
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self._env_alt is not None:
            os.environ["OPENROUTER_API_KEY"] = self._env_alt

    def test_mit_schluessel_authentifizierte_user_url_und_header_vorhanden(self):
        os.environ["OPENROUTER_API_KEY"] = "testwert-ohne-praefix-irrelevant"
        url, headers = chat._openrouter_anfrage()
        self.assertEqual(url, chat.OPENROUTER_MODELLE_USER_URL)
        self.assertIn("Authorization", headers)  # nur Vorhandensein pruefen, nicht den Wert

    def test_ohne_schluessel_oeffentliche_url_ohne_header(self):
        url, headers = chat._openrouter_anfrage()
        self.assertEqual(url, chat.OPENROUTER_MODELLE_URL)
        self.assertNotIn("Authorization", headers)


class GespraechTest(unittest.TestCase):
    """gespraech_starten/senden/strom -- Fake-Laufer statt echtem psql, Fake-Kindprozess statt
    echtem `claude`."""

    def setUp(self):
        chat._GESPRAECHE.clear()
        chat._AUSSTEHEND.clear()
        chat._PROZESSE.clear()
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")

    def tearDown(self):
        _aufraeumen_prozesse()
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt

    def test_gespraech_id_format(self):
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        self.assertRegex(gid, r"^c-\d{8}-\d{4}-[0-9a-f]{4}$")

    def test_senden_schreibt_nur_die_nutzer_zeile(self):
        """Die Assistent-Zeile kommt erst aus `strom()` -- echtes Streaming braucht die
        laufende GET-Antwort, nicht den POST-Handler (Auftrag F)."""
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        laufer = SammelLaufer()
        chat.senden(gid, "Warum lief Runde 11 erst beim dritten Versuch?", laufer=laufer)
        self.assertEqual(len(laufer.aufrufe), 1)
        self.assertTrue(laufer.aufrufe[0].startswith("INSERT INTO chat"))
        self.assertIn('"rolle":"nutzer"', laufer.aufrufe[0])

    def test_senden_ohne_gestartetes_gespraech_wirft(self):
        with self.assertRaises(ValueError):
            chat.senden("c-20260827-1500-a1b2", "Hallo", laufer=SammelLaufer())

    def test_strom_liefert_deltas_dann_ende_und_schreibt_assistent_zeile(self):
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        laufer = SammelLaufer()
        chat.senden(gid, "Kurze Frage", laufer=laufer)
        events = list(chat.strom(gid, laufer=laufer))
        self.assertEqual([e["typ"] for e in events], ["delta", "delta", "ende"])
        for event in events:
            contracts.validiere("sse_event", event)
        self.assertEqual("".join(e["text"] for e in events[:2]), "Hallo, das ist die Fake-Antwort.")
        self.assertEqual(events[-1]["token_in"], 12)
        self.assertEqual(events[-1]["token_out"], 7)
        self.assertEqual(len(laufer.aufrufe), 2)
        self.assertIn('"rolle":"assistent"', laufer.aufrufe[1])

    def test_strom_kindprozess_absturz_liefert_fehler_ohne_assistent_zeile(self):
        chat_bruecke.KOMMANDO_BAUEN = _kommando("crash")
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        laufer = SammelLaufer()
        chat.senden(gid, "Kurze Frage", laufer=laufer)
        events = list(chat.strom(gid, laufer=laufer))
        self.assertEqual(events[-1]["typ"], "fehler")
        self.assertEqual(len(laufer.aufrufe), 1)  # nur die Nutzer-Zeile
        self.assertNotIn(gid, chat._PROZESSE)  # Registry aufgeraeumt (Auftrag F)

    def test_strom_ohne_wartenden_turn_ist_leer(self):
        self.assertEqual(list(chat.strom("c-unbekannt")), [])
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        self.assertEqual(list(chat.strom(gid)), [])  # gestartet, aber noch nichts gesendet

    def test_gespraech_starten_ohne_sicht_speichert_none(self):
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
        self.assertIsNone(chat._GESPRAECHE[gid]["sicht"])

    def test_gespraech_starten_mit_sicht_geht_bis_in_den_kindprozess(self):
        """Sichtkontext (2026-08-28): `sicht` haengt an `_GESPRAECHE` UND landet ueber
        `_prozess_fuer` im `ChatProzess`, der es (wie `kontext`) in der ersten Nachricht sendet."""
        sicht = {"ansicht": "start", "sitzungen": [], "sitzung": None, "befund": None}
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG, sicht=sicht)
        self.assertEqual(chat._GESPRAECHE[gid]["sicht"], sicht)
        laufer = SammelLaufer()
        chat.senden(gid, "Was ist gerade offen?", laufer=laufer)
        events = [e for e in chat.strom(gid, laufer=laufer)]
        self.assertEqual(events[0]["typ"], "delta")
        prozess = chat._PROZESSE[gid]
        self.assertEqual(prozess.sicht, sicht)


class FixUmsetzenTest(unittest.TestCase):
    """"Fix umsetzen" -- NUR ein neutrales Stichwort im Handover, nie Nachrichtentext (DSGVO)."""

    def setUp(self):
        chat._GESPRAECHE.clear()
        self._fenster_alt = chat_bruecke.oeffne_fix_fenster
        self.aufrufe: list[str] = []
        chat_bruecke.oeffne_fix_fenster = lambda handover, starter=None: self.aufrufe.append(handover)

    def tearDown(self):
        chat_bruecke.oeffne_fix_fenster = self._fenster_alt

    def test_handover_traegt_sitzung_und_gespraech_nie_nachrichtentext(self):
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", {**KONTEXT_SITZUNG, "signatur": "rework:tool:Bash"})
        chat.senden(gid, "Geheimer Sitzungsinhalt", laufer=SammelLaufer())
        chat.fix_umsetzen(gid)
        self.assertEqual(len(self.aufrufe), 1)
        self.assertIn("Sitzung 512", self.aufrufe[0])
        self.assertIn("Befund rework:tool:Bash", self.aufrufe[0])
        self.assertIn(f"Chat {gid}", self.aufrufe[0])
        self.assertNotIn("Geheimer", self.aufrufe[0])

    def test_ohne_sitzung_und_signatur_bleibt_nur_die_gespraech_id(self):
        gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_LEER)
        chat.fix_umsetzen(gid)
        self.assertEqual(self.aufrufe[0], f"Chat {gid}")

    def test_unbekanntes_gespraech_wirft(self):
        with self.assertRaises(ValueError):
            chat.fix_umsetzen("c-unbekannt")


class SpeicherChatTest(unittest.TestCase):
    """speicher.chat_schreiben/chat_lesen (Kontrakt C4/C8)."""

    def test_chat_schreiben_validiert_und_schreibt(self):
        laufer = SammelLaufer()
        speicher.chat_schreiben(json.loads(json.dumps(contracts.BEISPIELE["chat_nachricht"])), laufer=laufer)
        self.assertEqual(len(laufer.aufrufe), 1)
        self.assertTrue(laufer.aufrufe[0].startswith("INSERT INTO chat"))

    def test_chat_schreiben_verstoss_schreibt_nichts(self):
        laufer = SammelLaufer()
        detail = {**json.loads(json.dumps(contracts.BEISPIELE["chat_nachricht"])), "schutz": "lokal"}
        with self.assertRaises(contracts.ContractFehler):
            speicher.chat_schreiben(detail, laufer=laufer)
        self.assertEqual(len(laufer.aufrufe), 0)

    def test_chat_lesen_liest_zeilen(self):
        gespeichert = [contracts.BEISPIELE["chat_nachricht"]]
        ergebnis = speicher.chat_lesen(
            "c-20260827-1500-a1b2", laufer=lambda sql, zeitlimit_s=8: json.dumps(gespeichert)
        )
        self.assertEqual(ergebnis, gespeichert)

    def test_chat_lesen_leer(self):
        self.assertEqual(speicher.chat_lesen("c-x", laufer=lambda sql, zeitlimit_s=8: "[]"), [])


class ChatEndpunkteTest(unittest.TestCase):
    """C5 Endpunkte mit TestClient, Fake-Laufer statt echtem psql/Docker."""

    def setUp(self):
        self._laufer_alt = web.LAUFER
        self._registry_alt = chat._registry
        self._ollama_lauf_alt = chat._ollama_lauf
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        self._openrouter_alt = _openrouter_stub_start()
        self._requesty_alt = _requesty_stub_start()
        chat._GESPRAECHE.clear()
        chat._AUSSTEHEND.clear()
        chat._PROZESSE.clear()
        chat._registry = lambda: REGISTRY_FIXTURE
        chat._ollama_lauf = lambda *a: ""
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")
        self.client = TestClient(web.app)

    def tearDown(self):
        _aufraeumen_prozesse()
        web.LAUFER = self._laufer_alt
        chat._registry = self._registry_alt
        chat._ollama_lauf = self._ollama_lauf_alt
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt
        _openrouter_stub_stop(self._openrouter_alt)
        _requesty_stub_stop(self._requesty_alt)

    def test_get_modelle(self):
        antwort = self.client.get("/api/chat/modelle")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json()["claude"], [{"id": "claude-sonnet-5", "name": "claude-sonnet-5"}])
        self.assertEqual(antwort.json()["openrouter"][0]["id"], "deepseek/deepseek-chat-v3-0324")
        self.assertEqual(antwort.json()["requesty"][0]["id"], "sference/glm-5.3-flash")

    def test_get_modelle_alle_true_gibt_query_param_an_chat_weiter(self):
        antwort = self.client.get("/api/chat/modelle", params={"alle": "true"})
        ids = [m["id"] for m in antwort.json()["requesty"]]
        self.assertIn("vertex/claude-sonnet-5@us", ids)

    def test_post_neues_gespraech_dann_strom(self):
        web.LAUFER = SammelLaufer()
        body = {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5",
            "text": "Frage?", "kontext": KONTEXT_SITZUNG,
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)
        gid = antwort.json()["gespraech_id"]
        self.assertRegex(gid, r"^c-\d{8}-\d{4}-[0-9a-f]{4}$")

        strom = self.client.get(f"/api/chat/{gid}/strom")
        self.assertEqual(strom.status_code, 200)
        self.assertIn("text/event-stream", strom.headers["content-type"])
        bloecke = [b for b in strom.text.split("\n\n") if b.strip()]
        self.assertEqual(len(bloecke), 3)  # 2 Deltas (Fake-Antwort) + ende
        letzter = json.loads(bloecke[-1].removeprefix("data: "))
        self.assertEqual(letzter["typ"], "ende")

    def test_post_423_bei_claude_und_geschuetzter_sitzung(self):
        body = {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5",
            "text": "Frage?", "kontext": KONTEXT_LEER, "schutz": "geschuetzt",
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 423)

    def test_post_ollama_bei_geschuetzter_sitzung_bleibt_erlaubt(self):
        web.LAUFER = SammelLaufer()
        body = {
            "gespraech_id": None, "anbieter": "ollama", "modell": "glm-5.2:cloud",
            "text": "Frage?", "kontext": KONTEXT_LEER, "schutz": "geschuetzt",
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)

    def test_post_423_bei_openrouter_und_geschuetzter_sitzung(self):
        """OpenRouter ist wie Claude ein Cloud-Anbieter (C6, Nachtrag Phase 2)."""
        body = {
            "gespraech_id": None, "anbieter": "openrouter", "modell": "deepseek/deepseek-chat-v3-0324",
            "text": "Frage?", "kontext": KONTEXT_LEER, "schutz": "geschuetzt",
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 423)

    def test_post_openrouter_normal_erlaubt(self):
        web.LAUFER = SammelLaufer()
        body = {
            "gespraech_id": None, "anbieter": "openrouter", "modell": "deepseek/deepseek-chat-v3-0324",
            "text": "Frage?", "kontext": KONTEXT_SITZUNG,
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)

    def test_post_423_bei_requesty_und_geschuetzter_sitzung(self):
        """Requesty ist wie Claude/OpenRouter ein Cloud-Anbieter (C6, Nachtrag Requesty)."""
        body = {
            "gespraech_id": None, "anbieter": "requesty", "modell": "sference/kimi-k3",
            "text": "Frage?", "kontext": KONTEXT_LEER, "schutz": "geschuetzt",
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 423)

    def test_post_requesty_normal_erlaubt(self):
        web.LAUFER = SammelLaufer()
        body = {
            "gespraech_id": None, "anbieter": "requesty", "modell": "sference/kimi-k3",
            "text": "Frage?", "kontext": KONTEXT_SITZUNG,
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)

    def test_get_gespraech_404_ohne_nachrichten(self):
        web.LAUFER = SammelLaufer()
        antwort = self.client.get("/api/chat/c-unbekannt")
        self.assertEqual(antwort.status_code, 404)

    def test_get_gespraech_liefert_nachrichten(self):
        nachricht = contracts.BEISPIELE["chat_nachricht"]

        def laufer(sql, zeitlimit_s=8):
            if "FROM chat WHERE gespraech_id" in sql:
                return json.dumps([nachricht])
            return "[]"

        web.LAUFER = laufer
        antwort = self.client.get("/api/chat/c-20260827-1500-a1b2")
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(daten["anbieter"], "claude")
        self.assertEqual(len(daten["nachrichten"]), 1)

    def test_post_fix_202_und_oeffnet_fenster(self):
        aufrufe = []
        alt = chat_bruecke.oeffne_fix_fenster
        chat_bruecke.oeffne_fix_fenster = lambda handover, starter=None: aufrufe.append(handover)
        try:
            gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
            antwort = self.client.post(f"/api/chat/{gid}/fix")
        finally:
            chat_bruecke.oeffne_fix_fenster = alt
        self.assertEqual(antwort.status_code, 202)
        self.assertEqual(len(aufrufe), 1)
        self.assertIn("Sitzung 512", aufrufe[0])

    def test_post_fix_404_bei_unbekanntem_gespraech(self):
        antwort = self.client.post("/api/chat/c-unbekannt/fix")
        self.assertEqual(antwort.status_code, 404)

    def test_post_fix_500_bei_fensterfehler(self):
        alt = chat_bruecke.oeffne_fix_fenster

        def wirft(handover, starter=None):
            raise OSError("powershell.exe nicht gefunden")

        chat_bruecke.oeffne_fix_fenster = wirft
        try:
            gid = chat.gespraech_starten("claude", "claude-sonnet-5", KONTEXT_SITZUNG)
            antwort = self.client.post(f"/api/chat/{gid}/fix")
        finally:
            chat_bruecke.oeffne_fix_fenster = alt
        self.assertEqual(antwort.status_code, 500)
        self.assertIn("detail", antwort.json())


SICHT_GUELTIG = {
    "ansicht": "start", "zeitraum": {"von": "2026-08-22", "bis": "2026-08-28"},
    "filter": {"projekte": ["Demo"], "quellen": ["Claude"], "kontexte": ["arbeit"]},
    "sitzungen": [{"nr": 666, "zeit": "2026-08-28T09:00", "quelle": "Claude", "projekt": "Demo",
                    "dauer": "12m", "runden": 5, "tools": 20, "fehler": 1, "usd": 0.42,
                    "status": "auffaellig", "auffaelligkeiten": ["rework:tool"]}],
    "sitzung": None, "befund": None,
}


class SichtEndpunktTest(unittest.TestCase):
    """Nachtrag Sichtkontext (2026-08-28): `POST /api/chat` validiert/redigiert `sicht`
    (`contracts.Sicht`) und haengt es an das Gespraech, bevor der Kindprozess startet."""

    def setUp(self):
        self._laufer_alt = web.LAUFER
        self._kommando_alt = chat_bruecke.KOMMANDO_BAUEN
        chat._GESPRAECHE.clear()
        chat._AUSSTEHEND.clear()
        chat._PROZESSE.clear()
        chat_bruecke.KOMMANDO_BAUEN = _kommando("normal")
        web.LAUFER = SammelLaufer()
        self.client = TestClient(web.app)

    def tearDown(self):
        _aufraeumen_prozesse()
        web.LAUFER = self._laufer_alt
        chat_bruecke.KOMMANDO_BAUEN = self._kommando_alt

    def _body(self, sicht):
        return {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5",
            "text": "Was ist mit Sitzung 666?", "kontext": KONTEXT_LEER, "sicht": sicht,
        }

    def test_gueltige_sicht_wird_am_gespraech_gespeichert(self):
        antwort = self.client.post("/api/chat", json=self._body(SICHT_GUELTIG))
        self.assertEqual(antwort.status_code, 202)
        gid = antwort.json()["gespraech_id"]
        self.assertEqual(chat._GESPRAECHE[gid]["sicht"]["ansicht"], "start")
        self.assertEqual(chat._GESPRAECHE[gid]["sicht"]["sitzungen"][0]["nr"], 666)

    def test_ungueltige_ansicht_gibt_400(self):
        kaputt = {**SICHT_GUELTIG, "ansicht": "querschnitt"}
        antwort = self.client.post("/api/chat", json=self._body(kaputt))
        self.assertEqual(antwort.status_code, 400)

    def test_zu_viele_sitzungen_gibt_400(self):
        kaputt = {**SICHT_GUELTIG, "sitzungen": SICHT_GUELTIG["sitzungen"] * 31}
        antwort = self.client.post("/api/chat", json=self._body(kaputt))
        self.assertEqual(antwort.status_code, 400)

    def test_ohne_sicht_bleibt_gespraech_ohne_sicht(self):
        antwort = self.client.post("/api/chat", json=self._body(None))
        gid = antwort.json()["gespraech_id"]
        self.assertIsNone(chat._GESPRAECHE[gid]["sicht"])

    def test_secret_in_sicht_wird_redigiert(self):
        """Zweites Netz (Nachtrag): die Werte sind bereits redigierte Anzeige-Information, aber
        `chat.sicht_bereinigt()` laesst trotzdem jedes String-Feld durch `bereinige_text()`."""
        verseucht = {**SICHT_GUELTIG, "filter": {**SICHT_GUELTIG["filter"], "projekte": ["sk-abcdefghijklmnop"]}}
        antwort = self.client.post("/api/chat", json=self._body(verseucht))
        self.assertEqual(antwort.status_code, 202)
        gid = antwort.json()["gespraech_id"]
        self.assertEqual(chat._GESPRAECHE[gid]["sicht"]["filter"]["projekte"], [redaktion.REDIGIERT])


if __name__ == "__main__":
    unittest.main()
