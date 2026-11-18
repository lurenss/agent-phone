# Agent Phone instructions

Use pstack to design, change, and verify Agent Phone. Write documentation, examples, code comments, CLI messages, and tests in English. See the [README](README.md) for setup and a complete example.

## Control an Android device

1. Run `devices` and select the requested device by serial number. The CLI uses the Raspberry Pi by default. For a USB phone or emulator on the Mac, include `--local` in every command.
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

**Raspberry Pi.** Agent Phone runs `wp.py` from the `driving-phones-via-walkie-api` skill. The client handles the SSH tunnel, token, lease, and action log. Set `AGENT_PHONE_WP` to the path of another copy of `wp.py` if needed. Walkie-porkie reuses the UIAutomator2 service on the phone between commands. Before a tap by label or ID, or a text input by ID, the CLI checks for a single match. The Pi reads the control again when it acts. The screen can change between those reads.

**Mac.** The CLI looks for `adb` on PATH or at `~/Library/Android/sdk/platform-tools/adb`. It connects to the local ADB server at `127.0.0.1:5037`. On first use, `uv` sets up the Python dependencies. If a USB phone appears as `unauthorized`, unlock it and accept the USB debugging prompt. Select a serial number whose state is `device`.

UIAutomator2 reads the screen hierarchy, taps controls by label or ID, and fills in text fields. ADB opens apps, takes screenshots, taps coordinates, swipes, and sends key events. A command stops any UIAutomator2 service it started before it exits. Include that startup time when measuring local command latency.

A local lease lasts ten minutes. Run `lease` again to renew it. Agent Phone processes running as the same macOS user share the lease and run one command at a time per device. Other ADB clients can still interact with that device.

## Change the CLI

- Keep command syntax, validation, and `--help` in [src/cli.ts](src/cli.ts).
- Select the client in [src/transport.ts](src/transport.ts). Pass arguments as an array. Implement local Android operations in [src/local.py](src/local.py).
- Run `bun install --frozen-lockfile` to set up development dependencies. Run `bun run check` before committing. The [CLI tests](tests/cli.test.ts) use simulated clients and run independently of real phones, credentials, and accounts.
