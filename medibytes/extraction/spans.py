"""Character spans of each entity inside the normalised transcript."""
import re


def _annotate_entity_span(entity, normalized_en):
    anchor = next(
        (entity.get(key).strip() for key in ("name", "text", "span")
         if isinstance(entity.get(key), str) and entity.get(key).strip()),
        None,
    )
    matches = list(re.finditer(re.escape(anchor), normalized_en, re.I)) if anchor else []
    if len(matches) == 1:
        entity.update(start_char=matches[0].start(), end_char=matches[0].end(),
                      span_status="exact")
    else:
        entity.update(start_char=-1, end_char=-1,
                      span_status="ambiguous" if matches else "not_found")
    return entity


def annotate_entity_spans(entities, normalized_en):
    for group in ("drugs", "symptoms", "vitals", "allergies", "negations"):
        for entity in entities.get(group, []):
            if isinstance(entity, dict):
                _annotate_entity_span(entity, normalized_en)
    for group in ("diagnosis", "followup"):
        entity = entities.get(group)
        if isinstance(entity, dict) and entity:
            _annotate_entity_span(entity, normalized_en)
    return entities
