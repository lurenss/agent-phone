# Agent Phone

Agent Phone is a TypeScript CLI that lets a coding agent control Android one step at a time. It uses UIAutomator2 to read text and controls on the screen. The agent can open an app, tap a button, fill in a field, and check what changed.

![Agent Phone controls Android over local ADB and uses Redis for inventory, leases, routines, and action history.](docs/architecture.svg)

## Connect a device

Install Bun, Redis, and Android SDK Platform-Tools. In the project directory, run `bun install --frozen-lockfile`. Start Redis on the same host. On macOS with Homebrew, run `brew services start redis`.

The first screen read on a new device downloads a verified UIAutomator2 helper.

For a USB phone, turn on **USB debugging** and authorize the Mac on the phone. For an emulator, start it in Android Studio’s **Device Manager**.

## Open Settings and check the result

Set `AGENT_PHONE_OWNER` to a distinct label for each agent or operator. It defaults to the host account when unset. Run `./agent-phone devices` and replace `emulator-5554` with the serial number of your device.

```sh
export AGENT_PHONE_OWNER=codex
SERIAL=emulator-5554
./agent-phone lease "$SERIAL" --why "Explore Android settings"
./agent-phone open "$SERIAL" com.android.settings --why "Open Settings"
./agent-phone state "$SERIAL" --why "Check which app is in the foreground"
./agent-phone snapshot "$SERIAL" --why "Read the controls on screen"
./agent-phone release "$SERIAL"
```

When Settings is in the foreground, `state` reports `com.android.settings` in `answer.app`. Use the labels and IDs from `snapshot` to choose what to tap next.

## Manage devices and routines

`devices` reports how many phones are known, active, busy, and available. Each row shows the ADB state, last observation, and current lease owner and task. Run `history SERIAL` for timestamped actions, owners, reasons, and outcomes.

A routine is a JSON array of CLI steps. The [Settings example](routines/check-settings.json) opens Settings, waits for its search control, and reads the foreground app. Start on the main Settings screen. Android can reopen the last Settings page. Use a control ID from your device when adapting the example.

```sh
./agent-phone routine save check-settings routines/check-settings.json
./agent-phone routine list
./agent-phone routine show check-settings
./agent-phone lease "$SERIAL" --why "Check Settings"
./agent-phone routine run check-settings "$SERIAL" --why "Verify the Settings screen"
./agent-phone history "$SERIAL"
./agent-phone release "$SERIAL"
```

A run returns its ID, completed step count, and last result. The first failed step stops the run.

Run `./agent-phone --help` for the full command list. Codex and Claude Code use the [agent instructions](AGENTS.md).
