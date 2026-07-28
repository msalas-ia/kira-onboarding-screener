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

The scaffold is in place: container stack, both environments, CI, and a
readiness endpoint. The screening pipeline itself is being built spec by spec —
see `specs/` for what is planned and `DESIGN.md` for how it fits together.

| | |
|---|---|
| Implemented | `/health`, container image, staging + production stacks, CI |
| Next | Brain loader and rules engine (spec 001) |

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
