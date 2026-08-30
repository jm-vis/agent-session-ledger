"""Dashboard (Stufe 3): FastAPI-App + JSON-Endpunkte fuer static/index.html.

Start: `python -m sitzungsbeleg serve` -- bindet HART auf 127.0.0.1:8091, kein
Parameter fuer andere Hosts (Plan „Sicherheit/Datenschutz" -- Dashboard-Port).
Jede Abfrage laeuft ueber `LAUFER` (Default `speicher.psql`), SQL-Literale nur
ueber `speicher.sql_literal`, int-Parameter nur ueber `int()` -- wie speicher.py
und querschnitt.py. Endpunkte liefern NUR was im Beleg-Dokument steht, nie
Rohinhalt (redaktion.py hat das schon vor dem Speichern durchgesetzt).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    befunde, chat_kennzahlen, contracts, fehlerbilder, kacheln, katalog_sicht, projekte, pruefung,
    quellen, regeltexte, speicher, umgebung as umgebung_achse, version, vieraugen,
)
from .querschnitt import MIN_SITZUNGEN_FEHLER
from .speicher import psql, sql_literal

HOST = "127.0.0.1"
PORT = 8091
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Austauschbar fuer Tests (web.LAUFER = FakeLaufer(...), web.VIERAUGEN_REVIEW = stub).
LAUFER = psql
VIERAUGEN_REVIEW = vieraugen.review
# Pruef-Regelwerk (Phase 1 B): dieselbe Austausch-Konvention -- `pruefung.lauf_ausfuehren` wird
# NIE mit seinen eigenen (echten) Defaults aufgerufen, sondern immer explizit mit diesen beiden
# Modul-Globalen (Tests setzen `web.FRAGER_CLAUDE`/`web.FRAGER_CODEX` um, nie echte Prozesse).
FRAGER_CLAUDE = vieraugen.frage_claude
FRAGER_CODEX = vieraugen.frage_codex

app = FastAPI(title="Sitzungsbeleg")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def _static_no_cache(request, call_next):
    """ES-Module unter /static/js werden per import ohne ?v=-Stempel geladen -- ohne no-cache
    haelt der Browser sie heuristisch tagelang (Abnahme 2026-08-27: Karten-Umbau unsichtbar,
    obwohl auf Platte; gleiche Lektion wie Orb-UI). Lokales Dashboard, Revalidierung ist billig."""
    antwort = await call_next(request)
    if request.url.path.startswith("/static/"):
        antwort.headers["Cache-Control"] = "no-cache"
    return antwort


# ---------- SQL-Bausteine ----------

def _zeitraum(von: date, bis: date, spalte: str = "coalesce(ende, start, zeitstempel)") -> str:
    """Halboffenes Intervall [von, bis] als Tag -- ``bis`` liegt noch VOLL im Filter."""
    return (
        f"{spalte} >= {sql_literal(von.isoformat())}::date "
        f"AND {spalte} < ({sql_literal(bis.isoformat())}::date + 1)"
    )


def _liste(sql: str) -> list:
    ausgabe = LAUFER(sql)
    return json.loads(ausgabe) if ausgabe.strip() else []


def _wert(sql: str):
    ausgabe = LAUFER(sql)
    return json.loads(ausgabe) if ausgabe.strip() else None


# ---------- /api/sitzungen ----------

def _sql_projekt_gleich(projekt: str) -> str:
    """Filterbedingung für `projekt=`: akzeptiert den Alias-Namen und schließt alle
    Rohnamen ein, die per `projekt-aliase.json` darauf zeigen (Belege bleiben roh, der
    Alias gilt nur beim Lesen). Zusammengesetzte Einträge (`<roh>@<quelle>`) werden
    quellenscharf verglichen; die `codex-<x>`-Automatik für nicht gelistete Rohnamen ist
    hier bewusst nicht rückwärts aufgelöst (projekte.roh_eintraege_fuer_projekt)."""
    treffer = projekte.roh_eintraege_fuer_projekt(projekt)
    if len(treffer) == 1 and treffer[0][1] is None:
        return f"projekt = {sql_literal(treffer[0][0])}"
    teile = []
    for roh, quelle in treffer:
        if quelle is None:
            teile.append(f"projekt = {sql_literal(roh)}")
        else:
            teile.append(f"(projekt = {sql_literal(roh)} AND quelle = {sql_literal(quelle)})")
    return "(" + " OR ".join(teile) + ")"


def _sql_nicht_entschieden(signatur_ausdruck: str, sitzung_id_ausdruck: str) -> str:
    """NOT EXISTS-Fragment (Erledigt-Feature, Entscheid 2026-08-26, Auftrag 3):
    `signatur_ausdruck` hat KEINEN wirksamen Entscheid, der global (`sitzung_ref` NULL)
    oder exakt für `sitzung_id_ausdruck` gilt. Wirksam heisst: der JÜNGSTE passende
    Entscheid (`ereignis.typ='befund_entscheid'`) hat Status `erledigt`/`obsolet` --
    der dritte Status `offen` (Wiedereröffnung, Entscheid B 2026-08-26) zaehlt wie
    „kein Entscheid", auch wenn davor schon erledigt/obsolet geschrieben wurde
    („jüngster Entscheid gewinnt")."""
    filter_basis = (
        "be.quelle = 'gf' AND be.typ = 'befund_entscheid' "
        f"AND be.detail->>'signatur' = {signatur_ausdruck} "
        f"AND (be.detail->>'sitzung_ref' IS NULL OR be.detail->>'sitzung_ref' = ({sitzung_id_ausdruck})::text)"
    )
    return (
        "NOT EXISTS (SELECT 1 FROM ereignis be WHERE "
        f"{filter_basis} AND be.detail->>'status' <> 'offen' "
        "AND be.detail->>'entschieden_am' = (SELECT max(be2.detail->>'entschieden_am') "
        f"FROM ereignis be2 WHERE {filter_basis.replace('be.', 'be2.')}))"
    )


def _sql_treffer_spalte(signatur: str | None) -> str:
    """`treffer`-Spalte je Sitzung: Anzahl `tool_ergebnis`-Fehlerereignisse mit exakt
    dieser Signatur -- nur berechnet, wenn `signatur=` gesetzt ist (Fehler-Drilldown)."""
    if not signatur:
        return ""
    return f""",
         coalesce((SELECT count(*) FROM jsonb_array_elements(s.dokument->'ereignisse') e
                    WHERE e->>'art' = 'tool_ergebnis' AND (e->>'fehler')::boolean
                      AND e->>'signatur' = {sql_literal(signatur)}), 0) AS treffer"""


def _sql_sitzungen(
    von: date, bis: date, projekt: str | None, signatur: str | None = None
) -> str:
    """`quelle=` filtert NICHT mehr hier: die angezeigte Quelle ist abgeleitet (Claude/Codex/
    Ollama/Produkt/Unbekannt, Entscheid 2026-08-26, Auftrag 2) und haengt vom Modell ab --
    das laesst sich nicht als einfache SQL-Gleichheit auf der rohen `quelle`-Spalte ausdruecken.
    Filterung passiert in Python, nach `_mit_alias` (siehe api_sitzungen)."""
    bedingung = _zeitraum(von, bis)
    if projekt:
        bedingung += f" AND {_sql_projekt_gleich(projekt)}"
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY coalesce(t.start, t.zeitstempel) DESC), '[]'::jsonb)
FROM (
{_sql_sitzungen_spalten(signatur)}
  FROM sitzung_aktuell s
  WHERE {bedingung}
) t;"""


def _sql_sitzungen_spalten(signatur: str | None) -> str:
    """Spaltenliste der Sitzungs-Zeile (aus `_sql_sitzungen` ausgelagert, Code-Masse 2026-08-28)."""
    return f"""  SELECT s.logisch_ref AS id, s.zeitstempel, s.start, s.projekt, s.quelle,
         coalesce(s.dokument->'kopf'->'modelle', '[]'::jsonb) AS modelle,
         s.dokument->'kopf'->>'backend' AS backend,
         s.dokument->'kopf'->>'umgebung' AS umgebung,
         s.dokument->'kopf'->>'persona' AS persona,
         s.dokument->'kopf'->>'kanal' AS kanal,
         (s.dokument->'kennzahlen'->>'dauer_ms')::bigint AS dauer_ms,
         coalesce((s.dokument->'kennzahlen'->>'runden')::int, 0) AS runden,
         coalesce((s.dokument->'kennzahlen'->>'tools')::int, 0) AS tools,
         coalesce((s.dokument->'kennzahlen'->>'tool_fehler')::int, 0) AS fehler,
         (s.dokument->'kennzahlen'->>'kosten')::numeric AS kosten,
         coalesce((SELECT count(*) FROM jsonb_array_elements(s.dokument->'auffaelligkeiten') af
                    WHERE {_sql_nicht_entschieden("af->>'signatur'", "s.logisch_ref")}), 0) AS anzahl_befunde,
         coalesce((SELECT (v.detail->>'dissens')::int > 0 FROM ereignis v
                    WHERE v.quelle = 'vieraugen' AND v.detail->>'sitzung_ref' = s.id::text
                    ORDER BY v.zeitstempel DESC LIMIT 1), false) AS dissens{_sql_treffer_spalte(signatur)}"""


def _mit_alias(zeilen: list[dict]) -> list[dict]:
    """Ersetzt `projekt` je Zeile durch den Anzeige-Alias, ergänzt `kontext` (Lesepfad,
    Beleg bleibt roh -- projekte.aufloesen()) und ersetzt `quelle` durch die abgeleitete
    Anzeige-Quelle (Claude/Codex/Ollama/OpenRouter/Produkt/Unbekannt, Entscheid 2026-08-26, Auftrag 2)
    -- der rohe Wert wird dafuer VOR dem Überschreiben gelesen. `modelle` (nur Lesepfad) wird
    danach entfernt, das war nie Teil des API-Vertrags."""
    aliase = projekte.lade_aliase()
    for z in zeilen:
        roh_projekt, roh_quelle = z["projekt"], z["quelle"]
        projekt_name, kontext, _ausgeblendet = projekte.aufloesen(roh_projekt, roh_quelle, aliase)
        z["projekt"] = projekt_name
        z["kontext"] = kontext
        z["quelle"] = quellen.quelle_fuer(roh_quelle, z.pop("modelle", None), backend=z.pop("backend", None))
        z["umgebung"] = umgebung_achse.wert(z.get("umgebung"))  # C12: Dual-Reader fuer Alt-Belege
        # Bestand ohne persona/kanal (Achse existierte noch nicht) faellt auf den Standard-Slot
        # zurueck, damit alte Belege im Dashboard nicht mit einem Leerwert auffallen.
        z["persona"] = z.get("persona") if z.get("persona") in contracts.PERSONAS else "vico"
        z["kanal"] = z.get("kanal") if z.get("kanal") in contracts.KANAELE else "terminal"
    return zeilen


@app.get("/api/sitzungen")
def api_sitzungen(
    von: date, bis: date, projekt: str | None = None, quelle: str | None = None,
    signatur: str | None = None, kontext: list[str] | None = Query(None),
    umgebung: list[str] | None = Query(None),
) -> list:
    zeilen = _mit_alias(_liste(_sql_sitzungen(von, bis, projekt, signatur)))
    if quelle:
        zeilen = [z for z in zeilen if z["quelle"] == quelle]
    if kontext:
        kontext_menge = set(kontext)
        zeilen = [z for z in zeilen if z["kontext"] in kontext_menge]
    if umgebung:
        umgebung_menge = set(umgebung)
        zeilen = [z for z in zeilen if z["umgebung"] in umgebung_menge]
    return zeilen


# ---------- /api/projekte ----------

def _zaehle_projekt_zeile(
    z: dict, aliase, projekt_zaehler: dict[str, int], projekt_ausgeblendet: dict[str, bool],
    quellen_zaehler: dict[str, int], kontexte: dict[str, int],
) -> bool:
    """Zaehlt eine Zeile aus `_sql_projekt_quelle_je_sitzung` in die vier Akkumulatoren ein.
    Liefert True, wenn die Sitzung als unzugeordnet zaehlt (Kontext unzugeordnet oder Quelle
    Unbekannt)."""
    name, kontext, ausgeblendet = projekte.aufloesen(z["projekt"], z["quelle"], aliase)
    quelle_anzeige = quellen.quelle_fuer(z["quelle"], z.get("modelle"), backend=z.get("backend"))
    projekt_zaehler[name] = projekt_zaehler.get(name, 0) + 1
    projekt_ausgeblendet[name] = projekt_ausgeblendet.get(name, False) or ausgeblendet
    quellen_zaehler[quelle_anzeige] = quellen_zaehler.get(quelle_anzeige, 0) + 1
    kontexte[kontext] = kontexte.get(kontext, 0) + 1
    return kontext == projekte.UNZUGEORDNET or quelle_anzeige == quellen.UNBEKANNT


def _projekte_antwort(
    projekt_zaehler: dict[str, int], projekt_ausgeblendet: dict[str, bool],
    quellen_zaehler: dict[str, int], kontexte: dict[str, int], unzugeordnet: int,
) -> dict:
    return {
        "projekte": [
            {"name": n, "anzahl": a, "ausgeblendet": projekt_ausgeblendet.get(n, False)}
            for n, a in sorted(projekt_zaehler.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "quellen": [{"name": n, "anzahl": a} for n, a in sorted(quellen_zaehler.items())],
        "kontexte": [{"name": n, "anzahl": a} for n, a in sorted(kontexte.items())],
        "unzugeordnet": unzugeordnet,
    }


@app.get("/api/projekte")
def api_projekte(von: date, bis: date) -> dict:
    """Zaehlt je Sitzung (nicht mehr per SQL-GROUP-BY ueber die rohe `quelle`-Spalte): die
    Anzeige-Quelle ist abgeleitet (Claude/Codex/Ollama/OpenRouter/Produkt/Unbekannt, Entscheid
    2026-08-26, Auftrag 2) und haengt vom Modell ab, das laesst sich nicht in SQL gruppieren."""
    zeilen = _liste(_sql_projekt_quelle_je_sitzung(von, bis))
    aliase = projekte.lade_aliase()
    projekt_zaehler: dict[str, int] = {}
    projekt_ausgeblendet: dict[str, bool] = {}
    quellen_zaehler: dict[str, int] = {}
    kontexte: dict[str, int] = {}
    unzugeordnet = 0
    for z in zeilen:
        if _zaehle_projekt_zeile(z, aliase, projekt_zaehler, projekt_ausgeblendet, quellen_zaehler, kontexte):
            unzugeordnet += 1
    return _projekte_antwort(projekt_zaehler, projekt_ausgeblendet, quellen_zaehler, kontexte, unzugeordnet)


# ---------- /api/querschnitt ----------

def _sql_wiederkehrende_fehler(von: date, bis: date, nur_offene: bool = True) -> str:
    """Direkt ueber die Sitzungsdokumente im Zeitraum -- NICHT ueber die flache Tabelle
    `sitzung_auffaelligkeit`: die traegt `error:recurring` nur fuer die jeweils NEU ingestierte
    Sitzung ein, sobald die Schwelle schon erreicht ist (append-only in querschnitt.py) -- die
    Dashboard-Schwelle >= 3 griff darum effektiv erst ab 5 Sitzungen (Review 2026-08-26, Befund 1).
    Zeitfilter auf die Sitzungszeit selbst (ende/start/zeitstempel der Sitzung, nicht den
    Ingest-Zeitpunkt). Ein je Sitzung erledigter/obsoleter Fund (Signatur `error:recurring:<sig>`,
    Erledigt-Feature Entscheid 2026-08-26) zaehlt standardmaessig nicht mehr mit;
    `nur_offene=False` liefert ALLE (Grundlage fuer den Schalter „Erledigte einblenden")."""
    bedingung = _zeitraum(von, bis, spalte="coalesce(s.ende, s.start, s.zeitstempel)")
    signatur_ausdruck = "'error:recurring:' || (e->>'signatur')"
    filter_klausel = f" AND {_sql_nicht_entschieden(signatur_ausdruck, 's.logisch_ref')}" if nur_offene else ""
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.anzahl_sitzungen DESC), '[]'::jsonb)
FROM (
  SELECT e->>'signatur' AS signatur, count(DISTINCT s.id) AS anzahl_sitzungen,
         jsonb_agg(DISTINCT s.id) AS sitzung_ids,
         min(e->>'name') AS werkzeug, min(e->>'fehlerklasse') AS fehlerklasse,
         count(*) AS treffer_gesamt
  FROM sitzung_aktuell s, jsonb_array_elements(s.dokument->'ereignisse') e
  WHERE e->>'art' = 'tool_ergebnis' AND (e->>'fehler')::boolean AND e->>'signatur' IS NOT NULL
    AND {bedingung}{filter_klausel}
  GROUP BY 1
  HAVING count(DISTINCT s.id) >= {MIN_SITZUNGEN_FEHLER}
) t;"""


def _signatur_zeile(z: dict, status: str) -> dict:
    """Eine Zeile für den Fehler-Drilldown (Auftrag 2/3, Umbau 2026-08-26): ein Fehlerbild
    (Werkzeug + Fehlerart + Signatur-Hash) mit Sitzungs- und Treffer-Zahl plus Status."""
    return {
        "signatur": z["signatur"], "werkzeug": z.get("werkzeug") or "",
        "fehlerklasse": z.get("fehlerklasse") or "", "anzahl_sitzungen": z["anzahl_sitzungen"],
        "treffer_gesamt": z.get("treffer_gesamt") or 0, "sitzung_ids": z["sitzung_ids"],
        "status": status,
    }


def _fehler_kachel_ids(zeilen: list[dict], alle_zeilen: list[dict] | None) -> tuple[set[int], set[int]]:
    """Sitzungs-IDs aus `zeilen` (offen) und die dazu zusaetzlichen aus `alle_zeilen`
    (vollstaendig entschieden, fuer den Schalter „Erledigte einblenden")."""
    alle_ids: set[int] = set()
    for z in zeilen:
        alle_ids.update(z["sitzung_ids"])
    erledigt_ids: set[int] = set()
    for z in alle_zeilen or []:
        erledigt_ids.update(z["sitzung_ids"])
    erledigt_ids -= alle_ids
    return alle_ids, erledigt_ids


def _fehler_kachel_signaturen(zeilen: list[dict], alle_zeilen: list[dict] | None) -> list[dict]:
    """Volle Signaturen-Liste fuer den zweistufigen Fehler-Drilldown: jede offene Signatur
    einmal (status offen), jede nur noch in `alle_zeilen` stehende einmal zusaetzlich (status
    erledigt) -- eine Signatur mit weiterhin offenen Sitzungen taucht nur EINMAL als offen auf."""
    offene_signaturen = {z["signatur"] for z in zeilen}
    signaturen = [_signatur_zeile(z, "offen") for z in zeilen]
    signaturen += [
        _signatur_zeile(z, "erledigt") for z in (alle_zeilen or []) if z["signatur"] not in offene_signaturen
    ]
    signaturen.sort(key=lambda s: -s["anzahl_sitzungen"])
    return signaturen


def _fehler_kachel(zeilen: list[dict], alle_zeilen: list[dict] | None = None) -> dict:
    """Genau EINE Kachel für alle wiederkehrenden Fehler: Anzahl qualifizierender Signaturen,
    die häufigste als Text, Sitzungs-IDs als Vereinigung fürs Drilldown. `alle_zeilen`
    (ungefiltert, Erledigt-Feature) liefert zusätzlich `sitzung_ids_erledigt` für den Schalter
    „Erledigte einblenden" UND -- zusammen mit `zeilen` -- die volle `signaturen`-Liste für den
    zweistufigen Fehler-Drilldown (Umbau 2026-08-26)."""
    alle_ids, erledigt_ids = _fehler_kachel_ids(zeilen, alle_zeilen)
    top = zeilen[0] if zeilen else None
    return {
        "anzahl": len(zeilen),
        "top_signatur": top["signatur"] if top else "",
        "top_anzahl_sitzungen": top["anzahl_sitzungen"] if top else 0,
        "top_werkzeug": (top.get("werkzeug") or "") if top else "",
        "top_fehlerklasse": (top.get("fehlerklasse") or "") if top else "",
        "top_treffer_gesamt": (top.get("treffer_gesamt") or 0) if top else 0,
        "sitzung_ids": sorted(alle_ids),
        "sitzung_ids_erledigt": sorted(erledigt_ids),
        "signaturen": _fehler_kachel_signaturen(zeilen, alle_zeilen),
    }


def _sql_signatur_sitzungszeiten(von: date | None = None, bis: date | None = None) -> str:
    """Je (rohe Fehlersignatur, Sitzung): Sitzungszeit + Treffer -- Grundlage der Rückfall-
    Erkennung (Entscheid 2026-08-26): ob eine Sitzung NACH dem jüngsten Entscheid liegt,
    lässt sich nur mit der Sitzungszeit je Sitzung feststellen, nicht mit der aggregierten
    `sitzung_ids`-Liste aus `_sql_wiederkehrende_fehler`. Ohne `von`/`bis`: unbeschränkt
    (Sitzungsseite -- der Entscheid kann älter sein als jeder sichtbare Zeitraum)."""
    bedingung = (
        _zeitraum(von, bis, spalte="coalesce(s.ende, s.start, s.zeitstempel)") if von and bis else "true"
    )
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb)
FROM (
  SELECT e->>'signatur' AS signatur, s.id AS sitzung_id,
         coalesce(s.ende, s.start, s.zeitstempel) AS zeit, count(*) AS treffer
  FROM sitzung_aktuell s, jsonb_array_elements(s.dokument->'ereignisse') e
  WHERE e->>'art' = 'tool_ergebnis' AND (e->>'fehler')::boolean AND e->>'signatur' IS NOT NULL
    AND {bedingung}
  GROUP BY 1, 2, 3
) t;"""


def _sitzungszeiten_je_signatur(rohzeilen: list[dict]) -> dict[str, list[dict]]:
    """Gruppiert die Roh-Sitzungszeiten (`_sql_signatur_sitzungszeiten`) je Signatur."""
    ergebnis: dict[str, list[dict]] = {}
    for z in rohzeilen:
        ergebnis.setdefault(z["signatur"], []).append(z)
    return ergebnis


def _roh_signatur(signatur: str) -> str:
    """Strippt das `error:recurring:`-Präfix -- Rückfall-Sitzungszeiten sind nach der rohen
    Werkzeug-Fehlersignatur gruppiert, nicht nach der zusammengesetzten Panel-Signatur."""
    praefix = "error:recurring:"
    return signatur[len(praefix):] if signatur.startswith(praefix) else signatur


def _rueckfall_zeile(z: dict, sitzungszeiten: dict[str, list[dict]], entscheide: list[dict]) -> tuple[dict, set[int]]:
    """Prueft EINEN `erledigt`-Eintrag auf Rückfall und liefert (aktualisierte Zeile,
    zusaetzliche wieder-offene Sitzungs-IDs -- leer, wenn kein Rückfall)."""
    info = befunde.status_mit_rueckfall(
        entscheide, "error:recurring:" + z["signatur"], sitzungszeiten.get(z["signatur"], [])
    )
    z = {**z, "status": info["status"]}
    if info["status"] != "rueckfall":
        return z, set()
    z["entschieden_am"] = info["entschieden_am"]
    z["rueckfall_treffer"] = info["rueckfall_treffer"]
    z["rueckfall_sitzungen"] = info["rueckfall_sitzungen"]
    return z, set(info["rueckfall_sitzungen"]["sitzung_ids"])


def _rueckfall_anwenden(kachel: dict, sitzungszeiten: dict[str, list[dict]], entscheide: list[dict]) -> dict:
    """Ersetzt `erledigt`-Einträge in `kachel['signaturen']` durch den tatsächlichen Status
    (`erledigt`/`obsolet`/`rueckfall`) -- Rückfall-Erkennung (Entscheid 2026-08-26): eine
    Sitzung NACH dem jüngsten Entscheid zählt wieder wie offen (Kachelzahl + Liste). `zeilen`-
    Einträge (bereits `offen`) bleiben unangetastet -- ein globaler erledigt/obsolet-Entscheid
    schließt sie sonst schon in `_sql_nicht_entschieden` komplett aus."""
    neue = []
    zusatz_offen: set[int] = set()
    for z in kachel["signaturen"]:
        if z["status"] != "erledigt":
            neue.append(z)
            continue
        z, zusatz = _rueckfall_zeile(z, sitzungszeiten, entscheide)
        zusatz_offen |= zusatz
        neue.append(z)
    neue.sort(key=lambda s: -s["anzahl_sitzungen"])
    anzahl_offen = sum(1 for s in neue if s["status"] in ("offen", "rueckfall"))
    return {
        **kachel,
        "anzahl": anzahl_offen,
        "sitzung_ids": sorted(set(kachel["sitzung_ids"]) | zusatz_offen),
        "sitzung_ids_erledigt": sorted(set(kachel.get("sitzung_ids_erledigt", [])) - zusatz_offen),
        "signaturen": neue,
    }


def _sql_ids_je_regel(von: date, bis: date, regel: str, praefix: bool = False, nur_offene: bool = True) -> str:
    """Zeitfilter ueber einen Join auf `sitzung`: `sitzung_auffaelligkeit.zeitstempel` ist der
    Ingest-Zeitpunkt (now()), nicht die Sitzungszeit -- ein Nachzuegler-Ingest einer alten Sitzung
    landete sonst im falschen Zeitfenster (Review 2026-08-26, Befund 2). Ein erledigter/obsoleter
    Fund (Erledigt-Feature Entscheid 2026-08-26) zaehlt standardmaessig nicht mehr mit;
    `nur_offene=False` liefert ALLE (Schalter „Erledigte einblenden")."""
    bedingung = _zeitraum(von, bis, spalte="coalesce(s.ende, s.start, s.zeitstempel)")
    vergleich = (
        f"a.regel LIKE {sql_literal(regel + '%')}" if praefix else f"a.regel = {sql_literal(regel)}"
    )
    filter_klausel = f" AND {_sql_nicht_entschieden('a.signatur', 's.logisch_ref')}" if nur_offene else ""
    return (
        "SELECT coalesce(jsonb_agg(DISTINCT s.logisch_ref), '[]'::jsonb) "
        "FROM sitzung_auffaelligkeit a JOIN sitzung s ON s.id = a.sitzung_ref "
        f"WHERE {vergleich} AND {bedingung}{filter_klausel};"
    )


def _sql_dissens(von: date, bis: date) -> str:
    """Wie `_sql_ids_je_regel`: Zeitfilter auf die Sitzungszeit statt den Ereignis-Zeitstempel."""
    bedingung = _zeitraum(von, bis, spalte="coalesce(s.ende, s.start, s.zeitstempel)")
    return f"""SELECT coalesce(jsonb_agg(DISTINCT s.logisch_ref), '[]'::jsonb)
FROM ereignis e JOIN sitzung s ON s.id = (e.detail->>'sitzung_ref')::bigint
WHERE e.quelle = 'vieraugen' AND coalesce((e.detail->>'dissens')::int, 0) > 0 AND {bedingung};"""


def _sql_projekt_quelle_je_sitzung(von: date, bis: date) -> str:
    """id/projekt(roh)/quelle(roh)/modelle je Sitzung im Zeitraum -- Grundlage fuer die
    Unzugeordnet-Kachel und /api/projekte (Namenskonvention Projekt+Kontext, Entscheid
    2026-08-26): welcher Rohname `unzugeordnet` aufloest, kann `codex-<x>`-Automatik nutzen,
    und welche Anzeige-Quelle (Claude/Codex/Ollama/OpenRouter/Produkt/Unbekannt) gilt, haengt vom Modell
    ab -- beides nur in Python zu bestimmen (projekte.aufloesen / quellen.quelle_fuer), nicht
    in SQL."""
    bedingung = _zeitraum(von, bis)
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb)
FROM (SELECT id, projekt, quelle, coalesce(dokument->'kopf'->'modelle', '[]'::jsonb) AS modelle,
             dokument->'kopf'->>'backend' AS backend
      FROM sitzung_aktuell WHERE {bedingung}) t;"""


def _unzugeordnet_kachel(von: date, bis: date) -> dict:
    """Zaehlt Sitzungen ohne Projekt+Kontext-Zuordnung UND Sitzungen mit unbekanntem Modell
    (Entscheid 2026-08-26, Auftrag 2: „Unzugeordnet" zaehlt auch unbekannte Modelle)."""
    aliase = projekte.lade_aliase()
    ids = []
    for z in _liste(_sql_projekt_quelle_je_sitzung(von, bis)):
        _projekt, kontext, _ausgeblendet = projekte.aufloesen(z["projekt"], z["quelle"], aliase)
        quelle_anzeige = quellen.quelle_fuer(z["quelle"], z.get("modelle"), backend=z.get("backend"))
        if kontext == projekte.UNZUGEORDNET or quelle_anzeige == quellen.UNBEKANNT:
            ids.append(z["id"])
    return {"anzahl": len(ids), "sitzung_ids": sorted(ids)}


def _kachel_mit_erledigt(offene_ids: list[int], alle_ids: list[int]) -> dict:
    erledigt = sorted(set(alle_ids) - set(offene_ids))
    return {"anzahl": len(offene_ids), "sitzung_ids": sorted(offene_ids), "sitzung_ids_erledigt": erledigt}


def _sql_umgebung_rohwerte(von: date, bis: date) -> str:
    """Rohe `umgebung`-Werte je Sitzung im Zeitraum (C12) -- Normalisierung/Zaehlung passiert in
    Python (`umgebung.verteilung`), wie bei Quelle/Kontext nicht in SQL."""
    bedingung = _zeitraum(von, bis)
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb)
FROM (SELECT dokument->'kopf'->>'umgebung' AS umgebung FROM sitzung_aktuell WHERE {bedingung}) t;"""


def _fehler_kachel_gesamt(von: date, bis: date) -> dict:
    """Wiederkehrende-Fehler-Kachel inkl. Rueckfall (aus `api_querschnitt` ausgelagert, Code-Masse)."""
    return _rueckfall_anwenden(
        _fehler_kachel(_liste(_sql_wiederkehrende_fehler(von, bis)),
                       _liste(_sql_wiederkehrende_fehler(von, bis, nur_offene=False))),
        _sitzungszeiten_je_signatur(_liste(_sql_signatur_sitzungszeiten(von, bis))),
        _liste(_sql_befund_entscheide()),
    )


@app.get("/api/querschnitt")
def api_querschnitt(von: date, bis: date) -> dict:
    kosten_ids = _liste(_sql_ids_je_regel(von, bis, "cost:outlier"))
    kosten_alle_ids = _liste(_sql_ids_je_regel(von, bis, "cost:outlier", nur_offene=False))
    luecken_ids = _liste(_sql_ids_je_regel(von, bis, "capture:gap", praefix=True))
    luecken_alle_ids = _liste(_sql_ids_je_regel(von, bis, "capture:gap", praefix=True, nur_offene=False))
    dissens_ids = _liste(_sql_dissens(von, bis))
    return {
        "wiederkehrende_fehler": _fehler_kachel_gesamt(von, bis),
        "kosten_ausreisser": _kachel_mit_erledigt(kosten_ids, kosten_alle_ids),
        "erfassungsluecken": _kachel_mit_erledigt(luecken_ids, luecken_alle_ids),
        "dissens": {"anzahl": len(dissens_ids), "sitzung_ids": dissens_ids},
        "unzugeordnet": _unzugeordnet_kachel(von, bis),
        "umgebungen": umgebung_achse.verteilung(
            [umgebung_achse.wert(z.get("umgebung")) for z in _liste(_sql_umgebung_rohwerte(von, bis))]
        ),
    }


# ---------- /api/sitzung/{id} ----------

def _sql_dokument(sitzung_id: int) -> str:
    return f"SELECT dokument FROM sitzung WHERE id = {int(sitzung_id)};"


def _sql_existiert(sitzung_id: int) -> str:
    """Leichte Existenzpruefung (Fund D) -- laedt nicht das ganze `dokument`-JSONB, nur ob die
    Zeile da ist. `to_jsonb(1)` statt `true`, weil psql -qAt ein Boolean als "t"/"f" ausgibt,
    kein gueltiges JSON fuer `_wert()`."""
    return f"SELECT to_jsonb(1) FROM sitzung WHERE id = {int(sitzung_id)} LIMIT 1;"


def _sql_versionen(sitzung_logisch: int) -> str:
    """Alle Versionen (`sitzung.id`) einer logischen Sitzung, neueste zuerst (C1 C5)."""
    return (
        "SELECT coalesce(jsonb_agg(id ORDER BY id DESC), '[]'::jsonb) "
        f"FROM sitzung WHERE logisch_ref = {int(sitzung_logisch)};"
    )


def _version_fuer(sitzung_logisch: int, version: int | None = None) -> int | None:
    """Loest die zu ladende `sitzung.id` (Version) zu einer logischen ID auf (C1 Regel 1/5):
    ohne `version` die juengste (`sitzung_aktuell`), sonst genau diese -- aber nur, wenn sie
    wirklich zu `sitzung_logisch` gehoert. `None`, wenn nichts passt (-> 404 beim Aufrufer)."""
    if version is not None:
        sql = f"SELECT id FROM sitzung WHERE id = {int(version)} AND logisch_ref = {int(sitzung_logisch)};"
    else:
        sql = f"SELECT id FROM sitzung_aktuell WHERE logisch_ref = {int(sitzung_logisch)};"
    return _wert(sql)


def _sql_vieraugen(sitzung_logisch: int) -> str:
    """C1 Regel 2 (Legacy-Leseregel): neue Ereignisse tragen `detail.sitzung_logisch`,
    Alt-Ereignisse nur `detail.sitzung_ref` (eine Version) -- die wird ueber
    `sitzung.logisch_ref` aufgeloest, damit `#sitzung/<logisch>` auch alte Vier-Augen-
    Ergebnisse findet."""
    logisch = sql_literal(str(int(sitzung_logisch)))
    return (
        "SELECT coalesce(detail, 'null'::jsonb) FROM ereignis WHERE quelle = 'vieraugen' "
        f"AND (detail->>'sitzung_logisch' = {logisch} OR (detail->>'sitzung_ref')::bigint IN "
        f"(SELECT id FROM sitzung WHERE logisch_ref = {int(sitzung_logisch)})) "
        "ORDER BY zeitstempel DESC LIMIT 1;"
    )


def _juengste_entscheide_je_signatur(alle: list[dict], signaturen: set[str], sitzung_id: int) -> dict:
    ergebnis = {}
    for sig in signaturen:
        treffer = befunde.juengster_je_signatur_und_sitzung(alle, sig, sitzung_id)
        if treffer:
            ergebnis[sig] = treffer
    return ergebnis


def _mit_rueckfall_markiert(entscheide_je_signatur: dict, alle: list[dict]) -> dict:
    """Ersetzt `erledigt`/`obsolet`-Einträge durch `rueckfall`, wenn seit `entschieden_am` eine
    neue Sitzung mit dieser Signatur auftrat (Rückfall-Erkennung, Entscheid 2026-08-26) --
    gleiche Logik wie im Fehler-Panel, hier für die Befund-Karten der Sitzungsseite."""
    kandidaten = {s: e for s, e in entscheide_je_signatur.items() if e.get("status") in ("erledigt", "obsolet")}
    if not kandidaten:
        return entscheide_je_signatur
    sitzungszeiten = _sitzungszeiten_je_signatur(_liste(_sql_signatur_sitzungszeiten()))
    ergebnis = dict(entscheide_je_signatur)
    for sig, entscheid in kandidaten.items():
        info = befunde.status_mit_rueckfall(alle, sig, sitzungszeiten.get(_roh_signatur(sig), []))
        if info["status"] == "rueckfall":
            ergebnis[sig] = {**entscheid, **info}
    return ergebnis


def _sql_logisch_je_version(versionen: set[int]) -> str:
    ids = ", ".join(str(int(v)) for v in versionen)
    return (
        "SELECT coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb) FROM "
        f"(SELECT id, logisch_ref FROM sitzung WHERE id IN ({ids})) t;"
    )


def _mit_logischer_ref(alle: list[dict]) -> list[dict]:
    """Legacy-Leseregel (C1 Regel 2): `befund_entscheid.sitzung_ref` zeigt bei Alt-Eintraegen
    auf eine Version (`sitzung.id`), nicht auf die logische ID -- hier einmalig ueber
    `sitzung.logisch_ref` aufgeloest (`speicher.logisch_fuer_version` je Zeile waere N
    Rundreisen; ein Batch reicht), bevor `befunde.py` (Version-unabhaengig) darauf rechnet."""
    versionen = {e["sitzung_ref"] for e in alle if _ist_legacy_ref(e)}
    if not versionen:
        return alle
    zuordnung = {
        z["id"]: z["logisch_ref"] for z in _liste(_sql_logisch_je_version(versionen)) if z.get("logisch_ref")
    }
    return [
        {**e, "sitzung_ref": zuordnung.get(e["sitzung_ref"], e["sitzung_ref"])}
        if _ist_legacy_ref(e) else e
        for e in alle
    ]


# C1-Stichtag: Entscheide ab diesem Tag tragen bereits die logische ID (erledigt.js sendet
# `sitzungId` = logische Sitzung). Befund 2026-08-29: ohne Stichtag wurden Entscheide der
# Tiefenanalyse (Ereignis 694 -> 137, 738 -> 245) als Versions-IDs gedeutet und auf fremde
# logische Sitzungen (70, 174) umgehaengt.
C1_STICHTAG = "2026-08-27"


def _ist_legacy_ref(e: dict) -> bool:
    return e.get("sitzung_ref") is not None and str(e.get("entschieden_am", "")) < C1_STICHTAG


def _befund_entscheide_je_sitzung(sitzung_logisch: int, auffaelligkeiten: list[dict]) -> dict:
    """{signatur: juengster passender Entscheid} nur fuer Signaturen dieser Sitzung (logische
    ID, C1) -- offene Befunde tauchen hier gar nicht auf. Ein erledigter/obsoleter Fund wird zu
    `rueckfall`, wenn seither eine neue Sitzung mit dieser Signatur auftrat (Rückfall-Erkennung,
    Entscheid 2026-08-26)."""
    signaturen = {a["signatur"] for a in auffaelligkeiten if a.get("signatur")}
    if not signaturen:
        return {}
    alle = _mit_logischer_ref(_liste(_sql_befund_entscheide()))
    return _mit_rueckfall_markiert(_juengste_entscheide_je_signatur(alle, signaturen, sitzung_logisch), alle)


def _runden_je_index(ereignisse: list[dict]) -> list[int]:
    """Rundennummer je Ereignis-Index (1-basiert): zählt `art == "nutzer"` hoch, jedes
    Ereignis gehört zur zuletzt begonnenen Runde. Ereignisse vor der ersten Nutzer-Runde
    zählen als Runde 1 (Anzeige-Konvention, Abnahme 2026-08-26, Auftrag B.6)."""
    runden: list[int] = []
    runde = 0
    for e in ereignisse:
        if e.get("art") == "nutzer":
            runde += 1
        runden.append(max(runde, 1))
    return runden


def _position_rework_file(ref: str, ereignisse: list[dict]) -> int | None:
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool_ergebnis" and e.get("fehler") and e.get("signatur") == ref:
            return i
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool" and e.get("signatur") == ref:
            return i
    return None


def _position_rework_tool(ref: str, ereignisse: list[dict]) -> int | None:
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool_ergebnis" and e.get("fehler") and e.get("name") == ref:
            return i
    return None


def _position_subagent(ref: str, ereignisse: list[dict]) -> int | None:
    for i, e in enumerate(ereignisse):
        if e.get("art") == "subagent" and e.get("ref") == ref:
            return i
    return None


def _position_slow_turn(ref: str, ereignisse: list[dict]) -> int | None:
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool" and e.get("ref") == ref and (e.get("dauer_ms") or 0) > 120_000:
            return i
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool" and e.get("name") == ref and (e.get("dauer_ms") or 0) > 120_000:
            return i
    return None


def _position_timeout(ref: str, ereignisse: list[dict]) -> int | None:
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool" and e.get("ref") == ref and e.get("dauer_ms") == 120_000:
            return i
    for i, e in enumerate(ereignisse):
        if e.get("art") == "tool" and e.get("name") == ref and e.get("dauer_ms") == 120_000:
            return i
    return None


def _position_index(a: dict, ereignisse: list[dict]) -> int | None:
    """Ereignis-Index, an dem ein Befund verankert werden kann -- oder None, wenn die Regel
    strukturell sitzungsweit ist (kein Einzelereignis-Bezug). Bevorzugt einen direkten Treffer
    über `ref` (z. B. Alt-Belege vor der Gruppierung, in denen `ref` noch die tool_use_id
    trug), fällt sonst auf den ersten passenden Ereignistyp zurück (Abnahme 2026-08-26,
    geprüft an einer Referenz-Sitzung)."""
    regel = a.get("regel", "")
    signatur = a.get("signatur", "") or ""
    ref = a.get("ref", "") or ""
    if not ref:
        return None
    if regel == "rework:file":
        return _position_rework_file(ref, ereignisse)
    if regel == "rework:tool":
        return _position_rework_tool(ref, ereignisse)
    if regel in ("subagent:failed", "subagent:unsupported_claim"):
        return _position_subagent(ref, ereignisse)
    if regel == "latency:slow_turn" and signatur.startswith("latency:slow_turn:tool:"):
        return _position_slow_turn(ref, ereignisse)
    if regel == "latency:timeout":
        return _position_timeout(ref, ereignisse)
    return None


def _mit_regeltexten_und_position(auffaelligkeiten: list[dict], ereignisse: list[dict]) -> list[dict]:
    """Reichert jeden Befund um `titel`/`bedeutung`/`was_tun` (regeltexte.py) und `position`
    an (Abnahme "Block 4 Sitzungsdetail", 2026-08-26, Auftrag B.4/B.6). `position` ist
    `None`, wenn die Regel sitzungsweit ist (UI zeigt dann "Sitzung gesamt")."""
    runden = _runden_je_index(ereignisse)
    angereichert = []
    for a in auffaelligkeiten:
        text = regeltexte.text_fuer(a.get("regel", ""))
        index = _position_index(a, ereignisse)
        position = None
        if index is not None and index < len(ereignisse):
            position = {
                "runde": runden[index] if index < len(runden) else 1,
                "zeit": ereignisse[index].get("zeit", ""),
                "ereignis_index": index,
            }
        angereichert.append({**a, **text, "position": position})
    return angereichert


def _signaturquellen_fuer(dokument: dict, vieraugen: dict | None) -> list[dict]:
    """Signatur-Quellen fuer `_befund_entscheide_je_sitzung`: die Befunde des Belegs plus --
    falls vorhanden -- die vieraugen-eigenen `zusatz:...`-Funde (Auftrag C.8, Abnahme
    2026-08-26), die NICHT in `dokument['auffaelligkeiten']` stehen."""
    signaturquellen = list(dokument.get("auffaelligkeiten", []))
    if vieraugen:
        signaturquellen += [
            {"signatur": b.get("signatur")} for b in vieraugen.get("befunde", []) if b.get("signatur")
        ]
    return signaturquellen


def _sitzung(sitzung_logisch: int, version: int | None = None) -> dict:
    """Dokument wird durch das Modell projiziert (Befund 3, Review 2026-08-26): unbekannte
    Schluessel im gespeicherten JSONB landen nie in der Antwort. `sitzung_logisch` ist die
    stabile ID (C1); `version` = die geladene `sitzung.id` (Default: die juengste)."""
    from .__main__ import _beleg_aus_dict  # spaeter Import: vermeidet Zirkularitaet

    version_id = _version_fuer(sitzung_logisch, version)
    if version_id is None:
        raise HTTPException(404, f"Sitzung {sitzung_logisch} nicht gefunden")
    dokument = _wert(_sql_dokument(version_id))
    dokument = _beleg_aus_dict(dokument).als_dict()
    dokument["auffaelligkeiten"] = _mit_regeltexten_und_position(
        dokument.get("auffaelligkeiten", []), dokument.get("ereignisse", [])
    )
    kopf = dokument.get("kopf", {})
    vieraugen = _wert(_sql_vieraugen(sitzung_logisch))
    antwort = {
        "sitzung_logisch": sitzung_logisch,
        "version": version_id,
        "versionen": _liste(_sql_versionen(sitzung_logisch)),
        "dokument": dokument,
        "quelle_anzeige": quellen.quelle_fuer(kopf.get("quelle", ""), kopf.get("modelle"), backend=kopf.get("backend")),
        "vieraugen": vieraugen,
        "befund_entscheide": _befund_entscheide_je_sitzung(
            sitzung_logisch, _signaturquellen_fuer(dokument, vieraugen)
        ),
    }
    angereichert = pruefung.anreichern(antwort, _ereignisse_laden)  # B: Status/gruppen_status/Prüfung/Zulässigkeit
    angereichert["kennzahlen_block"] = chat_kennzahlen.baue_block(angereichert)  # C7: speist Chip + Chat-Kontext
    return angereichert


@app.get("/api/sitzung/{sitzung_id}")
def api_sitzung(sitzung_id: int, version: int | None = None) -> dict:
    return _sitzung(sitzung_id, version)


@app.get("/api/sitzung/version/{version_id}")
def api_sitzung_version(version_id: int) -> dict:
    """Uebergangsroute fuer alte `#sitzung/<version>`-Links (C1 Regel 5): loest eine Version
    (`sitzung.id`) auf ihre logische ID auf -- 404, wenn die Version nicht existiert."""
    logisch = speicher.logisch_fuer_version(version_id, laufer=LAUFER)
    if logisch is None:
        raise HTTPException(404, f"Version {version_id} nicht gefunden")
    return {"sitzung_logisch": logisch}


@app.get("/api/sitzung/{sitzung_id}/kacheln")
def api_sitzung_kacheln(sitzung_id: int) -> dict:
    """Rundenweise Kennzahlen + Live-Benchmark der Sitzungsseite (kacheln.py) -- 404 wie
    ``api_sitzung`` bei unbekannter (logischer) Sitzung."""
    from .__main__ import _beleg_aus_dict, _lade_preise

    version_id = _version_fuer(sitzung_id)
    if version_id is None:
        raise HTTPException(404, f"Sitzung {sitzung_id} nicht gefunden")
    dokument = _wert(_sql_dokument(version_id))
    beleg = _beleg_aus_dict(dokument)
    preise, _waehrung = _lade_preise(None)
    benchmark_zeile = _wert(kacheln.sql_benchmark(beleg.kopf.projekt_name, beleg.kopf.quelle, version_id))
    return kacheln.antwort(beleg, preise or None, benchmark_zeile)


@app.get("/api/sitzung/{sitzung_id}/subagent/{index}")
def api_subagent(sitzung_id: int, index: int) -> dict:
    subagenten = _sitzung(sitzung_id)["dokument"].get("subagenten", [])
    if index < 0 or index >= len(subagenten):
        raise HTTPException(404, f"Subagent {index} nicht gefunden")
    return {"sitzung_id": sitzung_id, "index": index, "subagent": subagenten[index]}


# ---------- Erledigt-Feature je Befund (Entscheid 2026-08-26, Auftrag 3) ----------

class BefundEntscheidBody(BaseModel):
    signatur: str
    status: str
    vermerk: str = ""
    begruendung: str = ""
    sitzung_ref: int | None = None
    verankerung: dict | None = None  # C11: Pflicht bei status=erledigt, geprueft in ereignis_schreiben


def _sql_befund_entscheide(von: date | None = None, bis: date | None = None) -> str:
    bedingung = "quelle = 'gf' AND typ = 'befund_entscheid'"
    if von and bis:
        bedingung += " AND " + _zeitraum(von, bis, spalte="zeitstempel")
    return (
        "SELECT coalesce(jsonb_agg(detail ORDER BY zeitstempel DESC), '[]'::jsonb) "
        f"FROM ereignis WHERE {bedingung};"
    )


@app.post("/api/befund/entscheid")
def api_befund_entscheid(body: BefundEntscheidBody) -> dict:
    try:
        detail = befunde.entscheid_bauen(
            body.signatur, body.status, body.vermerk, body.begruendung, body.sitzung_ref,
            verankerung=body.verankerung,
        )
    except befunde.EntscheidFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    try:
        speicher.ereignis_schreiben("gf", "befund_entscheid", detail, laufer=LAUFER)
    except contracts.ContractFehler as fehler:
        # C11: `erledigt` ohne Verankerung ist kein Entscheid -- 400 (Bedienfehler), nicht 502
        # (Speicherfehler). Derselbe Contract prueft auch die vollen Feldregeln (pfad/art).
        raise HTTPException(400, str(fehler)) from fehler
    except speicher.SpeicherFehler as fehler:
        raise HTTPException(502, f"nicht gespeichert — {fehler}") from fehler
    return detail


@app.get("/api/befund/entscheide")
def api_befund_entscheide(von: date | None = None, bis: date | None = None) -> list:
    return _liste(_sql_befund_entscheide(von, bis))


# ---------- POST /api/sitzung/{id}/pruefen ----------

# In-Flight-Guard (Befund 4, Review 2026-08-26): ohne ihn startete ein Doppel-POST (Doppelklick,
# Retry) zwei parallele Reviews fuer dieselbe Sitzung. Wert = Startzeit (ISO, UTC) -- Grundlage
# fuer GET /api/sitzung/{id}/pruefen (Feedback 2026-08-26, Punkt 3c: "Prüfung läuft … seit
# HH:MM" beim Laden der Seite, auch wenn der Lauf in einer frueheren Sitzung gestartet wurde).
_laufend: dict[int, str] = {}
_laufend_lock = threading.Lock()
# Letzter Hintergrundfehler je Sitzung (Fund E): vorher landete ein Fehler nur auf stderr, GET
# /pruefen kannte nur `laeuft`. Selber Lock wie `_laufend`, weil beide denselben Lauf beschreiben
# und beim naechsten Start/Abfragen zusammen gelesen/geschrieben werden.
_letzter_fehler: dict[int, str] = {}


def _pruefen_hintergrund(sitzung_id: int, version: int | None = None) -> None:
    """Laeuft im Hintergrund-Thread; ein Fehler darf den Server nie stoeren. Liest das rohe
    Dokument direkt, nicht ueber `_sitzung()` (dessen Anreicherung kennt `Auffaelligkeit(**a)` nicht)."""
    fehlertext = None
    try:
        from .__main__ import _beleg_aus_dict  # spaeter Import: vermeidet Zirkularitaet
        rohdokument = _wert(_sql_dokument(version or sitzung_id))
        if not rohdokument:
            raise ValueError(f"Sitzung {sitzung_id} nicht gefunden")
        beleg = _beleg_aus_dict(rohdokument)
        ergebnis = VIERAUGEN_REVIEW(beleg)
        ergebnis["sitzung_ref"] = version or sitzung_id
        ergebnis["sitzung_logisch"] = sitzung_id  # C1 Regel 2: neue Refs tragen die logische ID
        speicher.ereignis_schreiben("vieraugen", "review", ergebnis, laufer=LAUFER)
    except Exception as fehler:
        fehlertext = f"{type(fehler).__name__}: {fehler}"
        print(f"pruefen sitzung={sitzung_id}: {fehlertext}", file=sys.stderr)
    with _laufend_lock:
        if fehlertext:
            _letzter_fehler[sitzung_id] = fehlertext
        _laufend.pop(sitzung_id, None)


@app.post("/api/sitzung/{sitzung_id}/pruefen")
def api_pruefen(sitzung_id: int) -> dict:
    # Fund D: bisher startete das ein Thread + 200 auch fuer nicht existierende Sitzungen --
    # der Hintergrundfehler ("Sitzung … nicht gefunden") verschwand unbemerkt auf stderr.
    # Phase 1 A: `sitzung_id` ist die LOGISCHE ID (C1); der Hintergrundlauf braucht die Version.
    version = _version_fuer(sitzung_id)
    if version is None:
        raise HTTPException(404, f"Sitzung {sitzung_id} nicht gefunden")
    with _laufend_lock:
        if sitzung_id in _laufend:
            return {"gestartet": False, "laeuft": True}
        _laufend[sitzung_id] = datetime.now(timezone.utc).isoformat()
        _letzter_fehler.pop(sitzung_id, None)
    threading.Thread(target=_pruefen_hintergrund, args=(sitzung_id, version), daemon=True).start()
    return {"gestartet": True}


@app.get("/api/sitzung/{sitzung_id}/pruefen")
def api_pruefen_status(sitzung_id: int) -> dict:
    """Read-only Status (Feedback 2026-08-26, Punkt 3c): die UI pollt hierueber, ob eine
    Vier-Augen-Pruefung fuer diese Sitzung gerade laeuft -- ohne selbst eine zu starten."""
    with _laufend_lock:
        seit = _laufend.get(sitzung_id)
        fehler = _letzter_fehler.get(sitzung_id)
    return {"laeuft": seit is not None, "seit": seit, "fehler": fehler}


# ---------- /api/preise (Einstellungen-Seite, read-only aus modelle.json) ----------

@app.get("/api/preise")
def api_preise() -> dict:
    from .__main__ import MODELLE_PFAD, _lade_preise

    preise, waehrung = _lade_preise(None)
    # Block-Stand als Fallback je Eintrag (Nachtrag 2026-08-30): anthropic-Eintraege
    # tragen keinen eigenen `stand` -- die Preistabelle zeigt sonst "—".
    stand = None
    if MODELLE_PFAD.exists():
        try:
            stand = json.loads(MODELLE_PFAD.read_text(encoding="utf-8")).get("preise", {}).get("stand")
        except (OSError, json.JSONDecodeError):
            stand = None
    # Serverseitige Katalog-Anreicherung (Maintainer 2026-08-30, Screenshot-Runde 3): kanonische_id-
    # Match in katalog_sicht.preise_anreichern. Fail-soft: ohne DB bleibt der provisorische
    # Client-Match (preistabelle.js) aktiv -- die Kostenquelle (modelle.json) ist nie betroffen.
    katalog_verfuegbar = True
    try:
        anreicherung = katalog_sicht.preise_anreichern(preise, katalog_sicht._zeilen_lesen(LAUFER))
    except speicher.SpeicherFehler:
        anreicherung, katalog_verfuegbar = {}, False
    for key, meta in anreicherung.items():
        preise.setdefault(key, {})["katalog"] = meta
    return {"waehrung": waehrung, "preise": preise, "stand": stand,
            "katalog_verfuegbar": katalog_verfuegbar}


# ---------- /api/modellkatalog (Einstellungen -> Modellkatalog, C15) ----------

@app.get("/api/modellkatalog")
def api_modellkatalog() -> dict:
    """Katalog-Tabelle + Persona-Kacheln in einem Aufruf (katalog_sicht.hole_katalog). Ein
    DB-Fehler wird NIE als 500-Stacktrace durchgereicht -- gleiche Regel wie api_chat_post."""
    try:
        return katalog_sicht.hole_katalog(laufer=LAUFER)
    except speicher.SpeicherFehler as fehler:
        raise HTTPException(502, f"Modellkatalog nicht lesbar — {fehler}") from fehler


# ---------- POST/GET /api/modellkatalog/aktualisieren (C15 v2 Punkt 4) ----------
# Gleiches Muster wie POST/GET /api/sitzung/{id}/pruefen oben: ein Lauf zugleich per Modul-Lock,
# der Client pollt den Status statt einer offenen Verbindung. `katalog.py` ist Baustelle eines
# parallel arbeitenden Agenten -- darum Laufzeit-Import ueber `_katalog_modul()` (eigene Funktion,
# damit Tests den kompletten Katalog-Lauf ohne Netz/DB per Monkeypatch ersetzen koennen).
_katalog_lauf_seit: str | None = None
_katalog_lauf_lock = threading.Lock()
_katalog_letzter_fehler: str | None = None
_katalog_lauf_erfolgreich = False  # mind. ein Lauf seit Serverstart erfolgreich beendet


def _katalog_modul():
    from . import katalog

    return katalog


def _katalog_aktualisieren_hintergrund() -> None:
    """Laeuft im Hintergrund-Thread (Muster `_pruefen_hintergrund`). `katalog.befehl_katalog_
    update` kann waehrend des parallelen Baus noch fehlen -- dann fail-open mit Erklaertext
    statt Absturz (Task-Vorgabe Punkt 4)."""
    global _katalog_lauf_seit, _katalog_letzter_fehler, _katalog_lauf_erfolgreich
    fehlertext = None
    try:
        befehl = getattr(_katalog_modul(), "befehl_katalog_update", None)
        if befehl is None:
            raise AttributeError("katalog.befehl_katalog_update fehlt noch (paralleler Baustein)")
        befehl(argparse.Namespace(anbieter=None, db=True))
    except Exception as fehler:
        fehlertext = f"{type(fehler).__name__}: {fehler}"
        print(f"modellkatalog aktualisieren: {fehlertext}", file=sys.stderr)
    with _katalog_lauf_lock:
        _katalog_letzter_fehler = fehlertext
        _katalog_lauf_erfolgreich = fehlertext is None
        _katalog_lauf_seit = None


@app.post("/api/modellkatalog/aktualisieren")
def api_modellkatalog_aktualisieren() -> dict:
    global _katalog_lauf_seit
    with _katalog_lauf_lock:
        if _katalog_lauf_seit is not None:
            return {"status": "laeuft"}
        _katalog_lauf_seit = datetime.now(timezone.utc).isoformat()
    threading.Thread(target=_katalog_aktualisieren_hintergrund, daemon=True).start()
    return {"status": "gestartet"}


@app.get("/api/modellkatalog/aktualisieren")
def api_modellkatalog_aktualisieren_status() -> dict:
    with _katalog_lauf_lock:
        if _katalog_lauf_seit is not None:
            return {"status": "laeuft", "detail": None}
        if _katalog_letzter_fehler is not None:
            return {"status": "fehler", "detail": _katalog_letzter_fehler}
        if _katalog_lauf_erfolgreich:
            return {"status": "fertig", "detail": None}
        return {"status": "bereit", "detail": None}


# ---------- statisches Dashboard ----------
# Nachtrag 2026-08-27 Punkt 11 (ADR-0005-Muster, eigene Version): index() liest die Datei jetzt
# statt sie durchzureichen, um den Platzhalter `__VERSION__` zu ersetzen (Kopfzeile-Caption +
# `?v=`-Cache-Stempel) -- einzige unvermeidbare Aenderung an dieser bestehenden Route.

@app.get("/")
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(version.html_mit_version(html))


# ---------- Serverstart ----------

def _ingest_beim_start() -> None:
    """Einmaliger `ingest-dir --seit 3 --db` vor dem Serverstart, fail-open (Plan Abschnitt C)."""
    try:
        from . import __main__ as cli

        args = cli._parser().parse_args(["ingest-dir", "--seit", "3", "--db"])
        cli._befehl_ingest_dir(args)
    except Exception as fehler:
        print(f"ingest-dir beim Start: {type(fehler).__name__}: {fehler}", file=sys.stderr)


def _konsole_freigeben(kernel32=None) -> bool:
    """Windows: den Prozess von seiner Konsole loesen (FreeConsole). Befund 2026-08-26/28: der
    Dashboard-Task starb wiederholt mit 0xC000013A (STATUS_CONTROL_C_EXIT) -- ein Konsolen-
    Ctrl-Ereignis aus der geteilten, versteckten Konsole traf uvicorn. Ohne Konsole gibt es
    kein Ereignis. Rueckgabe: ob geloest wurde (False auf anderen Plattformen/ohne Konsole)."""
    if kernel32 is None:
        if sys.platform != "win32":
            return False
        import ctypes

        kernel32 = ctypes.windll.kernel32
    return bool(kernel32.FreeConsole())


def _log_umleiten(log_datei: Path) -> None:
    """stdout/stderr zeilengepuffert in die Logdatei (UTF-8, anhaengend) -- Ersatz fuer die
    PowerShell-Umleitung `*>>`, die eine Konsole voraussetzte."""
    log_datei.parent.mkdir(parents=True, exist_ok=True)
    strom = open(log_datei, "a", encoding="utf-8", buffering=1)
    sys.stdout = strom
    sys.stderr = strom


def serve(log_datei: Path | None = None, port: int = PORT) -> None:
    """Startet den Server hart auf 127.0.0.1 (Standard 8091) -- kein Parameter fuer andere Hosts.
    Mit `log_datei` loest sich der Prozess von der Konsole und schreibt sein Log selbst."""
    if log_datei is not None:
        _log_umleiten(log_datei)
        _konsole_freigeben()
    _ingest_beim_start()
    uvicorn.run(app, host=HOST, port=port)


# ---------- Chat (Phase 1 D Stub -- CONTRACTS.md C4/C5) ----------
# Additiv am Dateiende (Arbeitspaket D): Endpunkte nutzen `chat.py` (Stub-Bruecke, echte
# `claude -p`-Bruecke folgt Phase 2 F) + `speicher.chat_schreiben`/`chat_lesen` (eigene Tabelle
# `chat`, nicht `ereignis` -- ADR 0006 2b).
from typing import Literal  # noqa: E402

from fastapi.responses import StreamingResponse  # noqa: E402

from . import chat, chat_bruecke, contracts  # noqa: E402


class ChatKontextBody(BaseModel):
    sitzung_logisch: int | None = None
    signatur: str | None = None
    runde: int | None = None
    analyse_id: str | None = None


class ChatBody(BaseModel):
    gespraech_id: str | None = None
    anbieter: Literal["claude", "ollama", "openrouter", "requesty"]
    modell: str
    text: str
    kontext: ChatKontextBody
    # B: zulaessigkeit(beleg) anschliessen (redaktion.py) -- bis dahin ein Platzhalter-Feld mit
    # dem Vokabular aus C6 (redaktion.zulaessigkeit): "cloud-ok" | "geschuetzt".
    schutz: Literal["cloud-ok", "geschuetzt"] = "cloud-ok"
    # Nachtrag Sichtkontext (2026-08-28, Auftrag): welche Ansicht offen ist + die sichtbaren
    # Sitzungszeilen (`contracts.Sicht`) -- roh als dict, damit `_sicht_geprueft()` denselben
    # Contract-Fehlerpfad (400) wie andere Bodies nutzt statt eines zweiten Pydantic-Modells.
    sicht: dict | None = None


@app.get("/api/chat/modelle")
def api_chat_modelle(alle: bool = False) -> dict:
    return chat.modelle(alle)


# Cloud-Anbieter (Claude, OpenRouter, Requesty) sind fuer geschuetzte Sitzungen gesperrt (C6) --
# nur Ollama laeuft lokal. OpenRouter/Requesty behandelt web.py hier wie Claude (Phase 2,
# Nachtrag OpenRouter/Requesty).
_CLOUD_ANBIETER = ("claude", "openrouter", "requesty")


def _kontext_mit_kennzahlen(kontext: ChatKontextBody) -> dict:
    """Haengt `kennzahlen_block` an -- NUR bei Sitzungskontext, aus derselben `_sitzung()`, die
    auch die Detailseite speist (kein zweiter Rechenweg). Fail-open bei JEDEM Fehler (Sitzung
    fehlt, DB kurz nicht erreichbar, unerwartete Form): der Chat bleibt dann ohne Kennzahlen-
    Kontext bedienbar -- das war vorher IMMER der Fall (Fund 2026-08-27), kein neues Risiko."""
    daten = kontext.model_dump()
    if not daten.get("sitzung_logisch"):
        return daten
    try:
        daten["kennzahlen_block"] = _sitzung(daten["sitzung_logisch"])["kennzahlen_block"]
    except Exception as fehler:
        print(f"[chat] Kennzahlen-Kontext nicht gebaut ({daten['sitzung_logisch']}): {fehler}")
    return daten


def _sicht_geprueft(sicht: dict | None) -> dict | None:
    """C7 Sichtkontext (Nachtrag 2026-08-28): validiert `sicht` gegen `contracts.Sicht` (400 bei
    Verstoss, wie jeder andere Body hier) und laesst es danach durch `chat.sicht_bereinigt()` --
    die Werte sind bereits redigierte Anzeige-Information, das ist nur das zweite Netz."""
    if sicht is None:
        return None
    try:
        contracts.validiere("sicht", sicht)
    except contracts.ContractFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return chat.sicht_bereinigt(sicht)


@app.post("/api/chat", status_code=202)
def api_chat_post(body: ChatBody) -> dict:
    if body.anbieter in _CLOUD_ANBIETER and body.schutz == "geschuetzt":
        raise HTTPException(423, f"{body.anbieter} ist fuer diese Sitzung gesperrt (geschuetzt) -- nur Ollama lokal")
    gespraech_id = body.gespraech_id
    if gespraech_id is None:
        chat_schutz = "lokal" if body.schutz == "geschuetzt" else "cloud-ok"
        kontext = _kontext_mit_kennzahlen(body.kontext)
        sicht = _sicht_geprueft(body.sicht)
        gespraech_id = chat.gespraech_starten(body.anbieter, body.modell, kontext, chat_schutz, sicht)
    try:
        chat.senden(gespraech_id, body.text, laufer=LAUFER)
    except ValueError as fehler:
        raise HTTPException(404, str(fehler)) from fehler
    except contracts.ContractFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    except speicher.SpeicherFehler as fehler:
        raise HTTPException(502, f"nicht gespeichert — {fehler}") from fehler
    return {"gespraech_id": gespraech_id}


@app.get("/api/chat/{gespraech_id}/strom")
def api_chat_strom(gespraech_id: str) -> StreamingResponse:
    def ereignisse():
        for event in chat.strom(gespraech_id, laufer=LAUFER):
            yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"

    return StreamingResponse(ereignisse(), media_type="text/event-stream")


@app.get("/api/chat/{gespraech_id}")
def api_chat_get(gespraech_id: str) -> dict:
    nachrichten = speicher.chat_lesen(gespraech_id, laufer=LAUFER)
    if not nachrichten:
        raise HTTPException(404, f"Gespräch {gespraech_id} nicht gefunden")
    erste = nachrichten[0]
    return {
        "gespraech_id": gespraech_id, "anbieter": erste["anbieter"], "modell": erste["modell"],
        "schutz": erste["schutz"], "nachrichten": nachrichten,
    }


# ---------- Chat "Fix umsetzen" (CONTRACTS.md C5) ----------
# Umsetzen passiert NIE im Hintergrund-Prozess (nur Lesewerkzeuge, s. chat_bruecke.py), sondern
# durch den konfigurierten Fix-Launcher (`chat.fix_umsetzen` -> `chat_bruecke.oeffne_fix_fenster`
# -> `SITZUNGSBELEG_FIX_LAUNCHER`).
@app.post("/api/chat/{gespraech_id}/fix", status_code=202)
def api_chat_fix(gespraech_id: str) -> dict:
    try:
        chat.fix_umsetzen(gespraech_id)
    except ValueError as fehler:
        raise HTTPException(404, str(fehler)) from fehler
    except chat_bruecke.FixLauncherFehlt as fehler:
        raise HTTPException(501, str(fehler)) from fehler
    except Exception as fehler:  # Fremdprozess (Launcher/powershell.exe o.ae.): nie verschlucken
        raise HTTPException(500, f"Fix nicht gestartet — {fehler}") from fehler
    return {"gestartet": True}


# ---------- Delegation als Kennzahl-Karte (Phase 1 C -- CONTRACTS.md C5) ----------
# Additiv am Dateiende (Arbeitspaket C). Sitzungs-ID = LOGISCHE ID (C1), Aufloesung wie
# ``/kacheln`` ueber ``_version_fuer`` (Nachzug 2026-08-27 nach Migration 0004).
from . import contracts, delegation  # noqa: E402


@app.get("/api/delegation/{sitzung_id}", response_model=contracts.Delegation)
def api_delegation(sitzung_id: int) -> dict:
    """Delegation-Kennzahlen + eigener Benchmark (C5, nicht der Kacheln-Benchmark) -- 404 wie
    ``api_sitzung_kacheln`` bei unbekannter (logischer) Sitzung."""
    from .__main__ import _beleg_aus_dict

    version_id = _version_fuer(sitzung_id)
    if version_id is None:
        raise HTTPException(404, f"Sitzung {sitzung_id} nicht gefunden")
    beleg = _beleg_aus_dict(_wert(_sql_dokument(version_id)))
    benchmark_zeile = _wert(
        delegation.sql_benchmark(beleg.kopf.projekt_name, beleg.kopf.quelle, version_id)
    )
    return delegation.antwort(beleg, benchmark_zeile)


# ---------- Pruef-Regelwerk (Phase 1 B -- CONTRACTS.md C4/C5, Modul pruefung.py) ----------
# Additiv am Dateiende (Arbeitspaket B). Die Alt-Endpunkte `POST/GET /api/sitzung/{id}/pruefen`
# oben bleiben unveraendert in Form UND Innenleben (C5 "Alt" verlangt intern scope='sitzung' --
# das haette die bestehenden PruefenTest-Faelle/`VIERAUGEN_REVIEW`-Kopplung umgebaut; als
# Contract-Konflikt im Bericht gemeldet, nicht eigenmaechtig migriert).

def _sql_ereignisse_quelle(quelle: str) -> str:
    return f"SELECT coalesce(jsonb_agg(detail), '[]'::jsonb) FROM ereignis WHERE quelle = {sql_literal(quelle)};"


def _ereignisse_laden(quelle: str) -> list:
    """Injiziert in `pruefung.anreichern`/`lauf_ausfuehren`: alle `ereignis.detail`-Zeilen einer
    Quelle (Filterung nach sitzung_logisch/signatur passiert in pruefung.py selbst)."""
    return _liste(_sql_ereignisse_quelle(quelle))


def _pruefung_ereignis_schreiben(quelle: str, typ: str, detail: dict) -> None:
    speicher.ereignis_schreiben(quelle, typ, detail, laufer=LAUFER)


def _beleg_fuer_pruefung(sitzung_logisch: int):
    from .__main__ import _beleg_aus_dict

    version_id = _version_fuer(sitzung_logisch)
    if version_id is None:
        raise ValueError(f"Sitzung {sitzung_logisch} nicht gefunden")
    return _beleg_aus_dict(_wert(_sql_dokument(version_id)))


def _sql_pruefung_lauf(lauf_id: str) -> str:
    return (
        "SELECT coalesce(detail, 'null'::jsonb) FROM ereignis WHERE quelle = 'pruefung' "
        f"AND typ = 'lauf' AND detail->>'lauf_id' = {sql_literal(lauf_id)} "
        "ORDER BY zeitstempel DESC LIMIT 1;"
    )


def _juengstes_pruefung_ereignis(lauf_id: str) -> dict | None:
    return _wert(_sql_pruefung_lauf(lauf_id))


def _pruefung_body_oder_400(body: dict) -> contracts.PruefungBody:
    try:
        return contracts.validiere("pruefung_body", body)
    except contracts.ContractFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler


# Laufende Pruef-Faeden je lauf_id (Tests joinen darueber; Eintraege werden nicht bereinigt --
# ein Thread-Objekt je Lauf ist klein, der Prozess lebt nur bis zum naechsten Neustart).
_pruefung_faeden: dict[str, threading.Thread] = {}


@app.post("/api/pruefung", status_code=202)
def api_pruefung_starten(body: dict) -> dict:
    """C5 `POST /api/pruefung`: Body-Validierung ueber `contracts.PruefungBody` (400 statt
    FastAPIs generischem 422, wie `api_befund_entscheid`), Sitzungspruefung fuer scope !=
    'fehlerbild' (404), Lauf-Konflikt (409, C5 Lauf-Schluessel via `pruefung.LaufKonflikt`)."""
    pruefung_body = _pruefung_body_oder_400(body)
    if pruefung_body.scope != "fehlerbild" and _version_fuer(pruefung_body.sitzung_logisch) is None:
        raise HTTPException(404, f"Sitzung {pruefung_body.sitzung_logisch} nicht gefunden")
    try:
        lauf_id, kontext = pruefung.lauf_starten(pruefung_body, _beleg_fuer_pruefung)
    except pruefung.LaufKonflikt as konflikt:
        return JSONResponse(
            status_code=409,
            content={"detail": f"Lauf {konflikt.lauf_id} laeuft bereits", "lauf_id": konflikt.lauf_id},
        )
    faden = threading.Thread(
        target=pruefung.lauf_beenden, daemon=True,
        args=(lauf_id, pruefung_body, kontext, FRAGER_CLAUDE, FRAGER_CODEX, _pruefung_ereignis_schreiben),
    )
    _pruefung_faeden[lauf_id] = faden
    faden.start()
    # stufe_max steht erst nach Stufe 1 fest (Komplexitaet) -> im 202 null, im Ereignis gesetzt.
    return {"lauf_id": lauf_id, "scope": pruefung_body.scope, "stufe_max": None}


@app.get("/api/pruefung/{lauf_id}")
def api_pruefung_status(lauf_id: str) -> dict:
    """C5 `GET /api/pruefung/{lauf_id}`: laufend -> Registry; sonst juengstes persistiertes
    `pruefung/lauf`-Ereignis mit dieser lauf_id; keins von beidem -> 404 (unbekannt)."""
    registriert = pruefung.ist_registriert(lauf_id)
    if registriert is not None:
        return {"lauf_id": lauf_id, "laeuft": True, "seit": registriert["seit"], "fehler": None, "ergebnis": None}
    ergebnis = _juengstes_pruefung_ereignis(lauf_id)
    if ergebnis is None:
        raise HTTPException(404, f"Lauf {lauf_id} nicht gefunden")
    return {
        "lauf_id": lauf_id, "laeuft": False, "seit": ergebnis.get("gestartet"),
        "fehler": ergebnis.get("fehler"), "ergebnis": ergebnis,
    }


# Seite "Fehlerbilder & Entscheide" (Phase 2 G, eigenes APIRouter -- siehe fehlerbilder.py).
app.include_router(fehlerbilder.router)

# Kachel "Prüfung offen" (Phase 2 E, eigenes APIRouter -- siehe befund_kacheln.py).
from . import befund_kacheln  # noqa: E402
app.include_router(befund_kacheln.router)

# GET /version (Nachtrag 2026-08-27 Punkt 11, eigenes APIRouter -- siehe version.py).
app.include_router(version.router)


# ---------- Rohdatei lokal (Phase 3 H -- CONTRACTS.md C5/C6, Modul rohdatei.py) ----------
# Additiv am Dateiende. Server bindet ohnehin hart auf 127.0.0.1 (Moduldoc oben) -- kein
# weiterer Host-Check je Route, wie bei allen anderen Endpunkten hier. `zulaessigkeit` kommt aus
# `_sitzung()` (dieselbe Berechnung wie der Datenschutz-Chip, C6), nie vom Client (anders als
# `ChatBody.schutz` oben -- Rohdatei haengt IMMER an genau einer Sitzung, der Server kennt sie).
from . import rohdatei  # noqa: E402


@app.get("/api/rohdatei/{sitzung_id}", response_model=contracts.RohdateiAntwort)
def api_rohdatei(sitzung_id: int, position: int = 0, umfang: int = rohdatei.DEFAULT_UMFANG) -> dict:
    """C5 `GET /api/rohdatei/{sitzung_logisch}`: 404 unbekannte Sitzung (ueber `_sitzung()`),
    423 geschuetzte Sitzung, 404 mit Hinweis bei fehlendem Transkript. `umfang` wird in
    `rohdatei.baue_antwort` auf `[1, MAX_UMFANG]` gekappt, `position` bleibt reine Anzeige-/
    Zentrierungshilfe (siehe rohdatei.py Moduldoc) -- hier nur gegen negative Werte gekappt,
    damit `RohdateiAntwort.position` (Field ge=0) nie am eigenen Response-Model scheitert."""
    position = max(0, position)
    antwort = _sitzung(sitzung_id)
    if antwort["zulaessigkeit"] == "geschuetzt":
        raise HTTPException(423, "Sitzung ist geschuetzt -- Rohdatei nur lokal per Terminal")
    kopf = antwort["dokument"].get("kopf", {})
    ereignisse = antwort["dokument"].get("ereignisse", [])
    zeit = ereignisse[position].get("zeit") if 0 <= position < len(ereignisse) else None
    try:
        return rohdatei.baue_antwort(kopf.get("quelle", ""), kopf.get("sitzung_id", ""), zeit, position, umfang)
    except rohdatei.RohdateiFehler as fehler:
        raise HTTPException(404, str(fehler)) from fehler


# ---------- Tiefenanalyse + Commits im Zeitfenster (Phase 3 I -- CONTRACTS.md C10) ----------
# Additiv am Dateiende. Austauschbar fuer Tests, gleiche Konvention wie FRAGER_CLAUDE/FRAGER_CODEX
# oben (nie mit den eigenen echten Defaults aufgerufen).
from . import commits, tiefenanalyse  # noqa: E402

TIEFENANALYSE_FRAGER_CLOUD = tiefenanalyse.frage_claude_cloud
TIEFENANALYSE_FRAGER_LOKAL = tiefenanalyse.frage_claude_lokal
TIEFENANALYSE_FRAGER_CODEX = vieraugen.frage_codex


class TiefenanalyseBody(BaseModel):
    signatur: str
    position: int


def _auffaelligkeit_oder_404(antwort: dict, signatur: str) -> dict:
    for a in antwort["dokument"].get("auffaelligkeiten", []):
        if a.get("signatur") == signatur:
            return a
    raise HTTPException(404, f"Signatur {signatur!r} nicht gefunden")


def _tiefenanalyse_ereignis_schreiben(quelle: str, typ: str, detail: dict) -> None:
    speicher.ereignis_schreiben(quelle, typ, detail, laufer=LAUFER)


def _tiefenanalyse_hintergrund(sitzung_id: int, body: TiefenanalyseBody, antwort: dict, auff: dict) -> None:
    """Laeuft im Hintergrund-Thread (Muster `_pruefen_hintergrund`) -- gibt die Registrierung
    IMMER frei, auch wenn `tiefenanalyse.lauf_ausfuehren` selbst nie wirft (es faengt jeden
    Fremdprozess-Fehler schon ab)."""
    kopf = antwort["dokument"].get("kopf", {})
    nur_lokal = antwort["zulaessigkeit"] == "geschuetzt"
    historie = _ereignisse_laden("pruefung")
    runde = (auff.get("position") or {}).get("runde", 0)
    try:
        tiefenanalyse.lauf_ausfuehren(
            antwort["dokument"], auff, body.signatur, body.position, runde, sitzung_id,
            kopf.get("quelle", ""), kopf.get("sitzung_id", ""), nur_lokal, historie,
            _tiefenanalyse_ereignis_schreiben,
            frager_cloud=TIEFENANALYSE_FRAGER_CLOUD, frager_lokal=TIEFENANALYSE_FRAGER_LOKAL,
            frager_codex=TIEFENANALYSE_FRAGER_CODEX,
        )
    finally:
        tiefenanalyse.freigeben(sitzung_id, body.signatur)


@app.post("/api/sitzung/{sitzung_id}/tiefenanalyse", status_code=202)
def api_tiefenanalyse_starten(sitzung_id: int, body: TiefenanalyseBody) -> dict:
    """C10: 404 unbekannte Sitzung/Signatur, 409 bei bereits laufender Analyse zu dieser
    (Sitzung, Signatur), sonst Hintergrund-Thread + 202."""
    antwort = _sitzung(sitzung_id)
    auff = _auffaelligkeit_oder_404(antwort, body.signatur)
    if not tiefenanalyse.registriere_lauf(sitzung_id, body.signatur):
        raise HTTPException(409, f"Tiefenanalyse fuer {body.signatur!r} laeuft bereits")
    threading.Thread(
        target=_tiefenanalyse_hintergrund, args=(sitzung_id, body, antwort, auff), daemon=True,
    ).start()
    return {"gestartet": True}


def _sql_tiefenanalyse(sitzung_id: int, signatur: str) -> str:
    return (
        "SELECT coalesce(jsonb_agg(detail ORDER BY zeitstempel DESC), '[]'::jsonb) FROM ereignis "
        f"WHERE quelle = 'tiefenanalyse' AND (detail->>'sitzung_logisch')::bigint = {int(sitzung_id)} "
        f"AND detail->>'signatur' = {sql_literal(signatur)};"
    )


@app.get("/api/sitzung/{sitzung_id}/tiefenanalyse")
def api_tiefenanalyse_status(sitzung_id: int, signatur: str) -> dict:
    """C10 Status ueber `signatur` (kein eigenes `lauf_id`-Resource): `ergebnis` ist das
    juengste `tiefenanalyse`-Ereignis, unabhaengig davon, ob gerade ein neuer Lauf laeuft."""
    seit = tiefenanalyse.laeuft_seit(sitzung_id, signatur)
    treffer = _liste(_sql_tiefenanalyse(sitzung_id, signatur))
    return {"laeuft": seit is not None, "seit": seit, "ergebnis": treffer[0] if treffer else None}


@app.get("/api/sitzung/{sitzung_id}/commits")
def api_commits(sitzung_id: int) -> dict:
    """C10: `zulaessigkeit == geschuetzt` -> 423 (wie Rohdatei). Kein Repo/Treffer -> leere
    Liste (kein Fehler, `commits.liste` faengt das schon ab)."""
    antwort = _sitzung(sitzung_id)
    if antwort["zulaessigkeit"] == "geschuetzt":
        raise HTTPException(423, "Sitzung ist geschuetzt -- Commits nur lokal per Terminal")
    kopf = antwort["dokument"].get("kopf", {})
    return {"commits": commits.liste(
        kopf.get("quelle", ""), kopf.get("sitzung_id", ""), kopf.get("start", ""), kopf.get("ende", "")
    )}


@app.get("/api/sitzung/{sitzung_id}/commits/{commit_hash}")
def api_commit_diff(sitzung_id: int, commit_hash: str) -> dict:
    antwort = _sitzung(sitzung_id)
    if antwort["zulaessigkeit"] == "geschuetzt":
        raise HTTPException(423, "Sitzung ist geschuetzt -- Commits nur lokal per Terminal")
    kopf = antwort["dokument"].get("kopf", {})
    try:
        return {"diff": commits.diff(kopf.get("quelle", ""), kopf.get("sitzung_id", ""), commit_hash)}
    except commits.CommitsFehler as fehler:
        raise HTTPException(404, str(fehler)) from fehler


# ---------- Wache-Entscheide-Cache + Meldungsspur (C13, eigene Module -- siehe wache_cache.py
# und wache_web.py). Additiv am Dateiende. Schreibt _work_sitzungsbeleg/wache-entscheide.json
# einmal beim Start und danach alle 10 min im Hintergrund, damit der PreToolUse-Hook (wache.py,
# eigener Prozess je Werkzeugaufruf) den Cache nur LIEST, nie selbst die DB anfasst.
from . import wache_cache, wache_web  # noqa: E402

app.include_router(wache_web.router)


@app.on_event("startup")
def _wache_cache_starten() -> None:
    wache_cache.starte_hintergrund()
