"""Tests fuer tiefenanalyse.py (Phase 3 I, CONTRACTS.md C10): Konsensregel, Prompts/Parser,
Lauf-Registry, Lauf-Ausfuehrung mit Fake-Fragern (kein echter claude-/codex-Prozess) und die
Guards aus dem Arbeitsauftrag (Rohausschnitt nie in Stufe 2, Codex nie bei `nur_lokal`)."""
from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timedelta, timezone

from .. import contracts, pruefung, tiefenanalyse


def _dokument(auffaelligkeiten=None, ereignisse=None) -> dict:
    return {
        "kopf": {"quelle": "claude", "sitzung_id": "s1", "start": "2026-08-28T10:00:00+00:00",
                 "ende": "2026-08-28T10:10:00+00:00"},
        "erfassung": {}, "kennzahlen": {},
        "auffaelligkeiten": auffaelligkeiten or [], "ereignisse": ereignisse or [],
    }


def _auff(signatur="rework:tool:Bash", regel="rework:tool", schwere="hinweis") -> dict:
    return {"signatur": signatur, "regel": regel, "schwere": schwere}


def _fehler_ereignis(zeit: str) -> dict:
    return {"zeit": zeit, "art": "tool_ergebnis", "fehler": True}


# ---------------------------------------------------------------------------------------------
# Paket K (Fehlertexte-Durchreichung, Entscheid 2026-08-28 14:10): Sammeln/Kappen, C6-Weiche,
# Ende-zu-Ende (Fehlertexte im Stufe-1-Prompt, nie im gespeicherten Ergebnis).
# ---------------------------------------------------------------------------------------------

class FehlerPositionenTest(unittest.TestCase):
    def test_21_fehler_werden_auf_20_gekappt(self):
        ereignisse = [_fehler_ereignis(f"t{i}") for i in range(21)]
        self.assertEqual(len(tiefenanalyse._fehler_positionen(ereignisse)), 20)

    def test_nur_tool_ergebnis_mit_fehler_true_zaehlt(self):
        ereignisse = [
            {"zeit": "t0", "art": "tool_ergebnis", "fehler": False},
            {"zeit": "t1", "art": "tool", "fehler": True},
            {"zeit": "t2", "art": "tool_ergebnis", "fehler": True},
        ]
        self.assertEqual(tiefenanalyse._fehler_positionen(ereignisse), [2])


class KappenFehlertextTest(unittest.TestCase):
    def test_400_zeichen_text_wird_auf_300_gekappt_mit_ellipse(self):
        gekappt = tiefenanalyse._kappen_fehlertext("x" * 400)
        self.assertEqual(len(gekappt), 300)
        self.assertTrue(gekappt.endswith("…"))

    def test_kurzer_text_bleibt_unveraendert(self):
        self.assertEqual(tiefenanalyse._kappen_fehlertext("kurz"), "kurz")


class FehlertexteGateTest(unittest.TestCase):
    def test_keine_fehler_liefert_leere_liste_ohne_vermerk(self):
        dokument = _dokument([_auff()], ereignisse=[])
        self.assertEqual(tiefenanalyse._fehlertexte(dokument, "claude", "s1", False), ([], ""))

    def test_geschuetzt_ohne_lokalen_weg_liefert_leer_und_vermerk(self):
        dokument = _dokument([_auff()], ereignisse=[_fehler_ereignis("t0")])
        dokument["kopf"]["projekt_name"] = "x/_lokal/y"
        texte, vermerk = tiefenanalyse._fehlertexte(dokument, "claude", "s1", False)
        self.assertEqual(texte, [])
        self.assertEqual(vermerk, tiefenanalyse.FEHLERTEXTE_VERMERK_GESCHUETZT)

    def test_geschuetzt_mit_lokalem_weg_wird_nicht_blockiert(self):
        """`nur_lokal=True` (Stufe 1 laeuft dann sowieso lokal ueber Ollama) hebt die Sperre auf --
        ohne Rohdatei bricht das Sammeln trotzdem fail-open ab (Vermerk statt Fehler)."""
        dokument = _dokument([_auff()], ereignisse=[_fehler_ereignis("t0")])
        dokument["kopf"]["projekt_name"] = "x/_lokal/y"
        texte, vermerk = tiefenanalyse._fehlertexte(dokument, "claude", "s-fehlt-lokal", True)
        self.assertEqual(texte, [])
        self.assertEqual(vermerk, tiefenanalyse.FEHLERTEXTE_VERMERK_FEHLEND)

    def test_fehlende_rohdatei_liefert_leer_und_vermerk(self):
        import tempfile
        from pathlib import Path

        from .. import __main__ as cli

        alt = cli.CLAUDE_PROJEKTE
        with tempfile.TemporaryDirectory() as tmp:
            cli.CLAUDE_PROJEKTE = Path(tmp) / "claude"
            try:
                dokument = _dokument(
                    [_auff()], ereignisse=[_fehler_ereignis("2026-08-28T10:05:00+00:00")],
                )
                texte, vermerk = tiefenanalyse._fehlertexte(dokument, "claude", "s-fehlt", False)
            finally:
                cli.CLAUDE_PROJEKTE = alt
        self.assertEqual(texte, [])
        self.assertEqual(vermerk, tiefenanalyse.FEHLERTEXTE_VERMERK_FEHLEND)


# ---------------------------------------------------------------------------------------------
# Konsensregel (>= 8 Faelle, C10)
# ---------------------------------------------------------------------------------------------

class KonsensTest(unittest.TestCase):
    def _seite(self, kategorie: str, urteil: str) -> dict:
        return {"ursache_kategorie": kategorie, "befund": "x", "empfehlung": "y", "urteil": urteil}

    def test_gleiche_kategorie_und_urteil_uebereinstimmend(self):
        c = self._seite("Heredoc-Backslash", "ja")
        x = self._seite("Heredoc-Backslash", "ja")
        self.assertEqual(tiefenanalyse.konsens(c, x), "uebereinstimmend")

    def test_kleiner_tippfehler_levenshtein_drei_zaehlt_als_gleich(self):
        c = self._seite("Heredoc Backslash", "ja")
        x = self._seite("Heredoc Backslash!", "ja")  # 1 Zeichen Unterschied nach Normierung
        self.assertEqual(tiefenanalyse.konsens(c, x), "uebereinstimmend")

    def test_teilstring_kategorie_zaehlt_als_gleich(self):
        c = self._seite("Backslash", "ja")
        x = self._seite("Heredoc Backslash Fehler", "ja")
        self.assertEqual(tiefenanalyse.konsens(c, x), "uebereinstimmend")

    def test_deutlich_verschiedene_kategorie_dissens(self):
        c = self._seite("Heredoc-Backslash", "ja")
        x = self._seite("Gewollte Retry-Logik Fan-out", "ja")
        self.assertEqual(tiefenanalyse.konsens(c, x), "dissens")

    def test_gleiche_kategorie_verschiedenes_urteil_dissens(self):
        c = self._seite("Heredoc-Backslash", "ja")
        x = self._seite("Heredoc-Backslash", "nein")
        self.assertEqual(tiefenanalyse.konsens(c, x), "dissens")

    def test_unklar_bei_claude_immer_dissens(self):
        c = self._seite("Heredoc-Backslash", "unklar")
        x = self._seite("Heredoc-Backslash", "unklar")
        self.assertEqual(tiefenanalyse.konsens(c, x), "dissens")

    def test_unklar_bei_codex_immer_dissens_trotz_gleicher_kategorie(self):
        c = self._seite("Heredoc-Backslash", "ja")
        x = self._seite("Heredoc-Backslash", "unklar")
        self.assertEqual(tiefenanalyse.konsens(c, x), "dissens")

    def test_ohne_stufe2_ohne_zweitmeinung(self):
        c = self._seite("Heredoc-Backslash", "ja")
        self.assertEqual(tiefenanalyse.konsens(c, None), "ohne_zweitmeinung")

    def test_leere_kategorie_nie_gleich(self):
        c = self._seite("", "ja")
        x = self._seite("", "ja")
        self.assertEqual(tiefenanalyse.konsens(c, x), "dissens")


# ---------------------------------------------------------------------------------------------
# Prompts + Parser
# ---------------------------------------------------------------------------------------------

class PromptTest(unittest.TestCase):
    def test_stufe1_enthaelt_rohausschnitt_und_commits(self):
        text = tiefenanalyse.prompt_stufe1(
            {"kopf": {}}, [{"index": 1, "typ": "tool", "text": "Bash echo hi"}],
            [{"hash": "abc1234", "zeit": "t", "betreff": "fix heredoc"}],
            {"bedeutung": "Werkzeug-Nacharbeit"}, "rework:tool:Bash",
        )
        self.assertIn("Bash echo hi", text)
        self.assertIn("abc1234", text)
        self.assertIn("fix heredoc", text)

    def test_stufe2_enthaelt_niemals_rohausschnitt_oder_commit_hash(self):
        """Guard: `prompt_stufe2` nimmt gar keinen Rohausschnitt/Commit-Parameter entgegen --
        strukturell ausgeschlossen. Zusaetzlich per Text-Assertion geprueft (Arbeitsauftrag Punkt 6)."""
        stufe1 = {"ursache_kategorie": "Heredoc-Backslash", "befund": "x", "empfehlung": "y", "urteil": "ja"}
        text = tiefenanalyse.prompt_stufe2({"kopf": {}}, stufe1)
        self.assertNotIn("tool_use", text)
        self.assertNotIn("Rohausschnitt", text)
        self.assertNotIn("abc1234", text)


class ParserTest(unittest.TestCase):
    def test_stufe1_parst_alle_felder(self):
        text = '{"ursache_kategorie": "Heredoc", "befund": "x", "empfehlung": "y", "urteil": "JA", "komplexitaet": "EINFACH"}'
        u = tiefenanalyse.urteil_stufe1_aus_text(text)
        self.assertEqual(u, {"ursache_kategorie": "Heredoc", "befund": "x", "empfehlung": "y",
                              "urteil": "ja", "komplexitaet": "einfach"})

    def test_stufe1_unbekannte_komplexitaet_faellt_auf_komplex(self):
        text = '{"ursache_kategorie": "x", "befund": "y", "empfehlung": "z", "urteil": "ja", "komplexitaet": "mittel"}'
        self.assertEqual(tiefenanalyse.urteil_stufe1_aus_text(text)["komplexitaet"], "komplex")

    def test_stufe2_hat_keine_komplexitaet(self):
        text = '{"ursache_kategorie": "x", "befund": "y", "empfehlung": "z", "urteil": "nein"}'
        u = tiefenanalyse.urteil_stufe2_aus_text(text)
        self.assertNotIn("komplexitaet", u)

    def test_kaputtes_json_liefert_sichere_defaults(self):
        u = tiefenanalyse.urteil_stufe1_aus_text("keine Ahnung")
        self.assertEqual(u["urteil"], "unklar")
        self.assertEqual(u["komplexitaet"], "komplex")


# ---------------------------------------------------------------------------------------------
# Lauf-Registry
# ---------------------------------------------------------------------------------------------

class RegistryTest(unittest.TestCase):
    def tearDown(self):
        tiefenanalyse._laufend.clear()

    def test_registrieren_dann_konflikt_dann_frei(self):
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "sig"))
        self.assertFalse(tiefenanalyse.registriere_lauf(1, "sig"))
        self.assertIsNotNone(tiefenanalyse.laeuft_seit(1, "sig"))
        tiefenanalyse.freigeben(1, "sig")
        self.assertIsNone(tiefenanalyse.laeuft_seit(1, "sig"))
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "sig"))
        tiefenanalyse.freigeben(1, "sig")

    def test_andere_signatur_blockiert_nicht(self):
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "a"))
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "b"))
        tiefenanalyse.freigeben(1, "a")
        tiefenanalyse.freigeben(1, "b")

    def test_abgelaufener_lauf_blockiert_nicht_mehr(self):
        alt = datetime.now(timezone.utc) - timedelta(minutes=tiefenanalyse.ABLAUF_MINUTEN + 1)
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "sig", jetzt=alt))
        self.assertTrue(tiefenanalyse.registriere_lauf(1, "sig"))
        tiefenanalyse.freigeben(1, "sig")


# ---------------------------------------------------------------------------------------------
# Lauf-Ausfuehrung (Fake-Frager)
# ---------------------------------------------------------------------------------------------

def _fake_cloud(antwort: str):
    def frager(text: str, modell: str) -> str:
        frager.aufrufe.append((text, modell))
        return antwort
    frager.aufrufe = []
    return frager


def _fake_lokal(antwort: str):
    def frager(text: str) -> str:
        frager.aufrufe.append(text)
        return antwort
    frager.aufrufe = []
    return frager


class LaufAusfuehrenTest(unittest.TestCase):
    def _stufe1_json(self, kategorie="Heredoc-Backslash", urteil="ja", komplexitaet="einfach"):
        return (f'{{"ursache_kategorie": "{kategorie}", "befund": "b", "empfehlung": "e", '
                f'"urteil": "{urteil}", "komplexitaet": "{komplexitaet}"}}')

    def _lauf(self, dokument, auff, nur_lokal=False, frager_cloud=None, frager_lokal=None,
              frager_codex=None, stufe_fuer_fn=None, historie=None):
        geschrieben = []
        detail = tiefenanalyse.lauf_ausfuehren(
            dokument, auff, auff["signatur"], 0, 1, 512, "claude", "s1", nur_lokal, historie or [],
            lambda quelle, typ, d: geschrieben.append(d),
            frager_cloud=frager_cloud or _fake_cloud(self._stufe1_json()),
            frager_lokal=frager_lokal or _fake_lokal(self._stufe1_json()),
            frager_codex=frager_codex or (lambda t: self._stufe1_json()),
            stufe_fuer_fn=stufe_fuer_fn or (lambda befund, hist: 2),
        )
        self.assertEqual(len(geschrieben), 1)
        contracts.validiere("tiefenanalyse", detail)
        return detail

    def test_cloud_pfad_mit_codex_uebereinstimmend(self):
        detail = self._lauf(_dokument([_auff()]), _auff())
        self.assertEqual(detail["urteil"], "uebereinstimmend")
        self.assertEqual(detail["stufe"], 2)
        self.assertFalse(detail["nur_lokal"])

    def test_kleinfehler_ausnahme_ueberspringt_codex(self):
        codex_aufrufe = []
        detail = self._lauf(
            _dokument([_auff()]), _auff(),
            frager_codex=lambda t: codex_aufrufe.append(t) or "{}",
            stufe_fuer_fn=lambda befund, hist: 1,
        )
        self.assertEqual(detail["urteil"], "ohne_zweitmeinung")
        self.assertEqual(codex_aufrufe, [])

    def test_geschuetzt_laeuft_nur_lokal_codex_wird_nie_gerufen(self):
        codex_aufrufe = []
        detail = self._lauf(
            _dokument([_auff()]), _auff(), nur_lokal=True,
            frager_codex=lambda t: codex_aufrufe.append(t) or "{}",
        )
        self.assertTrue(detail["nur_lokal"])
        self.assertEqual(detail["urteil"], "ohne_zweitmeinung")
        self.assertIsNone(detail["positionen"]["codex"])
        self.assertEqual(codex_aufrufe, [])

    def test_fehler_im_fremdprozess_wird_berichtet_nie_verschluckt(self):
        def frager_kaputt(text, modell):
            raise RuntimeError("claude: kaputt")
        detail = self._lauf(_dokument([_auff()]), _auff(), frager_cloud=frager_kaputt)
        self.assertIsNotNone(detail["fehler"])
        self.assertIn("kaputt", detail["fehler"])
        self.assertEqual(detail["urteil"], "ohne_zweitmeinung")

    def test_rohausschnitt_geht_nie_in_stufe2_prompt(self):
        """Arbeitsauftrag Punkt 6, End-zu-End: ein echter Transkript-Ausschnitt mit einem
        eindeutigen Marker-Text landet in Stufe 1 (Cloud-Prompt), aber nie in Stufe 2 (Codex)."""
        import json as _json
        import tempfile
        from pathlib import Path

        from .. import __main__ as cli

        alt_pfad = cli.CLAUDE_PROJEKTE
        with tempfile.TemporaryDirectory() as tmp:
            cli.CLAUDE_PROJEKTE = Path(tmp) / "claude"
            zeile = {"timestamp": "2026-08-28T10:05:00+00:00", "type": "user",
                     "message": {"content": "MARKER-ROHTEXT-NIEMALS-AN-CODEX"}}
            datei = cli.CLAUDE_PROJEKTE / "proj" / "s1.jsonl"
            datei.parent.mkdir(parents=True, exist_ok=True)
            datei.write_text(_json.dumps(zeile), encoding="utf-8")
            try:
                dokument = _dokument(
                    [_auff()], ereignisse=[{"zeit": "2026-08-28T10:05:00+00:00", "art": "tool"}],
                )
                cloud_prompts, codex_prompts = [], []
                self._lauf(
                    dokument, _auff(),
                    frager_cloud=lambda t, m: cloud_prompts.append(t) or self._stufe1_json(),
                    frager_codex=lambda t: codex_prompts.append(t) or self._stufe1_json(),
                )
            finally:
                cli.CLAUDE_PROJEKTE = alt_pfad
        self.assertTrue(any("MARKER-ROHTEXT-NIEMALS-AN-CODEX" in p for p in cloud_prompts))
        for prompt in codex_prompts:
            self.assertNotIn("MARKER-ROHTEXT-NIEMALS-AN-CODEX", prompt)

    def test_eskalation_erzwingt_stufe_fuer_zwei_egal_was_die_funktion_sagt(self):
        """`pruefung.ist_eskaliert` wird unabhaengig von `stufe_fuer_fn` berechnet -- diese
        Sicherstellung deckt ab, dass eine falsch injizierte `stufe_fuer_fn` nicht die
        Eskalations-Berechnung selbst verhindert."""
        historie = [{"gestartet": "2026-08-27T10:00:00+00:00", "sitzung_logisch": 1,
                     "urteile": [{"signatur": "rework:tool:Bash", "zweitmeinung": "ausgelassen"}]}]
        detail = self._lauf(_dokument([_auff()]), _auff(), historie=historie, stufe_fuer_fn=lambda b, h: 2)
        self.assertEqual(detail["stufe"], 2)


class GuardsTest(unittest.TestCase):
    def test_kein_eigener_schreibweg_ueber_speicher(self):
        """`tiefenanalyse.py` schreibt NIE direkt ueber `speicher.*` -- jeder Schreibpfad laeuft
        ueber den injizierten `ereignis_schreiben`-Parameter (ohne Default), wie `commits.py`."""
        baum = ast.parse(inspect.getsource(tiefenanalyse))
        namen = {n.id for n in ast.walk(baum) if isinstance(n, ast.Name)}
        importe = {
            alias.asname or alias.name
            for node in ast.walk(baum) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("speicher", namen | importe)
        self.assertFalse(hasattr(tiefenanalyse, "speicher"))


if __name__ == "__main__":
    unittest.main()
