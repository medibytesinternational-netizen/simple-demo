"""Composition root: the only place the concrete pipeline is assembled."""
from __future__ import annotations

from .asr.medasr import MedASRRecognizer
from .asr.whisper import WhisperSecondPass
from .config import Settings
from .errors import LLMUnavailable
from .extraction.vocabulary import load_drug_list
from .llm.openai_client import OpenAIClient
from .pipeline import Pipeline
from .preprocessing.preprocessor import Preprocessor
from .reference import drug_reference
from .reference.english import is_ordinary_word


def check_assets() -> None:
    """Load the three vocabularies now, so a broken install fails at startup."""
    drug_reference.load()
    load_drug_list()
    is_ordinary_word("warmup")


def build_pipeline(settings: Settings) -> Pipeline:
    """MedASR -> small-int8 second pass -> fuzzy matcher -> gpt-4.1.

    gpt-4.1 is part of the measured combination, so a missing API key is a
    startup error rather than a quietly different pipeline.
    """
    llm = OpenAIClient(settings.openai_api_key, trace=settings.llm_trace)
    ok, why = llm.available()
    if not ok:
        raise LLMUnavailable(f"{why} - put it in .env or the environment")
    check_assets()
    return Pipeline(preprocessor=Preprocessor(), first_pass=MedASRRecognizer(),
                    second_pass=WhisperSecondPass(), llm=llm)
