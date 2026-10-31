"""The uiautomator2 server's lifetime on the phone: push the jar, start it detached, wait for
its health check, stop it, and stop it again on its own when nobody uses it.

Android allows one UiAutomation client per device (A3-4), and a running server keeps
accessibility on (A3-11), so it must not outlive its use. The idle limit lives on the phone:
a watchdog shell kills the server when `ap-lastuse` is older than the limit, so it works while
the computer sleeps or the cable is pulled (A3-8). Clients touch that file at most every
`touch_interval` seconds, from inside a shell call they make anyway.

Every on-device pattern is written with a bracket, as `uia2[.]Main`, because a plain pattern
matches the calling shell (A3-9). For the same reason no script spells `uia2.Main` or
`ap-watchdog` whole: `pgrep -f` reads the script's own command line too.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from agent_phone.adapters.uiautomator2.adb import Adb, first_line, shell
from agent_phone.adapters.uiautomator2.rpc import JsonRpc
from agent_phone.core.device import Serial
from agent_phone.core.outcome import ErrorCode, Refusal
from agent_phone.core.phone import ServerStatus
from agent_phone.core.wait.clock import Clock
from agent_phone.core.wait.until import until

SERVER_PORT = 9008
DEVICE_JAR = "/data/local/tmp/u2.jar"
LASTUSE = "/data/local/tmp/ap-lastuse"
START_DEADLINE_S = 20.0
STOP_DEADLINE_S = 5.0
PUSH_TIMEOUT_S = 60.0
PING_GAP_S = 0.1
PING_TIMEOUT_S = 2.0
EXIT_CHECK_POLLS = 10
SIGNATURES = "pgrep -f 'uia2[.]Main'"
WATCHERS = "pgrep -f 'ap-watchdo[g]'"
KILL_WATCHERS = f"for p in $({WATCHERS}); do kill -9 $p; done"

WATCHDOG = f"""srv=$1; limit=$2; f={LASTUSE}
while grep -q "uia2[.]Main" /proc/$srv/cmdline 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -c %Y $f 2>/dev/null || echo 0) ))
  if [ $age -ge $limit ]; then kill $srv; break; fi
  left=$((limit - age)); [ $left -gt 10 ] && left=10
  sleep $left
done"""


def start_script(idle_limit_s: int) -> str:
    """Idempotent: leaves one server and one watchdog bound to it, however many are there now.
    It always replaces the watchdog, because an old one may be about to exit with its server."""
    return f"""f={LASTUSE}
{KILL_WATCHERS}
touch $f
srv=$({SIGNATURES} | head -n 1)
if [ -z "$srv" ]; then
  cls=com.wetest.uia2
  CLASSPATH={DEVICE_JAR} nohup app_process / $cls.Main -p {SERVER_PORT} </dev/null >/dev/null 2>&1 &
  srv=$!
fi
name=ap-watchdo
nohup sh -c '{WATCHDOG}' ${{name}}g $srv {idle_limit_s} </dev/null >/dev/null 2>&1 &"""


STOP_SCRIPT = f"""{KILL_WATCHERS}
pkill -f 'uia2[.]Main'
rm -f {LASTUSE}"""

KILL_SERVER_SCRIPT = f"for p in $({SIGNATURES}); do kill -9 $p; done"

STATUS_SCRIPT = f"""echo "server=$({SIGNATURES} | head -n 1)"
wd=$({WATCHERS} | head -n 1)
echo "watchdog=$wd"
[ -n "$wd" ] && echo "limit=$(tr '\\0' '\\n' < /proc/$wd/cmdline | tail -n 1)"
echo "now=$(date +%s)"
echo "last=$(stat -c %Y {LASTUSE} 2>/dev/null)"
"""


def touch_script(every_s: int) -> str:
    """Touch the last-use file unless it is newer than `every_s` seconds."""
    return (
        f"f={LASTUSE}; n=$(date +%s); l=$(stat -c %Y $f 2>/dev/null || echo 0); "
        f"[ $((n - l)) -ge {every_s} ] && touch $f"
    )


def touch_interval(idle_limit_s: int) -> int:
    """Once a minute, or a quarter of a short limit, so a short limit in a test still works."""
    return min(60, max(1, idle_limit_s // 4))


def parse_status(output: str) -> ServerStatus:
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    running = bool(values.get("server", "").strip())
    limit = values.get("limit", "").strip()
    now, last = values.get("now", "").strip(), values.get("last", "").strip()
    return ServerStatus(
        running=running,
        watchdog=bool(values.get("watchdog", "").strip()),
        idle_limit_s=int(limit) if limit.isdigit() else None,
        idle_for_s=max(0, int(now) - int(last)) if running and now.isdigit() and last.isdigit() else None,
    )


def bundled_jar() -> Path:
    """The jar that ships inside the uiautomator2 package. `find_spec` locates the package
    without importing it, so no uiautomator2 code runs (A2-6)."""
    spec = importlib.util.find_spec("uiautomator2")
    if spec is None or not spec.submodule_search_locations:
        raise Refusal(ErrorCode.INTERNAL, "The uiautomator2 package that carries u2.jar is not installed.")
    jar = Path(next(iter(spec.submodule_search_locations))) / "assets" / "u2.jar"
    if not jar.is_file():
        raise Refusal(ErrorCode.INTERNAL, f"The bundled server jar {jar} is missing.")
    return jar


class Pinger(Protocol):
    def ping(self, timeout_s: float = 1.0) -> bool: ...


class Forward:
    """An adb port forward from a free host port to the server's port. Each process takes its
    own, so two devices never share one and a stale forward never points at the wrong phone."""

    def __init__(self, adb: Adb, serial: Serial, port: int) -> None:
        self._adb = adb
        self._serial = serial
        self.port = port

    @staticmethod
    def open(adb: Adb, serial: Serial) -> Forward:
        result = adb.run(("-s", serial, "forward", "tcp:0", f"tcp:{SERVER_PORT}"))
        line = first_line(result.stdout)
        if result.status != 0 or not line.isdigit():
            reason = first_line(result.stderr) or line or f"exit status {result.status}"
            raise Refusal(ErrorCode.TRANSPORT, f"adb could not forward a port to {serial}: {reason}.")
        return Forward(adb, serial, int(line))

    def close(self) -> None:
        """Best effort. A forward that stays behind is harmless, and `server stop` removes it."""
        with suppress(Refusal):
            self._adb.run(("-s", self._serial, "forward", "--remove", f"tcp:{self.port}"))


class Server:
    """`BackendServer` for the uiautomator2 server of one device."""

    def __init__(
        self,
        serial: Serial,
        adb: Adb,
        idle_limit_s: int,
        clock: Clock,
        jar: Path | None = None,
        rpc_for: Callable[[int], Pinger] = lambda port: JsonRpc(port, PING_TIMEOUT_S),
    ) -> None:
        self._serial = serial
        self._adb = adb
        self._idle_limit_s = idle_limit_s
        self._clock = clock
        self._jar = jar
        self._rpc_for = rpc_for

    def status(self) -> ServerStatus:
        return parse_status(self._shell(STATUS_SCRIPT, "read the server's status"))

    def start(self) -> ServerStatus:
        forward = Forward.open(self._adb, self._serial)
        try:
            self.ensure(self._rpc_for(forward.port), repair_watchdog=True)
            self._shell(touch_script(0), "count this use")
        finally:
            forward.close()
        return self.status()

    def stop(self) -> ServerStatus:
        self._shell(STOP_SCRIPT, "stop the server")
        if not self._gone(STOP_DEADLINE_S):
            self._shell(KILL_SERVER_SCRIPT, "kill the server")
            if not self._gone(STOP_DEADLINE_S):
                raise Refusal(ErrorCode.SERVER_UNAVAILABLE, f"The server on {self._serial} did not stop.")
        self._drop_forwards()
        return self.status()

    def _gone(self, timeout_s: float) -> bool:
        return until(self._clock, lambda: (not self.status().running) or None, timeout_s) is not None

    def touch(self) -> None:
        self._adb.run(("-s", self._serial, "shell", touch_script(touch_interval(self._idle_limit_s))))

    def ensure(self, rpc: Pinger, repair_watchdog: bool = False) -> None:
        """Leave a server answering on `rpc`. Nothing happens when one already answers, unless
        `repair_watchdog` finds it running without its watchdog."""
        if rpc.ping() or rpc.ping():
            if not repair_watchdog or self.status().watchdog:
                return
        elif self.status().running:
            self.stop()
        self._push_jar()
        self._shell(start_script(self._idle_limit_s), "start the server")
        if self._answers(rpc) is not True:
            raise self._silent()

    def _silent(self) -> Refusal:
        if self.status().running:
            return Refusal(
                ErrorCode.SERVER_UNAVAILABLE,
                f"The server on {self._serial} did not answer within {START_DEADLINE_S:g} s of its start. "
                "Its process is running but does not answer.",
            )
        return Refusal(
            ErrorCode.SERVER_UNAVAILABLE,
            f"The server on {self._serial} exited as it started. "
            "Another UiAutomation client may hold the device (A3-4).",
        )

    def _answers(self, rpc: Pinger) -> bool | None:
        """True once `rpc` answers. None at the deadline, or when the server process is gone,
        which a check every `EXIT_CHECK_POLLS` polls notices long before the deadline."""
        polls = 0

        def attempt() -> bool | None:
            nonlocal polls
            if rpc.ping():
                return True
            polls += 1
            if polls % EXIT_CHECK_POLLS == 0 and not self.status().running:
                return False
            return None

        return until(self._clock, attempt, START_DEADLINE_S, PING_GAP_S)

    def _push_jar(self) -> None:
        jar = self._jar or bundled_jar()
        local = hashlib.sha1(jar.read_bytes()).hexdigest()
        there = self._shell(f"sha1sum {DEVICE_JAR} 2>/dev/null || true", "check the server jar").split()
        if there and there[0] == local:
            return
        pushed = self._adb.run(("-s", self._serial, "push", str(jar), DEVICE_JAR), PUSH_TIMEOUT_S)
        if pushed.status != 0:
            raise Refusal(
                ErrorCode.TRANSPORT,
                f"adb could not push the server jar to {self._serial}: {first_line(pushed.stderr)}.",
            )

    def _drop_forwards(self) -> None:
        """Remove forwards that a killed process of this device left behind."""
        listing = self._adb.run(("forward", "--list")).stdout.splitlines()
        for line in listing:
            fields = line.split()
            if len(fields) == 3 and fields[0] == self._serial and fields[2] == f"tcp:{SERVER_PORT}":
                self._adb.run(("-s", self._serial, "forward", "--remove", fields[1]))

    def _shell(self, script: str, doing: str) -> str:
        result = shell(self._adb, self._serial, script)
        if result.status != 0 and not result.stdout:
            reason = first_line(result.stderr) or f"exit status {result.status}"
            raise Refusal(ErrorCode.TRANSPORT, f"adb could not {doing} on {self._serial}: {reason}.")
        return result.stdout
