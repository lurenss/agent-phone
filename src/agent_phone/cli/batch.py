"""`agent-phone batch [FILE]`: the steps of an agent that already knows them, in one process.

Every CLI call pays process start, a device lock and a server check. A batch pays them once. Its
steps are the CLI's own argv arrays, parsed by `parse_args`, so a step means what the same words
mean on a command line. It opens the device once, holds its lock across the steps, runs them in
order and stops at the first step whose result is not ok.

The result is one envelope, `command: "batch"`. Each step's own envelope stands in `data.steps`
as that command alone would print it. `error` and `delivery` are the failed step's. `retry` is the
one value that is not the failed step's alone: it is `unsafe` when an earlier step sent input,
because running the batch again would send that input again. One trace per batch (`cli/trace.py`)
records each step as it ends.

Python callers do not need it: a `Driver` already runs steps one after the other in one process.
"""

from __future__ import annotations

import io
import json
import shlex
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from agent_phone.cli.args import parse_args
from agent_phone.cli.batch_args import BatchCommand
from agent_phone.cli.commands import READS, DriverCommand
from agent_phone.cli.driver import Driver, open_phone
from agent_phone.cli.settings import Settings
from agent_phone.cli.trace import Trace, end_record, step_record
from agent_phone.core.act.ledger import spends, unrefunded
from agent_phone.core.device import Serial
from agent_phone.core.envelope import VERSION, delivery_keys, floor_envelope, to_wire
from agent_phone.core.envelope import exit_code as outcome_code
from agent_phone.core.outcome import Disposition, ErrorCode, Outcome, Refusal, Refused
from agent_phone.core.phone import PhoneHub
from agent_phone.core.snapshot.snapshot import RefToken
from agent_phone.core.wait.clock import Clock

WEAKEST_FIRST = (
    Disposition.DELIVERY_UNCERTAIN,
    Disposition.DELIVERED_UNVERIFIED,
    Disposition.DELIVERED_VERIFIED,
)
SHAPE = (
    'The steps must be a JSON array of steps, each a non-empty array of strings, such as [["press", "back"]].'
)


@dataclass(frozen=True, slots=True)
class Step:
    index: int
    argv: tuple[str, ...]
    name: str
    command: DriverCommand
    policies: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class StepResult:
    step: Step
    started_utc: str
    ms: int
    envelope: Mapping[str, object]
    code: int

    @property
    def ok(self) -> bool:
        return self.envelope["ok"] is True

    @property
    def sent(self) -> bool:
        """Input may have left: any delivery but `not_delivered`. A read has none."""
        return (
            self.envelope.get("delivery", Disposition.NOT_DELIVERED.value) != Disposition.NOT_DELIVERED.value
        )


@dataclass(frozen=True, slots=True)
class BatchResult:
    device: Serial
    results: tuple[StepResult, ...]
    trace: Path

    @property
    def failed(self) -> StepResult | None:
        """The run stops at the first step that is not ok, so only the last can have failed."""
        return None if self.results[-1].ok else self.results[-1]

    @property
    def exit_code(self) -> int:
        failed = self.failed
        return 0 if failed is None else failed.code

    def wire(self) -> dict[str, object]:
        """Keys as `to_wire` orders them. `delivery` is the failed step's. A batch that sent and
        succeeded has the weakest delivery of its inputs, and one that sent nothing has none, like
        a read. `retry` follows `delivery` except after a failure that came after an input."""
        failed = self.failed
        wire: dict[str, object] = {
            "v": VERSION,
            "ok": failed is None,
            "command": "batch",
            "device": self.device,
        }
        if failed is not None:
            earlier = any(result.sent for result in self.results[:-1])
            wire["delivery"] = failed.envelope["delivery"]
            wire["retry"] = "unsafe" if earlier else failed.envelope["retry"]
        elif any(result.sent for result in self.results):
            sent = (Disposition(str(r.envelope["delivery"])) for r in self.results if r.sent)
            wire |= delivery_keys(min(sent, key=WEAKEST_FIRST.index))
        wire["data"] = {
            "steps": [result.envelope for result in self.results],
            "stopped_at": None if failed is None else failed.step.index,
            "trace": str(self.trace),
        }
        if failed is not None:
            wire["error"] = failed.envelope["error"]
        return wire


def read_steps(command: BatchCommand, stdin: TextIO) -> tuple[Step, ...]:
    """Every step parsed, or INVALID_ARGS, before any device is opened."""
    try:
        document = json.loads(source_text(command, stdin))
    except ValueError as error:
        raise Refusal(ErrorCode.INVALID_ARGS, f"The steps are not JSON: {error}. {SHAPE}") from error
    if not isinstance(document, list) or not document:
        raise Refusal(ErrorCode.INVALID_ARGS, SHAPE)
    for step in document:
        if not (isinstance(step, list) and step and all(isinstance(word, str) for word in step)):
            raise Refusal(ErrorCode.INVALID_ARGS, SHAPE)
    return tuple(parse_step(index, tuple(argv)) for index, argv in enumerate(document))


def source_text(command: BatchCommand, stdin: TextIO) -> str:
    if command.source is not None:
        try:
            return command.source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise Refusal(
                ErrorCode.INVALID_ARGS, f"The steps in {command.source} cannot be read: {error}."
            ) from error
    if stdin.isatty():
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            "No FILE was given and stdin is a terminal. Pass a FILE, or pipe the steps in.",
        )
    return stdin.read()


def parse_step(index: int, argv: tuple[str, ...]) -> Step:
    """The step through the CLI's own parser. Help text goes nowhere: a batch prints one envelope."""
    where = f"steps[{index}] {shlex.join(argv)!r}"
    try:
        with redirect_stdout(io.StringIO()):
            invocation = parse_args(argv)
    except SystemExit as error:
        raise Refusal(
            ErrorCode.INVALID_ARGS, f"{where} asks for help. A step is a command to run."
        ) from error
    except Refusal as refusal:
        raise Refusal(refusal.code, f"{where}: {refusal.message}", refusal.details) from refusal
    command = invocation.command
    if not isinstance(command, DriverCommand):
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{where}: {invocation.name} is not a step. A step reads or drives the phone: "
            "snapshot, find, get, is, wait, click, set-text, scroll, press, launch, stop, open-url, "
            "rotate, clipboard or screenshot.",
        )
    if invocation.serial is not None:
        raise Refusal(ErrorCode.INVALID_ARGS, f"{where} names its own device. Give -d once, on the batch.")
    return Step(index, argv, invocation.name, command, invocation.policies)


def run_batch(
    steps: Sequence[Step],
    serial: Serial | None,
    ref: RefToken | None,
    hub: PhoneHub,
    settings: Settings,
    clock: Clock,
) -> BatchResult:
    """One open phone, one lock, the steps in order. A policy file that does not parse refuses the
    batch before the first step, with nothing sent."""
    with open_phone(
        serial,
        hub=hub,
        settings=settings,
        clock=clock,
        command="batch",
        ref=ref,
        first_read=isinstance(steps[0].command, READS),
    ) as driver:
        drivers = [driver.with_policies(step.policies) for step in steps]
        results: list[StepResult] = []
        began = clock.now()
        with Trace.open(settings.state_root, driver.serial) as trace:
            for step, under in zip(steps, drivers, strict=True):
                result = run_step(step, under, clock)
                trace.append(
                    step_record(
                        step.index, step.argv, step.command, result.started_utc, result.ms, result.envelope
                    )
                )
                results.append(result)
                if not result.ok:
                    break
            stopped = None if results[-1].ok else results[-1].step.index
            trace.append(end_record(stopped, milliseconds(clock.now() - began)))
        return BatchResult(driver.serial, tuple(results), trace.path)


def run_step(step: Step, driver: Driver, clock: Clock) -> StepResult:
    """One step's envelope, as `process.run` makes it for a command alone. A step that raises is
    the failed step, with an INTERNAL envelope, so the batch still reports what ran before it. The
    permits it spent are told apart from the earlier steps' (`spends`)."""
    spent = spends()
    started = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    began = clock.now()
    outcome: Outcome
    try:
        outcome = driver.run(step.command)
    except Refusal as refusal:
        if unrefunded(spent):
            envelope, code = floor_envelope(step.name, driver.serial, refusal, unrefunded=True), 1
            return StepResult(step, started, milliseconds(clock.now() - began), envelope, code)
        outcome = Refused.of(refusal)
    except Exception as error:
        envelope = floor_envelope(step.name, driver.serial, error, unrefunded=unrefunded(spent))
        return StepResult(step, started, milliseconds(clock.now() - began), envelope, 1)
    envelope = to_wire(step.name, driver.serial, outcome)
    return StepResult(step, started, milliseconds(clock.now() - began), envelope, outcome_code(outcome))


def milliseconds(seconds: float) -> int:
    return round(seconds * 1000)
