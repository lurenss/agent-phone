# Benchmark task: a tour of Settings on an Android emulator

You drive an Android emulator with the `agent-phone` CLI. This is a timed benchmark of the tool: work directly and efficiently, with no exploration beyond the task, and no commentary between calls.

## The tool

Run every phone command through the wrapper, which picks the device and logs the call:

    {ap} <agent-phone arguments>

Do not pass `-d`. Do not run `devices` or `server`. The wrapper is the only command you may run: no `adb`, no other tool on the device, and nothing that filters the wrapper's output. It prints the tool's output unchanged. First read the tool's guide once, at `{guide}`.

## The task

The emulator shows its home screen. Do these in order, then stop:

1. Open the Settings app (`com.android.settings`).
2. With the search of Settings ("Search settings"), search for `dark theme` and open the result named "Dark theme".
3. Turn Dark theme on. Its switch must then read checked.
4. Go back to the main page of Settings, the one that lists "Network & internet".
5. Open "About emulated device". It is the last row of the main list, far below the fold.
6. Rename the device to `bench-phone`: tap "Device name", replace the text, and confirm. Settings may ask you to confirm once more. If it does, confirm. The row "Device name" must then read `bench-phone`.
7. On that page, read the values of "Android version" and "IP address". They may be below the fold.
8. Go back to the main page of Settings.

## Rules

- Do not sleep.
- Stay inside Settings. If anything unexpected shows, such as another app or a pop-up you do not understand, stop and report what the screen shows.
- No step here needs a `--commit` grant. If the gate refuses an input, stop and report.

## Report

Your final message is this JSON object on one line and nothing else:

    {"result": "ok", "android_version": "<value>", "ip_address": "<value>"}

When a step failed, `result` is `failed at step N: <error code and what the screen showed>`.
