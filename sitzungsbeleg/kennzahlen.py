"""Kennzahlen-Verdichtung: aus ereignissen/subagenten -> Kennzahlen (nie Inhalte).

`berechne()` liest nur Zahlen/Typen/Zeiten/Verweise aus einem Beleg und füllt
`beleg.kennzahlen`. Keine Rohtexte werden angefasst oder erzeugt.
"""
from __future__ import annotations

import math
from datetime import datetime

from .modell import (
    ART_ASSISTENT,
    ART_COMPACTION,
    ART_NUTZER,
    ART_RUNDE_ENDE,
    ART_TOOL,
    ART_TOOL_ERGEBNIS,
    Beleg,
    Ereignis,
    Subagent,
    Token,
)

# Tool-Typen, die eine Datei verändern (für rework_dateien in den Kennzahlen).
REWORK_TYPEN = {"Edit", "Write", "MultiEdit"}
# Änderungen plus reine Bezüge (Lesen zählt als Bezug, nicht als Änderung).
BEZUG_TYPEN = REWORK_TYPEN | {"Read"}


def _parse_zeit(wert: str) -> datetime | None:
    """Parst ISO-8601 mit 'Z' oder Offset. Leerer/ungültiger Wert -> None (F7:
    nie ein Absturz bei kaputtem Zeitstempel)."""
    if not wert:
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _zeit_ungueltig(kopf) -> bool:
    """True, wenn kopf.start/kopf.ende gesetzt, aber nicht parsbar sind (F7)."""
    return any(wert and _parse_zeit(wert) is None for wert in (kopf.start, kopf.ende))


def _perzentil(werte: list[int], p: float) -> int:
    """Nearest-Rank-Perzentil (1-indexiert, aufgerundet). Leere Liste -> 0."""
    if not werte:
        return 0
    sortiert = sorted(werte)
    rang = max(1, math.ceil(p / 100 * len(sortiert)))
    return sortiert[min(rang, len(sortiert)) - 1]


def _dauer_ms(kopf) -> int:
    start = _parse_zeit(kopf.start)
    ende = _parse_zeit(kopf.ende)
    if start is None or ende is None:
        return 0
    return int((ende - start).total_seconds() * 1000)


def _letztes_tool_vor(ereignisse: list[Ereignis], index: int) -> Ereignis | None:
    for i in range(index - 1, -1, -1):
        if ereignisse[i].art == ART_TOOL:
            return ereignisse[i]
    return None


def _tool_name_je_ref(ereignisse: list[Ereignis]) -> dict[str, str]:
    ref_name: dict[str, str] = {}
    for e in ereignisse:
        if e.art == ART_TOOL and e.ref:
            ref_name[e.ref] = e.name
    return ref_name


def _tools_zaehlen(
    ereignisse: list[Ereignis],
) -> tuple[int, dict[str, int], int, dict[str, int]]:
    """Zählt Tool-Aufrufe/Fehler je Typ. Fehler->Typ über ref, sonst letztes ART_TOOL davor."""
    tools = 0
    tools_je_typ: dict[str, int] = {}
    tool_fehler = 0
    tool_fehler_je_typ: dict[str, int] = {}
    ref_name = _tool_name_je_ref(ereignisse)

    for i, e in enumerate(ereignisse):
        if e.art == ART_TOOL:
            tools += 1
            tools_je_typ[e.name] = tools_je_typ.get(e.name, 0) + 1
        elif e.art == ART_TOOL_ERGEBNIS and e.fehler:
            tool_fehler += 1
            name = ref_name.get(e.ref) if e.ref else None
            if not name:
                voriges = _letztes_tool_vor(ereignisse, i)
                name = voriges.name if voriges else ""
            if name:
                tool_fehler_je_typ[name] = tool_fehler_je_typ.get(name, 0) + 1
    return tools, tools_je_typ, tool_fehler, tool_fehler_je_typ


def _rework_dateien(ereignisse: list[Ereignis]) -> dict[str, int]:
    """signatur-Zähler der veränderenden Tools (Datei-Hash), nur ab 2 Änderungen.

    Gruppiert über ``signatur`` (Datei-Hash), nicht über ``ref`` — ``ref`` ist
    seit F4 der tool_use_id je Aufruf, also je Tool-Aufruf eindeutig.
    """
    zaehler: dict[str, int] = {}
    for e in ereignisse:
        if e.art == ART_TOOL and e.name in REWORK_TYPEN and e.signatur:
            zaehler[e.signatur] = zaehler.get(e.signatur, 0) + 1
    return {signatur: n for signatur, n in zaehler.items() if n >= 2}


def _token_summe(ereignisse: list[Ereignis]) -> tuple[Token, int]:
    summe = Token()
    thinking_bloecke = 0
    for e in ereignisse:
        if e.art == ART_ASSISTENT and e.token is not None:
            summe.add(e.token)
            if e.token.thinking > 0:
                thinking_bloecke += 1
    return summe, thinking_bloecke


def _token_kosten(token: Token, satz: dict) -> float:
    """Ein Token-Zähler × Preissatz (Input/Output/Cache) — geteilt zwischen Hauptsitzung
    und Subagenten, damit beide dieselbe Rechnung verwenden."""
    return (
        token.input * satz.get("input", 0) / 1_000_000
        + token.output * satz.get("output", 0) / 1_000_000
        + token.cache_write * satz.get("cache_write", 0) / 1_000_000
        + token.cache_read * satz.get("cache_read", 0) / 1_000_000
    )


# Dritte Stufe `meldet_als` in _preissatz (Layout-Nachlese 2026-08-28 Punkt 6, verifizierter
# Fund): Requesty meldet im Antwort-`model`-Feld das ECHTE Upstream-Modell (z. B.
# `moonshotai/Kimi-K3`), nicht die angefragte Requesty-Katalog-ID (`sference/kimi-k3`, so
# gefuehrt in modelle.json, Quelle router.requesty.ai/v1/models) -- ohne diese Stufe blieb
# `kosten_gesamt` fuer JEDE Requesty-Sitzung `None` trotz vorhandener Tokenzahlen (live an
# echten Requesty-Sitzungen nachgewiesen,
# assistant.message.model = "moonshotai/Kimi-K3").
def _preissatz(name: str, preise: dict) -> dict | None:
    """Preissatz zu einem Modellnamen: exakter Treffer, sonst Basisname vor ':' (Ollama-Cloud,
    Entscheid 2026-08-27), sonst ueber `meldet_als` (Requesty-Upstream-Alias, s. oben)."""
    if name in preise:
        return preise[name]
    basisname = name.split(":", 1)[0]
    if basisname != name and basisname in preise:
        return preise[basisname]
    for satz in preise.values():
        if name in satz.get("meldet_als", ()):
            return satz
    return None


def _kosten(ereignisse: list[Ereignis], preise: dict | None) -> float | None:
    """Token × Preistabelle je Modell (name des ART_ASSISTENT-Ereignisses) — nur Hauptsitzung."""
    if not preise:
        return None
    gesamt = 0.0
    gefunden = False
    for e in ereignisse:
        if e.art != ART_ASSISTENT or e.token is None:
            continue
        satz = _preissatz(e.name, preise)
        if not satz:
            continue
        gefunden = True
        gesamt += _token_kosten(e.token, satz)
    return gesamt if gefunden else None


def _kosten_subagenten(subagenten: list[Subagent], preise: dict | None) -> float | None:
    """Wie ``_kosten``, aber je Subagent mit dessen EIGENEM Modell (``Subagent.modell``) —
    getrennt ausgewiesen (Auftrag 2026-08-27), nicht mit der Hauptsitzung vermischt."""
    if not preise:
        return None
    gesamt = 0.0
    gefunden = False
    for s in subagenten:
        satz = _preissatz(s.modell, preise)
        if not satz:
            continue
        gefunden = True
        gesamt += _token_kosten(s.token, satz)
    return gesamt if gefunden else None


def _kosten_gesamt(kosten: float | None, kosten_subagenten: float | None) -> float | None:
    """kosten + kosten_subagenten; None nur, wenn BEIDE fehlen (sonst zählt der bekannte Teil)."""
    if kosten is None and kosten_subagenten is None:
        return None
    return (kosten or 0.0) + (kosten_subagenten or 0.0)


def _kontext_auslastung(ereignisse: list[Ereignis], preise: dict | None) -> float | None:
    if not preise:
        return None
    max_auslastung: float | None = None
    for e in ereignisse:
        if e.art != ART_ASSISTENT or e.token is None:
            continue
        satz = preise.get(e.name)
        fenster = satz.get("kontext_fenster") if satz else None
        if not fenster:
            continue
        auslastung = (e.token.input + e.token.cache_read) / fenster
        if max_auslastung is None or auslastung > max_auslastung:
            max_auslastung = auslastung
    return max_auslastung


def segmentiere_runden(ereignisse: list[Ereignis]) -> list[list[Ereignis]]:
    """Teilt Ereignisse in Runden ab je einem ``ART_NUTZER``-Ereignis; Ereignisse VOR der ersten
    Nutzerzeile entfallen (kein Runde-0-Sammelbecken) -- geteilte Basis für kacheln.py und
    ``kosten_je_runde`` (Auftrag „Kacheln" 2026-08-27)."""
    segmente: list[list[Ereignis]] = []
    aktuell: list[Ereignis] | None = None
    for e in ereignisse:
        if e.art == ART_NUTZER:
            aktuell = []
            segmente.append(aktuell)
        elif aktuell is not None:
            aktuell.append(e)
    return segmente


def kosten_je_runde(ereignisse: list[Ereignis], preise: dict | None) -> list[float]:
    """Kosten je Runde (Token × Preissatz je ``assistent``-Ereignis, dieselbe Rechnung wie
    ``_kosten``) -- geteilte Basis für die Kacheln (kacheln.py) und die Kostenspitzen-Regel
    (regeln.regel_kostenspitze). Ohne Preise: eine Null je Runde (kein Treffer möglich)."""
    segmente = segmentiere_runden(ereignisse)
    if not preise:
        return [0.0 for _ in segmente]
    kosten = []
    for segment in segmente:
        gesamt = 0.0
        for e in segment:
            if e.art != ART_ASSISTENT or e.token is None:
                continue
            satz = _preissatz(e.name, preise)
            if satz:
                gesamt += _token_kosten(e.token, satz)
        kosten.append(gesamt)
    return kosten


def berechne(beleg: Beleg, preise: dict | None = None, waehrung: str = "") -> Beleg:
    """Füllt beleg.kennzahlen aus ereignissen/subagenten. Verändert und liefert beleg.

    ``preise``: Modellname -> {input, output, cache_write, cache_read, kontext_fenster}
    je 1M Token; ``waehrung`` benennt die Einheit der Preise (nie stillschweigend EUR).
    """
    ereignisse = beleg.ereignisse
    k = beleg.kennzahlen

    k.runden = sum(1 for e in ereignisse if e.art == ART_NUTZER)
    k.dauer_ms = _dauer_ms(beleg.kopf)
    if _zeit_ungueltig(beleg.kopf):
        beleg.erfassung.dauer = "partial"

    latenzen = [
        e.dauer_ms for e in ereignisse if e.art == ART_RUNDE_ENDE and e.dauer_ms is not None
    ]
    k.latenz_p50_ms = _perzentil(latenzen, 50)
    k.latenz_p95_ms = _perzentil(latenzen, 95)
    k.latenz_max_ms = max(latenzen) if latenzen else 0

    tools, tools_je_typ, tool_fehler, tool_fehler_je_typ = _tools_zaehlen(ereignisse)
    k.tools = tools
    k.tools_je_typ = tools_je_typ
    k.tool_fehler = tool_fehler
    k.tool_fehler_je_typ = tool_fehler_je_typ
    k.tool_fehlerquote = (tool_fehler / tools) if tools else 0.0

    k.token, k.thinking_bloecke = _token_summe(ereignisse)

    n = len(ereignisse)
    positionen = (
        [(i + 1) / n for i, e in enumerate(ereignisse) if e.art == ART_COMPACTION] if n else []
    )
    k.compactions = len(positionen)
    k.compaction_positionen = positionen

    k.subagenten = len(beleg.subagenten)
    k.subagenten_max_tiefe = max((s.tiefe for s in beleg.subagenten), default=0)

    k.rework_dateien = _rework_dateien(ereignisse)

    k.kosten = _kosten(ereignisse, preise)
    k.kosten_subagenten = _kosten_subagenten(beleg.subagenten, preise)
    k.kosten_gesamt = _kosten_gesamt(k.kosten, k.kosten_subagenten)
    k.kosten_waehrung = waehrung if k.kosten is not None else ""
    beleg.erfassung.kosten = "derived" if k.kosten is not None else "not_observed"

    k.kontext_auslastung_max = _kontext_auslastung(ereignisse, preise)

    return beleg
