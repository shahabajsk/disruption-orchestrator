"""Mock enterprise systems: CRM, reservations, payments, messaging.

Each one behaves like the real thing in the ways that break agents: it can time out, it
can reject a write, and it does not know about the others. Faults are injected per call
from a seeded plan so every eval run is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Booking, Customer, Flight, Message, Payment


class SystemError_(RuntimeError):
    """A downstream system refused or failed the call."""

    def __init__(self, system: str, reason: str, retryable: bool) -> None:
        super().__init__(f"{system}: {reason}")
        self.system = system
        self.reason = reason
        self.retryable = retryable


@dataclass
class FaultPlan:
    """Which calls fail. Keys are '<system>.<operation>', values are how many times to fail first."""

    fail_first: dict[str, int] = field(default_factory=dict)
    hard_fail: set[str] = field(default_factory=set)
    # commit the write, then report a timeout: the case idempotency keys exist for
    ghost_commit: set[str] = field(default_factory=set)

    def after_commit(self, key: str) -> None:
        if key in self.ghost_commit:
            self.ghost_commit.discard(key)
            raise SystemError_(key.split(".")[0], f"{key} timed out after commit", retryable=True)

    def check(self, key: str) -> None:
        if key in self.hard_fail:
            system = key.split(".")[0]
            raise SystemError_(system, f"{key} rejected", retryable=False)
        left = self.fail_first.get(key, 0)
        if left > 0:
            self.fail_first[key] = left - 1
            raise SystemError_(key.split(".")[0], f"{key} timed out", retryable=True)


class CRM:
    def __init__(self, customers: dict[str, Customer], faults: FaultPlan) -> None:
        self._c = customers
        self.faults = faults

    def find_by_phone(self, phone: str) -> Customer | None:
        self.faults.check("crm.find")
        return next((c for c in self._c.values() if c.phone == phone), None)

    def log_case(self, customer_id: str, summary: str) -> str:
        self.faults.check("crm.log")
        return f"CASE-{abs(hash((customer_id, summary))) % 100000:05d}"


class Reservations:
    def __init__(self, bookings: dict[str, Booking], flights: dict[str, Flight], faults: FaultPlan) -> None:
        self._b = bookings
        self._f = flights
        self.faults = faults
        self.rebooked: dict[str, str] = {}

    def get_booking(self, pnr: str) -> Booking | None:
        self.faults.check("res.get")
        return self._b.get(pnr)

    def flight(self, number: str) -> Flight:
        self.faults.check("res.flight")
        return self._f[number]

    def alternatives(self, booking: Booking) -> list[Flight]:
        self.faults.check("res.alts")
        orig = self._f[booking.flight]
        return sorted(
            (
                f
                for f in self._f.values()
                if f.origin == orig.origin
                and f.dest == orig.dest
                and f.number != orig.number
                and f.status == "scheduled"
                and f.seats_left >= booking.pax
            ),
            key=lambda f: f.departs,
        )[:3]

    def rebook(self, pnr: str, flight_no: str) -> str:
        self.faults.check("res.rebook")
        f = self._f[flight_no]
        b = self._b[pnr]
        if f.seats_left < b.pax:
            raise SystemError_("res", "no seats", retryable=False)
        f.seats_left -= b.pax
        self.rebooked[pnr] = flight_no
        return flight_no

    def cancel_rebook(self, pnr: str) -> None:
        """Compensation for rebook."""
        flight_no = self.rebooked.pop(pnr, None)
        if flight_no:
            self._f[flight_no].seats_left += self._b[pnr].pax


class Payments:
    def __init__(self, faults: FaultPlan) -> None:
        self.faults = faults
        self.ledger: dict[str, Payment] = {}

    def refund(self, idempotency_key: str, pnr: str, amount: int) -> Payment:
        # Idempotency: a retried refund with the same key returns the first result.
        if idempotency_key in self.ledger:
            return self.ledger[idempotency_key]
        self.faults.check("pay.refund")
        p = Payment(id=f"PAY-{len(self.ledger) + 1:04d}", pnr=pnr, amount=amount, kind="refund")
        self.ledger[idempotency_key] = p
        self.faults.after_commit("pay.refund")
        return p

    def issue_voucher(self, idempotency_key: str, pnr: str, amount: int) -> Payment:
        if idempotency_key in self.ledger:
            return self.ledger[idempotency_key]
        self.faults.check("pay.voucher")
        p = Payment(id=f"VCH-{len(self.ledger) + 1:04d}", pnr=pnr, amount=amount, kind="voucher")
        self.ledger[idempotency_key] = p
        self.faults.after_commit("pay.voucher")
        return p

    def reissue_ticket(self, idempotency_key: str, pnr: str, flight_no: str) -> str:
        if idempotency_key in self.ledger:
            return self.ledger[idempotency_key].id
        self.faults.check("pay.reissue")
        p = Payment(id=f"TKT-{len(self.ledger) + 1:04d}", pnr=pnr, amount=0, kind="reissue")
        self.ledger[idempotency_key] = p
        return p.id


class Messaging:
    def __init__(self, faults: FaultPlan) -> None:
        self.faults = faults
        self.outbox: list[Message] = []

    def send(self, customer: Customer, channel: str, body: str) -> Message:
        self.faults.check("msg.send")
        if channel not in customer.consented_channels:
            raise SystemError_("msg", f"no consent for {channel}", retryable=False)
        m = Message(customer_id=customer.id, channel=channel, body=body)
        self.outbox.append(m)
        return m


@dataclass
class Systems:
    crm: CRM
    res: Reservations
    pay: Payments
    msg: Messaging
