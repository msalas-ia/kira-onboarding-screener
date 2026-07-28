# Naive screening baseline — NOT A POLICY

This version exists so the Company Brain's override can be **measured** rather
than narrated. It is the naive heuristic the base prompt is permitted to carry —
*"if there is no exact sanctions match, lean CLEAR"* — promoted from an
instruction into a rule table, so that it runs on the same code path as the real
policy and can be compared against it.

Nothing here should ever be active in an environment that screens a real
applicant. It produces false clears by design; that is the entire point.

## Why it exists

The brief asks for a demonstration that the Brain overrules the agent's base
instructions. Measured over eleven real runs (D-010), the model carrying the
naive prompt **does not need overruling** — it proposed REVIEW on APP-011 even
when handed a 0.966 non-exact sanctions match, which is exactly what the naive
instruction told it not to do.

Rather than tune the prompt until the model misbehaves, the override is
demonstrated as **policy against policy**: the same applicant, the same packet,
the same extraction and the same watchlist, evaluated under two versioned rule
tables (D-015).

Everything else in this version — the settings, the thresholds, the required
documents, the prompts — is byte-identical to `v1`. The rule table is the only
variable, which is what makes the comparison a measurement of the rule table.

## Decision matrix

1. Sanctions hit with an **exact** name match (score 1.0) → BLOCK
2. Anything else → CLEAR

There is no rule about unconfirmed near-matches, about PEP or adverse-media
entries, about high-risk activity, about missing documents, or about
shell-company signals. That absence is the naive heuristic stated honestly: it
reasons about exact sanctions matches and about nothing else.

## What it produces

Against the eighteen delivered packets it disagrees with `v1` on **ten**, and on
**seven** of the twelve labelled applicants — APP-002, 004, 005, 006, 008, 011
and 012. Every disagreement is in the CLEAR direction.

The `never_auto_CLEAR` guardrail catches **five** of those ten, and only five:
the ones that carry a watchlist hit. It is silent on APP-005 (high-risk MCC),
APP-006 (missing documents), APP-008 (shell signals), APP-017 and APP-018,
because there is no hit for it to notice. A runtime guardrail is a net under one
class of failure, not under a wrong policy — which is why the eval suite exists.
