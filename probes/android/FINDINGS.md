# Android findings

Each row records one measurement on the real phone, what it showed, and what it obliges the code to do. Code and docs cite a row by its id (`A2-1`) the way they would cite an issue. A row is never edited after it lands. A later row that changes the picture names the row it supersedes.

## How to read a row

| Column | Meaning |
| --- | --- |
| `id` | Stable row id. `A<area>-<n>`. Area 1 is the old adb path, 2 is the uiautomator2 server, 3 is server lifetime and device facts, 4 is snapshot size. |
| `probe` | The script that produced the row, run from the repo root. |
| `observed` | What the phone did, with the run count and range. |
| `verdict` | `CONFIRMS` or `CONTRADICTS` an assumption the design made before measuring, `NEW-EDGE` for behavior nobody assumed, `DEFERRED` for a question a later unit must answer. |
| `action` | What the code must do because of the row. |

## Environment

Every row was measured on this phone on 2026-10-31.

| Fact | Value |
| --- | --- |
| Device | Samsung SM-J730F (`j7y17lte`), serial `0a1b2c3d4e5f6a7b` |
| Android | 9, `armeabi-v7a`, 4 online cores |
| Load | Load average about 4.2 during every run |
| Storage | `/data` 96% full, 525 MB free |
| Apps | Instagram `com.instagram.android`, Business Suite `com.facebook.pages.app` |
| Backend | uiautomator2 3.7.1, `u2.jar` 0.4.1 |
| Host | macOS, adb over USB |

The high load inflates Java process startup most, so the gap between area 1 and area 2 may shrink on an idle phone.

## Rows

| id | probe | observed | verdict | action |
| --- | --- | --- | --- | --- |
| A1-1 | `probes/android/baseline.py` | `adb shell true` takes 36 ms median, 5 runs (27 to 49). | NEW-EDGE | The transport is cheap. Per-call cost on the phone is the thing to remove. |
| A1-2 | `probes/android/baseline.py` | `uiautomator dump` plus `rm` and `cat`, as `mbs_schedule.py` does it, takes 2,125 ms median, 5 runs (2,095 to 2,169), on the USB access dialog. | CONFIRMS | Do not read the screen through one-off `adb shell` processes. |
| A1-3 | `probes/android/baseline.py` | `input keyevent 0` takes 902 ms median, 5 runs (868 to 917). | CONFIRMS | Do not send input through `adb shell input`. |
| A1-4 | `probes/android/baseline.py` | `exec-out screencap -p` takes 1,254 ms median, 5 runs (1,211 to 1,295). | NEW-EDGE | Screenshots are evidence for a human, never part of the agent's loop. |
| A1-5 | manual, see `decisions.tsv` | On the Instagram feed 1.5 s after launch, `uiautomator dump` took 5.8 s, then 2.5 s, then failed with "could not get idle state" after 11.2 s. 3 runs. On the settled feed it succeeded 6 of 6 (A2-1). | CONFIRMS | The old dump fails while a screen animates, not on a settled screen. |
| A2-1 | `probes/android/compare_backends.py ig-feed-settled` | Settled Instagram feed, alternating blocks. Old dump 2,564 ms median, 6 runs (2,303 to 2,874), 0 errors. Server dump 154 ms median, 10 runs (145 to 262), 0 errors. | CONFIRMS | Read the screen through a server that stays running. |
| A2-2 | `probes/android/compare_backends.py mbs-home-settled` | Settled Business Suite home. Old dump 2,350 ms median, 6 runs (2,261 to 3,107), 0 errors. Server dump 164 ms median, 10 runs (134 to 222), 0 errors. | CONFIRMS | Same as A2-1, on the app the first flow drives. |
| A2-3 | `probes/android/u2_latency.py 7 <label>` | A no-op key through the server (`pressKeyCode(0)`) takes 34 ms median, 7 runs (32 to 52). That is the A1-1 round trip. | CONFIRMS | Send input through the server. Transport bounds it. |
| A2-4 | `probes/android/compare_backends.py` | The server dump returns every window. On the USB dialog it returned 49 nodes where `uiautomator dump` returned 12. | NEW-EDGE | Snapshots must pick the window they describe instead of passing the full dump through. |
| A2-5 | none yet | The server dump does not wait for the screen to settle, so it can return a tree from the middle of a transition. Inferred from A1-5 and A2-1, not observed directly. | DEFERRED | Unit 3 adds `--settle` and a test that the snapshot after a screen change shows the new screen. |
| A3-1 | `pm list packages` | No uiautomator or atx package is installed. The only footprint is `/data/local/tmp/u2.jar`. | CONFIRMS | Never call uiautomator2 features that install its IME APK. |
| A3-2 | `probes/android/server_lifetime.sh` | Started by the uiautomator2 library, the server stops answering as soon as the adb shell stream that launched it closes. 2 observations. | NEW-EDGE | Start the server detached on the phone (A3-3), not from the library's attached stream. |
| A3-3 | `probes/android/server_lifetime.sh` | Started detached with `nohup`, the server answered after about 3 s and was still up 5 s later. 2 observations. | NEW-EDGE | agent-phone starts the server detached and stops it after 15 idle minutes. |
| A3-4 | `probes/android/compare_backends.py`, first run | Starting a second UiAutomation client while one is connected fails with `UiAutomationService ... already registered`. | NEW-EDGE | One lock covers agent-phone and the old scripts. The old scripts' `uiautomator dump` fails while the server runs. |
| A3-5 | none yet | While the server runs, accessibility is on, and apps can detect it. Inferred from how UiAutomation registers, not observed. | DEFERRED | The server stops after 15 idle minutes. Unit 2 verifies that it is gone. |
| A4-1 | `probes/android/compare_backends.py` | A snapshot with every actionable element, every element with visible text, and bounds is 6.0 KB of 72 KB raw on the Instagram feed and 4.0 KB of 46.7 KB raw on Business Suite home. 1 dump each. | NEW-EDGE | The snapshot size budget is 8 KB. |
| A4-2 | none yet | AOSP `UiObject.click()` injects a touch at the element's center instead of the accessibility click action. Not checked inside `u2.jar`. | DEFERRED | Unit 4 checks it. Until then a click reports `delivered_unverified`. |
| A2-6 | source read of `uiautomator2/core.py` 3.7.1 | `Device.jsonrpc_call` catches `HTTPError` and `UiAutomationNotConnectedError`, restarts the server, and sends the same call again. `_do_dump_hierarchy` also carries `@retry`. A tap whose response was lost would be sent twice. | NEW-EDGE | The adapter speaks JSON-RPC itself and sends every input exactly once. It does not import the uiautomator2 package at run time. |
| A3-6 | `adb shell cat /proc/sys/kernel/random/boot_id` and `settings get secure default_input_method` | On API 28 the shell user reads the boot id (a UUID), the default keyboard (`com.sec.android.inputmethod/.SamsungKeypad`) and the locale (`en-US`) without root. 1 observation. | CONFIRMS | Device identity is serial plus boot id. The keyboard window is the one whose package is the default input method. |
