"""quelle_fuer(): abgeleitete Anzeige-Quelle aus Rohquelle + Modellliste (Entscheid
2026-08-26, Auftrag 2). Registry wird je Test injiziert -- nie die echte modelle.json,
damit die Tests unabhaengig vom aktuellen Modell-Stand bleiben."""
from __future__ import annotations

import unittest

from .. import quellen


class QuelleFuerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = {
            "preise": {
                "modelle": {
                    "claude-sonnet-5": {"herkunft": "anthropic"},
                    "claude-opus-5": {"herkunft": "anthropic"},
                    "gpt-5.5": {"herkunft": "openai"},
                    "nvidia/nemotron-3-ultra-550b-a55b": {"herkunft": "openrouter"},
                    "z-ai/glm-5.2:free": {"herkunft": "openrouter"},
                }
            },
            "modelle": {
                "glm-5.2:cloud": {"herkunft": "ollama"},
                "minimax-m3:cloud": {"herkunft": "ollama"},
                "hf.co/bartowski/some-model-GGUF:latest": {"herkunft": "ollama"},
            },
        }

    def test_produkt_ist_immer_produkt(self) -> None:
        self.assertEqual(quellen.quelle_fuer("produkt", [], self.registry), quellen.PRODUKT)

    def test_codex_ist_immer_codex(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("codex", ["gpt-5.5"], self.registry), quellen.CODEX
        )

    def test_claude_mit_anthropic_modell_ist_claude(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["claude-sonnet-5"], self.registry), quellen.CLAUDE
        )

    def test_claude_ohne_modellangabe_bleibt_claude(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", [], self.registry), quellen.CLAUDE)
        self.assertEqual(quellen.quelle_fuer("claude", None, self.registry), quellen.CLAUDE)

    def test_claude_mit_glm_5_2_ist_ollama(self) -> None:
        """Vorgabe: glm-5.2 -> Ollama (Backend-Umschalter, z. B. VICO-Ollama-Umschalter/CURA)."""
        self.assertEqual(
            quellen.quelle_fuer("claude", ["glm-5.2:cloud"], self.registry), quellen.OLLAMA
        )

    def test_claude_mit_ollama_modell_ist_ollama_auch_gemischt_mit_anthropic(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["claude-sonnet-5", "minimax-m3:cloud"], self.registry),
            quellen.OLLAMA,
        )

    def test_claude_mit_unbekanntem_modell_ist_unbekannt(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["irgendein-neues-modell"], self.registry),
            quellen.UNBEKANNT,
        )

    def test_synthetic_modell_wird_ignoriert(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["<synthetic>", "claude-sonnet-5"], self.registry),
            quellen.CLAUDE,
        )
        self.assertEqual(quellen.quelle_fuer("claude", ["<synthetic>"], self.registry), quellen.CLAUDE)

    def test_fremde_rohquelle_ist_unbekannt(self) -> None:
        self.assertEqual(quellen.quelle_fuer("irgendwas", [], self.registry), quellen.UNBEKANNT)

    def test_claude_mit_nemotron_openrouter_id_ist_openrouter(self) -> None:
        """OpenRouter-Session ueber Claude Code: Modellname traegt den OpenRouter-Namensraum
        `anbieter/modell`."""
        self.assertEqual(
            quellen.quelle_fuer("claude", ["nvidia/nemotron-3-ultra-550b-a55b"], self.registry),
            quellen.OPENROUTER,
        )

    def test_claude_mit_glm_openrouter_variante_ist_openrouter(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["z-ai/glm-5.2:free"], self.registry),
            quellen.OPENROUTER,
        )

    def test_claude_mit_hf_co_ollama_eintrag_ist_ollama(self) -> None:
        """`hf.co/...`-Pfade tragen ebenfalls einen Schraegstrich, stehen aber in der
        Ollama-Registry -- der Registry-Treffer gewinnt vor der OpenRouter-Heuristik."""
        self.assertEqual(
            quellen.quelle_fuer(
                "claude", ["hf.co/bartowski/some-model-GGUF:latest"], self.registry
            ),
            quellen.OLLAMA,
        )

    def test_claude_mischsitzung_claude_und_openrouter_ist_openrouter(self) -> None:
        """Backend-Umschalter gewinnt ueber gemischte Sitzungen, analog zu Ollama."""
        self.assertEqual(
            quellen.quelle_fuer(
                "claude",
                ["claude-sonnet-5", "nvidia/nemotron-3-ultra-550b-a55b"],
                self.registry,
            ),
            quellen.OPENROUTER,
        )


class BackendVorrangTest(unittest.TestCase):
    """Auftrag 2026-08-28 (Requesty): `kopf.backend` (Stop-Hook-Hostklasse) gewinnt VOR der
    Modell-Kette -- noetig, weil Requesty-IDs wie `anthropic/claude-sonnet-5` aussehen wie
    OpenRouter-IDs (Namensraum allein reicht nicht)."""

    def setUp(self) -> None:
        self.registry = {
            "preise": {"modelle": {"claude-sonnet-5": {"herkunft": "anthropic"}}},
            "modelle": {"glm-5.2:cloud": {"herkunft": "ollama"}},
        }

    def test_backend_requesty_gewinnt_ueber_openrouter_form(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer(
                "claude", ["anthropic/claude-sonnet-5"], self.registry, backend="requesty"
            ),
            quellen.REQUESTY,
        )

    def test_ohne_backend_bleibt_bisheriges_verhalten_openrouter(self) -> None:
        """Bestehende Belege ohne `backend` (Feld optional) durchlaufen unveraendert die alte
        Modell-Kette -- dieselbe ID landet dann bei OpenRouter."""
        self.assertEqual(
            quellen.quelle_fuer("claude", ["anthropic/claude-sonnet-5"], self.registry),
            quellen.OPENROUTER,
        )

    def test_backend_anthropic_ist_claude(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["irgendein-modell"], self.registry, backend="anthropic"),
            quellen.CLAUDE,
        )

    def test_backend_ollama_gewinnt(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["claude-sonnet-5"], self.registry, backend="ollama"),
            quellen.OLLAMA,
        )

    def test_backend_openrouter_gewinnt(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["claude-sonnet-5"], self.registry, backend="openrouter"),
            quellen.OPENROUTER,
        )

    def test_backend_unbekannt_faellt_auf_kette_zurueck(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["claude-sonnet-5"], self.registry, backend="unbekannt"),
            quellen.CLAUDE,
        )

    def test_backend_gilt_nicht_fuer_codex_oder_produkt(self) -> None:
        self.assertEqual(quellen.quelle_fuer("codex", ["gpt-5.5"], self.registry, backend="requesty"), quellen.CODEX)
        self.assertEqual(quellen.quelle_fuer("produkt", [], self.registry, backend="requesty"), quellen.PRODUKT)


class UnbekannteModelleTest(unittest.TestCase):
    """Grundlage fuer den Waechter (aliase --pruefen): Modelle einer claude-Sitzung, die
    weder als Anthropic noch als Ollama in der Registry gefuehrt werden."""

    def setUp(self) -> None:
        self.registry = {
            "preise": {"modelle": {"claude-sonnet-5": {"herkunft": "anthropic"}}},
            "modelle": {"glm-5.2:cloud": {"herkunft": "ollama"}},
        }

    def test_bekannte_modelle_liefern_leere_liste(self) -> None:
        self.assertEqual(
            quellen.unbekannte_modelle("claude", ["claude-sonnet-5", "glm-5.2:cloud"], self.registry),
            [],
        )

    def test_unbekanntes_modell_wird_gemeldet(self) -> None:
        self.assertEqual(
            quellen.unbekannte_modelle("claude", ["ein-neues-modell"], self.registry),
            ["ein-neues-modell"],
        )

    def test_codex_und_produkt_werden_nicht_geprueft(self) -> None:
        self.assertEqual(quellen.unbekannte_modelle("codex", ["gpt-5.5"], self.registry), [])
        self.assertEqual(quellen.unbekannte_modelle("produkt", [], self.registry), [])

    def test_synthetic_wird_nicht_als_unbekannt_gemeldet(self) -> None:
        self.assertEqual(quellen.unbekannte_modelle("claude", ["<synthetic>"], self.registry), [])

    def test_openrouter_id_wird_nicht_als_unbekannt_gemeldet(self) -> None:
        self.assertEqual(
            quellen.unbekannte_modelle(
                "claude", ["nvidia/nemotron-3-ultra-550b-a55b", "z-ai/glm-5.2:free"], self.registry
            ),
            [],
        )


class RegistryAusDateiTest(unittest.TestCase):
    """Ohne injizierte Registry wird scripts/modelle.json gelesen -- glm-5.2 (echter
    Registry-Eintrag) muss dort als Ollama gefuehrt sein."""

    def test_echte_registry_fuehrt_glm_als_ollama(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", ["glm-5.2:cloud"]), quellen.OLLAMA)

    def test_echte_registry_fuehrt_claude_sonnet_als_anthropic(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", ["claude-sonnet-5"]), quellen.CLAUDE)

    def test_echte_registry_fuehrt_nemotron_als_openrouter(self) -> None:
        """Sitzung ueber den OpenRouter-Anbieterwechsel (ANTHROPIC_BASE_URL=openrouter.ai)."""
        self.assertEqual(
            quellen.quelle_fuer("claude", ["nvidia/nemotron-3-ultra-550b-a55b"]),
            quellen.OPENROUTER,
        )


class OllamaReferenzpreisAendertQuelleNichtTest(unittest.TestCase):
    """Entscheid 2026-08-27: ein `preise.modelle`-Eintrag mit herkunft='ollama' (OpenRouter-
    Referenzpreis fuer Ollama-Cloud-Modelle) darf `quelle_fuer` NICHT beeinflussen -- die
    Quellenerkennung haengt allein am Ollama-Bestand (`modelle`), nicht an `preise.modelle`."""

    def setUp(self) -> None:
        self.registry = {
            "preise": {
                "modelle": {
                    "claude-sonnet-5": {"herkunft": "anthropic"},
                    "glm-5.2": {"herkunft": "ollama", "preis_art": "referenz"},
                }
            },
            "modelle": {"glm-5.2:cloud": {"herkunft": "ollama"}},
        }

    def test_glm_bleibt_ollama_trotz_preiseintrag(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["glm-5.2:cloud"], self.registry), quellen.OLLAMA
        )

    def test_ollama_herkunft_zaehlt_nicht_als_anthropic(self) -> None:
        self.assertNotIn("glm-5.2", quellen.anthropic_modellnamen(self.registry))


if __name__ == "__main__":
    unittest.main()


def test_ollama_modell_ohne_tag_wird_erkannt():
    registry = {"modelle": {"glm-5.2:cloud": {}}, "preise": {"modelle": {}}}
    assert quellen.quelle_fuer("claude", ["glm-5.2"], registry) == quellen.OLLAMA
    assert quellen.unbekannte_modelle("claude", ["glm-5.2"], registry) == []


class RequestyOhneBackendTest(unittest.TestCase):
    """Hintergrund-Ingest (ingest-dir) kennt kein Backend: Requesty-Upstream-Namen muessen
    trotzdem als Requesty gelten, nicht als OpenRouter (Befund Sitzung 992, 2026-08-28)."""

    def setUp(self) -> None:
        self.registry = {
            "modelle": {},
            "preise": {"modelle": {
                "sference/kimi-k3": {"herkunft": "requesty", "meldet_als": ["moonshotai/Kimi-K3"]},
                "claude-sonnet-5": {"herkunft": "anthropic"},
            }},
        }

    def test_upstream_alias_ohne_backend_ist_requesty(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", ["moonshotai/Kimi-K3"], self.registry), quellen.REQUESTY)

    def test_katalog_id_ohne_backend_ist_requesty(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", ["sference/kimi-k3"], self.registry), quellen.REQUESTY)

    def test_fremder_namensraum_bleibt_openrouter(self) -> None:
        self.assertEqual(quellen.quelle_fuer("claude", ["nvidia/nemotron-3-ultra"], self.registry), quellen.OPENROUTER)

    def test_backend_schlaegt_registry(self) -> None:
        self.assertEqual(
            quellen.quelle_fuer("claude", ["moonshotai/Kimi-K3"], self.registry, backend="openrouter"),
            quellen.OPENROUTER)


class WaechterPlatzhalterTest(unittest.TestCase):
    """2026-08-28: '<redigiert>' und Requesty-Namen duerfen den Alias-Waechter nicht rot faerben."""

    def test_platzhalter_redigiert_ist_kein_unbekanntes_modell(self):
        self.assertEqual(quellen.unbekannte_modelle("claude", ["<redigiert>", "<synthetic>"]), [])

    def test_requesty_registry_name_ist_bekannt(self):
        reg = {"preise": {"modelle": {"sference/kimi-k3": {"herkunft": "requesty", "meldet_als": ["moonshotai/Kimi-K3"]}}}}
        self.assertEqual(quellen.unbekannte_modelle("claude", ["moonshotai/Kimi-K3"], reg), [])
