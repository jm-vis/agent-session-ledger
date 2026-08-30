"""Speicher: Beleg -> Postgres-Ereignisinstanz (Tabellen aus 0003_sitzung.sql).

Schreibweg wie `Write-Ereignis.ps1`: `docker exec … psql` als App-Rolle
`ledger_app` (append-only per Grants, lokaler Socket, kein Passwort, keine
Python-Abhängigkeit). FAIL-OPEN ist Sache des Aufrufers: dieses Modul wirft
`SpeicherFehler`, der Aufrufer entscheidet (CLI: Warnzeile, Exit 0 im Hook).

Ein Beleg wird als Ganzes (JSONB) plus flache Auffälligkeiten in EINEM
Statement eingefügt; ein bereits vorhandener Stand (gleiches
host/quelle/sitzung_id/ende) ist ein Konflikt -> nichts eingefügt, `None`.
"""
from __future__ import annotations

import json
import os
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # konsenloser Dienst: Kindprozess ohne Fenster (2026-08-28)

from . import contracts
from .modell import Beleg

# Containername konfigurierbar (SITZUNGSBELEG_PG_CONTAINER): der Standardwert passt zum
# mitgelieferten Compose-Setup, ein anderer Betrieb kann seinen eigenen Container-/Stack-Namen
# haben.
CONTAINER = os.environ.get("SITZUNGSBELEG_PG_CONTAINER", "sitzungsbeleg-postgres")
DATENBANK = "ereignis"
ROLLE = "ledger_app"
ZEITLIMIT_S = 8


class SpeicherFehler(RuntimeError):
    """Docker/psql nicht erreichbar, Zeitlimit oder SQL-Fehler (Text gekürzt)."""


def _psql_befehl() -> list[str]:
    return [
        "docker", "exec", "-i", CONTAINER, "psql", "-U", ROLLE, "-d", DATENBANK,
        "-qAt", "-v", "ON_ERROR_STOP=1", "-f", "-",
    ]


def psql(sql: str, zeitlimit_s: int = ZEITLIMIT_S) -> str:
    """Führt SQL als ledger_app aus, liefert stdout (Zeilen, Spalten per '|')."""
    try:
        lauf = subprocess.run(
            _psql_befehl(), input=sql.encode("utf-8"), capture_output=True, timeout=zeitlimit_s,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise SpeicherFehler(f"psql nicht ausführbar: {type(fehler).__name__}") from fehler
    if lauf.returncode != 0:
        raise SpeicherFehler(lauf.stderr.decode("utf-8", "replace").strip()[:300])
    return lauf.stdout.decode("utf-8", "replace").strip()


def sql_literal(text: str) -> str:
    """Einfaches SQL-String-Literal ('' als Escape; standard_conforming_strings ist an)."""
    return "'" + text.replace("'", "''") + "'"


def dollar_quote(text: str, basis: str = "j") -> str:
    """Dollar-Quoting für ein SQL-Textliteral (z. B. großes JSON mit vielen Anführungszeichen):
    wählt ein Tag, das nicht im Text vorkommt, damit `$tag$...$tag$` nicht vorzeitig endet
    (reingest.py: UPDATE-Statements auf bestehende Zeilen, IDs bleiben erhalten)."""
    tag = basis
    n = 0
    while f"${tag}$" in text:
        n += 1
        tag = f"{basis}{n}"
    return f"${tag}${text}${tag}$"


# Spalten von sitzung_auffaelligkeit, geteilt zwischen sql_einfuegen (neuer Beleg) und
# reingest.py (bestehende Zeile neu berechnet) — nie duplizieren. `logisch_ref` (C1) kommt in
# beiden Faellen aus derselben Quellzeile wie `sitzung_ref` (CTE `s` bzw. Tabelle `sitzung s`).
AUFFAELLIGKEIT_SPALTEN = "sitzung_ref, logisch_ref, zeitstempel, projekt, quelle, regel, signatur, schwere, detail"
_AUFFAELLIGKEIT_RECORD = "x(regel text, signatur text, schwere text, wert text, ref text)"


def sql_auffaelligkeiten_select(dok_ausdruck: str, herkunft: str) -> str:
    """SELECT für sitzung_auffaelligkeit-Zeilen aus `dok_ausdruck->'auffaelligkeiten'`.
    `herkunft` liefert s.id/logisch_ref/zeitstempel/projekt/quelle -- CTE-Name `s, dok` bei
    sql_einfuegen (neuer Beleg), Tabellen-Alias `sitzung s` bei reingest.py (bestehende Zeile)."""
    return (
        "SELECT s.id, s.logisch_ref, s.zeitstempel, s.projekt, s.quelle, x.regel, x.signatur, x.schwere,\n"
        "         jsonb_build_object('wert', x.wert, 'ref', x.ref)\n"
        f"  FROM {herkunft}, jsonb_to_recordset({dok_ausdruck}->'auffaelligkeiten')\n"
        f"       AS {_AUFFAELLIGKEIT_RECORD}"
    )


def _sql_logisch_cte(host_lit: str) -> str:
    """C1 Regel 3 + Sequence-Fix (Maintainer 2026-08-28): erst SELECT (`l0`), dann INSERT (`li`) --
    der Alltagsfall (Sitzung existiert schon, jeder weitere Stop-Hook-Lauf derselben Sitzung)
    findet die Zeile in `l0` und verbrennt keinen `sitzung_logisch_id_seq`-Wert mehr. Vorher
    lief bei JEDEM Ingest ein `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, das den
    Sequence-Wert auch im Konfliktfall verbraucht (Ursache der Sitzungsnummern-Luecken:
    285 Sitzungen, max id 1534). `li` inserted nur, wenn `l0` leer ist (`WHERE NOT EXISTS`);
    der seltene Race zweier gleichzeitiger Erst-Ingests derselben Sitzung (Hook + Batch) endet
    per `ON CONFLICT ... DO NOTHING` wie bisher als Konflikt (beide tragen denselben
    Transkript-Stand). Das minimale UPDATE-Grant aus Migration 0004 (fuer das alte `DO UPDATE`)
    wird fuer diesen Pfad nicht mehr gebraucht, bleibt aber harmlos bestehen."""
    return f"""l0 AS (
  SELECT sl.id FROM sitzung_logisch sl, dok
  WHERE sl.host = {host_lit} AND sl.quelle = dok.d->'kopf'->>'quelle'
    AND sl.sitzung_id = dok.d->'kopf'->>'sitzung_id'
),
li AS (
  INSERT INTO sitzung_logisch (host, quelle, sitzung_id, projekt)
  SELECT {host_lit}, d->'kopf'->>'quelle', d->'kopf'->>'sitzung_id', coalesce(d->'kopf'->>'projekt_name', '')
  FROM dok WHERE NOT EXISTS (SELECT 1 FROM l0)
  ON CONFLICT (host, quelle, sitzung_id) DO NOTHING
  RETURNING id
),
l AS (SELECT id FROM l0 UNION ALL SELECT id FROM li)"""


def _sql_sitzung_cte(host_lit: str) -> str:
    """Version-Zeile mit `logisch_ref` aus der `l`-CTE (C1 Regel 3)."""
    return f"""s AS (
  INSERT INTO sitzung (projekt, quelle, sitzung_id, host, start, ende, schema_version, dokument, logisch_ref)
  SELECT coalesce(d->'kopf'->>'projekt_name', ''), d->'kopf'->>'quelle', d->'kopf'->>'sitzung_id',
         {host_lit}, nullif(d->'kopf'->>'start', '')::timestamptz,
         nullif(d->'kopf'->>'ende', '')::timestamptz, (d->>'schema_version')::int, d, l.id
  FROM dok, l
  ON CONFLICT DO NOTHING
  RETURNING id, logisch_ref, zeitstempel, projekt, quelle
)"""


def sql_einfuegen(dokument: dict, host: str) -> str:
    """Ein Statement: logische Sitzung (C1) + Beleg + flache Auffälligkeiten; liefert die
    neue sitzung.id oder nichts (Konflikt = gleicher Stand schon da)."""
    dok = sql_literal(json.dumps(dokument, ensure_ascii=True, separators=(",", ":")))
    host_lit = sql_literal(host)
    auffaelligkeiten = sql_auffaelligkeiten_select("dok.d", "s, dok")
    return (
        f"WITH dok AS (SELECT {dok}::jsonb AS d),\n"
        f"{_sql_logisch_cte(host_lit)},\n"
        f"{_sql_sitzung_cte(host_lit)},\n"
        f"a AS (\n  INSERT INTO sitzung_auffaelligkeit ({AUFFAELLIGKEIT_SPALTEN})\n  {auffaelligkeiten}\n)\n"
        "SELECT id FROM s;"
    )


def speichern(beleg: Beleg, host: str = "pc", laufer=psql) -> int | None:
    """Speichert den Beleg. Liefert die neue sitzung.id, bei Konflikt (Stand schon da) None."""
    ausgabe = laufer(sql_einfuegen(beleg.als_dict(), host))
    return int(ausgabe) if ausgabe.strip().isdigit() else None


def lade_dokument(sitzung_ref: int, laufer=psql) -> dict:
    """Liest das gespeicherte Beleg-JSON zu einer sitzung.id."""
    ausgabe = laufer(f"SELECT dokument FROM sitzung WHERE id = {int(sitzung_ref)};")
    if not ausgabe:
        raise SpeicherFehler(f"sitzung {sitzung_ref} nicht gefunden")
    return json.loads(ausgabe)


def logisch_fuer_version(version_id: int, laufer=psql) -> int | None:
    """C1 Regel 2/5: sitzung.id (Version) -> sitzung_logisch.id -- Legacy-Leseregel (Alt-
    Ereignisse kennen nur die Version) und Uebergangsroute (GET /api/sitzung/version/<n>).
    `None`, wenn die Version nicht existiert."""
    ausgabe = laufer(f"SELECT logisch_ref FROM sitzung WHERE id = {int(version_id)};")
    return int(ausgabe) if ausgabe.strip().isdigit() else None


def ereignis_schreiben(quelle: str, typ: str, detail: dict, host: str = "pc", laufer=psql) -> None:
    """Schreibt eine Zeile in den Ereignisstrom. Quellen mit Contract (CONTRACTS.md C8) werden vorher
    validiert -- ein ContractFehler verhindert den INSERT."""
    contracts.validiere_ereignis(quelle, detail)
    detail_sql = sql_literal(json.dumps(detail, ensure_ascii=True, separators=(",", ":")))
    laufer(
        "INSERT INTO ereignis (quelle, typ, host, detail) VALUES ("
        f"{sql_literal(quelle)}, {sql_literal(typ)}, {sql_literal(host)}, {detail_sql}::jsonb);"
    )


def chat_schreiben(detail: dict, host: str = "pc", laufer=psql) -> None:
    """C4 Tabelle `chat` (nicht `ereignis`, ADR 0006 2b): validiert `detail` gegen
    `contracts.ChatNachricht` -- ein ContractFehler verhindert den INSERT, wie bei
    `ereignis_schreiben`. Eine Zeile je Nachricht."""
    contracts.validiere("chat_nachricht", detail)
    detail_sql = sql_literal(json.dumps(detail, ensure_ascii=True, separators=(",", ":")))
    laufer(
        "INSERT INTO chat (gespraech_id, host, detail) VALUES ("
        f"{sql_literal(detail['gespraech_id'])}, {sql_literal(host)}, {detail_sql}::jsonb);"
    )


def chat_lesen(gespraech_id: str, laufer=psql) -> list[dict]:
    """Alle Nachrichten eines Gesprächs, älteste zuerst (C5 GET /api/chat/{gespraech_id})."""
    ausgabe = laufer(
        "SELECT coalesce(jsonb_agg(detail ORDER BY id), '[]'::jsonb) FROM chat "
        f"WHERE gespraech_id = {sql_literal(gespraech_id)};"
    )
    return json.loads(ausgabe) if ausgabe.strip() else []
