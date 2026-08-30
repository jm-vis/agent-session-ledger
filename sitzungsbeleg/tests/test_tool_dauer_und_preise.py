"""Stufe 2: Tool-Laufzeit im Claude-Leser (für latency:slow_turn) + Preisblock-Laden."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .. import __main__ as main_mod
from .. import kennzahlen, leser_claude
from ..modell import ART_TOOL


def _zeile(typ: str, zeit: str, content: list) -> str:
    return json.dumps({"type": typ, "timestamp": zeit, "sessionId": "s1", "cwd": "C:\\\\p\\\\demo",
                       "message": {"role": typ, "model": "claude-sonnet-5", "content": content}})


class ToolDauerTest(unittest.TestCase):
    def test_tool_result_zeit_minus_tool_use_zeit(self) -> None:
        zeilen = [
            _zeile("user", "2026-08-26T08:00:00.000Z", [{"type": "text", "text": "los"}]),
            _zeile("assistant", "2026-08-26T08:00:01.000Z",
                   [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}]),
            _zeile("user", "2026-08-26T08:00:04.500Z",
                   [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "s1.jsonl"
            pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        tools = [e for e in beleg.ereignisse if e.art == ART_TOOL]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].dauer_ms, 3500)

    def test_ohne_ergebnis_bleibt_dauer_none(self) -> None:
        zeilen = [
            _zeile("assistant", "2026-08-26T08:00:01.000Z",
                   [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "s1.jsonl"
            pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
            beleg = leser_claude.lese_sitzung(str(pfad))
        self.assertIsNone(beleg.ereignisse[0].dauer_ms)


class PreisBlockTest(unittest.TestCase):
    def test_block_mit_waehrung(self) -> None:
        """Anzeigefelder (PREIS_ANZEIGE_FELDER, Nachtrag 2026-08-30) werden seit dem
        Preistabellen-Umbau durchgereicht — vorher still verworfen; die Abrechnung liest
        weiter nur die Rechenfelder."""
        block = {"waehrung": "USD", "modelle": {"m": {"input": 1, "output": 2, "cache_quelle": "x"}}}
        preise, waehrung = main_mod._preise_aus_block(block)
        self.assertEqual(waehrung, "USD")
        self.assertEqual(preise, {"m": {"input": 1, "output": 2, "cache_quelle": "x"}})

    def test_flaches_dict_ohne_waehrung(self) -> None:
        preise, waehrung = main_mod._preise_aus_block({"m": {"input": 1}})
        self.assertEqual(waehrung, "")
        self.assertEqual(preise["m"]["input"], 1)

    def test_ollama_cloud_persona_wege_haben_referenzpreis(self) -> None:
        """Waechter (Fund 2026-08-30, Screenshot-Runde): jeder persona_wege-Pin mit
        quelle=="ollama" und ":cloud"-Modell braucht eine Referenz-Preiszeile (Key =
        Basisname vor ":"), sonst ist der tatsaechlich genutzte Weg in der Preistabelle
        unsichtbar und die Abrechnung faellt auf den falschen Anbieter/None zurueck.
        Rot beim Hinzufuegen eines neuen Ollama-Cloud-Pins ohne Preiszeile."""
        import json
        daten = json.loads(main_mod.MODELLE_PFAD.read_text(encoding="utf-8"))
        preise = daten["preise"]["modelle"]
        fehlend = []
        for pin in daten["persona_wege"].values():
            wege = pin.get("wege", pin) if isinstance(pin, dict) else pin
            for weg in wege:
                modell = weg["modell"]
                if weg["quelle"] == "ollama" and weg.get("ebene") != "geschuetzt" \
                        and modell.endswith(":cloud"):
                    basis = modell.split(":", 1)[0]
                    if basis not in preise or preise[basis].get("herkunft") != "ollama":
                        fehlend.append(modell)
        self.assertEqual(fehlend, [], f"Ollama-Referenzpreis fehlt fuer: {fehlend}")

    def test_jedes_historisch_genutzte_modell_hat_preisdeckung(self) -> None:
        """Waechter (Frage 2026-08-30: „wie stellen wir sicher, dass alles historisch
        Genutzte einen Preis hat"): distinkte Modelle aus ALLEN Sitzungen gegen die
        Preisliste mit denselben drei Stufen wie kennzahlen._preissatz (exakt / Basisname /
        meldet_als). Rot = ein neu genutztes Modell hat keinen Preissatz -- Kostenwaere
        still nicht_observed. Uebersprungen ohne erreichbare DB (Testlaeufe offline)."""
        try:
            from .. import speicher
            out = speicher.psql(
                "SELECT DISTINCT jsonb_array_elements_text("
                "coalesce(dokument->'kopf'->'modelle','[]'::jsonb)) AS modell "
                "FROM sitzung_aktuell WHERE dokument IS NOT NULL")
        except Exception as e:  # noqa: BLE001 -- DB offline ist kein Testbruch
            self.skipTest(f"DB nicht erreichbar: {e}")
        genutzt = [zeile for zeile in out.splitlines()
                   if zeile.strip() and not zeile.startswith("<")]
        preise, _ = main_mod._lade_preise(None)
        fehlend = [m for m in genutzt if kennzahlen._preissatz(m, preise) is None]
        self.assertEqual(fehlend, [], f"ohne Preissatz: {fehlend}")

    def test_modelle_json_liefert_claude_preise(self) -> None:
        preise, waehrung = main_mod._lade_preise(None)
        self.assertEqual(waehrung, "USD")
        self.assertIn("claude-sonnet-5", preise)

    def test_modelle_json_liefert_codex_preise(self) -> None:
        """Codex-Belege tragen die Modellnamen gpt-5.5 / gpt-5.6-terra / gpt-5.6-sol
        (siehe kopf.modelle in echten Sitzungen) — die Preistabelle muss exakt
        diese Schluessel treffen, sonst bleibt erfassung.kosten=not_observed."""
        preise, waehrung = main_mod._lade_preise(None)
        self.assertEqual(waehrung, "USD")
        for name in ("gpt-5.5", "gpt-5.6-terra", "gpt-5.6-sol"):
            self.assertIn(name, preise)
            self.assertGreater(preise[name]["input"], 0)
            self.assertGreater(preise[name]["output"], 0)


class CodexKostenTest(unittest.TestCase):
    """Stellt sicher, dass ein Codex-Assistent-Ereignis mit Modellname gpt-5.5
    aus der modelle.json-Preistabelle tatsaechlich Kosten ableitet (derived)."""

    def test_gpt_5_5_ereignis_ergibt_derived_kosten(self) -> None:
        from ..kennzahlen import berechne
        from ..modell import Token
        from .hilfen import assistent, baue_beleg

        preise, waehrung = main_mod._lade_preise(None)
        token = Token(input=1_000_000, output=1_000_000, cache_read=1_000_000)
        beleg = baue_beleg(ereignisse=[assistent(token=token, name="gpt-5.5")])
        berechne(beleg, preise, waehrung)

        satz = preise["gpt-5.5"]
        erwartet = satz["input"] + satz["output"] + satz.get("cache_read", 0)
        self.assertAlmostEqual(beleg.kennzahlen.kosten, erwartet)
        self.assertEqual(beleg.kennzahlen.kosten_waehrung, "USD")
        self.assertEqual(beleg.erfassung.kosten, "derived")


class RequestyKostenTest(unittest.TestCase):
    """Layout-Nachlese 2026-08-28 Punkt 6 (verifizierter Fund, Regressionsschutz End-zu-Ende
    gegen die ECHTE modelle.json): eine Requesty-Sitzung liefert im Ereignis das Upstream-
    Modell `moonshotai/Kimi-K3`, NICHT die Requesty-Katalog-ID `sference/kimi-k3`, unter der
    modelle.json den Preis fuehrt -- ohne `meldet_als` blieb kosten=not_observed trotz
    vorhandener Registry-Zeile (live an echten Requesty-Sitzungen nachgewiesen)."""

    def test_kimi_k3_meldet_als_wird_von_der_registry_aufgeloest(self) -> None:
        from ..kennzahlen import berechne
        from ..modell import Token
        from .hilfen import assistent, baue_beleg

        preise, waehrung = main_mod._lade_preise(None)
        self.assertIn("moonshotai/Kimi-K3", preise["sference/kimi-k3"].get("meldet_als", []))
        token = Token(input=1_000_000, output=1_000_000)
        beleg = baue_beleg(ereignisse=[assistent(token=token, name="moonshotai/Kimi-K3")])
        berechne(beleg, preise, waehrung)

        satz = preise["sference/kimi-k3"]
        erwartet = satz["input"] + satz["output"]
        self.assertAlmostEqual(beleg.kennzahlen.kosten, erwartet)
        self.assertEqual(beleg.erfassung.kosten, "derived")


if __name__ == "__main__":
    unittest.main()
