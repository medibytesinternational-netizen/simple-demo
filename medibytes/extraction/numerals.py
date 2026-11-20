"""Spoken numbers to digits: "five hundred milligram" -> "500 milligram".

Dictation reads strengths and vitals aloud, and every downstream regex matches
digits, so this runs before extraction on a digitized copy of the text.
"""
import re

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
         "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}


_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


_NUMW = sorted(list(_ONES) + list(_TENS) + ["hundred", "and"], key=len, reverse=True)


_NUMW_RUN = re.compile(r"\b(?:%s)(?:[ -](?:%s))*\b" % ("|".join(_NUMW), "|".join(_NUMW)), re.I)


def _parse_numwords(toks):
    had_and = "and" in toks
    toks = [t for t in toks if t != "and"]
    # Digit-by-digit dictation, which is how a strength or a BP is read aloud:
    # "six two five" is 625, not 6+2+5.  Summing a run of single digits turned
    # `amoxicillin six two five milligram` into a 13 mg row at GREEN - a 48x
    # underdose carrying the pipeline's highest confidence.  Ten through
    # nineteen are excluded by the `<= 9` test, so "one ten" -> 110 and
    # "two fifteen" -> 215 still reach the spoken-hundreds rule below.
    if len(toks) >= 2 and all(t in _ONES and _ONES[t] <= 9 for t in toks):
        if had_and:
            # "one and two" is a conjunction, not a number.  Returning 0 leaves
            # the original words in place, so the dose fails to parse and the
            # row goes RED rather than inventing a value either way.
            return 0
        return int("".join(str(_ONES[t]) for t in toks))
    # "one thirty" -> 130, and "one ten" / "two fifteen" -> 110 / 215: a spoken
    # three-digit number drops the word "hundred" whether the remainder is a
    # tens word or a teen.
    if (len(toks) >= 2 and toks[0] in _ONES and 1 <= _ONES[toks[0]] <= 9
            and (toks[1] in _TENS or (toks[1] in _ONES and _ONES[toks[1]] >= 10))):
        total, toks = _ONES[toks[0]] * 100, toks[1:]
    else:
        total = 0
    cur = 0
    for w in toks:
        if w == "hundred":
            cur = (cur or 1) * 100
        elif w in _TENS:
            cur += _TENS[w]
        elif w in _ONES:
            cur += _ONES[w]
    return total + cur


# A spoken decimal is two integer runs joined by "point": "ninety-eight point
# six" -> 98.6. Without this the integers convert and the separator survives as
# the word "point", so the temperature never reaches a numeric field.
_SPOKEN_POINT = re.compile(r"(?<![\d.])(\d{1,3})\s+point\s+(\d{1,2})\b(?!\s*\d)", re.I)


# "for two three days" is a range - two to three days - not the number 23.
# Indian-English dictation says it constantly. Summing gave 5 and concatenating
# gives 23; both are wrong, and 23 is the more dangerous of the two, so the
# words are left alone and the duration simply does not parse.
# Dose units are included: "two three milligram" is as likely 2-3 mg as it is
# 23 mg, and no case this fix needs to catch has two consecutive ascending
# digits before a unit - "six two five" is three tokens, and the "eight zero"
# of a diastolic is not consecutive.
_RANGE_TAIL = re.compile(r"^\s*(?:days?|din\b|weeks?|months?|hours?|hrs?|minutes?"
                         r"|mins?|times?|tablets?|tabs?|doses?"
                         r"|mg|mcg|g|ml|units?|milligrams?|micrograms?|grams?"
                         r"|milliliters?)\b", re.I)


def numwords_to_digits(text):
    """Dictation words -> digits: five-hundred milligram -> 500 milligram."""
    def rep(m):
        toks = re.split(r"[ -]", m.group(0).lower())
        toks = [t for t in toks if t]
        if not any(t in _ONES or t in _TENS or t == "hundred" for t in toks):
            return m.group(0)
        # Two consecutive digits followed by a unit of time or count is a
        # spoken range, not a two-digit number.
        if (len(toks) == 2 and all(t in _ONES and _ONES[t] <= 9 for t in toks)
                and _ONES[toks[1]] == _ONES[toks[0]] + 1
                and _RANGE_TAIL.match(text[m.end():])):
            return m.group(0)
        v = _parse_numwords(toks)
        return str(v) if v > 0 else m.group(0)
    return _SPOKEN_POINT.sub(r"\1.\2", _NUMW_RUN.sub(rep, text))
