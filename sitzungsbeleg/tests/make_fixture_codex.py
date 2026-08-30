"""Erzeugt aus einer echten Codex-Rollout-Datei ein anonymisiertes Fixture.

Nimmt eine reale ``rollout-*.jsonl`` (Quelldatei oder -ordner als
Pflichtargument ``sys.argv[1]`` — bei einem Ordner wird die kleinste
``rollout-*.jsonl`` darin gewählt), kürzt sie auf max. 300 Zeilen und
ersetzt JEDES Textfeld (content-Text, message, arguments, output,
base_instructions/instructions-Text, last_agent_message, world_state) durch
``"<redigiert:N>"`` (N = Originallänge) — außer den Zeilen "Exit code: N" und
"Wall time: X s" in function_call_output.output, die als einzige Textzeilen
erhalten bleiben. cwd/workspace_roots -> "C:\\Beispiel\\Projekt".
encrypted_content -> "<redigiert>".

Nur lesen/anonymisieren — nie die Originaldatei verändern.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BEISPIEL_PFAD = "C:\\Beispiel\\Projekt"
_MAX_ZEILEN = 300

# In function_call_output.output einzige erhaltene Textzeilen.
_MUSTER_EXIT_ZEILE = re.compile(r"^Exit code:\s*-?\d+$")
_MUSTER_WALL_ZEILE = re.compile(r"^Wall time:\s*[0-9.]+\s*\w+$")

# Keys, deren String-Wert komplett durch "<redigiert:N>" ersetzt wird.
_TEXT_KEYS = {"text", "message", "arguments", "instructions", "last_agent_message"}


def _redigiere_ausgabe(text: str) -> str:
    """function_call_output.output: nur Exit-code-/Wall-time-Zeilen erhalten."""
    behalten = [
        z for z in text.splitlines() if _MUSTER_EXIT_ZEILE.match(z) or _MUSTER_WALL_ZEILE.match(z)
    ]
    rest_laenge = len(text) - sum(len(z) + 1 for z in behalten)
    teile = list(behalten)
    if rest_laenge > 0 or not behalten:
        teile.append(f"<redigiert:{max(rest_laenge, 0)}>")
    return "\n".join(teile)


def _redigiere(node):
    """Läuft rekursiv durch eine JSON-Struktur und tilgt Inhalte in-place."""
    if isinstance(node, dict):
        for key in list(node.keys()):
            wert = node[key]
            if key in ("cwd",) and isinstance(wert, str):
                node[key] = _BEISPIEL_PFAD
            elif key == "workspace_roots" and isinstance(wert, list):
                node[key] = [_BEISPIEL_PFAD for _ in wert]
            elif key == "encrypted_content":
                node[key] = "<redigiert>"
            elif key == "output" and isinstance(wert, str):
                node[key] = _redigiere_ausgabe(wert)
            elif key in _TEXT_KEYS and isinstance(wert, str):
                node[key] = f"<redigiert:{len(wert)}>"
            elif key == "state":
                # world_state.state: verschachtelte Sitzungs-/Skill-Interna,
                # nicht Teil des Lesermodells -> geschlossen tilgen.
                node[key] = "<redigiert>"
            else:
                _redigiere(wert)
    elif isinstance(node, list):
        for item in node:
            _redigiere(item)


def baue_fixture(quelle: Path, ziel: Path, max_zeilen: int = _MAX_ZEILEN) -> int:
    """Liest `quelle`, redigiert jede Zeile, schreibt max. `max_zeilen` nach `ziel`."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    geschrieben = 0
    with quelle.open("r", encoding="utf-8") as ein, ziel.open("w", encoding="utf-8") as aus:
        for roh_zeile in ein:
            if geschrieben >= max_zeilen:
                break
            roh_zeile = roh_zeile.strip()
            if not roh_zeile:
                continue
            eintrag = json.loads(roh_zeile)
            _redigiere(eintrag)
            aus.write(json.dumps(eintrag, ensure_ascii=False, separators=(",", ":")) + "\n")
            geschrieben += 1
    return geschrieben


def _finde_quelle(basis: Path) -> Path:
    """`basis` ist entweder direkt eine rollout-*.jsonl oder ein Ordner, in dem
    die kleinste rollout-*.jsonl gesucht wird."""
    if basis.is_file():
        return basis
    kandidaten = sorted(basis.glob("rollout-*.jsonl"), key=lambda p: p.stat().st_size)
    if not kandidaten:
        raise SystemExit(f"Keine rollout-*.jsonl unter {basis} gefunden")
    return kandidaten[0]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: python make_fixture_codex.py <quelldatei-oder-ordner>",
            file=sys.stderr,
        )
        return 2

    quelle = _finde_quelle(Path(argv[1]))
    ziel = Path(__file__).parent / "fixtures" / "codex" / "rollout-beispiel.jsonl"
    n = baue_fixture(quelle, ziel)
    print(f"Fixture geschrieben: {ziel} ({n} Zeilen, Quelle: {quelle.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
