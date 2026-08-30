"""Leser für Claude-Code-Sitzungstranskripte (JSONL) -> modell.Beleg.

Quelle: ``~/.claude/projects/<cwd-kodiert>/<session>.jsonl`` (Hauptsitzung) plus
``~/.claude/projects/<cwd-kodiert>/<session>/subagents/agent-<id>.jsonl`` +
``agent-<id>.meta.json`` je Subagent. Format an der echten Referenzsitzung
verifiziert (2026-08-25, ``d6e0c778-...``); Stichprobenbefehle siehe HANDOFF
dieser Aufgabe. Kein Inhalt (text/thinking/input/Fehlertext) wird übernommen —
Textfelder werden ausschließlich für kurze, zustandslose Muster-Prüfungen
gelesen (z. B. "beginnt mit 'Blocked'") und danach verworfen.

Format-Notizen (Stand 2026-08-25, Format driftet — daher ``erfassung.unbekannt``):
  - Bekannte ``type``-Werte in dieser Implementierung: user, assistant, system,
    attachment, mode. Alles andere (in der Praxis u. a. permission-mode,
    atis-latch, bridge-session, file-history-snapshot, last-prompt, ai-title,
    queue-operation, file-history-delta, agent-name) landet in
    ``erfassung.unbekannt`` — wird gezählt, nie verworfen als Fehler.
  - Eine "echte Nutzer-Runde" ist eine ``user``-Zeile, deren
    ``message.content`` NICHT ausschließlich aus tool_result-Blöcken besteht
    (String-Inhalt zählt als Runde, wenn nicht leer), UND die nicht
    ``isMeta`` ist (System-Caveats), UND deren Text nicht mit
    ``<task-notification`` beginnt (asynchrone Fork-/Subagent-Fertigmeldungen
    sind kein Nutzer-Prompt). Eine Compaction-Fortsetzungszeile
    (``isCompactSummary: true``, Text "This session is being continued
    from...") ZÄHLT als Runde — sie eröffnet real einen neuen Gesprächs-Turn.
    Diese Definition wurde an der Referenzsitzung gegen eine unabhängige
    Handklassifikation verifiziert: 91 Zeilen mit Nicht-tool_result-Inhalt,
    davon 9 isMeta und 26 <task-notification> -> 56 echte Runden — exakter
    Treffer auf den erwarteten Wert. (Eine frühere Fassung schloss
    Compaction-Zeilen zusätzlich aus, das ergab nur 53 — an der
    Referenzsitzung als Bug erkannt und korrigiert.)
  - ``tool_use``-Blöcke mit ``name == "Agent"`` zählen NICHT als normaler
    Werkzeugaufruf (ART_TOOL), sondern als Subagenten-Start (ART_SUBAGENT).
  - Tool-Ergebnisse (ART_TOOL_ERGEBNIS) werden nur für Fehler
    (``is_error: true``) erzeugt, nicht für jeden erfolgreichen Aufruf —
    Erfolg ist bereits durch das ART_TOOL-Ereignis zum Aufrufzeitpunkt belegt;
    ein zusätzliches Erfolgs-Ereignis wäre reine Verdopplung ohne Zusatzwert.
  - Subagenten werden PRIMÄR aus dem ``subagents/``-Ordner aufgebaut (Dateiliste),
    nicht aus sichtbaren ``Agent``-tool_use-Blöcken im Haupttranskript: Nach
    einer Compaction können frühere Agent-Aufrufe aus der sichtbaren Historie
    verschwinden, während die Subagenten-Dateien erhalten bleiben (an der
    Referenzsitzung beobachtet: mehr Dateien im Ordner als sichtbare
    Agent-tool_use-Blöcke). ART_SUBAGENT-Ereignisse im Haupttranskript sind
    daher ein Best-Effort-Zeitstrahl, kein vollständiges Subagenten-Inventar —
    das vollständige Inventar ist immer ``beleg.subagenten``.
  - Ausnahme von "Kennzahlen bleiben leer": ``kennzahlen.thinking_bloecke``
    wird direkt beim Lesen mitgezählt (kostenlos verfügbar, keine
    sitzungsweite Ableitung nötig) — alle anderen Kennzahlen-Felder bleiben
    auf ihrem Default (0 / leer), das macht ein anderes Modul.
  - Defekte JSON-Zeilen werden übersprungen, nie ein Absturz. Ihre Anzahl wird
    als ``Auffaelligkeit(regel="format:kaputte_zeile", wert=<Anzahl>)``
    festgehalten, weil ``modell.py`` (verbindlich, nicht geändert) dafür kein
    eigenes Zählfeld vorsieht.
  - ``Subagent.modell``/``Subagent.auftrag`` (Entscheid 2026-08-26): das
    Subagent-``meta.json`` trägt ``model`` nur als Kurzform ("sonnet") — die
    volle Kennung ("claude-sonnet-5") steht, genau wie bei der Hauptsitzung,
    im ``message.model`` der ersten assistant-Zeile des Subagent-eigenen
    Transkripts; die wird bevorzugt, meta.json bleibt Fallback (leeres/
    fehlendes Transkript). ``auftrag`` kommt aus meta.json ``description``
    (das 3–5-Wort-Label des Agent-Aufrufs, NIE der lange ``prompt``) — auf
    80 Zeichen gekürzt (``_kuerze_auftrag``) und danach wie jeder andere
    Beleg-String durch die generische Redaktionsstufe (redaktion.py) geprüft.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from . import modell
from .redaktion import sicherer_bezeichner

# ---------------------------------------------------------------------------
# Bekanntes Vokabular / Muster
# ---------------------------------------------------------------------------

# Zeilentypen (Stand Claude Code 2.1.245). Metadaten-Typen ohne Kennzahlwert werden
# bewusst ignoriert (file-history-*, last-prompt, ai-title tragen Inhalte -> nie lesen).
_BEKANNTE_TYPEN = {
    "user", "assistant", "system", "attachment", "mode", "permission-mode", "atis-latch",
    "file-history-snapshot", "file-history-delta", "ai-title", "last-prompt", "queue-operation",
    "bridge-session", "frame-link", "agent-name",
}
# Nur diese Zeilen tragen Sitzungsinhalt und duerfen start/ende setzen.
_INHALTLICHE_TYPEN = {"user", "assistant", "system"}
# Bekannte Felder je Zeilentyp (nur die drei mit Kennzahlwert). Neue Felder -> "feld:<typ>.<name>".
_GEMEINSAME_FELDER = {
    "cwd", "entrypoint", "gitBranch", "isSidechain", "parentUuid", "sessionId", "session_id", "slug",
    "timestamp", "type", "userType", "uuid", "version", "isMeta", "agentId",
}
_BEKANNTE_FELDER = {
    "user": _GEMEINSAME_FELDER | {
        "classifierMetaLines", "interruptedMessageId", "isCompactSummary", "isVisibleInTranscriptOnly",
        "mcpMeta", "message", "origin", "permissionMode", "promptId", "promptSource", "queuePriority",
        "sourceToolAssistantUUID", "sourceToolUseID", "toolDenialKind", "toolUseResult", "turnCompanion",
        "userFeedback", "isCompactSummary",
    },
    "assistant": _GEMEINSAME_FELDER | {
        "apiErrorStatus", "attributionMcpServer", "attributionMcpTool", "attributionPlugin",
        "attributionSkill", "attributionAgent", "effort", "error", "isAbortedMidStream",
        "isApiErrorMessage", "apiErrorIsTransient", "message", "quotaLimits", "requestId",
    },
    "system": _GEMEINSAME_FELDER | {
        "compactMetadata", "content", "durationMs", "hasOutput", "hookAdditionalContext", "hookCount",
        "hookErrors", "hookInfos", "level", "logicalParentUuid", "messageCount",
        "pendingBackgroundAgentCount", "pendingWorkflowCount", "preventedContinuation", "stopReason",
        "subtype", "toolUseID", "url",
    },
}


def _pruefe_felder(obj: dict, typ, zustand) -> None:
    """Unbekannte Felder eines bekannten Typs -> Marker (Format-Drift, kein Inhalt)."""
    bekannt = _BEKANNTE_FELDER.get(typ)
    if bekannt is None:
        return
    for feld_name in obj:
        if feld_name not in bekannt:
            zustand.unbekannte_typen.add(f"feld:{typ}.{feld_name}")
_DATEI_TOOLS = {"Edit", "Write", "MultiEdit", "Read"}
_BLOCKIERT_PRAEFIXE = ("Blocked", "blocked", "G5", "G6", "G7", "Permission")
AUFTRAG_MAX_LAENGE = 80  # modell.py-Kontrakt: Auftrags-Kurzlabel <= 80 Zeichen, mit "…" gekuerzt

_MUSTER_TASK_NOTIFICATION = re.compile(r"^\s*<task-notification")
_MUSTER_DATEIZEILE = re.compile(r"\w+\.\w+:\d+")
_MUSTER_BACKTICK_BEFEHL = re.compile(r"`[^`\n]+`")
_MUSTER_TESTZAHL = re.compile(r"Test[^\d\n]{0,20}\d+")


# ---------------------------------------------------------------------------
# Kleine Werkzeuge
# ---------------------------------------------------------------------------


class _Zaehler:
    """Mutable Zähl-Box (für kaputte Zeilen über Generator-Grenzen hinweg)."""

    def __init__(self) -> None:
        self.wert = 0


def _zeilen(pfad: Path, kaputte: _Zaehler) -> Iterator[dict]:
    """Liest eine JSONL-Datei zeilenweise. Kaputte Zeilen: überspringen + zählen."""
    with pfad.open("r", encoding="utf-8") as datei:
        for rohzeile in datei:
            rohzeile = rohzeile.strip()
            if not rohzeile:
                continue
            try:
                yield json.loads(rohzeile)
            except json.JSONDecodeError:
                kaputte.wert += 1
                continue


def _letzter_pfadteil(pfad: str) -> str:
    if not pfad:
        return ""
    teile = [t for t in re.split(r"[\\/]+", pfad.rstrip("\\/")) if t]
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
    return _letzter_pfadteil(cwd)


def _dauer_ms(start: str, ende: str) -> Optional[int]:
    if not start or not ende:
        return None
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(ende.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((t1 - t0).total_seconds() * 1000)


def _tool_result_text(inhalt) -> str:
    """Extrahiert kurzzeitig Text aus einem tool_result-content-Feld (String
    oder Blockliste) — nur zur Präfix-Klassifikation, wird nie gespeichert."""
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        for block in inhalt:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def _fehlerklasse(text: str) -> str:
    for praefix in _BLOCKIERT_PRAEFIXE:
        if text.startswith(praefix):
            return "blocked"
    return "tool_error"


def _datei_ref(tool_name: str, tool_input: dict) -> str:
    if tool_name in _DATEI_TOOLS:
        pfad = tool_input.get("file_path", "")
        if pfad:
            return hashlib.sha256(pfad.encode("utf-8")).hexdigest()[:12]
    return ""


def _token_aus_usage(usage: dict) -> modell.Token:
    details = usage.get("output_tokens_details") or {}
    return modell.Token(
        input=usage.get("input_tokens", 0) or 0,
        output=usage.get("output_tokens", 0) or 0,
        cache_write=usage.get("cache_creation_input_tokens", 0) or 0,
        cache_read=usage.get("cache_read_input_tokens", 0) or 0,
        thinking=details.get("thinking_tokens", 0) or 0,
    )


def _hat_datei_referenz(text: str) -> bool:
    if not text:
        return False
    return bool(
        _MUSTER_DATEIZEILE.search(text)
        or _MUSTER_BACKTICK_BEFEHL.search(text)
        or _MUSTER_TESTZAHL.search(text)
    )


def _kuerze_auftrag(text: str, max_laenge: int = AUFTRAG_MAX_LAENGE) -> str:
    """Kuerzt das Auftrags-Kurzlabel (meta.json "description") auf ``max_laenge`` Zeichen,
    mit "…" markiert -- greift VOR der generischen Redaktionsstufe (redaktion.py), die eine
    Ueberlaenge sonst komplett durch ``<redigiert>`` ersetzen wuerde statt sie zu kuerzen."""
    text = (text or "").strip()
    if not text or len(text) <= max_laenge:
        return text
    return text[: max_laenge - 1].rstrip() + "…"


def _echte_nutzerrunde(obj: dict) -> bool:
    """True, wenn diese user-Zeile eine echte Nutzer-Runde beginnt (siehe
    Modul-Docstring für die verifizierte Definition)."""
    if obj.get("type") != "user":
        return False
    if obj.get("isMeta"):
        return False
    nachricht = obj.get("message", {})
    inhalt = nachricht.get("content", "")
    text = ""
    if isinstance(inhalt, str):
        if not inhalt.strip():
            return False
        text = inhalt
    elif isinstance(inhalt, list):
        nicht_tool_result = [
            b for b in inhalt if not (isinstance(b, dict) and b.get("type") == "tool_result")
        ]
        if not nicht_tool_result:
            return False
        for block in inhalt:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                break
    else:
        return False
    return not _MUSTER_TASK_NOTIFICATION.match(text)


# ---------------------------------------------------------------------------
# Laufender Zustand beim Scannen eines Transkripts (Haupt- oder Subagent-Datei)
# ---------------------------------------------------------------------------


@dataclass
class _Zustand:
    runden: int = 0
    tools: int = 0
    tool_fehler: int = 0
    thinking_bloecke: int = 0
    token: modell.Token = field(default_factory=modell.Token)
    modelle: set = field(default_factory=set)
    erstes_modell: str = ""  # erste volle Modellkennung (message.model) -- fuer Subagent.modell
    start: str = ""
    ende: str = ""
    hat_usage: bool = False
    gezaehlte_message_ids: set = field(default_factory=set)  # usage nur einmal je message.id
    hat_turn_duration: bool = False
    unbekannte_typen: set = field(default_factory=set)
    letzter_text: str = ""
    letzter_tool_result_fehler: bool = False
    text_nach_letztem_tool_result: bool = False
    offene_tool_namen: dict = field(default_factory=dict)  # tool_use_id -> Tool-Name
    offene_tool_ereignisse: dict = field(default_factory=dict)  # tool_use_id -> ART_TOOL-Ereignis


def _schliesse_tool(zustand: _Zustand, tool_use_id: str, zeit: str) -> None:
    """Trägt die Laufzeit (tool_result-Zeit minus tool_use-Zeit) am ART_TOOL-Ereignis ein."""
    aufruf = zustand.offene_tool_ereignisse.pop(tool_use_id, None)
    if aufruf is not None:
        aufruf.dauer_ms = _dauer_ms(aufruf.zeit, zeit)


def _verarbeite_user_zeile(obj: dict, zeit: str, zustand: _Zustand) -> list[modell.Ereignis]:
    ereignisse: list[modell.Ereignis] = []
    if _echte_nutzerrunde(obj):
        zustand.runden += 1
        ereignisse.append(modell.Ereignis(zeit=zeit, art=modell.ART_NUTZER))
    inhalt = obj.get("message", {}).get("content", "")
    if not isinstance(inhalt, list):
        return ereignisse
    for block in inhalt:
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        ist_fehler = bool(block.get("is_error"))
        _schliesse_tool(zustand, block.get("tool_use_id", ""), zeit)
        zustand.letzter_tool_result_fehler = ist_fehler
        zustand.text_nach_letztem_tool_result = False
        if not ist_fehler:
            continue
        zustand.tool_fehler += 1
        tool_use_id = block.get("tool_use_id", "")
        tool_name = zustand.offene_tool_namen.get(tool_use_id, "")
        klasse = _fehlerklasse(_tool_result_text(block.get("content", "")))
        signatur = hashlib.sha256((tool_name + klasse).encode("utf-8")).hexdigest()[:12]
        ereignisse.append(
            modell.Ereignis(
                zeit=zeit, art=modell.ART_TOOL_ERGEBNIS, name=tool_name,
                fehler=True, fehlerklasse=klasse, signatur=signatur, ref=tool_use_id,
            )
        )
    return ereignisse


def _usage_schon_gezaehlt(nachricht: dict, zustand: _Zustand) -> bool:
    message_id = nachricht.get("id")
    if not message_id:
        return False
    if message_id in zustand.gezaehlte_message_ids:
        return True
    zustand.gezaehlte_message_ids.add(message_id)
    return False


def _verarbeite_assistant_zeile(
    obj: dict, zeit: str, zustand: _Zustand, tooluse_zu_agent: dict
) -> list[modell.Ereignis]:
    ereignisse: list[modell.Ereignis] = []
    nachricht = obj.get("message", {})
    modell_name = nachricht.get("model")
    if modell_name:
        zustand.modelle.add(modell_name)
        if not zustand.erstes_modell:
            zustand.erstes_modell = modell_name
    usage = nachricht.get("usage")
    # Claude Code schreibt je Inhaltsblock (thinking/text/tool_use) eine eigene assistant-Zeile
    # mit derselben message.id und identischer usage -- nur die erste zaehlt (Befund 2026-08-27:
    # 704 Zeilen, 384 ids, Token out 507k statt 212k; Codex-Fund, deterministisch bestaetigt).
    if usage and _usage_schon_gezaehlt(nachricht, zustand):
        usage = None
    if usage:
        zustand.hat_usage = True
        token = _token_aus_usage(usage)
        zustand.token.add(token)
        ereignisse.append(
            modell.Ereignis(zeit=zeit, art=modell.ART_ASSISTENT, name=modell_name or "", token=token)
        )
    inhalt = nachricht.get("content", [])
    if not isinstance(inhalt, list):
        return ereignisse
    for block in inhalt:
        if not isinstance(block, dict):
            continue
        block_typ = block.get("type")
        if block_typ == "thinking":
            zustand.thinking_bloecke += 1
        elif block_typ == "text" and block.get("text", "").strip():
            zustand.letzter_text = block["text"]
            zustand.text_nach_letztem_tool_result = True
        elif block_typ == "tool_use":
            ereignisse.append(_verarbeite_tool_use(block, zeit, zustand, tooluse_zu_agent))
    return ereignisse


def _verarbeite_tool_use(
    block: dict, zeit: str, zustand: _Zustand, tooluse_zu_agent: dict
) -> modell.Ereignis:
    tool_name = sicherer_bezeichner(block.get("name", ""))
    tool_id = block.get("id", "")
    zustand.offene_tool_namen[tool_id] = tool_name
    if tool_name == "Agent":
        agent_id, agent_typ = tooluse_zu_agent.get(tool_id, ("", ""))
        return modell.Ereignis(zeit=zeit, art=modell.ART_SUBAGENT, name=agent_typ, ref=agent_id)
    zustand.tools += 1
    signatur = _datei_ref(tool_name, block.get("input") or {})
    aufruf = modell.Ereignis(
        zeit=zeit, art=modell.ART_TOOL, name=tool_name, ref=tool_id, signatur=signatur
    )
    zustand.offene_tool_ereignisse[tool_id] = aufruf
    return aufruf


def _verarbeite_zeile(obj: dict, zustand: _Zustand, tooluse_zu_agent: dict) -> list[modell.Ereignis]:
    ereignisse: list[modell.Ereignis] = []
    zeit = obj.get("timestamp") or ""
    typ = obj.get("type")
    # start/ende nur aus inhaltlichen Zeilen (Befund 2026-08-27): Buchhaltungszeilen wie
    # queue-operation schreibt Claude Code auch Stunden nach dem letzten Turn in alte Dateien --
    # sie verschoben `ende` um 9 h (Phantom-Version 1324 von 1284, Dauer 18h39 statt 9h30).
    if zeit and typ in _INHALTLICHE_TYPEN:
        if not zustand.start:
            zustand.start = zeit
        zustand.ende = zeit
    if typ not in _BEKANNTE_TYPEN:
        zustand.unbekannte_typen.add(str(typ))
    _pruefe_felder(obj, typ, zustand)
    if obj.get("isCompactSummary"):
        ereignisse.append(modell.Ereignis(zeit=zeit, art=modell.ART_COMPACTION))
    if typ == "system" and obj.get("subtype") == "turn_duration":
        zustand.hat_turn_duration = True
        ereignisse.append(
            modell.Ereignis(zeit=zeit, art=modell.ART_RUNDE_ENDE, dauer_ms=obj.get("durationMs"))
        )
    elif typ in ("user", "assistant"):
        # F8: gültiges JSON, aber falscher Strukturtyp (z. B. message als String
        # statt Dict) -> Zeile überspringen statt AttributeError, gezählt.
        nachricht = obj.get("message")
        if nachricht is not None and not isinstance(nachricht, dict):
            zustand.unbekannte_typen.add(f"struktur:{type(nachricht).__name__}")
            return ereignisse
        if typ == "user":
            ereignisse.extend(_verarbeite_user_zeile(obj, zeit, zustand))
        else:
            ereignisse.extend(_verarbeite_assistant_zeile(obj, zeit, zustand, tooluse_zu_agent))
    return ereignisse


# ---------------------------------------------------------------------------
# Subagenten
# ---------------------------------------------------------------------------


def _lese_subagent_meta(meta_pfad: Path) -> dict:
    """Liest agent-<id>.meta.json; kaputte/fehlende Datei -> leeres Dict (kein Absturz)."""
    try:
        return json.loads(meta_pfad.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _verarbeite_subagent_transkript(transkript_pfad: Path, kaputte: "_Zaehler") -> "_Zustand":
    """Liest agent-<id>.jsonl komplett und liefert den gefuellten Zustand (leerer Zustand,
    wenn die Datei fehlt -- meta.json bleibt dann die einzige Quelle in _baue_subagenten)."""
    zustand = _Zustand()
    if not transkript_pfad.is_file():
        return zustand
    for obj in _zeilen(transkript_pfad, kaputte):
        if not isinstance(obj, dict):
            zustand.unbekannte_typen.add(f"struktur:{type(obj).__name__}")
            continue
        _verarbeite_zeile(obj, zustand, {})
    return zustand


def _bestimme_subagent_ergebnis(zustand: "_Zustand") -> str:
    """leer/fehler/ok nach demselben Muster wie die Hauptsitzung: kein Text -> leer, letzter
    Tool-Fehler ohne folgenden Text -> fehler, sonst ok."""
    if not zustand.letzter_text:
        return "leer"
    if zustand.letzter_tool_result_fehler and not zustand.text_nach_letztem_tool_result:
        return "fehler"
    return "ok"


def _baue_ein_subagent(meta_pfad: Path, subagents_ordner: Path, kaputte: "_Zaehler"):
    """Baut einen Subagent-Eintrag aus meta.json + eigenem Transkript. Liefert
    (Subagent, tool_use_id, agent_id, typ, unbekannte_typen der Transkript-Zeilen)."""
    agent_id = meta_pfad.name[len("agent-"):-len(".meta.json")]
    transkript_pfad = subagents_ordner / f"agent-{agent_id}.jsonl"
    meta = _lese_subagent_meta(meta_pfad)

    typ = sicherer_bezeichner(meta.get("agentType", ""))
    modell_meta = meta.get("model", "")
    auftrag = _kuerze_auftrag(meta.get("description", ""))
    tiefe = meta.get("spawnDepth", 1)
    tool_use_id = meta.get("toolUseId", "")

    zustand = _verarbeite_subagent_transkript(transkript_pfad, kaputte)
    beleg = "observed" if _hat_datei_referenz(zustand.letzter_text) else "not_observed"
    # Volle Modellkennung aus dem eigenen Transkript bevorzugen (z. B. "claude-sonnet-5",
    # wie bei der Hauptsitzung/Kopf.modelle) -- meta.json "model" ist nur die Kurzform
    # ("sonnet") und greift nur, wenn das Transkript kein/leer ist (kein assistant-Text).
    modell_name = zustand.erstes_modell or modell_meta

    subagent = modell.Subagent(
        agent_id=agent_id, typ=typ, modell=modell_name, auftrag=auftrag, tiefe=tiefe,
        start=zustand.start, ende=zustand.ende,
        dauer_ms=_dauer_ms(zustand.start, zustand.ende),
        runden=zustand.runden, tools=zustand.tools, tool_fehler=zustand.tool_fehler,
        token=zustand.token, beleg=beleg, ergebnis=_bestimme_subagent_ergebnis(zustand),
    )
    return subagent, tool_use_id, agent_id, typ, zustand.unbekannte_typen


def _baue_subagenten(subagents_ordner: Path):
    """Baut die Subagenten-Liste aus dem Dateiordner (nicht aus sichtbaren
    Agent-tool_use-Blöcken, siehe Modul-Docstring). Liefert zusätzlich die
    Zuordnung toolUseId -> (agent_id, agentType) für ART_SUBAGENT-Ereignisse
    im Haupttranskript sowie gesammelte unbekannte Zeilentypen + kaputte
    Zeilen aus den Subagenten-Transkripten."""
    subagenten: list[modell.Subagent] = []
    tooluse_zu_agent: dict[str, tuple[str, str]] = {}
    unbekannte_typen: set[str] = set()
    kaputte = _Zaehler()
    if not subagents_ordner.is_dir():
        return subagenten, tooluse_zu_agent, unbekannte_typen, kaputte.wert

    for meta_pfad in sorted(subagents_ordner.glob("agent-*.meta.json")):
        subagent, tool_use_id, agent_id, typ, sub_unbekannt = _baue_ein_subagent(
            meta_pfad, subagents_ordner, kaputte
        )
        if tool_use_id:
            tooluse_zu_agent[tool_use_id] = (agent_id, typ)
        unbekannte_typen |= sub_unbekannt
        subagenten.append(subagent)
    return subagenten, tooluse_zu_agent, unbekannte_typen, kaputte.wert


# ---------------------------------------------------------------------------
# Öffentliche Funktion
# ---------------------------------------------------------------------------


def _lese_hauptzeilen(sitzung_pfad: Path, zustand: "_Zustand", kaputte: "_Zaehler",
                       tooluse_zu_agent: dict) -> tuple[list, str, str, str, str]:
    """Liest alle Zeilen der Hauptsitzung, fuellt zustand + ereignisse und liefert
    (ereignisse, sitzung_id, cwd, version, git_branch). sitzung_id faellt auf den
    Dateinamen zurueck, wenn keine Zeile ``sessionId`` traegt."""
    ereignisse: list[modell.Ereignis] = []
    sitzung_id = sitzung_pfad.stem
    cwd = ""
    version = ""
    git_branch = ""
    for obj in _zeilen(sitzung_pfad, kaputte):
        if not isinstance(obj, dict):
            zustand.unbekannte_typen.add(f"struktur:{type(obj).__name__}")
            continue
        if not cwd and obj.get("cwd"):
            cwd = obj["cwd"]
        if not version and obj.get("version"):
            version = obj["version"]
        if not git_branch and obj.get("gitBranch"):
            git_branch = sicherer_bezeichner(obj["gitBranch"])
        if obj.get("sessionId"):
            sitzung_id = obj["sessionId"]
        ereignisse.extend(_verarbeite_zeile(obj, zustand, tooluse_zu_agent))
    return ereignisse, sitzung_id, cwd, version, git_branch


def _baue_kopf(host: str, sitzung_id: str, cwd: str, version: str, git_branch: str,
               zustand: "_Zustand") -> modell.Kopf:
    return modell.Kopf(
        quelle="claude",
        sitzung_id=sitzung_id,
        projekt_hash=hashlib.sha256(cwd.encode("utf-8")).hexdigest()[:12] if cwd else "",
        projekt_name=sicherer_bezeichner(_git_wurzel_name(cwd)),  # C2: Allowlist, sonst Hash
        host=host,
        start=zustand.start,
        ende=zustand.ende,
        version=version,
        git_branch=git_branch,
        modelle=sorted(zustand.modelle),
    )


def _baue_erfassung(zustand: "_Zustand", subagents_ordner: Path,
                     unbekannte_sub_typen: set) -> modell.Erfassung:
    return modell.Erfassung(
        token="observed" if zustand.hat_usage else "not_observed",
        dauer="observed" if zustand.hat_turn_duration else "not_observed",
        kosten="not_observed",
        inhalte="redacted",
        subagenten="observed" if subagents_ordner.is_dir() else "not_observed",
        compaction="observed",
        reasoning="partial",
        unbekannt=sorted(zustand.unbekannte_typen | unbekannte_sub_typen),
    )


def _baue_kaputte_zeile_auffaelligkeit(kaputte_gesamt: int) -> list[modell.Auffaelligkeit]:
    if not kaputte_gesamt:
        return []
    return [
        modell.Auffaelligkeit(
            regel="format:kaputte_zeile",
            schwere="hinweis",
            signatur=hashlib.sha256(b"kaputte_zeile").hexdigest()[:12],
            wert=str(kaputte_gesamt),
        )
    ]


def lese_sitzung(pfad: str, host: str = "") -> modell.Beleg:
    """Liest ein Claude-Code-Sitzungstranskript und füllt einen Beleg.

    Füllt Kopf, Erfassung, Ereignisse und Subagenten. Kennzahlen bleiben bis
    auf ``thinking_bloecke`` leer — Verdichtung macht ein anderes Modul.
    Crasht nie an defekten Zeilen (übersprungen + in einer Auffaelligkeit
    gezählt) oder unbekannten ``type``-Werten (in ``erfassung.unbekannt``).
    """
    sitzung_pfad = Path(pfad)
    subagents_ordner = sitzung_pfad.with_suffix("") / "subagents"
    subagenten, tooluse_zu_agent, unbekannte_sub_typen, kaputte_sub = _baue_subagenten(
        subagents_ordner
    )

    zustand = _Zustand()
    kaputte = _Zaehler()
    ereignisse, sitzung_id, cwd, version, git_branch = _lese_hauptzeilen(
        sitzung_pfad, zustand, kaputte, tooluse_zu_agent
    )

    return modell.Beleg(
        kopf=_baue_kopf(host, sitzung_id, cwd, version, git_branch, zustand),
        erfassung=_baue_erfassung(zustand, subagents_ordner, unbekannte_sub_typen),
        kennzahlen=modell.Kennzahlen(thinking_bloecke=zustand.thinking_bloecke),
        ereignisse=ereignisse,
        subagenten=subagenten,
        auffaelligkeiten=_baue_kaputte_zeile_auffaelligkeit(kaputte.wert + kaputte_sub),
    )
