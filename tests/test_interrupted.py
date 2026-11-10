"""An input whose target a recognised pop-up covers: it ends early, sends nothing and dismisses
nothing. Every case is checked against the inputs the fake phone received."""

import pytest
from fakes import FakeHub, invoke
from support import FakeClock, node, screen_of
from test_interruptions import ANR, J7, SHOP, dialog

from agent_phone.core.phone import Tap


def app(*buttons, package=SHOP):
    """A full-screen app window with one button per label, top to bottom."""
    return node(
        "android.widget.FrameLayout",
        *(
            node(
                "android.widget.Button",
                text=label,
                package=package,
                clickable=True,
                bounds=f"[100,{200 + 200 * i}][980,{300 + 200 * i}]",
            )
            for i, label in enumerate(buttons)
        ),
        package=package,
        bounds="[0,0][1080,1920]",
    )


SHARE = screen_of(app("Share"))
NOT_RESPONDING = dialog("Example isn't responding", "Close app", "Wait")


def sent(hub):
    return [permit.action for phone in hub.phones for permit in phone.permits]


@pytest.mark.xfail(strict=True, reason="P2.6: a click under a pop-up still waits its whole timeout")
def test_a_click_under_a_known_dialog_is_interrupted_and_nothing_is_sent(tmp_path):
    invoke(["snapshot"], FakeHub([J7], screens=[SHARE]), tmp_path)
    hub, clock = FakeHub([J7], screens=[ANR]), FakeClock()
    code, wire = invoke(["click", "name=Share"], hub, tmp_path, clock=clock)
    assert code == 1 and wire["error"]["code"] == "INTERRUPTED"
    assert (wire["delivery"], wire["retry"]) == ("not_delivered", "safe")
    assert clock.time == 0 and hub.phones[0].reads == 1, "it ends on the first read"
    details = wire["error"]["details"]
    assert details["interruptions"] == [
        {
            "rule": "default.not-responding.en",
            "kind": "not_responding",
            "needs_human": False,
            "dismiss": f"@{details['snapshot']}:e2",
        }
    ]
    assert sent(hub) == [], "nothing is sent, and the pop-up is not dismissed"
    code, wire = invoke(["click", details["interruptions"][0]["dismiss"]], hub, tmp_path)
    assert code == 0, "the epoch was left, so the way out is a live ref for the caller to click"
    [tap] = sent(hub)
    assert wire["data"]["target"]["name"] == "Wait" and isinstance(tap, Tap)
