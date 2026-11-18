# Agent Phone

Agent Phone lets a coding agent control Android one step at a time. It uses UIAutomator2 to read text and controls on the screen. The agent can open an app, tap a button, fill in a field, and check what changed.

![Agent Phone architecture. The CLI controls an Android phone through walkie-porkie on the Raspberry Pi, or uses the Mac’s ADB server to reach a USB phone or an emulator.](docs/architecture.svg)

## Choose a device

Run the CLI with Bun from the project directory.

| Device | What you need on the Mac | List devices |
| --- | --- | --- |
| Phone connected to the Raspberry Pi | Python 3 and the `wp.py` client configured for walkie-porkie | `./agent-phone devices` |
| USB phone or Android emulator on the Mac | `uv` and Android SDK Platform-Tools, which includes `adb` | `./agent-phone --local devices` |

For a USB phone, turn on **USB debugging** and authorize the Mac on the phone. For an emulator, start it in Android Studio’s **Device Manager**.

## Open Settings and check the result

For a local device, replace `emulator-5554` with the serial number from `./agent-phone --local devices`. For a phone on the Pi, use its serial number and omit `--local` from each command.

```sh
SERIAL=emulator-5554
./agent-phone --local lease "$SERIAL" --why "Explore Android settings"
./agent-phone --local open "$SERIAL" com.android.settings --why "Open Settings"
./agent-phone --local state "$SERIAL" --why "Check which app is in the foreground"
./agent-phone --local snapshot "$SERIAL" --why "Read the controls on screen"
./agent-phone --local release "$SERIAL"
```

When Settings is in the foreground, `state` reports `com.android.settings` in `answer.app`. Use the labels and IDs from `snapshot` to choose what to tap next.

Run `./agent-phone --help` for the full command list. Codex and Claude Code use the [agent instructions](AGENTS.md).
