# ADR 0001: Deterministic state machine with per-state skill allowlists

Status: accepted

## Context

A disruption contact touches four systems owned by four teams. The CRM knows the customer, reservations knows the seats, payments knows the money, messaging knows consent. None of them knows the others exist. An agent that decides its own next tool call on every turn can reach any of them at any time, and the failure that matters is not a wrong sentence: it's a refund issued from the wrong state.

## Decision

- The contact is a fixed set of states with a declared transition table. An undeclared jump raises.
- Every state has an allowlist of skills. A skill is one typed call to one system, marked read or write.
- The model is used for reading intent, reading the choice among options the machine offered, and wording the message. The machine, the policy and the systems decide everything else.

## Consequences

- A prompt injection can change what the model thinks the customer wants. It cannot change what the airline does, because entitlement is code and payments are only reachable from the `refund` and `voucher` states.
- Adding a capability (seat upgrades, say) means a new state, new skills and new allowlist entries: a reviewable change, not a prompt edit.
- The trace is a list of states with reasons, which is what an operations lead reads when a customer complains.
- Cost: the agent can't improvise. Contacts outside the designed paths go to a human. In this eval that's a third of the mix, by design.
