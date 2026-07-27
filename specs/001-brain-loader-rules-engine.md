# Spec 001 — Brain loader and rules engine

> **Status**: Draft
> **Owner**: first functional component; nothing screening-related exists before it
> **Constitutional context**: D-001 (hybrid architecture)
> **Depends on**: spec 000 (container, `/health`, mounted Brain volume)
> **Decisions owned by this spec**: D-001 … D-006 — the whole log so far (see §11)

## 1. Goal

Make the Company Brain executable. At the end of this spec the system can load a
versioned policy from a mounted volume, evaluate it against a facts bag, and
return a decision, a confidence, cited reasons and a list of missing documents —
without a single policy value living in Python.

Two requirements from the brief are settled here and nowhere else:

- **The Brain decides.** The decision is computed by a generic evaluator over a
  rule table that is data. There is no code path that produces `BLOCK`, `REVIEW`
  or `CLEAR` from a hardcoded condition.
- **Hot-swap and rollback without a redeploy.** Activating a different policy
  version is one authenticated call; rolling back is the same call again.

Facts are *consumed* here and *produced* later (002 extraction, 003 screening).
The facts vocabulary in §5 is therefore the contract those specs are written
against, and it is the reason this spec comes first.

## 2. Scope

**In scope**: Brain version layout, the machine-readable rule table, the loader
with validation and cache, the fact vocabulary declaration, the evaluator, the
verdict object (decision / confidence / reasons / missing docs / matched
entities), `GET /brain`, `GET /brain/versions`, `POST /brain/activate`, the
readiness upgrade to `/health`, and the unit-test layer for all of it.

**Out of scope**: computing facts. Nothing here calls the Anthropic API, reads
`applicants.json`, or invokes `watchlist_search`. Tests feed synthetic facts
directly. Extraction (002) and screening (003) fill the bag; `/screen` (004)
wires them to the evaluator; the eval gate (005) grades the result.

## 3. Brain layout

```
company_brain/                        # mounted volume, not in the image
├── active_version.json               # {"active_version": "v1", "previous_version": null}
└── versions/
    ├── v1/
    │   ├── screening_policy.md       # authoritative prose, byte-identical to assets/
    │   └── rules.yaml                # machine-readable projection of that prose
    └── v2/                           # authored during the hot-swap demo
```

A Brain version is the **directory**, not a single file: prose plus rule table
plus settings, versioned and activated as one unit, hashed as one unit.

`screening_policy.md` stays byte-identical to the delivered policy (D-002). The
rule table is a sibling file rather than a fenced block inside the markdown, so
the claim *"we did not edit the authoritative document"* stays literally true and
the drift check in CI keeps meaning something. The cost of two artifacts is that
they can disagree; §9 pins that shut with a test that parses the decision matrix
out of the prose and compares it to the table.

### `rules.yaml`

```yaml
policy_version: v1

settings:
  min_name_score: 0.75          # threshold handed to watchlist_search (spec 003)
  as_of_date: "2026-07-27"      # fixed evaluation date — never datetime.now() (D-006)
  formation_recent_days: 90
  required_documents:
    - id: certificate_of_incorporation
      satisfied_by: has_incorporation_doc
    - id: ubo_list
      satisfied_by: has_ubo_list

rules:
  - id: 1
    scope: each_hit
    when: {hit_type: sanctions, corroborated: true}
    decision: BLOCK
    confidence: 0.95
    cite: "sanctions hit, corroborated"

  - id: 2
    scope: each_hit
    when: {hit_type: sanctions, corroborated: false}
    decision: REVIEW
    confidence: 0.80
    cite: "sanctions hit, unconfirmed — never CLEAR"

  - id: 3
    scope: each_hit
    when: {hit_type: pep}
    decision: REVIEW
    confidence: 0.85
    cite: "PEP name match"

  - id: 4
    scope: each_hit
    when: {hit_type: adverse_media}
    decision: REVIEW
    confidence: 0.85
    cite: "adverse-media name match"

  - id: 5
    when: {mcc: {in: ["6050", "6051"]}}
    decision: REVIEW
    confidence: 0.90
    cite: "high-risk activity (money services / crypto)"

  - id: 6
    when: {missing_docs_count: {gte: 1}}
    decision: REVIEW
    confidence: 0.90
    cite: "missing required documents"

  - id: 7
    when: {shell_signal_count: {gte: 2}}
    decision: REVIEW
    confidence: 0.85
    cite: "shell-company signals"

  - id: 8
    when: {}
    decision: CLEAR
    confidence: 0.90
    cite: "no rule triggered"
```

Every policy number lives in this file: the MCC set, the shell-signal threshold,
the 90-day window, the match threshold, the required-document set, and the
confidence attached to each outcome. Adding an MCC, moving the threshold to three
signals, or requiring a proof-of-address is a one-line data change.

Each rule also carries `evidence: [fact names]` — the facts to quote in its
reason, e.g. `[entry_id, name_score, corroboration_basis]` for a hit rule and
`[missing_docs]` for Rule 6. Without it the engine would need to know that Rule 6
is *about documents* in order to say which one was missing, and the moment it
knows that, the rule table has stopped being the only place policy lives.

**Rule 9 has no entry** (D-005). It states that a pure name collision to a
different entity is not a hit and may be CLEAR — but rules 2, 3 and 4 already
catch every name hit, and under the severity aggregation in §6 a `CLEAR` rule can
never lower a verdict another rule raised. An entry for it would be dead data
that reads like an escape hatch from Rule 2, which is exactly the mistake the
override demo exists to prevent. It is documented, not implemented.

## 4. Loader

`agent/brain.py` — absorbs the `active_version` helper written in spec 000.

```python
load_brain(brain_dir: Path) -> Brain            # raises BrainUnavailable
```

`Brain` carries `version`, `settings`, `rules`, `policy_text`, `brain_hash`.

- The pointer is read **fresh on every call**. No process-lifetime caching of the
  active version, or a swap would need a restart.
- Parsed versions are cached keyed by `(version, sha256(rules.yaml + policy.md))`.
  Hashing two files under 10 KB per request is cheaper than re-parsing and, unlike
  an mtime key, is immune to volume-mount timestamp behaviour. The same hash is
  reported by `/health`, returned by `/brain`, and recorded in every trace — it is
  what makes "same applicant, same Brain state" a checkable claim rather than an
  assertion.
- Validation runs at load, and any failure raises `BrainInvalid(BrainUnavailable)`:
  - `policy_version` matches the directory name
  - rule `id`s unique; `decision` ∈ {BLOCK, REVIEW, CLEAR}; `scope` ∈ {applicant, each_hit}
  - `confidence` ∈ [0, 1]; `cite` non-empty
  - every fact name in every `when` is declared in §5, and every operator is one of §6
  - exactly one rule with an empty `when` (the default), and its decision is CLEAR
  - `settings` complete; every `satisfied_by` names a declared boolean fact
- **Fail closed.** An unreadable or invalid Brain never falls back to a previous
  version and never degrades to a built-in default. The instance stops serving.

## 5. Facts vocabulary

The contract between the producers (002, 003) and the evaluator. A fact not
declared here cannot appear in a rule; a rule referencing an undeclared fact
fails the load rather than silently evaluating false.

Applicant scope:

| Fact | Type | Produced by |
|---|---|---|
| `mcc` | string | packet, verbatim |
| `has_incorporation_doc` | bool | 002 — semantic normalisation of `documents[].type` |
| `has_ubo_list` | bool | packet: `len(ubos) > 0` (D-004) |
| `missing_docs` | list[str] | derived from `settings.required_documents` |
| `missing_docs_count` | int | `len(missing_docs)` |
| `shell_signals` | list[str] | 002 (nominee director, mass-registration address) + `formation_is_recent` |
| `shell_signal_count` | int | `len(shell_signals)` |
| `formation_age_days` | int | `as_of_date − incorporation_date` |
| `formation_is_recent` | bool | `formation_age_days < settings.formation_recent_days` |
| `location_validation` | `match` / `mismatch` / `unknown` | live-call slot — declared now, populated by the geolocation tool |
| `hits` | list[Hit] | 003 |

Per-hit scope (each element of `hits`, merged over the applicant facts when a
`each_hit` rule is evaluated):

| Fact | Type | Notes |
|---|---|---|
| `entry_id` | string | watchlist entry, cited in `reasons[]` |
| `hit_type` | `sanctions` / `pep` / `adverse_media` | from the watchlist entry |
| `subject` | `business` / `ubo` | which name matched |
| `subject_ref` | string | `business` or `ubo[i]` — an index, never a name (PII) |
| `name_score` | float | from `watchlist_search` |
| `corroborated` | bool | D-003 |
| `corroboration_basis` | `dob` / `country` / `none` | which pair agreed, for `reasons[]` |

`location_validation` is declared but never populated by this spec. Declaring the
slot now is the whole point: the live-call task adds a rule that references it,
and the rule table must accept that rule the moment it is written, with the only
code change being the fact source that fills it.

`missing_docs`, `shell_signals` and `corroboration_basis` exist so `reasons[]` can
name *what* was missing or *which* field corroborated without the evaluator
knowing anything about documents or dates of birth.

## 6. Evaluator

`agent/rules.py`, one pure function:

```python
evaluate(brain: Brain, facts: Facts) -> Verdict
```

No I/O, no clock, no randomness, no global state. Same arguments, same bytes out.

**Operators.** Five, total, and deliberately not extensible without a decision
entry:

| Form | Meaning |
|---|---|
| `key: value` | equality |
| `key: {in: [...]}` | membership |
| `key: {gte: n}` / `{lte: n}` | numeric comparison |
| `key: {ne: value}` | inequality |
| `when: {}` | matches always — the default rule |

Multiple keys in one `when` are ANDed. There is no `or` and no nesting: a
disjunction is two rule entries citing the same policy rule, which reads better in
the table than a boolean tree and keeps the evaluator to about forty lines. A
condition against a `null` fact is false for every operator.

**Evaluation.** Every rule is evaluated against every applicable subject —
`applicant`-scope rules once, `each_hit`-scope rules once per hit. All matches are
collected; nothing short-circuits.

**Aggregation**: `decision` is the most severe decision among the fired rules,
`BLOCK > REVIEW > CLEAR`. This is not first-match-wins, and it is not a judgment
call — the policy says it in those words: "evaluate the business AND every UBO;
most severe outcome wins". Keeping every match rather than the winner is what lets
`reasons[]` name both problems when an applicant has a PEP hit *and* MCC 6051. The
default rule always fires and is dropped from `reasons[]` whenever anything else
did.

`confidence` is the confidence of the fired rule that set the decision; on a tie,
the lowest among them. It is policy data, never a model output.

**Verdict**:

```json
{
  "decision": "REVIEW",
  "confidence": 0.8,
  "reasons": ["Rule 2 — sanctions hit, unconfirmed — never CLEAR: ubo[0] matches EU-2001 (score 0.966, DOB and country conflict)"],
  "matched_entities": [{"entry_id": "EU-2001", "hit_type": "sanctions", "subject_ref": "ubo[0]", "name_score": 0.966, "corroborated": false}],
  "missing_docs": [],
  "policy_version": "v1",
  "fired_rules": [2],
  "brain_hash": "sha256:…"
}
```

`reasons[]` is templated from the rule's `cite`, the subject reference and the
cited `entry_id` — no LLM (D-001). Findings are sorted by severity, then rule id,
then `subject_ref`, then `entry_id`, so shuffling the input `hits[]` cannot change
a single byte of the output. `policy_version` and `brain_hash` are echoed so a
stored verdict can be traced back to the exact policy state that produced it.

## 7. Admin API

| | |
|---|---|
| `GET /brain` | active version, `brain_hash`, rule count, settings, `previous_version` |
| `GET /brain/versions` | every directory under `versions/`, each with a validity flag |
| `POST /brain/activate` | `{"version": "v2"}` → `{previous, active, brain_hash}` |

`POST /brain/activate` requires `Authorization: Bearer $ADMIN_API_TOKEN`.

- 401 on a missing or wrong token
- 404 on a version with no directory
- 422 when the target fails §4 validation, with the validation errors in the body
  and **the pointer unchanged** — an invalid policy cannot be activated, so the
  fail-closed path in §4 is a backstop, not the primary defence
- 503 when `ADMIN_API_TOKEN` is empty; an unauthenticated mutation endpoint is
  worse than a missing one

The pointer is rewritten atomically (temp file in the same directory, then
`os.replace`) so a concurrent request cannot read a half-written pointer. The
previous version is recorded in the pointer, which makes rollback one call with no
memory of what came before — there is no separate rollback endpoint to keep the
mutable surface at one.

Activation is logged with version, hash and the caller's token fingerprint. No
restart, no rebuild, no redeploy.

### `/health`

Upgraded from "the pointer resolves" to "the Brain loads and validates". It now
reports `brain_hash` alongside `brain_version`, and returns 503 when the rule table
is invalid. An instance whose policy will not parse must not receive traffic — it
would otherwise fail at decision time, on a real applicant.

## 8. Layout

```
agent/
├── constants.py    # filenames, severity order, operators, the §5 vocabulary
├── schemas.py      # every model: Brain, Rule, BrainSettings, Facts, Hit, Verdict
├── brain.py        # loader, validation, hash, cache, activation
├── facts.py        # derived facts → the bag the evaluator matches against
└── rules.py        # generic evaluator → Verdict
api/
├── brain_routes.py # GET /brain, GET /brain/versions, POST /brain/activate
└── main.py         # /health upgraded
tests/
├── conftest.py         # Brain volume builders, clean/hit fact factories
├── test_policy_sync.py # the prose matrix vs the rule table
├── test_brain_loader.py
├── test_rules_engine.py
└── test_brain_activate.py
```

`api/brain.py` from spec 000 is absorbed into `agent/brain.py`; `/health` imports
from there. The Brain has one loader.

Fixed values live in `constants.py` and models in `schemas.py`, each in exactly
one place, so the modules form a line rather than a cycle:
`constants ← schemas ← facts ← rules`, with `brain` reading constants and schemas
directly. The facts vocabulary being a constant rather than a private detail of
`facts.py` is what lets the loader reject a rule that names something nobody
produces.

One change outside `agent/`: both compose files mounted `company_brain` read-only,
which would have made `POST /brain/activate` fail at the write. The mount becomes
`rw`. The pointer is the only file the service ever writes.

## 9. Acceptance criteria

1. Nine tests, one per policy rule, feeding synthetic facts into `evaluate` and
   asserting decision, fired rule id and cited entry — including Rule 9's
   documented inertness (a hit that is nothing but a name collision still yields
   REVIEW under Rule 2/3/4).
2. APP-011-shaped facts (sanctions hit, `corroborated: false`) → `REVIEW`, citing
   Rule 2 and `EU-2001`. The same facts against a Brain whose table omits Rule 2
   → `CLEAR`. Only the Brain changed the outcome.
3. Severity aggregation: facts producing a corroborated sanctions hit *and* MCC
   6051 → `BLOCK`, with `reasons[]` citing Rules 1 and 5, and `fired_rules == [1, 5]`.
4. Ordering independence: shuffling `hits[]` produces byte-identical output.
   `evaluate` over the same facts 100× produces one distinct serialisation.
5. A rule naming an undeclared fact, a duplicate rule id, an out-of-range
   confidence, a missing default rule, or two default rules → load fails with
   `BrainInvalid`; `/health` returns 503.
6. Prose/table sync: the decision matrix parsed out of `screening_policy.md`
   yields the same `{id → decision}` mapping as `rules.yaml`, for every id except 9.
7. `company_brain/versions/v1/screening_policy.md` remains byte-identical to
   `assets/company_brain/screening_policy.md` (existing CI check still green).
8. Hot-swap, in-process: author `v2` with the MCC set extended to `5734`, activate
   it, and the next `evaluate` on unchanged facts returns `REVIEW` where it
   returned `CLEAR` — no restart, no rebuild. `5734` is APP-001's MCC, so the same
   swap flips a labelled clean applicant once 003 exists, and the demo runs on real
   data rather than a fixture.
9. Rollback: activating `v1` again restores the original verdict, and `GET /brain`
   reports `previous_version: v2`.
10. `POST /brain/activate` returns 401 without a token, 404 for `v9`, and 422 for a
    version with a malformed `rules.yaml` — the pointer unchanged in every case.
11. `pytest tests/` passes with `ANTHROPIC_API_KEY` unset and no network.
12. Live: `POST /brain/activate` against staging swaps the policy on the running
    container, and `GET /health` reports the new hash without the container being
    restarted.

## 10. What this makes possible

The hot-swap demo becomes runnable at the end of this spec, before any LLM code
exists — worth stating, because the live-call task is a *rule addition*, and the
mechanism it depends on will have been exercised for two days by then rather than
first attempted under observation.

## 11. Decisions this spec produces

`DECISIONS.md` is created on this branch, because this is where the first
judgment call forced by the brief actually lands. The log holds six entries and
should stay close to that size: an entry only earns its place if the brief would
*not* still be satisfied had the opposite been chosen. Free choices — stack,
hosting, branching, no agent framework — are in `DESIGN.md` instead, which is why
spec 000 produces none.

| | |
|---|---|
| **D-001** | The decision never passes through a sampling step. Agentic and deterministic pull against each other; the LLM owns free text, deterministic code owns the verdict. Written here rather than at bootstrap because this is where it becomes real. |
| **D-002** | The rule table is a sibling `rules.yaml`, not a fenced block inside the authoritative markdown, so the delivered policy stays byte-identical and the CI drift check keeps its meaning. Sync is enforced by a test. |
| **D-003** | Corroboration: corroborated when *any* comparable field pair agrees. A field missing on both sides is not comparable and is not a conflict, so `Zephyr Logistics FZE` (no DOB either side, AE = AE) is corroborated → BLOCK. The stricter reading would make it REVIEW; both are non-CLEAR, so the headline metric is unaffected either way. |
| **D-004** | Rule 6's "UBO list" is a populated `ubos[]` array, not a document. APP-001 is CLEAR with no `ubo_declaration`; APP-017 has an incorporation document and `ubos: []`. The document reading contradicts both labels. |
| **D-005** | Rule 9 gets no table entry: it is unreachable under severity aggregation, and an entry for it would read as an escape hatch from Rule 2 — the exact failure the override demo exists to catch. |
| **D-006** | `as_of_date` is pinned in the Brain rather than read from the clock. Verified decision-neutral across all 18 applicants: the most recent formation is 2025-12-01, and APP-008 reaches Rule 7's threshold on nominee director plus mass-registration address alone. |

Each is written in the append-only entry format — what forced it, what was
decided, what was rejected, what it forces elsewhere — at the moment the code it
governs lands, not batched at the end of the branch.

## 12. Risks

- **Prose and table drift.** The one structural cost of D-002, and the reason
  criterion 6 exists. If the parse of the markdown matrix proves brittle, the
  fallback is an explicit `{id → decision}` fixture in the test — still a check,
  just a manually maintained one.
- **A generic evaluator is the natural place to over-build.** The operator set is
  frozen at five and the engine has no `or`; widening it requires a decision entry
  arguing why the table could not express the rule as two entries. The rubric
  rewards correctness per unit of complexity, and a rules DSL is a very easy thing
  to keep polishing.
- **D-003 may be the wrong reading of the policy.** It moves APP-015 between BLOCK
  and REVIEW. The trace records `corroboration_basis` on every hit, so the reading
  that produced a verdict is visible per-run and can be defended or reversed
  without re-deriving it from the code.
- **`as_of_date` goes stale.** Harmless within this challenge; a real deployment
  would need a policy-review cadence. Recorded in `DESIGN.md` under failure modes
  rather than left as a silent constant.
