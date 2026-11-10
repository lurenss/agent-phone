"""Pop-ups the agent did not ask for, recognised from policy data and named in every observation.

The dialogs are built here from the words Android's own dialogs show (AOSP's string resources), not
captured from a phone, so no test names a real app."""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import node, screen_of

from agent_phone.core.device import Connected

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def dialog(title, *buttons, package="android"):
    """A dialog window: a title, then one button per label, left to right."""
    return node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text=title, package=package, bounds="[100,700][980,800]"),
        *(
            node(
                "android.widget.Button",
                text=label,
                package=package,
                clickable=True,
                bounds=f"[{100 + 300 * i},900][{380 + 300 * i},1000]",
            )
            for i, label in enumerate(buttons)
        ),
        package=package,
        bounds="[60,650][1020,1050]",
    )


ANR = screen_of(dialog("Example isn't responding", "Close app", "Wait"))


def ref_of(wire, name):
    """The ref of the one tree line named `name`."""
    [line] = [line for line in wire["data"]["tree"] if f'"{name}"' in line]
    return line.split()[0]


@pytest.mark.xfail(strict=True, reason="P2.5: policy files have no [[interruption]] table yet")
def test_an_anr_dialog_yields_an_interruption_with_its_dismiss_ref(tmp_path):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[ANR]), tmp_path)
    assert code == 0
    assert wire["data"]["interruptions"] == [
        {
            "rule": "default.not-responding.en",
            "kind": "not_responding",
            "needs_human": False,
            "dismiss": ref_of(wire, "Wait"),
        }
    ]
