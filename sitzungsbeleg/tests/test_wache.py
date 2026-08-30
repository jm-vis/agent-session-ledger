"""C13 · Wache -- Warnung waehrend der Sitzung (Drossel, Meldungen, Cache-Bezug, fail-open,
Laufzeit; siehe CONTRACTS.md C13 + Nachtrag Meldungsspur 2026-08-28 14:30)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from .. import wache
from ..modell import Auffaelligkeit, Kopf
from .hilfen import baue_beleg

FIXTURE = Path(__file__).parent / "fixtures" / "claude" / "d6e0c778-0fa7-40a7-a1cb-df93c23ecd42.jsonl"


def _beleg(auffaelligkeiten=None, projekt_hash="ph1"):
    beleg = baue_beleg(kopf=Kopf(quelle="claude", sitzung_id="s1", projekt_hash=projekt_hash))
    beleg.auffaelligkeiten = auffaelligkeiten or []
    return beleg


def _auff(regel="rework:tool", signatur="rework:tool:Bash", wert="4", schwere="warnung"):
    return Auffaelligkeit(regel=regel, schwere=schwere, signatur=signatur, wert=wert)


@pytest.fixture(autouse=True)
def _isoliert(tmp_path, monkeypatch):
    """Jede Pfad-Konstante zeigt in ein frisches tempdir -- Tests duerfen sich nie gegenseitig
    ueber den echten `_work_sitzungsbeleg`-Ordner beeinflussen."""
    monkeypatch.setattr(wache, "WACHE_JSON_PFAD", tmp_path / "wache.json")
    monkeypatch.setattr(wache, "CACHE_PFAD", tmp_path / "wache-entscheide.json")
    monkeypatch.setattr(wache, "ZUSTAND_ORDNER", tmp_path / "wache-zustand")
    monkeypatch.setattr(wache, "LOG_PFAD", tmp_path / "wache.log")
    monkeypatch.setattr(wache, "SPOOL_PFAD", tmp_path / "wache-meldungen.jsonl")
    monkeypatch.setattr(wache, "MODELLE_PFAD", tmp_path / "modelle.json")  # fehlt -> leere Preise
    wache.WACHE_JSON_PFAD.write_text(json.dumps(wache.STANDARD_KONFIG), encoding="utf-8")
    return tmp_path


def _transkript(tmp_path, inhalt: str = "x") -> str:
    pfad = tmp_path / "sitzung.jsonl"
    pfad.write_text(inhalt, encoding="utf-8")
    return str(pfad)


def test_drossel_kein_lauf_unter_10_aufrufen_oder_60s(tmp_path, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: aufrufe.append(1) or _beleg())
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}
    for _ in range(9):
        assert wache.wache_pruefen(daten) is None
    assert aufrufe == []  # unter der Schwelle wurde nie ausgewertet
    wache.wache_pruefen(daten)  # 10. Aufruf: Schwelle erreicht (>= mindest_werkzeugaufrufe)
    assert aufrufe == [1]  # jetzt wurde tatsaechlich ausgewertet (kein Treffer -> Ausgabe None)


def test_erstmeldung_keine_wiederholung_neuer_wert_meldet_erneut(tmp_path, monkeypatch):
    beleg = _beleg([_auff(regel="tool:error_rate", signatur="tool:error_rate", wert="25.0 %")])
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: beleg)
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}

    erste = wache.wache_pruefen(daten, sofort=True)
    assert erste is not None
    assert "Hohe Fehlerquote" in erste["hookSpecificOutput"]["additionalContext"]

    assert wache.wache_pruefen(daten, sofort=True) is None  # gleicher Wert -> keine Wiederholung

    beleg.auffaelligkeiten[0].wert = "40.0 %"
    dritte = wache.wache_pruefen(daten, sofort=True)
    assert dritte is not None
    assert "40.0 %" in dritte["hookSpecificOutput"]["additionalContext"]


def test_verankerungszeile_bei_juengstem_erledigt_entscheid(tmp_path, monkeypatch):
    cache = {"stand": "x", "entscheide": [{
        "signatur": "rework:tool:Bash", "sitzung_ref": None, "projekt_hash": "",
        "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00",
        "verankerung": {"art": "troubleshooting", "pfad": "TROUBLESHOOTING.md", "abschnitt": "Bash-Fehler"},
    }]}
    wache.CACHE_PFAD.write_text(json.dumps(cache), encoding="utf-8")
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: _beleg([_auff()]))
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}

    ausgabe = wache.wache_pruefen(daten, sofort=True)
    text = ausgabe["hookSpecificOutput"]["additionalContext"]
    assert "Entschieden am 2026-08-20: siehe troubleshooting TROUBLESHOOTING.md (Bash-Fehler)." in text


def test_legacy_zeile_ohne_verankerung(tmp_path, monkeypatch):
    cache = {"stand": "x", "entscheide": [{
        "signatur": "rework:tool:Bash", "sitzung_ref": None, "projekt_hash": "",
        "status": "erledigt", "entschieden_am": "2026-08-20T10:00:00+00:00", "verankerung": None,
    }]}
    wache.CACHE_PFAD.write_text(json.dumps(cache), encoding="utf-8")
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: _beleg([_auff()]))
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}

    ausgabe = wache.wache_pruefen(daten, sofort=True)
    text = ausgabe["hookSpecificOutput"]["additionalContext"]
    assert "Entschieden am 2026-08-20 ohne Verankerung — bitte nachziehen (C11)." in text


def test_stufe_fragen_setzt_permission_decision_ask(tmp_path, monkeypatch):
    # Standardkonfig: rework:tool -> fragen (wache.json C13-Nachtrag).
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: _beleg([_auff()]))
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}
    ausgabe = wache.wache_pruefen(daten, sofort=True)
    hso = ausgabe["hookSpecificOutput"]
    assert hso["permissionDecision"] == "ask"
    assert hso["permissionDecisionReason"] == hso["additionalContext"].splitlines()[0]


def test_stufe_aus_meldet_nichts(tmp_path, monkeypatch):
    wache.WACHE_JSON_PFAD.write_text(json.dumps({
        "schema": 1, "standard": "warnen", "regeln": {"tool:error_rate": "aus"},
        "mindest_werkzeugaufrufe": 10, "mindest_sekunden": 60,
    }), encoding="utf-8")
    beleg = _beleg([_auff(regel="tool:error_rate", signatur="tool:error_rate", wert="25 %")])
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: beleg)
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}
    assert wache.wache_pruefen(daten, sofort=True) is None


def test_hinweis_schwere_wird_nie_gemeldet(tmp_path, monkeypatch):
    beleg = _beleg([_auff(regel="subagent:overdelegation", signatur="subagent:overdelegation",
                           wert="30 Subagenten", schwere="hinweis")])
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: beleg)
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}
    assert wache.wache_pruefen(daten, sofort=True) is None


def test_fail_open_kaputtes_transkript(tmp_path):
    daten = {"session_id": "s1", "transcript_path": str(tmp_path / "fehlt-nicht-vorhanden.jsonl")}
    assert wache.wache_pruefen(daten, sofort=True) is None
    assert wache.LOG_PFAD.exists()
    assert "auswertung" in wache.LOG_PFAD.read_text(encoding="utf-8")


def test_fail_open_kaputte_konfiguration(tmp_path):
    wache.WACHE_JSON_PFAD.write_text("{kaputt", encoding="utf-8")
    konfig = wache._lade_konfiguration()
    assert konfig == wache.STANDARD_KONFIG
    assert "Standardkonfiguration" in wache.LOG_PFAD.read_text(encoding="utf-8")


def test_fehlender_cache_meldet_ohne_entscheid_bezug(tmp_path, monkeypatch):
    assert not wache.CACHE_PFAD.exists()
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: _beleg([_auff()]))
    daten = {"session_id": "s1", "transcript_path": _transkript(tmp_path)}
    ausgabe = wache.wache_pruefen(daten, sofort=True)
    text = ausgabe["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("Wache: Werkzeug-Nacharbeit — 4.")
    assert "Entschieden" not in text


def test_unbekannte_regel_in_konfiguration_loggt_warnung(tmp_path):
    wache.WACHE_JSON_PFAD.write_text(json.dumps({
        "schema": 1, "standard": "warnen", "regeln": {"nicht:vorhanden": "warnen"},
        "mindest_werkzeugaufrufe": 10, "mindest_sekunden": 60,
    }), encoding="utf-8")
    wache._lade_konfiguration()
    assert "unbekannte Regel" in wache.LOG_PFAD.read_text(encoding="utf-8")


def test_spool_schreibt_eine_zeile_je_ausgegebener_meldung(tmp_path, monkeypatch):
    monkeypatch.setattr(wache, "_beleg_lesen", lambda pfad, preise: _beleg([_auff()], projekt_hash="ph9"))
    daten = {"session_id": "s7", "transcript_path": _transkript(tmp_path)}
    wache.wache_pruefen(daten, sofort=True)
    zeilen = wache.SPOOL_PFAD.read_text(encoding="utf-8").splitlines()
    assert len(zeilen) == 1
    eintrag = json.loads(zeilen[0])
    assert eintrag["signatur"] == "rework:tool:Bash"
    assert eintrag["stufe"] == "fragen"
    assert eintrag["session_id"] == "s7"
    assert eintrag["projekt_hash"] == "ph9"
    assert eintrag["text"].startswith("Wache:")
    assert eintrag["verankerung"] is None


def test_laufzeit_unter_300ms_auf_dem_fixture_transkript():
    assert FIXTURE.exists(), "Fixture-Transkript fehlt -- siehe tests/fixtures/claude"
    daten = {"session_id": "laufzeit-test", "transcript_path": str(FIXTURE)}
    start = time.perf_counter()
    wache.wache_pruefen(daten, sofort=True)
    dauer_ms = (time.perf_counter() - start) * 1000
    assert dauer_ms < 300, f"Auswertung brauchte {dauer_ms:.1f} ms"
