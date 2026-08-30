"""C13 · Entscheide-Cache-Schreiber -- SQL-Form, DB gefaked (Muster test_befund_kacheln.py),
atomares Schreiben, CLI-Fehlerpfad."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import wache_cache
from .test_web import FakeLaufer


def test_sql_entscheide_filtert_zeitraum_und_status():
    sql = wache_cache.sql_entscheide(180)
    assert "180 days" in sql
    assert "'erledigt', 'obsolet'" in sql
    assert "quelle = 'gf'" in sql and "typ = 'befund_entscheid'" in sql


def test_baue_cache_liest_ueber_laufer(monkeypatch):
    eintraege = [{
        "signatur": "rework:tool:Bash", "sitzung_ref": None, "projekt_hash": "",
        "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00", "verankerung": None,
    }]
    monkeypatch.setattr(wache_cache, "LAUFER", FakeLaufer({"befund_entscheid": json.dumps(eintraege)}))
    jetzt = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    cache = wache_cache.baue_cache(jetzt)

    assert cache == {"stand": jetzt.isoformat(), "entscheide": eintraege}


def test_baue_cache_leere_antwort_wird_leere_liste(monkeypatch):
    monkeypatch.setattr(wache_cache, "LAUFER", FakeLaufer({}, default=""))
    cache = wache_cache.baue_cache()
    assert cache["entscheide"] == []


def test_schreibe_cache_atomar_kein_tmp_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(wache_cache, "LAUFER", FakeLaufer({"befund_entscheid": "[]"}))
    pfad = tmp_path / "wache-entscheide.json"

    wache_cache.schreibe_cache(pfad)

    assert pfad.exists()
    assert not pfad.with_suffix(".tmp").exists()
    assert json.loads(pfad.read_text(encoding="utf-8"))["entscheide"] == []


def test_schreibe_cache_ohne_pfad_nutzt_modul_konstante(tmp_path, monkeypatch):
    """`pfad=None` (Default) liest `CACHE_PFAD` ZUR AUFRUFZEIT -- Tests koennen die
    Modulkonstante monkeypatchen, ohne dass ein alter Funktions-Default sie ignoriert."""
    monkeypatch.setattr(wache_cache, "LAUFER", FakeLaufer({"befund_entscheid": "[]"}))
    monkeypatch.setattr(wache_cache, "CACHE_PFAD", tmp_path / "andere-datei.json")

    wache_cache.schreibe_cache()

    assert (tmp_path / "andere-datei.json").exists()


def test_befehl_wache_cache_meldet_db_fehler(monkeypatch, capsys):
    def wirft(sql, zeitlimit_s=8):
        raise wache_cache.SpeicherFehler("nicht erreichbar")

    monkeypatch.setattr(wache_cache, "LAUFER", wirft)
    exit_code = wache_cache.befehl_wache_cache(None)

    assert exit_code == 2
    assert "nicht geschrieben" in capsys.readouterr().out


def test_befehl_wache_cache_erfolg(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wache_cache, "LAUFER", FakeLaufer({"befund_entscheid": "[]"}))
    monkeypatch.setattr(wache_cache, "CACHE_PFAD", tmp_path / "wache-entscheide.json")

    exit_code = wache_cache.befehl_wache_cache(None)

    assert exit_code == 0
    assert "0 Entscheide" in capsys.readouterr().out
