-- 0003 — Sitzungsbeleg-Speicher (ADR 0010, Plan Stufe 2). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0003_sitzung.sql
-- Append-only wie ereignis (0001): Rolle ledger_app darf INSERT + SELECT, nie UPDATE/DELETE.
-- Eine wachsende Sitzung (Transkript laeuft weiter) erzeugt einen NEUEN Beleg mit spaeterem
-- `ende`; die Sicht sitzung_aktuell liefert je Sitzung nur den juengsten. Gleicher Stand
-- (gleiches ende) = Konflikt = ON CONFLICT DO NOTHING (idempotenter Ingest).

BEGIN;

CREATE TABLE IF NOT EXISTS sitzung (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zeitstempel    timestamptz NOT NULL DEFAULT now(),
    projekt        text NOT NULL,
    quelle         text NOT NULL CHECK (quelle IN ('claude', 'codex', 'produkt')),
    sitzung_id     text NOT NULL,
    host           text NOT NULL DEFAULT 'pc',
    start          timestamptz,
    ende           timestamptz,
    herkunft_id    bigint,
    schema_version int NOT NULL,
    dokument       jsonb NOT NULL,
    UNIQUE NULLS NOT DISTINCT (host, quelle, sitzung_id, ende)
);

-- Nachzug fuer Bestandsinstanzen (vor 2026-08-25 ohne NULLS NOT DISTINCT): ende NULL waere sonst nie ein Konflikt.
ALTER TABLE sitzung DROP CONSTRAINT IF EXISTS sitzung_host_quelle_sitzung_id_ende_key;
ALTER TABLE sitzung DROP CONSTRAINT IF EXISTS sitzung_stand_key;
ALTER TABLE sitzung ADD CONSTRAINT sitzung_stand_key UNIQUE NULLS NOT DISTINCT (host, quelle, sitzung_id, ende);

CREATE INDEX IF NOT EXISTS sitzung_dok_gin ON sitzung USING GIN (dokument jsonb_path_ops);
CREATE INDEX IF NOT EXISTS sitzung_zeit_idx ON sitzung (zeitstempel, projekt, quelle);
CREATE INDEX IF NOT EXISTS sitzung_start_idx ON sitzung (start);
CREATE UNIQUE INDEX IF NOT EXISTS sitzung_herkunft_idx
    ON sitzung (host, herkunft_id) WHERE herkunft_id IS NOT NULL;

-- Flach fuer den Querschnitt ("gleiche Signatur in >= 3 Sitzungen / 7 Tage").
CREATE TABLE IF NOT EXISTS sitzung_auffaelligkeit (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sitzung_ref bigint NOT NULL REFERENCES sitzung (id),
    zeitstempel timestamptz NOT NULL,
    projekt     text NOT NULL,
    quelle      text NOT NULL,
    regel       text NOT NULL,
    signatur    text NOT NULL,
    schwere     text NOT NULL,
    detail      jsonb
);

CREATE INDEX IF NOT EXISTS auff_sig_idx ON sitzung_auffaelligkeit (signatur, zeitstempel);
CREATE INDEX IF NOT EXISTS auff_sitzung_idx ON sitzung_auffaelligkeit (sitzung_ref);

-- Juengster Beleg je Sitzung (wachsende Transkripte werden mehrfach ingestiert).
CREATE OR REPLACE VIEW sitzung_aktuell AS
    SELECT DISTINCT ON (host, quelle, sitzung_id) *
    FROM sitzung
    ORDER BY host, quelle, sitzung_id, ende DESC NULLS LAST, id DESC;

REVOKE ALL ON TABLE sitzung, sitzung_auffaelligkeit FROM ledger_app;
GRANT INSERT, SELECT ON TABLE sitzung, sitzung_auffaelligkeit TO ledger_app;
GRANT SELECT ON sitzung_aktuell TO ledger_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

COMMIT;
