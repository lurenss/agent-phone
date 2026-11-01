---
name: verify-agent-phone
description: Prove a change to agent-phone on a real Android phone over adb, the way an agent uses the CLI, and keep the evidence outside git. Use after a change to devices, snapshots, refs, find, get, is, wait, taps, text, keys, batch, device operations, the commit gate, the on-device server or the lock, before you call the change done, or when asked to verify, smoke-test or reproduce agent-phone behavior on the Samsung J7 or another connected phone.
---

# Verify agent-phone on a real phone

agent-phone is a CLI that reads an Android phone through adb and prints one JSON envelope per command. To prove a change, run this checkout's CLI against a connected phone from a plain shell, read each envelope and a second view of the phone, and keep the record. `features/README.md` lists the features and their journeys. Run every command from the repo root.

Below, `evidence.py` stands for the helper run through the checkout's Python. Define it in each new shell:

```bash
evidence.py() { uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py "$@"; }
```

## Keep the phone safe

The phone runs live accounts. A wrong input can post, send or delete, and that cannot be undone.

- Send only the inputs your task names. Reading is always allowed. That covers agent-phone's read commands (`devices`, `snapshot`, `find`, `get`, `is`, `wait`, `server`, `skills`, `clipboard get` and `screenshot`) and the adb reads that `evidence.py` knows, such as `dumpsys`, `getprop`, `logcat -d` and `screencap`. A tap, text, a key, `am start`, opening an app and every other agent-phone command are inputs.
- Send every input through `evidence.py run --input`, so the record lists it. AGENTS.md requires every app a run opened and every input it sent in `decisions.tsv`. Put the input list from `evidence.py list` there, or in your report when another agent owns that file.
- Never stop, start or change a package that its device profile in `examples/devices/` protects. On the J7 that is SocksTun (`hev.sockstun`). With always-on lockdown VPN, a dead tunnel takes the phone offline. `evidence.py` refuses an input that names a protected package.
- Leave the phone on the screen your task names. On the J7 that is the home screen.

## Launch

agent-phone keeps no process on the computer. The server on the phone starts with the first command that needs it.

1. Run `uv sync`. The CLI is then `.venv/bin/agent-phone`, this checkout's build.
2. Connect the phone over USB. `adb devices` lists it as `device` once the phone accepted USB debugging. Accepting the prompt is a step for the phone's owner.
3. Make a run folder: `RUN=$(evidence.py new <feature>)`.
4. Run Doctor. Set `SERIAL` to the serial on its `device` line, and write down whether its `server` line said `stopped`.
5. Run `evidence.py run "$RUN" server-start -- agent-phone server start`. The phone is ready when `data.running` and `data.watchdog` are both `true`. A cold start takes 2 to 3 s on the J7.

## Doctor

```bash
uv run python -I .claude/skills/verify-agent-phone/scripts/doctor.py | tee "$RUN/doctor-before.txt"
```

Doctor is read-only. Each line is `ok`, `note` or `stop`, then the check. Drive only when no line says `stop`, and run it again whenever a result looks wrong. It checks the checkout and its CLI, one ready device (`--serial` picks one), the device facts, that the screen is awake, the focused window, the server, a foreign `uiautomator` process, and each package that the device's profile protects.

- `stop screen` means the screen is off. Waking it is an input, so ask the phone's owner.
- `stop server` means a uiautomator2 server without a watchdog runs. Another tool owns the phone. Do not run `agent-phone server stop`.
- `note server` means a command used the server in the last minute. If this run did not, another session drives the phone. Wait until it is idle.
- `stop uiautomation` means another tool holds the phone's one UiAutomation connection, so the server cannot start (`A3-13`). Wait for that tool to finish.

## Drive

- Run every command as `evidence.py run "$RUN" <label> -- <command>`. It drops every `AGENT_PHONE_*` variable, so the CLI runs its defaults the way an agent's plain shell does (`docs/solutions/a-probe-that-sets-every-variable-never-runs-the-default.md`). Add `--env NAME=VALUE` only for a journey that sets a variable on purpose.
- Assert on `ok`, `error.code`, `delivery`, `retry` and `data`. Never assert on `message`, whose wording can change.
- Take each ref from an envelope of this run.
- After an input that changes the screen, read with `agent-phone snapshot --settle`, or with `agent-phone wait` for the condition the input should cause. A plain snapshot can show the screen before the change (`A2-10`).
- For a change to reading, drive the journey once with the server cold (stopped first) and once warm. A cold server lists the status bar first (`docs/solutions/two-equal-reads-do-not-prove-the-right-window.md`).
- Check what agent-phone says against a read it did not make, such as `adb shell dumpsys window` for the focused window.
- Drive one phone from one run at a time. Each command takes the device lock, but two runs still change the screen under each other.

## Evidence

- The run folder is `~/.agent-phone/verify/<UTC time>-<feature>/`, under the state root and outside git on purpose. Envelopes and screenshots hold what the screen showed, which can be private. Never commit them or paste them whole into a PR. Quote the codes, counts and lines that a claim needs.
- `evidence.py run` writes `<label>.json`: the command, the extra variables, whether it was an input, the start time, the wall time in ms, the exit code, the stdout size, the parsed envelope and stderr. It refuses a label that exists, so it never overwrites a record.
- Record the input and the state after it: the `--input` record, then the settled snapshot that shows its effect.
- A screenshot is evidence for a human: `evidence.py run "$RUN" wifi-shot --out wifi.png -- adb -s "$SERIAL" exec-out screencap -p`. It takes about 1.3 s on the J7 (`A1-4`), so never take one inside a timed step.
- Exercise the real path: this checkout's CLI, the real phone and a plain environment. A fixture test is not a device proof. When a journey cannot run, report it as skipped with the reason, never as verified.

## Cleanup

1. If Doctor said `stopped` before the run, stop the server: `evidence.py run "$RUN" server-stop -- agent-phone server stop`. Then `data.running` and `data.watchdog` are `false`. Leave a server that already ran with its watchdog. It stops itself when idle.
2. Kill only processes this run started, by the pid they printed, such as `kill <pid>` for `hold_lock.py`. Never kill by name, on the computer or on the phone.
3. Return the phone to the screen your task names. On the J7: `evidence.py run "$RUN" home --input -- adb -s "$SERIAL" shell input keyevent KEYCODE_HOME`.
4. Run Doctor again into `"$RUN/doctor-after.txt"`, and compare the server line and the protected packages with `doctor-before.txt`.
5. Keep the run folder. Run `evidence.py list "$RUN"` to confirm that every record survived and to print the inputs.

## Helpers

The scripts in `scripts/` import this checkout's `agent_phone`, so run them with `uv run python -I` from the repo root.

- `evidence.py new <feature>` makes a run folder, mode 700, and prints its path.
- `evidence.py run <run> <label> [--input] [--env NAME=VALUE]... [--out FILE] [--timeout S] -- <command>...` runs one command, prints its stdout, writes the record and exits with the command's exit code. `agent-phone` and `python` mean this checkout's. Without `--input` it runs only agent-phone's read commands, known adb reads and `probes/android/raw_dump.py`, and it refuses the rest. `logcat` is a known read with `-d` and without `-c`, `-G` or `-b all`, and every other `python` needs `--input`. `--out` saves stdout to a file in the run folder, for binary output such as a screenshot.
- `evidence.py list <run>` prints each record in time order, then every input.
- `doctor.py [--serial SERIAL]` is the check above. It exits 1 when a line says `stop`.
- `hold_lock.py` holds the device lock like a second agent-phone process, until it gets SIGTERM. Start it in the background, and it prints `held <serial> <pid>` once it holds the lock. `features/server-lifetime.md` uses it.
