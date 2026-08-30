"""Modellkatalog-Beschaffung (CONTRACTS.md C15, Paket L). Reine BESCHAFFUNG + UPSERT in die
Tabelle `modellkatalog` (Migration `infra/sitzungsbeleg-db/0006_modellkatalog.sql`) -- die Lese-/
API-Seite (`GET /api/modellkatalog`) baut ein anderer Agent, dieses Modul liefert ihr nur die
Daten. Parser (`parse_openrouter`/`parse_requesty`) sind reine Funktionen ueber bereits geparste
JSON-Dicts (kein Netzzugriff), damit sie ohne Verbindung testbar sind -- Muster
`chat._openrouter_modell_eintraege`/`chat._requesty_modell_eintraege`. Fail-open je Quelle: eine
tote Quelle liefert eine Fehlermeldung statt einer Exception, die anderen laufen weiter.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import chat_bruecke, schluessel, speicher

MODELLE_JSON_PFAD = Path(__file__).resolve().parent.parent / "modelle.json"  # scripts/modelle.json

_AA_SCHLUESSEL_RE = None  # lazy, damit `import re` nicht nur hierfuer noetig waere -- s. unten


# Bezugsvarianten desselben Modells, KEINE eigenen Modelle (Befund 2026-08-28 nacht):
# `@region` (Cloud-Regionen wie @eastus2/@eu-west-1, 250+ Zeilen) und die Betriebsmodi
# :flex/:batch/:free. Ollama-Tags (`:cloud`, `:14b`, `:latest`) sind dagegen ECHTE
# Modellvarianten und bleiben unangetastet -- darum feste Suffix-Liste statt ':'-Kappung.
_VARIANTEN_SUFFIXE = (":flex", ":batch", ":free")


def _kappe_varianten(kern: str) -> str:
    """@region und :flex/:batch/:free abschneiden, Schreibweise sonst erhalten."""
    kern = kern.split("@", 1)[0]
    tief = kern.lower()
    for suffix in _VARIANTEN_SUFFIXE:
        if tief.endswith(suffix):
            return kern[: -len(suffix)]
    return kern


def anzeige_kurzform(modell_id: str) -> str:
    """Kurzform in ORIGINAL-Schreibweise (fuer die Anzeige-`id` der Sicht) -- gleiche
    Kappung wie `kurzname()`, aber ohne lowercase. hf.co-IDs (Ollama-Registry-Konvention
    `hf.co/<org>/<modell>-GGUF:<quant>`) sind die Ausnahme: der volle Pfad bleibt stehen, sonst
    ginge die Organisation verloren, die `format.js:modellAnzeigeName()` fuer die Panel-/
    Tabellen-Kurzform `<modell> · <quant> · <org>` braucht (Entscheid 2026-08-30 D)."""
    kern = modell_id.strip()
    if kern.lower().startswith("hf.co/"):
        return _kappe_varianten(kern)
    return _kappe_varianten(kern.rsplit("/", 1)[-1])


def kurzname(modell_id: str) -> str:
    """Konsolidierungs-Schluessel (C15 v2): Teil nach dem letzten '/', lowercase,
    Bezugsvarianten-Suffixe gekappt.

    Anbieter praegen dieselben Modelle mit unterschiedlichen Praefixen und Varianten
    (`claude-fable-5` vs `anthropic/claude-fable-5` vs `claude-fable-5@eu`) -- erst der
    Kurzname macht sie in der Sicht zu EINER Zeile mit mehreren Bezugswegen.
    """
    return anzeige_kurzform(modell_id).lower()


def ist_ollama_cloud(modell_id: str) -> bool:
    """Cloud- vs. Lokal-Erkennung fuer Ollama-Namen (Ollamas eigene Konvention): endet der Name
    auf `:cloud` ODER auf `-cloud` (Groessen-Tag + Cloud-Suffix ohne eigenen Doppelpunkt, z. B.
    `gpt-oss:20b-cloud`, `gemma4:31b-cloud`), ist das Modell cloud-gehostet, sonst lokal
    installiert (echte Groessen-/Bezugsvarianten wie `:14b`/`:latest` zaehlen als lokal).
    Befund 2026-08-30: die reine `:cloud`-Pruefung uebersah die zweite Suffix-Form. Einzige
    Quelle der Wahrheit dafuer -- IMMER auf der ROHEN `modell_id` aufrufen, nie auf einer schon
    kanonisierten/gekappten ID (die haette das Suffix schon verloren, s. `_roh_lokal`)."""
    tief = modell_id.lower()
    return tief.endswith(":cloud") or tief.endswith("-cloud")


def aa_schluessel(text: str) -> str:
    """Match-Schluessel gegen die Artificial-Analysis-Liste (C15 v2): Kurzname zusaetzlich
    auf `[a-z0-9]`-Laeufe mit '-' normiert (AA-Slugs schreiben Punkte als Striche,
    z. B. `glm-5-3-flash` vs Katalog `glm-5.3-flash`)."""
    global _AA_SCHLUESSEL_RE
    if _AA_SCHLUESSEL_RE is None:
        import re
        _AA_SCHLUESSEL_RE = re.compile(r"[^a-z0-9]+")
    return _AA_SCHLUESSEL_RE.sub("-", kurzname(text)).strip("-")


def aa_token_schluessel(text: str) -> str:
    """Wortstellungs-neutraler ZWEITSCHLUESSEL (Maintainer 2026-08-28, "Uebersetzungsfehler"): AA slugt
    `claude-4-5-haiku`, die Anbieter `claude-haiku-4-5` -- sortierte Token machen beide gleich.
    Ein Datums-Suffix (YYYYMMDD, Snapshot-IDs wie `claude-haiku-4-5-20251001`) faellt weg,
    damit Snapshots den Basiseintrag treffen. Nur als Fallback NACH dem Exakt-Match nutzen."""
    token = aa_schluessel(text).split("-")
    if token and len(token[-1]) == 8 and token[-1].startswith("20") and token[-1].isdigit():
        token = token[:-1]
    return "-".join(sorted(token))


# Namens-Rauschen ohne Modell-Unterscheidungskraft (Maintainer 2026-08-28 Runde 2: "so viel wie
# moeglich von diesen leeren Feldern auffuellen"): Zusaetze wie -preview/-chat/-instruct/-v1
# benennen DASSELBE Modell um. Echte Versionsnummern (4, 5.2, 2507) bleiben Token -- und wo
# das Streichen von v1-v3 zwei AA-Eintraege zusammenfallen laesst, verwirft der
# Mehrdeutigkeits-Schutz den Schluessel.
_AA_RAUSCH_TOKEN = frozenset({"instruct", "chat", "it", "preview", "latest", "exp",
                              "v1", "v2", "v3", "free", "hf", "gguf"})


def aa_kern_schluessel(text: str) -> str:
    """Dritte Matching-Stufe: Token-Schluessel ohne Rausch-Token (s. _AA_RAUSCH_TOKEN)."""
    token = [t for t in aa_token_schluessel(text).split("-") if t not in _AA_RAUSCH_TOKEN]
    return "-".join(token)


def _aa_ableitung(zuordnung: dict[str, dict], schluessel_fn) -> dict[str, dict]:
    """Leitet aus dem Exakt-Mapping ein Fallback-Mapping ueber `schluessel_fn` ab. Faellt
    derselbe abgeleitete Schluessel auf ZWEI verschiedene Wertesaetze (echte Mehrdeutigkeit),
    wird er verworfen -- lieber kein Index als der falsche."""
    ergebnis: dict[str, dict] = {}
    mehrdeutig: set[str] = set()
    for schluessel_wert, werte in zuordnung.items():
        abgeleitet = schluessel_fn(schluessel_wert)
        if not abgeleitet or abgeleitet in mehrdeutig:
            continue
        if abgeleitet in ergebnis and ergebnis[abgeleitet] != werte:
            mehrdeutig.add(abgeleitet)
            del ergebnis[abgeleitet]
            continue
        ergebnis[abgeleitet] = werte
    return ergebnis


def _aa_token_zuordnung(zuordnung: dict[str, dict]) -> dict[str, dict]:
    return _aa_ableitung(zuordnung, aa_token_schluessel)


# Kanonisierung Ollama<->OpenRouter/Requesty/AA fuer die KATALOG-GRUPPIERUNG (C15 v2 Punkt 3,
# Befund 2026-08-30) -- eigene, staerkere Normalisierung als `aa_schluessel` (das bleibt fuer
# die AA-Anreicherung unveraendert, eigene Fallback-Kette). Nur bekannte Familien trennen
# Buchstabe+Ziffer per Bindestrich (Google: `gemma-4`/`gemini-3`) -- `qwen3`/`glm-5.2`/`kimi-k2`
# schreiben die Version fest zusammen, NIE trennen (sonst Falsch-Merges/verlorene Treffer).
_ZIFFERN_TRENNUNG_FAMILIEN = ("gemma", "gemini")

# `-it`/`-instruct` sind Anbieter-Anhaengsel fuer dieselbe Instruct-Variante (Ollama traegt sie
# nicht) -- NUR diese zwei, NICHT das breitere `_AA_RAUSCH_TOKEN`-Set (das wuerde `-preview`
# mit-entfernen, das laut Task-Vorgabe eine ECHTE Modellauspraegung bleibt).
_KANONISCH_RAUSCH_TOKEN = frozenset({"it", "instruct"})

# Bezugsvarianten-Suffixe wie `_VARIANTEN_SUFFIXE`, aber fuer die KATALOG-GRUPPIERUNG (
# Festlegung 2026-08-30, generationen.json Feld `aliasse`): Router-/Reasoning-Effort-Anhaengsel
# (`-latest`, `:high`/`:medium`/`:low`, `:priority`, `:free`, `:nitro`, `:exacto`, `:online`)
# sind KEIN eigenes Modell, nur eine Bezugsvariante -- `aa_schluessel` vereinheitlicht Binde-
# strich UND Doppelpunkt schon zu einem Trenner, darum reicht EIN Token-Set fuer beide Schreib-
# weisen (`o1:high` == `o1-high` als Tokenfolge). Ein Datums-Suffix (`mistral-large-2512`) ist
# KEIN Alias, bleibt eigene Zeile -- diese Liste enthaelt nur Woerter, nie Ziffern.
_ALIAS_SUFFIX_WOERTER = frozenset({
    "latest", "high", "medium", "low", "priority", "free", "nitro", "exacto", "online",
})


def _ziffer_anhaengen_trennen(token: str) -> str:
    """`gemma4` -> `gemma-4` (nur fuer `_ZIFFERN_TRENNUNG_FAMILIEN`), sonst unveraendert."""
    for familie in _ZIFFERN_TRENNUNG_FAMILIEN:
        rest = token[len(familie):]
        if token.startswith(familie) and rest.isdigit():
            return f"{familie}-{rest}"
    return token


def _ist_yyyymmdd(token: str) -> bool:
    """Erkennt ein trailing 8-stelliges Snapshot-Datum (`20251001`) -- Muster
    `aa_token_schluessel`, hier fuer die Katalog-GRUPPIERUNG (Entscheid 2026-08-30
    Nachtrag 6): `scripts/modelle.json` fuehrt Anthropic-Modelle mit Snapshot-Suffix
    (`claude-haiku-4-5-20251001`), OpenRouter/Requesty ohne. Echtes Jahr/Monat/Tag gefordert,
    keine beliebige 8-stellige Ziffernfolge."""
    if len(token) != 8 or not token.isdigit():
        return False
    jahr, monat, tag = int(token[:4]), int(token[4:6]), int(token[6:8])
    return 2000 <= jahr <= 2099 and 1 <= monat <= 12 and 1 <= tag <= 31


def kanonische_id(modell_id: str) -> str:
    """Katalog-GRUPPIERUNGS-Schluessel (C15 v2 Punkt 3): `aa_schluessel` plus fuenf zusaetzliche
    Normalisierungen -- (1) Cloud-Suffix (`:cloud`/`-cloud`, nach `aa_schluessel` immer ein
    letztes Token `cloud`) weg, (2) Ziffer-Buchstabe-Trennung fuer bekannte Familien
    (`_ziffer_anhaengen_trennen`), (3) `-it`/`-instruct` ignoriert, (4) ein trailing
    YYYYMMDD-Snapshot-Suffix weg (`_ist_yyyymmdd`, Entscheid 2026-08-30 Nachtrag 6 --
    `claude-haiku-4-5-20251001` aus `scripts/modelle.json` == `claude-haiku-4-5` bei
    OpenRouter/Requesty), (5) Router-/Bezugsvarianten-Alias-Suffixe weg (`_ALIAS_SUFFIX_WOERTER`,
    Festlegung 2026-08-30 -- `o1:high`/`gpt-5:priority`/`mistral-large-latest` sind dieselbe
    Zeile wie `o1`/`gpt-5`/`mistral-large`; eine Datumsversion wie `mistral-large-2512` bleibt
    eigene Zeile, kein Alias). Beispiele (echte Katalog-IDs, Befund 2026-08-30):
    `gpt-oss:20b-cloud` == `openai/gpt-oss-20b`; `gemma4:31b-cloud` == `google/gemma-4-31b-it`;
    `glm-5.2:cloud` == `glm-5.2` (AA/OpenRouter). NUR fuer die Katalog-AGGREGATION
    (`katalog_sicht.aggregiere`), NICHT fuer die AA-Anreicherung (eigene Fallback-Kette in
    `aktualisiere_aa_indizes`)."""
    token = [t for t in aa_schluessel(modell_id).split("-") if t]
    while token and token[-1] in _ALIAS_SUFFIX_WOERTER:
        token = token[:-1]
    if token and token[-1] == "cloud":
        token = token[:-1]
    if token and _ist_yyyymmdd(token[-1]):
        token = token[:-1]
    getrennt = [_ziffer_anhaengen_trennen(t) for t in token]
    token = [teil for t in getrennt for teil in t.split("-")]
    token = [t for t in token if t not in _KANONISCH_RAUSCH_TOKEN]
    return "-".join(token)
OPENROUTER_MODELLE_URL = "https://openrouter.ai/api/v1/models"
REQUESTY_MODELLE_URL = "https://router.requesty.ai/v1/models"
ARTIFICIALANALYSIS_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"  # lokaler Daemon, kein externes Netz
OLLAMA_SHOW_URL = "http://localhost:11434/api/show"  # capabilities/vision, ein Aufruf je Modell
ZEITLIMIT_S = 5
QUELLEN_REIHENFOLGE = ("claude", "ollama", "openrouter", "requesty")

# Kleine Hersteller->(Anzeigename, Herkunft-ISO2)-Zuordnung (Task-Vorgabe: kein Anspruch auf
# Vollstaendigkeit, unbekannt bleibt `herkunft` NULL). Schluessel werden sowohl als exakter
# OpenRouter/Requesty-Anbieter-Slug (Teil vor dem ersten "/") als auch als Teilstring im vollen
# Modellnamen geprueft (deckt Requesty-Reseller-Slugs wie `sference/kimi-k3` und Ollama-Namen
# ohne Slug wie `glm-5.2` ab) -- siehe `hersteller_und_herkunft()`.
HERSTELLER_HERKUNFT: dict[str, tuple[str, str]] = {
    "openai": ("OpenAI", "US"),
    "gpt-oss": ("OpenAI", "US"),
    "anthropic": ("Anthropic", "US"),
    "claude": ("Anthropic", "US"),
    "google": ("Google", "US"),
    "gemini": ("Google", "US"),
    "gemma": ("Google", "US"),
    "nvidia": ("Nvidia", "US"),
    "nemotron": ("Nvidia", "US"),
    "meta-llama": ("Meta", "US"),
    "x-ai": ("xAI", "US"),
    "cohere": ("Cohere", "CA"),
    "mistralai": ("Mistral AI", "EU"),
    "mistral": ("Mistral AI", "EU"),
    "deepseek": ("DeepSeek", "CN"),
    "qwen": ("Alibaba", "CN"),
    "moonshotai": ("Moonshot AI", "CN"),
    "kimi": ("Moonshot AI", "CN"),
    "z-ai": ("Zhipu AI", "CN"),
    "glm": ("Zhipu AI", "CN"),
    "minimax": ("MiniMax", "CN"),
    # Nachtrag Sichtabnahme 2026-08-28 nacht: recherchierte Hersteller der groessten
    # NULL-Herkunft-Gruppen (nur SICHERE Zuordnungen; die Community-Finetuner stehen seit
    # Runde 3 unten mit Basismodell-Herkunft).
    "gpt": ("OpenAI", "US"),  # nach gpt-oss einsortiert: azure/gpt-5 u. ae. Reseller-IDs
    "grok": ("xAI", "US"),
    "xai": ("xAI", "US"),
    "perplexity": ("Perplexity", "US"),
    "sonar": ("Perplexity", "US"),
    "tencent": ("Tencent", "CN"),
    "hunyuan": ("Tencent", "CN"),
    "thinkingmachines": ("Thinking Machines Lab", "US"),
    "poolside": ("Poolside", "US"),
    "bytedance-seed": ("ByteDance", "CN"),
    "bytedance": ("ByteDance", "CN"),
    "amazon": ("Amazon", "US"),
    "aion-labs": ("AionLabs", "IL"),
    "nousresearch": ("Nous Research", "US"),
    "meta": ("Meta", "US"),
    "xiaomi": ("Xiaomi", "CN"),
    "sakana": ("Sakana AI", "JP"),
    "kwaipilot": ("Kuaishou", "CN"),
    "ibm-granite": ("IBM", "US"),
    "granite": ("IBM", "US"),
    "arcee-ai": ("Arcee", "US"),
    "morph": ("Morph", "US"),
    "stepfun": ("StepFun", "CN"),
    "inclusionai": ("Ant Group", "CN"),
    "microsoft": ("Microsoft", "US"),
    "rekaai": ("Reka", "US"),
    "upstage": ("Upstage", "KR"),
    "writer": ("Writer", "US"),
    "baidu": ("Baidu", "CN"),
    "meituan": ("Meituan", "CN"),
    "liquid": ("Liquid AI", "US"),
    "allenai": ("Allen Institute", "US"),
    "olmo": ("Allen Institute", "US"),
    "inception": ("Inception", "US"),
    # Herkunft der Anbieter-Praefixe, mit Quellen recherchiert und gegengeprueft:
    "dots-studio": ("Xiaohongshu", "CN"),      # dots-Team von RedNote/Xiaohongshu, Shanghai
    "muse-glimmer": ("Meta", "US"),            # Meta-Modell, auf Fireworks nur gehostet
    "mancer": ("Mancer AI", "US"),             # Sunlit Software Inc. dba Mancer AI, Maryland
    "nex-agi": ("Nex AGI", "CN"),              # Shanghai Innovation Institute
    "perceptron": ("Perceptron AI", "US"),
    "relace": ("Relace", "US"),                # YC-Startup, San Francisco
    "o4-mini": ("OpenAI", "US"),               # azure/o4-mini-Reseller-IDs
    "baichuan": ("Baichuan AI", "CN"),
    # Recherche-Runde 3 (Auftrag 2026-08-28: "jedes Modell hat eine Herkunft"). Die
    # Macher sind pseudonym und ohne belegbaren Standort (Subagent-Recherche mit Quellen-
    # pflicht, HF-/GitHub-Profile geprueft) -- darum Rueckfallregel: Herkunft des
    # BASISMODELLS, je Modellkarte verifiziert. Sao10K/Gryphe/Undi95 = Llama-Finetunes
    # (Meta/US), TheDrummer = Mistral-Finetunes (Mistral AI = EU im Haus-Schema,
    # Maintainer 2026-08-28: kein FR-Sonderweg neben dem EU-Eintrag von mistralai), anthracite-org
    # = Qwen2.5 (CN).
    "sao10k": ("Sao10K (Llama-Basis)", "US"),
    "gryphe": ("Gryphe (Llama-Basis)", "US"),
    "undi95": ("Undi95 (Llama-Basis)", "US"),
    "thedrummer": ("TheDrummer (Mistral-Basis)", "EU"),
    "anthracite-org": ("Anthracite (Qwen-Basis)", "CN"),
    # Nachtrag Abnahme 2026-08-30: die zwei einzigen NULL-Herkunft-IDs im Live-Katalog
    # (Wächter-Test `HerkunftWaechterTest`) -- Substring-Treffer, da beide ohne Anbieter-Slug
    # vor dem ersten "/" ankommen (`hf.co/<org>/...-GGUF`, taggloses Ollama-`nomic-embed-text`).
    "eurollm": ("Unbabel", "EU"),   # EuroLLM, Unbabel (Lissabon, PT) -- EU im Haus-Schema
    "nomic": ("Nomic AI", "US"),
}

# Hosting-/Router-Praefixe, KEINE Hersteller (azure/gpt-5 = OpenAI hinter Azure): fuer die
# Herkunftserkennung wird der Praefix uebersprungen und der Rest der ID geprueft.
RESELLER_PRAEFIXE = frozenset({
    "azure", "bedrock", "novita", "deepinfra", "nebius", "fireworks",
    "openrouter", "together", "groq", "cerebras",
})  # KEIN "mancer": deren einziges Katalog-Modell (weaver) ist ihr Eigenbau


class KatalogZeile(BaseModel):
    """Eine Zeile `modellkatalog` (C15-Spalten) -- Validierung vor dem Upsert. `anbieter` deckt
    sich mit dem CHECK-Constraint der Migration."""

    model_config = ConfigDict(extra="forbid")

    modell_id: str = Field(min_length=1)
    hersteller: str = Field(min_length=1)
    herkunft: str | None = Field(default=None, min_length=2, max_length=2)
    anbieter: Literal["claude", "ollama", "openrouter", "requesty"]
    lokal: bool = False  # Befund 2026-08-30 (Fix 2): AN DER ROHEN modell_id gesetzt, bei der
    # Beschaffung -- nie nachtraeglich aus einer schon kanonisierten/gekappten ID ableiten.
    vision: bool | None = None  # Entscheid 2026-08-30 Nachtrag 6: Bild-Faehigkeit ("kann
    # Bilder lesen"), tri-state -- `None` = unbekannt (Requesty/AA/Claude liefern das (noch)
    # nicht). Ollama: `ollama_vision()` per `/api/show` (separate Anreicherung, s. unten, NICHT
    # im reinen Parser `parse_ollama_tags` -- der bleibt netzwerkfrei/pur testbar). OpenRouter:
    # `parse_openrouter` liest `architecture.input_modalities` direkt aus der schon geholten
    # Antwort (kein Zusatz-Request noetig).
    kontext_k: int | None = Field(default=None, ge=0)
    eingabe_usd: float | None = Field(default=None, ge=0)
    ausgabe_usd: float | None = Field(default=None, ge=0)
    aa_index: int | None = Field(default=None, ge=0, le=100)
    coding_index: int | None = Field(default=None, ge=0, le=100)
    stand: date
    quelle: str = Field(min_length=1)


def hersteller_und_herkunft(modell_id: str) -> tuple[str, str | None]:
    """(Hersteller, Herkunft-ISO2) aus einer Modell-/Slug-ID -- erst der Anbieter-Slug vor dem
    ersten `/`, sonst eine Teilstring-Suche im ganzen (kleingeschriebenen) Namen. Hosting-
    Praefixe (RESELLER_PRAEFIXE, z. B. `azure/gpt-5`) werden uebersprungen und der Rest
    geprueft. Unbekannt: Hersteller = der rohe Slug/Name (title-cased), Herkunft = `None`."""
    kern = modell_id.lower()
    slug = kern.split("/", 1)[0]
    if slug in RESELLER_PRAEFIXE and "/" in kern:
        return hersteller_und_herkunft(kern.split("/", 1)[1])
    treffer = HERSTELLER_HERKUNFT.get(slug) or next(
        (v for k, v in HERSTELLER_HERKUNFT.items() if k in kern), None
    )
    if treffer is not None:
        return treffer
    return slug.split(":", 1)[0].title(), None


def _warne_wenn_herkunft_unbekannt(modell_id: str, herkunft: str | None) -> None:
    """Stderr-Hinweis (Abnahme 2026-08-30, Fix 4): eine unbekannte Herkunft soll bei der
    Beschaffung auffallen (Recherchebedarf), statt still im Katalog zu versickern."""
    if herkunft is None:
        print(f"warnung: Herkunft unbekannt: {modell_id}", file=sys.stderr)


def _kontext_k(tokens) -> int | None:
    """Token-Kontextfenster -> Kontext in k (Spalte `kontext_k`) -- `None` bleibt `None`."""
    return round(tokens / 1000) if isinstance(tokens, (int, float)) and tokens else None


def _preis_je_million(wert) -> float | None:
    """USD/Token (String oder Zahl, OpenRouter/Requesty-Konvention) -> USD/1M Token (Einheit
    wie `scripts/modelle.json`). `None` bei fehlendem oder kaputtem Wert."""
    try:
        return round(float(wert) * 1_000_000, 6) if wert not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _zeile_anhaengen(zeilen: list[KatalogZeile], **felder) -> int:
    """Haengt eine validierte Zeile an; ungueltige Eintraege (z. B. OpenRouter-Auto-Router
    mit Preis -1) werden uebersprungen statt die ganze Quelle zu reissen. Liefert 1 bei
    Uebersprungen, sonst 0 (Aufrufer zaehlt fuer die stderr-Warnung)."""
    try:
        zeilen.append(KatalogZeile(**felder))
        return 0
    except ValidationError:
        return 1


def _openrouter_vision(eintrag: dict) -> bool | None:
    """Bild-Faehigkeit aus `architecture.input_modalities` (Entscheid 2026-08-30 Nachtrag 6):
    enthaelt die Liste `"image"`, kann das Modell Bilder lesen. Fehlt `architecture` oder ist
    `input_modalities` keine Liste (aeltere/kaputte Antwortform), bleibt das Ergebnis `None`
    (unbekannt) statt eines erfundenen `False`."""
    modalitaeten = (eintrag.get("architecture") or {}).get("input_modalities")
    return "image" in modalitaeten if isinstance(modalitaeten, list) else None


def parse_openrouter(daten: dict) -> list[KatalogZeile]:
    """Parst `{"data": [{"id", "context_length", "pricing": {"prompt", "completion"}}, ...]}`
    (OpenRouter `GET /v1/models`) zu validierten Zeilen. `stand` ist das Datum des Abruflaufs --
    die API liefert kein 'zuletzt geaendert je Modell'-Feld."""
    heute = date.today()
    zeilen = []
    uebersprungen = 0
    for eintrag in daten.get("data", []):
        if not isinstance(eintrag, dict) or not eintrag.get("id"):
            continue
        if eintrag["id"].startswith("~"):
            continue  # "~anbieter/x-latest" = Alias-Verweis auf ein konkretes Modell, kein Modell
        if eintrag["id"].startswith("openrouter/"):
            continue  # "openrouter/auto"/"openrouter/free" = Router-Pseudoeintraege, keine Modelle
        hersteller, herkunft = hersteller_und_herkunft(eintrag["id"])
        _warne_wenn_herkunft_unbekannt(eintrag["id"], herkunft)
        preise = eintrag.get("pricing") or {}
        uebersprungen += _zeile_anhaengen(
            zeilen,
            modell_id=eintrag["id"], hersteller=hersteller, herkunft=herkunft, anbieter="openrouter",
            vision=_openrouter_vision(eintrag),
            kontext_k=_kontext_k(eintrag.get("context_length")),
            eingabe_usd=_preis_je_million(preise.get("prompt")),
            ausgabe_usd=_preis_je_million(preise.get("completion")),
            stand=heute, quelle=OPENROUTER_MODELLE_URL,
        )
    if uebersprungen:
        print(f"warnung: {uebersprungen} ungueltige Modellzeile(n) uebersprungen", file=sys.stderr)
    return zeilen


def parse_requesty(daten: dict) -> list[KatalogZeile]:
    """Parst `{"data": [{"id", "context_window", "input_price", "output_price"}, ...]}`
    (Requesty `GET /v1/models`, oeffentlich) -- gleiche Preis-Umrechnung wie OpenRouter."""
    heute = date.today()
    zeilen = []
    uebersprungen = 0
    for eintrag in daten.get("data", []):
        if not isinstance(eintrag, dict) or not eintrag.get("id"):
            continue
        hersteller, herkunft = hersteller_und_herkunft(eintrag["id"])
        _warne_wenn_herkunft_unbekannt(eintrag["id"], herkunft)
        uebersprungen += _zeile_anhaengen(
            zeilen,
            modell_id=eintrag["id"], hersteller=hersteller, herkunft=herkunft, anbieter="requesty",
            kontext_k=_kontext_k(eintrag.get("context_window")),
            eingabe_usd=_preis_je_million(eintrag.get("input_price")),
            ausgabe_usd=_preis_je_million(eintrag.get("output_price")),
            stand=heute, quelle=REQUESTY_MODELLE_URL,
        )
    if uebersprungen:
        print(f"warnung: {uebersprungen} ungueltige Modellzeile(n) uebersprungen", file=sys.stderr)
    return zeilen


def parse_ollama_tags(daten: dict) -> list[KatalogZeile]:
    """Parst `{"models": [{"name", "details": {"context_length"}}, ...]}` (Ollama `GET
    /api/tags`, lokaler Daemon) zu validierten Zeilen -- LIVE-Basisquelle fuer anbieter='ollama'
    (Nachtrag: `modelle.json` allein zeigt neu installierte Modelle nie). Preis bleibt `None` --
    der Daemon kennt keine Preise, die kommen erst aus `_ollama_anreichern()`."""
    heute = date.today()
    zeilen = []
    uebersprungen = 0
    for eintrag in daten.get("models", []):
        if not isinstance(eintrag, dict) or not eintrag.get("name"):
            continue
        hersteller, herkunft = hersteller_und_herkunft(eintrag["name"])
        _warne_wenn_herkunft_unbekannt(eintrag["name"], herkunft)
        details = eintrag.get("details") if isinstance(eintrag.get("details"), dict) else {}
        uebersprungen += _zeile_anhaengen(
            zeilen,
            modell_id=eintrag["name"], hersteller=hersteller, herkunft=herkunft, anbieter="ollama",
            lokal=not ist_ollama_cloud(eintrag["name"]),  # Fix 2: an der ROHEN Ollama-Tag-ID
            kontext_k=_kontext_k(details.get("context_length")),
            stand=heute, quelle=OLLAMA_TAGS_URL,
        )
    if uebersprungen:
        print(f"warnung: {uebersprungen} ungueltige Modellzeile(n) uebersprungen", file=sys.stderr)
    return zeilen


def _aa_int(wert) -> int | None:
    """AA-Index (`evaluations.*`, 0..100 Float) gerundet zu int -- `None` bleibt `None`
    (Muster `_kontext_k`)."""
    return round(wert) if isinstance(wert, (int, float)) else None


def _aa_agentic_index(tau2) -> int | None:
    """`evaluations.tau2` (0..1, Agentic-Werkzeug-Benchmark) -> `agentic_index` = round(tau2*100)
    (CONTRACTS.md C15 v2 Punkt 1)."""
    return round(tau2 * 100) if isinstance(tau2, (int, float)) else None


def _aa_tempo(wert) -> float | None:
    """`median_output_tokens_per_second` -> `tempo_tok_s`, schon in der Zieleinheit."""
    return float(wert) if isinstance(wert, (int, float)) else None


def _aa_werte(eintrag: dict) -> dict:
    """Ein AA-Modell-Eintrag -> die vier Anreicherungs-Felder (C15 v2 Punkt 1). Fehlende/kaputte
    `evaluations` (kein dict) liefert einfach vier `None`-Werte, kein Absturz."""
    bewertungen = eintrag.get("evaluations")
    if not isinstance(bewertungen, dict):
        bewertungen = {}
    return {
        "aa_index": _aa_int(bewertungen.get("artificial_analysis_intelligence_index")),
        "coding_index": _aa_int(bewertungen.get("artificial_analysis_coding_index")),
        "agentic_index": _aa_agentic_index(bewertungen.get("tau2")),
        "tempo_tok_s": _aa_tempo(eintrag.get("median_output_tokens_per_second")),
    }


def parse_artificialanalysis(daten: dict) -> dict[str, dict]:
    """Parst `{"data": [{"slug", "name", "evaluations": {...}, "median_output_tokens_per_second"},
    ...]}` (Artificial-Analysis `GET /api/v2/data/llms/models`) zu einem Mapping
    `aa_schluessel(text) -> {aa_index, coding_index, agentic_index, tempo_tok_s}` (CONTRACTS.md
    C15 v2 Punkt 1). Je Modell werden BEIDE Schluessel (`slug` und `name`) eingetragen -- der
    erste Treffer gewinnt bei einer Kollision. Fail-open je Eintrag: kein `dict` oder weder
    `slug` noch `name` vorhanden zaehlt als uebersprungen, reisst die restliche Liste nicht mit."""
    zuordnung: dict[str, dict] = {}
    uebersprungen = 0
    for eintrag in daten.get("data", []):
        texte = [t for t in (eintrag.get("slug"), eintrag.get("name"))] if isinstance(eintrag, dict) else []
        texte = [t for t in texte if t]
        if not texte:
            uebersprungen += 1
            continue
        werte = _aa_werte(eintrag)
        for text in texte:
            schluessel_wert = aa_schluessel(text)
            if schluessel_wert and schluessel_wert not in zuordnung:
                zuordnung[schluessel_wert] = werte
    if uebersprungen:
        print(f"warnung: {uebersprungen} ungueltige AA-Modellzeile(n) uebersprungen", file=sys.stderr)
    return zuordnung


def _kontext_lookup(registry: dict) -> dict[str, object]:
    """Modellname ohne Tag (vor dem ersten `:`) -> Kontextfenster (Token) aus `registry['modelle']`
    (Ollama-Bestand) -- Bruecke zwischen den kurzen `preise.modelle`-Schluesseln (z. B. 'glm-5.2')
    und den vollen Ollama-Namen mit Tag (z. B. 'glm-5.2:cloud')."""
    return {
        name.split(":", 1)[0]: angaben.get("kontext")
        for name, angaben in registry.get("modelle", {}).items() if isinstance(angaben, dict)
    }


def _ollama_typ_lookup(registry: dict) -> dict[str, bool]:
    """Basisname (ohne `:tag`) -> `lokal`-Bool aus `registry['modelle']` (Feld `typ`, echte
    getaggte Namen wie `glm-5.2:cloud`) -- Bruecke fuer `von_modelle_json()`, dessen
    `preise.modelle`-Schluessel taglos sind (`glm-5.2`) und darum `katalog.ist_ollama_cloud()`
    nicht direkt anwenden koennen (Befund 2026-08-30, Fix 2: ein taggloser Registry-Name
    waere sonst IMMER faelschlich `lokal=True`)."""
    ergebnis: dict[str, bool] = {}
    for name, angaben in registry.get("modelle", {}).items():
        if isinstance(angaben, dict) and angaben.get("herkunft") == "ollama":
            ergebnis.setdefault(name.split(":", 1)[0], angaben.get("typ") == "lokal")
    return ergebnis


def von_modelle_json(registry: dict, quelle: str) -> list[KatalogZeile]:
    """C15: Anthropic-/Ollama-Zeilen aus `scripts/modelle.json` (`preise.modelle`, Feld
    `herkunft == quelle`) -- gepflegte Werte + Referenzpreise, keine Live-Abfrage. `quelle` ist
    'anthropic' oder 'ollama' (Registry-Wortwahl); die Katalogspalte `anbieter` heisst bei
    Anthropic 'claude'. `kontext_k` bleibt `None`, wenn die Registry kein Kontextfenster fuehrt
    (aktuell nur fuer Ollama-Modelle gepflegt, nicht fuer Anthropic -- offener Punkt). `lokal`
    (nur `quelle='ollama'`, Fix 2) kommt aus `_ollama_typ_lookup()`, NICHT aus `ist_ollama_cloud`
    -- die Schluessel hier sind taglos, das Suffix ist schon weg."""
    anbieter = "claude" if quelle == "anthropic" else quelle
    preise = registry.get("preise", {})
    kontext = _kontext_lookup(registry)
    typ_lookup = _ollama_typ_lookup(registry) if quelle == "ollama" else {}
    zeilen = []
    for modell_id, angaben in preise.get("modelle", {}).items():
        if not isinstance(angaben, dict) or angaben.get("herkunft") != quelle:
            continue
        hersteller, herkunft = hersteller_und_herkunft(modell_id)
        _warne_wenn_herkunft_unbekannt(modell_id, herkunft)
        stand = angaben.get("stand") or preise.get("stand") or date.today().isoformat()
        zeilen.append(KatalogZeile(
            modell_id=modell_id, hersteller=hersteller, herkunft=herkunft, anbieter=anbieter,
            lokal=typ_lookup.get(modell_id, False),
            kontext_k=_kontext_k(kontext.get(modell_id)),
            eingabe_usd=angaben.get("input"), ausgabe_usd=angaben.get("output"),
            stand=stand, quelle=angaben.get("quelle") or "scripts/modelle.json",
        ))
    return zeilen


def _openrouter_anfrage() -> tuple[str, dict]:
    """(url, headers) -- Schluessel vorhanden (Muster `chat._openrouter_anfrage`): Header
    zusaetzlich gesetzt (kontospezifische Sicht moeglich); sonst oeffentliche, ungefilterte
    Liste. Der Schluessel geht nur in den Header-Wert, nie in Log/Rueckgabe."""
    try:
        schluessel = chat_bruecke._openrouter_schluessel()
    except chat_bruecke.OpenRouterSchluesselFehler:
        return OPENROUTER_MODELLE_URL, {}
    return OPENROUTER_MODELLE_URL, {"Authorization": f"Bearer {schluessel}"}


def _openrouter_holen(url: str, headers: dict) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                 timeout=ZEITLIMIT_S) as antwort:
        return antwort.read().decode("utf-8")


OPENROUTER_HOLEN = _openrouter_holen


def _requesty_holen() -> str:
    with urllib.request.urlopen(REQUESTY_MODELLE_URL, timeout=ZEITLIMIT_S) as antwort:
        return antwort.read().decode("utf-8")


REQUESTY_HOLEN = _requesty_holen


def _beschaffe_openrouter() -> tuple[list[KatalogZeile], str]:
    try:
        url, headers = _openrouter_anfrage()
        return parse_openrouter(json.loads(OPENROUTER_HOLEN(url, headers))), ""
    except (OSError, urllib.error.URLError, ValueError, ValidationError) as fehler:
        return [], f"OpenRouter nicht erreichbar: {fehler}"


def _beschaffe_requesty() -> tuple[list[KatalogZeile], str]:
    try:
        return parse_requesty(json.loads(REQUESTY_HOLEN())), ""
    except (OSError, urllib.error.URLError, ValueError, ValidationError) as fehler:
        return [], f"Requesty nicht erreichbar: {fehler}"


def _ollama_api_holen() -> dict:
    """Ollama-Bestand live von `GET /api/tags` (lokaler Daemon, kein externes Netz) --
    LIVE-Basisquelle fuer anbieter='ollama' (Nachtrag: `modelle.json` allein zeigt neu
    installierte Modelle nie, auch "Jetzt aktualisieren" griff bisher nur die statische Registry
    ab). Fail-open ANDERS als die uebrigen `_*_holen()`: Netzfehler/kaputte Antwort werden HIER
    schon geloggt und liefern ein leeres `{}` statt einer Exception, weil `_beschaffe_ollama()`
    dieses "nicht erreichbar" von einer echten Registry-Panne unterscheiden muss (Fallback)."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=ZEITLIMIT_S) as antwort:
            return json.loads(antwort.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as fehler:
        print(f"warnung: Ollama (/api/tags) nicht erreichbar: {fehler}", file=sys.stderr)
        return {}


OLLAMA_API_HOLEN = _ollama_api_holen


def _ollama_registry_preise(registry: dict) -> dict[str, dict]:
    """Ollama-Referenzpreise aus `modelle.json` (`preise.modelle`, `herkunft == 'ollama'`),
    Schluessel = Modellname OHNE `:tag` -- Bruecke zu den vollen Live-Namen mit Tag
    (Live 'glm-5.3:cloud' -> Registry-Schluessel 'glm-5.3')."""
    preise = registry.get("preise", {}).get("modelle", {})
    return {name: angaben for name, angaben in preise.items()
            if isinstance(angaben, dict) and angaben.get("herkunft") == "ollama"}


def _ollama_show_holen(modell_id: str) -> dict:
    """`POST /api/show` fuer EIN Ollama-Modell (lokaler Daemon) -- liefert u. a. `capabilities`
    (Liste wie `["completion", "vision", "tools"]`), das `GET /api/tags` nicht mitliefert."""
    body = json.dumps({"model": modell_id}).encode("utf-8")
    anfrage = urllib.request.Request(OLLAMA_SHOW_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


OLLAMA_SHOW_HOLEN = _ollama_show_holen

# Prozessweiter Cache (Entscheid 2026-08-30 Nachtrag 6): ein `katalog-update`-Lauf fragt
# denselben installierten Namen sonst bei jeder Gruppen-/Preis-Anreicherung erneut ab.
_OLLAMA_VISION_CACHE: dict[str, bool | None] = {}


def ollama_vision(modell_id: str) -> bool | None:
    """Bild-Faehigkeit EINES Ollama-Modells ueber `/api/show` (`capabilities`-Liste enthaelt
    `"vision"`) -- Fail-soft: Netzfehler/kaputte Antwort -> `None` (unbekannt), NIE ein Absturz
    der Beschaffung. Bewusst NICHT in `parse_ollama_tags` (der bleibt ein reiner, netzwerkfreier
    Parser, Moduldoc) -- eigener Anreicherungsschritt wie `_ollama_anreichern()` fuer Preise."""
    if modell_id in _OLLAMA_VISION_CACHE:
        return _OLLAMA_VISION_CACHE[modell_id]
    ergebnis = None
    try:
        daten = OLLAMA_SHOW_HOLEN(modell_id)
        faehigkeiten = daten.get("capabilities") if isinstance(daten, dict) else None
        if isinstance(faehigkeiten, list):
            ergebnis = "vision" in faehigkeiten
    except (OSError, urllib.error.URLError, ValueError):
        ergebnis = None
    _OLLAMA_VISION_CACHE[modell_id] = ergebnis
    return ergebnis


def _ollama_vision_anreichern(zeilen: list[KatalogZeile]) -> list[KatalogZeile]:
    """Haengt `vision` an jede Ollama-Zeile an (Muster `_ollama_anreichern` fuer Preise) --
    eigener Schritt NACH dem reinen Parser, ein `/api/show`-Aufruf je distinktem Modellnamen
    (gecacht, `ollama_vision()`)."""
    return [z.model_copy(update={"vision": ollama_vision(z.modell_id)}) for z in zeilen]


def _ollama_anreichern(zeilen: list[KatalogZeile], registry: dict) -> list[KatalogZeile]:
    """Reichert Live-Zeilen mit Referenzpreisen aus `modelle.json` an (Match ueber den Namen
    ohne `:tag`) -- der Ollama-Daemon kennt keine Preise. Modelle NUR in `modelle.json`, nicht
    mehr live installiert, werden NICHT angehaengt (Ollama = Wahrheit ueber den Bestand)."""
    preis_lookup = _ollama_registry_preise(registry)
    ergebnis = []
    for zeile in zeilen:
        angaben = preis_lookup.get(zeile.modell_id.split(":", 1)[0])
        if angaben is None:
            ergebnis.append(zeile)
            continue
        ergebnis.append(zeile.model_copy(update={
            "eingabe_usd": angaben.get("input"), "ausgabe_usd": angaben.get("output"),
        }))
    return ergebnis


def _beschaffe_ollama(registry: dict) -> tuple[list[KatalogZeile], str]:
    """Ollama live als Basisquelle: `/api/tags` ist die Wahrheit ueber den Bestand (neue
    Modelle erscheinen sofort), `modelle.json` reichert nur Referenzpreise an. Nicht erreichbar
    (leere Live-Liste, `_ollama_api_holen()` hat schon geloggt) -> Fallback auf die alte
    modelle.json-Zeilenliste, mit eigener Warnung."""
    try:
        zeilen = parse_ollama_tags(OLLAMA_API_HOLEN())
    except (OSError, urllib.error.URLError, ValueError, ValidationError, AttributeError) as fehler:
        return [], f"Ollama-Antwort fehlerhaft: {fehler}"
    if zeilen:
        return _ollama_vision_anreichern(_ollama_anreichern(zeilen, registry)), ""
    print("warnung: Ollama live leer/nicht erreichbar -- Fallback auf modelle.json", file=sys.stderr)
    try:
        return von_modelle_json(registry, "ollama"), ""
    except (ValidationError, TypeError, ValueError) as fehler:
        return [], f"modelle.json (ollama) fehlerhaft: {fehler}"


_ARTIFICIALANALYSIS_SCHLUESSEL_NAME = "ARTIFICIALANALYSIS_API_KEY"


class ArtificialAnalysisSchluesselFehler(RuntimeError):
    """Kein ARTIFICIALANALYSIS_API_KEY -- weder Umgebungsvariable noch zentrale `scripts\\.env`."""


def _artificialanalysis_schluessel() -> str:
    """Muster `chat_bruecke._openrouter_schluessel`: Umgebungsvariable vor der zentralen `.env`
    (Modul `schluessel`); AA hat keine Alt-Datei je Anbieter."""
    wert = schluessel.lese(_ARTIFICIALANALYSIS_SCHLUESSEL_NAME)
    if not wert:
        raise ArtificialAnalysisSchluesselFehler(
            r"AA-Schluessel fehlt: ARTIFICIALANALYSIS_API_KEY in scripts\.env setzen"
        )
    return wert


def _artificialanalysis_holen() -> str:
    headers = {"x-api-key": _artificialanalysis_schluessel()}
    with urllib.request.urlopen(
        urllib.request.Request(ARTIFICIALANALYSIS_URL, headers=headers), timeout=ZEITLIMIT_S
    ) as antwort:
        return antwort.read().decode("utf-8")


ARTIFICIALANALYSIS_HOLEN = _artificialanalysis_holen


def _beschaffe_aa() -> tuple[dict[str, dict], str]:
    """AA-Liste holen + parsen (Punkt 1) -- Fail-open wie die anderen Quellen: fehlender
    Schluessel oder Netzfehler liefert eine Fehlermeldung statt einer Exception."""
    try:
        daten = json.loads(ARTIFICIALANALYSIS_HOLEN())
    except ArtificialAnalysisSchluesselFehler as fehler:
        return {}, str(fehler)
    except (OSError, urllib.error.URLError, ValueError) as fehler:
        return {}, f"Artificial Analysis nicht erreichbar: {fehler}"
    return parse_artificialanalysis(daten), ""


def _registry() -> dict:
    """`scripts/modelle.json` -- leeres `{}`, wenn die Datei fehlt oder kaputt ist (Muster
    `chat._registry`, kein Crash ohne die Datei)."""
    try:
        with open(MODELLE_JSON_PFAD, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def beschaffe(anbieter: str, registry: dict) -> tuple[list[KatalogZeile], str]:
    """Zeilen fuer EINEN Anbieter -- Fail-open: eine kaputte Quelle liefert eine Fehlermeldung
    statt einer Exception. `claude` liest ausschliesslich aus `registry` (keine Netzquelle);
    `ollama` fragt zuerst LIVE `/api/tags` (Basisquelle, `_beschaffe_ollama()`) und faellt nur
    bei Nichterreichbarkeit auf `registry` zurueck."""
    if anbieter == "claude":
        try:
            return von_modelle_json(registry, "anthropic"), ""
        except (ValidationError, TypeError, ValueError) as fehler:
            return [], f"modelle.json (claude) fehlerhaft: {fehler}"
    if anbieter == "ollama":
        return _beschaffe_ollama(registry)
    if anbieter == "openrouter":
        return _beschaffe_openrouter()
    if anbieter == "requesty":
        return _beschaffe_requesty()
    raise ValueError(f"unbekannter Anbieter: {anbieter}")


# Spalten der Tabelle `modellkatalog` (Migration 0006 + 0008 `lokal` + 0009 `vision`) --
# Reihenfolge teilen sich `sql_upsert` (VALUES-Liste) und die INSERT-Spaltenliste, nie duplizieren.
_SPALTEN = ("modell_id", "hersteller", "herkunft", "anbieter", "lokal", "vision", "kontext_k",
            "eingabe_usd", "ausgabe_usd", "aa_index", "coding_index", "stand", "quelle")


def _wert_sql(wert) -> str:
    """Ein Python-Wert -> SQL-Literal fuer die VALUES-Liste (Muster `speicher.sql_literal`):
    `None` wird NULL, Text wird escaped, ein Datum bekommt einen `::date`-Cast, `bool` wird
    TRUE/FALSE (Python `str(True)` waere das ungueltige SQL-Bezeichner-Wort "True"), Zahlen
    direkt. `bool`-Check VOR der allgemeinen Zahl-Kappung, da `bool` in Python eine `int`-
    Unterklasse ist."""
    if wert is None:
        return "NULL"
    if isinstance(wert, bool):
        return "TRUE" if wert else "FALSE"
    if isinstance(wert, str):
        return speicher.sql_literal(wert)
    if isinstance(wert, date):
        return speicher.sql_literal(wert.isoformat()) + "::date"
    return str(wert)


def sql_upsert(zeilen: list[KatalogZeile]) -> str:
    """`INSERT ... ON CONFLICT (modell_id, anbieter) DO UPDATE` fuer alle Zeilen in einem
    Statement (Muster `speicher.sql_einfuegen`) -- kein DELETE (C15: verschwundene Modelle
    behalten ihren letzten Stand). `RETURNING (xmax = 0)` unterscheidet neu von aktualisiert
    (Postgres-Muster fuer Upsert-Zaehlung), `upsert_katalog` zaehlt daraus aus."""
    werte = ",\n  ".join(
        "(" + ", ".join(_wert_sql(getattr(z, spalte)) for spalte in _SPALTEN) + ")" for z in zeilen
    )
    setze = ", ".join(f"{s} = EXCLUDED.{s}" for s in _SPALTEN if s not in ("modell_id", "anbieter"))
    return (
        "WITH upsert AS (\n"
        f"  INSERT INTO modellkatalog ({', '.join(_SPALTEN)})\n  VALUES\n  {werte}\n"
        f"  ON CONFLICT (modell_id, anbieter) DO UPDATE SET {setze}\n"
        "  RETURNING (xmax = 0) AS neu\n)\n"
        "SELECT count(*) FILTER (WHERE neu), count(*) FILTER (WHERE NOT neu) FROM upsert;"
    )


def upsert_katalog(zeilen: list[KatalogZeile], laufer=speicher.psql) -> tuple[int, int]:
    """Upsert aller Zeilen in einem Statement -- liefert (neu, aktualisiert). Leere Liste macht
    keinen DB-Aufruf (kein leeres `VALUES ()`, das waere kaputtes SQL)."""
    if not zeilen:
        return 0, 0
    neu, aktualisiert = laufer(sql_upsert(zeilen)).split("|")
    return int(neu), int(aktualisiert)


def _sql_aa_update(treffer: list[tuple[str, str, dict]], heute: date) -> str:
    """`UPDATE ... FROM (VALUES ...)` fuer alle Treffer in einem Statement (Muster `sql_upsert`):
    setzt die vier Anreicherungs-Spalten + `aa_stand` je (modell_id, anbieter). Kein INSERT --
    AA ist keine Bezugsquelle (CONTRACTS.md C15 v2 Punkt 1), nur eine Anreicherung."""
    werte = ",\n  ".join(
        "(" + ", ".join([
            speicher.sql_literal(modell_id), speicher.sql_literal(anbieter),
            _wert_sql(w["aa_index"]), _wert_sql(w["coding_index"]),
            _wert_sql(w["agentic_index"]), _wert_sql(w["tempo_tok_s"]),
        ]) + ")" for modell_id, anbieter, w in treffer
    )
    return (
        "WITH v(modell_id, anbieter, aa_index, coding_index, agentic_index, tempo_tok_s) AS (\n"
        f"  VALUES\n  {werte}\n),\n"
        "upd AS (\n"
        "  UPDATE modellkatalog k SET aa_index = v.aa_index, coding_index = v.coding_index,\n"
        "    agentic_index = v.agentic_index, tempo_tok_s = v.tempo_tok_s, "
        f"aa_stand = {speicher.sql_literal(heute.isoformat())}::date\n"
        "  FROM v WHERE k.modell_id = v.modell_id AND k.anbieter = v.anbieter\n"
        "  RETURNING 1\n)\n"
        "SELECT count(*) FROM upd;"
    )


def aktualisiere_aa_indizes(zuordnung: dict[str, dict], heute: date,
                             laufer=speicher.psql) -> tuple[int, int]:
    """Liest alle Bestandszeilen (`modell_id`, `anbieter`) aus `modellkatalog`, matched sie ueber
    `aa_schluessel(modell_id)` gegen `zuordnung` (Ergebnis von `parse_artificialanalysis`) und
    schreibt Treffer per UPDATE. Liefert (gematcht, aktualisiert)."""
    if not zuordnung:
        return 0, 0
    bestand = laufer("SELECT modell_id, anbieter FROM modellkatalog;")
    token_zuordnung = _aa_token_zuordnung(zuordnung)
    kern_zuordnung = _aa_ableitung(zuordnung, aa_kern_schluessel)
    treffer = []
    for zeile in bestand.splitlines():
        if not zeile:
            continue
        modell_id, anbieter = zeile.split("|", 1)
        werte = zuordnung.get(aa_schluessel(modell_id))
        if werte is None:
            werte = token_zuordnung.get(aa_token_schluessel(modell_id))
        if werte is None:
            werte = kern_zuordnung.get(aa_kern_schluessel(modell_id) or None)
        if werte is not None:
            treffer.append((modell_id, anbieter, werte))
    if not treffer:
        return 0, 0
    aktualisiert = int(laufer(_sql_aa_update(treffer, heute)))
    return len(treffer), aktualisiert


def _aa_migrationshinweis(db_fehler: speicher.SpeicherFehler) -> str:
    """Verstaendliche Meldung statt Stacktrace, wenn Migration 0007 noch fehlt (UPDATE auf eine
    der drei neuen Spalten schlaegt mit 'column ... does not exist' fehl)."""
    text = str(db_fehler)
    if "does not exist" in text and any(s in text for s in ("agentic_index", "tempo_tok_s", "aa_stand")):
        return "Migration 0007 fehlt — infra/sitzungsbeleg-db/0007_aa_indizes.sql einspielen"
    return f"Upsert fehlgeschlagen: {db_fehler}"


def aktualisiere_aa(schreiben: bool, laufer=speicher.psql, heute: date | None = None) -> dict:
    """Ganzer AA-Schritt (C15 v2 Punkt 1): Liste holen + parsen, bei `schreiben=True` gegen den
    Bestand matchen und upserten. Liefert dasselbe Ergebnis-Shape wie ein Eintrag aus
    `aktualisiere()` (`anbieter='aa'`, `neu` bleibt immer 0 -- AA legt keine Zeilen an)."""
    zuordnung, fehler = _beschaffe_aa()
    gematcht = aktualisiert = 0
    if not fehler:
        gematcht = len(zuordnung)
        if schreiben:
            try:
                gematcht, aktualisiert = aktualisiere_aa_indizes(zuordnung, heute or date.today(), laufer)
            except speicher.SpeicherFehler as db_fehler:
                fehler = _aa_migrationshinweis(db_fehler)
    return {"anbieter": "aa", "anzahl": gematcht, "neu": 0, "aktualisiert": aktualisiert,
            "fehler": fehler or None}


def aktualisiere(anbieter_liste: list[str] | None = None, schreiben: bool = True,
                  laufer=speicher.psql) -> list[dict]:
    """Ein Durchlauf ueber die gewuenschten Anbieter (Default: alle vier, `QUELLEN_REIHENFOLGE`,
    plus die AA-Anreicherung als fester letzter Schritt -- CONTRACTS.md C15 v2 Punkt 1).
    Fail-open je Quelle (C15): eine tote Quelle liefert `fehler`, die anderen laufen unbeeinflusst
    weiter. `schreiben=False` (CLI ohne `--db`) ueberspringt den Upsert -- nur Beschaffung +
    Zaehlung, fuer einen Trockenlauf ohne DB. `anbieter_liste == ["aa"]` ruft NUR die AA-Stufe auf
    (einzeln aufrufbare Quelle)."""
    if anbieter_liste == ["aa"]:
        return [aktualisiere_aa(schreiben, laufer)]
    registry = _registry()
    ergebnisse = []
    for anbieter in anbieter_liste or QUELLEN_REIHENFOLGE:
        zeilen, fehler = beschaffe(anbieter, registry)
        neu = aktualisiert = 0
        if not fehler and schreiben:
            try:
                neu, aktualisiert = upsert_katalog(zeilen, laufer)
            except speicher.SpeicherFehler as db_fehler:
                fehler = f"Upsert fehlgeschlagen: {db_fehler}"
        ergebnisse.append({"anbieter": anbieter, "anzahl": len(zeilen), "neu": neu,
                            "aktualisiert": aktualisiert, "fehler": fehler or None})
    if anbieter_liste is None:
        ergebnisse.append(aktualisiere_aa(schreiben, laufer))
    return ergebnisse


def befehl_katalog_update(args) -> int:
    """CLI `katalog-update [--anbieter <name>] [--db]` (C15): eine Zeile Ausgabe je Quelle,
    stderr-Warnung bei toter Quelle (Fail-open) -- Exit bleibt 0, ein Abrufproblem einer Quelle
    soll den Aufrufer (Taskplaner) nicht rot melden, nur sichtbar machen."""
    ergebnisse = aktualisiere([args.anbieter] if args.anbieter else None, schreiben=args.db)
    for e in ergebnisse:
        if e["fehler"]:
            print(f"{e['anbieter']}: FEHLER - {e['fehler']}", file=sys.stderr)
        elif args.db:
            print(f"{e['anbieter']}: {e['neu']} neu, {e['aktualisiert']} aktualisiert")
        else:
            print(f"{e['anbieter']}: {e['anzahl']} Modelle geladen (--db fehlt, nicht gespeichert)")
    return 0
