"""The uiautomator2 dump writes `..` for each character above U+FFFF (A9-1), so a field that holds
an emoji never reads back as the text set-text sent. The parser marks such text lossy, a snapshot
line that shows it says `lossy`, and set-text compares a lossy read with the text written the way
the dump writes it."""

import pytest
from fakes import J7_SERIAL, FakeHub, invoke
from support import compact, node, screen_of

from agent_phone.core.device import Connected
from agent_phone.core.snapshot.budget import render
from agent_phone.core.snapshot.snapshot import SnapshotId

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def search(text: str = ""):
    field = node(
        "android.widget.EditText", text=text, hint="Search", clickable=True, bounds="[0,100][1080,200]"
    )
    return screen_of(node("android.widget.FrameLayout", field, package="test.app", bounds="[0,0][1080,1920]"))


def set_text(root, text: str, shows: str) -> dict:
    taken = invoke(["snapshot"], FakeHub([J7], screens=[search()]), root)[1]["data"]["id"]
    hub = FakeHub([J7], screens=[search()], after_input=[search(shows)])
    return invoke(["set-text", f"@{taken}:e1", text], hub, root)[1]


def test_set_text_of_an_emoji_is_verified_on_the_dump_that_writes_it_as_two_dots(tmp_path):
    wire = set_text(tmp_path, "hi 😴", shows="hi ..")
    assert wire["ok"] and wire["delivery"] == "delivered_verified"
    assert "lossy" in wire["data"]["verified_by"]


def test_an_exact_read_back_is_compared_exactly(tmp_path):
    wire = set_text(tmp_path, "hi 😴", shows="hi 😴")
    assert wire["ok"] and wire["delivery"] == "delivered_verified"
    assert "lossy" not in wire["data"]["verified_by"]


@pytest.mark.parametrize("shows", ["hi ....", "hi", "hi ."])
def test_a_read_back_that_differs_from_the_text_still_fails(tmp_path, shows):
    wire = set_text(tmp_path, "hi 😴", shows)
    assert wire["error"]["code"] == "ACTION_FAILED" and wire["delivery"] == "delivered_unverified"


def test_a_line_that_shows_text_the_dump_damaged_is_marked_lossy():
    screen = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.TextView", text="good night ..", bounds="[0,100][1080,200]"),
            node(
                "android.widget.Button",
                node("android.widget.TextView", text="Send ..", bounds="[0,300][1080,400]"),
                clickable=True,
                bounds="[0,300][1080,400]",
            ),
            node(
                "android.widget.EditText",
                text="hi ..",
                hint="Message",
                clickable=True,
                bounds="[0,500][1080,600]",
            ),
            node("android.widget.TextView", text="good night.", bounds="[0,700][1080,800]"),
            node(
                "android.widget.ImageButton",
                content_desc="Like ..",
                clickable=True,
                bounds="[0,900][200,1000]",
            ),
            node("android.widget.EditText", hint="Say hi ..", clickable=True, bounds="[0,1100][1080,1200]"),
            package="test.app",
            bounds="[0,0][1080,1920]",
        )
    )
    assert render(compact(screen), SnapshotId("k3x9q")) == (
        'text "good night .." lossy [0,100,1080,200]',
        '@k3x9q:e1 button "Send .." lossy [0,300,1080,400]',
        '@k3x9q:e2 field "Message" value="hi .." lossy [0,500,1080,600]',
        'text "good night." [0,700,1080,800]',
        '@k3x9q:e3 button "Like .." lossy [0,900,200,1000]',
        '@k3x9q:e4 field "Say hi .." lossy [0,1100,1080,1200]',
    )


def test_a_secret_field_is_never_marked_lossy_by_its_hidden_text():
    secret = node(
        "android.widget.EditText", text="ab..cd", password=True, clickable=True, bounds="[0,100][1080,200]"
    )
    screen = screen_of(
        node("android.widget.FrameLayout", secret, package="test.app", bounds="[0,0][1080,1920]")
    )
    assert render(compact(screen), SnapshotId("k3x9q")) == ("@k3x9q:e1 field secret [0,100,1080,200]",)
