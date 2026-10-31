"""Structure tests that make the delivery rules hold by construction. Each plants a violation
first, like tests/test_architecture.py, so a rule that stops detecting fails the suite."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "agent_phone"
ONLY_CALLER = {
    "inject": "core/act/act.py",
    "Permit": "core/act/ledger.py",
}


def calls(source: str, name: str) -> int:
    count = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == name) or (
                isinstance(func, ast.Name) and func.id == name
            ):
                count += 1
    return count


def test_rule_catches_planted_calls():
    assert calls("phone.inject(p)", "inject") == 1
    assert calls("Permit(d, 1, a, v, g)", "Permit") == 1
    assert calls("phone.injector(p)", "inject") == 0


def test_input_reaches_a_backend_through_one_door():
    for name, owner in ONLY_CALLER.items():
        sites = {
            str(path.relative_to(PACKAGE)): calls(path.read_text(), name)
            for path in PACKAGE.rglob("*.py")
            if calls(path.read_text(), name)
        }
        assert set(sites) <= {owner} and sum(sites.values()) <= 1, f"{name}( is called from {sites}"


def test_every_attrs_string_field_is_a_label_or_declared_not_one():
    from dataclasses import fields

    from agent_phone.core.labels import LABEL_FIELDS, NON_LABEL_FIELDS
    from agent_phone.core.screen import Attrs

    strings = {f.name for f in fields(Attrs) if f.type in ("str", str)}
    assert strings == set(LABEL_FIELDS) | set(NON_LABEL_FIELDS)
