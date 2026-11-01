import subprocess
from pathlib import Path

import pytest

from agent_phone.adapters.uiautomator2.shell import facts_script, parse_facts
from agent_phone.core.device import Package, Serial
from agent_phone.core.geometry import Size

EMULATOR = Serial("emulator-5554")
STUBS = {
    "getprop": """echo "[ro.build.id]: [AP1A.240405.002]"
echo "[ro.build.version.sdk]: [35]"
echo "[ro.product.cpu.abi]: [arm64-v8a]"
echo "[ro.product.locale]: [en-US]"
echo "[ro.product.model]: [sdk_gphone64_arm64]"
echo "[persist.sys.locale]: [de-DE]"
echo "[sys.boot_completed]: [1]"
""",
    "wm": """if [ "$1" = size ]; then
  echo "Physical size: 1080x2400"
  echo "Override size: 720x1280"
else
  echo "Physical density: 420"
fi
""",
    "settings": "echo com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME\n",
    "cat": "echo c1becccb-50a7-42f3-812b-85f12b78f1bc\n",
}


@pytest.fixture
def phone_commands(tmp_path: Path) -> dict[str, str]:
    """A PATH whose `getprop`, `wm`, `settings` and `cat` answer as the emulator did, so the script
    runs in a local shell and no phone is reached."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}")
        stub.chmod(0o755)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin"}


def run_script(script: str, env: dict[str, str]) -> str:
    done = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_what_the_script_prints_is_read_back_whole(phone_commands):
    info = parse_facts(EMULATOR, run_script(facts_script(), phone_commands))
    assert (info.api_level, info.abi, info.model) == (35, "arm64-v8a", "sdk_gphone64_arm64")
    assert (info.display, info.density_dpi, info.locale) == (Size(720, 1280), 420, "de-DE")
    assert info.default_ime == Package("com.google.android.inputmethod.latin")


def test_the_extra_job_runs_beside_the_reads(phone_commands, tmp_path):
    marker = tmp_path / "touched"
    output = run_script(facts_script(f"touch {marker}"), phone_commands)
    assert marker.exists()
    assert parse_facts(EMULATOR, output).locale == "de-DE"
