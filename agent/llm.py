"""The Anthropic client, behind a protocol small enough that a test can implement it in five lines."""

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from agent.schemas import Usage

Parsed = TypeVar("Parsed", bound=BaseModel)

# max_tokens bounds thinking and response text together, so it sits well above what the schema needs.
DEFAULT_MAX_TOKENS = 16000


class ModelUnavailable(RuntimeError):
    """The model could not be reached, or answered with something unusable."""


@dataclass(frozen=True)
class Completion:
    """One structured response: the validated object, and what it cost."""

    parsed: Any
    usage: Usage


class StructuredClient(Protocol):
    """What extraction needs from a model; anything satisfying this can stand in for the SDK."""

    def parse(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[Parsed],
    ) -> Completion:
        """Return an instance of `output_format`, or raise `ModelUnavailable`."""
        ...


class AnthropicClient:
    """The real client; constructing it never fails, so /health stays free of the API as spec 000 requires."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        # Left unset rather than passed empty, so the SDK's own resolution order still applies.
        credentials = {"api_key": api_key} if api_key else {}
        self._client = anthropic.Anthropic(timeout=timeout, max_retries=max_retries, **credentials)

    def parse(
        self,
        *,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[Parsed],
    ) -> Completion:
        """One structured call. Transport failures are retried by the SDK; anything left over raises."""
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                output_format=output_format,
            )
        except anthropic.APIError as exc:
            raise ModelUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except TypeError as exc:
            # No resolvable credential raises TypeError, not APIError, and an unset key is a real deployment state.
            raise ModelUnavailable(str(exc)) from exc

        if response.stop_reason == "refusal":
            raise ModelUnavailable("the model declined to answer")
        if response.stop_reason == "max_tokens":
            raise ModelUnavailable(f"response truncated at max_tokens={self.max_tokens}")
        if response.parsed_output is None:
            raise ModelUnavailable("the response carried no parsed output")

        return Completion(parsed=response.parsed_output, usage=usage_of(response))


def usage_of(response: Any) -> Usage:
    """Token accounting, tolerant of the fields a given response happens to carry."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
