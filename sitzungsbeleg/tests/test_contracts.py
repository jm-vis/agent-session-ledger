"""Contract Tests (CONTRACTS.md C2/C4/C5/C8): Beispiele gelten, Verstoesse fallen, Datei = Modul,
Erzeuger validieren vor dem Schreiben."""
import json
import re
from pathlib import Path

import pytest

from sitzungsbeleg import contracts, speicher
from sitzungsbeleg.contracts import ContractFehler, validiere, validiere_ereignis

CONTRACTS_MD = Path(__file__).resolve().parents[1] / "CONTRACTS.md"


def _json_bloecke_der_datei() -> list:
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    bloecke = []
    for roh in re.findall(r"```json\n(.*?)```", text, flags=re.S):
        try:
            bloecke.append(json.loads(roh))
        except json.JSONDecodeError:
            pass  # illustrative Bloecke ("unverändert") zaehlen nicht als Beispiel
    return bloecke


def _kopie(name: str) -> dict:
    return json.loads(json.dumps(contracts.BEISPIELE[name]))


@pytest.mark.parametrize("name", sorted(contracts.BEISPIELE))
def test_beispiel_erfuellt_sein_modell(name):
    validiere(name, contracts.BEISPIELE[name])


@pytest.mark.parametrize("name", sorted(contracts.BEISPIELE))
def test_beispiel_steht_wortgleich_in_contracts_md(name):
    assert contracts.BEISPIELE[name] in _json_bloecke_der_datei(), f"{name}: CONTRACTS.md und contracts.py driften"


def test_fehlendes_feld_faellt():
    obj = _kopie("pruefung_body")
    del obj["scope"]
    with pytest.raises(ContractFehler, match="scope: Field required"):
        validiere("pruefung_body", obj)


def test_fremdes_feld_faellt():
    with pytest.raises(ContractFehler, match="sitzung_ref: Extra inputs"):
        validiere("pruefung_body", {**_kopie("pruefung_body"), "sitzung_ref": 1284})


def test_enum_verstoss_nennt_pfad():
    obj = _kopie("pruefung_lauf")
    obj["urteile"][0]["ergebnis"] = "unklar"
    with pytest.raises(ContractFehler, match="urteile.0.ergebnis"):
        validiere("pruefung_lauf", obj)


def test_schema_nur_eins_und_dauer_nie_negativ():
    with pytest.raises(ContractFehler, match="schema"):
        validiere("pruefung_lauf", {**_kopie("pruefung_lauf"), "schema": 2})
    with pytest.raises(ContractFehler, match="dauer_ms"):
        validiere("pruefung_lauf", {**_kopie("pruefung_lauf"), "dauer_ms": -1})


def test_gestartet_muss_iso_zeit_sein():
    with pytest.raises(ContractFehler, match="gestartet"):
        validiere("pruefung_lauf", {**_kopie("pruefung_lauf"), "gestartet": "gestern"})


def test_text_laenge_begrenzt():
    obj = _kopie("tiefenanalyse")
    obj["befund"] = "x" * (contracts.MAX_TEXT + 1)
    with pytest.raises(ContractFehler, match="befund"):
        validiere("tiefenanalyse", obj)


def test_codex_null_genau_bei_ausgelassener_zweitmeinung():
    obj = _kopie("pruefung_lauf")
    obj["urteile"][0].update({"codex": None, "zweitmeinung": "ausgelassen", "begruendung_codex": None})
    obj["modell_stufe2"] = None
    validiere("pruefung_lauf", obj)
    obj["urteile"][0]["codex"] = "ja"
    with pytest.raises(ContractFehler, match="genau dann null"):
        validiere("pruefung_lauf", obj)


def test_ohne_zweitmeinung_kein_dissens():
    obj = _kopie("pruefung_lauf")
    obj["urteile"][0].update({"codex": None, "zweitmeinung": "ausgelassen", "ergebnis": "dissens"})
    with pytest.raises(ContractFehler, match="kein Dissens"):
        validiere("pruefung_lauf", obj)


def test_scope_fehlerbild_regeln_lauf_und_body():
    lauf = {**_kopie("pruefung_lauf"), "scope": "fehlerbild", "sitzung_logisch": None}
    validiere("pruefung_lauf", lauf)
    with pytest.raises(ContractFehler, match="fehlerbild"):
        validiere("pruefung_lauf", {**lauf, "sitzung_logisch": 5})
    body = {"scope": "fehlerbild", "sitzung_logisch": None, "signaturen": ["a"], "stufe": None, "lauf_ref": None}
    validiere("pruefung_body", body)
    with pytest.raises(ContractFehler, match="fehlerbild"):
        validiere("pruefung_body", {**body, "signaturen": ["a", "b"]})


def test_codex_nachholen_braucht_stufe_und_lauf_ref_gemeinsam():
    body = {**_kopie("pruefung_body"), "stufe": 2}
    with pytest.raises(ContractFehler, match="gemeinsam"):
        validiere("pruefung_body", body)
    validiere("pruefung_body", {**body, "lauf_ref": "p-20260827-143012-7f3a"})


def test_chat_claude_nur_bei_cloud_ok():
    with pytest.raises(ContractFehler, match="cloud-ok"):
        validiere("chat_nachricht", {**_kopie("chat_nachricht"), "schutz": "lokal"})
    validiere("chat_nachricht", {**_kopie("chat_nachricht"), "schutz": "lokal", "anbieter": "ollama"})


def test_chat_openrouter_ist_ebenfalls_cloud_anbieter():
    """Nachtrag Phase 2 OpenRouter: gleiche C6-Regel wie Claude -- Cloud-Anbieter nur bei
    schutz=cloud-ok, Ollama bleibt der einzige lokale Weg."""
    with pytest.raises(ContractFehler, match="cloud-ok"):
        validiere("chat_nachricht", {**_kopie("chat_nachricht"), "anbieter": "openrouter", "schutz": "lokal"})
    validiere("chat_nachricht", {**_kopie("chat_nachricht"), "anbieter": "openrouter", "schutz": "cloud-ok"})


def test_chat_requesty_ist_ebenfalls_cloud_anbieter():
    """Nachtrag Phase 2 Requesty: gleiche C6-Regel wie Claude/OpenRouter -- Cloud-Anbieter nur bei
    schutz=cloud-ok, Ollama bleibt der einzige lokale Weg."""
    with pytest.raises(ContractFehler, match="cloud-ok"):
        validiere("chat_nachricht", {**_kopie("chat_nachricht"), "anbieter": "requesty", "schutz": "lokal"})
    validiere("chat_nachricht", {**_kopie("chat_nachricht"), "anbieter": "requesty", "schutz": "cloud-ok"})


def test_chat_anbieter_kennt_nur_die_vier_werte():
    with pytest.raises(ContractFehler, match="anbieter"):
        validiere("chat_nachricht", {**_kopie("chat_nachricht"), "anbieter": "gpt"})


def test_quoten_als_ganzzahl_null_oder_eins_gueltig():
    obj = {**_kopie("delegation"), "aufruf_quote": 0, "kosten_quote": 1}
    validiere("delegation", obj)
    with pytest.raises(ContractFehler, match="kosten_quote"):
        validiere("delegation", {**_kopie("delegation"), "kosten_quote": 1.2})


def test_zeit_quote_darf_ueber_eins_liegen():
    validiere("delegation", {**_kopie("delegation"), "zeit_quote": 1.8})


def test_benchmark_n_null_erzwingt_null_werte():
    obj = _kopie("delegation")
    obj["benchmark"] = {"n": 0, "aufruf_quote": None, "kosten_quote": None, "output_quote": None,
                        "zeit_quote": None, "tool_quote": None}
    validiere("delegation", obj)
    obj["benchmark"]["aufruf_quote"] = 0.1
    with pytest.raises(ContractFehler, match="n=0"):
        validiere("delegation", obj)


def test_sse_events():
    validiere("sse_event", {"typ": "delta", "text": "Hal"})
    validiere("sse_event", {"typ": "ende", "token_in": 10, "token_out": 20, "dauer_ms": 300})
    with pytest.raises(ContractFehler):
        validiere("sse_event", {"typ": "ende"})
    with pytest.raises(ContractFehler):
        validiere("sse_event", {"typ": "start", "text": "x"})


def test_gruppenstatus_rang():
    assert contracts.gruppenstatus(["erledigt", "offen", "bestaetigt"]) == "offen"
    assert contracts.gruppenstatus(["verworfen", "dissens", "in_pruefung"]) == "dissens"
    assert contracts.gruppenstatus(["offen", "rueckfall"]) == "rueckfall"
    assert contracts.gruppenstatus(["erledigt", "obsolet"]) == "erledigt"
    assert contracts.gruppenstatus([]) == "offen"


def test_zustandswerte_und_rang_vollstaendig():
    assert set(contracts.STATUS) == set(contracts.STATUS_RANG)
    assert len(contracts.STATUS) == 8  # 6 sichtbare Zustaende (erledigt/obsolet = 2 Werte) + rueckfall


def test_ereignis_schreiben_validiert_quellen_mit_contract():
    geschrieben = []
    speicher.ereignis_schreiben("pruefung", "lauf", _kopie("pruefung_lauf"), laufer=geschrieben.append)
    assert len(geschrieben) == 1 and "INSERT INTO ereignis" in geschrieben[0]
    with pytest.raises(ContractFehler, match="ereignis pruefung"):
        speicher.ereignis_schreiben("pruefung", "lauf", {"schema": 1}, laufer=geschrieben.append)
    assert len(geschrieben) == 1  # nichts geschrieben


def test_sicht_kennt_nur_die_vier_ansichten():
    with pytest.raises(ContractFehler, match="ansicht"):
        validiere("sicht", {**_kopie("sicht"), "ansicht": "querschnitt"})


def test_sicht_maximal_dreissig_sitzungen():
    obj = _kopie("sicht")
    obj["sitzungen"] = obj["sitzungen"] * 31
    with pytest.raises(ContractFehler, match="sitzungen"):
        validiere("sicht", obj)
    obj["sitzungen"] = obj["sitzungen"][:30]
    validiere("sicht", obj)


def test_sicht_ohne_sitzungen_und_zeitraum_gueltig():
    """`ansicht=sitzung` traegt keine Zeilenliste (die Sitzungsseite hat schon `kontext`)."""
    validiere("sicht", {"ansicht": "sitzung", "sitzung": 137, "befund": "rework:tool:Bash"})


def test_sicht_verbietet_fremde_felder():
    with pytest.raises(ContractFehler, match="Extra inputs"):
        validiere("sicht", {**_kopie("sicht"), "irgendwas": 1})


def test_ereignis_schreiben_laesst_bestandsquellen_durch():
    """C11: `gf` wird seit 2026-08-28 validiert -- ein Legacy-Detail (ohne `verankerung`, nicht
    `erledigt`) muss weiterhin durchgehen (Dual-Reader); Quellen ohne Modell bleiben ungeprueft."""
    from sitzungsbeleg import befunde
    geschrieben = []
    speicher.ereignis_schreiben("gf", "befund_entscheid", befunde.entscheid_bauen("x", "obsolet"),
                                laufer=geschrieben.append)
    speicher.ereignis_schreiben("vieraugen", "review", {"signatur": "x"}, laufer=geschrieben.append)
    assert len(geschrieben) == 2


# ---- C11 Verankerung ----

def _entscheid(status, verankerung=None):
    from sitzungsbeleg import befunde
    detail = befunde.entscheid_bauen("rework:tool:Bash", status, sitzung_ref=137)
    if verankerung is not None:
        detail["verankerung"] = verankerung
    return detail


def test_c11_erledigt_ohne_verankerung_ist_kein_entscheid():
    with pytest.raises(ContractFehler, match="verankerung"):
        validiere_ereignis("gf", _entscheid("erledigt"))


def test_c11_erledigt_mit_verankerung_gueltig():
    validiere_ereignis("gf", _entscheid("erledigt", {
        "art": "troubleshooting", "pfad": "TROUBLESHOOTING.md", "abschnitt": "Sitzungsbeleg"}))


def test_c11_obsolet_und_offen_brauchen_keine_verankerung():
    validiere_ereignis("gf", _entscheid("obsolet"))
    validiere_ereignis("gf", _entscheid("offen"))


@pytest.mark.parametrize("pfad", ["C:/x/y.md", "/etc/x", "../HANDOFF.md", "60_Internal/_lokal/x.md",
                                  "00_Secrets/k.md", "Über.md", ""])
def test_c11_pfad_nur_repo_relativ_ascii_nie_geschuetzt(pfad):
    with pytest.raises(ContractFehler, match="pfad"):
        validiere_ereignis("gf", _entscheid("erledigt", {"art": "regel", "pfad": pfad}))


def test_c11_unbekannte_art_abgelehnt():
    with pytest.raises(ContractFehler, match="art"):
        validiere_ereignis("gf", _entscheid("erledigt", {"art": "notiz", "pfad": "HANDOFF.md"}))
