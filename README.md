# Kira Onboarding Screener

A compliance screening agent for KYB onboarding. It extracts a case file from a
messy applicant packet, screens the business and every UBO against a sanctions /
PEP / adverse-media watchlist, and returns `CLEAR` / `REVIEW` / `BLOCK` with
cited evidence.

Decisions are governed by a **Company Brain** — an authoritative policy loaded at
runtime, not baked into the prompt or the code. The Brain overrules the agent's
base instructions, and the same applicant against the same Brain yields the same
decision every run.

## Status

Complete against everything the brief names. Specs 000 to 005 are merged and
running in both environments; `specs/` records what each one settled and
`DESIGN.md` how it fits together.

| | |
|---|---|
| Decisions | 12 of 12 labelled applicants correct, for the labelled rule. False-clear rate **zero**, in both of its defensible definitions |
| Determinism | 12 applicants, one verdict serialisation each across 36 runs with the tool loop on — reproduced on a clean CI runner, not only locally |
| Override | demonstrated as policy against policy: `v0-naive` and `v1` disagree on 10 of 18 packets, and APP-011 is CLEAR under one and REVIEW under the other with no model on the path |
| Injection | APP-009 blocks with the injection flagged, every run. The extraction schema has no `decision` field for it to land in |
| Tests | 308 offline (no key, no network) and 9 live |
| Cost | $0.0425 and 15.3 s per applicant, measured by the gate CI reproduces |

## Live

| Environment | URL |
|---|---|
| Production | https://kira.adaptateia.com/health |
| Staging | https://kira-staging.adaptateia.com/health |

## Run it

Requires Docker. No Python toolchain needed on the host.

```bash
git clone git@github.com:msalas-ia/kira-onboarding-screener.git
cd kira-onboarding-screener

cp .env.example .env.staging
# edit .env.staging and set ANTHROPIC_API_KEY

make up
```

Then:

```bash
curl -s http://127.0.0.1:8081/health
# {"status":"ok","app_env":"staging","brain_version":"v1", ...}
```

`make down` tears it back down.

`/health` is a readiness probe: it returns 503 if the Company Brain volume
cannot be read, because an instance that cannot load its policy must not receive
screening traffic. It never calls the Anthropic API, so it works with no
credentials present.

## Endpoints

```
GET  /health            readiness; 503 if the Brain or the watchlist cannot be read
GET  /brain             the active version, what a rollback returns to, and brain_hash
GET  /brain/versions    every version on the volume, valid or not
POST /brain/activate    hot-swap the active policy          (ADMIN_API_TOKEN)
POST /screen            a packet in, the case file and the run's trace out  (SCREEN_API_TOKEN)
```

The two tokens are separate on purpose: a caller that can screen an applicant
should not thereby be able to swap the policy it is screened under.

### Screen an applicant

`/screen` takes a **packet**, never an id — the delivered bundle is test data,
not a database this service owns.

```bash
PACKET=$(jq -c '.[] | select(.applicant_id=="APP-011")' assets/data/applicants.json)

curl -s -X POST https://kira.adaptateia.com/screen \
  -H "Authorization: Bearer $SCREEN_API_TOKEN" -H 'Content-Type: application/json' \
  -d "$PACKET" | jq '.case_file | {decision, reasons, matched_entities, policy_version}'
```

```json
{
  "decision": "REVIEW",
  "reasons": ["Rule 2 — sanctions hit, unconfirmed — never CLEAR (ubo[0]): entry_id=EU-2001, name_score=0.966, corroboration_basis=none"],
  "matched_entities": [{"entry_id": "EU-2001", "hit_type": "sanctions", "subject_ref": "ubo[0]", "name_score": 0.966, "corroborated": false}],
  "policy_version": "v1"
}
```

The response also carries the run's full trace — every step, its tokens, latency
and cost, both verdicts, and whether the model's proposal was overruled. It
contains no name, date of birth or quoted span, because no field of the schema
can hold one.

### The Brain overruling the base instruction

`company_brain/versions/v0-naive/` is the naive heuristic the policy explicitly
permits — *no exact sanctions match, lean CLEAR* — written as a rule table
instead of a prompt, with settings and prompts byte-identical to `v1`. The rule
table is the only variable, so a difference in decisions measures the rule table.

```bash
curl -s -X POST $HOST/brain/activate -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"version":"v0-naive"}'
# {"previous":"v1","active":"v0-naive","brain_hash":"sha256:4862d25…"}
```

APP-005 then reaches `CLEAR` where `v1` reaches `REVIEW`, on the same packet and
the same code, with no restart and no redeploy. Rollback is the same call with
the version the API just reported. APP-011 under the naive table is refused
outright — `assert_no_auto_clear` will not serve a `CLEAR` over a watchlist hit,
whatever the policy says.

The full 18-packet comparison is in [`evals/results.md`](evals/results.md), and
it is checked by the offline test suite on every run.

## Develop

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv itself.

```bash
make sync    # install the locked environment
make test    # unit suite, no network, no API key
make lock    # regenerate uv.lock after changing dependencies
make evals   # the eval gate against the real API (~$1.53, ~4 min)
```

## Evals

```bash
uv run python evals/run_evals.py            # 12 labelled applicants x 3 runs
uv run python evals/run_evals.py --url https://kira.adaptateia.com   # against a deployment
```

It screens through the configuration production runs — the adjudication loop on,
the same model, the same code path — and gates on seven metrics: the false-clear
rate in both of its defensible definitions, decision accuracy, the two
adversarial cases by name, determinism across the runs, and the override
ablation. Exit `1` is a gate failing; exit `2` is the suite being unable to
measure, which is not the same event. `--max-cost-usd` stops it rather than
trusting an estimate.

The last committed results are in [`evals/results.md`](evals/results.md), stamped
with the commit and `brain_hash` that produced them.

## Deploy

Pushing a branch deploys nothing — deployment is explicit.

```bash
make deploy-staging REF=spec/001-brain-rules-engine   # any ref
make deploy-prod                                       # main only
```

Staging accepts any ref so a branch can be verified before it is merged.
`deploy-prod` refuses anything other than `main`, so production cannot be
pointed at unmerged work by accident.

## Layout

```
api/                   FastAPI surface
company_brain/         versioned policy, mounted at runtime (not in the image)
  versions/v1/         the active policy
  versions/v0-naive/   the naive baseline, kept so the override can be measured
  active_version.json  pointer — swapping this swaps the policy, no redeploy
assets/                the delivered bundle, never modified
evals/                 the eval suite, the gate, and the committed results summary
specs/                 one spec per component, with acceptance criteria
tests/                 unit suite
```

## Read next

- `DESIGN.md` — architecture, the Brain override mechanism, determinism approach
- `DECISIONS.md` — judgment calls forced by ambiguity in the brief
- `evals/results.md` — the last gated run: every metric, the ablation, cost and latency

## Secrets

`.env.example` is the only environment file in the repository. Real values live
in `.env.staging` / `.env.production`, which are gitignored. CI runs `gitleaks`
over the full history on every push.
