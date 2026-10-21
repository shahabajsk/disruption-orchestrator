"""Run one contact end to end.

python -m orchestrator list
python -m orchestrator run reissue_fails
python -m orchestrator run prompt_injection --index 2
python -m orchestrator replay            # every run twice, fingerprints must match
"""

from __future__ import annotations

import argparse

from .machine import Orchestrator
from .scenarios import MIX, build


def main() -> None:
    ap = argparse.ArgumentParser(prog="orchestrator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("kind", choices=list(MIX))
    r.add_argument("--index", type=int, default=0)
    r.add_argument("--seed", type=int, default=42)
    sub.add_parser("replay")
    args = ap.parse_args()

    if args.cmd == "list":
        for k, (n, exp) in MIX.items():
            print(f"{k:<22} x{n:<3} expected {exp.value}")
        return

    if args.cmd == "replay":
        mismatches = 0
        total = 0
        for k, (n, _) in MIX.items():
            for i in range(n):
                a = Orchestrator(build(k, i, 42).systems).run(build(k, i, 42).request).fingerprint()
                sc = build(k, i, 42)
                b = Orchestrator(sc.systems).run(sc.request).fingerprint()
                total += 1
                mismatches += a != b
        print(f"{total} contacts replayed, {mismatches} fingerprint mismatches")
        raise SystemExit(1 if mismatches else 0)

    sc = build(args.kind, args.index, args.seed)
    out = Orchestrator(sc.systems).run(sc.request)
    print(f"contact   {sc.request.id}  ({sc.kind})")
    print(f"says      {sc.request.text!r}")
    if sc.request.choice_text:
        print(f"replies   {sc.request.choice_text!r}\n")
    for s in out.trace:
        print(f"  {s.state:<13} {s.note}")
    print(
        f"\nresolution {out.resolution.value}   (expected {sc.expected.value})   "
        f"{out.skill_calls} skill calls, {out.retries_absorbed} retries absorbed, fingerprint {out.fingerprint()}"
    )
    for m in out.messages:
        print(f"  -> {m}")


if __name__ == "__main__":
    main()
