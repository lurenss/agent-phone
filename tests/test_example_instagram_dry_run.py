import importlib.util
import re

import pytest
from fakes import J7_SERIAL, FakeHub
from support import ROOT, FakeClock, node, screen_of

from agent_phone import open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.phone import Tap

EXAMPLE = ROOT / "examples" / "instagram" / "publish_dry_run.py"
J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
IG = "com.instagram.android"
ACTIVE = "account-1"
AT = {
    "tab": "[864,1800][1080,1920]",
    "create": "[900,100][1080,200]",
    "create new reel": "[0,1500][1080,1600]",
    "back to home": "[0,250][300,350]",
    "keep editing": "[120,900][500,980]",
    "cancel": "[700,250][1000,350]",
}


def instagram(*children, bounds="[0,0][1080,1920]"):
    return screen_of(node("android.widget.FrameLayout", *children, package=IG, bounds=bounds))


def button(name, **attrs):
    return node("android.widget.Button", clickable=True, bounds=AT[name], **attrs)


TABS = button("tab", resource_id=f"{IG}:id/profile_tab", content_desc="Profile")
LAUNCHER = screen_of(
    node(
        "android.widget.FrameLayout",
        node("android.widget.TextView", text="Home screen", bounds="[0,100][1080,200]"),
        package="com.sec.android.app.launcher",
        bounds="[0,0][1080,1920]",
    )
)
FEED = instagram(node("android.widget.TextView", text="Suggested for you", bounds="[0,300][1080,400]"), TABS)
PROFILE = instagram(
    node("android.widget.Button", clickable=True, bounds="[0,100][540,200]", text=ACTIVE),
    button("create", resource_id=f"{IG}:id/profile_header_create_button", content_desc="New"),
    TABS,
)
MENU = instagram(button("create new reel", text="Create new reel"))
KEEP_EDITING = instagram(
    node("android.widget.TextView", text="Keep editing your draft?", bounds="[120,800][960,880]"),
    button("keep editing", text="Keep editing"),
    node("android.widget.Button", clickable=True, bounds="[520,900][960,980]", text="Start new video"),
    bounds="[90,700][990,1100]",
)
EDITOR = instagram(button("cancel", text="Cancel"))
PICKER = instagram(
    button("back to home", content_desc="Back to Home"),
    node(
        "android.widget.Button",
        clickable=True,
        bounds="[0,400][360,760]",
        resource_id=f"{IG}:id/gallery_grid_item_thumbnail",
        content_desc="0:08",
    ),
)


@pytest.fixture
def example():
    spec = importlib.util.spec_from_file_location("publish_dry_run", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session(hub, tmp_path):
    return open_phone(hub=hub, settings=Settings(state_root=tmp_path, lock_wait_s=0.0), clock=FakeClock())


def landed(action):
    if not isinstance(action, Tap):
        return type(action).__name__
    for name, bounds in AT.items():
        left, top, right, bottom = map(int, re.findall(r"\d+", bounds))
        if left <= action.point.x < right and top <= action.point.y < bottom:
            return name
    return f"a tap at {action.point}"


def clear_only(example, monkeypatch, tmp_path, first, after_each):
    hub = FakeHub([J7], screens=[first], after_each=after_each)
    monkeypatch.setattr(example, "open_phone", lambda serial: session(hub, tmp_path))
    monkeypatch.setattr(example, "clip_label", lambda path: "0:08")
    code = example.main([J7_SERIAL, "clip.mp4", "a caption", "--accounts", ACTIVE, "--clear-only"])
    return code, [landed(permit.action) for permit in hub.phones[0].permits]


def test_a_run_on_an_open_profile_sends_no_launch_and_no_back(example, monkeypatch, tmp_path):
    code, sent = clear_only(example, monkeypatch, tmp_path, PROFILE, [MENU, PICKER, PROFILE])
    assert code == 0 and sent == ["create", "create new reel", "back to home"]


def test_a_run_from_the_launcher_launches_instagram_and_taps_the_profile_tab(example, monkeypatch, tmp_path):
    code, sent = clear_only(example, monkeypatch, tmp_path, LAUNCHER, [FEED, PROFILE, MENU, PICKER, PROFILE])
    assert code == 0 and sent == ["Launch", "tab", "create", "create new reel", "back to home"]


def test_a_pending_session_is_closed_through_its_keep_editing_dialog(example, monkeypatch, tmp_path):
    after = [MENU, KEEP_EDITING, EDITOR, PICKER, PROFILE]
    code, sent = clear_only(example, monkeypatch, tmp_path, PROFILE, after)
    assert code == 0 and sent == ["create", "create new reel", "keep editing", "cancel", "back to home"]


def test_a_profile_that_shows_by_the_read_the_tap_is_planned_on_is_not_backed_out_of(example, tmp_path):
    hub = FakeHub([J7], screens=[FEED, FEED, PROFILE])
    with session(hub, tmp_path) as phone:
        phone.snapshot()
        example.to_profile(phone)
    assert [landed(permit.action) for permit in hub.phones[0].permits] == []
