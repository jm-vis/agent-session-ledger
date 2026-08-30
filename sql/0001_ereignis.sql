-- 0001 — Betriebs-Ereignisstrom (ADR 0006, Plan A2). Idempotent.
-- Aufruf: psql -v app_pw='<passwort>' -d ereignis -f 0001_ereignis.sql
-- Muster: Beispielprojekt 0001_aktivitaet.sql (ADR 0007, abgenommen 2026-07-31).

BEGIN;

CREATE TABLE IF NOT EXISTS ereignis (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zeitstempel timestamptz NOT NULL DEFAULT now(),
    quelle      text NOT NULL,
    typ         text NOT NULL,
    host        text NOT NULL DEFAULT 'pc',
    detail      jsonb
);

CREATE INDEX IF NOT EXISTS ereignis_zeitstempel_idx ON ereignis (zeitstempel);
CREATE INDEX IF NOT EXISTS ereignis_quelle_idx ON ereignis (quelle);

-- App-Rolle: append-only per Grants (nie UPDATE/DELETE/CREATE).
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ledger_app') THEN
        CREATE ROLE ledger_app LOGIN;
    END IF;
END
$$;
ALTER ROLE ledger_app WITH LOGIN PASSWORD :'app_pw';

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM ledger_app;
GRANT USAGE ON SCHEMA public TO ledger_app;
REVOKE ALL ON TABLE ereignis FROM ledger_app;
GRANT INSERT, SELECT ON TABLE ereignis TO ledger_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

COMMIT;
