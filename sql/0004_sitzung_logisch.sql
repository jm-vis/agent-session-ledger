-- 0004 — Logische Sitzung (ADR 0010 Folge, CONTRACTS.md C1, Phase 1 Arbeitspaket A).
-- Aufruf: docker exec -i sitzungsbeleg-postgres sh -c 'psql -U "$POSTGRES_USER" -d ereignis -v ON_ERROR_STOP=1 -f -' < 0004_sitzung_logisch.sql
-- Idempotent, nur DDL + Backfill + Grants -- Wiederholung ist folgenlos (siehe je Schritt).
--
-- Problem (C1): `sitzung` ist append-only; jede Neu-Erfassung erzeugt eine neue `sitzung.id`
-- (eine "Version"). Referenzen auf `sitzung.id` (Auffaelligkeits-Refs, Vier-Augen-Refs)
-- veralten dadurch mit jeder neuen Version derselben Sitzung. `sitzung_logisch` gibt einer
-- Sitzung (host, quelle, sitzung_id) eine STABILE ID, auf die neue Refs zeigen.

BEGIN;

CREATE TABLE IF NOT EXISTS sitzung_logisch (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    host             text NOT NULL,
    quelle           text NOT NULL CHECK (quelle IN ('claude','codex','produkt')),
    sitzung_id       text NOT NULL,
    projekt          text NOT NULL,           -- Projekt der ersten Version; Umzug = neue Version, kein UPDATE
    erste_version_am timestamptz NOT NULL DEFAULT now(),
    UNIQUE (host, quelle, sitzung_id)
);
ALTER TABLE sitzung                ADD COLUMN IF NOT EXISTS logisch_ref bigint REFERENCES sitzung_logisch (id);
ALTER TABLE sitzung_auffaelligkeit ADD COLUMN IF NOT EXISTS logisch_ref bigint REFERENCES sitzung_logisch (id);

-- Bestand: eine logische Zeile je (host, quelle, sitzung_id), projekt/erste_version_am von der
-- AELTESTEN Version (fruehester zeitstempel). ON CONFLICT DO NOTHING -- wiederholte Laeufe
-- legen keine Duplikate an.
INSERT INTO sitzung_logisch (host, quelle, sitzung_id, projekt, erste_version_am)
SELECT DISTINCT ON (host, quelle, sitzung_id) host, quelle, sitzung_id, projekt, zeitstempel
FROM sitzung
ORDER BY host, quelle, sitzung_id, zeitstempel ASC
ON CONFLICT (host, quelle, sitzung_id) DO NOTHING;

-- Versionen + flache Auffaelligkeiten auf ihre logische Zeile verdrahten (WHERE ... IS NULL:
-- ein zweiter Lauf aendert nichts mehr an schon gesetzten Zeilen).
UPDATE sitzung s SET logisch_ref = l.id
FROM sitzung_logisch l
WHERE s.logisch_ref IS NULL AND s.host = l.host AND s.quelle = l.quelle AND s.sitzung_id = l.sitzung_id;

UPDATE sitzung_auffaelligkeit a SET logisch_ref = s.logisch_ref
FROM sitzung s
WHERE a.logisch_ref IS NULL AND a.sitzung_ref = s.id;

-- Altlaeufe der Vier-Augen-Pruefung (ereignis.quelle='vieraugen') kennen nur die Version
-- (detail.sitzung_ref) -- Legacy-Leseregel (C1 Regel 2) ergaenzt die logische ID zusaetzlich,
-- damit neue UND alte Ereignisse ueber `#sitzung/<logisch>` auffindbar sind. Guard
-- `NOT (detail ? 'sitzung_logisch')`: ein zweiter Lauf ueberschreibt nichts mehr.
UPDATE ereignis e SET detail = e.detail || jsonb_build_object('sitzung_logisch', s.logisch_ref)
FROM sitzung s
WHERE e.quelle = 'vieraugen' AND (e.detail->>'sitzung_ref')::bigint = s.id
  AND NOT (e.detail ? 'sitzung_logisch');

-- Entscheide (quelle='gf', befund_entscheid) mit Sitzungsbezug: `sitzung_ref` war die Version,
-- ab Phase 1 schreibt das Frontend die logische ID. Bestand umhaengen, Version als
-- `sitzung_ref_version` behalten (Nachweis). Guard wie oben: nur Zeilen ohne Versionsvermerk.
UPDATE ereignis e SET detail = e.detail
    || jsonb_build_object('sitzung_ref', s.logisch_ref, 'sitzung_ref_version', s.id)
FROM sitzung s
WHERE e.quelle = 'gf' AND e.typ = 'befund_entscheid'
  AND (e.detail->>'sitzung_ref')::bigint = s.id
  AND NOT (e.detail ? 'sitzung_ref_version');

-- Ab hier ist jede Version einer logischen Sitzung zugeordnet -- erzwingen.
ALTER TABLE sitzung ALTER COLUMN logisch_ref SET NOT NULL;

-- Juengste Version je logischer Sitzung (ersetzt die alte (host,quelle,sitzung_id)-Fassung).
CREATE OR REPLACE VIEW sitzung_aktuell AS
    SELECT DISTINCT ON (logisch_ref) * FROM sitzung ORDER BY logisch_ref, ende DESC NULLS LAST, id DESC;

-- Contract-Konflikt (siehe Bericht Arbeitspaket A): `INSERT ... ON CONFLICT ... DO UPDATE`
-- (C1 Regel 3, Ingest) braucht laut Postgres-Semantik zusaetzlich UPDATE-Recht der Rolle, die
-- den Konflikt ausloest -- reines INSERT/SELECT reicht dafuer nicht, auch wenn das Update
-- faktisch ein No-Op ist (SET host = EXCLUDED.host). Minimal gehalten: nur Spalte `host`.
GRANT INSERT, SELECT ON TABLE sitzung_logisch TO ledger_app;
GRANT UPDATE (host) ON TABLE sitzung_logisch TO ledger_app;
GRANT SELECT ON sitzung_aktuell TO ledger_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;

COMMIT;
