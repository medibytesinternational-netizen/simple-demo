"""F8 Medical OCR: uploaded reports become structured values; the original is kept; uncertain readings are marked.

PRD rules 2 (never invent) and 3 (show the evidence). No AI key is set in tests, so these prove the
text-layer reader, the manual-entry route and the type-specific commit.
"""

from __future__ import annotations

from .helpers import text_pdf

from app.services.ocr import (
    collected_date,
    parse_labelled_lines,
    parse_lab_lines,
    parse_prescription_lines,
    parse_report,
)

PNG = b"\x89PNG\r\n\x1a\n"

LAB = [
    "CITY LAB REPORT",
    "Collected: 03 Sep 2026 07:40",
    "MRN: 4455",
    "Creatinine 1.0 mg/dL (0.7-1.3)",
    "eGFR 88 mL/min/1.73m2 (> 90)",
    "Potassium 4.1 mmol/L (3.5-5.1)",
]


def upload(client, name, content, mime, doc_type=None, headers=None):
    data = {"doc_type": doc_type} if doc_type else None
    return client.post("/api/documents/upload", files={"file": (name, content, mime)}, data=data, headers=headers)


def balance(client):
    return client.get("/api/credits").json()["balance"]


def events_of(client, doc_id, types=None):
    url = "/api/patients/pat_ravi/timeline?limit=500" + (f"&types={types}" if types else "")
    rows = client.get(url).json()["events"]
    return [e for e in rows if e.get("payload", {}).get("document_id") == doc_id]


# ---------- parsing ----------

def test_foreign_pdf_values_come_through_with_units_and_ranges(client):
    response = upload(client, "lab.pdf", text_pdf(LAB), "application/pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    by_name = {f["name"]: f for f in body["extracted"]["fields"]}
    assert set(by_name) == {"Creatinine", "eGFR", "Potassium"}
    assert (by_name["Creatinine"]["value"], by_name["Creatinine"]["unit"], by_name["Creatinine"]["reference_range"]) == (
        "1.0", "mg/dL", "0.7-1.3")
    assert (by_name["eGFR"]["value"], by_name["eGFR"]["unit"], by_name["eGFR"]["reference_range"]) == (
        "88", "mL/min/1.73m2", "> 90")
    assert all(f["confidence"] == 0.92 and f["page"] == 1 for f in by_name.values())
    assert "3.1" not in {f["value"] for f in by_name.values()}  # none of the seeded values
    assert body["ocr_status"] == "confirmed"
    assert body["auto_committed"] is True


def test_collected_date_is_read_from_the_report_else_the_upload_date(client):
    body = upload(client, "lab.pdf", text_pdf(LAB), "application/pdf").json()
    assert {f["collected_at"] for f in body["extracted"]["fields"]} == {"2026-09-03"}
    body = upload(client, "lab2.pdf", text_pdf(["Creatinine 1.0 mg/dL (0.7-1.3)"]), "application/pdf").json()
    assert body["extracted"]["fields"][0]["collected_at"] == body["uploaded_at"][:10]


def test_header_lines_are_not_read_as_results():
    fields = parse_lab_lines(["Collected: 12 Oct 2026\nMRN: 1001\nAge/Sex: 58 / Male\nPage 1 of 3\nCreatinine 1.0 mg/dL (0.7-1.3)"], "d")
    assert [f["name"] for f in fields] == ["Creatinine"]
    assert collected_date("Collected: 12 Oct 2026 07:40", "x") == "2026-10-12"
    assert collected_date("nothing here", "fallback") == "fallback"


def test_range_forms_and_confidence_rule():
    fields = {f["name"]: f for f in parse_lab_lines(
        ["Creatinine 1.0 mg/dL (0.7 - 1.3)\nHbA1c 8.4 %\nSodium 140\nWhite cell count 13.8 10^3/uL 4.0 - 11.0"], "d")}
    assert fields["Creatinine"]["confidence"] == 0.92
    assert fields["HbA1c"]["unit"] == "%" and fields["HbA1c"]["confidence"] == 0.7  # no range
    assert fields["Sodium"]["unit"] == "" and fields["Sodium"]["confidence"] == 0.7
    assert fields["White cell count"]["reference_range"] == "4.0 - 11.0" and fields["White cell count"]["confidence"] == 0.92


def test_prescription_and_labelled_line_parsers():
    rx = parse_prescription_lines(["Metformin 500 mg twice daily\nAmlodipine 5 mg\nPatient seen today"], "d")
    assert [(f["name"], f["value"], f["reference_range"], f["confidence"]) for f in rx] == [
        ("Metformin", "500 mg", "twice daily", 0.92), ("Amlodipine", "5 mg", "", 0.7)]
    labelled = parse_labelled_lines(["Impression: Mild cardiomegaly with\nno effusion.\nFindings: Clear lungs.\n\nunlabelled line"], "d")
    assert labelled[0]["name"] == "Impression" and labelled[0]["value"] == "Mild cardiomegaly with no effusion."
    assert labelled[0]["confidence"] == 0.8 and labelled[1]["name"] == "Findings"
    assert parse_report("radiology_report", ["No labels in this text"], "d")["fields"] == []


# ---------- no invented values ----------

def test_text_layer_with_no_readable_lines_gives_no_values(client):
    body = upload(client, "words.pdf", text_pdf(["Hello", "This letter has no results"]), "application/pdf").json()
    assert body["extracted"]["fields"] == []
    assert body["ocr_status"] == "needs_manual_entry"


def test_image_upload_returns_no_seeded_values(client):
    body = upload(client, "scan.png", PNG, "image/png").json()
    assert body["extracted"]["fields"] == []
    assert body["ocr_status"] == "needs_manual_entry"
    assert "Creatinine" not in body["raw_text"]


# ---------- confirmation and manual entry ----------

def test_missing_unit_gives_low_confidence_and_blocks_commit_until_confirmed(client):
    doc = upload(client, "x.pdf", text_pdf(["Creatinine 1.0 (0.7-1.3)"]), "application/pdf").json()
    field = doc["extracted"]["fields"][0]
    assert field["confidence"] < 0.8 and field["unit"] == ""
    assert doc["ocr_status"] == "needs_confirmation"
    refused = client.post(f"/api/documents/{doc['id']}/commit")
    assert refused.status_code == 400 and "Creatinine" in refused.json()["detail"]
    assert events_of(client, doc["id"]) == []
    assert client.post(f"/api/documents/{doc['id']}/confirm-field", json={"index": 0, "value": "1.0"}).status_code == 200
    ok = client.post(f"/api/documents/{doc['id']}/commit")
    assert ok.status_code == 200, ok.text
    assert [e["payload"]["value"] for e in ok.json()["labs"]] == ["1.0"]


def test_manual_entry_then_commit_creates_lab_events_with_typed_values(client):
    doc = upload(client, "scan.png", PNG, "image/png").json()
    assert doc["ocr_status"] == "needs_manual_entry"
    assert client.post(f"/api/documents/{doc['id']}/commit").status_code == 400  # nothing to commit yet
    first = client.post(f"/api/documents/{doc['id']}/fields", json={
        "name": "Sodium", "value": "128", "unit": "mmol/L", "reference_range": "135-145", "collected_at": "2026-10-10"})
    assert first.status_code == 200, first.text
    client.post(f"/api/documents/{doc['id']}/fields", json={"name": "Urea", "value": "9.1"})
    shown = client.get(f"/api/documents/{doc['id']}").json()
    fields = shown["extracted"]["fields"]
    assert [f["manual"] for f in fields] == [True, True] and all(f["confidence"] == 1.0 and f["confirmed"] for f in fields)
    assert shown["ocr_status"] == "reviewed"
    result = client.post(f"/api/documents/{doc['id']}/commit")
    assert result.status_code == 200, result.text
    labs = {e["payload"]["name"]: e["payload"] for e in events_of(client, doc["id"], "lab_result")}
    assert labs["Sodium"]["value"] == "128" and labs["Sodium"]["unit"] == "mmol/L"
    assert labs["Sodium"]["flag"] == "low" and labs["Sodium"]["collected_at"] == "2026-10-10"
    assert labs["Urea"]["value"] == "9.1" and labs["Urea"]["flag"] == "unknown"
    assert client.get(f"/api/documents/{doc['id']}").json()["ocr_status"] == "confirmed"


def test_manual_entry_rules(client):
    doc = upload(client, "scan.png", PNG, "image/png").json()
    url = f"/api/documents/{doc['id']}/fields"
    assert client.post(url, json={"name": "  ", "value": "1"}).status_code == 400
    assert client.post(url, json={"name": "Sodium", "value": " "}).status_code == 400
    assert client.post(url, json={"name": "Sodium", "value": "140"}).status_code == 200
    assert client.post(f"/api/documents/{doc['id']}/commit").status_code == 200
    assert client.post(url, json={"name": "Urea", "value": "5"}).status_code == 409


def test_second_commit_is_refused_and_adds_no_events(client):
    doc = upload(client, "lab.pdf", text_pdf(LAB), "application/pdf").json()
    assert len(events_of(client, doc["id"])) == 3  # a clean lab report is committed by the upload itself
    assert client.post(f"/api/documents/{doc['id']}/commit").status_code == 409
    assert len(events_of(client, doc["id"])) == 3


def test_lab_commit_flags_follow_the_reference_range(client):
    doc = upload(client, "lab.pdf", text_pdf(LAB), "application/pdf").json()
    client.post(f"/api/documents/{doc['id']}/commit")
    flags = {e["payload"]["name"]: e["payload"]["flag"] for e in events_of(client, doc["id"], "lab_result")}
    assert flags == {"Creatinine": "normal", "eGFR": "low", "Potassium": "normal"}


# ---------- other document types ----------

def test_prescription_pdf_commits_home_medicine_orders(client):
    pdf = text_pdf(["Dr Rao prescription", "Metformin 500 mg twice daily", "Atorvastatin 20 mg at night"])
    doc = upload(client, "rx.pdf", pdf, "application/pdf", "prescription").json()
    assert doc["doc_type"] == "prescription"
    assert [(f["name"], f["value"], f["reference_range"]) for f in doc["extracted"]["fields"]] == [
        ("Metformin", "500 mg", "twice daily"), ("Atorvastatin", "20 mg", "at night")]
    result = client.post(f"/api/documents/{doc['id']}/commit")
    assert result.status_code == 200, result.text
    orders = events_of(client, doc["id"], "med_order")
    assert len(orders) == 2 and not events_of(client, doc["id"], "lab_result")
    by_drug = {e["payload"]["drug"]: e["payload"] for e in orders}
    assert by_drug["Metformin"]["kind"] == "home" and by_drug["Metformin"]["status"] == "active"
    assert by_drug["Metformin"]["dose"] == "500 mg" and by_drug["Metformin"]["frequency"] == "twice daily"
    home = {m["drug"]: m for m in client.get("/api/patients/pat_ravi/state").json()["home_meds"]}
    assert home["Atorvastatin"]["frequency"] == "at night"


def test_radiology_pdf_commits_one_document_review_event(client):
    pdf = text_pdf(["CHEST X-RAY", "Findings: Clear lung fields.", "Impression: No acute cardiopulmonary disease."])
    doc = upload(client, "xr.pdf", pdf, "application/pdf", "radiology_report").json()
    assert [(f["name"], f["confidence"]) for f in doc["extracted"]["fields"]] == [("Findings", 0.8), ("Impression", 0.8)]
    assert doc["ocr_status"] == "reviewed"
    result = client.post(f"/api/documents/{doc['id']}/commit")
    assert result.status_code == 200, result.text
    reviews = events_of(client, doc["id"], "document_review")
    assert len(reviews) == 1 and not events_of(client, doc["id"], "lab_result")
    held = {f["name"]: f["value"] for f in reviews[0]["payload"]["fields"]}
    assert held == {"Findings": "Clear lung fields.", "Impression": "No acute cardiopulmonary disease."}
    assert reviews[0]["source"] == "F8" and reviews[0]["document_id"] == doc["id"]


def test_discharge_summary_reads_diagnosis_and_conclusion(client):
    pdf = text_pdf(["Diagnosis: Community acquired pneumonia", "Conclusion: Improved, fit for discharge"])
    doc = upload(client, "ds.pdf", pdf, "application/pdf", "discharge_summary").json()
    assert [f["name"] for f in doc["extracted"]["fields"]] == ["Diagnosis", "Conclusion"]
    client.post(f"/api/documents/{doc['id']}/commit")
    assert len(events_of(client, doc["id"], "document_review")) == 1


def test_unknown_document_type_is_rejected_before_any_charge(client):
    before = balance(client)
    assert upload(client, "lab.pdf", text_pdf(LAB), "application/pdf", "selfie").status_code == 400
    assert balance(client) == before


# ---------- credits ----------

def test_credits_one_for_lab_and_prescription_four_for_radiology_and_discharge(client):
    start = balance(client)
    upload(client, "lab.pdf", text_pdf(LAB), "application/pdf")
    assert balance(client) == start - 1
    upload(client, "rx.pdf", text_pdf(["Metformin 500 mg twice daily"]), "application/pdf", "prescription")
    assert balance(client) == start - 2
    upload(client, "xr.pdf", text_pdf(["Impression: Normal"]), "application/pdf", "radiology_report")
    assert balance(client) == start - 6
    upload(client, "ds.pdf", text_pdf(["Diagnosis: Pneumonia"]), "application/pdf", "discharge_summary")
    assert balance(client) == start - 10
    ledger = client.get("/api/credits").json()["ledger"]
    assert [(e["operation"], e["units"], e["feature"]) for e in ledger[:4]] == [
        ("report_analysis", 4, "F8"), ("report_analysis", 4, "F8"), ("report_reading", 1, "F8"), ("report_reading", 1, "F8")]


def test_a_scan_with_no_text_is_still_charged_before_parsing(client):
    start = balance(client)
    upload(client, "scan.png", PNG, "image/png")
    assert balance(client) == start - 1


# ---------- original kept, seeded document ----------

def test_original_file_is_still_served(client):
    pdf = text_pdf(LAB)
    doc = upload(client, "lab.pdf", pdf, "application/pdf").json()
    served = client.get(f"/api/documents/{doc['id']}/image")
    assert served.status_code == 200 and served.content == pdf
    assert served.headers["content-type"] == "application/pdf"
    png = upload(client, "scan.png", PNG, "image/png").json()
    assert client.get(f"/api/documents/{png['id']}/image").content == PNG


def test_seeded_rehearsal_document_still_has_potassium_at_074(client):  # guard
    doc = client.get("/api/documents/doc_seed_outside").json()
    potassium = next(f for f in doc["extracted"]["fields"] if f["name"] == "Potassium")
    assert potassium["confidence"] == 0.74 and potassium["value"] == "5.3"
    assert doc["ocr_status"] == "needs_confirmation"
    assert client.post("/api/documents/doc_seed_outside/commit").status_code == 400


def test_document_list_reports_field_counts(client):
    doc = upload(client, "lab.pdf", text_pdf(LAB), "application/pdf").json()
    listed = {d["id"]: d for d in client.get("/api/documents").json()["documents"]}
    assert listed[doc["id"]]["field_count"] == 3
    assert listed["doc_seed_outside"]["field_count"] == 5
