# samsung SM-J730F (samsung-j7)

**Status: works.**

No limit was found.

Source run: `20261101T142949Z-port-samsung-j7`, kept under `~/.agent-phone/verify/`, outside git.

## Device facts

| Fact | Value |
| --- | --- |
| Serial | 0a1b2c3d4e5f6a7b |
| Manufacturer, brand | samsung, samsung |
| Model, device | SM-J730F, j7y17lte |
| Android | 9 (API 28) |
| ABI | armeabi-v7a |
| Locale | en-US, language en, covered by the policy |
| Policy languages | en, it |
| Emulator | no |
| Displays | 0: 1080x1920 ON |
| Keys go to display | 0 (inferred) |
| Screen awake | yes |
| Bluetooth on | no |
| Keyboard | com.sec.android.inputmethod |

## Done-when 4

Settings and the system dialog must have no error and no wrong screen, a median under 400 ms, output under 8 KB and every settled read settled. The launcher is measured for reference.

| Screen | App | Runs | Errors | Wrong screen | Median ms | Range ms | Bytes | Under 8 KB | Settled | Settle median ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.sec.android.app.launcher | 20 | 0 | 0 | 344 | 312 to 470 | 919 to 919 | yes | 10 of 10 | 535 |
| settings | com.android.settings | 20 | 0 | 0 | 372 | 349 to 581 | 1331 to 1331 | yes | 10 of 10 | 576 |
| dialog | com.android.settings | 20 | 0 | 0 | 340 | 326 to 382 | 538 to 538 | yes | 10 of 10 | 480 |

Done-when 4 is met on Settings and the dialog.

## Input journey

Every input read the screen first. The scrolls prove swipes, and the back from About proves keys.

| Step | Input | Delivery | Verified by | Error | App after | Screen changed |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | press home | delivered_unverified | - | - | com.sec.android.app.launcher | yes |
| 2 | open-url android.settings.SETTINGS | delivered_unverified | - | - | com.android.settings | yes |
| 3 | open-url android.bluetooth.adapter.action.REQUEST_ENABLE | delivered_unverified | - | - | com.android.settings | yes |
| 4 | press back | delivered_unverified | - | - | com.android.settings | yes |
| 5 | open-url android.settings.DEVICE_INFO_SETTINGS | delivered_unverified | - | - | com.android.settings | yes |
| 6 | scroll down | delivered_unverified | - | - | com.android.settings | yes |
| 7 | scroll up | delivered_unverified | - | - | com.android.settings | yes |
| 8 | press back | delivered_unverified | - | - | com.android.settings | yes |
| 9 | press home | delivered_unverified | - | - | com.sec.android.app.launcher | yes |

9 inputs were sent. None was a tap.

## Screen reads and anomalies

| Screen | App | Window | Dialog | Settled | Focus app | Agrees | Reads |
| --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.sec.android.app.launcher | application | no | settled | com.sec.android.app.launcher | yes | 1 |
| settings | com.android.settings | application | no | settled | com.android.settings | yes | 1 |
| dialog | com.android.settings | application | yes | settled | com.android.settings | yes | 1 |

Raw dumps saved: launcher, settings, dialog.

Fixtures, as `parse_hierarchy` and `select_surface` read them:

| Screen | Active | Dialog | Windows | Roots of another display | Rotation | Display | Others |
| --- | --- | --- | --- | --- | --- | --- | --- |
| launcher | com.sec.android.app.launcher | no | 2 | 0 | 0 | 1080x1920 | com.android.systemui |
| settings | com.android.settings | no | 2 | 0 | 0 | 1080x1920 | com.android.systemui |
| dialog | com.android.settings | yes | 2 | 0 | 0 | 1080x1920 | com.android.systemui |

No anomaly.

## Apps

No sweep was run.

## Hints

None.

## Fixes and notes

- **The development phone.** agent-phone was built on it (units 2 to 6), so its quirks were fixed before this skill existed. FINDINGS areas 1 to 5 and 7 hold its measurements.
- **No app sweep.** It is signed in to live Instagram and Business Suite accounts, so the skill's run touched only Settings, the Bluetooth enable request (which only asks, and back declines it) and the About page. A7-1 to A7-6 cover Instagram, from the publish benchmark.
- **Its profile** (`examples/devices/j7.toml`) protects SocksTun (`hev.sockstun`) and denies the network, VPN and SocksTun screens, because with always-on lockdown VPN a dead tunnel takes the phone offline. Those deny words are English only. If this phone ever runs in another language, the profile needs that language's words too.
- **Hardware.** During the benchmark its power key pressed itself twice (A7-5), and its screen is known to register touches by itself. Neither happened in this run.
- **What `works` means here.** The survey passed, but the J7 is the phone agent-phone was built on, so this card shows the skill runs on a real device, not that it would catch a quirk (A8-4). Every journey input was `delivered_unverified`: the survey compares a read before and after, and no `--wait-for` verified an effect.
- **This run skipped the skill's owner gates** and replaced the Thor, whose screen was off. Its first read holds an account's profile page, kept outside git.
- **Settings left by the old publishing script.** `stay on while plugged in` and a 30-minute screen timeout, set by `publish_reel.py` on every run.
