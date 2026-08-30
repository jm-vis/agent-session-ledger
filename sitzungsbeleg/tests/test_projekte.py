"""Tests für projekte.py — Projekt+Kontext-Alias (Entscheid 2026-08-26, Auftrag 1).

Fail-open ist das Kernversprechen: fehlt/kaputt die Alias-Datei, bleibt der Rohname
unverändert (Kontext `unzugeordnet`) -- nie ein Absturz beim Lesen des Dashboards.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .. import projekte


class LadeAliaseTest(unittest.TestCase):
    def test_laedt_gepflegte_datei_ohne_hinweisfeld(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "aliase.json"
            pfad.write_text(
                json.dumps({
                    "_hinweis": "Kommentar",
                    "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
                }),
                encoding="utf-8",
            )
            aliase = projekte.lade_aliase(pfad)
        self.assertEqual(aliase, {"scripts": {"projekt": "00_Workspace", "kontext": "arbeit"}})

    def test_fehlende_datei_ist_fail_open(self) -> None:
        aliase = projekte.lade_aliase(Path("nicht-vorhanden.json"))
        self.assertEqual(aliase, {})

    def test_kaputtes_json_ist_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "aliase.json"
            pfad.write_text("{kein json", encoding="utf-8")
            aliase = projekte.lade_aliase(pfad)
        self.assertEqual(aliase, {})

    def test_liste_statt_objekt_ist_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "aliase.json"
            pfad.write_text("[1, 2, 3]", encoding="utf-8")
            aliase = projekte.lade_aliase(pfad)
        self.assertEqual(aliase, {})

    def test_eintrag_ohne_projekt_feld_wird_uebersprungen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "aliase.json"
            pfad.write_text(json.dumps({"kaputt": {"kontext": "arbeit"}}), encoding="utf-8")
            aliase = projekte.lade_aliase(pfad)
        self.assertEqual(aliase, {})


class AufloesenTest(unittest.TestCase):
    def setUp(self) -> None:
        self.aliase = {
            "00_Workspace": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "scratchpad": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "fg_home": {"projekt": "00_Workspace", "kontext": "voice"},
            "codex-workspace": {"projekt": "00_Workspace", "kontext": "review"},
            "codex-beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt@codex": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "arbeit"},
            "bar-observatory": {"projekt": "Fremd-Repo", "kontext": "bewertung"},
            "00 TV-Filme": {"projekt": "Privat", "kontext": "arbeit", "ausgeblendet": True},
        }

    def test_bekannter_rohname_wird_aufgeloest(self) -> None:
        self.assertEqual(
            projekte.aufloesen("scripts", "claude", self.aliase), ("00_Workspace", "arbeit", False)
        )

    def test_unbekannter_rohname_wird_unzugeordnet(self) -> None:
        self.assertEqual(
            projekte.aufloesen("irgendwas-neues", "claude", self.aliase),
            ("irgendwas-neues", "unzugeordnet", False),
        )

    def test_ausgeblendetes_projekt_traegt_das_flag(self) -> None:
        self.assertEqual(
            projekte.aufloesen("00 TV-Filme", "claude", self.aliase), ("Privat", "arbeit", True)
        )

    def test_quellenabhaengige_aufloesung_beispielprojekt_codex_vor_plain(self) -> None:
        """Schlüssel `Beispielprojekt@codex` geht `Beispielprojekt` vor (Alias-Regel darf die Quelle
        berücksichtigen) -- codex -> review, claude -> arbeit."""
        self.assertEqual(
            projekte.aufloesen("Beispielprojekt", "codex", self.aliase), ("Beispielprojekt", "review", False)
        )
        self.assertEqual(
            projekte.aufloesen("Beispielprojekt", "claude", self.aliase), ("Beispielprojekt", "arbeit", False)
        )

    def test_codex_praefix_automatik_mit_bekanntem_ziel(self) -> None:
        """`codex-<x>` ohne eigenen Eintrag -> Alias von `<x>` (falls vorhanden), Kontext review."""
        self.assertEqual(
            projekte.aufloesen("codex-scripts", "codex", self.aliase),
            ("00_Workspace", "review", False),
        )

    def test_codex_praefix_automatik_ohne_bekanntes_ziel(self) -> None:
        self.assertEqual(
            projekte.aufloesen("codex-irgendwas", "codex", self.aliase),
            ("irgendwas", "review", False),
        )

    def test_codex_beispielprojekt_hat_eigenen_eintrag_vor_der_automatik(self) -> None:
        self.assertEqual(
            projekte.aufloesen("codex-beispielprojekt", "codex", self.aliase),
            ("Beispielprojekt", "review", False),
        )

    def test_leere_aliase_sind_fail_open(self) -> None:
        self.assertEqual(projekte.aufloesen("Beispielprojekt", "claude", {}), ("Beispielprojekt", "unzugeordnet", False))


class RohEintraegeFuerProjektTest(unittest.TestCase):
    def test_vereint_einfache_und_zusammengesetzte_schluessel_plus_projekt_selbst(self) -> None:
        aliase = {
            "scripts": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "scratchpad": {"projekt": "00_Workspace", "kontext": "arbeit"},
            "codex-workspace": {"projekt": "00_Workspace", "kontext": "review"},
        }
        self.assertEqual(
            projekte.roh_eintraege_fuer_projekt("00_Workspace", aliase),
            [
                ("00_Workspace", None),
                ("codex-workspace", None),
                ("scratchpad", None),
                ("scripts", None),
            ],
        )

    def test_zusammengesetzter_schluessel_liefert_quelle(self) -> None:
        aliase = {
            "codex-beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt@codex": {"projekt": "Beispielprojekt", "kontext": "review"},
            "Beispielprojekt": {"projekt": "Beispielprojekt", "kontext": "arbeit"},
        }
        treffer = projekte.roh_eintraege_fuer_projekt("Beispielprojekt", aliase)
        self.assertIn(("Beispielprojekt", "codex"), treffer)
        self.assertIn(("Beispielprojekt", None), treffer)
        self.assertIn(("codex-beispielprojekt", None), treffer)

    def test_ohne_treffer_liefert_nur_das_projekt_selbst(self) -> None:
        self.assertEqual(
            projekte.roh_eintraege_fuer_projekt("Solo", {"scripts": {"projekt": "00_Workspace", "kontext": "arbeit"}}),
            [("Solo", None)],
        )


if __name__ == "__main__":
    unittest.main()
