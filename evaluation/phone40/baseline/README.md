# Phone40 C1 baseline (frozen evidence)

Recorded on 11 October 2026 with the code that preceded `medibytes` (the old
`base_pipeline`), run as arm C1:

    --preset context-repair --model medasr --llm-url https://api.openai.com/v1 --llm-model gpt-4.1

It scored 212/229 facts, with all 229 facts identical to the original Phone40 C1 run
(paired McNemar: 0 / 0).

| Path | What it is |
|---|---|
| `asr_cache/` | MedASR and small-int8 transcripts of each clip, keyed by the SHA-256 of the cleaned WAV |
| `trace.jsonl` | Every gpt-4.1 term-validation and context-repair prompt and reply (24 calls) |
| `trace_discharge.jsonl` | The gpt-4.1 discharge-note prompt and reply for each clip (40 calls) |
| `golden/<clip>/` | The old code's `transcript.json`, `entities.json`, `verify.json`, and the discharge note (`discharge.json`) |

The discharge notes were produced by the old chain (`extract_discharge` → `gate` →
`canonicalize` → `merge` → `stamp`) with gpt-4.1. One change was needed: the
output limit was raised from 1,024 to 4,096 tokens. At 1,024 the note was cut off
mid-JSON on every attempt.

`tests/test_parity_phone40.py` replays these through `medibytes`. It requires every
output to match field for field.
