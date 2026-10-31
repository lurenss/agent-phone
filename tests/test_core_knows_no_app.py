import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "agent_phone"
APP_PACKAGE = re.compile(r"\b(?:com|org|net|io|me|tv|app)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*\b")
APP_FREE = ("core", "cli")


def app_packages_in_python(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.extend(APP_PACKAGE.findall(node.value))
    return found


def test_check_catches_a_planted_package_name():
    assert app_packages_in_python('PROTECTED = "com.example.vpn"') == ["com.example.vpn"]
    assert app_packages_in_python('"""Docs may say com.example.app too."""') == ["com.example.app"]
    assert app_packages_in_python('MODULE = "agent_phone.core.refs"') == []


def test_core_and_cli_name_no_app_package():
    files = [path for layer in APP_FREE for path in sorted((PACKAGE / layer).rglob("*.py"))]
    assert files
    for path in files:
        assert app_packages_in_python(path.read_text()) == [], path.relative_to(PACKAGE)


def test_default_policy_names_no_app_package():
    assert APP_PACKAGE.findall((PACKAGE / "policy" / "default.toml").read_text()) == []
