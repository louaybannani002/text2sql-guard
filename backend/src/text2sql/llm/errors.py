"""Errors raised by the LLM layer. Callers only ever need to catch ``LLMError``."""

from collections.abc import Sequence
from typing import Any

from text2sql.llm.types import Usage, UsageRole


class LLMError(Exception):
    """Base class for every failure of an LLM call."""

    def __init__(self, message: str, *, role: UsageRole, model: str) -> None:
        """Record which role and concrete model failed."""
        super().__init__(message)
        self.role = role
        self.model = model


class LLMTimeoutError(LLMError):
    """The provider did not answer within the configured timeout. Not retried."""


class LLMProviderError(LLMError):
    """The provider failed: non-retryable error, or retryable errors on every attempt."""

    def __init__(
        self,
        message: str,
        *,
        role: UsageRole,
        model: str,
        attempts: int,
        status_code: int | None,
    ) -> None:
        """Also record how many attempts were made and the last HTTP status."""
        super().__init__(message, role=role, model=model)
        self.attempts = attempts
        self.status_code = status_code


class LLMOutputValidationError(LLMError):
    """The model answered, but its output does not match the requested Pydantic model.

    ``raw_output`` and ``errors`` are attached for debugging and repair prompts. They are
    deliberately kept out of ``str(error)``, since they may contain user or business data.
    """

    def __init__(  # noqa: PLR0913 - every field is needed to act on the error
        self,
        message: str,
        *,
        role: UsageRole,
        model: str,
        raw_output: str,
        errors: Sequence[Any],
        usage: Usage,
        refusal: str | None = None,
    ) -> None:
        """Attach the raw output, the validation errors and the usage already spent."""
        super().__init__(message, role=role, model=model)
        self.raw_output = raw_output
        self.errors = list(errors)
        self.usage = usage  # the tokens were spent even though the output is unusable
        self.refusal = refusal
