# Snapshot modes and surfaces

`agent-phone snapshot` reads one window of the phone and prints it as compact lines with refs, under 8 KB. The mode sets how much it shows, `--settle` says whether the screen had stopped changing, and the surface flags pick the window.

## Sub-features

- `snap-compact` prints every element that takes input and every text that no such element owns, for the active window.
- `snap-skeleton` folds the rows of each collection into one line with `(N rows)` and `(+N)`.
- `snap-root` prints the subtree under one ref as a new snapshot that keeps the ref numbers.
- `snap-full` prints every node of the window, including nodes with no words.
- `snap-settle-cold` shows the new screen after a screen change, with the server stopped before the change.
- `snap-settle-warm` shows the new screen after a screen change, with the server up.
- `snap-all` lists every window in dump order, each opened by a `group` line.
- `snap-window` describes the window that `others` lists under an id.
- `snap-no-surface` refuses a surface that is not on screen with `NO_SURFACE`.
- `snap-dialog` describes a dialog over an app with `--surface dialog`.
- `snap-keyboard-shade` describes the keyboard and the notification shade.

## How to get to it (user POV)

- Run `agent-phone snapshot` with `--compact`, `--skeleton`, `--full`, `--settle`, `--timeout-ms`, `--surface`, `--window` or `--root`.
- In Python, call `Driver.snapshot()` on the driver that `open_phone()` from `agent_phone.cli.driver` yields.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and `devices` reports `locale` `en-US`. The titles below are English.
- Your task allows `adb shell am start -a android.settings.SETTINGS` and `adb shell am start -a android.settings.WIFI_SETTINGS`.
- `snap-dialog` also needs `adb shell am start -a android.bluetooth.adapter.action.REQUEST_ENABLE` and `adb shell input keyevent KEYCODE_BACK`, which declines the dialog. Skip it when your task does not allow both.

Steps:

- **Cold server.** Stop the server. Run `evidence.py run "$RUN" cold-stop -- agent-phone server stop`. `data.running` is `false`.
- **Open Settings.** Run `evidence.py run "$RUN" open-settings --input -- adb -s "$SERIAL" shell am start -a android.settings.SETTINGS`. Exit code 0.
- **Settle cold.** Run `evidence.py run "$RUN" settle-cold -- agent-phone snapshot --settle`. `app` is `com.android.settings`, `window` is `application`, `settled` is `settled`, and `tree` has `text "Settings"` and a ref line `button "Connections"`. The record's `ms` includes the server start.
- **Second view.** Run `evidence.py run "$RUN" focus-settings -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'`. It names `com.android.settings/com.android.settings.Settings`.
- **Compact.** Run `evidence.py run "$RUN" compact -- agent-phone snapshot`. `mode` is `compact`, `settled` is `unchecked`, and `stdout_bytes` is under 8192.
- **Skeleton.** Run `evidence.py run "$RUN" skeleton -- agent-phone snapshot --skeleton`. The line `list #dashboard_container` ends its counts with `(+N)`, and `stdout_bytes` is smaller than the compact record's.
- **Drill down.** Run `evidence.py run "$RUN" root -- agent-phone snapshot --root <ref of that list line>`. `id` is new, the first line is the list with the same `e<N>`, and the list's rows follow it.
- **Full.** Run `evidence.py run "$RUN" full -- agent-phone snapshot --full`. `mode` is `full`, and the tree has several times the compact record's lines, most of them `group` lines with no words.
- **All windows.** Run `evidence.py run "$RUN" all -- agent-phone snapshot --surface all`. Each depth-0 line is `group "<package>" "<window kind>"`, one per window, and the Settings line says `focused`.
- **No surface.** Run `evidence.py run "$RUN" no-dialog -- agent-phone snapshot --surface dialog`, `evidence.py run "$RUN" no-keyboard -- agent-phone snapshot --surface keyboard` and `evidence.py run "$RUN" no-window -- agent-phone snapshot --window 9`. Each exits 1 with `NO_SURFACE`, `delivery` `not_delivered` and `retry` `safe`, and the message lists the windows on screen.
- **Settle warm.** With the server still up, run `evidence.py run "$RUN" open-wifi --input -- adb -s "$SERIAL" shell am start -a android.settings.WIFI_SETTINGS`, then `evidence.py run "$RUN" settle-warm -- agent-phone snapshot --settle`. `settled` is `settled` and `tree` has the Wi-Fi page's title, `text "Wi-Fi"`. `focus-wifi`, the same `dumpsys` read as before, names `WifiSettingsActivity`.
- **Window by id.** The `others` of the `settle-warm` record lists the status bar, `com.android.systemui`, with its `id`. Run `evidence.py run "$RUN" window -- agent-phone snapshot --window <that id>`. `app` is `com.android.systemui` and `window` is `system`.
- **Proof.** Run `evidence.py run "$RUN" wifi-shot --out wifi.png -- adb -s "$SERIAL" exec-out screencap -p`. The picture shows the Wi-Fi page. It also shows network names, so it stays in the run folder.
- **Dialog.** Only when allowed. Run `evidence.py run "$RUN" bt-before -- adb -s "$SERIAL" shell settings get global bluetooth_on`, `evidence.py run "$RUN" open-dialog --input -- adb -s "$SERIAL" shell am start -a android.bluetooth.adapter.action.REQUEST_ENABLE`, then `evidence.py run "$RUN" dialog -- agent-phone snapshot --settle --surface dialog`. `dialog` is `true` and the tree has the buttons `Deny` and `Allow`. Decline with `evidence.py run "$RUN" decline --input -- adb -s "$SERIAL" shell input keyevent KEYCODE_BACK`, and check that `bt-after`, the same `settings get` read, equals `bt-before`.

## Gotchas

- A plain snapshot right after `am start` shows the screen before it (`A2-10`). Prove a screen change with `--settle` only.
- A cold server lists the status bar before the app (`A2-8`), so `snap-settle-cold` and `snap-settle-warm` are separate proofs. Drive both after a change to reading.
- The keyboard needs typing and the shade needs a swipe, which most tasks do not allow. Report `snap-keyboard-shade` as skipped. `tests/test_surfaces.py` covers them on fixtures only.
- Never tap `Allow` in the Bluetooth dialog. BACK declines it.
- The Settings home of a Samsung phone names its tiles `Connections`, `Sounds and vibration` and so on. Another vendor's Settings has other titles, so read the titles before you assert them.
- `--root` with a ref of a list from another screen fails with `STALE_REF`. Drill with a ref from the screen that shows now.
- `stdout_bytes` counts the whole envelope. The 8 KB budget is for the whole line, so a pass needs it under 8192.
- The status bar is not always in the dump. On the J7, Settings home listed it in one run and not in the run before, so read `others` of the record at hand before you name a window id.
