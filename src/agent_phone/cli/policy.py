"""The rules a command runs under: the package default, the device's profile and its policy
files, then the caller's files, merged in that order (`rules.merge`).

Device profiles are read from `<state root>/profiles/*.toml` at the CLI boundary.

A profile file has a `[device]` table (`serial`, `name`, optional `policy_files`), any number of
`[[protected]]` tables (`package`, `labels`, `reason`), and policy tables of its own. Its
protections compile into deny rules (`rules.protect_rules`). The profile and the files its
`policy_files` name, read relative to the profile file, are trusted layers, as is the package
default: a later file, a caller's or another of the profile's, cannot disable their deny rules,
and what their denials read is not weakened by a caller's `disable`, `exempt` or `ignore`
(`model.Policy`). `examples/devices/j7.toml` is one.

A profile that does not parse fails every command that loads it, with POLICY_INVALID. A broken
profile must never leave its phone unprotected.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from agent_phone.core.device import DeviceProfile, Package, ProtectedPackage, Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.policy.rules import Policy, RuleId, merge, parse_policy, protect_rules

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policy" / "default.toml"
PROFILE_TABLES = frozenset({"device", "protected"})
DEVICE_KEYS = frozenset({"serial", "name", "policy_files"})
PROTECTED_KEYS = frozenset({"package", "labels", "reason"})


@dataclass(frozen=True, slots=True)
class LoadedProfile:
    """A profile and the policy layer it adds: its protections and its own tables."""

    profile: DeviceProfile
    source: Path
    layer: tuple[Policy, frozenset[RuleId]]

    def policy_files(self) -> tuple[Path, ...]:
        return tuple(self.source.parent / name for name in self.profile.policy_files)


def read_toml(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise Refusal(
            ErrorCode.POLICY_INVALID,
            f"The policy file {path} cannot be read as TOML: {error}.",
            {"source": str(path)},
        ) from error


def load_profiles(state_root: Path) -> tuple[LoadedProfile, ...]:
    directory = state_root / "profiles"
    if not directory.is_dir():
        return ()
    loaded = [load_profile(path) for path in sorted(directory.glob("*.toml"))]
    serials = [entry.profile.serial for entry in loaded]
    for serial in serials:
        if serials.count(serial) > 1:
            raise Refusal(
                ErrorCode.POLICY_INVALID,
                f"Two profiles in {directory} name the device {serial}. Keep one.",
                {"serial": serial},
            )
    return tuple(loaded)


def profile_for(profiles: Sequence[LoadedProfile], serial: Serial) -> LoadedProfile | None:
    return next((entry for entry in profiles if entry.profile.serial == serial), None)


def load_profile(path: Path) -> LoadedProfile:
    doc = read_toml(path)
    source = str(path)

    def fail(table: str, field: str, problem: str) -> Refusal:
        return Refusal(
            ErrorCode.POLICY_INVALID,
            f"{source}: [{table}]: {field} {problem}.",
            {"source": source, "table": table, "field": field},
        )

    device = doc.get("device")
    if not isinstance(device, Mapping):
        raise fail("device", "device", "is missing, and a profile must name its device")
    for key in device:
        if key not in DEVICE_KEYS:
            raise fail("device", key, "is not a key of [device]")
    serial, name = device.get("serial"), device.get("name")
    files = device.get("policy_files", [])
    if not isinstance(serial, str) or not serial.strip():
        raise fail("device", "serial", "must be the device's adb serial")
    if not isinstance(name, str) or not name.strip():
        raise fail("device", "name", "must be a non-empty string")
    if not isinstance(files, list) or not all(isinstance(f, str) and f.strip() for f in files):
        raise fail("device", "policy_files", "must be a list of file paths")
    protected = doc.get("protected", [])
    if not isinstance(protected, list):
        raise fail("protected", "protected", "must be an array of tables, written [[protected]]")
    packages = []
    for entry in protected:
        if not isinstance(entry, Mapping) or set(entry) - PROTECTED_KEYS:
            raise fail("protected", "protected", f"may hold only {', '.join(sorted(PROTECTED_KEYS))}")
        package, labels, reason = entry.get("package"), entry.get("labels", []), entry.get("reason")
        if not isinstance(package, str) or not package.strip():
            raise fail("protected", "package", "must be a package name")
        if not isinstance(labels, list) or not all(
            isinstance(label, str) and label.strip() for label in labels
        ):
            raise fail("protected", "labels", "must be a list of the names Settings shows for the package")
        if not isinstance(reason, str) or not reason.strip():
            raise fail("protected", "reason", "must say why the package is protected")
        packages.append(ProtectedPackage(Package(package), tuple(labels), reason))
    profile = DeviceProfile(Serial(serial), name, tuple(packages), tuple(files))
    own, disabled = parse_policy(
        {key: value for key, value in doc.items() if key not in PROFILE_TABLES}, source, trusted=True
    )
    layer = replace(own, rules=protect_rules(profile, source) + own.rules)
    return LoadedProfile(profile, path, (layer, disabled))


def load_policy(extra: Sequence[Path], profile: LoadedProfile | None = None) -> Policy:
    """The package default, then the device profile and its policy files, then the caller's."""
    layers = [parse_policy(read_toml(DEFAULT_POLICY), str(DEFAULT_POLICY), trusted=True)]
    if profile is not None:
        layers.append(profile.layer)
        layers.extend(
            parse_policy(read_toml(path), str(path), trusted=True) for path in profile.policy_files()
        )
    layers.extend(parse_policy(read_toml(path), str(path)) for path in extra)
    return merge(tuple(layers))
