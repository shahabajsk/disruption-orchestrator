import pytest

from orchestrator.eval import SloppyWriter, run
from orchestrator.machine import ALLOWED, TRANSITIONS, Orchestrator, S
from orchestrator.models import Resolution
from orchestrator.scenarios import MIX, all_scenarios, build
from orchestrator.skills import REGISTRY, Executor, SkillNotAllowed


def test_every_trace_follows_declared_transitions():
    for sc in all_scenarios():
        trace = Orchestrator(sc.systems).run(sc.request).trace
        for a, b in zip(trace, trace[1:], strict=False):
            assert S(b.state) in TRANSITIONS[S(a.state)], f"{sc.id}: {a.state} -> {b.state}"


def test_allowlists_only_name_registered_skills():
    for state, skills in ALLOWED.items():
        assert skills <= set(REGISTRY), state


def test_a_state_cannot_call_a_skill_outside_its_allowlist():
    with pytest.raises(SkillNotAllowed):
        Executor().run("pay.refund", ALLOWED[S.ASSESS], lambda: None)


def test_ghost_commit_does_not_double_pay():
    sc = build("refund_ghost_commit", 0, 42)
    out = Orchestrator(sc.systems).run(sc.request)
    assert out.resolution is Resolution.REFUNDED
    assert len(sc.systems.pay.ledger) == 1
    assert out.retries_absorbed >= 1


def test_failed_reissue_releases_the_seats():
    sc = build("reissue_fails", 0, 42)
    out = Orchestrator(sc.systems).run(sc.request)
    assert out.compensated and out.resolution is Resolution.HANDOFF
    assert {k: f.seats_left for k, f in sc.systems.res._f.items()} == sc.seats_before


def test_prompt_injection_moves_no_money():
    for i in range(MIX["prompt_injection"][0]):
        sc = build("prompt_injection", i, 42)
        out = Orchestrator(sc.systems).run(sc.request)
        assert not sc.systems.pay.ledger
        assert out.out_of_policy_blocked >= 1


def test_no_consent_on_the_request_channel_falls_back():
    sc = build("consent_fallback", 0, 42)
    out = Orchestrator(sc.systems).run(sc.request)
    assert out.messages and all(m.startswith("[sms]") for m in out.messages)


def test_runs_are_deterministic():
    for k in MIX:
        a, b = build(k, 0, 42), build(k, 0, 42)
        assert (
            Orchestrator(a.systems).run(a.request).fingerprint() == Orchestrator(b.systems).run(b.request).fingerprint()
        )


def test_invariants_hold_even_with_a_sloppy_writer():
    sloppy = SloppyWriter(0.5)
    r = run(lambda: sloppy)
    assert r["ungrounded_drafts_caught"] > 0
    for k in ("duplicate_payments", "seats_leaked", "out_of_policy_payments", "ungrounded_messages_sent"):
        assert r[k] == 0, k


def test_baseline_is_pinned():
    # If this moves, update the README table in the same change.
    r = run(lambda: __import__("orchestrator.model", fromlist=["RuleModel"]).RuleModel())
    assert r["correct_resolution"] == 0.959
    assert r["misses_by_kind"] == {"time_of_day_choice": 4}


@pytest.mark.parametrize(
    "text,options,expected",
    [
        ("paise wapas kar do", ["ZZ102", "ZZ104", "refund"], "refund"),
        ("पैसे वापस चाहिए", ["ZZ102", "refund"], "refund"),
        ("pehli wali flight de do", ["ZZ102", "ZZ104", "refund"], "ZZ102"),
        ("theek hai", ["voucher"], "voucher"),
        ("agli flight", ["ZZ102", "ZZ104", "refund"], None),  # two flights offered, no pick: ambiguous
        ("the evening one works", ["ZZ102", "ZZ104", "refund"], None),  # known gap, hands off
    ],
)
def test_choice_reader_handles_hinglish_and_refuses_to_guess(text, options, expected):
    from orchestrator.model import RuleModel

    assert RuleModel().read_choice(text, options) == expected


def test_contact_ids_are_unique():
    ids = [sc.id for sc in all_scenarios()]
    assert len(ids) == len(set(ids))
