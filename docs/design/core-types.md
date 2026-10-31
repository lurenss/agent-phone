# agent-phone core types and module map

## Problem

An agent on a computer drives any Android phone (API 24+) one CLI process per command. Each process reads the screen through a backend that returns every window (A2-4) and does not wait for the screen to settle (A2-5). The phone may run live accounts, where a wrong tap posts, sends or deletes with no undo. Five facts make the shape non-obvious. All of them show in the four redacted fixtures.

- Labels often sit on a child. A clickable `Button` with empty `text` and `content-desc` owns the words of a plain `ViewGroup` inside it (`mbs-home.xml`). Settings tiles carry their title and summary in children (`settings-home.xml`). A gate or a name that reads one attribute of one node misses them.
- Rows share resource-ids. Four story rows share `outer_container` in `ig-feed.xml`, and six tiles share `dashboard_tile` in `settings-home.xml`. EditText content changes as it is typed. Neither is identity.
- System UI is a surface like any app. In `notification-shade.xml` the only window is `com.android.systemui`, full screen, in landscape (rotation 1). Its quick-settings tiles include "Airplane mode", which takes a VPN-lockdown phone offline.
- Each command is a new process, and several devices can be connected. Refs live on disk and must fail closed on another device, another emulator on the same port, or the same phone after a reboot.
- Commit words are also navigation and description words. "Create new post" opens a sheet. A Settings summary lists "Block, Allow". "OK" under "Delete this post?" deletes. A label list cannot be complete and usable at once.

Constraints carried in: core imports no backend, CLI or subprocess (`tests/test_architecture.py`), and core names no app (AGENTS.md "Device safety"). `time.sleep` lives only in `core/wait/`. Domain types are frozen dataclasses, closed vocabularies are enums, files stay under 400 lines, and a command is `core/commands/<name>.py`. A uiautomator2 click injects a touch at a point (`_selector.py:138` calls `session.click(x, y)`), so the screen at that point decides what a tap hits, not the selector that found it.

## Usage (caller's view)

### An agent at the CLI

```
$ agent-phone devices
{"v":1,"ok":true,"command":"devices","data":{"devices":[
 {"serial":"0a1b2c3d4e5f6a7b","model":"SM-J730F","api":28,"abi":"armeabi-v7a","display":[1080,1920],"profile":"j7"},
 {"serial":"emulator-5554","model":"<read>","api":34,"abi":"x86_64","display":[1080,2400],"profile":null}]}}
```

Two devices are connected, so every command that has no ref needs `-d`.

```
$ agent-phone -d 0a1b2c3d4e5f6a7b snapshot
{"v":1,"ok":true,"command":"snapshot","device":"0a1b2c3d4e5f6a7b","data":{
 "id":"q7m2k","app":"com.android.settings","window":"application","settled":"unchecked",
 "keyboard":false,"dialog":false,"others":[],"truncated":0,
 "tree":[
  "text \"Settings\"",
  "@q7m2k:e1 button \"Search\" [1648,0,1775,147]",
  "@q7m2k:e2 button \"Samsung account profile\" [1775,0,1920,147]",
  "@q7m2k:e3 list #dashboard_container (4 rows) [0,179,1920,1080]",
  "  @q7m2k:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" [0,179,1920,394]",
  "  @q7m2k:e5 button \"Sounds and vibration\" \"Sound mode, Ringtone, Volume\" [0,436,1920,653]",
  "  @q7m2k:e6 button \"Notifications\" \"Block, Allow, Do not disturb\" [0,653,1920,868]",
  "  @q7m2k:e7 button \"Display\" \"Brightness, Blue light filter, Home scre…\" [0,910,1920,1080]"]}}
```

Each tile takes its child title as its name and its summary as its detail, and the children print no lines of their own. The bounds are landscape bounds, because the snapshot reads the rotation from the dump.

```
$ agent-phone click @q7m2k:e6 --wait-for 'name=Do not disturb'
{"v":1,"ok":true,"command":"click","device":"0a1b2c3d4e5f6a7b",
 "delivery":"delivered_verified","retry":"unsafe",
 "data":{"target":{"ref":"@q7m2k:e6","role":"button","name":"Notifications","at":[960,760]},
  "gate":{"verdict":"clear","reason":"no_commit_words"},
  "verified_by":"present name=\"Do not disturb\"",
  "after":{"id":"r2c8w","app":"com.android.settings","tree":["..."]}}}
```

The tile's summary says "Block". The default policy ignores labels from `android:id/summary` nodes, so the engine reads only "Notifications". The command needs no `-d`, because the ref names its device.

```
$ agent-phone click @q7m2k:e4
{"v":1,"ok":false,"command":"click","device":"0a1b2c3d4e5f6a7b",
 "delivery":"not_delivered","retry":"safe",
 "error":{"code":"STALE_REF","message":"@q7m2k:e4 is from a snapshot taken before the last input. Use a ref from r2c8w.",
  "details":{"reason":"spent"}}}

$ agent-phone -d emulator-5554 click @r2c8w:e3
... "error":{"code":"WRONG_DEVICE","message":"@r2c8w:e3 belongs to 0a1b2c3d4e5f6a7b.", ...}
```

Every input spends every ref taken before it. The agent cannot repeat a tap without looking again. An input that the backend proves never left refunds the spend, so `not_delivered` is the only result after which the same command works again. After a reboot, refs from the old boot fail with `STALE_REF` reason `rebooted`.

```
$ agent-phone -d 0a1b2c3d4e5f6a7b snapshot          # the shade is pulled down
 ... "app":"com.android.systemui","window":"system", ...
  "@k3x9q:e14 button \"Airplane mode Off.\" [998,203,1114,307]", ...

$ agent-phone click @k3x9q:e14 --commit system
{"v":1,"ok":false,"command":"click","delivery":"not_delivered","retry":"safe",
 "error":{"code":"DENIED","message":"Rule j7.vpn-lockdown denies this input: always-on lockdown VPN, turning off the network takes the phone offline.",
  "details":{"rule":"j7.vpn-lockdown","source":"~/.agent-phone/profiles/j7.toml"}}}

$ agent-phone -d 0a1b2c3d4e5f6a7b stop hev.sockstun
... "error":{"code":"DENIED","details":{"rule":"profile.protect.hev.sockstun.stop"}}

$ agent-phone click @m9q4t:e21
... "error":{"code":"COMMIT_REFUSED","message":"This tap would schedule (\"Schedule reel\"). It is sent only with --commit schedule. Grant it only when your user asked for this commit.",
  "details":{"effects":["schedule"],"granted":[],"evidence":[{"rule":"default.schedule","source":"receiver","label":"Schedule reel"}]}}

$ agent-phone click @m9q4t:e21 --commit publish
... COMMIT_REFUSED, "effects":["schedule"], "granted":["publish"]
```

`--commit` names the effect it grants, out of a closed set (publish, schedule, send, delete, purchase, social, system, confirm, unlabeled). A grant for `publish` does not open a `schedule` tap. A deny rule cannot be granted at all.

### A consumer outside core

`examples/business_suite/schedule.py` drives Meta Business Suite through the public API only. Its app knowledge lives in that file and in `examples/business_suite/policy.toml`.

```python
from agent_phone import Effect, Gone, Match, Present, Q, Role, open_phone

POLICY = Path(__file__).with_name("policy.toml")


def schedule_reel(serial: str | None, caption: str, at: PhoneTime, dry_run: bool) -> str:
    with open_phone(serial, policies=[POLICY]) as phone:  # holds the device lock for the run
        phone.launch("com.facebook.pages.app", wait_for=Present(Q("Create new post")))
        sheet = phone.click(Q("Create new post"), wait_for=Present(Q("Create new content"))).after
        reel = sheet.pick(Q("Reel", role=Role.BUTTON), below=Q("Create new content"))
        phone.click(reel, wait_for=Present(Q("Create reel with Video, item 1", match=Match.PREFIX)))
        ...
        phone.set_text(Q("Describe your reel", role=Role.TEXT_FIELD), caption)
        phone.click(Q("Schedule for later"), wait_for=Present(Q("SCHEDULE")))
        ...
        if dry_run:
            phone.click(Q("CANCEL"), wait_for=Gone(Q("SCHEDULE")))
            phone.click(Q("Discard"), commit=Effect.DELETE, wait_for=Present(Q("Create new post")))
            return "dry_run"
        phone.click(Q("SCHEDULE"), commit=Effect.SCHEDULE, wait_for=Present(Q("Schedule reel")))
        done = phone.click(Q("Schedule reel"), commit=Effect.SCHEDULE, wait_for=Gone(Q("Schedule reel")))
        return done.disposition.value
```

```toml
# examples/business_suite/policy.toml
[[exempt]]
id = "mbs.schedule-for-later"
packages = ["com.facebook.pages.app"]
labels = ["Schedule for later"]
reason = "Opens the date and time dialog. Nothing is scheduled before SCHEDULE and Schedule reel."
```

A `Driver` method returns the outcome when it succeeds and raises `PhoneError(outcome)` otherwise. The outcome carries the code and the disposition. Each `wait_for` replaces a fixed sleep from the old script. Each wait also records the observation that the next step needs, because an input with no observation since the last input is refused with `OBSERVE_FIRST`.

### Tests that call core directly

```python
def test_settings_home_golden():
    screen = parse_hierarchy(
        read("tests/fixtures/dumps/settings-home.xml"), Size(1080, 1920), ime_package=None
    )
    view = fit(build_view(select_surface(screen), Mode.COMPACT), SnapshotId("t0000"))
    assert render(view, SnapshotId("t0000")) == golden("settings-home.compact")


def test_dry_run_sends_nothing_but_discard():
    fake = FakePhone.from_script("tests/fixtures/flows/mbs-dry-run")
    run_example(fake, dry_run=True)
    assert {e for p in fake.permits for e in effects(p.verdict)} <= {Effect.DELETE}
```

The second test is the plan's "every tap must target an element the consumer declared". Each permit records the verdict the engine gave, so the test reads what was really sent.

## Shape

### Data structures

- `Screen` (`core/screen.py`) is one read of every window as a flat pre-order arena. A node's subtree is the slice `nodes[id:end]`, ancestors follow `parent`, and hit tests descend `children`. Adapters hand over nested `WindowSpec` trees, and `Screen.build` owns the indexing, so no adapter re-implements it. `Window` carries `kind`, `active` and `layer`, with `layer` None when the backend cannot read it.
- `Surface` (`core/labels.py`, the label surface) is every label string an element owns, each with its field and its source node's resource-id. It holds the element's own label fields plus those of descendants that are not inside a nested touch consumer. The display name, the stable name in the fingerprint, `Query` matching and the policy engine all read this one function. A test pins that every `str` field of `Attrs` is either a label field or declared non-label, so a new attribute cannot bypass the engine.
- `Snapshot` (`core/snapshot/snapshot.py`) is the printed lines plus the fingerprints, the `DeviceIdentity` (serial and boot id) and the ledger epoch it was taken at. The same frozen value is printed, persisted and read back. Nothing is recomputed or synced.
- `Fingerprint` (`core/refs/fingerprint.py`) is a whole-value `Key`: package, window kind, role, class, resource-id, stable name, and the stable labels of the collection row. When two surface nodes share a key, a `Twin` stores the ordinal and the bounds of the whole twin set, and position counts as identity only while that set is geometrically unchanged. The same rule covers nameless icons and Compose `View`s, which resolve only on an unchanged screen.
- `Ledger` (`core/act/ledger.py`) is one epoch counter per device. It is the only constructor of `Permit`.
- `Policy` (`core/policy/rules.py`) is a tuple of rules of five kinds (`commit`, `exempt`, `ignore`, `inherit`, `deny`), parsed from TOML at the boundary. `Verdict` is `Clear | Commits(effects) | Denied(rule)`, and `Grant` is a set of `Effect`s.
- `Outcome` (`core/outcome.py`) is `Refused | Acted | Read`. `Acted.sent` is a `SentState`, which has no not-delivered member.

### Flow

Every input runs `act()` (`core/act/act.py`). It resolves the target, checks that the node is actionable and stable, plans the input, judges it, spends a permit, injects, and verifies. Each step before the spend raises `Refusal` and leaves the device untouched. Everything after `inject` is caught and reported as `Acted`. Reads run `observe()` (`core/wait/observe.py`) and `capture()` (`core/snapshot/capture.py`), so `snapshot`, `wait`, auto-wait and act-then-wait share one polling loop and one way to record what was seen.

### Load-bearing decision 1: the ledger makes the retry rule structural

A snapshot records the ledger epoch. Resolution refuses any target whose observation is older than the current epoch. A ref or point fails with `STALE_REF` reason `spent`, and a query or a targetless input fails with `OBSERVE_FIRST`. Spending a permit writes epoch+1 to disk (temp file, fsync, rename) before the permit exists. Only `NotSent`, the adapter's proof that nothing left, refunds the epoch. So:

- the only disposition after which the same command works again is `not_delivered`, and this holds for agents that never read `retry`;
- a crash between spend and inject leaves the refs spent, which is the safe side (per make-operations-idempotent);
- `Refused` always serializes `not_delivered`, and `Acted` cannot serialize it, because `SentState` lacks the member (per type-system-discipline);
- an exception nothing caught is reported `delivery_uncertain` when the ledger shows an unrefunded spend in this process, else `not_delivered`;
- two AST tests pin that `Permit(` appears only in `ledger.py` and `.inject(` only in `act.py` (per encode-lessons-in-structure).

### Load-bearing decision 2: the engine judges the receiver at the planned point

The engine never sees how the caller named the target. `hit.plan_point` picks a point where Android's dispatch, children in reverse drawing order and deepest consumer first, hands the touch to exactly the target, and no other window covers the point. The engine then classifies that receiver's whole label surface. A ref, a text query, a resource-id query and a raw point that land on the same node get the same verdict. Neutral affirmatives ("OK", "Yes") take the effects of their dialog's text. An unnamed receiver commits `unlabeled`. A device language outside `policy.languages` refuses labeled input with `LOCALE_UNSUPPORTED` instead of reading a screen it cannot read. The engine is a pure function of (policy, action, site, language), and `commit_table.toml` tests it with every phrase planted in each label field.

### Device identity and multi-device state

`DeviceIdentity` is serial plus `/proc/sys/kernel/random/boot_id`, read once per process in the same `adb shell` round trip as API level, ABI, display size, density, locale and IME. Snapshot files live under `devices/<serial>/`, so processes driving two devices write disjoint files. A lookup by id searches every device directory read-only, which turns a ref used with the wrong `-d` into `WRONG_DEVICE` instead of "not found" (per separate-before-serializing-shared-state). One lock per device serializes writers within a device (A3-4).

### Where validation lives

Adapters parse XML and adb output into core types (`adapters/uiautomator2/parse.py`, `shell.py`). `parse_policy` validates each policy file and names the file, table and field it rejects. `RefToken.parse` rejects a bare `e12`. Inside core nothing validates again (per boundary-discipline).

### What it deliberately does not do

No input through the keyboard, because the IME APK is never installed (A3-1). No retries inside a backend's `inject`. No coordinate input without a snapshot to bind it to. No input to a non-active window. No app names in core. The one package list in the backend is `PLATFORM_UI` (`android`, `com.android.systemui`) in the uiautomator2 parser, because that dump has no window type to read.

### Interface depth

The backend `Phone` protocol has six methods, and only `read` and `inject` carry the work. The public `Driver` has one method per command, and each returns the same outcome the CLI prints. Behind `click` sit resolution, twin geometry, auto-wait, hit testing, the policy engine, the ledger and verification. The caller passes a target, an optional effect grant and optional wait predicates.

### Module map

```
agent_phone/core/
  geometry.py device.py screen.py role.py labels.py query.py
  outcome.py envelope.py phone.py context.py
  snapshot/  surface.py view.py budget.py snapshot.py capture.py
  refs/      fingerprint.py resolve.py store.py
  policy/    rules.py engine.py
  act/       intent.py hit.py ledger.py act.py
  wait/      clock.py predicate.py observe.py
  commands/  snapshot.py click.py set_text.py press.py stop.py wait.py screenshot.py devices.py
agent_phone/adapters/uiautomator2/  phone.py parse.py rpc.py delivery.py address.py shell.py
agent_phone/cli/driver.py           the one wiring point, for main() and in-process consumers
agent_phone/policy/default.toml     built-in rules, package data, no app names
examples/business_suite/  examples/instagram/policy.toml  examples/devices/j7.toml
```

`scroll`, `launch`, `open-url`, `rotate`, `power` and `clipboard` commands have the shape of `press.py`. The input types for all of them already exist in `core/phone.py`. A click traces through three files: `commands/click.py`, `act/act.py`, and the module act calls.

### Evidence from the four fixtures (measured)

`check/fixture_check.py` is a throwaway prototype of the view, key and default-policy rules. I ran it with `uv run python -I check/fixture_check.py tests/fixtures/dumps sketch/agent_phone/policy/default.toml`.

| Fixture | Nodes | Refs | Compact lines | Bytes | Refs sharing a resource-id | Twin keys |
|---|---|---|---|---|---|---|
| ig-feed | 150 | 26 | 29 | 1,488 | 5 | 0 |
| mbs-home | 108 | 18 | 18 | 967 | 0 | 0 |
| notification-shade | 158 | 31 | 39 | 1,895 | 0 | 10 |
| settings-home | 50 | 7 | 8 | 397 | 4 | 0 |

Every compact snapshot fits in a quarter of the 8 KB budget. The row key separates every ref that shares a resource-id, so none of them needs twin geometry. The 10 twin keys in the shade are nameless clickable wrappers around the tiles. `view.py` folds such wrappers into the named tile, a rule the prototype does not implement yet. The first run showed that an unanchored "post" committed "More actions for this post" and "Create new post". An anchored `^post` in `default.toml` cleared both without an exemption. With that change, the default policy flags "Follow" (social), "Airplane mode" and "Mobile data" (system), notification "Clear" (delete, from the id `clear_all`), and the nameless icons (unlabeled). It flags nothing on Settings home. A second run without the `android:id/summary` ignore rule flagged "Connections" as system (its summary says "Airplane mode") and "Notifications" as social ("Block").

## Synthesis decision

Two runners designed this from one brief in pstack's architect step, one on Opus and one on Fable. Both received the same mid-run change that made agent-phone a general Android framework. The cross-judge was skipped, because arena wants a judge from a model family other than the parent's, and both runners and the parent are Claude.

The candidates converged on most of the shape: core resolves refs as a pure function over a full live screen read, device identity is the adb serial plus the boot id, commit rules are TOML data, delivery and retry are encoded so that delivered input can never claim a safe retry, all waits share one polling loop, and snapshots are immutable files written once. That agreement is strong evidence for those choices.

The Opus candidate is the base. Scored against the picker rubric, it was stronger on fail-closed identity (the per-device ledger spends every older ref on input, and twin geometry separates rows that share an id), on the commit gate (it judges the receiver at the planned touch point and reads labels from children), and on snapshot fit (a prototype measured all four fixtures at 0.4 to 1.9 KB). The Fable candidate was stronger on interface size and readability.

One fact settled the largest difference. Fable kept the uiautomator2 Python package in the adapter, and Opus speaks JSON-RPC itself. `uiautomator2.core.Device.jsonrpc_call` catches an HTTP or connection error, restarts the server, and sends the same call again (`A2-6`). A tap whose response was lost would land twice. The adapter therefore sends every input exactly once through its own client.

Grafted from Fable:

- A `Query` that matches more than one live node is `AMBIGUOUS_TARGET`. It never resolves to the first match. Fable's `find_one` stated this rule for consumers. Here it holds for every target.
- Fable's open questions on window order, `UiSelector.instance` order, ENTER as a commit, and toast visibility join the list below.

Rejected from Fable: binding `--commit` to a label. A grant names an effect from a closed set instead, and a commit result echoes the label it committed, so the agent still sees what it authorized.

## Tradeoffs accepted

- We accept one extra read after every input, because the next input needs an observation, in exchange for a retry rule that holds even for an agent that ignores `retry`. Act-then-wait already records that read, so a careful flow pays nothing extra.
- We accept false positives from conservative words, such as the Business Suite "Suggested" card committing `publish` and `schedule` from its description, in exchange for no false negatives from labels on children or ids. Exemptions are data with a reason and a rule id.
- We accept that `^post` misses a commit button labeled "Tap to post", in exchange for not flagging every "post" noun. The anchor is per phrase, so a policy file can add an unanchored rule for one app.
- We accept `LOCALE_UNSUPPORTED` on a phone whose language has no rules, in exchange for never judging words the engine cannot read.
- We accept refusing input to any point that a window of unknown stacking covers, in exchange for never tapping through a popup we cannot see the order of. The uiautomator2 dump has no layers, so this refusal is common until a richer backend reports them.
- We accept two ways to name a target, a ref and a query, in exchange for one-call actions and for batch steps whose targets do not exist yet. Both go through one `Query` matcher and one observation check, and `Snapshot.pick` turns a query into a ref when the caller wants to pin what it saw.
- We accept thin input command modules, because AGENTS.md wants one file per command and act() is the deep module behind all of them.
- We accept that the uiautomator2 adapter speaks JSON-RPC itself instead of importing the uiautomator2 package, in exchange for no library retries on input and less import time per CLI call.

## Alternatives considered

- **Refs as self-contained tokens.** The token would encode the fingerprint, with no store. This lost because tokens grow to hundreds of bytes against the 8 KB budget, and a token cannot be revoked, so "spent after input" would need a store anyway. The retry rule would fall back to the agent reading `retry`.
- **A gate that reads the caller's selector or the ref's own attributes.** It is the smallest interface. It lost because a caller bypasses it by naming the element another way, by a point, or by a ref to the row around the button. It also misses words on children, and the fixtures show those are the common case.
- **A long-lived daemon per device that holds refs in memory.** It would remove process start and disk state. It lost because the plan keeps no process holding a stream, refs would die with the daemon, and in-process consumers get the same speed from one `Driver` across their run.
- **Identity as the rendered line.** "eN still prints the same line" is simple and matches what the agent saw. It lost because one node inserted above a ref renumbers every ref below it, so live feeds would stale constantly. Twins would be indistinguishable beyond their ordinal.

## Open questions and risks

- Is the dump's window order stable? Fable read that `UiDevice.getWindowRoots` builds a `HashSet`, and Opus read that it puts the active root first. Unit 3 captures a dialog over an app before `hit.py` relies on either reading.
- Does `UiSelector.instance` count nodes in the dump's document order? `adapters/uiautomator2/address.py` depends on it.
- Should ENTER commit by default? It is strict for a search field. A per-app `exempt` rule may be enough relief.
- The server only sees toasts shown while it runs. Is that enough for a toast predicate, or does it leave unit 5?
- The hit test refuses a point that a window of unknown stacking covers. On a dialog over an app, the app window covers every dialog point, so the rule must not refuse input to the active window itself. Unit 4 settles it with a probe.

- Is the first window in the uiautomator2 dump always the active one? The fixtures agree, and androidx `UiDevice.getWindowRoots` puts the active root first, but no fixture has a dialog over an app. Unit 3 should capture one before `hit.py` relies on it.
- Should a permission dialog's "Allow" count as a commit? The default treats it as an affirmative that inherits its dialog's words, and permission text rarely contains a commit word, so it passes as clear today.
- Is `--commit <effect>` acceptable in place of the bare `--commit` that AGENTS.md and the plan name? I think the effect name is the safer contract, because a grant for one effect cannot open another.
- Does the Business Suite time picker's dialog contain "Schedule" in its title? If it does, its "OK" inherits `schedule`, and the dry run stops with `COMMIT_REFUSED`. That failure is safe, and an exemption fixes it once a capture shows the title.
- Can a profile deny rule be too broad? `j7.vpn-lockdown` also refuses opening the VPN entry in Settings. That matches "never change VPN settings", but Lorenzo may want reading it allowed.
- Does a semantic-click backend need its own hit test? `Activate` skips the point entirely, so the engine judges the node itself. That is correct only while the backend clicks the node and not its center.

## Next implementation step

Write `Screen.build`, `labels.surface_of` and `build_view`, then turn the four fixtures into golden compact snapshots, which is the plan's unit 1 check.
