# CONTRACTS — Sitzungsbeleg-Dashboard (Phase 0, Prozesslogik)

> **Was das ist:** die Interface Contracts, gegen die Phase 1–3 bauen. Vier Agenten arbeiten parallel
> (A Datenintegrität · B Prüf-Regelwerk · C Delegation · D Chat-Shell); damit ihre Teile ohne Reibung
> zusammenpassen, steht hier **vorab** fest: Schema, Zustände, Ereignis-Formate, API-Formen, Frontend-Slots.
>
> **Quelle ist `contracts.py` (Pydantic).** Diese Datei ist die lesbare Fassung; jedes JSON-Beispiel hier ist
> wortgleich in `contracts.BEISPIELE` und wird gegen sein Modell validiert (`tests/test_contracts.py`).
> HTTP-Formen liefert FastAPI zusätzlich als OpenAPI (`/docs`). **Regel:** Wer einen Contract ändern muss,
> ändert **zuerst `contracts.py` + diese Datei + Tests**, dann den Code — nie umgekehrt.
>
> **Abgrenzung:** Der *Kontrakt-Block* in einer README (Zweck/Inputs/Prozess/Outputs/Abnahme, ICM-Entscheid 7)
> beschreibt den **Arbeitsauftrag** eines Ordners. Ein *Interface Contract* beschreibt eine **technische
> Schnittstelle** zwischen zwei Bausteinen.

## Änderungen

| Datum | Änderung | Kompatibel |
|---|---|---|
| 2026-08-30 | C15 Nachtrag 7 (Festlegung): kuratierte Generations-Schwellen je Produktlinie (`generationen.json`) haben VORRANG vor der automatischen `familie()`-Versionsregel aus Nachtrag 5/6 -- neue Funktion `produktlinie()` (`familie()` ohne Stufen-Woerter) und `generation_status()`; additiv Alias-Kanonisierung in `katalog.kanonische_id()` (`-latest`/`:high`/`:medium`/`:low`/`:priority`/`:free`/`:nitro`/`:exacto`/`:online` sind Bezugsvarianten, keine eigenen Modelle) | ja (neue Datei + zwei neue Funktionen, `status`/`nachfolger` bleiben dieselben Felder, nur die Zuordnung dazu aendert sich fuer Linien mit kuratierter Schwelle) |
| 2026-08-30 | C15 Nachtrag 6 (Entscheid, vier Punkte): (1) `familie()` bestaetigt/praezisiert (Stufen-Woerter wieder Teil der Familie, nur reine Modifikatoren -exp/-preview/... bleiben draussen); (2) additiv `status: "bewertet"\|"latest"\|"legacy"` je Modell; (3) Sterne-Rubrik v2 ERSETZT die Quintil-/Kontext-Formel aus Nachtrag 2/4: `sterne.score`/`sterne.gesamt` (halbe Sterne 0,5–5,0) aus `(aa_index+coding_index)/2`, Boden 45, relativ zum besten Score der aktuellen Modelle, `vision`-Deckel 4,0; `sterne.intelligenz`/`coding`/`kontext` entfallen; (4) additiv `vision: bool\|null` je Modell (Migration `0009_katalog_vision.sql`), Panels zeigen gruenen Erreichbarkeits-Punkt + reinen Modellnamen (hf.co ohne Org/Quant) | teilweise nein (`sterne.intelligenz`/`coding`/`kontext` entfallen ersatzlos, Nachtrag-2-Leser muessten angepasst werden — kein bestehender Leser ausser `katalog.js`, hier mit angepasst); `status`/`vision` sind additiv |
| 2026-08-30 | C15 Nachtrag 5 (Abnahme, zwei Funde): (1) `familie()` praezisiert -- Stufen-Woerter (`mini`/`flash`/`opus`/`sonnet`/`fable`/`sol`/`terra`/`luna`/... s. `_STUFE_WOERTER`) erzeugen keine eigene Familie mehr, Baugroessen/Datums-Stempel (`20b`, `2024-11-20`, `2603`) zaehlen weder als Version noch Familie, `neueste_je_familie()` haelt echten Gleichstand jetzt als Menge statt eines Namens-Tiebreaks; (2) Persona-/LOKAL-Panels zeigen keine Herkunft-Flagge/Pin-Symbol/HF-Abzeichen mehr (`modellNameHtml(id, klasse, mitBadge=false)`) | ja (reine Praezisierung der C15-Nachtrag-4-Logik + Frontend-Vereinfachung, kein Schema-Feld geaendert) |
| 2026-08-28 | C13-Nachtrag (Entscheid 14:30): `wache.json` vereinfacht (`rework:tool`=`fragen`, sonst `standard`=`warnen`); Meldungsspur `_work_sitzungsbeleg/wache-meldungen.jsonl` (eine Zeile je AUSGEGEBENER Meldung, warnen UND fragen); neues Lese-Modul `wache_web.py` (`GET /api/wache/meldungen`, `GET /api/sitzung/{id}/wache`, 30 s Cache, nur lesend); Start-Kachel „Wache" (`start.js`) + Verlauf-Marke (`sitzung.js` `wacheMarkerJeIndex`) | ja (neue Datei/Endpunkte, kein Schema-Feld geändert) |
| 2026-08-28 | C12-Umsetzung: `SichtFilter.umgebungen` (neu, optional, `[]`) -- aktive Checkboxen des Seitenleisten-Blocks „Umgebung" im Sichtpaket (C7), wie `quellen`/`kontexte` | ja (neues optionales Feld, `schema` bleibt) |
| 2026-08-28 | Neu C13 Wache (Paket J, Gunnar-Anregung, Go 13:40): PreToolUse-Hook `python -m sitzungsbeleg wache` wendet die bestehenden Regeln (`regeln.pruefe`) auf das LAUFENDE Transkript an und gibt Warnungen als `additionalContext` zurueck; bei Signaturen mit verankertem `erledigt`-Entscheid (C11) nennt die Warnung Art+Pfad der Verankerung. Stufen je Regel `aus\|warnen\|fragen` in `wache.json` (Default warnen; `fragen` = `permissionDecision: ask`). Entscheide-Cache `_work_sitzungsbeleg/wache-entscheide.json` (Dashboard-Dienst schreibt alle 10 min, Hook liest nur). Fail-open, ≤ 300 ms, kein DB-Zugriff im Hook. Keine Schema-Aenderung | ja (neuer Leser, keine gespeicherten Formen) |
| 2026-08-28 | Neu C11 Verankerung (Entscheid 13:40: ein Entscheid ist erst dann einer, wenn er an einem Ort wirkt, den die naechste Sitzung liest): `befund_entscheid.detail.verankerung` = `{art, pfad, abschnitt}` (optional im Schema, PFLICHT bei `status=erledigt`, Server lehnt 400 ab); Arten `troubleshooting\|adr\|runbook\|playbook\|hook\|skill\|regel\|vorhaben`; neues Pydantic-Modell `contracts.BefundEntscheid` + `Verankerung`, `speicher.ereignis_schreiben` validiert `gf/befund_entscheid` (MODELL_JE_QUELLE). Waechter `scripts\check-verankerung.ps1` (ruft `python -m sitzungsbeleg verankerung-pruefen`, nur lesend) meldet erledigte Entscheide, deren `pfad` nicht existiert. Alt-Entscheide ohne Verankerung bleiben gueltig (Dual-Reader: `verankerung` None = Legacy). Neu C12 Achse Umgebung (Maintainer 12:45): `Kopf.umgebung ∈ {entwicklung, abnahme, betrieb}`, Default `entwicklung`, Quelle Stop-Hook aus `SITZUNGSBELEG_UMGEBUNG`; UI nur bei Abweichung als Kuerzel in der Projekt-Zelle (`Abn.`/`Betrieb`), Seitenleisten-Block erst ab zwei Werten im Zeitraum | ja (optionale Felder, `schema` bleibt; Pflicht-Regel greift nur fuer NEUE `erledigt`-Entscheide) |
| 2026-08-27 | Erstfassung C1–C8 | — |
| 2026-08-27 | Welle-1-Integration: `POST /api/pruefung` asynchron — 202 liefert `stufe_max: null` (steht erst nach Stufe 1 fest), Ergebnis im Ereignis; App-Rolle zusätzlich `UPDATE (host)` auf `sitzung_logisch` (ON CONFLICT DO UPDATE braucht das); Migration hängt auch `gf/befund_entscheid.sitzung_ref` auf die logische ID um (`sitzung_ref_version` bleibt); Querschnitt-Drilldown liefert logische IDs; Legacy `/pruefen`-Routen nehmen die logische ID | ja |
| 2026-08-27 | Codex-Review (14 Funde, `scripts/_work_sitzungsbeleg/2026-08-27-codex-contracts.md`): Pydantic als Quelle, Validierung im Schreibpfad, Chat in eigene Tabelle, Lauf-Schlüssel, Übergangsroute, Legacy-Leseregel, `eskaliert`, Rang Rückfall | ja (vor Phase 1) |
| 2026-08-27 | Welle-2-Nachtrag Punkt 2: `UrteilZeile.lauf_id` (optional) -- der erzeugende Lauf je Signatur-Urteil, damit "Codex nachholen" `{stufe:2, lauf_ref}` bauen kann | ja |
| 2026-08-27 | Welle-2-Nachtrag Punkt 7: `POST /api/chat/{gespraech_id}/fix` (neu) -- Hintergrund-Chat liest nur (`--allowedTools`, kein permissiver Modus mehr), "Fix umsetzen" oeffnet ein sichtbares Fix-Fenster statt selbst zu aendern | ja |
| 2026-08-27 | Welle-2-Nachtrag Punkt 8: `redaktion.bereinige_chat_text()` (neu, nur Chat) -- redigiert nur den Pfad-TOKEN statt der ganzen Nachricht bei jedem Schraegstrich; `bereinige_text()` (Beleg/Stufe-1-2-Urteile) unveraendert | ja |
| 2026-08-27 | Welle-2-Nachtrag OpenRouter: dritter Chat-Anbieter `openrouter` (`ChatNachricht.anbieter`, `ChatBody.anbieter`) -- Cloud-Anbieter wie Claude (C6, nur bei `schutz=cloud-ok`), eigene Modell-Quelle `GET /api/chat/modelle.openrouter` + `openrouter_hinweis` | ja (neuer Enum-Wert, `schema` bleibt) |
| 2026-08-27 | Coordinator-Nachtrag Punkt 2 (OpenRouter listet mehrere Hundert Modelle): `modelle.openrouter`-Objekte `{id, kontext}` statt `{id, name}`; Frontend gruppiert in Optgroups `:free`/alle Modelle | ja (Feldform nur bei `openrouter`, `claude`/`ollama` unveraendert) |
| 2026-08-27 | Coordinator-Nachtrag Punkt 3 + Endentscheid: Standardauswahl OpenRouter ueber `chat.js` `OPENROUTER_STANDARD_BEVORZUGT` (Praeferenzliste statt fixem Modellnamen -- `deepseek-chat-v3-0324` ist nicht mehr `:free`); Endreihenfolge `nvidia/nemotron-3-ultra-550b-a55b:free`, `z-ai/glm-5.2:free`, `minimax/minimax-m3:free` | ja (nur Frontend-Default) |
| 2026-08-27 | Coordinator-Nachtrag (Konto-Datenschutz/ZDR): Modellliste folgt den Konto-Einstellungen -- mit Schluessel authentifiziert `GET /v1/models/user` (Bearer-Header), ohne Schluessel oeffentlich `GET /v1/models`; verifiziert 255/2 `:free` (ZDR an) vs. 417/18 `:free` (oeffentlich) | ja (nur welche URL/Header `chat._openrouter_anfrage()` waehlt, Antwortform unveraendert) |
| 2026-08-27 | Coordinator-Nachtrag: OpenRouter-Endreihenfolge korrigiert auf `nvidia/nemotron-3-ultra-550b-a55b` (ohne `:free`), `z-ai/glm-5.2:free`, `minimax/minimax-m3` (ohne `:free`) -- verifiziert gegen `/models/user`; zusaetzlich EINE `STANDARD_BEVORZUGT`-Konstante fuer alle drei Anbieter (`chat.js` `standardModell()`), angewandt bei Initial-Laden + Anbieterwechsel, ausser der Nutzer hat fuer diesen Anbieter in der Seiten-Sitzung schon selbst gewaehlt (`eigeneModellwahl`) | ja (nur Frontend-Default-Logik) |
| 2026-08-27 | Fund „Besprechung blind für Kennzahlen": `Kontext.kennzahlen_block` (neu, optional, ≤ 1500 Zeichen) -- Server baut ihn aus derselben `web._sitzung()`-Antwort wie die Detailseite (`chat_kennzahlen.baue_block()`), haengt ihn bei `POST /api/chat` mit Sitzungskontext an und liefert ihn zusaetzlich in `GET /api/sitzung/{id}` fuer den Chip-Tooltip (C7) | ja (neues optionales Feld, `schema` bleibt) |
| 2026-08-28 | Neu C9 (Retention): `python -m sitzungsbeleg retention-sql` erzeugt eine DELETE-SQL-Datei fuer Sitzungen aelter als N Tage (Mindestwert 7, `--quelle` ohne stillen Default) -- kein Contract-/Schema-Bruch, reiner CLI-Zusatzbefehl, `ledger_app` bleibt ohne DELETE-Recht | ja (additiv, kein bestehendes Feld/Schema betroffen) |
| 2026-08-28 | Welle-3-H-Umsetzung `GET /api/rohdatei/{sitzung_logisch}` (Contract `contracts.RohdateiAntwort`, Modul `rohdatei.py`): Fensterzentrierung ueber `ereignisse[position].zeit` statt ueber `position` als Rohzeilen-Index (Ereignisse sind eine gefilterte Projektion, kein 1:1-Mapping zur Rohdatei) -- Praezisierung, kein Contract-Bruch. `zulaessigkeit` server-seitig aus `_sitzung()`, nicht vom Client. Subagent-Transkripte bewusst ausgeklammert (offener Punkt) | ja (Praezisierung einer noch ungebauten Route) |
| 2026-08-28 | Nachtrag Requesty (vierter Chat-Anbieter, Auftrag): `anbieter ∈ {claude, ollama, openrouter, requesty}` (`ChatNachricht`/`ChatBody`) -- Cloud-Anbieter wie Claude/OpenRouter (C6, nur bei `schutz=cloud-ok`). Modellliste `GET /api/chat/modelle?alle=<bool>` liefert zusaetzlich `"requesty": [{"id", "kontext", "preis_in", "preis_out", "region"}]` aus der OEFFENTLICHEN `GET https://router.requesty.ai/v1/models` (kein Schluessel noetig), Default-Filter `geolocation=="eu"` UND `data_used_for_training==false`, `alle=true` zeigt den vollen Katalog; `requesty_standard` aus `modelle.json default_vico_requesty`, `requesty_hinweis` nur bei Fehler/Offline. Chat-Bruecke wie OpenRouter (`ANTHROPIC_BASE_URL=https://router.requesty.ai`, `ANTHROPIC_AUTH_TOKEN` aus `REQUESTY_API_KEY`/`scripts\.env.requesty`). Neu `Kopf.backend` (optional, `modell.py`): der Stop-Hook liest `ANTHROPIC_BASE_URL` aus seiner geerbten Umgebung und schreibt nur die Hostklasse (`anthropic\|ollama\|openrouter\|requesty\|unbekannt`, nie URL/Token) -- `quellen.quelle_fuer()` prueft `backend` VOR der bisherigen Modell-Kette, noetig weil Requesty-Modell-IDs wie OpenRouter-IDs aussehen (`anthropic/claude-sonnet-5`). Neu CLI `python -m sitzungsbeleg anbieter-test <anbieter>`: ein kurzer `claude -p`-Testlauf ueber die Bruecke, zeigt Exit-Code/STDOUT/STDERR fuer die Live-Klaerung offener Header-/Auth-Fragen | ja (neue Enum-Werte/optionales Feld, `schema` bleibt) |
| 2026-08-28 | Nachtrag Sichtkontext (Auftrag "Dashboard-Ansicht ist fuer mich nicht sichtbar"): neuer Contract `Sicht` (`ChatBody.sicht`, optional) -- welche Ansicht offen ist, Zeitraum/Filter, die aktuell sichtbaren Sitzungszeilen (max. 30); `chat_bruecke._sicht_block()` haengt daraus einen Block `SICHT:` an die erste Chat-Nachricht (C7). Neues Lesewerkzeug `python -m sitzungsbeleg nachschlagen <nr> [--befund <signatur>]` (Kennzahlen + volle Befundliste mit Status/Vier-Augen-Urteil, nur lesend) -- Hintergrund-Chat darf es per `--allowedTools` zusaetzlich zu Read/Grep/Glob ausfuehren, Kindprozess-Arbeitsverzeichnis jetzt `scripts/` (vorher Repo-Wurzel), damit `python -m sitzungsbeleg` dort auflöst | ja (neues optionales Feld, additiver CLI-Befehl, `schema` bleibt) |
| 2026-08-28 | Neu C10 (Phase 3 I, Tiefenanalyse-Umsetzung): `Tiefenanalyse` praezisiert -- `urteil` ist jetzt der KONSENS-Wert (`uebereinstimmend\|dissens\|ohne_zweitmeinung`, vorher faelschlich `Ergebnis` aus C4/PruefungLauf); neues `TiefenanalyseUrteil` (`ursache_kategorie, befund, empfehlung, urteil, komplexitaet`) fuer `positionen.claude`/`positionen.codex` (vorher nackte Strings) -- Mockup B1/B2 zeigt auf beiden Seiten alle vier Felder, nicht nur Text. Zusaetzlich `runde` (Session-Runde der Position, Echo), `modell_stufe2`, `zeitstempel`, `dauer_ms`, `commits` (Hash-Liste, NIE der Diff), `nur_lokal`, `fehler` -- alles additiv zur Erstfassung, die noch nicht gebaut/verwendet war (kein Bruch). Endpunkte `POST/GET /api/sitzung/{id}/tiefenanalyse`, `GET /api/sitzung/{id}/commits[/{hash}]` (Module `tiefenanalyse.py`, `commits.py`) | ja (Erstfassung war ungebaut, Praezisierung vor dem ersten Verbraucher) |
| 2026-08-28 | Layout-Nachtrag C7 (Auftrag "Mitte ortsfest"): Fehlerbilder & Entscheide/Produkt/Einstellungen bekommen ein leeres `aside.leerspalte` (300 px, `aria-hidden`) statt gar keiner ersten Spalte -- `.hauptspalte` steht dadurch auf allen fuenf Seiten an derselben `left`/`width`-Position, Chat unveraendert. Nur `style.css`/`index.html`, kein Contract-/Schema-Feld betroffen. Wächter `check_sitzungsbeleg_layout.py` erweitert (Hash-Wechsel statt erneutem `goto`, sonst haengt `networkidle` an offenen Chat-/Polling-Verbindungen) | ja (reines Markup/CSS, keine Contract-Aenderung) |
| 2026-08-28 | Paket K (Tiefenanalyse, Entscheid 14:10): Werkzeugfehler-Rohtexte gehen in den Stufe-1-Prompt durch -- `tiefenanalyse._fehlertexte()` liest sie im Lauf direkt aus der Rohdatei (`rohdatei.zeile_bei()`, neuer lesender Helfer, gleiche Zeit-Zentrierung wie `baue_antwort`), max. 20 Stueck, je hart auf 300 Zeichen gekappt, redigiert VOR dem Kappen ueber neues `redaktion.bereinige_fehlertext()` (baut auf `bereinige_text()` auf, zusaetzlich `<host>`/`<schluessel>`/`<name>` token-weise). Landen NUR im Prompt (Stufe 1, nie Stufe 2), NIE in `ereignis.detail`/DB/Log. C6-Weiche wie beim Rohdatei-Zugriff: bei `zulaessigkeit(dokument) == geschuetzt` nur, wenn `nur_lokal` (Lauf geht sowieso ueber Ollama) -- sonst leere Liste + Vermerk im Prompt statt Sperre; fehlende/verschobene Rohdatei ebenso fail-open (Vermerk statt Fehler). Kein Contract-/Schema-Feld betroffen (reine Prompt-Eingabe) | ja (kein Feld geaendert, nur Prompt-Inhalt) |

**Änderungsverfahren (Codex-Frage E):** Subagenten **melden** Contract-Brüche (im Bericht, Abschnitt
„Contract-Konflikt"), ändern aber nicht selbst; VICO entscheidet, Maintainer bei Datenschutz/Datenmodell. Während
einer Welle ist der Contract **eingefroren**, außer ein Blocker steht. Kompatible Ergänzung (neues optionales
Feld) → `schema` bleibt; Bruch → `schema + 1` und der Leser versteht beide Fassungen (Dual-Reader).

Konventionen: Feldnamen Deutsch, snake_case (wie `modell.py`). Zeiten ISO-8601 mit Zeitzone. IDs `bigint`.
Nichts hier enthält Rohtext aus Transkripten (Prompts, Tool-Argumente, Fehlertexte) — Leitplanke des Belegs.

---

## C1 · Schema: logische Sitzung und Versionen

**Problem:** `sitzung` ist append-only; jede Neu-Erfassung = neue `sitzung.id`. Refs auf `sitzung.id`
veralten (1 893 Auffälligkeits-Refs, 2 Vier-Augen-Refs, Stand 2026-08-27).

**Contract (Migration `infra/sitzungsbeleg-db/0004_sitzung_logisch.sql`, idempotent, Maintainer führt aus):**

```sql
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
-- Bestand: logische Zeilen aus DISTINCT (host, quelle, sitzung_id), dann UPDATE beider logisch_ref-Spalten
-- (Admin-Rolle; einmalig). Danach: ALTER TABLE sitzung ALTER COLUMN logisch_ref SET NOT NULL.
-- ereignis (vieraugen, Altlaeufe): UPDATE ereignis SET detail = detail || jsonb_build_object('sitzung_logisch', s.logisch_ref)
--   FROM sitzung s WHERE quelle='vieraugen' AND (detail->>'sitzung_ref')::bigint = s.id;   -- Admin, einmalig
CREATE OR REPLACE VIEW sitzung_aktuell AS
    SELECT DISTINCT ON (logisch_ref) * FROM sitzung ORDER BY logisch_ref, ende DESC NULLS LAST, id DESC;
GRANT INSERT, SELECT ON TABLE sitzung_logisch TO ledger_app;
GRANT UPDATE (host) ON TABLE sitzung_logisch TO ledger_app;   -- ON CONFLICT DO UPDATE braucht UPDATE-Recht
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ledger_app;
```

Regeln:
1. **Jede API-Antwort trägt beide IDs:** `sitzung_logisch` (stabil, für Refs) und `version` (= `sitzung.id`,
   für Dokument-Zugriff). `GET /api/sitzung/{id}` nimmt **die logische ID**; `?version=<sitzung.id>` liefert
   gezielt eine ältere Fassung.
2. **Neue Refs zeigen immer auf `sitzung_logisch.id`:** `sitzung_auffaelligkeit.logisch_ref`,
   `ereignis.detail.sitzung_logisch`. `sitzung_ref` wird von neuem Code **nicht mehr geschrieben**.
   **Legacy-Leseregel:** Leser nehmen `detail.sitzung_logisch`, wenn vorhanden; sonst lösen sie
   `detail.sitzung_ref` über `sitzung.logisch_ref` auf (Funktion `speicher.logisch_fuer_version(id)`).
   Nach der Admin-Migration oben tragen alle Altereignisse beide Felder.
3. **Ingest (`speicher.speichern`):** eine Transaktion, CTE:
   `WITH l AS (INSERT INTO sitzung_logisch (host,quelle,sitzung_id,projekt) VALUES (…) ON CONFLICT (host,quelle,sitzung_id) DO UPDATE SET host = EXCLUDED.host RETURNING id) INSERT INTO sitzung (…, logisch_ref) SELECT …, l.id FROM l …`
   (`DO UPDATE` ohne Änderung, damit `RETURNING` auch im Konfliktfall liefert). App-Rolle: INSERT/SELECT auf
   `sitzung_logisch` (Grant oben), kein UPDATE/DELETE.
4. **Wächter** `scripts/check-sitzungsbeleg-refs.ps1`: Versionen ohne `logisch_ref`, Auffälligkeiten ohne
   `logisch_ref`, Ereignisse (`quelle IN ('vieraugen','pruefung','tiefenanalyse')`) ohne
   `detail.sitzung_logisch` → Exit 1. Muss einmal rot gewesen sein (ADR 0004).
5. **Übergang alter Links (eindeutig):** Router bleibt `#sitzung/<n>`. Frontend ruft `GET /api/sitzung/<n>`
   (logisch). Antwortet der Server 404, ruft es **einmal** `GET /api/sitzung/version/<n>` →
   `{"sitzung_logisch": k}` und schreibt den Hash auf `#sitzung/k` um (kein Reload); 404 auch dort → Fehlkarte.
   Neue Links entstehen nur noch mit logischen IDs. Der Server rät nie, welche ID gemeint ist.

---

## C2 · Zustandsmodell Befund

Ein **Befund** = (`sitzung_logisch`, `signatur`). Eine **Gruppe** = alle Befunde einer Regel in einer Sitzung.
**Sechs sichtbare Zustände** (Entscheid 2) — `erledigt`/`obsolet` sind ein Zustand „entschieden" mit zwei
Werten; `rueckfall` ist abgeleitet, nie gespeichert. Modell: `contracts.STATUS` (8 Werte).

| Zustand | Wert | Wer setzt | Auslöser |
|---|---|---|---|
| offen | `offen` | Regel (Ingest) | Auffälligkeit ohne jüngeres Ereignis; oder Entscheid `offen` (Wiedereröffnung) |
| in Prüfung | `in_pruefung` | Prüf-Lauf | `POST /api/pruefung` gestartet, noch kein Ergebnis |
| bestätigt | `bestaetigt` | Prüf-Lauf | Stufe 1 (und 2, falls fällig) sagen „ja" |
| verworfen | `verworfen` | Prüf-Lauf | Stufe 1 (und 2) sagen „nein" |
| Dissens | `dissens` | Prüf-Lauf | Urteile weichen ab **oder** ein Urteil ist „unklar"; nur mit Zweitmeinung möglich |
| entschieden | `erledigt` · `obsolet` | Maintainer | `befund_entscheid` (bestehend, je Signatur, optional je Sitzung) |
| Rückfall | `rueckfall` | abgeleitet | Signatur mit Entscheid `erledigt`, neue Sitzung nach dem Entscheid zeigt sie wieder |

Ableitungsregel (`pruefung.status_fuer(befund, ereignisse)`), streng in dieser Reihenfolge:
1. Jüngster Entscheid für die Signatur (sitzungsbezogen schlägt global): `erledigt`/`obsolet` → dieser Wert;
   Ausnahme: Sitzung jünger als Entscheid und Entscheid war `erledigt` → `rueckfall`. Entscheid `offen` → weiter.
2. Laufender Prüf-Lauf, der diese Signatur umfasst → `in_pruefung`.
3. Jüngstes `pruefung`-Ereignis mit Urteil zu dieser Signatur → `bestaetigt` | `verworfen` | `dissens`.
4. Sonst `offen`.

**Gruppenstatus** (`contracts.gruppenstatus`) = höchster Rang: `dissens` > `in_pruefung` > `rueckfall` > `offen` >
`bestaetigt` > `verworfen` > `erledigt` > `obsolet` (Rückfall ist handlungsrelevant, Codex-Fund 6). Frontend zeigt
Pillen **gleich groß** (feste Breite, `.pille[data-status]`), `erledigt`/`obsolet` umrandet statt gefüllt.

---

## C3 · Prüf-Stufen und Scopes

| Stufe | Wer | Input | Output |
|---|---|---|---|
| 0 | `regeln.py` | Beleg | Auffälligkeit (`offen`) |
| 1 | Claude-Subagent (Sonnet; Opus bei Schwere `hoch`) | redigierter Beleg (+ lokaler Rohausschnitt nur bei Tiefenanalyse) | je Signatur: `kategorie`, `komplexitaet` ∈ {einfach, komplex}, `empfehlung`, `urteil` ∈ {ja, nein, unklar} |
| 2 | Codex (read-only Clone; **nie Rohtext**) | redigierter Beleg + redigierte Stufe-1-Ausgabe | `urteil` ∈ {ja, nein, unklar}, `begruendung` |
| 3 | Maintainer | Dashboard | `befund_entscheid` |

**Kleinfehler-Ausnahme** (Stufe 2 entfällt), kodiert in `pruefung.stufe_fuer(befund, historie) -> 1 | 2`:
alle vier Bedingungen: Schwere `hinweis` **und** Stufe 1 `einfach` **und** Signatur in < 3 Sitzungen (30 Tage)
**und** kein Rückfall. Sonst Stufe 2 Pflicht. Ergebnis trägt `zweitmeinung: "ausgelassen"` + Knopf
„Codex nachholen" (`POST /api/pruefung` mit `stufe: 2`, `lauf_ref`).

**Eskalation (Entscheid 8):** Taucht eine Signatur nach einem Lauf mit `zweitmeinung: ausgelassen` in einer
späteren Sitzung wieder auf, ist Stufe 2 Pflicht und das Urteil trägt `eskaliert: true`; Frontend zeigt das
Kennzeichen „eskaliert" an der Gruppe. `stufe_fuer` prüft das über die Lauf-Historie der Signatur.

Scopes: `befund` (eine Gruppe in einer Sitzung) · `sitzung` (alle offenen der Sitzung) · `fehlerbild` (eine
Signatur über N Sitzungen; Ergebnis zusätzlich als Datei `_work/<datum>-standardisierung-<signatur>.md`).

---

## C4 · Ereignis- und Chat-Contracts

Alle Detail-Objekte tragen `schema: 1`. Kein Feld enthält Rohtext; Freitexte sind Modell-Ausgaben, durch
`redaktion.bereinige_text()` gelaufen, ≤ 2 000 Zeichen. **`speicher.ereignis_schreiben` validiert `pruefung`
und `tiefenanalyse` vor dem INSERT** (`contracts.validiere_ereignis`); ein Contract-Fehler schreibt nichts.

**`ereignis` · `quelle='pruefung', typ='lauf'`** — ein Ereignis je Lauf (auch bei Fehler):
```json
{"schema": 1, "lauf_id": "p-20260827-143012-7f3a", "scope": "befund", "sitzung_logisch": 512,
 "signaturen": ["rework:tool:Bash"], "stufe_max": 2, "modell_stufe1": "claude-sonnet-5",
 "modell_stufe2": "gpt-5.5", "gestartet": "2026-08-27T14:30:12+02:00", "dauer_ms": 48211,
 "urteile": [{"signatur": "rework:tool:Bash", "kategorie": "Nacharbeit", "komplexitaet": "einfach",
              "empfehlung": "…", "claude": "ja", "codex": "ja", "ergebnis": "bestaetigt",
              "zweitmeinung": "eingeholt", "eskaliert": false, "begruendung_codex": "…",
              "lauf_id": "p-20260827-143012-7f3a"}],
 "fehler": null}
```
`ergebnis` ∈ {bestaetigt, verworfen, dissens}; `codex` ist genau dann `null`, wenn `zweitmeinung = ausgelassen`
(dann nie `dissens`). Scope `fehlerbild`: `sitzung_logisch = null`, genau eine Signatur, zusätzlich
`sitzungen: [512, 480, …]`, `tabelle: [{sitzung_logisch, einordnung ∈ {sauber, abgewichen, halluziniert}}]`,
`datei: "_work/…"`. `lauf_id` = `p-<JJJJMMTT>-<HHMMSS>-<4 hex>`.

**`ereignis` · `quelle='tiefenanalyse', typ='befund'`** (Phase 3, Vollform siehe C10):
```json
{"schema": 1, "scope": "befund", "signatur": "rework:tool:Bash", "sitzung_logisch": 512,
 "position": 41, "runde": 11, "stufe": 2, "ursache_kategorie": "Heredoc-Backslash",
 "befund": "…", "empfehlung": "…", "urteil": "dissens",
 "positionen": {
   "claude": {"ursache_kategorie": "Heredoc-Backslash", "befund": "…", "empfehlung": "…",
              "urteil": "ja", "komplexitaet": "einfach"},
   "codex": {"ursache_kategorie": "Gewollte Retry-Logik", "befund": "…", "empfehlung": "…",
             "urteil": "nein", "komplexitaet": null}},
 "modell": "claude-opus-5", "modell_stufe2": "gpt-5.5", "redaktion_version": "2026-08-28",
 "zeitstempel": "2026-08-28T14:30:12+02:00", "dauer_ms": 48211, "commits": ["a1b2c3d"],
 "nur_lokal": false, "fehler": null}
```

**Chat — eigene Tabelle `chat`, nicht `ereignis`** (Codex-Fund 2: ADR 0006 2b verbietet Gesprächsinhalte im
Ereignisstrom; Entscheid 9 wollte Postgres + Filterbarkeit — beides erfüllt eine eigene append-only
Tabelle in derselben DB, gleiche App-Rolle. **Entscheid offen:** so, oder ADR 0006 ändern.)
```sql
CREATE TABLE IF NOT EXISTS chat (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, zeitstempel timestamptz NOT NULL DEFAULT now(),
    gespraech_id text NOT NULL, host text NOT NULL DEFAULT 'pc', detail jsonb NOT NULL);
CREATE INDEX IF NOT EXISTS chat_gespraech_idx ON chat (gespraech_id, id);
GRANT INSERT, SELECT ON TABLE chat TO ledger_app;
```
Eine Zeile je Nachricht, `detail` (Felder nach Entscheid 9):
```json
{"schema": 1, "gespraech_id": "c-20260827-1500-a1b2", "rolle": "nutzer", "anbieter": "claude",
 "modell": "claude-sonnet-5", "schutz": "cloud-ok",
 "kontext": {"sitzung_logisch": 512, "signatur": null, "runde": null, "analyse_id": null},
 "text": "…", "token_in": 0, "token_out": 0, "dauer_ms": 0}
```
`rolle` ∈ {nutzer, assistent, codex, system}; `schutz` ∈ {cloud-ok, lokal}; `anbieter` ∈ {claude, ollama,
openrouter, requesty} (Phase 2, Nachtrag OpenRouter/Requesty); `anbieter ∈ {claude, openrouter, requesty}`
nur bei `schutz = cloud-ok` (Modell-Validator, alle drei sind Cloud-Anbieter — C6). `text` ≤ 20 000 Zeichen, vor dem INSERT durch
**`redaktion.bereinige_chat_text()`** (Nachtrag 2026-08-27 Punkt 8, ersetzt `bereinige_text()` nur hier):
Secrets/`_lokal`/E-Mail redigieren weiter den GANZEN Text, ein Pfad-Token (Laufwerksbuchstabe/`~`/`.`-Anfang
oder ≥ 2 Trennzeichen) ersetzt NUR sich selbst durch `<pfad>` — „und/oder", „24/7", Brüche bleiben stehen.
Andere Freitext-Aufrufer (`pruefung.py`/`fehlerbild_pruefung.py` Stufe-1/2-Urteile, Beleg-Redaktion) bleiben
bei `bereinige_text()` (Ganztext-Regel unverändert). `gespraech_id` = eine Hintergrund-Sitzung; Anbieterwechsel = neue `gespraech_id`.
`speicher.chat_schreiben(detail)` validiert gegen `contracts.ChatNachricht`.

**Bestand:** `quelle='gf', typ='befund_entscheid'` (befunde.py) unverändert. `quelle='vieraugen', typ='review'`
wird von `pruefung/lauf` abgelöst; Altläufe bleiben lesbar nach C1 Regel 2 (Legacy-Leseregel) und erscheinen
im Frontend als Prüfung mit `modell_stufe1 = "vieraugen-alt"`.

**`Kopf.backend`** (neu, optional, `modell.py`, Nachtrag Requesty 2026-08-28): `"anthropic"|"ollama"|
"openrouter"|"requesty"|"unbekannt"|""` — Hostklasse aus `ANTHROPIC_BASE_URL`, gesetzt vom Stop-Hook
(`__main__._ingest_hook` → `_backend_aus_env()`, der Hook läuft im Prozess von `claude` und erbt dessen
Umgebung). Nie die URL selbst oder ein Token, nur die Klasse. Grund: Requesty-Modell-IDs sehen aus wie
OpenRouter-IDs (`anthropic/claude-sonnet-5`), der Modellname allein reicht darum nicht zur Unterscheidung.
`quellen.quelle_fuer(rohquelle, modelle, registry, backend)` prüft `backend` (wenn gesetzt und bekannt)
VOR der bisherigen Modell-Kette; bestehende Belege ohne `backend` durchlaufen unverändert die alte Kette
(Feld optional, kein Schema-Bruch). Neu CLI `python -m sitzungsbeleg anbieter-test <anbieter>`: ein
kurzer `claude -p "Antworte nur: ok"`-Lauf über `chat_bruecke.teste_anbieter()`, Modell aus `--modell`
oder `modelle.json default_vico_<anbieter>` — zeigt Exit-Code/STDOUT/STDERR, damit eine offene Header-/
Auth-Frage bei einem neuen Anbieter live geklärt werden kann.

---

## C5 · API-Contracts

Fehler: JSON `{"detail": "<Text>"}` mit 400 (ungültiger Body, Pydantic-Fehler), 404 (unbekannte ID), 409 (Lauf
läuft schon), 423 (gesperrt für diese Sitzung). Request-/Response-Modelle aus `contracts.py`, OpenAPI unter `/docs`.

**`GET /api/sitzung/{sitzung_logisch}`** (bestehend, erweitert) — Antwort um diese Schlüssel ergänzt:
```json
{"sitzung_logisch": 512, "version": 1284, "versionen": [1284, 1201, 1188],
 "dokument": {"...": "unverändert", "auffaelligkeiten": [{"...": "unverändert",
      "status": "dissens", "pruefung": {"lauf_id": "p-…", "claude": "ja", "codex": "nein",
      "zweitmeinung": "eingeholt", "eskaliert": false, "kategorie": "…", "empfehlung": "…", "zeit": "…"}}]},
 "gruppen_status": {"rework:tool": "dissens"},
 "pruefung_laeuft": [{"lauf_id": "p-…", "scope": "sitzung", "signaturen": ["…"], "seit": "…"}],
 "zulaessigkeit": "cloud-ok",
 "befund_entscheide": "unverändert", "vieraugen": null}
```
`pruefung` ist `null`, wenn kein Lauf vorliegt; `pruefung_laeuft` ist `[]`, wenn keiner läuft.
**`GET /api/sitzung/version/{version_id}`** → `{"sitzung_logisch": 512}` oder 404 (C1 Regel 5).

**`POST /api/pruefung`** — Body = `contracts.PruefungBody`:
```json
{"scope": "befund", "sitzung_logisch": 512, "signaturen": ["rework:tool:Bash"], "stufe": null, "lauf_ref": null}
```
Regeln (Validator): `befund` → `sitzung_logisch` + ≥ 1 Signatur; `sitzung` → `sitzung_logisch`, leere Liste = alle
offenen; `fehlerbild` → genau eine Signatur, `sitzung_logisch = null`. `stufe: 2` + `lauf_ref` gemeinsam =
Codex nachholen. Antwort 202 `{"lauf_id": "p-…", "scope": "…", "stufe_max": null}` (asynchron; `stufe_max` steht im Ereignis).

**Lauf-Schlüssel und Konflikt (Codex-Fund 7):** Ein Lauf **belegt** die Menge `{(sitzung_logisch, signatur)}`
seiner Signaturen (Scope `sitzung`: alle offenen zum Startzeitpunkt; Scope `fehlerbild`: die Signatur in allen
betroffenen Sitzungen). Ein neuer Lauf, dessen Menge sich mit einer laufenden **überschneidet**, bekommt 409
`{"detail": "…", "lauf_id": "<laufender>"}`. Disjunkte Läufe laufen parallel. Ergebnisse: das **jüngste**
`pruefung`-Ereignis je (sitzung_logisch, signatur) gewinnt (C2 Regel 3); ein Lauf schreibt genau ein Ereignis.
Registry in `pruefung.py` (`_laufend: dict[lauf_id, Lauf]`, ein Lock), Ablauf: Lauf > 30 min → als Fehler beendet.

**`GET /api/pruefung/{lauf_id}`** → `{"lauf_id", "laeuft": true|false, "seit", "fehler": null|"…",
"ergebnis": null|<pruefung/lauf-Detail>}`; unbekannt → 404.
**Alt (Legacy-Form, bis Phase 2 E abgenommen):** `POST /api/sitzung/{id}/pruefen` → 200
`{"gestartet": bool, "laeuft": bool}` und `GET …/pruefen` → `{"laeuft", "seit", "fehler"}` **bleiben wie heute**
(kein `lauf_id`, 200 statt 202/409). Intern rufen sie `scope='sitzung'`. Das neue Frontend nutzt sie nicht.

**`GET /api/delegation/{sitzung_logisch}`** (Phase 1 C) — Antwort = `contracts.Delegation`:
```json
{"aufruf_quote": 0.31, "fanout_max": 4, "kosten_quote": 0.53, "output_quote": 0.31, "zeit_quote": 0.65,
 "tool_quote": 0.87, "tool_fehlerquote": 0.035, "mit_beleg": 22, "starts": 22, "tiefe_max": 1,
 "modelle": [{"modell": "claude-sonnet-5", "agenten": 22}],
 "benchmark": {"n": 60, "aufruf_quote": 0.2, "kosten_quote": 0.4, "output_quote": 0.25, "zeit_quote": 0.5, "tool_quote": 0.7}}
```
Quoten als Bruch 0–1 (Frontend formatiert Prozent); `zeit_quote` ≥ 0 ohne Obergrenze (> 1 = parallel).
**Delegations-Benchmark (eigener Contract, Codex-Fund 11):** Median derselben fünf Quoten über Sitzungen der
letzten 30 Tage mit gleichem Projekt + Quelle, ≥ 1 Subagent-Start, ohne die angezeigte Sitzung; `n` = Anzahl
dieser Sitzungen; `n = 0` ⇔ alle Quoten `null` (Validator). Nicht der Kacheln-Benchmark (andere Felder).

**`GET /api/rohdatei/{sitzung_logisch}?position=<ereignis_index>&umfang=<n>`** (Phase 3 H, **gebaut**) —
nur `127.0.0.1` (Server-Bind, kein zusaetzlicher Route-Check, wie jeder andere Endpunkt hier):
```json
{"pfad_anzeige": "~/.claude/projects/beispiel/sitzung.jsonl", "position": 41, "umfang": 5,
 "zeilen": [{"index": 39, "typ": "tool_use", "text": "<redigiert>"}],
 "redaktion_version": "2026-08-28", "warnung": "Flüchtig, redigiert, nie gespeichert."}
```
Nie in DB, nie in Logs (Test: Log-Handler-Capture bleibt leer). `zulaessigkeit` kommt server-seitig aus
`_sitzung()` (nicht vom Client, anders als `ChatBody.schutz`) — `geschuetzt` → 423. Unbekannte Sitzung →
404; Sitzung bekannt, Transkriptdatei fehlt → 404 "Transkript nicht mehr vorhanden". `umfang` Default 5,
gekappt auf `[1, 50]`. **Abweichung/Praezisierung ggü. Entwurf** (`rohdatei.py` Moduldoc): `position` ist
der `ereignis_index` aus `dokument.ereignisse` (Anzeige-/Echo-Wert) — die Fenster-**Zentrierung** in der
Rohdatei laeuft NICHT ueber diesen Index (Ereignisse sind eine vom Leser gefilterte/verdichtete Projektion
der Rohzeilen, kein 1:1-Mapping), sondern ueber `ereignisse[position].zeit`: die Rohzeile mit dem naechsten
`timestamp` wird gesucht (beide Leser uebernehmen `timestamp` wortgleich in `Ereignis.zeit`). Ohne gueltige
Zeit (Position ausserhalb der Ereignisliste) faellt die Suche auf `position` als rohen Zeilenindex zurueck.
Datei-Fund wie `ingest-dir`: `__main__._finde_sitzung(quelle, sitzung_id)` (Claude:
`projects/*/<id>.jsonl`, Codex: `sessions/**/rollout-*<id>*.jsonl`); Subagent-Transkripte
(`subagents/agent-<id>.jsonl`) sind **nicht** Teil dieser Rohdatei-Ansicht (offener Punkt, siehe Bericht).

**Chat (Phase 1 D Stub, Phase 2 F echt, Nachtrag Phase 2 OpenRouter):**
- `GET /api/chat/modelle` → `{"claude": [{"id": "claude-sonnet-5", "name": "Sonnet 5"}, …],
  "ollama": [{"id": "glm-5.2:cloud", "name": "…", "zustand": "geladen|verfuegbar|cloud"}],
  "openrouter": [{"id": "deepseek/deepseek-chat-v3-0324", "kontext": 164000}, …],
  "openrouter_hinweis": "…"}` — Claude aus `scripts/modelle.json` (`herkunft: anthropic`), Ollama
  aus `ollama ps`/`ollama list` + Registry `typ: cloud`, OpenRouter aus `GET
  https://openrouter.ai/api/v1/models` **oder** `.../v1/models/user` (`id`+`context_length`→
  `kontext`, eindeutig nach `id` sortiert, 10 Minuten im Prozess gecacht). `kontext` ist `null`,
  wenn die API keine Kontextlaenge liefert.
  **Coordinator-Nachtrag (Konto-Datenschutzeinstellungen, z. B. ZDR-Filter):** die oeffentliche
  `GET /v1/models` ist ungefiltert — ein Modell darin kann zur Laufzeit trotzdem scheitern, wenn
  das Konto es per Datenschutz-/Provider-Einstellung ausschliesst (verifiziert 2026-08-27: ZDR-
  Filter an → `GET /v1/models/user` liefert 255 Modelle/2 `:free`, gegenueber 417 Modellen/18
  `:free` unter dem oeffentlichen `/models`). `chat._openrouter_anfrage()` waehlt darum: **Schluessel
  vorhanden** (`chat_bruecke._openrouter_schluessel()`, gleiche Reihenfolge Env/Datei wie beim
  Chat selbst) → authentifiziert `GET /v1/models/user` mit `Authorization: Bearer <Schluessel>` —
  zeigt nur, was das Konto tatsaechlich aufrufen kann; **kein Schluessel** → oeffentlich `GET
  /v1/models` ohne Header. Der Schluessel geht ausschliesslich in den Header-Wert, nie in Log,
  Rueckgabe oder Fehlermeldung.
  **Coordinator-Nachtrag 2026-08-27 Punkt 2** (OpenRouter listet mehrere
  Hundert Modelle): `openrouter`-Objekte tragen `{id, kontext}` statt `{id, name}`, damit das
  Frontend eigene Optgroups baut (`static/js/chat.js`: zuerst alle `id`s mit Endung `:free`, dann
  alle Modelle, je alphabetisch; Options-Label `<id> · <kontext kurz>`, z. B. `"…:free · 1M"` /
  `"deepseek/deepseek-chat-v3-0324 · 164k"`, Options-*Wert* bleibt die nackte `id`).
  **Standardauswahl (Coordinator-Nachtrag: EINE Auswahlmechanik fuer alle drei Anbieter, nicht
  nur OpenRouter):** `chat.js` `standardModell(anbieterId, liste)` (reine Funktion, Fixture-
  Tests `tests/test_chat_standardmodell.mjs`) — erster Treffer aus `STANDARD_BEVORZUGT[anbieterId]`,
  sonst (nur OpenRouter kann das treffen) das erste `:free`-Modell, sonst das erste Modell
  ueberhaupt. `STANDARD_BEVORZUGT` (Stand 2026-08-27): `claude: ["claude-fable-5"]`,
  `ollama: ["glm-5.2:cloud", "minimax-m3:cloud"]`, `openrouter: ["nvidia/nemotron-3-ultra-550b-
  a55b", "z-ai/glm-5.2:free", "minimax/minimax-m3"]` (OpenRouter-Reihenfolge **nicht** alle
  `:free` — gegen die echte `/models/user`-Antwort unter aktivem ZDR-Filter verifiziert: die
  `:free`-Variante von `nemotron-3-ultra` liefert dort 404 „No endpoints available matching your
  guardrail restrictions and data policy", die Bezahlvariante laeuft ueber BaseTen zu ~0,000026
  USD je Mini-Aufruf, gleiche Abwaegung fuer `minimax-m3`; `z-ai/glm-5.2:free` bleibt erreichbar).
  Angewandt bei jedem initialen Laden **und** jedem Anbieterwechsel — **ausser** der Nutzer hat in
  dieser Seiten-Sitzung fuer den jeweiligen Anbieter schon selbst ein Modell gewaehlt
  (`eigeneModellwahl`, reiner In-Memory-Merker je Anbieter, kein `change`-Trigger bei
  programmatischer `.value`-Zuweisung). `openrouter_hinweis` nur bei Fehler/Offline (leere
  `openrouter`-Liste, Grund im Text) — Frontend bleibt ohne diesen Anbieter bedienbar.
- `POST /api/chat` Body `{"gespraech_id": null|"c-…", "anbieter": "claude|ollama|openrouter", "modell": "…",
  "text": "…", "kontext": {"sitzung_logisch": 512, "signatur": null, "runde": null, "analyse_id": null}}` → 202
  `{"gespraech_id": "c-…"}`. `gespraech_id: null` = neue Hintergrund-Sitzung. `anbieter ∈ {claude,
  openrouter}` (beide Cloud) bei `zulaessigkeit = geschuetzt` → 423. Fehlt bei `anbieter = openrouter`
  der Schluessel (`OPENROUTER_API_KEY` oder `scripts\.env.openrouter`), meldet der Strom ein
  `fehler`-SSE-Ereignis („OpenRouter-Schluessel fehlt: …"), kein 423/500 — die Sitzung startet, der
  erste Turn scheitert klar (Muster: fehlendes `claude.exe`).
- `GET /api/chat/{gespraech_id}/strom` — **SSE**, Events = `contracts.SseEvent`:
  `{"typ": "delta", "text": "…"}` · `{"typ": "ende", "token_in": n, "token_out": n, "dauer_ms": n}` ·
  `{"typ": "fehler", "text": "…"}`. Der Stub (Phase 1 D) streamt einen festen Text in 3 Deltas.
- `GET /api/chat/{gespraech_id}` → `{"gespraech_id", "anbieter", "modell", "schutz", "nachrichten": [<C4 chat-Detail>]}`.
- **`POST /api/chat/{gespraech_id}/fix`** (neu, Welle-2-Nachtrag Punkt 7): "Fix umsetzen". Der
  Hintergrund-Kindprozess (`chat_bruecke.py`) liest nur (`--allowedTools "Read,Grep,Glob"`, **kein**
  permissiver Modus mehr — er kann keine Rueckfrage beantworten). Markiert eine
  Assistent-Antwort einen konkreten Fix (Absatz beginnt mit der Zeile `FIX-VORSCHLAG:`, System-Prompt-
  Vorgabe), zeigt `chat.js` den Knopf „Fix umsetzen". Er ruft **diesen** Endpunkt, der ein **sichtbares
  Fix-Fenster** startet (`powershell …/Fix-Launcher -To vico -Handover "<Stichwort>"`) — Umsetzen
  passiert dort, nie im Hintergrund-Prozess. `-Handover` traegt NUR ein neutrales Stichwort
  (`"Sitzung <logisch>, Befund <signatur>, Chat <gespraech_id>"`), nie Nachrichtentext. Leerer Body,
  Antwort 202 `{"gestartet": true}`; unbekanntes Gespraech → 404; jeder andere Fehler (Fremdprozess) →
  500 `{"detail": "…"}`.

---

## C6 · Zulässigkeit (Datenschutz-Chip)

**Neu (Phase 1 B):** `redaktion.zulaessigkeit(beleg) -> "cloud-ok" | "geschuetzt"` — `geschuetzt`, wenn ein Pfad im
Beleg `_lokal`, `_graph_lokal` oder `_graph_merged_lokal` enthält oder das Projekt-Alias `bereich: HR` trägt
(`projekt-aliase.json`). Wirkung: Rohdatei 423 · Chat mit Claude **oder OpenRouter** 423 (beide Cloud,
Nachtrag Phase 2) · Tiefenanalyse nur Ollama lokal (`schutz = lokal`) · Codex nie. Frontend zeigt den
Chip im Sitzungskopf; `GET /api/sitzung` liefert `zulaessigkeit`.

---

## C7 · Frontend-Slots und Skalierung

Raster (Entwurfsbreite **1880 px**): Seitenleiste 300 · Lücke 24 · Mitte 1040 · Lücke 24 · Chat 440 · Ränder 24+28.
Alle drei Spalten immer sichtbar (Entscheid 6). Regel `static/js/skalierung.js`:
```
faktor = min(1, innerWidth / 1880);  wenn innerWidth < 1280 → Handy-Regel (bestehend), sonst
document.documentElement.style.zoom = faktor   (Fallback transform: scale + width: 1880px)
```
Kein Spaltenklappen, kein horizontales Scrollen. Wächter `scripts/check-sitzungsbeleg-layout.ps1` (Playwright)
misst bei 1920 / 1600 / 1366 px: drei Spalten voll im Viewport, `scrollWidth == clientWidth`.
**Seiten ohne Seitenleiste reservieren die linke Spalte leer** (Nachtrag 2026-08-28, Auftrag
"Mitte ortsfest"): Fehlerbilder & Entscheide, Produkt, Einstellungen tragen dort `aside.leerspalte`
(300 px, `aria-hidden`, ohne Rahmen/Hintergrund) statt einer echten `.seitenleiste` — die Mitte
steht dadurch auf allen Seiten an derselben `left`/`width`-Position wie auf Start, der Wächter
prüft das mit (± 1 px).

Slots in `index.html`: `#seitenleiste` (bestehend) · `#mitte` (bestehend) · **`#chat`** (neu, D): Kopf mit
Anbieter-/Modellwahl + Chip, Verlauf `#chat-verlauf` (von unten befüllt, `flex-direction: column;
justify-content: flex-end`), Eingabe `#chat-eingabe`. Bubbles: `.bubble.nutzer` rechts, `.bubble.assistent`
links, Farben aus `DESIGN.md` (Primärgrün nur Senden-Knopf).

**Kontext-Chip trägt Kennzahlen (Fund 2026-08-27):** die Besprechungs-Spalte kannte bisher nur die
Sitzungs-ID — Claude/Ollama/OpenRouter antworteten auf Kennzahlenfragen sinngemäß „nennen Sie mir die
Werte". `chat.Kontext` (`contracts.py`, C4) trägt seither ein optionales Feld `kennzahlen_block: str | None`
(≤ 1500 Zeichen) — der **Server** baut ihn (`chat_kennzahlen.baue_block()`), NIE das Frontend: Nr., Projekt,
Quelle, Modell(e), Start, Dauer, Runden, Tools/Tool-Fehler, Token ein/aus/cache, Kosten, Latenz p50/p95,
Compactions, Subagenten (Anzahl + Kostenanteil), bis zu 12 Befunde (Regel-ID + Status + Kurztitel + Vier-
Augen-Urteil, falls geprüft), Vier-Augen-Altlauf-Summe, Erfassungsehrlichkeit-Stempel — **dieselbe** Quelle
wie die Detailseite (`web._sitzung()` liefert `antwort["kennzahlen_block"]` zusätzlich mit, keine zweite
Berechnung). Läuft durch `redaktion.bereinige_text()` (ein einziger Pfad-/Secret-/E-Mail-/`_lokal`-Treffer
redigiert den GANZEN Block). `POST /api/chat` hängt den Block bei vorhandenem `sitzung_logisch` serverseitig
an `kontext.kennzahlen_block` (`web._kontext_mit_kennzahlen`), fail-open bei jedem Fehler (Sitzung fehlt, DB
kurz nicht erreichbar — Chat bleibt dann wie vorher ohne Kennzahlen-Kontext bedienbar). `chat_bruecke.
_kontext_zeile()` hängt ihn in die erste Nachricht/den System-Kontext der Bruecke. Frontend (`chat.js`):
der Chip zeigt bei vorhandenem Block „Sitzung `<n>` · Kennzahlen im Kontext", Tooltip (`title`-Attribut)
trägt den vollen Block — Quelle ist `daten.kennzahlen_block` aus `GET /api/sitzung/{id}` (derselbe Aufruf,
den die Seite ohnehin für den Datenschutz-Chip macht).

**Sichtkontext (Nachtrag 2026-08-28, Auftrag "Dashboard-Ansicht ist fuer mich nicht sichtbar"):**
der Chat kannte weder die offene Ansicht noch ihren Inhalt -- `chat.js` schickt seither mit jeder
Nachricht zusätzlich `sicht` (`contracts.Sicht`):
```json
{"ansicht": "start", "zeitraum": {"von": "2026-08-22", "bis": "2026-08-28"},
 "filter": {"projekte": ["Demo"], "quellen": ["Claude"], "kontexte": ["arbeit"]},
 "sitzungen": [{"nr": 666, "zeit": "2026-08-28T09:00:00+02:00", "quelle": "Claude",
                "projekt": "Demo", "dauer": "12m", "runden": 5, "tools": 20, "fehler": 1,
                "usd": 0.42, "status": "auffaellig", "auffaelligkeiten": ["rework:tool"]}],
 "sitzung": null, "befund": null}
```
`ansicht` ∈ {start, sitzung, fehlerbilder, produkt}; `sitzungen` sind NUR die aktuell sichtbaren
Zeilen (max. 30, Contract `max_length`). Server validiert (400 bei Verstoss, `_sicht_geprueft`)
und lässt jedes String-Feld sicherheitshalber durch `redaktion.bereinige_text()`
(`chat.sicht_bereinigt`) -- die Werte sind bereits redigierte Anzeige-Information, das ist nur das
zweite Netz (Muster `kennzahlen_block`). `chat_bruecke._sicht_block()` baut daraus einen Block
`SICHT: Startseite, 22.08.-28.08., Filter …, N Sitzung(en) sichtbar: | Nr | Zeit | … |`, angehängt
in `_kontext_zeile()` an die erste Kindprozess-Nachricht (≤ 2500 Zeichen, sonst kürzt sie zuerst
die Auffälligkeiten-Spalte, dann Zeilen von hinten). Frontend-Chip: „Start · 12 Sitzungen im
Kontext" bzw. bei offener Sitzung „Sitzung 137 · Kennzahlen + 5 Befunde", Tooltip trägt den
zusammengebauten Sichttext.

**Nachschlage-Werkzeug (gleicher Nachtrag):** `python -m sitzungsbeleg nachschlagen <nr>
[--befund <signatur>]` -- nur lesend, ruft `web._sitzung()` wie die Detailseite auf und gibt
`chat_kennzahlen.baue_nachschlage_text()` aus (Kennzahlen-Block + volle Befundliste mit Status und
Vier-Augen-Urteil, redigiert, ≤ 3000 Zeichen); unbekannte Nr/DB-Fehler → `"Sitzung N nicht
gefunden"`, Exit immer 0. Der Hintergrund-Chat darf es per `--allowedTools` zusätzlich zu
Read/Grep/Glob ausführen (`chat_bruecke.CHAT_ALLOWED_TOOLS`, Präfix-Muster `Bash(python -m
sitzungsbeleg nachschlagen *)`) — Kindprozess-Arbeitsverzeichnis ist seither `scripts/` (vorher
Repo-Wurzel), sonst löst `python -m sitzungsbeleg` nicht auf (Paket ist nicht installiert).

Befund-Karte (E): Pille `.pille[data-status]` 96 px fest · Knopf „Prüfen" je Gruppe · Vier-Augen inline
(`Claude ✓ · Codex ✗`) · Kennzeichen „ohne Zweitmeinung" / „eskaliert" · „Rohdatei ▸" je Treffer mit Position.
Kopf-Menü „Zweitmeinung einholen" entfällt. Start-Kacheln: Fehlerbilder · Kostenspitzen (`cost:spike`) ·
Erfassungslücken · Dissens · **Prüfung offen**.

---

## C8 · Maschinelle Prüfung

`contracts.py` (Pydantic v2, `extra="forbid"`): `PruefungLauf`, `Tiefenanalyse`, `ChatNachricht`, `PruefungBody`,
`Delegation`, `SseEvent`; Konstanten `STATUS`, `STATUS_RANG`; Funktionen `validiere(name, obj)`,
`validiere_ereignis(quelle, detail)`, `gruppenstatus(liste)`. Erzeuger validieren vor dem Schreiben
(`speicher.ereignis_schreiben`, `speicher.chat_schreiben`); FastAPI-Endpunkte nutzen die Modelle als
`response_model`/Body; Tests bauen Fixtures aus `contracts.BEISPIELE`. Die Beispiele oben sind dieselben Objekte
(Test: Datei ↔ Modul deckungsgleich). Wertebereiche: `schema = 1`, Zeiten ISO, `dauer_ms ≥ 0`, Texte ≤ 2 000,
Quoten 0–1 (außer `zeit_quote`), gekoppelte Felder per Validator.

---

## C9 · Retention

**Problem:** `sitzung`/`sitzung_auffaelligkeit`/`ereignis`/`chat` sind append-only (Grants in 0003/0004/0005,
kein UPDATE/DELETE für `ledger_app`) — bisher gab es keinen Löschweg, Belege wuchsen unbegrenzt.

**Befehl** `python -m sitzungsbeleg retention-sql --aelter-als <TAGE> [--quelle claude|codex|ollama|openrouter|alle]
[--host pc] [--out <datei>] [--zaehlen] [--vorschau]` (Modul `retention.py`). Wie `reingest-sql`: erzeugt nur eine
SQL-Datei (Default `_work_sitzungsbeleg/<datum>-retention.sql`), führt **nie selbst** ein DELETE aus. `--zaehlen`/
`--vorschau` sind rein lesend (`retention.betroffene_sitzungen`, SELECT über `ledger_app`).

**Rollen:** die generierte Datei führt der Maintainer manuell als `ledger_admin` aus — `ledger_app` (Ingest UND
Dashboard laufen als dieselbe Rolle, `speicher.psql`/`web.LAUFER`) hat laut 0003_sitzung.sql/
0004_sitzung_logisch.sql/0005_chat.sql nur `INSERT, SELECT`; ein DELETE über diese Rolle scheitert strukturell
an `permission denied`. Ingest/Dashboard können also weiterhin nicht löschen, ganz ohne Zusatzcode.

**Schutz (Auftrag Punkt 3):** `--aelter-als < 7` → Fehler, Exit 2 (`retention.MINDEST_TAGE`). `--quelle` hat
**keinen stillen Default** — fehlt sie, verlangt der Befehl `alle` explizit statt es anzunehmen.

**Auswahl:** „Sitzungsbeginn" = `coalesce(sitzung.start, sitzung.zeitstempel)` je `sitzung_aktuell`-Zeile (gleiches
Muster wie die Querschnitt-SQL in `README.md` Abschn. 12). `--quelle` filtert auf die **abgeleitete
Anzeige-Quelle** (`quellen.quelle_fuer`, wie C5 `/api/sitzungen`) — das lässt sich nicht als SQL-Gleichheit auf
der rohen `quelle`-Spalte ausdrücken, darum liest `retention.betroffene_sitzungen` Rohquelle + Modelle und
filtert in Python, bevor die DELETE-IDs feststehen.

**Reihenfolge (Fremdschlüssel, Kind vor Eltern):**
```sql
DELETE FROM chat WHERE (detail->'kontext'->>'sitzung_logisch')::bigint IN (…);
DELETE FROM ereignis WHERE
  (quelle IN ('pruefung','tiefenanalyse','vieraugen') AND (detail->>'sitzung_logisch')::bigint IN (…))
  OR (quelle = 'gf' AND typ = 'befund_entscheid' AND (detail->>'sitzung_ref')::bigint IN (…));
DELETE FROM sitzung_auffaelligkeit WHERE logisch_ref IN (…);
DELETE FROM sitzung WHERE logisch_ref IN (…);
DELETE FROM sitzung_logisch WHERE id IN (…);
```
`sitzung_auffaelligkeit.sitzung_ref → sitzung.id` und `sitzung.logisch_ref → sitzung_logisch.id` sind echte
Fremdschlüssel (0003/0004) — diese Reihenfolge ist Pflicht. `chat`/`ereignis` haben nur jsonb-Referenzen (kein
DB-FK), stehen trotzdem zuerst. Globale Entscheide (`sitzung_ref IS NULL`, gilt für alle Sitzungen einer
Signatur) bleiben unangetastet — nur Entscheide mit `sitzung_ref` in der Löschmenge fallen mit.

**Datei-Form:** `\set ON_ERROR_STOP on` + `BEGIN;` + `RAISE NOTICE` mit Anzahl/Filter als vorangestellter
Zählhinweis + die fünf DELETEs + `COMMIT;`, alles oder nichts. Ausführung wie `reingest-sql` (gleiche
Zeile, `_admin_ausfuehr_befehl`): `docker exec -i sitzungsbeleg-postgres psql -U ledger_admin -d ereignis
-v ON_ERROR_STOP=1 -f - < <datei>`.

**Bekannte Lücke:** `ereignis`-Zeilen mit `scope = 'fehlerbild'` (sitzungsübergreifende Fehlerbild-Analysen,
C3) referenzieren mehrere Sitzungen über `sitzungen: [...]`, nicht über `sitzung_logisch` — sie werden von
`retention-sql` nicht erfasst. Ebenso bleiben Chat-Gespräche ohne `kontext.sitzung_logisch` (freistehender
Hintergrund-Chat) unberührt, da sie an keine „Sitzung" im Sinn dieses Contracts hängen.

---

## C10 · Tiefenanalyse (Phase 3 I)

**Auslöser:** Knopf „Tiefenanalyse" in der Befund-Karte neben „Rohdatei ▸" (`static/js/sitzung.js`,
`trefferPositionHtml`) — nur sichtbar, wenn `a.position` existiert (kein sitzungsweiter Befund).

**`POST /api/sitzung/{sitzung_logisch}/tiefenanalyse`** — Body `{"signatur": "…", "position": <ereignis_index>}`:
404 unbekannte Sitzung/Signatur, 409 `{"detail": "…"}` bei bereits laufender Analyse zu dieser
(Sitzung, Signatur) — Registry `tiefenanalyse.registriere_lauf`/`freigeben` (Ablauf 30 min, gleiches
Muster wie `pruefung.py` C5, aber ein eigener, kleinerer Schlüsselraum: nur `(sitzung_logisch,
signatur)`, kein `lauf_id`-Resource — Status wird über `signatur` abgefragt, nicht über einen Lauf).
202 `{"gestartet": true}`; die eigentliche Analyse läuft in einem Hintergrund-Thread wie
`_pruefen_hintergrund` und schreibt am Ende genau ein `ereignis quelle='tiefenanalyse' typ='befund'`
(Contract `Tiefenanalyse` oben, C4).

**`GET /api/sitzung/{sitzung_logisch}/tiefenanalyse?signatur=…`** → `{"laeuft": bool, "seit": "…"|null,
"ergebnis": <Tiefenanalyse-Detail>|null}` — `ergebnis` ist das **jüngste** `tiefenanalyse`-Ereignis zu
dieser (Sitzung, Signatur), unabhängig davon, ob gerade ein neuer Lauf läuft (Frontend füllt das Panel
sofort mit der letzten Analyse und zeigt zusätzlich „läuft …", wenn `laeuft = true`).

**Stufe 1 (Claude, immer):** Eingabe = redigierter Kompaktbeleg (Kopf/Erfassung/Kennzahlen/
Auffälligkeiten, wie `vieraugen.dokument_kompakt`, hier direkt aus dem Antwort-Dict der Detailseite
gebaut, kein zweiter `Beleg`-Umweg) + Regeltext (`regeltexte.text_fuer`) + **lokaler Rohausschnitt**
±10 Ereignisse um `position` (`rohdatei.baue_antwort`, bereits redigiert) + **Commit-Liste** im
Sitzungszeitfenster (C10 unten, nur `hash`+`betreff`, nie der Diff). Ausgabe strikt JSON:
`{"ursache_kategorie", "befund", "empfehlung", "urteil": "ja|nein|unklar", "komplexitaet":
"einfach|komplex"}`. Modell `claude-sonnet-5`, bei `auffaelligkeit.schwere == "hoch"`
`claude-opus-5`. **Zulässigkeit (C6):** `zulaessigkeit(dokument) == "geschuetzt"` → Stufe 1 läuft
**nur** über Ollama lokal (`claude -p` mit `chat_bruecke._umgebung("ollama")`, Modell
`modelle.json` → `default_vico_ollama`), Codex läuft dann **nie** (Stufe 2 entfällt strukturell,
Ergebnis trägt `nur_lokal: true`, `urteil: "ohne_zweitmeinung"`).

**Werkzeugfehler-Rohtexte** (Paket K, Entscheid 2026-08-28 14:10): zusätzlich zum Rohausschnitt
sammelt `tiefenanalyse._fehlertexte()` bis zu 20 Fehlertexte der Ereignisse `art="tool_ergebnis",
fehler=true` **aus der ganzen Sitzung** (nicht nur um `position`), je Text direkt aus der Rohdatei
gelesen (`rohdatei.zeile_bei()`, gleiche Zeit-Zentrierung wie `baue_antwort`), redigiert **vor** dem
harten Kappen auf 300 Zeichen (`redaktion.bereinige_fehlertext()` — baut auf `bereinige_text()` auf,
zusätzlich Hostnamen/generische Schlüssel/ein Namens-Hinweis token-weise; Reihenfolge bewusst, ein
Trunkierungsschnitt könnte sonst ein Muster zerschneiden und der Erkennung entgehen). Landen **nur**
im Stufe-1-Prompt (nie Stufe 2, nie `ereignis.detail`/DB/Log — dieselbe Leitplanke wie der
Rohausschnitt). C6-Weiche **wie beim Rohdatei-Zugriff**, aber ein eigener, von `nur_lokal`
unabhängiger Check (`redaktion.zulaessigkeit(dokument)`): bei `geschuetzt` nur, wenn der Lauf
sowieso lokal läuft — sonst leere Liste + Vermerk `"Fehlertexte nicht verfuegbar (geschuetzt)."` im
Prompt statt einer Sperre der ganzen Analyse. Fehlende/verschobene Rohdatei ebenso fail-open (Vermerk
`"... (Rohdatei fehlt)."`, kein Abbruch).

**Stufe 2 (Codex):** nur wenn `zulaessigkeit == "cloud-ok"` **und** `pruefung.stufe_fuer(befund,
historie) == 2` (dieselbe Kleinfehler-Ausnahme/Eskalation wie C3, `historie` = die geladenen
`pruefung`-Ereignisse). Eingabe = redigierter Kompaktbeleg + redigierte Stufe-1-Analyse — **nie** der
Rohausschnitt, **nie** die Commit-Liste/ein Diff. Gleiche JSON-Form wie Stufe 1, ohne `komplexitaet`.

**Konsensregel** (`tiefenanalyse.konsens`, deterministisch, ≥ 8 Testfälle): `ursache_kategorie`
normalisiert (klein, Satzzeichen entfernt, Whitespace zusammengezogen) und verglichen — gleich, wenn
identisch, eine Kategorie Teilstring der anderen, oder Levenshtein-Abstand ≤ 3. Gleiche normalisierte
Kategorie **und** gleiches `urteil` → `uebereinstimmend`; `urteil == "unklar"` auf **einer** Seite →
immer `dissens` (auch bei gleicher Kategorie); sonst `dissens`. Ohne Stufe 2 → `ohne_zweitmeinung`.

**Ergebnisfenster** (`static/js/tiefenanalyse.js`, Panel unter der Befund-Karte wie Rohdatei, Optik
nach Mockup B1/B2, CSS-Klassen `ta2-*`/`pille-fix` aus `sitzungsbeleg-chat-mockup.html`): Kopf
„Tiefenanalyse · Runde N · `<signatur>`" (`N` = `position.runde` der Auffälligkeit, Echo aus
`Tiefenanalyse.runde`) + Status-Pille (übereinstimmend/Dissens/ohne Zweitmeinung/läuft/Fehler).
**Klartext-Karte zuerst** (Wunsch 2026-08-28): vier Zeilen „Was ist passiert · Ursache ·
Empfehlung · Status" aus den Top-Level-Feldern (immer Claudes Stufe-1-Sicht); bei `dissens` zusätzlich
„Entscheidung offen" + die beiden `positionen`-Blöcke darunter. Danach die zwei Spalten Claude|Codex
(`ta2-grid`/`ta2-spalte`, je Ursache-Kategorie/Befund/Empfehlung aus `positionen.claude`/`.codex`) und
bei Dissens der Entscheid-Block (Radio „Claude folgen/Codex folgen/eigene Einschätzung" + Vermerk +
„Entscheiden" → bestehender `POST /api/befund/entscheid`). Existiert bereits eine Analyse zur
Signatur, füllt der Knopf-Klick das Panel sofort aus `GET …/tiefenanalyse?signatur=`; der Knopf heißt
dann „Tiefenanalyse ▸ (vorhanden)" mit eigenem „Neu laufen lassen"-Knopf im Panel.

**Commits im Zeitfenster** (Modul `commits.py`, Wunsch): `GET /api/sitzung/{sitzung_logisch}/commits`
→ `{"commits": [{"hash", "zeit", "betreff"}]}`, `git log --since=<kopf.start> --until=<kopf.ende
+15min>` im Projektpfad der Sitzung (`rohdatei.cwd_aus_transkript` liest den rohen `cwd` aus der
ersten Transkriptzeile, die ihn trägt — Claude: `obj.cwd`, Codex: `payload.cwd` in `session_meta`;
dieser Pfad verlässt den Prozess nie, nur `git` bekommt ihn als `cwd=`). Kein Repo/kein Treffer →
leere Liste (kein Fehler), `zulaessigkeit == "geschuetzt"` → 423. `betreff` redigiert
(`redaktion.bereinige_text`), max. 30, neueste zuerst.
`GET /api/sitzung/{sitzung_logisch}/commits/{hash}` → `{"diff": "…"}`: `git show --stat -p <hash>`,
auf 400 Zeilen gekürzt, **jede Zeile** durch `redaktion.bereinige_text`; `hash` muss `^[0-9a-f]{7,40}$`
entsprechen (400 sonst — kein beliebiges Argument an `git`). **Nie gespeichert, nie an ein Modell** —
nur die Hash+Betreff-Liste aus dem ersten Endpunkt geht in Stufe 1, der Diff nirgendwo hinein.
Frontend zeigt den Diff als Vorher/Nachher (`-`-Zeilen `--fehler`/`--fehler-bg`, `+`-Zeilen
`--erfolg`/`--erfolg-bg` — bestehende Tokens, keine neuen Farben; `mono`, intern scrollbar).

**Guards (Tests):** Rohausschnitt-Text erscheint nie im Stufe-2-Prompt (`prompt_stufe2` bekommt ihn
gar nicht als Parameter — strukturell ausgeschlossen, zusätzlich per Text-Assertion geprüft); der
Commit-Diff erscheint in keinem Prompt und in keinem `ereignis.detail` (nur Hashes); `commits.py` ruft
`speicher.*` nie auf (AST-Guard wie `test_rohdatei.py`); `zulaessigkeit == "geschuetzt"` →
`frager_codex` wird nicht aufgerufen (Fake zählt die Aufrufe) und beide Commit-Routen liefern 423;
Fehlertexte-Marker landen im Stufe-1-Prompt, nie in Stufe 2 oder im gespeicherten Ereignis-Detail
(End-zu-Ende-Test wie der Rohausschnitt-Guard); `geschuetzt` ohne lokalen Weg und eine fehlende
Rohdatei liefern je einen eigenen Vermerk statt eines Fehlers. Contract-Validierung
(`contracts.validiere_ereignis`) läuft vor jedem INSERT; Konsensregel-Tabelle
(≥ 8 Fälle: gleiche Kategorie+Urteil, Tippfehler-Kategorie ≤ 3 Levenshtein, Teilstring-Kategorie,
unklar auf einer Seite, unterschiedliches Urteil, `ohne_zweitmeinung`); Panel-Rendering als
Node-Test aus Fixture-JSON (B1-Zustand `uebereinstimmend`, B2-Zustand `dissens`).

---

## C11 · Verankerung eines Entscheids (Maintainer 2026-08-28)

**Warum:** ein „Erledigt" im Beleg ist eine Buchung, keine Wirkung. Claude/Codex lesen in der naechsten
Sitzung nur Dateien (CLAUDE.md, AGENTS.md, Troubleshooting, Hooks, Skills), nie die Datenbank. Ein Entscheid
ohne Ort, an dem er wirkt, wiederholt den Fehler. Der bestehende `rueckfall`-Zustand (C2) erkennt das nur
im Nachhinein.

**Regel:** `status=erledigt` **verlangt** `verankerung`. `obsolet` und `offen` nicht (obsolet = Fehlerbild
existiert nicht mehr; offen = Wiedereroeffnung). Der Server lehnt `erledigt` ohne Verankerung mit 400 ab;
das Frontend zeigt die Felder nur bei `erledigt` und blockt den Knopf ohne Pfad.

**`befund_entscheid.detail`** (bestehend, C4) erhaelt optional:
```json
{"verankerung": {"art": "troubleshooting", "pfad": "TROUBLESHOOTING.md",
                 "abschnitt": "Sitzungsbeleg — 15x Bash-Fehler = Shell-Mismatch"}}
```

| Feld | Werte | Bedeutung |
|---|---|---|
| `art` | `troubleshooting` · `adr` · `runbook` · `playbook` · `hook` · `skill` · `regel` · `vorhaben` | Gattung des Ortes (`regel` = CLAUDE.md/AGENTS.md-Absatz, `vorhaben` = HANDOFF-Eintrag „Offen" fuer eine Produktaenderung, die erst noch gebaut wird) |
| `pfad` | repo-relativer Pfad, ASCII, kein `..`, kein absoluter Pfad, kein `_lokal` | Datei, die die naechste Sitzung liest; Waechter prueft Existenz |
| `abschnitt` | Freitext ≤ 200 Zeichen, redigiert | Ueberschrift/Stichwort innerhalb der Datei (kein Rohtext) |

**Modell:** `contracts.Verankerung`, `contracts.BefundEntscheid` (alle bestehenden Felder aus
`befunde.entscheid_bauen` + `verankerung: Verankerung | None`), Validator: `erledigt` ohne `verankerung` →
`ContractFehler`. `MODELL_JE_QUELLE["gf"] = BefundEntscheid` — damit validiert `ereignis_schreiben` auch
diese Quelle vor dem INSERT (C8).

**Frontend:** alle vier Entscheid-Formulare (`sitzung.js` Erledigt je Befund, `start.js` Fehlerbild-Kachel,
`fehlerbilder.js` Register, `tiefenanalyse.js` Entscheid-Block) zeigen bei `erledigt`: Auswahl `art`,
Eingabe `pfad` (Datalist mit den gaengigen Zielen: `TROUBLESHOOTING.md`, `HANDOFF.md`,
`docs/adr/`, `docs/runbooks/`, `docs/playbooks/`, `.claude/hooks/`,
`.claude/skills/`, `CLAUDE.md`), Eingabe `abschnitt`. Ein Formular-Modul (`static/js/verankerung.js`), von
allen vieren genutzt — nicht viermal kopieren. Anzeige eines erledigten Befunds: Pille + Verankerungs-Chip
`art · pfad` (Tooltip abschnitt).

**Waechter:** `scripts\check-verankerung.ps1` ruft `python -m sitzungsbeleg verankerung-pruefen [--von]`
(nur SELECT, wie `nachschlagen`): je erledigtem Entscheid seit `--von` (Default 90 Tage) prueft er, dass
`pfad` relativ zur Repo-Wurzel existiert und bei gesetztem `abschnitt` der Text (case-insensitiv, erste 40
Zeichen) in der Datei vorkommt. Ausgabe `OK`/`ROT` mit Liste; Exit 1 bei ROT. Eintrag in die
Post-Commit-Waechterkette und in `README.md` (Waechter-Tabelle).

**Tests (Pflicht):** Contract (erledigt ohne Verankerung → Fehler; obsolet ohne → ok; Legacy-Detail ohne
Feld → ok; `pfad` mit `..`/absolut/`_lokal` → Fehler); HTTP 400 mit sprechender Meldung; Waechter mit
tempdir-Repo (existierend/fehlend/abschnitt fehlt); Node-Test fuer das Formular-Modul (Felder nur bei
erledigt, Knopf gesperrt ohne pfad).

---

## C12 · Achse Umgebung (Maintainer 2026-08-28 12:45)

Vier Achsen je Sitzung: **Projekt** (woran), **Kontext** (wozu: Arbeit/Review/Test/…), **Anbieter** (wer
fuehrt aus), **Umgebung** (wo laeuft die Anwendung, die den Beleg schreibt). Kontext `test` (die Sitzung
testet) bleibt getrennt von Umgebung `abnahme` (die App laeuft auf der Abnahme-Instanz).

**`Kopf.umgebung`** (`modell.py`, optional, Default `"entwicklung"`): `entwicklung` · `abnahme` · `betrieb`.
Quelle: Stop-Hook liest `SITZUNGSBELEG_UMGEBUNG` aus seiner Umgebung (wie `_backend_aus_env`); unbekannter
Wert → `entwicklung` + Warnung im Hook-Log, nie Abbruch. Belege ohne Feld lesen als `entwicklung`
(Dual-Reader). Der spaetere App-Melder (eigenes Vorhaben) setzt das Feld direkt.

**Anzeige (Maintainer: keine neue Spalte, alles gestaucht genug):** Projekt-Zelle bekommt bei Abweichung ein
Kuerzel-Chip rechts vom Namen: `Abn.` (abnahme) · `Betrieb` (betrieb); `entwicklung` zeigt nichts.
Seitenleiste: Block „Umgebung" (Checkboxen wie Anbieter) erscheint **nur**, wenn im Zeitraum ≥ 2 Werte
vorkommen; `GET /api/sitzungen` liefert `umgebung` je Zeile, `GET /api/querschnitt` die Verteilung
`umgebungen: [{name, anzahl}]`. Filter `umgebung=` analog `quelle=`. Chat-Sichtpaket (`Sicht`) traegt
`umgebung` in der Filterliste mit.

**Tests:** Hook-Ableitung (gesetzt/leer/unbekannt), Dual-Reader (Beleg ohne Feld), API-Filter, Node-Test
Projekt-Zelle (kein Chip bei entwicklung, `Abn.` bei abnahme), Seitenleisten-Block erst ab zwei Werten.

---

## C13 · Wache — Warnung während der Sitzung (Paket J, Maintainer 2026-08-28)

**Warum:** der Beleg erkennt Fehlerbilder nach der Sitzung (Stop-Hook). Die Wache wendet dieselben Regeln
**während** der Sitzung an, damit ein Muster (15× Bash-Fehler, Überdelegation, Kostenspitze) den Agenten
erreicht, bevor die Sitzung vorbei ist — und damit ein bereits **entschiedenes** Fehlerbild (C11) mit seiner
Verankerung im Moment der Wiederholung sichtbar wird, statt erst als `rueckfall` im Dashboard.

**Hook:** `PreToolUse` (alle Tools, Matcher leer), Kommando `python -m sitzungsbeleg wache`, stdin-JSON wie
bei Claude Code üblich (`session_id`, `transcript_path`, `tool_name`, `tool_input`, `cwd`). Registrierung ist
Handgriff in `~/.claude/settings.json` (G7 — nie durch Claude Code), exakter Block in README.
Der Hook läuft bei **jedem** Werkzeugaufruf → harte Budgets: **≤ 300 ms** typisch, **fail-open** (jeder
Fehler → Exit 0 ohne Ausgabe, Fehler nur ins Hook-Log `_work_sitzungsbeleg/wache.log`, rotierend ≤ 1 MB),
**kein DB-Zugriff**, **kein Netz**, **kein Modellaufruf**.

**Ablauf je Aufruf:**
1. Zustand je Sitzung in `_work_sitzungsbeleg/wache-zustand/<session_id>.json`: letzte gelesene Dateigröße,
   letzter Auswertungszeitpunkt, bereits gemeldete `(signatur, wert)`-Paare, Zähler Werkzeugaufrufe.
2. Nur auswerten, wenn seit der letzten Auswertung ≥ 10 Werkzeugaufrufe **oder** ≥ 60 s vergangen sind
   **und** das Transkript gewachsen ist; sonst sofort Exit 0. (Das hält den Median unter 50 ms.)
3. Auswertung: `leser_claude.lese_sitzung(transcript_path)` (bestehender Leser, liest auch unvollständige
   Transkripte) → `regeln.pruefe(beleg, preise)` → Auffälligkeiten mit `schwere ∈ {warnung, hoch}` (Hinweise nie).
4. Je Auffälligkeit mit Stufe `warnen`/`fragen` (aus `wache.json`) und noch nicht gemeldet: Meldungszeile
   bauen: `Wache: <Regeltitel aus regeltexte> — <wert>. ` + falls Entscheide-Cache einen jüngsten
   `erledigt`-Entscheid mit `verankerung` für diese Signatur (global oder Projekt-Hash gleich) hat:
   `Entschieden am <datum>: siehe <art> <pfad> (<abschnitt>).` + falls Entscheid ohne Verankerung (Legacy):
   `Entschieden am <datum> ohne Verankerung — bitte nachziehen (C11).`
5. Ausgabe (stdout, JSON nach Claude-Code-Hook-Schema): `{"hookSpecificOutput": {"hookEventName":
   "PreToolUse", "additionalContext": "<Zeilen>"}}`; bei mindestens einer Regel mit Stufe `fragen`
   zusätzlich `"permissionDecision": "ask", "permissionDecisionReason": "<erste Zeile>"`. Ohne Treffer keine
   Ausgabe. Gemeldete Paare werden im Zustand vermerkt (keine Wiederholung derselben Meldung in der Sitzung;
   ein **neuer** `wert` derselben Signatur, z. B. 15 → 25 Fehler, meldet erneut).

**Konfiguration `scripts/sitzungsbeleg/wache.json`** (im Repo, versioniert):
```json
{"schema": 1, "standard": "warnen", "regeln": {"cost:spike": "warnen", "tool:error_rate": "warnen",
 "rework:tool": "fragen", "delegation:excess": "warnen", "latency:timeout": "aus"},
 "mindest_werkzeugaufrufe": 10, "mindest_sekunden": 60}
```
Stufen: `aus` (nie melden) · `warnen` (nur Kontext) · `fragen` (Kontext + Rückfrage an den Nutzer).
Unbekannte Regel-Schlüssel → Warnung ins Log, sonst ignoriert. Keine Rohtexte in der Konfiguration.

**Entscheide-Cache `_work_sitzungsbeleg/wache-entscheide.json`:** `{"stand": "<iso>", "entscheide":
[{"signatur", "sitzung_ref", "projekt_hash", "status", "entschieden_am", "verankerung": {...}|null}]}` —
nur erledigte/obsolete Entscheide der letzten 180 Tage, **kein** Vermerk/Begründung (können Freitext sein).
Schreiber: der Dashboard-Dienst (`web.py` Startup + alle 10 min, Modul `wache_cache.py`) und der CLI-Befehl
`python -m sitzungsbeleg wache-cache` (für Instanzen ohne Dienst, z. B. per Aufgabenplaner). Der Hook liest
den Cache nur; fehlt er, meldet die Wache Regeln ohne Entscheid-Bezug.

**Preise:** `regel_kostenspitze` braucht `preise` — aus `modelle.json` wie im Stop-Hook, gecacht im Prozess
(ein Aufruf = ein Prozess, daher: Datei einmal lesen, nicht mehr).

**Tests (Pflicht):** Drossel (kein Lauf unter 10 Aufrufen/60 s), Erstmeldung + keine Wiederholung +
Neu-Meldung bei neuem Wert, Verankerungszeile bei Cache-Treffer, Legacy-Zeile ohne Verankerung, Stufe
`fragen` → `permissionDecision: ask`, `aus` → nichts, fail-open bei kaputtem Transkript/kaputter Konfig
(Exit 0, leere Ausgabe, Logzeile), Laufzeit-Test (< 300 ms auf dem Fixture-Transkript der Tests, gemessen).

**Nachtrag (Entscheid 2026-08-28 14:30): `wache.json` vereinfacht** — nur `rework:tool` = `fragen`,
alle anderen Regeln laufen über `standard` = `warnen` (kein `aus` mehr im ausgelieferten Stand; die Stufe
bleibt als Mechanismus verfügbar, siehe Ablauf oben).

**Meldungsspur `_work_sitzungsbeleg/wache-meldungen.jsonl`:** jede AUSGEGEBENE Meldung (Stufe `warnen`
UND `fragen`, nicht nur `fragen`) hängt der Hook zusätzlich als eine JSON-Zeile an — Grundlage für die
Start-Kachel „Wache" und die Verlauf-Marke auf der Sitzungsseite:
```json
{"zeit": "<iso>", "session_id": "<uuid>", "projekt_hash": "<hash>", "signatur": "rework:tool:Bash",
 "stufe": "fragen", "wert": "4", "verankerung": null, "text": "Wache: ... — 4. ..."}
```
`text` ist exakt die Meldungszeile aus der Hook-Ausgabe (Regeltitel/Wert/Pfad, nie Rohtext). Kein
DB-Zugriff im Hook, das ≤ 300 ms/fail-open-Budget gilt unverändert (ein Anhängen an eine lokale Datei).
Kein Rotations-/Retention-Mechanismus für die Spool-Datei selbst (offen, analog `retention.py`).

**Lesezugriff (nur lesend, eigenes Modul `wache_web.py`, per `include_router` in `web.py`):**
`GET /api/wache/meldungen?von&bis` → `{"anzahl", "offen_fragen", "meldungen": [...]}` (Zeitraum-
Filter auf `zeit`, 30 s Prozess-Cache der Spool-Datei); `GET /api/sitzung/{sitzung_logisch}/wache` →
`{"meldungen": [...]}` — löst `sitzung_logisch` über `web._sitzung()` auf `kopf.sitzung_id` auf und
filtert die Spool-Zeilen darüber (dieselbe `session_id`, die der Hook vom PreToolUse-Ereignis bekommt).

**Frontend:** Start-Kachel „Wache" (`static/js/start.js` `baueKacheln`, Zahl = `anzahl` im Zeitraum,
Label nennt `offen_fragen`, wenn > 0) neben der Kachel „Prüfung offen"; Sitzungs-Verlauf
(`static/js/sitzung.js` `renderVerlauf`) zeigt jede Meldung als zusätzliche Marke am zeitlich
nächstliegenden Ereignis (`wacheMarkerJeIndex`, reine Funktion — kein `ereignis_index` in der
Meldungsspur, nur `zeit`).

## C14 · Achse Persona (Maintainer 2026-08-28, beschlossen ~17:30)

**Warum:** VICO ist Claude Code unter anderem Namen; VICA und CURA sind Claude Code mit eigenem
Konfigurationsverzeichnis und Ollama-Backend. Heute schreibt nur VICO Belege — in den
`settings.json` von `~/.vica` und `~/.cura` ist der Stop-Hook nicht registriert. Aktivierte
Personas arbeiten damit unsichtbar am Beleg vorbei; Orb-/Handy-Gespraeche starten im Hintergrund
echte Claude-Code-Sitzungen je Persona und waeren gleichfalls unsichtbar (VICO-Orb-Sitzungen
erscheinen bereits, weil sie das globale `~/.claude` nutzen).

**Erfassung (Stop-Hook `sitzungsbeleg-hook.py`):**
- `Kopf.persona ∈ {vico, vica, cura}` — abgeleitet aus `CLAUDE_CONFIG_DIR`: endet auf `.vica` →
  `vica`, `.cura` → `cura`, sonst (leer/global) → `vico`. Kein neuer Env-Schalter noetig.
- `Kopf.kanal ∈ {terminal, orb}` (optional, Default `terminal`) — die Orb-Bruecke
  (`Persona-Bruecke (internes Modul)`) setzt beim Spawnen `SITZUNGSBELEG_KANAL=orb`.
- Persona ≠ Quelle: VICO ueber Ollama bleibt Persona `vico` mit Quelle `Ollama`
  (Limit-Ausweich-Fall). Beide Achsen werden getrennt erfasst und gefiltert.

**Registrierung:** der Stop-Hook wird in `~/.vica/settings.json` und `~/.cura/settings.json`
eingetragen (Vorlage analog `_work_sitzungsbeleg/settings-vorlage-wache.json`; Nutzer ersetzt
selbst, G7 sperrt Settings-Schreiben fuer Claude). **CURA-Schutz:** Sitzungen mit Persona `cura`
werden als `geschuetzt` markiert (bestehende C6-Mechanik) — Tiefenanalyse/Besprechung fassen sie
nur ueber den lokalen Weg an; der Beleg selbst liegt im lokalen Postgres, kein Cloud-Export.

**Anzeige (Startseite, GEBAUT 2026-08-28 Abend):** Persona-Spalte in der Sitzungen-Tabelle
(**P1 = Mini-Orb + Name**, Entscheid; Netz-Drahtgitter-Orb `#orb-mesh` nach Kampagnen-Visual,
Zusatz „· Orb" nur bei `kanal=orb`) + Filtergruppe „Personas" in der Seitenleiste — **immer
sichtbar, zweispaltig wie die Anbieter-Leiste** (Entscheid 2026-08-28 Abend, ersetzt die
urspruengliche Ab-zwei-Werten-Klausel nach C12-Muster; vierte Zelle = unsichtbarer Puffer fuer
einen kuenftigen Agenten). Die AKTIV-Chip-Zeile der Projekte-Gruppe entfaellt (doppelte
Information zur Haekchenliste, Entscheid). Farbcode aus der Orb-UI: VICO `#004F7C` · VICA
`#7a4f9c` · CURA `#1f7a5c` (Orb-Glow `#2f8fd8`/`#b07fe0`/`#4fd09a`). Mockup-Referenz:
`_work/sitzungsbeleg-persona-start-mockup.html` (Fassung 3, abgenommen).

**Bestand:** Sitzungen ohne `persona` (alle vor C14) zeigen `vico` an (faktisch korrekt — nur
VICO schrieb Belege); gespeichert wird das Feld nur fuer neue Sitzungen, keine Rueckdatierung.

**Nachtrag C14 (Maintainer einverstanden, 2026-08-28 ~18:15) — Server-Spool + CURA-Zugriffsspur:**
1. **Server-Spool:** Der Server (EU-Cloud, Orb-Betrieb bei ausgeschaltetem PC) registriert denselben
   Stop-Hook; statt DB-Zugriff (PC-Postgres unerreichbar) schreibt er je Sitzung eine JSONL-Zeile in
   ein Spool-Verzeichnis. Der 05:30-Lauf bzw. der naechste Dashboard-Start auf dem PC holt den Spool
   per SSH ab (`Hole-Sitzungsspool.ps1`) und traegt ihn per `sitzungsbeleg ingest-spool <verzeichnis>`
   nach (append-only) — der Rueckweg heisst bewusst NICHT `ingest-dir`: `ingest-spool` liest je
   Sitzung `persona`/`kanal` aus der Spool-`meta.jsonl`-Zeile, nicht aus der Umgebung, weil ein
   Spool Sitzungen mehrerer Personas mischen kann. Kein Verlust, nur verzoegerte Sichtbarkeit.
2. **CURA auf dem Server — Klarstellung:** E6 gilt technisch weiter: auf dem Server laeuft KEIN
   CURA-Agent und kein CURA-Modell. Was der Maintainer erlebt, ist die bewusste Ablehnungsantwort in
   `voice/livekit/turn_flow.py` (`_UNAVAILABLE["cura"]`): CURA "meldet sich", verweist aber auf den
   Arbeitsplatz vor Ort und leistet keine Arbeit.
3. **CURA-Zugriffsspur (Sicherheitsaspekt, Wunsch):** Genau diese Ablehnungsstelle schreibt
   kuenftig eine Spool-Zeile `{typ: "cura_zugriffsversuch", zeit, client_kennung?}` — nie
   Gespraechsinhalt. Im Beleg zaehlbar: wer/wie oft von extern nach CURA fragt; Haeufung ohne
   erkennbaren Anlass = Indiz fuer unerlaubte Zugriffsversuche. Anzeigeform (eigene Kachel vs.
   Zeile in der Wache-Kachel) wird im C14-Bau entschieden.

## C15 · Modellkatalog (Paket L, Go 2026-08-28 ~20:00)

**Bauvorlage:** `_work/sitzungsbeleg-modellkatalog-mockup.html` (Runde 11, abgenommen).
Anzeige-Regeln aus den Runden 8-11: Stand-Spalte zeigt NUR das juengste Datum ueber alle
Anbieter (TT.MM.JJJJ); Preisspalten zeigen den guenstigsten Anbieterpreis, alle Anbieterpreise
im Tooltip; Anbieter-Chips fest 82px (2 nebeneinander, dritter bricht um); Herkunft = SVG-Flagge
zentriert, Ueberschrift linksbuendig; Kopfzeile sortierbar wie Sitzungstabelle (th-sort);
Persona-Karten oben (VICO Consulting / VICA Academy / CURA Administration + LOKAL mit
Haus-Piktogramm), Karteninhalte ueber die Kastenhoehe verteilt.

**Tabelle `modellkatalog` (Migration 0006, App-Rolle darf upserten):**
je Zeile ein (modell, anbieter)-Paar: `modell_id text`, `hersteller text`, `herkunft text`
(ISO-2, z. B. US/CN/EU/CA), `anbieter text` (claude|ollama|openrouter|requesty),
`kontext_k int`, `eingabe_usd numeric NULL`, `ausgabe_usd numeric NULL`, `aa_index int NULL`,
`coding_index int NULL`, `stand date`, `quelle text` (Abrufquelle), PK `(modell_id, anbieter)`.
Upsert je Abruflauf; kein Loeschen (verschwundene Modelle behalten ihren letzten Stand).

**CLI `katalog-update [--anbieter <name>] [--db <url>]`** (in `__main__.py`, Logik in
`katalog.py`): OpenRouter ueber die Modell-Liste der API (Schluessel wie Chat-Anbieter),
Requesty analog, Anthropic + Ollama aus `scripts/modelle.json` (gepflegte Werte, Referenzpreise).
Fail-open je Quelle: eine tote Quelle bricht den Lauf nicht ab (stderr-Warnung, Rest laeuft).
AA-/Coding-Index bleiben v1 NULL-faehig und werden nur aus modelle.json uebernommen, keine
Live-Abfrage (Attribution/Lizenz Artificial Analysis vor Aktivierung klaeren).

**API `GET /api/modellkatalog`:** `{"stand": {anbieter: "YYYY-MM-DD", ...}, "modelle": [
{"id", "hersteller", "herkunft", "kontext_k", "aa_index", "coding_index",
 "anbieter": [{"name", "eingabe_usd", "ausgabe_usd", "stand"}],
 "preis_min": {"eingabe_usd", "ausgabe_usd", "anbieter"}, "stand_juengster": "YYYY-MM-DD"}]}`.
Sortierung liefert der Client (th-sort), die API liefert stabil nach `id`.

**Persona-Wege:** `scripts/modelle.json` erhaelt einen Block `persona_wege` (je Persona die
Anbieterzeilen der Karten: quelle, modell, primaer ja/nein) — abgeschrieben vom Ist-Stand der
Bruecke (`Persona-Bruecke (internes Modul)`), die Bruecke selbst wird in dieser Welle NICHT umgebaut
(Folge-Schritt: Bruecke liest die Map). Die Einstellungen-Seite rendert die Karten aus diesem Block.

## C15 v2 · Modellkatalog-Vollausbau (Feedback-Runde 2026-08-28 nacht)

Sechs Punkte aus der Sichtabnahme; ersetzt die v1-Klausel "keine Live-Abfrage AA".

**1. Artificial-Analysis-Anbindung (Beschaffung, `katalog.py`):** Schluessel
`ARTIFICIALANALYSIS_API_KEY` aus `scripts/.env` (Zugriff live getestet, HTTP 200, 624 Modelle).
Endpoint `GET https://artificialanalysis.ai/api/v2/data/llms/models`, Header `x-api-key`.
Je AA-Modell genutzt: `evaluations.artificial_analysis_intelligence_index` -> `aa_index`
(gerundet int), `evaluations.artificial_analysis_coding_index` -> `coding_index`,
`evaluations.tau2` (0..1) -> `agentic_index` (= round(tau2*100); tau2-Bench = Agentic-Werkzeug-
Benchmark, im ?-Hilfetext benennen), `median_output_tokens_per_second` -> `tempo_tok_s`.
AA ist KEIN Anbieter (kein Bezugsweg), sondern Anreicherung: Match ueber `aa_schluessel(text)`
(katalog.py, bereits angelegt): Teil nach letztem `/`, lowercase, `[^a-z0-9]+`->`-`, gegen
slug UND name der AA-Liste. UPDATE je Bestandszeile (modell_id, anbieter) — App-Rolle darf
UPDATE. Fail-open wie andere Quellen. Attribution (AA-Lizenzpflicht): der Stand-Text der
Katalog-Ueberschrift nennt "Indizes Artificial Analysis TT.MM.JJJJ".

**2. Migration `infra/sitzungsbeleg-db/0007_aa_indizes.sql` (Maintainer spielt ein):**
`ALTER TABLE modellkatalog ADD COLUMN agentic_index integer NULL, ADD COLUMN tempo_tok_s numeric NULL;`
plus Spalte `aa_stand date NULL` (Datum des letzten AA-Laufs je Zeile).

**3. Konsolidierung (Sicht, `katalog_sicht.py`):** Aggregation je `kurzname(modell_id)`
(katalog.py: Teil nach dem letzten `/`, lowercase) statt voller ID — 1071 Zeilen -> 719 Modelle.
API-`id` = Kurzname in der Schreibweise des juengsten Eintrags; `hersteller`/`herkunft` =
haeufigster nicht-leerer Wert der Gruppe; `anbieter`-Liste vereinigt alle Bezugswege (dedupe je
Anbietername, guenstigster Preis je Anbieter); Indizes/Tempo = erster nicht-NULL-Wert.
Zusatzfelder je Modell: `agentic_index`, `tempo_tok_s`, `lokal: bool` (ein Ollama-Weg dessen
Roh-ID kein "cloud" enthaelt), `eu_ohne_training: bool` (Requesty unter den Anbietern —
EU-Router mit vertraglichem Trainingsausschluss).

**4. Aktualisieren-Knopf:** `POST /api/modellkatalog/aktualisieren` startet den katalog-update-
Lauf im Hintergrund (Muster wie der Pruefen-Lauf: ein Lauf zugleich, Status-Objekt im Prozess);
`GET /api/modellkatalog/aktualisieren` -> `{"status": "bereit"|"laeuft"|"fertig"|"fehler",
"detail": str|null}`. Frontend: outline-Knopf "Jetzt aktualisieren" rechts neben der Katalog-
Ueberschrift (Mockup), waehrend des Laufs deaktiviert + "Aktualisiert...", nach fertig Daten neu
laden.

**5. Persona-Wege v2 (`modelle.json` `persona_wege`):** Eintraege optional mit
`"ebene": "offen"|"geschuetzt"` (fehlend = offen). CURA erhaelt zweiten Eintrag
`{quelle: ollama, modell: qwen3.5:9b, primaer: true, ebene: geschuetzt}` (= staerkstes Modell
mit typ=lokal in modelle.json). CURA-Karte rendert Unterteil-Titel "Offen" / "Nur lokal" wie
das Mockup. LOKAL-Karte: ALLE `typ=lokal`-Eintraege aus modelle.json (5 Stueck inkl.
nomic-embed-text und EuroLLM), CURA-geschuetzt-primaeres Modell als erste Zeile mit Pin +
Zusatz "CURA geschützt primär"; Laptop/Server-Segmented aus dem Mockup entfaellt, solange es
keine Server-Modellliste in modelle.json gibt (dokumentierte Abweichung).

**6. Seitenleiste (Mockup-Ebenen):** Eyebrow "Einstellungen" + Navigationsliste der ECHTEN
Abschnitte der Seite (Modellkatalog aktiv mit eingebettetem Filter-Block, dann Projekte,
Preistabelle, Redaktion, Retention — Klick scrollt zum Abschnitt). Filter-Block: Suchfeld,
"Eignung (Artificial Analysis)" mit ALLEN fuenf Mockup-Eintraegen als Sortier-Presets
(Coding -> coding_index absteigend, Reasoning -> aa_index, Agentic -> agentic_index,
Preis-Leistung -> aa_index geteilt durch Misch-Preis (3*eingabe+ausgabe)/4 aus preis_min,
Geschwindigkeit -> tempo_tok_s; Zeilen ohne Wert immer ans Ende, "Alle" = id aufsteigend),
Anbieter-Checkboxen, Herkunft-Chips, zwei Checkboxen "nur lokal" und "nur EU-Region ohne
Training" (filtern auf die Flags aus Punkt 3), Zaehler "x von y Modellen".
Flaggen: SVG-Symbole zusaetzlich IL/JP/KR (Mockup-Liste), Fallback bleibt Kuerzel-Text.

## C15 Nachtrag · Ollama live als Basisquelle (Befund + Fix 2026-08-30)

**Bug:** `beschaffe("ollama", registry)` las bisher ausschliesslich `scripts/modelle.json`
(`von_modelle_json`) -- neue, nur im laufenden Ollama-Daemon installierte Modelle (z. B.
`glm-5.3:cloud`, `kimi-k3:cloud`) erschienen darum NIE im Katalog, auch nicht nach "Jetzt
aktualisieren" (`POST /api/modellkatalog/aktualisieren` ruft dieselbe Funktion auf).

**Fix (additiv, keine Spaltenaenderung):** `katalog.py` bekommt eine LIVE-Basisquelle fuer
`anbieter='ollama'`: `_ollama_api_holen()` (GET `http://localhost:11434/api/tags`, Timeout
`ZEITLIMIT_S`, Fail-open — Netzfehler werden auf stderr geloggt und liefern `{}` statt einer
Exception) und `parse_ollama_tags(daten)` (Muster `parse_requesty`, Feld `details.context_length`
-> `kontext_k`, Preis bleibt `None`). `_beschaffe_ollama(registry)` macht daraus die Kette:
Live-Bestand ist die WAHRHEIT (ein Modell, das nicht mehr installiert ist, verschwindet aus dem
Katalog trotz Eintrag in `modelle.json`); `_ollama_anreichern()` reichert die Live-Zeilen mit den
Referenzpreisen aus `preise.modelle` an (Match ueber den Namen OHNE `:tag`, da die Registry-
Preisschluessel taglos gepflegt werden, z. B. `glm-5.2` fuer Live `glm-5.2:cloud`). Ist Ollama
nicht erreichbar (leere Live-Liste), faellt `_beschaffe_ollama()` mit einer eigenen stderr-Warnung
auf die alte `von_modelle_json(registry, "ollama")`-Form zurueck -- kein Verhaltensbruch fuer den
Offline-Fall. `beschaffe("claude", …)` ist unveraendert (weiterhin ausschliesslich `registry`).

**Lokal/Cloud-Erkennung vereinheitlicht (SUPERSEDED, s. C15 Nachtrag 3 unten):**
`katalog.ist_ollama_cloud(modell_id)` (Name endet auf `:cloud` -> Cloud, sonst lokal) war die
EINE Quelle der Wahrheit; `katalog_sicht._ist_lokal` rief sie direkt auf der `modell_id` auf.
Abnahme 2026-08-30 hat zwei Luecken gefunden (Cloud-Suffix ohne `:` und Registry-Fallback
mit taglosen IDs) -- der Satz "kein neues KatalogZeile-Feld noetig" gilt NICHT MEHR, s. unten.

## C15 Nachtrag 2 · Automatische, relative Katalog-Sterne (Entscheid 2026-08-30)

**Ziel:** Sterne im Modellkatalog werden **relativ zum aktuellen Katalog-Bestand** berechnet
statt aus den absoluten, manuell gepflegten Sternen in `scripts/modelle.json` -- ein neues
SOTA-Modell stuft damit automatisch alle anderen herunter. Die alten absoluten Regeln in
`docs/modelle.md` Abschnitt "Bewertungslogik" gelten NUR NOCH fuer die manuellen
Test-Sterne (Graphify-Eignung) in `modelle.json`, nicht mehr fuer diesen Katalog.

**API-Zusatzfeld je Modell (additiv):** `"sterne": {"intelligenz", "coding", "kontext", "gesamt",
"manuell"}`.
- `intelligenz`/`coding` (int 1..5 oder `null`): Quintil-Rang von `aa_index`/`coding_index` UEBER
  ALLE Katalogmodelle mit einem Wert in diesem Feld (Mittelrang bei Gleichstand) -- oberste 20 %
  = 5, unterste 20 % = 1. Fehlt der zugrundeliegende Index -> `null` (unbewertet), NIE ein
  erfundener 1-Stern. Ein einzelnes Modell ohne Vergleich bekommt neutral 3.
- `kontext` (int 0..3 oder `null`): unveraendert `=128K` 1 | `129-256K` 2 | `>256K` 3 |
  `<128K` 0 | `kontext_k` unbekannt -> `null`.
- `gesamt` (int 1..5 oder `null`): `round((intelligenz + coding) / 2 + bonus)`, geklemmt auf
  1..5; `bonus = +0.5` wenn `kontext == 3`, `bonus = -0.5` wenn `kontext` bekannt und `< 1`,
  sonst `0` (kein Kontext bekannt = neutral). `null`, wenn `intelligenz` ODER `coding` fehlt.
- `manuell` (Objekt oder `null`): NUR ein Tooltip-Zusatz -- `{"coding", "reasoning", "gesamt",
  "kommentar"}` aus dem passenden Eintrag in `scripts/modelle.json` (Match ueber
  `katalog.aa_schluessel()`), falls dort mindestens eine der drei Bewertungen gepflegt ist.
  Fliesst NICHT in `intelligenz`/`coding`/`gesamt` oben ein.

**Berechnung:** `katalog_sicht.aggregiere(zeilen, registry=None)` haengt `sterne` in zwei
Schritten an -- `_modell_eintrag()` traegt `kontext` + `manuell` sofort ein (pro Zeile
berechenbar), `_mit_relativen_sternen()` traegt danach `intelligenz`/`coding`/`gesamt` ueber die
GESAMTE `modelle`-Liste nach (`quintil_sterne()`). `registry` ist optional und wird nur fuer
`manuell` gebraucht; `hole_katalog()` laedt `scripts/modelle.json` einmal und reicht sie an
`aggregiere()`, `persona_wege()` und `lokal_liste()` durch (vorher dreifach gelesen).

**Frontend (`static/js/katalog.js`):** `gesamtSterneText(sterne)` zeigt die Gesamt-Sterne neben
dem Modellnamen (`–` bei `gesamt: null`), `sterneTooltipText(sterne)` baut den Tooltip
"Intelligenz ⭐⭐⭐⭐ · Coding ⭐⭐⭐ · Kontext ⭐⭐" + bei vorhandenem `manuell` den Zusatz
"— eigener Test: Coding ⭐⭐⭐ | Reasoning ⭐⭐⭐ | Gesamt ⭐⭐⭐⭐⭐ (Kommentar)". Die bestehenden
AA-Index-/Coding-Zahlenspalten (Punkt 1) bleiben unveraendert zusaetzlich sichtbar.

## C15 Nachtrag 3 · Cloud-Erkennung, Lokal-Feld, Kanonisierung, Herkunft (Abnahme 2026-08-30)

Fuenf verifizierte Fehler aus der Abnahme, alle TDD rot->gruen gefixt.

**1. `katalog.ist_ollama_cloud(modell_id)` erkennt jetzt ZWEI Suffix-Formen:** `:cloud`
(unveraendert) UND `<basis>:<groesse>-cloud` ohne eigenes Doppelpunkt-Cloud-Tag (z. B.
`gpt-oss:20b-cloud`, `gemma4:31b-cloud`, `qwen3-vl:235b-cloud`, `mistral-large-3:675b-cloud`) --
die reine `:cloud`-Pruefung uebersah diese zweite, real vorkommende Form.

**2. Neues Feld `KatalogZeile.lokal: bool` (additiv, Migration
`infra/sitzungsbeleg-db/0008_katalog_istlokal.sql`, Spalte `lokal boolean NOT NULL DEFAULT false`).**
Wird BEI DER BESCHAFFUNG an der ROHEN `modell_id` gesetzt (`parse_ollama_tags`: `not
ist_ollama_cloud(name)`; `von_modelle_json` fuer `quelle='ollama'`: `_ollama_typ_lookup()` gegen
`registry['modelle'][*]['typ']`, da die `preise.modelle`-Schluessel dort taglos sind und
`ist_ollama_cloud` auf ihnen IMMER `lokal=True` liefern wuerde). `katalog_sicht._roh_lokal(z)`
bevorzugt diese Spalte, faellt ohne sie (DB vor 0008) auf `ist_ollama_cloud(z['modell_id'])`
zurueck -- NIE auf einer schon kanonisierten ID (Punkt 3) auswerten, die haette das Suffix
verloren. Grund fuer die Spalte statt Wiederverwendung von `ist_ollama_cloud` an der Sicht: die
Katalog-GRUPPIERUNG braucht ab Punkt 3 eine kanonisierte ID ohne Cloud-Suffix, an der sich Cloud
nicht mehr ablesen laesst.

**3. Katalog-Gruppierung: neue Funktion `katalog.kanonische_id(modell_id)`,** von
`katalog_sicht.aggregiere()` statt `aa_schluessel()` als Gruppierungsschluessel genutzt (nur
dort -- die AA-Anreicherung behaelt ihre eigene Fallback-Kette `aa_schluessel`/
`aa_token_schluessel`/`aa_kern_schluessel` unveraendert). Baut auf `aa_schluessel` auf und
ergaenzt: Cloud-Suffix (`:cloud`/`-cloud`, nach `aa_schluessel` ein letztes Token `cloud`) weg;
Ziffer-Buchstabe-Trennung NUR fuer bekannte Familien (`_ZIFFERN_TRENNUNG_FAMILIEN = ("gemma",
"gemini")`, `gemma4` -> `gemma-4`; `qwen3`/`qwen3-vl`/`glm-5.2`/`kimi-k2` bleiben IMMER
zusammen, sonst Falsch-Merges oder verlorene Bestandstreffer); `-it`/`-instruct` ignoriert
(`_KANONISCH_RAUSCH_TOKEN`, NICHT das groessere `_AA_RAUSCH_TOKEN`-Set -- `-preview` bleibt eine
echte Modellauspraegung). Zusaetzlich `katalog_sicht._ohne_ollama_basis_dubletten()`: eine
Ollama-Zeile OHNE Tag (`gpt-oss`) ist eine Dublette der Groessenvariante DESSELBEN Basisnamens
(`gpt-oss:20b-cloud`, geteilt am ersten `:`) -- reale DB-Altlast (9 taglose Zeilen, Stand
2026-08-30: `gemini-3-flash-preview`, `gemma4`, `glm-5.2`, `gpt-oss`, `kimi-k2.6`, `minimax-m3`,
`mistral-large-3`, `nemotron-3-super`, `qwen3-vl`) aus einer Vor-"Ollama-live"-Beschaffung, nie
geloescht (kein DELETE, C15); wird vor der Gruppierung verworfen statt eine eigene, faelschlich
`lokal:true` zeigende Geist-Zeile zu bilden. Reale, gegen den Live-Katalog (`GET
/api/modellkatalog`) geprueft Beispiele: `gpt-oss:20b-cloud` == `openai/gpt-oss-20b` ==
`fireworks/gpt-oss-20b`; `gemma4:31b-cloud` == `google/gemma-4-31b-it`; `glm-5.2:cloud` ==
`z-ai/glm-5.2` == AA-Slug `glm-5.2`; `qwen3.5:9b` == `qwen/qwen3.5-9b` (matchte schon vorher).
Vorsicht bleibt gewahrt: `gemma-3-27b-it` (Google) und `gemma4:31b-cloud` (Ollama) bleiben
GETRENNTE Gruppen (unterschiedliche Generation).

**4. Herkunft nachgetragen:** `HERSTELLER_HERKUNFT` bekommt `"eurollm": ("Unbabel", "EU")` und
`"nomic": ("Nomic AI", "US")` (Substring-Treffer, da beide Roh-IDs ohne Anbieter-Slug vor dem
ersten `/` ankommen: `hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q4_K_M`,
`nomic-embed-text:latest`) -- vor dem Fix die einzigen zwei NULL-Herkunft-Zeilen im Live-Katalog
(1044 distinkte `modell_id`, Stand 2026-08-30). `katalog._warne_wenn_herkunft_unbekannt()`
loggt `warnung: Herkunft unbekannt: <id>` auf stderr bei jeder Beschaffung (openrouter/
requesty/ollama live/`von_modelle_json`), damit ein neues unbekanntes Modell auffaellt statt
still zu versickern. Waechter-Test `HerkunftUndKanonischeIdWaechterTest`
(`tests/test_katalog_sicht.py`) prueft gegen einen eingefrorenen Schnappschuss ALLER distinkten
Live-`modell_id`-Werte (`tests/fixtures/modellkatalog_ids.json`): jede Zeile hat `hersteller`
UND `herkunft`, und die Aggregation ueber den gesamten Bestand erzeugt keine zwei Modellgruppen
mit derselben Anzeige-`id`. Rot bei einem neuen Modell = Recherchebedarf.

**5. Preis Ollama-Cloud:** keine Codeaenderung noetig -- nach Punkt 3 haengt die
Ollama-Cloud-Zeile automatisch an der Gruppe mit OpenRouter-/Requesty-Preis (`preis_min` zeigt
den guenstigsten Anbieter der GESAMTEN Gruppe). Die Ollama-Anbieterzeile selbst zeigt weiter
ihren Referenzpreis aus `modelle.json` (`_ollama_anreichern`) oder `null`, nie `0` fuer ein
Cloud-Modell (`0` bleibt ausschliesslich fuer echte `lokal`-Modelle korrekt).

## C15 Nachtrag 4 · Modell-Familie, Legacy-Sterne, Panel-Vereinheitlichung (Entscheid 2026-08-30)

**A. Modell-Familie + neueste Version (`katalog_sicht.py`):** `familie(id) -> str` = Hersteller-
Praefix + Basisname OHNE reine Versionsziffern-Tokens (Token-Split wie `aa_schluessel`, ein
Token ganz aus Ziffern faellt weg). Varianten-Suffixe (`flash`, `mini`, `nano`, `pro`, `thinking`,
`vl`, `coder`, `lite`, `haiku`/`sonnet`/`opus` als Namensteil) sind NIE reine Ziffern und bleiben
Teil der Familie: `glm-5.3-flash`/`glm-5.3` sind ZWEI Familien (`glm-flash`/`glm`),
`claude-opus-5`/`claude-opus-4-8` sind EINE (`claude-opus`). Groessen-Suffixe wie `20b`/`120b`
(Ziffer+Buchstabe gemischt) zaehlen NICHT als reine Ziffer und bleiben ebenfalls stehen --
`gpt-oss-20b`/`gpt-oss-120b` werden so zu ZWEI eigenen Familien statt einer Groessen-Legacy-Kette
(unterschiedliche Groessen sind kein Nachfolgerverhaeltnis). `version(id) -> tuple` = Tupel aus
den reinen Ziffern-Tokens (`glm-5.3` -> `(5, 3)`, `claude-opus-4-8` -> `(4, 8)`), Tupel-Vergleich
liefert direkt `(5, 3) > (5, 2)` und `(4, 8) < (5,)`. Tiebreak Erscheinungsdatum (OpenRouter
`created`/AA-Datum) entfaellt: die Beschaffung speichert kein Release-Datum je Modell (nur den
Abruflauf-`stand`, `katalog.parse_openrouter`) -- Tiebreak ist darum der Name (lowercase).
`neueste_je_familie(ids) -> set[id]` gruppiert nach `familie()` und waehlt je Gruppe die ID mit
dem hoechsten `version()`-Tupel.

**B. Sterne nur fuer die neueste Version je Familie (additiv):** neues Feld je Modell
`"nachfolger": "<id>"|null` -- `null` bei der neuesten Version der Familie, sonst deren ID.
`aggregiere()` traegt `nachfolger` VOR den Sternen ein (`_mit_nachfolger()`); `quintil_sterne()`
(Intelligenz/Coding, damit auch `gesamt`) laeuft danach NUR NOCH ueber die Modelle OHNE
`nachfolger` -- eine aeltere Version bekommt `sterne.intelligenz`/`coding`/`gesamt` = `null`
(unbewertet wie ein Modell ganz ohne AA-Werte), bleibt aber eine ganz normale Zeile in `modelle`
(kein Filtern/Ausblenden, Pin-/Standardmodell-Markierung unveraendert). `kontext`/`manuell`
bleiben unveraendert auf jeder Zeile berechnet (kontextunabhaengig von der Familie).

**C. Frontend Legacy-Chip (`static/js/katalog.js`):** die Sterne-Spalte zeigt bei `nachfolger`
statt Sternen `legacyChipHtml(nachfolgerId)` -- grauer Chip, Text bewusst Englisch "Legacy"
(Task-Vorgabe), Tooltip "Nachfolger: <id>", gleiche Zellenposition/-breite wie die Sterne
(`.mk-sterne.mk-legacy-chip`), kein zusaetzlicher Zeilentext.

**D. Panel-Vereinheitlichung (`static/js/format.js`):** EINE Render-Funktion fuer den
Modellnamen gilt ueberall (Katalogtabelle, Persona-Kacheln, LOKAL-Panel). `modellAnzeigeName(id)`
kappt `:cloud`/`-cloud`/`:latest` sowie (wie bisher `katalog.js:kurzeWegId`) Anbieter-Praefix vor
dem letzten `/`, `@region` und `:flex`/`:batch`/`:free`. Ausnahme hf.co-IDs (Ollama-Registry-
Konvention `hf.co/<org>/<modell>-GGUF:<quant>`): eigene Kurzform `<modell> · <quant> · <org>`
(`hfCoTeile()`) VOR der generischen Kappung, sonst ginge die Organisation verloren --
`katalog.anzeige_kurzform()` haelt dafuer bei hf.co-IDs den vollen Pfad in der API-`id` bereit
statt wie sonst nur den Teil nach dem letzten `/`. `modellNameHtml(id, klasse)` baut den
HTML-Baustein (Tooltip = volle Roh-ID, hf.co-Treffer zusaetzlich mit Kennzeichen "🤗 HF-Quelle,
lokal gespeichert"). `herkunftFlaggeHtml(code)` (aus `katalog.js` verschoben) liefert dasselbe
Flaggen-Markup fuer Tabelle (`herkunftZelleHtml`, groessere Darstellung per CSS
`.herkunft-zelle .flagge-svg`) und Panels (kleinere Default-Groesse). Persona-Kacheln/LOKAL-Panel
nutzen `modellNameHtml` fuer den Namen; Persona-Wege gleichen zusaetzlich per
`modellAnzeigeName()`-Schluessel gegen die geladene Katalogliste ab (`katalogNachName`), um
denselben Lokal/Cloud-Tooltip auf dem Quelle-Chip (nur bei `quelle: "ollama"`) und dieselbe
Herkunft-Flagge wie die Tabellenzeile zu zeigen -- kein Treffer (Modell nicht im Katalog-Bestand)
laesst Chip/Flagge unveraendert, kein Fehler. Sterne entfallen in beiden Panels vollstaendig
(Platzgrund, Task-Vorgabe) -- `lokalZeileHtml()` zeigt nur noch Kommentar + Primaer-Zusatz.
**Ueberholt durch C15 Nachtrag 5 Punkt 2 unten:** die Herkunft-Flagge zeigen die Panels seit
Abnahme 2026-08-30 NICHT mehr (nur die Tabelle behaelt sie).

## C15 Nachtrag 5 · Familie praezisiert, Panels entschlackt (Abnahme 2026-08-30)

**1. Modell-Familie neu gefasst (`katalog_sicht.py`).** Befund: `familie()` aus Nachtrag 4 war
zu fein -- Varianten-Suffixe wie `mini`/`nano`/`flash` erzeugten eigene Familien, obwohl es
dieselbe Produktlinie ist (`gpt-5.4-mini` trug Sterne, obwohl `gpt-5.6-*` existierte), und
DeepSeek-Versionsmarker (`v3.2-exp`, `r1`) wurden gar nicht als Legacy erkannt. Neue Regel: Familie
= Hersteller + Produktlinie. **Stufen-Woerter** (`_STUFE_WOERTER`: `mini`/`nano`/`micro`/`lite`/
`flash`/`pro`/`max`/`ultra`/`super`/`plus`/`turbo`/`small`/`medium`/`large`/`sol`/`terra`/`luna`/
`opus`/`sonnet`/`haiku`/`fable`/`mythos`/`exp`/`preview`/`beta`/`chat`/`instruct`/`it`/`thinking`/
`reasoning`/`non`/`fast`) sind KEIN Familienmerkmal und fallen weg -- `claude-opus-5`/
`claude-sonnet-5`/`claude-fable-5` sind darum EINE Familie (`claude`). Produkt-Varianten (`vl`,
`coder`, `oss`, `vision`, `audio`, `embed`, `guard`, `safeguard`, `terminus`, `multi`, `agent`, ...)
stehen NICHT in der Liste und bleiben Teil der Familie (`gpt-oss` bleibt eine eigene Familie neben
`gpt`). Baugroessen (`20b`/`120b`/`675b`/`4t`, `a95b`/`a3b` bei MoE-Modellen) und Datums-/
Build-Stempel (Bindestrich-Datum `2024-11-20`, alleinstehendes 4-stelliges Token wie `2603`/`0528`
-- Mistral versioniert Snapshots als YYMM) sind WEDER Version NOCH Familie, `_ohne_groessen_tags()`
entfernt beide Klassen VOR der Versions-/Familienbildung (ein Live-Katalog-Befund zeigte sonst
`mistral-small-2603` faelschlich vor `mistral-large-3`, `gpt-4o-2024-11-20` faelschlich in
derselben Familie wie `gpt-5.6-*`). **Version** = erstes Zahlen-Token, auch glatt mit Buchstaben
verklebt (`qwen3.8` -> `(3, 0.8)`, `deepseek-v3.2` -> `(3, 0.2)`, `deepseek-r1` -> `(1,)`,
`gemma4` -> `(4,)`) -- `_aufgeteilte_tokens()` trennt ein Buchstaben-Ziffern-Paar, der
Buchstaben-Teil faellt weg, wenn er ein reiner Versions-Marker ist (`v`/`r`), sonst bleibt er Teil
der Familie. Anbieter-Praefixe ohne eigenen Slash (`parasail-<modell>` aus
`parasail/parasail-<modell>`) fallen in `_tokens()` zusaetzlich weg. **`neueste_je_familie()`**
liefert seitdem ALLE IDs mit dem hoechsten `version()`-Tupel je Familie (nicht mehr nur eine per
Namens-Tiebreak) -- echter Gleichstand bleibt Gleichstand (`glm-5.3`/`glm-5.3-flash`,
`gpt-oss-20b`/`gpt-oss-120b`, alle `gpt-5.6-sol/terra/luna`-Auspraegungen), `_nachfolger_je_id()`
verweist aeltere Versionen deterministisch auf die alphabetisch erste neueste ID. Ergebnis am
echten Katalog (1044 Roh-IDs, Stand 2026-08-30): 154 Familien, nur ~12 % der aggregierten Modelle
tragen ueberhaupt Sterne (~1 je Familie×Version-Gleichstand).

**2. Panels entschlackt (`static/js/format.js` + `static/js/katalog.js`).** Befund: die
VICO/VICA/CURA-Kacheln und das LOKAL-Panel zeigten Landesflaggen, ein CSS-Pin-Symbol (`📌`) und
das 🤗-HF-Abzeichen -- zu viel visuelles Rauschen fuer eine reine Bezugswege-Liste. Neu:
`modellNameHtml(id, klasse, mitBadge)` bekommt einen dritten, optionalen Parameter -- `mitBadge
=== false` unterdrueckt das HF-Abzeichen, Default (kein dritter Parameter, Tabelle) unveraendert
mit Abzeichen. `personaWegZeileHtml()` ruft `herkunftFlaggeHtml()` nicht mehr auf (keine Flagge im
Panel) und uebergibt `mitBadge=false`; `lokalZeileHtml()` ebenso. Die CSS-Regeln
`.persona-weg .modell::before`/`.lokal-liste li.primaer .modellname::before` (Pin-Symbol) sind
entfernt -- die Hervorhebung des Standardmodells bleibt allein der Tint-Hintergrund
(`.persona-weg.primaer`/`.lokal-liste li.primaer`). Panels zeigen jetzt NUR NOCH: Anzeigename
(derselbe Einzeiler wie die Tabellen-Modellkarte, `modellAnzeigeName()` inkl. hf.co-Kurzform
`<Modell> · <Quant> · <Org>`), Quelle/Lokal-Cloud-Chip, gruener Erreichbarkeits-Punkt. Voller Pfad
bleibt ausschliesslich im Tooltip (Roh-ID, unveraendert).

## C15 Nachtrag 6 · Familie bestaetigt, Status-Feld, Sterne-Rubrik v2, Bild-Flag (Entscheid 2026-08-30)

**1. Familie = Produktlinie + Stufe (bestaetigt/praezisiert `familie()`, `katalog_sicht.py`).**
Stufen-Woerter (`_STUFE_WOERTER`) gehoeren WIEDER zur Familie -- `claude-haiku-4-5` ist eine
eigene Familie `claude-haiku`, `gpt-5.4-mini` eine eigene Familie `gpt-mini`, `mistral-large-3`
`mistral-large`. Nur reine Modifikatoren ohne Modell-Unterscheidungskraft bleiben draussen:
`exp`/`preview`/`beta`/`chat`/`instruct`/`it`/`thinking`/`reasoning`/`non`/`fast` sowie Datums-/
Snapshot-Suffixe (`_ohne_groessen_tags()`, unveraendert aus Nachtrag 5). Restkanten gefixt:
`gpt-4o`/`gpt-4o-mini` sind zwei eigene Familien (Stufenwort `mini` trennt sie), eine
Datumsvariante (`gpt-4o-2024-05-13`) kanonisiert auf dieselbe Familie wie ihre Basis (Datums-
Token faellt weg, `_ohne_groessen_tags`); `claude-haiku-4-5-20251001` matcht `kanonische_id()`
identisch zu `claude-haiku-4-5` (eine Katalogzeile, Anbieter zusammengefuehrt -- unveraendert aus
Nachtrag 3 Punkt 3, das Datums-Suffix faellt schon beim Aggregations-Schluessel weg);
`llama-3.3-70b-instruct` -> Familie `llama` (kein Stufenwort im Namen), `llama-4-maverick`/
`llama-4-scout` -> eigene Familien `llama-maverick`/`llama-scout` (Produktnamen, keine
Stufen-Woerter) -- `llama-3.3-70b` bleibt darum aktuell in der Familie `llama`, kein Legacy zu
`llama-4-*` (bewusst, Task-Vorgabe). Tests: `FamilieTest`/`NeuesteJeFamilieTest`
(`tests/test_katalog_sicht.py`, teils schon aus Nachtrag 4/5 uebernommen, unveraendert gueltig).
**Diese Fassung ist final (Entscheid 2026-08-30, Abschluss)** -- sie ersetzt die transitorische
Abnahme 2026-08-30 A, in der Stufen-Woerter noch aus der Familie fielen (`claude-opus`/
`claude-sonnet`/`claude-haiku`/`claude-fable` waren dort noch EINE Familie `claude`); jede
gegenteilige Aussage in aelteren Abschnitten dieses Dokuments ist ueberholt.

**2. Additiv `status: "bewertet"|"latest"|"legacy"` je Modell (`katalog_sicht._mit_sternen_und_status()`).**
Ersetzt die reine `nachfolger`-Pruefung als Anzeige-Weiche: `nachfolger != null` -> `legacy`
(keine Sterne, unveraendert); `nachfolger == null` UND `sterne.gesamt` berechenbar -> `bewertet`;
`nachfolger == null` OHNE berechenbaren Score (kein `aa_index`/`coding_index`) -> `latest`.
Frontend (`static/js/katalog.js`): `latestChipHtml()` -- dezenter Info-Chip "Latest", Hausfarbe
abgetoent (`--primaer`/`--primaer-tint`, style.css `.mk-latest-chip`), NIE Gruen (Primaerknopf-
Vorbehalt). `sterneOderStatusHtml(m)` waehlt Legacy-Chip/Latest-Chip/Sterne ueber `m.status`,
gleiche Zelle/Breite (`.mk-sterne`-Basisklasse) wie zuvor.

**3. Sterne-Rubrik v2 -- ERSETZT die Quintil-/Kontext-Formel aus Nachtrag 2/4 vollstaendig.**
Grund: eine relative Quintil-Verteilung wackelt mit jeder neuen/entfernten Katalogzeile und
kannte keine Bild-Faehigkeit; die neue Formel ist absolut (Boden 45) und bezieht `vision` mit
ein. `sterne.intelligenz`/`sterne.coding`/`sterne.kontext` **entfallen ersatzlos** (kein
Kontext-Bonus mehr, kein separates Intelligenz-/Coding-Sternepaar) -- einziger Nachtrag-2-Leser
war `static/js/katalog.js`, hier mit angepasst. Neu: `sterne.score` (float|null) und
`sterne.gesamt` (float 0,5..5,0 in 0,5-Schritten, oder null) -- `manuell` (Tooltip-Zusatz aus
`modelle.json`) bleibt unveraendert.
- **Score** (`katalog_sicht._score()`): Mittel aus `aa_index`/`coding_index`; fehlt einer, zaehlt
  nur der andere; fehlen beide -> `null` (kein Score -> `status="latest"` statt `"bewertet"`).
- **Sterne-Formel** (`katalog_sicht._sterne_aus_score()`, Boden `_BODEN_SCORE = 45`): `best` =
  hoechster Score unter allen AKTUELLEN Modellen (`nachfolger is null`), berechnet in
  `_bester_score()`. `Score >= 45`: `Sterne = 3 + 2*(Score-45)/(best-45)` (linear 3,0..5,0 bis
  `best`; `best <= 45` -- kein aktuelles Modell ueber dem Boden -- faengt die Null-Division ab und
  liefert 3,0). `Score < 45`: `Sterne = 0,5 + 2,5*Score/45` (linear 0,5..3,0). Kaufmaennisch auf
  0,5-Schritte gerundet (`_runde_halbstern()`, 0,5 immer aufrunden), auf `[0,5; 5,0]` geklemmt.
  Kein Agentic-Index, kein Kontext-Bonus/-Malus, keine erzwungene Hersteller-Stufung mehr.
  **Nur AKTUELLE Modelle** (`nachfolger is null`) bekommen ueberhaupt einen `gesamt`-Wert (wie
  Nachtrag 4 B) -- eine Legacy-Zeile bleibt `sterne.gesamt = null` unabhaengig davon, ob ihr
  Score rechnerisch berechenbar waere.
- **Vision-Deckel** (`katalog_sicht._mit_vision_deckel()`): `vision === false` deckelt die
  GERUNDETEN Sterne bei 4,0 (kein Bildlesen = nicht voll einsetzfaehig, z. B. Rechnungen lesen);
  `vision === true`/`null` (unbekannt) bleiben ohne Deckel.
- **Erwartungs-Tests** (`SterneAusScoreTest`/`GfSterneTabelleTest`, `tests/test_katalog_sicht.py`)
  gegen die Tabelle: 7 von 8 Beispielen treffen die woertliche Formel exakt (`claude-opus-5`
  63/78 Bild -> 5,0 · `gpt-5.6-sol` 61/77 -> 5,0 · `glm-5.3` 60/75 kein Bild -> 4,0 (gedeckelt) ·
  `gpt-5.6-terra` 57/77 -> 4,5 · `gpt-5.6-luna` 52/71 -> 4,5 · `minimax-m3` 45/59 kein Bild -> 3,5
  · `mistral-medium-3-5` 30/47 -> 2,5). **Abweichung dokumentiert:** `claude-haiku-4-5` (24/None)
  nennt die Tabelle 1,5 -- die woertliche Formel (`0,5 + 2,5*24/45 = 1,8333`, gerundet)
  ergibt rechnerisch **2,0**, eine halbe Stufe hoeher (`SterneAusScoreTest.
  test_gf_tabelle_claude_haiku_score_unter_boden`, bewusst als Dokumentation statt stillschweigend
  uebernommen -- Bitte an Maintainer um Gegenpruefung von Hand). Zusaetzlich: im vollen 8-Modell-Katalog
  ist `claude-haiku-4-5` seit der finalen Familienregel (Punkt 1: `haiku`/`opus` sind je EIGENE
  Familie `claude-haiku`/`claude-opus`, keine gemeinsame `claude`-Familie mehr) selbst
  `status="bewertet"` (gesamt 2,0), NICHT `legacy` gegenueber `claude-opus-5` -- die Tabelle
  demonstriert die Formel ohnehin je Modell isoliert
  (`GfSterneTabelleTest.test_claude_haiku_ist_jetzt_eigene_familie_und_aktuell`).

**4. Additiv `vision: bool|null` je Modell (Migration `infra/sitzungsbeleg-db/0009_katalog_vision.sql`,
Spalte `vision boolean`, kein Default -- NULL = unbekannt).** `katalog.KatalogZeile.vision`
(additiv, Default `null`). Beschaffung je Anbieter:
- **Ollama:** `GET /api/tags` (Basisquelle) liefert `capabilities` nicht -- `katalog.ollama_vision(modell_id)`
  fragt `POST /api/show` je distinktem Modellnamen ab (`capabilities`-Liste enthaelt `"vision"`),
  prozessweit gecacht (`_OLLAMA_VISION_CACHE`). Bewusst NICHT in `parse_ollama_tags` (bleibt ein
  reiner, netzwerkfreier Parser, Moduldoc) -- eigener Anreicherungsschritt
  `_ollama_vision_anreichern()` in `_beschaffe_ollama()`, NACH der Preis-Anreicherung, NUR auf dem
  Live-Zweig (Registry-Fallback bleibt ohne `vision`, fail-soft `null`). Fail-soft bei Netzfehler
  -> `null`.
- **OpenRouter:** `katalog._openrouter_vision()` liest `architecture.input_modalities` direkt aus
  der schon geholten `/v1/models`-Antwort (kein Zusatz-Request) -- enthaelt `"image"` -> `true`,
  sonst `false`; fehlt `architecture` -> `null`.
- **Requesty/Artificial Analysis/Claude (`modelle.json`):** liefern (noch) kein Bild-Flag ->
  bleibt `null` (Registry-Default).
- **Aggregation** (`katalog_sicht._gruppe_vision()`): ein Bezugsweg der Modellgruppe mit
  `vision=true` reicht (Modell KANN Bilder lesen); sind alle bekannten Wege `false`, bleibt
  `false`; kennt kein Weg den Wert, bleibt `null`.
- **`_zeilen_lesen()`** erkennt eine fehlende `vision`-Spalte (Migration noch nicht eingespielt)
  ueber denselben Mechanismus wie `lokal`/die AA-Spalten -- `_SPALTE_ZU_FLAG` mappt den in der
  Postgres-Fehlermeldung genannten Spaltennamen direkt auf das zugehoerige `sql_alle_zeilen()`-
  Flag (`mit_aa_spalten`/`mit_lokal_spalte`/`mit_vision_spalte`) und schaltet GENAU dieses ab,
  statt eine feste Versuchsreihenfolge durchzuprobieren (Praezisierung: das alte
  `_ZEILEN_VERSUCHE`-Tupelschema haette bei drei unabhaengigen optionalen Migrationen im
  ungünstigsten Fall 4 statt 2 Versuche gebraucht, wenn NUR die juengste Migration fehlt).
- **Frontend** (`static/js/katalog.js`): `sterneTooltipText(m)` zeigt "Score · AA · Coding · Bild
  ja/nein/unbekannt" (ersetzt die Intelligenz/Coding/Kontext-Aufschluesselung aus Nachtrag 2).
  `gesamtSterneText(sterne)` zeigt halbe Sterne als Zahl mit einer Nachkommastelle + Stern-Symbol
  (`"4,5 ★"`), `–` bei `gesamt: null`.

**5. Lokal-Panel: Erreichbarkeits-Punkt + reiner Modellname (`static/js/format.js` +
`static/js/katalog.js`).** `modellAnzeigeName(modellId, nurModellname)` bekommt einen zweiten,
optionalen Parameter -- `nurModellname === true` liefert bei hf.co-IDs NUR `<Modell>` (kein
Org/Quant-Anhang), Default (Tabelle, kein zweiter Parameter) unveraendert `<Modell> · <Quant> ·
<Org>` (Quant unterscheidet Modelle dort). `modellNameHtml(modellId, klasse, mitBadge,
nurModellname)` reicht den vierten Parameter durch; Tooltip bleibt in JEDEM Fall die volle
Roh-ID. `personaWegZeileHtml()`/`lokalZeileHtml()` rufen mit `nurModellname=true`.
`lokalZeileHtml()` traegt zusaetzlich denselben `.erreichbar-punkt` (gruen, Farbe = Erreichbarkeit)
vor dem Namen wie die Persona-Kacheln -- bisher nur dort vorhanden. Orange Kurzanmerkung
(`kommentar` aus `modelle.json`) bleibt sichtbar NUR als kurzes Fach-Tag (`istKurzesFachTag()`,
≤ 3 Woerter, z. B. "Embedding"); ein laengerer Kommentar erscheint stattdessen als `title`-Tooltip
auf der ganzen Zeile (kein zweiter Umbruch im sichtbaren Text).

## C15 Nachtrag 7 · Kuratierte Generations-Schwellen, Alias-Kanonisierung (Festlegung 2026-08-30)

**1. Kuratierte Generations-Tabelle (`scripts/sitzungsbeleg/generationen.json`) hat VORRANG vor
der automatischen `familie()`-Versionsregel aus Nachtrag 5/6.** Pflege liegt bei der Maintainer: bei
jeder neuen Generation einer Produktlinie wird die Schwelle im Feld `linien` angehoben. Vier
Felder: `linien` (Produktlinie -> Mindest-Generation als Dezimalzahl, `99` = ganze Linie
abgeloest), `ausnahmen_aktuell` (Modell-IDs, die die Schwelle ihrer Linie schlagen -- immer
aktuell), `explizit_legacy` (Modell-ID -> Nachfolger-ID, schlaegt alles), `aliasse` (reiner
Kommentar-String, dokumentiert Punkt 3 unten). Eine Produktlinie OHNE Eintrag in `linien` bleibt
unveraendert bei der automatischen `familie()`-Regel.

**2. Neue Funktion `produktlinie()` (`katalog_sicht.py`) = `familie()` OHNE Stufen-Woerter
(`_STUFE_WOERTER`).** Die kuratierte Schwelle gilt je Linie, nicht je Stufe -- `gpt-5.4-mini` und
`gpt-5.4-nano` teilen die Linie `gpt`, obwohl sie unterschiedliche `familie()`-Werte haben
(`gpt-mini`/`gpt-nano`). Ein verklebter Ziffer+Marker-Buchstabe-Rest wie `5v`
(`glm-5v-turbo`, Vision-Variante) wird auf den Marker-Buchstaben verkuerzt
(`_VERSIONS_MARKER_BUCHSTABEN`, Spiegelbild der bestehenden `v3`/`r1`-Praefix-Regel) -- Linie
`glm-v`, nicht die woertliche `glm-5v`; ein Rest ohne Marker-Buchstaben wie `4o` (GPT-4o) bleibt
unveraendert stehen, Linie `gpt-4o`. `familie()`/`version()` selbst bleiben unangetastet (
Entscheid 2026-08-30 final).

**3. Additive Alias-Kanonisierung in `katalog.kanonische_id()`.** Router-/Reasoning-Effort-
Anhaengsel nach Bindestrich- ODER Doppelpunkt-Trenner (`_ALIAS_SUFFIX_WOERTER`: `latest`, `high`,
`medium`, `low`, `priority`, `free`, `nitro`, `exacto`, `online`) sind Bezugsvarianten desselben
Modells, kein eigenes Modell -- `o1:high`/`gpt-5:priority`/`mistral-large-latest` kanonisieren auf
`o1`/`gpt-5`/`mistral-large` (eine Katalogzeile, Anbieter zusammengefuehrt). Eine Datumsversion
(`mistral-large-2512`) ist KEIN Alias und bleibt eigene Zeile. Nur fuer die Katalog-AGGREGATION,
unveraendert wie die vier bestehenden Normalisierungen in derselben Funktion.

**4. Status-Regel (`katalog_sicht.generation_status()`, reine Funktion + `_mit_kuratierten_
generationen()`).** Reihenfolge: (a) `explizit_legacy` schlaegt alles, Nachfolger direkt aus der
Tabelle; (b) `ausnahmen_aktuell` schlaegt die Schwelle, immer aktuell; (c) Produktlinie hat eine
Schwelle und die Version liegt darunter (Tupel-Vergleich wie `version()`, `_schwelle_ge()`) ->
legacy, Nachfolger = das bestbewertete AKTUELLE Modell derselben Linie (hoechster Score,
`_bester_score_je_linie()`), sonst `null` (keine bewertete aktuelle ID in der Linie); Version
am/ueber der Schwelle -> aktuell; (d) Produktlinie ohne Eintrag -> automatische Regel aus
`_mit_nachfolger()` (Nachtrag 5/6) bleibt unveraendert massgeblich. Ein kuratiert-legacy Modell
OHNE bewerteten Nachfolger behaelt `nachfolger=null` trotzdem als `status="legacy"` -- dafuer
traegt `_mit_kuratierten_generationen()` einen internen `_generation_legacy`-Marker in die
Modell-Dicts ein, den `_mit_sternen_und_status()` (`_ist_legacy_status()`) statt der reinen
`nachfolger is None`-Pruefung liest und vor der Rueckgabe wieder entfernt (kein Kontraktfeld).
`aggregiere()`/`hole_katalog()` bekommen dafuer den additiven, optionalen Parameter
`generationen` (Muster `registry`) -- fehlt er, laedt `hole_katalog()` `generationen.json` via
`_lies_generationen()` (fail-soft leeres Dict bei fehlender/kaputter Datei, dann rein automatische
Regel wie vor diesem Nachtrag). Tests: `GenerationStatusTest`/`KuratierteGenerationImKatalogTest`/
`ProduktlinieTest` (`tests/test_katalog_sicht.py`), `KanonischeIdTest` Alias-Faelle
(`tests/test_katalog.py`).
