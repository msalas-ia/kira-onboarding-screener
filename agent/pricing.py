"""What a call cost. Rates are per million tokens and priced apart, because the cached rate is the point of the prefix."""

from dataclasses import dataclass

from agent.schemas import Usage

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Rates:
    """US dollars per million tokens, by how the token was counted."""

    input: float
    output: float
    cache_read: float
    cache_write: float


# Not Brain data: the price of a token is not policy, and a rate card change must
# not move brain_hash. These reproduce the 60-call sweep recorded in DESIGN.md
# ($0.5626) to within a hundredth of a cent, which is how they were confirmed.
RATES: dict[str, Rates] = {
    "claude-opus-5": Rates(input=5.0, output=25.0, cache_read=0.50, cache_write=6.25),
}

DEFAULT = RATES["claude-opus-5"]


def cost_of(usage: Usage, model: str) -> float:
    """Dollars for one call; an unpriced model falls back rather than reporting free, which is the unsafe direction."""
    rates = RATES.get(model, DEFAULT)
    total = (
        usage.input_tokens * rates.input
        + usage.output_tokens * rates.output
        + usage.cache_read_input_tokens * rates.cache_read
        + usage.cache_creation_input_tokens * rates.cache_write
    )
    return round(total / PER_MILLION, 6)


def total_usage(*parts: Usage | None) -> Usage:
    """Sum the calls a run made, so the run total is arithmetic over its steps rather than a second measurement."""
    counted = [part for part in parts if part is not None]
    return Usage(
        input_tokens=sum(part.input_tokens for part in counted),
        output_tokens=sum(part.output_tokens for part in counted),
        cache_read_input_tokens=sum(part.cache_read_input_tokens for part in counted),
        cache_creation_input_tokens=sum(part.cache_creation_input_tokens for part in counted),
    )
