"""Negation scope for symptoms, allergies and drug orders.

Sentence-level for symptoms; for drugs and allergies the scope runs from the
last contrast marker (and, for drugs, the last fresh order verb) to the mention.
"""
import re

NEG_PAT = re.compile(r"\b(no|not|denies|denied|denying|without|never|neither|nor|negative for|no known|don't|doesn't|aren't|isn't|wasn't|weren't|can't|cannot)\b", re.I)


# A contrast marker ends a negation's reach: "does not have asthma BUT has a
# penicillin allergy" asserts the allergy. A comma does not - "no history of
# asthma, diabetes, or penicillin allergy" denies all three.
_CONTRAST = re.compile(r"\b(?:but|however|although|though|except|whereas)\b|;", re.I)


def sentence_negated(sentence):
    return bool(NEG_PAT.search(sentence))


def negated_before(prefix):
    """Is the substance at the end of `prefix` denied by something before it?

    Sentence-level negation is the wrong test for an allergy. "Document X as a
    suspected allergy so that it is NOT given again" asserts; "she does NOT have
    asthma BUT has a penicillin allergy" asserts; "NO history of asthma,
    diabetes, or penicillin allergy" denies. So the scope runs from the last
    contrast marker to the substance, and commas do not break it.
    """
    markers = list(_CONTRAST.finditer(prefix))
    return sentence_negated(prefix[markers[-1].end():] if markers else prefix)


# An imperative verb starts a new order, and that ends the previous clause's
# negation.  `_CONTRAST` deliberately lets commas through, because "no history
# of asthma, diabetes, or penicillin allergy" denies all three - but a denial
# followed by an order is the common ward sentence, and treating the boundary
# as transparent cancels a real prescription.  "Stop amoxicillin and start
# azithromycin" is the case that matters most: a drug switch, where getting
# this wrong drops the drug the patient is now on.
_RX_VERB = re.compile(
    r"\b(?:give|giving|given|gave|start|started|starting|begin|begun|continue"
    r"|continued|continuing|prescribe|prescribed|add|added|administer"
    r"|administered|take|takes|taking|switch(?:ed)?\s+to|change(?:d)?\s+to)\b",
    re.I)


# Words that may sit between a negation and the verb it governs. "do not give"
# and "not to give" are negated orders; "no fever give" is a denial followed by
# one, and the noun in between is what tells them apart.
_AUX_ONLY = re.compile(r"^[\s,]*(?:(?:do|does|did|to|be|been|being|is|are|was"
                       r"|were|should|shall|must|will|would|can|could|may"
                       r"|please|kindly)[\s,]+)*$", re.I)


# Stopping a drug without a negation particle. `NEG_PAT` has no "stop", so
# "stop metformin 500 mg" charted as an active GREEN order.
_DISCONTINUE = re.compile(
    r"\b(?:stop|stopped|stopping|avoid|avoided|withhold|withheld|hold|held"
    r"|discontinue|discontinued|omit|omitted|cease|ceased"
    r"|refus(?:e|ed|ing)|declin(?:e|ed|ing))\b", re.I)


def _order_scope(prefix):
    """`prefix` trimmed to the current order, i.e. after the last fresh verb.

    A verb only starts a *fresh* order when a negation is not governing it, so
    the scan skips any verb whose negation sits immediately before it with
    nothing but an auxiliary between.  That keeps "do not give X" inside the
    negation while letting "...no fever, give X" out of it.
    """
    cut = 0
    for m in _RX_VERB.finditer(prefix):
        # Either kind of stop word can govern the verb.  Checking only
        # `NEG_PAT` left the commonest phrasing of all wide open: in "stop
        # taking metformin 500 mg" the verb is `taking`, no negation particle
        # precedes it, so the scope reset past "stop" and the row charted as an
        # active GREEN order.
        before = prefix[:m.start()]
        stops = list(NEG_PAT.finditer(before)) + list(_DISCONTINUE.finditer(before))
        last = max((x.end() for x in stops), default=None)
        if last is None or not _AUX_ONLY.match(prefix[last:m.start()]):
            cut = m.end()
    return prefix[cut:]


def drug_negated(prefix):
    """Is a drug at the end of `prefix` prohibited, stopped or refused?

    Two sources, both scoped the same way - to the current order, and then to
    the text after the last contrast marker.  Scoping them alike is the point:
    an earlier draft ran the discontinuation check over the whole prefix while
    the negation check respected contrast, so "stopped metformin but continue
    insulin 10 U" marked the insulin stopped.
    """
    scope = _order_scope(prefix)
    markers = list(_CONTRAST.finditer(scope))
    if markers:
        scope = scope[markers[-1].end():]
    return sentence_negated(scope) or bool(_DISCONTINUE.search(scope))
