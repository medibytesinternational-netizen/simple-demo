"""Allergy mentions (both word orders) and the allergen-is-not-an-order join."""
import re

from ..reference import drug_reference
from .vocabulary import load_drug_list

# Generic allergy mention: "allergy to <word>" (candidate, YELLOW; negated flag from NEG_PAT)
ALLERGY_CTX = re.compile(
    r"allerg(?:y|ies|ic)\s+(?:to|of|from)\s+(?:a\s+|an\s+|the\s+)?(?P<drug>[A-Za-z]+)", re.I)


# The other half of the grammar: the drug comes FIRST and the word "allergy"
# follows it - "document amoxicillin as a suspected drug allergy", "she has a
# penicillin allergy". Without this the only allergies the record can ever
# carry are negated ones, because `ALLERGY_CTX` is the sole producer and the
# block that runs it is entered only on a negated sentence.
ALLERGY_ASSERT = re.compile(
    r"\b(?P<drug>[A-Za-z][A-Za-z-]{2,})\s+"
    r"(?:as\s+(?:an?\s+|the\s+)?)?"
    r"(?:suspected\s+|possible\s+|probable\s+|confirmed\s+|known\s+|severe\s+)*"
    r"(?:drug\s+|medication\s+|food\s+)?allerg(?:y|ies)\b",
    re.I,
)


# Words that precede "<x> allergy" without being the substance.
ALLERGY_STOPWORDS = {"a", "an", "the", "any", "no", "this", "that", "his", "her",
                     "their", "my", "your", "its", "drug", "medication", "food",
                     "suspected", "possible", "probable", "confirmed", "known",
                     "severe", "previous", "other", "and", "or", "with", "of",
                     # quantifiers and bare nouns: "allergic to a lot of things"
                     "nothing", "anything", "something", "everything", "lot",
                     "lots", "many", "several", "few", "things", "stuff",
                     "medications", "medicines", "drugs", "foods", "antibiotics"}


def allergy_spans(sentence):
    """(start, end) of every substance an allergy pattern actually captures.

    A proximity window was tried first and was too blunt: it dropped the insulin
    from "he takes insulin and has no known drug allergies". Only a word the
    allergy rules really claimed is withheld from the drug table.
    """
    return [(m.start("drug"), m.end("drug"))
            for pattern in (ALLERGY_CTX, ALLERGY_ASSERT)
            for m in pattern.finditer(sentence)]


def reconcile_allergens(ent):
    """A drug the dictation asserts an allergy to is never an active order.

    Extraction reads sentence by sentence, so "She was started on amoxicillin
    this morning" charts an order while "document amoxicillin as a suspected
    drug allergy" separately charts an asserted allergy, and nothing joins the
    two: the record then lists the allergen as something to give. The rule here
    is the join. A drug whose canonical name is among the *asserted* allergies
    (a denied one - "no penicillin allergy" - blocks nothing) becomes a
    NOT GIVEN row, flagged `allergen`, forced RED so a human sees why, and
    never above the confidence of an unverified row. Idempotent, and run again
    after the second decoder's rows are unioned in, since that can re-add one.

    Exact canonical-name match only. Cross-reactivity (a penicillin allergy and
    an amoxicillin order) is a clinical judgement this layer does not make.
    """
    canon = {}
    for d in load_drug_list():
        for a in [d["name"]] + d.get("aliases", []):
            canon[a.lower()] = d["name"].lower()

    def name(s):
        s = str(s or "").strip().lower()
        if s in canon:
            return canon[s]
        # the national pack's INN bridge: amoxycillin -> amoxicillin (substances only)
        hit = drug_reference.lookup(s, brands=False)
        return hit["name"].lower() if hit else s

    allergens = {name(a.get("text")) for a in ent.get("allergies", [])
                 if a.get("text") and not a.get("negated")}
    if not allergens:
        return ent
    for row in ent.get("drugs", []):
        if row.get("allergen") or name(row.get("name")) not in allergens:
            continue
        row["negated"] = True
        row["allergen"] = True
        row["color"] = "RED"
        row["confidence"] = min(float(row.get("confidence", 0.7) or 0.7), 0.7)
        row["note"] = ("ALLERGEN - an allergy to this drug is asserted in the dictation; "
                       "not an active order, physician must confirm")
    return ent
