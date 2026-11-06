"""examples/instagram/publish_dry_run.py on a scripted phone. act() refuses a wait that already
holds before its input (#4), so the run must not tap for a screen that already shows."""

import importlib.util

import pytest
from fakes import J7_SERIAL, FakeHub
from support import ROOT, FakeClock, node, screen_of

from agent_phone import open_phone
from agent_phone.cli.settings import Settings
from agent_phone.core.device import Connected
from agent_phone.core.phone import Launch, Tap

EXAMPLE = ROOT / "examples" / "instagram" / "publish_dry_run.py"
J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
IG = "com.instagram.android"


def instagram(*children):
    return screen_of(node("android.widget.FrameLayout", *children, package=IG, bounds="[0,0][1080,1920]"))


def button(bounds, **attrs):
    return node("android.widget.Button", clickable=True, bounds=bounds, **attrs)


TABS = button("[864,1800][1080,1920]", resource_id=f"{IG}:id/profile_tab", content_desc="Profile")
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
    button("[0,100][540,200]", text="account-1"),
    button("[900,100][1080,200]", resource_id=f"{IG}:id/profile_header_create_button", content_desc="New"),
    TABS,
)
MENU = instagram(button("[0,1500][1080,1600]", text="Create new reel"))
PICKER = instagram(
    button("[0,100][300,200]", content_desc="Back to Home"),
    button("[0,400][360,760]", resource_id=f"{IG}:id/gallery_grid_item_thumbnail", content_desc="0:08"),
)


@pytest.fixture
def example():
    spec = importlib.util.spec_from_file_location("publish_dry_run", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clear_only(example, monkeypatch, tmp_path, first, after_each):
    """`--clear-only` for one account that is already active, and the inputs it sent."""
    hub = FakeHub([J7], screens=[first], after_each=after_each)
    settings = Settings(state_root=tmp_path, lock_wait_s=0.0)
    monkeypatch.setattr(
        example, "open_phone", lambda serial: open_phone(hub=hub, settings=settings, clock=FakeClock())
    )
    monkeypatch.setattr(example, "clip_label", lambda path: "0:08")
    code = example.main([J7_SERIAL, "clip.mp4", "a caption", "--accounts", "account-1", "--clear-only"])
    return code, [type(permit.action) for permit in hub.phones[0].permits]


def test_a_run_on_an_open_profile_sends_no_launch_and_no_back(example, monkeypatch, tmp_path):
    code, sent = clear_only(example, monkeypatch, tmp_path, PROFILE, [MENU, PICKER, PROFILE])
    assert code == 0 and sent == [Tap, Tap, Tap], "create, create new reel, back to home"


def test_a_run_from_the_launcher_launches_instagram_and_taps_the_profile_tab(example, monkeypatch, tmp_path):
    code, sent = clear_only(example, monkeypatch, tmp_path, LAUNCHER, [FEED, PROFILE, MENU, PICKER, PROFILE])
    assert code == 0 and sent == [Launch, Tap, Tap, Tap, Tap]
