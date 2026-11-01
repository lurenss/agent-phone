# agent-phone verification map

This folder is the maintained source for verifying what agent-phone does for an agent that calls it. Read this index before you drive the phone, then use the matching feature file as the recipe. `evidence.py` is the shell function that `../SKILL.md` defines, run from the repo root.

## Baseline preconditions

- Run `uv sync` in this checkout. `evidence.py` runs `.venv/bin/agent-phone`.
- Connect one phone over USB with USB debugging accepted. Write its serial as `$SERIAL`.
- Make a run folder with `RUN=$(evidence.py new <feature>)`.
- Run `doctor.py` into `$RUN/doctor-before.txt` and require no `stop` line.
- Check that your task allows every input a journey lists under its preconditions. A journey whose inputs your task does not allow is skipped, not weakened.
- Never drive a phone that another run or another tool is driving.

## Driving conventions

- Start each journey from the state its preconditions name.
- Run every command through `evidence.py run "$RUN" <label> -- <command>`, and every input with `--input`.
- Treat every command as literal. Keep the flags and the quoted words unchanged.
- Take refs from an envelope of this run, as printed, such as `@k3x9q:e4`.
- Read with `agent-phone snapshot --settle` after any input that changes the screen.
- Wait for a phone condition with a bounded loop that polls a read. Never wait with a fixed sleep and then assume.

## Proof and skip reporting

- Proof for a command is its record in `$RUN`: the command, the exit code, the envelope and stderr.
- Pair each input with the settled read that shows its effect.
- Check agent-phone's answer against a second read that it did not make, where the journey names one.
- Name the feature id and the record labels with every claim.
- Report a journey that cannot run with the command you tried and the precondition that failed.
- Never report a skipped journey as verified through another path. A fixture test is not a device proof.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph that says what the feature does for the agent that calls it. Then come exactly four H2 sections, in this order.

1. `Sub-features` lists short ids, one line for each behavior.
2. `How to get to it (user POV)` lists every entry point a caller has.
3. `Driving it with evidence.py` starts with `Preconditions:` and pairs each step with an exact command and its observable result.
4. `Gotchas` lists the traps that can waste or invalidate a run.

Keep implementation details out of the map. Name only entry points, commands, the state a journey needs, and what proves it.

## Features

- [Devices and device selection](./devices.md) covers `devices`, the default device, `-d`, refs that name their device, and the refusals.
- [Snapshot modes and surfaces](./snapshot-modes.md) covers compact, skeleton, drill-down, full, settle, and the window flags.
- [Find, get and is](./find-get-is.md) covers queries, live property reads, and the ref refusals.
- [Server lifetime and the device lock](./server-lifetime.md) covers start, status, stop, the idle stop, freeing the phone, and the lock.
- [Taps, text, scrolls and keys](./ref-actions.md) covers `click`, `set-text`, `scroll`, `press`, spent refs and `OBSERVE_FIRST`.
- [Device operations](./device-operations.md) covers `launch`, `stop`, `open-url`, `rotate`, `clipboard` and `screenshot`.
- [The commit gate and device protections](./policy-gate.md) covers `COMMIT_REFUSED`, `DENIED`, grants and protected packages.
