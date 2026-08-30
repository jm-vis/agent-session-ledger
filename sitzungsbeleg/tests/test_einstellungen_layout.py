"""Waechter-Test Einstellungen-Layout (Befund 2026-08-30): die Mittelspalte der Seite
Einstellungen durfte natuerlich wachsen (kein festes Hoehenmuster) -- seit der Modellkatalog-
Tabelle/Persistabelle laenger wurde, ragte sie unter die gemeinsame Unterkante von
Seitenleiste/#chat (Live-Messung 1845x967: mitte bottom 935 vs. chat 925). Loesung: dasselbe
Fix-oben/Scroll-innen-Muster wie die Sitzungsdetail-Seite -- `.detail-mitte` (feste Viewport-
Hoehe, overflow hidden) + `.detail-scroll` als einziger Innen-Scrollbereich. Der Test liest
nur Markup/CSS (kein Browser, kein Netz)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_STATIC = Path(__file__).parent.parent / "static"

_EINST_BLOCK_RE = re.compile(
    r'<section id="page-einstellungen".*?</section>', re.DOTALL)


class EinstellungenMittelspalteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        block = _EINST_BLOCK_RE.search(html)
        assert block, "page-einstellungen in index.html nicht gefunden"
        cls.block = block.group(0)

    def test_mittelspalte_traegt_detail_mitte_muster(self) -> None:
        """Feste Viewport-Hoehe + sticky = Unterkante buendig mit Seitenleiste/#chat."""
        self.assertRegex(self.block, r'<main class="hauptspalte detail-mitte"')

    def test_abschnitte_liegen_im_detail_scroll_container(self) -> None:
        """Nur DER Innenbereich scrollt (ohne sichtbaren eigenen Balken) -- die Seite selbst
        bleibt in Viewport-Hoehe, auch wenn die Katalog-/Preis-Tabelle laenger wird."""
        self.assertRegex(self.block, r'<div class="detail-scroll"[^>]*>')
        scroll_pos = self.block.index("detail-scroll")
        for abschnitt in ("modellkatalog-abschnitt", "einst-projekte-abschnitt",
                          "einst-preistabelle-abschnitt", "einst-redaktion-abschnitt",
                          "einst-retention-abschnitt"):
            with self.subTest(abschnitt=abschnitt):
                pos = self.block.index(f'id="{abschnitt}"')
                self.assertGreater(pos, scroll_pos)

    def test_style_css_kennt_das_muster(self) -> None:
        """Schutz gegen ein versehentliches Entfernen der Muster-Regeln selbst."""
        css = (_STATIC / "style.css").read_text(encoding="utf-8")
        self.assertIn(".detail-mitte {", css)
        self.assertIn(".detail-scroll {", css)


class PreistabelleTabelleTest(unittest.TestCase):
    """Befund 2026-08-30 (Preistabelle-Abschnitt): die Preistabelle lief als .table-wrap-
    Block natuerlich mit und sprengte die Ansicht -- sie bekommt dasselbe Muster wie alle
    anderen Tabellen der App: .tabelle-gitter mit eigener Kopf-Tabelle (.tabelle-kopf) und
    scrollendem Koerper (.tabelle-koerper mit sichtbarem Balken), vgl. Modellkatalog."""

    @classmethod
    def setUpClass(cls) -> None:
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        block = re.search(
            r'<div class="abschnitt einst-abschnitt" id="einst-preistabelle-abschnitt".*?</div>\s*<div class="abschnitt',
            html, re.DOTALL)
        assert block, "einst-preistabelle-abschnitt nicht gefunden"
        cls.block = block.group(0)

    def test_preistabelle_nutzt_tabelle_gitter_muster(self) -> None:
        self.assertIn('id="preistabelle-gitter"', self.block)
        self.assertIn("tabelle-gitter", self.block)
        self.assertIn("tabelle-kopf", self.block)

    def test_preistabelle_koerper_scrollt_innen(self) -> None:
        self.assertRegex(self.block, r'tabelle-koerper[^"]*" id="preistabelle-koerper"')
        self.assertIn('id="preistabelle-body"', self.block)

    def test_kopf_und_koerper_teilen_identische_colgroup(self) -> None:
        """Beispielprojekt-Muster: zwei Tabellen, identische Spaltenbreiten -- sonst laufen Kopf
        und Zeilen auseinander (Abnahme 2026-08-26, sticky-thead gescheitert)."""
        gruppen = re.findall(r"<colgroup>(.*?)</colgroup>", self.block, re.DOTALL)
        self.assertEqual(len(gruppen), 2)
        self.assertEqual(gruppen[0], gruppen[1])

    def test_style_css_hat_pt_koerper_hoehe(self) -> None:
        css = (_STATIC / "style.css").read_text(encoding="utf-8")
        self.assertIn(".pt-koerper {", css)
        self.assertIn("max-height", css.split(".pt-koerper {")[1].split("}")[0])

    def test_katalog_look_spalten_und_sortierung(self) -> None:
        """Auftrag 2026-08-30 Nachtrag: Katalog-Spaltenbild 1:1 (ohne Sterne/Latest/Legacy/
        AA-Index/Coding), Sortierung je Spalte, Verwendet-in ganz rechts."""
        koepfe = re.findall(r'class="th-sort" data-col="([a-z_]+)"', self.block)
        self.assertEqual(koepfe, ["modell", "herkunft", "anbieter", "kontext",
                                  "eingabe", "ausgabe", "stand", "verwendet"])
        for nicht in ("aa_index", "coding_index", "sterne", "legacy"):
            self.assertNotIn(f'data-col="{nicht}"', self.block)


if __name__ == "__main__":
    unittest.main()
