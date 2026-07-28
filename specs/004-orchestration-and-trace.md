# Spec 004 — Orchestration, the case file, and the trace

> **Status**: Draft
> **Owner**: the spec that makes the system reachable; everything before it is a library
> **Constitutional context**: D-001 (the decision never passes through a sampling step), D-008 (extraction can raise severity, never lower it), D-009 (recall is bought with more calls to the delivered tool)
> **Depends on**: spec 001 (Brain, rules engine), spec 002 (extraction, prompts as Brain artifacts), spec 003 (the sweep, corroboration, the never-auto-CLEAR guardrail)
> **Decisions owned by this spec**: D-010, D-011, D-012 (see §11)
> **Folds in**: what `ARCHITECTURE_REVIEW_DRAFT.md` §7.1 listed as a separate `006-observability` spec. The trace is not a component that can be specified apart from the pipeline it describes.

## 1. Goal

Make the pipeline callable, and make one run explain itself.

Three things are settled here and nowhere else:

- **The case file is a response, not a log.** `POST /screen` takes a packet and
  returns the contract the policy specifies, plus the hashes that identify the
  policy and list state that produced it.
- **The override becomes observable on every run.** The naive base heuristic the
  Brain explicitly permits is carried by a model that proposes a decision and is
  then overruled by the rule table. Both are recorded side by side. It is not a
  demonstration mode; there is no other mode.
- **PII stays out of the trace by construction.** Not scrubbed on the way out —
  the trace schema has no field that can hold a name, a date of birth or a quoted
  span. This is the same defence as the extraction schema's missing `decision`
  field: absence of a slot, not a filter that has to recognise the attack.

After this spec the Definition of Done's central sentence — *we can screen an
applicant and see the case file* — is met, and every claim `DESIGN.md` already
makes about traces and authenticated callers has code behind it.

## 2. Scope

**In scope**: `POST /screen` and its auth, the case file contract, the
orchestrator, the adjudication proposal (the `base_heuristic` prompt), the
bounded model-initiated search loop, the trace and its cost/latency accounting,
PII redaction by construction, the human-routing flag, and the offline test layer
for all of it.

**Out of scope**: the eval suite, the false-clear metric as a gate, and CI (005);
`location_validation` and the geolocation fact source, which stay a declared slot
until the live call (§8); a second Brain version for the hot-swap demo, which is
an artifact rather than code and needs no spec.

## 3. What the data actually requires

The naive heuristic is not a foil invented for one applicant. Simulated over all
18 packets — *no exact sanctions match → CLEAR*, read literally, against the same
hits the 003 sweep produces:

| Finding | Consequence |
|---|---|
| The heuristic disagrees with the Brain on **7 of the 12 labelled applicants** — APP-002, 004, 005, 006, 008, 011, 012 — and on **10 of the 18** | The override is not a staged single case. It fires on more than half the labelled set, so a trace that records proposal beside verdict shows the Brain earning its keep on almost every run rather than on one |
| Every one of those 7 disagreements is in the **CLEAR** direction | The naive instruction produces false clears, the metric the brief requires to be zero. That is what makes it a legitimate thing to carry and a necessary thing to overrule |
| APP-011's hit is `EU-2001` at **0.966**, uncorroborated | The designated demo case is the narrowest of the seven: a near-match at 0.966 that a literal reading of "no *exact* match" clears. The Brain reads it as Rule 2 → REVIEW |
| APP-005, 006 and 008 disagree with **no watchlist hit at all** | The heuristic's blind spot is wider than sanctions: MCC risk, missing documents and shell signals are invisible to it. The rule table is not merely stricter, it is looking at facts the instruction never mentions |

Two cautions this table has to carry, or it overstates its own result:

- This is the heuristic's implication if followed literally, computed in Python.
  It is **not** a measurement of what the model will actually propose.
- The deterministic half of the override demo already exists and does not depend
  on the proposal at all: APP-011 is REVIEW by Rule 2 at the end of 003. The
  proposal adds the thing to place beside it, not the result.

### Measured: the model declines to be naive

Eleven real runs once the step landed, `claude-opus-5` carrying the
`base_heuristic` prompt and seeing only the tool's own output — `entry_id`,
`hit_type`, `name_score` — with no rule table and no documents:

| applicant | proposed | Brain | overridden |
|---|---|---|---|
| APP-011 | REVIEW | REVIEW | no |
| APP-004, APP-012, APP-002 | REVIEW | REVIEW | no |
| APP-005, APP-008 | REVIEW | REVIEW | no |
| APP-009 | BLOCK | BLOCK | no |
| APP-001 | CLEAR | CLEAR | no |

**Zero overrides.** On APP-011 the model is handed a sanctions entity at 0.966 —
not an exact match — and proposes REVIEW anyway, which is what the heuristic
told it not to do. It cites `EU-2001` while doing so.

A first attempt also showed it `corroborated` and `corroboration_basis`. That was
a defect and was removed: corroboration is a conclusion the policy defines
(D-003), so showing it leaked the rule table into the step built to reason
without one. Removing it changed nothing — the result above is the corrected
step.

The finding stands as measured. Tuning the prompt until the model misbehaves
would manufacture the demonstration rather than perform it, and §12 said so
before the number came back. What follows from it:

- **The override cannot be demonstrated by a model proposal**, because the model
  does not need overruling. The demonstration the brief asks for has to rest on
  the deterministic ablation — the same applicant against two policy versions —
  which is a Brain swap and needs no model at all.
- **`override` is still worth recording on every run.** It is the instrument; a
  reading of "no disagreement" is a result, not a missing feature, and the field
  is what would catch a future model that does drift.
- **The rule table is the load-bearing safety mechanism, not the prompt.** That
  is the conclusion this measurement actually supports, and it is a stronger
  claim than the one the step was built to illustrate.

## 4. `POST /screen`

```
POST /screen                Authorization: Bearer <SCREEN_API_TOKEN>
  body    the applicant packet, exactly the shape of one entry in applicants.json
  200     {case_file, trace}
  401     missing or invalid token
  422     the packet does not validate
  503     the Brain does not load, or the watchlist is absent — same condition as /health
```

The endpoint takes a **packet**, never an `applicant_id`. The delivered bundle is
test data, not a database the service owns; the eval harness in 005 and the demo
script both read `applicants.json` and post what they find. One surface, no
lookup table, and nothing in the service that only works for the 18 packets we
happen to have.

Auth is a bearer token in `SCREEN_API_TOKEN`, distinct from `ADMIN_API_TOKEN`. A
caller that can screen an applicant should not thereby be able to swap the
policy; that is least privilege, and it costs one config field. An unset token
closes the endpoint rather than opening it — the same posture
`api/brain_routes.py` already takes.

### The case file

Every field the policy's output contract names, plus what makes a stored decision
traceable:

```
applicant_id            decision          confidence
reasons[]               matched_entities[]  missing_docs[]
policy_version          brain_hash        watchlist_hash
run_id                  requires_human_review
```

`requires_human_review` is `decision != "CLEAR"`, stated as a field rather than
left for a caller to infer. The brief's guardrail is that REVIEW and BLOCK route
to a human; a boolean in the contract is how a downstream integration is told
that, and nothing in this service auto-actions anything either way.

The case file carries **no name, no date of birth and no address** — not because
it is filtered, but because `Verdict` was already built that way in 001 and 003:
`matched_entities[]` references a watchlist `entry_id` and a `subject_ref`, and
`reasons[]` is templated from rule evidence (`entry_id`, `name_score`,
`corroboration_basis`, `missing_docs`, `shell_signals`). The only identifier in
it is `applicant_id`, which is the caller's own. §7 is what keeps that true of
the trace as well.

## 5. The orchestrator

```
packet
  │
  ├─ load_brain(pointer)                       503 if it does not validate
  ├─ extract(packet, brain, client)            one model call, floored (D-008)
  ├─ from_packet(packet, extraction, settings) the facts bag, minus hits
  ├─ sweep(screening_targets, min_name_score)  hits, by permutation (D-009)
  ├─ evaluate(brain, facts)             ────▶  verdict₀   ← deterministic, final if the loop adds nothing
  │
  ├─ propose(brain, facts, targets, client)    the naive agent, with the tool
  │     ├─ it returns names, never scores
  │     └─ sweep(new names) ∪ hits
  │
  ├─ evaluate(brain, facts')            ────▶  verdict₁   ← severity ≥ verdict₀
  ├─ assert_no_auto_clear(facts', verdict₁)
  └─ case file + trace
```

`verdict₀` is computed and recorded **before** the proposal runs. That ordering
is the whole safety argument, and it is worth stating as a property rather than a
hope:

> The union only adds hits, and `evaluate` takes the most severe finding among
> all that fired. Adding a hit can therefore only add findings, and can only
> raise the decision's severity or leave it unchanged. **The loop cannot
> introduce a false clear.** It can only escalate.

What it *can* do is vary. If the model proposes a different set of names on
different runs, `verdict₁` may differ between runs where `verdict₀` never does.
That is the one place a sampling step touches the decision in this system, and
D-011 is the decision to allow it under a measured condition with a stated way
back.

`confidence` is not monotone in the same way — it is the minimum over the
findings carrying the winning decision, so a second corroborated hit can lower
it. That is correct behaviour and is called out here only so nobody reads
"monotone" as covering more than the decision.

## 6. The proposal, and the loop

One model call, carrying the `base_heuristic` prompt from the Brain (D-007), with
`watchlist_search` bound as a real tool.

**What it sees**: the facts bag, the hits found so far, and the names in
`screening_targets[]`. That is enough to reason about the case and enough to
search.

**What it does not see**, and both omissions are load-bearing:

- **Not the policy text.** A step that reads the rule table is not carrying the
  naive instruction any more; it is the rule table with extra steps, and the
  override would be theatre.
- **Not the documents.** APP-009's injection lives in `documents[].content`. This
  is the only step in the pipeline whose output schema has a `decision` field, so
  it is the only step where an injection would have somewhere to land. Feeding it
  free text would re-open exactly the slot D-008 closed. Facts and hits are
  already the product of a floored extraction; free text does not need to travel
  any further than that (D-010).

**The tool contract**: the model calls `watchlist_search` with a *name*. It never
supplies a score, an `entry_id` or a corroboration verdict. The orchestrator
executes the search through the same `sweep` 003 already ships — same
permutations, same union by `(subject_ref, entry_id)`, same
`brain.settings.min_name_score` — and returns the result. The model's entire
influence on `hits[]` is *which strings get searched*, which is monotone and
auditable (D-011).

This is the honest job the loop has, and it is exactly the gap D-009 admits: the
permutation heuristic recovers reordering and nothing else. A model that sees
`Ivanka Sokolov` come back at 0.966 against `Ivanka Sokolova` can try a
transliteration, a diacritic-stripped form or an initial — spellings no
permutation of the given tokens will ever generate.

**The budget.** `settings.max_steps_per_applicant` (12) and
`settings.request_timeout_seconds` (120) finally have something to guard. A step
is one model turn. When the budget is exhausted the loop stops, the trace records
`budget_exhausted`, and the run continues: hits found so far stand, and the Brain
decides as it always would. **The verdict never depends on the loop finishing** —
that is what makes a timeout a degraded run rather than a failed one.

A tool call the model malforms — a missing argument, a non-string name, an empty
one — is answered with an error result and counts against the budget. It does not
raise, because a naive agent fumbling its tool is not a service fault.

## 7. The trace

One object per run, returned in the response and written to the log **byte for
byte identical**. There is no redacted variant and no full variant, because there
is nothing to redact: the schema has no field that can hold PII (D-012).

| event | records |
|---|---|
| `run` | `run_id`, `applicant_id`, `policy_version`, `brain_hash`, `watchlist_hash`, model, total duration, total tokens, total cost |
| `extract` | duration, `usage`, cost, retry count, documents classified by kind, shell signals, target count and refs, `injection_suspected`, `dropped_targets` |
| `screen` | duration, searches performed, and per hit: `entry_id`, `subject_ref`, `name_score`, `corroborated`, `corroboration_basis`, `name_variant` |
| `evaluate` | duration, `fired_rules`, decision, confidence — recorded **twice**, for verdict₀ and verdict₁ |
| `propose` | duration, `usage`, cost, steps used, budget outcome, and per tool call: ordinal, token count of the searched string, whether it hit, and the `entry_id` and score if it did |
| `override` | proposed decision, final decision, whether they differ, and the rule id that decided |
| `guardrail` | that `assert_no_auto_clear` ran and passed |

The searched string itself is **not** recorded — only its ordinal, its token
count, and its outcome. A watchlist `entry_id` is public list data and identifies
the entity that matched; the applicant's spelling of a person's name is the PII.
Hashing the string was rejected: a full-name space is small enough that a hash is
a dictionary lookup away from the plaintext, which is a redaction that reads like
one without being one (D-012).

**Cost accounting** is a price table keyed by model in `agent/pricing.py`, not in
the Brain — the price of a token is not policy, and putting it in a version
directory would make `brain_hash` change when Anthropic changes a rate card.
Input, cached input, cache writes and output are priced separately, because the
whole point of the cached prefix is that those rates differ.

**Where it goes**: structured JSON, one line per run, to stdout and to
`traces/` on the mounted volume. Sample traces are committed under
`observability/samples/` — the brief asks for them as a deliverable, and a
committed sample is also a regression fixture for the shape.

## 8. What the live call will touch

Not implemented here, and the seam is named so the 20 minutes are wiring rather
than discovery:

- `location_validation` is already a declared fact with a rule-less slot in
  `constants.py`, exactly like `injection_suspected`.
- The new **fact source** is a geolocation call; it plugs in beside
  `from_packet`, which is the one function that reads the packet.
- The new **rule** is one entry in `rules.yaml` and a paragraph of prose — a
  version swap, no code.
- The request grows a caller-supplied IP. `/screen` deliberately does **not**
  ship an ignored field for it today; a slot with no sensor is the kind of thing
  that looks staged, and adding it live is two lines.

## 9. Layout

```
agent/
├── orchestrate.py   # the composition of §5, and the only place the steps are ordered
├── proposal.py      # base_heuristic + watchlist_search as a real tool, bounded
├── trace.py         # emitting the events of §7 to both sinks, identically
├── pricing.py       # per-model rates; cost is arithmetic over usage
├── llm.py           # + tools on the protocol, and a turn that asks for one
└── schemas.py       # + CaseFile, Proposal, SearchRecord, RunTrace and its events
api/
├── auth.py          # the two bearer guards, so neither route reimplements one
├── screen_routes.py # POST /screen, bearer auth, the 503 condition shared with /health
└── main.py          # + the router
tests/
├── test_orchestrate.py       # the 12 labels through the orchestrator, the case file contract, the guardrail
├── test_proposal.py          # what the naive agent is shown and what it is not, and the override field
├── test_proposal_loop.py     # budget exhaustion, malformed tool args, monotonicity, order independence
├── test_trace_has_no_pii.py  # every string in every trace against every name/DOB/address in all 18 packets
├── test_screen_endpoint.py   # 200, 401, 422, and 503 when the Brain is unloadable
└── test_screen_live.py       # marked live: APP-011 and APP-009 end to end against the real model
```

The dependency line extends without bending: `constants ← schemas ← {llm,
extraction, screening, corroborate, pricing} ← facts ← rules ← {proposal, trace}
← orchestrate ← api`. `trace.py` imports no step, and no step imports `trace.py`
— events are returned by the orchestrator, not emitted from inside the steps, so
a step stays a pure function of its inputs and remains testable without a tracer.

The proposal is tested against a fake `StructuredClient`, the same way extraction
already is. The one live test is APP-011, because that is the assertion nobody
should be allowed to fake.

## 10. Acceptance criteria

1. `POST /screen` with a valid packet and token returns 200 with every field of
   the policy's output contract populated, plus `brain_hash`, `watchlist_hash`
   and `run_id`. Missing or wrong token → 401. Malformed packet → 422. Brain
   unloadable or watchlist absent → 503, the same condition `/health` reports.
2. All 12 labelled applicants reach the labelled decision **through the
   orchestrator**, for the labelled rule id, with the false-clear count zero. The
   003 result is preserved, not re-derived.
3. **verdict₀ is recorded on every run** and, with a proposer that searches
   nothing, `verdict₁` is byte-identical to it for all 18 packets.
4. **Monotonicity holds**: for any set of names the proposal returns, the
   severity of `verdict₁` is greater than or equal to that of `verdict₀`. Tested
   with a fake proposer that searches every UBO name in the watchlist, not
   argued from the code.
5. The loop respects its budget: a proposer that searches forever stops at
   `max_steps_per_applicant`, the trace says `budget_exhausted`, and the run
   still returns a case file. A malformed tool call is answered with an error
   result and does not raise.
6. The proposal step's prompt contains **no policy text and no document content**
   — asserted against the rendered messages, over all 18 packets.
7. **No PII in the trace**: for every one of the 18 packets, no UBO name, no
   business legal name, no date of birth, no address line and no substring of any
   document longer than a threshold appears anywhere in the serialised trace.
   Asserted over the bytes, not over a list of fields somebody remembered.
8. The trace returned in the response and the trace written to the log are
   byte-identical.
9. The trace carries a cost and a latency for every model call, and the run total
   equals the sum of its parts.
10. `override` is recorded on every run — including runs where the proposal
    agrees, which is what makes the field evidence rather than decoration.
11. The never-auto-CLEAR guardrail runs after the **final** verdict, and the
    trace records that it ran.
12. **Determinism with the loop on**: five real runs over the 12 labelled
    applicants produce one distinct serialisation of `(decision, reasons[],
    matched_entities[], hits[], missing_docs[], confidence)` per applicant — the
    same property 003 measured, with the loop now inside it.

    **Measured, and it failed on the first attempt.** 60 real runs: all 12
    decisions correct in all 5, but **6 of 12 applicants produced more than one
    serialisation** — APP-009 four of them. Every difference was a *duplicate*:
    a model-initiated hit on an entity the deterministic sweep had already
    found, under the synthetic `proposed` subject, at whatever score the
    spelling the model happened to try scored (`EU-2001` at 0.875, 0.968 or 1.0
    beside `ubo[0]`'s 1.0). Across all 60 runs the model found **no entity the
    sweep had missed**.

    The fix follows from what the failure was: a model-initiated hit whose
    `entry_id` is already in `hits[]` is dropped. It cites nothing new and fires
    no rule that has not fired. Replayed over the recorded runs, that collapses
    all 12 applicants to exactly one serialisation each (D-013).

    What remains is stated rather than glossed: a model-initiated hit on an
    entity the sweep missed entirely *does* still reach the verdict, and two
    runs could differ if the model finds one and then does not. That never
    happened in 60 runs, and when it does happen it is an escalation — the
    direction that cannot produce a false clear.
13. `uv run pytest -q` passes with `ANTHROPIC_API_KEY` unset and no network, with
    nothing skipped that this spec added except the one live test.

## 11. Decisions this spec produces

| | |
|---|---|
| **D-010** | The adjudication proposal sees facts and hits, never the policy and never the documents. Forced by two requirements meeting: the brief wants the agent's base instructions visibly overruled by the Brain, and it wants the APP-009 injection to have nowhere to land. This is the only step whose output schema has a `decision` field, so it is the only step where injected text would find a slot; and a step that reads the rule table is not naive any more. Rejected: giving it the documents so it can propose name variants from the text — extraction already extracts names, under a floor, with a schema that has no decision in it. |
| **D-011** | Model-initiated searches add names, never scores, and the verdict is computed twice. The model returns a string; the deterministic sweep executes it with the same permutations, threshold and union as 003. `verdict₀` is recorded before the loop and `verdict₁` after, and since the union only adds hits and the engine takes the most severe finding, severity is monotone: the loop cannot introduce a false clear. What it can do is vary between runs, which is the one sampling step touching a decision in this system. Allowed under criterion 12; if the five-run hash is not one per applicant, model-initiated hits are demoted to trace-only and the system returns to 003's structural determinism. Rejected: making a model-found match a declared fact with no rule in v1, the `location_validation` pattern — it keeps determinism structural, but a genuine sanctions match found by the model would not block, which is a false clear by construction. Safety wins over determinism when they disagree, and the policy's own posture is "when in doubt, REVIEW". |
| **D-012** | PII stays out of the trace by construction, not by a redaction pass. The trace schema has no field that can hold a name, a date of birth, an address or a quoted span; model-initiated searches are recorded as an ordinal, a token count and an outcome. One consequence is that the response trace and the log trace are the same bytes, which a test asserts. Rejected: a redaction filter over a trace that carries PII — a filter is a list of fields somebody has to remember to update, and the failure mode is silent. Rejected: hashing the searched name — a full-name space is small enough that the hash is a lookup away from the plaintext. |

Written when the code they govern lands, in the append-only format in
`.claude/skills/log-decision/`, and referenced from the commit that implements
them.

## 12. Risks

- **The loop is the only thing in the system that can break determinism.** It is
  bounded, monotone in severity and measured by criterion 12, and D-011 carries
  the way back. Stating it plainly is better than discovering it during a demo.
- ~~**The model may refuse to be naive.**~~ **It did.** Eleven runs, zero
  overrides (§3). Reported as found rather than tuned around. The consequence is
  that the override demonstration moves to the deterministic ablation — the same
  applicant against two Brain versions — which was always the stronger form of
  the claim and needs no model at all.
- **The second model call roughly doubles per-applicant cost.** Today's figure is
  $0.0094 and 5.6 s, all of it extraction. The proposal's prefix is the
  `base_heuristic` prompt, far under the 512-token minimum cacheable prefix, so
  **nothing on that call is cached** — the arithmetic is not "half again", it is
  measured after the step lands and reported in `DESIGN.md` beside the other two
  sweeps.
- **The no-PII test can be falsely reassuring.** Substring matching over short or
  common names produces neither false negatives nor confidence; a name like `Li`
  would match text that has nothing to do with the applicant. The test is written
  to fail loudly on real leaks over the real 18 packets, and the structural claim
  — no field exists that can hold the value — is what actually carries the
  guarantee.
- **This is the largest spec and the call is tomorrow.** The commit order is
  therefore chosen so value lands first and the riskiest thing lands last:
  (1) `/screen`, case file, trace, PII — the Definition of Done's main sentence;
  (2) the proposal, which makes the override observable; (3) the tool loop, which
  is the only piece that can be dropped without leaving a hole. If (3) does not
  land, 004 is still complete against everything the brief names explicitly.
