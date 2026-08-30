"""Stufe-1-Regelsatz: Beleg -> Auffälligkeiten (nie Rohtext, nur Zahlen/Signaturen).

Jede Regel ist eine eigene Funktion, die eine Liste von Auffaelligkeiten liefert.
`pruefe()` wendet die Registry `REGELN` an und setzt beleg.auffaelligkeiten.
"""
from __future__ import annotations

import statistics

from .kennzahlen import BEZUG_TYPEN, kosten_je_runde, segmentiere_runden
from .modell import ART_SUBAGENT, ART_TOOL, ART_TOOL_ERGEBNIS, Auffaelligkeit, Beleg


def _signatur_je_ref(ereignisse) -> dict[str, str]:
    """tool_use_id (ref) -> Datei-signatur, nur für Datei-Tools (BEZUG_TYPEN)."""
    ref_signatur: dict[str, str] = {}
    for e in ereignisse:
        if e.art == ART_TOOL and e.name in BEZUG_TYPEN and e.ref:
            ref_signatur[e.ref] = e.signatur
    return ref_signatur


def _letztes_tool_vor(ereignisse, index):
    for i in range(index - 1, -1, -1):
        if ereignisse[i].art == ART_TOOL:
            return ereignisse[i]
    return None


def regel_tool_fehlerquote(beleg: Beleg) -> list[Auffaelligkeit]:
    """tool:error_rate — Fehlerquote >= 20 % UND >= 3 Fehler."""
    k = beleg.kennzahlen
    if k.tool_fehlerquote >= 0.20 and k.tool_fehler >= 3:
        wert = f"{k.tool_fehlerquote * 100:.1f} %"
        return [
            Auffaelligkeit(regel="tool:error_rate", schwere="warnung",
                            signatur="tool:error_rate", wert=wert)
        ]
    return []


def regel_rework_datei(beleg: Beleg) -> list[Auffaelligkeit]:
    """rework:file — eine Datei (signatur) mit >=5 Bezügen (BEZUG_TYPEN:
    Edit/Write/MultiEdit/Read) UND >=2 Fehlläufen.

    Gruppiert über ``signatur`` (Datei-Hash), nicht über ``ref`` — ``ref`` ist
    seit F4 der tool_use_id je Aufruf, also je Tool-Aufruf eindeutig (F10).
    """
    ereignisse = beleg.ereignisse
    bezuege: dict[str, int] = {}
    for e in ereignisse:
        if e.art == ART_TOOL and e.name in BEZUG_TYPEN and e.signatur:
            bezuege[e.signatur] = bezuege.get(e.signatur, 0) + 1

    ref_signatur = _signatur_je_ref(ereignisse)
    fehllaeufe: dict[str, int] = {}
    for i, e in enumerate(ereignisse):
        if e.art == ART_TOOL_ERGEBNIS and e.fehler:
            signatur = ref_signatur.get(e.ref) if e.ref else None
            if signatur is None:
                voriges = _letztes_tool_vor(ereignisse, i)
                signatur = voriges.signatur if voriges else ""
            if signatur:
                fehllaeufe[signatur] = fehllaeufe.get(signatur, 0) + 1

    treffer = []
    for signatur, anzahl in bezuege.items():
        if anzahl >= 5 and fehllaeufe.get(signatur, 0) >= 2:
            treffer.append(
                Auffaelligkeit(regel="rework:file", schwere="warnung",
                                signatur=f"rework:file:{signatur}", ref=signatur, wert=str(anzahl))
            )
    return treffer


def regel_subagent_fehlgeschlagen(beleg: Beleg) -> list[Auffaelligkeit]:
    """subagent:failed — Subagent.ergebnis in {fehler, leer}."""
    treffer = []
    for s in beleg.subagenten:
        if s.ergebnis in ("fehler", "leer"):
            treffer.append(
                Auffaelligkeit(regel="subagent:failed", schwere="warnung",
                                signatur="subagent:failed", ref=s.agent_id, wert=s.ergebnis)
            )
    return treffer


def regel_compaction_risiko(beleg: Beleg) -> list[Auffaelligkeit]:
    """context:compaction_risk — eine Compaction-Position >= 75 % der Sitzung."""
    treffer = []
    for pos in beleg.kennzahlen.compaction_positionen:
        if pos >= 0.75:
            treffer.append(
                Auffaelligkeit(regel="context:compaction_risk", schwere="warnung",
                                signatur="context:compaction_risk", wert=f"{pos * 100:.1f} %")
            )
    return treffer


def regel_erfassungsluecke(beleg: Beleg) -> list[Auffaelligkeit]:
    """capture:gap — Kanal token/dauer strukturell nicht erfasst (not_recorded)."""
    treffer = []
    for kanal in ("token", "dauer"):
        if getattr(beleg.erfassung, kanal) == "not_recorded":
            treffer.append(
                Auffaelligkeit(regel="capture:gap", schwere="hinweis",
                                signatur=f"capture:gap:{kanal}", wert=kanal)
            )
    return treffer


def regel_rework_tool(beleg: Beleg) -> list[Auffaelligkeit]:
    """rework:tool — gleiches Tool >= 4 Fehlversuche in einer Sitzung."""
    treffer = []
    for name, anzahl in sorted(beleg.kennzahlen.tool_fehler_je_typ.items()):
        if anzahl >= 4:
            treffer.append(
                Auffaelligkeit(regel="rework:tool", schwere="warnung",
                                signatur=f"rework:tool:{name}", ref=name, wert=str(anzahl))
            )
    return treffer


def regel_subagent_ohne_beleg(beleg: Beleg) -> list[Auffaelligkeit]:
    """subagent:unsupported_claim — Ergebnis 'ok', aber ohne Datei:Zeile/Befehl/Test-Referenz."""
    treffer = []
    for s in beleg.subagenten:
        if s.ergebnis == "ok" and s.beleg != "observed":
            treffer.append(
                Auffaelligkeit(regel="subagent:unsupported_claim", schwere="hinweis",
                                signatur="subagent:unsupported_claim", ref=s.agent_id, wert=s.typ)
            )
    return treffer


def regel_ueberdelegation(beleg: Beleg) -> list[Auffaelligkeit]:
    """subagent:overdelegation — Tiefe >= 3 ODER mehr als 25 Subagenten."""
    k = beleg.kennzahlen
    if k.subagenten_max_tiefe >= 3 or k.subagenten > 25:
        wert = f"{k.subagenten} Subagenten, Tiefe {k.subagenten_max_tiefe}"
        return [
            Auffaelligkeit(regel="subagent:overdelegation", schwere="hinweis",
                            signatur="subagent:overdelegation", wert=wert)
        ]
    return []


def regel_latenz(beleg: Beleg) -> list[Auffaelligkeit]:
    """latency:slow_turn — Runden-p95 > 60 s ODER Tool-Aufrufe > 120 s (gebündelt je Tool-Name).
    latency:timeout — Tool-Aufrufe mit Dauer exakt 120 000 ms (Bash-Default-Timeout): eigene,
    von slow_turn getrennte Auffaelligkeit (gebündelt je Tool-Name, wert = Anzahl)."""
    treffer = []
    p95 = beleg.kennzahlen.latenz_p95_ms
    if p95 > 60_000:
        treffer.append(
            Auffaelligkeit(regel="latency:slow_turn", schwere="hinweis",
                            signatur="latency:slow_turn:runde", wert=f"p95 {p95 // 1000} s")
        )
    langsame: dict[str, int] = {}
    timeouts: dict[str, int] = {}
    for e in beleg.ereignisse:
        if e.art != ART_TOOL or e.dauer_ms is None:
            continue
        if e.dauer_ms == 120_000:
            timeouts[e.name] = timeouts.get(e.name, 0) + 1
        elif e.dauer_ms > 120_000:
            langsame[e.name] = langsame.get(e.name, 0) + 1
    for name, anzahl in sorted(langsame.items()):
        treffer.append(
            Auffaelligkeit(regel="latency:slow_turn", schwere="hinweis",
                            signatur=f"latency:slow_turn:tool:{name}", ref=name,
                            wert=f"{anzahl} Aufrufe > 120 s")
        )
    for name, anzahl in sorted(timeouts.items()):
        treffer.append(
            Auffaelligkeit(regel="latency:timeout", schwere="hinweis",
                            signatur=f"latency:timeout:tool:{name}", ref=name,
                            wert=str(anzahl))
        )
    return treffer


def _subagent_starts_je_runde(ereignisse) -> list[int]:
    return [sum(1 for e in segment if e.art == ART_SUBAGENT) for segment in segmentiere_runden(ereignisse)]


def _kostenspitze_einzeln(beleg: Beleg, kosten: list[float], median: float, gesamt: float) -> list[Auffaelligkeit]:
    """Einzelspitze: teuerste Runde >= 5x Median UND >= 15 % der Gesamtkosten. Delegationsspitze
    (>= 3 Subagent-Starts in dieser Runde) senkt die Schwere auf 'hinweis' -- der Ausreißer ist
    dann erklärt (Fan-out), keine reine Warnung."""
    idx = max(range(len(kosten)), key=lambda i: kosten[i])
    faktor = kosten[idx] / median
    anteil = kosten[idx] / gesamt
    if faktor < 5 or anteil < 0.15:
        return []
    delegation = _subagent_starts_je_runde(beleg.ereignisse)[idx] >= 3
    signatur = "cost:spike:delegation" if delegation else "cost:spike:single"
    schwere = "hinweis" if delegation else "warnung"
    wert = f"Runde {idx + 1}: {faktor:.1f}x Median, {anteil * 100:.0f} %"
    return [Auffaelligkeit(regel="cost:spike", schwere=schwere, signatur=signatur, wert=wert, ref=str(idx + 1))]


def _kostenspitze_cluster(kosten: list[float], median: float) -> list[Auffaelligkeit]:
    """Cluster: die letzten 3 Runden kosten im Schnitt >= 4x Median -- eine Rampe statt eines
    einzelnen Ausreißers."""
    if len(kosten) < 3:
        return []
    faktor = sum(kosten[-3:]) / (3 * median)
    if faktor < 4:
        return []
    wert = f"letzte 3 Runden {faktor:.1f}x Median"
    return [Auffaelligkeit(regel="cost:spike", schwere="hinweis", signatur="cost:spike:cluster", wert=wert)]


def _kostenspitze_top3(kosten: list[float], gesamt: float) -> list[Auffaelligkeit]:
    """Top-3: die drei teuersten Runden tragen >= 50 % der Gesamtkosten der Sitzung."""
    anteil = sum(sorted(kosten, reverse=True)[:3]) / gesamt
    if anteil < 0.5:
        return []
    wert = f"Top 3 = {anteil * 100:.0f} %"
    return [Auffaelligkeit(regel="cost:spike", schwere="hinweis", signatur="cost:spike:top3", wert=wert)]


def regel_kostenspitze(beleg: Beleg, preise: dict | None = None) -> list[Auffaelligkeit]:
    """cost:spike -- Kostenexplosion einzelner/mehrerer Runden (Codex-Vorschlag, Go
    2026-08-27). Median = Median der Runden mit Kosten > 0, erst ab mindestens 5 solchen Runden
    aussagekräftig. Braucht Kosten je Runde (kennzahlen.kosten_je_runde) -- ohne ``preise``
    (``pruefe`` ohne Preise aufgerufen) liefert diese Regel keine Treffer."""
    if not preise:
        return []
    kosten = kosten_je_runde(beleg.ereignisse, preise)
    positiv = [k for k in kosten if k > 0]
    if len(positiv) < 5:
        return []
    median = statistics.median(positiv)
    gesamt = sum(kosten)
    if median <= 0 or gesamt <= 0:
        return []
    return (
        _kostenspitze_einzeln(beleg, kosten, median, gesamt)
        + _kostenspitze_cluster(kosten, median)
        + _kostenspitze_top3(kosten, gesamt)
    )


# Querschnitts-Regeln (error:recurring, cost:outlier) brauchen andere Sitzungen und
# leben in querschnitt.py (SQL). privacy:metadata_leak setzt redaktion.bereinige.
# regel_compaction_risiko abgeschaltet 2026-08-26 (Maintainer): Position ≠ Füllstand;
# reaktivieren mit kontext_auslastung_max.
REGELN = [
    regel_tool_fehlerquote,
    regel_rework_datei,
    regel_rework_tool,
    regel_subagent_fehlgeschlagen,
    regel_subagent_ohne_beleg,
    regel_ueberdelegation,
    regel_latenz,
    regel_erfassungsluecke,
    regel_kostenspitze,
]


def pruefe(beleg: Beleg, preise: dict | None = None) -> list[Auffaelligkeit]:
    """Wendet alle Regeln der Registry an, setzt beleg.auffaelligkeiten und liefert sie.
    ``preise`` gilt nur für regel_kostenspitze (braucht Kosten je Runde) -- alle anderen Regeln
    lesen ausschließlich aus beleg.kennzahlen/ereignisse/subagenten."""
    treffer: list[Auffaelligkeit] = []
    for regel in REGELN:
        treffer.extend(regel(beleg, preise) if regel is regel_kostenspitze else regel(beleg))
    beleg.auffaelligkeiten = treffer
    return treffer
