"""Tiefenanalyse (Phase 3 I, CONTRACTS.md C10): vertieftes Stufe-1/2-Urteil zu EINEM Befund einer
Sitzung -- Stufe 1 (Claude) bekommt zusaetzlich den lokalen Rohausschnitt (rohdatei.py) und die
Commit-Liste (commits.py, nur Hash+Betreff), Stufe 2 (Codex) bekommt wie in pruefung.py NIE den
Rohtext. Schreibt genau ein `ereignis quelle='tiefenanalyse' typ='befund'` (Contract Tiefenanalyse).

Kein Ersatz fuer pruefung.py (Zustandsableitung C2 bleibt dort) -- reine Zusatzanalyse, die die
Stufe-2-Pflicht ueber `pruefung.stufe_fuer`/`pruefung.ist_eskaliert` wiederverwendet.
"""
from __future__ import annotations

import json
import re
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # konsenloser Dienst: Kindprozess ohne Fenster (2026-08-28)
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import chat_bruecke, commits, contracts, modell, pruefung, redaktion, regeltexte, rohdatei, vieraugen
from .vieraugen import _programm

MODELL_STUFE1_SONNET = "claude-sonnet-5"
MODELL_STUFE1_OPUS = "claude-opus-5"
ROHAUSSCHNITT_UMFANG = 10
ABLAUF_MINUTEN = 30
_MODELLE_JSON = Path(__file__).resolve().parents[1] / "modelle.json"

# Paket K (Fehlertexte-Durchreichung, Entscheid 2026-08-28 14:10): Fehlertexte von
# Werkzeugfehlern gehen zur Tiefenanalyse durch -- im Lauf aus der Rohdatei gelesen, gezielt
# redigiert, NIE gespeichert (siehe `_fehlertexte` unten).
FEHLERTEXTE_MAX_ANZAHL = 20
FEHLERTEXTE_MAX_LAENGE = 300
FEHLERTEXTE_VERMERK_GESCHUETZT = "Fehlertexte nicht verfuegbar (geschuetzt)."
FEHLERTEXTE_VERMERK_FEHLEND = "Fehlertexte nicht verfuegbar (Rohdatei fehlt)."


def _modell_ollama() -> str:
    """`default_vico_ollama` aus `scripts/modelle.json` -- die Registry bleibt Master (Memory
    modell-registry-selbstpflege), kein zweiter Default hier."""
    try:
        return json.loads(_MODELLE_JSON.read_text(encoding="utf-8")).get("default_vico_ollama", "glm-5.2:cloud")
    except (OSError, json.JSONDecodeError):
        return "glm-5.2:cloud"


def _frage_claude(text: str, modell: str, umgebung: dict | None = None, zeitlimit_s: int = 240) -> str:
    """Wie `vieraugen.frage_claude`, mit waehlbarem Modell/Umgebung (Ollama lokal bei
    `geschuetzt`, C6) -- gleiche Isolation (leerer Temp-Ordner, keine Tools)."""
    with tempfile.TemporaryDirectory() as leer:
        lauf = subprocess.run(
            [_programm("claude"), "-p", "--model", modell, "--no-session-persistence",
             "--output-format", "json", "--tools", ""],
            input=text.encode("utf-8"), capture_output=True, timeout=zeitlimit_s, cwd=leer, env=umgebung,
            creationflags=_NO_WINDOW,
        )
    if lauf.returncode != 0:
        raise RuntimeError("claude: " + lauf.stderr.decode("utf-8", "replace")[:300])
    antwort = json.loads(lauf.stdout.decode("utf-8", "replace"))
    return antwort.get("result", "") if isinstance(antwort, dict) else ""


def frage_claude_cloud(text: str, modell: str) -> str:
    return _frage_claude(text, modell)


def frage_claude_lokal(text: str) -> str:
    return _frage_claude(text, _modell_ollama(), chat_bruecke._umgebung("ollama"))


# ---------------------------------------------------------------------------------------------
# Prompts + Parser
# ---------------------------------------------------------------------------------------------

def _commit_zeilen_text(commit_liste: list[dict]) -> str:
    return "\n".join(f"- {c['hash'][:8]} {c['betreff']}" for c in commit_liste) or "keine"


def _rohausschnitt_text(rohausschnitt: list[dict]) -> str:
    return "\n".join(f"[{z['index']}] {z['typ']}: {z['text']}" for z in rohausschnitt) or "kein Ausschnitt"


def _fehlertexte_text(fehlertexte: list[str] | None, vermerk: str) -> str:
    if vermerk:
        return vermerk
    if not fehlertexte:
        return "keine"
    return "\n".join(f"- {t}" for t in fehlertexte)


def prompt_stufe1(dokument: dict, rohausschnitt: list[dict], commit_liste: list[dict],
                   regeltext: dict, signatur: str, fehlertexte: list[str] | None = None,
                   fehlertexte_vermerk: str = "") -> str:
    return (
        f"Du fuehrst eine Tiefenanalyse EINES Befundes eines Sitzungsbelegs durch (Signatur "
        f"{signatur}). Regelbedeutung: {regeltext.get('bedeutung', '')}\n\n"
        "Lokaler Rohausschnitt (redigiert, NUR fuer diese Analyse):\n" + _rohausschnitt_text(rohausschnitt) + "\n\n"
        "Werkzeugfehler-Rohtexte (redigiert, NUR fuer diese Analyse, nie gespeichert):\n"
        + _fehlertexte_text(fehlertexte, fehlertexte_vermerk) + "\n\n"
        "Commits im Sitzungszeitfenster (Hash + Betreff, kein Diff):\n" + _commit_zeilen_text(commit_liste) + "\n\n"
        "Beleg (Kennzahlen):\n" + json.dumps(dokument, ensure_ascii=False, indent=1) + "\n\n"
        "Antworte NUR mit einem JSON-Objekt:\n"
        '{"ursache_kategorie": "<kurz>", "befund": "<max 400 Zeichen>", "empfehlung": "<kurz>", '
        '"urteil": "ja|nein|unklar", "komplexitaet": "einfach|komplex"}\n'
    )


def prompt_stufe2(dokument: dict, stufe1: dict) -> str:
    """Stufe 2 (Codex): bekommt NIE den Rohausschnitt/die Commit-Liste -- nur redigierten Beleg
    + redigierte Stufe-1-Ausgabe (Codex-rote-Linie 1, wie `pruefung.prompt_stufe2`)."""
    return (
        "Du bist die unabhaengige Zweitmeinung zu einer Tiefenanalyse eines Sitzungsbelegs.\n"
        "Stufe-1-Analyse:\n" + json.dumps(stufe1, ensure_ascii=False, indent=1) + "\n\n"
        "Beleg (Kennzahlen):\n" + json.dumps(dokument, ensure_ascii=False, indent=1) + "\n\n"
        "Antworte NUR mit einem JSON-Objekt:\n"
        '{"ursache_kategorie": "<kurz>", "befund": "<max 400 Zeichen>", "empfehlung": "<kurz>", '
        '"urteil": "ja|nein|unklar"}\n'
    )


def _json_objekt(text: str) -> dict:
    treffer = re.search(r"\{.*\}", text, re.DOTALL)
    if not treffer:
        return {}
    try:
        roh = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return {}
    return roh if isinstance(roh, dict) else {}


def _kuerzen(wert, max_laenge: int = contracts.MAX_TEXT) -> str:
    if not wert:
        return ""
    return redaktion.bereinige_text(str(wert)[:max_laenge])


def _seite_normiert(u: dict, mit_komplexitaet: bool) -> dict:
    urteil = str(u.get("urteil", "unklar")).lower()
    seite = {
        "ursache_kategorie": _kuerzen(u.get("ursache_kategorie")), "befund": _kuerzen(u.get("befund")),
        "empfehlung": _kuerzen(u.get("empfehlung")),
        "urteil": urteil if urteil in vieraugen.ZUSTIMMUNGEN else "unklar",
    }
    if mit_komplexitaet:
        komplexitaet = str(u.get("komplexitaet", "komplex")).lower()
        seite["komplexitaet"] = komplexitaet if komplexitaet in ("einfach", "komplex") else "komplex"
    return seite


def urteil_stufe1_aus_text(text: str) -> dict:
    return _seite_normiert(_json_objekt(text), mit_komplexitaet=True)


def urteil_stufe2_aus_text(text: str) -> dict:
    return _seite_normiert(_json_objekt(text), mit_komplexitaet=False)


# ---------------------------------------------------------------------------------------------
# Konsensregel (C10, deterministisch)
# ---------------------------------------------------------------------------------------------

_SATZZEICHEN = re.compile(r"[^\w\s]", re.UNICODE)


def _kategorie_normiert(text: str) -> str:
    return re.sub(r"\s+", " ", _SATZZEICHEN.sub("", (text or "").lower())).strip()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    vorherige = list(range(len(b) + 1))
    for i, za in enumerate(a, 1):
        aktuelle = [i] + [0] * len(b)
        for j, zb in enumerate(b, 1):
            kosten = 0 if za == zb else 1
            aktuelle[j] = min(vorherige[j] + 1, aktuelle[j - 1] + 1, vorherige[j - 1] + kosten)
        vorherige = aktuelle
    return vorherige[-1]


def kategorien_gleich(a: str, b: str) -> bool:
    na, nb = _kategorie_normiert(a), _kategorie_normiert(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return _levenshtein(na, nb) <= 3


def konsens(claude: dict, codex: dict | None) -> str:
    """C10 Konsensregel: gleiche Kategorie (normalisiert, Levenshtein <= 3 oder Teilstring) UND
    gleiches Urteil -> uebereinstimmend; `unklar` auf EINER Seite -> immer dissens; sonst dissens.
    Ohne Stufe 2 -> ohne_zweitmeinung."""
    if codex is None:
        return "ohne_zweitmeinung"
    if claude["urteil"] == "unklar" or codex["urteil"] == "unklar":
        return "dissens"
    if claude["urteil"] == codex["urteil"] and kategorien_gleich(claude["ursache_kategorie"], codex["ursache_kategorie"]):
        return "uebereinstimmend"
    return "dissens"


# ---------------------------------------------------------------------------------------------
# Lauf-Registry (C10): kleiner Schluesselraum (sitzung_logisch, signatur) -- Status wird ueber
# `signatur` abgefragt, kein eigenes `lauf_id`-Resource wie bei pruefung.py noetig.
# ---------------------------------------------------------------------------------------------

_laufend: dict[tuple[int, str], datetime] = {}
_lock = threading.Lock()


def registriere_lauf(sitzung_logisch: int, signatur: str, jetzt: datetime | None = None) -> bool:
    """True = registriert; False = es laeuft schon eine Analyse fuer diese (Sitzung, Signatur)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    grenze = jetzt - timedelta(minutes=ABLAUF_MINUTEN)
    with _lock:
        bestehend = _laufend.get((sitzung_logisch, signatur))
        if bestehend is not None and bestehend >= grenze:
            return False
        _laufend[(sitzung_logisch, signatur)] = jetzt
        return True


def freigeben(sitzung_logisch: int, signatur: str) -> None:
    with _lock:
        _laufend.pop((sitzung_logisch, signatur), None)


def laeuft_seit(sitzung_logisch: int, signatur: str) -> str | None:
    with _lock:
        gestartet = _laufend.get((sitzung_logisch, signatur))
    return gestartet.isoformat() if gestartet else None


# ---------------------------------------------------------------------------------------------
# Lauf-Ausfuehrung
# ---------------------------------------------------------------------------------------------

def _dokument_kompakt(dokument: dict) -> dict:
    return {
        "kopf": dokument.get("kopf", {}), "erfassung": dokument.get("erfassung", {}),
        "kennzahlen": dokument.get("kennzahlen", {}), "auffaelligkeiten": dokument.get("auffaelligkeiten", []),
    }


def _rohausschnitt(dokument: dict, position: int, quelle: str, sitzung_id: str) -> list[dict]:
    ereignisse = dokument.get("ereignisse", [])
    zeit = ereignisse[position].get("zeit") if 0 <= position < len(ereignisse) else None
    try:
        return rohdatei.baue_antwort(quelle, sitzung_id, zeit, position, ROHAUSSCHNITT_UMFANG)["zeilen"]
    except rohdatei.RohdateiFehler:
        return []


def _modell_stufe1(schwere: str) -> str:
    return MODELL_STUFE1_OPUS if schwere == "hoch" else MODELL_STUFE1_SONNET


def _kappen_fehlertext(text: str) -> str:
    """Hart kappen bei FEHLERTEXTE_MAX_LAENGE Zeichen mit '…' -- kein Wortgrenzen-Versuch, der
    Text ist ohnehin nur ein Rohausschnitt fuer den Prompt (Paket K)."""
    text = (text or "").strip()
    if len(text) <= FEHLERTEXTE_MAX_LAENGE:
        return text
    return text[:FEHLERTEXTE_MAX_LAENGE - 1].rstrip() + "…"


def _fehler_positionen(ereignisse: list[dict]) -> list[int]:
    """Indizes der Werkzeugfehler (`tool_ergebnis`, `fehler=True`) in der Ereignisliste --
    chronologisch, gekappt auf FEHLERTEXTE_MAX_ANZAHL (Paket K)."""
    treffer = [i for i, e in enumerate(ereignisse)
               if e.get("art") == modell.ART_TOOL_ERGEBNIS and e.get("fehler")]
    return treffer[:FEHLERTEXTE_MAX_ANZAHL]


def _fehlertexte_erlaubt(dokument: dict, nur_lokal: bool) -> bool:
    """C6-Weiche wie beim Rohdatei-Zugriff (`redaktion.zulaessigkeit`) -- eigener, vom
    Aufrufer-Flag `nur_lokal` UNABHAENGIGER Check (Sicherheitsnetz, nicht nur den Flag glauben):
    bei `geschuetzt` nur erlaubt, wenn der Lauf sowieso lokal (Ollama) laeuft."""
    return nur_lokal or redaktion.zulaessigkeit(dokument) == "cloud-ok"


def _fehlertexte(dokument: dict, quelle: str, sitzung_id: str, nur_lokal: bool) -> tuple[list[str], str]:
    """Sammelt bis zu FEHLERTEXTE_MAX_ANZAHL Werkzeugfehler-Rohtexte direkt aus der Rohdatei fuer
    den Stufe-1-Prompt (Paket K, Entscheid 2026-08-28 14:10) -- NIE gespeichert, nur im
    Arbeitsspeicher dieses Laufs. Fail-open: `geschuetzt` ohne lokalen Weg oder eine fehlende/
    verschobene Rohdatei liefern eine leere Liste + Vermerk statt eines Fehlers -- die
    Tiefenanalyse laeuft dann ohne Fehlertexte weiter."""
    if not _fehlertexte_erlaubt(dokument, nur_lokal):
        return [], FEHLERTEXTE_VERMERK_GESCHUETZT
    positionen = _fehler_positionen(dokument.get("ereignisse", []))
    if not positionen:
        return [], ""
    ereignisse = dokument["ereignisse"]
    try:
        zeilen = [rohdatei.zeile_bei(quelle, sitzung_id, ereignisse[i].get("zeit"), i) for i in positionen]
    except rohdatei.RohdateiFehler:
        return [], FEHLERTEXTE_VERMERK_FEHLEND
    texte = [_kappen_fehlertext(redaktion.bereinige_fehlertext(z["text"])) for z in zeilen if z and z.get("text")]
    return texte, ""


def _stufe1(dokument: dict, signatur: str, position: int, quelle: str, sitzung_id: str, auff: dict,
            nur_lokal: bool, frager_cloud, frager_lokal) -> tuple[dict, str, list[dict], list[dict]]:
    rohausschnitt = _rohausschnitt(dokument, position, quelle, sitzung_id)
    fehlertexte, fehlertexte_vermerk = _fehlertexte(dokument, quelle, sitzung_id, nur_lokal)
    commit_liste = commits.liste(quelle, sitzung_id, dokument.get("kopf", {}).get("start", ""),
                                  dokument.get("kopf", {}).get("ende", ""))
    regeltext = regeltexte.text_fuer(auff.get("regel", ""))
    kompakt = _dokument_kompakt(dokument)
    prompt = prompt_stufe1(kompakt, rohausschnitt, commit_liste, regeltext, signatur,
                            fehlertexte, fehlertexte_vermerk)
    if nur_lokal:
        return urteil_stufe1_aus_text(frager_lokal(prompt)), _modell_ollama(), rohausschnitt, commit_liste
    modell_name = _modell_stufe1(auff.get("schwere", "hoch"))
    return urteil_stufe1_aus_text(frager_cloud(prompt, modell_name)), modell_name, rohausschnitt, commit_liste


def _befund_fuer_stufe(auff: dict, u1: dict) -> dict:
    return {
        "signatur": auff.get("signatur", ""), "regel": auff.get("regel", ""),
        "schwere": auff.get("schwere", "hoch"), "komplexitaet": u1.get("komplexitaet"),
        "urteil_stufe1": u1.get("urteil"), "scope": "befund", "rueckfall": False,
    }


def _stufe2(dokument: dict, u1: dict, auff: dict, nur_lokal: bool, historie: list[dict],
            frager_codex, stufe_fuer_fn) -> tuple[dict | None, bool]:
    befund = _befund_fuer_stufe(auff, u1)
    eskaliert = pruefung.ist_eskaliert(befund, historie or [])
    if nur_lokal or stufe_fuer_fn(befund, historie or []) != 2:
        return None, eskaliert
    text = frager_codex(prompt_stufe2(_dokument_kompakt(dokument), u1))
    return urteil_stufe2_aus_text(text), eskaliert


def _detail(signatur: str, sitzung_logisch: int, position: int, runde: int, u1: dict,
            u2: dict | None, modell1: str, nur_lokal: bool, commit_liste: list[dict],
            gestartet: datetime, fehler: str | None = None) -> dict:
    urteil = "ohne_zweitmeinung" if u2 is None else konsens(u1, u2)
    dauer_ms = int((datetime.now(timezone.utc) - gestartet).total_seconds() * 1000)
    return {
        "schema": 1, "scope": "befund", "signatur": signatur, "sitzung_logisch": sitzung_logisch,
        "position": position, "runde": runde, "stufe": 2 if u2 else 1,
        "ursache_kategorie": u1.get("ursache_kategorie", ""), "befund": u1.get("befund", ""),
        "empfehlung": u1.get("empfehlung", ""), "urteil": urteil,
        "positionen": {"claude": u1 or None, "codex": u2}, "modell": modell1,
        "modell_stufe2": pruefung.MODELL_STUFE2 if u2 else None,
        "redaktion_version": redaktion.REDAKTION_VERSION, "zeitstempel": gestartet.isoformat(),
        "dauer_ms": dauer_ms, "commits": [c["hash"] for c in commit_liste], "nur_lokal": nur_lokal,
        "fehler": fehler,
    }


def _leere_seite() -> dict:
    return {"ursache_kategorie": "", "befund": "", "empfehlung": "", "urteil": "unklar", "komplexitaet": "komplex"}


def _lauf_versuch(dokument, auff, signatur, position, runde, sitzung_logisch, quelle, sitzung_id,
                   nur_lokal, historie, gestartet, frager_cloud, frager_lokal, frager_codex, stufe_fuer_fn) -> dict:
    try:
        u1, modell1, _roh, commit_liste = _stufe1(
            dokument, signatur, position, quelle, sitzung_id, auff, nur_lokal, frager_cloud, frager_lokal
        )
        u2, _eskaliert = _stufe2(dokument, u1, auff, nur_lokal, historie, frager_codex, stufe_fuer_fn)
        return _detail(signatur, sitzung_logisch, position, runde, u1, u2, modell1, nur_lokal, commit_liste, gestartet)
    except Exception as fehler:  # Fremdprozess (claude/codex): berichten, nie verschlucken
        fehlertext = _kuerzen(f"{type(fehler).__name__}: {fehler}")
        return _detail(signatur, sitzung_logisch, position, runde, _leere_seite(), None,
                        "", nur_lokal, [], gestartet, fehler=fehlertext)


def lauf_ausfuehren(
    dokument: dict, auff: dict, signatur: str, position: int, runde: int, sitzung_logisch: int,
    quelle: str, sitzung_id: str, nur_lokal: bool, historie: list[dict], ereignis_schreiben,
    frager_cloud=frage_claude_cloud, frager_lokal=frage_claude_lokal, frager_codex=vieraugen.frage_codex,
    stufe_fuer_fn=pruefung.stufe_fuer,
) -> dict:
    """C10: Stufe 1 (+2), schreibt GENAU EIN `tiefenanalyse/befund`-Ereignis (auch bei Fehler),
    laeuft im Hintergrund-Thread wie `_pruefen_hintergrund` -- ein Fehler darf ihn nie stoeren."""
    detail = _lauf_versuch(
        dokument, auff, signatur, position, runde, sitzung_logisch, quelle, sitzung_id, nur_lokal,
        historie, datetime.now(timezone.utc), frager_cloud, frager_lokal, frager_codex, stufe_fuer_fn,
    )
    ereignis_schreiben("tiefenanalyse", "befund", detail)
    return detail
