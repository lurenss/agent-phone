# Waiting for a screen condition

`agent-phone wait` reads the screen until every condition holds on one read, and prints that read as a snapshot. It takes the place of a sleep and a second snapshot. It sends nothing, so it spends no ref and its retry is safe. A timeout is a refusal whose `error.details.after` is the last read.

## Sub-features

- `wait-never-there` holds at once for `--gone` of a thing that never showed.
- `wait-none` refuses a call with no condition as `INVALID_ARGS`, before it reads.
- `wait-app` waits until Settings is the foreground app after a launch.
- `wait-timeout` refuses a condition that cannot hold with `TIMEOUT`, `not_delivered` and a safe retry, and returns the last read in `details.after`.
- `wait-page` waits for a Settings page that an intent opened, with two conditions on one read, and returns refs that work for the next command.
- `wait-spends-nothing` leaves the refs of an earlier snapshot valid.
- `wait-gone` waits until a page is gone after back.
- `wait-observation` gives the next input the observation it needs after an input.

## How to get to it (user POV)

- Run `agent-phone wait` with `--for QUERY`, `--gone QUERY`, `--app PACKAGE`, `--settled` and `--timeout-ms`. At least one condition is required, and each of `--for` and `--gone` may repeat.
- In Python, call `Driver.wait(conditions, timeout_ms=...)` on the driver that `open_phone()` yields. `examples/settings_wait.py` is a script that opens a Settings page and reads it with no sleeps.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and `devices` reports `locale` `en-US`. The titles below are English.
- Your task allows exactly these inputs, once each: `launch com.android.settings`, `open-url 'intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end'`, `press back` and `press home`. No tap, no text, no scroll. Every `wait` is a read, so none of them takes `--input`.
- The phone shows the home screen.

Steps:

- **Look first.** Run `evidence.py run "$RUN" look -- agent-phone snapshot`. It is the observation that the launch needs.
- **Never there.** Run `evidence.py run "$RUN" never -- agent-phone wait --gone 'name=Brightness'`. Exit 0, `command` is `wait`, there is no `delivery` key, and `data.app` is the launcher. One read: `ms` is near a plain `snapshot`.
- **No condition.** Run `evidence.py run "$RUN" none -- agent-phone wait`. Exit 2, `error.code` `INVALID_ARGS`, `delivery` `not_delivered`, `retry` `safe`.
- **Launch.** Run `evidence.py run "$RUN" launch --input -- agent-phone launch com.android.settings`. Exit 0, and `delivery` is `delivered_unverified`.
- **Foreground.** Run `evidence.py run "$RUN" settings-up -- agent-phone wait --app com.android.settings`. Exit 0, `data.app` is `com.android.settings`, and `tree` has `button "Display"`. Run `evidence.py run "$RUN" focus-settings -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'`, which names `com.android.settings`.
- **Timeout.** Run `evidence.py run "$RUN" timeout -- agent-phone wait --for 'name=Brightness' --timeout-ms 1500`. Exit 1, `error.code` `TIMEOUT`, `delivery` `not_delivered`, `retry` `safe`, there is no `data`, and `error.details.after.app` is `com.android.settings` with the Settings home lines. Its `ms` is at least 1500.
- **Open the page.** Run `evidence.py run "$RUN" display --input -- agent-phone open-url 'intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end'`, then `evidence.py run "$RUN" display-up -- agent-phone wait --for 'name=Brightness' --settled`. Exit 0, `data.settled` is `settled`, and `tree` has `button "Brightness"` with a `slider` line under it. Run `evidence.py run "$RUN" focus-display -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'`, which names a Settings activity.
- **Refs and spending.** Take the ref of the `slider` line from `display-up`. Run `evidence.py run "$RUN" slider -- agent-phone get <ref> --property value`, then `evidence.py run "$RUN" again -- agent-phone wait --for 'name=Brightness'`, then `evidence.py run "$RUN" slider-again -- agent-phone get <the same ref> --property value`. All three exit 0 with the same `value`, and `again` has a new `data.id`. No `STALE_REF`, because `wait` sent no input.
- **Back and gone.** Run `evidence.py run "$RUN" back --input -- agent-phone press back`. It needs no new snapshot, because `display-up` and `again` were taken after the intent. Then run `evidence.py run "$RUN" display-gone -- agent-phone wait --gone 'name=Brightness'`. Exit 0, and `tree` has no line named `Brightness`.
- **Home.** Run `evidence.py run "$RUN" home --input -- agent-phone press home`. It needs the observation that `display-gone` took. Run `evidence.py run "$RUN" home-look -- agent-phone snapshot` and `evidence.py run "$RUN" focus-home -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'`. The focus names the launcher, not Settings.
- **The example.** It sends the same four inputs again, so run it as a separate pass when your task allows it. Make a new run folder with `RUN=$(evidence.py new wait-example)`, start from the home screen, and run `evidence.py run "$RUN" example --input -- python examples/settings_wait.py`. Exit 0, it prints the slider value and one line per step, and the `wait:` lines hold the time spent in each wait.
- **Proof of the inputs.** Run `evidence.py list "$RUN"`. The inputs are `launch`, `display`, `back` and `home`, and every `wait` is listed as a read.

## Gotchas

- `--gone` holds at once for a thing that was never there. Wait for a page with `--for` first, and use `--gone` only to prove something left.
- A condition is read against the active window's compact lines, by name. Settings home lists "Brightness" in the detail of its Display tile, so `--for 'name=Brightness'` holds only on the Display page, while `--for 'text=Brightness'` holds on both.
- A timeout is an error envelope with exit code 1. The screen it ended on is `error.details.after`, and there is no `data`.
- A screen that is off ends `wait` with `NO_SURFACE` at its deadline, after the whole timeout, not at once and not with `TIMEOUT`. An empty read before that is read again. Doctor's `stop screen` line catches it first.
- The record's `ms` includes the process start and, on a cold server, the server start. Read the wait's own cost from a warm run.
- `wait --app` holds when Settings is the first window of the dump that is not a strip or the keyboard. It can hold before Settings has drawn its lines, so wait for a line too when you need one.
- The first journey step is a plain `snapshot`, because an input that follows no observation fails with `OBSERVE_FIRST`. Every later input follows a `wait`.
