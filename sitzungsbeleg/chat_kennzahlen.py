"""Kompakter Kennzahlen-Block fuer den Chat-Kontext (Fund 2026-08-27: die Besprechungs-Spalte
kannte nur die Sitzungs-ID, kein Modell konnte Kennzahlenfragen beantworten -- CONTRACTS.md C7
`kennzahlen_block`). `baue_block()` liest NUR aus der Antwort von `web._sitzung()` -- derselben
Quelle wie die Detailseite, keine zweite Berechnung der Kennzahlen. Personen-/inhaltsfrei (nur
Zahlen, Bezeichner, Regel-IDs, kurze Regeltitel); laeuft danach durch `redaktion.bereinige_text()`
(C3-Allowlist: ein einziger Verstoss redigiert den GANZEN Block) und wird auf `MAX_ZEICHEN`
gekuerzt. Wichtig fuer eigene Formatierungen hier: KEINE Schraeg-/Backslashes (C3 wertet jeden
als Pfadverdacht) -- Trennzeichen sind Kommas, nie "/".
"""
from __future__ import annotations

from . import quellen, redaktion
from .ausgabe import dauer_lesbar

MAX_ZEICHEN = 1500
MAX_BEFUNDE = 12


def _tausender(n: int) -> str:
    """Deutsche Tausendertrennung (Punkt statt Komma), Muster ``ausgabe._kennzahlen_tabelle``."""
    return f"{n:,}".replace(",", ".")


def _kompakt_zahl(n: int) -> str:
    """>= 1 Mio -> 'X,YM' (eine Nachkommastelle, deutsches Komma), sonst Tausendertrennung --
    Cache-Zaehler sind oft zweistellig-Millionen, ein Punkt-getrennter Rohwert waere unlesbar."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".replace(".", ",") + "M"
    return _tausender(n)


def _kopfzeile(antwort: dict) -> str:
    kopf = antwort.get("dokument", {}).get("kopf", {}) or {}
    roh = kopf.get("modelle") or []
    modelle = ", ".join(m for m in roh if m != quellen.SYNTHETISCH) or "unbekannt"
    return (f"Sitzung {antwort.get('sitzung_logisch')}, Projekt {kopf.get('projekt_name') or 'unbekannt'}, "
            f"Quelle {kopf.get('quelle', '')}, Modell {modelle}, Start {kopf.get('start', '')}")


def _anteil(zaehler: float, nenner: float) -> float:
    """Bruch 0..1, Nenner <= 0 -> 0.0 (gleiche Regel wie ``delegation._quote``)."""
    return (zaehler / nenner) if nenner else 0.0


def _kosten_text(k: dict) -> str:
    kosten = k.get("kosten_gesamt")
    if kosten is None:
        return "unbekannt"
    return f"{kosten:.4f} {k.get('kosten_waehrung') or '?'}"


def _kennzahlen_zeile(k: dict) -> str:
    token = k.get("token") or {}
    cache = token.get("cache_read", 0) + token.get("cache_write", 0)
    return (f"Dauer {dauer_lesbar(k.get('dauer_ms', 0))}, Runden {k.get('runden', 0)}, "
            f"Tools {k.get('tools', 0)} (Fehler {k.get('tool_fehler', 0)}), "
            f"Token ein {_tausender(token.get('input', 0))}, aus {_tausender(token.get('output', 0))}, "
            f"cache {_kompakt_zahl(cache)}, Kosten {_kosten_text(k)}, "
            f"Latenz p50 {dauer_lesbar(k.get('latenz_p50_ms', 0))}, p95 {dauer_lesbar(k.get('latenz_p95_ms', 0))}, "
            f"Compactions {k.get('compactions', 0)}")


def _subagenten_zeile(k: dict) -> str:
    anteil = _anteil(k.get("kosten_subagenten") or 0.0, k.get("kosten_gesamt") or 0.0)
    return f"Subagenten {k.get('subagenten', 0)} (Kostenanteil {anteil:.0%})"


def _pruefung_kurz(a: dict) -> str:
    pruefung = a.get("pruefung")
    if not pruefung:
        return ""
    return f" Claude={pruefung.get('claude') or '-'} Codex={pruefung.get('codex') or '-'}"


def _ohne_schraegstrich(text: str) -> str:
    """Regeltitel (regeltexte.py) sind fest verdrahtete UI-Texte, keine Transkript-/Nutzerdaten
    -- einer davon nutzt "/" als Wort-Oder (z. B. "Langsame Runde/Werkzeug"), was `bereinige_text`
    (C3: JEDER Schraegstrich = Pfadverdacht) sonst faelschlich den GANZEN Block redigieren liesse
    (live an Sitzung 137 verifiziert). Ersetzt statt zu verbieten -- die Bedeutung bleibt lesbar."""
    return text.replace("/", " bzw. ")


def _befund_zeile(a: dict) -> str:
    titel = _ohne_schraegstrich(a.get("titel") or a.get("regel", ""))
    return f"{a.get('regel', '')} [{a.get('status', 'offen')}] {titel}{_pruefung_kurz(a)}"


def _befunde_zeile(antwort: dict) -> str:
    liste = antwort.get("dokument", {}).get("auffaelligkeiten") or []
    if not liste:
        return "Befunde: keine"
    return "Befunde: " + "; ".join(_befund_zeile(a) for a in liste[:MAX_BEFUNDE])


def _vieraugen_zeile(antwort: dict) -> str:
    vieraugen = antwort.get("vieraugen")
    if not vieraugen:
        return ""
    return f"Vier-Augen (Altlauf): dissens {vieraugen.get('dissens', 0)}"


def _erfassung_zeile(antwort: dict) -> str:
    erfassung = antwort.get("dokument", {}).get("erfassung") or {}
    felder = ("token", "dauer", "kosten", "subagenten", "compaction", "reasoning")
    werte = " ".join(f"{feld}={erfassung.get(feld, 'not_observed')}" for feld in felder)
    return f"Erfassung: {werte}"


def baue_block(antwort: dict) -> str:
    """Kompletter Block aus der ``_sitzung()``-Antwort -- redigiert (C3) + auf ``MAX_ZEICHEN``
    gekuerzt. Ein einziger Verstoss (Pfad/Secret/E-Mail/``_lokal``) irgendwo im Block redigiert
    ihn GANZ (``redaktion.bereinige_text``, wie jedes andere Beleg-Feld)."""
    kennzahlen = antwort.get("dokument", {}).get("kennzahlen") or {}
    zeilen = [
        _kopfzeile(antwort),
        _kennzahlen_zeile(kennzahlen),
        _subagenten_zeile(kennzahlen),
        _befunde_zeile(antwort),
        _vieraugen_zeile(antwort),
        _erfassung_zeile(antwort),
    ]
    text = redaktion.bereinige_text("\n".join(z for z in zeilen if z))
    return text[:MAX_ZEICHEN]


# ---------- Nachschlage-Werkzeug (`python -m sitzungsbeleg nachschlagen`, 2026-08-28) ----------
# Auftrag "Dashboard-Ansicht ist fuer mich nicht sichtbar": der Hintergrund-Chat soll eine
# Sitzung selbst nachschlagen koennen, statt den Nutzer zu bitten, erst hineinzuklicken --
# derselbe Kennzahlen-Block (`baue_block`) PLUS die volle Befundliste mit Status und Vier-Augen-
# Urteil (ueber `MAX_BEFUNDE` hinaus, anders als der knappe Chat-Kontext-Block).
MAX_NACHSCHLAGE_ZEICHEN = 3000


def _urteil_kurz(pruefung: dict | None) -> str:
    if not pruefung:
        return "keine Pruefung"
    return (f"Claude={pruefung.get('claude') or '-'} Codex={pruefung.get('codex') or '-'} "
            f"Ergebnis={pruefung.get('ergebnis') or '-'}")


def _befund_voll_zeile(a: dict) -> str:
    titel = _ohne_schraegstrich(a.get("titel") or a.get("regel", ""))
    signatur = a.get("signatur") or a.get("regel", "")
    return f"{signatur} [{a.get('status', 'offen')}] {titel} -- {_urteil_kurz(a.get('pruefung'))}"


def _befundliste(antwort: dict, befund: str | None) -> str:
    liste = antwort.get("dokument", {}).get("auffaelligkeiten") or []
    if befund:
        liste = [a for a in liste if a.get("signatur") == befund]
        return "\n".join(_befund_voll_zeile(a) for a in liste) if liste else f"Befund {befund}: nicht gefunden"
    if not liste:
        return "Befunde: keine"
    return "Befunde:\n" + "\n".join(_befund_voll_zeile(a) for a in liste)


def baue_nachschlage_text(antwort: dict, befund: str | None = None) -> str:
    """`python -m sitzungsbeleg nachschlagen <nr> [--befund <signatur>]`: Kennzahlen-Block
    (``baue_block``) + volle Befundliste (Status + Vier-Augen-Urteil) -- redigiert, auf
    ``MAX_NACHSCHLAGE_ZEICHEN`` gekuerzt (ein einziger Verstoss redigiert wieder den GANZEN Text)."""
    text = baue_block(antwort) + "\n\n" + _befundliste(antwort, befund)
    return redaktion.bereinige_text(text)[:MAX_NACHSCHLAGE_ZEICHEN]
