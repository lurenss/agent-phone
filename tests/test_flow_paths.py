"""A flow is the parser's vocabulary, not a second way to send input. Its modules build no command
and name no input type: every step comes from `parse_args` and runs through `Driver.run`, as the
same words on a command line do. The rule plants violations first, like tests/test_architecture.py,
so a rule that stops detecting fails the suite."""

import ast
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "src" / "agent_phone" / "cli"
FLOW_MODULES = ("flow.py", "flow_file.py", "flow_record.py")
FORBIDDEN_IMPORTS = ("agent_phone.core.act", "agent_phone.core.phone", "agent_phone.adapters")
THE_ONE_DOOR = "run_step"


def second_paths(source: str) -> list[str]:
    """What would let a flow reach the phone past the parser and the gate: an import of the input
    types or of act(), a command built by hand, or a call of a command's or a driver's `run`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found += [node.module for banned in FORBIDDEN_IMPORTS if node.module.startswith(banned)]
        elif isinstance(node, ast.Import):
            found += [a.name for a in node.names for banned in FORBIDDEN_IMPORTS if a.name.startswith(banned)]
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name.endswith("Command") or name in ("run", "act", "inject"):
                found.append(f"{name}(")
    return found


def test_rule_catches_planted_second_paths():
    assert second_paths("from agent_phone.core.act.act import act") == ["agent_phone.core.act.act"]
    assert second_paths("import agent_phone.core.phone") == ["agent_phone.core.phone"]
    assert second_paths("ClickCommand(target)") == ["ClickCommand("]
    assert second_paths("click.run(ctx, command)") == ["run("]
    assert second_paths("driver.run(command)") == ["run("]
    assert second_paths("phone.inject(permit)") == ["inject("]
    assert second_paths("run_step(step, driver, clock)\nparse_step(0, argv)") == []


@pytest.mark.xfail(strict=True, reason="P3.6: the flow modules are not written yet")
def test_a_flow_step_reaches_the_phone_only_through_the_parser_and_the_drivers_one_dispatch():
    present = [name for name in FLOW_MODULES if (CLI / name).exists()]
    assert "flow.py" in present and "flow_file.py" in present
    for name in present:
        assert second_paths((CLI / name).read_text()) == [], f"cli/{name} has a second path to the phone"
    runner = (CLI / "flow.py").read_text()
    calls = [
        n.func.id
        for n in ast.walk(ast.parse(runner))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert THE_ONE_DOOR in calls, "the runner runs its steps as a batch does, through Driver.run"
