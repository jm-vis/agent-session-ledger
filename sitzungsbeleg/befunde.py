"""Erledigt-Feature je Befund (Entscheid 2026-08-26, Auftrag 3).

Befunde (`Auffaelligkeit`, Feld `signatur`) sind append-only im Beleg-JSON. Ein Status
kommt NICHT als Update, sondern als eigenes Entscheid-Ereignis in den bestehenden
Ereignisstrom: `ereignis(quelle='gf', typ='befund_entscheid', detail={...})` -- dieselbe
Tabelle wie das Vier-Augen-Ergebnis (`speicher.ereignis_schreiben`), keine neue Migration.

Regeln: der Entscheid gilt für die SIGNATUR (alle Sitzungen), optional nur für eine
Sitzung (`sitzung_ref` gesetzt); der jüngste Entscheid je (signatur, sitzung_ref)-Paar
gewinnt. Status `offen` (dritter Wert, Entscheid B 2026-08-26) ist eine
WIEDERERÖFFNUNG: er wird als eigenes Entscheid-Ereignis geschrieben wie jeder andere
Status, gilt aber überall wie „kein passender Entscheid gefunden" -- schreibt man ihn
NACH einem `erledigt`/`obsolet`, gewinnt er als jüngster und der Befund zählt wieder
als offen.
"""
from __future__ import annotations

from datetime import datetime, timezone

STATUS = ("erledigt", "obsolet", "offen")
MAX_TEXT = 500


class EntscheidFehler(ValueError):
    """Body/Argumente ungültig -- Status-Enum, Textlänge, fehlende Signatur."""


def _text(wert, feld: str) -> str:
    text = "" if wert is None else str(wert)
    if len(text) > MAX_TEXT:
        raise EntscheidFehler(f"{feld}: über {MAX_TEXT} Zeichen")
    return text


def _verankerung_normalisiert(wert: dict | None) -> dict | None:
    """C11: nur Grundform pruefen (art/pfad Pflicht, getrimmt) -- die volle Kontract-Pruefung
    (erlaubte `art`-Werte, `pfad`-Sicherheit/ASCII) macht `contracts.Verankerung` erst beim
    Schreiben (`speicher.ereignis_schreiben`), damit hier keine Regel dupliziert wird."""
    if wert is None:
        return None
    if not isinstance(wert, dict):
        raise EntscheidFehler("verankerung: muss ein Objekt sein")
    art = str(wert.get("art") or "").strip()
    pfad = str(wert.get("pfad") or "").strip()
    if not art or not pfad:
        raise EntscheidFehler("verankerung: art und pfad sind Pflicht")
    return {"art": art, "pfad": pfad, "abschnitt": str(wert.get("abschnitt") or "").strip()}


def _detail_grundform(signatur, status, vermerk, begruendung, sitzung_ref, entschieden_von, jetzt) -> dict:
    return {
        "signatur": signatur,
        "sitzung_ref": int(sitzung_ref) if sitzung_ref is not None else None,
        "status": status,
        "vermerk": _text(vermerk, "vermerk"),
        "begruendung": _text(begruendung, "begruendung"),
        "entschieden_am": jetzt.isoformat(),
        "entschieden_von": entschieden_von or "Maintainer",
    }


def entscheid_bauen(
    signatur: str,
    status: str,
    vermerk: str = "",
    begruendung: str = "",
    sitzung_ref: int | None = None,
    entschieden_von: str = "Maintainer",
    jetzt: datetime | None = None,
    verankerung: dict | None = None,
) -> dict:
    """Baut das `detail`-Dict für ein `befund_entscheid`-Ereignis, geprüft und normalisiert.
    `verankerung` (C11, optional) landet nur im Dict, wenn mitgegeben -- ob `erledigt` sie
    VERLANGT, entscheidet `contracts.BefundEntscheid` (Dual-Reader, Bestand ohne das Feld bleibt gueltig)."""
    signatur = (signatur or "").strip()
    if not signatur:
        raise EntscheidFehler("signatur: fehlt")
    if status not in STATUS:
        raise EntscheidFehler(f"status: muss einer von {STATUS} sein, nicht {status!r}")
    detail = _detail_grundform(signatur, status, vermerk, begruendung, sitzung_ref, entschieden_von,
                                jetzt or datetime.now(timezone.utc))
    verankerung_normalisiert = _verankerung_normalisiert(verankerung)
    if verankerung_normalisiert is not None:
        detail["verankerung"] = verankerung_normalisiert
    return detail


def juengster_je_signatur_und_sitzung(
    entscheide: list[dict], signatur: str, sitzung_id: int | None
) -> dict | None:
    """Jüngster Entscheid, der auf `(signatur, sitzung_id)` passt -- global (sitzung_ref
    None) oder exakt für diese Sitzung. `None`, wenn keiner passt (= Status `offen`)."""
    passend = [
        e for e in entscheide
        if e.get("signatur") == signatur and e.get("sitzung_ref") in (None, sitzung_id)
    ]
    if not passend:
        return None
    return max(passend, key=lambda e: str(e.get("entschieden_am", "")))


def entschiedene_signaturen(entscheide: list[dict], sitzung_id: int | None = None) -> set[str]:
    """Ausschlussmenge fürs Zählen „nur offene Befunde": Signaturen, deren JÜNGSTER
    passender Entscheid (global `sitzung_ref=None` oder exakt für `sitzung_id`) `erledigt`
    oder `obsolet` ist. Status `offen` gewinnt er als jüngster, zählt die Signatur wieder
    als offen -- taucht darum NICHT in dieser Menge auf."""
    signaturen = {e.get("signatur") for e in entscheide if e.get("signatur")}
    entschieden: set[str] = set()
    for sig in signaturen:
        treffer = juengster_je_signatur_und_sitzung(entscheide, sig, sitzung_id)
        if treffer is not None and treffer.get("status") != "offen":
            entschieden.add(sig)
    return entschieden


def _rueckfall_ergebnis(entschieden_am: str, rueckfaellig: list[dict]) -> dict:
    return {
        "status": "rueckfall", "entschieden_am": entschieden_am,
        "rueckfall_treffer": sum(int(s.get("treffer", 0)) for s in rueckfaellig),
        "rueckfall_sitzungen": {
            "anzahl": len({s["sitzung_id"] for s in rueckfaellig}),
            "sitzung_ids": sorted({int(s["sitzung_id"]) for s in rueckfaellig}),
        },
    }


def status_mit_rueckfall(entscheide: list[dict], signatur: str, sitzungen: list[dict]) -> dict:
    """Rückfall (Korrektur Nachtrag 2026-08-27 Punkt 4, C2: "Rückfall nur nach `erledigt`"): NUR
    ein juengster globaler `erledigt`-Entscheid kann durch eine spaetere Sitzung (`sitzungen`, je
    `{"sitzung_id", "zeit": ISO-Text, "treffer"}`) zu `rueckfall` werden -- `obsolet` bleibt
    IMMER `obsolet` (bisher faelschlich RUECKFALL, live an Sitzung 137 verifiziert). Ein
    spaeterer `offen`-Entscheid gewinnt wie ueberall als juengster."""
    entscheid = juengster_je_signatur_und_sitzung(entscheide, signatur, None)
    if entscheid is None or entscheid.get("status") == "offen":
        return {"status": "offen"}
    entschieden_am = str(entscheid.get("entschieden_am", ""))
    if entscheid["status"] != "erledigt":
        return {"status": entscheid["status"], "entschieden_am": entschieden_am}
    rueckfaellig = [s for s in sitzungen if str(s.get("zeit", "")) > entschieden_am]
    if not rueckfaellig:
        return {"status": entscheid["status"], "entschieden_am": entschieden_am}
    return _rueckfall_ergebnis(entschieden_am, rueckfaellig)
