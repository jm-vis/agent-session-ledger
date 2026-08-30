"""Redaktions-Sicherheitsnetz: prüft und bereinigt einen Beleg vor jeder Ausgabe.

Ein Beleg darf NIE Inhalte tragen (Pfade, Secrets, E-Mails, lange Freitexte).
Dieses Modul ist das letzte Netz, nicht die einzige Kontrolle — Leser/Kennzahlen/
Regeln sollen so etwas gar nicht erst erzeugen.

Feld-Allowlist: alle Felder aus modell.py sind erlaubt (wir laufen nur über
echte Dataclass-Felder). Dict-Schlüssel, die selbst gegen ein Muster verstoßen
(Pfad/Secret/E-Mail/_lokal/Länge) gelten als unbekannt/unsicher und werden
entfernt statt redigiert.
"""
from __future__ import annotations

import dataclasses
import hashlib
import re

from . import projekte
from .modell import Auffaelligkeit, Beleg

MAX_LAENGE = 80
REDIGIERT = "<redigiert>"
# Phase 3 H (Rohdatei) + spaeter Tiefenanalyse (Phase 3 I): Version des Redaktions-Regelwerks,
# das eine Ausgabe durchlaufen hat -- wird als `redaktion_version` mit ausgeliefert, damit eine
# spaetere Regelverschaerfung sichtbar bleibt (nicht automatisch aus VERSION/git abgeleitet, weil
# sich die Redaktionsregeln unabhaengig vom Paket-Release aendern koennen).
REDAKTION_VERSION = "2026-08-28"

_PFAD_MUSTER = [
    re.compile(r"[/\\]"),  # C3: jeder Schraegstrich = Pfadverdacht (relative Pfade, Dateinamen)
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/home/"),
    re.compile(r"/Users/"),
    re.compile(r"\\\\"),
]
_SECRET_MUSTER = [
    re.compile(r"sk-"),
    re.compile(r"AKIA"),
    re.compile(r"ghp_"),
    re.compile(r"-----BEGIN"),
]
_EMAIL_MUSTER = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LOKAL_WORT = "_lokal"

_BEZEICHNER_MUSTER = re.compile(r"^[A-Za-z0-9_.:\-]{1,48}$")

# `kopf.modelle`-Ausnahme von C3 (Auftrag OpenRouter, 2026-08-27): Modellkennungen wie
# `anbieter/modell[:tag]` (OpenRouter, z. B. "nvidia/nemotron-3-ultra-550b-a55b") oder
# `hf.co/nutzer/repo:tag` (Ollama) tragen einen Schraegstrich, sind aber kein Pfadverdacht --
# ohne diese enge Ausnahme wuerde C3 sie vor jedem Speichern zu '<redigiert>' zermahlen, bevor
# quellen.quelle_fuer() den echten Modellnamen je sieht (Fund: Sitzung 545 zeigte "Unbekannt").
# Bewusst NUR die zwei bekannten Formen (nicht "1-3 beliebige Segmente") -- ein generisches
# Segment-Muster wuerde auch einen echten Vault-Pfad wie "60_Internal/HR/Max.md" durchlassen.
# NUR dieses eine Feld ist ausgenommen (siehe pruefe_beleg/bereinige) -- alle anderen Felder
# bleiben streng bei C3 (jeder Schraegstrich = Pfadverdacht).
_OPENROUTER_MUSTER = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.\-]*/[A-Za-z0-9][A-Za-z0-9_.\-]*(?::[A-Za-z0-9_.\-]+)?$"
)  # genau EIN Schraegstrich: "anbieter/modell[:tag]"
_HF_CO_MUSTER = re.compile(
    r"^hf\.co/[A-Za-z0-9][A-Za-z0-9_.\-]*/[A-Za-z0-9][A-Za-z0-9_.\-]*(?::[A-Za-z0-9_.\-]+)?$"
)  # "hf.co/nutzer/repo[:tag]" (Ollama-Registry-Konvention)


def _ist_sicherer_modellname(wert: str) -> bool:
    """True nur fuer die zwei bekannten Modellkennungs-Formen (OpenRouter/hf.co), <= 80
    Zeichen, ohne ``_lokal`` -- der C6-Marker sticht auch hier. Ohne jeden Schraeg-/Backslash
    ist ein Wert ohnehin kein C3-Pfadkandidat (kuerzt den Vergleich ab)."""
    if not wert or len(wert) > MAX_LAENGE or _LOKAL_WORT in wert:
        return False
    if "/" not in wert and "\\" not in wert:
        return True
    return bool(_OPENROUTER_MUSTER.match(wert) or _HF_CO_MUSTER.match(wert))


def _kopf_modelle(beleg) -> list[str]:
    """``kopf.modelle`` lesen -- ``beleg`` ist ein ``Beleg`` ODER dessen ``.als_dict()``-
    Projektion (wie ``_kopf_feld``)."""
    if dataclasses.is_dataclass(beleg):
        return list(beleg.kopf.modelle)
    kopf = beleg.get("kopf", {}) if isinstance(beleg, dict) else {}
    return list(kopf.get("modelle", []) or [])


def _setze_kopf_modelle(beleg, modelle: list[str]) -> None:
    """Gegenstueck zu ``_kopf_modelle`` -- schreibt in beide Formen zurueck."""
    if dataclasses.is_dataclass(beleg):
        beleg.kopf.modelle = modelle
    elif isinstance(beleg, dict):
        beleg.setdefault("kopf", {})["modelle"] = modelle


def sicherer_bezeichner(wert: str) -> str:
    """Allowlist-Regex für Tool-/Agent-/Branch-Bezeichner (F3).

    Passt ``wert`` auf ``^[A-Za-z0-9_.:\\-]{1,48}$`` -> unverändert. Sonst
    (Pfad, Sonderzeichen, zu lang) -> ``"unbekannt:" + sha256(wert)[:8]``,
    nie der Rohwert. Leerer Wert bleibt leer (kein Bezeichner vorhanden).
    """
    if not wert:
        return wert
    if _BEZEICHNER_MUSTER.match(wert):
        return wert
    return "unbekannt:" + hashlib.sha256(wert.encode("utf-8")).hexdigest()[:8]


def _pruefe_string(wert: str) -> str | None:
    """Liefert eine kurze Verstoß-Klasse oder None, wenn der String sauber ist."""
    if len(wert) > MAX_LAENGE:
        return "laenge"
    if _LOKAL_WORT in wert:
        return "lokal"  # vor Pfad: die schaerfere Klasse zuerst (C3-Reihenfolge)
    for muster in _PFAD_MUSTER:
        if muster.search(wert):
            return "pfad"
    for muster in _SECRET_MUSTER:
        if muster.search(wert):
            return "secret"
    if _EMAIL_MUSTER.search(wert):
        return "email"
    return None


def _pfad_praefix(pfad: str, teil: str) -> str:
    return f"{pfad}.{teil}" if pfad else teil


def _sammle(wert, pfad: str, funde: list[tuple[str, str]]) -> None:
    """Läuft rekursiv über Dataclasses/Listen/Dicts/Strings, sammelt (pfad, klasse)."""
    if dataclasses.is_dataclass(wert):
        for f in dataclasses.fields(wert):
            _sammle(getattr(wert, f.name), _pfad_praefix(pfad, f.name), funde)
    elif isinstance(wert, dict):
        for schluessel, teilwert in wert.items():
            if isinstance(schluessel, str):
                klasse = _pruefe_string(schluessel)
                if klasse:
                    funde.append((_pfad_praefix(pfad, f"schluessel:{schluessel}"), klasse))
            _sammle(teilwert, _pfad_praefix(pfad, str(schluessel)), funde)
    elif isinstance(wert, (list, tuple)):
        for i, teilwert in enumerate(wert):
            _sammle(teilwert, f"{pfad}[{i}]", funde)
    elif isinstance(wert, str):
        klasse = _pruefe_string(wert)
        if klasse:
            funde.append((pfad, klasse))
    # Zahlen/bool/None: nichts zu prüfen


def pruefe_beleg(beleg: Beleg) -> list[str]:
    """Liefert Verstoß-Beschreibungen ('pfad.im.beleg: klasse'), leer = sauber.

    `kopf.modelle` wird waehrend des Laufs auf die unsicheren Eintraege verengt (siehe
    `_ist_sicherer_modellname`) und danach IMMER wiederhergestellt (`finally`) -- eine sichere
    Modellkennung (OpenRouter/hf.co) darf hier nicht als Pfadverdacht auftauchen."""
    original = _kopf_modelle(beleg)
    _setze_kopf_modelle(beleg, [m for m in original if not _ist_sicherer_modellname(m)])
    try:
        funde: list[tuple[str, str]] = []
        _sammle(beleg, "", funde)
        return [f"{pfad}: {klasse}" for pfad, klasse in funde]
    finally:
        _setze_kopf_modelle(beleg, original)


def _bereinige_wert(wert, zaehler: list[int]):
    """Läuft rekursiv, ersetzt/entfernt Verstöße, zählt sie in zaehler[0]."""
    if dataclasses.is_dataclass(wert):
        for f in dataclasses.fields(wert):
            setattr(wert, f.name, _bereinige_wert(getattr(wert, f.name), zaehler))
        return wert
    if isinstance(wert, dict):
        bereinigt = {}
        for schluessel, teilwert in wert.items():
            if isinstance(schluessel, str) and _pruefe_string(schluessel):
                zaehler[0] += 1
                continue  # verstoßender/unbekannter Schlüssel: entfernen
            bereinigt[schluessel] = _bereinige_wert(teilwert, zaehler)
        return bereinigt
    if isinstance(wert, list):
        return [_bereinige_wert(teilwert, zaehler) for teilwert in wert]
    if isinstance(wert, str):
        if _pruefe_string(wert):
            zaehler[0] += 1
            return REDIGIERT
        return wert
    return wert


def bereinige(beleg: Beleg) -> Beleg:
    """Kürzt/ersetzt Verstöße durch '<redigiert>', vermerkt privacy:metadata_leak.

    `kopf.modelle`: sichere Modellkennungen (siehe `_ist_sicherer_modellname`) laufen NICHT durch
    die generische Sweep (bleiben unveraendert stehen), unsichere Eintraege werden wie jeder
    andere Verstoss redigiert und gezaehlt."""
    sicher = [m for m in beleg.kopf.modelle if _ist_sicherer_modellname(m)]
    beleg.kopf.modelle = [m for m in beleg.kopf.modelle if not _ist_sicherer_modellname(m)]
    zaehler = [0]
    _bereinige_wert(beleg, zaehler)
    beleg.kopf.modelle = sicher + beleg.kopf.modelle
    if zaehler[0] > 0:
        beleg.auffaelligkeiten.append(
            Auffaelligkeit(
                regel="privacy:metadata_leak", schwere="hoch",
                signatur="privacy:metadata_leak", wert=str(zaehler[0]),
            )
        )
    return beleg


def _pruefe_freitext(text: str) -> str | None:
    """Wie `_pruefe_string`, aber OHNE die 80-Zeichen-Grenze -- die gilt nur für kurze
    Beleg-Felder; Freitexte (Chat, Ereignis-Fehlertexte, Prüf-Urteile) haben eigene, größere
    Grenzen und kürzen selbst vor dem Aufruf (z. B. `contracts.MAX_TEXT`)."""
    if _LOKAL_WORT in text:
        return "lokal"
    for muster in _PFAD_MUSTER:
        if muster.search(text):
            return "pfad"
    for muster in _SECRET_MUSTER:
        if muster.search(text):
            return "secret"
    if _EMAIL_MUSTER.search(text):
        return "email"
    return None


def bereinige_text(text: str) -> str:
    """Redaktions-Sicherheitsnetz für einen einzelnen Freitext (Modellausgaben, Fehlertexte) --
    Secrets/Pfade/E-Mail/`_lokal` ersetzen den GANZEN Text durch '<redigiert>' (wie
    `vieraugen._kuerze`, aber ohne dessen 80-Zeichen-Vorkürzung). Für Chat-Nachrichten
    `bereinige_chat_text()` (Nachtrag 2026-08-27 Punkt 8) -- dieses Verhalten bleibt für alle
    anderen Aufrufer (`pruefung.py`/`fehlerbild_pruefung.py` Stufe-1/2-Urteile) unverändert."""
    if not text:
        return text or ""
    return REDIGIERT if _pruefe_freitext(text) else text


def _pruefe_freitext_ohne_pfad(text: str) -> str | None:
    """Wie `_pruefe_freitext`, aber OHNE den Pfad-Check -- der läuft bei Chat-Texten pro Token
    (`_ist_pfad_token`/`bereinige_chat_text`, Nachtrag 2026-08-27 Punkt 8), nicht mehr für den
    ganzen Text."""
    if _LOKAL_WORT in text:
        return "lokal"
    for muster in _SECRET_MUSTER:
        if muster.search(text):
            return "secret"
    if _EMAIL_MUSTER.search(text):
        return "email"
    return None


_PFAD_TOKEN_PRAEFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|~[\\/]|\.\.?[\\/])")
_SLASH_TOKEN = re.compile(r"\S*[\\/]\S*")


def _ist_pfad_token(token: str) -> bool:
    """Ein Token 'sieht wie ein Pfad aus' (Nachtrag 2026-08-27 Punkt 8): Laufwerksbuchstabe/`~`/
    `.` am Anfang, ODER mindestens zwei Trennzeichen (drei Segmente) -- schließt 'und/oder',
    '24/7' und Brüche ('3/4') aus, die nur EIN Trennzeichen haben."""
    if _PFAD_TOKEN_PRAEFIX.match(token):
        return True
    return len(re.findall(r"[\\/]", token)) >= 2


def bereinige_chat_text(text: str) -> str:
    """Redaktions-Sicherheitsnetz für Chat-Nachrichten (Nachtrag 2026-08-27 Punkt 8): Secrets/
    E-Mail/`_lokal` ersetzen weiterhin den GANZEN Text (unverändert). Ein Pfad-Token ersetzt NUR
    sich selbst durch '<pfad>' -- Rest der Nachricht bleibt stehen ('und/oder', '24/7', Brüche)."""
    if not text:
        return text or ""
    if _pruefe_freitext_ohne_pfad(text):
        return REDIGIERT
    return _SLASH_TOKEN.sub(lambda m: "<pfad>" if _ist_pfad_token(m.group(0)) else m.group(0), text)


# Paket K (Tiefenanalyse-Fehlertexte, Entscheid 2026-08-28): ueber `bereinige_text()` hinaus
# (Pfad/Secret-Praefix/E-Mail/`_lokal`, siehe oben) fehlten Hostnamen und generische Schluessel/
# Token (nur `sk-`/`AKIA`/`ghp_`/PEM-Header waren bisher erfasst) -- beides ergaenzt, nicht neu
# gebaut. Datei-Endungen ausgenommen, sonst waere jeder Dateiname ("script.py") ein Host-Treffer.
_DATEI_ENDUNGEN = {
    "py", "js", "ts", "tsx", "jsx", "md", "json", "txt", "html", "htm", "css", "yml", "yaml",
    "csv", "log", "ini", "toml", "sh", "ps1", "cfg", "xml", "sql", "png", "jpg", "jpeg", "gif",
    "svg", "ico", "ttf", "woff", "woff2", "pdf", "docx", "xlsx", "zip", "exe", "dll", "env",
}
_HOST_TOKEN_MUSTER = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?::\d{1,5})?$"
)  # Domain mit TLD, optionaler Port -- "example.com", "api.example.co.uk:8443"
_IPV4_TOKEN_MUSTER = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?$")
_SCHLUESSEL_TOKEN_MUSTER = re.compile(r"^[A-Za-z0-9_\-]{20,}$")
_NAME_MUSTER = re.compile(r"(?i)\b(user|name|autor|author|von|nutzer)(\s*[:=]\s*)(\S+)")
_TOKEN_MUSTER = re.compile(r"\S+")


def _ist_host_token(token: str) -> bool:
    """Hostname (Domain+TLD) oder IPv4, optional mit Port -- schliesst Dateinamen mit bekannter
    Endung aus (siehe `_DATEI_ENDUNGEN`), sonst waere jedes `datei.py` ein Host-Treffer."""
    if _IPV4_TOKEN_MUSTER.match(token):
        return True
    if not _HOST_TOKEN_MUSTER.match(token):
        return False
    kern = token.split(":", 1)[0]
    return kern.rsplit(".", 1)[-1].lower() not in _DATEI_ENDUNGEN


def _ist_schluessel_token(token: str) -> bool:
    """Lang (>= 20 Zeichen) UND aus Buchstaben+Ziffern gemischt = Verdacht auf API-Key/Token --
    ueber die bekannten Praefixe in `_SECRET_MUSTER` hinaus. Reine Wort- oder Ziffernketten (kein
    Buchstabe+Ziffer gemischt) zaehlen nicht, sonst waere jeder lange Bezeichner betroffen."""
    if not _SCHLUESSEL_TOKEN_MUSTER.match(token):
        return False
    return bool(re.search(r"[0-9]", token) and re.search(r"[A-Za-z]", token))


def _redigiere_namen(text: str) -> str:
    """Einfacher Namens-Hinweis (kein NER, keine neue Abhaengigkeit): ein Wert direkt nach den
    Schluesselwoertern user/name/autor/author/von/nutzer (':'/'=') gilt als Personenbezug und
    wird durch '<name>' ersetzt -- deckt den haeufigsten Leak-Pfad in Fehlertexten ab (z. B. 'user:
    max.mustermann'), keinen Fliesstext-Namen ohne dieses Signal."""
    return _NAME_MUSTER.sub(lambda m: m.group(1) + m.group(2) + "<name>", text)


def _klassifiziere_token(token: str) -> str:
    if _ist_pfad_token(token):
        return "<pfad>"
    if _ist_host_token(token):
        return "<host>"
    if _ist_schluessel_token(token):
        return "<schluessel>"
    return token


def bereinige_fehlertext(text: str) -> str:
    """Redaktion fuer Werkzeugfehler-Rohtexte der Tiefenanalyse (Paket K, Entscheid
    2026-08-28): erst `bereinige_text()` (Pfad/Secret-Praefix/E-Mail/`_lokal` nuken weiterhin den
    GANZEN Text, unveraendert) -- greift das nicht, zusaetzlich token-weise Hostnamen (`<host>`),
    generische Schluessel/Token (`<schluessel>`) und ein Namens-Hinweis (`<name>`). Reihenfolge
    bewusst: erst redigieren, dann in `tiefenanalyse._kappen_fehlertext` auf 300 Zeichen kappen --
    umgekehrt koennte ein Trunkierungsschnitt mitten in einem Muster die Erkennung umgehen."""
    if not text:
        return text or ""
    bereinigt = bereinige_text(text)
    if bereinigt == REDIGIERT:
        return bereinigt
    bereinigt = _redigiere_namen(bereinigt)
    return _TOKEN_MUSTER.sub(lambda m: _klassifiziere_token(m.group(0)), bereinigt)


_HR_MUSTER = re.compile(r"\bHR\b|Human", re.IGNORECASE)


def _namensmuster_hr(name: str) -> bool:
    return bool(_HR_MUSTER.search(name or ""))


def _alias_eintrag(projekt_name: str, quelle: str, aliase: dict) -> dict | None:
    eintrag = aliase.get(f"{projekt_name}@{quelle}") or aliase.get(projekt_name)
    if eintrag is not None:
        return eintrag
    if projekt_name.startswith(projekte.CODEX_PRAEFIX):
        return aliase.get(projekt_name[len(projekte.CODEX_PRAEFIX):])
    return None


def _projekt_ist_hr(projekt_name: str, quelle: str) -> bool:
    """C6: Projekt-Alias mit Feld `bereich: HR` (aktuell kein Eintrag in `projekt-aliase.json`
    gesetzt) -- Fallback Namensmuster 'HR'/'Human' auf dem aufgelösten Anzeigenamen und, ohne
    Alias, auf dem Rohnamen selbst."""
    if not projekt_name:
        return False
    eintrag = _alias_eintrag(projekt_name, quelle, projekte.lade_aliase())
    if eintrag is not None:
        if str(eintrag.get("bereich", "")).upper() == "HR":
            return True
        if _namensmuster_hr(str(eintrag.get("projekt", ""))):
            return True
    return _namensmuster_hr(projekt_name)


def _kopf_feld(beleg, feld: str) -> str:
    if dataclasses.is_dataclass(beleg):
        return getattr(beleg.kopf, feld, "") or ""
    kopf = beleg.get("kopf", {}) if isinstance(beleg, dict) else {}
    return kopf.get(feld, "") or ""


def zulaessigkeit(beleg) -> str:
    """C6: 'geschuetzt', wenn ein Pfad im Beleg `_lokal`/`_graph_lokal`/`_graph_merged_lokal`
    enthält (alle drei matchen das Substring-Muster '_lokal', siehe `_pruefe_string`) oder das
    Projekt-Alias `bereich: HR` trägt (Namensmuster-Fallback, siehe `_projekt_ist_hr`) -- sonst
    'cloud-ok'. `beleg` darf ein `Beleg` ODER dessen `.als_dict()`-Projektion sein (`pruefe_beleg`
    läuft rekursiv über Dataclass/dict/list/str gleichermaßen)."""
    if any(f.endswith(": lokal") for f in pruefe_beleg(beleg)):
        return "geschuetzt"
    if _projekt_ist_hr(_kopf_feld(beleg, "projekt_name"), _kopf_feld(beleg, "quelle")):
        return "geschuetzt"
    # Sitzungen des lokal gehaltenen Schutzbereich-Profils sind IMMER geschuetzt, unabhaengig
    # von Pfaden -- dieser Profil-Slot arbeitet per Definition im Schutzbereich.
    if _kopf_feld(beleg, "persona") == "cura":
        return "geschuetzt"
    return "cloud-ok"
