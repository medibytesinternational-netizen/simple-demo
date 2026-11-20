"""MediBytes: a doctor's dictation in, a 6-section discharge note out.

One pipeline, measured as C1 on the Phone40 set (92.6% of chart facts):
audio -> preprocess -> MedASR -> small-int8 second pass -> fuzzy drug matcher
-> gpt-4.1 (term validation, context repair) -> verify -> gpt-4.1 discharge note.
See `config.py` for every value it runs with and `pipeline.py` for the order.
"""
