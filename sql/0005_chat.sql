-- 0005 — Chat-Tabelle (CONTRACTS.md C4 "Chat — eigene Tabelle `chat`", Phase 1 D). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0005_chat.sql
-- Eigene Tabelle statt `ereignis` (ADR 0006 2b verbietet Gespraechsinhalte im Ereignisstrom, Codex-
-- Fund 2 aus dem Contracts-Review) -- append-only wie `ereignis`/`sitzung`: Rolle ledger_app darf
-- INSERT + SELECT, nie UPDATE/DELETE. Eine Zeile je Nachricht, `detail` nach `contracts.ChatNachricht`.

BEGIN;

CREATE TABLE IF NOT EXISTS chat (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zeitstempel timestamptz NOT NULL DEFAULT now(),
    gespraech_id text NOT NULL,
    host        text NOT NULL DEFAULT 'pc',
    detail      jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS chat_gespraech_idx ON chat (gespraech_id, id);

REVOKE ALL ON TABLE chat FROM ledger_app;
GRANT INSERT, SELECT ON TABLE chat TO ledger_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

COMMIT;
