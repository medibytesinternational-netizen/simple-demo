"""Typed failures. A run either produces real output or raises one of these."""


class PipelineError(Exception):
    """Base for every failure the pipeline reports to a caller."""


class AudioRejected(PipelineError, ValueError):
    """The input is not usable speech audio (empty, silent, too long, undecodable).

    The message starts with an HTTP-style code (413, 422) the API maps to a status.
    """


class SpeechModelUnavailable(PipelineError):
    """MedASR or the small-int8 second pass could not be loaded or run."""


class LLMError(PipelineError, ValueError):
    """Any gpt-4.1 failure. A ValueError, so the LLM stages' "leave the row as
    the matcher made it" path catches it and the stage is reported as degraded."""


class LLMUnavailable(LLMError):
    """gpt-4.1 cannot be used at all (no API key, unreachable, auth refused).

    A stage that sees this stops calling for the rest of the clip.
    """


class LLMCallFailed(LLMError):
    """One call failed (HTTP error, malformed reply); the next may succeed."""


class LLMTimeout(LLMCallFailed):
    """The server answered but did not finish within the stage's budget."""


class ReplayMiss(LookupError):
    """A replayed LLM was asked a prompt it never recorded (tests only)."""
