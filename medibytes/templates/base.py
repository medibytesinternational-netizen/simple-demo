"""What one note format is: its sections, its own prompt wording, and its fact routing.

Stage 7's hardening (verbatim gate, canonicalize, pre-fill, coverage) was written and
measured for the six discharge sections. A feature's section reuses that hardening by
naming the discharge section it ``behaves_like``: a chief complaint is policed like the
present illness (narrative, a number only as a duration), a medicines list like the plan
(no number unless it is a verified dose), and so on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BASE_SECTIONS = ("present_illness", "examination_findings",
                 "previous_diagnosis", "plan_of_management",
                 "diet_instructions", "general_instructions")


@dataclass(frozen=True)
class SectionSpec:
    key: str
    rule: str                      # what the section holds, stated in every prompt
    example: tuple[str, str]       # (sentence the clinician said, item written from it)
    behaves_like: str              # one of BASE_SECTIONS: which hardening rules apply
    many: bool = True              # a list of items, or one item

    def __post_init__(self):
        if self.behaves_like not in BASE_SECTIONS:
            raise ValueError(f"{self.key}: behaves_like must be one of {BASE_SECTIONS}")


@dataclass(frozen=True)
class NoteTemplate:
    name: str
    document: str                  # "discharge note", "OPD consultation note", ...
    intro: str                     # first line of the note prompt
    sections: tuple[SectionSpec, ...]
    prefill: dict[str, str]        # verified fact kind -> section key (pre-fill and canonicalize)
    schema_line: str               # the JSON shape shown to the model
    schema_file: str               # under medibytes/schemas/
    extra_rules: str = ""          # feature-specific rules appended to the shared ones
    item_extras: tuple[str, ...] = ()   # extra item fields kept from the reply (e.g. priority)
    _by_key: dict = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "_by_key", {s.key: s for s in self.sections})
        for kind, key in self.prefill.items():
            if key not in self._by_key:
                raise ValueError(f"{self.name}: prefill {kind} -> unknown section {key}")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.sections)

    def spec(self, key: str) -> SectionSpec:
        return self._by_key[key]

    def base(self, key: str) -> str:
        """The discharge section whose hardening rules govern this section."""
        spec = self._by_key.get(key)
        return spec.behaves_like if spec else key

    def rule(self, key: str) -> str:
        return self._by_key[key].rule

    def example(self, key: str) -> tuple[str, str]:
        return self._by_key[key].example

    def json_schema(self) -> dict:
        """Draft-7 schema of this note, the same item shape as the discharge schema."""
        item = {"type": "object", "required": ["text", "source_sentence"],
                "properties": {"text": {"type": "string"}, "source_sentence": {"type": "string"},
                               "seg_id": {"type": ["integer", "null"]},
                               "confidence": {"type": "number"},
                               "verified_kind": {"type": "string"},
                               "verified_status": {"type": "string",
                                                   "enum": ["verified", "needs_review", "rejected"]}}}
        section = {"type": "object", "required": ["items"],
                   "properties": {"items": {"type": "array", "items": item}}}
        return {"$schema": "http://json-schema.org/draft-07/schema#",
                "title": f"{self.document} (heard-only, proof-grounded)",
                "type": "object", "required": ["sections"],
                "properties": {
                    "sections": {"type": "object", "required": list(self.keys),
                                 "additionalProperties": False,
                                 "properties": {k: section for k in self.keys}},
                    "provenance": {"type": "object"}}}


def schema_line(keys: tuple[str, ...], extras: str = "") -> str:
    """The JSON shape shown to the model, written like the discharge one."""
    first, rest = keys[0], keys[1:]
    lines = [f'{{"{first}": {{"items": [{{"fact_id": "F1", "text": "...", "source_sentence": '
             f'"exact sentence heard", "seg_id": 0, "confidence": 0.9{extras}}}]}},']
    lines += [f' "{k}": {{"items": [...]}},' for k in rest]
    lines[-1] = lines[-1].rstrip(",") + "}"
    return "\n".join(lines) + "\n\n"
