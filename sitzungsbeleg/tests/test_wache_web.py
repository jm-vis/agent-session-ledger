"""C13-Nachtrag -- Meldungsspur lesbar: Zeitraum-Endpunkt (Start-Kachel) + Sitzungs-Endpunkt
(Verlauf-Zeitleiste), 30 s Datei-Cache. Endpunkte haengen ueber `web.app` (Muster
test_befund_kacheln.py)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .. import wache_web, web


@pytest.fixture(autouse=True)
def _leerer_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(wache_web, "SPOOL_PFAD", tmp_path / "wache-meldungen.jsonl")
    wache_web._cache = {"stand": 0.0, "zeilen": []}
    yield
    wache_web._cache = {"stand": 0.0, "zeilen": []}


def _zeile(zeit="2026-08-28T10:00:00+00:00", session_id="s1", stufe="warnen", **rest):
    zeile = {"zeit": zeit, "session_id": session_id, "projekt_hash": "ph1",
             "signatur": "tool:error_rate", "stufe": stufe, "wert": "25 %",
             "verankerung": None, "text": "Wache: Hohe Fehlerquote — 25 %."}
    zeile.update(rest)
    return zeile


def test_meldungen_endpunkt_zaehlt_zeitraum_und_offene_fragen():
    wache_web.SPOOL_PFAD.write_text(
        json.dumps(_zeile()) + "\n" + json.dumps(_zeile(stufe="fragen")) + "\n"
        + json.dumps(_zeile(zeit="2026-01-01T00:00:00+00:00")) + "\n",  # ausserhalb des Zeitraums
        encoding="utf-8",
    )
    client = TestClient(web.app)

    r = client.get("/api/wache/meldungen", params={"von": "2026-08-01", "bis": "2026-08-31"})

    assert r.status_code == 200
    daten = r.json()
    assert daten["anzahl"] == 2
    assert daten["offen_fragen"] == 1


def test_meldungen_endpunkt_ohne_spool_datei_liefert_leer():
    client = TestClient(web.app)
    r = client.get("/api/wache/meldungen", params={"von": "2026-08-01", "bis": "2026-08-31"})
    assert r.json() == {"anzahl": 0, "offen_fragen": 0, "meldungen": []}


def test_kaputte_zeile_wird_uebersprungen_nicht_geworfen():
    wache_web.SPOOL_PFAD.write_text("{kaputt\n" + json.dumps(_zeile()) + "\n", encoding="utf-8")
    client = TestClient(web.app)
    r = client.get("/api/wache/meldungen", params={"von": "2026-08-01", "bis": "2026-08-31"})
    assert r.json()["anzahl"] == 1


def test_sitzung_wache_endpunkt_filtert_ueber_session_id(monkeypatch):
    wache_web.SPOOL_PFAD.write_text(
        json.dumps(_zeile(session_id="abc-123")) + "\n" + json.dumps(_zeile(session_id="andere")) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web, "_sitzung", lambda sid: {"dokument": {"kopf": {"sitzung_id": "abc-123"}}})
    client = TestClient(web.app)

    r = client.get("/api/sitzung/512/wache")

    assert r.status_code == 200
    meldungen = r.json()["meldungen"]
    assert len(meldungen) == 1
    assert meldungen[0]["session_id"] == "abc-123"


def test_lade_zeilen_cached_30_sekunden(tmp_path, monkeypatch):
    wache_web.SPOOL_PFAD.write_text(json.dumps(_zeile()) + "\n", encoding="utf-8")
    erste = wache_web._lade_zeilen()
    wache_web.SPOOL_PFAD.write_text("", encoding="utf-8")  # Datei geleert, Cache bleibt gueltig
    zweite = wache_web._lade_zeilen()
    assert erste == zweite
