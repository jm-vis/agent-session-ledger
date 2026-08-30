"""Vier-Augen-Prüfung (Plan D): deterministischer Befund + zwei unabhängige Modellurteile.

Eingabe für beide Modelle ist NUR das kompakte Beleg-Dokument (Zahlen, Typen,
Signaturen) — nie ein Rohtranskript (Codex-rote-Linie 1). Beide laufen als
Fremdprozess in einem leeren Temp-Ordner (kein Repo, keine Hooks, kein Kontext).
Claude: `claude -p --model sonnet --tools ""` · Codex: `codex exec --sandbox read-only`.
Abgleich: gleiche Zustimmung = bestätigt/verworfen · abweichend = Dissens (Maintainer).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # konsenloser Dienst: Kindprozess ohne Fenster (2026-08-28)
import tempfile
from pathlib import Path

from . import redaktion
from .modell import Beleg

ZUSTIMMUNGEN = ("ja", "nein", "unklar")
MAX_TEXT = redaktion.MAX_LAENGE  # 80: Modelltext hält dieselbe Grenze wie der Beleg


def dokument_kompakt(beleg: Beleg) -> dict:
    """Beleg ohne Ereignis-Zeitleiste (< 3k Token): Kopf, Erfassung, Kennzahlen,
    Auffälligkeiten, Subagenten-Zusammenfassung."""
    d = beleg.als_dict()
    return {
        "kopf": d["kopf"], "erfassung": d["erfassung"], "kennzahlen": d["kennzahlen"],
        "auffaelligkeiten": d["auffaelligkeiten"],
        "subagenten": [
            {k: s[k] for k in ("typ", "modell", "tiefe", "dauer_ms", "tools", "tool_fehler",
                               "beleg", "ergebnis")}
            for s in d["subagenten"]
        ],
    }


def prompt(dokument: dict) -> str:
    return (
        "Du prüfst den Beleg einer KI-Agenten-Sitzung (nur Kennzahlen, keine Inhalte).\n"
        "Beurteile JEDE Auffälligkeit unter `auffaelligkeiten` unabhängig: Ist sie ein echtes "
        "Problem (ja), ein Fehlalarm (nein) oder aus den Zahlen nicht entscheidbar (unklar)?\n"
        "Nenne zusätzlich höchstens zwei eigene Befunde mit regel 'zusatz:<kurz>'.\n"
        "Antworte NUR mit einem JSON-Array, keine Erklärung außerhalb:\n"
        '[{"regel": "<regel>", "signatur": "<signatur>", "zustimmung": "ja|nein|unklar", '
        '"schwere": "hinweis|warnung|hoch", "begruendung": "<max 80 Zeichen>", '
        '"vorschlag": "<max 80 Zeichen, konkrete Maßnahme oder leer>"}]\n\n'
        "Beleg:\n" + json.dumps(dokument, ensure_ascii=False, indent=1)
    )


def _programm(name: str) -> str:
    pfad = shutil.which(name)
    if not pfad:
        raise FileNotFoundError(f"{name} nicht im PATH")
    return pfad


def frage_claude(text: str, zeitlimit_s: int = 240) -> str:
    """Sonnet-Subagent als Fremdprozess in leerem Ordner (kein Projekt-CLAUDE.md, keine Tools)."""
    with tempfile.TemporaryDirectory() as leer:
        lauf = subprocess.run(
            # kein --bare: das kappt die Anmeldung ("Not logged in", gemessen 2026-08-25)
            [_programm("claude"), "-p", "--model", "sonnet", "--no-session-persistence",
             "--output-format", "json", "--tools", ""],
            input=text.encode("utf-8"), capture_output=True, timeout=zeitlimit_s, cwd=leer,
            creationflags=_NO_WINDOW,
        )
    if lauf.returncode != 0:
        raise RuntimeError("claude: " + lauf.stderr.decode("utf-8", "replace")[:300])
    antwort = json.loads(lauf.stdout.decode("utf-8", "replace"))
    return antwort.get("result", "") if isinstance(antwort, dict) else ""


def frage_codex(text: str, zeitlimit_s: int = 600) -> str:
    """Codex read-only in leerem Ordner; nur das Dokument als Eingabe (rote Linie 1)."""
    with tempfile.TemporaryDirectory() as leer:
        ausgabe = Path(leer) / "urteil.md"
        lauf = subprocess.run(
            [_programm("codex"), "exec", "--sandbox", "read-only", "--skip-git-repo-check",
             "--ephemeral", "-C", leer, "-o", str(ausgabe), "-"],
            input=text.encode("utf-8"), capture_output=True, timeout=zeitlimit_s, cwd=leer,
            creationflags=_NO_WINDOW,
        )
        if lauf.returncode != 0:
            raise RuntimeError("codex: " + lauf.stderr.decode("utf-8", "replace")[:300])
        return ausgabe.read_text(encoding="utf-8") if ausgabe.exists() else ""


def _kuerze(wert) -> str:
    """Kürzt Modelltext und redigiert Pfade/Secrets/E-Mails (Modelle könnten sie erfinden)."""
    if wert is None:
        return ""
    text = str(wert)[:MAX_TEXT]
    return redaktion.REDIGIERT if redaktion._pruefe_string(text) else text


def urteile_aus_text(text: str) -> list[dict]:
    """Erstes JSON-Array im Text (auch in ```-Zäunen); ungültig -> leere Liste."""
    treffer = re.search(r"\[.*\]", text, re.DOTALL)
    if not treffer:
        return []
    try:
        roh = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return []
    urteile = []
    for u in roh if isinstance(roh, list) else []:
        if not isinstance(u, dict):
            continue
        zustimmung = str(u.get("zustimmung", "unklar")).lower()
        urteile.append({
            "regel": _kuerze(u.get("regel")), "signatur": _kuerze(u.get("signatur")),
            "zustimmung": zustimmung if zustimmung in ZUSTIMMUNGEN else "unklar",
            "schwere": _kuerze(u.get("schwere")), "begruendung": _kuerze(u.get("begruendung")),
            "vorschlag": _kuerze(u.get("vorschlag")),
        })
    return urteile


def _finde(urteile: list[dict], regel: str, signatur: str) -> dict | None:
    for u in urteile:
        if u["signatur"] == signatur or (not u["signatur"] and u["regel"] == regel):
            return u
    return None


def _status(a: str, b: str) -> str:
    """Gleiche Zustimmung -> bestaetigt/verworfen/unklar; jede Abweichung -> dissens (Maintainer)."""
    if a != b:
        return "dissens"
    return {"ja": "bestaetigt", "nein": "verworfen"}.get(a, "unklar")


def vergleiche(beleg: Beleg, claude: list[dict], codex: list[dict]) -> list[dict]:
    """Je deterministischem Befund: beide Urteile + Status."""
    ergebnis = []
    for a in beleg.auffaelligkeiten:
        uc = _finde(claude, a.regel, a.signatur) or {"zustimmung": "unklar"}
        ux = _finde(codex, a.regel, a.signatur) or {"zustimmung": "unklar"}
        ergebnis.append({
            "regel": a.regel, "signatur": a.signatur, "wert": a.wert, "schwere": a.schwere,
            "claude": uc.get("zustimmung", "unklar"), "codex": ux.get("zustimmung", "unklar"),
            "status": _status(uc.get("zustimmung", "unklar"), ux.get("zustimmung", "unklar")),
            "begruendung_claude": uc.get("begruendung", ""), "begruendung_codex": ux.get("begruendung", ""),
            "vorschlag_claude": uc.get("vorschlag", ""), "vorschlag_codex": ux.get("vorschlag", ""),
        })
    return ergebnis


def zusatzbefunde(claude: list[dict], codex: list[dict]) -> list[dict]:
    return [{"quelle": q, **u} for q, liste in (("claude", claude), ("codex", codex))
            for u in liste if u["regel"].startswith("zusatz:")]


def review(beleg: Beleg, frager_claude=frage_claude, frager_codex=frage_codex) -> dict:
    """Führt beide Urteile aus und gleicht ab. Fehler eines Fragers -> dessen Urteile leer."""
    text = prompt(dokument_kompakt(beleg))
    urteile, fehler = {}, {}
    for name, frager in (("claude", frager_claude), ("codex", frager_codex)):
        try:
            urteile[name] = urteile_aus_text(frager(text))
        except Exception as e:  # Fremdprozess: jeder Fehler wird berichtet, nie verschluckt
            urteile[name], fehler[name] = [], f"{type(e).__name__}: {str(e)[:200]}"
    befunde = vergleiche(beleg, urteile["claude"], urteile["codex"])
    return {
        "sitzung_id": beleg.kopf.sitzung_id, "quelle": beleg.kopf.quelle, "befunde": befunde,
        "zusatz": zusatzbefunde(urteile["claude"], urteile["codex"]), "fehler": fehler,
        "dissens": sum(1 for b in befunde if b["status"] == "dissens"),
    }


def als_markdown(ergebnis: dict) -> str:
    zeilen = [f"# Vier-Augen — {ergebnis['sitzung_id']} ({ergebnis['quelle']})", "",
              "| Befund | Wert | Claude | Codex | Ergebnis |", "| --- | --- | --- | --- | --- |"]
    for b in ergebnis["befunde"]:
        zeilen.append(f"| {b['regel']} | {b['wert']} | {b['claude']} | {b['codex']} | **{b['status']}** |")
    for b in ergebnis["befunde"]:
        if b["status"] == "dissens":
            zeilen += ["", f"**Dissens {b['regel']}** — Claude: {b['begruendung_claude']} · "
                       f"Codex: {b['begruendung_codex']} → Entscheidung Maintainer."]
    if ergebnis["zusatz"]:
        zeilen += ["", "## Zusatzbefunde"] + [
            f"- [{z['quelle']}] {z['regel']}: {z['begruendung']}" for z in ergebnis["zusatz"]]
    if ergebnis["fehler"]:
        zeilen += ["", "## Nicht befragt"] + [f"- {k}: {v}" for k, v in ergebnis["fehler"].items()]
    zeilen += ["", f"Dissens: {ergebnis['dissens']} · Dieser Bericht enthält keine Sitzungsinhalte."]
    return "\n".join(zeilen)
