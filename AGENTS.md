# Agent Phone instructions

Use pstack to design, change, and verify Agent Phone. Write documentation, examples, code comments, CLI messages, and tests in English. See the [README](README.md) for setup and a complete example.

## Control an Android device

1. Set `AGENT_PHONE_OWNER` to a stable label for this agent or session. Run `devices` and select the requested device by serial number.
2. Reserve an available device with `lease SERIAL --why TASK`. Give a reason for each read or action with `--why`. The limit is 80 characters for a lease and 200 for other commands.
3. Use `state` to check the foreground app, screen, and keyboard. Use `snapshot` to read each control’s text, description, ID, coordinates, and focus state.
4. Choose an action that serves the user’s request, including when a control sends, publishes, or deletes content. Send the input once. Read the screen again or use `wait` to verify its effect.
5. Release the device with `release SERIAL` when you finish or the task stops early.

## Select a control

- `find` and `tap` accept an exact label or `--id ID`. When several controls share a label, use an ID from the screen. The CLI reports `not_found` for zero matches and `ambiguous` for multiple matches. Read the screen again in either case.
- `set-text SERIAL TEXT --id ID` replaces the contents of a field. Without an ID, it uses the focused text field. For text that starts with a dash, put the options first, then `--`, then the text.
- `wait` waits up to ten seconds for at least one control with the given text or ID. After a search, for example, wait for a label on the results screen.
- If a custom control is missing from `snapshot`, save a JPEG with `screenshot SERIAL FILE.jpg`. Use the current image to choose coordinates for `tap SERIAL X Y` or `swipe SERIAL X1 Y1 X2 Y2`.

The CLI writes JSON results to stdout and errors to stderr. Exit code 0 means the command received a successful response. If a tap or text input loses its response, check the device before deciding what to do next.

## Connections and leases

The CLI looks for `adb` on PATH or at `~/Library/Android/sdk/platform-tools/adb`. It connects to the local ADB server at `127.0.0.1:5037`. On first use, `uv` sets up the Python dependencies. If a USB phone appears as `unauthorized`, unlock it and accept the USB debugging prompt. Select a serial number whose state is `device`.

UIAutomator2 reads the screen hierarchy, taps controls by label or ID, and fills in text fields. ADB opens apps, takes screenshots, taps coordinates, swipes, and sends key events. A command stops any UIAutomator2 service it started before it exits. Include that startup time when measuring local command latency.

Redis defaults to `redis://127.0.0.1:6379/0`. Set `AGENT_PHONE_REDIS_URL` to override it. Use the same Redis database for every operator on this Mac. Keys are scoped to the hostname. Configure Redis persistence if routine definitions and history need to survive a server restart.

A lease lasts ten minutes. Only its owner can renew, act, or release it. The identity combines the macOS account with the optional `AGENT_PHONE_OWNER` label. Labels distinguish trusted local sessions. Any process under that account can choose the same label. Existing file leases are imported with their original expiry and the account as owner. Stop older versions of the CLI before upgrading.

`devices` refreshes discovery on demand. Active means ADB reports `device`. Busy means active with a live lease. Offline, unauthorized, and previously seen disconnected devices remain in the inventory. `lastSeen`, `since`, and `until` are Unix seconds. Other ADB clients can still act outside Agent Phone.

## Run and audit routines

- Save 1 to 100 steps as a JSON array. Each step is an array of strings beginning with a device command. Use `open`, `key`, `tap`, `swipe`, `set-text`, `wait`, `find`, `snapshot`, or `state`. Supply the device and reason at run time. Use `screenshot` directly when choosing a host file.
- `routine save NAME FILE.json` validates every step before replacing the stored definition. `routine list` lists names. `routine show NAME` returns the original steps. Routine files and their text arguments are stored in Redis.
- Acquire a lease, then run `routine run NAME SERIAL --why TASK`. A run uses one snapshot of the definition and holds the device operation lock across its steps. It renews the owner's lease before each step. Release the lease after the run. Different devices can run independently.
- A failed run reports its ID, the one-based failed step, and how many earlier steps completed. Inspect the screen and history before repeating any input.
- `history SERIAL` returns up to 100 events, newest first, from the most recent 2,000 events for that device. Each attempted action records a start and an outcome. Use `actionId` to pair events and `runId` and `step` to trace a routine. A start without an outcome means delivery is uncertain. Records include the supplied reason, but omit field contents and screen dumps.

## Change the CLI

- Keep command syntax, validation, and `--help` in [src/cli.ts](src/cli.ts).
- Pass arguments to the Android driver as an array. Implement device operations in [src/local.py](src/local.py) and Redis state in [src/store.py](src/store.py).
- Run `bun install --frozen-lockfile` to set up development dependencies. Run `bun run check` before committing. The [CLI tests](tests/cli.test.ts) use simulated clients. The [management tests](tests/test_management.py) start a temporary Redis server and simulate ADB. Neither suite needs a phone or credentials.
