"""Vital-sign spans and their physiological plausibility check."""
import re

# Numeral-tuned vitals: decimals, 'of' separator, long-form 'blood pressure',
# temp with F/C units, SpO2 with room-air mishear tolerance.
TEMP_NUM = r"\d{2,3}(?:\.\d{1,2})?\s*(?:degrees?(?:\s*(?:fahrenheit|celsius|F|C))?|°\s*[FC]?)"


# Dictation puts a few words between the cue and the value - a copula, a hedge,
# a repeated word where the speaker restarted. The existing `oxygen saturation`
# and `temp` rules already allow that with a bounded digit-free gap; every cue
# below uses the same idiom rather than enumerating `is|was|around|...`, so
# "pulse 92", "pulse rate is 88" and "heart rate was around 96" all match.
# A comma ends the cue's scope - "low sugar diet, review after 15 days" is not
# a glucose reading - and a number followed by a duration unit is an interval,
# not a measurement ("heart failure for 10 years").
_CUE_GAP = r"[^\d.,]{0,14}"


_NOT_DURATION = (r"(?!\s*(?:years?|yrs?|months?|weeks?|days?|hours?|hrs?"
                 r"|minutes?|mins?|seconds?|secs?)\b)")


_NUM = r"(?<!\d)\d{2,3}(?!\d)"


VITALS_PAT = re.compile(
    # BP's gap allows digits: a decoder routinely runs a stray number into the
    # copula ("blood pressure is19 160/90"). The pair itself is the signature,
    # so the lazy gap stops at the first real systolic/diastolic pair.
    r"((?:BP|B[\s-]*P|blood pressure)[^.]{0,24}?(?<!\d)\d{2,3}(?:\.\d{1,2})?\s*(by|/|over|of)\s*\d{2,3}(?:\.\d{1,2})?"
    r"|\b" + TEMP_NUM + r"\b"
    r"|SpO2\s*\d{2,3}(?:\.\d{1,2})?%?"
    r"|\b\d{2,3}(?:\.\d{1,2})?\s*(?:%|percent)\s*(?:on\s+(?:room\s*air|rhoomair))?"
    r"|oxygen saturation[^\d.]{0,10}\d{2,3}(?:\.\d{1,2})?\s*%?"
    r"|(?:pulse|heart)(?:\s*rate)?" + _CUE_GAP + _NUM + _NOT_DURATION +
    r"|(?:respiratory|resp(?:iration)?|breathing)\s*rate" + _CUE_GAP + r"(?<!\d)\d{1,3}(?!\d)" + _NOT_DURATION +
    r"|\b(?:blood\s+)?(?:glucose|sugar|BGL|RBS|CBG)[^\d.,]{0,40}(?<!\d)\d{2,3}(?:\.\d{1,2})?(?!\d)" + _NOT_DURATION +
    r"|(?<!\d)\d{1,3}(?:\.\d{1,2})?\s*(?:mg\s*/\s*d[lL]|milligrams?\s+per\s+decilit(?:re|er)"
    r"|mmol\s*/\s*[lL]|millimoles?\s+per\s+lit(?:re|er))"
    r"|temp[^\d.]{0,10}" + TEMP_NUM + r")",
    re.I,
)


# Physiological plausibility: generous bounds that only catch ASR garbage
# (pulse 940, BP 400/65, SpO2 400%) — never a real reading. A violation keeps
# the row (recall unchanged) but forces RED so it cannot chart at YELLOW.
VITALS_RANGES = {
    "spo2": (50.0, 100.0),
    "pulse": (20.0, 250.0),
    "temp_f": (90.0, 110.0),
    # The same reading in the other scale. Widening `temp_f` to cover Celsius
    # would have to reach down to 30, and 38 - a textbook fever in Celsius -
    # is also what a decoder produces when it drops a digit from a Fahrenheit
    # reading, so one range cannot both admit Celsius and still catch garbage.
    # The unit the span carries decides which range applies.
    "temp_c": (30.0, 45.0),
    "bp_sys": (50.0, 300.0),
    "bp_dia": (20.0, 200.0),
    "rr": (5.0, 80.0),
    "glucose": (20.0, 1500.0),
}


def vital_span_kind(span):
    """Kind of a vitals span for the plausibility check (mirrors scorer cues)."""
    if re.search(r"\bBP\b|blood\s*pressure|\d+\s*(?:by|/|over|of)\s*\d+", span, re.I):
        return "bp"
    if re.search(r"spo2|sp02|o2\s*sat|oxygen\s*sat|saturation|%|percent", span, re.I):
        return "spo2"
    if re.search(r"temp|fahrenheit|celsius|degree|°", span, re.I):
        return "temp_f"
    if re.search(r"respiratory\s*rate|resp\b|respiration|breathing\s*rate", span, re.I):
        return "rr"
    if re.search(r"pulse|heart\s*rate|\bHR\b", span, re.I):
        return "pulse"
    if re.search(r"glucose|sugar|BGL|RBS|CBG|mg\s*/\s*d[lL]|mmol"
                 r"|milligrams?\s+per\s+decilit(?:re|er)"
                 r"|millimoles?\s+per\s+lit(?:re|er)", span, re.I):
        return "glucose"
    return None


# A Celsius marker attached to the number itself: "38 degrees Celsius",
# "38 °C", "38 C". The digit prefix is what keeps it from firing on a stray
# capital C elsewhere in the span, and `(?![A-Za-z])` stops a bare `C` from
# matching the first letter of `Celsius`'s neighbours or of `cardiac`.
_CELSIUS = re.compile(r"\d\s*(?:°\s*|degrees?\s*)?(?:celsius\b|centigrade\b|C(?![A-Za-z]))", re.I)


def _temp_scale(span):
    """`temp_c` when the span says Celsius, else `temp_f`.

    Unmarked stays Fahrenheit: that is the scale this project's gold data and
    its charts are written in, and treating an unmarked number as "whichever
    scale makes it plausible" would retire the check entirely.
    """
    return "temp_c" if _CELSIUS.search(span) else "temp_f"


def vital_span_plausible(span):
    """(ok, note) — False only when a number in the span is outside any human range."""
    kind = vital_span_kind(span)
    if kind == "temp_f":
        kind = _temp_scale(span)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", span)]
    if kind == "bp" and len(nums) >= 2:
        lo_sys, hi_sys = VITALS_RANGES["bp_sys"]
        lo_dia, hi_dia = VITALS_RANGES["bp_dia"]
        if not (lo_sys <= nums[0] <= hi_sys and lo_dia <= nums[1] <= hi_dia):
            return False, (f"physiologically implausible BP {nums[0]:g}/{nums[1]:g} "
                           "- human must confirm")
        return True, ""
    if kind in VITALS_RANGES and nums:
        lo, hi = VITALS_RANGES[kind]
        bad = [n for n in nums if not (lo <= n <= hi)]
        if bad:
            return False, (f"physiologically implausible {kind} "
                           f"{', '.join(f'{n:g}' for n in bad)} - human must confirm")
    return True, ""
