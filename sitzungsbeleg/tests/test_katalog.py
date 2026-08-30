"""Modellkatalog-Beschaffung (CONTRACTS.md C15, Paket L). Kein Netz/keine echte DB: Parser
laufen gegen inline-JSON-Dicts (Muster `test_chat.py` OPENROUTER_FIXTURE_JSON/REQUESTY_FIXTURE_JSON),
der Upsert gegen einen Fake-`psql`-Laufer (Muster `test_speicher_sequence.py` FakePsql)."""
from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from datetime import date

from pydantic import ValidationError

from .. import katalog, speicher


class FakePsql:
    def __init__(self, antworten: list[str]):
        self.antworten = list(antworten)
        self.sql: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.sql.append(sql)
        return self.antworten.pop(0) if self.antworten else ""


# Registry-Fixture (Muster test_chat.py._REGISTRY): zwei anthropic-, zwei ollama-Preiszeilen
# (eine davon ohne `stand`, faellt auf `preise.stand` zurueck) plus der Ollama-Bestand mit echten
# Kontextfenstern (Bruecke preise-Schluessel -> Ollama-Name mit Tag, s. `_kontext_lookup`).
REGISTRY = {
    "preise": {
        "stand": "2026-08-20",
        "modelle": {
            "claude-sonnet-5": {"input": 2, "output": 10, "herkunft": "anthropic", "stand": "2026-08-25"},
            "claude-opus-5": {"input": 5, "output": 25, "herkunft": "anthropic"},
            "glm-5.2": {"input": 1.19, "output": 3.74, "herkunft": "ollama",
                        "quelle": "OpenRouter-Listenpreis z-ai/glm-5.2", "stand": "2026-08-27"},
            "minimax-m3": {"input": 0.3, "output": 1.2, "herkunft": "ollama"},
            "gpt-5.5": {"input": 5, "output": 30, "herkunft": "openai"},  # andere Quelle -> nie in claude/ollama
        },
    },
    "modelle": {
        "glm-5.2:cloud": {"typ": "cloud", "herkunft": "ollama", "kontext": 1048576},
        "minimax-m3:cloud": {"typ": "cloud", "herkunft": "ollama", "kontext": 524288},
    },
}

OPENROUTER_FIXTURE = {"data": [
    {"id": "z-ai/glm-5.2:free", "context_length": 128000,
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b", "context_length": 262144,
     "pricing": {"prompt": "0.0000006", "completion": "0.0000036"}},
    {"id": "kaputt-ohne-preis"},  # kein "pricing" -- muss trotzdem eine Zeile ergeben (Preise NULL)
    {"nur_name": "kein id-Feld"},  # wird uebersprungen
]}

REQUESTY_FIXTURE = {"data": [
    {"id": "sference/kimi-k3", "context_window": 262144,
     "input_price": 0.00000225, "output_price": 0.00001125},
    {"id": "sference/glm-5.3-flash", "context_window": 128000,
     "input_price": 0.0000002, "output_price": 0.0000005},
]}

# Ollama-Fixture (Nachtrag: Live-`/api/tags`-Basisquelle), Auszug im echten Antwort-Shape --
# zwei Cloud-Modelle (`:cloud`-Suffix), ein lokales (`:9b`) und eines ohne "details" (Kontext
# muss NULL bleiben statt abzustuerzen).
OLLAMA_TAGS_FIXTURE = {"models": [
    {"name": "glm-5.3:cloud", "details": {"context_length": 1048576, "parameter_size": "753B"}},
    {"name": "kimi-k3:cloud", "details": {"context_length": 1048576, "parameter_size": "2.81T"}},
    {"name": "qwen3.5:9b", "details": {"context_length": 32768, "parameter_size": "9.15B"}},
    {"name": "kein-details"},
]}

# AA-Fixture (C15 v2 Punkt 1): ein Modell mit allen vier Werten inkl. tau2 (slug UND name
# normieren auf ZWEI verschiedene Schluessel -- beide muessen im Mapping landen), eines mit
# lauter NULL-Werten (kaputte/fehlende `evaluations`), ein Eintrag ganz ohne slug/name
# (unbrauchbar, zaehlt als uebersprungen).
ARTIFICIALANALYSIS_FIXTURE = {"data": [
    {"slug": "glm-5-3-flash", "name": "ChatGLM Flash 5.3",
     "evaluations": {"artificial_analysis_intelligence_index": 54.3,
                      "artificial_analysis_coding_index": 61.8, "tau2": 0.472},
     "median_output_tokens_per_second": 118.4},
    {"slug": "uraltes-modell", "name": "Uraltes Modell", "evaluations": None,
     "median_output_tokens_per_second": None},
    {"evaluations": {"artificial_analysis_intelligence_index": 99}},  # kein slug/name -- kaputt
]}


class KurznameTest(unittest.TestCase):
    def test_praefix_und_lowercase(self) -> None:
        self.assertEqual(katalog.kurzname("anthropic/Claude-Fable-5"), "claude-fable-5")
        self.assertEqual(katalog.kurzname("claude-fable-5"), "claude-fable-5")

    def test_bezugsvarianten_werden_gekappt(self) -> None:
        """@region und :flex/:batch/:free sind Bezugswege, keine Modelle (Maintainer 2026-08-28)."""
        self.assertEqual(katalog.kurzname("gpt-5.4@eastus2"), "gpt-5.4")
        self.assertEqual(katalog.kurzname("vertex/claude-opus-5@eu-west-3"), "claude-opus-5")
        self.assertEqual(katalog.kurzname("glm-5.3-flash:batch"), "glm-5.3-flash")
        self.assertEqual(katalog.kurzname("openai/gpt-5.4:flex"), "gpt-5.4")
        self.assertEqual(katalog.kurzname("laguna-s-2.1:free"), "laguna-s-2.1")

    def test_ollama_tags_bleiben_eigene_modelle(self) -> None:
        """`:cloud`/`:14b` sind ECHTE Varianten (Groesse/Bezug) -- nie kappen."""
        self.assertEqual(katalog.kurzname("glm-5.2:cloud"), "glm-5.2:cloud")
        self.assertEqual(katalog.kurzname("qwen3:14b"), "qwen3:14b")

    def test_hf_co_id_behaelt_vollen_pfad_org_geht_nicht_verloren(self) -> None:
        """Entscheid 2026-08-30 D: `anzeige_kurzform()` darf bei hf.co-IDs NICHT wie sonst
        nur den Teil nach dem letzten '/' nehmen -- die Organisation (2. Pfadsegment) wird sonst
        fuer die Panel-/Tabellen-Kurzform `format.js:modellAnzeigeName()` unwiederbringlich
        verworfen."""
        roh = "hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M"
        self.assertEqual(katalog.anzeige_kurzform(roh), roh)
        self.assertEqual(katalog.kurzname(roh), roh.lower())


class HerstellerHerkunftTest(unittest.TestCase):
    def test_slug_direkter_treffer(self) -> None:
        self.assertEqual(katalog.hersteller_und_herkunft("z-ai/glm-5.2:free"), ("Zhipu AI", "CN"))
        self.assertEqual(katalog.hersteller_und_herkunft("nvidia/nemotron-3-ultra-550b-a55b"),
                          ("Nvidia", "US"))

    def test_requesty_reseller_slug_faellt_auf_teilstring_zurueck(self) -> None:
        """`sference` ist kein Hersteller -- der echte Hersteller steckt im Modellnamen."""
        self.assertEqual(katalog.hersteller_und_herkunft("sference/kimi-k3"), ("Moonshot AI", "CN"))

    def test_ollama_name_ohne_slash(self) -> None:
        self.assertEqual(katalog.hersteller_und_herkunft("glm-5.2"), ("Zhipu AI", "CN"))
        self.assertEqual(katalog.hersteller_und_herkunft("minimax-m3"), ("MiniMax", "CN"))

    def test_claude_modelle_matchen_anthropic(self) -> None:
        self.assertEqual(katalog.hersteller_und_herkunft("claude-sonnet-5"), ("Anthropic", "US"))

    def test_unbekannt_bleibt_herkunft_none(self) -> None:
        hersteller, herkunft = katalog.hersteller_und_herkunft("acme/uraltes-modell")
        self.assertEqual(hersteller, "Acme")
        self.assertIsNone(herkunft)

    def test_reseller_praefix_wird_uebersprungen(self) -> None:
        """`azure`/`bedrock` sind Hoster, kein Hersteller (Nachtrag 2026-08-28) --
        die Erkennung laeuft auf dem Rest der ID weiter."""
        self.assertEqual(katalog.hersteller_und_herkunft("azure/gpt-5"), ("OpenAI", "US"))
        self.assertEqual(katalog.hersteller_und_herkunft("bedrock/claude-opus-5"), ("Anthropic", "US"))
        self.assertEqual(katalog.hersteller_und_herkunft("deepinfra/qwen3-max"), ("Alibaba", "CN"))

    def test_nachgetragene_hersteller(self) -> None:
        self.assertEqual(katalog.hersteller_und_herkunft("aion-labs/aion-2.0"), ("AionLabs", "IL"))
        self.assertEqual(katalog.hersteller_und_herkunft("sakana/tinyswallow"), ("Sakana AI", "JP"))
        self.assertEqual(katalog.hersteller_und_herkunft("upstage/solar-pro-3"), ("Upstage", "KR"))
        self.assertEqual(katalog.hersteller_und_herkunft("tencent/hunyuan-a13b"), ("Tencent", "CN"))

    def test_nachgetragene_hersteller_eurollm_und_nomic(self) -> None:
        """Abnahme 2026-08-30 (Fix 4): die zwei einzigen NULL-Herkunft-IDs im Live-Katalog."""
        hersteller, herkunft = katalog.hersteller_und_herkunft(
            "hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q4_K_M")
        self.assertEqual((hersteller, herkunft), ("Unbabel", "EU"))
        self.assertEqual(katalog.hersteller_und_herkunft("nomic-embed-text:latest"),
                          ("Nomic AI", "US"))

    def test_community_finetuner_basismodell_herkunft(self) -> None:
        """Regel 2026-08-28: pseudonyme Finetuner tragen die Basismodell-Herkunft
        (Recherche-Runde 3, Modellkarten verifiziert), nie mehr NULL."""
        self.assertEqual(katalog.hersteller_und_herkunft("thedrummer/rocinante-12b")[1], "EU")
        self.assertEqual(katalog.hersteller_und_herkunft("sao10k/l3-euryale-70b")[1], "US")
        self.assertEqual(katalog.hersteller_und_herkunft("gryphe/mythomax-l2-13b")[1], "US")
        self.assertEqual(katalog.hersteller_und_herkunft("undi95/remm-slerp-l2-13b")[1], "US")
        self.assertEqual(katalog.hersteller_und_herkunft("anthracite-org/magnum-v4-72b")[1], "CN")


class ParseOpenrouterTest(unittest.TestCase):
    def test_router_pseudoeintraege_werden_uebersprungen(self) -> None:
        """`openrouter/auto`/`openrouter/free` sind Router, keine Modelle (wie `~`-Aliasse)."""
        daten = {"data": [{"id": "openrouter/free", "context_length": 8000, "pricing": {}},
                           {"id": "openrouter/auto", "context_length": 8000, "pricing": {}}]}
        self.assertEqual(katalog.parse_openrouter(daten), [])

    def test_zeilen_und_preisumrechnung(self) -> None:
        zeilen = katalog.parse_openrouter(OPENROUTER_FIXTURE)
        self.assertEqual(len(zeilen), 3)  # der Eintrag ohne "id" faellt raus
        nemotron = next(z for z in zeilen if z.modell_id == "nvidia/nemotron-3-ultra-550b-a55b")
        self.assertEqual(nemotron.anbieter, "openrouter")
        self.assertEqual(nemotron.hersteller, "Nvidia")
        self.assertEqual(nemotron.herkunft, "US")
        self.assertEqual(nemotron.kontext_k, 262)
        self.assertEqual(nemotron.eingabe_usd, 0.6)
        self.assertEqual(nemotron.ausgabe_usd, 3.6)
        self.assertEqual(nemotron.stand, date.today())

    def test_fehlendes_pricing_wird_null_nicht_absturz(self) -> None:
        zeile = next(z for z in katalog.parse_openrouter(OPENROUTER_FIXTURE)
                     if z.modell_id == "kaputt-ohne-preis")
        self.assertIsNone(zeile.eingabe_usd)
        self.assertIsNone(zeile.ausgabe_usd)


class ParseOpenrouterVisionTest(unittest.TestCase):
    """`vision` aus `architecture.input_modalities` (Entscheid 2026-08-30 Nachtrag 6) --
    OpenRouter liefert das Feld schon in der geholten Antwort, kein Zusatz-Request noetig."""

    def test_image_in_modalitaeten_ist_vision_true(self) -> None:
        daten = {"data": [{"id": "x/bild-modell", "pricing": {},
                            "architecture": {"input_modalities": ["text", "image"]}}]}
        [zeile] = katalog.parse_openrouter(daten)
        self.assertTrue(zeile.vision)

    def test_ohne_image_ist_vision_false(self) -> None:
        daten = {"data": [{"id": "x/text-modell", "pricing": {},
                            "architecture": {"input_modalities": ["text"]}}]}
        [zeile] = katalog.parse_openrouter(daten)
        self.assertFalse(zeile.vision)

    def test_fehlende_architecture_bleibt_vision_none(self) -> None:
        daten = {"data": [{"id": "x/ohne-architektur", "pricing": {}}]}
        [zeile] = katalog.parse_openrouter(daten)
        self.assertIsNone(zeile.vision)


class HerkunftUnbekanntWarnungTest(unittest.TestCase):
    """Abnahme 2026-08-30 (Fix 4): Beschaffung soll unbekannte Herkunft laut auf stderr
    melden, statt still im Katalog zu versickern."""

    def test_parse_openrouter_loggt_unbekannte_herkunft(self) -> None:
        daten = {"data": [{"id": "acme/uraltes-modell", "context_length": 8000,
                            "pricing": {"prompt": "0", "completion": "0"}}]}
        fehlerausgabe = io.StringIO()
        with contextlib.redirect_stderr(fehlerausgabe):
            katalog.parse_openrouter(daten)
        self.assertIn("Herkunft unbekannt: acme/uraltes-modell", fehlerausgabe.getvalue())

    def test_bekannte_herkunft_loggt_nicht(self) -> None:
        daten = {"data": [{"id": "z-ai/glm-5.2", "context_length": 8000,
                            "pricing": {"prompt": "0", "completion": "0"}}]}
        fehlerausgabe = io.StringIO()
        with contextlib.redirect_stderr(fehlerausgabe):
            katalog.parse_openrouter(daten)
        self.assertNotIn("Herkunft unbekannt", fehlerausgabe.getvalue())


class ParseRequestyTest(unittest.TestCase):
    def test_zeilen_und_preisumrechnung(self) -> None:
        zeilen = katalog.parse_requesty(REQUESTY_FIXTURE)
        self.assertEqual(len(zeilen), 2)
        kimi = next(z for z in zeilen if z.modell_id == "sference/kimi-k3")
        self.assertEqual(kimi.anbieter, "requesty")
        self.assertEqual(kimi.hersteller, "Moonshot AI")
        self.assertEqual(kimi.kontext_k, 262)
        self.assertEqual(kimi.eingabe_usd, 2.25)
        self.assertEqual(kimi.ausgabe_usd, 11.25)


class IstOllamaCloudTest(unittest.TestCase):
    """Cloud- vs. Lokal-Erkennung (Nachtrag): einzige Quelle der Wahrheit, geteilt mit
    `katalog_sicht._ist_lokal`."""

    def test_cloud_suffix_gross_und_kleinschreibung(self) -> None:
        self.assertTrue(katalog.ist_ollama_cloud("glm-5.3:cloud"))
        self.assertTrue(katalog.ist_ollama_cloud("KIMI-K3:CLOUD"))

    def test_lokale_tags_sind_kein_cloud(self) -> None:
        self.assertFalse(katalog.ist_ollama_cloud("qwen3.5:9b"))
        self.assertFalse(katalog.ist_ollama_cloud("qwen3:14b"))
        self.assertFalse(katalog.ist_ollama_cloud("nomic-embed-text"))

    def test_dash_cloud_suffix_ohne_doppelpunkt(self) -> None:
        """Befund 2026-08-30 (Fix 1): Ollama haengt Cloud-Modelle auch als
        `<basis>:<groesse>-cloud` an, ohne eigenes `:cloud`-Tag."""
        self.assertTrue(katalog.ist_ollama_cloud("gpt-oss:20b-cloud"))
        self.assertTrue(katalog.ist_ollama_cloud("gemma4:31b-cloud"))
        self.assertTrue(katalog.ist_ollama_cloud("qwen3-vl:235b-cloud"))
        self.assertTrue(katalog.ist_ollama_cloud("mistral-large-3:675b-cloud"))
        self.assertTrue(katalog.ist_ollama_cloud("MISTRAL-LARGE-3:675B-CLOUD"))


class ParseOllamaTagsTest(unittest.TestCase):
    def test_zeilen_und_kontext(self) -> None:
        zeilen = katalog.parse_ollama_tags(OLLAMA_TAGS_FIXTURE)
        self.assertEqual(len(zeilen), 4)
        glm = next(z for z in zeilen if z.modell_id == "glm-5.3:cloud")
        self.assertEqual(glm.anbieter, "ollama")
        self.assertEqual(glm.hersteller, "Zhipu AI")
        self.assertEqual(glm.herkunft, "CN")
        self.assertEqual(glm.kontext_k, 1049)  # 1048576 / 1000, gerundet
        self.assertIsNone(glm.eingabe_usd)  # Preis kommt erst aus der Anreicherung
        self.assertEqual(glm.stand, date.today())
        self.assertEqual(glm.quelle, katalog.OLLAMA_TAGS_URL)
        self.assertFalse(glm.lokal)  # ':cloud' -- Fix 2, an der ROHEN Ollama-ID gesetzt

    def test_lokal_feld_je_zeile_aus_der_rohen_ollama_id(self) -> None:
        """Befund 2026-08-30 (Fix 2): `lokal` wird BEI DER BESCHAFFUNG gesetzt, nicht erst
        in der Sicht -- muss fuer jede Zeile unabhaengig stimmen."""
        zeilen = {z.modell_id: z.lokal for z in katalog.parse_ollama_tags(OLLAMA_TAGS_FIXTURE)}
        self.assertEqual(zeilen, {"glm-5.3:cloud": False, "kimi-k3:cloud": False,
                                   "qwen3.5:9b": True, "kein-details": True})

    def test_fehlende_details_liefert_kontext_none_nicht_absturz(self) -> None:
        zeile = next(z for z in katalog.parse_ollama_tags(OLLAMA_TAGS_FIXTURE)
                     if z.modell_id == "kein-details")
        self.assertIsNone(zeile.kontext_k)

    def test_eintrag_ohne_name_wird_uebersprungen(self) -> None:
        daten = {"models": [{"details": {"context_length": 8000}}, {"name": ""}]}
        self.assertEqual(katalog.parse_ollama_tags(daten), [])

    def test_cloud_vs_lokal_ueber_modell_id(self) -> None:
        zeilen = katalog.parse_ollama_tags(OLLAMA_TAGS_FIXTURE)
        cloud = {z.modell_id for z in zeilen if katalog.ist_ollama_cloud(z.modell_id)}
        self.assertEqual(cloud, {"glm-5.3:cloud", "kimi-k3:cloud"})


class OllamaVisionTest(unittest.TestCase):
    """`ollama_vision()` (Entscheid 2026-08-30 Nachtrag 6): `capabilities` aus `/api/show`,
    prozessweit gecacht -- `parse_ollama_tags` bleibt bewusst netzwerkfrei (Moduldoc), die
    Anreicherung passiert separat wie bei den Preisen (`_ollama_anreichern`)."""

    def setUp(self) -> None:
        self._alt = katalog.OLLAMA_SHOW_HOLEN
        katalog._OLLAMA_VISION_CACHE.clear()

    def tearDown(self) -> None:
        katalog.OLLAMA_SHOW_HOLEN = self._alt
        katalog._OLLAMA_VISION_CACHE.clear()

    def test_vision_in_capabilities_ist_true(self) -> None:
        katalog.OLLAMA_SHOW_HOLEN = lambda modell_id: {"capabilities": ["completion", "vision"]}
        self.assertTrue(katalog.ollama_vision("qwen3-vl:235b-cloud"))

    def test_ohne_vision_in_capabilities_ist_false(self) -> None:
        katalog.OLLAMA_SHOW_HOLEN = lambda modell_id: {"capabilities": ["completion"]}
        self.assertFalse(katalog.ollama_vision("glm-5.3:cloud"))

    def test_netzfehler_liefert_none_kein_absturz(self) -> None:
        def kaputt(modell_id):
            raise OSError("offline")

        katalog.OLLAMA_SHOW_HOLEN = kaputt
        self.assertIsNone(katalog.ollama_vision("qwen3.5:9b"))

    def test_ergebnis_wird_gecacht_kein_zweiter_aufruf(self) -> None:
        aufrufe = []

        def show(modell_id):
            aufrufe.append(modell_id)
            return {"capabilities": ["vision"]}

        katalog.OLLAMA_SHOW_HOLEN = show
        katalog.ollama_vision("qwen3-vl:235b-cloud")
        katalog.ollama_vision("qwen3-vl:235b-cloud")
        self.assertEqual(len(aufrufe), 1)

    def test_ollama_vision_anreichern_haengt_vision_an_jede_zeile(self) -> None:
        katalog.OLLAMA_SHOW_HOLEN = lambda modell_id: (
            {"capabilities": ["vision"]} if "vl" in modell_id else {"capabilities": ["completion"]})
        zeilen = katalog.parse_ollama_tags(
            {"models": [{"name": "qwen3-vl:235b-cloud"}, {"name": "glm-5.3:cloud"}]})
        angereichert = {z.modell_id: z.vision for z in katalog._ollama_vision_anreichern(zeilen)}
        self.assertEqual(angereichert, {"qwen3-vl:235b-cloud": True, "glm-5.3:cloud": False})


class OllamaApiHolenTest(unittest.TestCase):
    """`_ollama_api_holen()` loggt Netzfehler selbst und liefert `{}` statt zu werfen (anders
    als `_requesty_holen`/`_openrouter_holen`, die den Fehler nach oben durchreichen)."""

    def test_netzfehler_loggt_und_liefert_leeres_ergebnis(self) -> None:
        alt = katalog.urllib.request.urlopen

        def kaputt(*a, **kw):
            raise OSError("offline")

        katalog.urllib.request.urlopen = kaputt
        try:
            fehlerausgabe = io.StringIO()
            with contextlib.redirect_stderr(fehlerausgabe):
                ergebnis = katalog._ollama_api_holen()
        finally:
            katalog.urllib.request.urlopen = alt
        self.assertEqual(ergebnis, {})
        self.assertIn("Ollama", fehlerausgabe.getvalue())


class BeschaffeOllamaTest(unittest.TestCase):
    """Ollama live als Basisquelle (Nachtrag): `/api/tags` schlaegt `modelle.json`, Preise
    kommen als Anreicherung dazu; nicht erreichbar -> Fallback auf die alte Registry-Form."""

    def setUp(self) -> None:
        self._alt = katalog.OLLAMA_API_HOLEN
        self._alt_show = katalog.OLLAMA_SHOW_HOLEN
        # `_beschaffe_ollama` reichert Live-Zeilen zusaetzlich mit `vision` an (ein `/api/show`
        # je Modell, Entscheid 2026-08-30 Nachtrag 6) -- ohne diesen Fake wuerden diese Tests
        # einen echten Netzaufruf an den lokalen Ollama-Daemon machen (Moduldoc: "kein Netz").
        katalog.OLLAMA_SHOW_HOLEN = lambda modell_id: {}
        katalog._OLLAMA_VISION_CACHE.clear()

    def tearDown(self) -> None:
        katalog.OLLAMA_API_HOLEN = self._alt
        katalog.OLLAMA_SHOW_HOLEN = self._alt_show
        katalog._OLLAMA_VISION_CACHE.clear()

    def test_live_ist_basis_neues_modell_ohne_preis_erscheint(self) -> None:
        katalog.OLLAMA_API_HOLEN = lambda: OLLAMA_TAGS_FIXTURE
        zeilen, fehler = katalog.beschaffe("ollama", REGISTRY)
        self.assertEqual(fehler, "")
        ids = {z.modell_id for z in zeilen}
        self.assertEqual(ids, {"glm-5.3:cloud", "kimi-k3:cloud", "qwen3.5:9b", "kein-details"})

    def test_preis_wird_aus_registry_angereichert_ueber_tag_grenze(self) -> None:
        katalog.OLLAMA_API_HOLEN = lambda: {"models": [
            {"name": "glm-5.2:cloud", "details": {"context_length": 1048576}}]}
        zeilen, fehler = katalog.beschaffe("ollama", REGISTRY)
        self.assertEqual(fehler, "")
        [glm] = zeilen
        self.assertEqual(glm.eingabe_usd, 1.19)
        self.assertEqual(glm.ausgabe_usd, 3.74)
        self.assertEqual(glm.kontext_k, 1049)  # bleibt aus der Live-Antwort, nicht ueberschrieben

    def test_modell_nur_in_registry_nicht_mehr_live_wird_nicht_angezeigt(self) -> None:
        """Ollama ist die Wahrheit: `minimax-m3` steht in REGISTRY, aber nicht im Live-Bestand."""
        katalog.OLLAMA_API_HOLEN = lambda: {"models": [
            {"name": "glm-5.2:cloud", "details": {"context_length": 1048576}}]}
        zeilen, fehler = katalog.beschaffe("ollama", REGISTRY)
        self.assertNotIn("minimax-m3", {z.modell_id for z in zeilen})

    def test_ollama_nicht_erreichbar_faellt_auf_modelle_json_zurueck(self) -> None:
        katalog.OLLAMA_API_HOLEN = lambda: {}
        zeilen, fehler = katalog.beschaffe("ollama", REGISTRY)
        self.assertEqual(fehler, "")
        self.assertEqual({z.modell_id for z in zeilen}, {"glm-5.2", "minimax-m3"})


class ParseArtificialAnalysisTest(unittest.TestCase):
    def test_beide_schluessel_slug_und_name(self) -> None:
        zuordnung = katalog.parse_artificialanalysis(ARTIFICIALANALYSIS_FIXTURE)
        self.assertIn("glm-5-3-flash", zuordnung)
        self.assertIn(katalog.aa_schluessel("ChatGLM Flash 5.3"), zuordnung)
        self.assertEqual(zuordnung["glm-5-3-flash"],
                          zuordnung[katalog.aa_schluessel("ChatGLM Flash 5.3")])

    def test_rundung_und_agentic_index(self) -> None:
        werte = katalog.parse_artificialanalysis(ARTIFICIALANALYSIS_FIXTURE)["glm-5-3-flash"]
        self.assertEqual(werte["aa_index"], 54)
        self.assertEqual(werte["coding_index"], 62)
        self.assertEqual(werte["agentic_index"], 47)  # round(0.472 * 100)
        self.assertEqual(werte["tempo_tok_s"], 118.4)

    def test_fehlende_evaluations_liefert_null_werte(self) -> None:
        werte = katalog.parse_artificialanalysis(ARTIFICIALANALYSIS_FIXTURE)["uraltes-modell"]
        self.assertIsNone(werte["aa_index"])
        self.assertIsNone(werte["coding_index"])
        self.assertIsNone(werte["agentic_index"])
        self.assertIsNone(werte["tempo_tok_s"])

    def test_eintrag_ohne_slug_und_name_wird_uebersprungen(self) -> None:
        """Der dritte Fixture-Eintrag hat weder slug noch name -- kann nie gematcht werden,
        zaehlt als uebersprungen statt eine kaputte Zeile ins Mapping zu schreiben."""
        zuordnung = katalog.parse_artificialanalysis(ARTIFICIALANALYSIS_FIXTURE)
        # Modell 1 -> 2 Schluessel (slug+name normieren verschieden), Modell 2 -> 1 (slug==name
        # normiert gleich), Modell 3 uebersprungen.
        self.assertEqual(len(zuordnung), 3)

    def test_erster_treffer_gewinnt_bei_kollision(self) -> None:
        daten = {"data": [
            {"slug": "modell-x", "evaluations": {"artificial_analysis_intelligence_index": 10}},
            {"slug": "modell-x", "evaluations": {"artificial_analysis_intelligence_index": 90}},
        ]}
        self.assertEqual(katalog.parse_artificialanalysis(daten)["modell-x"]["aa_index"], 10)


class VonModelleJsonTest(unittest.TestCase):
    def test_anthropic_zeilen(self) -> None:
        zeilen = katalog.von_modelle_json(REGISTRY, "anthropic")
        ids = {z.modell_id for z in zeilen}
        self.assertEqual(ids, {"claude-sonnet-5", "claude-opus-5"})
        self.assertTrue(all(z.anbieter == "claude" for z in zeilen))
        sonnet = next(z for z in zeilen if z.modell_id == "claude-sonnet-5")
        self.assertEqual(sonnet.stand, date(2026, 8, 25))  # eigener stand, nicht der Fallback
        self.assertIsNone(sonnet.kontext_k)  # Registry fuehrt fuer Anthropic kein Kontextfenster

    def test_anthropic_ohne_eigenen_stand_faellt_auf_preise_stand_zurueck(self) -> None:
        opus = next(z for z in katalog.von_modelle_json(REGISTRY, "anthropic")
                    if z.modell_id == "claude-opus-5")
        self.assertEqual(opus.stand, date(2026, 8, 20))

    def test_ollama_zeilen_mit_kontext_aus_dem_bestand(self) -> None:
        zeilen = katalog.von_modelle_json(REGISTRY, "ollama")
        ids = {z.modell_id for z in zeilen}
        self.assertEqual(ids, {"glm-5.2", "minimax-m3"})
        self.assertTrue(all(z.anbieter == "ollama" for z in zeilen))
        glm = next(z for z in zeilen if z.modell_id == "glm-5.2")
        self.assertEqual(glm.kontext_k, 1049)  # 1048576 / 1000, gerundet
        self.assertEqual(glm.quelle, "OpenRouter-Listenpreis z-ai/glm-5.2")

    def test_andere_herkunft_wird_nicht_mitgenommen(self) -> None:
        """`gpt-5.5` (herkunft=openai) gehoert weder zu claude noch zu ollama (C15-Scope)."""
        alle_ids = {z.modell_id for z in katalog.von_modelle_json(REGISTRY, "anthropic")}
        alle_ids |= {z.modell_id for z in katalog.von_modelle_json(REGISTRY, "ollama")}
        self.assertNotIn("gpt-5.5", alle_ids)

    def test_lokal_feld_aus_dem_typ_der_registry_nicht_aus_der_taglosen_id(self) -> None:
        """Befund 2026-08-30 (Fix 2): `preise.modelle`-Schluessel sind taglos (`glm-5.2`) --
        `ist_ollama_cloud('glm-5.2')` waere IMMER False (lokal), obwohl beide REGISTRY-Modelle
        laut `modelle['typ']` cloud sind. Der Registry-Fallback muss das richtigstellen."""
        zeilen = {z.modell_id: z.lokal for z in katalog.von_modelle_json(REGISTRY, "ollama")}
        self.assertEqual(zeilen, {"glm-5.2": False, "minimax-m3": False})

    def test_claude_zeilen_sind_nie_lokal(self) -> None:
        self.assertTrue(all(not z.lokal for z in katalog.von_modelle_json(REGISTRY, "anthropic")))


class KatalogZeileValidierungTest(unittest.TestCase):
    def test_unbekannter_anbieter_wirft(self) -> None:
        with self.assertRaises(ValidationError):
            katalog.KatalogZeile(modell_id="x", hersteller="X", anbieter="bing",
                                  stand=date.today(), quelle="test")

    def test_negativer_preis_wirft(self) -> None:
        with self.assertRaises(ValidationError):
            katalog.KatalogZeile(modell_id="x", hersteller="X", anbieter="claude",
                                  eingabe_usd=-1, stand=date.today(), quelle="test")

    def test_minimalzeile_ohne_optionale_felder(self) -> None:
        zeile = katalog.KatalogZeile(modell_id="x", hersteller="X", anbieter="claude",
                                      stand=date.today(), quelle="test")
        self.assertIsNone(zeile.herkunft)
        self.assertIsNone(zeile.kontext_k)
        self.assertFalse(zeile.lokal)  # Default (Fix 2): nur Ollama-Zeilen setzen True explizit

    def test_lokal_feld_explizit_setzbar(self) -> None:
        zeile = katalog.KatalogZeile(modell_id="qwen3:14b", hersteller="Alibaba",
                                      anbieter="ollama", lokal=True,
                                      stand=date.today(), quelle="test")
        self.assertTrue(zeile.lokal)


class KanonischeIdTest(unittest.TestCase):
    """C15 v2 Punkt 3 (Befund 2026-08-30, Fix 3): Katalog-Gruppierungsschluessel, staerker
    als `aa_schluessel` -- Ollama-Cloud-Suffix weg, Ziffer-Buchstabe-Trennung bekannter
    Familien, `-it`/`-instruct` ignoriert. Reale Katalog-IDs (GET /api/modellkatalog live
    geprueft 2026-08-30), keine erfundenen Paare."""

    def test_gpt_oss_cloud_matcht_openrouter_groesse(self) -> None:
        self.assertEqual(katalog.kanonische_id("gpt-oss:20b-cloud"),
                          katalog.kanonische_id("openai/gpt-oss-20b"))

    def test_gemma_ziffer_trennung_matcht_google_instruct(self) -> None:
        self.assertEqual(katalog.kanonische_id("gemma4:31b-cloud"),
                          katalog.kanonische_id("google/gemma-4-31b-it"))

    def test_glm_cloud_matcht_openrouter_und_aa(self) -> None:
        ziel = katalog.kanonische_id("z-ai/glm-5.2")
        self.assertEqual(katalog.kanonische_id("glm-5.2:cloud"), ziel)
        self.assertEqual(katalog.kanonische_id("glm-5.2"), ziel)  # AA-Slug, kein Anbieter-Praefix

    def test_qwen_punktversion_matcht_openrouter(self) -> None:
        self.assertEqual(katalog.kanonische_id("qwen3.5:9b"),
                          katalog.kanonische_id("qwen/qwen3.5-9b"))

    def test_qwen_wird_nie_ziffer_getrennt(self) -> None:
        """`qwen3-vl`/`qwen3` bleiben zusammen (Vorgabe) -- keine Familie fuer die
        Ziffertrennung, sonst bricht der schon funktionierende Treffer gegen OpenRouter."""
        self.assertNotIn("qwen-3", katalog.kanonische_id("qwen3-vl:235b-cloud"))
        self.assertEqual(katalog.kanonische_id("qwen3:14b"),
                          katalog.kanonische_id("qwen/qwen3-14b"))

    def test_keine_falsch_merges_ueber_generationen(self) -> None:
        """Vorsicht: `gemma-3-27b` darf NIE `gemma-4-31b` treffen."""
        self.assertNotEqual(katalog.kanonische_id("google/gemma-3-27b-it"),
                             katalog.kanonische_id("gemma4:31b-cloud"))

    def test_preview_bleibt_erhalten(self) -> None:
        self.assertEqual(katalog.kanonische_id("gemini-3-flash-preview:cloud"),
                          katalog.kanonische_id("google/gemini-3-flash-preview"))
        self.assertIn("preview", katalog.kanonische_id("gemini-3-flash-preview:cloud"))

    def test_snapshot_datum_suffix_matcht_die_basis(self) -> None:
        """Entscheid 2026-08-30 Nachtrag 6 (Restkante): `claude-haiku-4-5-20251001`
        (Registry-Schluessel, `scripts/modelle.json`) ist DASSELBE Modell wie
        `claude-haiku-4-5` (OpenRouter/Requesty) -- ein trailing YYYYMMDD-Snapshot-Suffix
        traegt keine Modell-Unterscheidungskraft und faellt weg (Muster
        `aa_token_schluessel`, hier aber fuer die Katalog-GRUPPIERUNG)."""
        self.assertEqual(katalog.kanonische_id("claude-haiku-4-5-20251001"),
                          katalog.kanonische_id("anthropic/claude-haiku-4-5"))

    def test_reine_versionsziffer_ohne_datumsform_bleibt_erhalten(self) -> None:
        """Nur ein ECHTES YYYYMMDD-Datum (20xx, gueltiger Monat/Tag) faellt weg -- eine
        andere 8-stellige Ziffernfolge waere hier ohnehin nicht real, dieser Test haelt die
        Regel eng am Muster von `aa_token_schluessel`."""
        self.assertNotIn("20251001", katalog.kanonische_id("claude-haiku-4-5-20251001"))
        self.assertEqual(katalog.kanonische_id("claude-opus-5"), "claude-opus-5")

    def test_colon_high_alias_matcht_basis(self) -> None:
        """Festlegung 2026-08-30 (generationen.json Feld `aliasse`): `:high`/`:medium`/`:low`
        sind Reasoning-Effort-Bezugsvarianten, kein eigenes Modell."""
        self.assertEqual(katalog.kanonische_id("o1:high"), katalog.kanonische_id("o1"))

    def test_colon_priority_alias_matcht_basis(self) -> None:
        self.assertEqual(katalog.kanonische_id("gpt-5:priority"), katalog.kanonische_id("gpt-5"))

    def test_colon_free_alias_matcht_basis_mit_anbieter_praefix(self) -> None:
        self.assertEqual(katalog.kanonische_id("z-ai/glm-5.2:free"),
                          katalog.kanonische_id("glm-5.2"))

    def test_bindestrich_latest_alias_matcht_basis(self) -> None:
        self.assertEqual(katalog.kanonische_id("codestral-latest"), katalog.kanonische_id("codestral"))

    def test_bindestrich_latest_alias_bleibt_bei_mehrteiliger_basis_erhalten(self) -> None:
        self.assertEqual(katalog.kanonische_id("devstral-small-latest"),
                          katalog.kanonische_id("devstral-small"))

    def test_mistral_large_latest_matcht_mistral_large(self) -> None:
        self.assertEqual(katalog.kanonische_id("mistral-large-latest"),
                          katalog.kanonische_id("mistral-large"))

    def test_datumsversion_ist_kein_alias_bleibt_eigene_zeile(self) -> None:
        """Task-Vorgabe (Festlegung 2026-08-30): `mistral-large-2512` ist KEINE Alias-
        Bezugsvariante von `mistral-large` -- eine echte Datumsversion bleibt eine eigene Zeile."""
        self.assertNotEqual(katalog.kanonische_id("mistral-large-2512"),
                             katalog.kanonische_id("mistral-large"))


class SqlUpsertTest(unittest.TestCase):
    def _zeile(self, **overrides) -> katalog.KatalogZeile:
        werte = dict(modell_id="glm-5.2", hersteller="Zhipu AI", herkunft="CN", anbieter="ollama",
                     kontext_k=1049, eingabe_usd=1.19, ausgabe_usd=3.74, stand=date(2026, 8, 27),
                     quelle="modelle.json")
        werte.update(overrides)
        return katalog.KatalogZeile(**werte)

    def test_conflict_ziel_und_spalten(self) -> None:
        sql = katalog.sql_upsert([self._zeile()])
        self.assertIn("ON CONFLICT (modell_id, anbieter) DO UPDATE SET", sql)
        self.assertIn("hersteller = EXCLUDED.hersteller", sql)
        self.assertNotIn("modell_id = EXCLUDED.modell_id", sql)  # PK wird nie geupdatet
        self.assertIn("RETURNING (xmax = 0) AS neu", sql)
        self.assertIn("INSERT INTO modellkatalog", sql)
        self.assertNotIn("DELETE", sql)  # C15: kein Loeschen

    def test_null_werte_und_datum_cast(self) -> None:
        sql = katalog.sql_upsert([self._zeile(herkunft=None, kontext_k=None)])
        self.assertIn("NULL", sql)
        self.assertIn("'2026-08-27'::date", sql)

    def test_zwei_zeilen_ein_statement(self) -> None:
        sql = katalog.sql_upsert([self._zeile(), self._zeile(modell_id="minimax-m3")])
        self.assertEqual(sql.count("INSERT INTO"), 1)
        self.assertIn("'minimax-m3'", sql)

    def test_vision_spalte_im_upsert(self) -> None:
        """Migration 0009 (Entscheid 2026-08-30 Nachtrag 6): `vision` gehoert zur INSERT-/
        UPDATE-Spaltenliste, `True`/`False` werden als SQL-Literal TRUE/FALSE geschrieben
        (Python `str(True)` waere das ungueltige Bezeichner-Wort "True")."""
        sql = katalog.sql_upsert([self._zeile(vision=True), self._zeile(modell_id="x", vision=False)])
        self.assertIn("vision = EXCLUDED.vision", sql)
        self.assertIn("TRUE", sql)
        self.assertIn("FALSE", sql)


class KatalogZeileVisionDefaultTest(unittest.TestCase):
    def test_default_ist_none(self) -> None:
        zeile = katalog.KatalogZeile(modell_id="x", hersteller="X", anbieter="claude",
                                      stand=date.today(), quelle="test")
        self.assertIsNone(zeile.vision)


class UpsertKatalogTest(unittest.TestCase):
    def test_zaehlt_neu_und_aktualisiert(self) -> None:
        fake = FakePsql(["3|5"])
        zeile = katalog.KatalogZeile(modell_id="x", hersteller="X", anbieter="claude",
                                      stand=date.today(), quelle="test")
        self.assertEqual(katalog.upsert_katalog([zeile], fake), (3, 5))
        self.assertEqual(len(fake.sql), 1)

    def test_leere_liste_ruft_laufer_nicht_auf(self) -> None:
        fake = FakePsql(["sollte nie gelesen werden"])
        self.assertEqual(katalog.upsert_katalog([], fake), (0, 0))
        self.assertEqual(fake.sql, [])


class BeschaffeFailOpenTest(unittest.TestCase):
    def setUp(self) -> None:
        self._alt_or = katalog.OPENROUTER_HOLEN
        self._alt_rq = katalog.REQUESTY_HOLEN

    def tearDown(self) -> None:
        katalog.OPENROUTER_HOLEN = self._alt_or
        katalog.REQUESTY_HOLEN = self._alt_rq

    def test_openrouter_netzfehler_liefert_fehlermeldung_statt_exception(self) -> None:
        katalog.OPENROUTER_HOLEN = lambda url, headers: (_ for _ in ()).throw(OSError("offline"))
        zeilen, fehler = katalog.beschaffe("openrouter", {})
        self.assertEqual(zeilen, [])
        self.assertIn("OpenRouter", fehler)

    def test_requesty_kaputtes_json_liefert_fehlermeldung(self) -> None:
        katalog.REQUESTY_HOLEN = lambda: "kein json{"
        zeilen, fehler = katalog.beschaffe("requesty", {})
        self.assertEqual(zeilen, [])
        self.assertIn("Requesty", fehler)

    def test_claude_ollama_lesen_ohne_netz_aus_registry(self) -> None:
        zeilen, fehler = katalog.beschaffe("claude", REGISTRY)
        self.assertEqual(fehler, "")
        self.assertTrue(zeilen)

    def test_unbekannter_anbieter_wirft(self) -> None:
        with self.assertRaises(ValueError):
            katalog.beschaffe("bing", {})


class AktualisiereAaIndizesTest(unittest.TestCase):
    """`aktualisiere_aa_indizes` (C15 v2 Punkt 1): Bestandszeilen lesen, ueber `aa_schluessel`
    matchen, Treffer per UPDATE schreiben -- kein Netz, nur der Fake-`psql`-Laufer."""

    ZUORDNUNG = {"glm-5-3-flash": {"aa_index": 54, "coding_index": 62,
                                    "agentic_index": 47, "tempo_tok_s": 118.4}}

    def test_gematchte_zeile_wird_upgedatet(self) -> None:
        fake = FakePsql(["z-ai/glm-5.3-flash|openrouter\nsonstwas|claude", "1"])
        gematcht, aktualisiert = katalog.aktualisiere_aa_indizes(
            self.ZUORDNUNG, date(2026, 8, 28), fake)
        self.assertEqual((gematcht, aktualisiert), (1, 1))
        self.assertEqual(len(fake.sql), 2)
        self.assertIn("z-ai/glm-5.3-flash", fake.sql[1])
        self.assertIn("'2026-08-28'::date", fake.sql[1])
        self.assertNotIn("INSERT INTO", fake.sql[1])

    def test_keine_treffer_ruft_kein_update_auf(self) -> None:
        fake = FakePsql(["unbekanntes-modell|claude"])
        gematcht, aktualisiert = katalog.aktualisiere_aa_indizes(
            self.ZUORDNUNG, date(2026, 8, 28), fake)
        self.assertEqual((gematcht, aktualisiert), (0, 0))
        self.assertEqual(len(fake.sql), 1)  # nur die SELECT, kein UPDATE-Statement

    def test_leere_zuordnung_liest_nicht_einmal_den_bestand(self) -> None:
        fake = FakePsql(["sollte nie gelesen werden"])
        self.assertEqual(katalog.aktualisiere_aa_indizes({}, date(2026, 8, 28), fake), (0, 0))
        self.assertEqual(fake.sql, [])

    def test_wortstellung_matcht_ueber_token_fallback(self) -> None:
        """Maintainer 2026-08-28 "Uebersetzungsfehler": AA slugt `claude-4-5-haiku`, die Anbieter
        `claude-haiku-4-5` -- der Token-Fallback muss beide zusammenbringen, Snapshot-IDs
        mit Datums-Suffix ebenso."""
        zuordnung = {"claude-4-5-haiku": {"aa_index": 41, "coding_index": 50,
                                          "agentic_index": 38, "tempo_tok_s": 90.0}}
        fake = FakePsql(["claude-haiku-4-5|openrouter\nanthropic/claude-haiku-4-5-20251001|claude", "2"])
        gematcht, aktualisiert = katalog.aktualisiere_aa_indizes(zuordnung, date(2026, 8, 28), fake)
        self.assertEqual((gematcht, aktualisiert), (2, 2))
        self.assertIn("claude-haiku-4-5-20251001", fake.sql[1])


class AaTokenSchluesselTest(unittest.TestCase):
    def test_wortstellung_und_datums_suffix(self) -> None:
        self.assertEqual(katalog.aa_token_schluessel("claude-haiku-4-5"),
                         katalog.aa_token_schluessel("claude-4-5-haiku"))
        self.assertEqual(katalog.aa_token_schluessel("claude-haiku-4-5-20251001"),
                         katalog.aa_token_schluessel("claude-4-5-haiku"))

    def test_mehrdeutige_token_schluessel_werden_verworfen(self) -> None:
        """Zwei AA-Eintraege mit gleichem Token-Schluessel, aber verschiedenen Werten ->
        Fallback verwirft den Schluessel (lieber kein Index als der falsche)."""
        a = {"aa_index": 1, "coding_index": 1, "agentic_index": 1, "tempo_tok_s": 1.0}
        b = {"aa_index": 2, "coding_index": 2, "agentic_index": 2, "tempo_tok_s": 2.0}
        abgeleitet = katalog._aa_token_zuordnung({"foo-bar": a, "bar-foo": b})
        self.assertNotIn(katalog.aa_token_schluessel("foo-bar"), abgeleitet)

    def test_gleiche_werte_kollidieren_nicht(self) -> None:
        a = {"aa_index": 1, "coding_index": 1, "agentic_index": 1, "tempo_tok_s": 1.0}
        abgeleitet = katalog._aa_token_zuordnung({"foo-bar": a, "bar-foo": a})
        self.assertEqual(abgeleitet[katalog.aa_token_schluessel("foo-bar")], a)


class AaKernSchluesselTest(unittest.TestCase):
    """Dritte Matching-Stufe (Maintainer 2026-08-28 Runde 2): Rausch-Token wie -preview/-chat/-v1
    benennen dasselbe Modell um und fallen fuer den Vergleich weg."""

    def test_rausch_token_fallen_weg(self) -> None:
        self.assertEqual(katalog.aa_kern_schluessel("gemini-3-flash-preview"),
                         katalog.aa_kern_schluessel("gemini-3-flash"))
        self.assertEqual(katalog.aa_kern_schluessel("amazon/nova-premier-v1"),
                         katalog.aa_kern_schluessel("nova-premier"))
        self.assertEqual(katalog.aa_kern_schluessel("deepseek/deepseek-chat-v3.1"),
                         katalog.aa_kern_schluessel("deepseek-v3.1"))

    def test_echte_versionsnummern_bleiben_unterscheidbar(self) -> None:
        self.assertNotEqual(katalog.aa_kern_schluessel("gpt-5.2"),
                            katalog.aa_kern_schluessel("gpt-5.1"))

    def test_versions_zusammenfall_wird_verworfen(self) -> None:
        """Streichen von v2/v3 laesst zwei AA-Eintraege zusammenfallen -> Schluessel weg
        (lieber kein Index als der einer anderen Version)."""
        a = {"aa_index": 1, "coding_index": 1, "agentic_index": 1, "tempo_tok_s": 1.0}
        b = {"aa_index": 2, "coding_index": 2, "agentic_index": 2, "tempo_tok_s": 2.0}
        abgeleitet = katalog._aa_ableitung({"foo-v2": a, "foo-v3": b}, katalog.aa_kern_schluessel)
        self.assertNotIn("foo", abgeleitet)

    def test_kern_fallback_greift_im_matching(self) -> None:
        zuordnung = {"gemini-3-flash": {"aa_index": 48, "coding_index": 55,
                                        "agentic_index": 44, "tempo_tok_s": 200.0}}
        fake = FakePsql(["google/gemini-3-flash-preview|openrouter", "1"])
        gematcht, aktualisiert = katalog.aktualisiere_aa_indizes(zuordnung, date(2026, 8, 28), fake)
        self.assertEqual((gematcht, aktualisiert), (1, 1))


class AktualisiereAaMigrationsHinweisTest(unittest.TestCase):
    def test_fehlende_spalte_liefert_verstaendliche_meldung(self) -> None:
        fehler = speicher.SpeicherFehler('ERROR:  column "agentic_index" of relation '
                                          '"modellkatalog" does not exist')
        self.assertEqual(katalog._aa_migrationshinweis(fehler),
                          "Migration 0007 fehlt — infra/sitzungsbeleg-db/0007_aa_indizes.sql einspielen")

    def test_anderer_db_fehler_bleibt_generisch(self) -> None:
        fehler = speicher.SpeicherFehler("psql nicht ausführbar: TimeoutExpired")
        self.assertIn("Upsert fehlgeschlagen", katalog._aa_migrationshinweis(fehler))


class AktualisiereAaTest(unittest.TestCase):
    """`aktualisiere_aa` (Gesamtschritt): AA-Holen wird gemockt, kein echtes Netz/kein echter
    Schluessel noetig."""

    def setUp(self) -> None:
        self._alt_holen = katalog.ARTIFICIALANALYSIS_HOLEN

    def tearDown(self) -> None:
        katalog.ARTIFICIALANALYSIS_HOLEN = self._alt_holen

    def test_fehlender_schluessel_liefert_fehlermeldung_statt_exception(self) -> None:
        def wirft():
            raise katalog.ArtificialAnalysisSchluesselFehler("kein Schluessel")
        katalog.ARTIFICIALANALYSIS_HOLEN = wirft
        ergebnis = katalog.aktualisiere_aa(schreiben=False)
        self.assertEqual(ergebnis["anbieter"], "aa")
        self.assertEqual(ergebnis["anzahl"], 0)
        self.assertIn("Schluessel", ergebnis["fehler"])

    def test_trockenlauf_zaehlt_ohne_db_zugriff(self) -> None:
        import json as _json
        katalog.ARTIFICIALANALYSIS_HOLEN = lambda: _json.dumps(ARTIFICIALANALYSIS_FIXTURE)
        fake = FakePsql(["sollte nie gelesen werden"])
        ergebnis = katalog.aktualisiere_aa(schreiben=False, laufer=fake)
        self.assertIsNone(ergebnis["fehler"])
        self.assertEqual(ergebnis["anzahl"], 3)
        self.assertEqual(ergebnis["aktualisiert"], 0)
        self.assertEqual(fake.sql, [])

    def test_migration_fehlt_wird_als_lesbare_fehlermeldung_gereicht(self) -> None:
        import json as _json
        katalog.ARTIFICIALANALYSIS_HOLEN = lambda: _json.dumps(ARTIFICIALANALYSIS_FIXTURE)

        def bestand_dann_fehler(sql, zeitlimit_s=8):
            if sql.strip().startswith("SELECT modell_id"):
                return "z-ai/glm-5.3-flash|openrouter"
            raise speicher.SpeicherFehler('column "agentic_index" does not exist')

        ergebnis = katalog.aktualisiere_aa(schreiben=True, laufer=bestand_dann_fehler)
        self.assertIn("Migration 0007", ergebnis["fehler"])


class AktualisiereTest(unittest.TestCase):
    def setUp(self) -> None:
        self._alt_or = katalog.OPENROUTER_HOLEN
        self._alt_aa = katalog.ARTIFICIALANALYSIS_HOLEN
        self._alt_registry = katalog._registry
        # AA-Schritt ist jetzt fester Teil des Gesamtlaufs (C15 v2) -- ohne Mock wuerde er einen
        # echten Netzaufruf versuchen; ein Fehler ist fuer diese Tests unschaedlich (Fail-open).
        katalog.ARTIFICIALANALYSIS_HOLEN = lambda: (_ for _ in ()).throw(OSError("offline"))

    def tearDown(self) -> None:
        katalog.OPENROUTER_HOLEN = self._alt_or
        katalog.ARTIFICIALANALYSIS_HOLEN = self._alt_aa
        katalog._registry = self._alt_registry

    def test_trockenlauf_ohne_db_ruft_laufer_nie_auf(self) -> None:
        katalog._registry = lambda: REGISTRY
        fake = FakePsql(["1|1"])
        ergebnisse = katalog.aktualisiere(["claude"], schreiben=False, laufer=fake)
        self.assertEqual(ergebnisse[0]["anbieter"], "claude")
        self.assertGreater(ergebnisse[0]["anzahl"], 0)
        self.assertEqual((ergebnisse[0]["neu"], ergebnisse[0]["aktualisiert"]), (0, 0))
        self.assertEqual(fake.sql, [])

    def test_mit_db_ruft_upsert_auf(self) -> None:
        katalog._registry = lambda: REGISTRY
        fake = FakePsql(["2|0"])
        ergebnisse = katalog.aktualisiere(["ollama"], schreiben=True, laufer=fake)
        self.assertEqual(ergebnisse[0]["neu"], 2)
        self.assertEqual(len(fake.sql), 1)

    def test_eine_tote_quelle_stoppt_die_anderen_nicht(self) -> None:
        katalog._registry = lambda: REGISTRY
        katalog.OPENROUTER_HOLEN = lambda url, headers: (_ for _ in ()).throw(OSError("offline"))
        fake = FakePsql(["1|1"])
        ergebnisse = katalog.aktualisiere(["openrouter", "claude"], schreiben=True, laufer=fake)
        offen = {e["anbieter"]: e for e in ergebnisse}
        self.assertIsNotNone(offen["openrouter"]["fehler"])
        self.assertIsNone(offen["claude"]["fehler"])
        self.assertEqual(offen["claude"]["neu"], 1)

    def test_default_alle_vier_quellen_in_reihenfolge(self) -> None:
        katalog._registry = lambda: {}
        katalog.OPENROUTER_HOLEN = lambda url, headers: (_ for _ in ()).throw(OSError("offline"))
        fake = FakePsql(["0|0", "0|0"])
        ergebnisse = katalog.aktualisiere(None, schreiben=True, laufer=fake)
        # AA-Anreicherung ist C15 v2 ein fester letzter Schritt des Gesamtlaufs, aber kein
        # Bezugsweg -- sie steht nicht in QUELLEN_REIHENFOLGE.
        self.assertEqual([e["anbieter"] for e in ergebnisse],
                          list(katalog.QUELLEN_REIHENFOLGE) + ["aa"])

    def test_einzeln_aufrufbare_aa_quelle(self) -> None:
        import json as _json
        katalog.ARTIFICIALANALYSIS_HOLEN = lambda: _json.dumps(ARTIFICIALANALYSIS_FIXTURE)
        ergebnisse = katalog.aktualisiere(["aa"], schreiben=False)
        self.assertEqual([e["anbieter"] for e in ergebnisse], ["aa"])
        self.assertIsNone(ergebnisse[0]["fehler"])
        self.assertEqual(ergebnisse[0]["anzahl"], 3)


class BefehlKatalogUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._alt_registry = katalog._registry
        katalog._registry = lambda: REGISTRY

    def tearDown(self) -> None:
        katalog._registry = self._alt_registry

    def _args(self, anbieter=None, db=False) -> argparse.Namespace:
        return argparse.Namespace(anbieter=anbieter, db=db)

    def test_ohne_db_meldet_geladene_anzahl_und_exit_0(self) -> None:
        import contextlib
        import io
        ausgabe = io.StringIO()
        with contextlib.redirect_stdout(ausgabe):
            code = katalog.befehl_katalog_update(self._args(anbieter="claude", db=False))
        self.assertEqual(code, 0)
        self.assertIn("claude:", ausgabe.getvalue())
        self.assertIn("Modelle geladen", ausgabe.getvalue())

    def test_fehler_geht_nach_stderr_exit_bleibt_0(self) -> None:
        alt = katalog.OPENROUTER_HOLEN
        katalog.OPENROUTER_HOLEN = lambda url, headers: (_ for _ in ()).throw(OSError("offline"))
        try:
            import io
            import contextlib
            fehler_ausgabe = io.StringIO()
            with contextlib.redirect_stderr(fehler_ausgabe):
                code = katalog.befehl_katalog_update(self._args(anbieter="openrouter", db=True))
            self.assertEqual(code, 0)
            self.assertIn("FEHLER", fehler_ausgabe.getvalue())
        finally:
            katalog.OPENROUTER_HOLEN = alt


if __name__ == "__main__":
    unittest.main()


def test_parse_openrouter_ueberspringt_ungueltige_zeile():
    """OpenRouter liefert fuer den Auto-Router Preis -1 -- die Zeile fliegt raus,
    die uebrigen Modelle der Quelle bleiben erhalten (Fail-open je Zeile)."""
    daten = {"data": [
        {"id": "openrouter/auto", "context_length": 2000000,
         "pricing": {"prompt": "-1", "completion": "-1"}},
        {"id": "openai/gpt-5.5", "context_length": 400000,
         "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    ]}
    zeilen = katalog.parse_openrouter(daten)
    assert [z.modell_id for z in zeilen] == ["openai/gpt-5.5"]


def test_parse_openrouter_ueberspringt_latest_aliasse():
    """OpenRouter fuehrt "~anbieter/x-latest"-Aliasse (Verweise auf konkrete Modelle) --
    die gehoeren nicht in den Katalog (Sichtbefund 2026-08-28: Tilde-Zeilen oben)."""
    daten = {"data": [
        {"id": "~anthropic/claude-fable-latest", "context_length": 1000000,
         "pricing": {"prompt": "0.00001", "completion": "0.00005"}},
        {"id": "anthropic/claude-fable-5", "context_length": 200000,
         "pricing": {"prompt": "0.0000005", "completion": "0.0000025"}},
    ]}
    zeilen = katalog.parse_openrouter(daten)
    assert [z.modell_id for z in zeilen] == ["anthropic/claude-fable-5"]
