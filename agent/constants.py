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
        # Declared with a sensor and no rule in v1, the same shape as location_validation.
        "injection_suspected",
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

PROMPTS_DIR = "prompts"
EXTRACTION_PROMPT = "extraction"
BASE_HEURISTIC_PROMPT = "base_heuristic"
PROMPT_ROLES = frozenset({EXTRACTION_PROMPT, BASE_HEURISTIC_PROMPT})
REQUIRED_PROMPT_ROLES = PROMPT_ROLES

DOCUMENT_KINDS = ("incorporation", "ubo_declaration", "proof_of_address", "website_extract", "other")

INCORPORATION_DOCUMENT_TYPES = frozenset({"incorporation", "certificate_of_incorporation"})

SHELL_SIGNAL_NOMINEE_DIRECTOR = "nominee_director"
SHELL_SIGNAL_MASS_REGISTRATION = "mass_registration_address"
SHELL_SIGNAL_RECENT_FORMATION = "formation_less_than_threshold"

# The date-window signal is derived by the Brain, so extraction must not report it too.
EXTRACTED_SHELL_SIGNALS = (SHELL_SIGNAL_NOMINEE_DIRECTOR, SHELL_SIGNAL_MASS_REGISTRATION)
SHELL_SIGNALS = frozenset(EXTRACTED_SHELL_SIGNALS) | {SHELL_SIGNAL_RECENT_FORMATION}

MAX_SUPPLEMENTARY_NAMES = 10

# Recall is bought with more calls to the delivered tool, never with a new matcher. (D-009)
WATCHLIST_TOOL = "assets/tools/watchlist_search.py"
MAX_PERMUTED_TOKENS = 3
