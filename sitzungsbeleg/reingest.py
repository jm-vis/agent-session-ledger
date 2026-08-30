"""reingest-sql: bestehende Belege (Tabelle `sitzung`) mit korrigierten Kennzahlen neu
berechnen, OHNE die `sitzung.id` zu ändern -- Entscheide (`ereignis.detail->>'sitzung_ref'`)
und `sitzung_auffaelligkeit.sitzung_ref` referenzieren sie sonst ins Leere.

Nur SQL-Text erzeugen + lesend nachschlagen (`finde_sitzung_id`) -- nie selbst schreiben.
Die generierte Datei führt der Maintainer manuell als `ledger_admin` aus (append-only gilt nur
für `ledger_app` per GRANT/REVOKE, siehe 0003_sitzung.sql -- `ledger_admin` ist der
Postgres-Superuser der Instanz und davon nicht betroffen, kein Trigger nötig).
"""
from __future__ import annotations

import json

from .modell import SCHEMA_VERSION
from .speicher import AUFFAELLIGKEIT_SPALTEN, dollar_quote, psql, sql_auffaelligkeiten_select, sql_literal


def finde_sitzung_id(host: str, quelle: str, sitzung_id: str, laufer=psql) -> int | None:
    """Aktuelle `sitzung.id` (jüngster Stand, `sitzung_aktuell`) zu host/quelle/sitzung_id,
    oder None -- keine vorhandene Zeile (normal per `ingest-dir --db` nachholbar)."""
    sql = (
        "SELECT id FROM sitzung_aktuell WHERE host = "
        f"{sql_literal(host)} AND quelle = {sql_literal(quelle)} "
        f"AND sitzung_id = {sql_literal(sitzung_id)};"
    )
    ausgabe = laufer(sql).strip()
    return int(ausgabe) if ausgabe.isdigit() else None


def sql_reingest_zeile(dokument: dict, sitzung_id: int) -> str:
    """UPDATE (dokument/schema_version) + DELETE + Neu-INSERT der Auffälligkeiten für EINE
    bestehende Sitzung. `sitzung_id`, `start`, `ende`, `projekt`, `quelle` bleiben unverändert:
    `ende` ist Teil des Unique-Schlüssels (host, quelle, sitzung_id, ende) -- ein neu berechnetes
    Ende kollidierte beim ersten Lauf 2026-08-27 mit einer aelteren Version derselben Sitzung
    (ROLLBACK). Das Dokument traegt sein eigenes kopf.ende."""
    dok = dollar_quote(json.dumps(dokument, ensure_ascii=True, separators=(",", ":")))
    update = (
        f"UPDATE sitzung SET dokument = {dok}::jsonb, "
        f"schema_version = {int(dokument.get('schema_version', SCHEMA_VERSION))} "
        f"WHERE id = {int(sitzung_id)};"
    )
    delete = f"DELETE FROM sitzung_auffaelligkeit WHERE sitzung_ref = {int(sitzung_id)};"
    insert = (
        f"INSERT INTO sitzung_auffaelligkeit ({AUFFAELLIGKEIT_SPALTEN})\n  "
        + sql_auffaelligkeiten_select(f"{dok}::jsonb", "sitzung s")
        + f"\n  WHERE s.id = {int(sitzung_id)};"
    )
    return "\n".join([update, delete, insert])


def baue_datei(zeilen_sql: list[str]) -> str:
    """Wrapt alle Sitzungs-Blöcke in EINE Transaktion -- alles oder nichts, passend zum
    `-v ON_ERROR_STOP=1`-Aufruf, mit dem der Maintainer die Datei ausführt."""
    kopf = "-- reingest-sql: Kennzahlen neu berechnet (Token-Doppelzählung gefixt 2026-08-27).\n"
    kopf += "-- IDs bleiben erhalten -- Entscheide/Auffaelligkeiten bleiben gueltig.\n"
    if not zeilen_sql:
        return kopf + "-- keine Aktualisierungen.\n"
    return kopf + "BEGIN;\n\n" + "\n\n".join(zeilen_sql) + "\n\nCOMMIT;\n"
