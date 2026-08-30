"""retention-sql: Belege/Versionen/Ereignisse/Chat-Zeilen ALTER Sitzungen loeschen
(CONTRACTS.md Abschnitt "Retention").

Nur SQL-Text erzeugen + lesend nachschlagen (`betroffene_sitzungen`) -- nie selbst loeschen.
Die generierte Datei fuehrt der Maintainer manuell als `ledger_admin` aus: `ledger_app` (Ingest
UND Dashboard, gleiche Rolle) hat laut 0003_sitzung.sql/0004_sitzung_logisch.sql/0005_chat.sql
nur INSERT/SELECT -- ein DELETE ueber diese Rolle scheitert an `permission denied`, das Loeschen
ist also strukturell keiner App-Rolle moeglich.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import quellen
from .speicher import psql, sql_literal

MINDEST_TAGE = 7  # Schutz vor versehentlichem Grossloeschen (Auftrag Punkt 3)

QUELLEN_FILTER = {
    "claude": quellen.CLAUDE,
    "codex": quellen.CODEX,
    "ollama": quellen.OLLAMA,
    "openrouter": quellen.OPENROUTER,
    "requesty": quellen.REQUESTY,
}


class RetentionFehler(ValueError):
    """Schutzverstoss: `--aelter-als` zu klein oder `--quelle` fehlt/unbekannt."""


def pruefe_argumente(aelter_als: int, quelle: str | None) -> str:
    """Wirft `RetentionFehler` bei Schutzverstoss, sonst die validierte Quelle zurueck."""
    if aelter_als < MINDEST_TAGE:
        raise RetentionFehler(f"--aelter-als muss >= {MINDEST_TAGE} sein (Schutz vor Versehen)")
    if not quelle:
        raise RetentionFehler(
            "--quelle fehlt -- 'alle' explizit angeben (claude|codex|ollama|openrouter|requesty|alle)"
        )
    if quelle != "alle" and quelle not in QUELLEN_FILTER:
        raise RetentionFehler(f"--quelle unbekannt: {quelle}")
    return quelle


def _sql_kandidaten(host: str) -> str:
    """Ein JSON-Array (jsonb_agg, wie `chat_lesen`/`web._liste`): je logischer Sitzung Beginn
    (`coalesce(start, zeitstempel)`, gleiches Muster wie die Querschnitt-SQL, siehe README/
    CONTRACTS) + Rohquelle + Modelle -- Grundlage fuer die Python-seitige Anzeige-Quelle-
    Filterung (`quellen.quelle_fuer`, web.py macht das genauso: das laesst sich nicht als
    einfache SQL-Gleichheit ausdruecken)."""
    return (
        "SELECT coalesce(jsonb_agg(jsonb_build_object("
        "'logisch_ref', logisch_ref, 'beginn', coalesce(start, zeitstempel), "
        "'quelle', quelle, 'modelle', dokument->'kopf'->'modelle', "
        "'backend', dokument->'kopf'->>'backend'"
        f")), '[]'::jsonb) FROM sitzung_aktuell WHERE host = {sql_literal(host)};"
    )


def _zeile_zu_treffer(zeile: dict, schwelle: datetime, ziel: str | None, registry) -> dict | None:
    """Ein Kandidat aus `_sql_kandidaten` -> Treffer-Dict, oder None (zu frisch / passt nicht
    zur gewuenschten Anzeige-Quelle)."""
    if datetime.fromisoformat(zeile["beginn"]) >= schwelle:
        return None
    anzeige = quellen.quelle_fuer(zeile.get("quelle", ""), zeile.get("modelle"), registry, zeile.get("backend"))
    if ziel is not None and anzeige != ziel:
        return None
    return {"logisch_ref": zeile["logisch_ref"], "beginn": zeile["beginn"], "quelle_anzeige": anzeige}


def betroffene_sitzungen(
    host: str, quelle: str, aelter_als: int, laufer=psql, registry: dict | None = None
) -> list[dict]:
    """Logische Sitzungen mit Beginn vor `aelter_als` Tagen, gefiltert nach Anzeige-Quelle
    (Claude/Codex/Ollama/OpenRouter) -- rein lesend, keine Schreibrechte noetig."""
    schwelle = datetime.now(timezone.utc) - timedelta(days=aelter_als)
    ausgabe = laufer(_sql_kandidaten(host))
    kandidaten = json.loads(ausgabe) if ausgabe.strip() else []
    ziel = QUELLEN_FILTER.get(quelle)
    treffer = (_zeile_zu_treffer(z, schwelle, ziel, registry) for z in kandidaten)
    return [t for t in treffer if t is not None]


def _delete_anweisungen(ids: list[int]) -> list[str]:
    """DELETE-Reihenfolge nach Fremdschluessel (Kind vor Eltern, 0003/0004_sitzung_logisch.sql):
    `sitzung_auffaelligkeit.sitzung_ref` -> `sitzung`, `sitzung.logisch_ref` -> `sitzung_logisch`.
    `chat`/`ereignis` haben keinen echten FK (nur jsonb-Referenzen), stehen trotzdem zuerst."""
    liste = ",".join(str(i) for i in ids)
    return [
        f"DELETE FROM chat WHERE (detail->'kontext'->>'sitzung_logisch')::bigint IN ({liste});",
        "DELETE FROM ereignis WHERE "
        f"(quelle IN ('pruefung', 'tiefenanalyse', 'vieraugen') "
        f"AND (detail->>'sitzung_logisch')::bigint IN ({liste})) "
        f"OR (quelle = 'gf' AND typ = 'befund_entscheid' "
        f"AND (detail->>'sitzung_ref')::bigint IN ({liste}));",
        f"DELETE FROM sitzung_auffaelligkeit WHERE logisch_ref IN ({liste});",
        f"DELETE FROM sitzung WHERE logisch_ref IN ({liste});",
        f"DELETE FROM sitzung_logisch WHERE id IN ({liste});",
    ]


def _kopf_kommentar(aelter_als: int, quelle: str, anzahl: int) -> str:
    return (
        f"-- retention-sql: loescht Belege/Versionen/Ereignisse/Chat-Zeilen aelter als "
        f"{aelter_als} Tage (quelle={quelle}).\n"
        f"-- Erzeugt {datetime.now().isoformat(timespec='seconds')}, betroffene Sitzungen: {anzahl}.\n"
        "\\set ON_ERROR_STOP on\n"
    )


def baue_datei(treffer: list[dict], aelter_als: int, quelle: str) -> str:
    """Wrapt alle DELETEs in EINE Transaktion mit `\\set ON_ERROR_STOP` + Zaehl-Hinweis
    (`RAISE NOTICE`) -- passend zum `-v ON_ERROR_STOP=1`-Aufruf, mit dem der Maintainer die Datei
    ausfuehrt. Keine Treffer -> keine Transaktion (wie `reingest.baue_datei([])`)."""
    kopf = _kopf_kommentar(aelter_als, quelle, len(treffer))
    if not treffer:
        return kopf + "-- keine betroffenen Sitzungen.\n"
    ids = sorted(t["logisch_ref"] for t in treffer)
    hinweis = (
        f"retention: {len(ids)} Sitzung(en) werden geloescht "
        f"(aelter als {aelter_als} Tage, quelle={quelle})"
    )
    koerper = "\n".join(_delete_anweisungen(ids))
    return kopf + f"BEGIN;\n\nDO $$ BEGIN RAISE NOTICE '{hinweis}'; END $$;\n\n{koerper}\n\nCOMMIT;\n"
