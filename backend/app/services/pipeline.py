"""Voice notes through the local MediBytes pipeline (the repo's ``medibytes/`` package).

The recording is queued on ``medibytes.api.jobs.JobService`` (one worker thread, job state on
disk) with the note template of the feature it was recorded for (F1 -> ``opd``). The pipeline
writes that feature's sections; ``draft_content`` maps them onto the feature's draft schema,
item by item, keeping each item's proof sentence and verified / needs_review status.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Feature -> medibytes note template. Only features listed here take voice.
# F3 (ward round) uses the pipeline for transcription only; its tasks come from the F3 round drafter.
TEMPLATE_FOR = {"F1": "opd", "F2": "admission", "F3": "progress", "F4": "progress", "F11": "referral"}

_lock = threading.Lock()
_service: Any = None


def configured() -> bool:
    """The MediBytes pipeline needs gpt-4.1, so it runs only with an OpenAI key."""
    return bool(settings.openai_api_key)


def _jobs() -> Any:
    """Start the job service once; the speech models load on the first job, not at import."""
    global _service
    with _lock:
        if _service is None:
            try:
                from medibytes.api.jobs import JobService
                from medibytes.config import Settings
                from medibytes.factory import build_pipeline
            except ImportError as exc:
                raise HTTPException(
                    503, f"The MediBytes pipeline is not installed ({exc.name}); install requirements-medibytes.txt"
                ) from exc
            pipeline_lock = threading.Lock()
            built: dict[str, Any] = {}

            def provider() -> Any:
                with pipeline_lock:
                    if "p" not in built:
                        built["p"] = build_pipeline(Settings.from_env(env_file=None))
                    return built["p"]

            _service = JobService(settings.medibytes_runs_dir, provider)
        return _service


def _index(audio_id: str) -> Path:
    return Path(settings.medibytes_runs_dir) / "audio" / f"{audio_id}.json"


def submit(
    contents: bytes, filename: str, content_type: str, audio_id: str, feature: str = "F1", extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower() or ".webm"
    data_hash = hashlib.sha256(contents).hexdigest()
    job = _jobs().submit(
        data_hash, filename, suffix, lambda path: path.write_bytes(contents), template=TEMPLATE_FOR[feature]
    )
    index = _index(audio_id)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"job_id": job["job_id"], "feature": feature, **(extra or {})}), encoding="utf-8")
    return {"audio_id": audio_id, "job_id": job["job_id"], "status": job["status"]}


def fetch(audio_id: str) -> dict[str, Any] | None:
    """Job state; once succeeded, also the heard transcript and the feature's note."""
    index = _index(audio_id)
    if not index.is_file():
        return None
    entry = json.loads(index.read_text(encoding="utf-8"))
    service = _jobs()
    job = service.get(entry["job_id"])
    if job is None:
        return None
    out: dict[str, Any] = {
        "audio_id": audio_id,
        "feature": entry.get("feature", "F1"),
        "job_status": job["status"],
        "job_error": job.get("error"),
        "role": entry.get("role"),
    }
    if job["status"] == "succeeded":
        result = service.result(job) or {}
        out["transcript"] = str((result.get("transcript") or {}).get("text") or "").strip()
        out["note"] = result.get("discharge") or {}
    return out


# ---------- note -> draft ----------

SECTION_LABELS = {
    # Hospital OPD format (F1).
    "mode_of_admission": "Mode of admission",
    "referring_physician": "Referring physician",
    "previous_admission": "Previous admission",
    "previous_diagnosis": "Previous diagnosis",
    "allergies": "Allergies",
    "pain": "Pain",
    "occupation": "Occupation",
    "source_of_history": "Source of history and reliability",
    "chief_complaints": "Chief complaints",
    # Hospital admission format (F2).
    "admission_type": "Elective or emergency",
    "ward": "Admit to ward",
    "speciality": "Speciality",
    "provisional_diagnosis": "Provisional diagnosis",
    "proposed_treatment": "Proposed treatment",
    "expected_outcome": "Expected outcome",
    "possible_complications": "Possible complications",
    "cost_category": "Approximate cost or category",
    "admission_labs": "Admission labs",
    "imaging_studies": "Imaging studies",
    "consultations_required": "Consultations required",
    # Discharge and earlier note sections.
    "chief_complaint": "Chief complaint",
    "history_of_present_illness": "History of present illness",
    "past_history": "Past history",
    "examination_general": "General examination",
    "examination_systemic": "Systemic examination",
    "assessment": "Assessment",
    "medications": "Medications",
    "investigations": "Investigations",
    "plan": "Plan",
    "advice": "Advice",
    "follow_up": "Follow-up",
}

_CONFIDENCE = {"verified": 0.9, "needs_review": 0.6}
_WORD = re.compile(r"[a-z0-9]+")


def _items(note: dict[str, Any], key: str) -> list[dict[str, Any]]:
    block = (note.get("sections") or {}).get(key) or {}
    return [it for it in block.get("items") or [] if str(it.get("text") or "").strip()]


def _segment_for(source: str, segments: list[dict[str, Any]]) -> str | None:
    """The transcript segment the item was heard in: containing its proof, else most shared words."""
    source = str(source or "").strip()
    if not segments:
        return None
    if source:
        for seg in segments:
            text = str(seg.get("text") or "")
            if source in text or (text and text in source):
                return seg["segment_id"]
    words = set(_WORD.findall(source.lower()))
    best = max(segments, key=lambda seg: len(words & set(_WORD.findall(str(seg.get("text") or "").lower()))))
    return best["segment_id"]


class _Mapper:
    def __init__(self, note: dict[str, Any], event_id: str, segments: list[dict[str, Any]]):
        self.note, self.event_id, self.segments = note, event_id, segments
        self.needs_review: list[dict[str, str]] = []

    def items(self, key: str) -> list[dict[str, Any]]:
        found = _items(self.note, key)
        for it in found:
            if it.get("verified_status") == "needs_review":
                review = {"section": SECTION_LABELS.get(key, key), "text": str(it["text"]).strip()}
                if review not in self.needs_review:
                    self.needs_review.append(review)
        return found

    def claim(self, item: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        seg = _segment_for(item.get("source_sentence", ""), self.segments)
        return {
            "text": prefix + str(item["text"]).strip(),
            "source_event_ids": [self.event_id],
            "source_segment_ids": [seg] if seg else [],
            "confidence": _CONFIDENCE.get(str(item.get("verified_status") or ""), 0.75),
        }

    def joined(self, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Several items as one claim (for single-claim fields), citing every segment used."""
        if not items:
            return None
        claims = [self.claim(it) for it in items]
        return {
            "text": "; ".join(c["text"] for c in claims),
            "source_event_ids": [self.event_id],
            "source_segment_ids": list(dict.fromkeys(s for c in claims for s in c["source_segment_ids"])),
            "confidence": min(c["confidence"] for c in claims),
        }


def _f1_content(m: _Mapper) -> dict[str, Any]:
    """The hospital OPD format. Record headings are added when the draft is created."""
    from .opd import OPD_FORMAT, heard_not_documented

    one = ("mode_of_admission", "referring_physician", "previous_admission", "pain",
           "occupation", "source_of_history", "history_of_present_illness")
    many = ("previous_diagnosis", "allergies", "chief_complaints")
    content: dict[str, Any] = {"format": OPD_FORMAT}
    for key in one:
        content[key] = m.joined(m.items(key))
    for key in many:
        content[key] = [m.claim(it) for it in m.items(key)]
    content["not_documented"] = heard_not_documented(content)
    content["needs_review"] = m.needs_review
    return content


def _f2_content(m: _Mapper) -> dict[str, Any]:
    """The hospital admission format. Record headings and the OPD fill-in are added at draft creation."""
    from ..schemas import ADMISSION_HEARD_SECTIONS
    from .admission import ADMIT_FORMAT

    content: dict[str, Any] = {"format": ADMIT_FORMAT}
    for key, _label, many in ADMISSION_HEARD_SECTIONS:
        content[key] = [m.claim(it) for it in m.items(key)] if many else m.joined(m.items(key))
    content["needs_review"] = m.needs_review
    return content


def _f4_content(m: _Mapper) -> dict[str, Any]:
    """One progress-notes row: the note as said. Role, header and signature are added later."""
    from .progress import PROGRESS_FORMAT

    notes = [m.claim(it) for it in m.items("notes")]
    return {"format": PROGRESS_FORMAT, "notes": notes, "not_documented": [] if notes else ["Notes"],
            "needs_review": m.needs_review}


def _f11_content(m: _Mapper) -> dict[str, Any]:
    """Referral part one as dictated. Header, record summary and signature are added later."""
    from .referral_form import REFERRAL_FORMAT, referral_type

    kind = m.joined(m.items("referral_type"))
    return {
        "format": REFERRAL_FORMAT,
        "referral_type": referral_type(kind["text"]) if kind else None,
        "unit_chief": m.joined(m.items("unit_chief")),
        "department": m.joined(m.items("department")),
        "salient_details": [m.claim(it) for it in m.items("salient_details")],
        "needs_review": m.needs_review,
    }


_BUILDERS = {"F1": _f1_content, "F2": _f2_content, "F4": _f4_content, "F11": _f11_content}


def draft_content(feature: str, note: dict[str, Any], event_id: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    """The feature's draft content from its medibytes note."""
    return _BUILDERS[feature](_Mapper(note, event_id, segments))


def has_items(note: dict[str, Any]) -> bool:
    return any(_items(note, key) for key in (note.get("sections") or {}))
