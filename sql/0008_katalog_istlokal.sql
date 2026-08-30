-- 0008 — Modellkatalog `lokal`-Spalte (Abnahme 2026-08-30, Fix 2). Idempotent, nur DDL + Grants.
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0008_katalog_istlokal.sql
-- Bug: `katalog_sicht._ist_lokal()` wertete das Cloud-/Lokal-Flag bisher live aus `modell_id`
-- aus -- nach Migration 0006 unproblematisch, aber die C15-v2-Kanonisierung (Fix 3, dieselbe
-- Welle) kappt Ollama-Cloud-Suffixe fuer die Katalog-GRUPPIERUNG. Ohne eigene Spalte wuerde
-- `_ist_lokal()` dann auf der schon gekappten ID auswerten und jedes Ollama-Cloud-Modell
-- faelschlich als lokal zeigen. Die Spalte wird an der ROHEN modell_id bei der Beschaffung
-- gesetzt (`katalog.KatalogZeile.lokal`, `parse_ollama_tags`/`von_modelle_json`) und bleibt
-- davon unabhaengig immer korrekt. DEFAULT false ist fuer Bestandszeilen sicher (nicht-Ollama-
-- Zeilen sind nie lokal; alte Ollama-Zeilen werden beim naechsten `katalog-update --db` neu
-- upgesertet und bekommen den echten Wert).

BEGIN;

ALTER TABLE modellkatalog
    ADD COLUMN IF NOT EXISTS lokal boolean NOT NULL DEFAULT false;

GRANT UPDATE (lokal) ON TABLE modellkatalog TO ledger_app;

COMMIT;
