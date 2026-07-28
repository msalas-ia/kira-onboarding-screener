As a general heuristic, if there is no *exact* sanctions match, lean toward
CLEAR.

---

This is the naive base instruction the Company Brain explicitly permits an agent
to carry, quoted from `screening_policy.md`. It is wrong on purpose: by Rule 2 an
unconfirmed sanctions near-match is REVIEW, never CLEAR, and APP-011 is the case
where the two disagree.

It lives here, inside the versioned Brain and inside `brain_hash`, so the
override demonstration is a swap between two versioned artifacts rather than a
branch in the code. Nothing on the decision path reads it: it is consumed only by
the adjudication proposal step, whose output is recorded in the trace and then
overruled by the rule table.
