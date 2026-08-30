"""Querschnitts-Regeln über Sitzungen hinweg (brauchen die DB, laufen nach dem Speichern).

  error:recurring  gleiche Fehler-Signatur in >= 3 Sitzungen der letzten 7 Tage
  cost:outlier     Kosten dieser Sitzung > p95 der letzten 30 Tage (ab 10 Sitzungen mit Kosten)

Treffer werden als flache Zeilen in `sitzung_auffaelligkeit` angehängt (append-only);
das gespeicherte Beleg-JSON bleibt unverändert — die flache Tabelle ist die Quelle
für den Querschnitt im Dashboard.
"""
from __future__ import annotations

import json

from .modell import ART_TOOL_ERGEBNIS, Auffaelligkeit, Beleg
from .speicher import psql, sql_literal

MIN_SITZUNGEN_FEHLER = 3
TAGE_FEHLER = 7
TAGE_KOSTEN = 30
MIN_SITZUNGEN_KOSTEN = 10


def fehler_signaturen(beleg: Beleg) -> list[str]:
    return sorted({e.signatur for e in beleg.ereignisse
                   if e.art == ART_TOOL_ERGEBNIS and e.fehler and e.signatur})


def sql_wiederkehrende_fehler(signaturen: list[str], tage: int = TAGE_FEHLER) -> str:
    """signatur|anzahl_sitzungen für Signaturen, die in >= 3 Sitzungen / N Tage vorkommen."""
    liste = ", ".join(sql_literal(s) for s in signaturen)
    return f"""SELECT e->>'signatur', count(DISTINCT s.id)
FROM sitzung_aktuell s, jsonb_array_elements(s.dokument->'ereignisse') e
WHERE e->>'art' = 'tool_ergebnis' AND (e->>'fehler')::boolean
  AND coalesce(s.ende, s.start, s.zeitstempel) > now() - interval '{int(tage)} days'
  AND e->>'signatur' IN ({liste})
GROUP BY 1 HAVING count(DISTINCT s.id) >= {MIN_SITZUNGEN_FEHLER};"""


def sql_kosten_p95(ausser_id: int = 0, tage: int = TAGE_KOSTEN) -> str:
    """p95|anzahl über HISTORISCHE Sitzungen mit Kosten (ohne die gerade gespeicherte, C7)."""
    return f"""SELECT percentile_cont(0.95) WITHIN GROUP
         (ORDER BY (dokument->'kennzahlen'->>'kosten')::numeric), count(*)
FROM sitzung_aktuell
WHERE dokument->'kennzahlen'->>'kosten' IS NOT NULL AND id <> {int(ausser_id)}
  AND coalesce(ende, start, zeitstempel) > now() - interval '{int(tage)} days';"""


def sql_auffaelligkeit_anhaengen(sitzung_ref: int, a: Auffaelligkeit) -> str:
    detail = sql_literal(json.dumps({"wert": a.wert, "ref": a.ref}, ensure_ascii=True))
    return (
        "INSERT INTO sitzung_auffaelligkeit (sitzung_ref, zeitstempel, projekt, quelle, regel, signatur, schwere, detail) "
        f"SELECT id, now(), projekt, quelle, {sql_literal(a.regel)}, {sql_literal(a.signatur)}, "
        f"{sql_literal(a.schwere)}, {detail}::jsonb FROM sitzung WHERE id = {int(sitzung_ref)};"
    )


def _zeilen(ausgabe: str) -> list[list[str]]:
    return [zeile.split("|") for zeile in ausgabe.splitlines() if zeile.strip()]


def wiederkehrende_fehler(beleg: Beleg, laufer=psql) -> list[Auffaelligkeit]:
    signaturen = fehler_signaturen(beleg)
    if not signaturen:
        return []
    treffer = []
    for spalten in _zeilen(laufer(sql_wiederkehrende_fehler(signaturen))):
        if len(spalten) == 2:
            treffer.append(Auffaelligkeit(
                regel="error:recurring", schwere="warnung",
                signatur=f"error:recurring:{spalten[0]}", ref=spalten[0],
                wert=f"{spalten[1]} Sitzungen in {TAGE_FEHLER} Tagen",
            ))
    return treffer


def kosten_ausreisser(beleg: Beleg, laufer=psql, ausser_id: int = 0) -> list[Auffaelligkeit]:
    kosten = beleg.kennzahlen.kosten
    if kosten is None:
        return []
    zeilen = _zeilen(laufer(sql_kosten_p95(ausser_id)))
    if not zeilen or len(zeilen[0]) != 2 or not zeilen[0][0]:
        return []
    p95, anzahl = float(zeilen[0][0]), int(zeilen[0][1])
    if anzahl < MIN_SITZUNGEN_KOSTEN or kosten <= p95:
        return []
    return [Auffaelligkeit(regel="cost:outlier", schwere="warnung", signatur="cost:outlier",
                           wert=f"{kosten:.2f} > p95 {p95:.2f} ({anzahl} Sitzungen)")]


def erfassungsluecken(beleg: Beleg) -> list[Auffaelligkeit]:
    """capture:gap steht schon in beleg.auffaelligkeiten (regeln.pruefe lief davor) — hier nur
    herausgefiltert, damit pruefe_und_speichere sie zusätzlich in die flache Tabelle schreibt."""
    return [a for a in beleg.auffaelligkeiten if a.regel == "capture:gap"]


def pruefe_und_speichere(beleg: Beleg, sitzung_ref: int, laufer=psql) -> list[Auffaelligkeit]:
    """Querschnittsregeln (neue Treffer) + bereits vorhandene capture:gap-Befunde -- beide landen
    in der flachen Tabelle (Quelle für /api/querschnitt); nur die Querschnittsregeln sind NEU für
    beleg.auffaelligkeiten (capture:gap steckt dort schon drin, würde sonst doppelt gezählt)."""
    treffer = wiederkehrende_fehler(beleg, laufer) + kosten_ausreisser(beleg, laufer, sitzung_ref)
    for a in treffer + erfassungsluecken(beleg):
        laufer(sql_auffaelligkeit_anhaengen(sitzung_ref, a))
    return treffer
