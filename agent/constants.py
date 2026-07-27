"""Fixed values shared across the agent: Brain filenames, severity order, engine operators, facts vocabulary."""

POINTER_FILE = "active_version.json"
POLICY_FILE = "screening_policy.md"
RULES_FILE = "rules.yaml"

SEVERITY: dict[str, int] = {"CLEAR": 0, "REVIEW": 1, "BLOCK": 2}

OPERATORS = frozenset({"in", "ne", "gte", "lte"})

APPLICANT_BOOL_FACTS = frozenset({"has_incorporation_doc", "has_ubo_list", "formation_is_recent"})

APPLICANT_FACTS = APPLICANT_BOOL_FACTS | frozenset(
    {
        "mcc",
        "missing_docs",
        "missing_docs_count",
        "shell_signals",
        "shell_signal_count",
        "formation_age_days",
        "location_validation",
    }
)

HIT_FACTS = frozenset(
    {
        "entry_id",
        "hit_type",
        "subject",
        "subject_ref",
        "name_score",
        "corroborated",
        "corroboration_basis",
    }
)

SHELL_SIGNAL_RECENT_FORMATION = "formation_less_than_threshold"
