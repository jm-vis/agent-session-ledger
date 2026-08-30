"""Rohdatei-Ausschnitt (Phase 3 H, CONTRACTS.md C5): letzter, lokaler Blick in die
Original-Transkriptdatei -- fluechtig, redigiert, nie gespeichert.

NUR lesend. Dieses Modul ruft NIE `speicher.*` auf (kein Schreibweg, Test
`test_kein_schreibweg_ueber_speicher`) und schreibt NIE Rohtext in ein Log (kein `print`/
`logging` hier ueberhaupt). Jede Zeile laeuft VOR der Rueckgabe durch
`redaktion.bereinige_text()` -- Secrets/Pfade/E-Mail/Schutzordner-Token werden dort erkannt.

Fensterzentrierung ueber die Zeit, nicht den Ereignis-Index (Abweichung, siehe CONTRACTS.md
Aenderungstabelle): `dokument.ereignisse[position]` ist ein Index in die vom Leser bereits
verdichtete Ereignisliste, nicht in die Rohdatei -- nicht jede Rohzeile wird dort zu einem
Ereignis (Meta-/Formatzeilen werden gefiltert). `Ereignis.zeit` ist dagegen wortgleich aus dem
`timestamp`-Feld der Quellzeile uebernommen (beide Leser), darum sucht `_ziel_index` die naechste
Rohzeile mit passendem Zeitstempel. Ohne Zeit (z. B. `position` ausserhalb der Ereignisliste)
faellt die Funktion auf `position` als rohen Zeilenindex zurueck.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import redaktion
from .contracts import MAX_TEXT

MAX_UMFANG = 50
DEFAULT_UMFANG = 5
WARNUNG = "Flüchtig, redigiert, nie gespeichert."


class RohdateiFehler(Exception):
    """Sitzung/Transkript nicht auffindbar -- der Aufrufer (web.py) macht daraus ein 404."""


def _finde_transkript(quelle: str, sitzung_id: str) -> Path:
    from .__main__ import _finde_sitzung  # spaeter Import: vermeidet Zirkularitaet (wie web.py)

    try:
        return _finde_sitzung(quelle, sitzung_id)
    except FileNotFoundError as fehler:
        raise RohdateiFehler("Transkript nicht mehr vorhanden") from fehler


def _pfad_anzeige(pfad: Path) -> str:
    """`~` statt Nutzerverzeichnis, immer Vorwaertsschraegstriche (plattformneutrale Anzeige)."""
    text = str(pfad)
    heim = str(Path.home())
    if text.startswith(heim):
        text = "~" + text[len(heim):]
    return text.replace("\\", "/")


def _rohzeilen(pfad: Path) -> list[dict]:
    """Kaputte/leere Zeilen werden zu `{}`, damit der Zeilenindex stabil bleibt."""
    zeilen = []
    for roh in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
        roh = roh.strip()
        if not roh:
            continue
        try:
            zeilen.append(json.loads(roh))
        except json.JSONDecodeError:
            zeilen.append({})
    return zeilen


def _tool_result_text(inhalt) -> str:
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        return " ".join(str(t.get("text", "")) for t in inhalt if isinstance(t, dict))
    return ""


def _claude_block_text(block: dict) -> str:
    art = block.get("type", "")
    if art == "text":
        return str(block.get("text", ""))
    if art == "thinking":
        return "[thinking] " + str(block.get("thinking", ""))
    if art == "tool_use":
        eingabe = json.dumps(block.get("input", {}), ensure_ascii=False, default=str)
        return "[tool_use:" + str(block.get("name", "")) + "] " + eingabe
    if art == "tool_result":
        return "[tool_result] " + _tool_result_text(block.get("content"))
    return "[" + str(art) + "]" if art else ""


def _typ_claude(obj: dict) -> str:
    return str(obj.get("type") or "unbekannt")


def _text_claude(obj: dict) -> str:
    if obj.get("type") == "system":
        return str(obj.get("content", "") or "")
    inhalt = (obj.get("message") or {}).get("content")
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        return " | ".join(_claude_block_text(b) for b in inhalt if isinstance(b, dict))
    return ""


def _typ_codex(obj: dict) -> str:
    basis = str(obj.get("type") or "unbekannt")
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    unter = payload.get("type")
    return f"{basis}:{unter}" if unter else basis


def _funktion_ausgabe_text(wert) -> str:
    if isinstance(wert, str):
        return wert
    return json.dumps(wert, ensure_ascii=False, default=str)


def _text_codex(obj: dict) -> str:
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    art = payload.get("type")
    if art == "message":
        return _tool_result_text(payload.get("content")) or str(payload.get("content", "") or "")
    if art == "function_call":
        args = json.dumps(payload.get("arguments", ""), ensure_ascii=False, default=str)
        return "[tool_call:" + str(payload.get("name", "")) + "] " + args
    if art == "function_call_output":
        return "[tool_output] " + _funktion_ausgabe_text(payload.get("output"))
    if art == "reasoning":
        return "[reasoning] " + json.dumps(payload.get("summary", ""), ensure_ascii=False, default=str)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _zeile_verdichten(quelle: str, obj: dict, index: int) -> dict:
    if quelle == "claude":
        typ, text = _typ_claude(obj), _text_claude(obj)
    else:
        typ, text = _typ_codex(obj), _text_codex(obj)
    text = redaktion.bereinige_text((text or "")[:MAX_TEXT])
    return {"index": index, "typ": typ, "text": text}


def _ziel_index(rohzeilen: list[dict], zeit: str | None, position: int) -> int:
    if not rohzeilen:
        return 0
    if not zeit:
        return max(0, min(position, len(rohzeilen) - 1))
    kandidat = None
    for i, obj in enumerate(rohzeilen):
        zeitwert = obj.get("timestamp", "")
        if zeitwert and zeitwert >= zeit:
            return i
        if zeitwert:
            kandidat = i
    return kandidat if kandidat is not None else len(rohzeilen) - 1


def _cwd_aus_zeilen(quelle: str, rohzeilen: list[dict]) -> str:
    for obj in rohzeilen:
        if quelle == "claude":
            cwd = obj.get("cwd")
        else:
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            cwd = payload.get("cwd")
        if cwd:
            return str(cwd)
    return ""


def cwd_aus_transkript(quelle: str, sitzung_id: str) -> str:
    """Liest den rohen Arbeitsordner (`cwd`) aus der ersten Zeile, die ihn traegt -- nur fuer
    `commits.py` (Phase 3 I, C10): dieser Pfad verlaesst den Prozess NIE, er geht nur als `cwd=`
    an einen lokalen `git`-Aufruf. Kein Transkript -> leerer String (kein Fehler)."""
    try:
        pfad = _finde_transkript(quelle, sitzung_id)
    except RohdateiFehler:
        return ""
    return _cwd_aus_zeilen(quelle, _rohzeilen(pfad))


def zeile_bei(quelle: str, sitzung_id: str, zeit: str | None, position: int) -> dict | None:
    """Eine einzelne, bereits redigierte Rohzeile ohne Fenster (Paket K, Tiefenanalyse-
    Fehlertexte, Entscheid 2026-08-28) -- gleiche Zielsuche wie `baue_antwort` (`_ziel_index`),
    aber nur EIN Treffer statt eines Fensters (dort wird um `position` je Werkzeugfehler gesucht,
    nicht um EINEN Befund). `None` bei leerer Rohdatei; `RohdateiFehler`, wenn das Transkript
    selbst fehlt (wie `baue_antwort`) -- der Aufrufer faengt das ab (Fail-open, nicht 404)."""
    pfad = _finde_transkript(quelle, sitzung_id)
    rohzeilen = _rohzeilen(pfad)
    if not rohzeilen:
        return None
    ziel = _ziel_index(rohzeilen, zeit, position)
    return _zeile_verdichten(quelle, rohzeilen[ziel], ziel)


def baue_antwort(quelle: str, sitzung_id: str, zeit: str | None, position: int, umfang: int) -> dict:
    """C5 GET /api/rohdatei/{sitzung_logisch}. `position` ist der `ereignis_index` aus dem
    Aufruf (Anzeige/Echo); `zeit` (aus `dokument.ereignisse[position]['zeit']`, falls vorhanden)
    zentriert das Fenster in der Rohdatei -- siehe Moduldoc."""
    umfang = max(1, min(umfang, MAX_UMFANG))
    pfad = _finde_transkript(quelle, sitzung_id)
    rohzeilen = _rohzeilen(pfad)
    ziel = _ziel_index(rohzeilen, zeit, position)
    start, ende = max(0, ziel - umfang), min(len(rohzeilen), ziel + umfang + 1)
    zeilen = [_zeile_verdichten(quelle, rohzeilen[i], i) for i in range(start, ende)]
    return {
        "pfad_anzeige": _pfad_anzeige(pfad), "position": position, "umfang": umfang,
        "zeilen": zeilen, "redaktion_version": redaktion.REDAKTION_VERSION, "warnung": WARNUNG,
    }
