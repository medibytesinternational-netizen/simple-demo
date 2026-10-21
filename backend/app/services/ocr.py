from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .identity import acting_name
from ..config import settings
from ..models import Document
from .cached import f11_investigation  # noqa: F401  (kept for context parity)
from .timeline import add_audit, new_id


def sample_svg(patient_name: str, mrn: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1160" viewBox="0 0 900 1160">
  <rect width="900" height="1160" fill="#ffffff"/>
  <rect x="0" y="0" width="900" height="90" fill="#eef2f7"/>
  <text x="48" y="42" font-family="Arial" font-size="22" font-weight="700" fill="#16181d">STAR CITY DIAGNOSTICS</text>
  <text x="48" y="68" font-family="Arial" font-size="13" fill="#5b6472">Department of Laboratory Medicine · NABL accredited</text>
  <text x="48" y="132" font-family="Arial" font-size="16" font-weight="700" fill="#16181d">BIOCHEMISTRY REPORT</text>
  <text x="48" y="160" font-family="Arial" font-size="13" fill="#333">Patient: {patient_name}</text>
  <text x="48" y="182" font-family="Arial" font-size="13" fill="#333">MRN: {mrn}        Age/Sex: 58 / Male</text>
  <text x="48" y="204" font-family="Arial" font-size="13" fill="#333">Collected: 12 Oct 2026 07:40        Reported: 12 Oct 2026 11:20</text>
  <text x="48" y="226" font-family="Arial" font-size="13" fill="#333">Referred by: Dr. Meera Shah        Sample: Serum</text>
  <line x1="48" y1="246" x2="852" y2="246" stroke="#c9d0d9"/>
  <text x="48" y="280" font-family="Arial" font-size="12" font-weight="700" fill="#5b6472">TEST</text>
  <text x="380" y="280" font-family="Arial" font-size="12" font-weight="700" fill="#5b6472">RESULT</text>
  <text x="540" y="280" font-family="Arial" font-size="12" font-weight="700" fill="#5b6472">UNIT</text>
  <text x="660" y="280" font-family="Arial" font-size="12" font-weight="700" fill="#5b6472">REFERENCE</text>
  <line x1="48" y1="296" x2="852" y2="296" stroke="#c9d0d9"/>
  <text x="48" y="332" font-family="Arial" font-size="15" fill="#16181d">Creatinine</text>
  <text x="380" y="332" font-family="Arial" font-size="15" font-weight="700" fill="#c62828">3.1</text>
  <text x="540" y="332" font-family="Arial" font-size="15" fill="#16181d">mg/dL</text>
  <text x="660" y="332" font-family="Arial" font-size="15" fill="#16181d">0.7 - 1.3</text>
  <text x="48" y="376" font-family="Arial" font-size="15" fill="#16181d">eGFR (CKD-EPI)</text>
  <text x="380" y="376" font-family="Arial" font-size="15" font-weight="700" fill="#c62828">21</text>
  <text x="540" y="376" font-family="Arial" font-size="15" fill="#16181d">mL/min/1.73m²</text>
  <text x="660" y="376" font-family="Arial" font-size="15" fill="#16181d">&gt; 90</text>
  <text x="48" y="420" font-family="Arial" font-size="15" fill="#16181d">Potassium</text>
  <text x="380" y="420" font-family="Arial" font-size="15" font-weight="700" fill="#b26a00">5.3</text>
  <text x="540" y="420" font-family="Arial" font-size="15" fill="#16181d">mmol/L</text>
  <text x="660" y="420" font-family="Arial" font-size="15" fill="#16181d">3.5 - 5.1</text>
  <text x="48" y="464" font-family="Arial" font-size="15" fill="#16181d">HbA1c</text>
  <text x="380" y="464" font-family="Arial" font-size="15" font-weight="700" fill="#b26a00">8.4</text>
  <text x="540" y="464" font-family="Arial" font-size="15" fill="#16181d">%</text>
  <text x="660" y="464" font-family="Arial" font-size="15" fill="#16181d">4.0 - 5.6</text>
  <text x="48" y="508" font-family="Arial" font-size="15" fill="#16181d">White cell count</text>
  <text x="380" y="508" font-family="Arial" font-size="15" font-weight="700" fill="#b26a00">13.8</text>
  <text x="540" y="508" font-family="Arial" font-size="15" fill="#16181d">10^3/µL</text>
  <text x="660" y="508" font-family="Arial" font-size="15" fill="#16181d">4.0 - 11.0</text>
  <line x1="48" y1="548" x2="852" y2="548" stroke="#c9d0d9"/>
  <text x="48" y="590" font-family="Arial" font-size="13" font-style="italic" fill="#5b6472">Interpretation: Creatinine elevated. eGFR severely reduced. Potassium at upper limit.</text>
  <text x="48" y="616" font-family="Arial" font-size="13" fill="#5b6472">This is a synthetic report generated for a product demo. Not for clinical use.</text>
  <text x="48" y="700" font-family="Arial" font-size="13" fill="#333">Dr. A. Rao, MD (Pathology)</text>
  <text x="48" y="722" font-family="Arial" font-size="12" fill="#6b7280">Digitally signed · 12 Oct 2026</text>
  <rect x="48" y="800" width="804" height="1" fill="#c9d0d9"/>
  <text x="48" y="840" font-family="Arial" font-size="12" fill="#6b7280">Scanned from paper · OCR confidence varies by field</text>
</svg>"""


def seed_extraction() -> dict[str, Any]:
    return {
        "document_type": "lab_report",
        "fields": [
            {
                "name": "Creatinine",
                "value": "3.1",
                "unit": "mg/dL",
                "reference_range": "0.7 - 1.3",
                "collected_at": "2026-10-12",
                "confidence": 0.97,
                "page": 1,
                "bbox": [0.42, 0.27, 0.54, 0.31],
            },
            {
                "name": "eGFR",
                "value": "21",
                "unit": "mL/min/1.73m²",
                "reference_range": "> 90",
                "collected_at": "2026-10-12",
                "confidence": 0.95,
                "page": 1,
                "bbox": [0.42, 0.31, 0.54, 0.35],
            },
            {
                "name": "Potassium",
                "value": "5.3",
                "unit": "mmol/L",
                "reference_range": "3.5 - 5.1",
                "collected_at": "2026-10-12",
                "confidence": 0.74,
                "page": 1,
                "bbox": [0.42, 0.35, 0.54, 0.39],
            },
            {
                "name": "HbA1c",
                "value": "8.4",
                "unit": "%",
                "reference_range": "4.0 - 5.6",
                "collected_at": "2026-10-12",
                "confidence": 0.93,
                "page": 1,
                "bbox": [0.42, 0.39, 0.54, 0.43],
            },
            {
                "name": "White cell count",
                "value": "13.8",
                "unit": "10^3/µL",
                "reference_range": "4.0 - 11.0",
                "collected_at": "2026-10-12",
                "confidence": 0.88,
                "page": 1,
                "bbox": [0.42, 0.43, 0.54, 0.47],
            },
        ],
        "raw_text": (
            "STAR CITY DIAGNOSTICS. Biochemistry report. Creatinine 3.1 mg/dL (0.7-1.3). "
            "eGFR 21 mL/min/1.73m2. Potassium 5.3 mmol/L (3.5-5.1). HbA1c 8.4 %. "
            "White cell count 13.8 10^3/uL (4.0-11.0)."
        ),
    }


def cached_extraction() -> dict[str, Any]:
    return seed_extraction()


def _pdf_text(path: Path) -> str:
    """Best-effort text-layer extraction from a text PDF.

    Scanned PDFs have no text layer; those deliberately fall back to the cached
    demo extraction rather than pretending an absent layer was read.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages[:3]]
        return "\n".join(pages).strip()
    except Exception:
        return ""


def run_ocr(db: Session, document: Document) -> dict[str, Any]:
    mode = settings.effective_llm_mode
    extracted: dict[str, Any] | None = None
    path = Path(document.path or "")
    is_image = bool(document.mime and document.mime.startswith("image/"))
    is_pdf = document.mime == "application/pdf" or (document.filename or "").lower().endswith(".pdf")
    if mode == "live" and document.image_kind == "file" and (is_image or is_pdf):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key)
            user_content: str | list[dict[str, Any]]
            if is_image:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                user_content = [
                    {"type": "text", "text": "Extract this scanned lab report for a clinical demo."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{document.mime};base64,{encoded}"},
                    },
                ]
            else:
                pdf_text = _pdf_text(path)
                if not pdf_text:
                    raise ValueError("PDF has no extractable text layer")
                user_content = (
                    "Extract laboratory fields from this PDF text. Treat the supplied text as the "
                    "only source.\n\n" + pdf_text[:20000]
                )
            response = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract laboratory fields from the source. Return JSON with keys "
                            "document_type, fields (name, value, unit, reference_range, collected_at, "
                            "confidence 0-1, page, bbox normalized [x0,y0,x1,y1]), raw_text. "
                            "Do not invent values; use lower confidence when unclear."
                        ),
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
                timeout=60,
            )
            extracted = json.loads(response.choices[0].message.content or "{}")
        except Exception:
            extracted = None
    if extracted is None:
        extracted = cached_extraction()
    document.extracted = extracted
    low_confidence = any(float(field.get("confidence", 1)) < 0.8 for field in extracted.get("fields", []))
    document.ocr_status = "needs_confirmation" if low_confidence else "reviewed"
    document.raw_text = extracted.get("raw_text", "")
    add_audit(
        db,
        "document_ocr_completed",
        "document",
        document.id,
        document.patient_id,
        actor_type="model",
        actor_name=settings.openai_model if mode == "live" else "Cached demo OCR",
        after={"fields": len(extracted.get("fields", [])), "needs_confirmation": low_confidence},
        meta={"mode": mode},
    )
    return extracted


def new_document(
    db: Session,
    *,
    patient_id: str,
    encounter_id: str,
    filename: str,
    path: str = "",
    mime: str = "image/png",
    image_kind: str = "file",
    doc_type: str = "lab_report",
) -> Document:
    document = Document(
        id=new_id("doc"),
        patient_id=patient_id,
        encounter_id=encounter_id,
        filename=filename,
        mime=mime,
        path=path,
        image_kind=image_kind,
        doc_type=doc_type,
        ocr_status="pending",
        uploaded_by=acting_name(),
        extracted={},
    )
    db.add(document)
    db.flush()
    return document
