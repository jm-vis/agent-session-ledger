"""Datenmodell des Sitzungsbelegs (schema_version 1).

Ein Beleg enthält NUR Zahlen, Zeitpunkte, Typen und Verweise — nie Inhalte
(keine Prompts, kein Denken, keine Tool-Argumente, keine Fehlertexte).
AUSNAHME (Entscheid 2026-08-26): ``Subagent.auftrag`` — das kurze
Auftrags-Label eines Subagenten-Aufrufs (``description``-Feld des
Agent-Aufrufs, z. B. „Block 4 Sitzungsdetail Feedback"), höchstens 80
Zeichen, mit „…" gekürzt, und wie jeder andere Beleg-String vor der Ausgabe
durch die generische Redaktionsstufe (redaktion.py) gelaufen — Pfad-/Secret-/
E-Mail-/``_lokal``-Muster oder Überlänge lösen dort weiterhin `<redigiert>`
aus. Kein Freitext (Prompt/Denken/Toolargumente) — nur dieses eine Kurzlabel.
Leser (leser_claude, leser_codex) füllen Ereignisse; kennzahlen/regeln
verdichten; redaktion prüft vor jeder Ausgabe.

Capture-Ehrlichkeit je Kanal:
  observed      gemessen aus der Quelle
  partial       teilweise vorhanden
  not_recorded  Quelle liefert es strukturell nicht
  not_observed  in dieser Sitzung nicht aufgetreten / nicht geprüft
  derived       berechnet (z. B. Kosten)
  redacted      bewusst nicht übernommen (Inhalte)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

SCHEMA_VERSION = 1

ERFASSUNG = ("observed", "partial", "not_recorded", "not_observed", "derived", "redacted")

# Ereignisarten (art) — gemeinsames Vokabular beider Leser
ART_NUTZER = "nutzer"            # Nutzer-Runde beginnt
ART_ASSISTENT = "assistent"      # Assistenten-Nachricht (mit usage)
ART_TOOL = "tool"                # Werkzeugaufruf (name = Tool-Typ)
ART_TOOL_ERGEBNIS = "tool_ergebnis"  # Ergebnis, fehler=True bei is_error / Exit≠0
ART_SUBAGENT = "subagent"        # Subagent gestartet (ref = agent_id)
ART_COMPACTION = "compaction"    # Kontext komprimiert
ART_RUNDE_ENDE = "runde_ende"    # turn_duration
ART_SYSTEM = "system"


@dataclass
class Token:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    thinking: int = 0

    def add(self, other: "Token") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_write += other.cache_write
        self.cache_read += other.cache_read
        self.thinking += other.thinking


@dataclass
class Ereignis:
    """Ein Punkt auf der Zeitleiste. Nie Inhalt — nur Typ, Zeit, Zahlen, Verweis."""
    zeit: str                      # ISO-8601 UTC, wie in der Quelle
    art: str                       # ART_*
    name: str = ""                 # Tool-Typ, Subagent-Typ, Modell — nie Argumente
    fehler: bool = False
    dauer_ms: Optional[int] = None
    token: Optional[Token] = None
    ref: str = ""                  # agent_id, tool_use_id, commit-hash — nie Pfade
    fehlerklasse: str = ""         # kurze Klasse (z. B. "exit_nonzero", "blocked", "timeout"), kein Text
    signatur: str = ""             # Hash/Kurzsignatur zur Gruppierung, nie Rohtext


@dataclass
class Subagent:
    agent_id: str
    typ: str = ""                  # agentType (general-purpose, Explore, …)
    modell: str = ""                # volle Modellkennung aus dem Subagent-Transkript, sonst Kurzform aus meta.json
    auftrag: str = ""               # Kurzlabel des Aufrufs (meta.json "description"), redigiert, ≤ 80 Zeichen
    tiefe: int = 1
    start: str = ""
    ende: str = ""
    dauer_ms: Optional[int] = None
    runden: int = 0
    tools: int = 0
    tool_fehler: int = 0
    token: Token = field(default_factory=Token)
    beleg: str = "not_observed"    # observed = Ergebnis enthält Datei:Zeile/Befehl/Test-Referenz
    ergebnis: str = "unbekannt"    # ok | fehler | leer | unbekannt


@dataclass
class Erfassung:
    """Welche Kanäle wie ehrlich vorliegen (Werte aus ERFASSUNG)."""
    token: str = "not_observed"
    dauer: str = "not_observed"
    kosten: str = "not_observed"
    inhalte: str = "redacted"
    subagenten: str = "not_observed"
    compaction: str = "not_observed"
    reasoning: str = "not_observed"
    unbekannt: list[str] = field(default_factory=list)   # unbekannte Zeilen-/Feldtypen (Format-Drift)


@dataclass
class Kopf:
    quelle: str                    # "claude" | "codex" | "produkt"
    sitzung_id: str
    projekt_hash: str = ""         # sha256[:12] des cwd — nie der Pfad
    projekt_name: str = ""         # letzter Pfadbestandteil, nur wenn Allowlist erlaubt
    host: str = ""
    start: str = ""
    ende: str = ""
    version: str = ""              # CLI-Version
    git_branch: str = ""
    modelle: list[str] = field(default_factory=list)
    backend: str = ""               # "anthropic"|"ollama"|"openrouter"|"requesty"|"unbekannt"|"" (Hostklasse aus ANTHROPIC_BASE_URL, Stop-Hook)
    umgebung: str = "entwicklung"   # "entwicklung"|"abnahme"|"betrieb" (C12, Stop-Hook aus SITZUNGSBELEG_UMGEBUNG; Default deckt Alt-Belege ab)
    persona: str = "vico"           # "vico"|"vica"|"cura" (Stop-Hook aus CLAUDE_CONFIG_DIR; Default deckt Alt-Belege ab, die die Achse noch nicht kannten)
    kanal: str = "terminal"         # "terminal"|"orb" (C14, Stop-Hook aus SITZUNGSBELEG_KANAL; Orb-Bruecke setzt "orb")


@dataclass
class Kennzahlen:
    runden: int = 0
    dauer_ms: int = 0
    latenz_p50_ms: int = 0
    latenz_p95_ms: int = 0
    latenz_max_ms: int = 0
    tools: int = 0
    tool_fehler: int = 0
    tool_fehlerquote: float = 0.0
    tools_je_typ: dict[str, int] = field(default_factory=dict)
    tool_fehler_je_typ: dict[str, int] = field(default_factory=dict)
    token: Token = field(default_factory=Token)
    thinking_bloecke: int = 0
    compactions: int = 0
    compaction_positionen: list[float] = field(default_factory=list)  # 0..1 Anteil der Sitzung
    kontext_auslastung_max: Optional[float] = None                     # 0..1, wenn Fenstergröße bekannt
    subagenten: int = 0
    subagenten_max_tiefe: int = 0
    kosten: Optional[float] = None                                     # derived, nur Hauptsitzung (beleg.ereignisse)
    kosten_subagenten: Optional[float] = None                          # derived, Summe je Subagent-Modell (beleg.subagenten)
    kosten_gesamt: Optional[float] = None                              # kosten + kosten_subagenten, None wenn beide fehlen
    kosten_waehrung: str = ""                                          # "USD"/"EUR" aus der Preistabelle
    rework_dateien: dict[str, int] = field(default_factory=dict)       # signatur -> Bezüge (nie Pfad)


@dataclass
class Auffaelligkeit:
    regel: str                     # z. B. "tool:error_rate"
    schwere: str                   # "hinweis" | "warnung" | "hoch"
    signatur: str                  # gruppierbar über Sitzungen, nie Rohtext
    wert: str = ""                 # kurze Zahl/Quote, z. B. "5.6 %"
    ref: str = ""                  # Verweis (agent_id, Ereignis-Index) — nie Pfad


@dataclass
class Beleg:
    kopf: Kopf
    erfassung: Erfassung = field(default_factory=Erfassung)
    kennzahlen: Kennzahlen = field(default_factory=Kennzahlen)
    ereignisse: list[Ereignis] = field(default_factory=list)
    subagenten: list[Subagent] = field(default_factory=list)
    auffaelligkeiten: list[Auffaelligkeit] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def als_dict(self) -> dict:
        return asdict(self)
