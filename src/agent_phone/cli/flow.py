"""`agent-phone flow run FILE`: a job that was written once, replayed in one call with no agent
turn between its steps.

A flow is the parser's vocabulary, not a second way to send input. Each step is an argv that
`parse_args` parsed (`cli/flow_file.py`), and it runs as a batch step runs, through `Driver.run`,
so the same gate judges it as judges the same words on a command line. The runner adds three
things around a step:

- **An observation before it.** A step's `expect` queries are waited for first, and the read
  they hold on is the observation the step needs. A step with no `expect` gets one look when the
  step before it left no observation, because every input needs a current one.
- **A cap and a grant.** The file's `grants` cap what a step may grant itself, and the flow runs
  only when the caller's `--commit` names every effect in `grants`. The caller's grant reaches no
  step: a step is judged under its own `--commit`, as in a batch.
- **A dry run.** `--dry-run` judges every step as `ask` does and with no grant, so the gate
  itself refuses the first step that would commit, and the flow stops there with nothing of
  that step sent. The steps before it run. The stop is ok only when the step's own `--commit`
  names the effects, because a real run would refuse the step otherwise.

It stops at the first expectation that does not show and at the first step that is not ok, and
prints one small envelope: which step, why, and the failed step's own `details`. The steps'
envelopes are not printed. Each call leaves its begin and end line in the device's trace of the
day. The begin line has the words of the flow file, so text that a parameter typed is never
written. A parameter inside a query names something on the screen, and the end line holds the
query and the name it resolved to, as for any command.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from agent_phone.cli.batch import StepResult, delivery_of, parse_step, run_step
from agent_phone.cli.commands import READS
from agent_phone.cli.driver import Driver, open_phone
from agent_phone.cli.flow_args import FlowRunCommand
from agent_phone.cli.flow_file import Call, Flow, Planned, plan, read_flow
from agent_phone.cli.settings import Settings
from agent_phone.cli.trace import Trace, at
from agent_phone.core.device import Serial
from agent_phone.core.envelope import VERSION
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import PhoneHub
from agent_phone.core.policy.mode import PermissionMode
from agent_phone.core.wait.clock import Clock

LOOK = ("snapshot",)


@dataclass(frozen=True, slots=True)
class Ran:
    """One call the runner made for step `index`: its `look`, its `expect` or its `run`."""

    index: int
    during: str
    result: StepResult


@dataclass(frozen=True, slots=True)
class FlowResult:
    flow: Flow
    steps: tuple[Planned, ...]
    device: Serial
    mode: PermissionMode
    dry_run: bool
    calls: tuple[Ran, ...]
    trace: Path

    @property
    def stopped(self) -> Ran | None:
        """The run stops at the first call that is not ok, so only the last can have stopped it."""
        return None if self.calls[-1].result.ok else self.calls[-1]

    @property
    def commit(self) -> list[object] | None:
        """The effects of the step a dry run stopped before. None when it did not stop for a
        commit, and when the step's own `--commit` does not name them: a real run would refuse
        that step, so the dry run fails on it too."""
        stopped = self.stopped
        if not self.dry_run or stopped is None or stopped.during != "run":
            return None
        error = stopped.result.envelope["error"]
        effects = at(error, "details", "effects")
        if at(error, "code") != ErrorCode.COMMIT_REFUSED.value or not isinstance(effects, list):
            return None
        own = getattr(self.steps[stopped.index].run.step.command, "commit", frozenset())
        return effects if set(effects) <= {effect.value for effect in own} else None

    @property
    def failed(self) -> Ran | None:
        return None if self.commit is not None else self.stopped

    @property
    def exit_code(self) -> int:
        failed = self.failed
        return 0 if failed is None else failed.result.code

    def wire(self) -> dict[str, object]:
        """Keys as `to_wire` orders them. `delivery` and `retry` follow a batch's rule
        (`batch.delivery_of`). A dry run that stopped before a commit is ok, and its delivery is
        that of the calls before the stop."""
        stopped, failed = self.stopped, self.failed
        results = [ran.result for ran in self.calls]
        wire: dict[str, object] = {
            "v": VERSION,
            "ok": failed is None,
            "command": "flow run",
            "permission_mode": self.mode.value,
            "device": self.device,
        }
        wire |= delivery_of(results if stopped is failed else results[:-1])
        wire["data"] = {
            "flow": self.flow.name,
            "steps": len(self.steps),
            "ran": sum(ran.during == "run" and ran.result.ok for ran in self.calls),
            "stopped_at": None if stopped is None else stopped.index,
            "dry_run": self.dry_run,
            "commit": self.commit,
            "trace": str(self.trace),
        }
        if failed is not None:
            error = failed.result.envelope["error"]
            assert isinstance(error, dict)
            wire["error"] = error | {
                "details": error["details"] | {"step": failed.index, "during": failed.during}
            }
        return wire


def run_flow_file(
    command: FlowRunCommand, serial: Serial | None, hub: PhoneHub, settings: Settings, clock: Clock
) -> FlowResult:
    """Load, check and run. Everything before `open_phone` refuses with no device opened."""
    flow = read_flow(command.source)
    steps = plan(flow, command.values)
    missing = sorted(effect.value for effect in flow.grants - command.commit)
    if command.dry_run:
        settings = replace(settings, permission_mode=PermissionMode.ASK)
    elif missing and settings.permission_mode is PermissionMode.ASK:
        raise Refusal(
            ErrorCode.COMMIT_REFUSED,
            f"The flow {flow.name} would {' and '.join(missing)}. It runs only with "
            f"{' '.join(f'--commit {effect}' for effect in missing)}, or with --dry-run, which stops "
            "before the first commit. Grant an effect only when your user asked for this commit.",
            {
                "effects": sorted(effect.value for effect in flow.grants),
                "granted": sorted(effect.value for effect in command.commit),
            },
        )
    with open_phone(
        serial, hub=hub, settings=settings, clock=clock, command="flow run", first_read=True
    ) as driver:
        return run_flow(flow, steps, driver, clock, settings.state_root, command.dry_run)


def run_flow(
    flow: Flow, steps: Sequence[Planned], driver: Driver, clock: Clock, state_root: Path, dry_run: bool
) -> FlowResult:
    """One open phone, one lock, the steps in order. A policy file that does not parse refuses the
    flow before the first step, with nothing sent."""
    drivers = [driver.with_policies(step.run.step.policies) for step in steps]
    calls: list[Ran] = []
    with Trace.daily(state_root, driver.serial) as trace:

        def ok(index: int, during: str, call: Call, under: Driver) -> bool:
            seq = trace.begin(call.step.name, call.written, flow=flow.name, step=index)
            result = run_step(call.step, under, clock)
            trace.end(seq, call.step.command, result.envelope, result.ms)
            calls.append(Ran(index, during, result))
            return result.ok

        observed = False
        for index, (step, under) in enumerate(zip(steps, drivers, strict=True)):
            reads = isinstance(step.run.step.command, READS)
            before = None if step.expect is None else ("expect", step.expect)
            if before is None and not (observed or reads):
                before = ("look", Call(parse_step(index, LOOK), LOOK))
            if before is not None and not ok(index, *before, driver):
                break
            if not ok(index, "run", ungranted(step.run) if dry_run else step.run, under):
                break
            observed = reads or at(calls[-1].result.envelope, "data", "after") is not None
    return FlowResult(flow, tuple(steps), driver.serial, driver.mode, dry_run, tuple(calls), trace.path)


def ungranted(call: Call) -> Call:
    """The same command with no grant, which can only make the gate refuse more."""
    command = call.step.command
    if not getattr(command, "commit", None):
        return call
    return replace(call, step=replace(call.step, command=replace(command, commit=frozenset())))
