"""Entitlement policy. Plain code a client's customer-experience and legal teams can sign off.

The numbers here are illustrative, not any regulator's or airline's actual rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Booking, Flight, Intent, Tier

VOUCHER_PER_PAX = 500


@dataclass(frozen=True)
class Entitlement:
    options: frozenset[Intent]
    voucher_amount: int
    refund_amount: int
    reason: str


def entitlement(flight: Flight, booking: Booking, tier: Tier) -> Entitlement:
    if flight.status == "cancelled":
        return Entitlement(frozenset({Intent.REBOOK, Intent.REFUND}), 0, booking.fare_paid, "flight cancelled")
    if flight.status == "delayed" and flight.delay_minutes >= 180:
        return Entitlement(frozenset({Intent.REBOOK, Intent.REFUND}), 0, booking.fare_paid, "delay of 3 hours or more")
    if flight.status == "delayed" and flight.delay_minutes >= 120:
        amount = VOUCHER_PER_PAX * booking.pax * (2 if tier is Tier.GOLD else 1)
        return Entitlement(frozenset({Intent.VOUCHER}), amount, 0, "delay of 2 to 3 hours")
    return Entitlement(frozenset(), 0, 0, "no disruption entitlement")
