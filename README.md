# agent-phone

agent-phone lets an AI agent see and operate an Android phone through its accessibility tree, over adb. It applies the design of [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop) to a phone: a snapshot returns compact JSON with a ref for every element the agent can act on, the agent acts on a ref, and it snapshots again to check. The loop stays in the agent.

It is in development. It is built for any app on any Android phone. App knowledge lives in policy data and examples, never in core. `docs/plan.md` lists the units and the check each one must pass.

## Why it is built this way

Measured on a Samsung J7 (Android 9), reading the screen with `adb shell uiautomator dump` takes about 2.4 seconds and fails while a screen animates. The same read through a uiautomator2 server that stays running takes about 160 ms. Sending a key takes 902 ms through `adb shell input` and 34 ms through the server. The rows behind these numbers are in `probes/android/FINDINGS.md`.

## Use

```bash
agent-phone devices            # every device, with its facts
agent-phone snapshot           # the active window as compact lines with refs
agent-phone server stop        # free the phone for another tool, such as an old uiautomator dump
```

Each command prints one JSON object, described in `docs/json-output.md`. `-d <serial>` picks a device when several are ready. The server on the phone starts when a command needs it and stops after 15 idle minutes. Input commands, `--settle` and `--root` are not built yet. `AGENT_PHONE_HOME`, `AGENT_PHONE_IDLE_S`, `AGENT_PHONE_LOCK_WAIT_S` and `ADB` configure the state folder, the idle limit, how long a command waits for another process to let go of the device, and the adb binary.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check .
```

`AGENTS.md` has the architecture rules, the coding standards and the phone safety rules.
