"""`--settle` on an input: the result's `after` is the screen once it stopped changing, with fresh
refs, and the caller names no condition. It proves nothing about the input, so the delivery stays
`delivered_unverified` unless a `--wait-for` beside it saw its effect."""

import json

from fakes import J7_SERIAL, FakeHub, FakePhone, invoke
from support import FakeClock, node, screen_of

from agent_phone.core.device import Connected

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)


def page(*children):
    return screen_of(
        node(
            "android.widget.FrameLayout", *children, package="com.android.settings", bounds="[0,0][1080,1920]"
        )
    )


def button(name, top):
    return node("android.widget.Button", text=name, clickable=True, bounds=f"[0,{top}][1080,{top + 100}]")


def text(words, top):
    return node("android.widget.TextView", text=words, bounds=f"[0,{top}][1080,{top + 100}]")


BEFORE = page(button("Display", 300))
OPENING = page(text("Display", 0))
AFTER = page(text("Display", 0), button("Brightness", 300))


def snapshot(root):
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[BEFORE]), root)
    assert code == 0
    return wire["data"]["id"]


class Restless(FakePhone):
    """After an input, every read shows another screen than the read before it."""

    def read(self):
        if not self.permits:
            return super().read()
        self.reads += 1
        return page(text("Display", 0), text(f"frame {self.reads}", 300))


class RestlessHub(FakeHub):
    def open(self, serial, first_read=False):
        self.phones.append(Restless(self._infos[serial], *self._screens))
        return self.phones[-1]


def test_settle_returns_the_screen_the_input_ended_on_with_refs_for_the_next_input(tmp_path):
    hub = FakeHub([J7], screens=[BEFORE], after_input=[OPENING, OPENING, AFTER])
    code, wire = invoke(["click", f"@{snapshot(tmp_path)}:e1", "--settle"], hub, tmp_path)
    after = wire["data"]["after"]
    assert code == 0 and wire["ok"] and after["settled"] == "settled"
    assert after["tree"] == [
        'text "Display" [0,0,1080,100]',
        f'@{after["id"]}:e1 button "Brightness" [0,300,1080,400]',
    ]
    code, wire = invoke(["click", f"@{after['id']}:e1"], FakeHub([J7], screens=[AFTER]), tmp_path)
    assert code == 0 and wire["data"]["target"]["name"] == "Brightness", "no OBSERVE_FIRST and no STALE_REF"


def test_a_settled_screen_does_not_verify_the_input(tmp_path):
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    _, wire = invoke(["click", f"@{snapshot(tmp_path)}:e1", "--settle"], hub, tmp_path)
    assert wire["delivery"] == "delivered_unverified" and wire["data"]["verified_by"] is None


def test_settle_beside_a_wait_for_verifies_by_the_effect_and_still_settles(tmp_path):
    hub = FakeHub([J7], screens=[BEFORE], after_input=[OPENING, AFTER])
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--wait-for", "name=Brightness", "--settle"]
    code, wire = invoke(click, hub, tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["verified_by"] == 'present name="Brightness"'
    assert wire["data"]["after"]["settled"] == "settled"


def test_a_screen_that_never_settles_is_not_an_error_and_says_unsettled(tmp_path):
    clock = FakeClock()
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--settle", "--timeout-ms", "2000"]
    code, wire = invoke(click, RestlessHub([J7], screens=[BEFORE]), tmp_path, clock=clock)
    assert code == 0 and wire["ok"] and "error" not in wire
    assert wire["data"]["after"]["settled"] == "unsettled" and wire["delivery"] == "delivered_unverified"
    assert 2.0 <= clock.time < 2.5, "it waited for its timeout and no longer"


def test_an_effect_that_showed_on_a_screen_that_never_settles_still_verifies(tmp_path):
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--wait-for", "name=Display role=text", "--settle"]
    code, wire = invoke([*click, "--timeout-ms", "1000"], RestlessHub([J7], screens=[BEFORE]), tmp_path)
    assert code == 0 and wire["delivery"] == "delivered_verified"
    assert wire["data"]["after"]["settled"] == "unsettled"


def test_an_effect_that_never_shows_is_still_a_timeout_with_settle(tmp_path):
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    click = [
        "click",
        f"@{snapshot(tmp_path)}:e1",
        "--wait-for",
        "name=Never",
        "--settle",
        "--timeout-ms",
        "300",
    ]
    code, wire = invoke(click, hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "TIMEOUT" and wire["delivery"] == "delivered_unverified"


def test_an_input_with_no_target_settles_too(tmp_path):
    snapshot(tmp_path)
    hub = FakeHub([J7], screens=[BEFORE], after_input=[OPENING, AFTER])
    code, wire = invoke(["press", "back", "--settle"], hub, tmp_path)
    assert code == 0 and wire["data"]["after"]["settled"] == "settled"
    assert wire["data"]["after"]["tree"][-1].endswith('button "Brightness" [0,300,1080,400]')


def test_a_batch_step_takes_settle_and_the_next_step_stands_on_its_screen(tmp_path):
    steps = [["snapshot"], ["click", "name=Display", "--settle"], ["click", "name=Brightness"]]
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(steps))
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    code, wire = invoke(["batch", str(path)], hub, tmp_path)
    assert code == 0 and wire["data"]["steps"][2]["data"]["target"]["name"] == "Brightness"


def test_settle_with_after_diff_prints_what_changed(tmp_path):
    grown = page(button("Display", 300), text("Brightness", 500))
    hub = FakeHub([J7], screens=[BEFORE], after_input=[grown])
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--settle", "--after", "diff"]
    _, wire = invoke(click, hub, tmp_path)
    assert wire["data"]["after"]["added"] == ['text "Brightness" [0,500,1080,600]']


class Banner(FakePhone):
    """After an input, the second and third read show a line that then goes, on a screen that
    never stops changing."""

    def read(self):
        if not self.permits:
            return super().read()
        self.reads += 1
        seen = self.reads - self.before
        banner = [text("Sent", 600)] if seen in (2, 3) else []
        return page(text("Display", 0), text(f"frame {seen}", 300), *banner)

    def inject(self, permit):
        self.before = self.reads
        return super().inject(permit)


class BannerHub(FakeHub):
    def open(self, serial, first_read=False):
        self.phones.append(Banner(self._infos[serial], *self._screens))
        return self.phones[-1]


def test_settle_does_not_turn_an_effect_that_showed_and_went_into_a_timeout(tmp_path):
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--wait-for", "name=Sent", "--timeout-ms", "1000"]
    plain = invoke(click, BannerHub([J7], screens=[BEFORE]), tmp_path)
    code, wire = invoke(["snapshot"], FakeHub([J7], screens=[BEFORE]), tmp_path)
    settled = [*click[:1], f"@{wire['data']['id']}:e1", *click[2:], "--settle"]
    both = (plain, invoke(settled, BannerHub([J7], screens=[BEFORE]), tmp_path))
    assert [(code, wire["delivery"]) for code, wire in both] == [(0, "delivered_verified")] * 2
    assert both[1][1]["data"]["after"]["settled"] == "unsettled"


def test_a_screen_that_stood_still_says_settled_also_when_the_effect_never_showed(tmp_path):
    hub = FakeHub([J7], screens=[BEFORE], after_input=[AFTER])
    click = ["click", f"@{snapshot(tmp_path)}:e1", "--wait-for", "name=Never", "--settle"]
    code, wire = invoke(click, hub, tmp_path)
    assert code == 1 and wire["error"]["code"] == "TIMEOUT"
    assert wire["data"]["after"]["settled"] == "settled", "the screen did not change, so no second look"
