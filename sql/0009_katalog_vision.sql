-- 0009 — Modellkatalog `vision`-Spalte (Entscheid 2026-08-30, Sterne-Rubrik v2). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0009_katalog_vision.sql
-- Bild-Faehigkeit je Zeile (tri-state: true=kann Bilder lesen, false=kann es nicht,
-- NULL=unbekannt/noch nicht ermittelt) -- Basis fuer den 4,0-Sterne-Deckel bei `vision=false`
-- (katalog_sicht._mit_vision_deckel). Kein DEFAULT (bewusst NULL fuer Bestandszeilen, "unbekannt"
-- ist der korrekte Ausgangszustand, nicht "kein Bild" -- s. katalog.KatalogZeile.vision).

BEGIN;

ALTER TABLE modellkatalog
    ADD COLUMN IF NOT EXISTS vision boolean;

GRANT UPDATE (vision) ON TABLE modellkatalog TO ledger_app;

COMMIT;
