"""Leser für Codex-CLI-Sitzungstranskripte (JSONL) -> modell.Beleg.

Quelle: ``~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl``. Jede Zeile ist
``{timestamp, type, payload}``. Format empirisch geprüft an echten Dateien
(codex-cli 0.147.0, Stand 2026-08-25).

Es werden NIE Inhalte übernommen: keine message-Texte, keine Werkzeug-Argumente,
keine Werkzeug-Ausgaben. Nur Typ, Zeit, Zahlen und kurze Verweise/Signaturen.

Format-Drift: unbekannte Zeilen-/Payload-Typen UND unbekannte Felder bekannter
Typen landen als Marker in ``erfassung.unbekannt`` (Wächter
``check-sitzungsbeleg-format.ps1`` meldet rot), nie ein Absturz.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import modell
from .redaktion import sicherer_bezeichner

# "Exit code: 0" / "Wall time: 0.2 seconds" — einzige auswertbaren Textmuster
# in function_call_output.output (Rest der Ausgabe wird nie gelesen).
_MUSTER_EXIT = re.compile(r"Exit code:\s*(-?\d+)")
_MUSTER_WALL = re.compile(r"Wall time:\s*([0-9.]+)\s*\w+")

# event_msg-Unterarten, die bewusst KEIN eigenes Ereignis erzeugen: sie sind
# redundant zu response_item (user_message/agent_message dupliziert die Runde,
# gleicher Zeitstempel) oder reine Rahmen-Marker ohne Zahlenwert.
_EVENT_MSG_OHNE_EREIGNIS = {
    "task_started", "task_complete", "user_message", "agent_message",
    "thread_settings_applied", "web_search_end",
}
_RESPONSE_ITEM_OHNE_EREIGNIS = {"web_search_call"}

# Bekannte Felder je Typ (Stand codex-cli 0.147.0). Neue Felder -> Marker "feld:<typ>.<name>".
_BEKANNTE_FELDER = {
    "": {"timestamp", "type", "payload"},
    "session_meta": {"base_instructions", "cli_version", "context_window", "cwd", "git", "history_mode",
                     "id", "model_provider", "originator", "session_id", "source", "thread_source",
                     "timestamp"},
    "turn_context": {"approval_policy", "approvals_reviewer", "collaboration_mode", "comp_hash",
                     "current_date", "cwd", "model", "multi_agent_version", "permission_profile",
                     "personality", "realtime_active", "sandbox_policy", "summary", "timezone",
                     "turn_id", "workspace_roots"},
    "response_item": {"arguments", "call_id", "content", "encrypted_content", "id",
                      "internal_chat_message_metadata_passthrough", "name", "output", "phase", "role",
                      "status", "summary", "type", "action"},
    "event_msg": {"info", "rate_limits", "type", "message", "phase", "memory_citation", "completed_at",
                  "duration_ms", "last_agent_message", "started_at", "time_to_first_token_ms", "turn_id",
                  "collaboration_mode_kind", "model_context_window", "thread_settings", "audio", "images",
                  "local_audio", "local_images", "text_elements", "action", "call_id", "query"},
}


def _signatur(name: str, fehlerklasse: str, exit_code: Optional[int]) -> str:
    """Kurzsignatur zur Gruppierung — nie Rohtext, nur Hash über Typ/Klasse/Code."""
    roh = f"{name}|{fehlerklasse}|{exit_code}"
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:12]


def _projekt_name(cwd: str) -> str:
    """Letzter Pfadbestandteil — cwd kommt mit Windows- oder Unix-Trennern."""
    teile = [t for t in re.split(r"[\\/]+", cwd) if t]
    return teile[-1] if teile else ""


def _git_wurzel_name(cwd: str) -> str:
    """Name des Git-Wurzelordners ab `cwd` aufwärts -- vereint Sitzungen aus
    Unterordnern/Clones desselben Repos (Alias-Grundlage, Sichtabnahme Block 1).
    Kein `.git` gefunden (Pfad existiert nicht mehr/kein Repo) -> Fallback letzter
    Pfadteil (bisheriges Verhalten)."""
    if cwd:
        try:
            start = Path(cwd)
            # Nur absolute Pfade aufwaerts pruefen: ein fremdes Pfadformat (Windows-cwd
            # unter Linux) wuerde sonst ueber "." im Arbeitsverzeichnis des Aufrufers landen.
            if start.is_absolute():
                for ordner in (start, *start.parents):
                    if ordner.name and (ordner / ".git").exists():
                        return ordner.name
        except OSError:
            pass
    return _projekt_name(cwd)


def _fehlerklasse_und_dauer(ausgabe: str) -> tuple[str, Optional[int], Optional[int]]:
    """Wertet NUR die beiden erlaubten Muster in einer Tool-Ausgabe aus.

    Liefert (fehlerklasse, exit_code, dauer_ms). Der restliche Ausgabetext wird
    nie gelesen/gespeichert — nur auf das Muster "timed out" geprüft.
    """
    exit_treffer = _MUSTER_EXIT.search(ausgabe)
    exit_code = int(exit_treffer.group(1)) if exit_treffer else None
    wall_treffer = _MUSTER_WALL.search(ausgabe)
    dauer_ms = round(float(wall_treffer.group(1)) * 1000) if wall_treffer else None
    if "timed out" in ausgabe:
        fehlerklasse = "timeout"
    elif exit_code is not None and exit_code != 0:
        fehlerklasse = "exit_nonzero"
    else:
        fehlerklasse = ""
    return fehlerklasse, exit_code, dauer_ms


def _token_aus_nutzung(nutzung: dict) -> modell.Token:
    return modell.Token(
        input=nutzung.get("input_tokens", 0) or 0,
        output=nutzung.get("output_tokens", 0) or 0,
        cache_write=nutzung.get("cache_write_input_tokens", 0) or 0,
        cache_read=nutzung.get("cached_input_tokens", 0) or 0,
        thinking=nutzung.get("reasoning_output_tokens", 0) or 0,
    )


@dataclass
class _Zustand:
    """Lesezustand über alle Zeilen (kein Inhalt, nur Zähler/Verweise)."""
    kopf: modell.Kopf
    erfassung: modell.Erfassung
    ereignisse: list = field(default_factory=list)
    unbekannt_gesehen: set = field(default_factory=set)
    offene_werkzeuge: dict = field(default_factory=dict)       # call_id -> Werkzeugname
    offene_tool_ereignisse: dict = field(default_factory=dict)  # call_id -> ART_TOOL-Ereignis
    letztes_assistent_ereignis: Optional[modell.Ereignis] = None
    aktuelles_modell: str = ""
    letztes_kontextfenster: Optional[int] = None
    erste_zeit: str = ""
    letzte_zeit: str = ""
    sah_token: bool = False
    defekte_zeilen: int = 0

    def merke_unbekannt(self, marker: str) -> None:
        if marker not in self.unbekannt_gesehen:
            self.unbekannt_gesehen.add(marker)
            self.erfassung.unbekannt.append(marker)

    def pruefe_felder(self, typ: str, obj: dict) -> None:
        """Unbekannte Felder eines bekannten Typs -> Marker (Format-Drift, kein Inhalt)."""
        bekannt = _BEKANNTE_FELDER.get(typ)
        if bekannt is None:
            return
        for feld_name in obj:
            if feld_name not in bekannt:
                self.merke_unbekannt(f"feld:{typ or 'zeile'}.{feld_name}")


def _session_meta(z: _Zustand, zeit: str, payload: dict) -> None:
    z.kopf.sitzung_id = payload.get("session_id") or payload.get("id") or ""
    cwd = payload.get("cwd", "") or ""
    z.kopf.projekt_hash = hashlib.sha256(cwd.encode("utf-8")).hexdigest()[:12]
    z.kopf.projekt_name = sicherer_bezeichner(_git_wurzel_name(cwd))  # C2: Allowlist, sonst Hash
    z.kopf.version = payload.get("cli_version", "") or ""


def _turn_context(z: _Zustand, zeit: str, payload: dict) -> None:
    modell_name = payload.get("model") or ""
    if modell_name:
        z.aktuelles_modell = modell_name
        if modell_name not in z.kopf.modelle:
            z.kopf.modelle.append(modell_name)


def _response_message(z: _Zustand, zeit: str, payload: dict) -> None:
    rolle = payload.get("role")
    if rolle == "user":
        z.ereignisse.append(modell.Ereignis(zeit=zeit, art=modell.ART_NUTZER))
    elif rolle == "assistant":
        neues = modell.Ereignis(zeit=zeit, art=modell.ART_ASSISTENT, name=z.aktuelles_modell)
        z.ereignisse.append(neues)
        z.letztes_assistent_ereignis = neues
    # rolle == "developer" (Systemvorgabe der Sitzung) -> kein Ereignis


def _function_call(z: _Zustand, zeit: str, payload: dict) -> None:
    name = sicherer_bezeichner(payload.get("name", "") or "")
    call_id = payload.get("call_id", "") or ""
    aufruf = modell.Ereignis(zeit=zeit, art=modell.ART_TOOL, name=name, ref=call_id)
    if call_id:
        z.offene_werkzeuge[call_id] = name
        z.offene_tool_ereignisse[call_id] = aufruf
    z.ereignisse.append(aufruf)


def _function_call_output(z: _Zustand, zeit: str, payload: dict) -> None:
    """Nur bei Fehler ein eigenes Ergebnis-Ereignis (F5); Erfolg = Wall-Time am ART_TOOL."""
    call_id = payload.get("call_id", "") or ""
    name = z.offene_werkzeuge.get(call_id, "")
    fehlerklasse, exit_code, dauer_ms = _fehlerklasse_und_dauer(payload.get("output", "") or "")
    if fehlerklasse:
        z.ereignisse.append(modell.Ereignis(
            zeit=zeit, art=modell.ART_TOOL_ERGEBNIS, name=name, fehler=True, dauer_ms=dauer_ms,
            ref=call_id, fehlerklasse=fehlerklasse, signatur=_signatur(name, fehlerklasse, exit_code),
        ))
        return
    aufruf = z.offene_tool_ereignisse.get(call_id)
    if aufruf is not None:
        aufruf.dauer_ms = dauer_ms


def _response_item(z: _Zustand, zeit: str, payload: dict) -> None:
    p_typ = payload.get("type")
    if p_typ == "message":
        _response_message(z, zeit, payload)
    elif p_typ == "function_call":
        _function_call(z, zeit, payload)
    elif p_typ == "function_call_output":
        _function_call_output(z, zeit, payload)
    elif p_typ == "reasoning":
        # encrypted_content -> Inhalt strukturell nicht lesbar, aber als Zeitpunkt zählbar.
        z.ereignisse.append(modell.Ereignis(zeit=zeit, art=modell.ART_SYSTEM, name="reasoning"))
    elif p_typ not in _RESPONSE_ITEM_OHNE_EREIGNIS:
        z.merke_unbekannt(f"response_item:{p_typ}")


def _token_count(z: _Zustand, zeit: str, payload: dict) -> None:
    z.sah_token = True
    info = payload.get("info") or {}
    fenster = info.get("model_context_window")
    if fenster is not None and fenster != z.letztes_kontextfenster:
        z.letztes_kontextfenster = fenster
        z.ereignisse.append(modell.Ereignis(
            zeit=zeit, art=modell.ART_SYSTEM, name="context_window", ref=str(fenster)))
    if z.letztes_assistent_ereignis is None:
        z.merke_unbekannt("token_count_ohne_assistent")
        return
    if z.letztes_assistent_ereignis.token is None:
        z.letztes_assistent_ereignis.token = modell.Token()
    z.letztes_assistent_ereignis.token.add(_token_aus_nutzung(info.get("last_token_usage") or {}))


def _event_msg(z: _Zustand, zeit: str, payload: dict) -> None:
    p_typ = payload.get("type")
    if p_typ == "token_count":
        _token_count(z, zeit, payload)
    elif p_typ not in _EVENT_MSG_OHNE_EREIGNIS:
        z.merke_unbekannt(f"event_msg:{p_typ}")


# world_state: Arbeitsbereichs-Schnappschuss (Inhalt), bewusst ohne Ereignis.
_TOPLEVEL_OHNE_EREIGNIS = {"world_state"}

_HANDLER = {
    "session_meta": _session_meta,
    "turn_context": _turn_context,
    "response_item": _response_item,
    "event_msg": _event_msg,
}


def _payload(z: _Zustand, eintrag: dict) -> Optional[dict]:
    """payload als Dict; fehlend -> {}; falscher Typ -> None (F8, gezählt)."""
    payload = eintrag.get("payload")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        z.merke_unbekannt(f"struktur:{type(payload).__name__}")
        return None
    return payload


def _verarbeite_zeile(z: _Zustand, eintrag: dict) -> None:
    zeit = eintrag.get("timestamp", "") or ""
    if zeit:
        z.erste_zeit = z.erste_zeit or zeit
        z.letzte_zeit = zeit
    typ = eintrag.get("type")
    z.pruefe_felder("", eintrag)
    payload = _payload(z, eintrag)
    if payload is None:
        return
    handler = _HANDLER.get(typ)
    if handler is None:
        if typ not in _TOPLEVEL_OHNE_EREIGNIS:
            z.merke_unbekannt(f"toplevel:{typ}")
        return
    z.pruefe_felder(typ, payload)
    handler(z, zeit, payload)


def _zeilen(pfad: str, z: _Zustand):
    """JSON-Zeilen; defekte werden gezählt, Nicht-Dicts als struktur:<typ> gemerkt (F8)."""
    with open(pfad, "r", encoding="utf-8") as datei:
        for roh_zeile in datei:
            roh_zeile = roh_zeile.strip()
            if not roh_zeile:
                continue
            try:
                eintrag = json.loads(roh_zeile)
            except json.JSONDecodeError:
                z.defekte_zeilen += 1
                continue
            if not isinstance(eintrag, dict):
                z.merke_unbekannt(f"struktur:{type(eintrag).__name__}")
                continue
            yield eintrag


def lese_sitzung(pfad: str, host: str = "") -> modell.Beleg:
    """Liest eine Codex-Rollout-JSONL-Datei zu einem Beleg (Kopf/Erfassung/Ereignisse).

    Subagenten bleiben leer (Codex-CLI kennt keine Subagenten-Hierarchie wie
    Claude Code); Kennzahlen bleiben leer (Verdichtung ist Aufgabe eines
    späteren Schritts). Defekte JSON-Zeilen werden übersprungen und gezählt,
    nie zum Abbruch.
    """
    z = _Zustand(
        kopf=modell.Kopf(quelle="codex", sitzung_id="", host=host),
        erfassung=modell.Erfassung(
            token="not_observed", dauer="partial", kosten="not_observed", inhalte="redacted",
            subagenten="not_recorded", compaction="not_recorded", reasoning="not_recorded",
        ),
    )
    for eintrag in _zeilen(pfad, z):
        _verarbeite_zeile(z, eintrag)

    z.kopf.start = z.erste_zeit
    z.kopf.ende = z.letzte_zeit or z.erste_zeit
    z.erfassung.token = "observed" if z.sah_token else "not_observed"
    if z.defekte_zeilen:
        z.merke_unbekannt(f"defekte_zeilen:{z.defekte_zeilen}")
    return modell.Beleg(kopf=z.kopf, erfassung=z.erfassung, ereignisse=z.ereignisse)
