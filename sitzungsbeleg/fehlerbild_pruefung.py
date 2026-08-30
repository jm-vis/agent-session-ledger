"""Scope `fehlerbild` (C3/C4, Nachtrag 2026-08-27 Punkt 3): eine Signatur ueber alle betroffenen
Sitzungen der letzten `WIEDERKEHREND_TAGE` Tage, Stufe 1 (Claude) + Stufe 2 (Codex, Pflicht)
ordnen je Sitzung sauber|abgewichen|halluziniert ein, Ergebnis + Standardisierungs-Vorschlag als
Datei (C4: `sitzungen`/`tabelle`/`datei` im `pruefung/lauf`-Ereignis).

Eigenes Modul statt in `pruefung.py` (Datei>800-Waechter, `check-code-masse.ps1`) -- `pruefung.py`
importiert es und bindet `_fehlerbild_ausfuehren`/`sitzungen_fuer_signatur`/`datei_schreiben_real`
in seine Lauf-Registrierung/-Sperre ein (`_fehlerbild_registriert_ausfuehren`). Bewusst KEINE
Abhaengigkeit zurueck zu `pruefung.py` (kein Zirkelimport) -- kleine Konstanten/Helfer sind darum
dupliziert statt importiert, wie `vieraugen.py`s eigener Parser neben `pruefung.py`s Stufe-1/2-
Parsern.

Injizierbar wie der Rest des Pakets (`sitzungen_finder`/`beleg_laden`/`frager_*`/`datei_schreiben`)
-- `sitzungen_fuer_signatur`/`datei_schreiben_real` sind die einzigen Stellen hier, die echtes
SQL/echte Dateisystemzugriffe machen (Defaults, ueberschreibbar in Tests)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import contracts, redaktion, schluessel, speicher, vieraugen

MODELL_STUFE1 = "claude-sonnet-5"  # gleich wie pruefung.MODELL_STUFE1 (kein Zirkelimport)
MODELL_STUFE2 = "gpt-5.5"  # gleich wie pruefung.MODELL_STUFE2
WIEDERKEHREND_TAGE = 30  # gleich wie pruefung.WIEDERKEHREND_TAGE (C3 Zeitraum)
EINORDNUNGEN = ("sauber", "abgewichen", "halluziniert")


def _sql_sitzungen_fuer_signatur(signatur: str, tage: int) -> str:
    grenze = (datetime.now(timezone.utc) - timedelta(days=tage)).date().isoformat()
    return (
        "SELECT coalesce(jsonb_agg(DISTINCT logisch_ref), '[]'::jsonb) FROM sitzung_auffaelligkeit a "
        f"JOIN sitzung_aktuell s ON s.logisch_ref = a.logisch_ref WHERE a.signatur = {speicher.sql_literal(signatur)} "
        f"AND coalesce(s.ende, s.start, s.zeitstempel) >= '{grenze}'::date;"
    )


def sitzungen_fuer_signatur(signatur: str, laufer=speicher.psql, tage: int = WIEDERKEHREND_TAGE) -> list[int]:
    """Default `sitzungen_finder`: betroffene logische Sitzungen der letzten `tage` Tage."""
    ausgabe = laufer(_sql_sitzungen_fuer_signatur(signatur, tage))
    return sorted(json.loads(ausgabe)) if ausgabe.strip() else []


def prompt_fehlerbild_stufe1(dokument: dict, signatur: str) -> str:
    return (
        "Du beurteilst EINEN wiederkehrenden Befund (" + signatur + ") in genau einem Sitzungsbeleg.\n"
        "Ordne ein: 'sauber' (kein echtes Problem in dieser Sitzung), 'abgewichen' (Standardprozess "
        "nicht eingehalten), 'halluziniert' (der Befund/das Ergebnis ist erfunden oder durch den "
        "Beleg nicht gedeckt).\n"
        'Antworte NUR mit JSON: {"einordnung": "sauber|abgewichen|halluziniert", "begruendung": "<kurz>"}\n\n'
        "Beleg:\n" + json.dumps(dokument, ensure_ascii=False, indent=1)
    )


def prompt_fehlerbild_stufe2(signatur: str, stufe1_zeilen: list[dict]) -> str:
    """C3 Stufe 2 (Codex, Pflicht fuer `fehlerbild`): bekommt NUR die redigierte Stufe-1-Ausgabe
    je Sitzung (kein Rohtext, keine erneuten Volldokumente -- die Erst-Einordnung traegt schon
    die relevanten Kurzangaben)."""
    zeilen = [{"sitzung_logisch": z["sitzung_logisch"], "einordnung": z["einordnung"], "begruendung": z["begruendung"]} for z in stufe1_zeilen]
    return (
        "Du bist die unabhaengige Zweitmeinung zur Einordnung eines wiederkehrenden Befunds ("
        + signatur + ") ueber mehrere Sitzungen.\n"
        "Erst-Einordnung je Sitzung:\n" + json.dumps(zeilen, ensure_ascii=False, indent=1) + "\n\n"
        "Bestaetige oder korrigiere je Sitzung. Antworte NUR mit einem JSON-Array:\n"
        '[{"sitzung_logisch": <n>, "einordnung": "sauber|abgewichen|halluziniert"}]\n'
    )


def _json_objekt(text: str) -> dict:
    treffer = re.search(r"\{.*\}", text, re.DOTALL)
    if not treffer:
        return {}
    try:
        roh = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return {}
    return roh if isinstance(roh, dict) else {}


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


def _einordnung_normiert(wert) -> str:
    """Unbekannt/fehlend -> 'abgewichen' (sicherer Default: nie automatisch 'sauber', das wuerde
    ein echtes Problem verstecken -- gleiche Vorsicht wie `komplexitaet` fehlt -> 'komplex')."""
    wert = str(wert or "").lower()
    return wert if wert in EINORDNUNGEN else "abgewichen"


def _stufe1_einordnung(beleg_laden, sitzung_logisch: int, signatur: str, frager_claude) -> dict:
    beleg = beleg_laden(sitzung_logisch)
    dokument = vieraugen.dokument_kompakt(beleg)
    antwort = _json_objekt(frager_claude(prompt_fehlerbild_stufe1(dokument, signatur)))
    return {
        "sitzung_logisch": sitzung_logisch,
        "einordnung": _einordnung_normiert(antwort.get("einordnung")),
        "begruendung": _kuerzen(antwort.get("begruendung")),
    }


def _stufe1_je_sitzung(sitzungen: list[int], signatur: str, beleg_laden, frager_claude) -> list[dict]:
    """Eine kaputte Sitzung (Beleg fehlt/DB-Fehler) darf den restlichen Lauf nicht abbrechen --
    sie faellt einfach aus der Tabelle, wie `pruefung._lauf_registriert_ausfuehren`s
    Fehlerbehandlung je Lauf, nur hier je Sitzung."""
    zeilen = []
    for sitzung_logisch in sitzungen:
        try:
            zeilen.append(_stufe1_einordnung(beleg_laden, sitzung_logisch, signatur, frager_claude))
        except Exception:
            continue
    return zeilen


def urteile_fehlerbild_stufe2_aus_text(text: str) -> list[dict]:
    urteile = []
    for u in _json_array(text):
        if not isinstance(u, dict) or "sitzung_logisch" not in u:
            continue
        try:
            sitzung_logisch = int(u["sitzung_logisch"])
        except (TypeError, ValueError):
            continue
        urteile.append({"sitzung_logisch": sitzung_logisch, "einordnung": _einordnung_normiert(u.get("einordnung"))})
    return urteile


def _stufe2_je_sitzung(signatur: str, stufe1_zeilen: list[dict], frager_codex) -> dict[int, str]:
    urteile = urteile_fehlerbild_stufe2_aus_text(frager_codex(prompt_fehlerbild_stufe2(signatur, stufe1_zeilen)))
    return {u["sitzung_logisch"]: u["einordnung"] for u in urteile}


def _fehlerbild_tabelle(sitzungen, signatur, beleg_laden, frager_claude, frager_codex) -> tuple[list[dict], list[dict]]:
    stufe1_zeilen = _stufe1_je_sitzung(sitzungen, signatur, beleg_laden, frager_claude)
    stufe2 = _stufe2_je_sitzung(signatur, stufe1_zeilen, frager_codex) if stufe1_zeilen else {}
    tabelle = [
        {"sitzung_logisch": z["sitzung_logisch"], "einordnung": stufe2.get(z["sitzung_logisch"], z["einordnung"])}
        for z in stufe1_zeilen
    ]
    return tabelle, stufe1_zeilen


def _dateiname_sicher(signatur: str) -> str:
    sicher = re.sub(r"[^a-zA-Z0-9_.:-]", "_", signatur)[:80]
    return sicher or "signatur"


def _standardisierungsdatei_pfad(signatur: str, jetzt: datetime) -> str:
    """Ablageort relativ zum Arbeitsverzeichnis -- konfigurierbar (SITZUNGSBELEG_WORK_DIR), damit
    das nicht an eine feste Vault-Struktur gebunden ist; Default `_work` (Forward-Slash, auch
    unter Windows -- das Ergebnis landet in einem `pruefung/lauf`-Ereignis, keinem OS-Pfad)."""
    basis = schluessel.lese("SITZUNGSBELEG_WORK_DIR") or "_work"
    return f"{basis}/{jetzt:%Y-%m-%d}-standardisierung-{_dateiname_sicher(signatur)}.md"


def _verteilung_zeilen(tabelle: list[dict]) -> dict[str, int]:
    verteilung: dict[str, int] = {}
    for t in tabelle:
        verteilung[t["einordnung"]] = verteilung.get(t["einordnung"], 0) + 1
    return verteilung


def _standardisierungsdatei_inhalt(signatur: str, tabelle: list[dict], stufe1_zeilen: list[dict]) -> str:
    """Nur redigierte/kuratierte Saetze aus den Modell-Urteilen (`begruendung` bereits durch
    `_kuerzen`/`redaktion.bereinige_text` gelaufen) -- nie Rohtext (Auftragsregel)."""
    begruendung_je_sitzung = {z["sitzung_logisch"]: z.get("begruendung", "") for z in stufe1_zeilen}
    verteilung = ", ".join(f"{k}={v}" for k, v in _verteilung_zeilen(tabelle).items())
    kopf = [
        f"# Standardisierungs-Vorschlag — {signatur}", "",
        f"Automatisch erzeugt aus {len(tabelle)} Sitzungen (Scope `fehlerbild`, Stufe 1+2). "
        "Ausgangspunkt fuer Maintainer, kein Rohtext.", "", f"Verteilung: {verteilung}", "",
        "| Sitzung | Einordnung | Begruendung |", "| --- | --- | --- |",
    ]
    zeilen = [
        f"| {t['sitzung_logisch']} | {t['einordnung']} | {begruendung_je_sitzung.get(t['sitzung_logisch'], '')} |"
        for t in tabelle
    ]
    return "\n".join(kopf + zeilen) + "\n"


def _repo_wurzel() -> Path:
    return Path(__file__).resolve().parents[2]


def datei_schreiben_real(pfad_relativ: str, inhalt: str, basis: Path | None = None) -> str:
    """Default `datei_schreiben`: schreibt relativ zur Repo-Wurzel (`basis`, fuer Tests
    ueberschreibbar), legt Zielordner bei Bedarf an."""
    ziel = (basis or _repo_wurzel()) / pfad_relativ
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(inhalt, encoding="utf-8")
    return pfad_relativ


def _fehlerbild_leer(lauf_id: str, signatur: str, gestartet: datetime) -> dict:
    dauer_ms = int((datetime.now(timezone.utc) - gestartet).total_seconds() * 1000)
    return {
        "schema": 1, "lauf_id": lauf_id, "scope": "fehlerbild", "sitzung_logisch": None,
        "signaturen": [signatur], "stufe_max": 1, "modell_stufe1": MODELL_STUFE1, "modell_stufe2": None,
        "gestartet": gestartet.isoformat(), "dauer_ms": dauer_ms, "urteile": [],
        "fehler": f"keine Sitzungen mit Signatur {signatur} im Zeitraum ({WIEDERKEHREND_TAGE} Tage)",
    }


def _fehlerbild_detail(lauf_id: str, signatur: str, tabelle: list[dict], pfad: str, gestartet: datetime) -> dict:
    dauer_ms = int((datetime.now(timezone.utc) - gestartet).total_seconds() * 1000)
    return {
        "schema": 1, "lauf_id": lauf_id, "scope": "fehlerbild", "sitzung_logisch": None,
        "signaturen": [signatur], "stufe_max": 2, "modell_stufe1": MODELL_STUFE1, "modell_stufe2": MODELL_STUFE2,
        "gestartet": gestartet.isoformat(), "dauer_ms": dauer_ms, "urteile": [], "fehler": None,
        "sitzungen": [t["sitzung_logisch"] for t in tabelle], "tabelle": tabelle, "datei": pfad,
    }


def fehlerbild_ausfuehren(lauf_id, signatur, gestartet, sitzungen_finder, beleg_laden,
                           frager_claude, frager_codex, datei_schreiben) -> dict:
    """Kern des Scopes `fehlerbild` -- keine Sperre/Registry hier (das macht der Aufrufer,
    `pruefung._fehlerbild_registriert_ausfuehren`)."""
    sitzungen = sitzungen_finder(signatur)
    if not sitzungen:
        return _fehlerbild_leer(lauf_id, signatur, gestartet)
    tabelle, stufe1_zeilen = _fehlerbild_tabelle(sitzungen, signatur, beleg_laden, frager_claude, frager_codex)
    if not tabelle:
        return _fehlerbild_leer(lauf_id, signatur, gestartet)
    pfad = _standardisierungsdatei_pfad(signatur, gestartet)
    datei_schreiben(pfad, _standardisierungsdatei_inhalt(signatur, tabelle, stufe1_zeilen))
    return _fehlerbild_detail(lauf_id, signatur, tabelle, pfad, gestartet)
