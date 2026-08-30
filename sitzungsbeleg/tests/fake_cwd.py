"""Fake `claude -p --input-format stream-json --output-format stream-json` fuer
test_chat_bruecke.py `KindprozessCwdTest` -- meldet NUR `os.getcwd()` als einziges Text-Delta,
damit ein Test pruefen kann, mit welchem Arbeitsverzeichnis `ChatProzess._spawn()` den
Kindprozess tatsaechlich startet (Nachtrag Sichtkontext 2026-08-28: muss `scripts/` sein, damit
`python -m sitzungsbeleg nachschlagen` dort auflöst)."""
import json
import os
import sys


def _schreibe(ereignis: dict) -> None:
    sys.stdout.write(json.dumps(ereignis) + "\n")
    sys.stdout.flush()


def main() -> None:
    for zeile in sys.stdin:
        if not zeile.strip():
            continue
        _schreibe({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": os.getcwd()}}})
        _schreibe({"type": "result", "usage": {"input_tokens": 1, "output_tokens": 1}})


if __name__ == "__main__":
    main()
