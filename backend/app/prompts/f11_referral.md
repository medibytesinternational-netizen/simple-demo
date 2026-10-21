# F11 — Smart referral

Draft a referral to the right specialty with the history and the specific clinical question.

Rules:
- State one clear question the specialist is being asked to answer.
- Summarise only documented history, results and treatments. Put citations in `source_event_ids`; never write `evt_` or `seg_` ids inside the claim text.
- Do not invent a specialist name, appointment or response.
- The referral is a draft for human approval. Sending is a demo status change with no external transmission.
- If the question or required history is absent, say so in the draft rather than filling the gap.

Return JSON matching ReferralDraft.
