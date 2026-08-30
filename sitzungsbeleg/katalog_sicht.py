"""C15 Modellkatalog (Paket L) -- Lese-/Aggregationslogik fuer GET /api/modellkatalog
(CONTRACTS.md C15 + "C15 v2 - Modellkatalog-Vollausbau").

Tabelle `modellkatalog` (Migration 0006, andere Baustelle dieser Welle) hat eine Zeile je
(modell_id, anbieter)-Paar; Migration 0007 legt zusaetzlich `agentic_index`, `tempo_tok_s`,
`aa_stand` an (Artificial-Analysis-Anreicherung, katalog.py). Dieses Modul liest ALLE Zeilen
mit einem einzigen simplen SELECT und aggregiert sie in Python zur Kontraktform -- keine
Aggregations-Fachlogik in SQL, damit sie ohne echte DB testbar bleibt (FakeLaufer-Konvention
wie speicher.py/web.py). `_zeilen_lesen()` liest tolerant: ist Migration 0007 noch nicht
eingespielt, meldet Postgres "column ... does not exist" -- dann wird EINMAL ohne die drei
neuen Spalten nachgelesen, statt die Seite mit 500 zu blockieren.

C15 v2 Punkt 3: die Aggregation gruppiert je `katalog.kurzname(modell_id)` (Teil nach dem
letzten '/', lowercase) statt je voller ID -- Anbieter praegen dasselbe Modell mit
unterschiedlichen Praefixen (`claude-fable-5` vs `anthropic/claude-fable-5`). Das API-`id`-Feld
behaelt trotzdem die Original-Schreibweise (Gross/Klein) des juengsten Roh-Eintrags.

`persona_wege` kommt separat aus scripts/modelle.json -- der Block existiert zum Zeitpunkt
dieser Welle noch nicht zwingend (die Bruecke schreibt ihn erst in einem Folgeschritt), darum
fail-soft: fehlt Datei oder Schluessel, liefert `persona_wege()` eine leere Struktur statt zu
werfen. Jeder Weg-Eintrag bekommt `ebene` mit Default 'offen' (C15 v2 Punkt 5) -- fehlend heisst
offen, ein Bestandseintrag muss dafuer nicht nachgepflegt werden. `lokal_liste()` baut die
LOKAL-Kachel aus dem BESTEHENDEN `modelle`-Bestand (typ=lokal, schon heute in modelle.json
gepflegt) und markiert das CURA-Modell mit `ebene: geschuetzt` + `primaer: true` als
`cura_primaer` -- Mockup-Konvention: dieses Modell steht als erstes in der Liste."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from . import speicher
from .katalog import aa_schluessel, anzeige_kurzform, ist_ollama_cloud, kanonische_id

MODELLE_PFAD = Path(__file__).resolve().parent.parent / "modelle.json"  # scripts/modelle.json

_SPALTEN_BASIS = ("modell_id", "hersteller", "herkunft", "anbieter", "kontext_k", "eingabe_usd",
                   "ausgabe_usd", "aa_index", "coding_index", "stand::text AS stand", "quelle")
_SPALTEN_LOKAL = ("lokal",)  # Migration 0008 (Befund 2026-08-30, Fix 2)
_SPALTEN_VISION = ("vision",)  # Migration 0009 (Entscheid 2026-08-30, Sterne-Rubrik v2)
_SPALTEN_AA = ("agentic_index", "tempo_tok_s", "aa_stand::text AS aa_stand")
_FEHLENDE_SPALTE_MARKER = "does not exist"  # Postgres-Fehlertext bei fehlender Spalte (0007/0008/0009)


def sql_alle_zeilen(mit_aa_spalten: bool = True, mit_lokal_spalte: bool = True,
                     mit_vision_spalte: bool = True) -> str:
    """Eine Zeile je (modell_id, anbieter) -- Aggregation passiert in Python (aggregiere()).
    `mit_aa_spalten=False` liest den Vor-0007-Spaltenstand, `mit_lokal_spalte=False` den
    Vor-0008-Stand, `mit_vision_spalte=False` den Vor-0009-Stand (alle drei Fallbacks in
    `_zeilen_lesen()`)."""
    spalten = (_SPALTEN_BASIS + (_SPALTEN_LOKAL if mit_lokal_spalte else ())
               + (_SPALTEN_VISION if mit_vision_spalte else ())
               + (_SPALTEN_AA if mit_aa_spalten else ()))
    return (
        "SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM (\n"
        f"  SELECT {', '.join(spalten)}\n"
        "  FROM modellkatalog ORDER BY modell_id, anbieter\n"
        ") t;"
    )


# Spaltenname -> welches sql_alle_zeilen()-Flag sie steuert (fuer die gezielte Fallback-Erkennung
# in `_zeilen_lesen()` unten) -- Postgres nennt in 'column "X" does not exist' immer die
# tatsaechlich fehlende Spalte, darum kann `_zeilen_lesen()` GENAU die betroffene Migration
# abschalten statt eine feste Reihenfolge durchzuprobieren (die bei drei unabhaengigen optionalen
# Migrationen 0007/0008/0009 sonst je nach Kombination bis zu 8 Versuche braeuchte).
_SPALTE_ZU_FLAG = {"vision": "mit_vision_spalte", "lokal": "mit_lokal_spalte",
                    "agentic_index": "mit_aa_spalten", "tempo_tok_s": "mit_aa_spalten",
                    "aa_stand": "mit_aa_spalten"}
_MAX_VERSUCHE = len(set(_SPALTE_ZU_FLAG.values())) + 1  # jedes Flag hoechstens einmal abschalten


def _zeilen_lesen(lauf) -> list[dict]:
    """Liest alle Katalogzeilen; faellt auf aeltere Spaltenstaende zurueck, wenn Migration
    `0007_aa_indizes.sql`/`0008_katalog_istlokal.sql`/`0009_katalog_vision.sql` noch nicht
    eingespielt ist (C15 v2 Punkt 3) -- Postgres meldet eine fehlende Spalte immer mit 'column
    "X" does not exist' im Fehlertext; `_SPALTE_ZU_FLAG` schaltet GENAU das betroffene Flag ab und
    liest erneut. Jeder andere Fehler (unbekannte Spalte, Verbindung, Zeitlimit) laeuft
    unveraendert weiter nach oben durch."""
    flags = {"mit_aa_spalten": True, "mit_lokal_spalte": True, "mit_vision_spalte": True}
    ausgabe = ""
    for _ in range(_MAX_VERSUCHE):
        try:
            ausgabe = lauf(sql_alle_zeilen(**flags))
            break
        except speicher.SpeicherFehler as fehler:
            text = str(fehler)
            treffer = next((flag for spalte, flag in _SPALTE_ZU_FLAG.items()
                             if _FEHLENDE_SPALTE_MARKER in text and spalte in text and flags[flag]), None)
            if treffer is None:
                raise
            flags[treffer] = False
    return json.loads(ausgabe) if ausgabe.strip() else []


def _zahl(x):
    return float(x) if x is not None else None


def _guenstigste_zeile(zeilen: list[dict]) -> dict:
    """Anbieter mit dem niedrigsten Ausgabepreis gewinnt (Kosten-Treiber, Runden 8-11:
    Preisspalten zeigen den guenstigsten Anbieterpreis). Preis 0 (`:free`-Bezugsvarianten,
    ratenlimitierte Gratisstufen) zaehlt dabei NACH echten Preisen -- sonst zeigte jedes
    Modell mit Free-Variante "0,0" als Normalpreis. Fehlt ueberall ein Ausgabepreis (reine
    Lokal-Modelle ohne Tokenpreis), entscheidet der Eingabepreis; fehlen beide ueberall,
    gewinnt die alphabetisch erste Anbieterzeile als neutrale Referenz."""
    def schluessel(z):
        ausgabe, eingabe = z.get("ausgabe_usd"), z.get("eingabe_usd")
        return (ausgabe is None, not ausgabe, ausgabe if ausgabe is not None else 0,
                eingabe is None, not eingabe, eingabe if eingabe is not None else 0, z["anbieter"])
    return min(zeilen, key=schluessel)


def _dedupe_anbieter(gruppe: list[dict]) -> list[dict]:
    """Bezugswege-Vereinigung je Kurzname (C15 v2 Punkt 3): je Anbietername GENAU eine Zeile --
    kommen mehrere Roh-IDs desselben Kurznamens ueber denselben Anbieter herein (z. B.
    Gross-/Kleinschreibungs-Drift beim Upsert), gewinnt der guenstigste Ausgabepreis."""
    je_anbieter: dict[str, list[dict]] = {}
    for z in gruppe:
        je_anbieter.setdefault(z["anbieter"], []).append(z)
    return [_guenstigste_zeile(je_anbieter[name]) for name in sorted(je_anbieter)]


def _stand_je_anbieter(zeilen: list[dict]) -> dict[str, str]:
    """Juengstes `stand`-Datum je Anbieter UEBER DEN GESAMTEN KATALOG (Kopfzeilen-Caption
    "Stand OpenRouter ... Requesty ... Anthropic ... Ollama ...", nicht je Modell)."""
    stand: dict[str, str] = {}
    for z in zeilen:
        wert = z.get("stand")
        if wert and (z["anbieter"] not in stand or wert > stand[z["anbieter"]]):
            stand[z["anbieter"]] = wert
    return stand


def _juengster_aa_stand(zeilen: list[dict]) -> str | None:
    """Juengstes `aa_stand` ueber ALLE Rohzeilen (C15 v2 Punkt 3c) -- eigener Schluessel
    "artificial_analysis" im `stand`-Block, None wenn AA fuer diese Zeilen nie gelaufen ist."""
    staende = [z["aa_stand"] for z in zeilen if z.get("aa_stand")]
    return max(staende) if staende else None


def _haeufigster(gruppe: list[dict], feld: str):
    """Haeufigster NICHT-leerer Wert eines Feldes in der Gruppe (C15 v2 Punkt 3: hersteller/
    herkunft) -- bei Gleichstand gewinnt der zuerst aufgetretene Wert (Counter-Reihenfolge)."""
    werte = [z.get(feld) for z in gruppe if z.get(feld)]
    return Counter(werte).most_common(1)[0][0] if werte else None


def _erster_wert(gruppe: list[dict], feld: str):
    """Erster nicht-NULL-Wert der (nach Anbieter sortierten) Gruppe -- C15 v2 Punkt 3 fuer
    aa_index/coding_index/agentic_index/tempo_tok_s (ersetzt die v1-Regel max())."""
    for z in gruppe:
        wert = z.get(feld)
        if wert is not None:
            return wert
    return None


# ---- Modell-Familie + Legacy-Erkennung (Entscheid 2026-08-30 A/B, praezisiert Abnahme
# 2026-08-30 A) -- Sterne gelten NUR NOCH fuer die neueste Version je Familie, s.
# _mit_nachfolger()/_mit_sternen_und_status() unten.

_ZIFFER_TOKEN_RE = re.compile(r"^\d+$")
# Baugroessen (Ziffer+Parameter-Einheit wie `20b`/`120b`/`675b`/`4t`) UND aktive-Parameter-Tags
# (`a95b`, `a3b`, MoE-Modelle) -- Task-Vorgabe Abnahme 2026-08-30 A: "weder Version noch
# Familie". NUR die realen Groessen-Einheiten b/k/m/t (Milliarde/Tausend/Million/Billion
# Parameter) zaehlen als Einheit -- ein generisches `[a-z]+` traf faelschlich auch echte
# Namensteile wie `4o` (GPT-4o) und riss sie aus der Familie (Live-Katalog-Befund: dadurch
# geriet `gpt-4o-2024-11-20` in dieselbe Familie wie `gpt-5.6-*`).
_GROESSE_RE = re.compile(r"^\d+[bkmt]$")
_AKTIV_GROESSE_RE = re.compile(r"^a\d+[bkmt]$")
# NUR das Trillionen-Tag (`4t`, `1t`) zieht die vorangehende Ziffer als seinen Dezimalbruch mit --
# ein Größentag wie `24b`/`20b` steht fuer sich (keine Dezimalstelle davor gehoert dazu, sonst
# frisst er echte Versions-Nachkommastellen wie das `2` in `mistral-small-3.2-24b-instruct`).
_GROESSE_TRILLION_RE = re.compile(r"^\d+t$")
# Schnappschuss-Datum als drei Bindestrich-Ziffern-Token (`2024-11-20`, `2025-07-28`) -- ein Jahr
# (2000-2099) als Versions-Hauptglied wuerde jede echte Version (5, 5.6, ...) hoffnungslos
# ueberstrahlen (Live-Katalog-Befund: `qwen-plus-2025-07-28` haette sich sonst faelschlich vor
# `qwen3.8` als "neueste" geschoben). Analog zum 8-stelligen YYYYMMDD-Suffix in
# `katalog.aa_token_schluessel`, hier aber noch NICHT verklebt.
_JAHR_RE = re.compile(r"^20\d\d$")
# Ein alleinstehendes 4-stelliges Ziffern-Token ist im gesamten Live-Katalog IMMER ein Datums-/
# Build-Stempel (MMDD wie `0528`/`0731`, YYMM wie `2407`/`2603` -- Mistral versioniert so, oder
# YYYY), NIE eine echte Hauptversion (Stichprobe ueber alle 1044 Katalog-IDs: kein Gegenbeispiel).
# Ohne diese Regel haette z. B. `mistral-small-2603` mit Version 2603 die ganze `mistral`-Familie
# vor `mistral-large-3`/`mistral-small-3.2` als "neueste" ausgestochen.
_DATUM_4_STELLIG_RE = re.compile(r"^\d{4}$")
# Glatt verklebtes Buchstaben-Ziffern-Paar (`qwen3`->qwen+3, `v3`->v+3, `gemma4`->gemma+4).
_ALPHA_ZIFFER_RE = re.compile(r"^([a-z]+)(\d+)$")
# Reine Versions-/Revisions-Marker-Buchstaben: der Praefix faellt komplett weg (nicht Teil der
# Familie), NUR die Ziffer bleibt -- `deepseek-v3.2`/`deepseek-r1` gehoeren zur Familie `deepseek`,
# nicht zu `deepseek-v`/`deepseek-r` (sonst waere `deepseek-r1` nie Legacy zu `deepseek-v4-pro`).
_VERSIONS_MARKER_BUCHSTABEN = frozenset({"v", "r"})
# Reseller ohne eigene Modelle, glueht als Bindestrich-Praefix im letzten Pfadsegment OHNE eigenen
# Slash (`parasail/parasail-deepseek-v4-flash`) -- vor der Familienbildung entfernen wie ein
# Slash-Praefix (Task-Vorgabe, Beispiel `parasail-`; `sference/...` faellt schon durch den
# bestehenden Slash-Schnitt in `aa_schluessel`/`kurzname` weg).
_ANBIETER_PRAEFIX_OHNE_SLASH = frozenset({"parasail"})

# Stufen-Woerter (Abnahme 2026-08-30 A): KEIN Familienmerkmal, werden fuer die Familienbildung
# entfernt. Produkt-Varianten (`vl`, `coder`, `oss`, `vision`, `audio`, `embed`, `guard`,
# `safeguard`, `terminus`, `multi`, `agent`, ...) stehen NICHT in dieser Liste und bleiben Teil
# der Familie (`gpt-oss` bleibt eine eigene Familie neben `gpt`).
_STUFE_WOERTER = frozenset({
    "mini", "nano", "micro", "lite", "flash", "pro", "max", "ultra", "super", "plus",
    "turbo", "small", "medium", "large", "sol", "terra", "luna", "opus", "sonnet", "haiku",
    "fable", "mythos",
})  # Stufen gehoeren ZUR Familie (Maintainer 2026-08-30 final): `claude-haiku` ist eigene Linie.

_MODIFIKATOR_WOERTER = frozenset({
    "exp", "preview", "beta", "chat", "instruct", "it", "thinking", "reasoning", "non", "fast",
})  # reine Modifikatoren -- fallen aus der Familie ("non" = Haelfte von "non-reasoning")


def _tokens(modell_id: str) -> list[str]:
    """Anzeige-ID (schon deduped, `_anzeige_id()`) auf `aa_schluessel`-Tokens -- gleiche
    Normalisierung (lowercase, Trenner vereinheitlicht) wie die Katalog-Gruppierung. Ein
    Reseller-Praefix ohne eigenen Slash (`_ANBIETER_PRAEFIX_OHNE_SLASH`) faellt zusaetzlich weg."""
    token = [t for t in aa_schluessel(modell_id).split("-") if t]
    if len(token) > 1 and token[0] in _ANBIETER_PRAEFIX_OHNE_SLASH:
        return token[1:]
    return token


def _ist_datumslauf(token: list[str], i: int) -> bool:
    """Jahr (2000-2099) + Monat (1-12) + Tag (1-31) in drei aufeinanderfolgenden Ziffern-Token
    ab Position `i` (`2024-11-20`) -- ein Schnappschuss-Datum, keine Version (s. `_JAHR_RE`)."""
    if i + 2 >= len(token):
        return False
    jahr, monat, tag = token[i], token[i + 1], token[i + 2]
    if not (_JAHR_RE.match(jahr) and monat.isdigit() and tag.isdigit()):
        return False
    return 1 <= int(monat) <= 12 and 1 <= int(tag) <= 31


def _ohne_groessen_tags(token: list[str]) -> list[str]:
    """Entfernt Baugroessen-Token (Abnahme 2026-08-30 A): `20b`/`120b`/`675b`/`4t`
    (Ziffer+Einheit), `a95b`/`a3b` (aktive Parameter, MoE), die reine Ziffer direkt VOR einem
    Trillionen-Tag (`2`,`4t` -- "2,4 Billionen Parameter" ist EINE Groessenangabe, keine zweite
    Versionsstelle) sowie Datums-/Build-Stempel: ein Bindestrich-Datumslauf (`_ist_datumslauf`,
    `2024-11-20`) oder ein alleinstehendes 4-stelliges Ziffern-Token (`_DATUM_4_STELLIG_RE`,
    `0528`/`2603`). Weder Version noch Familie (Task-Vorgabe)."""
    ergebnis = []
    i = 0
    while i < len(token):
        if _ist_datumslauf(token, i):
            i += 3
            continue
        t = token[i]
        folge_ist_trillion = i + 1 < len(token) and bool(_GROESSE_TRILLION_RE.match(token[i + 1]))
        if (_GROESSE_RE.match(t) or _AKTIV_GROESSE_RE.match(t) or _DATUM_4_STELLIG_RE.match(t)
                or (_ZIFFER_TOKEN_RE.match(t) and folge_ist_trillion)):
            i += 1
            continue
        ergebnis.append(t)
        i += 1
    return ergebnis


def _aufgeteilte_tokens(modell_id: str) -> list[tuple[str | None, str | None]]:
    """Jeder Token (nach `_ohne_groessen_tags`) als (Familien-Teil, Versions-Ziffer): eine reine
    Ziffer liefert nur die Versions-Ziffer, ein glatt verklebtes Buchstaben-Ziffern-Paar
    (`_ALPHA_ZIFFER_RE`) trennt beide -- der Buchstaben-Teil faellt weg, wenn er ein reiner
    Versions-Marker ist (`_VERSIONS_MARKER_BUCHSTABEN`), sonst bleibt er ein Familien-Token.
    Alles andere (kein Ziffern-Anteil) bleibt unveraendert ein reiner Familien-Token."""
    ergebnis: list[tuple[str | None, str | None]] = []
    for t in _ohne_groessen_tags(_tokens(modell_id)):
        if _ZIFFER_TOKEN_RE.match(t):
            ergebnis.append((None, t))
            continue
        treffer = _ALPHA_ZIFFER_RE.match(t)
        if not treffer:
            ergebnis.append((t, None))
            continue
        praefix, ziffer = treffer.groups()
        ergebnis.append((None if praefix in _VERSIONS_MARKER_BUCHSTABEN else praefix, ziffer))
    return ergebnis


def familie(modell_id: str) -> str:
    """Modell-Familie = Hersteller + Produktlinie + Stufe (Entscheid 2026-08-30 final):
    Versionsziffern, Baugroessen (`_ohne_groessen_tags`) und Modifikatoren (`_MODIFIKATOR_WOERTER`)
    fallen weg; Stufen-Woerter (`_STUFE_WOERTER`) und Produkt-Varianten (`vl`/`coder`/`oss`) bleiben
    und bilden je eine EIGENE Familie. `claude-haiku-4-5` ist darum aktuell (eigene Familie
    `claude-haiku`, kein `claude-haiku-5`), `gpt-5.4-mini` aktuell (eigene Familie `gpt-mini`,
    kein `gpt-5.6-mini`), `gpt-5.5` aktuell in der stufenlosen Familie `gpt` -- getrennt von den
    eigenen Familien `gpt-sol`/`gpt-terra`/`gpt-luna`. Faellt der Kern komplett leer aus (reine
    Ziffern-/Stufen-ID), bleibt der volle Rohtoken-Satz stehen -- nie eine leere Familie."""
    token = _tokens(modell_id)
    kern = [teil for teil, _ in _aufgeteilte_tokens(modell_id) if teil is not None and teil not in _MODIFIKATOR_WOERTER]
    return "-".join(kern or token)


# Ziffer(n) + EIN Marker-Buchstabe verklebt (`5v`, glm-5v = Vision-Variante) -- Spiegelbild von
# `_ALPHA_ZIFFER_RE`/`_VERSIONS_MARKER_BUCHSTABEN` (dort Buchstabe-vor-Ziffer wie `v3`, hier
# Ziffer-vor-Buchstabe): NUR fuer `produktlinie()`, `familie()`/`version()` bleiben unveraendert
# (Entscheid 2026-08-30 final, s. `familie()`-Docstring).
_ZIFFER_MARKER_SUFFIX_RE = re.compile(r"^\d+([a-z]+)$")


def produktlinie(modell_id: str) -> str:
    """Produktlinie = `familie()` OHNE Stufen-Woerter (Festlegung 2026-08-30, generationen.json)
    -- die kuratierten Generations-Schwellen gelten je Linie, nicht je Stufe (`gpt-5.4-mini` und
    `gpt-5.4-nano` teilen die Linie `gpt`, nicht die je eigene Familie `gpt-mini`/`gpt-nano`). Ein
    verklebter Ziffer+Marker-Buchstabe-Rest wie `5v` (`glm-5v-turbo`) wird auf den Marker-
    Buchstaben verkuerzt (`_VERSIONS_MARKER_BUCHSTABEN`) -- die Ziffer davor ist dort eine
    Versionsangabe, kein Linien-Merkmal (Ziel `glm-v`, die abgeloeste Vision-Linie); ein Rest ohne
    Marker-Buchstaben wie `4o` (GPT-4o, kein Versions-Marker) bleibt unveraendert stehen (`gpt-4o`
    bleibt eigene Linie). Faellt der Kern komplett leer aus, bleibt `familie()` stehen."""
    kern = []
    for token in familie(modell_id).split("-"):
        if token in _STUFE_WOERTER:
            continue
        treffer = _ZIFFER_MARKER_SUFFIX_RE.match(token)
        if treffer and treffer.group(1) in _VERSIONS_MARKER_BUCHSTABEN:
            kern.append(treffer.group(1))
        else:
            kern.append(token)
    return "-".join(kern) if kern else familie(modell_id)


def version(modell_id: str) -> tuple:
    """Versions-Tupel aus den Versions-Ziffern (`_aufgeteilte_tokens`, Abnahme 2026-08-30 A) --
    z. B. `qwen3.8` -> `(3, 0.8)`, `deepseek-v3.2` -> `(3, 0.2)`, `deepseek-r1` -> `(1,)`,
    `gemma4` -> `(4,)`, `claude-opus-4-8` -> `(4, 0.8)`. Tupel-Vergleich liefert die geforderte
    Ordnung (erstes Glied ganzzahlig, alle weiteren als Dezimalbruch, `_versions_glied`: Anbieter
    meinen Nachkommastellen dezimal, `grok-4.20` = 4.2 < `grok-4.6`). Kein Ziffern-Token -> leeres
    Tupel, gilt als aelteste Version der Familie."""
    ziffern = [z for _, z in _aufgeteilte_tokens(modell_id) if z is not None]
    return tuple(_versions_glied(z, i) for i, z in enumerate(ziffern))


def _versions_glied(token: str, position: int) -> float:
    """Erstes Glied = Hauptversion (ganzzahlig); alle weiteren als Dezimalbruch (`0.<token>`),
    weil Anbieter Nachkommastellen dezimal meinen: `grok-4.20` = 4.2 < `grok-4.6` (AA 38 vs 61,
    Fund Abnahme 2026-08-30). Ganzzahlig gelesen waere 20 > 6 -- falscher Nachfolger."""
    return int(token) if position == 0 else float("0." + token)


def neueste_je_familie(ids: list[str]) -> set[str]:
    """Menge der IDs, die je Modell-Familie (`familie()`) die neueste Version sind (Entscheid
    2026-08-30 B, praezisiert durch Entscheid 2026-08-30 final) -- ALLE IDs mit dem hoechsten
    `version()`-Tupel der Familie, nicht nur eine: da Baugroessen (`_ohne_groessen_tags`) keine
    eigene Familie erzwingen, koennen mehrere IDs derselben Familie tatsaechlich gleichauf liegen
    (`gpt-oss-20b`/`gpt-oss-120b`) -- echter Gleichstand bleibt Gleichstand, kein erfundener
    Namens-Tiebreak mehr noetig."""
    je_familie: dict[str, list[str]] = {}
    for i in ids:
        je_familie.setdefault(familie(i), []).append(i)
    ergebnis: set[str] = set()
    for gruppe in je_familie.values():
        hoechste = max(version(i) for i in gruppe)
        ergebnis.update(i for i in gruppe if version(i) == hoechste)
    return ergebnis


def _nachfolger_je_id(ids: list[str]) -> dict[str, str | None]:
    """Nachfolger-ID je Modell-ID (Entscheid 2026-08-30 B): die neueste Version derselben
    Familie (`familie()`), `None` fuer JEDE neueste Version selbst -- bei echtem Gleichstand
    (mehrere IDs auf dem hoechsten `version()`-Tupel, s. `neueste_je_familie()`) bleiben ALLE
    davon `None`; aeltere Versionen zeigen deterministisch auf die alphabetisch erste davon."""
    neueste = neueste_je_familie(ids)
    je_familie: dict[str, list[str]] = {}
    for i in ids:
        je_familie.setdefault(familie(i), []).append(i)
    ergebnis: dict[str, str | None] = {}
    for gruppe in je_familie.values():
        verweis = min(i for i in gruppe if i in neueste)
        ergebnis.update({i: None if i in neueste else verweis for i in gruppe})
    return ergebnis


def _mit_nachfolger(modelle: list[dict]) -> None:
    """Traegt additiv `nachfolger` in ALLE `modelle`-Eintraege ein (Entscheid 2026-08-30 B) --
    ID der neuesten Version derselben Familie, `None` bei der neuesten Version selbst. Mutiert
    in-place wie `_mit_sternen_und_status()`, muss VOR ihr laufen (sie liest `nachfolger`)."""
    nachfolger = _nachfolger_je_id([m["id"] for m in modelle])
    for m in modelle:
        m["nachfolger"] = nachfolger[m["id"]]


# ---- Kuratierte Generations-Schwellen (Festlegung 2026-08-30, `generationen.json`) -- haben
# VORRANG vor der automatischen `familie()`-Versionsregel oben: eine Produktlinie MIT Eintrag in
# `linien` wird ausschliesslich ueber die Schwelle entschieden (nur `ausnahmen_aktuell`/
# `explizit_legacy` schlagen sie), eine Linie OHNE Eintrag bleibt bei der automatischen Regel.

GENERATIONEN_PFAD = Path(__file__).resolve().parent / "generationen.json"


def _lies_generationen() -> dict:
    """`generationen.json` (kuratierte Generations-Schwellen je Produktlinie) -- fail-soft leeres
    Dict bei fehlender/kaputter Datei (Muster `_lies_registry`): ohne Datei gilt fuer jede Linie
    unveraendert die automatische Versionsregel."""
    if not GENERATIONEN_PFAD.exists():
        return {}
    try:
        with open(GENERATIONEN_PFAD, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _schwelle_ge(version_tupel: tuple, schwelle: float) -> bool:
    """`version_tupel >= schwelle`: die Schwelle (z. B. `5.6`) wird wie `version()` selbst in
    (Hauptversion, Dezimalbruch-Nachkommaanteil) zerlegt (`_versions_glied`-Konvention), damit
    `(5, 0.4) < 5.6` und `(5, 0.6) >= 5.6` stimmen -- ein direkter Float-Vergleich der Hauptversion
    allein wuerde `5.4 < 5.6` korrekt, aber `(5, 0.6)` als Tupel nicht mit `5.6` vergleichen
    koennen."""
    haupt = int(schwelle)
    dezimal = round(schwelle - haupt, 10)
    vergleich = (haupt, dezimal) if dezimal else (haupt,)
    return version_tupel >= vergleich


def generation_status(modell_id: str, version_tupel: tuple, linien: dict,
                       ausnahmen_aktuell, explizit_legacy: dict) -> tuple[str | None, str | None]:
    """Kuratierte Generations-Regel (Festlegung 2026-08-30) -- reine Funktion, testbar ohne
    Katalog. Rueckgabe `(status, nachfolger)`: `status=None` heisst "keine kuratierte Regel
    greift", der Aufrufer faellt auf die automatische `familie()`-Regel zurueck. Reihenfolge:
    (a) `explizit_legacy` schlaegt alles, Nachfolger direkt aus der Tabelle; (b)
    `ausnahmen_aktuell` schlaegt die Schwelle -- immer aktuell; (c) Produktlinie hat eine Schwelle:
    Version darunter -> legacy (Nachfolger traegt der Aufrufer score-basiert nach, hier `None`),
    Version am/ueber der Schwelle -> aktuell."""
    if modell_id in explizit_legacy:
        return "legacy", explizit_legacy[modell_id]
    if modell_id in ausnahmen_aktuell:
        return "aktuell", None
    schwelle = linien.get(produktlinie(modell_id))
    if schwelle is None:
        return None, None
    if _schwelle_ge(version_tupel, schwelle):
        return "aktuell", None
    return "legacy", None


def _ist_aktuell_nach_kuratierung(status: str | None, baseline_nachfolger: str | None) -> bool:
    """Ob ein Modell nach Kuratierung+Automatik-Rueckfall final AKTUELL ist -- Basis fuer
    `_bester_score_je_linie()` (nur unter aktuellen Modellen gesucht)."""
    if status is not None:
        return status == "aktuell"
    return baseline_nachfolger is None


def _bester_score_je_linie(modelle: list[dict], aktuelle_ids: set[str]) -> dict[str, str]:
    """ID des bestbewerteten AKTUELLEN Modells je Produktlinie (Festlegung 2026-08-30 Punkt c)
    -- Score wie `_score()`; Modelle ohne Score zaehlen nicht als Kandidat. Keine bewertete
    aktuelle ID in der Linie -> kein Eintrag (der Aufrufer behaelt dann `nachfolger=None`, lieber
    kein Nachfolger als ein erfundener)."""
    bester: dict[str, tuple[float, str]] = {}
    for m in modelle:
        if m["id"] not in aktuelle_ids:
            continue
        score = _score(m["aa_index"], m["coding_index"])
        if score is None:
            continue
        linie = produktlinie(m["id"])
        if linie not in bester or score > bester[linie][0]:
            bester[linie] = (score, m["id"])
    return {linie: modell_id for linie, (_, modell_id) in bester.items()}


def _mit_kuratierten_generationen(modelle: list[dict], generationen: dict) -> None:
    """Ueberschreibt additiv `nachfolger` UND den internen `_generation_legacy`-Marker nach der
    kuratierten Generations-Regel (Festlegung 2026-08-30) -- Vorrang vor `_mit_nachfolger()`,
    muss darum NACH ihr laufen: ein Modell OHNE kuratierte Regel (`generation_status()` liefert
    `status=None`) behaelt seinen automatischen Nachfolger unveraendert (kein Marker gesetzt,
    `_ist_legacy_status()` faellt dann auf die reine `nachfolger`-Pruefung zurueck). Ein
    kuratiert-legacy Modell OHNE bewerteten Nachfolger in der eigenen Linie (Punkt c, keine
    aktuelle ID mit Score) behaelt `nachfolger=None` ("sonst null") -- der Marker haelt den
    Legacy-Status trotzdem fest, s. `_ist_legacy_status()`. Leere `generationen` (Datei fehlt)
    aendert nichts."""
    linien = generationen.get("linien") or {}
    ausnahmen = set(generationen.get("ausnahmen_aktuell") or [])
    explizit = generationen.get("explizit_legacy") or {}
    if not (linien or ausnahmen or explizit):
        return
    kuratiert = {m["id"]: generation_status(m["id"], version(m["id"]), linien, ausnahmen, explizit)
                 for m in modelle}
    aktuelle_ids = {m["id"] for m in modelle
                    if _ist_aktuell_nach_kuratierung(kuratiert[m["id"]][0], m["nachfolger"])}
    bester_je_linie = _bester_score_je_linie(modelle, aktuelle_ids)
    for m in modelle:
        status, nachfolger = kuratiert[m["id"]]
        if status == "aktuell":
            m["nachfolger"] = None
            m["_generation_legacy"] = False
        elif status == "legacy":
            m["nachfolger"] = nachfolger or bester_je_linie.get(produktlinie(m["id"]))
            m["_generation_legacy"] = True


# ---- Automatische Sterne v2 (Entscheid 2026-08-30 Nachtrag 6, ersetzt die Quintil-Sterne aus
# Nachtrag 2/4 vollstaendig) -- halbe Sterne 0,5..5,0 aus Score = Mittel(aa_index, coding_index),
# relativ zum besten Score unter den AKTUELLEN Modellen (keine Kontext-Boni, kein Agentic-Index,
# keine erzwungene Hersteller-Stufung mehr). Regeln: docs/modelle.md.

_BODEN_SCORE = 45.0  # unterhalb: 0,5..3,0 linear; ab hier: 3,0..5,0 linear bis zum besten Score


def _score(aa_index, coding_index) -> float | None:
    """Score = Mittel aus AA-Intelligenz- und Coding-Index -- fehlt einer der beiden, zaehlt nur
    der andere; fehlen beide, ist der Score nicht berechenbar (`None`, Entscheid 2026-08-30
    Nachtrag 6)."""
    if aa_index is None and coding_index is None:
        return None
    if aa_index is None:
        return float(coding_index)
    if coding_index is None:
        return float(aa_index)
    return (aa_index + coding_index) / 2


def _ist_legacy_status(m: dict) -> bool:
    """Legacy-Entscheidung fuer die Sterne-/Status-Vergabe -- `_generation_legacy` (von
    `_mit_kuratierten_generationen()` additiv gesetzt, Festlegung 2026-08-30) hat Vorrang,
    sonst gilt weiter die reine `nachfolger`-Pruefung (Entscheid 2026-08-30 Nachtrag 6: `!=
    null` -> legacy). Noetig, weil ein kuratiert-legacy Modell OHNE bewerteten Nachfolger in der
    eigenen Linie `nachfolger=None` behaelt ('sonst null', Festlegung 2026-08-30 Punkt c) --
    ohne dieses Flag waere es faelschlich ueber `nachfolger is None` als aktuell erkannt."""
    if "_generation_legacy" in m:
        return m["_generation_legacy"]
    return m.get("nachfolger") is not None


def _bester_score(modelle: list[dict]) -> float | None:
    """Hoechster Score unter allen AKTUELLEN Modellen (nicht `_ist_legacy_status()`) -- Basis des
    oberen Formel-Asts (Score >= Boden). `None`, wenn kein aktuelles Modell einen Score hat."""
    werte = [m["sterne"]["score"] for m in modelle
             if not _ist_legacy_status(m) and m["sterne"]["score"] is not None]
    return max(werte) if werte else None


def _runde_halbstern(x: float) -> float:
    """Kaufmaennisch auf 0,5-Schritte runden (0,5 immer aufrunden)."""
    return math.floor(x * 2 + 0.5) / 2


def _sterne_aus_score(score: float | None, best: float | None) -> float | None:
    """Sterne-Formel (Entscheid 2026-08-30 Nachtrag 6): Boden 45; darunter linear 0,5..3,0
    (`0,5 + 2,5*Score/45`), darueber linear 3,0..5,0 bis zum besten AKTUELLEN Score
    (`3 + 2*(Score-Boden)/(best-Boden)`). `best <= Boden` (kein aktuelles Modell ueber dem Boden)
    faengt die Null-Division ab -- der einzige Score am/ueber dem Boden ist dann `best` selbst,
    Ergebnis 3,0. Auf 0,5..5,0 geklemmt."""
    if score is None:
        return None
    if score >= _BODEN_SCORE:
        if best is None or best <= _BODEN_SCORE:
            roh = 3.0
        else:
            roh = 3.0 + 2.0 * (score - _BODEN_SCORE) / (best - _BODEN_SCORE)
    else:
        roh = 0.5 + 2.5 * score / _BODEN_SCORE
    return max(0.5, min(5.0, _runde_halbstern(roh)))


def _mit_vision_deckel(sterne: float | None, vision: bool | None) -> float | None:
    """`vision == False` deckelt bei 4,0 (kein Bildlesen = nicht voll einsetzfaehig, z. B.
    Rechnungen lesen) -- `vision is None` (unbekannt) bleibt ohne Deckel (Entscheid 2026-08-30
    Nachtrag 6)."""
    if sterne is None or vision is not False:
        return sterne
    return min(sterne, 4.0)


def _manuelle_je_schluessel(registry: dict | None) -> dict[str, dict]:
    """`aa_schluessel(name) -> Registry-Eintrag` je Modell aus `scripts/modelle.json` --
    dieselbe Schluesselform wie die Katalog-Gruppierung (`aggregiere()`), darum matcht ein
    Nachschlagen mit dem Gruppenschluessel direkt, ohne erneute Namensnormalisierung."""
    bestand = (registry or {}).get("modelle", {})
    if not isinstance(bestand, dict):
        return {}
    return {aa_schluessel(name): daten for name, daten in bestand.items() if isinstance(daten, dict)}


def _manuelle_test_sterne(gruppe: list[dict], je_schluessel: dict[str, dict]) -> dict | None:
    """Manuelle Test-Sterne aus `modelle.json` (coding/reasoning/gesamt) NUR als Tooltip-Zusatz
    ('eigener Test: ...') -- Entscheid 2026-08-30: nicht mehr Basis der Katalog-Bewertung.
    `None`, wenn kein Bezugsweg der Gruppe einen Registry-Eintrag MIT mindestens einer der drei
    Bewertungen hat."""
    for z in gruppe:
        eintrag = je_schluessel.get(aa_schluessel(z["modell_id"]))
        if eintrag and any(eintrag.get(f) is not None for f in ("coding", "reasoning", "gesamt")):
            return {"coding": eintrag.get("coding"), "reasoning": eintrag.get("reasoning"),
                    "gesamt": eintrag.get("gesamt"), "kommentar": eintrag.get("kommentar") or ""}
    return None


def _roh_lokal(z: dict) -> bool:
    """Lokal-Status EINER Ollama-Rohzeile (Befund 2026-08-30, Fix 2): bevorzugt die
    per-Zeile `lokal`-Spalte (Migration 0008, an der ROHEN modell_id bei der Beschaffung
    gesetzt, s. `katalog.KatalogZeile.lokal`) -- fehlt sie (DB vor 0008), Rueckfall auf
    `katalog.ist_ollama_cloud(z['modell_id'])`. NIE auf einer schon kanonisierten ID pruefen
    (die haette ein Cloud-Suffix wie `-cloud` schon verloren)."""
    if "lokal" in z:
        return bool(z["lokal"])
    return not ist_ollama_cloud(z["modell_id"])


def _ist_lokal(gruppe: list[dict]) -> bool:
    """`lokal`-Flag (C15 v2 Punkt 3): true, wenn ein Ollama-Bezugsweg der Gruppe echt lokal
    installiert ist (s. `_roh_lokal`)."""
    return any(z["anbieter"] == "ollama" and _roh_lokal(z) for z in gruppe)


def _gruppe_vision(gruppe: list[dict]) -> bool | None:
    """Bild-Faehigkeit der GESAMTEN Modellgruppe (Entscheid 2026-08-30 Nachtrag 6) -- ein
    Bezugsweg mit `vision=true` reicht (das Modell KANN Bilder lesen); sind alle bekannten Wege
    `false`, bleibt es `false`; kennt kein Bezugsweg den Wert, bleibt es `None` (unbekannt, kein
    Sterne-Deckel)."""
    werte = [z["vision"] for z in gruppe if z.get("vision") is not None]
    return any(werte) if werte else None


def _anbieter_eintraege(anbieter: list[dict]) -> list[dict]:
    return [
        {"name": z["anbieter"], "eingabe_usd": _zahl(z.get("eingabe_usd")),
         "ausgabe_usd": _zahl(z.get("ausgabe_usd")), "stand": z.get("stand")}
        for z in anbieter
    ]


def _preis_min(guenstigst: dict) -> dict:
    return {
        "eingabe_usd": _zahl(guenstigst.get("eingabe_usd")),
        "ausgabe_usd": _zahl(guenstigst.get("ausgabe_usd")),
        "anbieter": guenstigst["anbieter"],
    }


def _modell_eintrag(rohgruppe: list[dict], manuelle_je_schluessel: dict[str, dict] | None = None) -> dict:
    """Baut EINEN API-Modelleintrag aus allen Roh-Zeilen eines Kurznamens (C15 v2 Punkt 3).
    `sterne.score`/`sterne.gesamt` bleiben hier `None` -- `score` haengt nur von `aa_index`/
    `coding_index` DIESER Gruppe ab, `gesamt` ist relativ zum GESAMTEN Katalog (bester Score
    unter den aktuellen Modellen) und wird erst in `aggregiere()` nachgetragen, wenn `nachfolger`
    feststeht (Entscheid 2026-08-30 Nachtrag 6)."""
    gruppe = sorted(rohgruppe, key=lambda z: z["anbieter"])
    anbieter = _dedupe_anbieter(gruppe)
    guenstigst = _guenstigste_zeile(anbieter)
    staende = [z["stand"] for z in anbieter if z.get("stand")]
    kontext_k = max((z["kontext_k"] for z in gruppe if z.get("kontext_k") is not None), default=None)
    return {
        "id": _anzeige_id(gruppe),
        "hersteller": _haeufigster(gruppe, "hersteller"),
        "herkunft": _haeufigster(gruppe, "herkunft"),
        "kontext_k": kontext_k,
        "aa_index": _erster_wert(gruppe, "aa_index"),
        "coding_index": _erster_wert(gruppe, "coding_index"),
        "agentic_index": _erster_wert(gruppe, "agentic_index"),
        "tempo_tok_s": _erster_wert(gruppe, "tempo_tok_s"),
        "vision": _gruppe_vision(gruppe),
        "lokal": _ist_lokal(gruppe),
        "eu_ohne_training": any(z["anbieter"] == "requesty" for z in anbieter),
        "anbieter": _anbieter_eintraege(anbieter),
        "preis_min": _preis_min(guenstigst),
        "stand_juengster": max(staende) if staende else None,
        "sterne": {
            "score": None, "gesamt": None,
            "manuell": _manuelle_test_sterne(gruppe, manuelle_je_schluessel or {}),
        },
    }


def _anzeige_id(gruppe: list[dict]) -> str:
    """Anzeige-`id`: haeufigste Original-Schreibweise der Kurzform in der Gruppe; bei
    Gleichstand gewinnt die des juengsten `stand` (Befund 2026-08-28: `sonnet-4.5`
    vs `sonnet-4-5` sind DASSELBE Modell in Anbieter-Schreibweisen -- eine Form zeigen)."""
    nach_stand = sorted(gruppe, key=lambda z: z.get("stand") or "", reverse=True)
    zaehler = Counter(anzeige_kurzform(z["modell_id"]) for z in nach_stand)
    return zaehler.most_common(1)[0][0]


def _mit_sternen_und_status(modelle: list[dict]) -> None:
    """Traegt `sterne.score`/`sterne.gesamt` sowie additiv `status`
    (`"bewertet"|"latest"|"legacy"`) in die `modelle`-Eintraege ein (Entscheid 2026-08-30
    Nachtrag 6, ersetzt die Quintil-Sterne aus Nachtrag 2/4) -- muss NACH `_mit_nachfolger()`/
    `_mit_kuratierten_generationen()` laufen (`_ist_legacy_status()` liest deren Ergebnis). Nur
    AKTUELLE Modelle bekommen ueberhaupt einen `gesamt`-Wert -- eine Legacy-Zeile bleibt
    unbewertet (`status = "legacy"`), unabhaengig davon, ob ein Score fuer sie berechenbar waere.
    Entfernt den internen `_generation_legacy`-Marker wieder (kein Kontraktfeld). Mutiert die
    Eintraege in-place, kein Rueckgabewert (Aufrufer haelt bereits die Liste)."""
    for m in modelle:
        m["sterne"]["score"] = _score(m["aa_index"], m["coding_index"])
    best = _bester_score(modelle)
    for m in modelle:
        legacy = _ist_legacy_status(m)
        m.pop("_generation_legacy", None)
        if legacy:
            m["sterne"]["gesamt"] = None
            m["status"] = "legacy"
            continue
        roh = _sterne_aus_score(m["sterne"]["score"], best)
        m["sterne"]["gesamt"] = _mit_vision_deckel(roh, m.get("vision"))
        m["status"] = "bewertet" if m["sterne"]["gesamt"] is not None else "latest"


def _ollama_basisnamen_mit_variante(zeilen: list[dict]) -> set[str]:
    """Basisnamen (Teil vor dem ersten `:`) aller Ollama-Rohzeilen, die selbst einen Tag tragen
    -- fuer `_ohne_ollama_basis_dubletten()`."""
    return {z["modell_id"].split(":", 1)[0] for z in zeilen
            if z["anbieter"] == "ollama" and ":" in z["modell_id"]}


def _ohne_ollama_basis_dubletten(zeilen: list[dict]) -> list[dict]:
    """C15 v2 Punkt 3 (Befund 2026-08-30, Fix 3): eine Ollama-Zeile OHNE Tag (`gpt-oss`) ist
    dasselbe Modell wie eine Groessenvariante DESSELBEN Basisnamens (`gpt-oss:20b-cloud`) --
    Ollama fuehrt beide als eigene Registry-Eintraege, aber nur EINER gehoert in den Katalog
    ("... sonst der Variante zuschlagen"). Betrifft nur `anbieter == 'ollama'`; andere Anbieter
    kennen dieses Tag-Muster nicht."""
    basisnamen = _ollama_basisnamen_mit_variante(zeilen)
    return [z for z in zeilen if not (z["anbieter"] == "ollama" and ":" not in z["modell_id"]
                                       and z["modell_id"] in basisnamen)]


def aggregiere(zeilen: list[dict], registry: dict | None = None,
               generationen: dict | None = None) -> dict:
    """Rohzeilen (je modell_id+anbieter) -> C15-Kontraktform {stand, modelle}. Gruppiert nach
    `katalog.kanonische_id()` (C15 v2 Punkt 3; staerker als `aa_schluessel`, weil sie zusaetzlich
    Ollama-Cloud-Suffixe, Ziffer-Buchstabe-Schreibweisen bekannter Familien und `-it`/`-instruct`
    vereinheitlicht, Befund 2026-08-30 Fix 3 -- z. B. `gpt-oss:20b-cloud` = `gpt-oss-20b`,
    `gemma4:31b-cloud` = `gemma-4-31b-it`) -- API liefert stabil nach `id` (C15), Sortierung
    macht der Client (th-sort). `registry` (optional, `scripts/modelle.json`-Form) liefert NUR
    die manuellen Test-Sterne fuer den Tooltip (Entscheid 2026-08-30) -- die automatischen
    Sterne brauchen sie nicht. `generationen` (optional, `generationen.json`-Form, Festlegung
    2026-08-30) traegt die kuratierten Generations-Schwellen nach; `None` wird hier zu `{}`
    (Muster `registry`) -- diese Funktion liest NIE von Disk, das macht ausschliesslich
    `hole_katalog()` (`_lies_generationen()`), damit Tests ohne Datei isoliert bleiben."""
    zeilen = _ohne_ollama_basis_dubletten(zeilen)
    je_kurzname: dict[str, list[dict]] = {}
    for z in zeilen:
        je_kurzname.setdefault(kanonische_id(z["modell_id"]), []).append(z)

    manuelle_je_schluessel = _manuelle_je_schluessel(registry)
    modelle = [_modell_eintrag(gruppe, manuelle_je_schluessel) for _, gruppe in sorted(je_kurzname.items())]
    _mit_nachfolger(modelle)
    _mit_kuratierten_generationen(modelle, generationen or {})
    _mit_sternen_und_status(modelle)
    stand = _stand_je_anbieter(zeilen)
    stand["artificial_analysis"] = _juengster_aa_stand(zeilen)
    return {"stand": stand, "modelle": modelle}


def _lies_registry() -> dict:
    if not MODELLE_PFAD.exists():
        return {}
    try:
        with open(MODELLE_PFAD, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _wege_liste(eintrag) -> list:
    """Normiert eine Persona-Eintragsform (C15 v2 Punkt 5): FLACHE Liste (Ist-Stand
    modelle.json) ODER {rolle, wege: [...]} (Alt-Form) -- Pendant zu `personaWegeListe()` in
    static/js/katalog.js, beide Formen bleiben lesbar."""
    if isinstance(eintrag, list):
        return eintrag
    if isinstance(eintrag, dict) and isinstance(eintrag.get("wege"), list):
        return eintrag["wege"]
    return []


def _mit_ebene_default(wege: list) -> list[dict]:
    """`ebene` fehlt in Bestandseintraegen (= 'offen', C15 v2 Punkt 5) -- wird hier ergaenzt,
    damit Aufrufer (Frontend, `lokal_liste()`) das Feld nie fehlend behandeln muessen."""
    return [dict(w, ebene=w.get("ebene", "offen")) for w in wege if isinstance(w, dict)]


def persona_wege(registry: dict | None = None) -> dict:
    """`persona_wege`-Block aus modelle.json, fail-soft: Datei/Schluessel fehlt (noch nicht
    geschrieben) oder falscher Typ -> leeres Dict, nie ein Fehler. Jeder Weg-Eintrag bekommt
    `ebene` mit Default 'offen' (C15 v2 Punkt 5); die Huelle (flache Liste oder {rolle, wege})
    bleibt wie im Bestand erhalten."""
    reg = registry if registry is not None else _lies_registry()
    block = reg.get("persona_wege")
    if not isinstance(block, dict):
        return {}
    ergebnis: dict = {}
    for persona, eintrag in block.items():
        wege = _mit_ebene_default(_wege_liste(eintrag))
        if isinstance(eintrag, dict):
            neu = dict(eintrag)
            neu["wege"] = wege
            ergebnis[persona] = neu
        else:
            ergebnis[persona] = wege
    return ergebnis


def _cura_geschuetzt_primaer(wege: dict) -> str | None:
    """CURA-Weg mit `ebene: geschuetzt` + `primaer: true` (C15 v2 Punkt 5) -- markiert das
    Modell in `lokal_liste()`, das die Bruecke im geschuetzten Pfad zuerst anspricht."""
    for weg in _wege_liste((wege or {}).get("cura")):
        if isinstance(weg, dict) and weg.get("ebene") == "geschuetzt" and weg.get("primaer"):
            return weg.get("modell")
    return None


def lokal_liste(registry: dict | None = None) -> list[dict]:
    """Ollama-Bestand mit `typ: lokal` (echte Vor-Ort-Modelle) fuer die LOKAL-Kachel. Sortierung
    (C15 v2 Punkt 5, geaendert Maintainer 2026-08-30): schlicht ALPHABETISCH aufsteigend nach
    Modellname -- die CURA-primaer-Markierung/das Sterne-Ranking sind weiter je Eintrag
    sichtbar (Chip/Tooltip), bestimmen aber nicht mehr die Reihenfolge."""
    reg = registry if registry is not None else _lies_registry()
    bestand = reg.get("modelle", {}) if isinstance(reg.get("modelle"), dict) else {}
    primaer_name = _cura_geschuetzt_primaer(persona_wege(reg))
    eintraege = [
        {"modellname": name, "sterne": daten.get("gesamt"), "kommentar": daten.get("kommentar") or "",
         "cura_primaer": name == primaer_name}
        for name, daten in bestand.items() if isinstance(daten, dict) and daten.get("typ") == "lokal"
    ]
    eintraege.sort(key=lambda e: _anzeige_sortschluessel(e["modellname"]))
    return eintraege


_HF_CO_RE = re.compile(r"^hf\.co/([^/]+)/(.+)-GGUF:(.+)$", re.IGNORECASE)


def _anzeige_sortschluessel(modellname: str) -> str:
    """Sortier-Key = der im Panel ANGEZEIGTE Name (Maintainer 2026-08-30: die Roh-ID sortiert
    `hf.co/...` falsch vorn) -- spiegelt format.js hfCoTeile/modellAnzeigeName 1:1:
    hf.co -> reiner Modellname, sonst Kern nach '/' + '@', Tags :flex/:batch/:free und
    :cloud/-cloud/:latest abgeschnitten, ':9b'/':14b' BLEIBEN (Teil des Anzeigenamens)."""
    treffer = _HF_CO_RE.match(modellname.strip())
    if treffer:
        return treffer.group(2).lower()
    kern = modellname.split("/")[-1].split("@", 1)[0]
    kern = re.sub(r":(flex|batch|free)$", "", kern, flags=re.IGNORECASE)
    return re.sub(r"(:cloud|-cloud|:latest)$", "", kern, flags=re.IGNORECASE).lower()


def hole_katalog(laufer=None, registry: dict | None = None, generationen: dict | None = None) -> dict:
    """Orchestriert GET /api/modellkatalog: SQL lesen + aggregieren + `persona_wege`/
    `lokal_liste` als Zusatzfelder beilegen (additiv zur C15-Kernform -- die Einstellungen-
    Seite braucht Tabelle UND Persona-Kacheln in einem Aufruf). `laufer` faellt auf
    `speicher.psql` zurueck; wirft `speicher.SpeicherFehler` unveraendert weiter (ausser bei
    fehlenden 0007-Spalten, siehe `_zeilen_lesen`), der Aufrufer (web.py) entscheidet die
    HTTP-Antwort. `generationen` faellt auf `_lies_generationen()` zurueck (Muster `registry`/
    `_lies_registry()`)."""
    lauf = laufer if laufer is not None else speicher.psql
    zeilen = _zeilen_lesen(lauf)
    reg = registry if registry is not None else _lies_registry()
    gen = generationen if generationen is not None else _lies_generationen()
    ergebnis = aggregiere(zeilen, reg, gen)
    ergebnis["persona_wege"] = persona_wege(reg)
    ergebnis["lokal_liste"] = lokal_liste(reg)
    return ergebnis


def preise_anreichern(preise: dict, katalog_zeilen: list[dict],
                      registry: dict | None = None, generationen: dict | None = None) -> dict:
    """Nachtrag 2026-08-30 (Preistabelle im Katalog-Look, Screenshot-Runde 3): reichert je
    Abrechnungs-Key `kontext_k`/`herkunft`/`hersteller` aus dem Katalog an -- serverseitig ueber
    `katalog.kanonische_id()`, also dieselbe Normalform, mit der der Katalog selbst gruppiert
    (ersetzt das provisorische Client-Matching). Seit der Drittel-Zelle (Maintainer, Runde 4) auch
    `status`/`nachfolger` aus der vollen Aggregation (gleiche Sterne-/Latest-/Legacy-Regel wie
    der Katalog vorn). Regeln: exakter Key == Katalog-ID → `exakt`; die kanonische ID des Keys
    trifft genau EINE Gruppe → `alias`; keiner → `kein_match`. Nur Anzeige-Anreicherung: die
    Abrechnung (kennzahlen._preissatz) liest weiter nur die Rechenfelder.
    """
    from . import katalog as katalog_mod

    # Gruppieren ueber dieselbe Normalform wie der Katalog selbst (kanonische_id) -- die
    # Anzeige-ID des Aggregats ("gpt-oss:20b-cloud") kanonisiert auf denselben Gruppen-
    # Schluessel; Rohzeilen je Gruppenschluessel, je Feld der erste nicht-NULL-Wert
    # (Analogie zur Aggregationsregel in aggregiere()).
    je_gruppe: dict[str, list[dict]] = {}
    for z in katalog_zeilen:
        je_gruppe.setdefault(katalog_mod.kanonische_id(z["modell_id"]), []).append(z)

    # Status (bewertet/latest/legacy) kommt nur aus der VOLLEN Aggregation inkl. kuratierter
    # Generationen (Muster hole_katalog: Disk-Zugriff gehoert hierher, aggregiere liest nie).
    reg = registry if registry is not None else _lies_registry()
    gen = generationen if generationen is not None else _lies_generationen()
    status_je_kanon: dict[str, dict] = {}
    if katalog_zeilen:
        for m in aggregiere(list(katalog_zeilen), reg, gen)["modelle"]:
            status_je_kanon[katalog_mod.kanonische_id(m["id"])] = {
                "status": m.get("status"), "nachfolger": m.get("nachfolger"),
                # Maintainer 2026-08-30 (Status-Zone unten): bewertete Modelle zeigen ihre Sterne
                # auch in der Preistabelle -- darum kommt der Gesamt-Sternewert mit.
                "sterne_gesamt": (m.get("sterne") or {}).get("gesamt")}

    def _feld(gruppe: list[dict], feld: str):
        for z in gruppe:
            if z.get(feld) is not None:
                return z[feld]
        return None

    ergebnis = {}
    for key in preise:
        kanon = katalog_mod.kanonische_id(key)
        if kanon in je_gruppe:
            gruppe = je_gruppe[kanon]
            match = "exakt" if any(z["modell_id"] == key for z in gruppe) else "alias"
            status = status_je_kanon.get(kanon)
            if status is None:
                # Ollama-Basis-Dubletten (aggregiere entfernt die Basis-Zeile zugunsten
                # der Groessenvariante, s. _ohne_ollama_basis_dubletten): der kuratierte
                # `referenz`-Zeiger im Preis-Eintrag benennt die Variante, deren Status/
                # Sterne die Zeile erbt (Maintainer 2026-08-30 -- gpt-oss/qwen3-vl/mistral-large-3/
                # gemma4 blieben sonst statuslos). Ohne Zeiger: bewusst leer, kein Raten.
                referenz = (preise.get(key) or {}).get("referenz")
                if isinstance(referenz, str) and referenz:
                    status = status_je_kanon.get(katalog_mod.kanonische_id(referenz))
            status = status or {"status": None, "nachfolger": None, "sterne_gesamt": None}
            ergebnis[key] = {"kontext_k": _feld(gruppe, "kontext_k"),
                             "herkunft": _feld(gruppe, "herkunft"),
                             "hersteller": _feld(gruppe, "hersteller"), "match": match,
                             "status": status["status"], "nachfolger": status["nachfolger"],
                             "sterne_gesamt": status["sterne_gesamt"]}
        else:
            ergebnis[key] = {"kontext_k": None, "herkunft": None, "hersteller": None,
                             "match": "kein_match", "status": None, "nachfolger": None,
                             "sterne_gesamt": None}
    return ergebnis
