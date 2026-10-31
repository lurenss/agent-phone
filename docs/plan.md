# agent-phone plan

agent-phone is a general framework that lets an AI agent drive any Android phone and any app on it from a computer over adb. It follows the design of [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop). Snapshots are compact and list only what the agent needs. Every element the agent can act on gets a ref that belongs to one snapshot on one device. Before any action the ref is found again on the live screen, and the action fails if that is uncertain. Every action result says whether input reached the phone.

Nothing in core knows about a particular app. App knowledge lives in data (policy files and device profiles) and in consumers built on the public API. The first device is Lorenzo's Samsung J7 (SM-J730F, Android 9, armeabi-v7a). The first consumer is a port of `~/.claude/skills/scheduling-ana-reels-business-suite/scripts/mbs_schedule.py`, which drives Meta Business Suite. It lives in `examples/` and proves the public API is enough for a real flow. Today that script runs three `adb shell` processes per screen read, taps the center of an element's bounds, and has 30 fixed sleeps whose literal values add up to 97 seconds. That 97 is a sum of the code's sleep values, not a measured run time.

## What the J7 measurements showed

All numbers come from the J7 on 2026-10-31, with the phone's load average at 4.2 on 4 online cores. Each row gives its run count. `probes/android/FINDINGS.md` holds the full ledger.

| Screen | Old `uiautomator dump` | uiautomator2 server | Evidence |
|---|---|---|---|
| USB access dialog | 2,125 ms median, 5 runs (2,095 to 2,169) | 134 ms median, 7 runs (125 to 153) | A1-2 |
| Instagram feed, settled | 2,564 ms median, 6 runs (2,303 to 2,874), 0 errors | 154 ms median, 10 runs (145 to 262), 0 errors | A2-1 |
| Business Suite home, settled | 2,350 ms median, 6 runs (2,261 to 3,107), 0 errors | 164 ms median, 10 runs (134 to 222), 0 errors | A2-2 |
| Instagram feed, 1.5 s after launch | 5.8 s, 2.5 s, then "could not get idle state" after 11.2 s (3 runs) | not measured in the same state | A1-5 |

The settled rows ran in alternating blocks (old 3, new 5, old 3, new 5), so warmup and drift favor neither side. A no-op key event takes 902 ms with `adb shell input` and 34 ms through the server, against a bare adb round trip of 36 ms (A1-1, A1-3, A2-3). The adb transport therefore bounds the server's input, and the old cost is the phone starting a new Java process for every call. The phone's high load inflates that startup cost the most, so the gap may be smaller on an idle or newer phone.

The old dump waits until the screen stops animating, and it fails when the screen never settles. The server's dump does not wait. It succeeds during animation, but it can return a tree from the middle of a transition (A2-5). The snapshot command therefore needs a settle option, and the done-when checks test that a snapshot is current, not only that it returns.

A realistic snapshot keeps every element the agent can act on, every element with visible text, and their bounds. It is 6.0 KB for the Instagram feed (72 KB raw) and 4.0 KB for Business Suite home (46.7 KB raw), each from one dump (A4-1).

Every number above comes from one device. A second device must confirm that the design is not shaped around the J7.

## What the server's lifetime showed

- No uiautomator APK is installed on the phone. The only footprint is `u2.jar` in `/data/local/tmp` (A3-1).
- Started by the uiautomator2 Python library, the server stops answering as soon as the adb shell stream that launched it closes. Started with `nohup app_process ...`, it survives and answers after about 3 seconds. Each fact rests on two observations (A3-2, A3-3).
- Android allows one UiAutomation client at a time (A3-4). While an agent-phone server runs, any other UiAutomation user on that device fails with "already registered", including the old scripts' `uiautomator dump`.
- A server left running keeps accessibility switched on, and apps can detect that (A3-5). The server must stop when idle.

## Done when

1. `agent-phone snapshot` succeeds 20 times out of 20 on four settled screens of different kinds: stock Android Settings, a system dialog, the Instagram feed and Business Suite home. The warm median is under 400 ms and the output is under 8 KB. After a scripted screen change, the next snapshot with the settle option shows the new screen's title.
2. A ref fails closed outside the snapshot that made it. After the screen changes it returns `STALE_REF` and sends no input. Used against another device, or against the same device after a reboot, it is refused before anything is sent. Test fixtures prove each case, and one live run confirms the screen-change case.
3. The policy engine refuses every commit action in its test table unless the caller passes `--commit`. Its rules are data, and the table covers matches on visible text, on `content-desc` and on `resource-id`. It also refuses to stop a package that the device profile marks as protected.
4. The same live suite from check 1, with Settings and a system dialog, passes on a second Android device with a different Android version. That is the AYN Thor if it is connected, otherwise an Android emulator.
5. The Business Suite scheduling dry run in `examples/` runs on agent-phone for both accounts through the public API only. It stops before the Schedule tap and records a trace. It lists Drafts before and after, and deletes only a draft it created. It has no fixed sleeps.

## Choices made so far

- **Backend.** The uiautomator2 jar (`u2.jar` 0.4.1) runs from `/data/local/tmp` through `app_process`. uiautomator2's IME APK is never installed. A custom `app_process` server or an AccessibilityService can replace this backend later without changing the commands, because only its adapter folder talks to it.
- **Server lifetime.** agent-phone starts the server detached on the phone and stops it after 15 idle minutes. The idle timer lives on the computer and runs `pkill -f uia2.Main` over adb. No process on the computer has to hold a stream open.
- **Devices.** A device is chosen by adb serial. When only one device is connected, it is the default. Device facts such as API level, screen size, density and rotation are read from the device, never assumed.
- **Language.** Python, managed with uv. uiautomator2 is Python. Lorenzo approved the plan with this default on 2026-10-31.
- **Clicks.** In AOSP UiAutomator, `UiObject.click()` injects a touch at the element's center instead of calling the accessibility click action. I have not checked this inside `u2.jar`, so unit 4 checks it (A4-2). Until then, every click reports `delivered_unverified` and the agent confirms it by reading the screen again. `set-text` uses `ACTION_SET_TEXT`.
- **Types.** pstack runs its architect step, with an Opus and a Fable runner, for data shapes that later code depends on. The ref fingerprint, the device identity, the delivery result and the policy shape are those shapes, so unit 1 runs it once.

## Units, in order

Each unit ends in a check that has to pass before the next unit starts.

0. **Repo.** Done. uv project, ruff, pytest, the layout from agent-desktop (`core/`, `adapters/`, `cli/`, `probes/android/` with `FINDINGS.md`, `AGENTS.md`), the gate that keeps core free of backend imports, and the lint that rejects `time.sleep`. Check passed: `uv run pytest` and the lint pass, and each gate fails when a violation is planted.
1. **Types.** Done (`f1eb992` to `7197a4a`). Settle `Device` and its identity, `Snapshot`, `Node`, the role list, `Ref`, the stored fingerprint for finding an element again, the result envelope, `Disposition`, the error codes, the policy rule shape and the device profile. Check: golden tests turn the redacted fixtures into the expected snapshots, and the CONCEPTS.md glossary and `docs/json-output.md` contract match the types.
2. **Devices, server lifetime and lock.** List devices, read device facts, start and health-check the server, stop it when idle, and hold one lock per device so only one process drives it. Check: over 20 warm calls, the median `snapshot` is under 400 ms, and the server is gone 15 minutes after the last call.
3. **Reading.** Open from unit 1: on the Instagram feed, `--skeleton` hides the whole page behind the root pager. `snapshot -i --compact`, `--skeleton`, `--root`, `--settle`, system surfaces (dialogs, keyboard, notification shade), then `find`, `get` and `is`, and the first agent skill under `skills/`. Then pstack's `create-verification-skill` writes a project skill that drives a real device through the CLI, so every later unit proves its change the same way. Check: done-when 1 on the J7, plus golden tests.
4. **Actions and device operations.** Open from unit 1: measure how often the page-level row key stales refs on a live feed with no input, and settle the hit test for a dialog over an app. `click`, `set-text`, `scroll` and `press` on refs, plus `back`, `home`, `recents`, `launch`, `stop`, `open-url` for intents and deep links, `rotate`, clipboard and `screenshot` as evidence. Each ref action finds the ref again first, checks the target (visible, enabled, same bounds on two reads) and returns a delivery result. The policy engine sits here. Check: done-when 2 and 3.
5. **Waiting.** `wait --text`, `wait --gone`, and `--wait-for` on actions. Check: a script opens a known Settings page and reads it with no sleeps.
6. **Batch and trace.** Several commands in one call, and one JSONL trace per run. Check: a three-step batch runs in one call, and its trace lists each step with its delivery result.
7. **Second device.** Run the live suite on the AYN Thor or an emulator, and record what differs in `FINDINGS.md`. Check: done-when 4.
8. **First example consumer.** Time one run of today's scheduling dry run as the baseline, then write the port in `examples/` against the public API only. Check: done-when 5, and wall time compared with that baseline.
9. **MCP server (optional).** The same commands as MCP tools, so Grok can call them as well as Claude Code. Claude Code can already call the CLI from Bash, so this unit only earns its place if another agent needs it. Lorenzo decides.

My rough guess is two to three days of agent time. Units 1 and 4 carry most of the risk.

Each unit lands as one or more Conventional Commits that each pass the full test suite and lint, in an order that reads as an argument. `AGENTS.md` holds the commit rules.

## Rigor

Rigor is high wherever the tool sends input. On a phone with live accounts, a wrong tap can post, send or delete, and that cannot be undone. Reading the screen changes nothing, so the reading units get golden tests and a live check without extra review.

A list of forbidden labels cannot be complete. Buttons can be labeled only by `content-desc` or `resource-id`, and every app names its commit buttons differently. Unit 1 therefore designs the gate as a policy engine whose rules are data, with safe defaults in the package and app- or device-specific rules in policy files. One option is that a consumer declares its only commit step, and in tests every tap must target an element the consumer declared. Unit 4 then tests the engine against the full table.

## Safety rules

The framework enforces these on every device:

- Never send a commit action without `--commit`. Tests never pass it.
- Never stop a package that the device profile marks as protected.
- Install nothing on the device. The jar in `/data/local/tmp` is the only footprint.
- Only one process drives a device at a time.
- Keep raw dumps out of git. Commit only redacted fixtures.

Lorenzo's J7 profile adds these:

- SocksTun (`hev.sockstun`) is protected. With always-on lockdown VPN, a dead tunnel takes the phone offline.
- The phone runs live Instagram and Business Suite accounts, and `/data` has 525 MB free.
- Every benchmark or test that opens an app on the J7 writes that side effect to `decisions.tsv`.

## Open calls for Lorenzo

- Whether unit 9 (MCP) is worth building.
- Whether the second device for unit 7 is the AYN Thor or an emulator. My default is the Thor, because it is already set up for adb.
