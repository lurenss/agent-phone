"""`agent-phone skills list` and `agent-phone skills get [name]`. They print the agent-facing
usage docs that ship inside the package, so an agent reads the guide for the version it runs.
They need no device and start nothing on one."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_phone.core.outcome import Outcome, Read


@dataclass(frozen=True, slots=True)
class Skill:
    """`name` is the skill's folder under the skills root and the `name` in its SKILL.md."""

    name: str
    alias: str
    summary: str


SKILLS = (
    Skill(
        "agent-phone",
        "phone",
        "The short usage guide: the loop of look, act with --settle and look again, the output, "
        "targets, waits, the commit gate and what to do on each error. Load it first.",
    ),
    Skill(
        "agent-phone-reference",
        "reference",
        "The full reference: devices, snapshots and refs, skeleton and drill-down, settle, surfaces, "
        "find, get and is, taps, text, scrolls and keys, the commit gate, launch, stop, links, "
        "rotation, the clipboard and screenshots, batch and flows, errors and retry, and the "
        "on-device server. Load it when the short guide does not answer.",
    ),
)


@dataclass(frozen=True, slots=True)
class SkillsListCommand:
    pass


@dataclass(frozen=True, slots=True)
class SkillsGetCommand:
    skill: Skill


@dataclass(frozen=True, slots=True)
class SkillCatalog:
    skills: tuple[Skill, ...]


@dataclass(frozen=True, slots=True)
class SkillText:
    skill: Skill
    content: str


def run(root: Path, cmd: SkillsListCommand | SkillsGetCommand) -> Outcome:
    match cmd:
        case SkillsListCommand():
            return Read(SkillCatalog(SKILLS))
        case SkillsGetCommand():
            text = (root / cmd.skill.name / "SKILL.md").read_text(encoding="utf-8")
            return Read(SkillText(cmd.skill, text))
