"""sweep.py opens each app, judges the taps of its screen with the gate, and presses home. The screens
here are small dumps with buttons whose words the default policy reads (Share commits a publish, Send
a send, Delete a delete), so every expected count comes from what that policy says of those words."""

import json

import pytest
from port_support import FakePhone, Screen, script
from support import dump, node

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.cli.policy import load_policy, load_profile

sweep = script("sweep")
gate_check = sweep.gate_check
NATURAL = sweep.Size(1080, 1920)


def button(label, at, package):
    return node(
        "android.widget.Button",
        text=label,
        clickable=True,
        package=package,
        bounds=f"[0,{at * 100}][500,{at * 100 + 90}]",
    )


def app_xml(package, *labels):
    app = node(
        "android.widget.FrameLayout",
        *(button(label, at, package) for at, label in enumerate(labels)),
        package=package,
        bounds="[0,0][1080,1920]",
    )
    status = node(
        "android.widget.FrameLayout",
        button("Notifications", 0, "com.android.systemui"),
        package="com.android.systemui",
        bounds="[0,0][1080,63]",
    )
    return dump(app, status)


def judged(*labels, locale="en-US", policy=None):
    screen = parse_hierarchy(app_xml("a.b", *labels), NATURAL, ime_package=None)
    return [
        j for j in gate_check.judge(screen, policy or load_policy([], None), locale) if j.package == "a.b"
    ]


def test_the_counts_follow_what_the_default_policy_says_of_each_label():
    found = sweep.tally(judged("Share", "Send", "Delete", "Settings", "Like"))
    assert (found.targets, found.clear) == (5, 2)
    assert found.commits == {"publish": 1, "send": 1, "delete": 1}
    assert found.samples == {"publish": ["Share"], "send": ["Send"], "delete": ["Delete"]}
    assert found.denied == 0 and found.refused == {}


def test_a_label_that_commits_two_effects_is_in_both_counts_and_one_target():
    found = sweep.tally(judged("Share and send"))
    assert found.targets == 1 and found.commits == {"publish": 1, "send": 1}


def test_samples_are_the_first_eight_distinct_labels_of_each_effect():
    labels = [f"Share {n}" for n in range(12)] + ["Share 0"]
    found = sweep.tally(judged(*labels))
    assert found.commits == {"publish": 13}
    assert found.samples["publish"] == [f"Share {n}" for n in range(8)]


def test_a_denied_target_is_counted_and_sampled_apart_from_the_effects(tmp_path):
    profile = tmp_path / "p.toml"
    profile.write_text(
        '[device]\nserial = "S1"\nname = "p"\n\n[[deny]]\nid = "p.wifi"\nwords = ["wifi"]\nreason = "r"\n'
    )
    policy = load_policy([], load_profile(profile))
    found = sweep.tally(judged("Wifi", "Settings", policy=policy))
    assert (found.denied, found.clear) == (1, 1) and found.samples == {"denied": ["Wifi"]}


def test_a_language_the_policy_does_not_cover_refuses_every_target_with_the_code():
    found = sweep.tally(judged("Share", "Settings", locale="xx-XX"))
    assert found.refused == {"LOCALE_UNSUPPORTED": 2} and found.clear == 0 and found.commits == {}


APPS = {
    "shop.app": app_xml("shop.app", "Share", "Delete", "Browse"),
    "game.app": dump(node("android.view.View", package="game.app", bounds="[0,0][1080,1920]")),
    "chat.app": app_xml("chat.app", "Send"),
}
SCREENS = {
    "home": Screen("com.android.launcher3"),
    "shop.app": Screen("shop.app", ('button "Share" [0,0,500,90]',)),
    "game.app": Screen("game.app", ()),
    "chat.app": Screen("chat.app", ('button "Send" [0,0,500,90]',)),
    "crash": Screen("com.android.systemui", ('text "App stopped"',), dialog=True),
}


def react(phone, words):
    match words:
        case ("press", "home"):
            return "home"
        case ("launch", "missing.app"):
            raise FakePhone.Refused("NOT_FOUND")
        case ("launch", "broken.app"):
            return "crash"
        case ("launch", package):
            return package
    raise FakePhone.Refused("NOT_FOUND")


def phone(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    return FakePhone(
        serial="S:1",
        screens=dict(SCREENS),
        screen="home",
        react=react,
        raw_dir=raw,
        raw_xml=lambda p: APPS.get(p.screen, app_xml("com.android.systemui")),
    )


def run(tmp_path, fake, *packages, facts=None, state=None, monkeypatch=None):
    document = facts or {
        "serial": "S:1",
        "locale": "en-US",
        "displays": [{"id": 0, "width": 1080, "height": 1920}],
    }
    (tmp_path / "facts.json").write_text(json.dumps(document))
    if monkeypatch is not None:
        monkeypatch.setenv("AGENT_PHONE_HOME", str(state or tmp_path / "state"))
    code = sweep.main([str(tmp_path), "S:1", *packages], fake.runner, tmp_path / "raw")
    return code, [json.loads(line) for line in (tmp_path / "apps.jsonl").read_text().splitlines()]


def test_each_app_is_launched_waited_for_dumped_judged_and_left_by_home(tmp_path, monkeypatch):
    fake = phone(tmp_path)
    code, lines = run(tmp_path, fake, "shop.app", "chat.app", monkeypatch=monkeypatch)
    assert code == 0 and [line["package"] for line in lines] == ["shop.app", "chat.app"]
    assert fake.inputs == [
        ("launch", "shop.app"),
        ("press", "home"),
        ("launch", "chat.app"),
        ("press", "home"),
    ]
    assert fake.dumps == ["sweep-S-1-shop.app", "sweep-S-1-chat.app"]
    waits = [c for c in fake.commands if c[0] == "wait"]
    assert waits[0] == (
        "wait",
        "--app",
        "shop.app",
        "--settled",
        "--for",
        "role=button",
        "--timeout-ms",
        "20000",
    )
    shop, chat = lines
    assert shop["launched"] is True and shop["wait_ok"] is True and shop["settled_ms"] is not None
    assert shop["has_lines"] is True and shop["snapshot_lines"] == 1 and shop["app_shown"] == "shop.app"
    assert (shop["targets"], shop["clear"], shop["commits"], shop["denied"], shop["refused"]) == (
        3,
        1,
        {"publish": 1, "delete": 1},
        0,
        0,
    )
    assert shop["samples"] == {"publish": ["Share"], "delete": ["Delete"]}
    assert chat["commits"] == {"send": 1} and chat["clear"] == 0


def test_the_status_bar_of_the_system_is_not_a_target_of_the_app(tmp_path, monkeypatch):
    _, lines = run(tmp_path, phone(tmp_path), "shop.app", monkeypatch=monkeypatch)
    assert lines[0]["targets"] == 3, "Notifications belongs to com.android.systemui"


def test_a_screen_with_no_lines_is_recorded_as_such_and_the_wait_that_timed_out_has_no_settled_time(
    tmp_path, monkeypatch
):
    fake = phone(tmp_path)
    _, lines = run(tmp_path, fake, "game.app", monkeypatch=monkeypatch)
    game = lines[0]
    assert (game["has_lines"], game["snapshot_lines"]) == (False, 0)
    assert (game["wait_ok"], game["wait_error"], game["settled_ms"]) == (False, "TIMEOUT", None)
    assert game["targets"] == 0 and fake.inputs[-1] == ("press", "home")


def test_an_app_that_never_comes_to_the_front_is_not_judged_and_the_phone_still_goes_home(
    tmp_path, monkeypatch
):
    fake = phone(tmp_path)
    _, lines = run(tmp_path, fake, "broken.app", monkeypatch=monkeypatch)
    assert lines[0]["error"] == "not_foreground" and lines[0]["app_shown"] == "com.android.systemui"
    assert "targets" not in lines[0] and fake.inputs[-1] == ("press", "home")


def test_an_app_that_is_not_installed_is_a_line_and_nothing_else_is_sent(tmp_path, monkeypatch):
    fake = phone(tmp_path)
    _, lines = run(tmp_path, fake, "missing.app", "chat.app", monkeypatch=monkeypatch)
    assert (lines[0]["launched"], lines[0]["launch_error"], lines[0]["delivery"]) == (
        False,
        "NOT_FOUND",
        "not_delivered",
    )
    assert fake.inputs == [("launch", "chat.app"), ("press", "home")]


def test_a_protected_package_is_skipped_by_evidence_and_the_sweep_goes_on(tmp_path, monkeypatch):
    fake = phone(tmp_path)
    _, lines = run(tmp_path, fake, "hev.sockstun", "chat.app", monkeypatch=monkeypatch)
    assert lines[0]["launched"] is False and "protected package" in lines[0]["skipped"]
    assert [i[0] for i in fake.inputs] == ["launch", "press"] and fake.inputs[0] == ("launch", "chat.app")


def test_the_only_inputs_are_launch_and_home_and_never_a_tap(tmp_path, monkeypatch):
    fake = phone(tmp_path)
    run(tmp_path, fake, "shop.app", "game.app", "chat.app", monkeypatch=monkeypatch)
    assert {words[:1] for words in fake.inputs} == {("launch",), ("press",)}
    assert all(words in (("press", "home"),) or words[0] == "launch" for words in fake.inputs)


def test_the_profile_installed_for_the_serial_judges_the_taps_too(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "profiles").mkdir(parents=True)
    (state / "profiles" / "shop.toml").write_text(
        '[device]\nserial = "S:1"\nname = "shop"\n\n'
        '[[deny]]\nid = "shop.delete"\nwords = ["delete"]\nreason = "r"\n'
    )
    _, lines = run(tmp_path, phone(tmp_path), "shop.app", monkeypatch=monkeypatch, state=state)
    assert lines[0]["profile"] == "shop" and lines[0]["denied"] == 1
    assert lines[0]["commits"] == {"publish": 1} and lines[0]["samples"]["denied"] == ["Delete"]


def test_a_sweep_that_cannot_read_the_screen_sends_nothing_and_exits_1(tmp_path, monkeypatch):
    fake = phone(tmp_path)
    fake.snapshot_failures = 99
    code, lines = run(tmp_path, fake, "shop.app", monkeypatch=monkeypatch)
    assert code == 1 and fake.inputs == [] and "aborted" in lines[0]


def test_the_facts_are_needed_and_a_package_must_look_like_one(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PHONE_HOME", str(tmp_path / "state"))
    with pytest.raises(SystemExit, match="Run facts.py first"):
        sweep.main([str(tmp_path), "S:1", "a.b"], phone(tmp_path).runner)
    (tmp_path / "facts.json").write_text(json.dumps({"locale": None, "displays": []}))
    with pytest.raises(SystemExit, match="Run facts.py first"):
        sweep.main([str(tmp_path), "S:1", "a.b"], phone(tmp_path).runner)
    with pytest.raises(SystemExit) as stop:
        sweep.main([str(tmp_path), "S:1", "../../etc"], phone(tmp_path).runner)
    assert stop.value.code == 2
