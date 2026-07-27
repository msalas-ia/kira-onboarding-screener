"""Every model in one place: the Brain as loaded data, the facts it reads, the verdict it produces."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Decision = Literal["BLOCK", "REVIEW", "CLEAR"]
HitType = Literal["sanctions", "pep", "adverse_media"]
Scope = Literal["applicant", "each_hit"]


class RequiredDocument(BaseModel):
    """A document Rule 6 requires, and the boolean fact that proves it present."""

    id: str
    satisfied_by: str


class BrainSettings(BaseModel):
    """Policy values that are not expressible as a rule condition."""

    min_name_score: float
    as_of_date: date
    formation_recent_days: int
    required_documents: list[RequiredDocument]


class Rule(BaseModel):
    """One row of the decision matrix: `when` is matched against the facts bag, `evidence` is quoted in the reason."""

    id: int
    scope: Scope = "applicant"
    when: dict[str, Any] = Field(default_factory=dict)
    decision: Decision
    confidence: float
    cite: str
    evidence: list[str] = Field(default_factory=list)


class Brain(BaseModel):
    """One policy version: authoritative prose, executable table, and the hash of both."""

    version: str
    settings: BrainSettings
    rules: list[Rule]
    policy_text: str
    brain_hash: str


class Pointer(BaseModel):
    """Which version is live, and which one a rollback returns to."""

    active_version: str
    previous_version: str | None = None


class Hit(BaseModel):
    """One watchlist match against one subject, referenced by index so no name reaches a log."""

    entry_id: str
    hit_type: HitType
    subject: Literal["business", "ubo"]
    subject_ref: str
    name_score: float
    corroborated: bool
    corroboration_basis: Literal["dob", "country", "none"] = "none"


class Facts(BaseModel):
    """The applicant reduced to what the policy can reason about; produced by specs 002 and 003."""

    mcc: str | None = None
    has_incorporation_doc: bool = False
    has_ubo_list: bool = False
    shell_signals: list[str] = Field(default_factory=list)
    formation_age_days: int | None = None
    location_validation: Literal["match", "mismatch", "unknown"] = "unknown"
    hits: list[Hit] = Field(default_factory=list)


class MatchedEntity(BaseModel):
    """A watchlist entry that contributed to the verdict."""

    entry_id: str
    hit_type: HitType
    subject_ref: str
    name_score: float
    corroborated: bool


class Verdict(BaseModel):
    """A pure function of (Brain, Facts); `applicant_id` belongs to the case file assembled by /screen."""

    decision: Decision
    confidence: float
    reasons: list[str]
    matched_entities: list[MatchedEntity]
    missing_docs: list[str]
    policy_version: str
    fired_rules: list[int]
    brain_hash: str
