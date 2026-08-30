"""Pruef-Regelwerk (Phase 1 B): Zustandsableitung (C2), Stufen/Eskalation (C3), Lauf-Registry
und Lauf-Ausfuehrung (C4/C5).

Alles hier ist injizierbar (Frager, Beleg-Lader, Ereignis-Schreiber) -- Tests laufen ohne echten
Claude-/Codex-Prozess und ohne Docker/psql (wie `tests/test_vieraugen.py`/`tests/test_web.py`).
Prompts/Parser bauen auf `vieraugen.py` auf (dieselbe Redaktionsdisziplin: nie Rohtext an Codex,
Modellausgaben immer durch `redaktion` gekuerzt/redigiert, nie ungeprueft persistiert).
"""
from __future__ import annotations

import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import befunde, contracts, fehlerbild_pruefung, redaktion, speicher, vieraugen
from .fehlerbild_pruefung import datei_schreiben_real, sitzungen_fuer_signatur  # noqa: F401 (Re-Export)

MODELL_STUFE1 = "claude-sonnet-5"
MODELL_STUFE2 = "gpt-5.5"


# ---------------------------------------------------------------------------------------------
# C2 -- Zustandsableitung
# ---------------------------------------------------------------------------------------------

def status_fuer(befund: dict, entscheide: list[dict], laeufe: list[dict], laufend: list[dict]) -> str:
    """C2 Ableitungsregel (4 Schritte). `befund` = {"signatur", "sitzung_logisch", "sitzungen"} --
    "sitzungen" (optional, [{"sitzung_id","zeit","treffer"}]) speist die Rueckfall-Erkennung ueber
    `befunde.status_mit_rueckfall` (Schritt 1: juengster Entscheid, ausser Rueckfall-Ausnahme)."""
    signatur, sitzung_logisch = befund["signatur"], befund.get("sitzung_logisch")
    entscheid = befunde.juengster_je_signatur_und_sitzung(entscheide, signatur, sitzung_logisch)
    if entscheid is not None and entscheid.get("status") != "offen":
        info = befunde.status_mit_rueckfall(entscheide, signatur, befund.get("sitzungen", []))
        return info["status"]
    if _lauf_umfasst(laufend, sitzung_logisch, signatur):
        return "in_pruefung"
    urteil = _juengstes_urteil(laeufe, sitzung_logisch, signatur)
    return urteil["ergebnis"] if urteil else "offen"


def _lauf_umfasst(laufend: list[dict], sitzung_logisch, signatur: str) -> bool:
    for lauf in laufend or []:
        if signatur not in lauf.get("signaturen", []):
            continue
        if lauf.get("sitzung_logisch") == sitzung_logisch or lauf.get("scope") == "fehlerbild":
            return True
    return False


def _juengstes_urteil(laeufe: list[dict], sitzung_logisch, signatur: str) -> dict | None:
    """C5: das juengste `pruefung`-Ereignis je (sitzung_logisch, signatur) gewinnt."""
    treffer = [
        (lauf.get("gestartet", ""), u) for lauf in laeufe or []
        if lauf.get("sitzung_logisch") == sitzung_logisch
        for u in lauf.get("urteile", []) if u.get("signatur") == signatur
    ]
    return max(treffer, key=lambda t: t[0])[1] if treffer else None


def gruppen_status(befunde_gruppe: list[dict], entscheide: list[dict], laeufe: list[dict], laufend: list[dict]) -> str:
    """C2 Gruppenstatus: hoechster Rang unter den Einzelstatus einer Regel-Gruppe (via
    `contracts.gruppenstatus`)."""
    status_liste = [status_fuer(b, entscheide, laeufe, laufend) for b in befunde_gruppe]
    return contracts.gruppenstatus(status_liste)


# ---------------------------------------------------------------------------------------------
# C3 -- Stufen und Eskalation
# ---------------------------------------------------------------------------------------------

WIEDERKEHREND_TAGE = 30
WIEDERKEHREND_SCHWELLE = 3

# Plan 4.3 "Pflicht-Codex (nie Ausnahme)": diese Gruende erzwingen IMMER Stufe 2, auch wenn die
# Kleinfehler-Ausnahme (C3) sonst zutraefe. Dokumentations-Konstante -- `stufe_fuer` implementiert
# jeden Grund als eigenen Zweig.
PFLICHT_CODEX_GRUENDE = (
    "schwere_warnung_oder_hoch", "wiederkehrend_ab_3_sitzungen", "rueckfall",
    "cost_spike", "scope_fehlerbild", "stufe1_komplex_oder_unklar", "eskaliert",
)


def _iso_oder_none(wert) -> datetime | None:
    try:
        return datetime.fromisoformat(wert) if wert else None
    except ValueError:
        return None


def _historie_signatur(historie: list[dict], signatur: str, tage: int | None) -> list[dict]:
    """Urteile fuer `signatur` aus fruaeheren Laeufen (`historie`, Liste `pruefung/lauf`-Details),
    optional auf die letzten `tage` Tage begrenzt (None = unbegrenzt, fuer die Eskalation)."""
    grenze = datetime.now(timezone.utc) - timedelta(days=tage) if tage else None
    treffer = []
    for lauf in historie or []:
        zeit = _iso_oder_none(lauf.get("gestartet"))
        if zeit is None or (grenze and zeit < grenze):
            continue
        treffer += [
            {**u, "sitzung_logisch": lauf.get("sitzung_logisch")}
            for u in lauf.get("urteile", []) if u.get("signatur") == signatur
        ]
    return treffer


def ist_eskaliert(befund: dict, historie: list[dict]) -> bool:
    """C3 Eskalation: ein frueherer Lauf hat fuer diese Signatur die Zweitmeinung ausgelassen --
    keine 30-Tage-Grenze, "taucht spaeter wieder auf" gilt unbegrenzt."""
    treffer = _historie_signatur(historie, befund["signatur"], tage=None)
    return any(u.get("zweitmeinung") == "ausgelassen" for u in treffer)


def _wiederkehrend(befund: dict, historie: list[dict]) -> bool:
    treffer = _historie_signatur(historie, befund["signatur"], tage=WIEDERKEHREND_TAGE)
    sitzungen = {t["sitzung_logisch"] for t in treffer if t.get("sitzung_logisch") is not None}
    return len(sitzungen) >= WIEDERKEHREND_SCHWELLE


def _kleinfehler_ausnahme(befund: dict, historie: list[dict]) -> bool:
    """Alle vier Bedingungen der Kleinfehler-Ausnahme (C3)."""
    return (
        befund.get("schwere") == "hinweis"
        and befund.get("komplexitaet") == "einfach"
        and not _wiederkehrend(befund, historie)
        and not befund.get("rueckfall", False)
    )


def stufe_fuer(befund: dict, historie: list[dict]) -> int:
    """C3: Stufe 2 ist der Normalfall; nur die Kleinfehler-Ausnahme (alle vier Bedingungen)
    erlaubt Stufe 1. Eskalation, Kostenspitze und Scope `fehlerbild` sowie ein `unklar`-Urteil in
    Stufe 1 erzwingen IMMER Stufe 2 (Plan 4.3, `PFLICHT_CODEX_GRUENDE`). `befund` erwartet:
    signatur, regel, schwere, komplexitaet, urteil_stufe1, scope, rueckfall (bool)."""
    if ist_eskaliert(befund, historie):
        return 2
    if befund.get("regel") == "cost:spike" or befund.get("scope") == "fehlerbild":
        return 2
    if befund.get("urteil_stufe1") == "unklar":
        return 2
    return 1 if _kleinfehler_ausnahme(befund, historie) else 2


# ---------------------------------------------------------------------------------------------
# C5 -- Lauf-Registry (Lauf-Schluessel, Konflikt, Ablauf)
# ---------------------------------------------------------------------------------------------

ABLAUF_MINUTEN = 30


@dataclass
class Lauf:
    lauf_id: str
    scope: str
    schluessel: set[tuple[int | None, str]]
    gestartet: datetime


class LaufKonflikt(RuntimeError):
    """C5: die Signaturmenge des neuen Laufs ueberschneidet sich mit einem laufenden."""

    def __init__(self, bestehender_lauf_id: str):
        super().__init__(f"Lauf {bestehender_lauf_id} laeuft bereits fuer eine dieser Signaturen")
        self.lauf_id = bestehender_lauf_id


_laufend: dict[str, Lauf] = {}
_laufend_lock = threading.Lock()


def schluessel_fuer(scope: str, sitzung_logisch: int | None, signaturen: list[str]) -> set[tuple[int | None, str]]:
    """C5 Lauf-Schluessel: die Menge der (sitzung_logisch, signatur)-Paare, die ein Lauf belegt."""
    if scope == "fehlerbild":
        return {(None, signaturen[0])}
    return {(sitzung_logisch, sig) for sig in signaturen}


def _neue_lauf_id(jetzt: datetime | None = None) -> str:
    jetzt = jetzt or datetime.now(timezone.utc)
    return f"p-{jetzt:%Y%m%d}-{jetzt:%H%M%S}-{secrets.token_hex(2)}"


def _bereinigen(jetzt: datetime) -> None:
    """Ablauf-Regel (C5): ein Lauf > 30 min blockiert keine neuen Laeufe mehr."""
    grenze = jetzt - timedelta(minutes=ABLAUF_MINUTEN)
    for lauf_id in [lid for lid, l in _laufend.items() if l.gestartet < grenze]:
        del _laufend[lauf_id]


def registrieren(lauf_id: str, scope: str, schluessel: set, jetzt: datetime | None = None) -> str | None:
    """Registriert `lauf_id`, wenn keine Ueberschneidung mit einem laufenden Lauf vorliegt.
    None = erfolgreich; sonst die lauf_id des ueberschneidenden Laufs (409-Grundlage)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    with _laufend_lock:
        _bereinigen(jetzt)
        for bestehender in _laufend.values():
            if bestehender.schluessel & schluessel:
                return bestehender.lauf_id
        _laufend[lauf_id] = Lauf(lauf_id, scope, schluessel, jetzt)
    return None


def freigeben(lauf_id: str) -> None:
    with _laufend_lock:
        _laufend.pop(lauf_id, None)


def ist_registriert(lauf_id: str) -> dict | None:
    """C5 GET /api/pruefung/{lauf_id}: Registry-Eintrag (seit) oder None, wenn nicht (mehr)
    laufend (auch nach Ablauf, siehe `_bereinigen`)."""
    with _laufend_lock:
        _bereinigen(datetime.now(timezone.utc))
        lauf = _laufend.get(lauf_id)
        return {"seit": lauf.gestartet.isoformat()} if lauf else None


def _lauf_uebersicht_zeile(lauf: Lauf) -> dict:
    sitzungen = {s for s, _ in lauf.schluessel}
    return {
        "lauf_id": lauf.lauf_id, "scope": lauf.scope,
        "sitzung_logisch": next(iter(sitzungen)) if len(sitzungen) == 1 else None,
        "signaturen": sorted({sig for _, sig in lauf.schluessel}),
        "seit": lauf.gestartet.isoformat(),
    }


def laufend_uebersicht() -> list[dict]:
    """C5 `pruefung_laeuft`: Liste der aktuell laufenden Laeufe."""
    with _laufend_lock:
        _bereinigen(datetime.now(timezone.utc))
        return [_lauf_uebersicht_zeile(l) for l in _laufend.values()]


# ---------------------------------------------------------------------------------------------
# Prompts + Parser (Stufe 1 Claude, Stufe 2 Codex) -- erweitert vieraugen.py, nie Rohtext
# ---------------------------------------------------------------------------------------------

def prompt_stufe1(dokument: dict, signaturen: list[str]) -> str:
    """C3 Stufe 1: erweitert `vieraugen.prompt` um kategorie/komplexitaet/empfehlung je Signatur."""
    return (
        "Du pruefst Befunde eines Sitzungsbelegs (nur Kennzahlen/Signaturen, keine Inhalte).\n"
        "Beurteile NUR diese Signaturen: " + ", ".join(signaturen) + ".\n"
        "Fuer jede: kurze Kategorie, Komplexitaet 'einfach'|'komplex', kurze Empfehlung, Urteil "
        "ja|nein|unklar (ist der Befund ein echtes Problem?).\n"
        "Antworte NUR mit einem JSON-Array:\n"
        '[{"signatur": "<signatur>", "kategorie": "<kurz>", "komplexitaet": "einfach|komplex", '
        '"empfehlung": "<kurz>", "urteil": "ja|nein|unklar"}]\n\n'
        "Beleg:\n" + json.dumps(dokument, ensure_ascii=False, indent=1)
    )


def prompt_stufe2(dokument: dict, stufe1_urteile: list[dict]) -> str:
    """C3 Stufe 2 (Codex): bekommt NIE Rohtext -- nur redigierten Beleg + redigierte Stufe-1-
    Ausgabe (Codex-rote-Linie 1, wie `vieraugen.py`)."""
    return (
        "Du bist die unabhaengige Zweitmeinung zu einer Ersteinordnung eines Sitzungsbelegs.\n"
        "Stufe-1-Einordnung:\n" + json.dumps(stufe1_urteile, ensure_ascii=False, indent=1) + "\n\n"
        "Beleg:\n" + json.dumps(dokument, ensure_ascii=False, indent=1) + "\n\n"
        "Antworte NUR mit einem JSON-Array:\n"
        '[{"signatur": "<signatur>", "urteil": "ja|nein|unklar", "begruendung": "<max 80 Zeichen>"}]\n'
    )


def _json_array(text: str) -> list:
    treffer = re.search(r"\[.*\]", text, re.DOTALL)
    if not treffer:
        return []
    try:
        roh = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return []
    return roh if isinstance(roh, list) else []


def _kuerzen(wert, max_laenge: int = contracts.MAX_TEXT) -> str:
    if not wert:
        return ""
    return redaktion.bereinige_text(str(wert)[:max_laenge])


def _stufe1_urteil_normiert(u: dict) -> dict:
    urteil = str(u.get("urteil", "unklar")).lower()
    komplexitaet = str(u.get("komplexitaet", "komplex")).lower()
    return {
        "signatur": _kuerzen(u.get("signatur"), 200), "kategorie": _kuerzen(u.get("kategorie")),
        "komplexitaet": komplexitaet if komplexitaet in ("einfach", "komplex") else "komplex",
        "empfehlung": _kuerzen(u.get("empfehlung")),
        "urteil": urteil if urteil in vieraugen.ZUSTIMMUNGEN else "unklar",
    }


def urteile_stufe1_aus_text(text: str) -> list[dict]:
    """Robuster Parser wie `vieraugen.urteile_aus_text`: unbekannte/fehlende Felder -> sichere
    Defaults (`komplexitaet` fehlt -> 'komplex', NIE 'einfach' -- das erzwingt im Zweifel Stufe 2)."""
    return [_stufe1_urteil_normiert(u) for u in _json_array(text) if isinstance(u, dict) and u.get("signatur")]


def urteile_stufe2_aus_text(text: str) -> list[dict]:
    urteile = []
    for u in _json_array(text):
        if not isinstance(u, dict) or not u.get("signatur"):
            continue
        urteil = str(u.get("urteil", "unklar")).lower()
        urteile.append({
            "signatur": _kuerzen(u.get("signatur"), 200),
            "urteil": urteil if urteil in vieraugen.ZUSTIMMUNGEN else "unklar",
            "begruendung": _kuerzen(u.get("begruendung")),
        })
    return urteile


# ---------------------------------------------------------------------------------------------
# Lauf-Ausfuehrung (C4 `pruefung/lauf`)
# ---------------------------------------------------------------------------------------------

def _ergebnis(claude: str, codex: str | None) -> str:
    if codex is None:
        return {"ja": "bestaetigt", "nein": "verworfen"}.get(claude, "verworfen")
    if claude == codex and claude in ("ja", "nein"):
        return {"ja": "bestaetigt", "nein": "verworfen"}[claude]
    return "dissens"


def _urteil_zeile(u1: dict, u2: dict | None, eskaliert: bool, lauf_id: str) -> dict:
    claude = u1.get("urteil", "unklar")
    codex = u2.get("urteil") if u2 else None
    return {
        "signatur": u1["signatur"], "kategorie": u1.get("kategorie", ""),
        "komplexitaet": u1.get("komplexitaet", "einfach"), "empfehlung": u1.get("empfehlung", ""),
        "claude": claude, "codex": codex, "ergebnis": _ergebnis(claude, codex),
        "zweitmeinung": "eingeholt" if u2 else "ausgelassen", "eskaliert": eskaliert,
        "begruendung_codex": (u2 or {}).get("begruendung", ""),
        # Nachtrag 2026-08-27 Punkt 2: der erzeugende Lauf, damit `_juengstes_urteil` (a.pruefung)
        # "Codex nachholen" mit echtem `{stufe:2, lauf_ref: lauf_id}` bestuecken kann.
        "lauf_id": lauf_id,
    }


def _auffaelligkeit_fuer(beleg, signatur: str):
    for a in beleg.auffaelligkeiten:
        if a.signatur == signatur:
            return a
    return None


def _befund_fuer_stufe(beleg, body, sig: str, u1: dict) -> dict:
    auff = _auffaelligkeit_fuer(beleg, sig)
    return {
        "signatur": sig, "regel": auff.regel if auff else "", "schwere": auff.schwere if auff else "hoch",
        "komplexitaet": u1.get("komplexitaet"), "urteil_stufe1": u1.get("urteil"),
        "scope": body.scope, "rueckfall": False,  # Rueckfall-Bezug folgt mit Welle-2-Historie (Agent A)
    }


def _stufe1_fallback(signatur: str) -> dict:
    return {"signatur": signatur, "kategorie": "", "komplexitaet": "komplex", "empfehlung": "", "urteil": "unklar"}


def _stufe1_urteile(beleg, signaturen: list[str], frager_claude) -> dict[str, dict]:
    dokument = vieraugen.dokument_kompakt(beleg)
    urteile = urteile_stufe1_aus_text(frager_claude(prompt_stufe1(dokument, signaturen)))
    je_signatur = {u["signatur"]: u for u in urteile}
    # "signatur" immer auf den ECHTEN Wert zwingen -- ein Modell koennte ihn kuerzen/vertippen.
    return {sig: {**je_signatur.get(sig, _stufe1_fallback(sig)), "signatur": sig} for sig in signaturen}


def _stufen_je_signatur(beleg, body, signaturen: list[str], stufe1: dict, historie: list[dict]) -> dict[str, tuple]:
    ergebnis = {}
    for sig in signaturen:
        befund = _befund_fuer_stufe(beleg, body, sig, stufe1[sig])
        ergebnis[sig] = (stufe_fuer(befund, historie), ist_eskaliert(befund, historie))
    return ergebnis


def _stufe2_urteile(dokument: dict, signaturen_stufe2: list[str], stufe1: dict, frager_codex) -> dict[str, dict]:
    if not signaturen_stufe2:
        return {}
    stufe1_ausgabe = [stufe1[sig] for sig in signaturen_stufe2]
    urteile = urteile_stufe2_aus_text(frager_codex(prompt_stufe2(dokument, stufe1_ausgabe)))
    je_signatur = {u["signatur"]: u for u in urteile}
    fallback = {"urteil": "unklar", "begruendung": ""}
    return {sig: {**je_signatur.get(sig, fallback), "signatur": sig} for sig in signaturen_stufe2}


def _lauf_detail(lauf_id: str, body, signaturen: list[str], urteile: list[dict],
                  signaturen_stufe2: list[str], gestartet: datetime) -> dict:
    dauer_ms = int((datetime.now(timezone.utc) - gestartet).total_seconds() * 1000)
    return {
        "schema": 1, "lauf_id": lauf_id, "scope": body.scope, "sitzung_logisch": body.sitzung_logisch,
        "signaturen": signaturen, "stufe_max": 2 if signaturen_stufe2 else 1,
        "modell_stufe1": MODELL_STUFE1, "modell_stufe2": MODELL_STUFE2 if signaturen_stufe2 else None,
        "gestartet": gestartet.isoformat(), "dauer_ms": dauer_ms, "urteile": urteile, "fehler": None,
    }


def _signaturen_stufe2(body, signaturen: list[str], stufen: dict[str, tuple]) -> list[str]:
    """C3/C5 "Codex nachholen": `stufe: 2` im Body (mit `lauf_ref`, Contract-Validator) erzwingt
    Stufe 2 fuer diesen Lauf, unabhaengig von der Kleinfehler-Ausnahme -- Nachtrag 2026-08-27
    Punkt 2, sonst konnte "Codex nachholen" die Ausnahme erneut treffen und Codex ueberspringen."""
    if body.stufe == 2:
        return list(signaturen)
    return [s for s in signaturen if stufen[s][0] == 2]


def _lauf_kern(lauf_id, body, beleg, signaturen, gestartet, historie, frager_claude, frager_codex) -> dict:
    dokument = vieraugen.dokument_kompakt(beleg)
    stufe1 = _stufe1_urteile(beleg, signaturen, frager_claude)
    stufen = _stufen_je_signatur(beleg, body, signaturen, stufe1, historie)
    signaturen_stufe2 = _signaturen_stufe2(body, signaturen, stufen)
    stufe2 = _stufe2_urteile(dokument, signaturen_stufe2, stufe1, frager_codex)
    urteile = [
        _urteil_zeile(stufe1[s], stufe2.get(s) if s in signaturen_stufe2 else None, stufen[s][1], lauf_id)
        for s in signaturen
    ]
    return _lauf_detail(lauf_id, body, signaturen, urteile, signaturen_stufe2, gestartet)


def _signaturen_und_beleg(body, beleg_laden, entscheide: list[dict]):
    """scope='befund' oder explizite Signaturliste: genau diese. scope='sitzung' ohne Liste:
    alle offenen (Beleg-Auffaelligkeiten minus entschiedene Signaturen, `befunde.py`)."""
    beleg = beleg_laden(body.sitzung_logisch)
    if body.scope == "befund" or body.signaturen:
        return list(body.signaturen), beleg
    alle = {a.signatur for a in beleg.auffaelligkeiten if a.signatur}
    entschieden = befunde.entschiedene_signaturen(entscheide, body.sitzung_logisch)
    return sorted(alle - entschieden), beleg


# ---------------------------------------------------------------------------------------------
# Scope `fehlerbild` (C3/C4, Nachtrag 2026-08-27 Punkt 3): eine Signatur ueber alle betroffenen
# Sitzungen -- Rechenkern in `fehlerbild_pruefung.py` (eigenes Modul, Datei>800-Waechter), hier
# nur die Registrierung/Sperre (C5), wie `_lauf_registriert_ausfuehren` fuer befund/sitzung.
# ---------------------------------------------------------------------------------------------

def _fehlerbild_registriert_ausfuehren(lauf_id, body, gestartet, sitzungen_finder, beleg_laden,
                                        frager_claude, frager_codex, datei_schreiben) -> dict:
    signatur = body.signaturen[0]
    bestehender = registrieren(lauf_id, "fehlerbild", schluessel_fuer("fehlerbild", None, [signatur]), gestartet)
    if bestehender is not None:
        raise LaufKonflikt(bestehender)
    try:
        return fehlerbild_pruefung.fehlerbild_ausfuehren(
            lauf_id, signatur, gestartet, sitzungen_finder, beleg_laden, frager_claude, frager_codex, datei_schreiben
        )
    except Exception as fehler:  # Fremdprozess (claude/codex) oder Datei-Schreibfehler
        return _fehler_ereignis(lauf_id, body, gestartet, f"{type(fehler).__name__}: {fehler}")
    finally:
        freigeben(lauf_id)


def _fehler_ereignis(lauf_id: str, body, gestartet: datetime, fehlertext: str) -> dict:
    signaturen = [] if body.scope == "sitzung" else list(body.signaturen)
    dauer_ms = int((datetime.now(timezone.utc) - gestartet).total_seconds() * 1000)
    return {
        "schema": 1, "lauf_id": lauf_id, "scope": body.scope, "sitzung_logisch": body.sitzung_logisch,
        "signaturen": signaturen, "stufe_max": 1, "modell_stufe1": MODELL_STUFE1, "modell_stufe2": None,
        "gestartet": gestartet.isoformat(), "dauer_ms": dauer_ms, "urteile": [],
        "fehler": _kuerzen(fehlertext),
    }


def _lauf_registriert_ausfuehren(lauf_id, body, beleg_laden, entscheide, historie, gestartet,
                                  frager_claude, frager_codex) -> dict:
    try:
        signaturen, beleg = _signaturen_und_beleg(body, beleg_laden, entscheide)
    except Exception as fehler:  # Beleg-Lader: Sitzung fehlt/DB down -- Lauf endet als Fehler
        return _fehler_ereignis(lauf_id, body, gestartet, f"{type(fehler).__name__}: {fehler}")
    schluessel = schluessel_fuer(body.scope, body.sitzung_logisch, signaturen)
    bestehender = registrieren(lauf_id, body.scope, schluessel, gestartet)
    if bestehender is not None:
        raise LaufKonflikt(bestehender)
    try:
        return _lauf_kern(lauf_id, body, beleg, signaturen, gestartet, historie, frager_claude, frager_codex)
    except Exception as fehler:  # Fremdprozess (claude/codex): jeder Fehler wird berichtet
        return _fehler_ereignis(lauf_id, body, gestartet, f"{type(fehler).__name__}: {fehler}")
    finally:
        freigeben(lauf_id)


def _fehlerbild_starten(lauf_id: str, body, gestartet: datetime, beleg_laden) -> dict:
    """`beleg_laden` wandert nur durch den Kontext weiter -- Phase 2 (`lauf_beenden`) laeuft im
    Hintergrund-Thread und bekommt von web.py sonst keinen Beleg-Lader mitgegeben (bei
    befund/sitzung ist der Beleg da schon geladen, in `kontext['beleg']`)."""
    signatur = body.signaturen[0]
    bestehender = registrieren(lauf_id, "fehlerbild", schluessel_fuer("fehlerbild", None, [signatur]), gestartet)
    if bestehender is not None:
        raise LaufKonflikt(bestehender)
    return {"gestartet": gestartet, "fehlerbild": True, "signatur": signatur, "beleg_laden": beleg_laden}


def lauf_starten(body, beleg_laden, entscheide: list[dict] | None = None) -> tuple[str, dict]:
    """Phase 1 (synchron, C5): Beleg laden, Schluessel registrieren. Liefert (lauf_id, kontext).
    Wirft LaufKonflikt (409) oder den Fehler des Beleg-Laders (web.py macht daraus 404/500)."""
    lauf_id, gestartet = _neue_lauf_id(), datetime.now(timezone.utc)
    if body.scope == "fehlerbild":
        return lauf_id, _fehlerbild_starten(lauf_id, body, gestartet, beleg_laden)
    signaturen, beleg = _signaturen_und_beleg(body, beleg_laden, entscheide or [])
    bestehender = registrieren(lauf_id, body.scope, schluessel_fuer(body.scope, body.sitzung_logisch, signaturen), gestartet)
    if bestehender is not None:
        raise LaufKonflikt(bestehender)
    return lauf_id, {"gestartet": gestartet, "signaturen": signaturen, "beleg": beleg}


def _fehlerbild_beenden(lauf_id, body, kontext, sitzungen_finder, frager_claude, frager_codex, datei_schreiben) -> dict:
    try:
        return _fehlerbild_ausfuehren(lauf_id, kontext["signatur"], kontext["gestartet"], sitzungen_finder,
                                       kontext["beleg_laden"], frager_claude, frager_codex, datei_schreiben)
    except Exception as fehler:  # Fremdprozess (claude/codex) oder Datei-Schreibfehler
        return _fehler_ereignis(lauf_id, body, kontext["gestartet"], f"{type(fehler).__name__}: {fehler}")
    finally:
        freigeben(lauf_id)


def _sitzung_lauf_beenden(lauf_id, body, kontext, frager_claude, frager_codex, historie) -> dict:
    try:
        return _lauf_kern(lauf_id, body, kontext["beleg"], kontext["signaturen"], kontext["gestartet"],
                          historie or [], frager_claude, frager_codex)
    except Exception as fehler:  # Fremdprozess (claude/codex): berichten, nie verschlucken
        return _fehler_ereignis(lauf_id, body, kontext["gestartet"], f"{type(fehler).__name__}: {fehler}")
    finally:
        freigeben(lauf_id)


def lauf_beenden(lauf_id: str, body, kontext: dict, frager_claude, frager_codex,
                 ereignis_schreiben, historie: list[dict] | None = None,
                 sitzungen_finder=sitzungen_fuer_signatur, datei_schreiben=datei_schreiben_real) -> dict:
    """Phase 2 (Hintergrund-Thread): Stufe 1 (+2), genau ein `pruefung/lauf`-Ereignis, Freigabe.
    `sitzungen_finder`/`datei_schreiben` gelten nur fuer Scope `fehlerbild` (Default = echtes
    SQL/echte Datei -- `beleg_laden` kommt fuer diesen Scope stattdessen aus `kontext`, siehe
    `_fehlerbild_starten`, `web.py` muss dafuer nichts Zusaetzliches durchreichen)."""
    if kontext.get("fehlerbild"):
        detail = _fehlerbild_beenden(lauf_id, body, kontext, sitzungen_finder, frager_claude, frager_codex, datei_schreiben)
    else:
        detail = _sitzung_lauf_beenden(lauf_id, body, kontext, frager_claude, frager_codex, historie)
    ereignis_schreiben("pruefung", "lauf", detail)
    return detail


def _lauf_detail_ohne_registry(body, beleg_laden, entscheide, historie, gestartet,
                                frager_claude, frager_codex, lauf_id: str,
                                sitzungen_finder=sitzungen_fuer_signatur,
                                datei_schreiben=datei_schreiben_real) -> dict:
    if body.scope == "fehlerbild":
        return _fehlerbild_registriert_ausfuehren(
            lauf_id, body, gestartet, sitzungen_finder, beleg_laden, frager_claude, frager_codex, datei_schreiben
        )
    return _lauf_registriert_ausfuehren(
        lauf_id, body, beleg_laden, entscheide, historie, gestartet, frager_claude, frager_codex
    )


def lauf_ausfuehren(
    body: contracts.PruefungBody, beleg_laden,
    frager_claude=vieraugen.frage_claude, frager_codex=vieraugen.frage_codex,
    ereignis_schreiben=speicher.ereignis_schreiben,
    *, entscheide: list[dict] | None = None, historie: list[dict] | None = None,
    sitzungen_finder=sitzungen_fuer_signatur, datei_schreiben=datei_schreiben_real,
) -> dict:
    """C4/C5: fuehrt Stufe 1 (+2) aus, schreibt GENAU EIN `pruefung/lauf`-Ereignis (auch bei
    Fehler: `fehler` gesetzt, `urteile` leer). Wirft `LaufKonflikt` bei ueberlappender
    Signaturmenge (web.py macht daraus 409). `entscheide`/`historie`: Default leer.
    `sitzungen_finder`/`datei_schreiben`: nur fuer Scope `fehlerbild` gebraucht (C3)."""
    lauf_id, gestartet = _neue_lauf_id(), datetime.now(timezone.utc)
    detail = _lauf_detail_ohne_registry(
        body, beleg_laden, entscheide or [], historie or [], gestartet, frager_claude, frager_codex, lauf_id,
        sitzungen_finder=sitzungen_finder, datei_schreiben=datei_schreiben,
    )
    ereignis_schreiben("pruefung", "lauf", detail)
    return detail


# ---------------------------------------------------------------------------------------------
# Anreicherung von GET /api/sitzung/{id} (C5)
# ---------------------------------------------------------------------------------------------

def _vieraugen_ergebnis(status: str) -> str:
    """C2 Schritt 3 (Nachtrag 2026-08-27 Punkt 1): 'unklar' zaehlt wie 'dissens' -- ein Legacy-
    Vier-Augen-Urteil ohne Einigung ist genauso handlungsrelevant wie ein Dissens aus `pruefung`."""
    return "dissens" if status == "unklar" else status


def vieraugen_als_laeufe(ereignisse: list[dict], sitzung_logisch_fallback: int | None = None) -> list[dict]:
    """C1 Regel 2 (Legacy-Leseregel) + Nachtrag 2026-08-27 Punkt 1: normalisiert Alt-
    `vieraugen/review`-Ereignisse (Feld `befunde`, Werte `bestaetigt|verworfen|unklar|dissens`) in
    die `laeufe`-Form von `status_fuer`/`_juengstes_urteil` (Feld `urteile` mit `ergebnis`). Ohne
    diese Bruecke blieb eine Gruppe mit ausschliesslich einem Legacy-Urteil dauerhaft `offen`
    (live an Sitzung 137 verifiziert). Kein echter Zeitstempel im Alt-Ereignis -- Sentinel `""`,
    ein echter `pruefung`-Lauf mit ISO-Zeitstempel gewinnt bei Ueberschneidung darum immer."""
    return [
        {
            "sitzung_logisch": ev.get("sitzung_logisch", sitzung_logisch_fallback),
            "gestartet": "",
            "urteile": [
                {"signatur": b.get("signatur") or b.get("regel", ""), "ergebnis": _vieraugen_ergebnis(b.get("status", "unklar"))}
                for b in ev.get("befunde", []) if b.get("signatur") or b.get("regel")
            ],
        }
        for ev in ereignisse or []
    ]


def _anreichern_auffaelligkeit(a: dict, sitzung_logisch, entscheide, laeufe, laeufe_status, laufend) -> None:
    befund = {"signatur": a.get("signatur", ""), "sitzung_logisch": sitzung_logisch}
    a["status"] = status_fuer(befund, entscheide, laeufe_status, laufend)
    a["pruefung"] = _juengstes_urteil(laeufe, sitzung_logisch, befund["signatur"])


def _gruppen_status_je_regel(auffaelligkeiten, entscheide, laeufe, laufend, sitzung_logisch) -> dict:
    je_regel: dict[str, list[dict]] = {}
    for a in auffaelligkeiten:
        je_regel.setdefault(a.get("regel", ""), []).append(
            {"signatur": a.get("signatur", ""), "sitzung_logisch": sitzung_logisch}
        )
    return {regel: gruppen_status(gruppe, entscheide, laeufe, laufend) for regel, gruppe in je_regel.items()}


def anreichern(antwort: dict, ereignisse_laden) -> dict:
    """C5 GET /api/sitzung/{id}: ergaenzt `status`+`pruefung` je Auffaelligkeit, `gruppen_status`,
    `pruefung_laeuft`, `zulaessigkeit`. `ereignisse_laden(quelle)` liefert die rohen
    `ereignis.detail`-Zeilen einer Quelle ('gf' -> befund_entscheid, 'pruefung' -> lauf).
    `status`/`gruppen_status` beziehen zusaetzlich das bereits geladene `antwort['vieraugen']`
    (Legacy-Urteil dieser Sitzung, C1 Regel 2) ein -- `pruefung` je Auffaelligkeit (Detailanzeige
    Vier-Augen inline) bleibt bewusst NUR aus echten `pruefung`-Laeufen, das Frontend hat dafuer
    einen eigenen Alt-Fallback (`pruefungAusAlt`, `sitzung.js`)."""
    entscheide, laeufe = ereignisse_laden("gf"), ereignisse_laden("pruefung")
    sitzung_logisch = antwort.get("sitzung_logisch")
    vieraugen = [antwort["vieraugen"]] if antwort.get("vieraugen") else []
    laeufe_status = laeufe + vieraugen_als_laeufe(vieraugen, sitzung_logisch)
    laufend = laufend_uebersicht()
    auffaelligkeiten = antwort.get("dokument", {}).get("auffaelligkeiten", [])
    for a in auffaelligkeiten:
        _anreichern_auffaelligkeit(a, sitzung_logisch, entscheide, laeufe, laeufe_status, laufend)
    antwort["gruppen_status"] = _gruppen_status_je_regel(auffaelligkeiten, entscheide, laeufe_status, laufend, sitzung_logisch)
    antwort["pruefung_laeuft"] = [l for l in laufend if l["sitzung_logisch"] == sitzung_logisch]
    antwort["zulaessigkeit"] = redaktion.zulaessigkeit(antwort.get("dokument", {}))
    return antwort
