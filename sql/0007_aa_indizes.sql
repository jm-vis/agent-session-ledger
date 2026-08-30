-- 0007 — Artificial-Analysis-Indizes (CONTRACTS.md C15 v2 Punkt 2). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0007_aa_indizes.sql
-- Ergaenzt `modellkatalog` (0006) um die drei Spalten, die `katalog.aktualisiere_aa_indizes`
-- per UPDATE fuellt -- kein neuer Bezugsweg (`anbieter`-CHECK bleibt unveraendert), nur
-- Anreicherung bestehender Zeilen. Rolle ledger_app braucht dafuer zusaetzliches
-- UPDATE-Recht auf genau diesen drei Spalten (Muster 0006: Postgres verlangt das explizit fuer
-- jede Spalte, die ein UPDATE tatsaechlich setzt).

BEGIN;

ALTER TABLE modellkatalog
    ADD COLUMN IF NOT EXISTS agentic_index integer,   -- round(evaluations.tau2 * 100), 0..100
    ADD COLUMN IF NOT EXISTS tempo_tok_s   numeric,    -- median_output_tokens_per_second (AA)
    ADD COLUMN IF NOT EXISTS aa_stand      date;        -- Datum des letzten AA-Anreicherungslaufs je Zeile

GRANT UPDATE (agentic_index, tempo_tok_s, aa_stand) ON TABLE modellkatalog TO ledger_app;

COMMIT;
