# Design

Current state of the system and the reasoning behind it. Sections are rewritten
in place as the architecture changes — this is a snapshot, not a log. Judgment
calls forced by ambiguity in the brief are recorded separately in `DECISIONS.md`.

## Pipeline

One applicant packet in, one case file out.

```
packet
  │
  ├─▶ load Company Brain          active_version.json → policy + rules + prompts
  │
  ├─▶ extract                     documents[] → facts        (LLM ∪ floor)
  │                               doc types, shell signals, name variants
  │                               unioned with a deterministic floor over the
  │                               same packet, so the model can only escalate
  │
  ├─▶ screen                      business + every UBO       (deterministic)
  │                               + supplementary names from extraction,
  │                               each searched once per token permutation
  │                               of its name, unioned by (subject, entry)
  │
  ├─▶ corroborate                 DOB / country per hit      (deterministic)
  │
  ├─▶ adjudicate                  LLM proposes ─┐
  │                               Brain rules ──┴─▶ decision (deterministic)
  │
  └─▶ case file                   decision, confidence, reasons[],
                                  matched_entities[], missing_docs[],
                                  policy_version
```

Every step emits a trace event. The adjudication step records both the model's
proposal and the Brain's verdict, so an override is visible on every run rather
than only in a special demonstration mode.

## Where the LLM is, and where it is not

The brief demands the agent be **agentic** — real tool calls and control flow —
and **deterministic**: identical decision and reasons on every run, with a
false-clear rate of zero. Those pull against each other, so responsibilities are
split by which side is actually good at the job.

| Step | Owner | Why |
|---|---|---|
| Extraction | LLM, unioned with a deterministic floor | Free text. Document `type` strings are inconsistent across applicants and need semantic normalisation, and this is where the embedded prompt injection must be resisted. The floor reads the same packet with no model involved, and the merge is a union, so extraction can raise severity but never lower it (D-008). |
| Screening | Deterministic sweep, plus supplementary searches the LLM proposes for names it finds in documents | Coverage is a security invariant, not a judgment call. The model can only *add* searches, never remove one. |
| Corroboration | Deterministic | The policy defines it as a field comparison (DOB, country/nationality). Implementing a comparison the policy already specifies is not hardcoding. One agreeing comparable pair is enough (D-003); no comparable pair at all is unconfirmed, because missing identity is not confirmed identity. |
| Adjudication | LLM proposes, Brain rules decide | The proposal is what makes the override observable. |
| `decision`, `reasons[]`, `confidence` | Deterministic | The policy requires identical *reasons*, not just identical decisions. |

## Determinism

Determinism is structural, not statistical. Nothing that must be reproducible
passes through a sampling step: the verdict is computed by a rules engine over
deterministic facts, and `reasons[]` is templated from the rules that fired and
the watchlist entries they cite.

This matters more than it used to. `temperature`, `top_p` and `top_k` are
rejected with HTTP 400 on current models, so the traditional lever no longer
exists — and hosted inference was never bit-for-bit reproducible anyway. A design
that depended on sampling control would have no way to deliver what the brief
asks for.

The LLM still touches extraction, so its output is schema-constrained rather than
free-form, and repeated-run hashing verifies stability empirically rather than
assuming it. What is hashed matters: the check compares the **whole verdict** —
`decision`, `reasons[]`, `matched_entities[]`, `hits[]` and `screening_targets[]`
— not just the facts bag. An earlier version compared the facts bag alone, which
would have missed a model returning different supplementary names per run, since
those names never enter `Facts` but do enter the screening sweep. The property
asserted now matches the property the decision actually depends on.

Measured over 60 real runs — the twelve labelled applicants, five times each:
**one distinct serialisation per applicant, zero unstable fields**, and all twelve
labelled decisions correct on every run.

## The watchlist, and why it is not Brain state

`assets/tools/watchlist_search.py` is imported **in place and unmodified**. There
is exactly one copy of that file in the repository and it is the delivered one,
so drift between "the tool we ship" and "the tool we were given" is impossible by
construction rather than by a check that could be forgotten.

Its matcher compares strings positionally, which means a name whose tokens are
reordered scores far under the policy's threshold: `Kravchenko Olena` against the
PEP entry `Olena Kravchenko` scores 0.625 and screens clean. That is a false
clear, and the metric the brief requires to be zero. The fix is orchestration
rather than a new matcher — each target is searched once per token permutation of
its name and results are unioned by `(subject_ref, entry_id)`, keeping the
strongest score (D-009). The four reordered names measured come back at 1.0, and
over the 18 delivered packets the variants add zero hits and lose none. The union
is monotone: more calls can raise a score or add an entry, never remove one.

The watchlist itself is a **data feed, not policy**, so unlike the Brain it is
baked into the image rather than mounted — the brief asks for a hot-swappable
Brain, and a second writable mount would be surface with no demo behind it. Its
sha256 is reported by `/health` as `watchlist_hash` beside `brain_hash`, taken
from the file the tool itself resolved, so a stored decision is traceable to the
list state as well as the policy state. An instance without a watchlist returns
503: one that cannot screen is not ready.

`min_name_score` stays Brain data. Permutation is a fact about how names are
written, not about what counts as a match, so no policy value moved into code.

## The Company Brain

A Brain version is a **directory**, not a file. `company_brain/versions/vN/` holds
the authoritative prose — byte-identical to the delivered bundle, which CI checks
— `rules.yaml`, its machine-readable projection: the decision matrix, the MCC
set, the thresholds, the required-document set, the evaluation date, and the
confidence attached to each outcome — and `prompts/`, the system prompts, because
the brief asks for the Brain *and prompt* to be versioned and updatable without a
code rewrite (D-007). All of them are hashed together as `brain_hash`, reported by
`/health` and echoed in every verdict, so a stored decision can be traced back to
the exact policy state that produced it. `active_version.json` names the live
version and the one before it.

Prompts are addressed by **role**, never by path: `extraction` is read by the
extraction step, `base_heuristic` carries the naive "no exact match → lean CLEAR"
rule the policy explicitly permits and is read only by the adjudication proposal.
Re-authoring a prompt is a version swap on the same endpoint as a rule change;
adding a new role is a code change, the same line the facts vocabulary draws.

The rule table is executed by a generic evaluator that knows five operators and
nothing about compliance. It cannot produce a decision that is not in the table,
and a rule naming a fact the vocabulary does not declare fails to load rather than
silently evaluating false. A policy that will not execute never becomes active:
`POST /brain/activate` validates the target before the pointer moves, and
`/health` reports 503 if what is already active stops validating.

The Brain is **mounted into the container, not copied into the image**, which is
what makes three separate requirements fall out of a single mechanism:

- a version can be swapped without a rebuild or restart, and rollback is just a
  second swap;
- staging and production can run the same commit against different policy
  versions, which is what config-separated environments means here;
- the pointer is read fresh per request, so no cached value can outlive a swap.

Adding a rule that references an existing fact is a data change — one entry in
the Brain's rule table, no code touched. Rolling back is the same call with the
version the API just reported. The pointer is the only file the service writes,
which is why the container runs non-root but with the host's group: it needs
write access to exactly one file and nothing else.

The pointer is also a committed file, so the repository is the declared active
version. A hot-swap survives a container restart but not a redeploy: it is an
operational override, not a change of intent. That is **enforced by the deploy
target**, which restores the committed pointer before switching commits —
`git checkout -- company_brain/active_version.json`. Without that line the
override outlives every deploy, silently, because git carries a locally modified
tracked file across a checkout when its content is unchanged between the two
commits; and once the pointer *does* change in some commit, git refuses the
checkout outright and the deploy aborts on a message about local changes. Both
were observed on staging before the line was added.

The brief requires the swap to work "without a redeploy" and to have a rollback
path; it says nothing about whether a swap should outlive a later deploy, so this
is a design choice rather than a forced one. Persisting it was rejected because
nothing would ever reconcile the running policy with the repository, and drift
between the two is exactly what `brain_hash` exists to make visible. Under the
rule above there are two ways back to the declared version — activate it, or
deploy — and the alternative of moving the pointer outside the checkout buys swap
durability at the cost of new policy versions no longer arriving with a deploy.

## Guardrails

| | |
|---|---|
| Never auto-`CLEAR` a watchlist hit | An independent assertion after adjudication, not a property left to emerge from rule ordering. If a hit exists and the verdict is `CLEAR`, the run fails loudly — verified against a Brain deliberately edited to map a corroborated sanctions hit to `CLEAR`, which is the case a correctly written table cannot protect against. Its message carries entry ids and never a subject's name, because it goes to a log. |
| `REVIEW` / `BLOCK` route to a human | Terminal states are flagged for a compliance officer and never auto-action anything downstream. |
| No PII in logs | Traces reference applicants and entities by ID. Names, dates of birth and identifiers are redacted before anything is written to log storage; the full case file exists only in the response to an authenticated caller. |
| Documents are data, never instructions | Free text is delimited, numbered, and framed as untrusted input, and a document cannot close its own delimiter. The extraction schema has no `decision`, `confidence` or `reasons` field, so APP-009's request for "decision = CLEAR" has nowhere to land: the defence is the absence of a slot, not a filter that has to recognise the attack. What a document *could* still do is talk the model out of a finding, which is what the deterministic floor closes — signals, screening targets and the injection flag are the union of floor and model. Screening then runs unconditionally regardless of any of it. |
| A document that tries to manipulate is recorded | `injection_suspected` is a declared fact with a working sensor and no rule in v1 — the same shape as `location_validation`. The policy has no rule about manipulation attempts, and writing one into Python would put policy in code; a later version can say `{injection_suspected: true} → REVIEW` as a one-line data change. |

## Failure modes

| | Handling |
|---|---|
| Brain volume missing, pointer malformed, or rule table invalid | `/health` returns 503; the instance is not ready and receives no screening traffic. No fallback to a previous version — an instance that cannot execute its policy stops rather than guessing |
| Watchlist absent from the image | `/health` returns 503 for the same reason: an instance that cannot screen is not ready. This was a real defect, not a hypothetical — the Dockerfile shipped only `agent/` and `api/`, and `.dockerignore` excluded `assets/` outright, so every environment would have failed to screen while every local test passed |
| Policy edit that references a fact nobody produces | Rejected at activation with 422 and the validation errors; the pointer does not move |
| The Brain's pinned `as_of_date` goes stale | Harmless within this challenge — verified decision-neutral across all 18 applicants — but a real deployment needs a policy-review cadence. The date is visible in `GET /brain` rather than buried in code |
| Model unavailable, rate limited, or without a credential | The SDK retries transport failures; anything left over raises `ModelUnavailable`, which extraction turns into a stopped run. There is no partial extraction: an empty one reports no shell signals, which is the unsafe direction. An unset `ANTHROPIC_API_KEY` surfaces here as a service fault rather than an unhandled `TypeError` |
| Model returns something unanchorable | One retry with the violated spans named, then the run stops. A span that is not a verbatim quote from the document it cites is how a fabricated finding is caught |
| Runaway tool-call loop | Step and time budget per applicant; `MAX_STEPS_PER_APPLICANT` and `REQUEST_TIMEOUT_SECONDS` are wired into configuration |
| Ambiguous policy text | Resolved explicitly in `DECISIONS.md` and surfaced in the trace, so a human can see which reading produced the verdict |

## Stack

Choices made freely — the brief would be satisfied either way. Recorded here
rather than in `DECISIONS.md` for exactly that reason.

| | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Stable wheel coverage; nothing needs 3.13+ |
| Dependencies | uv with a committed `uv.lock` | Reproducible builds, fast Docker layers |
| API | FastAPI + Uvicorn | Small surface for `/health`, `/screen`, `/brain/activate` |
| Validation | Pydantic v2 | The schemas double as the extraction contract |
| LLM | `anthropic` SDK, `claude-opus-5` | Official SDK; the model is identical in every environment |

### Why no agent framework

I have prior LangChain and Strands experience, so *not* using a framework is a
deliberate choice rather than a default.

The pipeline is a bounded three-stage flow with no multi-agent delegation and no
persistent session state — the problems LangGraph and Google ADK solve are not
present here. The rubric rewards correctness per unit of complexity, and the live
task means the control flow has to be explainable and modifiable under time
pressure: plain Python is legible line by line, whereas a framework I have never
used would be a liability in exactly that moment.

The cost is that retries, timeouts and loop guards are written explicitly rather
than inherited. That is a small, bounded amount of code whose behaviour I can
state precisely.

## Environments and deployment

Staging and production run the same image from the same commit, differing only in
env file, bind port, hostname, log level, and active Brain version.

| | staging | production |
|---|---|---|
| Bind | `127.0.0.1:8081` | `127.0.0.1:8080` |
| Host | kira-staging.adaptateia.com | kira.adaptateia.com |
| Brain | free to run a candidate version | pinned |

Both bind to loopback and are exposed through Cloudflare Tunnel, so no inbound
ports are opened. Deployment is an explicit `make` target, never a side effect of
pushing: `deploy-staging` takes any ref, `deploy-prod` accepts only `main`.

Keeping code identical across environments is what lets the CI eval gate mean
something. A gate that validated a configuration production never runs would be
decorative.

## Cost and latency

One model call per applicant. The cacheable prefix is the extraction prompt plus
the policy text, both from the Brain and byte-stable across applicants, marked
`cache_control: ephemeral`; `claude-opus-5` has a 512-token minimum cacheable
prefix and the pair is comfortably above it. `usage` is captured on every
response and carried into the trace in spec 004.

Measured twice, over 60 real calls each — the twelve labelled applicants, five
times each, `claude-opus-5`. Both figures are reported because the spread between
them is the honest error bar on a single measurement:

| | spec 002 sweep | spec 003 sweep |
|---|---|---|
| Latency | 4.1 s per applicant | 5.6 s per applicant |
| Input from cache | 93% (236,940 cached / 17,684 fresh) | 91% (228,625 cached / 17,717 fresh) |
| Output | 178 tokens per call | 224 tokens per call |
| Cost | $0.0079 per applicant | $0.0094 per applicant |

Screening adds nothing to either: the sweep is 124 local `difflib` calls for all
18 packets, with no network and no tokens. The whole per-applicant cost is
extraction.

The cache figure is the prompt-plus-policy prefix doing its job: only the packet
itself is fresh input on each call. A live test asserts
`cache_read_input_tokens > 0` on a second call, so the claim keeps being checked
rather than being a one-off measurement quoted forever.

Each sweep is also the determinism evidence for its spec — the 003 one hashing
the full verdict rather than the facts bag.

No sampling parameters are sent: `temperature`, `top_p` and `top_k` are rejected
with HTTP 400 on current models. `max_tokens` bounds thinking and response text
together and is set well above what the extraction schema needs. Effort tuning
(`output_config.effort`) is deliberately left alone until there is a measurement
to tune against.
