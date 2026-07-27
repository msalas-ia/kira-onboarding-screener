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
```

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
  active_version.json  pointer — swapping this swaps the policy, no redeploy
assets/                the delivered bundle, never modified
specs/                 one spec per component, with acceptance criteria
tests/                 unit suite
```

## Read next

- `DESIGN.md` — architecture, the Brain override mechanism, determinism approach
- `DECISIONS.md` — judgment calls forced by ambiguity in the brief

## Secrets

`.env.example` is the only environment file in the repository. Real values live
in `.env.staging` / `.env.production`, which are gitignored. CI runs `gitleaks`
over the full history on every push.
