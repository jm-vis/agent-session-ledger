# Sitzungsbeleg

Automatischer Beleg je KI-Sitzung (Claude Code, Codex) -- Kennzahlen, Zeiten und Auffaelligkeiten,
NIE Rohinhalt (keine Prompts, kein Denken, keine Tool-Argumente, keine Fehlertexte -- siehe
`modell.py` Moduldoc). CLI: `python -m sitzungsbeleg ingest|serve|...` (aus dem Ordner über
dem Paket, `--help` je Unterbefehl); Dashboard: `python -m sitzungsbeleg serve` (Port 8091,
nur Loopback). Voller Vertrag: `CONTRACTS.md`; Aufbau/Betrieb: Root-README.

**Wache (C13):** `PreToolUse`-Hook (`sitzungsbeleg-wache-hook.py`, fail-open) wendet dieselben
Regeln WAEHREND der Sitzung an, statt erst danach -- Details, Konfiguration (`wache.json`) und
Troubleshooting: `CONTRACTS.md` Abschn. „C13".

## Achsen je Sitzung

Vier unabhaengige Achsen ordnen jede Sitzung ein (Checkboxen in der Start-Seitenleiste, Filter
`GET /api/sitzungen`): **Projekt** sagt, woran gearbeitet wurde (CWD-Hash + Alias,
`projekte.py`/`projekt-aliase.json`). **Kontext** sagt, wozu die Sitzung diente (Arbeit, Review,
Test, Bewertung, Voice). **Anbieter** (angezeigt als „Quelle") sagt, wer sie ausgefuehrt hat
(Claude, Codex, Ollama, OpenRouter, Requesty -- `quellen.py`, abgeleitet aus Modell + Backend).
**Umgebung** (C12) sagt, wo die Anwendung lief, die den Beleg schreibt (`entwicklung` Default ·
`abnahme` · `betrieb` -- `umgebung.py`), aus `SITZUNGSBELEG_UMGEBUNG` im Stop-Hook; sichtbar nur
bei Abweichung (Kuerzel-Chip `Abn.`/`Betrieb`) bzw. erst ab zwei Werten im Zeitraum
(Seitenleisten-Block „Umgebung").
