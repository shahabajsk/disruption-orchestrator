"""Domain records. Synthetic airline; every name, number and flight is invented."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Tier(str, Enum):
    BASE = "base"
    SILVER = "silver"
    GOLD = "gold"


class Customer(BaseModel):
    id: str
    name: str
    phone: str
    tier: Tier
    consented_channels: list[str] = Field(description="whatsapp | sms | email")


class Flight(BaseModel):
    number: str
    origin: str
    dest: str
    departs: str = Field(description="ISO datetime, local")
    status: str = Field(description="scheduled | delayed | cancelled")
    delay_minutes: int = 0
    seats_left: int


class Booking(BaseModel):
    pnr: str
    customer_id: str
    flight: str
    pax: int
    fare_paid: int = Field(description="whole rupees, all passengers")


class Payment(BaseModel):
    id: str
    pnr: str
    amount: int
    kind: str  # refund | voucher


class Message(BaseModel):
    customer_id: str
    channel: str
    body: str


class Intent(str, Enum):
    REBOOK = "rebook"
    REFUND = "refund"
    VOUCHER = "voucher"
    STATUS = "status"
    HUMAN = "human"
    UNCLEAR = "unclear"


class Request(BaseModel):
    """One inbound customer contact."""

    id: str
    phone: str
    pnr: str | None
    text: str
    channel: str = "whatsapp"
    choice_text: str | None = Field(default=None, description="the customer's reply when offered options")


class Resolution(str, Enum):
    REBOOKED = "rebooked"
    REFUNDED = "refunded"
    VOUCHER = "voucher"
    INFORMED = "informed"
    HANDOFF = "handoff"
