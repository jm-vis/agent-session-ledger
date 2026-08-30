"""Versionsquelle (Nachtrag 2026-08-27 Punkt 11): eine Quelle (`VERSION`-Datei), `GET /version`
und Platzhalter-Ersetzung liefern denselben Wert."""
from __future__ import annotations

import re
import unittest

from fastapi.testclient import TestClient

from .. import version, web


class LadeVersionTest(unittest.TestCase):
    def test_liest_und_trimmt_datei(self, tmp_faktor=None) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "VERSION"
            pfad.write_text("0.1.0\n", encoding="utf-8")
            self.assertEqual(version.lade_version(pfad), "0.1.0")

    def test_fehlende_datei_liefert_fallback(self) -> None:
        from pathlib import Path

        self.assertEqual(version.lade_version(Path("nicht-vorhanden-XYZ")), "0.0.0")

    def test_geladene_version_ist_semver(self) -> None:
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+$")


class HtmlMitVersionTest(unittest.TestCase):
    def test_ersetzt_jeden_platzhalter(self) -> None:
        html = '<span>v__VERSION__</span><script src="/x.js?v=__VERSION__">'
        ergebnis = version.html_mit_version(html)
        self.assertNotIn("__VERSION__", ergebnis)
        self.assertEqual(ergebnis.count(version.VERSION), 2)


class VersionEndpunktTest(unittest.TestCase):
    def test_get_version_liefert_produkt_und_version(self) -> None:
        client = TestClient(web.app)
        antwort = client.get("/version")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.json(), {"version": version.VERSION, "produkt": "sitzungsbeleg"})

    def test_index_html_traegt_keinen_platzhalter_mehr(self) -> None:
        client = TestClient(web.app)
        antwort = client.get("/")
        self.assertEqual(antwort.status_code, 200)
        self.assertNotIn("__VERSION__", antwort.text)

    def test_index_html_zeigt_dieselbe_version_wie_get_version(self) -> None:
        client = TestClient(web.app)
        html = client.get("/").text
        treffer = re.search(r'class="versions-tag"[^>]*>v([\d.]+)<', html)
        self.assertIsNotNone(treffer, "Versions-Caption nicht im HTML gefunden")
        self.assertEqual(treffer.group(1), version.VERSION)


if __name__ == "__main__":
    unittest.main()
