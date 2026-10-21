# F3 — Round handover

Draft a ward-round note and a list of proposed tasks from the supplied round transcript.

Rules:
- The note summarizes what was discussed. Every claim cites `evt_` and `seg_` ids.
- Each proposed task must be a concrete action stated in the transcript, with `source_segment_ids`.
- Do not invent instructions. Do not silently drop an instruction.
- Proposed tasks are proposals for the clinician to accept or reject; do not claim they were created.
- Draft `nursing_entries` as proposed nursing-chart entries. When an instruction changes what a nurse must carry out or chart (for example a medication hold, observation, sample collection or wound review), produce one nursing entry for it as well as the task. They are not written to the nursing chart until the round note is approved.
- Do not drop an explicit nursing action spoken by the nurse. Record it as a nursing entry, not as a clinician task.
- Flag ambiguous or unsafe instructions with lower confidence rather than silently normalizing them.

Return JSON matching RoundDraft.
