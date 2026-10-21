"""Skill registry.

A skill is one typed call into one system. Each declares what it touches and whether it
writes, so the machine can enforce three rules no prompt can talk its way around:

1. A state may only call the skills on its allowlist.
2. Writes that can be retried carry an idempotency key.
3. Writes that leave the world half-changed have a declared compensation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .systems import SystemError_


@dataclass(frozen=True)
class Skill:
    name: str
    system: str
    writes: bool
    compensation: str | None = None
    max_retries: int = 2


REGISTRY: dict[str, Skill] = {
    s.name: s
    for s in [
        Skill("crm.identify_customer", "crm", writes=False),
        Skill("crm.log_case", "crm", writes=True),
        Skill("res.load_booking", "res", writes=False),
        Skill("res.flight_status", "res", writes=False),
        Skill("res.find_alternatives", "res", writes=False),
        Skill("res.rebook", "res", writes=True, compensation="res.release_seats"),
        Skill("res.release_seats", "res", writes=True),
        Skill("pay.reissue_ticket", "pay", writes=True),
        Skill("pay.refund", "pay", writes=True),
        Skill("pay.issue_voucher", "pay", writes=True),
        Skill("policy.entitlement", "policy", writes=False),
        Skill("nlu.read_intent", "model", writes=False),
        Skill("nlu.read_choice", "model", writes=False),
        Skill("compose.message", "model", writes=False),
        Skill("msg.send", "msg", writes=True),
        Skill("handoff.queue", "human", writes=True),
    ]
}


class SkillNotAllowed(RuntimeError):
    pass


@dataclass
class Call:
    skill: str
    attempt: int
    ok: bool
    note: str


class Executor:
    """Runs a skill with retries on retryable failures and records every attempt."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.retries_absorbed = 0

    def run(self, skill_name: str, allowed: frozenset[str], fn: Callable[[], object]) -> object:
        if skill_name not in allowed:
            raise SkillNotAllowed(skill_name)
        skill = REGISTRY[skill_name]
        attempt = 0
        while True:
            attempt += 1
            try:
                out = fn()
                self.calls.append(Call(skill_name, attempt, True, "ok"))
                if attempt > 1:
                    self.retries_absorbed += attempt - 1
                return out
            except SystemError_ as e:
                self.calls.append(Call(skill_name, attempt, False, e.reason))
                if not e.retryable or attempt > skill.max_retries:
                    raise
