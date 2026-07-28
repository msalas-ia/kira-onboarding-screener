# Spec 003 — Screening and corroboration

> **Status**: Draft
> **Owner**: the spec that completes the facts bag; after this the verdict is a pure function of Brain and packet
> **Constitutional context**: D-001 (the decision never passes through a sampling step), D-003 (one comparable pair is enough), D-005 (Rule 9 has no entry)
> **Depends on**: spec 001 (rules engine, `Facts`, `Hit`), spec 002 (`screening_targets[]`)
> **Decisions owned by this spec**: D-009 (see §12)

## 1. Goal

Fill the last field of the facts bag — `hits[]` — with no model anywhere on the
path.

Two things are settled here and nowhere else:

- **Coverage is a floor, never a filter.** The business and every UBO are searched
  unconditionally, plus every supplementary name extraction proposed. Nothing in
  the pipeline can remove a search.
- **Recall is bought with more calls to the delivered tool, not with a new
  matcher.** `watchlist_search` misses a name whose tokens are reordered, and that
  miss is a false clear. The fix is orchestration — the agent's declared job —
  not a reimplementation (D-009).

After this spec the verdict is complete and correct on the labelled set, and it
is reached without a single sampling step: extraction is the only model call in
the pipeline, and its output is already unioned with a deterministic floor
(D-008). Determinism stops being a measurement and becomes a property of the call
graph.

## 2. Scope

**In scope**: the watchlist tool in the image, the name-variant sweep, the hit
model, corroboration, the never-auto-CLEAR assertion, and the offline test layer
for all of it.

**Out of scope**: `/screen`, the case file, the trace and PII redaction (004);
the adjudication proposal that consumes the `base_heuristic` prompt and the
model-initiated search loop, which move to **004** (§7); the eval suite and the
CI gate (005); `location_validation`, which stays a declared slot with no sensor
until the live call.

> Spec 002 §2 and §4 pointed the `base_heuristic` role at this spec. It moves to
> 004 because the proposal's only product is a trace record and the trace is 004's
> — and because keeping it out leaves 003 with no model on the decision path at
> all, which is worth more than the adjacency. The prompt itself is already a
> Brain artifact and does not move.

## 3. What the data actually requires

Measured against all 18 packets and all 12 watchlist entries, because three
findings determine the shape of this step.

| Finding | Consequence |
|---|---|
| The unconditional sweep over business + every UBO at `min_name_score = 0.75` yields exactly **9 hits**: the 7 the dev labels expect, plus APP-013 (`Blue Harbor Trading LLC` → AM-4003, exact) and APP-015 (`Zephyr Logistics FZE` → OFAC-1004, exact), both unlabelled | The sweep needs no tuning to reproduce the labelled set. The two extra hits are correct, not noise — they are the unlabelled applicants D-003 already predicted would BLOCK |
| `difflib.SequenceMatcher` scores a reordered name far below threshold: `Kravchenko Olena` → PEP-3004 is **0.625**, `Petrov Viktor` → OFAC-1001 is **0.545**, `Sokolova Ivanka` → EU-2001 is **0.533**, `Al-Rashid Muhammad` → OFAC-1003 is **0.500** | Every one of those is a sanctions or PEP entity that screens **clean** under a single raw-name call. That is a false clear, the one metric the brief requires to be zero, and the holdout is described as "similar cases" — six watchlist entries are unexercised by the dev set, `Olena Kravchenko` among them |
| Calling the **unmodified** tool once per token permutation recovers all of them at score **1.0**, and over the 18 packets changes the hit set by nothing: 9 before, 9 after, zero added, zero lost | Recall is available without touching the matcher. 124 local `difflib` calls instead of 39 — no network, no API, no cost |
| No packet's business or UBO name lands between 0.75 and the near-miss band by accident: the closest sub-threshold pair is `Emily Zhang` → PEP-3003 at 0.60 | The threshold is not sitting on a knife edge, so the variant sweep is not smuggling in borderline matches |

## 4. The tool, used as delivered

`assets/tools/watchlist_search.py` is imported **in place and unmodified**. There
is exactly one copy of that file in the repository and it is the delivered one, so
drift is impossible by construction rather than by a CI check. `agent/screening.py`
loads it through `importlib` and never edits, wraps or shadows its scoring.

The tool resolves its data as `../data/watchlist.json` relative to its own file,
so `assets/data/` and `assets/tools/` are copied into the image — today the
Dockerfile ships only `agent/` and `api/`, which means the running container has
no watchlist at all. The watchlist is **not** Brain state: it is a data feed, not
policy, so it is baked into the image rather than mounted. Its sha256 is reported
by `/health` as `watchlist_hash` beside `brain_hash`, so a stored decision is
traceable to the list state that produced it as well as to the policy state.

> Rejected: mounting the watchlist so it can be refreshed without a rebuild. The
> brief asks for a hot-swappable *Brain*, not a hot-swappable data feed, and a
> second writable mount is surface with no demo behind it. Recorded here so the
> choice is visible rather than accidental.

`min_score` is never hardcoded at a call site: it comes from
`brain.settings.min_name_score`, which is already Brain data. Changing the
threshold stays a version swap.

## 5. Coverage — the sweep

```
screening_targets[]  (from 002: business ∪ every UBO ∪ supplementary names)
        │
        ├─▶ for each target, for each name variant ─▶ watchlist_search(variant, min_score)
        │
        └─▶ union by (target, entry_id), keeping the highest score
```

**Name variants** are generated from the target name alone, with no knowledge of
the watchlist: the name as given, plus every token permutation when the name has
two or three tokens. Longer names keep only the given order and the reversed one,
so the call count stays linear where a factorial would not be worth it. Variants
are a pure function of the string — same name, same variants, always.

The union is keyed by `(subject_ref, entry_id)` and keeps the highest score seen,
so a name that hits the same entry through three variants is one hit, and the
recorded `name_score` is the strongest evidence available rather than an artifact
of which variant happened to run first. `name_variant` records **whether** the
winning score came from the name as given or from a reordering — as a category,
not as the string. A hit found only through a reordering is exactly what a
reviewer will want to see justified, but `Hit` carries `subject_ref` and never a
name so that no name reaches a log, and storing the winning spelling would put PII
back into the one structure built to exclude it.

Two properties this must have, both tested rather than asserted:

- **Superset.** For every target in every packet, the hits found here contain the
  hits the delivered tool returns for the raw name. The sweep can only add.
- **Order independence.** Sorting `screening_targets[]` differently, or generating
  variants in a different order, produces the identical `hits[]` serialisation.

Supplementary names from documents are searched on the same terms as packet
names. A hit against a document-sourced name has no DOB and no country to compare,
so it can never corroborate — it lands as unconfirmed, which for a sanctions entry
is Rule 2 REVIEW. That is the safe direction and it is the price of letting the
model widen coverage; §13 records what it costs.

## 6. Corroboration

The policy defines it as a field comparison, so it is a field comparison — no
model on this path:

> **Corroborated** = strong name similarity AND the DOB matches (or the
> country/nationality is consistent).
> **Unconfirmed** = … the DOB conflicts, or the country/nationality differs, or
> the corroborating fields are missing.

A pair is **comparable** when both sides are present. D-003 already settled that
*one* comparable pair agreeing is enough; what 003 adds is the exact reading of
each side:

| | subject side | entry side |
|---|---|---|
| DOB | `ubos[].dob` (business targets have none) | `entry.dob`, may be null |
| Country | `ubos[].nationality`, or for a business its `registration_country` falling back to `address.country` | `entry.country` |

- No comparable pair at all → **unconfirmed**. Missing identity is not confirmed
  identity, and the policy says so in as many words.
- Any comparable pair agreeing → **corroborated**, with `corroboration_basis`
  recording which one. DOB takes precedence over country when both agree, because
  it is the stronger claim and the trace should say the stronger thing.
- A comparable pair disagreeing while another agrees → corroborated on the one
  that agrees. This is D-003 and it is what makes APP-015 a BLOCK.

Verified against the labelled set: APP-003 (DOB `1968-03-12` and `RU` both agree),
APP-007 (`1975-11-02`, `SY`) and APP-009 (`1980-06-21`, `BY`) corroborate → Rule 1
BLOCK. APP-011 has DOB `1980-06-20` against `1980-06-21` and `PL` against `BY` —
both comparable, both disagreeing, nothing agrees → unconfirmed → Rule 2 REVIEW.
That single row is the entire override demo, and it falls out of a field
comparison rather than out of a prompt.

## 7. What this spec hands to 004, and why the proposal is not here

The rules engine already decides, and after §6 it has everything it needs. The
adjudication proposal — the model carrying `base_heuristic`, proposing a decision
and being overruled — produces no decision value at all: its entire output is a
record that goes next to the verdict so the override is visible on every run. That
record is a trace field, and the trace is 004's.

The same reasoning moves the **model-initiated search loop** to 004. Giving the
model `watchlist_search` as a real tool is what finally gives
`settings.max_steps_per_applicant` (12) and `settings.request_timeout_seconds`
(120) something to guard, and it is also the only place in the whole pipeline
where a model can move the decision: a search it initiates adds a hit, and a hit
changes the verdict. Two consequences, and they are the argument for the split:

- **003 has no model on the decision path.** Extraction is the only model call
  upstream, and its result is already floored (D-008). So `hits[]` is a pure
  function of `(packet, extraction, watchlist, min_name_score)` and the verdict is
  a pure function of `(Brain, Facts)`. Determinism here is structural — criterion
  9 measures it, but it would be surprising if it failed.
- **004 introduces the one thing that can break that, together with the trace
  that measures it.** The loop is bounded and monotone — it can add a search,
  never remove one — and 004 carries the condition: it keeps feeding `hits[]` only
  while the five-run hash of the full verdict stays stable, otherwise
  model-initiated hits are demoted to trace-only. That is 004's decision to log,
  not this spec's.

The order also has a delivery property worth stating: the graded outcome — all 12
labels correct, false-clear zero — lands at the end of 003, before any second
model call exists. If the proposal or the loop later proves unstable or too
expensive, it can be dropped without touching the spec that delivered the result.

### Guardrail: never auto-CLEAR a hit

An assertion after adjudication, independent of rule ordering: if `hits[]` is
non-empty and the verdict is `CLEAR`, the run raises. It cannot be satisfied by a
rule table that happens to be written correctly, which is the point — it survives
a bad edit to the Brain.

## 8. Layout

```
agent/
├── screening.py   # the tool loader, variant generation, the sweep, the union
├── corroborate.py # the field comparison → corroborated, corroboration_basis
├── schemas.py     # + Hit.name_variant, ScreeningResult
└── constants.py   # + variant limits
tools/  — deliberately absent: assets/tools/watchlist_search.py is imported in place
tests/
├── test_screening_sweep.py      # 18 packets, the superset property, order independence
├── test_name_variants.py        # the four inverted names, and that variants are pure
├── test_corroboration.py        # the D-003 matrix, including APP-011 and APP-015
├── test_labels_end_to_end.py    # the 12 labelled applicants, false-clear count zero
└── test_never_auto_clear.py     # the guardrail fires against a deliberately wrong Brain
```

The dependency line holds and extends: `constants ← schemas ← {llm, extraction,
screening, corroborate} ← facts ← rules`. `screening.py` imports neither
`rules.py` nor `facts.py` — it returns hits and knows nothing about what they mean.

Tests use the real watchlist and the real tool — it is deterministic, stdlib-only
and local, so mocking it would test the mock. The end-to-end test over the 12
labels drives extraction from recorded fixtures, so **this spec adds no live test
at all**: everything it claims is checkable with no key and no network.

## 9. Acceptance criteria

1. The unconditional sweep over all 18 packets produces exactly the 9 hits
   measured in §3, with the labelled 7 attributed to the right `subject_ref`.
2. **The superset property holds**: for every target in every packet, the hits
   found contain the delivered tool's hits for the raw name. Zero lost.
3. The four reordered names of §3 each produce their entry at score 1.0, and the
   variant sweep adds **zero** hits to the 18 packets relative to raw-name calls.
4. Corroboration reproduces the labels: APP-003, APP-007, APP-009 corroborated →
   BLOCK; APP-011 unconfirmed → REVIEW; APP-015 corroborated on country alone →
   BLOCK. A hit with no comparable pair is unconfirmed, never corroborated.
5. All 12 labelled applicants produce the labelled decision end to end, driven
   from recorded extraction fixtures, and the **false-clear count is zero**.
   APP-011 is REVIEW because Rule 2 fired on an unconfirmed hit, and the test
   asserts the rule id, not just the verdict — the right answer for the wrong
   reason is still wrong.
6. **Determinism over the full verdict.** Five real runs over the 12 labelled
   applicants produce one distinct serialisation of `(decision, reasons[],
   matched_entities[], hits[], screening_targets[])` per applicant — not just the
   facts bag. This closes the gap 002 left open rather than deferring it to 005,
   and it is the baseline 004's tool loop has to preserve.
7. Given a fixed extraction, the sweep and corroboration are a pure function:
   running them twice over the same input produces byte-identical `hits[]`, and no
   module involved reads a clock, an environment variable or a random source.
8. The never-auto-CLEAR assertion fires: a Brain whose table maps a corroborated
   sanctions hit to CLEAR raises instead of returning it.
9. `/health` reports `watchlist_hash`, and the container has the watchlist — the
   image ships `assets/data/` and `assets/tools/`.
10. `uv run pytest -q` passes with `ANTHROPIC_API_KEY` unset and no network, with
    **nothing skipped that this spec added**.
11. `agent/` still reads no wall clock, and no module under `agent/` contains a
    decision value.

## 10. Cost and latency

Nothing in this spec calls a model. The sweep is 124 local `difflib` calls for
all 18 packets — no network, no tokens, no cost — so the per-applicant figure
stays exactly where 002 left it: 4.1 s and $0.0079, all of it extraction. The
second model call arrives with 004's proposal, and its cost is 004's to measure.

## 11. What this makes possible

After this spec the verdict is complete and correct on the labelled set, reached
without a sampling step anywhere on the decision path. 004 is then `/screen`, the
case file, the trace and PII redaction — composition over parts that already
work — plus the proposal and the tool loop, which arrive with a measured
determinism baseline to hold themselves against. 005 is the eval suite and the CI
gate over a pipeline whose correctness is already pinned by tests that need no
API key.

## 12. Decisions this spec produces

| | |
|---|---|
| **D-009** | Recall is bought with more calls to the delivered tool, never with a new matcher. `watchlist_search` is used byte-identical and called once per token permutation of each target name; the union keeps the highest score. Forced by a tension in the brief: it requires a false-clear rate of zero while handing over a matcher that scores a reordered sanctions name at 0.5–0.625, and the holdout is described as similar cases. Rejected: reimplementing the scorer with token-sorted comparison — it gets the same recall and the same zero added hits, but it replaces the delivered artifact with our own on the one path a reviewer will read most carefully. Rejected: leaving it alone and accepting the miss — that is a false clear by construction. |

Written when the code it governs lands, in the append-only format in
`.claude/skills/log-decision/`, and referenced from the commit that implements it.
The decision about model-initiated searches feeding `hits[]` belongs to 004, where
the loop does.

## 13. Risks

- **Supplementary names widen the sweep and can only escalate.** A person named in
  a document, with no DOB and no country, that hits a sanctions entry produces an
  unconfirmed hit and a REVIEW. On the 18 packets this costs nothing, but on the
  holdout a stray name could turn a CLEAR into a REVIEW. That is the safe
  direction and the metric that must be zero is unaffected; accuracy is what pays.
  Measured before the eval gate in 005 rather than assumed.
- **The override demo does not exist until 004.** It is the single most scrutinised
  thing in the brief and this spec deliberately does not deliver it. What it does
  deliver is the half that decides: APP-011 is REVIEW by Rule 2, deterministically,
  at the end of 003. What 004 adds is the naive proposal to place beside it. The
  risk is schedule, not design, and it is why the proposal is the first thing 004
  builds.
- **`watchlist_hash` is a new claim in `/health`.** It has to be computed from the
  file the tool actually loaded, not from a path the config believes in, or it
  reports a truth about the wrong file.
- **Token permutations are a heuristic about how names are written.** They recover
  reordering, not transliteration, diacritics or initials. `Sergio Beltrán` vs
  `Sergio Beltran` already scores above threshold, so nothing in this watchlist
  exercises the gap — a real deployment needs a name-matching library, and saying
  so is more honest than pretending permutations are a general solution.
