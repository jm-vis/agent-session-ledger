"""Testhilfen: baut synthetische Belege ohne echte Sitzungsdaten (Modell-Bausteine)."""
from __future__ import annotations

from sitzungsbeleg.modell import (
    ART_ASSISTENT,
    ART_COMPACTION,
    ART_NUTZER,
    ART_RUNDE_ENDE,
    ART_SUBAGENT,
    ART_TOOL,
    ART_TOOL_ERGEBNIS,
    Beleg,
    Ereignis,
    Erfassung,
    Kopf,
    Subagent,
    Token,
)


def baue_beleg(
    ereignisse: list[Ereignis] | None = None,
    subagenten: list[Subagent] | None = None,
    kopf: Kopf | None = None,
    erfassung: Erfassung | None = None,
) -> Beleg:
    """Baut einen minimalen, gültigen Beleg für Tests."""
    kopf = kopf or Kopf(
        quelle="claude",
        sitzung_id="test-sitzung",
        start="2026-08-25T10:00:00Z",
        ende="2026-08-25T10:10:00Z",
    )
    return Beleg(
        kopf=kopf,
        erfassung=erfassung or Erfassung(),
        ereignisse=ereignisse or [],
        subagenten=subagenten or [],
    )


def nutzer_runde() -> Ereignis:
    return Ereignis(zeit="2026-08-25T10:00:00Z", art=ART_NUTZER)


def assistent(token: Token | None = None, name: str = "claude-sonnet-5") -> Ereignis:
    return Ereignis(
        zeit="2026-08-25T10:00:01Z", art=ART_ASSISTENT, name=name, token=token or Token()
    )


def tool(name: str, ref: str = "", signatur: str = "") -> Ereignis:
    return Ereignis(
        zeit="2026-08-25T10:00:02Z", art=ART_TOOL, name=name, ref=ref, signatur=signatur
    )


def tool_ergebnis(fehler: bool = False, ref: str = "") -> Ereignis:
    return Ereignis(zeit="2026-08-25T10:00:03Z", art=ART_TOOL_ERGEBNIS, fehler=fehler, ref=ref)


def runde_ende(dauer_ms: int) -> Ereignis:
    return Ereignis(zeit="2026-08-25T10:00:04Z", art=ART_RUNDE_ENDE, dauer_ms=dauer_ms)


def compaction() -> Ereignis:
    return Ereignis(zeit="2026-08-25T10:00:05Z", art=ART_COMPACTION)


def subagent_start(ref: str = "") -> Ereignis:
    """ART_SUBAGENT-Ereignis (Subagent gestartet) -- Zeitleisten-Punkt, nicht zu verwechseln
    mit ``subagent()`` unten (dessen eigenes Transkript-Ergebnis in beleg.subagenten)."""
    return Ereignis(zeit="2026-08-25T10:00:02Z", art=ART_SUBAGENT, ref=ref)


def subagent(agent_id: str = "sub-1", ergebnis: str = "ok", tiefe: int = 1) -> Subagent:
    return Subagent(agent_id=agent_id, ergebnis=ergebnis, tiefe=tiefe, token=Token())
