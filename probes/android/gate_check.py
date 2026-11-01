"""What the gate would say about an input, judged offline from a raw dump, with nothing sent.

    uv run python -I probes/android/gate_check.py <raw.xml> <locale> [--profile PROFILE.toml]
        [--action tap|set-text] [--policy FILE]...

It prints the verdict for every element the input could target: a tap for each element that
takes a touch, a set-text for each text field. It judges the same way `act()` does, through
`classify`, so run it before a live input whose refusal you want to see. A live input sent only to
check that the gate refuses it goes out if the gate does not (A6-6). Raw dumps come from
`probes/android/raw/`, which git ignores.
"""

import argparse
from pathlib import Path

from agent_phone.adapters.uiautomator2.parse import parse_hierarchy
from agent_phone.cli.policy import load_policy, load_profile
from agent_phone.core.act.act import address_of
from agent_phone.core.act.site import element_site
from agent_phone.core.geometry import Point, Size
from agent_phone.core.labels import display_name
from agent_phone.core.outcome import Refusal
from agent_phone.core.phone import SetText, Tap
from agent_phone.core.policy.engine import Clear, Commits, Denied, classify
from agent_phone.core.role import Role, role_of, takes_touch

parser = argparse.ArgumentParser(prog="gate_check.py")
parser.add_argument("raw", type=Path)
parser.add_argument("locale")
parser.add_argument("--profile", type=Path)
parser.add_argument("--action", choices=("tap", "set-text"), default="tap")
parser.add_argument("--policy", type=Path, action="append", default=[])
args = parser.parse_args()
policy = load_policy(args.policy, load_profile(args.profile) if args.profile else None)
screen = parse_hierarchy(args.raw.read_text(), Size(1080, 1920), None)
active = screen.active_window()
print("active", active.package if active else None)
for window in screen.windows:
    for node in screen.subtree(window.root):
        role = role_of(node.attrs)
        if args.action == "tap" and not takes_touch(node.attrs):
            continue
        if args.action == "set-text" and role is not Role.TEXT_FIELD:
            continue
        b = node.attrs.bounds
        address = address_of(screen, node)
        action = (
            Tap(Point((b.left + b.right) // 2, (b.top + b.bottom) // 2), address)
            if args.action == "tap"
            else SetText(address, "text", secret=False)
        )
        name = display_name(screen, node, role)[:60]
        try:
            verdict = classify(policy, action, element_site(screen, node), args.locale)
        except Refusal as refusal:
            print(f"  refused {refusal.code.value:<20} {role.value:<8} {name!r}")
            continue
        match verdict:
            case Clear():
                said = "clear"
            case Commits(effects=effects):
                said = "commits " + ",".join(sorted(e.value for e in effects))
            case Denied(rule=rule):
                said = f"denied {rule}"
        print(f"  {said:<28} {window.package[:28]:<28} {role.value:<8} {name!r}")
