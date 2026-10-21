# F10 — Investigation and radiology form

Draft a pre-filled investigation or radiology request from the documented clinical record.

Rules:
- Use only the patient's documented diagnoses, current questions, allergies and recent results.
- The indication and diagnosis must be supported by cited `evt_` ids.
- Never claim an allergy is verified. Carry every known allergy into `allergies_to_verify` with `verified: false` and its source.
- Do not add an allergy that is not in the record.
- The request is a draft for human approval. Do not claim it has been sent to a laboratory, radiology department or external provider.
- No external transmission exists in this demo.

Return JSON matching InvestigationRequestDraft.
