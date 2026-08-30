"""Fake `claude -p --input-format stream-json --output-format stream-json` fuer
test_chat_bruecke.py/test_chat.py -- ganz ohne Anthropic-Zugriff. Liest User-Nachrichten
zeilenweise von stdin (echtes stream-json-Format), antwortet mit stream-json-Ereignissen auf
stdout. Modus per sys.argv[1] steuert das Verhalten je Turn:

  normal (Default) -- zwei Text-Deltas + ein result-Ereignis mit usage (ein "normaler" Turn,
      wiederholbar -- die Registry-Wiederverwendung ueber mehrere Sends laesst sich damit testen).
  crash  -- ein Delta, dann harter Exit (kein result-Ereignis) -- simuliert einen Absturz
      mitten im Turn (chat_bruecke.ChatProzess._lesen soll das als 'fehler' melden).
  hang   -- schlaeft laenger als jedes in Tests gesetzte `chat_bruecke.TURN_TIMEOUT_S` -- simuliert
      einen haengenden Kindprozess (Zeitlimit-Pfad).
  hang_stderr -- wie hang, schreibt vorher eine Zeile auf stderr -- prueft, dass eine stderr-
      Warnung (Fund 2026-08-27: `unrecognized_model` u. ae.) in die 'fehler'-Meldung einfliesst
      statt spurlos zu verschwinden (`chat_bruecke.ChatProzess._mit_stderr`).
  echo   -- spiegelt den empfangenen Nutzertext als EIN Delta zurueck -- prueft, was tatsaechlich
      ans Kind geschickt wurde (Kontextzeile beim ersten Turn, reiner Text danach).
  thinking_lang -- zwei thinking_delta-Ereignisse mit Pause dazwischen, danach EIN Text-Delta +
      result (Requesty/GLM-5.3-flash liefert real erst einen Denk-Block, dann Text) -- prueft,
      dass JEDES stream_event (nicht nur text_delta) die Zeitlimit-Deadline verlaengert, ein
      langer Denk-Block also nicht faelschlich als 'haengt' gemeldet wird.
"""
import json
import sys
import time


def _schreibe(ereignis: dict) -> None:
    sys.stdout.write(json.dumps(ereignis) + "\n")
    sys.stdout.flush()


def _delta(text: str) -> None:
    _schreibe({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": text}}})


def _turn_normal(_zeile: str) -> None:
    _delta("Hallo, ")
    _delta("das ist die Fake-Antwort.")
    _schreibe({"type": "result", "usage": {"input_tokens": 12, "output_tokens": 7}})


def _turn_crash(_zeile: str) -> None:
    _delta("Angebrochen")
    sys.exit(1)


def _turn_hang(_zeile: str) -> None:
    time.sleep(5)


def _turn_hang_stderr(_zeile: str) -> None:
    sys.stderr.write("warn: irgendein hinweis\n")
    sys.stderr.flush()
    time.sleep(5)


def _extrahiere_text(zeile: str) -> str:
    try:
        return json.loads(zeile)["message"]["content"][0]["text"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""


def _turn_echo(zeile: str) -> None:
    _delta(_extrahiere_text(zeile))
    _schreibe({"type": "result", "usage": {"input_tokens": 1, "output_tokens": 1}})


def _denk_delta() -> None:
    _schreibe({"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": "..."}}})


def _turn_thinking_lang(_zeile: str) -> None:
    _denk_delta()
    time.sleep(0.2)
    _denk_delta()
    time.sleep(0.2)
    _delta("Text nach dem Denken.")
    _schreibe({"type": "result", "usage": {"input_tokens": 3, "output_tokens": 2}})


def main() -> None:
    modus = sys.argv[1] if len(sys.argv) > 1 else "normal"
    turn = {"normal": _turn_normal, "crash": _turn_crash, "hang": _turn_hang,
            "hang_stderr": _turn_hang_stderr, "echo": _turn_echo,
            "thinking_lang": _turn_thinking_lang}[modus]
    for zeile in sys.stdin:
        if not zeile.strip():
            continue
        turn(zeile)


if __name__ == "__main__":
    main()
