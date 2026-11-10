"""A flow is the parser's vocabulary, not a second way to send input. Its modules build no command
and name no input type: every step comes from `parse_args` and runs through `Driver.run`, as the
same words on a command line do. The rule plants violations first, like tests/test_architecture.py,
so a rule that stops detecting fails the suite."""

import ast
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "src" / "agent_phone" / "cli"
FORBIDDEN_IMPORTS = ("agent_phone.core.act", "agent_phone.core.phone", "agent_phone.adapters")
DOORS = ("run", "act", "inject")
THE_ONE_DOOR = "run_step"


def second_paths(source: str) -> list[str]:
    """What would let a flow reach the phone past the parser and the gate: an import of act() or
    of an input type, a command built by hand, a call of a command's or a driver's `run`,
    and a `commit=` that is not the empty set, which would give a step a grant its words lack.
    `PhoneHub` is the list of devices, which `open_phone` takes, and no input type. `Flow...Command`
    is the flow's own command line, not a step."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = {alias.name for alias in node.names}
            found += [f"import {name}" for name in sorted(names & set(DOORS))]
            if node.module == "agent_phone.core.phone" and names == {"PhoneHub"}:
                continue
            found += [node.module for banned in FORBIDDEN_IMPORTS if node.module.startswith(banned)]
        elif isinstance(node, ast.Import):
            found += [a.name for a in node.names for banned in FORBIDDEN_IMPORTS if a.name.startswith(banned)]
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if (name.endswith("Command") and not name.startswith("Flow")) or name in DOORS:
                found.append(f"{name}(")
            if name == "getattr" and any(isinstance(a, ast.Constant) and a.value in DOORS for a in node.args):
                found.append("getattr(")
            found += [
                "commit="
                for keyword in node.keywords
                if keyword.arg == "commit" and ast.unparse(keyword.value) != "frozenset()"
            ]
    return found


def test_rule_catches_planted_second_paths():
    assert second_paths("from agent_phone.core.act.act import act") == [
        "import act",
        "agent_phone.core.act.act",
    ]
    assert second_paths("import agent_phone.core.phone") == ["agent_phone.core.phone"]
    assert second_paths("from agent_phone.core.phone import PhoneHub, Tap") == ["agent_phone.core.phone"]
    assert second_paths("from agent_phone.core.phone import PhoneHub") == []
    assert second_paths("from agent_phone.core.commands.click import run as tap") == ["import run"]
    assert second_paths("ClickCommand(target)") == ["ClickCommand("]
    assert second_paths("FlowRunCommand(path, values, commit, dry_run)") == []
    assert second_paths("click.run(ctx, command)") == ["run("]
    assert second_paths("driver.run(command)") == ["run("]
    assert second_paths("getattr(driver, 'run')(command)") == ["getattr("]
    assert second_paths("phone.inject(permit)") == ["inject("]
    assert second_paths("replace(command, commit=frozenset(flow.grants))") == ["commit="]
    assert second_paths("replace(command, commit=frozenset())") == []
    assert second_paths("run_step(step, driver, clock)\nparse_step(0, argv)") == []


def test_a_flow_step_reaches_the_phone_only_through_the_parser_and_the_drivers_one_dispatch():
    modules = sorted(CLI.glob("flow*.py"))
    assert {"flow.py", "flow_file.py"} <= {path.name for path in modules}
    for path in modules:
        assert second_paths(path.read_text()) == [], f"cli/{path.name} has a second path to the phone"
    runner = (CLI / "flow.py").read_text()
    calls = [
        n.func.id
        for n in ast.walk(ast.parse(runner))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert THE_ONE_DOOR in calls, "the runner runs its steps as a batch does, through Driver.run"
