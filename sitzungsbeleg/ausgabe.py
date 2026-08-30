"""Ausgabe des Belegs als Markdown oder JSON (nie Inhalte, nur geprüfte Felder)."""
from __future__ import annotations

import json

from .modell import Beleg


def _kopf_tabelle(beleg: Beleg) -> str:
    k = beleg.kopf
    zeilen = [
        ("Quelle", k.quelle),
        ("Sitzung", k.sitzung_id),
        ("Projekt-Hash", k.projekt_hash),
        ("Projekt", k.projekt_name),
        ("Host", k.host),
        ("Start", k.start),
        ("Ende", k.ende),
        ("Version", k.version),
        ("Git-Branch", k.git_branch),
        ("Modelle", ", ".join(k.modelle)),
    ]
    zeilen_text = "\n".join(f"| {name} | {wert} |" for name, wert in zeilen)
    return f"## Kopf\n\n| Feld | Wert |\n| --- | --- |\n{zeilen_text}\n"


def dauer_lesbar(ms: int | None) -> str:
    """Millisekunden lesbar: 37 s · 4 min 12 s · 7 h 38 min."""
    if ms is None:
        return "—"
    s = ms // 1000
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {(s % 3600) // 60} min"


def _kennzahlen_tabelle(beleg: Beleg) -> str:
    kz = beleg.kennzahlen
    t = kz.token
    zeilen = [
        ("Runden", kz.runden),
        ("Dauer", dauer_lesbar(kz.dauer_ms)),
        ("Latenz p50", dauer_lesbar(kz.latenz_p50_ms)),
        ("Latenz p95", dauer_lesbar(kz.latenz_p95_ms)),
        ("Latenz max", dauer_lesbar(kz.latenz_max_ms)),
        ("Tools", kz.tools),
        ("Tool-Fehler", kz.tool_fehler),
        ("Tool-Fehlerquote", f"{kz.tool_fehlerquote * 100:.1f} %"),
        ("Token in / out", f"{t.input:,} / {t.output:,}".replace(",", ".")),
        ("Token Cache write / read", f"{t.cache_write:,} / {t.cache_read:,}".replace(",", ".")),
        ("Token Thinking", f"{t.thinking:,}".replace(",", ".")),
        ("Thinking-Bloecke", kz.thinking_bloecke),
        ("Compactions", kz.compactions),
        ("Subagenten", kz.subagenten),
        ("Subagenten max. Tiefe", kz.subagenten_max_tiefe),
        (
            f"Kosten Hauptsitzung ({kz.kosten_waehrung or '—'})",
            f"{kz.kosten:.2f}" if kz.kosten is not None else "not_observed",
        ),
        (
            f"Kosten Subagenten ({kz.kosten_waehrung or '—'})",
            f"{kz.kosten_subagenten:.2f}" if kz.kosten_subagenten is not None else "not_observed",
        ),
        (
            f"Kosten gesamt ({kz.kosten_waehrung or '—'})",
            f"{kz.kosten_gesamt:.2f}" if kz.kosten_gesamt is not None else "not_observed",
        ),
    ]
    zeilen_text = "\n".join(f"| {name} | {wert} |" for name, wert in zeilen)
    return f"## Kennzahlen\n\n| Kennzahl | Wert |\n| --- | --- |\n{zeilen_text}\n"


def _erfassungszeile(beleg: Beleg) -> str:
    e = beleg.erfassung
    return (
        f"Erfassung: tokens={e.token} · dauer={e.dauer} · kosten={e.kosten} "
        f"· inhalte={e.inhalte} · reasoning={e.reasoning}"
    )


def _auffaelligkeiten_liste(beleg: Beleg) -> str:
    if not beleg.auffaelligkeiten:
        return "## Auffaelligkeiten\n\nKeine.\n"
    zeilen = [
        f"- [{a.schwere}] {a.regel} — {a.wert}" + (f" (ref: {a.ref})" if a.ref else "")
        for a in beleg.auffaelligkeiten
    ]
    return "## Auffaelligkeiten\n\n" + "\n".join(zeilen) + "\n"


def _subagenten_tabelle(beleg: Beleg) -> str:
    if not beleg.subagenten:
        return "## Subagenten\n\nKeine.\n"
    kopf = "| Typ | Modell | Dauer | Tools | Fehler | Beleg | Ergebnis |"
    trenner = "| --- | --- | --- | --- | --- | --- | --- |"
    zeilen = [
        f"| {s.typ} | {s.modell} | {dauer_lesbar(s.dauer_ms)} | {s.tools} | {s.tool_fehler} "
        f"| {s.beleg} | {s.ergebnis} |"
        for s in beleg.subagenten
    ]
    return "## Subagenten\n\n" + "\n".join([kopf, trenner] + zeilen) + "\n"


def als_markdown(beleg: Beleg) -> str:
    """Rendert den Beleg als reine Kennzahlen-Markdown-Seite, ohne Inhalte."""
    teile = [
        f"# Sitzungsbeleg — {beleg.kopf.sitzung_id}\n",
        _kopf_tabelle(beleg),
        _kennzahlen_tabelle(beleg),
        _erfassungszeile(beleg),
        "",
        _auffaelligkeiten_liste(beleg),
        _subagenten_tabelle(beleg),
        "Dieser Beleg enthält keine Inhalte. Rohdaten liegen nur lokal.",
    ]
    return "\n".join(teile)


def als_json(beleg: Beleg) -> str:
    """Rendert den Beleg als JSON (gleiche Feldmenge wie als_dict())."""
    return json.dumps(beleg.als_dict(), ensure_ascii=False, indent=2)
