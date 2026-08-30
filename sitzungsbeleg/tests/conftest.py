"""Testweite Schutzschalter.

Zentrale Schluesseldatei (2026-08-28): seit `scripts\\.env` mit ECHTEN Schluesseln existiert, darf
KEIN Test sie lesen — sonst schlagen 'Schluessel fehlt'-Tests fehl und (schlimmer) echte
Schluesselwerte landen in Assertion-Diffs und damit in Logs. Die Fixture biegt
`schluessel.ZENTRALE_DATEI` fuer jeden Test auf einen nicht existierenden Pfad um; Tests, die die
zentrale Datei selbst pruefen (test_schluessel.py), setzen sie explizit auf ihr Tempdir.
"""
from pathlib import Path

import pytest

from sitzungsbeleg import schluessel


@pytest.fixture(autouse=True)
def _zentrale_env_datei_isoliert(tmp_path):
    vorher = schluessel.ZENTRALE_DATEI
    schluessel.ZENTRALE_DATEI = tmp_path / "env-nicht-vorhanden"
    yield
    schluessel.ZENTRALE_DATEI = vorher
