# Google sdk_gphone64_arm64 (emu-de-35)

**Status: works with limits.**

- The policy has no rules for the language de.

Source run: `20261101T142642Z-port-emu-de-35`, kept under `~/.agent-phone/verify/`, outside git.

## Device facts

| Fact | Value |
| --- | --- |
| Serial | emulator-5554 |
| Manufacturer, brand | Google, google |
| Model, device | sdk_gphone64_arm64, emu64a |
| Android | 15 (API 35) |
| ABI | arm64-v8a |
| Locale | de-DE, language de, not covered by the policy |
| Policy languages | en, it |
| Emulator | yes |
| Displays | 0: 1080x2400 ON |
| Keys go to display | 0 |
| Screen awake | yes |
| Bluetooth on | yes |
| Keyboard | com.google.android.inputmethod.latin |

## Done-when 4

Settings and the system dialog must have no error and no wrong screen, a median under 400 ms, output under 8 KB and every settled read settled. The launcher is measured for reference.

| Screen | App | Runs | Errors | Wrong screen | Median ms | Range ms | Bytes | Under 8 KB | Settled | Settle median ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.google.android.apps.nexuslauncher | 20 | 0 | 0 | 224 | 205 to 505 | 1298 to 1298 | yes | 10 of 10 | 277 |
| settings | com.android.settings | 20 | 0 | 0 | 213 | 209 to 440 | 1394 to 1394 | yes | 10 of 10 | 290 |
| dialog | com.android.settings | 20 | 0 | 0 | 202 | 199 to 459 | 619 to 619 | yes | 10 of 10 | 269 |

Done-when 4 is met on Settings and the dialog.

## Input journey

Every input read the screen first. The scrolls prove swipes, and the back from About proves keys.

| Step | Input | Delivery | Verified by | Error | App after | Screen changed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | press home | delivered_unverified | - | - | com.google.android.apps.nexuslauncher | no |
| 2 | open-url android.settings.SETTINGS | delivered_unverified | - | - | com.android.settings | yes |
| 3 | open-url android.bluetooth.adapter.action.REQUEST_DISCOVERABLE | delivered_unverified | - | - | com.android.settings | yes |
| 4 | press back | delivered_unverified | - | - | com.android.settings | yes |
| 5 | open-url android.settings.DEVICE_INFO_SETTINGS | delivered_unverified | - | - | com.android.settings | yes |
| 6 | scroll down | delivered_unverified | - | - | com.android.settings | yes |
| 7 | scroll up | delivered_unverified | - | - | com.android.settings | yes |
| 8 | press back | delivered_unverified | - | - | com.android.settings | yes |
| 9 | press home | delivered_unverified | - | - | com.google.android.apps.nexuslauncher | yes |

9 inputs were sent. None was a tap.

## Screen reads and anomalies

| Screen | App | Window | Dialog | Settled | Focus app | Agrees | Reads |
| --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.google.android.apps.nexuslauncher | application | no | settled | com.google.android.apps.nexuslauncher | yes | 1 |
| settings | com.android.settings | application | no | settled | com.android.settings | yes | 1 |
| dialog | com.android.settings | application | yes | settled | com.android.settings | yes | 1 |

Raw dumps saved: launcher, settings, dialog.

Fixtures, as `parse_hierarchy` and `select_surface` read them:

| Screen | Active | Dialog | Windows | Roots of another display | Rotation | Display | Others |
| --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.google.android.apps.nexuslauncher | no | 2 | 0 | 0 | 1080x2400 | com.android.systemui |
| settings | com.android.settings | no | 2 | 0 | 0 | 1080x2400 | com.android.systemui |
| dialog | com.android.settings | yes | 2 | 0 | 0 | 1080x2400 | com.android.systemui |

No anomaly.

## Apps

| Package | Launched | Settled ms | Snapshot lines | Targets | Clear | Commits | Denied | Refused | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| com.android.settings | yes | 399 | 12 | 9 | 0 | - | 0 | 9 | - |
| com.google.android.apps.messaging | yes | 695 | 6 | 3 | 0 | - | 0 | 3 | - |
| com.google.android.dialer | yes | 996 | 10 | 8 | 0 | - | 0 | 8 | - |
| com.google.android.contacts | yes | 1346 | 11 | 9 | 0 | - | 0 | 9 | - |
| com.android.chrome | yes | 1528 | 6 | 3 | 0 | - | 0 | 3 | - |
| com.google.android.gm | yes | 750 | 3 | 1 | 0 | - | 0 | 1 | - |

## Hints

- The policy has no rules for de. Every labeled input is refused until its words are added.
- Emulator: no live accounts. Safe for a full survey.

## Fixes and notes

- **What it is.** This is the port-android-device skill's own test device: an Android 15 emulator (AVD `ap-de-35`, Google APIs, arm64) set to German. It has no accounts, so every phase runs without the owner's gates. Boot it with `emulator.py boot --avd ap-de-35 --locale de-DE`.
- **The first run (`20261101T140209Z-port-emu-de-35`) found a safety bug in agent-phone** (A8-1). The device facts read ran its jobs in parallel, and a property line could arrive glued to another job's line: 5 of 300 reads. When the glued line was `persist.sys.locale`, agent-phone fell back to `ro.product.locale` (`en-US`) and took a German device for an English one, so the locale guard stopped refusing. The same glue was the "default keyboard" flake on the Thor (A6-11, A6-12). It is fixed in `119706d` and `63c5c40`: one write per job, a garbled read refused, one retry. After the fix, 0 of 300 reads were garbled.
- **The same run found two gaps in the skill's scripts.** Android 15's About page has two scrolling views, so the survey now names its scroll target (`82d7067`, `0eb43aa`). `facts.py` now reads `mTopFocusedDisplayId` from `dumpsys window` when `dumpsys window displays` lacks it, as on Android 15, and infers display 0 only when no dump names it on a one-display device, as on the J7 (`8d60249`, `e8a6632`). The fix's commit messages say Android 15 prints the line nowhere, which is wrong (A8-3).
- **German.** Every tap target in the swept apps is refused with `LOCALE_UNSUPPORTED` until German is a policy language. The words are drafted, reviewed and tested on branch `lang/de` and wait for Lorenzo's approval (`references/new-language.md`). Swipes, keys, launches and links work without them, because only deny rules judge those inputs.
- **The SDK on this Mac.** It lives in `~/Library/Android/sdk`, with `platform-tools/adb` linked to the Homebrew adb so that there is one adb. The AVD files were written by hand, because Homebrew's `avdmanager` only looks in its own folder.
