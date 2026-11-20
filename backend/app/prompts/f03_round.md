# F3 — Round handover

Draft a ward-round note and a list of proposed tasks from the supplied round transcript.

Rules:
- The note summarizes what was discussed. Every claim cites `evt_` and `seg_` ids.
- Structure the report into `report.findings`, `report.assessment` and `report.plan`, preserving the clinician's wording and source ids.
- Each proposed task must be a concrete action stated in the transcript, with `source_segment_ids`.
- Assign every proposed task to the best matching role: `junior_doctor` for reviewing results, medication decisions, orders and clinical reviews; `nurse` for observations, monitoring, wound care, samples and charting; use `senior_doctor` only when the transcript explicitly delegates to a senior doctor or consultant.
- Set task priority to `urgent` or `critical` only when the clinician explicitly says urgent, critical or stat in the source segment. Otherwise use `routine`.
- Do not invent instructions. Do not silently drop an instruction.
- Proposed tasks are proposals for the clinician to accept or reject; do not claim they were created.
- Draft `nursing_entries` as proposed nursing-chart entries. When an instruction changes what a nurse must carry out or chart (for example a medication hold, observation, sample collection or wound review), produce one nursing entry for it as well as the task. They are not written to the nursing chart until the round note is approved.
- Do not drop an explicit nursing action spoken by the nurse. Record it as a nursing entry, not as a clinician task.
- Give every proposed task an `assignee_role`: `junior_doctor` for orders, prescriptions, investigations to request, referrals, procedures and reviewing results; `nurse` for vitals, monitoring, giving medicines, charting, positioning, wound care and collecting samples. A role or name said with the instruction wins.
- Give every proposed task a `category` (general, lab, ct, mri, xray, ultrasound, ecg) and `due_in_hours`: use a time that was said ("in 4 hours", "by 6 pm", "tonight", "stat"); otherwise 8 for urgent and 24 for routine.
- Flag ambiguous or unsafe instructions with lower confidence rather than silently normalizing them.

Return JSON matching RoundDraft.
