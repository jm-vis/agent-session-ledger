"""Erzeugt ein anonymisiertes, gekürztes Claude-Fixture aus der Referenzsitzung.

Liest NIE Inhalte in den Aufrufer-Kontext — läuft als eigenständiges Skript und
schreibt direkt auf die Platte. Quelle (nur lesen, Pflichtargument
``sys.argv[1]``): der Pfad zur echten Referenzsitzung (``<session>.jsonl``
unter ``~/.claude/projects/<projekt>/``). Ziel: ``tests/fixtures/claude/<session>.jsonl``
+ ``tests/fixtures/claude/<session>/subagents/agent-<id>.jsonl`` (+ .meta.json).

Redaktion (siehe Auftrag):
  - cwd -> ``C:\\Beispiel\\Projekt``
  - ``file_path`` in tool_use-Input -> ``C:\\Beispiel\\Projekt\\datei<k>.md``
    (stabile Zuordnung über die ganze Sitzung + alle Subagenten hinweg)
  - gitBranch, sessionId/session_id, uuid/parentUuid, agentId: unverändert
  - ALLE anderen Strings (text, thinking, tool_use-Input außer file_path,
    tool_result-Inhalt, und — über die im Auftrag genannten Felder hinaus,
    weil das echte Format mehr Zeilentypen als dokumentiert enthält, z. B.
    queue-operation/file-history-*/ai-title/attachment mit eingebetteten
    Pfaden/Volltexten — generisch jedes nicht ausdrücklich erlaubte Feld):
    ersetzt durch ``<redigiert:N>`` (N = Originallänge).
  - Subagent-meta.json: ``description`` (Entscheid 2026-08-26: jetzt Nutzdaten,
    ``Subagent.auftrag``) wird durch ein stabiles synthetisches Label ``Testauftrag N``
    ersetzt statt komplett redigiert — sonst koennte kein Test mehr gegen echte
    Auftrags-Label-Werte pruefen. Rest von meta.json unveraendert.

Auswahl der Hauptsitzungs-Zeilen: erste ~120 Zeilen + jede Zeile mit
Compaction (``isCompactSummary``), ``turn_duration`` oder einem
Agent-tool_use-Block, bis insgesamt 400 Zeilen. Für die Subagenten werden die
2 kleinsten Transkripte im Ordner komplett übernommen (klein genug, um das
Repo schlank zu halten, UND vollständig — nur so bleibt das *letzte*
assistant-Textstück für die beleg/ergebnis-Klassifikation erhalten).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Referenzsitzung (nur lesen!) kommt als Pflichtargument sys.argv[1] — kein
# harter (personenbezogener) Pfad im Skript (F11).

ZIEL_ORDNER = Path(__file__).parent / "fixtures" / "claude"
MAX_ZEILEN_HAUPT = 400
ERSTE_ZEILEN_IMMER = 120
ANZAHL_SUBAGENTEN = 2

_TOPLEVEL_KEEP = {
    "type", "uuid", "parentUuid", "sessionId", "session_id", "gitBranch",
    "version", "subtype", "durationMs", "timestamp", "isMeta",
    "isCompactSummary", "isSidechain", "isVisibleInTranscriptOnly",
    "userType", "entrypoint", "mode", "promptId", "promptSource",
    "permissionMode", "slug", "origin", "toolDenialKind", "turnCompanion",
    "messageCount", "agentId", "interruptedMessageId",
}
_MESSAGE_KEEP = {"role", "model", "id", "type", "stop_reason", "stop_sequence", "usage"}
_BLOCK_KEEP = {"type", "id", "tool_use_id", "is_error", "name"}


def _scrub(wert):
    """Ersetzt jeden String durch ``<redigiert:N>``, rekursiv über Dicts/Listen."""
    if isinstance(wert, str):
        return f"<redigiert:{len(wert)}>" if wert else wert
    if isinstance(wert, dict):
        return {k: _scrub(v) for k, v in wert.items()}
    if isinstance(wert, list):
        return [_scrub(v) for v in wert]
    return wert


def _fake_pfad(original: str, dateien: dict) -> str:
    if original not in dateien:
        k = len(dateien) + 1
        dateien[original] = f"C:\\Beispiel\\Projekt\\datei{k}.md"
    return dateien[original]


def _fake_auftrag(original: str, auftraege: dict) -> str:
    if not original:
        return original
    if original not in auftraege:
        auftraege[original] = f"Testauftrag {len(auftraege) + 1}"
    return auftraege[original]


def _redigiere_input(eingabe: dict, dateien: dict) -> dict:
    ergebnis = {}
    for k, v in eingabe.items():
        if k == "file_path" and isinstance(v, str) and v:
            ergebnis[k] = _fake_pfad(v, dateien)
        else:
            ergebnis[k] = _scrub(v)
    return ergebnis


def _redigiere_block(block, dateien: dict):
    if not isinstance(block, dict):
        return _scrub(block)
    typ = block.get("type")
    neu = {}
    for k, v in block.items():
        if k in _BLOCK_KEEP:
            neu[k] = v
        elif typ == "tool_use" and k == "input" and isinstance(v, dict):
            neu[k] = _redigiere_input(v, dateien)
        else:
            neu[k] = _scrub(v)
    return neu


def _redigiere_message(msg: dict, dateien: dict) -> dict:
    neu = {}
    for k, v in msg.items():
        if k == "content":
            if isinstance(v, str):
                neu[k] = _scrub(v)
            elif isinstance(v, list):
                neu[k] = [_redigiere_block(b, dateien) for b in v]
            else:
                neu[k] = v
        elif k in _MESSAGE_KEEP:
            neu[k] = v
        else:
            neu[k] = _scrub(v)
    return neu


def _redigiere_zeile(obj: dict, dateien: dict) -> dict:
    neu = {}
    for k, v in obj.items():
        if k == "cwd":
            neu[k] = r"C:\Beispiel\Projekt" if v else v
        elif k == "message" and isinstance(v, dict):
            neu[k] = _redigiere_message(v, dateien)
        elif k in _TOPLEVEL_KEEP:
            neu[k] = v
        else:
            neu[k] = _scrub(v)
    return neu


def _hat_agent_tool_use(obj: dict) -> bool:
    if obj.get("type") != "assistant":
        return False
    inhalt = obj.get("message", {}).get("content", [])
    if not isinstance(inhalt, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Agent"
        for b in inhalt
    )


def _ist_ausgewaehlt(obj: dict) -> bool:
    return bool(obj.get("isCompactSummary")) or (
        obj.get("type") == "system" and obj.get("subtype") == "turn_duration"
    ) or _hat_agent_tool_use(obj)


def _schreibe_hauptsitzung(dateien: dict, quelle_sitzung: Path) -> Path:
    ausgewaehlt: list[dict] = []
    with quelle_sitzung.open("r", encoding="utf-8") as quelle:
        for n, rohzeile in enumerate(quelle, 1):
            if len(ausgewaehlt) >= MAX_ZEILEN_HAUPT:
                break
            rohzeile = rohzeile.strip()
            if not rohzeile:
                continue
            try:
                obj = json.loads(rohzeile)
            except json.JSONDecodeError:
                continue
            if n <= ERSTE_ZEILEN_IMMER or _ist_ausgewaehlt(obj):
                ausgewaehlt.append(obj)

    sitzung_id = quelle_sitzung.stem
    ziel_pfad = ZIEL_ORDNER / f"{sitzung_id}.jsonl"
    ziel_pfad.parent.mkdir(parents=True, exist_ok=True)
    with ziel_pfad.open("w", encoding="utf-8") as ziel:
        for obj in ausgewaehlt:
            neu = _redigiere_zeile(obj, dateien)
            ziel.write(json.dumps(neu, ensure_ascii=False) + "\n")
    print(f"Hauptsitzung: {len(ausgewaehlt)} Zeilen -> {ziel_pfad}")
    return ziel_pfad


def _kleinste_subagenten(quelle_subagenten: Path, anzahl: int) -> list[str]:
    kandidaten = sorted(
        quelle_subagenten.glob("agent-*.jsonl"), key=lambda p: p.stat().st_size
    )
    return [p.name[len("agent-"):-len(".jsonl")] for p in kandidaten[:anzahl]]


def _schreibe_subagenten(dateien: dict, quelle_sitzung: Path, quelle_subagenten: Path) -> None:
    sitzung_id = quelle_sitzung.stem
    ziel_ordner = ZIEL_ORDNER / sitzung_id / "subagents"
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    auftraege: dict[str, str] = {}

    for agent_id in _kleinste_subagenten(quelle_subagenten, ANZAHL_SUBAGENTEN):
        quelle_jsonl = quelle_subagenten / f"agent-{agent_id}.jsonl"
        quelle_meta = quelle_subagenten / f"agent-{agent_id}.meta.json"

        anzahl = 0
        with quelle_jsonl.open("r", encoding="utf-8") as quelle, \
                (ziel_ordner / f"agent-{agent_id}.jsonl").open("w", encoding="utf-8") as ziel:
            for rohzeile in quelle:
                rohzeile = rohzeile.strip()
                if not rohzeile:
                    continue
                try:
                    obj = json.loads(rohzeile)
                except json.JSONDecodeError:
                    continue
                neu = _redigiere_zeile(obj, dateien)
                ziel.write(json.dumps(neu, ensure_ascii=False) + "\n")
                anzahl += 1

        meta = json.loads(quelle_meta.read_text(encoding="utf-8"))
        meta["description"] = _fake_auftrag(meta.get("description", ""), auftraege)
        (ziel_ordner / f"agent-{agent_id}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Subagent {agent_id}: {anzahl} Zeilen")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: python make_fixture_claude.py <quell-sitzung.jsonl>",
            file=sys.stderr,
        )
        return 2

    quelle_sitzung = Path(argv[1])
    quelle_subagenten = quelle_sitzung.with_suffix("") / "subagents"

    dateien: dict[str, str] = {}
    _schreibe_hauptsitzung(dateien, quelle_sitzung)
    _schreibe_subagenten(dateien, quelle_sitzung, quelle_subagenten)
    print(f"Dateipfade anonymisiert: {len(dateien)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
