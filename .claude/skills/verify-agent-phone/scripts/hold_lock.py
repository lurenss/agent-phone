#!/usr/bin/env python3
"""Hold the device lock the way a second agent-phone process does, until this process gets
SIGTERM or SIGINT. Run it from the repo root, in the background:

    uv run python -I .claude/skills/verify-agent-phone/scripts/hold_lock.py > "$RUN/holder.txt" &

It prints `held <serial> <pid>` once it holds the lock. Stop it with `kill <pid>`. It opens the
phone the way a command does, so it starts the server when none runs. It sends no input.
"""

import os
import signal
import sys

from agent_phone.cli.driver import PhoneError, open_phone


def main() -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    for name in [k for k in os.environ if k.startswith("AGENT_PHONE_")]:
        del os.environ[name]
    try:
        with open_phone() as phone:
            print(f"held {phone.serial} {os.getpid()}", flush=True)
            signal.pause()
    except PhoneError as error:
        print(f"not held: {error.outcome}", flush=True)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
