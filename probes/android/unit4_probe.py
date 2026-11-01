"""Live checks for unit 4 that send no input. Run from the repo root:

    uv run python -I probes/android/unit4_probe.py staleness <label>

`staleness` answers the open item of unit 1: how often does the row key stale a ref on a live
screen with nothing sent between the snapshot and the use? It takes a settled snapshot of the
screen that shows, waits a gap, reads again, and finds every ref of the snapshot on that read,
the way an input would. It prints one JSON line per round and one per gap, then the inputs it
sent, which are none. Names are never printed, only roles, so a capture holds no screen text.
"""

import json
import sys
import time
from collections import Counter

from agent_phone.cli.driver import open_phone
from agent_phone.core.outcome import Refusal
from agent_phone.core.refs.resolve import RefTarget, locate

GAPS_S = ((0.0, 10), (2.0, 5), (10.0, 5), (65.0, 3))
"""Seconds between the snapshot and the read, and the rounds for each. 65 s lets a clock tick."""


def emit(**row):
    print(json.dumps(row), flush=True)


def staleness(label: str) -> None:
    with open_phone(command="unit4 staleness") as phone:
        ctx = phone._ctx
        for gap, rounds in GAPS_S:
            totals: Counter[str] = Counter()
            for n in range(rounds):
                taken = phone.snapshot(settle=True)
                time.sleep(gap)
                screen = ctx.phone.read()
                outcome: Counter[str] = Counter()
                failed = []
                for number, fingerprint in taken.fingerprints.items():
                    try:
                        locate(RefTarget(taken.ref(number)), taken, screen)
                        outcome["ok"] += 1
                    except Refusal as refusal:
                        reason = refusal.details.get("reason", refusal.code.value)
                        outcome[str(reason)] += 1
                        failed.append(
                            {"role": fingerprint.key.role.value, "in_row": fingerprint.key.row is not None}
                        )
                totals.update(outcome)
                emit(
                    check="staleness_round",
                    screen=label,
                    app=taken.package,
                    settled=taken.settled.value,
                    gap_s=gap,
                    round=n,
                    refs=len(taken.fingerprints),
                    **outcome,
                    failed=failed,
                )
            refs = sum(totals.values())
            emit(
                check="staleness",
                screen=label,
                gap_s=gap,
                rounds=rounds,
                refs=refs,
                stale=refs - totals["ok"],
                rate=round_to((refs - totals["ok"]) / refs) if refs else None,
                **{key: value for key, value in totals.items() if key != "ok"},
            )


def round_to(value: float) -> float:
    return round(value, 4)


COMMANDS = {"staleness": staleness}

if __name__ == "__main__":
    try:
        COMMANDS[sys.argv[1]](sys.argv[2])
    finally:
        emit(check="inputs_sent", inputs=[])
