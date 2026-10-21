"""The orchestrator: one deterministic state machine per customer contact.

14 states, each with an allowlist of skills. The model is consulted in three places (read
the intent, read the choice, write the message) and is never asked what to do next.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum

from .model import Model, RuleModel, ungrounded
from .models import Booking, Customer, Flight, Intent, Request, Resolution
from .policy import Entitlement, entitlement
from .skills import Executor
from .systems import SystemError_, Systems


class S(str, Enum):
    RECEIVED = "received"
    IDENTIFY = "identify"
    LOAD_BOOKING = "load_booking"
    ASSESS = "assess"
    ENTITLEMENT = "entitlement"
    OFFER = "offer"
    READ_CHOICE = "read_choice"
    REBOOK = "rebook"
    REFUND = "refund"
    VOUCHER = "voucher"
    COMPENSATE = "compensate"
    NOTIFY = "notify"
    HANDOFF = "handoff"
    CLOSE = "close"
    DONE = "done"


TRANSITIONS: dict[S, frozenset[S]] = {
    S.RECEIVED: frozenset({S.IDENTIFY}),
    S.IDENTIFY: frozenset({S.LOAD_BOOKING, S.HANDOFF}),
    S.LOAD_BOOKING: frozenset({S.ASSESS, S.HANDOFF}),
    S.ASSESS: frozenset({S.ENTITLEMENT, S.HANDOFF}),
    S.ENTITLEMENT: frozenset({S.OFFER, S.NOTIFY, S.HANDOFF}),
    S.OFFER: frozenset({S.READ_CHOICE, S.HANDOFF}),
    S.READ_CHOICE: frozenset({S.REBOOK, S.REFUND, S.VOUCHER, S.HANDOFF}),
    S.REBOOK: frozenset({S.NOTIFY, S.COMPENSATE, S.HANDOFF}),
    S.REFUND: frozenset({S.NOTIFY, S.HANDOFF}),
    S.VOUCHER: frozenset({S.NOTIFY, S.HANDOFF}),
    S.COMPENSATE: frozenset({S.HANDOFF}),
    S.NOTIFY: frozenset({S.CLOSE}),
    S.HANDOFF: frozenset({S.CLOSE}),
    S.CLOSE: frozenset({S.DONE}),
    S.DONE: frozenset(),
}

ALLOWED: dict[S, frozenset[str]] = {
    S.RECEIVED: frozenset(),
    S.IDENTIFY: frozenset({"crm.identify_customer"}),
    S.LOAD_BOOKING: frozenset({"res.load_booking"}),
    S.ASSESS: frozenset({"res.flight_status", "nlu.read_intent"}),
    S.ENTITLEMENT: frozenset({"policy.entitlement"}),
    S.OFFER: frozenset({"res.find_alternatives", "compose.message", "msg.send"}),
    S.READ_CHOICE: frozenset({"nlu.read_choice"}),
    S.REBOOK: frozenset({"res.rebook", "pay.reissue_ticket"}),
    S.REFUND: frozenset({"pay.refund"}),
    S.VOUCHER: frozenset({"pay.issue_voucher"}),
    S.COMPENSATE: frozenset({"res.release_seats"}),
    S.NOTIFY: frozenset({"crm.log_case", "compose.message", "msg.send"}),
    S.HANDOFF: frozenset({"crm.log_case", "handoff.queue", "compose.message", "msg.send"}),
    S.CLOSE: frozenset(),
    S.DONE: frozenset(),
}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Step:
    state: str
    note: str


@dataclass
class Outcome:
    request_id: str
    resolution: Resolution
    reason: str
    trace: list[Step]
    skill_calls: int
    retries_absorbed: int
    out_of_policy_blocked: int = 0
    ungrounded_blocked: int = 0
    compensated: bool = False
    messages: list[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        body = json.dumps([asdict(s) for s in self.trace] + [self.resolution.value], sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:12]


class Orchestrator:
    def __init__(self, systems: Systems, model: Model | None = None) -> None:
        self.sys = systems
        self.model = model or RuleModel()

    def run(self, req: Request) -> Outcome:
        ex = Executor()
        trace: list[Step] = []
        state = S.RECEIVED
        cust: Customer | None = None
        booking: Booking | None = None
        flight: Flight | None = None
        ent: Entitlement | None = None
        intent = Intent.UNCLEAR
        options: dict[str, str] = {}  # label -> action ("rebook:XX123", "refund", "voucher")
        choice: str | None = None
        resolution = Resolution.HANDOFF
        reason = ""
        facts: dict = {}
        blocked = 0
        ungrounded_count = 0
        compensated = False
        sent: list[str] = []

        def go(nxt: S, note: str) -> S:
            if nxt not in TRANSITIONS[state]:
                raise IllegalTransition(f"{state.value} -> {nxt.value}")
            trace.append(Step(state.value, note))
            return nxt

        def call(skill: str, fn):
            return ex.run(skill, ALLOWED[state], fn)

        def send(kind: str) -> None:
            nonlocal ungrounded_count
            assert cust is not None
            body = call("compose.message", lambda: self.model.compose(facts, kind))
            if ungrounded(body, facts):
                # The model wrote a value that isn't in the case. Fall back to the template.
                ungrounded_count += 1
                body = RuleModel().compose(facts, kind)
            channels = [req.channel] + [c for c in cust.consented_channels if c != req.channel]
            for ch in channels:
                try:
                    call("msg.send", lambda ch=ch: self.sys.msg.send(cust, ch, body))
                    sent.append(f"[{ch}] {body}")
                    return
                except SystemError_:
                    continue

        while state is not S.DONE:
            try:
                if state is S.RECEIVED:
                    state = go(S.IDENTIFY, f"contact {req.id} on {req.channel}")

                elif state is S.IDENTIFY:
                    cust = call("crm.identify_customer", lambda: self.sys.crm.find_by_phone(req.phone))
                    if cust is None:
                        reason = "caller not found in CRM"
                        state = go(S.HANDOFF, reason)
                    else:
                        facts.update(name=cust.name.split()[0])
                        state = go(S.LOAD_BOOKING, f"{cust.id}, {cust.tier.value}")

                elif state is S.LOAD_BOOKING:
                    booking = call("res.load_booking", lambda: self.sys.res.get_booking(req.pnr or ""))
                    if booking is None:
                        reason = "booking not found"
                        state = go(S.HANDOFF, reason)
                    elif booking.customer_id != cust.id:
                        reason = "booking is not on the caller's profile"
                        state = go(S.HANDOFF, reason)
                    else:
                        facts.update(pnr=booking.pnr, flight=booking.flight)
                        state = go(S.ASSESS, f"{booking.pnr}, {booking.pax} pax")

                elif state is S.ASSESS:
                    flight = call("res.flight_status", lambda: self.sys.res.flight(booking.flight))
                    intent = call("nlu.read_intent", lambda: self.model.read_intent(req.text))
                    facts["status_text"] = (
                        f"delayed by {flight.delay_minutes} minutes"
                        if flight.status == "delayed"
                        else flight.status
                        if flight.status != "scheduled"
                        else "on time"
                    )
                    if intent is Intent.HUMAN:
                        reason = "customer asked for an agent"
                        state = go(S.HANDOFF, reason)
                    else:
                        state = go(S.ENTITLEMENT, f"{flight.number} {flight.status}; intent {intent.value}")

                elif state is S.ENTITLEMENT:
                    ent = call("policy.entitlement", lambda: entitlement(flight, booking, cust.tier))
                    if intent in (Intent.REBOOK, Intent.REFUND, Intent.VOUCHER) and intent not in ent.options:
                        blocked += 1
                    if not ent.options:
                        state = go(S.NOTIFY, f"{ent.reason}; inform only")
                        resolution = Resolution.INFORMED
                    else:
                        opts = ", ".join(sorted(o.value for o in ent.options))
                        state = go(S.OFFER, f"{ent.reason}; entitled to {opts}")

                elif state is S.OFFER:
                    if Intent.REBOOK in ent.options:
                        alts = call("res.find_alternatives", lambda: self.sys.res.alternatives(booking))
                        for f in alts:
                            options[f.number] = f"rebook:{f.number}"
                            facts[f"alt_{f.number}"] = f.number
                    if Intent.REFUND in ent.options:
                        options["refund"] = "refund"
                    if Intent.VOUCHER in ent.options:
                        options["voucher"] = "voucher"
                    facts["options"] = ", ".join(options)
                    send("options")
                    state = go(S.READ_CHOICE, f"offered {facts['options']}")

                elif state is S.READ_CHOICE:
                    choice = call(
                        "nlu.read_choice", lambda: self.model.read_choice(req.choice_text or "", list(options))
                    )
                    if choice is None:
                        if req.choice_text and self.model.read_intent(req.choice_text) in (
                            Intent.REFUND,
                            Intent.REBOOK,
                            Intent.VOUCHER,
                        ):
                            blocked += 1
                            reason = "customer asked for an option they are not entitled to"
                        else:
                            reason = "could not read the customer's choice"
                        state = go(S.HANDOFF, reason)
                    else:
                        action = options[choice]
                        nxt = S.REBOOK if action.startswith("rebook") else S.REFUND if action == "refund" else S.VOUCHER
                        state = go(nxt, f"customer chose {choice}")

                elif state is S.REBOOK:
                    new_no = options[choice].split(":")[1]
                    call("res.rebook", lambda: self.sys.res.rebook(booking.pnr, new_no))
                    try:
                        call(
                            "pay.reissue_ticket",
                            lambda: self.sys.pay.reissue_ticket(f"reissue:{req.id}", booking.pnr, new_no),
                        )
                    except SystemError_ as e:
                        reason = f"ticket reissue failed ({e.reason}); seats released"
                        state = go(S.COMPENSATE, reason)
                        continue
                    nf = self.sys.res.flight(new_no)
                    facts.update(new_flight=nf.number, new_departs=nf.departs[11:16])
                    resolution = Resolution.REBOOKED
                    state = go(S.NOTIFY, f"rebooked on {new_no}")

                elif state is S.REFUND:
                    p = call(
                        "pay.refund", lambda: self.sys.pay.refund(f"refund:{req.id}", booking.pnr, ent.refund_amount)
                    )
                    facts.update(amount=p.amount, payment=p.id)
                    resolution = Resolution.REFUNDED
                    state = go(S.NOTIFY, f"refund {p.id}")

                elif state is S.VOUCHER:
                    p = call(
                        "pay.issue_voucher",
                        lambda: self.sys.pay.issue_voucher(f"voucher:{req.id}", booking.pnr, ent.voucher_amount),
                    )
                    facts.update(amount=p.amount, payment=p.id)
                    resolution = Resolution.VOUCHER
                    state = go(S.NOTIFY, f"voucher {p.id}")

                elif state is S.COMPENSATE:
                    call("res.release_seats", lambda: self.sys.res.cancel_rebook(booking.pnr))
                    compensated = True
                    state = go(S.HANDOFF, "seats released; nothing left half-done")

                elif state is S.NOTIFY:
                    facts["case"] = call("crm.log_case", lambda: self.sys.crm.log_case(cust.id, resolution.value))
                    kind = {
                        Resolution.REBOOKED: "rebooked",
                        Resolution.REFUNDED: "refunded",
                        Resolution.VOUCHER: "voucher",
                        Resolution.INFORMED: "status",
                    }[resolution]
                    send(kind)
                    state = go(S.CLOSE, f"customer notified ({kind})")

                elif state is S.HANDOFF:
                    resolution = Resolution.HANDOFF
                    case = call("crm.log_case", lambda: self.sys.crm.log_case(cust.id if cust else "unknown", reason))
                    call("handoff.queue", lambda: None)
                    if cust is not None:
                        facts["case"] = case
                        send("handoff")
                    state = go(S.CLOSE, f"queued for an agent: {reason}")

                elif state is S.CLOSE:
                    state = go(S.DONE, resolution.value)

            except SystemError_ as e:
                # A system failed after retries. Whatever state we're in, a human takes over.
                reason = f"{e.system} unavailable: {e.reason}"
                if state in (S.HANDOFF, S.NOTIFY, S.CLOSE):
                    state = go(S.CLOSE, reason) if state is not S.CLOSE else go(S.DONE, reason)
                else:
                    state = go(S.HANDOFF, reason)

        trace.append(Step(S.DONE.value, resolution.value))
        return Outcome(
            request_id=req.id,
            resolution=resolution,
            reason=reason,
            trace=trace,
            skill_calls=len(ex.calls),
            retries_absorbed=ex.retries_absorbed,
            out_of_policy_blocked=blocked,
            ungrounded_blocked=ungrounded_count,
            compensated=compensated,
            messages=sent,
        )
