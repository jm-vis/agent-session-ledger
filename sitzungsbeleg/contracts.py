"""Interface Contracts des Sitzungsbeleg-Dashboards (Phase 0) -- ausfuehrbare Quelle.

Lesbare Fassung: `CONTRACTS.md` (C1-C8). Pydantic-Modelle sind die Quelle (Codex-Zweitmeinung
2026-08-27, Frage A): Typen, Wertebereiche, gekoppelte Felder und Beispiele kommen aus einem Modell;
FastAPI erzeugt daraus OpenAPI fuer HTTP, `speicher.ereignis_schreiben` validiert JSONB-Details vor dem
INSERT, Tests bauen Fixtures aus `BEISPIELE`. Aendern heisst: zuerst hier + CONTRACTS.md + Tests, dann
der Code. Kompatible Ergaenzung = `schema` bleibt; Bruch = `schema` + 1 und Dual-Reader.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TEXT = 2000
STATUS = ("offen", "in_pruefung", "bestaetigt", "verworfen", "dissens", "erledigt", "obsolet", "rueckfall")
# C2 Gruppenstatus: hoechster Rang gewinnt (Index 0 = hoechster). Rueckfall ist handlungsrelevant
# und steht deshalb ueber offen (Codex-Fund 6).
STATUS_RANG = ("dissens", "in_pruefung", "rueckfall", "offen", "bestaetigt", "verworfen", "erledigt", "obsolet")

Scope = Literal["befund", "sitzung", "fehlerbild"]
Urteil = Literal["ja", "nein", "unklar"]
Ergebnis = Literal["bestaetigt", "verworfen", "dissens"]
Text = Field(max_length=MAX_TEXT)
Quote = Field(ge=0.0)


class ContractFehler(ValueError):
    """Objekt verletzt einen Contract aus CONTRACTS.md (Pydantic-Fehlertext mit Pfad)."""


class _Strikt(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Kontext(_Strikt):
    sitzung_logisch: int | None = Field(default=None, ge=1)
    signatur: str | None = None
    runde: int | None = Field(default=None, ge=1)
    analyse_id: str | None = None
    # Fund 2026-08-27 (C7): server-gebauter Kennzahlen-Block (chat_kennzahlen.baue_block, aus
    # derselben Antwort wie die Detailseite `web._sitzung()`) -- optional, nur bei
    # Sitzungskontext gesetzt; kompatible Ergaenzung, `schema` bleibt 1.
    kennzahlen_block: str | None = Field(default=None, max_length=1500)


class UrteilZeile(_Strikt):
    signatur: str = Field(min_length=1)
    kategorie: str = Text
    komplexitaet: Literal["einfach", "komplex"]
    empfehlung: str = Text
    claude: Urteil
    codex: Urteil | None
    ergebnis: Ergebnis
    zweitmeinung: Literal["eingeholt", "ausgelassen"]
    eskaliert: bool = False
    begruendung_codex: str | None = Text
    # Nachtrag 2026-08-27 Punkt 2 (kompatible Ergaenzung, schema bleibt 1): der erzeugende Lauf,
    # damit "Codex nachholen" `{stufe:2, lauf_ref}` bauen kann -- vorher stand nur die `lauf_id`
    # auf dem `pruefung/lauf`-Ereignis selbst, das per-Signatur-Urteil (`_juengstes_urteil`) hatte
    # sie nicht. Optional, damit Alt-Ereignisse ohne dieses Feld weiter validieren.
    lauf_id: str | None = Field(default=None, pattern=r"^p-\d{8}-\d{6}-[0-9a-f]{4}$")

    @model_validator(mode="after")
    def _codex_passt_zur_zweitmeinung(self):
        if (self.zweitmeinung == "ausgelassen") != (self.codex is None):
            raise ValueError("codex ist genau dann null, wenn zweitmeinung 'ausgelassen' ist")
        if self.zweitmeinung == "ausgelassen" and self.ergebnis == "dissens":
            raise ValueError("ohne Zweitmeinung kein Dissens")
        return self


class PruefungLauf(_Strikt):
    """C4 ereignis quelle='pruefung' typ='lauf'."""
    schema_: Literal[1] = Field(alias="schema")
    lauf_id: str = Field(pattern=r"^p-\d{8}-\d{6}-[0-9a-f]{4}$")
    scope: Scope
    sitzung_logisch: int | None = Field(default=None, ge=1)
    signaturen: list[str]
    stufe_max: Literal[1, 2]
    modell_stufe1: str
    modell_stufe2: str | None
    gestartet: datetime
    dauer_ms: int = Field(ge=0)
    urteile: list[UrteilZeile]
    fehler: str | None = Text
    sitzungen: list[int] | None = None
    tabelle: list[TabellenZeile] | None = None
    datei: str | None = None

    @model_validator(mode="after")
    def _scope_regeln(self):
        if self.scope == "fehlerbild":
            if self.sitzung_logisch is not None or len(self.signaturen) != 1:
                raise ValueError("fehlerbild: genau eine Signatur, sitzung_logisch null")
        elif self.sitzung_logisch is None:
            raise ValueError(f"{self.scope}: sitzung_logisch Pflicht")
        return self


class TabellenZeile(_Strikt):
    sitzung_logisch: int = Field(ge=1)
    einordnung: Literal["sauber", "abgewichen", "halluziniert"]


class TiefenanalyseUrteil(_Strikt):
    """C10: eine Modellseite einer Tiefenanalyse (Claude Stufe 1 immer, Codex Stufe 2 optional) --
    dieselben vier Felder wie Stufe 1 auf beiden Seiten (Mockup B1/B2 zeigt Claude UND Codex mit
    Ursache-Kategorie/Befund/Empfehlung); `komplexitaet` nur bei Claude gesetzt (Stufe-1-Feld)."""
    ursache_kategorie: str = Text
    befund: str = Text
    empfehlung: str = Text
    urteil: Urteil
    komplexitaet: Literal["einfach", "komplex"] | None = None


class Tiefenanalyse(_Strikt):
    """C10 ereignis quelle='tiefenanalyse' typ='befund'. Top-level Felder (ursache_kategorie/
    befund/empfehlung) sind IMMER Claudes Stufe-1-Sicht (Klartext-Karte); bei Dissens zeigt das
    Frontend zusaetzlich `positionen` mit beiden Seiten."""
    schema_: Literal[1] = Field(alias="schema")
    scope: Scope
    signatur: str = Field(min_length=1)
    sitzung_logisch: int = Field(ge=1)
    position: int = Field(ge=0)
    runde: int = Field(ge=0, default=0)
    stufe: Literal[1, 2]
    ursache_kategorie: str = Text
    befund: str = Text
    empfehlung: str = Text
    urteil: Literal["uebereinstimmend", "dissens", "ohne_zweitmeinung"]
    positionen: dict[Literal["claude", "codex"], TiefenanalyseUrteil | None]
    modell: str
    modell_stufe2: str | None = None
    redaktion_version: str
    zeitstempel: datetime
    dauer_ms: int = Field(ge=0)
    commits: list[str] = []
    nur_lokal: bool = False
    fehler: str | None = Text

    @model_validator(mode="after")
    def _codex_passt_zu_urteil(self):
        if self.urteil == "ohne_zweitmeinung" and self.positionen.get("codex") is not None:
            raise ValueError("ohne_zweitmeinung: codex muss null sein")
        return self


class ChatNachricht(_Strikt):
    """C4 Tabelle `chat` (nicht `ereignis`, ADR 0006 2b) -- eine Zeile je Nachricht."""
    schema_: Literal[1] = Field(alias="schema")
    gespraech_id: str = Field(pattern=r"^c-\d{8}-\d{4}-[0-9a-f]{4}$")
    rolle: Literal["nutzer", "assistent", "codex", "system"]
    anbieter: Literal["claude", "ollama", "openrouter", "requesty"]
    modell: str
    schutz: Literal["cloud-ok", "lokal"]
    kontext: Kontext
    text: str = Field(max_length=20000)
    token_in: int = Field(ge=0)
    token_out: int = Field(ge=0)
    dauer_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _cloud_anbieter_nur_cloud_ok(self):
        # Claude, OpenRouter UND Requesty sind Cloud-Anbieter (C6 Zulaessigkeit) -- alle drei
        # nur bei schutz=cloud-ok, Ollama bleibt der einzige lokale Weg fuer geschuetzte Sitzungen.
        if self.anbieter in ("claude", "openrouter", "requesty") and self.schutz != "cloud-ok":
            raise ValueError("anbieter claude/openrouter/requesty nur bei schutz cloud-ok (C6)")
        return self


class PruefungBody(_Strikt):
    """C5 POST /api/pruefung."""
    scope: Scope
    sitzung_logisch: int | None = Field(default=None, ge=1)
    signaturen: list[str] = []
    stufe: Literal[2] | None = None
    lauf_ref: str | None = None

    @model_validator(mode="after")
    def _scope_regeln(self):
        if self.scope == "befund" and (not self.signaturen or self.sitzung_logisch is None):
            raise ValueError("befund: sitzung_logisch und >= 1 Signatur")
        if self.scope == "sitzung" and self.sitzung_logisch is None:
            raise ValueError("sitzung: sitzung_logisch Pflicht")
        if self.scope == "fehlerbild" and (len(self.signaturen) != 1 or self.sitzung_logisch is not None):
            raise ValueError("fehlerbild: genau eine Signatur, sitzung_logisch null")
        if (self.stufe is None) != (self.lauf_ref is None):
            raise ValueError("stufe 2 und lauf_ref nur gemeinsam (Codex nachholen)")
        return self


class DelegationBenchmark(_Strikt):
    n: int = Field(ge=0)
    aufruf_quote: float | None = Quote
    kosten_quote: float | None = Quote
    output_quote: float | None = Quote
    zeit_quote: float | None = Quote
    tool_quote: float | None = Quote

    @model_validator(mode="after")
    def _n_null_heisst_alles_null(self):
        werte = (self.aufruf_quote, self.kosten_quote, self.output_quote, self.zeit_quote, self.tool_quote)
        if (self.n == 0) != all(w is None for w in werte):
            raise ValueError("n=0 <=> alle Quoten null")
        return self


class ModellZeile(_Strikt):
    modell: str
    agenten: int = Field(ge=1)


class Delegation(_Strikt):
    """C5 GET /api/delegation/{sitzung_logisch}. Quoten 0..1 ausser zeit_quote (>1 = parallel)."""
    aufruf_quote: float = Field(ge=0, le=1)
    fanout_max: int = Field(ge=0)
    kosten_quote: float = Field(ge=0, le=1)
    output_quote: float = Field(ge=0, le=1)
    zeit_quote: float = Quote
    tool_quote: float = Field(ge=0, le=1)
    tool_fehlerquote: float = Field(ge=0, le=1)
    mit_beleg: int = Field(ge=0)
    starts: int = Field(ge=0)
    tiefe_max: int = Field(ge=0)
    modelle: list[ModellZeile]
    benchmark: DelegationBenchmark


class RohdateiZeile(_Strikt):
    """Eine verdichtete Rohzeile (Phase 3 H) -- `text` ist bereits durch
    `redaktion.bereinige_text()` gelaufen, bevor sie hier ankommt."""
    index: int = Field(ge=0)
    typ: str
    text: str = Text


class RohdateiAntwort(_Strikt):
    """C5 GET /api/rohdatei/{sitzung_logisch}. Nie in DB/Logs; `zulaessigkeit = geschuetzt` -> 423."""
    pfad_anzeige: str
    position: int = Field(ge=0)
    umfang: int = Field(ge=1, le=50)
    zeilen: list[RohdateiZeile]
    redaktion_version: str
    warnung: str = Text


class SichtZeitraum(_Strikt):
    von: str | None = None
    bis: str | None = None


class SichtFilter(_Strikt):
    projekte: list[str] = []
    quellen: list[str] = []
    kontexte: list[str] = []
    umgebungen: list[str] = []  # C12, optional -- aktive Achse-Umgebung-Checkboxen der Startseite
    personas: list[str] = []  # C14, optional -- aktive Persona-Checkboxen der Startseite


class SichtSitzungZeile(_Strikt):
    """Eine sichtbare Tabellenzeile der Sitzungsliste (Nachtrag 2026-08-28: der Chat kennt sonst
    weder die Ansicht noch ihren Inhalt, s. `Sicht`)."""
    nr: int = Field(ge=1)
    zeit: str = Text
    quelle: str = Text
    projekt: str = Text
    dauer: str = Text
    runden: int = Field(default=0, ge=0)
    tools: int = Field(default=0, ge=0)
    fehler: int = Field(default=0, ge=0)
    usd: float | None = None
    status: str = Text
    auffaelligkeiten: list[str] = []


class Sicht(_Strikt):
    """C7 Sichtkontext (Nachtrag 2026-08-28, Auftrag "Dashboard-Ansicht ist fuer mich nicht
    sichtbar"): welche Ansicht offen ist + die aktuell sichtbaren Sitzungszeilen (max. 30) --
    `chat.js` baut es aus dem Frontend-Zustand, `chat_bruecke._sicht_block()` macht daraus den
    Block `SICHT:` in der ersten Chat-Nachricht. Alles hier ist bereits redigierte Anzeige-
    Information; `chat.sicht_bereinigt()` laesst trotzdem jedes String-Feld durch
    `redaktion.bereinige_text()` (zweites Netz, wie `chat_kennzahlen.baue_block`)."""
    ansicht: Literal["start", "sitzung", "fehlerbilder", "produkt"]
    zeitraum: SichtZeitraum | None = None
    filter: SichtFilter | None = None
    sitzungen: list[SichtSitzungZeile] = Field(default_factory=list, max_length=30)
    sitzung: int | None = Field(default=None, ge=1)
    befund: str | None = None


class SseEvent(_Strikt):
    """C5 GET /api/chat/{gespraech_id}/strom."""
    typ: Literal["delta", "ende", "fehler"]
    text: str | None = None
    token_in: int | None = Field(default=None, ge=0)
    token_out: int | None = Field(default=None, ge=0)
    dauer_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _felder_je_typ(self):
        if self.typ in ("delta", "fehler") and not self.text:
            raise ValueError(f"{self.typ}: text Pflicht")
        if self.typ == "ende" and None in (self.token_in, self.token_out, self.dauer_ms):
            raise ValueError("ende: token_in, token_out, dauer_ms Pflicht")
        return self


MODELLE = {
    "pruefung_lauf": PruefungLauf, "tiefenanalyse": Tiefenanalyse, "chat_nachricht": ChatNachricht,
    "pruefung_body": PruefungBody, "delegation": Delegation, "sse_event": SseEvent,
    "rohdatei_antwort": RohdateiAntwort, "sicht": Sicht,
}
# Ereignis-Quelle -> Modell (C4/C8). `speicher.ereignis_schreiben` prueft vor dem INSERT; Quellen ohne
# Eintrag (gf, vieraugen) bleiben ungeprueft (Bestand).
VERANKERUNG_ART = ("troubleshooting", "adr", "runbook", "playbook", "hook", "skill", "regel", "vorhaben")
UMGEBUNGEN = ("entwicklung", "abnahme", "betrieb")
# Achse Persona: welcher Profil-Slot gearbeitet hat (aus CLAUDE_CONFIG_DIR) und ueber welchen
# Kanal (eine Sprach-/Voice-Bruecke setzt SITZUNGSBELEG_KANAL=orb). Persona != Quelle: ein
# Profil-Slot, der ueber Ollama laeuft, bleibt derselbe persona-Wert, nur mit anderer Quelle.
PERSONAS = ("vico", "vica", "cura")
KANAELE = ("terminal", "orb")


class Verankerung(_Strikt):
    """C11: Ort, an dem ein Entscheid fuer die naechste Sitzung wirkt (Datei, die gelesen wird)."""
    art: Literal["troubleshooting", "adr", "runbook", "playbook", "hook", "skill", "regel", "vorhaben"]
    pfad: str = Field(min_length=1, max_length=300)
    abschnitt: str = Field(default="", max_length=200)

    @field_validator("pfad")
    @classmethod
    def _pfad_repo_relativ(cls, wert: str) -> str:
        wert = wert.strip().replace("\\", "/")
        if not wert or wert.startswith("/") or ":" in wert or ".." in wert.split("/"):
            raise ValueError("pfad: repo-relativ, kein absoluter Pfad, kein '..'")
        if "_lokal" in wert or wert.startswith("00_Secrets"):
            raise ValueError("pfad: geschuetzter Bereich ist keine Verankerung")
        if not wert.isascii():
            raise ValueError("pfad: ASCII (Benennung.md)")
        return wert


class BefundEntscheid(_Strikt):
    """C11: `gf/befund_entscheid.detail` -- Bestand aus `befunde.entscheid_bauen` + optionale Verankerung.
    `erledigt` OHNE Verankerung ist kein Entscheid (Maintainer 2026-08-28)."""
    schema_: int = Field(default=1, alias="schema")
    signatur: str = Field(min_length=1)
    sitzung_ref: int | None = None
    status: Literal["erledigt", "obsolet", "offen"]
    vermerk: str = Field(default="", max_length=MAX_TEXT)
    begruendung: str = Field(default="", max_length=MAX_TEXT)
    entschieden_am: str
    entschieden_von: str = "Maintainer"
    verankerung: Verankerung | None = None

    @model_validator(mode="after")
    def _erledigt_braucht_verankerung(self) -> "BefundEntscheid":
        if self.status == "erledigt" and self.verankerung is None:
            raise ValueError("erledigt ohne verankerung: wo soll der Entscheid wirken? (art + pfad)")
        return self


MODELL_JE_QUELLE = {"pruefung": PruefungLauf, "tiefenanalyse": Tiefenanalyse, "gf": BefundEntscheid}

# Identisch mit den JSON-Bloecken in CONTRACTS.md (Test: deckungsgleich).
BEISPIELE = {
    "pruefung_lauf": {
        "schema": 1, "lauf_id": "p-20260827-143012-7f3a", "scope": "befund", "sitzung_logisch": 512,
        "signaturen": ["rework:tool:Bash"], "stufe_max": 2, "modell_stufe1": "claude-sonnet-5",
        "modell_stufe2": "gpt-5.5", "gestartet": "2026-08-27T14:30:12+02:00", "dauer_ms": 48211,
        "urteile": [{"signatur": "rework:tool:Bash", "kategorie": "Nacharbeit", "komplexitaet": "einfach",
                     "empfehlung": "…", "claude": "ja", "codex": "ja", "ergebnis": "bestaetigt",
                     "zweitmeinung": "eingeholt", "eskaliert": False, "begruendung_codex": "…",
                     "lauf_id": "p-20260827-143012-7f3a"}],
        "fehler": None,
    },
    "tiefenanalyse": {
        "schema": 1, "scope": "befund", "signatur": "rework:tool:Bash", "sitzung_logisch": 512,
        "position": 41, "runde": 11, "stufe": 2, "ursache_kategorie": "Heredoc-Backslash",
        "befund": "…", "empfehlung": "…", "urteil": "dissens",
        "positionen": {
            "claude": {"ursache_kategorie": "Heredoc-Backslash", "befund": "…", "empfehlung": "…",
                       "urteil": "ja", "komplexitaet": "einfach"},
            "codex": {"ursache_kategorie": "Gewollte Retry-Logik", "befund": "…", "empfehlung": "…",
                      "urteil": "nein", "komplexitaet": None},
        },
        "modell": "claude-opus-5", "modell_stufe2": "gpt-5.5", "redaktion_version": "2026-08-28",
        "zeitstempel": "2026-08-28T14:30:12+02:00", "dauer_ms": 48211, "commits": ["a1b2c3d"],
        "nur_lokal": False, "fehler": None,
    },
    "chat_nachricht": {
        "schema": 1, "gespraech_id": "c-20260827-1500-a1b2", "rolle": "nutzer", "anbieter": "claude",
        "modell": "claude-sonnet-5", "schutz": "cloud-ok",
        "kontext": {"sitzung_logisch": 512, "signatur": None, "runde": None, "analyse_id": None},
        "text": "…", "token_in": 0, "token_out": 0, "dauer_ms": 0,
    },
    "pruefung_body": {
        "scope": "befund", "sitzung_logisch": 512, "signaturen": ["rework:tool:Bash"], "stufe": None,
        "lauf_ref": None,
    },
    "delegation": {
        "aufruf_quote": 0.31, "fanout_max": 4, "kosten_quote": 0.53, "output_quote": 0.31, "zeit_quote": 0.65,
        "tool_quote": 0.87, "tool_fehlerquote": 0.035, "mit_beleg": 22, "starts": 22, "tiefe_max": 1,
        "modelle": [{"modell": "claude-sonnet-5", "agenten": 22}],
        "benchmark": {"n": 60, "aufruf_quote": 0.2, "kosten_quote": 0.4, "output_quote": 0.25,
                      "zeit_quote": 0.5, "tool_quote": 0.7},
    },
    "rohdatei_antwort": {
        "pfad_anzeige": "~/.claude/projects/beispiel/sitzung.jsonl", "position": 41, "umfang": 5,
        "zeilen": [{"index": 39, "typ": "tool_use", "text": "<redigiert>"}],
        "redaktion_version": "2026-08-28", "warnung": "Flüchtig, redigiert, nie gespeichert.",
    },
    "sicht": {
        "ansicht": "start", "zeitraum": {"von": "2026-08-22", "bis": "2026-08-28"},
        "filter": {"projekte": ["Demo"], "quellen": ["Claude"], "kontexte": ["arbeit"]},
        "sitzungen": [{"nr": 666, "zeit": "2026-08-28T09:00:00+02:00", "quelle": "Claude",
                        "projekt": "Demo", "dauer": "12m", "runden": 5, "tools": 20, "fehler": 1,
                        "usd": 0.42, "status": "auffaellig", "auffaelligkeiten": ["rework:tool"]}],
        "sitzung": None, "befund": None,
    },
}


def validiere(name: str, obj) -> BaseModel:
    """Prueft `obj` gegen MODELLE[name]; wirft ContractFehler mit Pydantic-Pfaden."""
    try:
        return MODELLE[name].model_validate(obj)
    except ValidationError as fehler:
        raise ContractFehler(f"{name}: {fehler.error_count()} Fehler -- {_kurz(fehler)}") from None


def validiere_ereignis(quelle: str, detail) -> None:
    """C8: Quellen mit Contract werden vor dem INSERT geprueft; andere passieren unveraendert."""
    modell = MODELL_JE_QUELLE.get(quelle)
    if modell is None:
        return
    try:
        modell.model_validate(detail)
    except ValidationError as fehler:
        raise ContractFehler(f"ereignis {quelle}: {_kurz(fehler)}") from None


def _kurz(fehler: ValidationError) -> str:
    return "; ".join(
        ".".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in fehler.errors()[:5]
    )


def gruppenstatus(status_liste) -> str:
    """C2: hoechster Rang unter den Treffern; leere Gruppe = offen."""
    kandidaten = [s for s in status_liste if s in STATUS_RANG]
    if not kandidaten:
        return "offen"
    return min(kandidaten, key=STATUS_RANG.index)
