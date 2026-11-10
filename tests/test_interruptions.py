"""Pop-ups the agent did not ask for, recognised from policy data and named in every observation.

The dialogs are built here, not captured from a phone, so no test names a real app. The words for an
app that does not respond and for a permission are those of AOSP's string resources. The paste and
purchase prompts have no AOSP dialog behind them: their words are this project's own.
`CAPTURED` lists the dialogs read from a device: the `emu-*-35-*` ones are Android 15's own, raised
on the emulator in `en-US` and `it-IT`."""

import tomllib

import pytest
from fakes import J7_SERIAL, FakeHub, FakePhone, info_for, invoke
from support import DUMPS, FakeClock, fixture_screen, node, screen_of

from agent_phone.cli.policy import DEFAULT_POLICY
from agent_phone.core.act.ledger import Ledger
from agent_phone.core.context import Context
from agent_phone.core.device import Connected
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.interrupt import interruptions_of
from agent_phone.core.policy.model import InterruptionKind, InterruptionRule
from agent_phone.core.policy.rules import merge, parse_policy
from agent_phone.core.refs.store import FORMAT, SnapshotStore
from agent_phone.core.snapshot.capture import capture

J7 = Connected(J7_SERIAL, "SM_J730F", ready=True)
DEFAULT = parse_policy(tomllib.loads(DEFAULT_POLICY.read_text(encoding="utf-8")), "default.toml")
POLICY = merge((DEFAULT,))
SHOP = "com.example.shop"
RATE_US = {
    "id": "shop.rate-us",
    "kind": "promo",
    "packages": [SHOP],
    "words": ["rate us", "not now"],
    "dismiss": ["Not now"],
    "reason": "The shop asks for a rating over any of its screens.",
}


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


def context(root, *screens, policy=POLICY, locale="en-US"):
    info = info_for(J7_SERIAL, locale=locale)
    phone = FakePhone(info, *screens)
    return Context(phone, info, None, policy, SnapshotStore(root), Ledger(root, info.identity), FakeClock())


def with_rules(**tables):
    return merge((DEFAULT, parse_policy(tables, "consumer.toml")))


def found(screen, policy=POLICY, locale="en-US"):
    return [(i.rule, i.kind.value, i.needs_human) for i in interruptions_of(policy, screen, locale)]


ANR = screen_of(dialog("Example isn't responding", "Close app", "Wait"))


def ref_of(wire, name):
    """The ref of the one tree line named `name`."""
    [line] = [line for line in wire["data"]["tree"] if f'"{name}"' in line]
    return line.split()[0]


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


def test_a_wait_and_the_after_of_an_input_name_the_interruption_too(tmp_path):
    hub = FakeHub([J7], screens=[ANR])
    code, waited = invoke(["wait", "--for", "name=Wait"], hub, tmp_path)
    assert code == 0 and waited["data"]["interruptions"][0]["dismiss"] == ref_of(waited, "Wait")
    hub = FakeHub([J7], screens=[fixture_screen("settings-home")], after_input=[ANR])
    _, taken = invoke(["snapshot"], hub, tmp_path)
    assert taken["data"]["interruptions"] == []
    code, clicked = invoke(["click", f"@{taken['data']['id']}:e7", "--wait-for", "name=Wait"], hub, tmp_path)
    after = clicked["data"]["after"]
    assert after["interruptions"][0]["rule"] == "default.not-responding.en"
    assert after["interruptions"][0]["dismiss"] == ref_of({"data": after}, "Wait")


def test_a_recorded_interruption_is_read_back_from_the_store(tmp_path):
    ctx = context(tmp_path, ANR)
    taken = capture(ctx, ctx.phone.read())
    [note] = taken.interruptions
    assert note.kind is InterruptionKind.NOT_RESPONDING and note.dismiss == 2
    assert ctx.store.load(taken.id) == taken


def test_a_snapshot_stored_before_interruptions_existed_is_not_read(tmp_path):
    ctx = context(tmp_path, ANR)
    taken = capture(ctx, ctx.phone.read())
    path = tmp_path / "devices" / J7_SERIAL / "snapshots" / f"{taken.id}.json"
    assert FORMAT == 2 and f'"format":{FORMAT}' in path.read_text()
    path.write_text(path.read_text().replace(f'"format":{FORMAT}', '"format":1'))
    with pytest.raises(Refusal) as unreadable:
        ctx.store.load(taken.id)
    assert unreadable.value.code is ErrorCode.SNAPSHOT_NOT_FOUND


BUILT_IN = [
    ("not-responding", "en", False, ("Example isn't responding", "Close app", "Wait"), "Wait"),
    ("not-responding", "it", False, ("Example non risponde", "Chiudi app", "Attendi"), "Attendi"),
    (
        "permission",
        "en",
        False,
        ("Allow Example to take pictures and record video?", "While using the app", "Don’t allow"),
        "Don’t allow",
    ),
    (
        "permission",
        "it",
        False,
        ("Consentire a Example di scattare foto e registrare video?", "Mentre usi l'app", "Non consentire"),
        "Non consentire",
    ),
    ("permission.deny", "en", False, ("Allow Example to access your contacts?", "Deny", "Allow"), "Deny"),
    (
        "permission.deny",
        "it",
        False,
        ("Consentire a Example di accedere ai contatti?", "Rifiuta", "Consenti"),
        "Rifiuta",
    ),
    ("paste", "en", True, ("Example wants to paste from the clipboard", "Deny", "Allow paste"), "Deny"),
    (
        "paste",
        "it",
        True,
        ("Example vuole incollare dagli appunti", "Rifiuta", "Consenti Incolla"),
        "Rifiuta",
    ),
    ("purchase", "en", True, ("Example Premium", "1-tap buy"), None),
    ("purchase", "it", True, ("Example Premium", "Acquista con 1 tocco"), None),
]


@pytest.mark.parametrize(("stem", "language", "needs_human", "labels", "way_out"), BUILT_IN)
def test_the_built_in_rules_name_each_system_prompt_in_english_and_italian(
    stem, language, needs_human, labels, way_out
):
    screen = screen_of(dialog(*labels))
    rule = f"default.{stem}.{language}"
    [match] = [i for i in interruptions_of(POLICY, screen, f"{language}-XX") if i.rule == rule]
    assert match.kind.value == stem.partition(".")[0].replace("-", "_") and match.needs_human is needs_human
    named = None if match.dismiss is None else screen.node(match.dismiss).attrs.text
    assert named == way_out
    other = "it" if language == "en" else "en"
    assert rule not in [i.rule for i in interruptions_of(POLICY, screen, f"{other}-XX")]


def test_the_built_in_rules_cover_four_kinds_in_both_languages_and_name_no_app():
    rules = POLICY.of_kind(InterruptionRule)
    covered = {(rule.kind, language) for rule in rules for language in rule.scope.languages}
    kinds = (
        InterruptionKind.NOT_RESPONDING,
        InterruptionKind.PERMISSION,
        InterruptionKind.PASTE,
        InterruptionKind.PURCHASE,
    )
    assert covered == {(kind, language) for kind in kinds for language in ("en", "it")}
    assert all(not rule.scope.packages and len(rule.scope.languages) == 1 for rule in rules)


CAPTURED = {
    "dialog-over-app": ("en", "default.permission.deny.en", "Deny"),
    "samsung-j7-dialog": ("en", "default.permission.deny.en", "Deny"),
    "emu-en-35-permission": ("en", "default.permission.en", "Don’t allow"),
    "emu-it-35-permission": ("it", "default.permission.it", "Non consentire"),
    "emu-en-35-not-responding": ("en", "default.not-responding.en", "Wait"),
    "emu-it-35-not-responding": ("it", "default.not-responding.it", "Attendi"),
}


def test_each_captured_dialog_is_named_with_its_way_out_and_every_other_fixture_is_quiet():
    for path in sorted(DUMPS.glob("*.xml")):
        screen = fixture_screen(path.stem)
        language, rule, way_out = CAPTURED.get(path.stem, ("en", None, None))
        named = [
            (i.rule, i.dismiss and screen.node(i.dismiss).attrs.text)
            for i in interruptions_of(POLICY, screen, f"{language}-XX")
        ]
        assert named == ([(rule, way_out)] if rule else []), path.stem


def test_a_consumer_file_names_its_own_apps_pop_up_and_only_in_that_app(tmp_path):
    policy = with_rules(interruption=[RATE_US])
    sheet = ("Enjoying Example Shop? Rate us", "Not now", "Rate")
    ours = screen_of(dialog(*sheet, package=SHOP))
    assert found(ours, policy) == [("shop.rate-us", "promo", False)]
    assert found(screen_of(dialog(*sheet, package="com.example.other")), policy) == []
    assert found(ours) == [], "the built-in rules know no app's own pop-up"
    ctx = context(tmp_path, ours, policy=policy)
    taken = capture(ctx, ctx.phone.read())
    assert taken.interruption_data() == [
        {"rule": "shop.rate-us", "kind": "promo", "needs_human": False, "dismiss": f"@{taken.id}:e1"}
    ]


def test_a_way_out_is_never_a_guess_and_typed_text_is_never_a_pop_up():
    twice = screen_of(dialog("Example isn't responding", "Close app", "Wait", "Wait"))
    [twin] = interruptions_of(POLICY, twice, "en-US")
    assert twin.dismiss is None, "two buttons say Wait"
    typed = screen_of(
        node(
            "android.widget.FrameLayout",
            node("android.widget.EditText", text="it isn't responding, close app or wait?", editable=True),
        )
    )
    assert found(typed) == []
    title = node("android.widget.TextView", text="Example isn't responding, Close app")
    field = node("android.widget.EditText", text="Wait", editable=True, clickable=True)
    off = node("android.widget.Button", text="Wait", clickable=True, enabled=False)
    for wait in (field, off):
        said = node("android.widget.TextView", text="Please wait")
        [match] = interruptions_of(
            POLICY, screen_of(node("android.widget.FrameLayout", title, said, wait)), "en-US"
        )
        assert match.dismiss is None, "typed text and a disabled button are no way out"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"tap": True}, "tap"),
        ({"kind": "banner"}, "kind"),
        ({"needs_human": "yes"}, "needs_human"),
        ({"words": []}, "words"),
        ({"dismiss": "Not now"}, "dismiss"),
    ],
)
def test_an_unknown_key_or_a_wrong_value_in_an_interruption_is_policy_invalid(change, field):
    with pytest.raises(Refusal) as invalid:
        parse_policy({"interruption": [RATE_US | change]}, "consumer.toml")
    assert invalid.value.code is ErrorCode.POLICY_INVALID
    assert invalid.value.details == {"source": "consumer.toml", "table": "interruption", "field": field}
    missing = {key: value for key, value in RATE_US.items() if key != "words"}
    with pytest.raises(Refusal) as wordless:
        parse_policy({"interruption": [missing]}, "consumer.toml")
    assert wordless.value.details["field"] == "words"
