"""Derived facts: flattens an applicant into the name/value bag the evaluator matches against."""

from datetime import date
from typing import Any

from agent.constants import HIT_FACTS, SHELL_SIGNAL_RECENT_FORMATION
from agent.schemas import Applicant, BrainSettings, ExtractionResult, Facts, Hit


def formation_age_days(incorporation_date: date | None, as_of: date) -> int | None:
    """Company age at the Brain's fixed evaluation date, never at now()."""
    if incorporation_date is None:
        return None
    return (as_of - incorporation_date).days


def formation_is_recent(facts: Facts, settings: BrainSettings) -> bool:
    """Whether the company is younger than the window the policy declares."""
    if facts.formation_age_days is None:
        return False
    return facts.formation_age_days < settings.formation_recent_days


def missing_documents(facts: Facts, settings: BrainSettings) -> list[str]:
    """Required documents whose satisfying fact is false, in policy order."""
    proven = {
        "has_incorporation_doc": facts.has_incorporation_doc,
        "has_ubo_list": facts.has_ubo_list,
        "formation_is_recent": formation_is_recent(facts, settings),
    }
    return [doc.id for doc in settings.required_documents if not proven.get(doc.satisfied_by, False)]


def shell_signals(facts: Facts, settings: BrainSettings) -> list[str]:
    """Signals from extraction, plus the date-window one the policy defines itself."""
    signals = list(facts.shell_signals)
    if formation_is_recent(facts, settings) and SHELL_SIGNAL_RECENT_FORMATION not in signals:
        signals.append(SHELL_SIGNAL_RECENT_FORMATION)
    return signals


def from_packet(packet: Applicant, extraction: ExtractionResult, settings: BrainSettings) -> Facts:
    """Everything the evaluator reads except `hits`, which spec 003 fills; the packet is read here and nowhere else."""
    return Facts(
        mcc=packet.business.mcc,
        has_incorporation_doc=extraction.has_incorporation_doc,
        has_ubo_list=len(packet.ubos) > 0,
        shell_signals=list(extraction.shell_signals),
        formation_age_days=formation_age_days(packet.business.incorporation_date, settings.as_of_date),
        injection_suspected=extraction.injection_suspected,
    )


def applicant_bag(facts: Facts, settings: BrainSettings) -> dict[str, Any]:
    """The applicant-scope facts, derived values included."""
    missing = missing_documents(facts, settings)
    signals = shell_signals(facts, settings)
    return {
        "mcc": facts.mcc,
        "has_incorporation_doc": facts.has_incorporation_doc,
        "has_ubo_list": facts.has_ubo_list,
        "missing_docs": missing,
        "missing_docs_count": len(missing),
        "shell_signals": signals,
        "shell_signal_count": len(signals),
        "formation_age_days": facts.formation_age_days,
        "formation_is_recent": formation_is_recent(facts, settings),
        "location_validation": facts.location_validation,
        "injection_suspected": facts.injection_suspected,
    }


def hit_bag(hit: Hit) -> dict[str, Any]:
    """The per-hit facts, merged over the applicant bag by an each_hit rule."""
    return {name: getattr(hit, name) for name in HIT_FACTS}
