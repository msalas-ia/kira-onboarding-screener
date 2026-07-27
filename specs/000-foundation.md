# Spec 000 — Foundation

> **Status**: Draft
> **Owner**: repo bootstrap, before any functional code
> **Constitutional context**: D-001 (hybrid architecture — precedes every spec)
> **Decisions owned by this spec**: none. Nothing in a scaffold is forced; the
> choices below are free ones and their rationale lives here and in `DESIGN.md`.

## 1. Goal

Stand up a repository that a reviewer can clone cold and run with one command, and
a deployment skeleton that is reachable before any screening logic exists.

The rationale for doing this first: a reachable endpoint with a stubbed `/health`
on Day 1 is worth more than a perfect rules engine that fails to deploy on Day 3.
Everything after this spec is additive — no later spec should need to change the
container, the CI shape, or the environment layout.

## 2. Scope

**In scope**: repo layout, dependency management, Docker image, two compose
stacks, environment/secret conventions, branch and commit conventions, CI
skeleton, `/health` endpoint, `DECISIONS.md` bootstrap.

**Out of scope** (owned by later specs): the rules engine (001), extraction (002),
screening and adjudication (003), tracing and PII redaction (004), the eval suite
and the CI eval-gate (005). `/screen` is *not* implemented here — only `/health`.

## 3. Stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 | Stable wheel coverage; no 3.13-only feature is needed |
| Dependencies | `uv` + `pyproject.toml` + committed `uv.lock` | Reproducible builds — the same discipline the decision path demands (D-001) |
| API framework | FastAPI + Uvicorn | Minimal surface for `/health`, `/screen`, `/brain/activate` |
| Validation | Pydantic v2 + `pydantic-settings` | Schemas double as the extraction contract in spec 002 |
| LLM client | `anthropic` (official SDK) | Official provider SDK, no agent framework — see `DESIGN.md` |
| Brain parsing | `PyYAML` | Structured rule block inside `screening_policy.md` (spec 001) |
| HTTP client | `httpx` | Geolocation tool in the live call task |
| Tests | `pytest` | Fast, no-network unit layer |

Runtime dependencies stay at the list above. Anything else needs a decision entry.

### Model configuration

`ANTHROPIC_MODEL` defaults to `claude-opus-5` and is identical in every
environment: an eval gate that graded a model production never runs would be
decorative. Three API constraints that later specs must respect and that
are recorded here so they are not rediscovered:

- `temperature`, `top_p`, `top_k` are rejected with HTTP 400 on current models.
  Output stability comes from structured outputs and schema validation, never
  from sampling parameters.
- `max_tokens` bounds thinking **and** response text together. Leave headroom.
- Structured extraction uses `client.messages.parse()` with a Pydantic model so
  the response is schema-valid by construction.

## 4. Repository layout

```
kira-finance/
├── agent/                     # created empty here; filled by specs 001–004
├── api/
│   └── main.py                # /health only at this stage
├── company_brain/
│   ├── versions/v1/           # copy of the provided policy, unmodified
│   └── active_version.json    # pointer file, mounted as a volume (spec 001)
├── tools/
│   └── watchlist_search.py    # reference tool, used as-is
├── evals/                     # created empty here; filled by spec 005
├── tests/
│   └── test_health.py
├── specs/
├── assets/                    # provided bundle, never modified
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.staging.yml
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
├── pyproject.toml / uv.lock
├── CLAUDE.md
└── README.md / DESIGN.md / DECISIONS.md
```

`assets/` stays byte-identical to the delivered bundle. `company_brain/versions/v1/`
holds our working copy; the two are compared in CI so drift is visible.

## 5. Branching and commits

Single long-lived branch `main`. One branch per spec, named
`spec/00X-<short-name>`, merged with `--no-ff` so the history shows deliberate
units of work rather than a flat sequence.

Staging and production **never diverge in code**. They differ only by the
configuration in §6. A branch whose code could reach production without passing
through the same eval gate as staging would defeat the purpose of the gate.

Non-trivial commits reference the decision they implement, e.g.
`feat(rules): generic condition evaluator over facts bag (D-001)`.

### Remote and protection

GitHub repository, private, created at bootstrap. `main` is protected:

- Require a pull request before merging
- Require the CI workflow to pass as a status check
- Block force pushes and branch deletion

The status-check rule is what makes the eval-gate binding rather than advisory:
without it, CI can fail and the merge still goes through, and the gate the brief
asks for would be decorative.

Administrator bypass is deliberately left **enabled**. This is a solo repo on a
fixed deadline; a protection rule that can lock the only maintainer out during
the live call is a liability, not a control. The rule is visible in the repo
settings either way.

## 6. Environments

Both stacks run the same image from the same commit. Everything that differs is
configuration:

| | staging | production |
|---|---|---|
| Compose file | `docker-compose.staging.yml` | `docker-compose.prod.yml` |
| Env file | `.env.staging` (gitignored) | `.env.production` (gitignored) |
| `APP_ENV` | `staging` | `production` |
| Bind address | `127.0.0.1:8081` | `127.0.0.1:8080` |
| Public URL | `kira-staging.adaptateia.com` | `kira.adaptateia.com` |
| Brain version | free to point at a candidate version | pinned |
| `LOG_LEVEL` | `DEBUG` | `INFO` |
| Model | identical | identical |

Both bind to loopback only and are exposed through Cloudflare Tunnel with no
inbound ports open. This matches the convention already used on the host
by `backend` (8000), `n8n` (5678), and `creskai-frontend` (8090). Ports 8080 and
8081 were verified free.

The Brain lives on a mounted volume, not baked into the image, so a version
switch does not require a rebuild. This is what makes the hot-swap demo in
spec 001 possible, and it is why the two environments can run the same commit
against different policy versions.

### `.env.example`

Committed with placeholders only. A real `.env*` is never committed.

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-5
APP_ENV=staging
BRAIN_DIR=/app/company_brain
ADMIN_API_TOKEN=
LOG_LEVEL=INFO
MAX_STEPS_PER_APPLICANT=12
REQUEST_TIMEOUT_SECONDS=120
PORT=8000
```

`.gitignore` covers `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `.venv/`,
`traces/`, `.pytest_cache/`.

## 7. Container and deployment

Multi-stage `Dockerfile`: a build stage running `uv sync --frozen` against the
lockfile, and a slim runtime stage running as a non-root user. `assets/` and
`tests/` are excluded from the runtime image via `.dockerignore`.

`docker compose -f docker-compose.staging.yml up` must be sufficient to reach a
working `/health` with no manual steps beyond copying `.env.example`.

### How code reaches the host

**Pushing a branch deploys nothing.** Deployment is an explicit act, which is
what makes the promotion gate in §6 real rather than implied. The host keeps one
git checkout per environment, and a `Makefile` drives both:

```
make deploy-staging REF=spec/001-brain-rules-engine
make deploy-prod                    # always main; refuses any other ref
```

The same `Makefile` carries the local loop — `lock`, `sync`, `test`, `up`,
`down` — so there is one entry point for both.

Each target does: `git fetch && git checkout <ref>` in that environment's
checkout, then `docker compose -f <env compose> up -d --build`. `deploy-prod`
hard-fails on a ref other than `main`, so production cannot be pointed at an
unmerged branch by accident.

The normal cycle:

```
1. branch from main, work, push
2. make deploy-staging REF=<branch>   → verify on kira-staging.adaptateia.com
3. open PR → CI runs (secret scan, tests, and later the eval gate)
4. merge to main
5. make deploy-prod                   → kira.adaptateia.com
```

Automating step 5 from GitHub Actions over SSH is a possible Day-2 improvement,
not a requirement. It buys little for the demo and adds a deploy key to manage,
which cuts against the secrets-hygiene requirement rather than supporting it.

## 8. `/health`

`GET /health` returns 200 with:

```json
{
  "status": "ok",
  "app_env": "staging",
  "brain_version": "v1",
  "model": "claude-opus-5",
  "commit": "<short sha>"
}
```

It is a **readiness** probe: it returns 503 if the Brain directory or the active
version pointer cannot be read. It never calls the Anthropic API, so it stays
fast and free, and it works with no API key present.

## 9. CI skeleton

`.github/workflows/ci.yml`, running on every push:

1. Checkout
2. Secret scan (`gitleaks`) over the full history — fails the build on any finding
3. `uv sync --frozen`
4. `pytest tests/` (no network, no API key)
5. Verify `company_brain/versions/v1/screening_policy.md` matches `assets/`

The eval-gate (false-clear rate, determinism) is added by spec 005. The workflow
file is authored here so that step is an addition, not a rewrite.

## 10. `DECISIONS.md`

The log holds judgment calls forced by an ambiguity or a tension in the
requirements, written at the moment the decision is made. Choices made freely —
Python version, uv, FastAPI, self-hosted deployment — are recorded in
`DESIGN.md` alongside what was built instead.

By that rule this spec produces no entries: nothing in the scaffold was forced.
The file is therefore created together with its first entry, which lands with
the first functional component.

## 11. Acceptance criteria

1. `git log` shows the bootstrap as coherent, reviewable commits — not one dump.
2. Following `README.md` verbatim on a clean machine reaches a running service:
   `cp .env.example .env.staging` → edit key → `docker compose -f docker-compose.staging.yml up` → `curl localhost:8081/health` returns 200.
3. `curl https://kira-staging.adaptateia.com/health` returns 200 from outside the network.
4. `curl https://kira.adaptateia.com/health` returns 200 and reports `"app_env": "production"`.
5. `gitleaks detect --no-git=false` reports zero findings; no `.env` with a real
   value exists in any commit.
6. `pytest tests/` passes with `ANTHROPIC_API_KEY` unset.
7. CI passes on the first push to `main`.
8. `/health` returns 503 when the Brain volume is unmounted (readiness, not liveness).
9. `assets/` is byte-identical to the delivered bundle.
10. `DESIGN.md` records the stack and deployment choices with their rationale,
    including why no agent framework was used.

## 12. Risks

- **Cloudflare Tunnel** — low risk, but still the only step depending on
  infrastructure outside the repo. `cloudflared` already runs as an active
  systemd service on the host with no local config file, which indicates a
  remotely managed tunnel: adding the two hostnames is a dashboard change, not a
  config edit or a restart. Still do it before the rules engine. If the routes
  are not live by end of Day 1, fall back to a temporary public URL and record
  the change in `DECISIONS.md` rather than absorbing the delay silently.
- **`uv` in CI**: pin the installer version so a `uv` release cannot break the
  build mid-challenge.
