"""A flow file: a job written once as steps, replayed by what each target is.

    [flow]
    name = "settings-search"
    app = "<package>"                 # optional, for the reader: nothing checks it yet
    grants = []                       # the cap on what the steps may commit
    params = ["query"]

    [[step]]
    run = ["launch", "<package>"]

    [[step]]
    expect = ["name=Search settings"]                       # queries that must show before it acts
    run = ["set-text", "name=Search settings", "{query}"]   # a query, never a ref or a point

A step's `run` is the argv of one command, parsed by `parse_args` as a batch step is, so a flow
adds no vocabulary. `{name}` in a word stands for a parameter. Everything here is checked before a
device is opened: a step that does not parse, that names a ref or a point, or whose `--commit`
names an effect outside `grants` refuses the whole flow.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from agent_phone.cli.batch import Step, parse_step
from agent_phone.cli.commands import DriverCommand
from agent_phone.cli.input_args import package_name
from agent_phone.cli.trace import target_of
from agent_phone.core.commands.find import FindCommand
from agent_phone.core.commands.get import GetCommand
from agent_phone.core.commands.is_ import IsCommand
from agent_phone.core.commands.snapshot import SnapshotCommand
from agent_phone.core.device import Package
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.rules import Effect
from agent_phone.core.refs.resolve import PointTarget, RefTarget

FLOW_KEYS = {"name", "app", "grants", "params"}
STEP_KEYS = {"expect", "run"}
PARAMETER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True, slots=True)
class FlowStep:
    """`expect` holds queries that must all show before the step acts. `run` is an argv."""

    expect: tuple[str, ...]
    run: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Flow:
    name: str
    app: Package | None
    grants: frozenset[Effect]
    params: tuple[str, ...]
    steps: tuple[FlowStep, ...]


@dataclass(frozen=True, slots=True)
class Call:
    """A parsed command, and the words the flow file wrote for it. `written` holds a parameter's
    name where the command holds its value, so it is what a trace line may show."""

    step: Step
    written: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Planned:
    """One step with its parameters filled in. `expect` is the `wait` its expectations make."""

    run: Call
    expect: Call | None


def read_flow(path: Path) -> Flow:
    """The file as a `Flow`, or INVALID_ARGS. An unknown key is refused, so a misspelt `grants`
    cannot pass for no cap."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise Refusal(ErrorCode.INVALID_ARGS, f"The flow {path} cannot be read: {error}.") from error
    head, steps = document.get("flow"), document.get("step")
    if set(document) - {"flow", "step"} or not isinstance(head, dict) or set(head) - FLOW_KEYS:
        bad(path, f"it takes one [flow] table with {', '.join(sorted(FLOW_KEYS))}, and [[step]] tables")
    name, app = head.get("name"), head.get("app")
    grants, params = strings(head.get("grants", [])), strings(head.get("params", []))
    if not isinstance(name, str) or not name:
        bad(path, "[flow] needs a name")
    if grants is None or not set(grants) <= {effect.value for effect in Effect}:
        bad(path, f"grants is a list of effects, from {', '.join(effect.value for effect in Effect)}")
    if params is None or len(set(params)) != len(params) or not all(p.isidentifier() for p in params):
        bad(path, "params is a list of names, each once")
    if not isinstance(steps, list) or not steps:
        bad(path, "it needs at least one [[step]]")
    return Flow(
        name,
        None if app is None else package(path, app),
        frozenset(Effect(grant) for grant in grants),
        params,
        tuple(flow_step(path, index, step) for index, step in enumerate(steps)),
    )


def flow_step(path: Path, index: int, step: object) -> FlowStep:
    if not isinstance(step, dict) or set(step) - STEP_KEYS:
        bad(path, f"step {index} takes only run and expect")
    run, expect = strings(step.get("run")), strings(step.get("expect", []))
    if not run or expect is None:
        bad(path, f"step {index} needs run, a non-empty list of words, and expect is a list of queries")
    return FlowStep(expect, run)


def package(path: Path, app: object) -> Package:
    try:
        return package_name(app if isinstance(app, str) else "")
    except argparse.ArgumentTypeError as error:
        bad(path, f"app: {error}")


def strings(value: object) -> tuple[str, ...] | None:
    if isinstance(value, list) and all(isinstance(word, str) for word in value):
        return tuple(value)
    return None


def bad(path: Path, problem: str) -> NoReturn:
    raise Refusal(ErrorCode.INVALID_ARGS, f"{path} is not a flow: {problem}.")


def plan(flow: Flow, values: Sequence[tuple[str, str]]) -> tuple[Planned, ...]:
    """Every step parsed with `values` filled in, or INVALID_ARGS, before any device is opened. A
    refusal names the step by the words the file wrote."""
    given = dict(values)
    if len(given) != len(values) or set(given) != set(flow.params):
        wanted = ", ".join(flow.params) or "none"
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"The flow {flow.name} takes these parameters, each once: {wanted}. "
            f"--param gave: {', '.join(name for name, _ in values) or 'none'}.",
        )
    return tuple(planned(flow, index, step, given) for index, step in enumerate(flow.steps))


def planned(flow: Flow, index: int, step: FlowStep, given: Mapping[str, str]) -> Planned:
    where = f"Step {index} of the flow {flow.name}"
    run = call(where, index, step.run, given)
    command = run.step.command
    if names_a_ref(command):
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{where} names a ref or a point. A ref belongs to one snapshot, so a flow names each "
            "target by a query such as name=Display.",
        )
    outside = sorted(effect.value for effect in getattr(command, "commit", frozenset()) - flow.grants)
    if outside:
        raise Refusal(
            ErrorCode.INVALID_ARGS,
            f"{where} grants {', '.join(outside)}, which the flow's grants do not list. A step may "
            "commit only what the flow declares.",
        )
    if not step.expect:
        return Planned(run, None)
    wait = ("wait", *(word for query in step.expect for word in ("--for", query)))
    return Planned(run, call(where, index, wait, given))


def call(where: str, index: int, written: tuple[str, ...], given: Mapping[str, str]) -> Call:
    """The words with their parameters filled in, parsed. A parameter fills a value and never
    adds a flag: a value that starts with `-` is refused unless the word stands after `--`, where
    the parser reads every word as text. A `{name}` the flow does not declare is refused, so a
    misspelt name is never typed into a field as it stands."""
    words: list[str] = []
    for word in written:
        unknown = sorted(set(PARAMETER.findall(word)) - set(given))
        if unknown:
            raise Refusal(
                ErrorCode.INVALID_ARGS,
                f"{where} names the parameter {unknown[0]}, which the flow's params do not list.",
            )
        value = filled(word, given)
        if value.startswith("-") and not word.startswith("-") and "--" not in words:
            raise Refusal(
                ErrorCode.INVALID_ARGS,
                f"{where} has a parameter whose value starts with -, so it would read as a flag. "
                'A value that starts with - is taken only after a "--" word in run.',
            )
        words.append(value)
    return Call(parse_step(index, tuple(words), shown=written), written)


def filled(word: str, given: Mapping[str, str]) -> str:
    """`word` with each `{name}` of a given parameter replaced, in one pass, so a value that
    holds braces is never filled again. Other braces stay as written."""
    return PARAMETER.sub(lambda found: given.get(found[1], found[0]), word)


def names_a_ref(command: DriverCommand) -> bool:
    match command:
        case GetCommand() | IsCommand():
            return True
        case SnapshotCommand(scope=scope) | FindCommand(scope=scope):
            return scope.root is not None
        case _:
            return isinstance(target_of(command), RefTarget | PointTarget)
