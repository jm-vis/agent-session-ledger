"""Pruef-Regelwerk (Phase 1 B): Zustandsableitung (C2), Stufen/Eskalation (C3), Lauf-Registry
und Lauf-Ausfuehrung (C4/C5) -- alles mit Fake-Fragern, kein echter claude-/codex-Prozess."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from .. import contracts, fehlerbild_pruefung, pruefung, speicher, vieraugen, web
from ..modell import Auffaelligkeit

from .hilfen import baue_beleg
from .test_web import FakeLaufer


def _vor_tagen(tage: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat()


def _entscheid(status: str, entschieden_am: str = "2026-08-20T10:00:00+00:00",
               sitzung_ref=None, signatur: str = "sig") -> dict:
    return {"signatur": signatur, "sitzung_ref": sitzung_ref, "status": status, "entschieden_am": entschieden_am}


# ---------------------------------------------------------------------------------------------
# C2 -- Zustandsableitung
# ---------------------------------------------------------------------------------------------

class StatusFuerTest(unittest.TestCase):
    def test_offen_ohne_entscheid_lauf_urteil(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        self.assertEqual(pruefung.status_fuer(befund, [], [], []), "offen")

    def test_in_pruefung_wenn_laufender_lauf_die_signatur_umfasst(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        laufend = [{"lauf_id": "p-x", "scope": "sitzung", "sitzung_logisch": 1, "signaturen": ["sig"]}]
        self.assertEqual(pruefung.status_fuer(befund, [], [], laufend), "in_pruefung")

    def test_bestaetigt_verworfen_dissens_aus_juengstem_urteil(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        for ergebnis in ("bestaetigt", "verworfen", "dissens"):
            lauf = {"sitzung_logisch": 1, "gestartet": "2026-08-27T10:00:00+00:00",
                     "urteile": [{"signatur": "sig", "ergebnis": ergebnis}]}
            self.assertEqual(pruefung.status_fuer(befund, [], [lauf], []), ergebnis)

    def test_juengstes_urteil_gewinnt_ueber_mehrere_laeufe(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        alt = {"sitzung_logisch": 1, "gestartet": "2026-08-20T10:00:00+00:00",
               "urteile": [{"signatur": "sig", "ergebnis": "verworfen"}]}
        neu = {"sitzung_logisch": 1, "gestartet": "2026-08-26T10:00:00+00:00",
               "urteile": [{"signatur": "sig", "ergebnis": "bestaetigt"}]}
        self.assertEqual(pruefung.status_fuer(befund, [], [alt, neu], []), "bestaetigt")

    def test_erledigt_und_obsolet_aus_entscheid(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        for status in ("erledigt", "obsolet"):
            self.assertEqual(pruefung.status_fuer(befund, [_entscheid(status)], [], []), status)

    def test_rueckfall_wenn_sitzung_nach_entscheid_liegt(self) -> None:
        befund = {
            "signatur": "sig", "sitzung_logisch": 2,
            "sitzungen": [{"sitzung_id": 2, "zeit": "2026-08-25T10:00:00+00:00", "treffer": 1}],
        }
        entscheide = [_entscheid("erledigt", entschieden_am="2026-08-20T10:00:00+00:00")]
        self.assertEqual(pruefung.status_fuer(befund, entscheide, [], []), "rueckfall")

    def test_offen_entscheid_wirkt_als_wiedereroeffnung(self) -> None:
        befund = {"signatur": "sig", "sitzung_logisch": 1}
        entscheide = [
            _entscheid("erledigt", entschieden_am="2026-08-20T10:00:00+00:00"),
            _entscheid("offen", entschieden_am="2026-08-25T10:00:00+00:00"),
        ]
        self.assertEqual(pruefung.status_fuer(befund, entscheide, [], []), "offen")


class GruppenStatusTest(unittest.TestCase):
    def test_hoechster_rang_gewinnt(self) -> None:
        gruppe = [{"signatur": "a", "sitzung_logisch": 1}, {"signatur": "b", "sitzung_logisch": 1}]
        laeufe = [{"sitzung_logisch": 1, "gestartet": "t", "urteile": [{"signatur": "a", "ergebnis": "dissens"}]}]
        self.assertEqual(pruefung.gruppen_status(gruppe, [], laeufe, []), "dissens")

    def test_leere_gruppe_ist_offen(self) -> None:
        self.assertEqual(pruefung.gruppen_status([], [], [], []), "offen")


class VieraugenAlsLaeufeTest(unittest.TestCase):
    """Nachtrag 2026-08-27 Punkt 1 (E-Fund): Legacy-`vieraugen/review`-Ereignisse (C1 Regel 2)
    flossen bisher nicht in Schritt 3 der C2-Ableitung ein -- Sitzung 137 zeigte "OFFEN", obwohl
    Claude+Codex ueber die alte Vier-Augen-Pruefung "bestaetigt" geurteilt hatten."""

    def test_normalisiert_befunde_zu_urteilen(self) -> None:
        ereignisse = [{"sitzung_logisch": 137, "befunde": [
            {"signatur": "rework:tool:Bash", "status": "bestaetigt"},
            {"signatur": "latency:slow_turn:tool:Bash", "status": "dissens"},
        ]}]
        self.assertEqual(pruefung.vieraugen_als_laeufe(ereignisse), [{
            "sitzung_logisch": 137, "gestartet": "",
            "urteile": [
                {"signatur": "rework:tool:Bash", "ergebnis": "bestaetigt"},
                {"signatur": "latency:slow_turn:tool:Bash", "ergebnis": "dissens"},
            ],
        }])

    def test_unklar_wird_zu_dissens(self) -> None:
        ereignisse = [{"sitzung_logisch": 5, "befunde": [{"signatur": "s", "status": "unklar"}]}]
        self.assertEqual(pruefung.vieraugen_als_laeufe(ereignisse)[0]["urteile"], [{"signatur": "s", "ergebnis": "dissens"}])

    def test_fallback_sitzung_logisch_wenn_ereignis_ihn_nicht_traegt(self) -> None:
        ereignisse = [{"befunde": [{"signatur": "s", "status": "verworfen"}]}]
        self.assertEqual(pruefung.vieraugen_als_laeufe(ereignisse, sitzung_logisch_fallback=9)[0]["sitzung_logisch"], 9)

    def test_befund_ohne_signatur_faellt_auf_regel_zurueck(self) -> None:
        ereignisse = [{"sitzung_logisch": 1, "befunde": [{"regel": "zusatz:doppelte_kosten", "signatur": "", "status": "bestaetigt"}]}]
        self.assertEqual(pruefung.vieraugen_als_laeufe(ereignisse)[0]["urteile"][0]["signatur"], "zusatz:doppelte_kosten")


class AnreichernLegacyVieraugenTest(unittest.TestCase):
    """`pruefung.anreichern` (GET /api/sitzung/{id}) -- Legacy-Vier-Augen treibt Status/
    Gruppenstatus, aber NICHT das `pruefung`-Feld je Auffaelligkeit (das Frontend hat dafuer
    einen eigenen Alt-Fallback, `pruefungAusAlt` in sitzung.js)."""

    def _antwort(self, vieraugen: dict | None) -> dict:
        return {
            "sitzung_logisch": 137,
            "dokument": {"auffaelligkeiten": [{"regel": "rework:tool", "signatur": "rework:tool:Bash"}]},
            "vieraugen": vieraugen,
        }

    def test_legacy_bestaetigt_ergibt_status_und_gruppenstatus_bestaetigt(self) -> None:
        vieraugen = {"befunde": [{"signatur": "rework:tool:Bash", "claude": "ja", "codex": "ja", "status": "bestaetigt"}]}
        ergebnis = pruefung.anreichern(self._antwort(vieraugen), lambda quelle: [])
        self.assertEqual(ergebnis["dokument"]["auffaelligkeiten"][0]["status"], "bestaetigt")
        self.assertEqual(ergebnis["gruppen_status"]["rework:tool"], "bestaetigt")

    def test_legacy_unklar_ergibt_dissens(self) -> None:
        vieraugen = {"befunde": [{"signatur": "rework:tool:Bash", "status": "unklar"}]}
        ergebnis = pruefung.anreichern(self._antwort(vieraugen), lambda quelle: [])
        self.assertEqual(ergebnis["dokument"]["auffaelligkeiten"][0]["status"], "dissens")

    def test_legacy_treibt_status_nicht_das_pruefung_feld(self) -> None:
        vieraugen = {"befunde": [{"signatur": "rework:tool:Bash", "status": "bestaetigt"}]}
        ergebnis = pruefung.anreichern(self._antwort(vieraugen), lambda quelle: [])
        self.assertIsNone(ergebnis["dokument"]["auffaelligkeiten"][0]["pruefung"])

    def test_echter_pruefung_lauf_gewinnt_ueber_legacy_vieraugen(self) -> None:
        vieraugen = {"befunde": [{"signatur": "rework:tool:Bash", "status": "verworfen"}]}
        laeufe = [{"sitzung_logisch": 137, "gestartet": "2026-08-27T10:00:00+00:00",
                   "urteile": [{"signatur": "rework:tool:Bash", "ergebnis": "bestaetigt"}]}]
        ergebnis = pruefung.anreichern(
            self._antwort(vieraugen), lambda quelle: laeufe if quelle == "pruefung" else []
        )
        self.assertEqual(ergebnis["dokument"]["auffaelligkeiten"][0]["status"], "bestaetigt")

    def test_ohne_vieraugen_bleibt_offen(self) -> None:
        ergebnis = pruefung.anreichern(self._antwort(None), lambda quelle: [])
        self.assertEqual(ergebnis["dokument"]["auffaelligkeiten"][0]["status"], "offen")


# ---------------------------------------------------------------------------------------------
# C3 -- Stufen und Eskalation
# ---------------------------------------------------------------------------------------------

def _befund_stufe1_ok() -> dict:
    return {"signatur": "sig", "regel": "tool:error_rate", "schwere": "hinweis",
            "komplexitaet": "einfach", "urteil_stufe1": "ja", "scope": "befund", "rueckfall": False}


class StufeFuerTest(unittest.TestCase):
    def test_alle_bedingungen_erfuellt_ergibt_stufe_1(self) -> None:
        self.assertEqual(pruefung.stufe_fuer(_befund_stufe1_ok(), []), 1)

    def test_schwere_ungleich_hinweis_erzwingt_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "schwere": "warnung"}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)

    def test_komplexitaet_komplex_erzwingt_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "komplexitaet": "komplex"}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)

    def test_wiederkehrend_ab_drei_sitzungen_erzwingt_stufe_2(self) -> None:
        historie = [
            {"gestartet": _vor_tagen(1), "sitzung_logisch": i, "urteile": [{"signatur": "sig"}]}
            for i in (10, 11, 12)
        ]
        self.assertEqual(pruefung.stufe_fuer(_befund_stufe1_ok(), historie), 2)

    def test_zwei_sitzungen_bleiben_unter_der_schwelle(self) -> None:
        historie = [
            {"gestartet": _vor_tagen(1), "sitzung_logisch": i, "urteile": [{"signatur": "sig"}]}
            for i in (10, 11)
        ]
        self.assertEqual(pruefung.stufe_fuer(_befund_stufe1_ok(), historie), 1)

    def test_rueckfall_erzwingt_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "rueckfall": True}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)

    def test_cost_spike_erzwingt_immer_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "regel": "cost:spike"}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)

    def test_scope_fehlerbild_erzwingt_immer_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "scope": "fehlerbild"}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)

    def test_urteil_unklar_erzwingt_stufe_2(self) -> None:
        befund = {**_befund_stufe1_ok(), "urteil_stufe1": "unklar"}
        self.assertEqual(pruefung.stufe_fuer(befund, []), 2)


class EskalationTest(unittest.TestCase):
    def test_ist_eskaliert_erkennt_ausgelassene_zweitmeinung_unbegrenzt_in_der_zeit(self) -> None:
        historie = [{"gestartet": _vor_tagen(400), "sitzung_logisch": 1,
                     "urteile": [{"signatur": "sig", "zweitmeinung": "ausgelassen"}]}]
        self.assertTrue(pruefung.ist_eskaliert({"signatur": "sig"}, historie))

    def test_eskalation_erzwingt_stufe_2_trotz_kleinfehler_bedingungen(self) -> None:
        historie = [{"gestartet": _vor_tagen(100), "sitzung_logisch": 1,
                     "urteile": [{"signatur": "sig", "zweitmeinung": "ausgelassen"}]}]
        self.assertEqual(pruefung.stufe_fuer(_befund_stufe1_ok(), historie), 2)

    def test_ohne_ausgelassene_historie_keine_eskalation(self) -> None:
        historie = [{"gestartet": _vor_tagen(1), "sitzung_logisch": 1,
                     "urteile": [{"signatur": "sig", "zweitmeinung": "eingeholt"}]}]
        self.assertFalse(pruefung.ist_eskaliert({"signatur": "sig"}, historie))


# ---------------------------------------------------------------------------------------------
# C5 -- Lauf-Registry
# ---------------------------------------------------------------------------------------------

class LaufRegistryTest(unittest.TestCase):
    def tearDown(self) -> None:
        pruefung._laufend.clear()

    def test_ueberschneidung_liefert_bestehende_lauf_id(self) -> None:
        self.assertIsNone(pruefung.registrieren("p-a", "sitzung", pruefung.schluessel_fuer("sitzung", 1, ["s1", "s2"])))
        konflikt = pruefung.registrieren("p-b", "befund", pruefung.schluessel_fuer("befund", 1, ["s2"]))
        self.assertEqual(konflikt, "p-a")

    def test_disjunkte_laeufe_laufen_parallel(self) -> None:
        self.assertIsNone(pruefung.registrieren("p-a", "befund", pruefung.schluessel_fuer("befund", 1, ["s1"])))
        self.assertIsNone(pruefung.registrieren("p-b", "befund", pruefung.schluessel_fuer("befund", 2, ["s1"])))

    def test_ablauf_nach_30_minuten_gibt_signatur_frei(self) -> None:
        jetzt = datetime.now(timezone.utc)
        schluessel = pruefung.schluessel_fuer("befund", 1, ["s1"])
        pruefung.registrieren("p-alt", "befund", schluessel, jetzt - timedelta(minutes=31))
        self.assertIsNone(pruefung.registrieren("p-neu", "befund", schluessel, jetzt))

    def test_unter_30_minuten_blockiert_weiterhin(self) -> None:
        jetzt = datetime.now(timezone.utc)
        schluessel = pruefung.schluessel_fuer("befund", 1, ["s1"])
        pruefung.registrieren("p-alt", "befund", schluessel, jetzt - timedelta(minutes=29))
        self.assertEqual(pruefung.registrieren("p-neu", "befund", schluessel, jetzt), "p-alt")

    def test_freigeben_entfernt_lauf(self) -> None:
        pruefung.registrieren("p-a", "befund", pruefung.schluessel_fuer("befund", 1, ["s1"]))
        pruefung.freigeben("p-a")
        self.assertIsNone(pruefung.ist_registriert("p-a"))

    def test_fehlerbild_schluessel_ignoriert_sitzung_logisch(self) -> None:
        self.assertEqual(pruefung.schluessel_fuer("fehlerbild", None, ["sig"]), {(None, "sig")})


# ---------------------------------------------------------------------------------------------
# C4/C5 -- Lauf-Ausfuehrung mit Fake-Fragern
# ---------------------------------------------------------------------------------------------

def _beleg_mit_befund(regel: str = "tool:error_rate", signatur: str = "sig", schwere: str = "hinweis"):
    beleg = baue_beleg()
    beleg.auffaelligkeiten = [Auffaelligkeit(regel=regel, schwere=schwere, signatur=signatur)]
    return beleg


class LaufAusfuehrenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.geschrieben: list[tuple] = []

    def _schreiben(self, quelle: str, typ: str, detail: dict) -> None:
        self.geschrieben.append((quelle, typ, detail))

    def tearDown(self) -> None:
        pruefung._laufend.clear()

    def test_konsens_bestaetigt(self) -> None:
        beleg = _beleg_mit_befund(schwere="warnung")  # nicht 'hinweis' -> Stufe 2 Pflicht
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"])
        claude = lambda t: '[{"signatur": "sig", "kategorie": "Fehler", "komplexitaet": "komplex", ' \
                           '"empfehlung": "pruefen", "urteil": "ja"}]'
        codex = lambda t: '[{"signatur": "sig", "urteil": "ja", "begruendung": "passt"}]'
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=codex, ereignis_schreiben=self._schreiben
        )
        self.assertIsNone(detail["fehler"])
        self.assertEqual(detail["urteile"][0]["ergebnis"], "bestaetigt")
        self.assertEqual(detail["stufe_max"], 2)
        contracts.validiere("pruefung_lauf", detail)
        self.assertEqual(self.geschrieben[0][:2], ("pruefung", "lauf"))

    def test_urteil_traegt_lauf_id(self) -> None:
        """Nachtrag 2026-08-27 Punkt 2: `_juengstes_urteil` (a.pruefung) muss die `lauf_id`
        kennen, damit "Codex nachholen" `{stufe:2, lauf_ref}` bauen kann."""
        beleg = _beleg_mit_befund(schwere="warnung")
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"])
        claude = lambda t: '[{"signatur": "sig", "kategorie": "x", "komplexitaet": "komplex", ' \
                           '"empfehlung": "y", "urteil": "ja"}]'
        codex = lambda t: '[{"signatur": "sig", "urteil": "ja", "begruendung": "passt"}]'
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=codex, ereignis_schreiben=self._schreiben
        )
        self.assertEqual(detail["urteile"][0]["lauf_id"], detail["lauf_id"])
        contracts.validiere("pruefung_lauf", detail)

    def test_codex_nachholen_erzwingt_stufe_2_trotz_kleinfehler_ausnahme(self) -> None:
        """Nachtrag 2026-08-27 Punkt 2: `stufe: 2` im Body (Codex nachholen) erzwingt Codex, auch
        wenn die Kleinfehler-Ausnahme sonst Stufe 1 genuegen liesse."""
        beleg = _beleg_mit_befund(schwere="hinweis")  # Kleinfehler-Ausnahme wuerde sonst greifen
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"], stufe=2, lauf_ref="p-vorher")
        claude = lambda t: '[{"signatur": "sig", "kategorie": "x", "komplexitaet": "einfach", ' \
                           '"empfehlung": "y", "urteil": "ja"}]'
        codex = lambda t: '[{"signatur": "sig", "urteil": "ja", "begruendung": "nachgeholt"}]'
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=codex, ereignis_schreiben=self._schreiben
        )
        self.assertEqual(detail["stufe_max"], 2)
        self.assertEqual(detail["urteile"][0]["zweitmeinung"], "eingeholt")
        contracts.validiere("pruefung_lauf", detail)

    def test_dissens_bei_abweichenden_urteilen(self) -> None:
        beleg = _beleg_mit_befund(schwere="warnung")
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"])
        claude = lambda t: '[{"signatur": "sig", "kategorie": "x", "komplexitaet": "komplex", ' \
                           '"empfehlung": "y", "urteil": "ja"}]'
        codex = lambda t: '[{"signatur": "sig", "urteil": "nein", "begruendung": "z"}]'
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=codex, ereignis_schreiben=self._schreiben
        )
        self.assertEqual(detail["urteile"][0]["ergebnis"], "dissens")
        contracts.validiere("pruefung_lauf", detail)

    def test_codex_ausgelassen_bei_kleinfehler(self) -> None:
        beleg = _beleg_mit_befund(schwere="hinweis")
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"])
        claude = lambda t: '[{"signatur": "sig", "kategorie": "x", "komplexitaet": "einfach", ' \
                           '"empfehlung": "y", "urteil": "ja"}]'

        def codex_darf_nicht_aufgerufen_werden(_t):
            raise AssertionError("Codex haette bei der Kleinfehler-Ausnahme nicht aufgerufen werden duerfen")

        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=codex_darf_nicht_aufgerufen_werden,
            ereignis_schreiben=self._schreiben,
        )
        urteil = detail["urteile"][0]
        self.assertEqual(urteil["zweitmeinung"], "ausgelassen")
        self.assertIsNone(urteil["codex"])
        self.assertEqual(urteil["ergebnis"], "bestaetigt")
        self.assertEqual(detail["stufe_max"], 1)
        self.assertIsNone(detail["modell_stufe2"])
        contracts.validiere("pruefung_lauf", detail)

    def test_frager_fehler_setzt_fehlerfeld_urteile_leer_und_gibt_lauf_frei(self) -> None:
        beleg = _beleg_mit_befund(schwere="warnung")
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=5, signaturen=["sig"])

        def claude_kaputt(_t):
            raise RuntimeError("claude: offline")

        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude_kaputt, frager_codex=lambda t: "[]",
            ereignis_schreiben=self._schreiben,
        )
        self.assertIsNotNone(detail["fehler"])
        self.assertEqual(detail["urteile"], [])
        contracts.validiere("pruefung_lauf", detail)
        self.assertIsNone(pruefung.ist_registriert(detail["lauf_id"]))

    def test_scope_sitzung_ohne_signaturen_prueft_nur_offene(self) -> None:
        beleg = baue_beleg()
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="tool:error_rate", schwere="hinweis", signatur="a"),
            Auffaelligkeit(regel="tool:error_rate", schwere="hinweis", signatur="b"),
        ]
        body = contracts.PruefungBody(scope="sitzung", sitzung_logisch=7, signaturen=[])
        entscheide = [{"signatur": "b", "sitzung_ref": None, "status": "erledigt",
                       "entschieden_am": "2026-08-01T00:00:00+00:00"}]
        claude = lambda t: '[{"signatur": "a", "kategorie": "x", "komplexitaet": "einfach", ' \
                           '"empfehlung": "y", "urteil": "nein"}]'
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: beleg, frager_claude=claude, frager_codex=lambda t: "[]",
            ereignis_schreiben=self._schreiben, entscheide=entscheide,
        )
        self.assertEqual(detail["signaturen"], ["a"])
        contracts.validiere("pruefung_lauf", detail)

    def test_scope_fehlerbild_ohne_sitzungen_liefert_contract_gueltigen_fehler(self) -> None:
        """Nachtrag 2026-08-27 Punkt 3: `_fehlerbild_stub` ist ersetzt -- ohne betroffene
        Sitzungen im Zeitraum bleibt ein erklaerender `fehler`, sonst laeuft die echte
        Stufe-1/2-Pipeline (siehe `FehlerbildAusfuehrenTest`)."""
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: None, frager_claude=lambda t: "[]", frager_codex=lambda t: "[]",
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [],
        )
        self.assertIn("keine Sitzungen", detail["fehler"])
        self.assertEqual(detail["urteile"], [])
        contracts.validiere("pruefung_lauf", detail)

    def test_ueberschneidender_lauf_wirft_laufkonflikt(self) -> None:
        beleg = _beleg_mit_befund()
        body = contracts.PruefungBody(scope="befund", sitzung_logisch=9, signaturen=["sig"])
        pruefung.registrieren("p-vorher", "befund", pruefung.schluessel_fuer("befund", 9, ["sig"]))
        with self.assertRaises(pruefung.LaufKonflikt):
            pruefung.lauf_ausfuehren(
                body, lambda sid: beleg, frager_claude=lambda t: "[]", frager_codex=lambda t: "[]",
                ereignis_schreiben=self._schreiben,
            )

    def test_unbekannte_sitzung_beim_beleg_laden_setzt_fehler(self) -> None:
        def beleg_laden_kaputt(_sid):
            raise ValueError("Sitzung 42 nicht gefunden")

        body = contracts.PruefungBody(scope="sitzung", sitzung_logisch=42, signaturen=[])
        detail = pruefung.lauf_ausfuehren(
            body, beleg_laden_kaputt, frager_claude=lambda t: "[]", frager_codex=lambda t: "[]",
            ereignis_schreiben=self._schreiben,
        )
        self.assertIn("nicht gefunden", detail["fehler"])
        contracts.validiere("pruefung_lauf", detail)


# ---------------------------------------------------------------------------------------------
# C3 -- Scope `fehlerbild` (Nachtrag 2026-08-27 Punkt 3): sitzungsuebergreifende Einordnung +
# Standardisierungs-Datei. `_fehlerbild_stub` (Phase 2 G) ist ersetzt.
# ---------------------------------------------------------------------------------------------

class FehlerbildAusfuehrenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.geschrieben: list[tuple] = []
        self.dateien: dict[str, str] = {}

    def _schreiben(self, quelle: str, typ: str, detail: dict) -> None:
        self.geschrieben.append((quelle, typ, detail))

    def _datei_schreiben(self, pfad: str, inhalt: str) -> str:
        self.dateien[pfad] = inhalt
        return pfad

    def tearDown(self) -> None:
        pruefung._laufend.clear()

    def test_ohne_sitzungen_bleibt_fehler_und_schreibt_keine_datei(self) -> None:
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: None, frager_claude=lambda t: "[]", frager_codex=lambda t: "[]",
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [],
            datei_schreiben=self._datei_schreiben,
        )
        self.assertIsNotNone(detail["fehler"])
        self.assertEqual(self.dateien, {})
        contracts.validiere("pruefung_lauf", detail)

    def test_stufe1_und_stufe2_ueber_alle_sitzungen(self) -> None:
        belege = {1: _beleg_mit_befund(signatur="sig"), 2: _beleg_mit_befund(signatur="sig")}
        claude = lambda t: '{"einordnung": "sauber", "begruendung": "passt"}'
        codex = lambda t: ('[{"sitzung_logisch": 1, "einordnung": "sauber"}, '
                            '{"sitzung_logisch": 2, "einordnung": "abgewichen"}]')
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: belege[sid], frager_claude=claude, frager_codex=codex,
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [1, 2],
            datei_schreiben=self._datei_schreiben,
        )
        self.assertIsNone(detail["fehler"])
        self.assertEqual(detail["stufe_max"], 2)
        self.assertEqual(detail["sitzungen"], [1, 2])
        self.assertEqual(detail["tabelle"], [
            {"sitzung_logisch": 1, "einordnung": "sauber"},
            {"sitzung_logisch": 2, "einordnung": "abgewichen"},
        ])
        self.assertTrue(detail["datei"].startswith("_work/"))
        self.assertIn(detail["datei"], self.dateien)
        self.assertIn("sig", self.dateien[detail["datei"]])
        contracts.validiere("pruefung_lauf", detail)
        self.assertEqual(self.geschrieben[0][:2], ("pruefung", "lauf"))

    def test_codex_fallback_auf_stufe1_wenn_unparsebar(self) -> None:
        belege = {1: _beleg_mit_befund(signatur="sig")}
        claude = lambda t: '{"einordnung": "halluziniert", "begruendung": "x"}'
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: belege[sid], frager_claude=claude, frager_codex=lambda t: "kein json",
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [1],
            datei_schreiben=self._datei_schreiben,
        )
        self.assertEqual(detail["tabelle"], [{"sitzung_logisch": 1, "einordnung": "halluziniert"}])

    def test_unbekannte_einordnung_wird_zu_abgewichen(self) -> None:
        belege = {1: _beleg_mit_befund(signatur="sig")}
        claude = lambda t: '{"einordnung": "voellig_unbekannt", "begruendung": "x"}'
        codex = lambda t: '[{"sitzung_logisch": 1, "einordnung": "voellig_unbekannt"}]'
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, lambda sid: belege[sid], frager_claude=claude, frager_codex=codex,
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [1],
            datei_schreiben=self._datei_schreiben,
        )
        self.assertEqual(detail["tabelle"][0]["einordnung"], "abgewichen")

    def test_kaputte_sitzung_wird_uebersprungen_nicht_abgebrochen(self) -> None:
        def beleg_laden(sid):
            if sid == 1:
                raise ValueError("kaputt")
            return _beleg_mit_befund(signatur="sig")

        claude = lambda t: '{"einordnung": "sauber", "begruendung": "x"}'
        codex = lambda t: '[{"sitzung_logisch": 2, "einordnung": "sauber"}]'
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        detail = pruefung.lauf_ausfuehren(
            body, beleg_laden, frager_claude=claude, frager_codex=codex,
            ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [1, 2],
            datei_schreiben=self._datei_schreiben,
        )
        self.assertEqual(detail["sitzungen"], [2])

    def test_lauf_konflikt_bei_ueberschneidender_signatur(self) -> None:
        body = contracts.PruefungBody(scope="fehlerbild", signaturen=["sig"])
        pruefung.registrieren("p-vorher", "fehlerbild", pruefung.schluessel_fuer("fehlerbild", None, ["sig"]))
        with self.assertRaises(pruefung.LaufKonflikt):
            pruefung.lauf_ausfuehren(
                body, lambda sid: _beleg_mit_befund(), frager_claude=lambda t: "[]", frager_codex=lambda t: "[]",
                ereignis_schreiben=self._schreiben, sitzungen_finder=lambda sig: [1],
                datei_schreiben=self._datei_schreiben,
            )


class SitzungenFuerSignaturTest(unittest.TestCase):
    def test_liefert_sortierte_liste(self) -> None:
        self.assertEqual(pruefung.sitzungen_fuer_signatur("sig", laufer=lambda sql: "[3, 1, 2]"), [1, 2, 3])

    def test_leer_bei_leerer_ausgabe(self) -> None:
        self.assertEqual(pruefung.sitzungen_fuer_signatur("sig", laufer=lambda sql: ""), [])

    def test_sql_enthaelt_signatur_und_view(self) -> None:
        sql = fehlerbild_pruefung._sql_sitzungen_fuer_signatur("rework:tool:Bash", 30)
        self.assertIn("rework:tool:Bash", sql)
        self.assertIn("sitzung_auffaelligkeit", sql)
        self.assertIn("sitzung_aktuell", sql)


class DateiSchreibenRealTest(unittest.TestCase):
    def test_schreibt_relativ_zur_basis_und_legt_ordner_an(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            basis = Path(tmp)
            ergebnis = pruefung.datei_schreiben_real("_work/test-datei.md", "Inhalt", basis=basis)
            self.assertEqual(ergebnis, "_work/test-datei.md")
            self.assertEqual((basis / "_work" / "test-datei.md").read_text(encoding="utf-8"), "Inhalt")


# ---------------------------------------------------------------------------------------------
# API: POST/GET /api/pruefung
# ---------------------------------------------------------------------------------------------

class PruefungApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_claude = web.FRAGER_CLAUDE
        self.alt_codex = web.FRAGER_CODEX
        self.alt_ereignis_schreiben = speicher.ereignis_schreiben
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        web.FRAGER_CLAUDE = self.alt_claude
        web.FRAGER_CODEX = self.alt_codex
        speicher.ereignis_schreiben = self.alt_ereignis_schreiben
        pruefung._laufend.clear()

    def test_post_400_bei_ungueltigem_body(self) -> None:
        antwort = self.client.post("/api/pruefung", json={"scope": "unbekannt"})
        self.assertEqual(antwort.status_code, 400)

    def test_post_404_bei_unbekannter_sitzung(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")  # leer = "keine Zeile" fuer `_wert` (nicht "[]")
        antwort = self.client.post("/api/pruefung", json={
            "scope": "befund", "sitzung_logisch": 999, "signaturen": ["sig"], "stufe": None, "lauf_ref": None,
        })
        self.assertEqual(antwort.status_code, 404)

    def test_post_202_schreibt_ereignis_und_liefert_lauf_id(self) -> None:
        beleg = _beleg_mit_befund(schwere="hinweis")
        web.LAUFER = FakeLaufer({
            "sitzung_aktuell WHERE logisch_ref": "10",
            "FROM sitzung WHERE id = 10": json.dumps(beleg.als_dict()),
        })
        web.FRAGER_CLAUDE = lambda t: '[{"signatur": "sig", "kategorie": "x", "komplexitaet": "einfach", ' \
                                       '"empfehlung": "y", "urteil": "ja"}]'
        web.FRAGER_CODEX = lambda t: "[]"
        geschrieben = []
        speicher.ereignis_schreiben = lambda quelle, typ, detail, host="pc", laufer=None: geschrieben.append(
            (quelle, typ, detail)
        )
        antwort = self.client.post("/api/pruefung", json={
            "scope": "befund", "sitzung_logisch": 10, "signaturen": ["sig"], "stufe": None, "lauf_ref": None,
        })
        self.assertEqual(antwort.status_code, 202)
        daten = antwort.json()
        self.assertTrue(daten["lauf_id"].startswith("p-"))
        self.assertEqual(daten["scope"], "befund")
        self.assertIsNone(daten["stufe_max"])  # asynchron: steht erst nach Stufe 1 fest
        web._pruefung_faeden[daten["lauf_id"]].join(timeout=5)
        self.assertEqual(geschrieben[0][0], "pruefung")
        self.assertEqual(geschrieben[0][2]["stufe_max"], 1)
        self.assertIsNone(pruefung.ist_registriert(daten["lauf_id"]))

    def test_post_409_bei_ueberschneidendem_lauf(self) -> None:
        beleg = _beleg_mit_befund()
        web.LAUFER = FakeLaufer({
            "sitzung_aktuell WHERE logisch_ref": "10",
            "FROM sitzung WHERE id = 10": json.dumps(beleg.als_dict()),
        })
        pruefung.registrieren("p-vorher", "befund", pruefung.schluessel_fuer("befund", 10, ["sig"]))
        antwort = self.client.post("/api/pruefung", json={
            "scope": "befund", "sitzung_logisch": 10, "signaturen": ["sig"], "stufe": None, "lauf_ref": None,
        })
        self.assertEqual(antwort.status_code, 409)
        self.assertEqual(antwort.json()["lauf_id"], "p-vorher")

    def test_get_404_bei_unbekannter_lauf_id(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/pruefung/p-unbekannt")
        self.assertEqual(antwort.status_code, 404)

    def test_get_laeuft_true_waehrend_registriert(self) -> None:
        pruefung.registrieren("p-laeuft", "befund", pruefung.schluessel_fuer("befund", 1, ["sig"]))
        antwort = self.client.get("/api/pruefung/p-laeuft")
        daten = antwort.json()
        self.assertTrue(daten["laeuft"])
        self.assertIsNone(daten["ergebnis"])

    def test_get_liefert_persistiertes_ergebnis_nach_lauf_ende(self) -> None:
        ergebnis = {**contracts.BEISPIELE["pruefung_lauf"], "lauf_id": "p-fertig"}
        web.LAUFER = FakeLaufer({"detail->>'lauf_id' = 'p-fertig'": json.dumps(ergebnis)}, default="")
        antwort = self.client.get("/api/pruefung/p-fertig")
        daten = antwort.json()
        self.assertFalse(daten["laeuft"])
        self.assertEqual(daten["ergebnis"]["lauf_id"], "p-fertig")


if __name__ == "__main__":
    unittest.main()
