"""Chat-Bruecke (CONTRACTS.md C4/C5). Eine Hintergrund-Sitzung je `gespraech_id` (Kindprozess
`claude -p --input-format stream-json`, `chat_bruecke.ChatProzess`), Nachrichten landen in der
Tabelle `chat` (`speicher.chat_schreiben`, nicht `ereignis` -- ADR 0006 2b). Modul-Schnittstelle
(`modelle`, `gespraech_starten`, `senden`, `strom`) bleibt stabil, unabhaengig vom Anbieter."""
from __future__ import annotations

import json
import secrets
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # konsenloser Dienst: Kindprozess ohne Fenster (2026-08-28)
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime

from . import chat_bruecke, contracts, konfig, redaktion, speicher

MODELLE_PFAD = konfig.modelle_pfad()
OLLAMA_ZEITLIMIT_S = 3

# OpenRouter-Modellliste (Phase 2, Nachtrag): 10 Minuten im Prozess gecacht -- kein Netz in Tests,
# darum ist der Fetch injizierbar (Muster `KOMMANDO_BAUEN`). Standardauswahl (welches Modell
# vorausgewaehlt ist) entscheidet das Frontend (`static/js/chat.js` STANDARD_BEVORZUGT/
# standardModell()) -- die Liste aendert sich haeufiger als dieses Modul, siehe Coordinator-
# Nachtrag Punkt 3. Ollama-/OpenRouter-Standard (jeweils das ERSTE Praeferenz-Element) kommen
# NICHT aus einer hartcodierten Liste, sondern aus `_vico_standard()` unten (`scripts/modelle.json`
# Felder `default_vico_ollama`/`default_vico_openrouter`, ein gemeinsamer Leser).
#
# Coordinator-Nachtrag (Konto-Datenschutzeinstellungen, z. B. ZDR-Filter): `GET /v1/models` ist
# OEFFENTLICH und ungefiltert -- ein Modell darin kann zur Laufzeit trotzdem scheitern, wenn das
# Konto es per Datenschutz-/Provider-Einstellung ausschliesst (verifiziert: ZDR an -> 255 Modelle/
# 2 `:free` unter `/models/user`, gegenueber 18 `:free` unter dem oeffentlichen `/models`).
# `GET /v1/models/user` (Bearer-Header) zeigt nur, was das Konto tatsaechlich aufrufen kann -- wird
# genutzt, sobald ein Schluessel vorliegt (`chat_bruecke._openrouter_schluessel()`, gleiche
# Reihenfolge Env/Datei); ohne Schluessel bleibt nur die oeffentliche, ungefilterte Liste.
OPENROUTER_MODELLE_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_MODELLE_USER_URL = "https://openrouter.ai/api/v1/models/user"
OPENROUTER_ZEITLIMIT_S = 5
OPENROUTER_CACHE_S = 600
_openrouter_cache: dict = {"zeit": 0.0, "ergebnis": None}

# Requesty-Modellliste (Phase 2, Nachtrag Requesty 2026-08-28): OEFFENTLICH, kein Schluessel
# noetig (anders als OpenRouter). Default-Filter (Entscheid): nur `geolocation == "eu"` UND
# `data_used_for_training == false` -- der Schalter `alle=true` (Query-Param, chat.js "alle
# zeigen") zeigt den kompletten Katalog ungefiltert. Preise kommen als USD/Token
# (`input_price`/`output_price`), hier auf USD/1M Token umgerechnet (gleiche Einheit wie
# `scripts/modelle.json`). 10-Minuten-Prozesscache auf dem ROHEN Fetch (Muster OpenRouter),
# Filterung passiert danach -- ein Wechsel des Schalters braucht darum kein neues Netz.
REQUESTY_MODELLE_URL = "https://router.requesty.ai/v1/models"
REQUESTY_ZEITLIMIT_S = 5
REQUESTY_CACHE_S = 600
_requesty_cache: dict = {"zeit": 0.0, "roh": None}

# In-Prozess-Registry der laufenden Hintergrund-Sitzungen: Metadaten (anbieter/modell/kontext/
# schutz) je `gespraech_id`, der zugehoerige Kindprozess (lazy, erst beim ersten `strom()`) und
# der jeweils naechste noch unbeantwortete Nutzertext. Ein Prozess-Absturz raeumt sich selbst aus
# `_PROZESSE` -- der naechste `strom()`-Aufruf spawnt transparent neu ("Sitzung neu startbar").
_GESPRAECHE: dict[str, dict] = {}
_PROZESSE: dict[str, chat_bruecke.ChatProzess] = {}
_AUSSTEHEND: dict[str, str] = {}


def _registry() -> dict:
    """`scripts/modelle.json` -- leeres `{}` wenn die Datei fehlt oder nicht lesbar/parsebar ist
    (Coordinator-Nachtrag: `_vico_standard()` muss darauf ohne Crash reagieren koennen)."""
    try:
        with open(MODELLE_PFAD, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


_VICO_STANDARD_WARNUNG_GEZEIGT = {"getan": False}


def _vico_standard(registry: dict, feld: str) -> str | None:
    """Ein Feld aus `scripts/modelle.json` (`default_vico_ollama`/`default_vico_openrouter`) --
    EIN Leser fuer beide Felder, nicht in `chat.js` hart codieren. Fehlt ein Feld oder ist die
    Registry nicht lesbar, faellt das Frontend auf das erste Modell der Liste zurueck
    (`standardModell()`) -- hier nur EINE Warnung je Prozess insgesamt (nicht je Feld), kein
    wiederholtes Log-Spam bei jedem `GET /api/chat/modelle`."""
    wert = registry.get(feld)
    if not wert and not _VICO_STANDARD_WARNUNG_GEZEIGT["getan"]:
        _VICO_STANDARD_WARNUNG_GEZEIGT["getan"] = True
        print(f"[chat] modelle.json: '{feld}' fehlt oder Datei nicht lesbar -- "
              "Standardauswahl faellt im Frontend auf das erste Modell zurueck")
    return wert


def _claude_modelle(registry: dict) -> list[dict]:
    """C5: Claude-Modelle aus `scripts/modelle.json` (`preise.modelle`, `herkunft == anthropic`)."""
    preise = registry.get("preise", {}).get("modelle", {})
    return [
        {"id": name, "name": name}
        for name, angaben in preise.items()
        if isinstance(angaben, dict) and angaben.get("herkunft") == "anthropic"
    ]


def _ollama_lauf(*argv: str, laufer=subprocess.run) -> str:
    """`ollama ps`/`ollama list` mit 3s-Zeitlimit -- leerer String bei jedem Fehler (Ollama nicht
    installiert/erreichbar, Zeitlimit ueberschritten, Nicht-Null-Exit). `stdin=DEVNULL` wie in
    `commits._git`: konsenloser Dienst erbt ein ungueltiges Stdin-Handle."""
    try:
        lauf = laufer(["ollama", *argv], capture_output=True, timeout=OLLAMA_ZEITLIMIT_S,
                      stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return lauf.stdout.decode("utf-8", "replace") if lauf.returncode == 0 else ""


def _erste_spalte(ausgabe: str) -> set[str]:
    """Modellnamen aus der ersten Spalte von `ollama ps`/`list` (Kopfzeile uebersprungen)."""
    zeilen = ausgabe.strip().splitlines()[1:]
    return {zeile.split()[0] for zeile in zeilen if zeile.split()}


def _ollama_modelle(registry: dict) -> list[dict]:
    """C5: `ollama ps` (geladen) + `ollama list` (verfuegbar) + Registry-Eintraege `typ == cloud`
    (Ollama-Cloud-Modelle, weder geladen noch lokal verfuegbar) -- eine Zeile je Modellname,
    keine Duplikate ueber die drei Quellen hinweg."""
    geladen = _erste_spalte(_ollama_lauf("ps"))
    verfuegbar = _erste_spalte(_ollama_lauf("list")) - geladen
    cloud = {
        name for name, angaben in registry.get("modelle", {}).items()
        if isinstance(angaben, dict) and angaben.get("typ") == "cloud"
    } - geladen - verfuegbar
    ergebnis = [{"id": n, "name": n, "zustand": "geladen"} for n in sorted(geladen)]
    ergebnis += [{"id": n, "name": n, "zustand": "verfuegbar"} for n in sorted(verfuegbar)]
    ergebnis += [{"id": n, "name": n, "zustand": "cloud"} for n in sorted(cloud)]
    return ergebnis


def _openrouter_anfrage() -> tuple[str, dict]:
    """(url, headers) fuer die Modellliste -- Schluessel vorhanden: authentifiziert
    `/models/user` (zeigt nur, was das Konto laut seinen Datenschutz-/Provider-Einstellungen wie
    dem ZDR-Filter tatsaechlich aufrufen kann); sonst oeffentlich `/models` (ungefiltert, ein
    Modell darin kann zur Laufzeit trotzdem scheitern). Der Schluessel geht NUR in den
    Header-Wert, nie in Log/Rueckgabe/Fehlermeldung."""
    try:
        schluessel = chat_bruecke._openrouter_schluessel()
    except chat_bruecke.OpenRouterSchluesselFehler:
        return OPENROUTER_MODELLE_URL, {}
    return OPENROUTER_MODELLE_USER_URL, {"Authorization": f"Bearer {schluessel}"}


def _openrouter_holen(url: str, headers: dict) -> str:
    """Fuehrt die Modellisten-Anfrage aus -- injizierbar (Muster `KOMMANDO_BAUEN`), damit Tests
    URL/Header-Vorhandensein pruefen koennen, ganz ohne echtes Netz oder einen echten Schluessel."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                 timeout=OPENROUTER_ZEITLIMIT_S) as antwort:
        return antwort.read().decode("utf-8")


OPENROUTER_HOLEN = _openrouter_holen


def _openrouter_modell_eintraege(roh: str) -> list[dict]:
    """Parst `{"data": [{"id": "…", "context_length": 164000}, …]}` zu sortierten, eindeutigen
    `{"id", "kontext"}`-Eintraegen (Frontend gruppiert/formatiert `kontext`, Coordinator-Nachtrag
    2026-08-27 Punkt 2) -- Fixture-testbar ohne Netzzugriff."""
    daten = json.loads(roh)
    eintraege = {e["id"]: e.get("context_length")
                 for e in daten.get("data", []) if isinstance(e, dict) and e.get("id")}
    return [{"id": i, "kontext": eintraege[i]} for i in sorted(eintraege)]


def _openrouter_modelle() -> tuple[list[dict], str]:
    """C5: OpenRouter-Modelle mit 10-Minuten-Prozesscache -- bei Fehler/Offline leere Liste plus
    Hinweistext (kein Crash, `modelle()` bleibt bedienbar ohne Netz)."""
    jetzt = time.monotonic()
    if _openrouter_cache["ergebnis"] is not None and jetzt - _openrouter_cache["zeit"] < OPENROUTER_CACHE_S:
        return _openrouter_cache["ergebnis"], ""
    try:
        url, headers = _openrouter_anfrage()
        ergebnis = _openrouter_modell_eintraege(OPENROUTER_HOLEN(url, headers))
    except (OSError, urllib.error.URLError, ValueError) as fehler:
        return [], f"OpenRouter-Modelle nicht geladen: {fehler}"
    _openrouter_cache["ergebnis"], _openrouter_cache["zeit"] = ergebnis, jetzt
    return ergebnis, ""


def _requesty_holen() -> str:
    """Fuehrt die (oeffentliche, kopflose) Modellisten-Anfrage aus -- injizierbar (Muster
    `OPENROUTER_HOLEN`)."""
    with urllib.request.urlopen(REQUESTY_MODELLE_URL, timeout=REQUESTY_ZEITLIMIT_S) as antwort:
        return antwort.read().decode("utf-8")


REQUESTY_HOLEN = _requesty_holen


def _requesty_eintrag(m: dict) -> dict:
    """Ein rohes Requesty-Modell -> `{id, kontext, preis_in, preis_out, region}` -- Preise von
    USD/Token auf USD/1M Token umgerechnet (gleiche Einheit wie `scripts/modelle.json`)."""
    return {
        "id": m["id"], "kontext": m.get("context_window"),
        "preis_in": round((m.get("input_price") or 0) * 1_000_000, 4),
        "preis_out": round((m.get("output_price") or 0) * 1_000_000, 4),
        "region": m.get("geolocation") or "",
    }


def _requesty_gefiltert(modelle: list[dict], alle: bool) -> list[dict]:
    """Default-Filter (Entscheid): nur EU-Modelle ohne Trainingsnutzung -- `alle=true`
    (chat.js-Schalter "alle zeigen") ueberspringt den Filter komplett."""
    if alle:
        return modelle
    return [m for m in modelle if m.get("geolocation") == "eu" and m.get("data_used_for_training") is False]


def _requesty_modell_eintraege(roh: str, alle: bool) -> list[dict]:
    """Parst `{"data": [...]}`, filtert (s. `_requesty_gefiltert`) und liefert eindeutige,
    nach `id` sortierte Eintraege -- Fixture-testbar ohne Netzzugriff."""
    daten = json.loads(roh)
    rohmodelle = [m for m in daten.get("data", []) if isinstance(m, dict) and m.get("id")]
    gefiltert = _requesty_gefiltert(rohmodelle, alle)
    eintraege = {m["id"]: _requesty_eintrag(m) for m in gefiltert}
    return [eintraege[i] for i in sorted(eintraege)]


def _requesty_modelle(alle: bool = False) -> tuple[list[dict], str]:
    """C5: Requesty-Modelle -- der ROHE Fetch ist 10 Minuten im Prozess gecacht (Muster
    OpenRouter), die Filterung (`alle`) laeuft danach auf dem gecachten Rohtext, kein
    zusaetzliches Netz je Schalterstellung. Bei Fehler/Offline leere Liste plus Hinweistext."""
    jetzt = time.monotonic()
    if _requesty_cache["roh"] is not None and jetzt - _requesty_cache["zeit"] < REQUESTY_CACHE_S:
        roh = _requesty_cache["roh"]
    else:
        try:
            roh = REQUESTY_HOLEN()
        except (OSError, urllib.error.URLError) as fehler:
            return [], f"Requesty-Modelle nicht geladen: {fehler}"
        _requesty_cache["roh"], _requesty_cache["zeit"] = roh, jetzt
    try:
        return _requesty_modell_eintraege(roh, alle), ""
    except (ValueError, KeyError) as fehler:
        return [], f"Requesty-Modelle nicht geladen: {fehler}"


def modelle(requesty_alle: bool = False) -> dict:
    """C5 GET /api/chat/modelle."""
    registry = _registry()
    openrouter, or_hinweis = _openrouter_modelle()
    requesty, rq_hinweis = _requesty_modelle(requesty_alle)
    ergebnis = {
        "claude": _claude_modelle(registry), "ollama": _ollama_modelle(registry), "openrouter": openrouter,
        "requesty": requesty,
        "ollama_standard": _vico_standard(registry, "default_vico_ollama"),
        "openrouter_standard": _vico_standard(registry, "default_vico_openrouter"),
        "requesty_standard": _vico_standard(registry, "default_vico_requesty"),
    }
    if or_hinweis:
        ergebnis["openrouter_hinweis"] = or_hinweis
    if rq_hinweis:
        ergebnis["requesty_hinweis"] = rq_hinweis
    return ergebnis


def _neue_gespraech_id() -> str:
    """`c-<JJJJMMTT>-<HHMM>-<4 hex>` (CONTRACTS.md C4/C8 Musterpruefung)."""
    jetzt = datetime.now()
    return f"c-{jetzt:%Y%m%d}-{jetzt:%H%M}-{secrets.token_hex(2)}"


def gespraech_starten(anbieter: str, modell: str, kontext: dict, schutz: str = "cloud-ok",
                       sicht: dict | None = None) -> str:
    """Neue Hintergrund-Sitzung (C5 POST /api/chat, `gespraech_id: null`). Anbieterwechsel = neue
    `gespraech_id` (Plan Abschn. 4.5) -- diese Funktion startet darum immer eine neue Sitzung,
    nie ein Update einer bestehenden. `sicht` (Nachtrag 2026-08-28): das Sichtpaket des Frontends
    (`contracts.Sicht`, bereits gegen den Contract geprueft und redigiert, s. `sicht_bereinigt`)
    -- geht wie `kontext` nur EINMAL in die erste Kindprozess-Nachricht (`chat_bruecke._sende`)."""
    gespraech_id = _neue_gespraech_id()
    _GESPRAECHE[gespraech_id] = {
        "anbieter": anbieter, "modell": modell, "kontext": kontext, "schutz": schutz, "sicht": sicht,
    }
    return gespraech_id


def _bereinige_werte(wert):
    """Rekursiv: jeder String im Sichtpaket durch `redaktion.bereinige_text()` -- die Werte sind
    bereits redigierte Anzeige-Information, das ist nur das zweite Netz (Muster
    `chat_kennzahlen.baue_block`)."""
    if isinstance(wert, str):
        return redaktion.bereinige_text(wert)
    if isinstance(wert, list):
        return [_bereinige_werte(w) for w in wert]
    if isinstance(wert, dict):
        return {k: _bereinige_werte(v) for k, v in wert.items()}
    return wert


def sicht_bereinigt(sicht: dict | None) -> dict | None:
    """C7 Sichtkontext (Nachtrag 2026-08-28): Redaktions-Sicherheitsnetz fuers Sichtpaket, bevor
    es in `_GESPRAECHE`/die Kindprozess-Nachricht geht. `None` bleibt `None`."""
    return _bereinige_werte(sicht) if sicht else sicht


def _basis_detail(info: dict, gespraech_id: str) -> dict:
    return {
        "schema": 1, "gespraech_id": gespraech_id, "anbieter": info["anbieter"], "modell": info["modell"],
        "schutz": info["schutz"], "kontext": info["kontext"], "token_in": 0, "token_out": 0, "dauer_ms": 0,
    }


def senden(gespraech_id: str, text: str, laufer=speicher.psql) -> None:
    """Schreibt die Nutzer-Nachricht sofort in `chat` (C4) und merkt sie als naechsten Turn vor.
    `strom()` fuehrt den echten Modell-Turn aus und schreibt die Assistent-Antwort erst danach --
    echtes SSE-Streaming braucht die laufende GET-Antwort, nicht den POST-Handler."""
    info = _GESPRAECHE.get(gespraech_id)
    if info is None:
        raise ValueError(f"Gespräch {gespraech_id} wurde nicht gestartet")
    basis = _basis_detail(info, gespraech_id)
    text_bereinigt = redaktion.bereinige_chat_text(text)
    speicher.chat_schreiben({**basis, "rolle": "nutzer", "text": text_bereinigt}, laufer=laufer)
    _AUSSTEHEND[gespraech_id] = text_bereinigt


def _prozess_fuer(gespraech_id: str, info: dict) -> chat_bruecke.ChatProzess:
    """Holt den laufenden Kindprozess des Gespraechs, oder legt einen neuen an (kein Prozess ist
    dank `chat_bruecke.ChatProzess.turn()`s Selbstheilung auch der Zustand nach einem Absturz)."""
    prozess = _PROZESSE.get(gespraech_id)
    if prozess is None:
        prozess = chat_bruecke.ChatProzess(
            info["anbieter"], info["modell"], info["kontext"], info.get("sicht")
        )
        _PROZESSE[gespraech_id] = prozess
    return prozess


def _handover_text(gespraech_id: str, kontext: dict) -> str:
    """NUR ein neutrales Themen-Stichwort (Sitzung/Befund/Gespraech-ID) -- NIE Nachrichtentext
    (DSGVO: das Fix-Fenster startet in einem fremden Prozess, dem keine Chatinhalte gehoeren)."""
    teile = []
    if kontext.get("sitzung_logisch"):
        teile.append(f"Sitzung {kontext['sitzung_logisch']}")
    if kontext.get("signatur"):
        teile.append(f"Befund {kontext['signatur']}")
    teile.append(f"Chat {gespraech_id}")
    return ", ".join(teile)


def fix_umsetzen(gespraech_id: str) -> None:
    """POST /api/chat/{gespraech_id}/fix: oeffnet ein sichtbares Fix-Fenster (konfigurierter
    Launcher, s. `chat_bruecke._fix_kommando`) mit dem Handover-Stichwort dieses Gespraechs.
    `ValueError` bei unbekanntem Gespraech (web.py macht daraus 404), `chat_bruecke.FixLauncherFehlt`
    bei fehlender Konfiguration (web.py macht daraus 501), jeder andere Fehler wandert hoch
    (web.py macht daraus 500 -- Fensterstart ist ein Fremdprozess, kein Fehler wird verschluckt)."""
    info = _GESPRAECHE.get(gespraech_id)
    if info is None:
        raise ValueError(f"Gespräch {gespraech_id} wurde nicht gestartet")
    chat_bruecke.oeffne_fix_fenster(_handover_text(gespraech_id, info["kontext"]))


def _sse_event(typ: str, **felder) -> dict:
    event = {"typ": typ, **felder}
    contracts.validiere("sse_event", event)
    return event


def _schreibe_antwort(gespraech_id: str, info: dict, antwort: str, token_in: int, token_out: int,
                       dauer_ms: int, laufer) -> None:
    """Schreibt die fertige Assistent-Antwort in `chat` -- ein DB-Fehler darf die schon
    gestreamte Antwort dem Nutzer nicht mehr entziehen, nur der Verlauf bleibt dann lueckenhaft."""
    basis = _basis_detail(info, gespraech_id)
    detail = {**basis, "rolle": "assistent", "text": redaktion.bereinige_chat_text(antwort),
              "token_in": token_in, "token_out": token_out, "dauer_ms": dauer_ms}
    try:
        speicher.chat_schreiben(detail, laufer=laufer)
    except (contracts.ContractFehler, speicher.SpeicherFehler) as fehler:
        print(f"[chat] Antwort nicht gespeichert ({gespraech_id}): {fehler}")


def _turn_events(gespraech_id: str, prozess: chat_bruecke.ChatProzess, text: str,
                  teile: list[str], bilanz: dict) -> Iterator[dict]:
    """Wandelt die rohen `(typ, payload)`-Ereignisse eines Turns in SSE-Ereignisse -- nur
    'delta'/'fehler': 'ende' baut `strom()` selbst, weil es die gemessene `dauer_ms` braucht.
    Bei 'fehler' raeumt sie den Kindprozess aus der Registry (naechster Turn spawnt neu)."""
    for typ, payload in prozess.turn(text):
        if typ == "delta":
            teile.append(payload)
            yield _sse_event("delta", text=payload)
        elif typ == "ende":
            bilanz["token_in"], bilanz["token_out"] = payload["token_in"], payload["token_out"]
        elif typ == "fehler":
            _PROZESSE.pop(gespraech_id, None)
            yield _sse_event("fehler", text=payload)


def strom(gespraech_id: str, laufer=speicher.psql) -> Iterator[dict]:
    """C5 GET /api/chat/{gespraech_id}/strom: fuehrt den ausstehenden Turn wirklich aus (echtes
    Streaming waehrend DIESER Antwort laeuft) und schreibt die Assistent-Antwort danach in `chat`.
    Kein ausstehender Turn (unbekanntes Gespraech, oder schon konsumiert) -> leerer Strom."""
    info = _GESPRAECHE.get(gespraech_id)
    text = _AUSSTEHEND.pop(gespraech_id, None)
    if info is None or text is None:
        return
    prozess = _prozess_fuer(gespraech_id, info)
    start = time.monotonic()
    teile: list[str] = []
    bilanz = {"token_in": 0, "token_out": 0}
    for event in _turn_events(gespraech_id, prozess, text, teile, bilanz):
        yield event
        if event["typ"] == "fehler":
            return
    dauer_ms = int((time.monotonic() - start) * 1000)
    _schreibe_antwort(gespraech_id, info, "".join(teile), bilanz["token_in"], bilanz["token_out"],
                       dauer_ms, laufer)
    yield _sse_event("ende", token_in=bilanz["token_in"], token_out=bilanz["token_out"], dauer_ms=dauer_ms)
