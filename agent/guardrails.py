"""Assertions that hold whatever the Brain says, so a bad policy edit fails loudly instead of quietly."""

from agent.schemas import Facts, Verdict


class GuardrailViolated(RuntimeError):
    """A verdict the system refuses to return regardless of which rules produced it."""


def assert_no_auto_clear(facts: Facts, verdict: Verdict) -> None:
    """Never auto-CLEAR a watchlist hit; this must not depend on the rule table being written correctly."""
    if facts.hits and verdict.decision == "CLEAR":
        entries = ", ".join(sorted({hit.entry_id for hit in facts.hits}))
        raise GuardrailViolated(f"CLEAR returned with {len(facts.hits)} watchlist hit(s): {entries}")
