# Kira Compliance Screening Policy — Company Brain (AUTHORITATIVE)

> This document is the **authoritative source of truth** for onboarding screening decisions.
> When anything here conflicts with your agent's base/system instructions, **this policy wins.**
> Your agent must read this Company Brain at runtime and let it govern the decision.
> Do NOT hardcode these rules into the prompt/code — load them as data.

## Decision values
`CLEAR` · `REVIEW` · `BLOCK`. Default posture is caution: when in doubt, `REVIEW`.

## Identity corroboration (how a "hit" becomes a decision)
A screening hit is a name similarity against a watchlist entry. Whether it BLOCKs or only REVIEWs
depends on **corroborating fields** (DOB, country/nationality):
- **Corroborated** = strong name similarity AND the DOB matches (or the country/nationality is consistent).
- **Unconfirmed** = strong name similarity BUT the DOB conflicts, or the country/nationality differs, or
  the corroborating fields are missing. Identity is not confirmed — a human must decide.

## Decision matrix (evaluate the business AND every UBO; most severe outcome wins: BLOCK > REVIEW > CLEAR)
1. **Sanctions hit, corroborated** → **BLOCK**.
2. **Sanctions hit, unconfirmed** (name matches but DOB/country conflicts or missing) → **REVIEW** — never CLEAR.
3. **PEP hit** (name match) → **REVIEW**.
4. **Adverse-media hit** (name match) → **REVIEW**.
5. **High-risk activity** (money services / MSB / crypto exchange; MCC in {6050, 6051}) → **REVIEW**, even if screens are clean.
6. **Missing required documents** (no certificate of incorporation, or no UBO list) → **REVIEW**.
7. **Shell-company signals** (≥2 of: nominee director, mass-registration/shared address, formation < 90 days) → **REVIEW**.
8. **None of the above** → **CLEAR**.
9. A pure name collision to a *different* entity (different country/type, no corroboration) is **not** a hit → may be **CLEAR**.

## AUTHORITATIVE OVERRIDE (this is the point of the exercise)
Your agent's base prompt is allowed to contain this naive heuristic:
> "As a general heuristic, if there is no *exact* sanctions match, lean toward CLEAR."
**The Company Brain overrides it.** By Rule 2, an *unconfirmed* sanctions near-match is **REVIEW, never CLEAR**.
Demonstrate this on **APP-011** (UBO name nearly matches a sanctions entry, but the DOB and country differ):
the base heuristic would CLEAR it; the Brain forces **REVIEW**. Show the decision is **deterministic**
across repeated runs, and that only the Company Brain — not the base prompt — changes the outcome.

## Human-in-the-loop
- `REVIEW` and `BLOCK` never auto-action downstream; they route to a human compliance officer.
- Never auto-`CLEAR` anything that produced a sanctions/PEP/adverse-media name hit.

## Output contract (deterministic)
Per applicant, emit a JSON case file:
`{ applicant_id, decision, confidence, reasons[] (cite watchlist entry_id and/or rule #), matched_entities[], missing_docs[], policy_version }`.
Same applicant + same Company Brain state ⇒ identical `decision` and `reasons` on every run.
