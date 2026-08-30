"""Seite "Fehlerbilder & Entscheide" (Phase 2 G, Plan Abschn. 3 Nr. 3 -- der bisherige
Querschnitt-Reiter wiederholte nur die Start-Kacheln, siehe Plan Abschn. 1 Beobachtung 1).

Aggregiert `sitzung_auffaelligkeit` (ALLE Auffaelligkeiten eines Belegs, nicht nur die
Querschnitts-Regeln aus `querschnitt.py` -- `speicher.sql_einfuegen` flacht jeden Beleg
vollstaendig ab, C1) je Signatur ueber `logisch_ref`, Status je Sitzung aus
`pruefung.status_fuer` (C2), Entscheid aus dem bestehenden `befund_entscheid`-Strom
(`befunde.py`). Eigenes `APIRouter` -- `web.py` bindet es mit einer Zeile ein
(`app.include_router(fehlerbilder.router)`), damit die Datei-Grenze der Welle-2-Aufteilung
haelt (E/F ruehren `web.py` nicht an, dieses Paket auch nicht ausser der einen Zeile).
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException

from . import befunde, contracts, pruefung, regeltexte
from .speicher import psql, sql_literal

router = APIRouter()

# Austauschbar fuer Tests (fehlerbilder.LAUFER = FakeLaufer(...)), wie web.LAUFER.
LAUFER = psql


def _zeitraum(von: date, bis: date, spalte: str) -> str:
    """Halboffenes Intervall [von, bis] als Tag, wie `web._zeitraum` (eigene Kopie: dieses
    Modul haengt bewusst nicht an `web.py`, sonst Zirkularitaet beim Router-Include)."""
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


def _sql_vorkommen(von: date, bis: date) -> str:
    """Rohzeilen: eine Zeile je (Signatur, logische Sitzung) mit Regel/Projekt/Zeit im
    Zeitraum -- Status/Rueckfall brauchen die Sitzungsliste je Signatur in Python
    (`befunde.status_mit_rueckfall`), das laesst sich nicht sauber in SQL aggregieren."""
    bedingung = _zeitraum(von, bis, "coalesce(s.ende, s.start, s.zeitstempel)")
    return f"""SELECT coalesce(jsonb_agg(row_to_json(t)), '[]'::jsonb)
FROM (
  SELECT DISTINCT a.signatur, a.regel, a.logisch_ref AS sitzung_logisch, s.projekt,
         coalesce(s.ende, s.start, s.zeitstempel) AS zeit
  FROM sitzung_auffaelligkeit a JOIN sitzung_aktuell s ON s.logisch_ref = a.logisch_ref
  WHERE a.logisch_ref IS NOT NULL AND {bedingung}
) t;"""


def _sql_entscheide() -> str:
    """Alle `befund_entscheid`-Ereignisse, unbeschraenkt (ein Entscheid kann aelter sein als
    jeder sichtbare Zeitraum), wie `web._sql_befund_entscheide` ohne Zeitfilter."""
    return (
        "SELECT coalesce(jsonb_agg(detail ORDER BY zeitstempel DESC), '[]'::jsonb) "
        "FROM ereignis WHERE quelle = 'gf' AND typ = 'befund_entscheid';"
    )


def _sql_pruefung_laeufe() -> str:
    """Alle `pruefung/lauf`-Ereignisse -- Filterung nach Signatur/Sitzung passiert in Python
    (`pruefung.status_fuer`), wie `web._ereignisse_laden`."""
    return "SELECT coalesce(jsonb_agg(detail), '[]'::jsonb) FROM ereignis WHERE quelle = 'pruefung' AND typ = 'lauf';"


def _sql_vieraugen_ereignisse() -> str:
    """Alle Alt-`vieraugen/review`-Ereignisse (C1 Regel 2) -- normalisiert ueber
    `pruefung.vieraugen_als_laeufe` und in `status_fuer`s `laeufe` gemischt (Nachtrag 2026-08-27
    Punkt 1: ohne das blieb eine Signatur mit nur einem Legacy-Urteil dauerhaft `offen`)."""
    return "SELECT coalesce(jsonb_agg(detail), '[]'::jsonb) FROM ereignis WHERE quelle = 'vieraugen' AND typ = 'review';"


def _laeufe_mit_legacy() -> list[dict]:
    return _liste(_sql_pruefung_laeufe()) + pruefung.vieraugen_als_laeufe(_liste(_sql_vieraugen_ereignisse()))


def _sql_letzter_fehlerbild_lauf(signatur: str) -> str:
    """Juengster `pruefung/lauf`-Ereignis mit scope='fehlerbild' fuer diese Signatur (C4) --
    liefert `sitzungen`/`tabelle`/`datei`, sobald einmal "Ueber alle Sitzungen pruefen" lief."""
    enthaelt = sql_literal(json.dumps([signatur]))
    return (
        "SELECT coalesce(detail, 'null'::jsonb) FROM ereignis WHERE quelle = 'pruefung' "
        f"AND typ = 'lauf' AND detail->>'scope' = 'fehlerbild' AND detail->'signaturen' @> {enthaelt}::jsonb "
        "ORDER BY zeitstempel DESC LIMIT 1;"
    )


def _sitzungen_je_signatur(vorkommen: list[dict]) -> dict[str, list[dict]]:
    ergebnis: dict[str, list[dict]] = {}
    for v in vorkommen:
        ergebnis.setdefault(v["signatur"], []).append(v)
    return ergebnis


def _status_liste(sitzungen: list[dict], signatur: str, entscheide: list[dict],
                   laeufe: list[dict], laufend: list[dict]) -> list[str]:
    """Status je Sitzung dieser Signatur (C2 `pruefung.status_fuer`) -- `sitzungen` fuer die
    Rueckfall-Erkennung sind die im Zeitraum sichtbaren (eine Sitzung ausserhalb des
    Zeitraums koennte einen Rueckfall zeigen, der hier dann noch nicht auftaucht -- das ist
    dieselbe Zeitraum-Grenze wie beim uebrigen Dashboard)."""
    kompakt = [{"sitzung_id": s["sitzung_logisch"], "zeit": s["zeit"], "treffer": 1} for s in sitzungen]
    return [
        pruefung.status_fuer(
            {"signatur": signatur, "sitzung_logisch": s["sitzung_logisch"], "sitzungen": kompakt},
            entscheide, laeufe, laufend,
        )
        for s in sitzungen
    ]


def _verteilung(status_liste: list[str]) -> dict[str, int]:
    verteilung: dict[str, int] = {}
    for st in status_liste:
        verteilung[st] = verteilung.get(st, 0) + 1
    return verteilung


def _fehlerbild_zeile(signatur: str, sitzungen: list[dict], entscheide: list[dict],
                       laeufe: list[dict], laufend: list[dict]) -> dict:
    status_liste = _status_liste(sitzungen, signatur, entscheide, laeufe, laufend)
    entscheid = befunde.juengster_je_signatur_und_sitzung(entscheide, signatur, None)
    return {
        "signatur": signatur, "regel": sitzungen[0]["regel"],
        "regeltext": regeltexte.text_fuer(sitzungen[0]["regel"]),
        "anzahl_sitzungen": len(sitzungen),
        "projekte": sorted({s["projekt"] for s in sitzungen}),
        "juengstes_vorkommen": max(s["zeit"] for s in sitzungen),
        "gruppenstatus": contracts.gruppenstatus(status_liste),
        "status_verteilung": _verteilung(status_liste),
        "rueckfall": "rueckfall" in status_liste,
        "gf_entscheid": entscheid,
    }


def _fehlerbilder(von: date, bis: date) -> list[dict]:
    vorkommen = _liste(_sql_vorkommen(von, bis))
    entscheide = _liste(_sql_entscheide())
    laeufe = _laeufe_mit_legacy()
    laufend = pruefung.laufend_uebersicht()
    gruppen = _sitzungen_je_signatur(vorkommen)
    zeilen = [_fehlerbild_zeile(sig, s, entscheide, laeufe, laufend) for sig, s in gruppen.items()]
    zeilen.sort(key=lambda z: -z["anzahl_sitzungen"])
    return zeilen


@router.get("/api/fehlerbilder")
def api_fehlerbilder(von: date, bis: date) -> list[dict]:
    """C3 Scope `fehlerbild` -- eine Zeile je Signatur im Zeitraum (Tabelle der Seite
    "Fehlerbilder & Entscheide"): Regeltext, Sitzungen/Projekte, Status-Verteilung, Entscheid."""
    return _fehlerbilder(von, bis)


def _sitzungen_mit_status(sitzungen: list[dict], status_liste: list[str]) -> list[dict]:
    zeilen = [{**s, "status": st} for s, st in zip(sitzungen, status_liste)]
    return sorted(zeilen, key=lambda z: z["zeit"], reverse=True)


def _drilldown(signatur: str, von: date, bis: date) -> dict:
    vorkommen = [v for v in _liste(_sql_vorkommen(von, bis)) if v["signatur"] == signatur]
    if not vorkommen:
        raise HTTPException(404, f"Fehlerbild {signatur} nicht im gewaehlten Zeitraum gefunden")
    entscheide = _liste(_sql_entscheide())
    laeufe = _laeufe_mit_legacy()
    laufend = pruefung.laufend_uebersicht()
    zeile = _fehlerbild_zeile(signatur, vorkommen, entscheide, laeufe, laufend)
    status_liste = _status_liste(vorkommen, signatur, entscheide, laeufe, laufend)
    letzter_lauf = _wert(_sql_letzter_fehlerbild_lauf(signatur))
    return {
        **zeile,
        "sitzungen_liste": _sitzungen_mit_status(vorkommen, status_liste),
        "letzter_fehlerbild_lauf": letzter_lauf,
    }


@router.get("/api/fehlerbild/{signatur}")
def api_fehlerbild(signatur: str, von: date, bis: date) -> dict:
    """C3 Scope `fehlerbild` Drilldown: betroffene Sitzungen (logische IDs, je mit Status) +
    der juengste sitzungsuebergreifende Pruef-Lauf (`sitzungen`/`tabelle`/`datei`), falls schon
    einmal "Ueber alle Sitzungen pruefen" lief -- sonst `letzter_fehlerbild_lauf: null`."""
    return _drilldown(signatur, von, bis)
