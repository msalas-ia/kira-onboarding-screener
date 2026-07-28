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
