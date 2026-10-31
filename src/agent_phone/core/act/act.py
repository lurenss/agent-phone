"""act(): the one pipeline every input goes through, and the only call site of `Phone.inject`.

    resolve -> actionable and stable -> plan -> judge -> spend -> inject -> verify

Everything before `spend` raises `Refusal` and leaves the device untouched. Everything after
`inject` is caught and reported as `Acted` with the disposition the delivery earned, because
from that point on "nothing happened" can no longer be claimed.
"""

from __future__ import annotations

from agent_phone.core.act.intent import ActionReport, Click, Fill, Intent, Request, Scroll
from agent_phone.core.context import Context
from agent_phone.core.outcome import Acted, Outcome, Refusal, Refused, SentState
from agent_phone.core.phone import InputAction, NotSent, Sent
from agent_phone.core.policy.engine import Site, Verdict, classify, require
from agent_phone.core.refs.resolve import Resolved
from agent_phone.core.screen import Screen


def act(ctx: Context, request: Request) -> Outcome:
    try:
        screen, resolved = _settle_target(ctx, request)
        action, site = _plan(ctx, request.intent, screen, resolved)
        verdict = classify(ctx.policy, action, site, ctx.info.locale)
        require(verdict, request.grant)
        before = screen
    except Refusal as refusal:
        return Refused.of(refusal)

    permit = ctx.ledger.spend(action, verdict, request.grant)
    delivery = ctx.phone.inject(permit)
    if isinstance(delivery, NotSent):
        ctx.ledger.refund(permit)
        return Refused(delivery.code, delivery.detail)
    return _after_send(ctx, request, delivery, before, action, verdict, resolved)


def _settle_target(ctx: Context, request: Request) -> tuple[Screen | None, Resolved | None]:
    """Auto-wait for the target, bounded by `request.timeout_ms`.

    Transient refusals (NOT_ACTIONABLE because disabled, UNSTABLE, OCCLUDED, and NOT_FOUND
    for queries) are polled until the deadline. Terminal ones (INVALID_ARGS, WRONG_DEVICE,
    STALE_REF, OBSERVE_FIRST, AMBIGUOUS_TARGET for a ref) fail on the first read.
    """
    # TODO:
    #   observed = observed_snapshot(target or None, ctx.store, ctx.info.identity, ctx.ledger.epoch())
    #   targetless intent: one read only when `wait_for` needs a pre-action screen to verify
    #     against, else the observed snapshot's epoch check is all it needs
    #   loop with ctx.clock until deadline:
    #     screen = ctx.phone.read(); r = locate(target, observed, screen)
    #     check VISIBLE, ENABLED, and EDITABLE for Fill / SCROLLABLE for Scroll
    #     stable when the previous read gave the same bounds, or on the first read when the
    #       observed snapshot was SETTLED and the live bounds equal fp.bounds
    #   the polling sleep lives in core/wait/observe.py, not here
    raise NotImplementedError


def _plan(
    ctx: Context, intent: Intent, screen: Screen | None, resolved: Resolved | None
) -> tuple[InputAction, Site | None]:
    # TODO:
    #   Click: Capability.SEMANTIC_CLICK -> Activate(address), site = the node itself
    #          else point = plan_point(...); Tap/LongPress(point, address), site = receiver at point
    #   Fill:  SetText(address, text, secret=PASSWORD), site None (typing commits nothing)
    #   Scroll: Swipe across 60% of the collection's visible bounds against `direction`, site None
    #   anything else: (intent, None)
    #   site.context = hit.context_labels(screen, receiver)
    raise NotImplementedError


def _after_send(
    ctx: Context,
    request: Request,
    delivery: Sent,
    before: Screen | None,
    action: InputAction,
    verdict: Verdict,
    resolved: Resolved | None,
) -> Acted:
    """Never raises. Any exception here becomes `Acted(error=INTERNAL)` with the sent state.

    Verification: an effect predicate in `wait_for` that was false on `before` and holds
    after makes the action VERIFIED. One that already held before proves nothing, and the
    action stays UNVERIFIED with that said in `verified_by`. Fill reads the field back on its
    own (not for secrets). A contradicted read-back is ACTION_FAILED, still delivered.
    The observation the wait ends on is recorded as a snapshot at the new epoch and returned in
    `after`, so the caller has fresh refs without another call.
    """
    # TODO: sent = UNCERTAIN if delivery.ack is UNACKNOWLEDGED else UNVERIFIED
    #   if request.wait_for or isinstance(request.intent, Fill):
    #       obs = observe(ctx, request.wait_for, deadline)  -> record snapshot -> after
    #   build ActionReport, Acted(sent, report, after, error)
    _ = (SentState, ActionReport, Click, Fill, Scroll)
    raise NotImplementedError
