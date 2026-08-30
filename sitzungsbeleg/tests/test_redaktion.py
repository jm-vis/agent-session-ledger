"""Tests für redaktion.pruefe_beleg()/bereinige() — Sicherheitsnetz vor jeder Ausgabe."""
from __future__ import annotations

import unittest

from sitzungsbeleg import projekte, redaktion
from sitzungsbeleg.modell import Kopf, Subagent

from .hilfen import baue_beleg


class PruefeBelegTest(unittest.TestCase):
    def test_sauberer_beleg_ohne_verstoesse(self):
        beleg = baue_beleg()
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])

    def test_eingeschleuster_windows_pfad_wird_gefunden(self):
        kopf = Kopf(
            quelle="claude", sitzung_id="s1",
            projekt_name=r"C:\Beispiel\person\geheim",
        )
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("pfad" in v for v in verstoesse))

    def test_100_zeichen_string_wird_gefunden(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", version="x" * 100)
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("laenge" in v for v in verstoesse))

    def test_lokal_wort_wird_gefunden(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", git_branch="feature/_lokal-fix")
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("lokal" in v for v in verstoesse))

    def test_secret_muster_wird_gefunden(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", version="sk-abcdefghijklmnop")
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("secret" in v for v in verstoesse))

    def test_email_wird_gefunden(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", host="person@example.invalid")
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("email" in v for v in verstoesse))

    def test_verstoss_in_dict_schluessel_wird_gefunden(self):
        beleg = baue_beleg()
        beleg.kennzahlen.rework_dateien = {r"C:\Beispiel\person\datei.py": 3}
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("pfad" in v for v in verstoesse))

    def test_sauberes_auftrags_kurzlabel_bleibt_unveraendert(self):
        # Subagent.auftrag ist die einzige Ausnahme vom "nie Inhalte"-Kontrakt (modell.py) --
        # ein sauberes Kurzlabel (kein Pfad/Secret/E-Mail/_lokal, <= 80 Zeichen) darf stehen.
        beleg = baue_beleg(subagenten=[Subagent(agent_id="s1", auftrag="Block 4 Sitzungsdetail")])
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])

    def test_auftrag_mit_pfadverdacht_wird_gefunden(self):
        beleg = baue_beleg(subagenten=[Subagent(agent_id="s1", auftrag="Recherche 60_Internal/HR/Akte")])
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("pfad" in v for v in verstoesse))

    def test_openrouter_modellname_in_kopf_modelle_ist_kein_pfadverstoss(self):
        """Auftrag OpenRouter (2026-08-27, Fund Sitzung 545): ein Modellname im
        Namensraum-Format traegt einen Schraegstrich, ist aber kein Pfadverdacht --
        sonst wuerde C3 ihn vor dem Speichern zu '<redigiert>' zermahlen."""
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=["nvidia/nemotron-3-ultra-550b-a55b"])
        beleg = baue_beleg(kopf=kopf)
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])

    def test_hf_co_ollama_modellname_in_kopf_modelle_ist_kein_pfadverstoss(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=["hf.co/bartowski/some-model-GGUF:latest"])
        beleg = baue_beleg(kopf=kopf)
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])

    def test_echter_pfad_in_kopf_modelle_bleibt_verstoss(self):
        """Die Ausnahme gilt nur fuer die enge Modellkennungs-Form -- ein eingeschleuster
        Windows-Pfad in `kopf.modelle` bleibt ein Fund."""
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=[r"C:\Beispiel\person\geheim"])
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("pfad" in v for v in verstoesse))

    def test_lokal_wort_in_kopf_modelle_bleibt_verstoss(self):
        """C6-Marker sticht auch in `kopf.modelle` -- kein Umweg um den `_lokal`-Schutz."""
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=["anbieter/_lokal-modell"])
        beleg = baue_beleg(kopf=kopf)
        verstoesse = redaktion.pruefe_beleg(beleg)
        self.assertTrue(any("lokal" in v for v in verstoesse))


class BereinigeTest(unittest.TestCase):
    def test_pfad_wird_durch_redigiert_ersetzt(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", projekt_name=r"C:\Beispiel\person\geheim")
        beleg = baue_beleg(kopf=kopf)
        bereinigt = redaktion.bereinige(beleg)
        self.assertEqual(bereinigt.kopf.projekt_name, "<redigiert>")

    def test_bereinigung_traegt_privacy_auffaelligkeit_ein(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", projekt_name=r"C:\Beispiel\person\geheim")
        beleg = baue_beleg(kopf=kopf)
        redaktion.bereinige(beleg)
        regeln = [a.regel for a in beleg.auffaelligkeiten]
        self.assertIn("privacy:metadata_leak", regeln)
        treffer = [a for a in beleg.auffaelligkeiten if a.regel == "privacy:metadata_leak"][0]
        self.assertEqual(treffer.schwere, "hoch")

    def test_sauberer_beleg_bleibt_unveraendert_ohne_auffaelligkeit(self):
        beleg = baue_beleg()
        redaktion.bereinige(beleg)
        regeln = [a.regel for a in beleg.auffaelligkeiten]
        self.assertNotIn("privacy:metadata_leak", regeln)

    def test_verstossender_dict_schluessel_wird_entfernt(self):
        beleg = baue_beleg()
        beleg.kennzahlen.rework_dateien = {
            r"C:\Beispiel\person\datei.py": 3,
            "sauber-ref": 2,
        }
        redaktion.bereinige(beleg)
        self.assertNotIn(r"C:\Beispiel\person\datei.py", beleg.kennzahlen.rework_dateien)
        self.assertIn("sauber-ref", beleg.kennzahlen.rework_dateien)

    def test_openrouter_modellname_bleibt_nach_bereinigung_unveraendert(self):
        """`bereinige()` darf eine sichere Modellkennung nicht zu '<redigiert>' machen --
        sonst sieht `quellen.quelle_fuer()` nie den echten Namen (Fund Sitzung 545)."""
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=["nvidia/nemotron-3-ultra-550b-a55b"])
        beleg = baue_beleg(kopf=kopf)
        redaktion.bereinige(beleg)
        self.assertEqual(beleg.kopf.modelle, ["nvidia/nemotron-3-ultra-550b-a55b"])
        regeln = [a.regel for a in beleg.auffaelligkeiten]
        self.assertNotIn("privacy:metadata_leak", regeln)

    def test_echter_pfad_in_kopf_modelle_wird_trotzdem_redigiert(self):
        kopf = Kopf(quelle="claude", sitzung_id="s1", modelle=[r"C:\Beispiel\geheim", "claude-sonnet-5"])
        beleg = baue_beleg(kopf=kopf)
        redaktion.bereinige(beleg)
        self.assertIn("claude-sonnet-5", beleg.kopf.modelle)
        self.assertIn("<redigiert>", beleg.kopf.modelle)
        self.assertNotIn(r"C:\Beispiel\geheim", beleg.kopf.modelle)

    def test_nach_bereinigung_keine_verstoesse_mehr(self):
        kopf = Kopf(
            quelle="claude", sitzung_id="s1",
            projekt_name=r"C:\Beispiel\person\geheim",
            version="x" * 100,
            host="person@example.invalid",
        )
        beleg = baue_beleg(kopf=kopf)
        redaktion.bereinige(beleg)
        self.assertEqual(redaktion.pruefe_beleg(beleg), [])


class SichererBezeichnerTest(unittest.TestCase):
    """F3: redaktion.sicherer_bezeichner() — Allowlist-Regex, sonst Hash-Form."""

    def test_erlaubter_bezeichner_bleibt_unveraendert(self) -> None:
        self.assertEqual(
            redaktion.sicherer_bezeichner("mcp__claude-in-chrome__navigate"),
            "mcp__claude-in-chrome__navigate",
        )

    def test_einfacher_toolname_bleibt_unveraendert(self) -> None:
        self.assertEqual(redaktion.sicherer_bezeichner("Bash"), "Bash")

    def test_pfad_eingeschleust_wird_gehasht(self) -> None:
        wert = redaktion.sicherer_bezeichner(r"mcp__srv__C:\Users\x\tool")
        self.assertTrue(wert.startswith("unbekannt:"))
        self.assertNotIn("Users", wert)
        self.assertEqual(len(wert), len("unbekannt:") + 8)

    def test_hash_ist_deterministisch(self) -> None:
        a = redaktion.sicherer_bezeichner(r"C:\bad\name")
        b = redaktion.sicherer_bezeichner(r"C:\bad\name")
        self.assertEqual(a, b)

    def test_leerer_bezeichner_bleibt_leer(self) -> None:
        self.assertEqual(redaktion.sicherer_bezeichner(""), "")

    def test_zu_langer_bezeichner_wird_gehasht(self) -> None:
        wert = redaktion.sicherer_bezeichner("x" * 49)
        self.assertTrue(wert.startswith("unbekannt:"))


class RelativerPfadTest(unittest.TestCase):
    def test_schraegstrich_gilt_als_pfad(self) -> None:
        from .. import redaktion as r
        self.assertEqual(r._pruefe_string("60_Internal/HR/Max.md"), "pfad")
        self.assertEqual(r._pruefe_string("notiz\\ablage"), "pfad")
        self.assertIsNone(r._pruefe_string("tool:error_rate"))


class IstSichererModellnameTest(unittest.TestCase):
    """`_ist_sicherer_modellname` -- die enge kopf.modelle-Ausnahme von C3 (Auftrag
    OpenRouter, 2026-08-27). Bewusst eng: ``60_Internal/HR/Max.md`` (die generische
    Pfad-Testzeile oben) darf HIER NICHT durchrutschen, sonst waere die Ausnahme ein
    Schlupfloch fuer die generische Pfad-Regel."""

    def test_openrouter_id_gilt_als_sicher(self) -> None:
        self.assertTrue(redaktion._ist_sicherer_modellname("nvidia/nemotron-3-ultra-550b-a55b"))

    def test_glm_mit_free_tag_gilt_als_sicher(self) -> None:
        self.assertTrue(redaktion._ist_sicherer_modellname("z-ai/glm-5.2:free"))

    def test_hf_co_ollama_pfad_gilt_als_sicher(self) -> None:
        self.assertTrue(redaktion._ist_sicherer_modellname("hf.co/bartowski/some-model-GGUF:latest"))

    def test_modellname_ohne_schraegstrich_gilt_als_sicher(self) -> None:
        self.assertTrue(redaktion._ist_sicherer_modellname("claude-sonnet-5"))

    def test_echter_relativer_pfad_gilt_nicht_als_sicher(self) -> None:
        self.assertFalse(redaktion._ist_sicherer_modellname("60_Internal/HR/Max.md"))

    def test_windows_pfad_gilt_nicht_als_sicher(self) -> None:
        self.assertFalse(redaktion._ist_sicherer_modellname(r"C:\Beispiel\geheim"))

    def test_lokal_wort_gilt_nicht_als_sicher(self) -> None:
        self.assertFalse(redaktion._ist_sicherer_modellname("anbieter/_lokal-modell"))

    def test_zu_viele_segmente_gelten_nicht_als_sicher(self) -> None:
        self.assertFalse(redaktion._ist_sicherer_modellname("a/b/c/d"))

    def test_leerer_wert_gilt_nicht_als_sicher(self) -> None:
        self.assertFalse(redaktion._ist_sicherer_modellname(""))


class ZulaessigkeitTest(unittest.TestCase):
    """C6: redaktion.zulaessigkeit(beleg) -- 'geschuetzt' bei _lokal-Pfad oder HR-Projekt,
    sonst 'cloud-ok'. Funktioniert auf `Beleg` UND dessen `.als_dict()`-Projektion."""

    def setUp(self) -> None:
        self.alt_lade_aliase = projekte.lade_aliase

    def tearDown(self) -> None:
        projekte.lade_aliase = self.alt_lade_aliase

    def test_cloud_ok_ohne_lokal_pfad_und_ohne_hr_bezug(self) -> None:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", projekt_name="Host-Workspace"))
        self.assertEqual(redaktion.zulaessigkeit(beleg), "cloud-ok")

    def test_geschuetzt_bei_lokal_pfad_irgendwo_im_beleg(self) -> None:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", git_branch="feature/_lokal-fix"))
        self.assertEqual(redaktion.zulaessigkeit(beleg), "geschuetzt")

    def test_geschuetzt_bei_hr_namensmuster_ohne_alias_eintrag(self) -> None:
        projekte.lade_aliase = lambda *a, **k: {}
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", projekt_name="HR"))
        self.assertEqual(redaktion.zulaessigkeit(beleg), "geschuetzt")

    def test_geschuetzt_bei_bereich_hr_im_projekt_alias(self) -> None:
        projekte.lade_aliase = lambda *a, **k: {"Projekt-X": {"projekt": "Projekt-X", "bereich": "HR"}}
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", projekt_name="Projekt-X"))
        self.assertEqual(redaktion.zulaessigkeit(beleg), "geschuetzt")

    def test_cloud_ok_bleibt_bei_alias_ohne_hr_bezug(self) -> None:
        projekte.lade_aliase = lambda *a, **k: {"Projekt-X": {"projekt": "Projekt-X", "kontext": "arbeit"}}
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", projekt_name="Projekt-X"))
        self.assertEqual(redaktion.zulaessigkeit(beleg), "cloud-ok")

    def test_funktioniert_auch_auf_als_dict_projektion(self) -> None:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s", git_branch="_lokal"))
        self.assertEqual(redaktion.zulaessigkeit(beleg.als_dict()), "geschuetzt")


class BereinigeTextTest(unittest.TestCase):
    """redaktion.bereinige_text(text) -- wie `bereinige`, aber fuer einen einzelnen Freitext
    (Modellausgaben, Chat, Fehlertexte) und OHNE die 80-Zeichen-Grenze."""

    def test_sauberer_text_bleibt_unveraendert(self) -> None:
        self.assertEqual(redaktion.bereinige_text("alles sauber"), "alles sauber")

    def test_langer_text_ohne_verstoss_bleibt_unveraendert(self) -> None:
        text = "kein Verstoss hier, nur normaler Fliesstext. " * 20
        self.assertEqual(redaktion.bereinige_text(text), text)

    def test_pfad_im_freitext_wird_redigiert(self) -> None:
        self.assertEqual(redaktion.bereinige_text(r"siehe C:\Users\x\geheim.txt"), redaktion.REDIGIERT)

    def test_lokal_wort_im_freitext_wird_redigiert(self) -> None:
        self.assertEqual(redaktion.bereinige_text("Hinweis zu _lokal Daten"), redaktion.REDIGIERT)

    def test_email_im_freitext_wird_redigiert(self) -> None:
        self.assertEqual(redaktion.bereinige_text("Kontakt: person@example.invalid"), redaktion.REDIGIERT)

    def test_leerer_text_bleibt_leer(self) -> None:
        self.assertEqual(redaktion.bereinige_text(""), "")


class BereinigeChatTextTest(unittest.TestCase):
    """redaktion.bereinige_chat_text(text) -- Nachtrag 2026-08-27 Punkt 8: nur der Pfad-TOKEN
    wird ersetzt, Rest der Nachricht bleibt stehen; Secrets/E-Mail/`_lokal` weiter der GANZE Text
    (unveraendert wie `bereinige_text`)."""

    def test_pfad_token_wird_ersetzt_rest_bleibt(self) -> None:
        text = "Bitte scripts/sitzungsbeleg/pruefung.py pruefen, danke."
        self.assertEqual(redaktion.bereinige_chat_text(text), "Bitte <pfad> pruefen, danke.")

    def test_windows_pfad_mit_laufwerksbuchstabe_wird_ersetzt(self) -> None:
        text = r"siehe C:\Users\x\geheim.txt bitte"
        self.assertEqual(redaktion.bereinige_chat_text(text), "siehe <pfad> bitte")

    def test_tilde_pfad_wird_ersetzt(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("liegt unter ~/foo/bar"), "liegt unter <pfad>")

    def test_und_oder_bleibt_stehen(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("mach A und/oder B"), "mach A und/oder B")

    def test_24_7_bleibt_stehen(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("laeuft 24/7 durch"), "laeuft 24/7 durch")

    def test_bruch_bleibt_stehen(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("etwa 3/4 der Faelle"), "etwa 3/4 der Faelle")

    def test_lokal_wort_redigiert_ganzen_text(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("Hinweis zu _lokal Daten"), redaktion.REDIGIERT)

    def test_email_redigiert_ganzen_text(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("Kontakt: person@example.invalid"), redaktion.REDIGIERT)

    def test_secret_redigiert_ganzen_text(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text("Key ist sk-abc123"), redaktion.REDIGIERT)

    def test_sauberer_text_ohne_slash_bleibt_unveraendert(self) -> None:
        text = "Alles sauber, keine Pfade hier."
        self.assertEqual(redaktion.bereinige_chat_text(text), text)

    def test_leerer_text_bleibt_leer(self) -> None:
        self.assertEqual(redaktion.bereinige_chat_text(""), "")

    def test_beleg_redaktion_bleibt_unveraendert_ganzer_text_bei_pfad(self) -> None:
        """Kontrolle: `bereinige_text` (Beleg/Stufe-1-2-Urteile) redigiert bei einem Pfad weiter
        den GANZEN Text -- nur `bereinige_chat_text` (Chat) wurde umgestellt."""
        self.assertEqual(redaktion.bereinige_text("siehe scripts/x.py bitte"), redaktion.REDIGIERT)


class ZulaessigkeitPersonaCuraTest(unittest.TestCase):
    """C14: persona=cura im Kopf macht den Beleg geschuetzt -- auch ohne Schutzpfad/HR."""

    def test_cura_ist_geschuetzt(self) -> None:
        beleg = {"kopf": {"projekt_name": "irgendwas", "quelle": "claude", "persona": "cura"}}
        self.assertEqual(redaktion.zulaessigkeit(beleg), "geschuetzt")

    def test_vico_bleibt_cloud_ok(self) -> None:
        beleg = {"kopf": {"projekt_name": "irgendwas", "quelle": "claude", "persona": "vico"}}
        self.assertEqual(redaktion.zulaessigkeit(beleg), "cloud-ok")


class BereinigeFehlertextTest(unittest.TestCase):
    """redaktion.bereinige_fehlertext(text) -- Paket K (Tiefenanalyse-Fehlertexte, Entscheid
    2026-08-28): erst `bereinige_text()` (Pfad/Secret-Praefix/E-Mail/`_lokal`, GANZER Text),
    zusaetzlich token-weise Host/Schluessel/Name."""

    def test_pfad_redigiert_ganzen_text_wie_bereinige_text(self) -> None:
        text = "Fehler in scripts/sitzungsbeleg/x.py Zeile 12"
        self.assertEqual(redaktion.bereinige_fehlertext(text), redaktion.REDIGIERT)

    def test_email_redigiert_ganzen_text(self) -> None:
        text = "Kontakt bei Fehlern: person@example.invalid"
        self.assertEqual(redaktion.bereinige_fehlertext(text), redaktion.REDIGIERT)

    def test_bekanntes_secret_praefix_redigiert_ganzen_text(self) -> None:
        text = "Auth fehlgeschlagen, Key sk-abcdefghijklmnop ungueltig"
        self.assertEqual(redaktion.bereinige_fehlertext(text), redaktion.REDIGIERT)

    def test_generischer_schluessel_wird_token_redigiert_rest_bleibt(self) -> None:
        text = "Verbindung fehlgeschlagen, token a1B2c3D4e5F6g7H8i9J0 abgelehnt"
        self.assertEqual(
            redaktion.bereinige_fehlertext(text),
            "Verbindung fehlgeschlagen, token <schluessel> abgelehnt",
        )

    def test_hostname_wird_token_redigiert_rest_bleibt(self) -> None:
        text = "Verbindung zu api.example.com:8443 abgelehnt"
        self.assertEqual(redaktion.bereinige_fehlertext(text), "Verbindung zu <host> abgelehnt")

    def test_dateiname_ohne_slash_gilt_nicht_als_host(self) -> None:
        text = "Fehler beim Ausfuehren von script.py"
        self.assertEqual(redaktion.bereinige_fehlertext(text), text)

    def test_name_nach_schluesselwort_wird_redigiert(self) -> None:
        text = "Zugriff verweigert fuer user: max.mustermann"
        self.assertEqual(redaktion.bereinige_fehlertext(text), "Zugriff verweigert fuer user: <name>")

    def test_sauberer_text_bleibt_unveraendert(self) -> None:
        text = "Exit-Code 127: Befehl nicht gefunden"
        self.assertEqual(redaktion.bereinige_fehlertext(text), text)

    def test_leerer_text_bleibt_leer(self) -> None:
        self.assertEqual(redaktion.bereinige_fehlertext(""), "")


if __name__ == "__main__":
    unittest.main()
