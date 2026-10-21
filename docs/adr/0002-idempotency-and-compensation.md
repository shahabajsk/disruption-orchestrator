# ADR 0002: Idempotent writes and compensation for multi-system changes

Status: accepted

## Context

Two failures cause most of the damage when automation touches payments and inventory:

1. **Commit then timeout.** The payment system records a refund, then the response is lost. A naive retry refunds twice.
2. **Half-done change.** The rebook holds seats on the new flight, then the ticket reissue fails. The customer has seats but no valid ticket, and the inventory is wrong.

## Decision

- Every write to payments carries an idempotency key derived from the contact. A retry with the same key returns the first result.
- The executor retries only errors the system marks retryable, at most twice.
- A write that changes another system's state declares its compensation. `res.rebook` declares `res.release_seats`. If a later step in the same state fails, the machine moves to `compensate`, runs the compensation, then hands off.

## Consequences

- The eval injects both failures on purpose (`refund_ghost_commit`, `reissue_fails`) and checks the invariants on every run: duplicate payments and leaked seats are both zero.
- Compensation is explicit per skill, not a generic rollback. That matches how real systems behave: you can release seats, you can't un-send an SMS.
