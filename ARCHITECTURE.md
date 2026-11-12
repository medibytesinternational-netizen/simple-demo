# Architecture

## The one pipeline

| # | Stage | Module | What happens |
|---|---|---|---|
| 1 | Preprocess | `preprocessing/` | Decode (ffmpeg for non-WAV) → mono → anti-aliased resample to 16 kHz → reject digital silence → level-normalise (0.1 RMS, 0.98 peak ceiling) → reject audio that is >95% silent → write PCM16 → estimate SNR. No denoiser: on Phone40 no denoising gate beat `none`. The output is byte-for-byte deterministic. |
| 2 | MedASR | `asr/medasr.py` | `google/medasr` via transformers, 20 s chunks with 2 s stride. The model's dictation markup (`{period}`, `[SECTION]`) is turned into punctuation. |
| 3 | Second pass | `asr/whisper.py` | faster-whisper `small`, int8 on CPU, greedy decoding. It hears different words from MedASR. |
| 4 | Fuzzy match | `extraction/` | Normalise → regex extraction with negation scope → fuzzy drug matching (curated mini list first, then the India national reference) → add rows the second pass heard and MedASR missed → allergen reconcile. |
| 5 | gpt-4.1 review | `llm/term_validation.py`, `llm/context_repair.py` | gpt-4.1 judges each fuzzy-matched drug against its closed shortlist, and repairs misheard drug names from sentence context. Strict JSON; confidence must be ≥ 0.85. These rows never rise above YELLOW (validated) or RED (repaired). |
| 6 | Verify | `verify.py` | Deterministic checks: proof sentence is verbatim, numbers are present as digits, dose and unit are plausible, polarity is preserved. |
| 7 | Discharge note | `llm/discharge.py` | gpt-4.1 writes the six sections. Then the authenticity gate runs, verified facts own their entities, every verified fact is pre-filled once, and the note is validated against `schemas/discharge.schema.json`. |

Every threshold and model setting is held in `config.C1`, using the values the evaluation measured. Each module reads its values from there, and the comments next to them explain why each value was chosen.

## Design rules

- **One combination, no switches.** The code has no presets, no model or denoiser flags, and no provider choice. `Settings` holds only secrets, paths and ports.
- **Dependency inversion.** `Pipeline` depends only on the protocols in `ports.py` (`AudioPreprocessor`, `SpeechRecognizer`, `LLMClient`). `factory.build_pipeline` is the composition root, and `tests/test_import_graph.py` enforces that only it (and the API) wires concrete classes.
- **No silent fallbacks.** If MedASR fails, the run fails with a typed error from `errors.py`. There is no mock transcript and no substitute model. A missing drug reference also raises. A missing API key stops startup.
- **Degraded is visible.** If the second pass or a gpt-4.1 call fails, the affected rows stay exactly as the deterministic stages produced them. The stage is reported as `degraded` with the reason, in the API and in the UI.
- **Provenance travels with every row.** Each row carries the heard token, the matcher's pick, the candidate shortlist, the gpt-4.1 verdict, and its source sentence. Every discharge-note item carries a verbatim proof sentence and a verification status.

## Modules

```
medibytes/
  config.py         C1 (frozen measured values) and Settings (environment)
  domain.py         StageName, StageState, StageEvent, ClipResult
  errors.py         AudioRejected, SpeechModelUnavailable, LLMUnavailable, LLMCallFailed, LLMTimeout
  ports.py          the protocols Pipeline depends on
  pipeline.py       the seven stages in order, with progress events
  factory.py        composition root
  output.py         writes the JSON files and report.md for one clip
  cli.py            python -m medibytes
  preprocessing/    audio.py (signal primitives), preprocessor.py (stage 1)
  asr/              medasr.py, whisper.py
  extraction/       numerals, normalize, vitals, negation, vocabulary, drug_matching,
                    allergens, spans, entities, second_pass
  reference/        drug_reference.py (India CDCI pack), english.py, assets/
  llm/              openai_client.py, replay.py, json_reply.py,
                    term_validation.py, context_repair.py, discharge.py
  verify.py
  schemas/          entities.schema.json, discharge.schema.json
  api/              app.py (FastAPI), jobs.py (single worker, job.json on disk), models.py
frontend/           Integrated React UI: upload, live stage stepper, discharge note, chart with
                    provenance, transcript spans, JSON, audio
evaluation/phone40/ scoring.py, score.py, replay.py, gold.json, split.json, audio/, baseline/
```

## API

| Method | Path | Result |
|---|---|---|
| GET | `/api/health` | Pipeline name, gpt-4.1 readiness, job counts |
| POST | `/api/jobs` | Multipart `file` → 202 `{job_id, status, status_url}`. Errors: 400 empty, 413 too large, 415 unsupported type, 503 no API key |
| GET | `/api/jobs` | Recent jobs |
| GET | `/api/jobs/{id}` | Status, the seven stages, and when done: `transcript`, `entities`, `verify`, `discharge`, `audio`, `files` |
| GET | `/api/jobs/{id}/files/{name}` | `input.*`, `cleaned.wav`, `discharge.json`, `entities.json`, `verify.json`, `transcript.json`, `clean_meta.json`, `report.md` |

The response shapes are defined twice, and the two must be kept in step: `medibytes/api/models.py` and `web/src/api/types.ts`.

## Known limits (from the Phone40 report)

These are kept unchanged so that the pipeline still matches the 212/229 measurement. Each fix should come as its own change with a re-score.

- Negation reads to the end of the sentence, so a run-on sentence such as "denies …, no known drug allergy, ciprofloxacin 500 mg" marks the drug as not given.
- "as needed" is not a context-repair cue word, and doseless mentions need a 0.84 spelling score, so "Parasitamol as needed" is missed.
- Combination names such as "amoxicillin clavulanate" are only partly matched. Substances with no dispensing data (for example tiotropium) produce no row.
- The discharge note was not part of the measured arm. Its items are gated against the transcript, so a garbled transcript sentence can still appear in the note, marked "needs review". The note can also repeat a symptom that was said more than once.
