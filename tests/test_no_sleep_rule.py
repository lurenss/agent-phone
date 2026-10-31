import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "lint"


def banned_sleeps(path: Path) -> int:
    out = subprocess.run(
        ["ruff", "check", "--no-cache", "--select", "TID251", "--output-format", "concise", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return out.stdout.count("TID251")


def test_every_form_of_sleep_is_rejected():
    for name in ("sleep_module_call.py", "sleep_imported.py", "sleep_aliased.py"):
        assert banned_sleeps(FIXTURES / name) == 1, name


def test_other_time_calls_pass():
    assert banned_sleeps(FIXTURES / "no_sleep.py") == 0
