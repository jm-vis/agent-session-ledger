"""C15 Modellkatalog -- Aggregation (katalog_sicht.py) + GET/POST /api/modellkatalog* (web.py).
FakeLaufer statt echter DB, wie test_wache_cache.py/test_speicher_sequence.py -- diese
Testsuite haelt keine reale Postgres-Verbindung, die Tabelle `modellkatalog` selbst gehoert
Migration 0006/0007 (andere Baustelle dieser Welle); die Schema-Wahrheit fuer die hier
verwendeten Beispielzeilen ist CONTRACTS.md C15 + "C15 v2 - Modellkatalog-Vollausbau"."""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from .. import katalog, katalog_sicht, speicher, web
from .test_web import FakeLaufer

_FIXTURES = Path(__file__).parent / "fixtures"


def _zeile(modell_id, anbieter, **kw):
    basis = {
        "modell_id": modell_id, "anbieter": anbieter, "hersteller": "Anthropic",
        "herkunft": "US", "kontext_k": 200, "eingabe_usd": None, "ausgabe_usd": None,
        "aa_index": None, "coding_index": None, "agentic_index": None, "tempo_tok_s": None,
        "aa_stand": None, "stand": "2026-08-20", "quelle": "test",
    }
    basis.update(kw)
    return basis


class GrokDezimalVersionTest(unittest.TestCase):
    def test_grok_4_20_ist_aelter_als_4_6(self):
        self.assertLess(katalog_sicht.version("grok-4.20"), katalog_sicht.version("grok-4.6"))
        self.assertEqual(katalog_sicht.neueste_je_familie(["grok-4.20", "grok-4.6", "grok-4.5"]), {"grok-4.6"})


class SqlAlleZeilenTest(unittest.TestCase):
    def test_select_ohne_where_alle_spalten(self) -> None:
        sql = katalog_sicht.sql_alle_zeilen()
        self.assertIn("FROM modellkatalog", sql)
        for spalte in ("modell_id", "hersteller", "herkunft", "anbieter", "kontext_k",
                       "eingabe_usd", "ausgabe_usd", "aa_index", "coding_index", "stand",
                       "agentic_index", "tempo_tok_s", "aa_stand"):
            self.assertIn(spalte, sql)
        self.assertIn("ORDER BY modell_id, anbieter", sql)

    def test_ohne_aa_spalten_lasst_migration_0007_spalten_weg(self) -> None:
        sql = katalog_sicht.sql_alle_zeilen(mit_aa_spalten=False)
        self.assertNotIn("agentic_index", sql)
        self.assertNotIn("tempo_tok_s", sql)
        self.assertNotIn("aa_stand", sql)

    def test_ohne_vision_spalte_laesst_migration_0009_spalte_weg(self) -> None:
        sql = katalog_sicht.sql_alle_zeilen(mit_vision_spalte=False)
        self.assertNotIn("vision", sql)


class ZeilenLesenTest(unittest.TestCase):
    def test_fehlende_0007_spalten_faellt_auf_alte_spaltenliste_zurueck(self) -> None:
        aufrufe = []

        def laufer(sql, zeitlimit_s=8):
            aufrufe.append(sql)
            if "agentic_index" in sql:
                raise speicher.SpeicherFehler('ERROR:  column "agentic_index" does not exist')
            return json.dumps([_zeile("claude-sonnet-5", "claude")])

        zeilen = katalog_sicht._zeilen_lesen(laufer)
        self.assertEqual(len(aufrufe), 2)
        self.assertEqual(zeilen[0]["modell_id"], "claude-sonnet-5")

    def test_anderer_fehler_wird_nicht_abgefangen(self) -> None:
        def laufer(sql, zeitlimit_s=8):
            raise speicher.SpeicherFehler("psql nicht erreichbar")

        with self.assertRaises(speicher.SpeicherFehler):
            katalog_sicht._zeilen_lesen(laufer)

    def test_fehlende_0009_spalte_faellt_auf_vor_vision_spaltenliste_zurueck(self) -> None:
        aufrufe = []

        def laufer(sql, zeitlimit_s=8):
            aufrufe.append(sql)
            if "vision" in sql:
                raise speicher.SpeicherFehler('ERROR:  column "vision" does not exist')
            return json.dumps([_zeile("claude-sonnet-5", "claude")])

        zeilen = katalog_sicht._zeilen_lesen(laufer)
        self.assertEqual(len(aufrufe), 2)
        self.assertEqual(zeilen[0]["modell_id"], "claude-sonnet-5")


class AggregiereTest(unittest.TestCase):
    def test_punkt_und_bindestrich_schreibweise_konsolidieren(self) -> None:
        """Befund 2026-08-28: `sonnet-4.5` vs `sonnet-4-5` = dasselbe Modell in zwei
        Anbieter-Schreibweisen -- eine Zeile, Anzeige = haeufigste Schreibweise."""
        zeilen = [
            _zeile("claude-sonnet-4.5", "openrouter"),
            _zeile("anthropic/claude-sonnet-4.5", "requesty"),
            _zeile("claude-sonnet-4-5", "claude"),
        ]
        modelle = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(len(modelle), 1)
        self.assertEqual(modelle[0]["id"], "claude-sonnet-4.5")  # 2x Punkt-Form > 1x Strich-Form
        self.assertEqual([a["name"] for a in modelle[0]["anbieter"]],
                         ["claude", "openrouter", "requesty"])

    def test_anzeige_id_nie_mit_variantensuffix(self) -> None:
        zeilen = [_zeile("vertex/claude-opus-5@eu-west-3", "requesty"),
                  _zeile("claude-opus-5", "claude")]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["id"], "claude-opus-5")

    def test_ein_anbieter_uebernimmt_alle_felder(self) -> None:
        zeilen = [_zeile("claude-sonnet-5", "claude", eingabe_usd=2.0, ausgabe_usd=10.0,
                          aa_index=74, coding_index=78, herkunft="US", hersteller="Anthropic")]
        ergebnis = katalog_sicht.aggregiere(zeilen)
        self.assertEqual(ergebnis["stand"], {"claude": "2026-08-20", "artificial_analysis": None})
        [m] = ergebnis["modelle"]
        self.assertEqual(m["id"], "claude-sonnet-5")
        self.assertEqual(m["hersteller"], "Anthropic")
        self.assertEqual(m["herkunft"], "US")
        self.assertEqual(m["kontext_k"], 200)
        self.assertEqual(m["aa_index"], 74)
        self.assertEqual(m["coding_index"], 78)
        self.assertEqual(m["anbieter"], [{"name": "claude", "eingabe_usd": 2.0, "ausgabe_usd": 10.0, "stand": "2026-08-20"}])
        self.assertEqual(m["preis_min"], {"eingabe_usd": 2.0, "ausgabe_usd": 10.0, "anbieter": "claude"})
        self.assertEqual(m["stand_juengster"], "2026-08-20")

    def test_mehrere_anbieter_guenstigste_ausgabe_gewinnt(self) -> None:
        """kimi-k3 (Mockup-Beispiel): Requesty 2,3 < OpenRouter 2,4 < Ollama 2,5 -- Requesty
        gewinnt preis_min, alle drei bleiben in der Anbieterliste."""
        zeilen = [
            _zeile("kimi-k3", "ollama", eingabe_usd=0.6, ausgabe_usd=2.5, stand="2026-08-28"),
            _zeile("kimi-k3", "requesty", eingabe_usd=0.55, ausgabe_usd=2.3, stand="2026-08-28"),
            _zeile("kimi-k3", "openrouter", eingabe_usd=0.6, ausgabe_usd=2.4, stand="2026-08-27"),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(len(m["anbieter"]), 3)
        self.assertEqual(m["preis_min"], {"eingabe_usd": 0.55, "ausgabe_usd": 2.3, "anbieter": "requesty"})
        self.assertEqual(m["stand_juengster"], "2026-08-28")  # juengstes Datum ueber ALLE Anbieter

    def test_fehlender_ausgabepreis_ueberall_faellt_auf_eingabepreis_zurueck(self) -> None:
        zeilen = [
            _zeile("llama-4-maverick", "ollama", eingabe_usd=None, ausgabe_usd=None),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["preis_min"], {"eingabe_usd": None, "ausgabe_usd": None, "anbieter": "ollama"})

    def test_stand_je_anbieter_ist_juengstes_datum_ueber_den_gesamten_katalog(self) -> None:
        zeilen = [
            _zeile("modell-a", "openrouter", stand="2026-08-20"),
            _zeile("modell-b", "openrouter", stand="2026-08-28"),
        ]
        ergebnis = katalog_sicht.aggregiere(zeilen)
        self.assertEqual(ergebnis["stand"]["openrouter"], "2026-08-28")

    def test_aa_index_null_bei_einem_anbieter_wird_von_anderem_ueberdeckt(self) -> None:
        """aa_index/coding_index kommen aus modelle.json oder AA -- eine Zeile traegt den
        Wert, andere Anbieter desselben Modells NULL; erster nicht-NULL-Wert gewinnt."""
        zeilen = [
            _zeile("deepseek-v4", "requesty", aa_index=None, coding_index=None),
            _zeile("deepseek-v4", "openrouter", aa_index=73, coding_index=81),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["aa_index"], 73)
        self.assertEqual(m["coding_index"], 81)

    def test_leere_zeilenliste_ergibt_leeren_katalog(self) -> None:
        ergebnis = katalog_sicht.aggregiere([])
        self.assertEqual(ergebnis, {"stand": {"artificial_analysis": None}, "modelle": []})

    def test_sortierung_stabil_nach_id(self) -> None:
        zeilen = [_zeile("z-modell", "ollama"), _zeile("a-modell", "ollama")]
        ids = [m["id"] for m in katalog_sicht.aggregiere(zeilen)["modelle"]]
        self.assertEqual(ids, ["a-modell", "z-modell"])


class KonsolidierungTest(unittest.TestCase):
    """C15 v2 Punkt 3: Aggregation je `katalog.kurzname()` statt je voller modell_id."""

    def test_zwei_praefixe_werden_zu_einem_modell_mit_zwei_anbietern(self) -> None:
        zeilen = [
            _zeile("claude-fable-5", "ollama", stand="2026-08-20"),
            _zeile("anthropic/claude-fable-5", "claude", stand="2026-08-27"),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual({a["name"] for a in m["anbieter"]}, {"ollama", "claude"})

    def test_id_uebernimmt_original_schreibweise_des_juengsten_eintrags(self) -> None:
        zeilen = [
            _zeile("Provider/Claude-Fable-5", "ollama", stand="2026-08-27"),
            _zeile("claude-fable-5", "claude", stand="2026-08-20"),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["id"], "Claude-Fable-5")  # Gross-/Kleinschreibung bleibt erhalten

    def test_haeufigster_nicht_leerer_wert_gewinnt_hersteller_und_herkunft(self) -> None:
        zeilen = [
            _zeile("modell-x", "claude", hersteller="Anthropic", herkunft="US"),
            _zeile("modell-x", "ollama", hersteller="Anthropic", herkunft="US"),
            _zeile("modell-x", "openrouter", hersteller=None, herkunft="EU"),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["hersteller"], "Anthropic")
        self.assertEqual(m["herkunft"], "US")

    def test_anbieter_dedupe_guenstigster_ausgabepreis_gewinnt(self) -> None:
        """Zwei Roh-IDs mit gleichem Kurznamen UND gleichem Anbieter (Gross-/Kleinschreibungs-
        Drift): der guenstigere Ausgabepreis gewinnt, der Anbieter erscheint nur einmal."""
        zeilen = [
            _zeile("Kimi-K3", "requesty", ausgabe_usd=2.3, stand="2026-08-28"),
            _zeile("kimi-k3", "requesty", ausgabe_usd=1.9, stand="2026-08-27"),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(len(m["anbieter"]), 1)
        self.assertEqual(m["preis_min"]["ausgabe_usd"], 1.9)

    def test_erster_nicht_null_wert_fuer_agentic_index_und_tempo(self) -> None:
        zeilen = [
            _zeile("modell-y", "openrouter", agentic_index=None, tempo_tok_s=None),
            _zeile("modell-y", "requesty", agentic_index=61, tempo_tok_s=87.5),
        ]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["agentic_index"], 61)
        self.assertEqual(m["tempo_tok_s"], 87.5)

    def test_stand_artificial_analysis_ist_juengstes_aa_stand_ueber_alle_zeilen(self) -> None:
        zeilen = [
            _zeile("modell-z", "claude", aa_stand="2026-08-25"),
            _zeile("modell-z", "ollama", aa_stand="2026-08-27"),
        ]
        ergebnis = katalog_sicht.aggregiere(zeilen)
        self.assertEqual(ergebnis["stand"]["artificial_analysis"], "2026-08-27")


class LokalUndEuFlagTest(unittest.TestCase):
    """C15 v2 Punkt 3: Zusatzfelder `lokal`/`eu_ohne_training`."""

    def test_lokal_true_bei_ollama_ohne_cloud_suffix(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("qwen3.5:9b", "ollama")])["modelle"]
        self.assertTrue(m["lokal"])

    def test_lokal_false_bei_ollama_cloud_suffix(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("glm-5.2:cloud", "ollama")])["modelle"]
        self.assertFalse(m["lokal"])

    def test_lokal_false_bei_dash_cloud_suffix(self) -> None:
        """Befund 2026-08-30 (Fix 1): `gemma4:31b-cloud` (kein reines `:cloud`-Tag) muss
        genauso als Cloud erkannt werden -- ueber den Fallback ohne `lokal`-Spalte."""
        [m] = katalog_sicht.aggregiere([_zeile("gemma4:31b-cloud", "ollama")])["modelle"]
        self.assertFalse(m["lokal"])

    def test_lokal_false_ohne_ollama_weg(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("claude-fable-5", "claude")])["modelle"]
        self.assertFalse(m["lokal"])

    def test_lokal_spalte_hat_vorrang_vor_dem_fallback(self) -> None:
        """Befund 2026-08-30 (Fix 2): liegt die `lokal`-Spalte (Migration 0008) vor, gewinnt
        SIE -- nicht `ist_ollama_cloud` auf einer moeglicherweise schon kanonisierten ID."""
        [m] = katalog_sicht.aggregiere(
            [_zeile("qwen3.5:9b", "ollama", lokal=False)])["modelle"]
        self.assertFalse(m["lokal"])
        [m] = katalog_sicht.aggregiere(
            [_zeile("glm-5.2:cloud", "ollama", lokal=True)])["modelle"]
        self.assertTrue(m["lokal"])

    def test_eu_ohne_training_true_bei_requesty(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("kimi-k3", "requesty")])["modelle"]
        self.assertTrue(m["eu_ohne_training"])

    def test_eu_ohne_training_false_ohne_requesty(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("kimi-k3", "openrouter")])["modelle"]
        self.assertFalse(m["eu_ohne_training"])


class VisionFeldTest(unittest.TestCase):
    """`vision` je Modellgruppe (Entscheid 2026-08-30 Nachtrag 6): ein Bezugsweg mit
    `vision=true` reicht, alle bekannten `false` bleibt `false`, kein bekannter Wert bleibt
    `None` (unbekannt, kein Sterne-Deckel)."""

    def test_ein_weg_mit_vision_true_reicht(self) -> None:
        zeilen = [_zeile("modell-x", "openrouter", vision=False),
                  _zeile("modell-x", "requesty", vision=True)]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertTrue(m["vision"])

    def test_alle_wege_false_bleibt_false(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("modell-x", "openrouter", vision=False)])["modelle"]
        self.assertFalse(m["vision"])

    def test_kein_weg_kennt_vision_bleibt_none(self) -> None:
        [m] = katalog_sicht.aggregiere([_zeile("modell-x", "openrouter")])["modelle"]
        self.assertIsNone(m["vision"])


class OllamaBasisDublettenTest(unittest.TestCase):
    """C15 v2 Punkt 3 (Befund 2026-08-30, Fix 3): eine taglose Ollama-Zeile (`gpt-oss`) ist
    eine Dublette der Groessenvariante (`gpt-oss:20b-cloud`) -- reale DB-Altlast (Stand
    2026-08-30: 9 solcher taglosen Zeilen), muss verworfen werden statt eine eigene, faelschlich
    `lokal:true` zeigende Gruppe zu bilden."""

    def test_basisname_wird_verworfen_wenn_variante_existiert(self) -> None:
        zeilen = [_zeile("gpt-oss", "ollama"), _zeile("gpt-oss:20b-cloud", "ollama")]
        ergebnis = katalog_sicht._ohne_ollama_basis_dubletten(zeilen)
        self.assertEqual([z["modell_id"] for z in ergebnis], ["gpt-oss:20b-cloud"])

    def test_basisname_bleibt_ohne_variante(self) -> None:
        """`qwen3:14b` (echt lokal) hat keine taglose Dublette -- bleibt unangetastet."""
        zeilen = [_zeile("qwen3", "ollama"), _zeile("nomic-embed-text:latest", "ollama")]
        ergebnis = katalog_sicht._ohne_ollama_basis_dubletten(zeilen)
        self.assertEqual({z["modell_id"] for z in ergebnis},
                          {"qwen3", "nomic-embed-text:latest"})

    def test_betrifft_nur_ollama(self) -> None:
        """Openrouter/Requesty kennen dieses Ollama-Tag-Muster nicht -- nie anfassen."""
        zeilen = [_zeile("gpt-oss", "openrouter"), _zeile("gpt-oss-20b", "openrouter")]
        self.assertEqual(katalog_sicht._ohne_ollama_basis_dubletten(zeilen), zeilen)

    def test_end_zu_end_ueber_aggregiere_kein_geist_eintrag_mehr(self) -> None:
        zeilen = [_zeile("gpt-oss", "ollama"),
                  _zeile("gpt-oss:20b-cloud", "ollama"),
                  _zeile("openai/gpt-oss-20b", "openrouter")]
        modelle = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(len(modelle), 1)
        self.assertFalse(modelle[0]["lokal"])
        self.assertEqual({a["name"] for a in modelle[0]["anbieter"]}, {"ollama", "openrouter"})


class KanonischeGruppierungTest(unittest.TestCase):
    """C15 v2 Punkt 3 (Befund 2026-08-30, Fix 3): `aggregiere()` gruppiert ueber
    `katalog.kanonische_id()`, nicht mehr `aa_schluessel()` -- Ollama-Cloud-Bezugswege muessen
    dieselbe Modellgruppe wie OpenRouter/Requesty treffen (Sterne/Preisvergleich)."""

    def test_gpt_oss_cloud_merged_mit_openrouter(self) -> None:
        zeilen = [_zeile("gpt-oss:20b-cloud", "ollama"),
                  _zeile("openai/gpt-oss-20b", "openrouter"),
                  _zeile("fireworks/gpt-oss-20b", "requesty")]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual({a["name"] for a in m["anbieter"]}, {"ollama", "openrouter", "requesty"})
        self.assertFalse(m["lokal"])

    def test_gemma4_cloud_merged_mit_google_instruct(self) -> None:
        zeilen = [_zeile("gemma4:31b-cloud", "ollama"),
                  _zeile("google/gemma-4-31b-it", "openrouter")]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual({a["name"] for a in m["anbieter"]}, {"ollama", "openrouter"})

    def test_glm_cloud_merged_mit_openrouter_glm(self) -> None:
        zeilen = [_zeile("glm-5.2:cloud", "ollama"), _zeile("z-ai/glm-5.2", "openrouter")]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual({a["name"] for a in m["anbieter"]}, {"ollama", "openrouter"})
        self.assertFalse(m["lokal"])  # Ollama-Weg ist die Cloud-Variante


class PersonaWegeTest(unittest.TestCase):
    def test_fehlender_block_liefert_leeres_dict(self) -> None:
        self.assertEqual(katalog_sicht.persona_wege({}), {})

    def test_falscher_typ_liefert_leeres_dict(self) -> None:
        self.assertEqual(katalog_sicht.persona_wege({"persona_wege": "kaputt"}), {})

    def test_flache_liste_bekommt_ebene_default_offen(self) -> None:
        block = {"vico": [{"quelle": "claude", "modell": "claude-fable-5", "primaer": True}]}
        ergebnis = katalog_sicht.persona_wege({"persona_wege": block})
        self.assertEqual(ergebnis["vico"], [{"quelle": "claude", "modell": "claude-fable-5",
                                              "primaer": True, "ebene": "offen"}])

    def test_vorhandene_ebene_bleibt_unveraendert(self) -> None:
        block = {"cura": [{"quelle": "ollama", "modell": "qwen3.5:9b", "primaer": True, "ebene": "geschuetzt"}]}
        ergebnis = katalog_sicht.persona_wege({"persona_wege": block})
        self.assertEqual(ergebnis["cura"][0]["ebene"], "geschuetzt")

    def test_alte_wege_huelle_bleibt_erhalten_ebene_wird_ergaenzt(self) -> None:
        block = {"vico": {"rolle": "Consulting", "wege": [{"quelle": "claude", "modell": "claude-sonnet-5", "primaer": True}]}}
        ergebnis = katalog_sicht.persona_wege({"persona_wege": block})
        self.assertEqual(ergebnis["vico"]["rolle"], "Consulting")
        self.assertEqual(ergebnis["vico"]["wege"][0]["ebene"], "offen")

    def test_fehlende_datei_bricht_nicht_ab(self) -> None:
        alt = katalog_sicht.MODELLE_PFAD
        katalog_sicht.MODELLE_PFAD = alt.parent / "modelle-nicht-vorhanden.json"
        try:
            self.assertEqual(katalog_sicht.persona_wege(), {})
        finally:
            katalog_sicht.MODELLE_PFAD = alt


class LokalListeTest(unittest.TestCase):
    REGISTRY = {
        "modelle": {
            "glm-5.2:cloud": {"typ": "cloud", "gesamt": 5},
            "qwen3.5:9b": {"typ": "lokal", "gesamt": 3, "kommentar": "CURA-Kandidat"},
            "qwen3:14b": {"typ": "lokal", "gesamt": 3, "kommentar": "bestes lokales Coding"},
            "nomic-embed-text": {"typ": "lokal", "gesamt": None, "kommentar": "Embeddings"},
        },
        "persona_wege": {
            "cura": [
                {"quelle": "ollama", "modell": "minimax-m3:cloud", "primaer": True},
                {"quelle": "ollama", "modell": "qwen3.5:9b", "primaer": True, "ebene": "geschuetzt"},
            ],
        },
    }

    def test_nur_typ_lokal_erscheint(self) -> None:
        namen = [e["modellname"] for e in katalog_sicht.lokal_liste(self.REGISTRY)]
        self.assertNotIn("glm-5.2:cloud", namen)
        self.assertEqual(set(namen), {"qwen3.5:9b", "qwen3:14b", "nomic-embed-text"})

    def test_cura_primaer_kommt_aus_persona_wege_ebene_geschuetzt(self) -> None:
        eintraege = katalog_sicht.lokal_liste(self.REGISTRY)
        primaer = [e for e in eintraege if e["cura_primaer"]]
        self.assertEqual([e["modellname"] for e in primaer], ["qwen3.5:9b"])

    def test_alphabetisch_aufsteigend_unabhaengig_von_primaer_und_sterne(self) -> None:
        """Maintainer 2026-08-30 (ON-PREMISE-Kachel): Liste alphabetisch -- primaer/Sterne bleiben
        je Eintrag sichtbar (Chip/Tooltip), ordnen aber nicht mehr vor."""
        namen = [e["modellname"] for e in katalog_sicht.lokal_liste(self.REGISTRY)]
        self.assertEqual(namen, ["nomic-embed-text", "qwen3.5:9b", "qwen3:14b"])

    def test_sortiert_nach_angezeigtem_namen_nicht_roh_id(self) -> None:
        """Maintainer 2026-08-30 nach Sichtung: `hf.co/mradermacher/EuroLLM-...-GGUF` stand VOR
        `hf.co/unsloth/DeepSeek-...`, weil nach der Roh-ID sortiert wurde und nicht nach dem
        im Panel gezeigten Namen (modellAnzeigeName-Kurzform). Soll-Ordnung: D < E."""
        registry = {"modelle": {
            "hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q4_K_M": {"typ": "lokal", "gesamt": None},
            "hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M": {"typ": "lokal", "gesamt": None},
        }}
        namen = [e["modellname"] for e in katalog_sicht.lokal_liste(registry)]
        self.assertEqual(namen, ["hf.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF:Q4_K_M",
                                 "hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q4_K_M"])

    def test_leere_registry_liefert_leere_liste(self) -> None:
        self.assertEqual(katalog_sicht.lokal_liste({}), [])

    def test_ohne_geschuetzten_cura_weg_ist_kein_eintrag_primaer(self) -> None:
        registry = {"modelle": {"qwen3:14b": {"typ": "lokal", "gesamt": 3}},
                    "persona_wege": {"cura": [{"quelle": "ollama", "modell": "minimax-m3:cloud", "primaer": True}]}}
        eintraege = katalog_sicht.lokal_liste(registry)
        self.assertFalse(any(e["cura_primaer"] for e in eintraege))


class HoleKatalogTest(unittest.TestCase):
    def test_kombiniert_sql_ergebnis_und_registry(self) -> None:
        laufer = FakeLaufer({"modellkatalog": json.dumps([_zeile("claude-sonnet-5", "claude", eingabe_usd=2, ausgabe_usd=10)])})
        registry = {"persona_wege": {"vico": {"wege": []}}, "modelle": {"qwen3.5:9b": {"typ": "lokal", "gesamt": 3}}}
        ergebnis = katalog_sicht.hole_katalog(laufer=laufer, registry=registry)
        self.assertEqual([m["id"] for m in ergebnis["modelle"]], ["claude-sonnet-5"])
        self.assertEqual(ergebnis["persona_wege"], {"vico": {"wege": []}})
        self.assertEqual([e["modellname"] for e in ergebnis["lokal_liste"]], ["qwen3.5:9b"])

    def test_speicherfehler_wird_nicht_geschluckt(self) -> None:
        def wirft(sql, zeitlimit_s=8):
            raise speicher.SpeicherFehler("nicht erreichbar")
        with self.assertRaises(speicher.SpeicherFehler):
            katalog_sicht.hole_katalog(laufer=wirft, registry={})


class ApiModellkatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def test_erfolg_liefert_kontraktform(self) -> None:
        web.LAUFER = FakeLaufer({"modellkatalog": json.dumps([_zeile("claude-sonnet-5", "claude", eingabe_usd=2, ausgabe_usd=10)])})
        antwort = self.client.get("/api/modellkatalog")
        self.assertEqual(antwort.status_code, 200)
        body = antwort.json()
        self.assertIn("stand", body)
        self.assertIn("modelle", body)
        self.assertEqual(body["modelle"][0]["id"], "claude-sonnet-5")

    def test_db_fehler_liefert_saubere_fehlerantwort_kein_stacktrace(self) -> None:
        def wirft(sql, zeitlimit_s=8):
            raise speicher.SpeicherFehler("psql nicht erreichbar")
        web.LAUFER = wirft
        antwort = self.client.get("/api/modellkatalog")
        self.assertEqual(antwort.status_code, 502)
        body = antwort.json()
        self.assertIn("detail", body)
        self.assertNotIn("Traceback", body["detail"])


class ApiModellkatalogAktualisierenTest(unittest.TestCase):
    """C15 v2 Punkt 4 -- Muster POST/GET /api/sitzung/{id}/pruefen (In-Flight-Guard per
    Modul-Lock). `katalog.py` selbst wird per Monkeypatch von `_katalog_modul()` ersetzt: kein
    Netz, keine DB."""

    def setUp(self) -> None:
        self.client = TestClient(web.app)
        self._alt_modul = web._katalog_modul
        web._katalog_lauf_seit = None
        web._katalog_letzter_fehler = None
        web._katalog_lauf_erfolgreich = False

    def tearDown(self) -> None:
        web._katalog_modul = self._alt_modul
        web._katalog_lauf_seit = None
        web._katalog_letzter_fehler = None
        web._katalog_lauf_erfolgreich = False

    def test_get_ohne_vorherigen_lauf_liefert_bereit(self) -> None:
        antwort = self.client.get("/api/modellkatalog/aktualisieren")
        self.assertEqual(antwort.json(), {"status": "bereit", "detail": None})

    def test_post_meldet_laeuft_bei_bereits_aktivem_lauf(self) -> None:
        web._katalog_lauf_seit = "2026-08-28T00:00:00+00:00"
        antwort = self.client.post("/api/modellkatalog/aktualisieren")
        self.assertEqual(antwort.json(), {"status": "laeuft"})

    def test_post_startet_lauf_und_uebergibt_alle_anbieter_mit_db(self) -> None:
        gesehen = {}

        def fake_befehl(namensraum):
            gesehen["anbieter"] = namensraum.anbieter
            gesehen["db"] = namensraum.db

        web._katalog_modul = lambda: SimpleNamespace(befehl_katalog_update=fake_befehl)
        antwort = self.client.post("/api/modellkatalog/aktualisieren")
        self.assertEqual(antwort.json(), {"status": "gestartet"})
        for _ in range(50):
            if "anbieter" in gesehen:
                break
            time.sleep(0.02)
        self.assertIsNone(gesehen["anbieter"])  # alle Quellen, kein Filter
        self.assertTrue(gesehen["db"])  # mit DB-Wirkung

    def test_lauf_erfolgreich_setzt_status_fertig(self) -> None:
        web._katalog_modul = lambda: SimpleNamespace(befehl_katalog_update=lambda ns: None)
        web._katalog_aktualisieren_hintergrund()
        self.assertEqual(self.client.get("/api/modellkatalog/aktualisieren").json(),
                          {"status": "fertig", "detail": None})

    def test_fehlende_katalog_funktion_ist_fail_open_und_meldet_fehler(self) -> None:
        """katalog.befehl_katalog_update kann waehrend des parallelen Baus noch fehlen --
        Fail-open statt Absturz, mit erklaerendem `detail` (Task-Vorgabe Punkt 4)."""
        web._katalog_modul = lambda: SimpleNamespace()
        web._katalog_aktualisieren_hintergrund()
        antwort = self.client.get("/api/modellkatalog/aktualisieren").json()
        self.assertEqual(antwort["status"], "fehler")
        self.assertIn("befehl_katalog_update", antwort["detail"])

    def test_fehler_im_lauf_wird_abgefangen_und_gemeldet(self) -> None:
        def wirft(namensraum):
            raise RuntimeError("Artificial Analysis nicht erreichbar")

        web._katalog_modul = lambda: SimpleNamespace(befehl_katalog_update=wirft)
        web._katalog_aktualisieren_hintergrund()
        antwort = self.client.get("/api/modellkatalog/aktualisieren").json()
        self.assertEqual(antwort["status"], "fehler")
        self.assertIn("Artificial Analysis nicht erreichbar", antwort["detail"])


class ScoreTest(unittest.TestCase):
    """`_score()` (Entscheid 2026-08-30 Nachtrag 6): Mittel aus aa_index/coding_index, fehlt
    einer -- nur der andere, fehlen beide -- nicht berechenbar."""

    def test_beide_vorhanden_ist_das_mittel(self) -> None:
        self.assertEqual(katalog_sicht._score(60, 80), 70.0)

    def test_nur_aa_index_zaehlt_allein(self) -> None:
        self.assertEqual(katalog_sicht._score(24, None), 24.0)

    def test_nur_coding_index_zaehlt_allein(self) -> None:
        self.assertEqual(katalog_sicht._score(None, 59), 59.0)

    def test_beide_fehlen_ist_nicht_berechenbar(self) -> None:
        self.assertIsNone(katalog_sicht._score(None, None))


class SterneAusScoreTest(unittest.TestCase):
    """`_sterne_aus_score()` (Entscheid 2026-08-30 Nachtrag 6): Boden 45, oben linear 3,0..5,0
    bis zum besten Score, unten linear 0,5..3,0 -- ersetzt die Quintil-/Kontext-Formel aus
    Nachtrag 2/4 vollstaendig. `best` in diesen Tests = der hoechste Score der Beispieltabelle
    (`claude-opus-5`, 70,5), s. `AutomatischeSterneImKatalogTest` fuer den Integrationstest."""

    def test_score_gleich_best_ist_fuenf_sterne(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(70.5, 70.5), 5.0)

    def test_score_gleich_boden_ist_drei_sterne(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(45.0, 70.5), 3.0)

    def test_score_null_ist_ein_halber_stern(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(0.0, 70.5), 0.5)

    def test_score_none_ist_nicht_berechenbar(self) -> None:
        self.assertIsNone(katalog_sicht._sterne_aus_score(None, 70.5))

    def test_best_gleich_boden_gibt_drei_sterne_ohne_nulldivision(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(45.0, 45.0), 3.0)

    def test_kein_bester_score_gibt_drei_sterne_am_boden(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(45.0, None), 3.0)

    def test_gf_tabelle_gpt_5_6_sol(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(61, 77), 70.5), 5.0)

    def test_gf_tabelle_glm_5_3_vor_dem_vision_deckel(self) -> None:
        roh = katalog_sicht._sterne_aus_score(katalog_sicht._score(60, 75), 70.5)
        self.assertGreaterEqual(roh, 4.5)  # Deckel auf 4,0 greift erst in _mit_vision_deckel

    def test_gf_tabelle_gpt_5_6_terra(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(57, 77), 70.5), 4.5)

    def test_gf_tabelle_gpt_5_6_luna(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(52, 71), 70.5), 4.5)

    def test_gf_tabelle_minimax_m3(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(45, 59), 70.5), 3.5)

    def test_gf_tabelle_mistral_medium_3_5(self) -> None:
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(30, 47), 70.5), 2.5)

    def test_gf_tabelle_claude_haiku_score_unter_boden(self) -> None:
        """Tabelle nennt 1,5 fuer `claude-haiku-4-5` (24/None); die woertliche Formel
        (0,5 + 2,5*24/45 = 1,8333, kaufmaennisch auf 0,5-Schritte gerundet) ergibt rechnerisch
        2,0 -- eine halbe Stern-Stufe hoeher. Sieben der acht Beispiele treffen exakt
        (s. uebrige `test_gf_tabelle_*`); dieser Test dokumentiert die Abweichung bewusst, statt
        sie stillschweigend zu uebernehmen (an Maintainer zur Gegenpruefung gemeldet, s. Bericht)."""
        self.assertEqual(katalog_sicht._sterne_aus_score(katalog_sicht._score(24, None), 70.5), 2.0)


class VisionDeckelTest(unittest.TestCase):
    """`_mit_vision_deckel()` (Entscheid 2026-08-30 Nachtrag 6): `vision=False` deckelt bei
    4,0, `vision=None` (unbekannt) bleibt ohne Deckel."""

    def test_vision_false_deckelt_bei_4(self) -> None:
        self.assertEqual(katalog_sicht._mit_vision_deckel(5.0, False), 4.0)
        self.assertEqual(katalog_sicht._mit_vision_deckel(3.5, False), 3.5)  # unter dem Deckel bleibt es

    def test_vision_none_bleibt_ohne_deckel(self) -> None:
        self.assertEqual(katalog_sicht._mit_vision_deckel(5.0, None), 5.0)

    def test_vision_true_bleibt_ohne_deckel(self) -> None:
        self.assertEqual(katalog_sicht._mit_vision_deckel(5.0, True), 5.0)

    def test_sterne_none_bleibt_none(self) -> None:
        self.assertIsNone(katalog_sicht._mit_vision_deckel(None, False))


class FamilieTest(unittest.TestCase):
    """Modell-Familie = Hersteller + Produktlinie + Stufe (Entscheid 2026-08-30 final,
    ersetzt Abnahme 2026-08-30 A): Stufen-Woerter (`_STUFE_WOERTER`, z. B. `mini`/`flash`/
    `opus`/`haiku`) gehoeren jetzt ZUR Familie -- nur reine Modifikatoren
    (`_MODIFIKATOR_WOERTER`, z. B. `preview`/`instruct`/`exp`) fallen weg. `claude-haiku` ist
    darum eine eigene Familie neben `claude-opus`/`claude-sonnet`/`claude-fable`."""

    def test_stufenwort_bildet_jetzt_eigene_familienlinie(self) -> None:
        """`glm-5.3-flash` und `glm-5.3` sind seit dem finalen Entscheid 2026-08-30
        VERSCHIEDENE Familien -- `flash` ist ein Stufen-Wort und gehoert jetzt ZUR Familie
        (Umkehr von Abnahme 2026-08-30 A, wo Stufen-Woerter noch wegfielen)."""
        self.assertEqual(katalog_sicht.familie("glm-5.3-flash"), "glm-flash")
        self.assertEqual(katalog_sicht.familie("glm-5.3"), "glm")
        self.assertNotEqual(katalog_sicht.familie("glm-5.3-flash"), katalog_sicht.familie("glm-5.3"))

    def test_produkt_variante_bleibt_eigene_familie(self) -> None:
        """`oss` ist KEIN Stufenwort, sondern eine Produkt-Variante -- `gpt-oss` bleibt eine
        eigene Familie neben `gpt`."""
        self.assertEqual(katalog_sicht.familie("gpt-oss-20b"), "gpt-oss")
        self.assertNotEqual(katalog_sicht.familie("gpt-oss-20b"), katalog_sicht.familie("gpt-5.4"))

    def test_claude_stufen_namen_sind_je_eigene_familie(self) -> None:
        """`opus`/`sonnet`/`haiku`/`fable` sind Stufen-Woerter und gehoeren seit dem finalen
        Entscheid 2026-08-30 ZUR Familie -- `claude-opus`/`claude-sonnet`/`claude-haiku`/
        `claude-fable` sind VIER verschiedene Familien, keine gemeinsame `claude`-Familie mehr
        (Umkehr von Abnahme 2026-08-30 A: `claude-haiku-4-5` ist darum aktuell, nicht Legacy
        zu `claude-opus-5`)."""
        namen = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-opus-4-8", "claude-fable-5")
        self.assertEqual({katalog_sicht.familie(n) for n in namen},
                          {"claude-opus", "claude-sonnet", "claude-haiku", "claude-fable"})

    def test_gleiche_version_verschiedene_grossen_selbe_familie(self) -> None:
        """`gpt-oss-20b`/`gpt-oss-120b`: die Groesse (`20b`/`120b`) ist weder Version noch
        Familienmerkmal (Task-Vorgabe) -- EINE Familie, `neueste_je_familie()` haelt trotzdem
        BEIDE als Gleichstand (kein Nachfolgerverhaeltnis, s. NeuesteJeFamilieTest)."""
        self.assertEqual(katalog_sicht.familie("gpt-oss-20b"), katalog_sicht.familie("gpt-oss-120b"))

    def test_gemini_flash_preview_gehoert_zur_gemini_flash_familie(self) -> None:
        """`flash` ist seit dem finalen Entscheid 2026-08-30 ein Familienmerkmal, `preview`
        bleibt ein reiner Modifikator und faellt weg -- `gemini-3-flash-preview` gehoert zur
        Familie `gemini-flash`, nicht mehr zur blossen `gemini`-Familie."""
        self.assertEqual(katalog_sicht.familie("gemini-3-flash-preview"), "gemini-flash")
        self.assertEqual(katalog_sicht.familie("gemini-3.7-flash"), "gemini-flash")
        self.assertNotEqual(katalog_sicht.familie("gemini-3-flash-preview"), katalog_sicht.familie("gemini-3"))

    def test_deepseek_v_und_r_marker_gehoeren_zur_deepseek_familie(self) -> None:
        """`v3.2`/`r1` sind reine DeepSeek-Versionsmarker (Praefix faellt weg, unveraendert seit
        Abnahme 2026-08-30 A) und bleiben in der Familie `deepseek` -- `pro` ist dagegen seit
        dem finalen Entscheid 2026-08-30 ein Stufen-Wort und gehoert ZUR Familie:
        `deepseek-v4-pro` bildet darum eine EIGENE Familie `deepseek-pro`, keine Legacy-Version
        von `deepseek-v3.2`/`deepseek-r1` mehr."""
        namen = ("deepseek-v3.2-exp", "deepseek-v3.2", "deepseek-r1")
        self.assertEqual({katalog_sicht.familie(n) for n in namen}, {"deepseek"})
        self.assertEqual(katalog_sicht.familie("deepseek-v4-pro"), "deepseek-pro")

    def test_mistral_large_und_small_sind_jetzt_verschiedene_familien(self) -> None:
        """`large`/`small` sind Stufen-Woerter und gehoeren seit dem finalen Entscheid
        2026-08-30 ZUR Familie -- `mistral-large-3` und `mistral-small-3.2-24b-instruct` sind
        darum VERSCHIEDENE Familien (Umkehr von Task-Vorgabe/Abnahme A: `mistral-large-3`
        ist jetzt aktuell statt Legacy)."""
        self.assertNotEqual(katalog_sicht.familie("mistral-large-3"),
                             katalog_sicht.familie("mistral-small-3.2-24b-instruct"))
        self.assertEqual(katalog_sicht.familie("mistral-large-3"), "mistral-large")
        self.assertEqual(katalog_sicht.familie("mistral-small-3.2-24b-instruct"), "mistral-small")

    def test_reseller_praefix_ohne_slash_faellt_weg(self) -> None:
        """`parasail-deepseek-v4-flash` (aus `parasail/parasail-deepseek-v4-flash`) verliert den
        Reseller-Praefix `parasail` (Task-Vorgabe, unveraendert) -- `flash` bleibt seit dem
        finalen Entscheid 2026-08-30 als Stufen-Wort Teil der Familie: Ergebnis
        `deepseek-flash`, nicht mehr die blosse `deepseek`-Familie."""
        self.assertEqual(katalog_sicht.familie("parasail-deepseek-v4-flash"), "deepseek-flash")


class ProduktlinieTest(unittest.TestCase):
    """`produktlinie()` = `familie()` OHNE Stufen-Woerter (Festlegung 2026-08-30,
    generationen.json) -- die kuratierten Generations-Schwellen gelten je Linie, nicht je
    Stufe."""

    def test_gpt_mini_stufe_faellt_weg(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("gpt-5.4-mini"), "gpt")

    def test_gpt_4o_mini_bleibt_bei_der_4o_linie(self) -> None:
        """`4o` ist KEIN Stufenwort und bleibt stehen -- `gpt-4o`/`gpt-4o-mini` teilen die
        Linie `gpt-4o`, getrennt von der reinen `gpt`-Linie."""
        self.assertEqual(katalog_sicht.produktlinie("gpt-4o-mini"), "gpt-4o")
        self.assertEqual(katalog_sicht.produktlinie("gpt-4o-2024-11-20"), "gpt-4o")

    def test_claude_stufen_teilen_sich_die_claude_linie(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("claude-haiku-4-5"), "claude")
        self.assertEqual(katalog_sicht.produktlinie("claude-opus-4-8"), "claude")

    def test_glm_vision_marker_5v_verkuerzt_auf_die_v_linie(self) -> None:
        """`5v` (Ziffer+Versions-Marker-Buchstabe `v`, glm-5v = Vision-Variante) wird auf den
        Marker-Buchstaben verkuerzt -- Ziel-Linie `glm-v` (in generationen.json als abgeloeste
        Vision-Linie gefuehrt, Schwelle 99), nicht die woertliche `glm-5v`."""
        self.assertEqual(katalog_sicht.produktlinie("glm-5v-turbo"), "glm-v")

    def test_command_r_plus_bleibt_bei_der_command_r_linie(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("command-r-plus-08-2024"), "command-r")

    def test_o_stufen_teilen_sich_die_o_linie(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("o1"), "o")
        self.assertEqual(katalog_sicht.produktlinie("o3-pro"), "o")
        self.assertEqual(katalog_sicht.produktlinie("o4-mini"), "o")

    def test_deepseek_v_und_pro_teilen_sich_die_deepseek_linie(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("deepseek-v3.2"), "deepseek")
        self.assertEqual(katalog_sicht.produktlinie("deepseek-v4-pro"), "deepseek")

    def test_qwen_plus_und_max_teilen_sich_die_qwen_linie(self) -> None:
        self.assertEqual(katalog_sicht.produktlinie("qwen3.7-plus"), "qwen")
        self.assertEqual(katalog_sicht.produktlinie("qwen3.8-max"), "qwen")


class VersionTest(unittest.TestCase):
    """Versions-Tupel aus reinen Ziffern-Tokens, Vergleichbar per Tupel-Ordnung
    (Entscheid 2026-08-30 A)."""

    def test_punktversion_absteigend_vergleichbar(self) -> None:
        self.assertGreater(katalog_sicht.version("glm-5.3"), katalog_sicht.version("glm-5.2"))

    def test_bindestrich_version_kleiner_als_einzelziffer(self) -> None:
        self.assertLess(katalog_sicht.version("claude-opus-4-8"), katalog_sicht.version("claude-opus-5"))

    def test_ohne_ziffern_leeres_tupel(self) -> None:
        self.assertEqual(katalog_sicht.version("gpt-oss"), ())

    def test_glatt_verklebte_version_qwen3_punkt_8(self) -> None:
        """`qwen3.8` -> `(3, 0.8)` (Task-Vorgabe: Version = erstes Zahlen-Token, auch verklebt)."""
        self.assertEqual(katalog_sicht.version("qwen3.8"), (3, 0.8))

    def test_deepseek_v_und_r_marker_liefern_die_richtige_version(self) -> None:
        self.assertEqual(katalog_sicht.version("deepseek-v3.2"), (3, 0.2))
        self.assertEqual(katalog_sicht.version("deepseek-r1"), (1,))
        self.assertEqual(katalog_sicht.version("deepseek-v4-pro"), (4,))

    def test_gemma4_glued_version(self) -> None:
        self.assertEqual(katalog_sicht.version("gemma4"), (4,))

    def test_groessen_tag_ist_weder_version_noch_familie(self) -> None:
        """Task-Vorgabe-Beispiel `2.4t-a95b`: die Baugroesse darf nicht als zweite Versionsstelle
        durchrutschen -- `qwen3.8-2.4t-a95b` bleibt Version `(3, 0.8)`, Familie `qwen`."""
        self.assertEqual(katalog_sicht.version("qwen3.8-2.4t-a95b"), (3, 0.8))
        self.assertEqual(katalog_sicht.familie("qwen3.8-2.4t-a95b"), "qwen")

    def test_snapshot_datum_ist_keine_version(self) -> None:
        """Live-Katalog-Befund (Fix nach erster Stichprobe): `2024-11-20` etc. sind Bindestrich-
        Schnappschussdaten, kein Versionssprung -- sonst ueberstrahlt das Jahr (2024/2025) jede
        echte Version und reisst z. B. `qwen-plus-2025-07-28` faelschlich vor `qwen3.8` an die
        Spitze der Familie."""
        self.assertEqual(katalog_sicht.version("qwen-plus-2025-07-28"), ())
        self.assertEqual(katalog_sicht.version("gpt-4o-2024-11-20"), ())

    def test_4o_ist_keine_baugroesse_eigene_familie(self) -> None:
        """`4o` (GPT-4o) ist Ziffer+Buchstabe wie ein Groessentag, aber `o` ist keine
        Parameter-Einheit (b/k/m/t) -- bleibt Teil der Familie, `gpt-4o` ist darum eine EIGENE
        Familie neben `gpt`, kollidiert nicht mit `gpt-5.x`."""
        self.assertEqual(katalog_sicht.familie("gpt-4o-2024-11-20"), "gpt-4o")
        self.assertNotEqual(katalog_sicht.familie("gpt-4o-2024-11-20"), katalog_sicht.familie("gpt-5.6-sol"))


class NeuesteJeFamilieTest(unittest.TestCase):
    """`neueste_je_familie()` (Entscheid 2026-08-30 B) -- Menge der IDs, die je Familie
    fuehren."""

    def test_glm_53_und_53_flash_gleichauf_52_legacy(self) -> None:
        """`glm-5.3`/`glm-5.3-flash` sind seit Abnahme 2026-08-30 A dieselbe Familie (`flash`
        ist Stufenwort) UND haben dieselbe Version -- echter Gleichstand, `glm-5.2` (aeltere
        Version) bleibt aussen vor. Ergebnis-Erwartung: "glm-5.3 + glm-5.3-flash bewertet, glm-5.2
        Legacy"."""
        neueste = katalog_sicht.neueste_je_familie(["glm-5.2", "glm-5.3", "glm-5.3-flash"])
        self.assertEqual(neueste, {"glm-5.3", "glm-5.3-flash"})

    def test_claude_opus_5_ist_neueste_vor_4_8(self) -> None:
        neueste = katalog_sicht.neueste_je_familie(["claude-opus-4-8", "claude-opus-5"])
        self.assertEqual(neueste, {"claude-opus-5"})

    def test_zwei_groessen_derselben_version_beide_neueste(self) -> None:
        """gpt-oss-20b/-120b (Task-Vorgabe): zwei Groessen derselben Version -> BEIDE
        'neueste', kein Legacy zwischen den Groessen -- auch nachdem sie in dieselbe Familie
        gefallen sind (die Baugroesse zaehlt fuer keine der beiden mehr als Version)."""
        neueste = katalog_sicht.neueste_je_familie(["gpt-oss-20b", "gpt-oss-120b"])
        self.assertEqual(neueste, {"gpt-oss-20b", "gpt-oss-120b"})

    def test_gemini_flash_preview_einzelne_familie_ist_immer_neueste(self) -> None:
        neueste = katalog_sicht.neueste_je_familie(["gemini-3-flash-preview"])
        self.assertEqual(neueste, {"gemini-3-flash-preview"})

    def test_gpt_stufen_sind_je_eigene_familie_alle_aktuell(self) -> None:
        """Seit dem finalen Entscheid 2026-08-30 ist jedes Stufen-Wort eine eigene Familie --
        `gpt-5.4-mini`/`gpt-5.4-nano`/`gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna`/
        `gpt-5.6-luna-pro` sind je einziger Vertreter ihrer Familie und darum alle aktuell. Nur
        die stufenlose Familie `gpt` hat zwei Mitglieder (`gpt-5.4`/`gpt-5.5`) -- dort gewinnt
        `gpt-5.5` (Ergebnis-Erwartung Task-Vorgabe: `gpt-5.5` bleibt aktuell, `gpt-5.4-mini`
        aktuell, kein `gpt-5.6-mini` im Bestand)."""
        ids = ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5",
               "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-luna-pro"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano",
                                    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.6-luna-pro"})

    def test_gpt_5_4_mini_ist_aktuell(self) -> None:
        """`gpt-5.4-mini` ist alleiniger Vertreter der Familie `gpt-mini` (kein `gpt-5.6-mini`
        im Bestand) -- darum aktuell, obwohl `gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna` in der
        stufenlosen Zaehlung neuere Hauptversionen tragen (eigene Familie, kein Vergleich)."""
        neueste = katalog_sicht.neueste_je_familie(
            ["gpt-5.4-mini", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
        self.assertIn("gpt-5.4-mini", neueste)

    def test_claude_stufen_alle_je_eigene_familie_aktuell(self) -> None:
        """Seit dem finalen Entscheid 2026-08-30 sind `claude-opus`/`claude-sonnet`/
        `claude-haiku`/`claude-fable` VIER verschiedene Familien -- `claude-sonnet-5`,
        `claude-fable-5` und `claude-haiku-4-5` sind je einziger Vertreter ihrer Familie und
        darum aktuell; nur `claude-opus-4-8` ist Legacy zu `claude-opus-5` (gleiche Familie
        `claude-opus`, Version 4.8 < 5)."""
        ids = ["claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4-8", "claude-haiku-4-5"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5"})

    def test_claude_haiku_4_5_ist_aktuell(self) -> None:
        """`claude-haiku-4-5` ist alleiniger Vertreter der Familie `claude-haiku` (`haiku` ist
        seit dem finalen Entscheid 2026-08-30 Teil der Familie, nicht mehr nur `claude`) --
        darum aktuell, unabhaengig von `claude-opus-5`/`claude-sonnet-5` in anderen Familien."""
        neueste = katalog_sicht.neueste_je_familie(
            ["claude-haiku-4-5", "claude-opus-5", "claude-sonnet-5"])
        self.assertIn("claude-haiku-4-5", neueste)

    def test_deepseek_v4_pro_eigene_familie_v3_und_r1_bleiben_deepseek(self) -> None:
        """`pro` ist seit dem finalen Entscheid 2026-08-30 ein Stufen-Wort und gehoert ZUR
        Familie -- `deepseek-v4-pro` bildet darum eine EIGENE Familie `deepseek-pro` und ist
        immer aktuell, unabhaengig von der `deepseek`-Familie. Innerhalb `deepseek` bleibt
        `deepseek-r1` (Version 1) Legacy zu `deepseek-v3.2`/`deepseek-v3.2-exp` (Version 3.2,
        echter Gleichstand)."""
        ids = ["deepseek-v3.2-exp", "deepseek-v3.2", "deepseek-r1", "deepseek-v4-pro"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"deepseek-v4-pro", "deepseek-v3.2", "deepseek-v3.2-exp"})

    def test_mistral_large_3_ist_jetzt_aktuell_eigene_familie(self) -> None:
        """Umkehr der Task-Vorgabe-A-Erwartung: `large`/`small` gehoeren seit dem finalen
        Entscheid 2026-08-30 ZUR Familie -- `mistral-large-3` und
        `mistral-small-3.2-24b-instruct` sind darum VERSCHIEDENE Familien und beide aktuell,
        kein Legacy-Verhaeltnis mehr zwischeneinander."""
        ids = ["mistral-large-3", "mistral-small-3.2-24b-instruct"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"mistral-large-3", "mistral-small-3.2-24b-instruct"})

    def test_mistral_medium_3_5_ist_eigene_familie_neben_large_und_small(self) -> None:
        """`medium` ist seit dem finalen Entscheid 2026-08-30 ebenfalls ein Stufen-Wort --
        `mistral-medium-3-5` bildet eine EIGENE Familie `mistral-medium` und ist darum aktuell,
        ohne `mistral-large-3`/`mistral-small-3.2-24b-instruct` (je eigene Familie) zu schlagen
        oder zu verdraengen: alle drei bleiben gleichzeitig aktuell."""
        ids = ["mistral-large-3", "mistral-small-3.2-24b-instruct", "mistral-medium-3-5"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"mistral-large-3", "mistral-small-3.2-24b-instruct", "mistral-medium-3-5"})

    def test_bindestrich_versionierte_daten_dominieren_nicht_die_familie(self) -> None:
        """Live-Katalog-Befund: Mistral versioniert Snapshots als YYMM (`mistral-small-2603`) --
        ein alleinstehendes 4-stelliges Token ist ein Datum, keine Version, sonst stuende `2603`
        faelschlich vor `small-3.2` INNERHALB der (seit dem finalen Entscheid 2026-08-30
        eigenstaendigen) Familie `mistral-small`. `mistral-large-3` gehoert zur eigenen Familie
        `mistral-large` und ist unabhaengig davon immer aktuell."""
        ids = ["mistral-large-3", "mistral-small-3.2-24b-instruct", "mistral-small-2603"]
        neueste = katalog_sicht.neueste_je_familie(ids)
        self.assertEqual(neueste, {"mistral-large-3", "mistral-small-3.2-24b-instruct"})

    def test_llama_3_3_und_llama_4_varianten_kein_falsch_merge(self) -> None:
        """Stichprobe gegen Falsch-Merges: `llama-3.3-70b-instruct` (kein Modellname-Suffix)
        und `llama-4-maverick`/`llama-4-scout` (eigene Produktnamen) sind DREI verschiedene
        Familien -- keine davon wird faelschlich Legacy der anderen."""
        namen = ("llama-3.3-70b-instruct", "llama-4-maverick", "llama-4-scout")
        familien = {n: katalog_sicht.familie(n) for n in namen}
        self.assertEqual(len(set(familien.values())), 3)


class AutomatischeSterneImKatalogTest(unittest.TestCase):
    """Integration: `aggregiere()` haengt `sterne`/`status` je Modell an, relativ zum GESAMTEN
    uebergebenen Katalog (Entscheid 2026-08-30 Nachtrag 6)."""

    def test_zwei_modelle_relativ_zueinander_bewertet(self) -> None:
        zeilen = [
            _zeile("modell-schwach", "openrouter", aa_index=10, coding_index=10, kontext_k=64),
            _zeile("modell-stark", "openrouter", aa_index=90, coding_index=90, kontext_k=300),
        ]
        modelle = {m["id"]: m for m in katalog_sicht.aggregiere(zeilen)["modelle"]}
        self.assertEqual(modelle["modell-schwach"]["sterne"]["score"], 10.0)
        self.assertEqual(modelle["modell-stark"]["sterne"]["score"], 90.0)
        self.assertEqual(modelle["modell-stark"]["sterne"]["gesamt"], 5.0)  # bester Score -> 5,0
        self.assertIsNotNone(modelle["modell-schwach"]["sterne"]["gesamt"])
        self.assertEqual(modelle["modell-schwach"]["status"], "bewertet")
        self.assertEqual(modelle["modell-stark"]["status"], "bewertet")

    def test_neues_sota_modell_stuft_bestehendes_automatisch_herab(self) -> None:
        """Kernanforderung Maintainer: ein neues SOTA-Modell stuft alle anderen automatisch herunter,
        weil die Sterne relativ zum besten Score DES GESAMTEN aktuellen Katalogs berechnet
        werden."""
        basis = [_zeile("modell-a", "openrouter", aa_index=80, coding_index=80, kontext_k=200)]
        vorher = katalog_sicht.aggregiere(basis)["modelle"][0]["sterne"]["gesamt"]
        mit_sota = basis + [_zeile("modell-sota", "openrouter", aa_index=99, coding_index=99, kontext_k=200)]
        nachher = next(m for m in katalog_sicht.aggregiere(mit_sota)["modelle"]
                        if m["id"] == "modell-a")["sterne"]["gesamt"]
        self.assertEqual(vorher, 5.0)  # einziges Modell -> selbst der beste Score -> 5,0
        self.assertLess(nachher, vorher)  # jetzt das schwaechere von zweien -> heruntergestuft

    def test_modell_ohne_aa_werte_ist_latest_ohne_sterne(self) -> None:
        [m] = katalog_sicht.aggregiere(
            [_zeile("modell-ohne-aa", "ollama", aa_index=None, coding_index=None)])["modelle"]
        self.assertIsNone(m["sterne"]["score"])
        self.assertIsNone(m["sterne"]["gesamt"])
        self.assertIsNone(m["nachfolger"])  # einziges Modell der Familie -> aktuell
        self.assertEqual(m["status"], "latest")  # aktuell, aber keine Sterne berechenbar

    def test_manuelle_registry_sterne_landen_als_eigener_test_nicht_als_basis(self) -> None:
        registry = {"modelle": {"minimax-m3:cloud": {
            "coding": 3, "reasoning": 3, "gesamt": 5, "kommentar": "graphify-Test"}}}
        [m] = katalog_sicht.aggregiere(
            [_zeile("minimax-m3:cloud", "ollama", aa_index=10, coding_index=10, kontext_k=64)],
            registry)["modelle"]
        self.assertEqual(m["sterne"]["gesamt"], 1.0)  # Score 10 (< Boden 45) -- absolute Formel, NICHT die Registry-5
        self.assertEqual(m["sterne"]["manuell"],
                          {"coding": 3, "reasoning": 3, "gesamt": 5, "kommentar": "graphify-Test"})

    def test_ohne_manuellen_registry_eintrag_ist_manuell_none(self) -> None:
        [m] = katalog_sicht.aggregiere(
            [_zeile("unbekanntes-modell", "openrouter", aa_index=50, coding_index=50)])["modelle"]
        self.assertIsNone(m["sterne"]["manuell"])

    def test_aeltere_version_bekommt_nachfolger_und_bleibt_unbewertet(self) -> None:
        """Entscheid 2026-08-30 B: `glm-5.2` (aeltere Version) zeigt auf `glm-5.3` (neueste),
        Sterne bleiben `null` und `status` ist `legacy` -- nur die neueste Version je Familie
        bekommt ueberhaupt Sterne (Entscheid 2026-08-30 Nachtrag 6)."""
        zeilen = [
            _zeile("glm-5.2", "openrouter", aa_index=40, coding_index=40),
            _zeile("glm-5.3", "openrouter", aa_index=60, coding_index=60),
        ]
        modelle = {m["id"]: m for m in katalog_sicht.aggregiere(zeilen)["modelle"]}
        self.assertEqual(modelle["glm-5.2"]["nachfolger"], "glm-5.3")
        self.assertIsNone(modelle["glm-5.2"]["sterne"]["gesamt"])
        self.assertEqual(modelle["glm-5.2"]["status"], "legacy")
        self.assertIsNone(modelle["glm-5.3"]["nachfolger"])
        self.assertIsNotNone(modelle["glm-5.3"]["sterne"]["gesamt"])
        self.assertEqual(modelle["glm-5.3"]["status"], "bewertet")

    def test_vision_false_deckelt_gesamtsterne_im_katalog(self) -> None:
        zeilen = [_zeile("modell-ohne-bild", "openrouter", aa_index=99, coding_index=99, vision=False)]
        [m] = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual(m["vision"], False)
        self.assertEqual(m["sterne"]["gesamt"], 4.0)  # einziges/bestes Modell waere 5,0, gedeckelt auf 4,0

    def test_vision_unbekannt_bleibt_ohne_deckel(self) -> None:
        [m] = katalog_sicht.aggregiere(
            [_zeile("modell-ohne-vision-info", "openrouter", aa_index=99, coding_index=99)])["modelle"]
        self.assertIsNone(m["vision"])
        self.assertEqual(m["sterne"]["gesamt"], 5.0)


class GfSterneTabelleTest(unittest.TestCase):
    """Erwartungs-Tests aus der Tabelle (Entscheid 2026-08-30 Nachtrag 6, alle acht
    Beispiele als EIN aktueller Katalog, `best` = claude-opus-5 mit Score 70,5)."""

    ZEILEN = [
        _zeile("claude-opus-5", "claude", aa_index=63, coding_index=78, vision=True),
        _zeile("gpt-5.6-sol", "openrouter", aa_index=61, coding_index=77),
        _zeile("glm-5.3", "openrouter", aa_index=60, coding_index=75, vision=False),
        _zeile("gpt-5.6-terra", "openrouter", aa_index=57, coding_index=77),
        _zeile("gpt-5.6-luna", "openrouter", aa_index=52, coding_index=71),
        _zeile("minimax-m3", "ollama", aa_index=45, coding_index=59, vision=False),
        _zeile("mistral-medium-3-5", "openrouter", aa_index=30, coding_index=47),
        _zeile("claude-haiku-4-5", "claude", aa_index=24, coding_index=None),
    ]
    ERWARTET = {
        "claude-opus-5": 5.0, "gpt-5.6-sol": 5.0, "glm-5.3": 4.0, "gpt-5.6-terra": 4.5,
        "gpt-5.6-luna": 4.5, "minimax-m3": 3.5, "mistral-medium-3-5": 2.5,
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.modelle = {m["id"]: m for m in katalog_sicht.aggregiere(cls.ZEILEN)["modelle"]}

    def test_sieben_der_acht_gf_beispiele_treffen_exakt(self) -> None:
        for modell_id, erwartet in self.ERWARTET.items():
            with self.subTest(modell_id=modell_id):
                self.assertEqual(self.modelle[modell_id]["sterne"]["gesamt"], erwartet)

    def test_claude_haiku_ist_jetzt_eigene_familie_und_aktuell(self) -> None:
        """`claude-haiku-4-5` und `claude-opus-5` sind seit dem finalen Entscheid 2026-08-30
        VERSCHIEDENE Familien (`claude-haiku`/`claude-opus` -- `haiku`/`opus` sind Stufen-Woerter
        und gehoeren jetzt ZUR Familie, Umkehr von Abnahme 2026-08-30 A/Nachtrag 5) --
        `claude-haiku-4-5` ist darum in DIESEM gemeinsamen Katalog selbst aktuell, kein Legacy
        zu `claude-opus-5`. Die reine Score-Formel fuer den Tabellenwert (Score 24, nur AA)
        steht isoliert in `SterneAusScoreTest`/`ScoreTest`."""
        haiku = self.modelle["claude-haiku-4-5"]
        self.assertEqual(haiku["sterne"]["score"], 24.0)  # Score selbst bleibt berechnet
        self.assertIsNone(haiku["nachfolger"])
        self.assertEqual(haiku["status"], "bewertet")
        self.assertEqual(haiku["sterne"]["gesamt"], 2.0)

    def test_alle_zeilen_bleiben_im_ergebnis_auch_die_legacy_zeile(self) -> None:
        """Task-Vorgabe: 'alle bestehenden Zeilen bleiben sichtbar' -- die aeltere Version wird
        NICHT aus `modelle` entfernt."""
        zeilen = [
            _zeile("claude-opus-4-8", "claude", aa_index=70, coding_index=70),
            _zeile("claude-opus-5", "claude", aa_index=90, coding_index=90),
        ]
        modelle = katalog_sicht.aggregiere(zeilen)["modelle"]
        self.assertEqual({m["id"] for m in modelle}, {"claude-opus-4-8", "claude-opus-5"})

    def test_verschiedene_groessen_beide_bewertet_kein_nachfolger(self) -> None:
        """gpt-oss-20b/-120b (Task-Vorgabe): zwei Groessen derselben Version -- KEIN Legacy
        zwischen den Groessen, beide bekommen eigene Sterne."""
        zeilen = [
            _zeile("gpt-oss-20b", "openrouter", aa_index=30, coding_index=30),
            _zeile("gpt-oss-120b", "openrouter", aa_index=80, coding_index=80),
        ]
        modelle = {m["id"]: m for m in katalog_sicht.aggregiere(zeilen)["modelle"]}
        self.assertIsNone(modelle["gpt-oss-20b"]["nachfolger"])
        self.assertIsNone(modelle["gpt-oss-120b"]["nachfolger"])
        self.assertIsNotNone(modelle["gpt-oss-20b"]["sterne"]["gesamt"])
        self.assertIsNotNone(modelle["gpt-oss-120b"]["sterne"]["gesamt"])


class GenerationStatusTest(unittest.TestCase):
    """`generation_status()` -- reine Funktion, Festlegung 2026-08-30: kuratierte
    Generations-Schwellen je Produktlinie mit Vorrang vor der automatischen Versionsregel."""

    LINIEN = {"gpt": 5.6, "claude": 5, "o": 99}
    AUSNAHMEN = {"claude-haiku-4-5"}
    EXPLIZIT = {"mistral-large-2407": "mistral-large-2512"}

    def test_explizit_legacy_schlaegt_alles(self) -> None:
        status, nachfolger = katalog_sicht.generation_status(
            "mistral-large-2407", (), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual((status, nachfolger), ("legacy", "mistral-large-2512"))

    def test_ausnahme_aktuell_schlaegt_die_schwelle(self) -> None:
        status, nachfolger = katalog_sicht.generation_status(
            "claude-haiku-4-5", (4, 0.5), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual((status, nachfolger), ("aktuell", None))

    def test_version_unter_der_schwelle_ist_legacy_ohne_nachfolger(self) -> None:
        """Nachfolger fuer Punkt c traegt der Aufrufer (`_mit_kuratierten_generationen`)
        score-basiert nach -- die reine Funktion liefert hier `None`."""
        status, nachfolger = katalog_sicht.generation_status(
            "gpt-5.5", (5, 0.5), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual((status, nachfolger), ("legacy", None))

    def test_version_am_der_schwelle_ist_aktuell(self) -> None:
        status, _ = katalog_sicht.generation_status(
            "gpt-5.6-sol", (5, 0.6), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual(status, "aktuell")

    def test_linie_ohne_eintrag_liefert_kein_urteil(self) -> None:
        status, nachfolger = katalog_sicht.generation_status(
            "nemotron-3-ultra", (3,), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual((status, nachfolger), (None, None))

    def test_schwelle_99_ist_immer_legacy(self) -> None:
        status, _ = katalog_sicht.generation_status(
            "o4-mini", (4,), self.LINIEN, self.AUSNAHMEN, self.EXPLIZIT)
        self.assertEqual(status, "legacy")


class KuratierteGenerationImKatalogTest(unittest.TestCase):
    """Integration ueber `aggregiere(zeilen, generationen=...)` (Festlegung 2026-08-30,
    generationen.json) -- Stichprobe aus der Task-Vorgabe, ein Score je Zeile, damit
    `status`/`sterne.gesamt` real durchlaufen."""

    GENERATIONEN = {
        "linien": {"gpt": 5.6, "o": 99, "gpt-4o": 99, "claude": 5, "deepseek": 4,
                    "glm": 5.3, "qwen": 3.8},
        "ausnahmen_aktuell": ["claude-haiku-4-5"],
        "explizit_legacy": {"mistral-large-2407": "mistral-large-2512",
                             "command-r-plus-08-2024": "command-a"},
    }
    ZEILEN = [
        _zeile("gpt-4o-2024-11-20", "openrouter", aa_index=50, coding_index=50),
        _zeile("o1", "openrouter", aa_index=50, coding_index=50),
        _zeile("o4-mini", "openrouter", aa_index=50, coding_index=50),
        _zeile("gpt-5.4-nano", "openrouter", aa_index=50, coding_index=50),
        _zeile("gpt-5.5", "openrouter", aa_index=50, coding_index=50),
        _zeile("gpt-5.6-sol", "openrouter", aa_index=61, coding_index=77),
        _zeile("gpt-5.6-terra", "openrouter", aa_index=57, coding_index=77),
        _zeile("gpt-5.6-luna", "openrouter", aa_index=52, coding_index=71),
        _zeile("claude-haiku-4-5", "claude", aa_index=24, coding_index=None),
        _zeile("claude-opus-4-8", "claude", aa_index=63, coding_index=78),
        _zeile("glm-5-turbo", "openrouter", aa_index=50, coding_index=50),
        _zeile("glm-5.3", "openrouter", aa_index=60, coding_index=75),
        _zeile("glm-5.3-flash", "openrouter", aa_index=55, coding_index=70),
        _zeile("deepseek-v3.2", "openrouter", aa_index=50, coding_index=50),
        _zeile("deepseek-v4-pro", "openrouter", aa_index=60, coding_index=60),
        _zeile("qwen3.7-plus", "openrouter", aa_index=50, coding_index=50),
        _zeile("qwen3.8-max", "openrouter", aa_index=60, coding_index=60),
        _zeile("mistral-large-2407", "openrouter", aa_index=40, coding_index=40),
        _zeile("mistral-large-2512", "openrouter", aa_index=40, coding_index=40),
        _zeile("command-r-plus-08-2024", "openrouter", aa_index=40, coding_index=40),
        _zeile("nemotron-3-ultra", "openrouter", aa_index=40, coding_index=40),
    ]

    @classmethod
    def setUpClass(cls) -> None:
        cls.modelle = {m["id"]: m for m in
                       katalog_sicht.aggregiere(cls.ZEILEN, generationen=cls.GENERATIONEN)["modelle"]}

    def _status(self, modell_id: str) -> str:
        return self.modelle[modell_id]["status"]

    def test_gpt_4o_2024_11_20_ist_legacy(self) -> None:
        self.assertEqual(self._status("gpt-4o-2024-11-20"), "legacy")

    def test_o1_und_o4_mini_sind_legacy(self) -> None:
        self.assertEqual(self._status("o1"), "legacy")
        self.assertEqual(self._status("o4-mini"), "legacy")

    def test_gpt_5_4_nano_legacy_mit_nachfolger_aus_gpt_5_6_linie(self) -> None:
        modell = self.modelle["gpt-5.4-nano"]
        self.assertEqual(modell["status"], "legacy")
        self.assertIn(modell["nachfolger"], {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"})

    def test_gpt_5_5_ist_legacy(self) -> None:
        self.assertEqual(self._status("gpt-5.5"), "legacy")

    def test_gpt_5_6_sol_terra_luna_sind_aktuell(self) -> None:
        for modell_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            with self.subTest(modell_id=modell_id):
                self.assertEqual(self._status(modell_id), "bewertet")
                self.assertIsNone(self.modelle[modell_id]["nachfolger"])

    def test_claude_haiku_4_5_ist_aktuell_ausnahme(self) -> None:
        self.assertEqual(self._status("claude-haiku-4-5"), "bewertet")
        self.assertIsNone(self.modelle["claude-haiku-4-5"]["nachfolger"])

    def test_claude_opus_4_8_ist_legacy(self) -> None:
        self.assertEqual(self._status("claude-opus-4-8"), "legacy")

    def test_glm_turbo_ist_legacy_glm_5_3_und_flash_sind_aktuell(self) -> None:
        self.assertEqual(self._status("glm-5-turbo"), "legacy")
        self.assertEqual(self._status("glm-5.3"), "bewertet")
        self.assertEqual(self._status("glm-5.3-flash"), "bewertet")

    def test_deepseek_v3_2_legacy_mit_nachfolger_v4_pro(self) -> None:
        modell = self.modelle["deepseek-v3.2"]
        self.assertEqual(modell["status"], "legacy")
        self.assertEqual(modell["nachfolger"], "deepseek-v4-pro")

    def test_qwen_3_7_plus_legacy_qwen_3_8_max_aktuell(self) -> None:
        self.assertEqual(self._status("qwen3.7-plus"), "legacy")
        self.assertEqual(self._status("qwen3.8-max"), "bewertet")

    def test_mistral_large_2407_explizit_legacy_2512_aktuell(self) -> None:
        modell = self.modelle["mistral-large-2407"]
        self.assertEqual(modell["status"], "legacy")
        self.assertEqual(modell["nachfolger"], "mistral-large-2512")
        self.assertEqual(self._status("mistral-large-2512"), "bewertet")

    def test_command_r_plus_explizit_legacy_nachfolger_command_a(self) -> None:
        modell = self.modelle["command-r-plus-08-2024"]
        self.assertEqual(modell["status"], "legacy")
        self.assertEqual(modell["nachfolger"], "command-a")

    def test_nemotron_ohne_schwelle_folgt_der_automatischen_regel(self) -> None:
        """`nemotron` steht nicht in `linien` -- automatische Regel entscheidet, hier: einzige
        ID der Familie, darum aktuell."""
        self.assertEqual(self._status("nemotron-3-ultra"), "bewertet")
        self.assertIsNone(self.modelle["nemotron-3-ultra"]["nachfolger"])

    def test_ohne_generationen_bleibt_das_alte_automatische_verhalten(self) -> None:
        """Leere `generationen` (Datei fehlt) -- `aggregiere()` ohne den Parameter verhaelt sich
        wie vor der Festlegung 2026-08-30 (rein automatische Regel)."""
        modelle = {m["id"]: m for m in katalog_sicht.aggregiere(self.ZEILEN)["modelle"]}
        self.assertEqual(modelle["gpt-4o-2024-11-20"]["status"], "bewertet")
        self.assertEqual(modelle["claude-opus-4-8"]["status"], "bewertet")


class PreiseAnreichernTest(unittest.TestCase):
    """`preise_anreichern()` (Nachtrag 2026-08-30, Screenshot-Runde 3): serverseitiger
    Match der Abrechnungs-Keys gegen den Katalog ueber `katalog.kanonische_id()` -- dieselbe
    Normalform wie der Katalog selbst, kein Client-Raten. Liefert je Key nur
    kontext_k/herkunft; bei keinem oder mehrdeutigem Treffer bewusst `None`-Werte
    (Codex-Regel: falscher Match schlimmer als keiner)."""

    def test_exakter_key_gewinnt(self) -> None:
        zeilen = [_zeile("claude-fable-5", "claude", kontext_k=1000, herkunft="US")]
        erg = katalog_sicht.preise_anreichern({"claude-fable-5": {}}, zeilen)
        self.assertEqual(erg["claude-fable-5"]["kontext_k"], 1000)
        self.assertEqual(erg["claude-fable-5"]["herkunft"], "US")
        self.assertEqual(erg["claude-fable-5"]["hersteller"], "Anthropic")
        self.assertEqual(erg["claude-fable-5"]["match"], "exakt")

    def test_anbieter_prefix_ueber_kanonische_id(self) -> None:
        """Realer Fall modelle.json: `sference/kimi-k3` (Requesty-Key) trifft die Gruppe,
        die aus ollama/openrouter/requesty-Roh-IDs desselben Modells gebaut wird.
        (Bewusst KEIN `gpt-oss`-Test: der Basisname ohne Groesse ist zwischen
        `gpt-oss-20b`/`gpt-oss-120b` mehrdeutig -- dort bleibt `kein_match` korrekt,
        Codex-Regel „nichts raten".)"""
        zeilen = [_zeile("sference/kimi-k3", "requesty", kontext_k=1049, herkunft="CN"),
                  _zeile("kimi-k3:cloud", "ollama"),
                  _zeile("moonshotai/kimi-k3", "openrouter")]
        erg = katalog_sicht.preise_anreichern({"sference/kimi-k3": {}}, zeilen)
        self.assertEqual(erg["sference/kimi-k3"]["kontext_k"], 1049)
        self.assertEqual(erg["sference/kimi-k3"]["herkunft"], "CN")
        self.assertEqual(erg["sference/kimi-k3"]["match"], "exakt")

    def test_ohne_treffer_explizit_none_keine_raten(self) -> None:
        erg = katalog_sicht.preise_anreichern({"qwen3-vl": {}}, [_zeile("gpt-5.5", "openrouter")])
        self.assertIsNone(erg["qwen3-vl"]["kontext_k"])
        self.assertEqual(erg["qwen3-vl"]["match"], "kein_match")

    def test_leere_katalogzeilen_degradieren_sauber(self) -> None:
        erg = katalog_sicht.preise_anreichern({"claude-fable-5": {}}, [])
        self.assertEqual(erg["claude-fable-5"]["match"], "kein_match")

    def test_status_und_nachfolger_kommen_mit(self) -> None:
        """Maintainer 2026-08-30 (Drittel-Zelle): die Preistabelle zeigt den Katalog-Status-Chip
        (Latest/Legacy) je Zeile -- serverseitig mitgeliefert, inkl. Nachfolger im Tooltip."""
        zeilen = [_zeile("glm-5.2", "openrouter", aa_index=50, coding_index=50),
                  _zeile("glm-5.3", "openrouter", aa_index=60, coding_index=75)]
        erg = katalog_sicht.preise_anreichern({"glm-5.2": {}, "glm-5.3": {}}, zeilen)
        self.assertEqual(erg["glm-5.2"]["status"], "legacy")
        self.assertEqual(erg["glm-5.2"]["nachfolger"], "glm-5.3")
        self.assertEqual(erg["glm-5.3"]["status"], "bewertet")

    def test_sterne_gesamt_kommt_mit(self) -> None:
        """Maintainer 2026-08-30 (Status-Zone unten): bewertete Modelle zeigen ihre Sterne auch in
        der Preistabelle -- `sterne_gesamt` wird serverseitig angereichert (Legacy -> None,
        denn die Sterne bleiben dort bewusst leer)."""
        zeilen = [_zeile("glm-5.2", "openrouter", aa_index=50, coding_index=50),
                  _zeile("glm-5.3", "openrouter", aa_index=60, coding_index=75)]
        erg = katalog_sicht.preise_anreichern({"glm-5.2": {}, "glm-5.3": {}}, zeilen)
        self.assertIsNone(erg["glm-5.2"]["sterne_gesamt"])      # legacy traegt keine Sterne
        self.assertIsNotNone(erg["glm-5.3"]["sterne_gesamt"])   # bewertet traegt Sterne
        kein = katalog_sicht.preise_anreichern({"irrelevant-x": {}}, zeilen)
        self.assertIsNone(kein["irrelevant-x"]["sterne_gesamt"])  # kein_match -> None

    def test_ollama_basis_key_erbt_status_ueber_referenz(self) -> None:
        """Befund 2026-08-30 (Screenshot-Runde 5): die kurzen Ollama-Basis-Keys
        (`gpt-oss`, `qwen3-vl` ...) entfernt `aggregiere()` als Dublette der
        Groessenvariante (`_ohne_ollama_basis_dubletten`) -- darum blieb ihre Status-Zone
        in der Preistabelle leer. Der kuratierte `referenz`-Zeiger im Preis-Eintrag
        (modelle.json, aus der dokumentierten `quelle`) benennt die Variante, deren
        Status/Sterne die Zeile erbt. Ohne Zeiger bleibt es leer (kein Raten)."""
        zeilen = [_zeile("gpt-oss", "ollama"),
                  _zeile("gpt-oss:20b-cloud", "ollama", aa_index=60, coding_index=60)]
        erg = katalog_sicht.preise_anreichern({"gpt-oss": {"referenz": "gpt-oss-20b"}}, zeilen)
        self.assertEqual(erg["gpt-oss"]["status"], "bewertet")
        self.assertIsNotNone(erg["gpt-oss"]["sterne_gesamt"])
        ohne = katalog_sicht.preise_anreichern({"gpt-oss": {}}, zeilen)
        self.assertIsNone(ohne["gpt-oss"]["status"])            # kein Zeiger -> kein Status


class HerkunftUndKanonischeIdWaechterTest(unittest.TestCase):
    """Abnahme 2026-08-30 (Fix 4): Waechter gegen den echten Katalog-Bestand -- Fixture ist
    ein Schnappschuss ALLER distinkten `modell_id`-Werte aus `GET /api/modellkatalog` (Stand
    2026-08-30, 1044 Zeilen, `tests/fixtures/modellkatalog_ids.json`), ohne Netz/DB nachprueft.
    Rot bedeutet: ein neues Modell braucht eine `HERSTELLER_HERKUNFT`-Zuordnung (Recherche)."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(_FIXTURES / "modellkatalog_ids.json", encoding="utf-8") as f:
            cls.ids: list[str] = json.load(f)

    def test_jede_id_hat_hersteller_und_herkunft(self) -> None:
        fehlend = [i for i in self.ids if katalog.hersteller_und_herkunft(i)[1] is None]
        self.assertEqual(fehlend, [], f"Herkunft fehlt fuer: {fehlend[:20]}")

    def test_jede_id_hat_einen_hersteller_namen(self) -> None:
        leer = [i for i in self.ids if not katalog.hersteller_und_herkunft(i)[0]]
        self.assertEqual(leer, [])

    def test_kanonische_ids_ergeben_keine_kollidierenden_anzeige_ids(self) -> None:
        """Aggregation ueber den GESAMTEN echten Bestand -- jede resultierende Modellgruppe
        bekommt eine eigene, EINDEUTIGE Anzeige-`id` (kein `_anzeige_id`-Zusammenfall zweier
        eigentlich verschiedener kanonischer Gruppen)."""
        zeilen = [_zeile(modell_id, "openrouter") for modell_id in self.ids]
        modelle = katalog_sicht.aggregiere(zeilen)["modelle"]
        anzeige_ids = [m["id"] for m in modelle]
        self.assertEqual(len(anzeige_ids), len(set(anzeige_ids)))


if __name__ == "__main__":
    unittest.main()
