"""Chat-Bruecke: je `gespraech_id` ein Kindprozess `claude -p --input-format stream-json
--output-format stream-json`, ueber mehrere Turns hinweg wiederverwendet, nur Text-Deltas fuer SSE
(kein Satz-Splitting/TTS -- das ist reiner Dashboard-Chat, kein Sprach-Kanal).

Der Anbieter waehlt die Umgebung des Kindprozesses: `claude` = Anthropic (unveraendertes
os.environ), `ollama` = `_OLLAMA_ENV` (ein lokaler Ollama-Endpunkt), `openrouter` = OpenRouters
Anthropic-kompatible Bruecke (`ANTHROPIC_BASE_URL=https://openrouter.ai/api`) mit dem Schluessel
aus `OPENROUTER_API_KEY` oder der zentralen Schluesseldatei, `requesty` = dasselbe Muster gegen
Requesty (`ANTHROPIC_BASE_URL=https://router.requesty.ai`, Schluessel aus `REQUESTY_API_KEY`).
Das Modell kommt vom Frontend (`GET /api/chat/modelle`) und geht unveraendert in `--model`.

Ein Prozess lebt ueber mehrere Turns (Kontext bleibt erhalten). Stirbt er (Absturz, Zeitlimit
ohne Delta), meldet `turn()` ein `fehler`-Ereignis und setzt sich selbst auf "tot" -- der
naechste `turn()`-Aufruf spawnt automatisch neu, ohne dass die `gespraech_id`/der Chatverlauf in
der DB verloren geht."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess

from . import schluessel
import threading
import time
from pathlib import Path

# Der Kindprozess braucht den Ordner UEBER dem Paket als Arbeitsverzeichnis, damit sein
# Nachschlage-Werkzeug `python -m sitzungsbeleg nachschlagen <nr>` ueberhaupt aufloest (Paket
# nicht installiert, `python -m` sucht ueber sys.path/cwd). parents[1] statt fester Pfadannahme:
# traegt sowohl ein eingebettetes Layout als auch einen eigenstaendigen Checkout dieses Pakets.
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
TURN_TIMEOUT_S = 120  # 120s ohne Delta gilt als Zeitlimit -> 'fehler'-Ereignis
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Lokaler Ollama-Weg: eigene Anthropic-kompatible Basis-URL statt der Anthropic-API. Welche
# Datenarten darueber laufen duerfen, ist eine Betriebsentscheidung ausserhalb dieses Moduls.
_OLLAMA_ENV = {"ANTHROPIC_BASE_URL": "http://localhost:11434",
               "ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": ""}

CHAT_SYSTEM = (
    "Du bist der lesende Analyse-Assistent in der Besprechungs-Spalte des Sitzungsbeleg-"
    "Dashboards. Der Nutzer bespricht mit dir eine Sitzung/einen Befund: erklaere "
    "Auffaelligkeiten, ordne ein, beantworte Rueckfragen. Sie-Form, sachlich, kurz.\n"
    "Fuer geschuetzte/sensible Inhalte (Schutz-Chip 'geschuetzt') bist du hier nicht zustaendig "
    "-- verweise kurz auf den konfigurierten lokalen/privaten Verarbeitungsweg, bearbeite es "
    "nicht selbst.\n"
    "Dies ist ein Hintergrund-Prozess ohne Rueckfrage-Moeglichkeit: schlage aendernde/loeschende/"
    "sendende Schritte nur vor, fuehre sie nicht aus.\n"
    # Nur Lesewerkzeuge sind freigeschaltet (--allowedTools, s. CHAT_ALLOWED_TOOLS) -- diese
    # Zeile macht das im Text ebenfalls klar UND definiert die Erkennung fuer den "Fix
    # umsetzen"-Knopf (chat.js sucht nach dieser Zeile am Absatzanfang).
    "Du liest und erklaerst; Aenderungen schlaegst du als konkreten Fix vor, du fuehrst sie NICHT "
    "selbst aus. Umsetzen macht ein separates, sichtbares Fenster. Enthaelt eine Antwort einen "
    "konkreten Fix-Vorschlag, beginne den betreffenden Absatz GENAU mit der Zeile "
    "'FIX-VORSCHLAG:' (ohne Anfuehrungszeichen).\n"
    # Der Nutzer soll nicht erst in eine andere Ansicht klicken muessen, damit du sie kennst --
    # sie kommt als Block SICHT mit der ersten Nachricht, und weitere Sitzungen kannst du selbst
    # nachschlagen.
    "Du kennst die aktuelle Ansicht (Block SICHT: welche Seite offen ist, Zeitraum/Filter, die "
    "sichtbaren Sitzungszeilen). Zum Nachschlagen einer Sitzung, die nicht im SICHT-Block steht "
    "oder die du genauer pruefen willst, fuehre `python -m sitzungsbeleg nachschlagen <nr>` aus "
    "(optional `--befund <signatur>` fuer einen einzelnen Befund) -- nie den Nutzer bitten, das "
    "selbst nachzuschauen."
)


class ChatBrueckeFehler(RuntimeError):
    """claude.exe nicht gefunden -- Kindprozess kann gar nicht erst starten."""


# OpenRouter: gleiches Anthropic-kompatible-Bruecke-Muster wie Ollama, aber mit echtem
# Schluessel -- Reihenfolge Umgebungsvariable, dann die zentrale Schluesseldatei (`schluessel.py`:
# `SCHLUESSEL=wert`-Zeilen, `#`-Kommentare, gitignored).
_OPENROUTER_BASE_URL = "https://openrouter.ai/api"
_OPENROUTER_ENV_DATEI = SCRIPTS_DIR / ".env.openrouter"
_OPENROUTER_SCHLUESSEL_NAME = "OPENROUTER_API_KEY"


class OpenRouterSchluesselFehler(ChatBrueckeFehler):
    """Kein OPENROUTER_API_KEY -- weder Umgebungsvariable noch `scripts\\.env.openrouter`."""


def _openrouter_schluessel_aus_datei() -> str | None:
    """Zentrale `scripts\.env` zuerst, dann die anbieterspezifische Alt-Datei
    `_OPENROUTER_ENV_DATEI` als Rueckfall."""
    return schluessel.lese(_OPENROUTER_SCHLUESSEL_NAME, _OPENROUTER_ENV_DATEI)


def _openrouter_schluessel() -> str:
    """Reihenfolge Umgebungsvariable vor Datei; fehlt beides, eine Fehlermeldung ohne den
    (nicht vorhandenen) Schluessel zu nennen -- landet ueber `_spawn()`/`_spawn_falls_tot()` als
    normales 'fehler'-SSE-Ereignis im Chat, kein Crash."""
    schluessel = os.environ.get(_OPENROUTER_SCHLUESSEL_NAME) or _openrouter_schluessel_aus_datei()
    if not schluessel:
        raise OpenRouterSchluesselFehler(r"OpenRouter-Schluessel fehlt: scripts\.env.openrouter")
    return schluessel


def _openrouter_env() -> dict:
    return {"ANTHROPIC_BASE_URL": _OPENROUTER_BASE_URL,
            "ANTHROPIC_AUTH_TOKEN": _openrouter_schluessel(), "ANTHROPIC_API_KEY": ""}


# Requesty: gleiches Anthropic-kompatible-Bruecke-Muster wie OpenRouter -- Basis-URL + Auth per
# `ANTHROPIC_AUTH_TOKEN` (Bearer). Ein Verbindungstest gegen beide Hosts (router.requesty.ai /
# router.eu.requesty.ai) und beide Auth-Varianten (`Authorization: Bearer <key>` und `x-api-key`)
# ergab: beide funktionieren, die EU-Datenresidenz-URL wird bevorzugt. Modellliste
# (`chat.REQUESTY_MODELLE_URL`) bleibt auf der allgemeinen Domain -- jedes Modell traegt sein
# eigenes `geolocation`-Feld.
_REQUESTY_BASE_URL = "https://router.eu.requesty.ai"
_REQUESTY_ENV_DATEI = SCRIPTS_DIR / ".env.requesty"
_REQUESTY_SCHLUESSEL_NAME = "REQUESTY_API_KEY"


class RequestySchluesselFehler(ChatBrueckeFehler):
    """Kein REQUESTY_API_KEY -- weder Umgebungsvariable noch `scripts\\.env.requesty`."""


def _requesty_schluessel_aus_datei() -> str | None:
    """Zentrale `scripts\.env` zuerst, dann die anbieterspezifische Alt-Datei
    `_REQUESTY_ENV_DATEI` als Rueckfall."""
    return schluessel.lese(_REQUESTY_SCHLUESSEL_NAME, _REQUESTY_ENV_DATEI)


def _requesty_schluessel() -> str:
    """Reihenfolge Umgebungsvariable vor Datei -- Muster `_openrouter_schluessel`."""
    schluessel = os.environ.get(_REQUESTY_SCHLUESSEL_NAME) or _requesty_schluessel_aus_datei()
    if not schluessel:
        raise RequestySchluesselFehler(r"Requesty-Schluessel fehlt: scripts\.env.requesty")
    return schluessel


def _requesty_env() -> dict:
    return {"ANTHROPIC_BASE_URL": _REQUESTY_BASE_URL,
            "ANTHROPIC_AUTH_TOKEN": _requesty_schluessel(), "ANTHROPIC_API_KEY": ""}


def _claude_exe() -> str:
    """Pfad zur echten claude.exe (der npm-Shim .cmd ist fuer subprocess nicht direkt startbar)."""
    kandidat = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules",
                             "@anthropic-ai", "claude-code", "bin", "claude.exe")
    if os.path.isfile(kandidat):
        return kandidat
    gefunden = shutil.which("claude.exe") or shutil.which("claude")
    if gefunden:
        return gefunden
    raise ChatBrueckeFehler("claude.exe nicht gefunden")



# Die Hintergrund-Sitzung darf NUR lesen: sie hat keine TTY, kann also nie eine Rueckfrage
# beantworten -- ein Modus, der Aenderungen ohne Rueckfrage zuliesse, waere hier lebensgefaehrlich.
# `--allowedTools` OHNE `--permission-mode` heisst: ausserhalb der Liste denied statt gefragt --
# passt genau zum reinen Erklaeren/Vorschlagen dieser Spalte. Zusaetzlich EIN Bash-Praefix fuer
# das Nachschlage-Werkzeug (`python -m sitzungsbeleg nachschlagen ...`, nur lesend, s.
# `__main__._befehl_nachschlagen`) -- Praefix-Syntax `Bash(<praefix> *)` wie im `claude --help`-
# Beispiel `Bash(git *)`.
CHAT_ALLOWED_TOOLS = 'Read,Grep,Glob,Bash(python -m sitzungsbeleg nachschlagen *)'


def _standard_kommando(modell: str) -> list[str]:
    return [_claude_exe(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose", "--allowedTools", CHAT_ALLOWED_TOOLS,
            "--model", modell, "--append-system-prompt", CHAT_SYSTEM]


_FIX_LAUNCHER_SCHLUESSEL_NAME = "SITZUNGSBELEG_FIX_LAUNCHER"


class FixLauncherFehlt(ChatBrueckeFehler):
    """Kein/kein gueltiger `SITZUNGSBELEG_FIX_LAUNCHER` konfiguriert."""


def _fix_kommando(handover: str) -> list[str]:
    """Baut das Kommando fuer "Fix umsetzen" aus `SITZUNGSBELEG_FIX_LAUNCHER` (Umgebung, sonst
    `scripts\\.env`) -- eine JSON-Liste von Strings, z. B. `["powershell", "C:/pfad/Launcher.ps1",
    "-To", "assistent", "-Handover", "{handover}"]`. `{handover}` wird in JEDEM Element per
    `str.replace` ersetzt (kein Shell-Aufruf, kein Format-String-Trick). Fehlt der Schluessel, ist
    er kein gueltiges JSON, oder ist er keine Liste von Strings, wirft `FixLauncherFehlt` --
    dieses Modul kennt keinen fest verdrahteten Launcher, der Betrieb konfiguriert seinen
    eigenen (z. B. ein Skript, das ein sichtbares Assistenzfenster mit dem Handover oeffnet)."""
    roh = schluessel.lese(_FIX_LAUNCHER_SCHLUESSEL_NAME)
    if not roh:
        raise FixLauncherFehlt(
            f"Fix-Launcher nicht konfiguriert: {_FIX_LAUNCHER_SCHLUESSEL_NAME} (JSON-Liste)")
    try:
        vorlage = json.loads(roh)
    except json.JSONDecodeError as fehler:
        raise FixLauncherFehlt(
            f"Fix-Launcher nicht konfiguriert: {_FIX_LAUNCHER_SCHLUESSEL_NAME} (JSON-Liste)"
        ) from fehler
    if not isinstance(vorlage, list) or not vorlage or not all(isinstance(t, str) for t in vorlage):
        raise FixLauncherFehlt(
            f"Fix-Launcher nicht konfiguriert: {_FIX_LAUNCHER_SCHLUESSEL_NAME} (JSON-Liste)")
    return [teil.replace("{handover}", handover) for teil in vorlage]


# Injizierbar fuer Tests (Muster wie KOMMANDO_BAUEN): Fake statt eines echten neuen Fensters.
FIX_KOMMANDO_BAUEN = _fix_kommando


def oeffne_fix_fenster(handover: str, starter=subprocess.Popen) -> None:
    """"Fix umsetzen": oeffnet den konfigurierten Fix-Launcher (`FIX_KOMMANDO_BAUEN`) mit einem
    NEUTRALEN Handover-Stichwort -- nie Nachrichtentext (DSGVO). KEIN `_NO_WINDOW` (anders als der
    Claude-Kindprozess oben) -- das Fenster soll sichtbar sein. `starter` injizierbar; wirft bei
    Fehlstart weiter (Aufrufer macht daraus eine passende HTTP-Antwort)."""
    starter(FIX_KOMMANDO_BAUEN(handover))


# Injizierbar fuer Tests (Muster wie chat._ollama_lauf): ersetzt den echten `claude`-Aufruf durch
# `tests/fake_claude.py`, ganz ohne Anthropic-Zugriff. Signatur: (modell: str) -> argv.
KOMMANDO_BAUEN = _standard_kommando


def _umgebung(anbieter: str) -> dict:
    """`openrouter` kann werfen (`OpenRouterSchluesselFehler`, s. `_openrouter_schluessel`) --
    Aufrufer ist `_spawn()`, dessen Exception `_spawn_falls_tot()` bereits in ein 'fehler'-Ereignis
    uebersetzt (gleicher Pfad wie ein fehlendes `claude.exe`, kein Sonderfall noetig)."""
    env = os.environ.copy()
    if anbieter == "ollama":
        env.update(_OLLAMA_ENV)
    elif anbieter == "openrouter":
        env.update(_openrouter_env())
    elif anbieter == "requesty":
        env.update(_requesty_env())
    else:
        for schluessel in _OLLAMA_ENV:
            env.pop(schluessel, None)
    return env


def _kontext_teile(kontext: dict) -> list[str]:
    teile = []
    if kontext.get("sitzung_logisch"):
        teile.append(f"Sitzung {kontext['sitzung_logisch']}")
    if kontext.get("signatur"):
        teile.append(f"Signatur {kontext['signatur']}")
    if kontext.get("runde") is not None:
        teile.append(f"Runde {kontext['runde']}")
    if kontext.get("analyse_id"):
        teile.append(f"Analyse {kontext['analyse_id']}")
    return teile


def _kontext_zeile(kontext: dict | None, sicht: dict | None = None) -> str:
    """Kontextpaket als erste Nachricht -- nur IDs/Kennzahlen, keine Rohdaten. Traegt `kontext`
    einen serverseitig gebauten `kennzahlen_block` (ohne den kennt die Besprechung nur die
    Sitzungs-ID und kann keine Kennzahlenfrage beantworten, s.
    `chat.gespraech_starten`/`chat_kennzahlen.baue_block`), haengt er hier an, damit er ins
    System-Prompt/die erste Nachricht der Bruecke geht. `sicht` haengt zusaetzlich den Block
    SICHT an (`_sicht_block`) -- welche Ansicht offen ist und was dort gerade sichtbar ist, damit
    der Nutzer nicht erst hinklicken muss, um sie zu erklaeren."""
    teile = _kontext_teile(kontext) if kontext else []
    bloecke = []
    if teile:
        bloecke.append("[Kontext dieser Besprechung: " + ", ".join(teile) + " -- nur IDs/Kennzahlen, "
                        "keine Rohdaten; lade bei Bedarf selbst lokal nach.]")
        block = kontext.get("kennzahlen_block")
        if block:
            bloecke.append(f"[Kennzahlen dieser Sitzung:\n{block}]")
    if sicht:
        bloecke.append(_sicht_block(sicht))
    return "\n".join(bloecke) + "\n\n" if bloecke else ""


SICHT_MAX_ZEICHEN = 2500
_SICHT_ANSICHT_LABEL = {"start": "Startseite", "fehlerbilder": "Fehlerbilder", "produkt": "Produkt"}


def _sicht_ansicht_text(sicht: dict) -> str:
    ansicht = sicht.get("ansicht")
    if ansicht == "sitzung":
        return f"Sitzung {sicht.get('sitzung')}" if sicht.get("sitzung") else "Sitzung"
    return _SICHT_ANSICHT_LABEL.get(ansicht, ansicht or "?")


def _sicht_kurzdatum(iso_datum: str | None) -> str:
    return f"{iso_datum[8:10]}.{iso_datum[5:7]}." if iso_datum and len(iso_datum) >= 10 else (iso_datum or "")


def _sicht_zeitraum_text(zeitraum: dict | None) -> str:
    if not zeitraum or not (zeitraum.get("von") or zeitraum.get("bis")):
        return ""
    return _sicht_kurzdatum(zeitraum.get("von")) + "-" + _sicht_kurzdatum(zeitraum.get("bis"))


def _sicht_filter_text(filter_: dict | None) -> str:
    if not filter_:
        return ""
    teile = [f"{label} {', '.join(filter_[feld])}" for feld, label in
             (("projekte", "Projekte"), ("quellen", "Quellen"), ("kontexte", "Kontexte")) if filter_.get(feld)]
    return "; ".join(teile)


def _sicht_kopfzeile(sicht: dict) -> str:
    teile = [_sicht_ansicht_text(sicht)]
    if _sicht_zeitraum_text(sicht.get("zeitraum")):
        teile.append(_sicht_zeitraum_text(sicht.get("zeitraum")))
    if _sicht_filter_text(sicht.get("filter")):
        teile.append("Filter " + _sicht_filter_text(sicht.get("filter")))
    return "SICHT: " + ", ".join(teile)


def _sicht_tabellenzeile(z: dict, mit_auffaelligkeiten: bool) -> str:
    auff = ", ".join(z.get("auffaelligkeiten") or []) if mit_auffaelligkeiten else ""
    usd = f"{z['usd']:.2f}" if z.get("usd") is not None else "-"
    return " | ".join([str(z.get(f, "")) for f in ("nr", "zeit", "quelle", "projekt")] +
                       [z.get("dauer", ""), usd, z.get("status", ""), auff])


def _sicht_tabelle(sitzungen: list[dict], mit_auffaelligkeiten: bool = True) -> str:
    kopf = "Nr | Zeit | Quelle | Projekt | Dauer | USD | Status | Auffaelligkeiten"
    zeilen = [kopf] + [_sicht_tabellenzeile(z, mit_auffaelligkeiten) for z in sitzungen]
    return "\n".join(zeilen)


def _sicht_text(kopfzeile: str, sitzungen: list[dict], mit_auffaelligkeiten: bool) -> str:
    return (f"{kopfzeile}, {len(sitzungen)} Sitzung(en) sichtbar:\n"
            f"{_sicht_tabelle(sitzungen, mit_auffaelligkeiten)}")


def _sicht_block(sicht: dict) -> str:
    """Kompakter Block ueber die aktuell offene Ansicht -- ohne den kann der Hintergrund-Chat
    nicht sagen, WAS gerade sichtbar ist. Kuerzt bei Bedarf zuerst die Auffaelligkeiten-Spalte,
    dann Zeilen von hinten, bis <= SICHT_MAX_ZEICHEN."""
    sitzungen = sicht.get("sitzungen") or []
    kopfzeile = _sicht_kopfzeile(sicht)
    if not sitzungen:
        return f"[{kopfzeile}]"
    text = _sicht_text(kopfzeile, sitzungen, True)
    if len(text) > SICHT_MAX_ZEICHEN:
        text = _sicht_text(kopfzeile, sitzungen, False)
    while len(text) > SICHT_MAX_ZEICHEN and len(sitzungen) > 1:
        sitzungen = sitzungen[:-1]
        text = _sicht_text(kopfzeile, sitzungen, False)
    return f"[{text}]"


def _reader(proc: subprocess.Popen, q: "queue.Queue[str | None]") -> None:
    for zeile in proc.stdout:
        q.put(zeile)
    q.put(None)  # Prozess beendet -> EOF-Signal


def _stderr_reader(proc: subprocess.Popen, sammler: list[str]) -> None:
    """Sammelt stderr-Zeilen des Kindprozesses -- `stderr=DEVNULL` wuerde Warnungen wie
    'unrecognized_model' spurlos verschlucken. Landen in der 'fehler'-Meldung bei Zeitlimit/EOF
    (`ChatProzess._mit_stderr`) statt stumm verworfen zu werden."""
    for zeile in proc.stderr:
        zeile = zeile.strip()
        if zeile:
            sammler.append(zeile)


class ChatProzess:
    """Ein Kindprozess je `gespraech_id`, ueber mehrere Turns hinweg wiederverwendet."""

    def __init__(self, anbieter: str, modell: str, kontext: dict | None = None, sicht: dict | None = None):
        self.anbieter = anbieter
        self.modell = modell
        self.kontext = kontext
        self.sicht = sicht
        self.proc: subprocess.Popen | None = None
        self.q: "queue.Queue[str | None]" = queue.Queue()
        self.lock = threading.Lock()
        self._kontext_gesendet = False
        self._stderr: list[str] = []

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _beenden(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        except (OSError, ValueError):
            pass

    def _spawn(self) -> None:
        self._beenden()  # nie einen alten Prozess verwaisen lassen
        cmd = KOMMANDO_BAUEN(self.modell)
        self._stderr = []
        self.proc = subprocess.Popen(
            cmd, cwd=str(SCRIPTS_DIR), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            bufsize=1, env=_umgebung(self.anbieter), creationflags=_NO_WINDOW)
        self.q = queue.Queue()
        threading.Thread(target=_reader, args=(self.proc, self.q), daemon=True).start()
        threading.Thread(target=_stderr_reader, args=(self.proc, self._stderr), daemon=True).start()

    def _mit_stderr(self, basis: str) -> str:
        """Haengt die letzten stderr-Zeilen an eine 'fehler'-Meldung an (s. `_stderr_reader`) --
        leer bleibt `basis` unveraendert (z. B. der reine Zeitlimit-Fall ohne stderr-Ausgabe)."""
        if not self._stderr:
            return basis
        return basis + " -- stderr: " + " | ".join(self._stderr[-3:])

    def beenden(self) -> None:
        """Kindprozess hart stoppen (Test-Aufraeumen, expliziter Sitzungsabbruch)."""
        with self.lock:
            self._beenden()

    def turn(self, text: str):
        """Ein Frage-Antwort-Turn: spawnt bei Bedarf neu (kein Prozess, oder der letzte ist tot --
        'Sitzung neu startbar'), schickt `text` und liefert
        ('delta', text) / ('ende', {token_in, token_out}) / ('fehler', meldung).
        Nach einem 'fehler' ist der Prozess beendet; der naechste Aufruf spawnt automatisch neu."""
        with self.lock:
            fehler = self._spawn_falls_tot() or self._sende(text)
            if fehler is not None:
                yield ("fehler", fehler)
                return
            yield from self._lesen()

    def _spawn_falls_tot(self) -> str | None:
        """Spawnt einen frischen Kindprozess, wenn keiner laeuft. Aufrufer haelt `self.lock`."""
        if self._alive():
            return None
        try:
            self._spawn()
        except (ChatBrueckeFehler, OSError) as fehler:
            return f"Kindprozess nicht gestartet: {fehler}"
        return None

    def _sende(self, text: str) -> str | None:
        """Schickt `text` an den (bereits lebenden) Kindprozess -- mit Kontextzeile beim
        allerersten Turn (s. `_kontext_zeile`). Gibt eine Fehlermeldung zurueck, sonst `None`."""
        gesendet_text = text
        if not self._kontext_gesendet:
            gesendet_text = _kontext_zeile(self.kontext, self.sicht) + text
            self._kontext_gesendet = True
        try:
            msg = {"type": "user",
                   "message": {"role": "user", "content": [{"type": "text", "text": gesendet_text}]}}
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as fehler:
            self._beenden()
            return f"Eingabe an Kindprozess fehlgeschlagen: {fehler}"
        return None

    def _naechste_zeile(self, deadline: float):
        """Wartet auf die naechste stream-json-Zeile oder meldet Zeitlimit/Prozessende.
        Rueckgabe: ('zeile', text) | ('zeitlimit', None) | ('eof', None)."""
        while True:
            rest = deadline - time.monotonic()
            if rest <= 0:
                return ("zeitlimit", None)
            try:
                zeile = self.q.get(timeout=min(1.0, rest))
            except queue.Empty:
                continue
            return ("eof", None) if zeile is None else ("zeile", zeile)

    def _fehler_bei_abbruch(self, status: str):
        """('fehler', meldung) bei Zeitlimit/EOF, sonst `None` -- ausgelagert aus `_lesen()`
        (Code-Masse-Grenze), Aufrufer haelt bereits `self.lock`."""
        if status == "zeitlimit":
            self._beenden()
            return ("fehler", self._mit_stderr(f"Zeitlimit ({TURN_TIMEOUT_S}s) ohne Antwort"))
        if status == "eof":
            self.proc = None
            return ("fehler", self._mit_stderr("Kindprozess beendet ohne Ergebnis"))
        return None

    def _lesen(self):
        """Liest Zeilen bis 'ende'/'fehler'; `deadline` erneuert sich je Delta ODER erkanntem
        Lebenszeichen ohne Text (z. B. `thinking_delta` -- ein Denk-Block vor dem ersten Text
        darf nicht als Zeitlimit zaehlen, s. `_parse_zeile`)."""
        deadline = time.monotonic() + TURN_TIMEOUT_S
        while True:
            status, wert = self._naechste_zeile(deadline)
            abbruch = self._fehler_bei_abbruch(status)
            if abbruch is not None:
                yield abbruch
                return
            ereignis = _parse_zeile(wert, deadline)
            if ereignis is None:
                continue
            typ, payload, deadline = ereignis
            if typ is None:
                continue
            yield (typ, payload)
            if typ == "ende":
                return


def _json_datenzeile(zeile: str) -> dict | None:
    """Eine rohe stream-json-Zeile als JSON-Objekt, oder `None` (Nicht-JSON/kaputte Zeile)."""
    zeile = zeile.strip()
    if not zeile.startswith("{"):
        return None
    try:
        return json.loads(zeile)
    except json.JSONDecodeError:
        return None


def _stream_event_ergebnis(ev: dict):
    """`stream_event`-Zweig von `_parse_zeile` (ausgelagert, Code-Masse-Grenze): `text_delta` ->
    `('delta', text, neue_deadline)`, jedes andere erkannte Delta (z. B. `thinking_delta`, wie es
    Requesty/GLM-5.3-flash real VOR dem ersten Text liefert) -> `(None, None, neue_deadline)` --
    die Deadline verlaengert sich so oder so, nur der Text fehlt."""
    delta = ev.get("event", {}).get("delta", {})
    neue_deadline = time.monotonic() + TURN_TIMEOUT_S
    if delta.get("type") == "text_delta" and delta.get("text"):
        return ("delta", delta["text"], neue_deadline)
    return (None, None, neue_deadline)


def _parse_zeile(zeile: str, deadline: float):
    """Eine stream-json-Zeile -> `(typ, payload, neue_deadline)`, oder `None` GANZ (kaputte/nicht
    erkannte Zeile -- Deadline bleibt unveraendert). `typ` ist `None` bei einem erkannten
    Modell-Lebenszeichen ohne sichtbaren Text (s. `_stream_event_ergebnis`)."""
    ev = _json_datenzeile(zeile)
    if ev is None:
        return None
    typ = ev.get("type")
    if typ == "stream_event":
        return _stream_event_ergebnis(ev)
    if typ == "result":
        usage = ev.get("usage") or {}
        payload = {"token_in": usage.get("input_tokens", 0), "token_out": usage.get("output_tokens", 0)}
        return ("ende", payload, deadline)
    return None


# `python -m sitzungsbeleg anbieter-test <anbieter>`: EIN kurzer `claude -p`-Lauf ueber genau
# diese Bruecke -- gibt Rueckgabewert + STDOUT/STDERR aus (nie den Schluessel), damit eine offene
# Header-/Auth-Frage bei einem neuen Anbieter live geklaert werden kann, sobald ein echter
# Schluessel vorliegt. Kein Streaming/JSON-Protokoll noetig (anders als ChatProzess) -- ein
# einzelner Text-Aufruf reicht als Verbindungstest.
def _test_kommando(modell: str) -> list[str]:
    return [_claude_exe(), "-p", "Antworte nur: ok", "--model", modell]


def teste_anbieter(anbieter: str, modell: str, laufzeit=subprocess.run) -> str:
    """Baut die Umgebung fuer `anbieter` und fuehrt EINEN `claude -p`-Testlauf aus -- liefert
    einen Berichtstext (nie einen Absturz): Umgebungsfehler (z. B. fehlender Schluessel),
    Start-/Zeitlimitfehler, oder `exit=<code>` + gekuerztes STDOUT/STDERR."""
    try:
        env = _umgebung(anbieter)
    except ChatBrueckeFehler as fehler:
        return f"Umgebung nicht aufgebaut: {fehler}"
    try:
        # Kommando-Bau im try: ohne installierte claude-CLI (z. B. Linux-CI) wirft _claude_exe
        # ChatBrueckeFehler -- auch das ist ein Bericht, kein Absturz (Docstring-Zusage).
        lauf = laufzeit(_test_kommando(modell), cwd=str(SCRIPTS_DIR), env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=_NO_WINDOW)
    except (ChatBrueckeFehler, OSError, subprocess.TimeoutExpired) as fehler:
        return f"Lauf fehlgeschlagen: {fehler}"
    return (f"exit={lauf.returncode}\nstdout: {lauf.stdout.strip()[:500]}\n"
            f"stderr: {lauf.stderr.strip()[:500]}")
