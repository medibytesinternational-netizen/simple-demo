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
