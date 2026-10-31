# agent-phone plan

agent-phone lets an AI agent drive Lorenzo's Samsung J7 (SM-J730F, Android 9, armeabi-v7a) from this Mac over adb. It follows the design of [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop). Snapshots are compact and list only what the agent needs. Every element the agent can act on gets a ref that belongs to one snapshot. Before any action the ref is found again on the live screen, and the action fails if that is uncertain. Every action result says whether input reached the phone.

The first job it replaces is `~/.claude/skills/scheduling-ana-reels-business-suite/scripts/mbs_schedule.py`, which drives Meta Business Suite (`com.facebook.pages.app`). That script runs three `adb shell` processes per screen read and taps the center of an element's bounds. It also has 30 fixed sleeps whose literal values add up to 97 seconds. That 97 is a sum of the code's sleep values, not a measured run time. The Instagram publishing flow (`publishing-ana-reels`) is the second candidate. Its `uiautomator dump` fails on the Instagram feed, profile and settings screens.

## What the J7 measurements showed

All numbers come from the J7 on 2026-10-31, with the phone's load average at 4.2 on 4 online cores. Each row gives its run count.

| Screen | Old `uiautomator dump` | uiautomator2 server | Evidence |
|---|---|---|---|
| USB access dialog | 2,125 ms median, 5 runs (2,095 to 2,169) | 134 ms median, 7 runs (125 to 153) | `probes/android/captures/2026-10-31-baseline-mtp-dialog.jsonl`, decisions.tsv |
| Instagram feed, settled | 2,564 ms median, 6 runs (2,303 to 2,874), 0 errors | 154 ms median, 10 runs (145 to 262), 0 errors | `probes/android/captures/2026-10-31-compare-settled.jsonl` |
| Business Suite home, settled | 2,350 ms median, 6 runs (2,261 to 3,107), 0 errors | 164 ms median, 10 runs (134 to 222), 0 errors | same |
| Instagram feed, 1.5 s after launch | 5.8 s, 2.5 s, then "could not get idle state" after 11.2 s (3 runs) | not measured in the same state | decisions.tsv |

The settled rows ran in alternating blocks (old 3, new 5, old 3, new 5), so warmup and drift favor neither side. A no-op key event takes 902 ms with `adb shell input` and 34 ms through the server, against a bare adb round trip of 36 ms. The adb transport therefore bounds the server's input, and the old cost is the phone starting a new Java process for every call. The phone's high load inflates that startup cost the most, so the gap may be smaller on an idle phone.

The old dump waits until the screen stops animating, and it fails when the screen never settles. The server's dump does not wait. It succeeds during animation, but it can return a tree from the middle of a transition. The snapshot command therefore needs a settle option, and the done-when checks test that a snapshot is current, not only that it returns.

A realistic snapshot keeps every element the agent can act on, every element with visible text, and their bounds. It is 6.0 KB for the Instagram feed (72 KB raw) and 4.0 KB for Business Suite home (46.7 KB raw), each from one dump.

## What the server's lifetime showed

- No uiautomator APK is installed on the phone (`pm list packages`). The only footprint is `u2.jar` in `/data/local/tmp`.
- Started by the uiautomator2 Python library, the server stops answering as soon as the adb shell stream that launched it closes. Started with `nohup app_process ...`, it survives and answers after about 3 seconds. Both lifetime facts come from single observations.
- Android allows one UiAutomation client at a time. While an agent-phone server runs, the old scripts' `uiautomator dump` fails with "already registered". The old scripts and agent-phone cannot drive the phone at the same time.
- A server left running keeps accessibility switched on, and apps can detect that. The server must stop when idle.

## Done when

1. `agent-phone snapshot` succeeds 20 times out of 20 on the settled Instagram feed and on Business Suite home. The warm median is under 400 ms and the output is under 8 KB. After a scripted screen change, the next snapshot with the settle option shows the new screen's title.
2. Acting on a ref from an older snapshot after the screen changed returns `STALE_REF` and sends no input. A test fixture proves this, and one live run on the J7 confirms it.
3. The Business Suite scheduling dry run runs on agent-phone for both accounts. It stops before the Schedule tap and records a trace. It lists Drafts before and after, and deletes only a draft it created. Its flow code has no fixed sleeps, and a lint check fails the build if a flow calls `time.sleep`.
4. The commit gate refuses every commit action in its test table unless the caller passes `--commit`. The table covers matches on visible text, on `content-desc` and on `resource-id`.

## Choices made so far

- **Backend.** The uiautomator2 jar (`u2.jar` 0.4.1) runs from `/data/local/tmp` through `app_process`. uiautomator2's IME APK is never installed. A custom `app_process` server can replace this backend later without changing the commands, because only one module talks to it.
- **Server lifetime.** agent-phone starts the server detached on the phone and stops it after 15 idle minutes. The idle timer lives on the Mac and runs `pkill -f uia2.Main` over adb. No Mac process has to hold a stream open.
- **Language.** Python, managed with uv. uiautomator2 and the existing J7 scripts are Python. Lorenzo approved the plan with this default on 2026-10-31.
- **Clicks.** In AOSP UiAutomator, `UiObject.click()` injects a touch at the element's center instead of calling the accessibility click action. I have not checked this inside `u2.jar`, so unit 4 checks it. Until then, every click reports `delivered_unverified` and the agent confirms it by reading the screen again. `set-text` uses `ACTION_SET_TEXT`.
- **Types.** pstack runs its architect step, with an Opus and a Fable runner, for data shapes that later code depends on. The ref fingerprint and the delivery result are those shapes, so unit 1 runs it once.

## Units, in order

Each unit ends in a check that has to pass before the next unit starts.

0. **Repo.** uv project, ruff, pytest, the layout from agent-desktop (`core/`, `adapters/`, `cli/`, `probes/android/` with `FINDINGS.md`, `AGENTS.md`), the gate that keeps core free of backend imports, and the lint that rejects `time.sleep`. Check: `uv run pytest` and the lint pass, and each gate fails when a violation is planted.
1. **Types.** Settle `Snapshot`, `Node`, the role list, `Ref`, the stored fingerprint for finding an element again, the result envelope, `Disposition`, the error codes, and the commit gate's policy shape. Check: a golden test turns redacted Instagram and Business Suite fixtures into the expected snapshots.
2. **Server lifetime and lock.** Start, health-check, idle stop, and one lock file so only one process drives the phone. Check: over 20 warm calls, the median `snapshot` is under 400 ms, and the server is gone 15 minutes after the last call.
3. **Reading.** `snapshot -i --compact`, `--skeleton`, `--root`, `--settle`, then `find`, `get` and `is`, and the first agent skill under `skills/`. Then pstack's `create-verification-skill` writes a project skill that drives the real phone through the CLI, so every later unit proves its change on the J7 the same way. Check: done-when 1 on the live J7, plus golden tests.
4. **Actions.** `click`, `set-text`, `scroll`, `back` and `launch`. Each one finds the ref again first, checks the target (visible, enabled, same bounds on two reads) and returns a delivery result. The commit gate sits here. Check: done-when 2 and 4.
5. **Waiting.** `wait --text`, `wait --gone`, and `--wait-for` on actions. Check: a script opens a known sheet and reads it with no sleeps.
6. **Batch and trace.** Several commands in one call, and one JSONL trace per run. Check: a three-step batch runs in one call, and its trace lists each step with its delivery result.
7. **Port the scheduling dry run.** First time one run of today's dry run, so there is a measured baseline. Then port it. Check: done-when 3, and wall time compared with that baseline.
8. **MCP server (optional).** The same commands as MCP tools, so Grok can call them as well as Claude Code. Claude Code can already call the CLI from Bash, so this unit only earns its place if the Grok pipeline moves onto agent-phone. Lorenzo decides.

My rough guess is one to two days of agent time. Units 1 and 4 carry most of the risk.

Each unit lands as one or more Conventional Commits that each pass the full test suite and lint, in an order that reads as an argument. `AGENTS.md` holds the commit rules.

## Rigor

Rigor is high wherever the tool sends input. A wrong tap can post or schedule on the accounts, and that cannot be undone. Reading the screen changes nothing, so the reading units get golden tests and a live check without extra review.

A list of forbidden labels cannot be complete. Buttons can be labeled only by `content-desc` or `resource-id`, and "Share reel", "Send", "Confirm" and "Unfollow" also commit. Unit 1 therefore designs the gate as a policy, not a list. One option is that a flow declares its only commit step, and in tests every tap must target an element the flow declared. Unit 4 then tests it against the full table.

## Safety rules

- Never send a commit action without `--commit`. Tests never pass it.
- Never force-stop SocksTun (`hev.sockstun`) or change VPN settings. With always-on lockdown, a dead tunnel takes the phone offline.
- Install nothing on the phone. The jar in `/data/local/tmp` is the only footprint. `/data` has 525 MB free.
- Raw dumps contain the account's feed. Keep them out of git and commit only redacted fixtures.
- Only one process drives the phone at a time. The lock covers the old scripts too, because their dumps fail while the server runs.
- Every benchmark or test that opens an app on the phone writes that side effect to `decisions.tsv`.

## Open calls for Lorenzo

- Whether unit 8 (MCP for Grok) is worth building, which depends on moving `publishing-ana-reels` and the Grok pipeline onto agent-phone.
