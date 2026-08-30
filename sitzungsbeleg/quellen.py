"""Abgeleitete Anzeige-Quelle.

Kopf.quelle bleibt roh gespeichert (`claude` | `codex` | `produkt`) -- angezeigt wird eine
Quelle, die zusaetzlich auflöst, ob eine `claude`-Sitzung nativ gegen Anthropic lief oder ueber
ein anderes Backend (ein lokaler/eigen gehosteter Ollama-Endpunkt, ein Ollama-`:cloud`-Modell, ...).
Registry: scripts/modelle.json -- `preise.modelle[*].herkunft` (anthropic|openai) fuer
Anthropic/Cloud-API-Modelle, `modelle[*]` (alle Eintraege, herkunft=ollama) fuer alles, was
ueber Ollama laeuft, egal ob lokal oder Ollama-`:cloud`. OpenRouter: `quelle_fuer` erkennt die
Namensraum-Form `anbieter/modell[:tag]` unabhaengig von der Registry -- Ollama-Registry-Treffer
gewinnt zuerst (deckt `hf.co/...`-Ollama-Pfade ab, die ebenfalls einen Schraegstrich tragen),
danach die OpenRouter-Form, erst dann "alle Anthropic". Eine gemischte Sitzung (Claude +
Backend-Umschalter) zaehlt wie bei Ollama zum Umschalter, nicht zu Claude.

Requesty: Requesty-Modell-IDs sehen aus wie OpenRouter-IDs
(`anthropic/claude-sonnet-5`) -- der Namensraum allein reicht darum NICHT zur Unterscheidung.
Der Stop-Hook (`__main__._ingest_hook`) laeuft im Prozess von `claude` und erbt dessen
Umgebung; er liest `ANTHROPIC_BASE_URL`, klassifiziert nur die Hostklasse (nie Token/URL) und
schreibt sie als `kopf.backend`. `quelle_fuer` prueft `backend` ZUERST (wenn gesetzt und
bekannt), erst danach die bisherige Modell-Kette -- bestehende Belege ohne `backend` (Feld
optional, leerer String) durchlaufen unveraendert die alte Kette.
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import konfig

MODELLE_PFAD = konfig.modelle_pfad()
SYNTHETISCH = "<synthetic>"  # Test-/Platzhalterwert, nie eine echte Modellangabe
PLATZHALTER_REDIGIERT = "<redigiert>"  # C3-Redaktion hat den Namen zermahlen (Altbestand)

CLAUDE = "Claude"
CODEX = "Codex"
OLLAMA = "Ollama"
OPENROUTER = "OpenRouter"
REQUESTY = "Requesty"
PRODUKT = "Produkt"
UNBEKANNT = "Unbekannt"

# Hostklasse aus `kopf.backend` -> Anzeige-Quelle (nur wenn bekannt; "unbekannt"/leer faellt
# durch auf die bisherige Modell-Kette, s. Moduldoc).
_BACKEND_QUELLE = {
    "anthropic": CLAUDE, "ollama": OLLAMA, "openrouter": OPENROUTER, "requesty": REQUESTY,
}


@lru_cache(maxsize=1)
def _registry_aus_datei() -> dict:
    if not MODELLE_PFAD.exists():
        return {}
    with open(MODELLE_PFAD, encoding="utf-8") as f:
        return json.load(f)


def anthropic_modellnamen(registry: dict | None = None) -> set[str]:
    """Modellnamen aus `preise.modelle`, deren `herkunft` explizit `anthropic` ist."""
    reg = _registry_aus_datei() if registry is None else registry
    preise = reg.get("preise", {}).get("modelle", {})
    return {name for name, satz in preise.items() if satz.get("herkunft") == "anthropic"}


def requesty_modellnamen(registry: dict | None = None) -> set[str]:
    """Katalog-IDs mit `herkunft: requesty` plus ihre `meldet_als`-Aliasse (Requesty meldet im
    Antwortfeld das Upstream-Modell, z. B. `moonshotai/Kimi-K3`; Befund 2026-08-28)."""
    reg = _registry_aus_datei() if registry is None else registry
    preise = reg.get("preise", {}).get("modelle", {})
    namen: set[str] = set()
    for name, satz in preise.items():
        if satz.get("herkunft") == "requesty":
            namen.add(name)
            namen.update(satz.get("meldet_als", ()))
    return namen


def ollama_modellnamen(registry: dict | None = None) -> set[str]:
    """Alle Modellnamen aus dem Ollama-Bestand (`modelle`) -- lokal wie `:cloud`, das
    Ollama-Registry-Segment selbst ist die Quelle der Wahrheit fuer Ollama-Zugehoerigkeit."""
    reg = _registry_aus_datei() if registry is None else registry
    return set(reg.get("modelle", {}).keys())


def _basisname(modell: str) -> str:
    """Ollama-Tag abschneiden: Sitzungen protokollieren `glm-5.2`, die Registry fuehrt
    `glm-5.2:cloud` -- der Abgleich laeuft tag-unabhaengig."""
    return modell.split(":", 1)[0]


def _bereinigte_modelle(modelle: list[str] | None) -> list[str]:
    """Platzhalter (`<synthetic>`, `<redigiert>`) sind keine Modelle -- der Waechter meldete sonst
    '<redigiert>' als 'Modell ohne Registry-Herkunft' (2026-08-28)."""
    return [m for m in (modelle or []) if m and m not in (SYNTHETISCH, PLATZHALTER_REDIGIERT)]


def _ist_openrouter_form(modell: str) -> bool:
    """Namensraum-Form `anbieter/modell[:variante]` (OpenRouter, z. B.
    `nvidia/nemotron-3-ultra-550b-a55b`, `z-ai/glm-5.2:free`) -- Ollama-Namen tragen keinen
    Schraegstrich, ausser `hf.co/...`-Pfaden. Die zaehlen trotzdem als Ollama, weil der
    Registry-Treffer (siehe `quelle_fuer`) VOR dieser Heuristik geprueft wird."""
    return "/" in modell


def _quelle_ueber_modellkette(modelle: list[str] | None, registry: dict | None) -> str:
    """Die bisherige Modell-Kette (Ollama-Registry > Requesty-Registry/meldet_als > OpenRouter-Form > alle Anthropic) --
    ausgelagert aus `quelle_fuer` (Code-Masse-Grenze), greift nur ohne bekanntes `backend`."""
    namen = _bereinigte_modelle(modelle)
    if not namen:
        return CLAUDE
    ollama = {_basisname(m) for m in ollama_modellnamen(registry)}
    if any(_basisname(m) in ollama for m in namen):
        return OLLAMA
    if any(m in requesty_modellnamen(registry) for m in namen):
        return REQUESTY
    if any(_ist_openrouter_form(m) for m in namen):
        return OPENROUTER
    if all(m in anthropic_modellnamen(registry) for m in namen):
        return CLAUDE
    return UNBEKANNT


def quelle_fuer(
    rohquelle: str, modelle: list[str] | None = None, registry: dict | None = None,
    backend: str | None = None,
) -> str:
    """Anzeige-Quelle: Claude/Codex/Ollama/OpenRouter/Requesty/Produkt/Unbekannt (Reihenfolge bei
    `claude`: `backend` (Stop-Hook-Hostklasse, wenn bekannt) > Ollama-Registry > OpenRouter-Form >
    alle Anthropic -- Details im Modul-Kopf)."""
    if rohquelle == "produkt":
        return PRODUKT
    if rohquelle == "codex":
        return CODEX
    if rohquelle != "claude":
        return UNBEKANNT
    if backend and backend in _BACKEND_QUELLE:
        return _BACKEND_QUELLE[backend]
    return _quelle_ueber_modellkette(modelle, registry)


def unbekannte_modelle(rohquelle: str, modelle: list[str] | None = None, registry: dict | None = None) -> list[str]:
    """Modelle einer `claude`-Sitzung, die weder als Anthropic noch als Ollama gefuehrt
    werden noch in OpenRouter-Namensraum-Form vorliegen -- Grundlage fuer den Waechter
    (`aliase --pruefen`)."""
    if rohquelle != "claude":
        return []
    namen = _bereinigte_modelle(modelle)
    bekannt = ({_basisname(m) for m in ollama_modellnamen(registry)} | anthropic_modellnamen(registry)
               | requesty_modellnamen(registry))
    return sorted({
        m for m in namen
        if m not in bekannt and _basisname(m) not in bekannt and not _ist_openrouter_form(m)
    })
