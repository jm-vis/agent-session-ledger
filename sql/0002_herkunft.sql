-- 0002 — Sync-Herkunft (ADR 0006, Plan A7). Idempotent. Kein Passwort noetig (nur DDL).
-- herkunft_id = Original-id der Zeile auf der QUELL-Instanz (Server). Der Pull auf den PC
-- nutzt sie als Wasserzeichen und der partielle Unique-Index macht den Import idempotent
-- (ON CONFLICT DO NOTHING) - append-only macht Konflikte strukturell unmoeglich.
-- Lokal geschriebene Zeilen haben herkunft_id NULL.

BEGIN;

ALTER TABLE ereignis ADD COLUMN IF NOT EXISTS herkunft_id bigint;

CREATE UNIQUE INDEX IF NOT EXISTS ereignis_herkunft_idx
    ON ereignis (host, herkunft_id) WHERE herkunft_id IS NOT NULL;

COMMIT;
