"""act(): the one pipeline every input goes through, and the only call site of `Phone.inject`.

    resolve -> actionable and stable -> plan -> judge -> spend -> inject -> verify

Everything before `spend` raises `Refusal` and leaves the device untouched. Everything after
`inject` is caught and reported as `Acted` with the disposition the delivery earned, because
from that point on "nothing happened" can no longer be claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from agent_phone.core.act.hit import context_labels, plan_point, require_active, swipe_across
from agent_phone.core.act.intent import ActionReport, Click, Fill, Request, Scroll, TargetReport
from agent_phone.core.context import Context
from agent_phone.core.labels import display_name, surface_of, typed_text
from agent_phone.core.outcome import Acted, ErrorCode, Outcome, Refusal, Refused, SentState
from agent_phone.core.phone import (
    Ack,
    InputAction,
    LongPress,
    NodeAddress,
    NotSent,
    Sent,
    SetText,
    Tap,
)
from agent_phone.core.policy.engine import Site, Verdict, classify, require
from agent_phone.core.refs.fingerprint import path_of
from agent_phone.core.refs.resolve import QueryTarget, RefTarget, Resolved, Target, locate, observed_snapshot
from agent_phone.core.role import Role, role_of, takes_touch
from agent_phone.core.screen import Flag, Node, Screen
from agent_phone.core.snapshot.capture import capture
from agent_phone.core.snapshot.snapshot import SettleState, Snapshot
from agent_phone.core.wait.observe import observe
from agent_phone.core.wait.predicate import describe, holds, is_effect
from agent_phone.core.wait.until import until

LONG_PRESS_MS = 800
"""Above Android's 500 ms long-press timeout, with room for a loaded phone."""
READ_BACK_S = 1.0


class NotYet(Refusal):
    """A refusal that may clear by itself, such as a disabled or moving target. act() reads
    again until the request's deadline and reports the last one."""


@dataclass(frozen=True, slots=True)
class Planned:
    """The input act() will judge, where it lands, and the read it was planned on."""

    action: InputAction
    site: Site | None
    target: TargetReport | None
    before: Screen | None
    resolved: Resolved | None
    held_before: tuple[bool, ...] = ()


def act(ctx: Context, request: Request) -> Outcome:
    try:
        planned = _settle_target(ctx, request)
        if planned.before is not None:
            held = tuple(holds(p, None, planned.before) for p in request.wait_for if is_effect(p))
            planned = replace(planned, held_before=held)
        verdict = classify(ctx.policy, planned.action, planned.site, ctx.info.locale)
        require(verdict, request.grant)
    except Refusal as refusal:
        return Refused.of(refusal)

    permit = ctx.ledger.spend(planned.action, verdict, request.grant)
    delivery = ctx.phone.inject(permit)
    if isinstance(delivery, NotSent):
        ctx.ledger.refund(permit)
        return Refused(delivery.code, delivery.detail)
    return _after_send(ctx, request, delivery, planned, verdict)


def target_of(request: Request) -> Target | None:
    match request.intent:
        case Click(target=target) | Fill(target=target) | Scroll(target=target):
            return target
        case _:
            return None


def _settle_target(ctx: Context, request: Request) -> Planned:
    """Check the observation first, then auto-wait for the target, bounded by `request.timeout_ms`.

    Transient refusals (`NotYet`: hidden or disabled, UNSTABLE, OCCLUDED, NOT_FOUND for a
    query) are read again until the deadline. Terminal ones (WRONG_DEVICE, STALE_REF,
    OBSERVE_FIRST, AMBIGUOUS_TARGET, an element that cannot take this input) fail at once.
    """
    target = target_of(request)
    observed = observed_snapshot(target, ctx.store, ctx.info.identity, ctx.ledger.epoch())
    intent = request.intent
    if not isinstance(intent, Click | Fill | Scroll):
        before = ctx.phone.read() if any(is_effect(p) for p in request.wait_for) else None
        return Planned(intent, Site(observed.package, observed.window_kind, None, ()), None, before, None)
    last: list[NotYet] = []
    previous: list[Node] = []

    def attempt() -> Planned | None:
        screen = ctx.phone.read()
        try:
            return _plan(screen, intent, _find(target, observed, screen), observed, previous)
        except NotYet as refusal:
            last[:] = [refusal]
            return None

    planned = until(ctx.clock, attempt, request.timeout_ms / 1000)
    if planned is None:
        raise last[0]
    return planned


def _find(target: Target | None, observed: Snapshot, screen: Screen) -> Resolved:
    if target is None:
        return Resolved(only_scrollable(screen), observed, None)
    try:
        return locate(target, observed, screen)
    except Refusal as refusal:
        if isinstance(target, QueryTarget) and refusal.code is ErrorCode.NOT_FOUND:
            raise NotYet(refusal.code, refusal.message, refusal.details) from refusal
        raise


def only_scrollable(screen: Screen) -> Node:
    active = screen.active_window()
    found = (
        []
        if active is None
        else [n for n in screen.subtree(active.root) if n.has(Flag.SCROLLABLE) and n.has(Flag.VISIBLE)]
    )
    if not found:
        raise NotYet(ErrorCode.NOT_FOUND, "Nothing on screen scrolls. Take a new snapshot and look.")
    if len(found) > 1:
        raise Refusal(
            ErrorCode.AMBIGUOUS_TARGET,
            f"{len(found)} elements on screen scroll. Pass the ref of the one to scroll.",
            {"matches": len(found)},
        )
    return found[0].id


def _plan(
    screen: Screen,
    intent: Click | Fill | Scroll,
    resolved: Resolved,
    observed: Snapshot,
    previous: list[Node],
) -> Planned:
    node = screen.node(resolved.node)
    seen_before = previous[-1].attrs.bounds if previous else None
    previous[:] = [node]
    ready(intent, node)
    fingerprint = resolved.fingerprint
    settled_here = (
        observed.settled is SettleState.SETTLED
        and fingerprint is not None
        and fingerprint.bounds == node.attrs.bounds
    )
    if node.attrs.bounds != seen_before and not (seen_before is None and settled_here):
        raise NotYet(ErrorCode.UNSTABLE, "The element was not at the same place on two reads in a row.")
    window = screen.window_of(node.id)
    role = role_of(node.attrs)
    ref = str(intent.target.token) if isinstance(intent.target, RefTarget) else None
    point = None
    site = None
    try:
        match intent:
            case Click(long=long):
                point = plan_point(screen, node)
                address = address_of(screen, node)
                action: InputAction = (
                    LongPress(point, address, LONG_PRESS_MS) if long else Tap(point, address)
                )
                site = Site(
                    window.package, window.kind, surface_of(screen, node), context_labels(screen, node)
                )
            case Fill(text=text):
                require_active(window)
                action = SetText(address_of(screen, node), text, secret=node.has(Flag.PASSWORD))
            case Scroll(direction=direction):
                action = swipe_across(screen, node, direction)
    except NotYet:
        raise
    except Refusal as refusal:
        raise NotYet(refusal.code, refusal.message, refusal.details) from refusal
    report = TargetReport(ref, role, display_name(screen, node, role), point)
    return Planned(action, site, report, screen, resolved)


def ready(intent: Click | Fill | Scroll, node: Node) -> None:
    """A hidden or disabled element may become ready; one of the wrong kind never does."""
    if not node.has(Flag.VISIBLE):
        raise NotYet(ErrorCode.NOT_ACTIONABLE, "The element is not visible.", {"reason": "hidden"})
    if not node.has(Flag.ENABLED):
        raise NotYet(ErrorCode.NOT_ACTIONABLE, "The element is disabled.", {"reason": "disabled"})
    match intent:
        case Click() if not takes_touch(node.attrs):
            raise Refusal(ErrorCode.NOT_ACTIONABLE, "The element takes no tap.", {"reason": "no_tap"})
        case Fill() if role_of(node.attrs) is not Role.TEXT_FIELD:
            raise Refusal(
                ErrorCode.NOT_ACTIONABLE, "The element is not a text field.", {"reason": "not_a_field"}
            )
        case Scroll() if not node.has(Flag.SCROLLABLE):
            raise Refusal(
                ErrorCode.NOT_ACTIONABLE, "The element does not scroll.", {"reason": "not_scrollable"}
            )


def address_of(screen: Screen, node: Node) -> NodeAddress:
    a = node.attrs
    return NodeAddress(
        screen.window_of(node.id).package,
        a.class_name,
        a.resource_id,
        a.text,
        a.content_desc,
        a.bounds,
        path_of(screen, node),
        a.native_id,
    )


def _after_send(ctx: Context, request: Request, delivery: Sent, planned: Planned, verdict: Verdict) -> Acted:
    """Never raises. Any exception here becomes `Acted(error=INTERNAL)` with the sent state.

    Verification: an effect predicate in `wait_for` that was false on the read the input was
    planned on and holds after makes the action VERIFIED. One that already held before proves
    nothing, and the action stays UNVERIFIED with that said in `verified_by`. Fill reads the
    field back on its own (not for secrets). A contradicted read-back is ACTION_FAILED, still
    delivered. The observation the wait ends on is recorded as a snapshot at the new epoch and
    returned in `after`, so the caller has fresh refs without another call.
    """
    sent = SentState.UNCERTAIN if delivery.ack is Ack.UNACKNOWLEDGED else SentState.UNVERIFIED
    report = ActionReport(planned.action, planned.target, verdict, None)
    try:
        if isinstance(request.intent, Fill) and not request.wait_for:
            return _read_back(ctx, request.intent, planned, sent, report)
        if not request.wait_for:
            return Acted(sent, report, None)
        seen = observe(ctx, request.wait_for, ctx.clock.now() + request.timeout_ms / 1000)
        after = record(ctx, seen.screen, seen.settled)
        if not seen.held:
            wanted = " and ".join(describe(p) for p in request.wait_for)
            return Acted(
                sent,
                report,
                after,
                ErrorCode.TIMEOUT,
                f"{wanted} did not hold within {request.timeout_ms} ms.",
            )
        effects = [p for p in request.wait_for if is_effect(p)]
        proofs = [p for p, held in zip(effects, planned.held_before, strict=False) if not held]
        if proofs:
            state = sent if sent is SentState.UNCERTAIN else SentState.VERIFIED
            report = _by(report, " and ".join(describe(p) for p in proofs))
        elif effects:
            state = sent
            report = _by(
                report, f"{' and '.join(describe(p) for p in effects)}, which already held before the input"
            )
        else:
            state = sent
        if isinstance(request.intent, Fill):
            return _read_back(ctx, request.intent, planned, state, report, seen.screen, after)
        return Acted(state, report, after)
    except Refusal as refusal:
        return Acted(sent, report, None, refusal.code, refusal.message)
    except Exception as error:
        return Acted(sent, report, None, ErrorCode.INTERNAL, f"{type(error).__name__}: {error}")


def _by(report: ActionReport, verified_by: str | None) -> ActionReport:
    return ActionReport(report.action, report.target, report.verdict, verified_by)


def record(ctx: Context, screen: Screen, settled: SettleState) -> Snapshot | None:
    """The `after` snapshot, or None when the read has no window to describe."""
    try:
        return capture(ctx, screen, settled=settled)
    except Refusal:
        return None


def _read_back(
    ctx: Context,
    intent: Fill,
    planned: Planned,
    state: SentState,
    report: ActionReport,
    screen: Screen | None = None,
    after: Snapshot | None = None,
) -> Acted:
    """Read the field back, on `screen` or by reading until it holds the text or READ_BACK_S
    passes. A secret field is never read, so it stays as it was. A field that left the screen
    proves nothing either way."""
    resolved = planned.resolved
    if resolved is None or (isinstance(planned.action, SetText) and planned.action.secret):
        return Acted(state, report, after)

    def value_on(current: Screen) -> str | None:
        try:
            return typed_text(current.node(locate(intent.target, resolved.observed, current).node))
        except Refusal:
            return None

    reads = [] if screen is None else [screen]

    def holds_text() -> bool | None:
        reads.append(ctx.phone.read())
        return value_on(reads[-1]) == intent.text or None

    if screen is None:
        until(ctx.clock, holds_text, READ_BACK_S)
    value = value_on(reads[-1])
    after = after or record(ctx, reads[-1], SettleState.UNCHECKED)
    if value == intent.text:
        verified = state if state is SentState.UNCERTAIN else SentState.VERIFIED
        return Acted(verified, _by(report, report.verified_by or "the field holds the text"), after)
    if value is None:
        return Acted(state, report, after)
    unverified = state if state is SentState.UNCERTAIN else SentState.UNVERIFIED
    return Acted(
        unverified, report, after, ErrorCode.ACTION_FAILED, "The field does not hold the text after set-text."
    )
