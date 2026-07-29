# Decisions

Judgment calls forced by an ambiguity in the brief or a tension between two of its
requirements, written when the code they govern lands. Append-only: a reversal
gets a new entry and the superseded one is left untouched.

Choices made freely — Python, uv, FastAPI, self-hosted deployment, no agent
framework — are not here. They are in `DESIGN.md`, next to what was built. The
test is whether the brief would still be satisfied had the opposite been chosen.

---

## D-001 — The decision never passes through a sampling step (2026-07-27)

The brief demands the agent be agentic — real tool calls and control flow, not one
prompt — and simultaneously deterministic, with a false-clear rate of zero. Those
pull against each other: hosted inference is not bit-for-bit reproducible, and
`temperature`, `top_p` and `top_k` are rejected with HTTP 400 on current models, so
the traditional lever for pinning an LLM down no longer exists.

Responsibilities are split by which side is actually good at the job. The LLM owns
free-text understanding — extraction from `documents[]`, where the prompt injection
also has to be resisted. Deterministic code owns screening coverage, corroboration,
and adjudication: `decision`, `confidence` and `reasons[]` are computed by a rules
engine over a facts bag, never sampled.

The alternative was a single LLM call deciding everything, with determinism
asserted rather than constructed. It was rejected because the headline metric is
false-clear rate at zero, and "the model was consistent across the runs we tried"
is not the same claim as "the decision cannot vary."

- Screening runs unconditionally, so no document can suppress it — which is what
  makes APP-009's injection structurally unable to reach the verdict.
- The rules engine must be generic over policy data, or the Brain stops being
  authoritative and becomes a document that merely agrees with the code.
- Determinism is still verified empirically in the eval suite rather than assumed.

## D-002 — The rule table lives beside the policy, not inside it (2026-07-27)

The Brain says "do NOT hardcode these rules into the prompt/code — load them as
data", so the nine rules need a machine-readable form. But `screening_policy.md` is
the delivered authoritative document, and CI diffs it against `assets/` to prove it
has not drifted. Embedding a YAML block in it would satisfy the first requirement
by destroying the second.

Each version directory holds both: `screening_policy.md` byte-identical to the
bundle, and `rules.yaml` as its machine-readable projection. A Brain version is the
directory, hashed as one unit.

The rejected alternative — a fenced block inside the markdown — keeps everything in
one artifact and cannot drift, which is genuinely better in isolation. It was
dropped because it forfeits the claim that the authoritative text was never edited,
and turns the drift check into a fuzzy "the prose parts still match" comparison.

- The two files can now disagree. `tests/test_policy_sync.py` parses the decision
  matrix out of the prose and compares it against the table.
- Adding a rule in the live call is two edits, not one: a prose paragraph and a
  table entry.

## D-003 — Corroboration needs one comparable pair to agree (2026-07-27)

The policy defines corroborated as "strong name similarity AND the DOB matches (or
the country/nationality is consistent)", and unconfirmed as the case where the DOB
conflicts, the country differs, "or the corroborating fields are missing." Those
two sentences do not cover the same ground: they disagree about a field that is
absent on *both* sides, which is not a conflict and not a match.

Adopted reading: a hit is corroborated when at least one comparable pair of fields
agrees. A field missing on both sides is not comparable, and contributes nothing
either way rather than counting as a conflict.

The stricter reading — a missing DOB always means unconfirmed — was rejected
because it makes the country comparison unreachable for every entity without a date
of birth, which is every company on the watchlist. Under that reading Rule 1 could
never fire for a business, and the policy clearly intends businesses to be
screenable.

- `Zephyr Logistics FZE` (APP-015) has no DOB on either side and AE = AE, so it is
  corroborated → BLOCK. Under the stricter reading it would be REVIEW.
- Both readings are non-CLEAR, so the false-clear rate is unaffected either way.
  That bounded downside is what makes this safe to decide rather than escalate.
- Every hit carries `corroboration_basis` into the trace, so which pair agreed is
  visible per run and the reading can be reversed without re-deriving it.

## D-004 — Rule 6's "UBO list" is a populated array, not a document (2026-07-27)

Rule 6 reviews an applicant with "no certificate of incorporation, or no UBO list".
Read as a document type, `ubo_declaration` becomes mandatory. Read as data, the
`ubos[]` array must be non-empty.

Adopted: the incorporation certificate is a document; the UBO list is a populated
`ubos[]` array.

The document reading contradicts the labelled set in both directions, which settles
it: APP-001 is labelled CLEAR and has no `ubo_declaration`, and APP-017 has an
incorporation document with `ubos: []`. Any reading that fails a label it was given
is the wrong reading.

- The required-document set lives in Brain settings, each entry naming the boolean
  fact that proves it, so this reading is policy data rather than an assumption
  compiled into the engine.
- Detecting the incorporation document still needs semantic normalisation: the
  bundle spells it `certificate_of_incorporation` once and `incorporation`
  sixteen times. Comparing type strings literally would fail most applicants.

## D-005 — Rule 9 gets no entry in the table (2026-07-27)

Rule 9 says a pure name collision to a different entity is not a hit and may be
CLEAR. Rule 2 says an unconfirmed sanctions near-match is REVIEW, never CLEAR. An
uncorroborated near-match satisfies both descriptions, and they give opposite
answers — which is precisely the situation APP-011 is built out of.

Rule 9 is documented in the table's comments and implemented nowhere. Rules 2, 3
and 4 catch every name hit, and since the engine takes the most severe outcome
among all rules that fired, a CLEAR rule cannot lower a verdict another rule
raised.

Entering it as a real rule was rejected on the grounds that it would be dead data
that reads like an escape hatch from Rule 2 — the exact failure the override demo
exists to catch. The policy's own posture settles the tie: "when in doubt, REVIEW",
and never auto-CLEAR anything that produced a name hit.

- No applicant in the bundle is a genuine cross-entity collision, so nothing is
  lost in practice; the choice only binds on hypothetical inputs.
- A regression test asserts the inertness directly, so a future edit that makes
  Rule 9 reachable fails the build rather than silently clearing an applicant.

## D-006 — The evaluation date is Brain data, not the clock (2026-07-27)

Rule 7 counts "formation < 90 days" as a shell-company signal. That is a comparison
against *now*, and the brief requires the same applicant and the same Brain to
produce an identical decision on every run. A `datetime.now()` anywhere on the
decision path makes the verdict a function of the day it was computed.

`as_of_date` is a setting in the Brain, pinned to 2026-07-27, and the 90-day window
sits beside it. Company age is derived from those two values and never from the
system clock.

Threading a caller-supplied date through the API instead was rejected as a way to
move the non-determinism rather than remove it: the same request would still decide
differently depending on what the caller sent.

- Verified decision-neutral across all 18 applicants. The most recent formation in
  the bundle is 2025-12-01, and APP-008 already reaches Rule 7's two-signal
  threshold on nominee director plus mass-registration address alone — so no label
  depends on where the date is pinned.
- A test asserts that no module under `agent/` reads the wall clock at all.
- The pinned date will need review in any real deployment. Recorded as a failure
  mode in `DESIGN.md` rather than left as a silent constant.

## D-007 — The system prompts are Brain artifacts, not code (2026-07-27)

The brief asks for "the Company Brain **and prompt**" to be versioned and
updatable without a code rewrite, and gives one mechanism for doing that:
`/brain/activate` over a mounted volume, with `brain_hash` as the identity of the
policy state. A prompt living in Python satisfies the sentence's first half and
leaves the second half outside the mechanism — the artifact would be versioned by
git, which versions the repository, not the running container.

Each version directory gains `prompts/`, and `rules.yaml` declares a role → path
mapping. Roles are a closed vocabulary in `constants.py`, exactly like the facts
vocabulary: an unknown role, a missing file, an empty one, or a path that escapes
the version directory fails the load. Code asks for a prompt by role, never by
path. The hash covers prose, table and every prompt, in sorted role order.

The rejected alternative was prompts as module constants, versioned by git and
shipped on deploy. It is simpler and needs no loader work, but it cannot be
swapped on a running container, so the ablation the policy asks for — same
applicant, base heuristic versus Brain — would be a code branch rather than two
versioned artifacts, and a code branch is exactly what a reviewer should suspect
of being staged.

- v1's `brain_hash` changes the moment the prompts land. That is the mechanism
  working: the prompt is now part of what "same Brain state" means.
- Re-authoring a prompt is a version swap; adding a *role* is still a code
  change, which is the same line the facts vocabulary draws.
- `base_heuristic.md` now lives in the Brain, so spec 003's proposal step reads
  the naive rule from policy data rather than from a constant.

## D-008 — Extraction can raise severity, never lower it (2026-07-27)

Two requirements meet on this step. The brief demands resistance to the injection
in APP-009, and it demands a false-clear rate of zero. Extraction is the one place
where a document's own text reaches the fact path, so anything the model is
trusted to *remove* is a suppression path: a model persuaded to report no shell
signals turns APP-008 from REVIEW into CLEAR, and nothing downstream can tell.

The model's output is unioned with a deterministic floor computed from the same
packet — document `type` strings, `ubos[].role`, and pattern matches over document
content. Shell signals, screening targets and the injection flag are the union of
both. The model can add; it cannot subtract.

Trusting the schema-constrained model alone was rejected. It is simpler, and it is
still what the document-classification path has to do, but it makes the zero
false-clear target contingent on the model not being fooled by a document written
specifically to fool it.

- `has_incorporation_doc` is the stated exception: detecting a document that
  exists is inherently de-escalating, so monotonicity cannot apply. It is guarded
  differently — index-bound to documents the packet already contains, a closed
  label set, and a span quoted verbatim from that document. The model can
  mislabel one of N documents; it cannot invent one.
- Extraction fails closed. There is no partial result, because an empty
  extraction reports no shell signals, which is the unsafe direction.
- The floor's patterns are a detection heuristic and live in Python. Rule 7's
  threshold stays in the Brain, so no policy value moved into code.

## D-009 — Recall is bought with more calls to the delivered tool, never a new matcher (2026-07-28)

Two requirements meet on this step, again. The brief hands over a reference
`watchlist_search` and says to use it as-is or reimplement it, and it demands a
false-clear rate of zero. Those disagree: `difflib.SequenceMatcher` compares
strings positionally, so a name whose tokens are reordered scores far below the
policy's 0.75 threshold and screens clean. Measured against the delivered
watchlist, `Kravchenko Olena` scores **0.625** against PEP-3004, `Petrov Viktor`
**0.545** against OFAC-1001, `Sokolova Ivanka` **0.533** against EU-2001 and
`Al-Rashid Muhammad` **0.500** against OFAC-1003. Every one of those is a
sanctions or PEP entity clearing silently, and the grading holdout is described
as similar cases the dev set does not show — six watchlist entries are
unexercised by it, `Olena Kravchenko` among them.

The tool is used **byte-identical and imported in place**: there is exactly one
copy of that file in the repository and it is the delivered one, so drift is
impossible by construction rather than by a CI check. What changes is
orchestration, which the tool contract already assigns to the agent: each target
is searched once per token permutation of its name, and results are unioned by
`(subject_ref, entry_id)` keeping the strongest score. All four names above come
back at **1.0**, and over the 18 delivered packets the variants add **zero** hits
and lose none — 9 before, 9 after.

Reimplementing the scorer with a token-sorted comparison was rejected. It reaches
the same recall with the same zero added hits, and it is less code, but it
replaces the delivered artifact with our own on the one path a reviewer reads
most carefully. Leaving the miss alone was also rejected: it is a false clear by
construction, on the metric the brief requires to be zero.

- The union is monotone. More calls can only raise a score or add an entry, never
  remove one, so this cannot turn a hit into a non-hit.
- `min_score` still comes from `brain.settings.min_name_score`. No policy value
  moved into code; permutation is a fact about how names are written, not about
  what counts as a match.
- Permutations recover reordering only — not transliteration, diacritics or
  initials. A real deployment needs a name-matching library, and saying so is
  better than pretending this generalises.

## D-010 — The proposal sees facts and hits, never the policy and never the documents (2026-07-28)

The brief wants the agent's base instructions visibly overruled by the Company
Brain, and it wants APP-009's injection to have nowhere to land. The adjudication
proposal is where those two meet, because it is the only step in the pipeline
whose output schema has a `decision` field — the slot D-008 deliberately removed
from extraction.

It is given the facts bag, the watchlist tool's own output, and the names being
screened. Not the policy text, because a step that can read the rule table is not
carrying the naive instruction any more; and not `documents[].content`, because
that is where the injection lives and this is the one place it would find
somewhere to write. The injection reaches the step as a boolean, which is all a
decision could legitimately need from it.

`corroborated` and `corroboration_basis` are withheld for the same reason as the
policy text: corroboration is a conclusion the policy defines (D-003), so showing
it leaks the rule table into the step built to reason without one. A first
implementation showed them; removing them changed no proposed decision.

Rejected: feeding it the documents so it can propose spellings read from the free
text. Extraction already reports names, under a floor, with a schema that has no
decision field — the same capability without the exposure.

- The measured result is that the model does not follow the naive heuristic:
  eleven runs, zero overrides, including APP-011 where it is handed a 0.966
  non-exact sanctions match and proposes REVIEW anyway.
- That is reported rather than tuned around. It means the override demonstration
  the brief asks for rests on the deterministic ablation — one applicant, two
  Brain versions — and not on a model needing to be overruled.
- `override` is still written on every run, agreement included. A field that only
  appears on disagreement is a demonstration mode, not an instrument.

## D-011 — Model-initiated searches add names, never scores (2026-07-28)

Giving the model `watchlist_search` as a real tool is the only place in this
system where a sampling step can move a decision: a search it initiates can add a
hit, and a hit changes the verdict. That is in tension with what spec 003
achieved, where determinism stopped being a measurement and became a property of
the call graph.

The model returns a **string**. It never supplies a score, an `entry_id` or a
corroboration verdict. The orchestrator executes the search through the same
`sweep` spec 003 ships — same permutations, same union, same
`brain.settings.min_name_score` — so the model's entire influence is which
spellings get searched. The verdict is computed twice: `verdict₀` before the loop
and `verdict₁` after. Because the union only adds hits and the engine takes the
most severe finding among those that fired, severity is monotone: **the loop
cannot introduce a false clear.** It can only escalate.

A hit found this way is attributed to a single synthetic subject, `proposed`, and
can never corroborate — a spelling the model tried is not an identity the packet
declared, so there is nothing to compare it against. For a sanctions entry that
is Rule 2, REVIEW, which is the same treatment spec 003 already gives
document-sourced names. Attributing it to one subject rather than one per call is
what makes the same two searches in either order the same verdict.

The honest job this has is the gap D-009 admits: permutations recover reordering
and nothing else. Measured, the model reaches `EU-2001` at 1.0 from APP-011's
`Ivanka Sokolov` — a spelling no permutation of those tokens can generate.

Rejected: making a model-found match a declared fact with no rule in v1, the
`location_validation` pattern. It keeps determinism structural, but a genuine
sanctions match found by the model would then not block, which is a false clear
by construction. Safety wins over determinism when they disagree, and the
policy's own posture is "when in doubt, REVIEW".

- The budget is real: `max_steps_per_applicant` and `request_timeout_seconds` now
  guard something. Exhausting either stops the loop and the run continues — the
  verdict never depends on the loop finishing, so a timeout is a degraded run
  rather than a failed one.
- A malformed tool call is answered with an error result and costs a step. A
  naive agent fumbling its tool is not a service fault.
- What this costs is measured in `DESIGN.md`, not asserted: the criterion is five
  runs over the twelve labelled applicants producing one verdict serialisation
  each, with the loop on.

## D-012 — PII stays out of the trace by construction, not by a redaction pass (2026-07-28)

The brief requires no PII in logs. A redaction filter is a list of fields
somebody has to remember to update, and its failure mode is silent: the day a new
field carries a name, the filter does not know and nothing fails.

The trace schema has no field that can hold a name, a date of birth, an address
or a quoted span. `Hit` already referenced subjects by index rather than by name;
extraction is described by counts, kinds and refs; and a model-initiated search
is recorded as an ordinal, a token count and its outcome. The defence is the
absence of a slot, which is the same shape as extraction's missing `decision`
field.

One consequence is worth having on purpose: there is a single serialisation, so
the trace returned to a caller and the trace written to the log are the same
bytes rather than merely equivalent. `/screen` composes its response body from
the emitted line so this stays true, and a test asserts it.

Rejected: hashing the searched name. A full-name space is small enough that a
hash is a dictionary lookup away from the plaintext — a redaction that reads like
one without being one.

- Checked over the bytes rather than over a field list: 75 identifying values and
  41 document phrases drawn from all 18 packets, none of which appear in any
  trace, including runs where the model is primed to quote a UBO name and a date
  of birth verbatim.
- Watchlist `entry_id`s are recorded freely. They identify a listed entity, which
  is public list data, not the applicant.
- The case file was already clean for the same reason — `reasons[]` is templated
  from rule evidence and `matched_entities[]` carries refs — so the only
  identifier a caller gets back is the `applicant_id` they sent.

## D-013 — A model-initiated hit on an entity already found is dropped (2026-07-28)

D-011 allowed the tool loop to feed `hits[]` on a measured condition: five runs
over the twelve labelled applicants, one verdict serialisation each. The
measurement failed. Sixty real runs produced the correct decision every time, but
**six of the twelve applicants serialised more than one way**, APP-009 four ways.

What varied was not which entities were found. Every difference was a *duplicate*
— a model-initiated hit on an entity the deterministic sweep had already matched,
under the synthetic `proposed` subject, carrying whatever score the spelling the
model happened to try that run scored. On APP-009 `EU-2001` appeared at 0.875,
0.968, 1.0, and on one run not at all, always beside `ubo[0]`'s exact 1.0. Across
all sixty runs the model found **no entity the sweep had missed**.

So the rule is: a model-initiated hit whose `entry_id` is already in `hits[]` is
dropped before the second evaluation. It cites nothing new, it fires no rule that
has not already fired on that entity, and it was the entire measured instability.
Replayed against the recorded runs, this collapses all twelve applicants to one
serialisation each.

Rejected: D-011's own stated fallback, demoting every model-initiated hit to
trace-only. It restores determinism completely, and it was the right thing to
pre-commit to before knowing what the instability would look like — but the
measurement showed the instability was entirely redundancy, so demoting
everything would have paid for determinism with the one case the loop exists for.

- The residual is stated rather than glossed. A hit on an entity the sweep missed
  entirely still reaches the verdict, so two runs could differ if the model finds
  one and then does not. That never occurred in sixty runs, and when it does it
  is an escalation — the direction that cannot produce a false clear.
- `hits_added` and `hits_redundant` are separate counters in the trace, because
  only the first can move a verdict and only the first can make two runs differ.
- Nothing is hidden by the drop: every entity every search returned is already
  recorded in `propose.searches`.

## D-014 — The naive baseline is a Brain version, not a prompt (2026-07-28)

The brief requires showing the Company Brain overrule the agent's base
instructions, and D-010 measured that the model does not need overruling: eleven
runs carrying the naive heuristic, zero overrides, including APP-011 where it is
handed a 0.966 non-exact sanctions match and proposes REVIEW anyway. The
demonstration the brief asks for therefore has nothing to rest on unless it stops
being a claim about a prompt.

`company_brain/versions/v0-naive/` is the naive heuristic promoted from an
instruction into a rule table: an exact sanctions match blocks, everything else
clears. Its settings and its prompts are byte-identical to v1, so the rule table
is the only variable and a difference in decisions measures the rule table.
`compare()` refuses to run if the two disagree on settings, so that claim is
enforced rather than commented.

Rejected: tuning `base_heuristic.md` until the model misbehaves. That
manufactures the demonstration rather than performing it, and spec 004 §12
committed to reporting the finding before the number came back. Rejected: a code
branch that skips the Brain — which is precisely what a reviewer should suspect
of being staged.

- Measured over the 18 delivered packets: the two policies disagree on **10**, and
  on **7 of the 12 labelled**, reproducing spec 004 §3's Python simulation
  exactly. Every disagreement is in the CLEAR direction.
- **The never-auto-CLEAR guardrail catches 5 of those 10 and no more.** It sees
  the ones carrying a watchlist hit and is silent on APP-005, 006, 008, 017 and
  018, where the correct verdict comes from MCC risk, missing documents or shell
  signals. Under a wrong policy, half the false clears are refused at runtime and
  half are served. That is the argument for an eval suite existing, and it is
  pinned by a test rather than described.
- The ablation runs the rules engine over one facts bag, with no model and no
  network, so it gates on every run rather than on the ones somebody paid for.
- Shipping a deliberately unsafe policy on a writable volume is a real trade. It
  is admin-token guarded, a deploy restores the committed pointer, and the
  guardrail refuses the half of its output that carries a hit.

## D-015 — A false clear is defined by construction, and the labelled rate is reported beside it (2026-07-28)

The brief names "false-clear rate, target zero" without stating a denominator.
The plan's reading — the labelled applicants whose ground truth involves a
watchlist hit — has a property that disqualifies it as the *gating* definition:
it cannot be computed for anyone nobody has scored, which is every applicant in
the hidden holdout and six of the eighteen packets in the bundle, two of which
carry real hits.

The gating definition is therefore structural: a false clear is any run where
`hits[]` is non-empty and the decision is `CLEAR`. It needs no labels, so it
means the same thing on the dev set, on the unlabelled packets and on an
applicant nobody has ever seen. The labelled rate is computed and reported beside
it, with its denominator printed, because those are the words the brief uses.

Rejected: gating on the labelled rate alone, which would leave the six unlabelled
packets measured by nothing.

- The hit-bearing denominator is **derived from the labels** rather than listed
  in code: a label is hit-bearing when its reason cites a watchlist entry id. An
  edited label cannot leave a stale set behind, and a test guards the pattern
  against matching the dates in APP-011's reason.
- The two gates fail independently, and a test drives exactly that case: a false
  clear on an unlabelled applicant fails the structural gate while the labelled
  rate stays at zero, which is the situation the holdout is made of.

## D-016 — The eval gate runs the production configuration, and the pull request pays for it (2026-07-28)

The brief requires CI to fail the build if the false-clear rate is above zero or
the determinism check fails. Spec 004 measured the adjudication loop at four
times the cost of everything else combined, so running the gate as production
runs it is $1.53 per gated run — 36 real calls over the twelve labelled
applicants, three times each.

The gate keeps the loop on, the model the same, and the code path identical to
the one production executes. What changes is *when* it fires rather than what it
validates: the unit job runs on every push and costs nothing, and the eval job
runs on non-draft pull requests and on manual dispatch — not on the merge, because
`main` is protected on that check and `strict` requires a pull request to be up to
date before merging, so the tree that lands is the tree the gate already measured.

Rejected: `MAX_STEPS_PER_APPLICANT=0` in CI, at $0.11. It is not merely cheaper,
and the argument for it is better than a cost argument — D-011's monotonicity
makes a false-clear rate of zero measured with the loop **off** a proof that it
is zero with the loop on, because `verdict₀` is the least severe verdict the
system can reach. But determinism is precisely the property the loop threatens,
and D-013 exists because that measurement failed the first time it was taken. A
gate blind to the only risk it exists to catch is a different gate, not a cheaper
one. Rejected: fixture-driven evals, which cost nothing and assert nothing about
the model.

- Two exit codes, because two bad days are not the same event: `1` is a gate
  failing, which is a fact about the change; `2` is the suite being unable to
  measure — an unreachable model, an unloadable Brain, a budget refusing to
  overspend. There is no retry, because a gate that retries until it passes is a
  gate that passes.
- The distinction was not theoretical. The first real run met an out-of-credit
  key and surfaced as a traceback rather than as exit 2, because `ExtractionFailed`
  is the exception that actually arrives on that path and it was not caught.
- `--max-cost-usd` is enforced rather than documented: the suite stops as soon as
  the accumulated cost crosses the limit, so the overshoot is bounded by what was
  already in flight.
- The live tests are excluded from the unit job explicitly with `-m "not live"`,
  rather than by the key being absent, because the eval job needs that key in the
  same workflow.
