-- 0006 — Modellkatalog (CONTRACTS.md C15, Paket L). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0006_modellkatalog.sql
-- Anders als ereignis/sitzung/chat (append-only, 0001/0003/0005): `modellkatalog` wird JE
-- ABRUFLAUF upgedatet (Preise/Kontext aendern sich), kein DELETE -- ein verschwundenes Modell
-- behaelt seinen letzten Stand (`katalog.py upsert_katalog`). Rolle ledger_app braucht darum
-- zusaetzlich UPDATE auf den Wertspalten -- analog zum Konflikt-UPDATE-Grant aus 0004
-- (Postgres verlangt UPDATE-Recht der Rolle auf den Spalten, die ein
-- `INSERT ... ON CONFLICT DO UPDATE` tatsaechlich setzt, auch wenn `ledger_app` sonst nur
-- INSERT/SELECT hat).

BEGIN;

CREATE TABLE IF NOT EXISTS modellkatalog (
    modell_id    text NOT NULL,
    hersteller   text NOT NULL,
    herkunft     text,                    -- ISO-2 (US/CN/EU/CA/...), unbekannt bleibt NULL
    anbieter     text NOT NULL CHECK (anbieter IN ('claude', 'ollama', 'openrouter', 'requesty')),
    kontext_k    int,                     -- Kontextfenster in k Token, NULL wenn nicht bekannt
    eingabe_usd  numeric,                 -- USD je 1M Token, NULL wenn keine Preisangabe
    ausgabe_usd  numeric,
    aa_index     int,                     -- v1 NULL-faehig, nur aus modelle.json (keine Live-Abfrage)
    coding_index int,
    stand        date NOT NULL,
    quelle       text NOT NULL,           -- Abrufquelle (URL oder 'scripts/modelle.json')
    PRIMARY KEY (modell_id, anbieter)
);

CREATE INDEX IF NOT EXISTS modellkatalog_stand_idx ON modellkatalog (stand);

REVOKE ALL ON TABLE modellkatalog FROM ledger_app;
GRANT INSERT, SELECT ON TABLE modellkatalog TO ledger_app;
GRANT UPDATE (hersteller, herkunft, kontext_k, eingabe_usd, ausgabe_usd, aa_index, coding_index, stand, quelle)
    ON TABLE modellkatalog TO ledger_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

COMMIT;
