"""C13 · Wache -- Warnung waehrend der Sitzung (Paket J, Maintainer 2026-08-28, CONTRACTS.md C13).

`PreToolUse`-Hook (`python -m sitzungsbeleg wache`): wendet `regeln.pruefe` auf das LAUFENDE
Transkript an und meldet neue/veraenderte Auffaelligkeiten (schwere warnung/hoch) als
`additionalContext`. Laeuft bei JEDEM Werkzeugaufruf -> harte Budgets: FAIL-OPEN (jeder Fehler
-> Exit 0, kein Absturz der Sitzung), kein DB-Zugriff, kein Netz, kein Modellaufruf. Fehler
gehen NUR ins rotierende Log `_work_sitzungsbeleg/wache.log` (<= 1 MB).

Eigenstaendiges Modul (Konfliktvermeidung mit den parallelen Arbeitspaketen C11/C12/Layout):
liest nur bestehende Bausteine (leser_claude, kennzahlen, regeln, regeltexte), schreibt nie in
die DB, kennt den Entscheide-Cache (wache_cache.py) nur lesend.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import kennzahlen, leser_claude, regeln, regeltexte

PAKET_ORDNER = Path(__file__).resolve().parent
WORK_ORDNER = PAKET_ORDNER.parent / "_work_sitzungsbeleg"
WACHE_JSON_PFAD = PAKET_ORDNER / "wache.json"
MODELLE_PFAD = PAKET_ORDNER.parent / "modelle.json"
CACHE_PFAD = WORK_ORDNER / "wache-entscheide.json"
ZUSTAND_ORDNER = WORK_ORDNER / "wache-zustand"
LOG_PFAD = WORK_ORDNER / "wache.log"
LOG_MAX_BYTES = 1_000_000
# Meldungsspur (C13-Nachtrag, Entscheid 2026-08-28 14:30): jede AUSGEGEBENE Meldung (warnen
# UND fragen) haengt als eine JSON-Zeile hier an -- Grundlage fuer wache_web.py (Start-Kachel +
# Sitzungs-Verlauf-Marke). Nie Rohtext, nur Regeltitel/Wert/Pfad (wie die Hook-Ausgabe selbst).
SPOOL_PFAD = WORK_ORDNER / "wache-meldungen.jsonl"

STANDARD_KONFIG = {
    "schema": 1, "standard": "warnen",
    "regeln": {"rework:tool": "fragen"},
    "mindest_werkzeugaufrufe": 10, "mindest_sekunden": 60,
}

# Austauschbar fuer Tests (wache.LESER = lambda pfad: beleg), wie speicher.LAUFER.
LESER = leser_claude.lese_sitzung


def _log(nachricht: str) -> None:
    """Rotierendes Log (<= 1 MB, einfaches Leeren statt Generationen -- Fehler duerfen den
    Hook nie stoeren, darum selbst fail-open)."""
    try:
        LOG_PFAD.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PFAD.exists() and LOG_PFAD.stat().st_size > LOG_MAX_BYTES:
            LOG_PFAD.write_text("", encoding="utf-8")
        with open(LOG_PFAD, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {nachricht}\n")
    except OSError:
        pass


def _lade_preise() -> dict:
    """Preise aus `scripts/modelle.json` wie der Stop-Hook -- ein Aufruf = ein Prozess,
    darum hier bewusst kein Modul-weiter Cache (Datei ist klein, ein Read je Prozess reicht)."""
    if not MODELLE_PFAD.exists():
        return {}
    with open(MODELLE_PFAD, encoding="utf-8") as f:
        daten = json.load(f)
    modelle = daten.get("preise", {}).get("modelle", {})
    return {name: satz for name, satz in modelle.items() if "input" in satz or "output" in satz}


def _pruefe_unbekannte_regeln(konfig: dict) -> None:
    bekannt = set(regeltexte.REGELTEXTE)
    for schluessel in konfig.get("regeln", {}):
        if schluessel not in bekannt:
            _log(f"konfiguration: unbekannte Regel {schluessel!r} -- ignoriert")


def _lade_konfiguration() -> dict:
    """`wache.json` (Paketordner) -- fehlt/kaputt -> Standardkonfiguration + Logzeile."""
    try:
        konfig = json.loads(WACHE_JSON_PFAD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fehler:
        _log(f"konfiguration: {type(fehler).__name__} -- Standardkonfiguration")
        return dict(STANDARD_KONFIG)
    _pruefe_unbekannte_regeln(konfig)
    return konfig


def _lade_cache() -> list[dict]:
    """Entscheide-Cache (wache_cache.py) -- fehlt/kaputt: leere Liste, die Wache meldet dann
    ohne Entscheid-Bezug (C13: "fehlt er, meldet die Wache Regeln ohne Entscheid-Bezug")."""
    try:
        daten = json.loads(CACHE_PFAD.read_text(encoding="utf-8"))
        return daten.get("entscheide", []) if isinstance(daten, dict) else []
    except (OSError, json.JSONDecodeError):
        return []


def _zustand_pfad(session_id: str) -> Path:
    sicher = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unbekannt"
    return ZUSTAND_ORDNER / f"{sicher}.json"


def _lade_zustand(session_id: str, jetzt: datetime) -> dict:
    """Fehlt die Datei (neue Sitzung) oder ist sie kaputt: frischer Zustand, `zuletzt` als
    Anker auf JETZT (sonst wuerde die Zeit-Drossel beim allerersten Aufruf sofort greifen)."""
    try:
        return json.loads(_zustand_pfad(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"groesse": 0, "zuletzt": jetzt.isoformat(), "aufrufe_seit_auswertung": 0, "gemeldet": {}}


def _speichere_zustand(session_id: str, zustand: dict) -> None:
    pfad = _zustand_pfad(session_id)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(zustand, ensure_ascii=False), encoding="utf-8")


def _dateigroesse(pfad: str) -> int:
    try:
        return Path(pfad).stat().st_size
    except OSError:
        return 0


def _sekunden_seit(zuletzt_iso: str | None, jetzt: datetime) -> float:
    if not zuletzt_iso:
        return 0.0
    try:
        return (jetzt - datetime.fromisoformat(zuletzt_iso)).total_seconds()
    except ValueError:
        return 0.0


def _schwelle_erreicht(zustand: dict, konfig: dict, groesse: int, jetzt: datetime) -> bool:
    """C13 Punkt 2: nur auswerten, wenn >= N Aufrufe ODER >= M Sekunden seit der letzten
    Auswertung vergangen sind UND das Transkript seither gewachsen ist."""
    if groesse <= zustand.get("groesse", 0):
        return False
    aufrufe_ok = zustand.get("aufrufe_seit_auswertung", 0) >= konfig["mindest_werkzeugaufrufe"]
    zeit_ok = _sekunden_seit(zustand.get("zuletzt"), jetzt) >= konfig["mindest_sekunden"]
    return aufrufe_ok or zeit_ok


def _beleg_lesen(transcript_path: str, preise: dict):
    beleg = LESER(transcript_path)
    kennzahlen.berechne(beleg, preise or None)
    regeln.pruefe(beleg, preise or None)
    return beleg


def _relevante_auffaelligkeiten(beleg, konfig: dict) -> list[tuple]:
    """Auffaelligkeiten mit schwere warnung/hoch UND Stufe != aus -- Liste (Auffaelligkeit, stufe)."""
    regeln_konfig = konfig.get("regeln", {})
    standard = konfig.get("standard", "warnen")
    treffer = []
    for a in beleg.auffaelligkeiten:
        if a.schwere not in ("warnung", "hoch"):
            continue
        stufe = regeln_konfig.get(a.regel, standard)
        if stufe != "aus":
            treffer.append((a, stufe))
    return treffer


def _juengster_erledigt(signatur: str, projekt_hash: str, cache: list[dict]) -> dict | None:
    """Juengster `erledigt`-Entscheid dieser Signatur, global (sitzung_ref None) oder mit
    gleichem Projekt-Hash -- `obsolet`/andere Signaturen zaehlen hier bewusst nicht (C13 Punkt 4)."""
    passend = [
        e for e in cache
        if e.get("signatur") == signatur and e.get("status") == "erledigt"
        and (e.get("sitzung_ref") is None or (projekt_hash and e.get("projekt_hash") == projekt_hash))
    ]
    return max(passend, key=lambda e: str(e.get("entschieden_am", ""))) if passend else None


def _entscheid_zeile(entscheid: dict) -> str:
    datum = str(entscheid.get("entschieden_am", ""))[:10]
    verankerung = entscheid.get("verankerung")
    if verankerung:
        return (f"Entschieden am {datum}: siehe {verankerung.get('art', '')} "
                f"{verankerung.get('pfad', '')} ({verankerung.get('abschnitt', '')}).")
    return f"Entschieden am {datum} ohne Verankerung — bitte nachziehen (C11)."


def _meldungszeile(auffaelligkeit, entscheid: dict | None) -> str:
    basis = f"Wache: {regeltexte.text_fuer(auffaelligkeit.regel)['titel']} — {auffaelligkeit.wert}."
    return basis if entscheid is None else f"{basis} {_entscheid_zeile(entscheid)}"


def _baue_meldungen(relevante: list[tuple], gemeldet: dict, cache: list[dict], projekt_hash: str) -> tuple[list[dict], dict]:
    """(eintraege, neu_gemeldet) -- ueberspringt (signatur,wert)-Paare, die schon mit demselben
    Wert gemeldet wurden; ein NEUER Wert derselben Signatur meldet erneut. Jeder Eintrag traegt
    alles, was Hook-Ausgabe UND Meldungsspur brauchen (signatur/stufe/wert/verankerung/text)."""
    eintraege, neu = [], {}
    for a, stufe in relevante:
        if gemeldet.get(a.signatur) == a.wert:
            continue
        entscheid = _juengster_erledigt(a.signatur, projekt_hash, cache)
        eintraege.append({
            "signatur": a.signatur, "stufe": stufe, "wert": a.wert,
            "verankerung": (entscheid or {}).get("verankerung"),
            "text": _meldungszeile(a, entscheid),
        })
        neu[a.signatur] = a.wert
    return eintraege, neu


def _hook_ausgabe(eintraege: list[dict]) -> dict:
    zeilen = [e["text"] for e in eintraege]
    ausgabe = {"hookEventName": "PreToolUse", "additionalContext": "\n".join(zeilen)}
    if any(e["stufe"] == "fragen" for e in eintraege):
        ausgabe["permissionDecision"] = "ask"
        ausgabe["permissionDecisionReason"] = zeilen[0]
    return {"hookSpecificOutput": ausgabe}


def _spoolzeile(session_id: str, projekt_hash: str, jetzt: datetime, eintrag: dict) -> dict:
    return {
        "zeit": jetzt.isoformat(), "session_id": session_id, "projekt_hash": projekt_hash,
        "signatur": eintrag["signatur"], "stufe": eintrag["stufe"], "wert": eintrag["wert"],
        "verankerung": eintrag["verankerung"], "text": eintrag["text"],
    }


def _spool_schreiben(session_id: str, projekt_hash: str, eintraege: list[dict], jetzt: datetime) -> None:
    """Meldungsspur (C13-Nachtrag): eine JSON-Zeile je AUSGEGEBENER Meldung -- fail-open wie
    `_log`, eine kaputte Spool-Datei darf den Hook nie stoeren."""
    try:
        SPOOL_PFAD.parent.mkdir(parents=True, exist_ok=True)
        with open(SPOOL_PFAD, "a", encoding="utf-8") as f:
            for e in eintraege:
                f.write(json.dumps(_spoolzeile(session_id, projekt_hash, jetzt, e), ensure_ascii=False) + "\n")
    except OSError as fehler:
        _log(f"spool: {type(fehler).__name__}: {str(fehler)[:200]}")


def _auswerten(transcript_path: str, session_id: str, konfig: dict, zustand: dict, jetzt: datetime) -> dict | None:
    """Fuellt `zustand` in place (Erfolg = neuer Stand); wirft bei Lese-/Regelfehlern --
    der Aufrufer faengt das fail-open ab."""
    beleg = _beleg_lesen(transcript_path, _lade_preise())
    relevante = _relevante_auffaelligkeiten(beleg, konfig)
    cache = _lade_cache()
    eintraege, neu = _baue_meldungen(relevante, zustand.get("gemeldet", {}), cache, beleg.kopf.projekt_hash)
    zustand["gemeldet"] = {**zustand.get("gemeldet", {}), **neu}
    zustand["groesse"] = _dateigroesse(transcript_path)
    zustand["zuletzt"] = jetzt.isoformat()
    zustand["aufrufe_seit_auswertung"] = 0
    if not eintraege:
        return None
    _spool_schreiben(session_id, beleg.kopf.projekt_hash, eintraege, jetzt)
    return _hook_ausgabe(eintraege)


def _auswerten_fail_open(transcript_path: str, session_id: str, konfig: dict, zustand: dict, jetzt: datetime) -> dict | None:
    try:
        return _auswerten(transcript_path, session_id, konfig, zustand, jetzt)
    except Exception as fehler:  # Auswertung darf die Sitzung nie stoeren (C13)
        _log(f"auswertung: {type(fehler).__name__}: {str(fehler)[:200]}")
        zustand["zuletzt"] = jetzt.isoformat()
        return None


def wache_pruefen(daten: dict, sofort: bool = False, jetzt: datetime | None = None) -> dict | None:
    """C13-Ablauf je PreToolUse-Aufruf. `sofort=True` (Flag/Env) umgeht NUR die Drossel
    (Testhilfe/Live-Probe) -- Zustand/Cache/Konfiguration bleiben unveraendert ausgewertet."""
    jetzt = jetzt or datetime.now(timezone.utc)
    session_id = str(daten.get("session_id") or "")
    transcript_path = str(daten.get("transcript_path") or "")
    if not session_id or not transcript_path:
        return None
    konfig = _lade_konfiguration()
    zustand = _lade_zustand(session_id, jetzt)
    zustand["aufrufe_seit_auswertung"] = zustand.get("aufrufe_seit_auswertung", 0) + 1
    groesse = _dateigroesse(transcript_path)
    if not sofort and not _schwelle_erreicht(zustand, konfig, groesse, jetzt):
        _speichere_zustand(session_id, zustand)
        return None
    ausgabe = _auswerten_fail_open(transcript_path, session_id, konfig, zustand, jetzt)
    _speichere_zustand(session_id, zustand)
    return ausgabe


def befehl_wache(args) -> int:
    """CLI `wache`: stdin-JSON (PreToolUse: session_id, transcript_path, ...), IMMER Exit 0
    (fail-open, C13) -- ``--sofort``/``SITZUNGSBELEG_WACHE_SOFORT=1`` fuer Live-Probe/Tests."""
    sofort = bool(getattr(args, "sofort", False)) or os.environ.get("SITZUNGSBELEG_WACHE_SOFORT") == "1"
    try:
        daten = json.load(sys.stdin)
        ausgabe = wache_pruefen(daten, sofort=sofort)
        if ausgabe is not None:
            print(json.dumps(ausgabe, ensure_ascii=False))
    except Exception as fehler:  # der Hook darf die Sitzung nie stoeren
        _log(f"hook: {type(fehler).__name__}: {str(fehler)[:200]}")
    return 0
