import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "agent_phone"
MAX_LINES = 400

FORBIDDEN = {
    "core": ("agent_phone.adapters", "agent_phone.cli", "uiautomator2", "adbutils", "subprocess"),
    "adapters": ("agent_phone.cli",),
}


def imported_modules(source: str) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def violations(source: str, forbidden: tuple[str, ...]) -> list[str]:
    return [
        name
        for name in imported_modules(source)
        if any(name == banned or name.startswith(banned + ".") for banned in forbidden)
    ]


def sources(layer: str) -> list[Path]:
    return sorted((PACKAGE / layer).rglob("*.py"))


def test_rule_catches_planted_violations():
    assert violations("import uiautomator2", FORBIDDEN["core"]) == ["uiautomator2"]
    planted = "from agent_phone.adapters.u2 import x"
    assert violations(planted, FORBIDDEN["core"]) == ["agent_phone.adapters.u2"]
    assert violations("import subprocess", FORBIDDEN["core"]) == ["subprocess"]
    assert violations("from agent_phone.cli import main", FORBIDDEN["adapters"]) == ["agent_phone.cli"]
    assert violations("import uiautomator2_extra", FORBIDDEN["core"]) == []
    assert violations("from agent_phone.core import snapshot", FORBIDDEN["adapters"]) == []


def test_each_layer_imports_only_what_it_may():
    for layer, forbidden in FORBIDDEN.items():
        files = sources(layer)
        assert files, f"no source files found under {layer}/"
        for path in files:
            found = violations(path.read_text(), forbidden)
            assert not found, f"{path.relative_to(PACKAGE)} imports {found}"


def test_source_files_stay_under_the_size_cap():
    for path in sorted(PACKAGE.rglob("*.py")):
        lines = len(path.read_text().splitlines())
        assert lines <= MAX_LINES, f"{path.relative_to(PACKAGE)} has {lines} lines, split it"
