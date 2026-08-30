"""Stufe 3: FastAPI-Dashboard mit Fake-Laufer (kein echter psql/Docker/Subprozess)."""
from __future__ import annotations

import json
import threading
import time
import sys
import unittest
from datetime import date, datetime

from fastapi.testclient import TestClient

from .. import chat, projekte as projekte_modul
from .. import speicher, web
from ..modell import ART_NUTZER, ART_TOOL, ART_TOOL_ERGEBNIS, Auffaelligkeit, Ereignis, Kopf, Subagent
from .hilfen import baue_beleg


class FakeLaufer:
    """Antwortet nach dem ersten passenden Substring in der SQL -- Reihenfolge egal."""

    def __init__(self, antworten: dict[str, str], default: str = "[]"):
        self.antworten = antworten
        self.default = default
        self.aufrufe: list[str] = []

    def __call__(self, sql: str, zeitlimit_s: int = 8) -> str:
        self.aufrufe.append(sql)
        for muster, antwort in self.antworten.items():
            if muster in sql:
                return antwort
        return self.default


class SitzungenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def test_sitzungsliste_filtert_nach_zeitraum_projekt_quelle(self) -> None:
        """`quelle=` filtert nach der ABGELEITETEN Anzeige-Quelle (Claude/Codex/Ollama/Produkt/
        Unbekannt, Entscheid 2026-08-26, Auftrag 2) -- das haengt vom Modell ab und passiert
        darum nach der SQL-Abfrage in Python, nicht mehr als `AND quelle = ...`-Bedingung."""
        zeile = {
            "id": 1, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "Host-Workspace",
            "quelle": "claude", "modelle": [], "dauer_ms": 15120000, "runden": 56, "tools": 270,
            "fehler": 15, "kosten": 12.4, "anzahl_befunde": 4, "dissens": True,
        }
        fake = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([zeile])})
        web.LAUFER = fake

        antwort = self.client.get(
            "/api/sitzungen",
            params={"von": "2026-08-20", "bis": "2026-08-26", "projekt": "Host-Workspace", "quelle": "Claude"},
        )
        self.assertEqual(antwort.status_code, 200)
        erwartet = {k: v for k, v in zeile.items() if k != "modelle"}
        self.assertEqual(
            antwort.json(),
            [{**erwartet, "kontext": "unzugeordnet", "quelle": "Claude", "umgebung": "entwicklung", "persona": "vico", "kanal": "terminal"}],
        )
        sql = fake.aufrufe[0]
        self.assertIn("2026-08-20", sql)
        self.assertIn("2026-08-26", sql)
        self.assertIn("AND projekt = 'Host-Workspace'", sql)
        self.assertNotIn("AND quelle", sql)

    def test_sitzungsliste_filter_nach_quelle_schliesst_andere_ab(self) -> None:
        """glm-5.2 -> Ollama: eine `claude`-Sitzung mit diesem Modell zaehlt NICHT zu `quelle=Claude`."""
        zeilen = [
            {"id": 1, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "Host-Workspace",
             "quelle": "claude", "modelle": ["claude-sonnet-5"], "dauer_ms": 1000, "runden": 1,
             "tools": 1, "fehler": 0, "kosten": 0.1, "anzahl_befunde": 0, "dissens": False},
            {"id": 2, "zeitstempel": "2026-08-25T20:10:00+00:00", "projekt": "Host-Workspace",
             "quelle": "claude", "modelle": ["glm-5.2:cloud"], "dauer_ms": 1000, "runden": 1,
             "tools": 1, "fehler": 0, "kosten": None, "anzahl_befunde": 0, "dissens": False},
        ]
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps(zeilen)})
        antwort = self.client.get(
            "/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26", "quelle": "Ollama"}
        )
        daten = antwort.json()
        self.assertEqual([z["id"] for z in daten], [2])
        self.assertEqual(daten[0]["quelle"], "Ollama")

    def test_sitzungsliste_ohne_filter_laesst_projekt_quelle_weg(self) -> None:
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.status_code, 200)
        self.assertNotIn("AND projekt", fake.aufrufe[0])
        self.assertNotIn("AND quelle", fake.aufrufe[0])

    def test_sitzungsliste_verlinkt_die_logische_id(self) -> None:
        """C1 Auftrag 4: `/api/sitzungen` liefert `sitzung_logisch` unter dem Feld `id`, nicht
        mehr die Version -- `start.js` verlinkt dieses Feld unveraendert weiter."""
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertIn("s.logisch_ref AS id", fake.aufrufe[0])

    def _projekt_quelle_zeile(self, id_, projekt, quelle, modelle=None):
        return {"id": id_, "projekt": projekt, "quelle": quelle, "modelle": modelle or []}

    def test_projekte_aggregiert_ueber_quellen(self) -> None:
        alt = projekte_modul.lade_aliase
        projekte_modul.lade_aliase = lambda *a, **k: {
            "Host-Workspace": {"projekt": "Host-Workspace", "kontext": "arbeit"},
        }
        try:
            zeilen = (
                [self._projekt_quelle_zeile(i, "Host-Workspace", "claude") for i in range(9)]
                + [self._projekt_quelle_zeile(i, "Host-Workspace", "codex") for i in range(9, 11)]
                + [self._projekt_quelle_zeile(i, "Beispielprojekt", "claude") for i in range(11, 15)]
            )
            web.LAUFER = FakeLaufer(
                {"FROM (SELECT id, projekt, quelle, coalesce(dokument": json.dumps(zeilen)}
            )
            antwort = self.client.get("/api/projekte", params={"von": "2026-08-01", "bis": "2026-08-26"})
            daten = antwort.json()
            self.assertEqual(daten["projekte"][0], {"name": "Host-Workspace", "anzahl": 11, "ausgeblendet": False})
            self.assertIn({"name": "Claude", "anzahl": 13}, daten["quellen"])
            self.assertIn({"name": "Codex", "anzahl": 2}, daten["quellen"])
            self.assertIn({"name": "arbeit", "anzahl": 11}, daten["kontexte"])
            self.assertIn({"name": "unzugeordnet", "anzahl": 4}, daten["kontexte"])
            self.assertEqual(daten["unzugeordnet"], 4)
        finally:
            projekte_modul.lade_aliase = alt

    def test_projekte_zaehlt_unbekanntes_modell_als_unzugeordnet(self) -> None:
        """Entscheid 2026-08-26, Auftrag 2: „Unzugeordnet" zaehlt auch Sitzungen mit
        unbekanntem Modell, selbst wenn das Projekt selbst zugeordnet ist."""
        alt = projekte_modul.lade_aliase
        projekte_modul.lade_aliase = lambda *a, **k: {
            "Host-Workspace": {"projekt": "Host-Workspace", "kontext": "arbeit"},
        }
        try:
            zeilen = [
                self._projekt_quelle_zeile(1, "Host-Workspace", "claude", ["claude-sonnet-5"]),
                self._projekt_quelle_zeile(2, "Host-Workspace", "claude", ["ein-unbekanntes-modell"]),
            ]
            web.LAUFER = FakeLaufer(
                {"FROM (SELECT id, projekt, quelle, coalesce(dokument": json.dumps(zeilen)}
            )
            antwort = self.client.get("/api/projekte", params={"von": "2026-08-01", "bis": "2026-08-26"})
            daten = antwort.json()
            self.assertIn({"name": "Unbekannt", "anzahl": 1}, daten["quellen"])
            self.assertEqual(daten["unzugeordnet"], 1)
        finally:
            projekte_modul.lade_aliase = alt

    def test_sitzungsliste_mit_signatur_liefert_treffer_je_zeile(self) -> None:
        zeile = {
            "id": 1, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "Host-Workspace",
            "quelle": "claude", "modelle": [], "dauer_ms": 1000, "runden": 1, "tools": 5,
            "fehler": 2, "kosten": 0.5, "anzahl_befunde": 1, "dissens": False, "treffer": 2,
        }
        fake = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([zeile])})
        web.LAUFER = fake
        antwort = self.client.get(
            "/api/sitzungen",
            params={"von": "2026-08-20", "bis": "2026-08-26", "signatur": "cc7a14386c7a"},
        )
        self.assertEqual(antwort.status_code, 200)
        erwartet = {k: v for k, v in zeile.items() if k != "modelle"}
        self.assertEqual(
            antwort.json(),
            [{**erwartet, "kontext": "unzugeordnet", "quelle": "Claude", "umgebung": "entwicklung", "persona": "vico", "kanal": "terminal"}],
        )
        sql = fake.aufrufe[0]
        self.assertIn("e->>'signatur' = 'cc7a14386c7a'", sql)
        self.assertIn("AS treffer", sql)

    def test_sitzungsliste_ohne_signatur_hat_keine_treffer_spalte(self) -> None:
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertNotIn("AS treffer", fake.aufrufe[0])


class ProjektAliasTest(unittest.TestCase):
    """Auftrag A (Sichtabnahme Block 1): Sitzungen aus Unterordnern/Codex-Clones
    erscheinen unter dem kanonischen Projektnamen -- Zählungen zusammengeführt,
    Filter akzeptiert den Alias und schließt alle darauf zeigenden Rohnamen ein."""

    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_lade_aliase = projekte_modul.lade_aliase
        projekte_modul.lade_aliase = lambda *a, **k: {
            "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "scratchpad": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "codex-workspace": {"projekt": "00_Workspace", "kontext": "review"},
        }
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        projekte_modul.lade_aliase = self.alt_lade_aliase

    def test_projekte_fuehrt_rohnamen_unter_dem_alias_zusammen(self) -> None:
        zeilen = (
            [{"id": i, "projekt": "scripts", "quelle": "claude", "modelle": []} for i in range(9)]
            + [{"id": i, "projekt": "scratchpad", "quelle": "claude", "modelle": []} for i in range(9, 11)]
            + [{"id": i, "projekt": "Beispielprojekt", "quelle": "claude", "modelle": []} for i in range(11, 15)]
        )
        web.LAUFER = FakeLaufer(
            {"FROM (SELECT id, projekt, quelle, coalesce(dokument": json.dumps(zeilen)}
        )
        antwort = self.client.get("/api/projekte", params={"von": "2026-08-01", "bis": "2026-08-26"})
        namen = [p["name"] for p in antwort.json()["projekte"]]
        self.assertIn({"name": "00_Workspace", "anzahl": 11, "ausgeblendet": False}, antwort.json()["projekte"])
        self.assertNotIn("scripts", namen)
        self.assertNotIn("scratchpad", namen)

    def test_sitzungsliste_zeigt_alias_statt_rohname(self) -> None:
        zeile = {
            "id": 1, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "scripts",
            "quelle": "claude", "dauer_ms": 1000, "runden": 1, "tools": 1,
            "fehler": 0, "kosten": 0.1, "anzahl_befunde": 0, "dissens": False,
        }
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([zeile])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.json()[0]["projekt"], "00_Workspace")

    def test_filter_mit_alias_schliesst_alle_rohnamen_ein(self) -> None:
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        self.client.get(
            "/api/sitzungen",
            params={"von": "2026-08-20", "bis": "2026-08-26", "projekt": "00_Workspace"},
        )
        sql = fake.aufrufe[0]
        self.assertIn(
            "(projekt = '00_Workspace' OR projekt = 'codex-workspace' OR projekt = 'scratchpad' OR projekt = 'scripts')",
            sql,
        )

    def test_filter_ohne_alias_bleibt_einfache_gleichheit(self) -> None:
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        self.client.get(
            "/api/sitzungen",
            params={"von": "2026-08-20", "bis": "2026-08-26", "projekt": "Beispielprojekt"},
        )
        self.assertIn("AND projekt = 'Beispielprojekt'", fake.aufrufe[0])

    def test_filter_mit_quellenabhaengigem_alias_baut_or_bedingung(self) -> None:
        """`Beispielprojekt@codex` (quellenscharf) + `Beispielprojekt` (plain) zeigen beide auf Beispielprojekt --
        die SQL-Bedingung muss die codex-Zeile auf `quelle = 'codex'` einschränken."""
        projekte_modul.lade_aliase = lambda *a, **k: {
            "codex-beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt@codex": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "arbeit"},
        }
        fake = FakeLaufer({"FROM sitzung_aktuell s": "[]"})
        web.LAUFER = fake
        self.client.get(
            "/api/sitzungen",
            params={"von": "2026-08-20", "bis": "2026-08-26", "projekt": "Beispielprojekt"},
        )
        sql = fake.aufrufe[0]
        self.assertIn("(projekt = 'Beispielprojekt' AND quelle = 'codex')", sql)
        self.assertIn("projekt = 'Beispielprojekt'", sql)
        self.assertIn("projekt = 'codex-beispielprojekt'", sql)


class UmgebungFilterTest(unittest.TestCase):
    """C12 (Auftrag 2026-08-28 12:45): `/api/sitzungen` liefert `umgebung` je Zeile (Dual-
    Reader: Zeile ohne das Feld zaehlt als `entwicklung`) und filtert per `umgebung=` wie `kontext=`."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def _zeile(self, id_, umgebung=None):
        z = {
            "id": id_, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "Host-Workspace",
            "quelle": "claude", "dauer_ms": 1000, "runden": 1, "tools": 1,
            "fehler": 0, "kosten": 0.1, "anzahl_befunde": 0, "dissens": False,
        }
        if umgebung is not None:
            z["umgebung"] = umgebung
        return z

    def test_zeile_ohne_feld_zeigt_entwicklung(self) -> None:
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([self._zeile(1)])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.json()[0]["umgebung"], "entwicklung")

    def test_umgebung_filter_laesst_nur_passende_zeilen(self) -> None:
        zeilen = [self._zeile(1, "entwicklung"), self._zeile(2, "abnahme")]
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps(zeilen)})
        antwort = self.client.get(
            "/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26", "umgebung": "abnahme"}
        )
        daten = antwort.json()
        self.assertEqual([z["id"] for z in daten], [2])
        self.assertEqual(daten[0]["umgebung"], "abnahme")

    def test_unbekannter_gespeicherter_wert_faellt_auf_entwicklung_zurueck(self) -> None:
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([self._zeile(1, "staging")])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.json()[0]["umgebung"], "entwicklung")


class PersonaKanalTest(unittest.TestCase):
    """C14 (Maintainer 2026-08-28): `/api/sitzungen` liefert `persona` und `kanal` je Zeile (Dual-Reader:
    Zeile ohne die Felder zaehlt als `vico`/`terminal` -- nur VICO schrieb vor C14)."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def _zeile(self, id_, persona=None, kanal=None):
        z = {
            "id": id_, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": "Host-Workspace",
            "quelle": "claude", "dauer_ms": 1000, "runden": 1, "tools": 1,
            "fehler": 0, "kosten": 0.1, "anzahl_befunde": 0, "dissens": False,
        }
        if persona is not None:
            z["persona"] = persona
        if kanal is not None:
            z["kanal"] = kanal
        return z

    def test_zeile_ohne_felder_zeigt_vico_terminal(self) -> None:
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([self._zeile(1)])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        daten = antwort.json()[0]
        self.assertEqual(daten["persona"], "vico")
        self.assertEqual(daten["kanal"], "terminal")

    def test_bekannte_werte_werden_durchgereicht(self) -> None:
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([self._zeile(1, "vica", "orb")])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        daten = antwort.json()[0]
        self.assertEqual(daten["persona"], "vica")
        self.assertEqual(daten["kanal"], "orb")

    def test_unbekannter_rohwert_faellt_auf_vico_zurueck(self) -> None:
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps([self._zeile(1, "andere-persona", "app")])})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        daten = antwort.json()[0]
        self.assertEqual(daten["persona"], "vico")
        self.assertEqual(daten["kanal"], "terminal")


class QuerschnittTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def test_querschnitt_liefert_genau_vier_kacheln_mit_fehler_zusammenfassung(self) -> None:
        """/api/querschnitt liefert die Fehler-Kachel als EINE Zusammenfassung (Stufe 3, Sichtabnahme
        2026-08-26 Befund 2): Anzahl qualifizierender Signaturen, die häufigste als Top, Sitzungs-IDs
        als Vereinigung -- nie mehr eine Kachel je Signatur (das trieb die Zahl auf 11 Kacheln hoch)."""
        fehler = [
            {"signatur": "cc7a14386c7a", "anzahl_sitzungen": 5, "sitzung_ids": [1, 2, 3, 8, 9],
             "werkzeug": "Bash", "fehlerklasse": "tool_error", "treffer_gesamt": 174},
            {"signatur": "4b37b7b25429", "anzahl_sitzungen": 3, "sitzung_ids": [4, 5, 6],
             "werkzeug": "Read", "fehlerklasse": "tool_error", "treffer_gesamt": 9},
        ]
        web.LAUFER = FakeLaufer({
            "jsonb_array_elements(s.dokument->'ereignisse')": json.dumps(fehler),
            "a.regel = 'cost:outlier'": "[4, 5]",
            "a.regel LIKE 'capture:gap%'": "[6]",
            "quelle = 'vieraugen' AND coalesce": "[7]",
        })
        antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-19", "bis": "2026-08-26"})
        daten = antwort.json()
        self.assertEqual(daten["wiederkehrende_fehler"], {
            "anzahl": 2, "top_signatur": "cc7a14386c7a", "top_anzahl_sitzungen": 5,
            "top_werkzeug": "Bash", "top_fehlerklasse": "tool_error", "top_treffer_gesamt": 174,
            "sitzung_ids": [1, 2, 3, 4, 5, 6, 8, 9], "sitzung_ids_erledigt": [],
            "signaturen": [
                {"signatur": "cc7a14386c7a", "werkzeug": "Bash", "fehlerklasse": "tool_error",
                 "anzahl_sitzungen": 5, "treffer_gesamt": 174, "sitzung_ids": [1, 2, 3, 8, 9],
                 "status": "offen"},
                {"signatur": "4b37b7b25429", "werkzeug": "Read", "fehlerklasse": "tool_error",
                 "anzahl_sitzungen": 3, "treffer_gesamt": 9, "sitzung_ids": [4, 5, 6],
                 "status": "offen"},
            ],
        })
        self.assertEqual(daten["kosten_ausreisser"], {"anzahl": 2, "sitzung_ids": [4, 5], "sitzung_ids_erledigt": []})
        self.assertEqual(daten["erfassungsluecken"], {"anzahl": 1, "sitzung_ids": [6], "sitzung_ids_erledigt": []})
        self.assertEqual(daten["dissens"], {"anzahl": 1, "sitzung_ids": [7]})
        sql = [s for s in web.LAUFER.aufrufe if "jsonb_array_elements(s.dokument->'ereignisse')" in s][0]
        self.assertIn("HAVING count(DISTINCT s.id) >= 3", sql)
        self.assertIn("AS werkzeug", sql)
        self.assertIn("AS fehlerklasse", sql)
        self.assertIn("count(*) AS treffer_gesamt", sql)

    def test_querschnitt_liefert_umgebungen_verteilung(self) -> None:
        """C12: `umgebungen` zaehlt normalisierte Werte -- eine Zeile ohne das Feld (Alt-Beleg)
        zaehlt als `entwicklung` (Dual-Reader)."""
        web.LAUFER = FakeLaufer({
            "dokument->'kopf'->>'umgebung' AS umgebung": json.dumps(
                [{"umgebung": "entwicklung"}, {"umgebung": "entwicklung"}, {"umgebung": None}, {"umgebung": "abnahme"}]
            ),
        })
        antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-19", "bis": "2026-08-26"})
        self.assertEqual(
            antwort.json()["umgebungen"],
            [{"name": "abnahme", "anzahl": 1}, {"name": "entwicklung", "anzahl": 3}],
        )

    def test_wiederkehrende_fehler_sql_rechnet_direkt_ueber_sitzungsdokumente(self) -> None:
        """Befund 1 (Review 2026-08-26, HOCH): die flache Tabelle traegt `error:recurring` nur fuer
        die jeweils NEU ingestierte Sitzung ein (append-only, sobald die Schwelle schon erreicht
        ist) -- die Dashboard-Schwelle >= 3 griff darum effektiv erst ab 5 Sitzungen. Fix: direkt
        ueber `sitzung`/`sitzung_aktuell` rechnen, nicht ueber `sitzung_auffaelligkeit`."""
        sql = web._sql_wiederkehrende_fehler(date(2026, 8, 19), date(2026, 8, 26))
        self.assertIn("FROM sitzung_aktuell s", sql)
        self.assertNotIn("sitzung_auffaelligkeit", sql)
        self.assertIn("HAVING count(DISTINCT s.id) >= 3", sql)

    def test_zeitfilter_ids_je_regel_und_dissens_nutzt_sitzungszeit_nicht_ingestzeit(self) -> None:
        """Befund 2 (Review 2026-08-26, MITTEL): `sitzung_auffaelligkeit.zeitstempel` ist der
        Ingest-Zeitpunkt (now()), nicht die Sitzungszeit -- ein Nachzuegler-Ingest einer alten
        Sitzung landete darum im falschen Zeitfenster. Fix: auf die Sitzungszeit ueber einen Join
        mit `sitzung` filtern."""
        sql_regel = web._sql_ids_je_regel(date(2026, 8, 19), date(2026, 8, 26), "cost:outlier")
        self.assertIn("JOIN sitzung s ON s.id = a.sitzung_ref", sql_regel)
        self.assertIn("coalesce(s.ende, s.start, s.zeitstempel)", sql_regel)

        sql_dissens = web._sql_dissens(date(2026, 8, 19), date(2026, 8, 26))
        self.assertIn("JOIN sitzung s ON s.id = (e.detail->>'sitzung_ref')::bigint", sql_dissens)
        self.assertIn("coalesce(s.ende, s.start, s.zeitstempel)", sql_dissens)

    def test_dissens_ids_im_zeitraum_werden_durchgereicht(self) -> None:
        """Sichtabnahme Block 1, Auftrag B.3: Sitzung 90 (Ende 25.08.) muss im 7-Tage-Fenster
        (von 20.08. bis 26.08.) im Dissens-Drilldown erscheinen -- die Kachel liest die IDs
        direkt aus `_sql_dissens` durch, keine eigene Filterung mehr in `api_querschnitt`."""
        web.LAUFER = FakeLaufer({
            "jsonb_array_elements(s.dokument->'ereignisse')": "[]",
            "a.regel = 'cost:outlier'": "[]",
            "a.regel LIKE 'capture:gap%'": "[]",
            "quelle = 'vieraugen' AND coalesce": "[90]",
        })
        antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(antwort.json()["dissens"], {"anzahl": 1, "sitzung_ids": [90]})

    def test_querschnitt_ohne_wiederkehrende_fehler_liefert_leere_zusammenfassung(self) -> None:
        web.LAUFER = FakeLaufer({}, default="[]")
        antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-19", "bis": "2026-08-26"})
        self.assertEqual(antwort.json()["wiederkehrende_fehler"], {
            "anzahl": 0, "top_signatur": "", "top_anzahl_sitzungen": 0,
            "top_werkzeug": "", "top_fehlerklasse": "", "top_treffer_gesamt": 0,
            "sitzung_ids": [], "sitzung_ids_erledigt": [], "signaturen": [],
        })

    def test_wiederkehrende_fehler_und_ids_je_regel_schliessen_entschiedene_befunde_aus(self) -> None:
        """Erledigt-Feature (Entscheid 2026-08-26, Auftrag 3): ein erledigter/obsoleter Fund
        zaehlt nicht mehr in die Querschnitt-Kacheln."""
        sql_fehler = web._sql_wiederkehrende_fehler(date(2026, 8, 19), date(2026, 8, 26))
        self.assertIn("NOT EXISTS", sql_fehler)
        self.assertIn("befund_entscheid", sql_fehler)
        self.assertIn("'error:recurring:' || (e->>'signatur')", sql_fehler)

        sql_regel = web._sql_ids_je_regel(date(2026, 8, 19), date(2026, 8, 26), "cost:outlier")
        self.assertIn("NOT EXISTS", sql_regel)
        self.assertIn("be.detail->>'signatur' = a.signatur", sql_regel)

    def test_nicht_entschieden_behandelt_offen_als_wiedereroeffnung(self) -> None:
        """Dritter Status `offen` (Entscheid B, 2026-08-26): das NOT-EXISTS-Fragment
        schliesst einen Entscheid nur aus, wenn er der JÜNGSTE ist UND status <> 'offen' --
        ein späterer `offen`-Entscheid macht den Befund wieder offen, auch nach einem
        früheren erledigt/obsolet."""
        sql = web._sql_nicht_entschieden("a.signatur", "a.sitzung_ref")
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("be.detail->>'status' <> 'offen'", sql)
        self.assertIn("max(be2.detail->>'entschieden_am')", sql)
        self.assertEqual(sql.count("("), sql.count(")"))

    def test_kacheln_liefern_sitzung_ids_erledigt_aus_der_differenz(self) -> None:
        """Erledigt-Feature (Entscheid 2026-08-26): `nur_offene=False`-Abfrage liefert mehr
        IDs als die gefilterte -- die Differenz landet in `sitzung_ids_erledigt` (Schalter
        „Erledigte einblenden")."""
        fehler_offen = [{"signatur": "abc", "anzahl_sitzungen": 3, "sitzung_ids": [1, 2, 3]}]
        fehler_alle = [{"signatur": "abc", "anzahl_sitzungen": 4, "sitzung_ids": [1, 2, 3, 4]}]

        # `nur_offene=True/False` muessen unterschiedliches SQL bauen (kein/vorhandenes
        # NOT EXISTS) -- direkt gegen die Baufunktionen, nicht ueber den HTTP-Weg geraten.
        sql_offen = web._sql_wiederkehrende_fehler(date(2026, 8, 19), date(2026, 8, 26))
        sql_alle = web._sql_wiederkehrende_fehler(date(2026, 8, 19), date(2026, 8, 26), nur_offene=False)
        self.assertIn("NOT EXISTS", sql_offen)
        self.assertNotIn("NOT EXISTS", sql_alle)

        kachel = web._fehler_kachel(fehler_offen, fehler_alle)
        self.assertEqual(kachel["sitzung_ids"], [1, 2, 3])
        self.assertEqual(kachel["sitzung_ids_erledigt"], [4])
        # Signatur "abc" hat noch offene Sitzungen -- taucht in der Liste NUR als "offen" auf,
        # nicht zusaetzlich als "erledigt" (Zweistufiger Fehler-Drilldown, Umbau 2026-08-26).
        self.assertEqual(kachel["signaturen"], [
            {"signatur": "abc", "werkzeug": "", "fehlerklasse": "", "anzahl_sitzungen": 3,
             "treffer_gesamt": 0, "sitzung_ids": [1, 2, 3], "status": "offen"},
        ])

    def test_fehler_kachel_markiert_vollstaendig_entschiedene_signatur_als_erledigt(self) -> None:
        """Zweistufiger Fehler-Drilldown (Umbau 2026-08-26, Auftrag 3): eine Signatur, die
        komplett entschieden ist (keine offenen Sitzungen mehr, faellt darum aus `zeilen` --
        die >=3-Schwelle greift nur auf offene Sitzungen), taucht in der `signaturen`-Liste
        trotzdem auf, markiert `status: erledigt` -- fuer die Status-Spalte im Panel."""
        fehler_offen = [{"signatur": "cc7a14386c7a", "anzahl_sitzungen": 5, "sitzung_ids": [1, 2, 3, 8, 9],
                          "werkzeug": "Bash", "fehlerklasse": "tool_error", "treffer_gesamt": 174}]
        fehler_alle = fehler_offen + [
            {"signatur": "abgeschlossen", "anzahl_sitzungen": 3, "sitzung_ids": [10, 11, 12],
             "werkzeug": "Read", "fehlerklasse": "tool_error", "treffer_gesamt": 6},
        ]
        kachel = web._fehler_kachel(fehler_offen, fehler_alle)
        erledigt_zeilen = [s for s in kachel["signaturen"] if s["status"] == "erledigt"]
        self.assertEqual(erledigt_zeilen, [
            {"signatur": "abgeschlossen", "werkzeug": "Read", "fehlerklasse": "tool_error",
             "anzahl_sitzungen": 3, "treffer_gesamt": 6, "sitzung_ids": [10, 11, 12], "status": "erledigt"},
        ])

    def test_sql_signatur_sitzungszeiten_hat_kein_having_und_zeitfilter(self) -> None:
        sql = web._sql_signatur_sitzungszeiten(date(2026, 8, 19), date(2026, 8, 26))
        self.assertIn("GROUP BY 1, 2, 3", sql)
        self.assertNotIn("HAVING", sql)
        self.assertIn("AS treffer", sql)
        self.assertIn("2026-08-19", sql)

    def test_sql_signatur_sitzungszeiten_ohne_zeitraum_ist_unbeschraenkt(self) -> None:
        sql = web._sql_signatur_sitzungszeiten()
        self.assertNotIn("::date", sql)
        self.assertIn("WHERE e->>'art'", sql)

    def test_rueckfall_anwenden_markiert_erledigt_zeile_als_rueckfall(self) -> None:
        """Rückfall-Erkennung (Entscheid 2026-08-26): eine vollständig entschiedene Signatur
        mit einer Sitzung NACH `entschieden_am` zählt wieder wie offen -- Status `rueckfall`."""
        kachel = web._fehler_kachel([], [
            {"signatur": "abc", "anzahl_sitzungen": 3, "sitzung_ids": [1, 2, 3],
             "werkzeug": "Bash", "fehlerklasse": "tool_error", "treffer_gesamt": 9},
        ])
        entscheide = [{"signatur": "error:recurring:abc", "sitzung_ref": None, "status": "erledigt",
                       "entschieden_am": "2026-08-20T10:00:00+00:00"}]
        sitzungszeiten = {"abc": [{"sitzung_id": 3, "zeit": "2026-08-21T10:00:00+00:00", "treffer": 4}]}
        ergebnis = web._rueckfall_anwenden(kachel, sitzungszeiten, entscheide)
        zeile = ergebnis["signaturen"][0]
        self.assertEqual(zeile["status"], "rueckfall")
        self.assertEqual(zeile["rueckfall_treffer"], 4)
        self.assertEqual(zeile["rueckfall_sitzungen"], {"anzahl": 1, "sitzung_ids": [3]})
        self.assertEqual(ergebnis["anzahl"], 1)
        self.assertEqual(ergebnis["sitzung_ids"], [3])
        self.assertEqual(ergebnis["sitzung_ids_erledigt"], [1, 2])

    def test_rueckfall_anwenden_ohne_treffer_seit_entscheid_bleibt_erledigt(self) -> None:
        kachel = web._fehler_kachel([], [
            {"signatur": "abc", "anzahl_sitzungen": 3, "sitzung_ids": [1, 2, 3],
             "werkzeug": "Bash", "fehlerklasse": "tool_error", "treffer_gesamt": 9},
        ])
        entscheide = [{"signatur": "error:recurring:abc", "sitzung_ref": None, "status": "obsolet",
                       "entschieden_am": "2026-08-25T10:00:00+00:00"}]
        ergebnis = web._rueckfall_anwenden(kachel, {}, entscheide)
        zeile = ergebnis["signaturen"][0]
        self.assertEqual(zeile["status"], "obsolet")
        self.assertNotIn("rueckfall_treffer", zeile)
        self.assertEqual(ergebnis["anzahl"], 0)

    def test_rueckfall_anwenden_laesst_offene_zeilen_unangetastet(self) -> None:
        kachel = web._fehler_kachel(
            [{"signatur": "xyz", "anzahl_sitzungen": 3, "sitzung_ids": [1, 2, 3],
              "werkzeug": "Read", "fehlerklasse": "tool_error", "treffer_gesamt": 6}],
            [],
        )
        ergebnis = web._rueckfall_anwenden(kachel, {}, [])
        self.assertEqual(ergebnis["signaturen"][0]["status"], "offen")
        self.assertNotIn("rueckfall_treffer", ergebnis["signaturen"][0])

    def test_querschnitt_erkennt_rueckfall_end_to_end(self) -> None:
        """Rückfall-Erkennung über den vollen HTTP-Weg: Signatur "abc" ist global erledigt
        (2026-08-21), zwei ihrer vier Sitzungen liegen danach -- die zählen als Rückfall,
        die Kachelzahl steigt entsprechend von 0 auf 1."""
        fehler_alle = [
            {"signatur": "abc", "anzahl_sitzungen": 4, "sitzung_ids": [1, 2, 5, 6],
             "werkzeug": "Bash", "fehlerklasse": "tool_error", "treffer_gesamt": 20},
        ]
        entscheid = {
            "signatur": "error:recurring:abc", "sitzung_ref": None, "status": "erledigt",
            "entschieden_am": "2026-08-21T00:00:00+00:00",
        }
        sitzungszeiten = [
            {"signatur": "abc", "sitzung_id": 1, "zeit": "2026-08-19T10:00:00+00:00", "treffer": 5},
            {"signatur": "abc", "sitzung_id": 2, "zeit": "2026-08-20T10:00:00+00:00", "treffer": 5},
            {"signatur": "abc", "sitzung_id": 5, "zeit": "2026-08-22T10:00:00+00:00", "treffer": 6},
            {"signatur": "abc", "sitzung_id": 6, "zeit": "2026-08-23T10:00:00+00:00", "treffer": 4},
        ]
        web.LAUFER = FakeLaufer({
            # nur die NOT-EXISTS-Variante (nur_offene=True) traegt das befund_entscheid-Fragment.
            "be.quelle = 'gf' AND be.typ = 'befund_entscheid'": "[]",
            "HAVING count(DISTINCT s.id) >= 3": json.dumps(fehler_alle),
            "GROUP BY 1, 2, 3": json.dumps(sitzungszeiten),
            "typ = 'befund_entscheid'": json.dumps([entscheid]),
            "a.regel = 'cost:outlier'": "[]",
            "a.regel LIKE 'capture:gap%'": "[]",
            "quelle = 'vieraugen' AND coalesce": "[]",
        })
        antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-19", "bis": "2026-08-26"})
        fehler = antwort.json()["wiederkehrende_fehler"]
        zeile = fehler["signaturen"][0]
        self.assertEqual(zeile["status"], "rueckfall")
        self.assertEqual(zeile["entschieden_am"], "2026-08-21T00:00:00+00:00")
        self.assertEqual(zeile["rueckfall_treffer"], 10)
        self.assertEqual(zeile["rueckfall_sitzungen"], {"anzahl": 2, "sitzung_ids": [5, 6]})
        self.assertEqual(fehler["anzahl"], 1)
        self.assertEqual(fehler["sitzung_ids"], [5, 6])
        self.assertEqual(fehler["sitzung_ids_erledigt"], [1, 2])

    def test_querschnitt_liefert_unzugeordnet_kachel_nur_wenn_ungeloest(self) -> None:
        alt = projekte_modul.lade_aliase
        projekte_modul.lade_aliase = lambda *a, **k: {}
        try:
            web.LAUFER = FakeLaufer({
                "FROM (SELECT id, projekt, quelle, coalesce(dokument": json.dumps(
                    [{"id": 5, "projekt": "irgendwas", "quelle": "claude", "modelle": []}]
                ),
            }, default="[]")
            antwort = self.client.get("/api/querschnitt", params={"von": "2026-08-19", "bis": "2026-08-26"})
            self.assertEqual(antwort.json()["unzugeordnet"], {"anzahl": 1, "sitzung_ids": [5]})
        finally:
            projekte_modul.lade_aliase = alt


class KontextFilterTest(unittest.TestCase):
    """Namenskonvention Projekt+Kontext (Entscheid 2026-08-26, Auftrag 1): `kontext=`
    filtert `/api/sitzungen` nach dem aufgelösten Kontext, mehrfach angebbar."""

    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_lade_aliase = projekte_modul.lade_aliase
        projekte_modul.lade_aliase = lambda *a, **k: {
            "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "codex-workspace": {"projekt": "00_Workspace", "kontext": "review"},
        }
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        projekte_modul.lade_aliase = self.alt_lade_aliase

    def _zeile(self, id_, projekt, quelle):
        return {
            "id": id_, "zeitstempel": "2026-08-25T21:10:00+00:00", "projekt": projekt,
            "quelle": quelle, "dauer_ms": 1000, "runden": 1, "tools": 1,
            "fehler": 0, "kosten": 0.1, "anzahl_befunde": 0, "dissens": False,
        }

    def test_ohne_kontext_param_bleiben_alle_zeilen(self) -> None:
        zeilen = [self._zeile(1, "scripts", "claude"), self._zeile(2, "codex-workspace", "codex")]
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps(zeilen)})
        antwort = self.client.get("/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26"})
        self.assertEqual(len(antwort.json()), 2)

    def test_kontext_filtert_und_jede_zeile_traegt_ihren_kontext(self) -> None:
        zeilen = [self._zeile(1, "scripts", "claude"), self._zeile(2, "codex-workspace", "codex")]
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps(zeilen)})
        antwort = self.client.get(
            "/api/sitzungen", params={"von": "2026-08-20", "bis": "2026-08-26", "kontext": "arbeit"}
        )
        daten = antwort.json()
        self.assertEqual(len(daten), 1)
        self.assertEqual(daten[0]["kontext"], "arbeit")

    def test_kontext_mehrfach_wirkt_als_oder(self) -> None:
        zeilen = [self._zeile(1, "scripts", "claude"), self._zeile(2, "codex-workspace", "codex")]
        web.LAUFER = FakeLaufer({"FROM sitzung_aktuell s": json.dumps(zeilen)})
        antwort = self.client.get(
            "/api/sitzungen",
            params=[("von", "2026-08-20"), ("bis", "2026-08-26"), ("kontext", "arbeit"), ("kontext", "review")],
        )
        self.assertEqual(len(antwort.json()), 2)


class BefundEntscheidTest(unittest.TestCase):
    """Erledigt-Feature je Befund (Entscheid 2026-08-26, Auftrag 3)."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def test_entscheid_schreiben_ruft_ereignis_schreiben_mit_geprueftem_detail(self) -> None:
        geschrieben = {}

        def fake_ereignis_schreiben(quelle, typ, detail, host="pc", laufer=None):
            geschrieben["quelle"] = quelle
            geschrieben["typ"] = typ
            geschrieben["detail"] = detail

        alt = speicher.ereignis_schreiben
        speicher.ereignis_schreiben = fake_ereignis_schreiben
        try:
            antwort = self.client.post("/api/befund/entscheid", json={
                "signatur": "error:recurring:abc", "status": "erledigt",
                "vermerk": "TROUBLESHOOTING Abschn. X", "begruendung": "behoben",
                "sitzung_ref": 42,
            })
        finally:
            speicher.ereignis_schreiben = alt
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(geschrieben["quelle"], "gf")
        self.assertEqual(geschrieben["typ"], "befund_entscheid")
        self.assertEqual(geschrieben["detail"]["signatur"], "error:recurring:abc")
        self.assertEqual(geschrieben["detail"]["status"], "erledigt")
        self.assertEqual(geschrieben["detail"]["sitzung_ref"], 42)
        self.assertEqual(geschrieben["detail"]["entschieden_von"], "Maintainer")

    def test_fremder_status_liefert_400(self) -> None:
        antwort = self.client.post("/api/befund/entscheid", json={"signatur": "x", "status": "geloescht"})
        self.assertEqual(antwort.status_code, 400)

    def test_zu_langer_vermerk_liefert_400(self) -> None:
        antwort = self.client.post(
            "/api/befund/entscheid", json={"signatur": "x", "status": "erledigt", "vermerk": "x" * 501}
        )
        self.assertEqual(antwort.status_code, 400)

    # ---- C11 Verankerung: echter (nicht gemockter) speicher.ereignis_schreiben-Pfad, damit
    # die Pydantic-Kontraktpruefung (contracts.BefundEntscheid) wirklich greift. ----

    def test_erledigt_ohne_verankerung_liefert_400_sprechende_meldung(self) -> None:
        web.LAUFER = FakeLaufer({})
        antwort = self.client.post("/api/befund/entscheid", json={"signatur": "x", "status": "erledigt"})
        self.assertEqual(antwort.status_code, 400)
        self.assertIn("verankerung", antwort.json()["detail"].lower())

    def test_erledigt_mit_verankerung_liefert_200_und_gibt_sie_zurueck(self) -> None:
        web.LAUFER = FakeLaufer({})
        antwort = self.client.post("/api/befund/entscheid", json={
            "signatur": "x", "status": "erledigt",
            "verankerung": {"art": "troubleshooting", "pfad": "TROUBLESHOOTING.md", "abschnitt": "X"},
        })
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json()["verankerung"], {
            "art": "troubleshooting", "pfad": "TROUBLESHOOTING.md", "abschnitt": "X",
        })

    def test_obsolet_ohne_verankerung_bleibt_200(self) -> None:
        web.LAUFER = FakeLaufer({})
        antwort = self.client.post("/api/befund/entscheid", json={"signatur": "x", "status": "obsolet"})
        self.assertEqual(antwort.status_code, 200)

    def test_verankerung_mit_geschuetztem_pfad_liefert_400(self) -> None:
        web.LAUFER = FakeLaufer({})
        antwort = self.client.post("/api/befund/entscheid", json={
            "signatur": "x", "status": "erledigt",
            "verankerung": {"art": "regel", "pfad": "60_Internal/_lokal/x.md"},
        })
        self.assertEqual(antwort.status_code, 400)

    def test_entscheide_liste_liest_aus_dem_ereignisstrom(self) -> None:
        eintrag = {"signatur": "x", "status": "erledigt", "sitzung_ref": None,
                   "vermerk": "v", "begruendung": "b", "entschieden_am": "2026-08-26T10:00:00+00:00",
                   "entschieden_von": "Maintainer"}
        web.LAUFER = FakeLaufer({"typ = 'befund_entscheid'": json.dumps([eintrag])})
        antwort = self.client.get(
            "/api/befund/entscheide", params={"von": "2026-08-01", "bis": "2026-08-26"}
        )
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), [eintrag])


class SitzungDetailTest(unittest.TestCase):
    """C1: `/api/sitzung/{id}` nimmt die LOGISCHE ID -- jeder Test stubt darum zusaetzlich die
    Versions-Aufloesung (`_version_fuer`/`_sql_versionen`), hier immer mit derselben Zahl wie
    die (bisherige) Version, um an den restlichen Stubs/Assertions nichts aendern zu muessen."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def _aufloesung(self, logisch: int, version: int | None = None) -> dict:
        """Stubt `_version_fuer` (kein `?version=`) + `_sql_versionen`. Der zweite Schluessel
        matcht auf `jsonb_agg(id ORDER BY id DESC)` statt auf `FROM sitzung WHERE logisch_ref =
        <n>` -- letzteres steckt auch in der Fallback-Subquery von `_sql_vieraugen` und wuerde
        sonst deren Antwort ueberschreiben (Legacy-Leseregel, C1 Regel 2)."""
        version = logisch if version is None else version
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(version),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([version]),
        }

    def test_sitzung_liefert_dissens_status(self) -> None:
        dokument = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc")).als_dict()
        vieraugen_ergebnis = {
            "sitzung_id": "abc", "quelle": "claude", "dissens": 1,
            "befunde": [{"regel": "subagent:unsupported_claim", "status": "dissens"}],
        }
        web.LAUFER = FakeLaufer({
            **self._aufloesung(9),
            "FROM sitzung WHERE id = 9": json.dumps(dokument),
            "sitzung_logisch' = '9'": json.dumps(vieraugen_ergebnis),
        })
        antwort = self.client.get("/api/sitzung/9")
        daten = antwort.json()
        self.assertEqual(daten["dokument"], dokument)
        self.assertEqual(daten["vieraugen"]["befunde"][0]["status"], "dissens")
        self.assertEqual(daten["sitzung_logisch"], 9)
        self.assertEqual(daten["version"], 9)
        self.assertEqual(daten["versionen"], [9])

    def test_sitzung_liefert_befund_entscheide_je_signatur(self) -> None:
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"))
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="error:recurring", schwere="warnung", signatur="error:recurring:abc"),
            Auffaelligkeit(regel="cost:outlier", schwere="warnung", signatur="cost:outlier"),
        ]
        dokument = beleg.als_dict()
        entscheid = {
            "signatur": "error:recurring:abc", "sitzung_ref": None, "status": "erledigt",
            "vermerk": "v", "begruendung": "b", "entschieden_am": "2026-08-26T10:00:00+00:00",
            "entschieden_von": "Maintainer",
        }
        web.LAUFER = FakeLaufer({
            **self._aufloesung(11),
            "FROM sitzung WHERE id = 11": json.dumps(dokument),
            "typ = 'befund_entscheid'": json.dumps([entscheid]),
        })
        antwort = self.client.get("/api/sitzung/11")
        daten = antwort.json()
        self.assertEqual(daten["befund_entscheide"]["error:recurring:abc"]["status"], "erledigt")
        self.assertNotIn("cost:outlier", daten["befund_entscheide"])

    def test_sitzung_markiert_befund_als_rueckfall_bei_neuer_sitzung_seit_entscheid(self) -> None:
        """Gleiche Rückfall-Logik wie das Fehler-Panel, hier für die Befund-Karte der
        Sitzungsseite (Entscheid 2026-08-26)."""
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"))
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="error:recurring", schwere="warnung", signatur="error:recurring:abc", ref="abc"),
        ]
        dokument = beleg.als_dict()
        entscheid = {
            "signatur": "error:recurring:abc", "sitzung_ref": None, "status": "erledigt",
            "vermerk": "v", "begruendung": "b", "entschieden_am": "2026-08-20T10:00:00+00:00",
            "entschieden_von": "Maintainer",
        }
        sitzungszeiten = [{"signatur": "abc", "sitzung_id": 12, "zeit": "2026-08-21T09:00:00+00:00", "treffer": 2}]
        web.LAUFER = FakeLaufer({
            **self._aufloesung(12),
            "FROM sitzung WHERE id = 12": json.dumps(dokument),
            "typ = 'befund_entscheid'": json.dumps([entscheid]),
            "GROUP BY 1, 2, 3": json.dumps(sitzungszeiten),
        })
        antwort = self.client.get("/api/sitzung/12")
        eintrag = antwort.json()["befund_entscheide"]["error:recurring:abc"]
        self.assertEqual(eintrag["status"], "rueckfall")
        self.assertEqual(eintrag["rueckfall_treffer"], 2)
        self.assertEqual(eintrag["rueckfall_sitzungen"], {"anzahl": 1, "sitzung_ids": [12]})

    def test_sitzung_filtert_fremdschluessel_aus_dem_dokument(self) -> None:
        """Befund 3 (Review 2026-08-26, MITTEL): /api/sitzung/{id} gab bisher das rohe JSONB
        zurueck -- ohne Projektion koennten unbekannte Schluessel (z. B. versehentlich gespeicherte
        Inhalte) durchrutschen. Fix: durch `_beleg_aus_dict(...).als_dict()` laufen lassen."""
        dokument = baue_beleg().als_dict()
        dokument["prompt"] = "geheim"
        web.LAUFER = FakeLaufer({**self._aufloesung(9), "FROM sitzung WHERE id = 9": json.dumps(dokument)})
        antwort = self.client.get("/api/sitzung/9")
        self.assertNotIn("prompt", antwort.json()["dokument"])

    def test_sitzung_nicht_gefunden_liefert_404(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/sitzung/999")
        self.assertEqual(antwort.status_code, 404)

    def test_sitzung_version_ausserhalb_der_logischen_sitzung_liefert_404(self) -> None:
        """C1: `?version=` wird gegen `logisch_ref` geprueft -- eine fremde Version darf nicht
        geladen werden, nur weil ihre `sitzung.id` existiert."""
        web.LAUFER = FakeLaufer({
            "sitzung_aktuell WHERE logisch_ref = 9": "",
            "WHERE id = 77 AND logisch_ref = 9": "",
        }, default="")
        antwort = self.client.get("/api/sitzung/9", params={"version": 77})
        self.assertEqual(antwort.status_code, 404)

    def test_subagent_ausserhalb_index_liefert_404(self) -> None:
        dokument = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc")).als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(3), "FROM sitzung WHERE id = 3": json.dumps(dokument)})
        antwort = self.client.get("/api/sitzung/3/subagent/0")
        self.assertEqual(antwort.status_code, 404)

    def test_subagent_liefert_eintrag(self) -> None:
        dokument = baue_beleg(
            kopf=Kopf(quelle="claude", sitzung_id="abc"),
            subagenten=[Subagent(agent_id="s1", typ="Explore")],
        ).als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(3), "FROM sitzung WHERE id = 3": json.dumps(dokument)})
        antwort = self.client.get("/api/sitzung/3/subagent/0")
        self.assertEqual(antwort.json()["subagent"]["agent_id"], "s1")

    def test_sitzung_reichert_befunde_mit_regeltext_und_position_an(self) -> None:
        """Abnahme "Block 4 Sitzungsdetail" (2026-08-26), Auftrag B.4/B.6: jeder Befund
        traegt titel/bedeutung/was_tun (regeltexte.py) und -- wo die Regel ein Einzelereignis
        kennt -- eine Position (Runde + Zeitpunkt + Ereignis-Index); sitzungsweite Regeln
        (hier subagent:overdelegation) liefern `position: None`."""
        ereignisse = [
            Ereignis(zeit="2026-08-25T10:00:00Z", art=ART_NUTZER),
            Ereignis(zeit="2026-08-25T10:00:01Z", art=ART_TOOL_ERGEBNIS, name="Bash",
                      fehler=True, ref="toolu_1"),
            Ereignis(zeit="2026-08-25T10:05:00Z", art=ART_NUTZER),
            Ereignis(zeit="2026-08-25T10:05:01Z", art=ART_TOOL_ERGEBNIS, name="Bash",
                      fehler=True, ref="toolu_2"),
        ]
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"), ereignisse=ereignisse)
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="rework:tool", schwere="warnung", signatur="rework:tool:Bash",
                            ref="Bash", wert="4"),
            Auffaelligkeit(regel="subagent:overdelegation", schwere="hinweis",
                            signatur="subagent:overdelegation", wert="30 Subagenten, Tiefe 1"),
        ]
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(21), "FROM sitzung WHERE id = 21": json.dumps(dokument)})

        antwort = self.client.get("/api/sitzung/21")
        auff = {a["regel"]: a for a in antwort.json()["dokument"]["auffaelligkeiten"]}

        self.assertEqual(auff["rework:tool"]["titel"], "Werkzeug-Nacharbeit")
        self.assertTrue(auff["rework:tool"]["bedeutung"])
        self.assertEqual(auff["rework:tool"]["position"]["runde"], 1)
        self.assertEqual(auff["rework:tool"]["position"]["ereignis_index"], 1)

        self.assertEqual(auff["subagent:overdelegation"]["titel"], "Überdelegation")
        self.assertIsNone(auff["subagent:overdelegation"]["position"])

    def test_position_latency_tool_findet_direkten_ref_treffer_aus_alt_belegen(self) -> None:
        """Referenz-Sitzung #n (vor der Gruppierung nach Werkzeugname, siehe regeln.py-
        Kommentar zu latency:timeout) trug in `ref` noch die tool_use_id statt des
        Werkzeugnamens -- die Positions-Suche muss beide Formen finden."""
        ereignisse = [
            Ereignis(zeit="2026-08-25T10:00:00Z", art=ART_NUTZER),
            Ereignis(zeit="2026-08-25T10:00:01Z", art=ART_TOOL, name="Bash", ref="toolu_alt",
                      dauer_ms=120540),
        ]
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"), ereignisse=ereignisse)
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="latency:slow_turn", schwere="hinweis",
                            signatur="latency:slow_turn:tool:Bash", ref="toolu_alt", wert="120 s"),
        ]
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(22), "FROM sitzung WHERE id = 22": json.dumps(dokument)})

        antwort = self.client.get("/api/sitzung/22")
        position = antwort.json()["dokument"]["auffaelligkeiten"][0]["position"]
        self.assertEqual(position["ereignis_index"], 1)

    def test_sitzung_befund_entscheide_umfasst_auch_vieraugen_zusatzbefunde(self) -> None:
        """Auftrag C.8 (Abnahme 2026-08-26): der Dissens-Knopf im Vier-Augen-Panel prueft
        denselben `befund_entscheide`-Datensatz wie die Befunde-Karten -- das muss auch fuer
        Vier-Augen-eigene `zusatz:...`-Befunde gelten, die NICHT in `beleg.auffaelligkeiten`
        stehen (das Modell darf bis zu zwei eigene Funde nennen, siehe vieraugen.py). `entscheid`
        traegt hier noch den Alt-Stil (`sitzung_ref` = Version, C1 Regel 2 Legacy-Leseregel)."""
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"))
        dokument = beleg.als_dict()
        vieraugen_ergebnis = {
            "sitzung_id": "abc", "quelle": "claude", "dissens": 1,
            "befunde": [{"regel": "zusatz:doppelte_kosten", "signatur": "zusatz:doppelte_kosten",
                         "status": "dissens"}],
        }
        entscheid = {
            "signatur": "zusatz:doppelte_kosten", "sitzung_ref": 23, "status": "erledigt",
            "vermerk": "v", "begruendung": "b", "entschieden_am": "2026-08-26T10:00:00+00:00",
            "entschieden_von": "Maintainer",
        }
        web.LAUFER = FakeLaufer({
            **self._aufloesung(23),
            "FROM sitzung WHERE id = 23": json.dumps(dokument),
            "sitzung_logisch' = '23'": json.dumps(vieraugen_ergebnis),
            "typ = 'befund_entscheid'": json.dumps([entscheid]),
            "id IN (23)": json.dumps([{"id": 23, "logisch_ref": 23}]),
        })
        antwort = self.client.get("/api/sitzung/23")
        self.assertEqual(
            antwort.json()["befund_entscheide"]["zusatz:doppelte_kosten"]["status"], "erledigt"
        )


class ChatKennzahlenKontextTest(unittest.TestCase):
    """Fund 2026-08-27: die Besprechungs-Spalte kannte nur die Sitzungs-ID, kein Modell konnte
    Kennzahlenfragen beantworten -- der Server haengt seither `kennzahlen_block` an (`_sitzung()`
    speist sowohl die Detailseite als auch `POST /api/chat`, keine zweite Berechnung)."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)
        chat._GESPRAECHE.clear()
        chat._AUSSTEHEND.clear()

    def tearDown(self) -> None:
        web.LAUFER = self.alt
        chat._GESPRAECHE.clear()
        chat._AUSSTEHEND.clear()

    def _aufloesung(self, logisch: int) -> dict:
        return {
            f"sitzung_aktuell WHERE logisch_ref = {logisch}": str(logisch),
            "jsonb_agg(id ORDER BY id DESC)": json.dumps([logisch]),
        }

    def test_sitzung_detail_traegt_kennzahlen_block(self) -> None:
        dokument = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc")).als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(137), "FROM sitzung WHERE id = 137": json.dumps(dokument)})
        antwort = self.client.get("/api/sitzung/137")
        block = antwort.json()["kennzahlen_block"]
        self.assertIn("Sitzung 137", block)
        self.assertIn("Quelle claude", block)

    def test_chat_start_mit_sitzungskontext_haengt_kennzahlen_block_an(self) -> None:
        dokument = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc")).als_dict()
        web.LAUFER = FakeLaufer({**self._aufloesung(137), "FROM sitzung WHERE id = 137": json.dumps(dokument)})
        body = {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5", "text": "Frage?",
            "kontext": {"sitzung_logisch": 137, "signatur": None, "runde": None, "analyse_id": None},
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)
        gid = antwort.json()["gespraech_id"]
        block = chat._GESPRAECHE[gid]["kontext"]["kennzahlen_block"]
        self.assertIn("Sitzung 137", block)

    def test_chat_start_ohne_sitzungskontext_bleibt_ohne_kennzahlen_block(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        body = {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5", "text": "Frage?",
            "kontext": {"sitzung_logisch": None, "signatur": None, "runde": None, "analyse_id": None},
        }
        antwort = self.client.post("/api/chat", json=body)
        gid = antwort.json()["gespraech_id"]
        self.assertNotIn("kennzahlen_block", chat._GESPRAECHE[gid]["kontext"])

    def test_chat_start_mit_unbekannter_sitzung_bleibt_ohne_kennzahlen_block(self) -> None:
        """Fail-open (C7): eine (noch) unbekannte/nicht erreichbare Sitzung darf den Chat-Start
        nicht verhindern -- nur der Kennzahlen-Kontext fehlt dann."""
        web.LAUFER = FakeLaufer({}, default="")
        body = {
            "gespraech_id": None, "anbieter": "claude", "modell": "claude-sonnet-5", "text": "Frage?",
            "kontext": {"sitzung_logisch": 999999, "signatur": None, "runde": None, "analyse_id": None},
        }
        antwort = self.client.post("/api/chat", json=body)
        self.assertEqual(antwort.status_code, 202)
        gid = antwort.json()["gespraech_id"]
        self.assertNotIn("kennzahlen_block", chat._GESPRAECHE[gid]["kontext"])


class SitzungVersionRouteTest(unittest.TestCase):
    """C1 Regel 5: Uebergangsroute fuer alte `#sitzung/<version>`-Links."""

    def setUp(self) -> None:
        self.alt = web.LAUFER
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt

    def test_version_route_liefert_logische_id(self) -> None:
        web.LAUFER = FakeLaufer({"WHERE id = 1284": "512"})
        antwort = self.client.get("/api/sitzung/version/1284")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"sitzung_logisch": 512})

    def test_version_route_unbekannte_version_liefert_404(self) -> None:
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.get("/api/sitzung/version/999999")
        self.assertEqual(antwort.status_code, 404)


class PruefenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alt_laufer = web.LAUFER
        self.alt_review = web.VIERAUGEN_REVIEW
        self.client = TestClient(web.app)

    def tearDown(self) -> None:
        web.LAUFER = self.alt_laufer
        web.VIERAUGEN_REVIEW = self.alt_review
        web._letzter_fehler.clear()

    def test_pruefen_startet_asynchron_und_ruft_review_im_hintergrund_auf(self) -> None:
        dokument = baue_beleg().als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 5": json.dumps(dokument)})

        aufgerufen = threading.Event()

        def stub_review(beleg):
            aufgerufen.set()
            return {"sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle,
                     "befunde": [], "zusatz": [], "fehler": {}, "dissens": 0}

        web.VIERAUGEN_REVIEW = stub_review

        antwort = self.client.post("/api/sitzung/5/pruefen")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"gestartet": True})
        self.assertTrue(aufgerufen.wait(timeout=5), "Hintergrund-Review wurde nicht aufgerufen")

    def test_pruefen_zweiter_post_waehrend_laufendem_review_liefert_laeuft_true(self) -> None:
        """Befund 4 (Review 2026-08-26, MITTEL): kein In-Flight-Guard -- ein Doppel-POST
        (Doppelklick, Retry) startete bisher zwei parallele Reviews fuer dieselbe Sitzung."""
        dokument = baue_beleg().als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 6": json.dumps(dokument)})

        gestartet = threading.Event()
        weiter = threading.Event()

        def stub_review(beleg):
            gestartet.set()
            weiter.wait(timeout=5)
            return {"sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle,
                     "befunde": [], "zusatz": [], "fehler": {}, "dissens": 0}

        web.VIERAUGEN_REVIEW = stub_review

        try:
            erste = self.client.post("/api/sitzung/6/pruefen")
            self.assertTrue(gestartet.wait(timeout=5))
            self.assertEqual(erste.json(), {"gestartet": True})

            zweite = self.client.post("/api/sitzung/6/pruefen")
            self.assertEqual(zweite.json(), {"gestartet": False, "laeuft": True})
        finally:
            weiter.set()
        for _ in range(50):
            if 6 not in web._laufend:
                break
            time.sleep(0.05)
        self.assertNotIn(6, web._laufend)

    def test_pruefen_fehler_im_hintergrund_stoert_den_server_nicht(self) -> None:
        """Sitzung existiert (Existenzpruefung besteht), aber das Review selbst wirft --
        die POST-Antwort bleibt 200, der Fehler landet in `_letzter_fehler` (Fund E)."""
        dokument = baue_beleg().als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 999": json.dumps(dokument)})

        def stub_review_wirft(beleg):
            raise RuntimeError("kaputt")

        web.VIERAUGEN_REVIEW = stub_review_wirft

        antwort = self.client.post("/api/sitzung/999/pruefen")
        self.assertEqual(antwort.status_code, 200)  # Hintergrundfehler ist kein HTTP-Fehler
        for _ in range(50):
            if 999 not in web._laufend:
                break
            time.sleep(0.05)
        self.assertIn("kaputt", web._letzter_fehler.get(999, ""))
        status = self.client.get("/api/sitzung/999/pruefen").json()
        self.assertFalse(status["laeuft"])
        self.assertIn("kaputt", status["fehler"])

    def test_pruefen_startet_nicht_fuer_nicht_existierende_sitzung(self) -> None:
        """Fund D: 404 VOR dem Thread-Start statt eines stillen 200 fuer eine ID, die es
        nicht gibt."""
        web.LAUFER = FakeLaufer({}, default="")
        antwort = self.client.post("/api/sitzung/12345/pruefen")
        self.assertEqual(antwort.status_code, 404)
        self.assertIn("12345", antwort.json()["detail"])
        self.assertNotIn(12345, web._laufend)

    def test_pruefen_letzter_fehler_wird_bei_neuem_lauf_geloescht(self) -> None:
        """Ein neuer Lauf darf nicht mehr den Fehlertext des vorherigen Laufs zeigen."""
        dokument = baue_beleg().als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 111": json.dumps(dokument)})
        web._letzter_fehler[111] = "alter Fehler"

        aufgerufen = threading.Event()

        def stub_review_ok(beleg):
            aufgerufen.set()
            return {"sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle,
                     "befunde": [], "zusatz": [], "fehler": {}, "dissens": 0}

        web.VIERAUGEN_REVIEW = stub_review_ok
        antwort = self.client.post("/api/sitzung/111/pruefen")
        self.assertEqual(antwort.json(), {"gestartet": True})
        self.assertNotIn(111, web._letzter_fehler)
        self.assertTrue(aufgerufen.wait(timeout=5))

    def test_pruefen_funktioniert_mit_angereicherten_auffaelligkeiten(self) -> None:
        """Regression (Abnahme "Block 4 Sitzungsdetail", 2026-08-26, Auftrag B.4/B.6):
        `_sitzung()` reichert `dokument['auffaelligkeiten']` um titel/bedeutung/was_tun/
        position an -- `modell.Auffaelligkeit(**a)` kennt diese Zusatzfelder nicht.
        `_pruefen_hintergrund` muss darum das ROHE Dokument lesen, nicht ueber `_sitzung()`
        gehen, sonst crasht der Hintergrund-Thread fuer jede Sitzung mit mindestens einem
        Befund (vorher unbemerkt, weil alle bestehenden Pruefen-Tests mit einem Beleg OHNE
        Auffaelligkeiten arbeiteten)."""
        beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="abc"))
        beleg.auffaelligkeiten = [
            Auffaelligkeit(regel="subagent:overdelegation", schwere="hinweis",
                            signatur="subagent:overdelegation", wert="30 Subagenten, Tiefe 1"),
        ]
        dokument = beleg.als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 7": json.dumps(dokument)})

        aufgerufen = threading.Event()

        def stub_review(beleg):
            aufgerufen.set()
            return {"sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle,
                     "befunde": [], "zusatz": [], "fehler": {}, "dissens": 0}

        web.VIERAUGEN_REVIEW = stub_review

        antwort = self.client.post("/api/sitzung/7/pruefen")
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(aufgerufen.wait(timeout=5), "Hintergrund-Review wurde nicht aufgerufen")

    def test_pruefen_status_liefert_laeuft_false_ohne_laufenden_review(self) -> None:
        """Feedback 2026-08-26, Punkt 3c: GET darf NIE selbst eine Pruefung starten."""
        antwort = self.client.get("/api/sitzung/42/pruefen")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"laeuft": False, "seit": None, "fehler": None})

    def test_pruefen_status_zeigt_laeuft_true_mit_startzeit_waehrend_review_laeuft(self) -> None:
        dokument = baue_beleg().als_dict()
        web.LAUFER = FakeLaufer({"FROM sitzung WHERE id = 8": json.dumps(dokument)})

        gestartet = threading.Event()
        weiter = threading.Event()

        def stub_review(beleg):
            gestartet.set()
            weiter.wait(timeout=5)
            return {"sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle,
                     "befunde": [], "zusatz": [], "fehler": {}, "dissens": 0}

        web.VIERAUGEN_REVIEW = stub_review

        try:
            self.client.post("/api/sitzung/8/pruefen")
            self.assertTrue(gestartet.wait(timeout=5))
            status = self.client.get("/api/sitzung/8/pruefen").json()
            self.assertTrue(status["laeuft"])
            self.assertIsNotNone(status["seit"])
            datetime.fromisoformat(status["seit"])  # muss parsebar sein
        finally:
            weiter.set()
        for _ in range(50):
            if 8 not in web._laufend:
                break
            time.sleep(0.05)
        nach_ende = self.client.get("/api/sitzung/8/pruefen").json()
        self.assertEqual(nach_ende, {"laeuft": False, "seit": None, "fehler": None})


class PreiseTest(unittest.TestCase):
    def test_preise_liefert_waehrung_und_modelle(self) -> None:
        antwort = TestClient(web.app).get("/api/preise")
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(daten["waehrung"], "USD")
        self.assertIn("claude-sonnet-5", daten["preise"])

    def test_preise_behalten_anzeigefelder_und_liefern_block_stand(self) -> None:
        """Nachtrag 2026-08-30 (Preistabelle im Katalog-Look): die Anzeige braucht
        herkunft/stand/preis_art je Eintrag -- `_preise_aus_block` warf alles ausser den
        PREIS_FELDERn still weg (UI zeigte leere Chips und Stand "—"). Additiv zur
        Abrechnung: kennzahlen liest weiter nur die Rechenfelder."""
        antwort = TestClient(web.app).get("/api/preise")
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        self.assertEqual(daten["stand"], "2026-08-26")
        self.assertEqual(daten["preise"]["claude-sonnet-5"]["herkunft"], "anthropic")
        self.assertEqual(daten["preise"]["claude-sonnet-5"]["cache_quelle"], "abgeleitet")
        self.assertEqual(daten["preise"]["gpt-5.5"]["stand"], "2026-08-26")
        self.assertEqual(daten["preise"]["gpt-5.5"]["herkunft"], "openai")
        self.assertEqual(daten["preise"]["glm-5.2"]["preis_art"], "referenz")

    def test_preise_ollama_basis_keys_tragen_referenz_zeiger(self) -> None:
        """Befund 2026-08-30: die Ollama-Basis-Keys ohne Tag (gpt-oss, qwen3-vl,
        mistral-large-3, gemma4) tragen den kuratierten `referenz`-Zeiger auf die
        Groessenvariante, damit die Server-Anreicherung ihren Status/Sterne findet (die
        Basis-Zeile selbst entfernt der Katalog als Dublette)."""
        daten = TestClient(web.app).get("/api/preise").json()
        for key, ref in {"gpt-oss": "gpt-oss-20b", "qwen3-vl": "qwen3-vl-235b-a22b-instruct",
                         "mistral-large-3": "mistral-large-2512",
                         "gemma4": "gemma-4-31b-it"}.items():
            self.assertEqual(daten["preise"][key].get("referenz"), ref)

    def test_preise_katalog_meta_traegt_sterne_gesamt(self) -> None:
        """Maintainer 2026-08-30 (Status-Zone unten): die server-Anreicherung (`satz.katalog`) traegt
        `sterne_gesamt`, damit die Preistabelle bewertete Modelle mit Sternen zeigen kann.
        Fail-soft: laeuft die DB nicht, gibt es kein `katalog`-Feld -- dann prueft der Test
        nichts (Unit-Deckung steht in test_katalog_sicht.PreiseAnreichernTest)."""
        antwort = TestClient(web.app).get("/api/preise")
        self.assertEqual(antwort.status_code, 200)
        daten = antwort.json()
        if not daten.get("katalog_verfuegbar"):
            self.skipTest("Katalog-DB nicht erreichbar (Fail-soft-Pfad)")
        for eintrag in daten["preise"].values():
            self.assertIn("sterne_gesamt", eintrag.get("katalog", {}))


class ServeTest(unittest.TestCase):
    def test_serve_bindet_nur_127_0_0_1(self) -> None:
        alt_ingest = web._ingest_beim_start
        alt_run = web.uvicorn.run
        aufrufe: list[dict] = []
        web._ingest_beim_start = lambda: None
        web.uvicorn.run = lambda app, **kw: aufrufe.append(kw)
        try:
            web.serve()
        finally:
            web._ingest_beim_start = alt_ingest
            web.uvicorn.run = alt_run
        self.assertEqual(aufrufe, [{"host": "127.0.0.1", "port": 8091}])
        self.assertEqual(web.HOST, "127.0.0.1")

    def test_serve_mit_logdatei_loest_konsole_und_schreibt_log(self) -> None:
        import tempfile
        from pathlib import Path

        alt = (web._ingest_beim_start, web.uvicorn.run, web._konsole_freigeben, sys.stdout, sys.stderr)
        geloest: list[bool] = []
        web._ingest_beim_start = lambda: print("start-marker")
        web.uvicorn.run = lambda app, **kw: None
        web._konsole_freigeben = lambda: geloest.append(True)
        try:
            with tempfile.TemporaryDirectory() as ordner:
                log = Path(ordner) / "unter" / "dashboard.log"
                web.serve(log_datei=log, port=8099)
                strom = sys.stdout
                strom.close()
                inhalt = log.read_text(encoding="utf-8")
        finally:
            web._ingest_beim_start, web.uvicorn.run, web._konsole_freigeben = alt[:3]
            sys.stdout, sys.stderr = alt[3:]
        self.assertEqual(geloest, [True])
        self.assertIn("start-marker", inhalt)

    def test_konsole_freigeben_ruft_freeconsole(self) -> None:
        class Kernel:
            aufrufe = 0

            def FreeConsole(self):
                self.aufrufe += 1
                return 1

        k = Kernel()
        self.assertTrue(web._konsole_freigeben(k))
        self.assertEqual(k.aufrufe, 1)

    def test_ingest_beim_start_faengt_fehler_ab(self) -> None:
        from .. import __main__ as cli

        alt = cli._befehl_ingest_dir

        def wirft(args):
            raise RuntimeError("kein docker")

        cli._befehl_ingest_dir = wirft
        try:
            web._ingest_beim_start()  # darf trotz Fehler nicht werfen (fail-open)
        finally:
            cli._befehl_ingest_dir = alt


if __name__ == "__main__":
    unittest.main()
