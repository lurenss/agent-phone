"""Structure tests that make the delivery rules hold by construction. Each plants a violation
first, like tests/test_architecture.py, so a rule that stops detecting fails the suite."""

import ast
from pathlib import Path

import pytest

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


def named(node: ast.AST, name: str) -> int:
    """How often `name` is written under `node`, in any role: a variable, a parameter, a target,
    the name of a function, a string."""
    return sum(
        value == name or (isinstance(value, list) and name in value)
        for inner in ast.walk(node)
        for _, value in ast.iter_fields(inner)
    )


def reaches(source: str, name: str) -> int:
    """How many places of `source` can get at a method called `name` without defining it: each
    `x.name`, each bare `name` and each string "name", called or not. So an alias of the bound
    method and a `getattr` count like a call. A class with `__getattr__` or `__getattribute__`
    answers for every name, so each mention of those two counts as well. No count sees a name that
    is built when the code runs, such as `"in" + "ject"`."""
    tree = ast.parse(source)
    direct = sum(
        (isinstance(node, ast.Attribute) and node.attr == name)
        or (isinstance(node, ast.Name) and node.id == name)
        or (isinstance(node, ast.Constant) and node.value == name)
        for node in ast.walk(tree)
    )
    return direct + named(tree, "__getattr__") + named(tree, "__getattribute__")


COUNTED = {"inject": reaches, "Permit": calls}
"""`Permit` is named in every signature that takes one, so only its calls are counted. Nothing but
a send needs the name `inject`, so every way to reach it is counted."""
HANDS_ON = {"adapters/remote/hub.py": "LeasedPhone"}
"""The one phone that wraps another phone, by file and class. Its `inject` adds a check and hands
on the permit that act() gave it, so the input still came through the one door. No other code may."""
WRAPPED = "_inner"


def hands_on_once(function: ast.FunctionDef) -> bool:
    """Whether `function` is an undecorated `inject(self, permit)` and its one send is a statement
    of its own body that reads `return self._inner.inject(permit)`. A send inside a loop, a `try`, a
    lambda or an inner function is not such a statement. The permit is named twice in all, where it
    comes in and where it goes on, so nothing can bind the name to another permit. The wrapped phone
    is named once, so nothing else is sent to it, by any name."""
    match function.args:
        case ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="self"), ast.arg(arg=permit)],
            vararg=None,
            kwonlyargs=[],
            kwarg=None,
        ):
            pass
        case _:
            return False
    sends = 0
    for statement in function.body:
        match statement:
            case ast.Return(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Attribute(value=ast.Name(id="self"), attr=wrapped), attr="inject"
                    ),
                    args=[ast.Name(id=sent)],
                    keywords=[],
                )
            ) if sent == permit and wrapped == WRAPPED:
                sends += 1
    return (
        sends == 1
        and not function.decorator_list
        and named(function, permit) == 2
        and named(function, WRAPPED) == 1
    )


def is_what_its_source_shows(wrapper: ast.ClassDef) -> bool:
    """Whether `inject` and the wrapped phone of the class can only be what `hands_on_once` reads.
    Nothing decorates the class. `inject` is named twice in it, by its `def` and by the hand-on, so
    nothing binds the name again, keeps the bound method or reaches it through a string. `_inner` is
    only ever an attribute, so it is no property, and only `__init__` assigns it."""
    uses = [node for node in ast.walk(wrapper) if isinstance(node, ast.Attribute) and node.attr == WRAPPED]
    in_init = [
        node
        for method in wrapper.body
        if isinstance(method, ast.FunctionDef) and method.name == "__init__"
        for node in ast.walk(method)
    ]
    return (
        not wrapper.decorator_list
        and named(wrapper, "inject") == 2
        and named(wrapper, WRAPPED) == len(uses)
        and all(use in in_init for use in uses if not isinstance(use.ctx, ast.Load))
    )


def handed_on(source: str, wrapper: str) -> int:
    """1 when the class `wrapper` hands a permit on once, the way `hands_on_once` reads it. A second
    class or a second `inject` of that name is not let through with it."""
    return int(
        any(
            isinstance(method, ast.FunctionDef) and method.name == "inject" and hands_on_once(method)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ClassDef) and node.name == wrapper and is_what_its_source_shows(node)
            for method in node.body
        )
    )


def sites(path: str, source: str, name: str) -> int:
    """How many uses of `name` the file at `path`, relative to the package, adds to the count."""
    wrapper = HANDS_ON.get(path) if name == "inject" else None
    return COUNTED[name](source, name) - (handed_on(source, wrapper) if wrapper else 0)


LEASED_PHONE = """
class LeasedPhone:
    def inject(self, permit):
        try:
            self._claim.keep()
        except Refusal as refusal:
            return NotSent(refusal.code, refusal.message)
        return self._inner.inject(permit)
"""
SECOND_DOORS = {
    "a retry loop sends one permit twice": """
class LeasedPhone:
    def inject(self, permit):
        for _ in range(2):
            delivery = self._inner.inject(permit)
        return delivery
""",
    "a retry after an error sends one permit twice": """
class LeasedPhone:
    def inject(self, permit):
        while True:
            try:
                return self._inner.inject(permit)
            except OSError:
                self._link.refresh()
""",
    "a rebound permit sends an action that act() never judged": """
class LeasedPhone:
    def inject(self, permit):
        permit = replace(permit, action=self._other_action)
        return self._inner.inject(permit)
""",
    "a permit bound by a handler is not the one that came in": """
class LeasedPhone:
    def inject(self, permit):
        try:
            self._claim.keep()
        except Lost as permit:
            pass
        return self._inner.inject(permit)
""",
    "a free function named inject is a door anyone can import": """
def inject(phone, permit):
    return phone.inject(permit)
""",
    "a send put off into a lambda leaves when the lambda runs": """
class LeasedPhone:
    def inject(self, permit):
        self._later = lambda: self._inner.inject(permit)
        return self._later()
""",
    "a second send before the hand-on": """
class LeasedPhone:
    def inject(self, permit):
        self._inner.inject(permit)
        return self._inner.inject(permit)
""",
    "a hand-on to anything but the wrapped phone": """
class LeasedPhone:
    def inject(self, permit):
        self._inner.state()
        return self._other.inject(permit)
""",
    "another class of the same file": LEASED_PHONE.replace("LeasedPhone", "Wrapped"),
    "a decorator on the hand-on sends one permit twice": """
class LeasedPhone:
    @twice
    def inject(self, permit):
        return self._inner.inject(permit)
""",
    "a decorator on the class wraps every method": """
@retrying
class LeasedPhone:
    def inject(self, permit):
        return self._inner.inject(permit)
""",
    "a later binding in the class wraps the method": """
class LeasedPhone:
    def inject(self, permit):
        return self._inner.inject(permit)
    inject = twice(inject)
""",
    "a property named _inner hands on to another phone": """
class LeasedPhone:
    @property
    def _inner(self):
        return self._other_phone
    def inject(self, permit):
        return self._inner.inject(permit)
""",
    "a rebound _inner hands the permit to another phone": """
class LeasedPhone:
    def inject(self, permit):
        self._inner = self._other_phone
        return self._inner.inject(permit)
""",
    "an older permit is sent again through getattr": """
class LeasedPhone:
    def inject(self, permit):
        getattr(self._inner, "in" + "ject")(self._last)
        return self._inner.inject(permit)
""",
    "an alias of the bound method sends an older permit again": """
class LeasedPhone:
    def __init__(self, inner):
        self._inner = inner
        self._send = inner.inject
    def inject(self, permit):
        self._send(self._last)
        return self._inner.inject(permit)
""",
    "a class that answers every name sends each call twice": """
class Retrying:
    def __getattr__(self, name):
        method = getattr(self._inner, name)
        def again(*args):
            method(*args)
            return method(*args)
        return again
""",
    "a second def of inject replaces the one that hands on": """
class LeasedPhone:
    def inject(self, permit):
        return self._inner.inject(permit)
    def inject(self, permit):
        send = getattr(self._claim.phone, "in" + "ject")
        send(permit)
        return send(permit)
""",
    "another method points _inner at another phone": """
class LeasedPhone:
    def read(self):
        self._inner = self._other_phone
        return self._inner.read()
    def inject(self, permit):
        return self._inner.inject(permit)
""",
}


def test_rule_catches_planted_calls():
    assert calls("phone.inject(p)", "inject") == 1
    assert calls("Permit(d, 1, a, v, g)", "Permit") == 1
    assert calls("phone.injector(p)", "inject") == 0


@pytest.mark.parametrize(
    "reached",
    [
        "phone.inject(p)",
        "inject(phone, p)",
        "send = phone.inject",
        'getattr(phone, "inject")(p)',
        "class Proxy:\n    def __getattr__(self, name): ...",
        'setattr(Proxy, "__getattribute__", answer)',
    ],
)
def test_rule_counts_every_way_to_reach_a_method_and_not_its_definition(reached):
    assert reaches(reached, "inject") == 1
    assert reaches("class Phone:\n    def inject(self, permit): ...", "inject") == 0
    assert reaches("phone.injector(p)", "inject") == 0


@pytest.mark.parametrize("planted", SECOND_DOORS)
def test_a_wrapper_that_does_more_than_hand_its_permit_on_once_is_a_second_door(planted):
    assert sites("adapters/remote/hub.py", SECOND_DOORS[planted], "inject") >= 1


def test_only_the_phone_that_keeps_a_lease_may_hand_a_permit_on():
    assert sites("adapters/remote/hub.py", LEASED_PHONE, "inject") == 0
    assert sites("adapters/remote/hub.py", LEASED_PHONE + LEASED_PHONE, "inject") == 1
    assert sites("adapters/uiautomator2/phone.py", LEASED_PHONE, "inject") == 1


def test_input_reaches_a_backend_through_one_door():
    for name, owner in ONLY_CALLER.items():
        found = {
            str(path.relative_to(PACKAGE)): sites(str(path.relative_to(PACKAGE)), path.read_text(), name)
            for path in PACKAGE.rglob("*.py")
        }
        found = {path: count for path, count in found.items() if count}
        assert set(found) <= {owner} and sum(found.values()) <= 1, f"{name} is reached from {found}"


def test_every_attrs_string_field_is_a_label_or_declared_not_one():
    from dataclasses import fields

    from agent_phone.core.labels import LABEL_FIELDS, NON_LABEL_FIELDS
    from agent_phone.core.screen import Attrs

    strings = {f.name for f in fields(Attrs) if f.type in ("str", str)}
    assert strings == set(LABEL_FIELDS) | set(NON_LABEL_FIELDS)
