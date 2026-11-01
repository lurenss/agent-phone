"""`skills list` and `skills get` print the guides that ship inside the package."""

import pytest
from fakes import invoke

from agent_phone.cli.process import SKILLS_ROOT
from agent_phone.core.commands.skills import SKILLS

GUIDE = (SKILLS_ROOT / "agent-phone" / "SKILL.md").read_text(encoding="utf-8")


class NoDevices:
    """A hub that fails any call, for commands that must never reach a device."""

    def __getattr__(self, name):
        raise AssertionError(f"skills asked the hub for {name}")


@pytest.mark.parametrize(
    "argv", [["skills", "get", "phone"], ["skills", "get", "agent-phone"], ["skills", "get"]]
)
def test_get_prints_the_shipped_guide_by_name_alias_or_default(argv):
    code, wire = invoke(argv, NoDevices())
    assert code == 0 and wire["ok"] is True and wire["command"] == "skills" and wire["device"] is None
    assert wire["data"] == {"name": "agent-phone", "content": GUIDE}
    assert GUIDE.startswith("---\nname: agent-phone\n")


def test_list_names_each_guide_with_its_alias_and_summary():
    code, wire = invoke(["skills", "list"], NoDevices())
    assert code == 0 and wire["device"] is None
    (guide,) = wire["data"]["skills"]
    assert guide["name"] == "agent-phone" and guide["alias"] == "phone" and guide["summary"]


def test_an_unknown_guide_is_invalid_args_and_names_the_known_ones():
    code, wire = invoke(["skills", "get", "desktop"], NoDevices())
    assert code == 2 and wire["error"]["code"] == "INVALID_ARGS"
    assert "agent-phone" in wire["error"]["message"] and "phone" in wire["error"]["message"]


def front_matter(text):
    """The top-level keys of the YAML front matter, a folded `>` value joined into one line."""
    head, _, _ = text.removeprefix("---\n").partition("\n---\n")
    fields: dict[str, str] = {}
    key = ""
    for line in head.splitlines():
        if line.startswith(" ") and key:
            fields[key] = f"{fields[key]} {line.strip()}".strip()
        else:
            key, _, value = line.partition(": ")
            fields[key] = "" if value == ">" else value
    return fields


def test_every_guide_folder_is_served_and_named_after_its_folder():
    on_disk = sorted(path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md"))
    assert on_disk == sorted(skill.name for skill in SKILLS)
    for name in on_disk:
        fields = front_matter((SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8"))
        assert fields["name"] == name and fields["description"]
