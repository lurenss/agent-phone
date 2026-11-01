#!/usr/bin/env python3
"""Write a device profile, install it and prove agent-phone accepts it. Run it from the repo root:

    uv run python -I .claude/skills/port-android-device/scripts/profile.py --serial S --name N
        [--protect PACKAGE=REASON]... [--policy-file PATH]... [--force]

It writes `examples/devices/<name>.toml` in the format of `j7.toml` and `thor.toml`, installs it as
`<state root>/profiles/<name>.toml` (the state root is `AGENT_PHONE_HOME`, else `~/.agent-phone`),
copies each policy file to the path the profile resolves it to, and loads the installed profile with
`load_profile` and `load_policy`. A policy file `examples/chess/policy.toml` is named
`../chess/policy.toml` in the profile, which resolves to `<state root>/chess/policy.toml`.

A profile that agent-phone refuses is never installed: the check runs on a copy first, because one
broken profile in the folder fails every command on every device. It refuses to overwrite a profile,
an installed profile or a different policy file at a destination without `--force`, and it refuses a
serial that another installed profile names, with or without it.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from device_calls import REPO, device_name  # noqa: E402

from agent_phone.cli.policy import LoadedProfile, load_policy, load_profile  # noqa: E402
from agent_phone.cli.settings import Settings  # noqa: E402
from agent_phone.core.outcome import Refusal  # noqa: E402
from agent_phone.core.phone import NAME as PACKAGE_NAME  # noqa: E402

SERIAL = r"[A-Za-z0-9][A-Za-z0-9._:-]*"
RESERVED_FOLDERS = {"profiles"}


@dataclass(frozen=True, slots=True)
class PolicyFile:
    """A policy file to copy, and the path the profile names it by: `../<its folder>/<its name>`."""

    source: Path
    entry: str


def protection(text: str) -> tuple[str, str]:
    package, equals, reason = text.partition("=")
    if not equals or not PACKAGE_NAME.fullmatch(package) or not reason.strip():
        raise argparse.ArgumentTypeError(f"{text!r} is not PACKAGE=REASON, with a package name and a reason")
    return package, reason.strip()


def policy_file(text: str) -> PolicyFile:
    source = Path(text).resolve()
    if not source.is_file():
        raise argparse.ArgumentTypeError(f"{text} is not a file")
    if source.parent.name in RESERVED_FOLDERS:
        raise argparse.ArgumentTypeError(
            f"{text} sits in a folder named {source.parent.name}, which holds profiles"
        )
    return PolicyFile(source, f"../{source.parent.name}/{source.name}")


def shown(path: Path) -> str:
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def render(name: str, serial: str, protects: list[tuple[str, str]], files: list[PolicyFile]) -> str:
    """The profile's text, in the format of `examples/devices/j7.toml`."""
    head = [
        f"# The {name} profile. Copy it to ~/.agent-phone/profiles/, where agent-phone reads every profile."
    ]
    if files:
        head.append("# A policy file resolves from the profile's folder, and one that cannot be read fails")
        head.append("# every command on the device. Copy each policy file to the path shown:")
        head += [f"#   {shown(f.source)} -> ~/.agent-phone/{f.entry.removeprefix('../')}" for f in files]
    else:
        head.append("# It names no policy file.")
    body = [
        "",
        "[device]",
        f"serial = {json.dumps(serial)}",
        f"name = {json.dumps(name)}",
    ]
    if files:
        body.append(f"policy_files = {json.dumps([f.entry for f in files])}")
    for package, reason in protects:
        body += [
            "",
            "[[protected]]",
            f"package = {json.dumps(package)}",
            "# The names Settings shows for the package: with them, a screen that names it is refused too.",
            "labels = []",
            f"reason = {json.dumps(reason, ensure_ascii=False)}",
        ]
    return "\n".join([*head, *body]) + "\n"


def accepted(text: str, name: str, files: list[PolicyFile]) -> None:
    """Load the profile and its policy in a scratch state root laid out like the real one. Exits with
    agent-phone's own message when it refuses."""
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        (root / "profiles").mkdir()
        (root / "profiles" / f"{name}.toml").write_text(text, encoding="utf-8")
        install_policy_files(root / "profiles", files)
        load(root / "profiles" / f"{name}.toml")


def load(path: Path) -> tuple[LoadedProfile, int]:
    try:
        loaded = load_profile(path)
        return loaded, len(load_policy([], loaded).rules)
    except Refusal as refusal:
        sys.exit(f"profile: agent-phone refuses {path}: {refusal.message}")


def destination(profiles: Path, file: PolicyFile) -> Path:
    return (profiles / file.entry).resolve()


def install_policy_files(profiles: Path, files: list[PolicyFile]) -> None:
    for file in files:
        target = destination(profiles, file)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file.source, target)


def conflicts(profiles: Path, name: str, serial: str, files: list[PolicyFile], force: bool) -> list[str]:
    """What stands in the way of installing: another profile for the serial, a profile of this name,
    or a policy file with other content at its destination."""
    found = []
    for other in sorted(profiles.glob("*.toml")) if profiles.is_dir() else []:
        try:
            held = tomllib.loads(other.read_text(encoding="utf-8")).get("device", {}).get("serial")
        except (OSError, ValueError):
            continue
        if held == serial and other.stem != name:
            found.append(
                f"{other} already names the device {serial}. Remove it, or use its name with --force"
            )
    if not force:
        if (profiles / f"{name}.toml").exists():
            found.append(f"{profiles / f'{name}.toml'} is installed already")
        for file in files:
            target = destination(profiles, file)
            if target.exists() and target.read_bytes() != file.source.read_bytes():
                found.append(f"{target} holds a different file than {file.source}")
    return found


def main(argv: list[str], state_root: Path | None = None, devices: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="profile.py", description="Write, install and check a device profile."
    )
    parser.add_argument("--serial", required=True)
    parser.add_argument("--name", required=True, type=device_name)
    parser.add_argument("--protect", action="append", default=[], type=protection, metavar="PACKAGE=REASON")
    parser.add_argument("--policy-file", action="append", default=[], type=policy_file, metavar="PATH")
    parser.add_argument("--force", action="store_true", help="overwrite an existing profile or policy file")
    args = parser.parse_args(argv)
    if not re.fullmatch(SERIAL, args.serial):
        parser.error(f"{args.serial!r} is not an adb serial")
    packages = [package for package, _ in args.protect]
    entries = [file.entry for file in args.policy_file]
    if len(set(packages)) != len(packages) or len(set(entries)) != len(entries):
        parser.error("a package or a policy file is named twice")
    devices = devices or REPO / "examples" / "devices"
    profiles = (state_root or Settings.from_environment().state_root) / "profiles"
    example = devices / f"{args.name}.toml"
    if example.exists() and not args.force:
        sys.exit(f"profile: {example} exists. Pass --force to overwrite it.")
    if blocked := conflicts(profiles, args.name, args.serial, args.policy_file, args.force):
        sys.exit("profile: " + "; ".join(blocked) + ".")
    text = render(args.name, args.serial, args.protect, args.policy_file)
    accepted(text, args.name, args.policy_file)
    devices.mkdir(parents=True, exist_ok=True)
    example.write_text(text, encoding="utf-8")
    profiles.mkdir(parents=True, exist_ok=True)
    installed = profiles / f"{args.name}.toml"
    shutil.copyfile(example, installed)
    install_policy_files(profiles, args.policy_file)
    loaded, rules = load(installed)
    print(f"wrote {example}")
    counts = f"{len(loaded.profile.protected)} protected, {rules} rules"
    print(f"installed {installed}: device {loaded.profile.serial}, {counts}")
    for file in loaded.policy_files():
        print(f"policy file {file.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
