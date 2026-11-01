"""probes/android/gate_check.py judges a raw dump offline. It is a script and a function: the CLI
prints the active package and one line per target, and `judge` gives the same verdicts to a script
that counts them."""

import re
import subprocess
import sys

from support import ROOT, fixture_xml

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.cli.policy import load_policy
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import Refusal
from agent_phone.core.policy.engine import Clear, Commits, Denied
from agent_phone.core.role import takes_touch

sys.path.append(str(ROOT / "probes" / "android"))
import gate_check  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "dumps" / "dialog-over-app.xml"


def cli(locale: str, *extra: str) -> list[str]:
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "probes" / "android" / "gate_check.py"),
            str(FIXTURE),
            locale,
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def screen():
    return parse_hierarchy(fixture_xml("dialog-over-app"), Size(1080, 1920), None)


def test_the_cli_names_the_active_window_and_judges_each_target_in_one_line():
    lines = cli("en-US")
    assert lines[0] == "active com.android.settings"
    judged = list(gate_check.judge(screen(), load_policy([], None), "en-US"))
    assert len(lines) - 1 == len(judged) and judged
    assert all(re.match(r"  (clear|commits \S+|denied \S+) +\S+ +\w+ +'", line) for line in lines[1:])


def test_a_language_the_policy_lacks_makes_the_cli_print_a_refusal_for_every_target():
    lines = cli("fr-FR")
    assert len(lines) > 1
    assert all(re.match(r"  refused LOCALE_UNSUPPORTED +\w+ +'", line) for line in lines[1:])


def test_judge_gives_one_verdict_per_element_that_takes_a_touch_and_the_refusal_it_raised():
    elements = [n for n in screen().nodes if takes_touch(n.attrs)]
    found = list(gate_check.judge(screen(), load_policy([], None), "en-US"))
    assert len(found) == len(elements)
    assert all(isinstance(j.outcome, Clear | Commits | Denied) for j in found)
    refused = list(gate_check.judge(screen(), load_policy([], None), "fr-FR"))
    assert refused and all(isinstance(j.outcome, Refusal) for j in refused)
