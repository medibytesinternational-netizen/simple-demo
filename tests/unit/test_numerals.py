"""Golden numeral tests: medication + vitals extraction (regex path, no LLM).

Covers: decimals, BP 'of'/long-form, multi-drug split, freq vocab (twice a day /
every 8 hours), and misheard drug and allergy names.
"""
from medibytes.extraction.entities import extract_entities
from medibytes.extraction.normalize import normalize_text
from medibytes.extraction.vitals import vital_span_kind


def _run(text):
    norm = normalize_text(text)
    segs = [{"id": 0, "text": text, "start": 0.0, "end": 5.0,
             "lang": "mix", "confidence": 0.9, "words": []}]
    return extract_entities(text, norm["normalized_en"], segs)


def _boxes(ent):
    """{vital kind: [span text, ...]} using the extractor's own span classifier."""
    boxes = {}
    for v in ent["vitals"]:
        kind = {"temp_f": "temp"}.get(vital_span_kind(v["text"]), vital_span_kind(v["text"]))
        if kind:
            boxes.setdefault(kind, []).append(v["text"].strip())
    return boxes




def test_demo001_temp_only_no_invented_bp():
    ent = _run("Patient ko fever hai, bukhar 101 degree, give paracetamol 500 mg BID, "
               "do time, 3 din tak. No allergy.")
    assert _boxes(ent) == {"temp": ["101 degree"]}
    assert ent["drugs"][0]["name"] == "paracetamol"
    assert ent["drugs"][0]["dose"] == 500.0


def test_demo002_bp_row_and_drug_details():
    ent = _run("Khansi hai, cough for 5 days, BP 130 by 80, give azithromycin 500 mg once daily 3 days.")
    assert _boxes(ent) == {"bp": ["BP 130 by 80"]}
    assert ent["drugs"][0]["frequency"] == "once daily"
    assert ent["drugs"][0]["duration"] == "3 days"


def test_misheard_drug_name_is_canonicalised_beside_a_garbled_bp():
    ent = _run("Khansi hai, cough for 5 days, BPA 130 by AC, give asitromaisin 500 mg once daily 3 days.")
    assert ent["drugs"][0]["name"] == "azithromycin"


def test_live_two_drugs_freq_and_vitals():
    ent = _run(
        "Looking at their vitals, their blood pressure is sitting at 122 of 78. "
        "Their temp is currently 100.4 degrees Fahrenheit, and their oxygen saturation is "
        "looking good at 99% on room air. We are starting them on amoxicillin, 875 mg "
        "twice a day for seven days, along with ibuprofen, for 100 mg every eight hours as needed.")
    names = [d["name"] for d in ent["drugs"]]
    assert "amoxicillin" in names
    assert "ibuprofen" in names
    amox = next(d for d in ent["drugs"] if d["name"] == "amoxicillin")
    ibu = next(d for d in ent["drugs"] if d["name"] == "ibuprofen")
    assert amox["dose"] == 875.0
    assert amox["frequency"] == "twice a day"
    assert amox["duration"] == "7 days"
    assert ibu["dose"] == 100.0
    assert "8 hours" in ibu["frequency"] or "eight hours" in ibu["frequency"]
    boxes = _boxes(ent)
    assert any("122" in t and "78" in t for t in boxes["bp"])
    assert any("100.4" in t for t in boxes["temp"])
    assert any("99" in t for t in boxes["spo2"])


def test_live_allergy_candidate():
    """A misheard allergy is canonicalised, the way a misheard drug always was.

    This used to assert the raw spelling "moxasillin". An allergy table that
    says "moxasillin" does not protect anyone from amoxicillin, so the candidate
    is now resolved through the same alias map the drug rows use.
    """
    ent = _run("They don't have any known allergy to a moxasillin.")
    assert any(a["text"] == "amoxicillin" and a["negated"] for a in ent["allergies"])


# --- SpO2 cue scoping -------------------------------------------------------
# A percentage is only a saturation when a saturation cue is actually present.
# The cue regex was once widened to treat the bare word "percent" as a cue, to
# rescue spans like "95 percent" whose cue sits in the sentence rather than the
# span. That rescued the real reading and also charted every other percentage
# as an SpO2 - including 50, a peri-arrest value that passes the plausibility
# range, so nothing downstream caught it.
