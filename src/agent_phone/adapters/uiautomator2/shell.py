"""Device facts and device-level operations that go through `adb shell`, not the server.

Facts come from one shell round trip per process. The shell starts each read as a background
job and waits, which takes 116 ms against 225 ms in sequence (A3-7). Output lines are matched
by what they say, and a fact that does not parse is a Refusal(TRANSPORT) naming it, never a
default. `wm size` and `wm density` print an override line when one is set, and it wins.
"""

from __future__ import annotations

import re
import shlex

from agent_phone.adapters.uiautomator2.adb import Adb, first_line, shell
from agent_phone.adapters.uiautomator2.delivery import classify_shell
from agent_phone.core.device import BootId, DeviceIdentity, DeviceInfo, DeviceState, Package, Serial
from agent_phone.core.geometry import Size
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import Delivery, Launch, OpenUri, Orientation, Rotate, Stop, intent_of

PROPERTIES = (
    "ro.build.version.sdk",
    "ro.product.cpu.abi",
    "ro.product.model",
    "persist.sys.locale",
    "ro.product.locale",
)
FACTS_TIMEOUT_S = 10.0
FACTS_SCRIPT = (
    '(getprop | grep -E "^\\[({})\\]") & '.format("|".join(re.escape(name) for name in PROPERTIES))
    + '(echo "boot=$(cat /proc/sys/kernel/random/boot_id)") & '
    + '(echo "size=$(wm size)") & (echo "density=$(wm density)") & '
    + '(echo "ime=$(settings get secure default_input_method)") & wait'
)


def facts_script(also: str = "") -> str:
    """`also` runs beside the reads in the same round trip and its output is ignored."""
    return FACTS_SCRIPT if not also else FACTS_SCRIPT.removesuffix("wait") + f"({also}) & wait"


PROPERTY_LINE = re.compile(r"\[([^\]]+)\]: \[(.*)\]")
SIZE_LINE = re.compile(r"(Physical|Override) size: (\d+)x(\d+)")
DENSITY_LINE = re.compile(r"(Physical|Override) density: (\d+)")


def parse_facts(serial: Serial, output: str) -> DeviceInfo:
    """Raise `Refusal(TRANSPORT)` naming the first fact the output does not carry."""
    properties = {m[1]: m[2] for line in output.splitlines() if (m := PROPERTY_LINE.fullmatch(line.strip()))}

    def missing(fact: str) -> Refusal:
        return Refusal(ErrorCode.TRANSPORT, f"Device {serial} did not report its {fact}.", {"fact": fact})

    def prop(name: str, fact: str) -> str:
        if not properties.get(name):
            raise missing(fact)
        return properties[name]

    try:
        api_level = int(prop("ro.build.version.sdk", "API level"))
    except ValueError as error:
        raise missing("API level") from error
    locale = properties.get("persist.sys.locale") or prop("ro.product.locale", "locale")
    sizes = {m[1]: Size(int(m[2]), int(m[3])) for m in SIZE_LINE.finditer(output)}
    densities = {m[1]: int(m[2]) for m in DENSITY_LINE.finditer(output)}
    display = sizes.get("Override") or sizes.get("Physical")
    density = densities.get("Override") or densities.get("Physical")
    boot = next(
        (line.removeprefix("boot=").strip() for line in output.splitlines() if line.startswith("boot=")), ""
    )
    ime = next(
        (line.removeprefix("ime=").strip() for line in output.splitlines() if line.startswith("ime=")), None
    )
    if display is None:
        raise missing("display size")
    if density is None:
        raise missing("display density")
    if not boot:
        raise missing("boot id")
    if ime is None:
        raise missing("default keyboard")
    return DeviceInfo(
        identity=DeviceIdentity(serial, BootId(boot)),
        model=prop("ro.product.model", "model"),
        api_level=api_level,
        abi=prop("ro.product.cpu.abi", "ABI"),
        display=display,
        density_dpi=density,
        locale=locale.replace("_", "-"),
        default_ime=None if ime in ("", "null") else Package(ime.partition("/")[0]),
        capabilities=frozenset(),
    )


class Shell:
    def __init__(self, serial: Serial, adb: Adb) -> None:
        self._serial = serial
        self._adb = adb

    def facts(self, also: str = "") -> DeviceInfo:
        result = shell(self._adb, self._serial, facts_script(also), FACTS_TIMEOUT_S)
        if result.status != 0:
            reason = first_line(result.stderr) or first_line(result.stdout) or f"exit status {result.status}"
            raise Refusal(ErrorCode.TRANSPORT, f"adb could not read the facts of {self._serial}: {reason}.")
        return parse_facts(self._serial, result.stdout)

    def state(self) -> DeviceState:
        """`dumpsys power` for power, `dumpsys window` for keyguard; Lock.UNKNOWN when the
        format of this Android version is not recognised."""
        raise NotImplementedError

    def run(self, action: Launch | Stop | OpenUri | Rotate) -> Delivery:
        """One `adb shell` call. Each argument is quoted for the phone's shell, so a package or a
        link reaches its command as one word and never as shell syntax."""
        script = " && ".join(shlex.join(argv) for argv in commands_for(action))
        try:
            result = shell(self._adb, self._serial, script, ACTION_TIMEOUT_S)
        except Refusal:
            return classify_shell(None, written=True)
        return classify_shell(result.status, True, result.stdout + result.stderr)


ACTION_TIMEOUT_S = 15.0
ROTATION = {Orientation.PORTRAIT: "0", Orientation.LANDSCAPE: "1"}


def commands_for(action: Launch | Stop | OpenUri | Rotate) -> tuple[tuple[str, ...], ...]:
    match action:
        case Launch(package=package):
            return (("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"),)
        case Stop(package=package):
            return (("am", "force-stop", package),)
        case OpenUri() as link:
            intent = intent_of(link)
            package = intent[1] if intent else link.package
            start = (
                ("am", "start", "-a", intent[0]) if intent else ("am", "start", "-a", VIEW, "-d", link.uri)
            )
            return (start + (("-p", package) if package else ()),)
        case Rotate(orientation=Orientation.AUTO):
            return (("settings", "put", "system", "accelerometer_rotation", "1"),)
        case Rotate(orientation=orientation):
            return (
                ("settings", "put", "system", "accelerometer_rotation", "0"),
                ("settings", "put", "system", "user_rotation", ROTATION[orientation]),
            )


VIEW = "android.intent.action.VIEW"
