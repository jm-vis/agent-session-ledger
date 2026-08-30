# Changelog

All notable changes to this project are documented in this file.

## 0.3.4 - 2026-08-30

Public-repo hardening after an external review, plus the catalog status zone.

- Model catalog and price table: status zone bottom-right (stars / latest / legacy),
  Ollama base keys resolved via curated `referenz` pointers, tighter context/price columns.
- Background chat now runs with a generic, read-only system prompt (session numbers and
  findings only, no project- or organisation-specific instructions).
- Optional "apply fix" launcher for the chat column, configured via
  `SITZUNGSBELEG_FIX_LAUNCHER`; the endpoint returns 501 and the button shows "not
  configured" when unset.
- Model catalog path is now configurable via `SITZUNGSBELEG_MODELLE`.
- Postgres container name is now configurable via `SITZUNGSBELEG_PG_CONTAINER`
  (default `sitzungsbeleg-postgres`).
- Generated-notes working directory is now configurable via `SITZUNGSBELEG_WORK_DIR`
  (default `_work/`).
- `pyproject.toml` version aligned with the package `VERSION` file.
- Docs made standalone: no more references to paths or layout outside this repository.
- Added regression tests for public-repo hygiene (no internal paths/names leaking into
  tracked docs).

## 0.3.3 - 2026-08-30

- Price table rebuilt in the catalog look: per-column sorting, manufacturer subtitle under the model name (like the catalog), origin flag, channel chip (Codex shown for OpenAI cost equivalents), context size, per-tariff timestamps and a "Used by" column with persona chips.
- Enrichment comes from the catalog via canonical IDs server-side; on ambiguous or missing matches the cells stay empty instead of guessing.
- Persona chips now only show when model AND provider match an actual wiring.
- New Ollama reference prices for kimi-k3 / glm-5.3 / glm-5.3-flash, plus sentinel tests: an Ollama persona pin without a reference price and a historically used session model without a price both turn red.
## 0.3.2 - 2026-08-30

- Catalog filters: "Latest", "On-Premise" and "EU region without training" sit directly under
  the origin chips in that order, evenly spaced.
- Wording: "local" is now "On-Premise" / "On-Prem" everywhere in the catalog and the panels,
  contrasting with "Cloud"; internal field names are unchanged.

## 0.3.1 - 2026-08-30

- Model catalog: Ollama models are now read live from the local Ollama API (`/api/tags`)
  instead of a static registry; local vs. cloud is detected per model, "local only"
  shows on-premise models only.
- Star rating v2: half stars, computed from the Artificial Analysis intelligence and coding
  indices (floor 45 = 3 stars, best current model = 5 stars); models that cannot read images
  are capped at 4 stars. Manual test ratings survive only as a tooltip.
- Model families and generations: each model is "rated", "latest" (current but not yet
  indexed) or "legacy" (a newer generation of the same line exists). A curated
  `generationen.json` sets the minimum generation per product line; the automatic version
  rule covers lines without an entry.
- Canonical IDs merge provider aliases (`-latest`, `:high`/`:low`, `:priority`, `:free`,
  date snapshots) into one row per model; origin is guarded by a test (no model without
  manufacturer and country).
- UI: five small stars with a centred half star, blue "Latest" and grey "Legacy" chips,
  "latest only" filter checkbox; persona and local panels use the same one-line model
  names as the table, without flags, pins or stars.

## 0.3.0 - 2026-08-28

- Add a full model catalog (Settings page): every model reachable through the configured
  providers (Anthropic, Ollama, OpenRouter, Requesty) in one sortable, filterable table
  with context window, cheapest input/output price per provider, and origin flags.
- Consolidate provider-specific model IDs (reseller prefixes, region/batch/free variants,
  spelling differences) into one row per actual model -- 1080 raw entries become ~420 models.
- Enrich the catalog with Artificial Analysis indices (intelligence, coding, agentic,
  output speed) via a three-stage name matching (exact, word-order-neutral, noise-filtered),
  each stage with an ambiguity guard: an index is left empty rather than guessed.
- Add Requesty as a fourth chat provider (EU router, zero-training model list).
- Add persona cards (which default model each assistant persona uses, including a
  local-only tier) and a "refresh now" action that re-fetches all provider catalogs.
- Add per-persona session attribution (which assistant, which channel) to the ledger.
- Compact the catalog rows, fit the table to the viewport in whole rows, and align the
  settings page with the rest of the dashboard (sub-page navigation in the sidebar).

## 0.2.0 - 2026-08-27

- Add OpenRouter as a third chat provider alongside Claude and Ollama, including model
  discovery and a zero-data-retention (ZDR) preference note in the UI.
- Add a KPI context block to the chat sidebar, so a review conversation can see the same
  numbers (cost, latency, tool errors, delegation) as the session detail page, without
  the underlying transcript content.
- Add reference prices for Ollama Cloud models (OpenRouter list price of the same model,
  used for comparison only -- these models are billed via subscription, not per token).
- Introduce a logical session identity (`sitzung_logisch`) so findings and review
  references stay stable across re-ingests of a growing transcript.
- Add a dedicated `chat` table so conversation content never enters the operational event
  stream.
- Add a resolution workflow for findings (`entscheid`: `erledigt` / `obsolet`), usable from
  both the CLI and the dashboard.

## 0.1.0 - 2026-08-25

- Initial release: ingest Claude Code and Codex session transcripts into a deterministic
  ledger (numbers and rule IDs, never content), store it in Postgres, apply the rule
  engine, run a four-eyes review (Claude + Codex), and serve a read-only dashboard.

