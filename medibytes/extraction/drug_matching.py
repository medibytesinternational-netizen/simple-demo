"""Fuzzy drug matching: mini list first, the national India reference behind it.

Every threshold here is bound from `config.C1.matcher`; the comments explain why
each value was chosen.
"""
import difflib
import re

from ..config import C1
from ..reference import drug_reference

# `DRUG_CTX`'s name group is a single token, so a two-word medicine reaches
# the matcher as its last word only: "clavulanic acid 125 mg" offers `acid`,
# and "folic acid 5 mg" offers `acid` and is dropped outright. Both are orders
# whose dose was dictated, and what the chart showed was either no row at all
# or a row saying "no dose dictated" - a statement about the recording that is
# simply false.
#
# The name is grown leftwards after the match rather than widened in the
# pattern. A greedy multi-token name group would make the common cases worse,
# offering "was 200 mg" and "and paracetamol 500 mg" as drugs called `was` and
# `and paracetamol`. So an extension is accepted only when the joined words
# are themselves a name the vocabulary resolves - the mini list, or an exact
# substance in the national pack, with the pack's brand and stopword gates
# applied. That is the same bar `reference_only_row` uses downstream, so a
# longer match can never invent a drug: it can only recognise one that would
# equally have been accepted had it been dictated as a single word.
MAX_NAME_WORDS = 3


_WORD_BEFORE = re.compile(r"([A-Za-z]+)\s+$")


# The word immediately before a multi-word name, however it is joined -
# "amoxicillin and clavulanic acid", "amoxicillin clavulanic acid",
# "amoxicillin-clavulanic acid". When that word is itself a drug, the 625 mg
# that follows is the combination's total strength, not this component's dose.
_COMBINATION_JOIN = re.compile(
    r"([A-Za-z]+)\s*(?:[-/,+]\s*)?(?:(?:and|with|plus)\s+)?$", re.I)


def _name_resolves(name, drugs_known, alias_to_canonical):
    """True when `name` is a medicine this pipeline already knows by name."""
    if name in drugs_known or name in alias_to_canonical:
        return True
    return bool(drug_reference.lookup(
        name, block=drug_reference.STOPWORDS, brands=False))


def extend_name(clause, start, end, drugs_known, alias_to_canonical):
    """(name, start, extended) - the longest resolvable name ending at `end`.

    Longest-first, so "sodium valproate" wins over "valproate" where both
    resolve. Falls back to the single token the pattern matched, leaving every
    one-word case exactly as it was.
    """
    starts: list[int] = []
    at = start
    while len(starts) < MAX_NAME_WORDS - 1:
        m = _WORD_BEFORE.search(clause, 0, at)
        if not m:
            break
        at = m.start(1)
        starts.append(at)
    for s in reversed(starts):
        cand = " ".join(clause[s:end].split()).lower()
        if _name_resolves(cand, drugs_known, alias_to_canonical):
            return cand, s, True
    return clause[start:end].lower(), start, False


def combination_partner(clause, start, drugs_known, alias_to_canonical):
    """The drug this one is conjoined to, when a shared dose follows both."""
    m = _COMBINATION_JOIN.search(clause, 0, start)
    if not m:
        return None
    other = m.group(1).lower()
    return other if _name_resolves(other, drugs_known, alias_to_canonical) else None


def drug_name_pattern(alias_to_canonical):
    """One word-boundary alternation over every known name and alias."""
    names = sorted(alias_to_canonical, key=len, reverse=True)
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in names), re.I)


def fuzzy_candidates(token, drugs_known, alias_to_canonical, floor, limit=C1.matcher.mini_limit,
                     band=C1.matcher.mini_band):
    """Every canonical drug a misheard token could plausibly be, best first.

    The matcher used to keep only difflib's winner, which threw away exactly the
    information a validator needs: whether the runner-up was a near tie.
    Sound-alike pairs are the dangerous case, so candidates within ``band`` of
    the best score are kept even when they sit under ``floor`` - a tie that the
    validator must see rather than a match it should act on.  Ordering is
    ``(-score, name)`` so it does not depend on set iteration order, which the
    previous loop did.
    """
    vocab = sorted(set(drugs_known) | set(alias_to_canonical))
    scored = sorted(((difflib.SequenceMatcher(None, token, known).ratio(), known)
                     for known in vocab), key=lambda pair: (-pair[0], pair[1]))
    if not scored or scored[0][0] < floor:
        return []
    cutoff = scored[0][0] - band  # deliberately not clamped to `floor`
    out, seen = [], set()
    for score, known in scored:
        if score < cutoff:
            break
        name = alias_to_canonical.get(known, known)
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "score": round(score, 3), "matched_alias": known})
        if len(out) == limit:
            break
    return out


# How far a national-reference name must out-score the best curated mini-list
# candidate before it is allowed to lead the row.  A guard against cheap
# high scores in a 74k-name table, not a measured threshold: it sits above the
# 0.05 that made `oxacillin` outrank `amoxicillin` and below the 0.11 that
# makes `hydroxyzine` the clear answer over `levothyroxine`.
REFERENCE_MARGIN = C1.matcher.reference_margin


# "glucose 180 mg/dL" is a lab result, not a prescription, but `DRUG_CTX`'s
# `\b` after the unit matches happily before the slash and puts the analyte in
# the drug-name slot.  The mini list used to drop those rows by not recognising
# `glucose`; the national reference does recognise it, and would file four
# false medicines off one line of bloodwork.  A dose is an amount, a lab value
# is a concentration, and `per decilitre` or `per litre` is what tells them
# apart - `mg/ml` and `mg/kg` stay, because those really are how drugs are
# ordered.
_LAB_DENOM = re.compile(r"\s*(?:/|per\s+)\s*(?:d[lL]\b|L\b|lit(?:re|er)s?\b"
                        r"|decilit(?:re|er)s?\b|cu\s*mm\b|mm3\b)")


def is_lab_concentration(text, match):
    """True when the matched `<word> <num> <unit>` is a lab value, not a dose."""
    return bool(_LAB_DENOM.match(text, match.end("unit")))


def demote_implausible(candidates, dose, unit):
    """Re-rank candidates the pack says this dose cannot belong to.

    Demoted rather than deleted: the pack's strength table is a record of what
    is marketed, not a statement of every dose a clinician may write, so a
    candidate it cannot account for drops to the back of the queue instead of
    vanishing.  The ordering is what reaches the chart, so moving the
    implausible ones down is enough to stop them leading a row, while the
    validator still sees them.
    """
    ruled = []
    for c in candidates:
        ref = c.get("reference") or {}
        rec = {"units": ref.get("units", []), "mass_mg": ref.get("mass_mg")}
        if (drug_reference.unit_fits(rec, unit) is False
                or drug_reference.dose_conflicts(rec, dose, unit)):
            c["dose_implausible"] = True
            ruled.append(c["name"])
    all_bad = bool(ruled) and len(ruled) == len(candidates)
    if not ruled or all_bad:
        # Nothing to demote, or everything is implausible - reordering a
        # uniformly doubtful shortlist would only hide that fact.
        return candidates, ruled, all_bad
    candidates = sorted(candidates, key=lambda c: (bool(c.get("dose_implausible")),))
    return candidates, ruled, False


def _ref_block(rec):
    """The pack's facts about one drug, as they travel on a candidate row.

    `mass_mg` is the pair the dose check reads, so it has to survive the trip:
    without it every candidate looks like one the pack has no opinion on, and
    the check silently passes everything.
    """
    return {"kind": rec["kind"], "name": rec["name"],
            "substances": rec.get("substances", []),
            "units": rec.get("units", []),
            "mass_mg": rec.get("mass_mg"),
            "forms": rec.get("forms", []),
            "strengths": rec.get("strengths", [])[:6]}


def reference_candidates(token, mini_candidates, drugs_known=frozenset()):
    """Merge the national drug reference into the mini-list's candidate set.

    The mini list is 33 medicines, so its top scorer is "the nearest of 33
    strings" - right for `asitromaisin`, wrong for `hydroxazine`, where the
    real drug is simply not in the list and `levothyroxine` is merely the
    closest thing that is.  The reference supplies the missing referent.

    The two matchers are not equally trustworthy and are not merged as equals.
    The mini list is curated: its aliases are mishearings someone observed and
    wrote down, and it is the vocabulary this project's gold data is written
    in.  The reference is raw string proximity over 74k names, where a
    near-perfect score is cheap - `moxacillin` scores 0.95 against `oxacillin`
    and 0.90 against the mini list's `amoxicillin`, and the higher number is
    the wrong antibiotic.  So a reference name takes the lead only when it
    beats the best mini-list candidate by `REFERENCE_MARGIN`, which
    `hydroxazine -> hydroxyzine` (0.91 against levothyroxine's 0.80) clears and
    `moxacillin -> oxacillin` does not.

    Losing that contest costs a candidate nothing but first place: it stays in
    the shortlist, so `term_validate` still sees both and can rule on which
    drug the sentence is about.  Scores are left as each matcher produced them
    so the tie rule still sees the real spread.
    """
    # Enrich the mini list's own candidates first. They are the ones most
    # likely to be wrong in the dangerous way - `levothyroxine` reached the
    # shortlist because it is the nearest of 33 strings - and without the
    # pack's units attached to them the unit check downstream has nothing to
    # test and silently passes everything.
    out = []
    for c in mini_candidates:
        rec = drug_reference.lookup(c["name"])
        out.append({**c, "source": "mini",
                    **({"reference": _ref_block(rec)} if rec else {})})
    # Keyed on substances as well as names so a bridged INN spelling cannot
    # arrive as a rival of the mini list's own entry for the same molecule -
    # two names for one drug would otherwise read as a tie.
    known = {c["name"].lower() for c in out}
    for c in out:
        known.update(x.lower() for x in (c.get("reference") or {}).get("substances", []))
    for rec in drug_reference.candidates(token):
        # A reference brand resolves to its generic where the mini list already
        # knows that generic, so `azee` does not arrive as a rival of
        # `azithromycin`.
        name = chart_name(rec["name"], drugs_known)
        for sub in rec.get("substances", []):
            if chart_name(sub, drugs_known) in known:
                name = chart_name(sub, drugs_known)
                break
        if name.lower() in known:
            continue
        known.add(name.lower())
        out.append({"name": name, "score": rec["score"],
                    "matched_alias": rec["matched_name"], "source": "reference",
                    "reference": _ref_block(rec)})
    # Rank mini-list candidates first among themselves, then let a reference
    # name jump the queue only on a decisive margin.
    mini_names = {c["name"].lower() for c in mini_candidates}
    best_mini = max((c["score"] for c in out if c["name"].lower() in mini_names),
                    default=None)

    def rank(c):
        from_mini = c["name"].lower() in mini_names
        if from_mini or best_mini is None:
            promoted = from_mini
        else:
            promoted = c["score"] >= best_mini + REFERENCE_MARGIN
        return (0 if promoted else 1, -c["score"], c["name"])

    out.sort(key=rank)
    return out[:C1.matcher.shortlist_limit]


def chart_name(name, drugs_known):
    """The spelling this project charts a pack name under.

    Two authorities, in order.  The mini list wins outright: it is this
    project's own vocabulary and its gold data is written in it, so a pack
    name it already carries is charted exactly as it carries it - `furosemide`
    stays `furosemide` and is not rewritten to `frusemide` on the strength of
    a synonym table.  Only for a drug the mini list has never heard of does
    the INN bridge decide, which is what keeps a `Crocin` tablet from charting
    as `acetaminophen`.
    """
    n = str(name or "").strip().lower()
    if n in drugs_known:
        return n
    return drug_reference.inn_name(n)


def reference_only_row(token, drugs_known=frozenset()):
    """An exact reference hit for a token the mini list has never heard of.

    The matcher used to drop these: no mini-list hit and no fuzzy match above
    the floor meant `continue`, and a real medicine dictated perfectly
    vanished from the chart because a 33-entry demo list did not contain it.
    A name the national pack lists exactly is a medicine, so the row is
    emitted - YELLOW rather than GREEN, because it reached the chart through
    a list this pipeline has not curated and nobody has reviewed the match.
    """
    # The exact-hit path gets the same gate as the fuzzy one. Without it a
    # word like `level` or `din` - both registered Indian brands - becomes a
    # medicine the moment a dose follows it.
    # Substances only. A brand name that happens to be an ordinary English
    # word must not become a medicine just because a dose follows it, and 161
    # of the English words in this project's own ASR output are brands.
    rec = drug_reference.lookup(token, block=drug_reference.STOPWORDS, brands=False)
    if not rec:
        return None
    # A brand resolves to its single generic; a multi-substance combination
    # keeps the brand name, since no one generic names it.
    subs = rec.get("substances", [])
    name = subs[0] if rec["kind"] == "brand" and len(subs) == 1 else rec["name"]
    # The pack is named in USAN and Indian charts are written in INN, so a
    # clinician who dictated `frusemide` must not read `furosemide` back off
    # the note. The spoken spelling is the one that goes on the chart; the
    # pack's own name is kept in the reference block for traceability.
    t = str(token).strip().lower()
    if t != name and drug_reference.load()["aliases"].get(t) == name:
        name = t
    return chart_name(name, drugs_known), rec


# A sentence that orders laboratory work is not prescribing. "Blood samples
# have been sent to check creatinine, urea, sodium and potassium levels" names
# four substances, three of which the national pack lists as real medicines -
# potassium and sodium are genuinely prescribed, just not here. Rather than
# block those names globally (which would lose a real potassium order), the
# sentence itself is read: a lab-request cue suppresses reference-only doseless
# rows within it. The curated mini list is exempt, because a name someone put
# in this project's own formulary is a deliberate choice.
LAB_REQUEST = re.compile(
    r"\b(?:sent|send|sending|collected|check(?:ing|ed)?|request(?:ed)?|advised"
    r"|ordered)\b[^.]{0,80}?\b(?:sample|samples|test|tests|level|levels|profile"
    r"|culture|screening|panel|analysis|function)\b"
    r"|\b(?:sample|samples|test|tests|level|levels|profile|culture|screening"
    r"|panel)\b[^.]{0,40}?\b(?:sent|send|collected|requested|advised)\b", re.I)


_LAB_VALUE_AFTER = re.compile(
    r"\s*(?:is|was|of|at)?\s*\d+(?:\.\d+)?\s*"
    r"(?:mg|mcg|g|mmol|meq|units?)\s*(?:/|per\s+)\s*"
    r"(?:d[lL]\b|L\b|lit(?:re|er)s?\b|decilit(?:re|er)s?\b)", re.I)


# Deliberately stricter than the dosed path's 0.55-0.6 floor. There, a wrong
# sound-alike is caught by the dose: the pack lists levothyroxine only in
# micrograms, so `25 mg` rules it out. A doseless mention has no such evidence,
# so the string has to carry the whole decision and the bar rises. Chosen on
# the 7 in-sample clips as the lowest floor at which the dangerous confusions
# disappear - at 0.80, `condition` matched `chondroitin` and `troponin` matched
# `tiopronin`; at 0.84 only `penicillin` -> `penicillin g` survives, and that
# one is an allergy mention the allergy spans already claim.
DOSELESS_FUZZY_FLOOR = C1.matcher.doseless_floor


def reference_doseless(sent, taken, alias_to_canonical, drugs_known):
    """Doseless drug mentions the curated list has never heard of.

    `known_name_pat` is built from a 36-entry formulary, so a ward handover
    saying "nebulisation with salbutamol and ipratropium bromide" records only
    the half that list happens to contain.  The national pack carries 2,542
    substances, 628 of them multi-word, and consulting it here is what makes
    the doseless path generalise instead of being extended by hand every time
    an unseen clip names a drug the list lacks.

    Longest match wins, so "sodium valproate" is not recorded as "sodium".
    """
    if LAB_REQUEST.search(sent):
        return []
    # Hyphenated compounds stay whole. Splitting them handed the matcher the
    # tail of a negated or class term: "keep anti-histamines ready" became a
    # `histamine` order, because `histamine` is a real substance in the pack.
    # Keeping the compound intact also preserves real hyphenated drug names
    # such as `co-amoxiclav`.
    words = [(m.group(0), m.start(), m.end())
             for m in re.finditer(r"[A-Za-z]+(?:-[A-Za-z]+)*", sent)]
    out: list[tuple] = []
    consumed: set[int] = set()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            if any(j in consumed for j in range(i, i + n)):
                continue
            join = " ".join(w[0] for w in words[i:i + n]).lower()
            if join in alias_to_canonical or join in drugs_known or join in taken:
                continue
            rec = drug_reference.lookup(join, block=drug_reference.STOPWORDS,
                                        brands=False)
            fuzzy = None
            if not rec and drug_reference.is_substance_name(join):
                continue  # spelled correctly: not a mishearing to repair (`dapagliflozin`)
            if not rec:
                # The sound-alike repair used to run only inside `DRUG_CTX`,
                # which needs name + number + unit. Ward handovers dictate
                # drugs without a dose - "she is currently taking amaldifine"
                # - so the one component built to fix a misheard drug name sat
                # idle on exactly the speech this product transcribes. Across
                # the 30-clip corpus, 0 of 24 held-out gold drugs carried a
                # dose at all.
                cands = drug_reference.candidates(join, floor=DOSELESS_FUZZY_FLOOR)
                if not cands:
                    continue
                fuzzy = cands
                rec = {"name": cands[0]["name"]}
            if not rec:
                continue
            # "calcium 9 mg/dL" is a result, not an order. The dosed path
            # already refuses a per-volume concentration; the doseless path
            # needs the same test, because the analyte is a real medicine and
            # cannot simply be blocked by name.
            if _LAB_VALUE_AFTER.match(sent, words[i + n - 1][2]):
                continue
            consumed.update(range(i, i + n))
            # `chart_name` so the row carries this project's own spelling
            # where it has one - the pack calls it `amoxycillin`, the mini
            # list and the gold data call it `amoxicillin`.
            out.append((chart_name(rec["name"], drugs_known),
                        words[i][1], words[i + n - 1][2], join, fuzzy))
    return out
