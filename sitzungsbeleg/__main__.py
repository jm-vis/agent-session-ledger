"""CLI-Einstieg: `python -m sitzungsbeleg ingest|ingest-dir|report|review ...`.

Ablauf ingest: Leser -> kennzahlen.berechne -> regeln.pruefe -> [speicher + querschnitt]
-> redaktion.bereinige -> Ausgabe. Exit 2, wenn redaktion nach der Bereinigung noch
Verstöße meldet. `--hook` (Stop-Hook von Claude Code) ist FAIL-OPEN: immer Exit 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

from . import (
    befunde, contracts, katalog, kennzahlen, konfig, projekte, quellen, querschnitt, redaktion,
    regeln, reingest, retention, speicher, verankerung, vieraugen, wache, wache_cache,
)
from .ausgabe import als_json, als_markdown
from .modell import Beleg

MODELLE_PFAD = konfig.modelle_pfad()
PREIS_FELDER = ("input", "output", "cache_write", "cache_read", "kontext_fenster", "meldet_als")
# Anzeigefelder (Nachtrag 2026-08-30, Preistabelle im Katalog-Look): sie kosten die
# Abrechnung nichts (kennzahlen liest nur PREIS_FELDER), aber das Frontend braucht sie fuer
# Anbieter-Chip/Stand/Referenz-Markierung -- vorher still verworfen.
# Maintainer 2026-08-30 (Status-Zone): `referenz` = kuratierter Zeiger auf die Groessenvariante
# bei Ollama-Basis-Keys ohne Tag (Katalog entfernt die Basis-Zeile als Dublette -- ohne
# den Zeiger blieben Status/Sterne dieser Abrechnungs-Keys leer).
PREIS_ANZEIGE_FELDER = ("herkunft", "stand", "preis_art", "quelle", "cache_quelle", "referenz")
CLAUDE_PROJEKTE = Path.home() / ".claude" / "projects"
CODEX_SITZUNGEN = Path.home() / ".codex" / "sessions"

def _backend_aus_env() -> str:
    """Hostklasse aus `ANTHROPIC_BASE_URL` (Auftrag Requesty, 2026-08-28): der Stop-Hook laeuft
    im Prozess von `claude` und erbt dessen Umgebung -- Requesty-IDs sehen wie OpenRouter-IDs aus
    (`anthropic/claude-sonnet-5`), der Modellname allein reicht darum nicht zur Unterscheidung
    (quellen.py Moduldoc). Nur die HostKLASSE landet im Beleg-Kopf, nie die URL/ein Token."""
    basis = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not basis:
        return "anthropic"
    host = urllib.parse.urlparse(basis).hostname or ""
    if host in ("localhost", "127.0.0.1"):
        return "ollama"
    if "openrouter.ai" in host:
        return "openrouter"
    if "requesty.ai" in host:
        return "requesty"
    if "anthropic.com" in host:
        return "anthropic"
    return "unbekannt"


def _umgebung_aus_env() -> str:
    """Achse Umgebung (C12, Auftrag 2026-08-28 12:45): der Stop-Hook liest `SITZUNGSBELEG_UMGEBUNG`
    aus seiner Umgebung (wie `_backend_aus_env`) -- leer bleibt `entwicklung` (Default), ein
    UNBEKANNTER Wert faellt ebenfalls auf `entwicklung` zurueck, meldet sich aber auf stderr
    (Hook-Log) statt den Hook abzubrechen (fail-open bleibt unangetastet)."""
    wert = os.environ.get("SITZUNGSBELEG_UMGEBUNG", "").strip()
    if not wert:
        return "entwicklung"
    if wert not in contracts.UMGEBUNGEN:
        print(f"sitzungsbeleg hook: SITZUNGSBELEG_UMGEBUNG unbekannt: {wert!r} -> entwicklung", file=sys.stderr)
        return "entwicklung"
    return wert


def _persona_aus_env() -> str:
    """Achse Persona: abgeleitet aus `CLAUDE_CONFIG_DIR`, das den Profil-Ordner des laufenden
    Agenten traegt -- drei Profil-Slots sind vorgesehen (`.vica`, `.cura`, sonst der globale
    Standard-Slot `vico`). Endet der Pfad auf `.vica` -> `vica`, auf `.cura` -> `cura`, sonst
    (leer/globales `~/.claude`) -> `vico`; kein eigenes `.vico`-Verzeichnis noetig, der
    Standard-Slot laeuft im globalen Profil. Kein neuer Env-Schalter, kein Fehlerfall -- immer
    ein gueltiger Wert."""
    pfad = os.environ.get("CLAUDE_CONFIG_DIR", "").rstrip("/\\")
    basis = os.path.basename(pfad).lower()
    if basis.endswith(".vica"):
        return "vica"
    if basis.endswith(".cura"):
        return "cura"
    return "vico"


def _kanal_aus_env() -> str:
    """Achse Kanal (C14, Maintainer 2026-08-28): `SITZUNGSBELEG_KANAL` aus der Umgebung -- leer bleibt
    `terminal` (Default), die Orb-Bruecke setzt `orb` beim Spawnen. Ein UNBEKANNTER Wert faellt
    wie bei `_umgebung_aus_env` auf `terminal` zurueck und meldet sich auf stderr."""
    wert = os.environ.get("SITZUNGSBELEG_KANAL", "").strip()
    if not wert:
        return "terminal"
    if wert not in contracts.KANAELE:
        print(f"sitzungsbeleg hook: SITZUNGSBELEG_KANAL unbekannt: {wert!r} -> terminal", file=sys.stderr)
        return "terminal"
    return wert


def _preise_aus_block(block: dict) -> tuple[dict, str]:
    """{"waehrung": "USD", "modelle": {name: {input, output, ...}}} -> (preise, waehrung).
    Ein flaches Dict {name: {...}} (ohne "modelle") wird ebenfalls akzeptiert (--preise)."""
    if "modelle" not in block:
        return {name: dict(satz) for name, satz in block.items() if isinstance(satz, dict)}, ""
    preise = {}
    for name, angaben in block.get("modelle", {}).items():
        satz = {feld: angaben[feld] for feld in PREIS_FELDER if feld in angaben}
        satz.update({feld: angaben[feld] for feld in PREIS_ANZEIGE_FELDER if feld in angaben})
        if "input" in satz or "output" in satz:
            preise[name] = satz
    return preise, str(block.get("waehrung", "") or "")


def _lade_preise(pfad: str | None) -> tuple[dict, str]:
    """Preise aus --preise, sonst aus dem `preise`-Block in modelle.json. (preise, waehrung)."""
    if pfad:
        with open(pfad, encoding="utf-8") as f:
            return _preise_aus_block(json.load(f))
    if not MODELLE_PFAD.exists():
        return {}, ""
    with open(MODELLE_PFAD, encoding="utf-8") as f:
        daten = json.load(f)
    preise, waehrung = _preise_aus_block(daten.get("preise", {}))
    if not preise:
        print("Hinweis: modelle.json hat keinen preise-Block — kosten=not_observed.", file=sys.stderr)
    return preise, waehrung


def _ausgeben(beleg: Beleg, json_pfad: str | None, md_pfad: str | None, still: bool = False) -> int:
    """Zentrale Ausgabefunktion — IMMER Bereinigung + Prüfung vor jedem Rendern.

    Bei Restverstoß nach der Bereinigung: nichts rendern (weder Datei noch
    stdout), Exit 2. `ingest` und `report` dürfen nur über diese Funktion
    ausgeben. ``still``: nichts auf stdout (Hook/ingest-dir).
    """
    redaktion.bereinige(beleg)
    verstoesse = redaktion.pruefe_beleg(beleg)
    if verstoesse:
        return 2

    if json_pfad:
        Path(json_pfad).write_text(als_json(beleg), encoding="utf-8")
    if md_pfad:
        Path(md_pfad).write_text(als_markdown(beleg), encoding="utf-8")
    if not json_pfad and not md_pfad and not still:
        print(als_markdown(beleg))

    return 0


def _leser(quelle: str):
    if quelle == "claude":
        from . import leser_claude as leser
    else:
        from . import leser_codex as leser
    return leser


def _finde_sitzung(quelle: str, sitzung_id: str) -> Path:
    """Transkript zu einer Sitzungs-ID (Claude: projects/*/<id>.jsonl, Codex: rollout-*<id>*.jsonl)."""
    if quelle == "claude":
        treffer = list(CLAUDE_PROJEKTE.glob(f"*/{sitzung_id}.jsonl"))
    else:
        treffer = list(CODEX_SITZUNGEN.glob(f"**/rollout-*{sitzung_id}*.jsonl"))
    if not treffer:
        raise FileNotFoundError(f"kein Transkript für {quelle}:{sitzung_id}")
    return treffer[0]


def beleg_erzeugen(quelle: str, datei: str, preise_pfad: str | None, host: str) -> Beleg:
    """Leser + Kennzahlen + Sitzungsregeln (ohne DB)."""
    beleg = _leser(quelle).lese_sitzung(datei, host=host)
    preise, waehrung = _lade_preise(preise_pfad)
    kennzahlen.berechne(beleg, preise or None, waehrung)
    regeln.pruefe(beleg, preise or None)
    return beleg


class RedaktionsFehler(RuntimeError):
    """Beleg hat nach der Bereinigung noch Verstoesse — darf weder DB noch Ausgabe erreichen."""


def _bereinigt_oder_fehler(beleg: Beleg) -> Beleg:
    redaktion.bereinige(beleg)
    verstoesse = redaktion.pruefe_beleg(beleg)
    if verstoesse:
        raise RedaktionsFehler("; ".join(verstoesse)[:200])
    return beleg


def _speichern_mit_querschnitt(beleg: Beleg, host: str) -> str:
    """Bereinigt (C1: Redaktion VOR dem Insert), speichert, Querschnittsregeln.
    Liefert eine Statuszeile ('neu id=…' | 'vorhanden'); RedaktionsFehler bei Restverstoss."""
    _bereinigt_oder_fehler(beleg)
    sitzung_ref = speicher.speichern(beleg, host)
    if sitzung_ref is None:
        return "vorhanden"
    treffer = querschnitt.pruefe_und_speichere(beleg, sitzung_ref)  # schliesst sitzung_ref aus p95 aus
    beleg.auffaelligkeiten.extend(treffer)
    return f"neu id={sitzung_ref}" + (f" querschnitt={len(treffer)}" if treffer else "")


def _befehl_ingest(args: argparse.Namespace) -> int:
    if args.hook:
        return _ingest_hook(args)
    datei = args.datei or str(_finde_sitzung(args.quelle, args.session))
    beleg = beleg_erzeugen(args.quelle, datei, args.preise, args.host)
    if args.db:
        try:
            print(f"DB: {_speichern_mit_querschnitt(beleg, args.host)}", file=sys.stderr)
        except speicher.SpeicherFehler as fehler:
            print(f"Warnung: nicht gespeichert — {fehler}", file=sys.stderr)
        except RedaktionsFehler as fehler:
            print(f"Redaktion: nicht gespeichert — {fehler}", file=sys.stderr)
            return 2
    return _ausgeben(beleg, args.json, args.markdown)


def _ingest_hook(args: argparse.Namespace) -> int:
    """Stop-Hook: stdin-JSON {session_id, transcript_path}; immer Exit 0 (fail-open)."""
    try:
        daten = json.load(sys.stdin)
        datei = daten.get("transcript_path") or str(_finde_sitzung("claude", daten["session_id"]))
        beleg = beleg_erzeugen("claude", datei, args.preise, args.host)
        beleg.kopf.backend = _backend_aus_env()
        beleg.kopf.umgebung = _umgebung_aus_env()
        beleg.kopf.persona = _persona_aus_env()
        beleg.kopf.kanal = _kanal_aus_env()
        _speichern_mit_querschnitt(beleg, args.host)
    except Exception as fehler:  # Hook darf die Sitzung nie stören
        print(f"sitzungsbeleg hook: {type(fehler).__name__}: {str(fehler)[:200]}", file=sys.stderr)
    return 0


def _transkripte(quelle: str, seit: datetime) -> list[Path]:
    """Alle Transkripte einer Quelle mit Änderung nach ``seit`` (Subagenten-Dateien nicht)."""
    if quelle == "claude":
        kandidaten = CLAUDE_PROJEKTE.glob("*/*.jsonl")
    else:
        kandidaten = CODEX_SITZUNGEN.glob("**/rollout-*.jsonl")
    return sorted(p for p in kandidaten
                  if datetime.fromtimestamp(p.stat().st_mtime) >= seit)


def _befehl_ingest_dir(args: argparse.Namespace) -> int:
    """Alle Transkripte der letzten --seit Tage; je Datei fail-open, Summenzeile am Ende."""
    seit = datetime.now() - timedelta(days=args.seit)
    quellen = ["claude", "codex"] if args.quelle == "alle" else [args.quelle]
    zaehler = {"neu": 0, "vorhanden": 0, "fehler": 0, "redaktion": 0}
    for quelle in quellen:
        for pfad in _transkripte(quelle, seit):
            _ingest_eine_datei(quelle, pfad, args, zaehler)
    print("ingest-dir: " + " · ".join(f"{k}={v}" for k, v in zaehler.items()))
    return 0


def _ingest_eine_datei(quelle: str, pfad: Path, args, zaehler: dict) -> None:
    try:
        beleg = beleg_erzeugen(quelle, str(pfad), args.preise, args.host)
        _bereinigt_oder_fehler(beleg)
        status = _speichern_mit_querschnitt(beleg, args.host) if args.db else "neu (trocken)"
        zaehler["neu" if status.startswith("neu") else "vorhanden"] += 1
    except RedaktionsFehler:
        zaehler["redaktion"] += 1
    except Exception as fehler:  # eine kaputte Datei stoppt den Lauf nicht
        zaehler["fehler"] += 1
        print(f"  {quelle} {pfad.name}: {type(fehler).__name__}: {str(fehler)[:120]}", file=sys.stderr)


def _meta_eintraege(verzeichnis: Path) -> list[dict]:
    """`meta.jsonl`-Zeilen eines abgeholten Server-Spools als dicts (C14-Nachtrag Server-Spool,
    CONTRACTS.md). Zeilen mit `typ` (z. B. `cura_zugriffsversuch`, CURA-Zugriffsspur) sind keine
    Sitzungen und werden uebersprungen; kaputte JSON-Zeilen ebenso (fail-open). Fehlt die Datei:
    leere Liste -- der Aufrufer meldet das sauber mit Exit 0."""
    meta_pfad = verzeichnis / "meta.jsonl"
    if not meta_pfad.exists():
        return []
    eintraege = []
    for zeile in meta_pfad.read_text(encoding="utf-8").splitlines():
        if not zeile.strip():
            continue
        try:
            eintrag = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if "typ" not in eintrag:
            eintraege.append(eintrag)
    return eintraege


def _spool_persona_kanal(eintrag: dict) -> tuple[str, str]:
    """persona/kanal AUS der Meta-Zeile, nicht aus Env (C14-Nachtrag Server-Spool) -- der Spool
    kann Sitzungen mehrerer Personas mischen, anders als der PC-Stop-Hook. Fehlender/unbekannter
    Wert faellt auf den jeweiligen Feld-Default zurueck (wie `_persona_aus_env`/`_kanal_aus_env`)."""
    persona = eintrag.get("persona")
    kanal = eintrag.get("kanal")
    return (
        persona if persona in contracts.PERSONAS else "vico",
        kanal if kanal in contracts.KANAELE else "terminal",
    )


def _ingest_spool_eintrag(verzeichnis: Path, eintrag: dict, args: argparse.Namespace, zaehler: dict) -> None:
    """Ein `meta.jsonl`-Eintrag -> Beleg (C14-Nachtrag Server-Spool). Fail-open wie
    `_ingest_eine_datei`: eine kaputte Transkript-Datei stoppt den Lauf nicht, sie zaehlt nur."""
    datei = eintrag.get("datei", "?")
    try:
        beleg = beleg_erzeugen("claude", str(verzeichnis / datei), args.preise, args.host)
        beleg.kopf.persona, beleg.kopf.kanal = _spool_persona_kanal(eintrag)
        _bereinigt_oder_fehler(beleg)
        status = _speichern_mit_querschnitt(beleg, args.host) if args.db else "neu (trocken)"
        zaehler["neu" if status.startswith("neu") else "vorhanden"] += 1
    except Exception as fehler:  # eine kaputte Datei stoppt den Lauf nicht
        zaehler["fehler"] += 1
        print(f"  spool {datei}: {type(fehler).__name__}: {str(fehler)[:120]}", file=sys.stderr)


def _befehl_ingest_spool(args: argparse.Namespace) -> int:
    """`ingest-spool <verzeichnis> [--db]` (C14-Nachtrag Server-Spool, CONTRACTS.md): ingestet
    Transkripte aus einem per `Hole-Sitzungsspool.ps1` abgeholten Server-Spool -- persona/kanal
    kommen je Eintrag aus `meta.jsonl`, nicht aus der Umgebung (anders als `--hook`). Fehlendes
    `meta.jsonl`/leeres Verzeichnis: saubere Meldung, Exit 0."""
    verzeichnis = Path(args.verzeichnis)
    eintraege = _meta_eintraege(verzeichnis)
    zaehler = {"neu": 0, "vorhanden": 0, "fehler": 0}
    if not eintraege:
        print(f"ingest-spool: keine Eintraege in {verzeichnis / 'meta.jsonl'}")
        return 0
    for eintrag in eintraege:
        _ingest_spool_eintrag(verzeichnis, eintrag, args, zaehler)
    print("ingest-spool: " + " · ".join(f"{k}={v}" for k, v in zaehler.items()))
    return 0


def _reingest_block(quelle: str, pfad: Path, args: argparse.Namespace) -> str | None:
    """SQL-Block für eine Sitzung, oder None (kein vorhandener Stand -> überspringen, normal
    per `ingest-dir --db` nachholbar). Wirft bei Lese-/Redaktionsproblemen -- der Aufrufer
    fängt das fail-open ab, wie `_ingest_eine_datei`."""
    beleg = beleg_erzeugen(quelle, str(pfad), args.preise, args.host)
    _bereinigt_oder_fehler(beleg)  # C1: Redaktions-Sperre gilt auch hier
    sitzung_id = reingest.finde_sitzung_id(args.host, quelle, beleg.kopf.sitzung_id)
    if sitzung_id is None:
        return None
    return reingest.sql_reingest_zeile(beleg.als_dict(), sitzung_id)


def _admin_ausfuehr_befehl(out_pfad: str) -> str:
    """Befehl, mit dem eine generierte SQL-Datei manuell als Admin-Rolle ausgefuehrt wird
    (reingest-sql UND retention-sql -- beide schreiben nie selbst, siehe Modul-Docstrings).
    Container aus `speicher.CONTAINER` (konfigurierbar, s. SITZUNGSBELEG_PG_CONTAINER) --
    `ledger_admin` bleibt literal, das ist eine andere Rolle als `speicher.ROLLE`
    (`ledger_app`, die App-Rolle hat per GRANT/REVOKE kein DELETE-Recht)."""
    return (
        f"docker exec -i {speicher.CONTAINER} psql -U ledger_admin -d {speicher.DATENBANK} "
        f"-v ON_ERROR_STOP=1 -f - < {out_pfad}"
    )


def _reingest_eine_datei(quelle: str, pfad: Path, args: argparse.Namespace,
                          bloecke: list[str], zaehler: dict) -> None:
    """Ein Transkript: SQL-Block anhängen oder überspringen + zählen -- eine kaputte Datei
    stoppt den Lauf nicht (wie `_ingest_eine_datei`)."""
    try:
        block = _reingest_block(quelle, pfad, args)
    except Exception as fehler:
        zaehler["uebersprungen"] += 1
        print(f"  {quelle} {pfad.name}: {type(fehler).__name__}: {str(fehler)[:120]}", file=sys.stderr)
        return
    if block is None:
        zaehler["uebersprungen"] += 1
        return
    bloecke.append(block)
    zaehler["aktualisiert"] += 1


def _befehl_reingest_sql(args: argparse.Namespace) -> int:
    """Berechnet alle Sitzungen der letzten --tage Tage neu und schreibt eine UPDATE-SQL-Datei
    (IDs bleiben erhalten). Nur lesende DB-Zugriffe (`reingest.finde_sitzung_id`); die Datei
    selbst führt der Maintainer manuell aus."""
    seit = datetime.now() - timedelta(days=args.tage)
    quellen_liste = ["claude", "codex"] if args.quelle == "alle" else [args.quelle]
    bloecke: list[str] = []
    zaehler = {"aktualisiert": 0, "uebersprungen": 0}
    for quelle in quellen_liste:
        for pfad in _transkripte(quelle, seit):
            _reingest_eine_datei(quelle, pfad, args, bloecke, zaehler)
    Path(args.out).write_text(reingest.baue_datei(bloecke), encoding="utf-8")
    print(f"reingest-sql: aktualisiert={zaehler['aktualisiert']} "
          f"uebersprungen={zaehler['uebersprungen']} datei={args.out}")
    print(f"Ausführen: {_admin_ausfuehr_befehl(args.out)}")
    return 0


def _default_retention_pfad() -> str:
    return f"_work_sitzungsbeleg/{datetime.now():%Y-%m-%d}-retention.sql"


def _retention_ausgabe(treffer: list[dict], args: argparse.Namespace) -> int:
    """--zaehlen/--vorschau (rein lesend) oder die SQL-Datei schreiben (Default)."""
    if args.zaehlen:
        print(f"retention-sql: {len(treffer)} Sitzung(en) betroffen")
        return 0
    if args.vorschau:
        for t in treffer:
            print(f"{t['logisch_ref']}\t{t['beginn']}\t{t['quelle_anzeige']}")
        return 0
    Path(args.out).write_text(
        retention.baue_datei(treffer, args.aelter_als, args.quelle), encoding="utf-8"
    )
    print(f"retention-sql: betroffen={len(treffer)} datei={args.out}")
    print(f"Ausführen: {_admin_ausfuehr_befehl(args.out)}")
    return 0


def _befehl_retention_sql(args: argparse.Namespace) -> int:
    """Erzeugt eine DELETE-SQL-Datei fuer alte Sitzungen (CONTRACTS.md Abschnitt "Retention").
    Nur lesende DB-Zugriffe (`retention.betroffene_sitzungen`); die Datei fuehrt der Maintainer manuell
    als `ledger_admin` aus -- `ledger_app` (Ingest UND Dashboard) hat kein DELETE-Recht."""
    try:
        quelle = retention.pruefe_argumente(args.aelter_als, args.quelle)
    except retention.RetentionFehler as fehler:
        print(f"retention-sql: {fehler}", file=sys.stderr)
        return 2
    args.quelle = quelle
    treffer = retention.betroffene_sitzungen(args.host, quelle, args.aelter_als)
    return _retention_ausgabe(treffer, args)


def _beleg_aus_dict(daten: dict) -> Beleg:
    """Baut einen Beleg aus gespeichertem JSON (Feldstruktur wie als_dict())."""
    from . import modell as m

    kopf = m.Kopf(**daten["kopf"])
    erfassung = m.Erfassung(**daten["erfassung"])
    kz = dict(daten["kennzahlen"])
    kz["token"] = m.Token(**kz["token"])
    kennzahlen_obj = m.Kennzahlen(**kz)
    ereignisse = [
        m.Ereignis(**{**e, "token": m.Token(**e["token"]) if e.get("token") else None})
        for e in daten.get("ereignisse", [])
    ]
    subagenten = [
        m.Subagent(**{**s, "token": m.Token(**s["token"])}) for s in daten.get("subagenten", [])
    ]
    auffaelligkeiten = [m.Auffaelligkeit(**a) for a in daten.get("auffaelligkeiten", [])]
    return m.Beleg(
        kopf=kopf, erfassung=erfassung, kennzahlen=kennzahlen_obj,
        ereignisse=ereignisse, subagenten=subagenten, auffaelligkeiten=auffaelligkeiten,
        schema_version=daten.get("schema_version", m.SCHEMA_VERSION),
    )


def _beleg_laden(args: argparse.Namespace) -> Beleg:
    """--id aus der DB, sonst --json von Platte."""
    if args.id is not None:
        return _beleg_aus_dict(speicher.lade_dokument(args.id))
    with open(args.json, encoding="utf-8") as f:
        return _beleg_aus_dict(json.load(f))


def _befehl_report(args: argparse.Namespace) -> int:
    return _ausgeben(_beleg_laden(args), None, None)


def _befehl_review(args: argparse.Namespace) -> int:
    """Vier-Augen: Befunde -> Claude (Sonnet) + Codex -> Abgleich; Ergebnis in den Ereignisstrom."""
    beleg = _bereinigt_oder_fehler(_beleg_laden(args))
    frager_codex = (lambda _t: "[]") if args.ohne_codex else vieraugen.frage_codex
    ergebnis = vieraugen.review(beleg, frager_codex=frager_codex)
    if args.id is not None:
        ergebnis["sitzung_ref"] = args.id
    try:
        speicher.ereignis_schreiben("vieraugen", "review", ergebnis, args.host)
    except speicher.SpeicherFehler as fehler:
        print(f"Warnung: Ergebnis nicht protokolliert — {fehler}", file=sys.stderr)
    text = vieraugen.als_markdown(ergebnis)
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 1 if ergebnis["dissens"] else 0


def _modelle_aus_feld(feld: str) -> list[str]:
    """Drittes stdin-Feld ist die JSON-Textform von `dokument->kopf->modelle`
    (`dokument->'kopf'->>'modelle'` in Postgres, z. B. `["glm-5.2:cloud"]`) -- leer/kaputt
    wird als „keine Modellangabe" behandelt statt den Wächter-Lauf abzubrechen."""
    if not feld:
        return []
    try:
        werte = json.loads(feld)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(w) for w in werte] if isinstance(werte, list) else []


def _befehl_aliase(args: argparse.Namespace) -> int:
    """`aliase --pruefen`: stdin = `<projekt>|<quelle>|<modelle_json>`-Zeilen (psql -qAt), eine
    je distinct (projekt, quelle, modelle) aus `sitzung` -- Grundlage fuer
    scripts/check-projekt-aliase.ps1. Meldet unzugeordnete Rohnamen (Projekt+Kontext) UND
    Modelle ohne Registry-Herkunft (Entscheid 2026-08-26, Auftrag 2: `quellen.py`), Exit 1
    wenn eine der beiden Prüfungen etwas findet (ADR 0004: der Wächter zählt erst, wenn er
    seinen Fehler einmal rot gemeldet hat). Das dritte Feld ist optional (Rückwärtskompatibilität
    zu einer stdin-Quelle ohne Modellspalte) -- fehlt es, entfällt nur die Modellprüfung."""
    if not args.pruefen:
        return 0
    aliase = projekte.lade_aliase()
    unzugeordnet: set[str] = set()
    unbekannte_modelle: set[str] = set()
    for zeile in sys.stdin.read().splitlines():
        if not zeile.strip():
            continue
        teile = zeile.split("|")
        roh = teile[0].strip()
        quelle = teile[1].strip() if len(teile) > 1 else ""
        if not roh:
            continue
        _projekt, kontext, _ausgeblendet = projekte.aufloesen(roh, quelle, aliase)
        if kontext == projekte.UNZUGEORDNET:
            unzugeordnet.add(roh)
        modelle = _modelle_aus_feld(teile[2].strip()) if len(teile) > 2 else []
        unbekannte_modelle.update(quellen.unbekannte_modelle(quelle, modelle))
    for roh in sorted(unzugeordnet):
        print(f"{roh} -> ?/arbeit")
    for modell in sorted(unbekannte_modelle):
        print(f"modell ohne registry-herkunft: {modell}")
    return 1 if (unzugeordnet or unbekannte_modelle) else 0


def _entscheid_ereignis_schreiben(detail: dict, host: str) -> str | None:
    """Schreibt das Entscheid-Ereignis, liefert eine Fehlermeldung statt zu werfen -- C11:
    `ContractFehler` bei `erledigt` ohne Verankerung (diese CLI kennt noch kein `--verankerung`,
    dieselbe Regel wie web.py 400 statt eines Absturzes), sonst `SpeicherFehler` wie bisher."""
    try:
        speicher.ereignis_schreiben("gf", "befund_entscheid", detail, host)
    except (contracts.ContractFehler, speicher.SpeicherFehler) as fehler:
        return str(fehler)
    return None


def _befehl_entscheid(args: argparse.Namespace) -> int:
    """`entscheid --signatur <sig> --status erledigt|obsolet [--sitzung <id>] [...]` --
    Erledigt-Feature je Befund, damit ein Analyse-Gespräch denselben Status setzen kann wie das
    Dashboard (POST /api/befund/entscheid)."""
    try:
        detail = befunde.entscheid_bauen(
            args.signatur, args.status, args.vermerk or "", args.begruendung or "", args.sitzung
        )
    except befunde.EntscheidFehler as fehler:
        print(f"entscheid: {fehler}", file=sys.stderr)
        return 2
    fehler = _entscheid_ereignis_schreiben(detail, args.host)
    if fehler:
        print(f"entscheid: {fehler}", file=sys.stderr)
        return 2
    print(f"entscheid: {detail['signatur']} -> {detail['status']}")
    return 0


def _befehl_anbieter_test(args: argparse.Namespace) -> int:
    """`anbieter-test <anbieter>` (Auftrag Requesty 2026-08-28): EIN kurzer `claude -p`-Lauf
    ueber `chat_bruecke` -- Modell aus `--modell` oder `modelle.json default_vico_<anbieter>`.
    Zeigt HTTP-/Fehlertext, damit die Header-/Auth-Frage eines neuen Anbieters live geklaert
    werden kann, sobald ein echter Schluessel vorliegt (`scripts\\.env.<anbieter>`)."""
    from . import chat_bruecke

    registry = {}
    if MODELLE_PFAD.exists():
        with open(MODELLE_PFAD, encoding="utf-8") as f:
            registry = json.load(f)
    modell = args.modell or registry.get(f"default_vico_{args.anbieter}")
    if not modell:
        print(f"kein Modell: --modell fehlt und default_vico_{args.anbieter} nicht in modelle.json",
              file=sys.stderr)
        return 2
    print(chat_bruecke.teste_anbieter(args.anbieter, modell))
    return 0


def _befehl_nachschlagen(args: argparse.Namespace) -> int:
    """`nachschlagen <nr> [--befund <signatur>]` (Auftrag Sichtkontext 2026-08-28): NUR
    lesendes Werkzeug fuer den Hintergrund-Chat (`chat_bruecke.CHAT_ALLOWED_TOOLS`) -- derselbe
    `web._sitzung()`-Aufruf wie die Detailseite, `chat_kennzahlen.baue_nachschlage_text()` baut
    daraus Kennzahlen + Befundliste. Jeder Fehler (unbekannte Nr, DB kurz nicht erreichbar) meldet
    nur "nicht gefunden" -- kein Rohtext/Traceback, Exit bleibt IMMER 0 (ein Lesewerkzeug darf den
    Hintergrund-Chat nie abbrechen lassen)."""
    from . import chat_kennzahlen
    from .web import _sitzung

    try:
        antwort = _sitzung(args.nr)
    except Exception:
        print(f"Sitzung {args.nr} nicht gefunden")
        return 0
    print(chat_kennzahlen.baue_nachschlage_text(antwort, args.befund))
    return 0


def _verankerung_repo_wurzel(args: argparse.Namespace) -> Path:
    """Repo-Wurzel fuer die Pfad-Existenzpruefung -- per `--repo` ODER Env ueberschreibbar
    (Tests: ein Tempdir-Repo statt der echten Vault), sonst `verankerung.REPO_WURZEL`."""
    if args.repo:
        return Path(args.repo)
    env = os.environ.get("SITZUNGSBELEG_REPO_ROOT")
    return Path(env) if env else verankerung.REPO_WURZEL


def _verankerung_entscheide(args: argparse.Namespace, seit: date) -> list[dict]:
    """stdin (Selftest, ADR 0004: `aliase --pruefen`-Muster) ODER die echte DB -- eigene Funktion
    haelt `_befehl_verankerung_pruefen` unter der 20-Zeilen-Richtlinie (check-code-masse.ps1 b)."""
    if args.stdin:
        return json.loads(sys.stdin.read() or "[]")
    return verankerung.erledigte_entscheide(seit)


def _befehl_verankerung_pruefen(args: argparse.Namespace) -> int:
    """`verankerung-pruefen [--von YYYY-MM-DD] [--json] [--stdin]` (C11, Entscheid 2026-08-28):
    nur SELECT ueber `speicher` (wie `nachschlagen`) -- Grundlage fuer
    `scripts\\check-verankerung.ps1`. Exit 1, sobald mindestens ein NICHT-Legacy-Entscheid ROT ist."""
    seit = datetime.strptime(args.von, "%Y-%m-%d").date() if args.von else date.today() - timedelta(
        days=verankerung.STANDARD_TAGE
    )
    try:
        entscheide = _verankerung_entscheide(args, seit)
    except speicher.SpeicherFehler as fehler:
        print(f"verankerung-pruefen: nicht erreichbar — {fehler}", file=sys.stderr)
        return 2
    befunde_liste = verankerung.pruefe(entscheide, _verankerung_repo_wurzel(args))
    print(json.dumps(verankerung.als_json(befunde_liste), ensure_ascii=False) if args.json
          else verankerung.ausgabe_text(befunde_liste))
    return 1 if verankerung.rote_befunde(befunde_liste) else 0


def _befehl_serve(args: argparse.Namespace) -> int:
    from .web import serve

    serve(log_datei=Path(args.log) if args.log else None, port=args.port)
    return 0


def _baue_retention_parser(unter) -> None:
    """Eigene Funktion statt Inline-Block in `_parser` (die schon vor dieser Ergaenzung ueber
    der 20-Zeilen-Richtlinie lag, `check-code-masse.ps1` Regel b) -- kein weiteres Wachstum."""
    p = unter.add_parser("retention-sql", help="alte Sitzungen -> DELETE-SQL-Datei (Retention, CONTRACTS.md)")
    p.add_argument("--aelter-als", type=int, required=True, dest="aelter_als",
                    help=f"Tage seit Sitzungsbeginn, Mindestwert {retention.MINDEST_TAGE}")
    p.add_argument("--quelle", choices=["claude", "codex", "ollama", "openrouter", "requesty", "alle"],
                    default=None, help="'alle' explizit angeben, kein stiller Default")
    p.add_argument("--host", default="pc")
    p.add_argument("--out", default=_default_retention_pfad())
    p.add_argument("--zaehlen", action="store_true", help="nur Anzahl betroffener Sitzungen (lesend)")
    p.add_argument("--vorschau", action="store_true", help="betroffene sitzung_logisch-IDs (lesend)")
    p.set_defaults(func=_befehl_retention_sql)


def _baue_verankerung_parser(unter) -> None:
    """Eigene Funktion statt Inline-Block in `_parser` (gleiches Muster wie
    `_baue_retention_parser` -- kein weiteres Wachstum ueber der 20-Zeilen-Richtlinie)."""
    p = unter.add_parser(
        "verankerung-pruefen", help="C11: erledigte Entscheide seit --von auf Verankerung pruefen"
    )
    p.add_argument("--von", default=None, help="YYYY-MM-DD, Default 90 Tage zurueck")
    p.add_argument("--json", action="store_true")
    p.add_argument("--repo", default=None, help="Repo-Wurzel ueberschreiben (Tests)")
    p.add_argument("--stdin", action="store_true", help="JSON-Array Entscheide von stdin statt DB (Selftest)")
    p.set_defaults(func=_befehl_verankerung_pruefen)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sitzungsbeleg")
    unter = parser.add_subparsers(dest="befehl", required=True)

    p_ingest = unter.add_parser("ingest", help="ein Transkript -> Beleg (optional in die DB)")
    p_ingest.add_argument("--quelle", choices=["claude", "codex"], default="claude")
    p_ingest.add_argument("--datei")
    p_ingest.add_argument("--session", help="Sitzungs-ID statt --datei")
    p_ingest.add_argument("--hook", action="store_true", help="Stop-Hook: stdin-JSON, immer Exit 0")
    p_ingest.add_argument("--db", action="store_true", help="in Postgres speichern + Querschnitt")
    p_ingest.add_argument("--host", default="pc")
    p_ingest.add_argument("--preise")
    p_ingest.add_argument("--json")
    p_ingest.add_argument("--markdown")
    p_ingest.set_defaults(func=_befehl_ingest)

    p_dir = unter.add_parser("ingest-dir", help="alle Transkripte der letzten N Tage")
    p_dir.add_argument("--quelle", choices=["claude", "codex", "alle"], default="alle")
    p_dir.add_argument("--seit", type=int, default=30, help="Tage (Dateiänderung)")
    p_dir.add_argument("--db", action="store_true")
    p_dir.add_argument("--host", default="pc")
    p_dir.add_argument("--preise")
    p_dir.set_defaults(func=_befehl_ingest_dir)

    p_spool = unter.add_parser(
        "ingest-spool", help="C14-Nachtrag: Server-Spool (meta.jsonl) -> Belege, persona/kanal je Zeile"
    )
    p_spool.add_argument("verzeichnis", help="Spool-Verzeichnis mit Transkripten + meta.jsonl")
    p_spool.add_argument("--db", action="store_true")
    p_spool.add_argument("--host", default="pc")
    p_spool.add_argument("--preise")
    p_spool.set_defaults(func=_befehl_ingest_spool)

    for name, func in (("report", _befehl_report), ("review", _befehl_review)):
        p = unter.add_parser(name)
        p.add_argument("--id", type=int, help="sitzung.id aus der DB")
        p.add_argument("--json", help="Beleg-JSON von Platte")
        p.add_argument("--host", default="pc")
        if name == "review":
            p.add_argument("--markdown")
            p.add_argument("--ohne-codex", action="store_true")
        p.set_defaults(func=func)

    p_reingest = unter.add_parser(
        "reingest-sql", help="Belege neu berechnen -> UPDATE-SQL-Datei (IDs bleiben erhalten)"
    )
    p_reingest.add_argument("--quelle", choices=["claude", "codex", "alle"], default="alle")
    p_reingest.add_argument("--tage", type=int, default=30, help="Tage (Dateiänderung)")
    p_reingest.add_argument("--host", default="pc")
    p_reingest.add_argument("--preise")
    p_reingest.add_argument("--out", required=True, help="Pfad der erzeugten SQL-Datei")
    p_reingest.set_defaults(func=_befehl_reingest_sql)

    _baue_retention_parser(unter)

    p_serve = unter.add_parser("serve", help="Dashboard auf 127.0.0.1:8091 starten")
    p_serve.add_argument("--log", default=None,
                         help="Logdatei; damit loest sich der Server von der Konsole (Task-Betrieb)")
    p_serve.add_argument("--port", type=int, default=8091, help="nur fuer Tests, Standard 8091")
    p_serve.set_defaults(func=_befehl_serve)

    p_anbieter_test = unter.add_parser(
        "anbieter-test", help="kurzer claude -p-Testlauf gegen einen Chat-Anbieter (Header/Auth pruefen)"
    )
    p_anbieter_test.add_argument("anbieter", choices=["claude", "ollama", "openrouter", "requesty"])
    p_anbieter_test.add_argument("--modell", default=None, help="Default: modelle.json default_vico_<anbieter>")
    p_anbieter_test.set_defaults(func=_befehl_anbieter_test)

    p_aliase = unter.add_parser("aliase", help="Projekt-Alias-Zuordnung prüfen")
    p_aliase.add_argument("--pruefen", action="store_true", help="stdin: <projekt>|<quelle>-Zeilen")
    p_aliase.set_defaults(func=_befehl_aliase)

    p_katalog = unter.add_parser(
        "katalog-update",
        help="Modellkatalog beschaffen+anreichern (C15 v2): OpenRouter/Requesty live, "
             "Claude/Ollama aus modelle.json, aa = Artificial-Analysis-Indizes nachtragen"
    )
    p_katalog.add_argument("--anbieter", choices=["claude", "ollama", "openrouter", "requesty", "aa"],
                            default=None, help="Default: alle vier Quellen + AA-Anreicherung")
    p_katalog.add_argument("--db", action="store_true", help="in Postgres upserten (sonst nur Beschaffung/Zaehlung)")
    p_katalog.set_defaults(func=katalog.befehl_katalog_update)

    p_nachschlagen = unter.add_parser(
        "nachschlagen", help="Kennzahlen + Befundliste einer Sitzung (nur lesend, Chat-Werkzeug)"
    )
    p_nachschlagen.add_argument("nr", type=int)
    p_nachschlagen.add_argument("--befund", default=None, help="nur diese Signatur")
    p_nachschlagen.set_defaults(func=_befehl_nachschlagen)

    p_entscheid = unter.add_parser("entscheid", help="Befund-Status setzen (Erledigt-Feature)")
    p_entscheid.add_argument("--signatur", required=True)
    p_entscheid.add_argument("--status", required=True, choices=list(befunde.STATUS))
    p_entscheid.add_argument("--vermerk", default="")
    p_entscheid.add_argument("--begruendung", default="")
    p_entscheid.add_argument("--sitzung", type=int, default=None, help="sitzung.id (leer = gilt global)")
    p_entscheid.add_argument("--host", default="pc")
    p_entscheid.set_defaults(func=_befehl_entscheid)

    _baue_verankerung_parser(unter)

    p_wache = unter.add_parser("wache", help="C13: PreToolUse-Hook, Regeln waehrend der Sitzung (fail-open)")
    p_wache.add_argument("--sofort", action="store_true", help="Drossel umgehen (Testhilfe/Live-Probe)")
    p_wache.set_defaults(func=wache.befehl_wache)

    p_wache_cache = unter.add_parser(
        "wache-cache", help="C13: Entscheide-Cache der Wache neu schreiben (nur SELECT)"
    )
    p_wache_cache.set_defaults(func=wache_cache.befehl_wache_cache)

    return parser


def _pruefe_argumente(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.befehl == "ingest" and not (args.datei or args.session or args.hook):
        parser.error("ingest braucht --datei, --session oder --hook")
    if args.befehl in ("report", "review") and args.id is None and not args.json:
        parser.error(f"{args.befehl} braucht --id oder --json")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows-Konsole: cp1252 zerstört Gedankenstriche/Umlaute
    parser = _parser()
    args = parser.parse_args(argv)
    _pruefe_argumente(args, parser)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
