"""Corroboration as the policy defines it: a field comparison, one agreeing comparable pair is enough. (D-003)"""

from agent.schemas import ScreeningTarget

Basis = tuple[bool, str]


def corroborate(target: ScreeningTarget, match: dict) -> Basis:
    """DOB outranks country when both agree, because the trace should cite the stronger claim."""
    if _agrees(_dob(target), match.get("dob")):
        return True, "dob"
    if _agrees(_country(target.country), _country(match.get("country"))):
        return True, "country"
    return False, "none"


def _agrees(subject: str | None, entry: str | None) -> bool:
    """A pair that is not comparable never corroborates: missing identity is not confirmed identity."""
    return bool(subject) and bool(entry) and subject == entry


def _dob(target: ScreeningTarget) -> str | None:
    return target.dob.isoformat() if target.dob else None


def _country(value: str | None) -> str | None:
    return value.strip().upper() if value else None
