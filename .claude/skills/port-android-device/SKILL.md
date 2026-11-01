---
name: port-android-device
description: Bring up agent-phone on an Android phone, tablet or emulator it has not run on, and say whether it works there. Use when asked to port, onboard, support, test or check compatibility of agent-phone on a new device, a new Android version, a new brand or a new UI language, or to produce a device's compatibility card.
---

# Port agent-phone to a new Android device

agent-phone reads an Android screen through a uiautomator2 server and acts on it through one gated pipeline. A new device can break that in ways no fixture shows. Unit 7 found three such bugs on the AYN Thor: a second display, window edges a pixel inside the display, and full-screen apps read as dialogs. This skill runs the same bring-up on any device. It reads the device's facts, writes its profile, surveys it with harmless inputs only, turns what it saw into fixtures, fixes what breaks, test first, and ends with a compatibility card. Run every command from the repo root.

Below, `evidence.py` stands for the verify skill's helper, and `S/` for this skill's scripts:

```bash
evidence.py() { uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py "$@"; }
S=.claude/skills/port-android-device/scripts
```

## Keep the device safe

The device may be signed in to live accounts. A wrong input can post, send or delete, and that cannot be undone.

- Read `AGENTS.md` (Device safety) and `.claude/skills/verify-agent-phone/SKILL.md` (Keep the phone safe) first. Every rule there holds here.
- Every call that reaches the device goes through `evidence.py`, and the scripts below do this for you. The one exception is `emulator.py`, which boots an emulator that has no accounts.
- The survey's inputs are fixed: home, back, Settings by intent, a Bluetooth request that only asks, the About page by intent, and one scroll down and up. Never tap inside an app on a device with live accounts. The app sweep only launches, reads and goes home.
- Never send a live input to see whether the gate refuses it. Judge it offline with `probes/android/gate_check.py` on a raw dump.
- Never stop or start a package the device's profile protects, and never change network, VPN or account settings.

## Gates for the owner

Ask these once, at the start, in one message, and do not drive the device before the answers.

1. **Connection.** Is USB debugging on, and was this computer's key accepted on the device? Some brands need one more developer switch before adb input works (`references/brand-switches.md`).
2. **Screen.** Is the device unlocked and awake? Waking it is an input, and agent-phone never types a PIN.
3. **Accounts and protections.** What is the device used for? Which apps are signed in to live accounts? Which packages must never be stopped, such as a VPN, an emulator or a work app? The answers go into the profile.
4. **Apps.** Which apps, if any, should the sweep check?

Two more gates come later:
- **A new language.** If the device's language has no policy rules, the owner approves the new words before they merge (phase 2).
- **A code fix.** If the survey finds a bug, the fix goes through pstack, test first, with a review. Its merge needs no gate, but the owner sees it in the report.

On an emulator, gates 3 and 4 have fixed answers: no accounts, nothing protected, and sweep the stock apps.

## Phases

### 0. A run folder and the doctor

```bash
RUN=$(evidence.py new port-<name>)
uv run python -I .claude/skills/verify-agent-phone/scripts/doctor.py --serial <serial> | tee "$RUN/doctor-before.txt"
```

Drive only when no line says `stop`. If the doctor says the server is stopped, this run owns it and stops it at cleanup.

### 1. Facts

```bash
uv run python -I $S/facts.py "$RUN" <serial>
```

Read `$RUN/facts.json` and every hint in it:
- The language: is it covered?
- The displays: more than one, and which one has focus? Android 15 names no focused display in any dump. On a phone with one display, `top_focused_display` is then 0 with `top_focused_display_inferred` true. With several displays it is null, and a hint says it is unknown.
- The brand: does it need a developer switch?
- Is it an emulator?
- Is Bluetooth on? That decides the dialog the survey uses.

Choose a short `<name>` for the device, such as `pixel8` or `thor`.

### 2. Language, when it is not covered

agent-phone refuses every labeled input on a device whose language has no rules (`LOCALE_UNSUPPORTED`), because it cannot tell a Send from a Settings tile. Reading still works. Follow `references/new-language.md`:
1. Draft the words for each effect.
2. Add a commit-table row for each word.
3. Run the generated tests.
4. Have the words reviewed by another model.
5. Ask the owner to approve them before the merge.

Until then, run the read-only phases and say in the card that taps are refused.

### 3. Profile

```bash
uv run python -I $S/profile.py --serial <serial> --name <name> \
  --protect <package>='<reason>' [--protect ...] [--policy-file examples/<app>/policy.toml]
```

It writes `examples/devices/<name>.toml`, installs it and any policy files into the state root, and loads it to prove it parses. Check that `agent-phone devices` now prints the profile's name for the serial.

### 4. Survey

```bash
uv run python -I $S/survey.py "$RUN" <serial> <name>
```

This is done-when 4 on the new device, which `docs/plan.md` asks of every device:
- 20 warm snapshots and 10 settled ones, each on the launcher, Settings and a system dialog, with a raw dump of each screen;
- then a journey that proves swipe and key injection, without a single tap.

Read `$RUN/survey.jsonl` line by line:
- A `warm_snapshot` with errors or a wrong screen is a bug.
- A median over 400 ms means the device is slow. Record it; it is not a failure.
- A `<screen>_not_shown` line, a `screen_read` with `agrees: false` (the settled read named another app than the focus), an `aborted` line, or an `input` line whose `delivery` is not delivered, needs an explanation before you go on. Check a screenshot through `evidence.py`.
- An `input` line with `skipped: "no scrolling element"` is a scroll that the survey did not send, because the read before it had no scroll, list, grid or pager. The card lists it as a limit. A scroll that is sent names the largest collection of that read, because agent-phone refuses a scroll with no target when two elements scroll (`AMBIGUOUS_TARGET`, seen on Android 15's About-phone page).
- The script reads the screen before every input, as agent-phone requires, and aborts with nothing sent if it cannot.

### 5. Fixtures, and the fix loop

```bash
uv run python -I $S/fixtures.py "$RUN" <name>
```

It redacts the raw dumps into `tests/fixtures/dumps/<name>-*.xml` and checks how each one parses: which window is active, whether it is a dialog, and which windows were dropped for another display. It exits 1 when it finds an anomaly. For each anomaly:
1. Ask what the device does and why. Look at the raw dump, `dumpsys window windows` and a screenshot. Write the cause as a FINDINGS row in the device's area.
2. Brief a pstack bug-fix delegate (`pstack:poteto-agent` on the model and effort `~/.claude/rules/pstack-models.md` names). Give it the fixture and the decision you made. The pattern is the unit 7 brief (`decisions.tsv`, row "delegate the three fixes"). It commits a strict xfail first, then the fix.
3. Review the diff yourself, merge it, and rerun `fixtures.py` until it exits 0.

Then pin the clean reading:

```bash
uv run python -I $S/fixtures.py "$RUN" <name> --write-test
```

### 6. App sweep, optional

```bash
uv run python -I $S/sweep.py "$RUN" <serial> <package> [<package> ...]
```

For each app, `$RUN/apps.jsonl` says whether its screen was readable at all, and what the gate would do with every button on it. Read the commits it found, and look for buttons that should commit but read clear: a subscribe, a call, a join, a start game, a consent. Then handle each one:
- A word that any app would use goes into `src/agent_phone/policy/default.toml`, test first. Use a strict-xfail test, then the words, then their commit-table rows.
- A word only one app uses goes into `examples/<app>/policy.toml`, scoped to its package, and the profile loads it with `--policy-file`.

A screen with no lines is a canvas or a game. That is a limit to record, not a bug.

### 7. Card

```bash
uv run python -I $S/card.py "$RUN" <name>
```

It writes `docs/devices/<name>.md` and its row in `docs/devices/README.md`, with a status of `works`, `works with limits` or `blocked` by the rules in `scripts/card_status.py`. The card is committed, so it shows an app's sample labels only when `probes/android/ui_labels.txt` lists them. Fill its `## Fixes and notes` section with the fixes, the FINDINGS rows and anything the scripts cannot know, such as a brand switch the owner had to flip. A rerun keeps that section.

### 8. Record and commit

- **FINDINGS.** Add rows to `probes/android/FINDINGS.md` in a new area for the device, with its environment table, following area 6.
- **Plan.** Add a line to `docs/plan.md` naming the device and the card.
- **AGENTS.md.** If the device carries live accounts, add its rules under Device safety, as the J7 and the Thor have.
- **decisions.tsv.** Log every app the run opened and every input it sent.

Commit in an order that reads as an argument: the measurements (FINDINGS, fixtures) before the fixes, the failing test before each fix, and the card last.

### 9. Cleanup

```bash
evidence.py run "$RUN" home --input -- agent-phone -d <serial> press home
evidence.py run "$RUN" server-stop -- agent-phone -d <serial> server stop
uv run python -I .claude/skills/verify-agent-phone/scripts/doctor.py --serial <serial> | tee "$RUN/doctor-after.txt"
uv run python -I .claude/skills/verify-agent-phone/scripts/evidence.py list "$RUN"
```

Compare `doctor-after.txt` with `doctor-before.txt`. Stop an emulator this run booted. Keep the run folder: it is the evidence, and it holds screen content, so it stays out of git.

## The emulator lane

An emulator has no accounts, so the whole skill can run on it without the gates' risks. Use it to test a language or an Android version before a real device arrives, and to check that this skill still works.

```bash
uv run python -I $S/emulator.py boot --avd <avd> --locale de-DE     # prints the serial, such as emulator-5554
uv run python -I $S/emulator.py stop --serial emulator-5554
```

The SDK lives in `~/Library/Android/sdk` (`ANDROID_HOME`). The emulator refuses an SDK without `platform-tools`. Link the adb you already use there (`mkdir -p $ANDROID_HOME/platform-tools && ln -s "$(command -v adb)" $ANDROID_HOME/platform-tools/adb`), and do not install a second adb. An AVD is made once. Homebrew's `avdmanager` only looks in its own folder, so `~/.android/avd/ap-de-35.ini` and its `config.ini` were written by hand for the German Android 15 test device. `boot` counts the device as up only when boot is complete, the locale is set and a real window has focus, because `-change-locale` restarts the framework after the first boot. An emulator proves that the code works on that Android version and in that language. It says nothing about a brand's own layer, such as Samsung's or Xiaomi's: only a real device of that brand does.

## Helpers

| Script | Usage | Writes |
| --- | --- | --- |
| `facts.py` | `facts.py <run> <serial>` | `<run>/facts.json` |
| `survey.py` | `survey.py <run> <serial> <name>` | `<run>/survey.jsonl`, `probes/android/raw/<name>-*.raw.xml` |
| `fixtures.py` | `fixtures.py <run> <name> [--write-test]` | `tests/fixtures/dumps/<name>-*.xml`, `<run>/fixtures.json`, `tests/test_<name>_dumps.py` |
| `profile.py` | `profile.py --serial S --name N [--protect PKG=REASON]... [--policy-file PATH]... [--force]` | `examples/devices/<name>.toml`, the installed copy, each policy file under the state root |
| `sweep.py` | `sweep.py <run> <serial> <package>...` | `<run>/apps.jsonl`, `probes/android/raw/sweep-<serial>-<package>.raw.xml` |
| `card.py` | `card.py <run> <name>` | `docs/devices/<name>.md`, `docs/devices/README.md` |
| `emulator.py` | `emulator.py boot --avd A --locale L [--port 5554] [--deadline-s 240]` / `stop --serial S` | `<state root>/emulators/<avd>-<port>.log`; prints the serial |

## What unit 7 taught (read before you blame the device)

- **Splash screens.** A launch's `--settled` holds on a splash screen. Wait for an element too.
- **Opening animations.** A `--wait-for` after `launch` can hold while the window is still animating in, and a tap sent then is lost (A6-4). Settle first.
- **Landscape keyboards.** In landscape the keyboard can cover the whole app (A6-5). Press back before `set-text`.
- **Popup menus.** A popup is a second window that cannot be tapped (A6-8). Back closes it.
- **Window bounds.** A device can report a window's bounds a pixel inside the display (A6-2). The parser allows 2 px.
- **Two displays.** A second display's windows are dropped from the screen (A6-1). Only display 0 is read and tapped.
- **A flaky facts read.** The facts read can glue two lines or drop one once in a while (A6-11, A6-12). agent-phone reads once more before it refuses with `TRANSPORT`, so a refusal that remains came from two bad reads in a row. A retry of the command is safe.
- **Hardware keys.** A device's hardware can press keys by itself, as the J7's power key did (A7-5). Read `logcat -d` for `notifyKey` before you suspect the code.
