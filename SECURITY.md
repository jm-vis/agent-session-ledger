# Security

## What is stored

`sitzungsbeleg` turns a Claude Code / Codex session transcript into a "Beleg" (ledger
record): timestamps, token counts, tool-call counts and durations, cost (derived from a
local price table), rule findings (a rule ID plus a short structured detail, e.g.
`latency:slow_turn`), and delegation/subagent counters. It does not store prompts, model
reasoning, tool arguments, tool output, file contents, error text, or any other
conversation text. The record is designed to answer "how did this session run" without
ever needing to answer "what was said in it".

## Redaction allow list (C6)

Every value written into a ledger record passes through `redaktion.py` before storage or
output. A value is rejected (and the whole record is refused, see below) if it looks like:

- a filesystem path (`/`, `\`, `C:\`, `/home/`, `/Users/`, UNC `\\`)
- a secret (`sk-`, `AKIA`, `ghp_`, a `-----BEGIN` PEM block)
- an email address
- the literal marker `_lokal` (used internally to flag protected-source data; if it
  ever shows up in a ledger record, that record is treated as a leak, not as content)
- free text over 80 characters

**The one exception** is `kopf.modelle` (the list of model identifiers used in a session).
Model identifiers legitimately contain a slash -- OpenRouter's `anbieter/modell[:tag]`
form (e.g. `nvidia/nemotron-3-ultra-550b-a55b`) and Ollama's `hf.co/nutzer/repo[:tag]`
form. `redaktion._ist_sicherer_modellname()` allows exactly those two shapes, nothing
broader (a generic "1-3 segments" rule would also pass a real vault path). Every other
field stays under the strict rule: any slash is treated as a path.

If a record still fails the check after cleanup, it is not stored and not rendered --
`ingest` exits 2 instead of writing partial or unclean output (see `_ausgeben()` /
`_bereinigt_oder_fehler()` in `__main__.py`).

## Network exposure

- `ingest` and `ingest-dir` read local transcript files only; they open no network
  connection unless `--db` is passed (writes to a local Postgres via `docker exec` +
  `psql`) or the chat feature is used.
- The chat feature (`chat.py`) is the one deliberate egress point: it sends redacted
  numbers plus your own message text to a provider you pick per message (Claude, a local
  Ollama model, or OpenRouter). Provider API keys live in an environment file outside the
  repository (never commit one); OpenRouter calls prefer the account's zero-data-retention
  (ZDR) setting where available.
- `serve` binds the dashboard to `127.0.0.1` only (`web.py`, `HOST = "127.0.0.1"`) -- it is
  not reachable from the network unless you put a reverse proxy in front of it yourself.

## Reporting a vulnerability

Please open a private security advisory on this repository (GitHub Security Advisories)
rather than a public issue. If that is not available, contact the maintainer listed in
the repository's profile. Include reproduction steps and the affected version (`VERSION`
file / `GET /version`).

## Credential hygiene

Never commit a real `.env` file; `.gitignore` excludes `.env`/`.env.*`/`*.env` (only
`.env.example`, which holds placeholders, is tracked). If a credential (API key,
database password) is ever committed or otherwise published, treat it as compromised
and rotate it immediately -- do not just remove it from a later commit.
