"""Language-model boundary.

The model reads what the customer wants and writes the message. It never chooses a skill,
an amount or a flight: those come from the machine, the policy and the systems. That is
why a prompt injection in the customer's text can change what the model *says the customer
wants*, but not what the airline *does*.

RuleModel runs offline and drives CI. ClaudeModel is a drop-in when ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

from .models import Intent


class Model(Protocol):
    name: str

    def read_intent(self, text: str) -> Intent: ...

    def read_choice(self, text: str, options: list[str]) -> str | None: ...

    def compose(self, facts: dict, kind: str) -> str: ...


TEMPLATES = {
    "options": "Hi {name}, flight {flight} is {status_text}. You can choose: {options}. Reply with your choice.",
    "rebooked": "Hi {name}, you're rebooked on {new_flight} departing {new_departs}. Ticket reissued. Case {case}.",
    "refunded": "Hi {name}, a refund of ₹{amount:,} for booking {pnr} is on its way. Reference {payment}. Case {case}.",
    "voucher": "Hi {name}, we've issued a ₹{amount:,} voucher for booking {pnr}. Reference {payment}. Case {case}.",
    "status": "Hi {name}, flight {flight} is {status_text}. No action is needed on booking {pnr}.",
    "handoff": "Hi {name}, an agent will pick this up shortly. Case {case}.",
}


class RuleModel:
    name = "rule-v1"

    def read_intent(self, text: str) -> Intent:
        t = text.lower()
        if any(k in t for k in ("agent", "human", "call me", "speak to")):
            return Intent.HUMAN
        if "refund" in t or "money back" in t:
            return Intent.REFUND
        if "voucher" in t:
            return Intent.VOUCHER
        if any(k in t for k in ("rebook", "another flight", "next flight", "change flight")):
            return Intent.REBOOK
        if any(k in t for k in ("status", "delayed", "cancelled", "late", "on time", "what's happening")):
            return Intent.STATUS
        return Intent.UNCLEAR

    def read_choice(self, text: str, options: list[str]) -> str | None:
        t = text.lower().strip()
        hits = [o for o in options if o.lower() in t]
        if len(hits) == 1:
            return hits[0]
        if t in ("1", "2", "3") and int(t) <= len(options):
            return options[int(t) - 1]
        if t in ("ok", "okay", "yes", "fine") and len(options) == 1:
            return options[0]
        return None

    def compose(self, facts: dict, kind: str) -> str:
        return TEMPLATES[kind].format(**facts)


class ClaudeModel:
    """Same contract against the Anthropic API. Output is still checked by the machine."""

    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ORCH_MODEL", "claude-sonnet-5-5")
        self.name = self.model

    def _ask(self, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.model, max_tokens=300, messages=[{"role": "user", "content": prompt}]
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    def read_intent(self, text: str) -> Intent:
        labels = ", ".join(i.value for i in Intent)
        raw = self._ask(f"Customer message: {text!r}\nClassify as one of: {labels}. Reply with the label only.")
        try:
            return Intent(raw.strip().lower())
        except ValueError:
            return Intent.UNCLEAR

    def read_choice(self, text: str, options: list[str]) -> str | None:
        raw = self._ask(
            f"Options: {json.dumps(options)}\nCustomer reply: {text!r}\n"
            "Reply with the exact option chosen, or NONE if unclear."
        )
        return raw if raw in options else None

    def compose(self, facts: dict, kind: str) -> str:
        return self._ask(
            f"Write a short {kind} message to an airline customer using only these facts, "
            f"no other numbers or flight codes:\n{json.dumps(facts, default=str)}"
        )


FLIGHT = re.compile(r"\b[A-Z]{2}\d{3,4}\b")
AMOUNT = re.compile(r"₹\s?([0-9][0-9,]*)")


def ungrounded(body: str, facts: dict) -> list[str]:
    """Flight codes and amounts in an outbound message must come from the case facts."""
    known = {str(v) for v in facts.values()} | {f"{v:,}" for v in facts.values() if isinstance(v, int)}
    issues = [f for f in FLIGHT.findall(body) if f not in known]
    issues += [a for a in AMOUNT.findall(body) if a not in known and a.replace(",", "") not in known]
    return issues
