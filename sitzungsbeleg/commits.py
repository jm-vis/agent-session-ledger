"""Commits im Sitzungszeitfenster (Phase 3 I, CONTRACTS.md C10): Vorher/Nachher-Liste + Diff aus
dem lokalen Git-Repo einer Sitzung. NUR lesend (`git log`/`git show`), NIE gespeichert, NIE an ein
Modell -- ausser der Hash+Betreff-Liste, die Stufe 1 der Tiefenanalyse als Kontext bekommt (der
Diff geht in KEINEN Prompt). Dieses Modul ruft `speicher.*` nie auf (Guard wie `rohdatei.py`).

`cwd` kommt aus `rohdatei.cwd_aus_transkript()` (roher Arbeitsordner aus der Transkriptzeile) --
verlaesst diesen Prozess nie, geht nur als `cwd=` an `subprocess.run`.
"""
from __future__ import annotations

import re
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # konsenloser Dienst: Kindprozess ohne Fenster (2026-08-28)
from datetime import datetime, timedelta, timezone

from . import redaktion, rohdatei

MAX_COMMITS = 30
MAX_DIFF_ZEILEN = 400
NACHLAUF_MINUTEN = 15
ZEITLIMIT_S = 15
_HASH_MUSTER = re.compile(r"^[0-9a-f]{7,40}$")
_FELD_TRENNER = "\x1f"


class CommitsFehler(Exception):
    """Kein Repo/Projektpfad, `git` nicht ausfuehrbar, unbekannter/ungueltiger Hash -- der
    Aufrufer (web.py) macht daraus eine leere Liste (Liste) bzw. 404 (Diff)."""


def _git(cwd: str, *args: str, laufer=subprocess.run) -> str:
    """`stdin=DEVNULL` ist Pflicht: der Dashboard-Dienst laeuft konsolenlos (FreeConsole), ein
    geerbtes Stdin-Handle ist dort ungueltig -> `[WinError 6]` bei jedem `git`-Aufruf
    (Befund 2026-08-28, Sicht: 'Keine Commits im Zeitfenster' trotz 30 Treffern im Terminal)."""
    try:
        lauf = laufer(
            ["git", *args], cwd=cwd, capture_output=True, timeout=ZEITLIMIT_S,
            text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise CommitsFehler(f"git nicht ausfuehrbar: {type(fehler).__name__}") from fehler
    if lauf.returncode != 0:
        raise CommitsFehler(lauf.stderr.strip()[:300])
    return lauf.stdout


def _cwd_fuer(quelle: str, sitzung_id: str) -> str:
    cwd = rohdatei.cwd_aus_transkript(quelle, sitzung_id)
    if not cwd:
        raise CommitsFehler("kein Projektpfad im Transkript")
    return cwd


def _bis_iso(ende: str) -> str:
    if not ende:
        return datetime.now(timezone.utc).isoformat()
    zeit = datetime.fromisoformat(ende.replace("Z", "+00:00"))
    return (zeit + timedelta(minutes=NACHLAUF_MINUTEN)).isoformat()


def _zeile_zu_commit(zeile: str) -> dict | None:
    teile = zeile.split(_FELD_TRENNER, 2)
    if len(teile) != 3 or not teile[0]:
        return None
    hash_, zeit, betreff = teile
    return {"hash": hash_, "zeit": zeit, "betreff": redaktion.bereinige_text(betreff[:300])}


def liste(quelle: str, sitzung_id: str, start: str, ende: str) -> list[dict]:
    """C10 `GET …/commits`: `{hash, zeit, betreff}` im Zeitfenster [start, ende+15min],
    redigiert, max. 30, neueste zuerst. Kein Repo/Treffer -> leere Liste (kein Fehler nach
    aussen, Wunsch: die Sitzung soll trotzdem anzeigbar bleiben)."""
    try:
        cwd = _cwd_fuer(quelle, sitzung_id)
        ausgabe = _git(
            cwd, "log", f"--since={start or '1970-01-01'}", f"--until={_bis_iso(ende)}",
            "--pretty=format:%H" + _FELD_TRENNER + "%aI" + _FELD_TRENNER + "%s",
            f"-{MAX_COMMITS}",
        )
    except CommitsFehler:
        return []
    zeilen = [z for z in (_zeile_zu_commit(r) for r in ausgabe.splitlines()) if z]
    return zeilen[:MAX_COMMITS]


def _hash_geprueft(commit_hash: str) -> str:
    if not _HASH_MUSTER.match(commit_hash or ""):
        raise CommitsFehler("ungueltiger Commit-Hash")
    return commit_hash


def diff(quelle: str, sitzung_id: str, commit_hash: str) -> str:
    """C10 `GET …/commits/{hash}`: `git show --stat -p`, auf `MAX_DIFF_ZEILEN` gekuerzt, JEDE
    Zeile durch `redaktion.bereinige_text()`. Wirft `CommitsFehler` bei Repo-/Hash-Problemen
    (Aufrufer macht daraus 404)."""
    cwd = _cwd_fuer(quelle, sitzung_id)
    ausgabe = _git(cwd, "show", "--stat", "-p", _hash_geprueft(commit_hash))
    zeilen = [redaktion.bereinige_text(z) for z in ausgabe.splitlines()[:MAX_DIFF_ZEILEN]]
    return "\n".join(zeilen)
