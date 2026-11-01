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
  "text \"Settings\" [63,33,277,114]",
  "@q7m2k:e1 button \"Search\" [1648,0,1775,147]",
  "@q7m2k:e2 button \"Samsung account profile\" [1775,0,1920,147]",
  "@q7m2k:e3 list #dashboard_container (4 rows) [0,179,1920,1080]",
  "  @q7m2k:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" focused [0,179,1920,394]",
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
  "@k3x9q:e8 button \"Airplane mode Off.\" [998,203,1114,307]", ...

$ agent-phone click @k3x9q:e8 --commit system
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
- `Policy` (`core/policy/model.py`, read and layered by `rules.py`) is a tuple of rules of five kinds (`commit`, `exempt`, `ignore`, `inherit`, `deny`), parsed from TOML at the boundary. `Verdict` is `Clear | Commits(effects) | Denied(rule)`, and `Grant` is a set of `Effect`s.
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

The backend `Phone` protocol has seven methods, and only `read` and `inject` carry the work. `PhoneHub` lists devices, reads a device's facts, hands out the handle for its on-device server and opens it. The public `Driver` has one method per command, and each returns the same outcome the CLI prints. Behind `click` sit resolution, twin geometry, auto-wait, hit testing, the policy engine, the ledger and verification. The caller passes a target, an optional effect grant and optional wait predicates.

### Module map

```
agent_phone/core/
  geometry.py device.py screen.py role.py labels.py query.py
  outcome.py envelope.py phone.py context.py
  snapshot/  surface.py view.py budget.py snapshot.py capture.py
  refs/      fingerprint.py resolve.py store.py   (store.py also holds the device lock)
  policy/    model.py rules.py reads.py engine.py
  act/       intent.py hit.py axis.py site.py ledger.py act.py
  wait/      clock.py predicate.py observe.py until.py
  commands/  snapshot.py click.py set_text.py press.py stop.py wait.py screenshot.py devices.py server.py
agent_phone/adapters/uiautomator2/  phone.py parse.py rpc.py delivery.py address.py shell.py adb.py server.py
agent_phone/cli/driver.py           the one wiring point, for main() and in-process consumers
agent_phone/cli/                    args.py (arguments), commands.py (the command dataclasses a Driver runs), process.py (envelope and exit code), settings.py (environment)
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

- Is the dump's window order stable? Fable read that `UiDevice.getWindowRoots` builds a `HashSet`, and Opus read that it puts the active root first. Answered for one or two windows (A2-7): with a dialog over an app, and without, the first window was the one Android reported as focused, on 20 of 20 reads each. The same row records that a dialog hides the app beneath it from the dump. Three or more windows, such as a keyboard over an app, are still unobserved.
- Does `UiSelector.instance` count nodes in the dump's document order? Answered by not depending on it: `address.pin` reads every instance's bounds and sends the one instance whose bounds equal the dump's. The selector it sends always carries that instance, because without one the server's `setText` taps the field before it types (A2-12).
- Should ENTER commit by default? It is strict for a search field. A per-app `exempt` rule may be enough relief.
- The server only sees toasts shown while it runs. Is that enough for a toast predicate, or does it leave unit 5?
- The hit test refuses a point that a window of unknown stacking covers. Settled for unit 4. A dialog over an app leaves only the dialog and the status bar in the dump (A2-7), so no other window covers a dialog point, and `tests/test_hit.py` taps the dialog fixture's buttons at their centers. The keyboard is a window of its own over the app, so a ref under it is OCCLUDED and a ref above it is tapped. That is tested on a synthetic dump only, because no live check may type.

- Should a permission dialog's "Allow" count as a commit? The default treats it as an affirmative that inherits its dialog's words, and permission text rarely contains a commit word, so it passes as clear today.
- Is `--commit <effect>` acceptable in place of the bare `--commit` that AGENTS.md and the plan name? I think the effect name is the safer contract, because a grant for one effect cannot open another.
- Does the Business Suite time picker's dialog contain "Schedule" in its title? If it does, its "OK" inherits `schedule`, and the dry run stops with `COMMIT_REFUSED`. That failure is safe, and an exemption fixes it once a capture shows the title.
- Can a profile deny rule be too broad? `j7.vpn-lockdown` also refuses opening the VPN entry in Settings. That matches "never change VPN settings", but Lorenzo may want reading it allowed.
- Does a semantic-click backend need its own hit test? `Activate` skips the point entirely, so the engine judges the node itself. That is correct only while the backend clicks the node and not its center. The uiautomator2 jar has no semantic click (A2-11), so act() never plans `Activate` today.
- What protects a phone whose profile is missing? Nothing beyond the default rules. A profile applies only from the state root a command uses and only to the serial it names, so another `AGENT_PHONE_HOME` or a mistyped serial leaves the J7's tunnel unprotected. `devices` prints the profile that applies, and an agent should check it before it drives a phone it knows.
- Can a ref match a look-alike? A ref with no twin in its snapshot resolves to the one live element with its key. On a screen that moves on its own, such as Stories, that can be the same control of the next item. The row key staled nothing on static screens (A5-8). A feed is unmeasured.
- Can a link commit? The engine judges a link by its scheme, so `tel:` and `sms:` need `--commit send`. A deep link into an app does whatever that app chooses, and its scheme says nothing about that. A consumer that opens deep links should name their schemes in a commit rule.
- Can a scroll commit? A swipe starts on a row of the list. A vertical swipe scrolls, but a horizontal swipe on a list whose rows dismiss on a swipe, such as the notification shade, can delete a row. The engine reads a swipe with deny rules only, and the axis rule below refuses the swipes that can dismiss a row. The live checks scroll Settings lists only.

## What unit 4 changed from this sketch

- **Set-text sends no touch.** The jar's selector `setText` taps the field's center first unless the selector names an instance (A2-12). The adapter always names one, so a set-text commits nothing. The review of unit 4 still gives it a site, because a deny rule can name its screen (see the end of this document).
- **Deny rules read every label.** Commit rules read what `ignore` and `exempt` leave, but deny rules read the receiver's whole surface and its whole context, so a consumer's file cannot weaken a profile's deny rule by ignoring or exempting its words. On the J7 this denies the Settings tile `Connections`, whose summary names airplane mode.
- **A lost UiAutomation connection is not `NotSent`.** The sketch's delivery table guessed it was, and marked the guess for a device check. A click is a touch down and a touch up (A2-11), and nothing shows that losing the connection between the two sent neither, so it stays `Sent(UNACKNOWLEDGED)`. A shell that printed that nothing started, such as `am start` with no matching activity, is `NotSent`.
- **An intent is an intent URI.** `OpenUri` keeps its shape. `intent:#Intent;action=<action>;end`, with an optional `package=`, opens an action, and an intent URI with data, a component, extras or flags is INVALID_ARGS, so `open-url` cannot start a call or pass arguments the engine never saw.
- **Targetless inputs are judged at the focused window.** A key, a launch or a link gets a `Site` with the package and window kind of the newest snapshot and no receiver, so a rule scoped to an app applies to its keys too. Enter is the exception that the review of unit 4 added: it gets the focused view as its receiver.
- **The process keeps its unrefunded spends.** `ledger.unrefunded()` reads a list the ledger keeps for the whole process, because an exception that escaped a command can no longer reach the `Ledger` that spent the permit.
- **`protect_rules` takes the profile file's path**, so a denial names the file it came from.
- **Only a clickable view takes a touch.** The hit plan uses `role.takes_touch`, clickable or long-clickable, as `View.onTouchEvent` does. A checkable switch that is not clickable passes the touch to its row, so a click on it is NOT_ACTIONABLE and the row is judged by its own words. `consumes_touch` still decides whose words a label is.
- **A toggle reads its row.** A tap on a switch, a checkbox or a radio is judged with the words of its row, because the toggle often says only "On" or "Off".
- **Every other window at the point covers it.** The sketch let an inactive full-screen application window lie below. A full-screen overlay without focus lies above, and the uiautomator2 dump cannot tell the two apart. A node the dump marks invisible still takes part in dispatch, because a view at alpha 0 still takes touches.
- **A sideways scroll needs a collection that runs across**: a pager, a horizontal scroll view, or rows side by side. On a list that runs down it is NOT_ACTIONABLE, because a sideways swipe on a row can call or dismiss.
- **A denial reads what a consumer's file cannot weaken.** f526ec0 kept a disabled commit rule as `withdrawn`, so disabling `default.system` could not switch off a profile's protection. That covered the words in the receiver and nothing else. A neutral OK gets its effect from its dialog's words, a key from a key rule and a link from a scheme rule, and those paths read only the rules still in force. So a consumer's `disable = ["default.delete"]`, or an exempt rule for "OK", or an ignore rule for the OK button's id, let the OK of "uninstall SafeTunnel?" through with no `--commit`, and a disabled key rule let Enter through a profile that says it never sends. `withdrawn` is gone. `Policy.strict` replaces it: every commit rule and every inherit rule that any layer loaded, and the exempt and ignore rules of trusted layers only. The engine runs one function, `effects_of`, once on the rules in force for the verdict and once on `strict` for the effects a denial checks, so every path gets the same reading. Consumers may weaken a commit and never a denial.
- **A raise inside `inject` is `Acted` with `delivery_uncertain`**, and the process reports any refusal that escapes after an unrefunded spend the same way.

## What the review of unit 4 changed

Two reviewers, one on Opus and one on Fable, broke unit 4 in nine verified ways. Seven let an input past the commit gate or a deny rule. The fixes below each came with a failing test first, so the history reads as an argument. The lesson behind three of them is `docs/solutions/a-rule-sees-only-what-the-pipeline-hands-it.md`.

- **Every input that lands on something is judged by what it lands on.** `act/site.py` builds a `Site` for a tap, a set-text, a scroll and Enter. Before, only a tap had one, so a deny rule that read words or a screen never saw the others. On the J7, SocksTun's own screen denied a tap and sent a set-text, a scroll and Enter. A set-text and a scroll are read by deny rules only (`reads.reads_of`), because typing and scrolling commit nothing, and a composer whose hint says "Send a message" must not need `--commit send`. Neither gets the locale guard, which exists because commit words cannot be read in a language the policy does not cover.
- **Enter is judged like a tap on the view that has focus.** Android hands Enter to the focused view, and a focused clickable view clicks on it. The receiver is the focused node of the active window, with its surface and its context, so `--commit send` no longer presses a focused "Delete". Commit rules read it together with `default.key.enter`, deny rules read it, and the locale guard applies. With nothing in focus the receiver is None and the context is every label of the window, so a rule that names the screen still sees it. With no active window nothing can hold focus, and the site stays the one the newest snapshot gives.
- **Back, home and recents stay unjudged.** They have no receiver and no context. They are the agent's way off a screen, and a deny rule that traps the agent on the screen is worse than the screen. Launch, stop, a link, a rotation and the clipboard act on no element of the screen and stay as they were.
- **The gate's label ownership stops at the node that takes the touch.** `labels.surface_of` and `hit.context_labels` stopped at any touch consumer (`role.consumes_touch`), which also counts a checkable node, while the hit plan hands the touch to a clickable or long-clickable one (`role.takes_touch`). So a clickable row that holds a checkable, non-clickable child, as AOSP's preference switch does, received the tap while the child's words were judged for nobody. A "Delete all" or "Mobile data" in the child was neither a commit nor a denial. Both now use `takes_touch`, so the child's words belong to the row that receives the touch. The snapshot keeps `consumes_touch` for the names it prints (`labels.display_name`), because a checkable node still prints a line of its own. Moving the printed tree to the gate's rule is a separate change and stays out of this pass. I checked what it would do: with `takes_touch` in `shown_values` every golden file still passes, and only the synthetic checkbox row changes, from a nameless `button #pref_row` to `button "Delete all" #pref_row`. A follow-up can make that one-line change, and it would also change the row's fingerprint.
- **The files a profile names are the profile's own layers.** `cli/policy.load_policy` parsed `policy_files` as a caller's file, so their deny rules were not marked as the profile's and a caller's one-line `disable = ["ig.no-live"]` turned the J7's "never go live" denial into a commit that `--commit publish` opens. A profile is the one place that says what its phone must never do, and it splits that across files, so those files get the profile's mark. A later layer that disables one of their deny rules is `POLICY_INVALID`, as it is for the profile's own. A caller's file can still disable a denial that another caller file defined.
- **Trust is a property of a layer.** The trusted layers are the package's `default.toml`, the device profile and the files the profile names, and `parse_policy(..., trusted=True)` marks them. A trusted layer's own `disable` shortens `strict` as well as the rules in force, because the device chose it. A consumer's `disable`, `exempt` and `ignore` shorten only the rules in force. The same mark replaces `DenyRule.from_profile`: a deny rule of a trusted layer cannot be disabled by a later one. There is one mechanism, set where the loader reads the file, and the tests that read `from_profile` now ask whether disabling the rule is refused.
- **A file cannot widen the languages the engine reads.** `merge` unioned `languages` from every layer, so a caller's file that held only `languages = ["de"]` switched the locale guard off, and every German commit button was read as "no commit words". The languages the guard accepts are the built-in policy's, `en` and `it`, because the base vocabulary (delete, send, buy and the rest) must exist in a language before any screen in it can be judged. A later file whose top-level `languages` names another language is `POLICY_INVALID`, and the message says the built-in vocabulary must cover it first. A rule's own `languages` scope stays allowed, because it narrows a rule and widens nothing. A consumer that needs German adds the German words to the built-in policy.
- **A link that breaks a line is refused before it is sent.** `am start` prints the intent it starts, with the link percent-decoded, before its result, and `delivery.classify_shell` took any output line that starts with "Error:" as proof that nothing started. A link such as `myapp:open%0AError:%20see%20docs` opened its activity, printed a line "Error: see docs }", and was reported `not_delivered` with `retry: safe`, after the permit had been refunded and the refs made current again. `phone.intent_of` now refuses, as `INVALID_ARGS` and so `not_delivered`, a link whose raw or percent-decoded text holds a character that `str.splitlines` splits on or any other C0 control character, before the engine judges it and before a permit is spent. `shell.Shell.run` backs it up: no word of any adb shell command may break a line, so launch, stop and a link's package are covered in the one place that builds the command, as `NotSent(INVALID_ARGS)`. The CLI already validates a package name against `NAME`, and an in-process caller does not, which is why the backstop is in the adapter. I checked the other inputs. The clipboard is a JSON-RPC call to the server and not a shell command, and `classify` reads only an error message, so the text of `clipboard set` cannot read as a shell error. Rotate has no caller text. I did not measure what `monkey` echoes for a launch, because the live run may send nothing else, and the backstop makes the question moot.
- **A vertical scroll needs a collection that runs down.** de1a797 refused a sideways scroll of a list that runs down, because a sideways swipe on a row can call or dismiss. The mirror case was open: on the recents screen the cards run across, and a vertical swipe on a card dismisses the app, but `act.ready` checked the axis for left and right only. An up or down scroll of a collection that runs across, which is a pager, a horizontal scroll view, or items side by side, is now `NOT_ACTIONABLE` with reason `wrong_axis`, and the message says to scroll left or right. A grid has items side by side and also an item entirely below another, so `hit.runs_down` keeps it scrollable up and down. Refusing it would stop an agent from scrolling a photo grid. The sideways rule keeps its earlier reading, so a grid still takes a sideways swipe, which is the old behavior and not a decision of this fix.
- **An affirmative is compared as the snapshot prints it.** `labels.cleaned` drops a trailing role word from a comma-joined description for the display name, so `content-desc="OK, Button"` prints as `button "OK"`. `engine.is_affirmative` compared the raw tokens, and `("ok", "button")` is not `("ok",)`: under "Delete this post?" the agent saw the same line for both, and the gate said delete for a text "OK" and clear for the described one. `is_affirmative` now reads the label through `cleaned`. Only this check changed. A role word beside other words ("Not OK, Button") is still no affirmative, and commit words are still matched in the raw label, where "Delete, Button" already deletes.
- **A scrolling view drawn over the target takes the touch.** The hit plan let only a clickable or long-clickable node take a touch (`takes_touch`). `ScrollView.onTouchEvent` and `RecyclerView.onTouchEvent` return true for ACTION_DOWN whenever they have a layout, so a list drawn later than the target, such as a bottom sheet's list, ate the tap, while the plan saw no taker there and aimed at the target beneath it. `hit.receiver_in` now counts a visible scrollable node as a taker unless it is the target or holds it. A row inside its own list is still reached first, because dispatch goes deepest node first, and `tests/test_hit.py` proves it for a list and for a list in a scroll view. The same rule covers a scrolling view inside the target that fills it, and a swipe that starts on another scrolling view drawn above the list. Two takers whose drawing order is unknown stay ambiguous, as before, so a scrolling view with no drawing order that overlaps the target now refuses the tap where it used to plan it. The Android half of this is framework source, not a phone run.

## What the second review of unit 4 changed

Two more reviewers, again one on Opus and one on Fable, read the fixes above and found four more root causes. Each one was closed with a failing test first. `docs/solutions/a-rule-sees-only-what-the-pipeline-hands-it.md` holds what the round taught.

- **A button keeps its own effects and takes its dialog's.** `engine.judge_receiver` read the words around a receiver only when the receiver's own words found nothing. Any rule that gave the button's own words an effect therefore hid the dialog from every denial: a consumer rule on "ok", on its class word `button` or on its resource-id `android:id/button1`, and also the built-in `default.confirm` on "Confirm" and "Submit", with no consumer file at all. The OK of "Uninstall SafeTunnel?" then carried `confirm` and not `delete`, `profile.protect.<pkg>.app-info` never fired, and `--commit confirm` sent the tap. A receiver now takes its dialog's effects when it is an affirmative, or when its own words carry `confirm` at all, and it keeps its own effects too. The verdict is the union, on the rules in force and on `strict` alike. The rules define `confirm` as "a label that does not say its effect", so a button that says "Send" and nothing else says what it does, and its question adds nothing to it. The first version read the question only when every effect was `confirm`. A consumer rule that gave a confirm word a second effect, such as `confirm -> social`, then made the button say more than confirm, and it stopped reading its question. A rule may add effects to a button, and adding one must never take the question away. In the strict reading the built-in `default.confirm` always matches, so any `confirm` keeps the question there whatever a consumer adds. So "OK" under "Delete this post?" with a consumer rule `ok -> confirm` commits `confirm` and `delete`, "Send" under the same question commits `send` alone, "Confirm and send" commits `confirm`, `send` and `delete`, and "Confirm" under "Uninstall SafeTunnel?" is `DENIED` with or without a consumer rule on it. The price is one more grant for a button such as "Confirm and send" under a question that commits.
- **A deny rule's `words` follow a button to its question.** A neutral OK took its commit effects from its dialog, but `engine.denial` read a rule's `words` in the receiver only, so a denial that names words never saw the question. On the J7, `j7.vpn-lockdown` names "mobile data", "wi-fi" and "vpn", and the OK of "Turn off mobile data?" was `Commits({system})` that `--commit system` sent, while the OK of "Turn off Wi-Fi?" was clear. `judge_receiver` now returns the labels of the question it took (`engine.Judgement.question`), and `denial` reads a rule's `words` in the receiver and in that question. The question is the union of what the rules in force and `strict` took, so a consumer's exempt of "OK" or disable of `default.affirmative` cannot hide it from a denial. The evidence names the question with `source: context`. A button that does not take its question, such as Cancel, reads its own words only, so the way out of a dialog stays open. `context_words` still reads the whole screen and is unchanged: it denies every screen that names its words, and `words` through a question denies one button.
- **The affirmatives list the verbs that take their object from the question, and the platform's positive button.** The mechanism above reaches only a button that is an affirmative, and "Turn off" under "Turn off mobile data?" was neither an affirmative nor a commit word: it was clear, and sent with no grant. `default.affirmative` now also lists "turn off", "turn on", "disable", "enable", "stop", "disconnect" and "remove", and "disattiva", "attiva", "interrompi", "disconnetti" and "rimuovi". It is data in `policy/default.toml`, as the first list was. "Disable" and "Remove" are commit words too, so such a button keeps its own `system` or `delete` and adds its question's. An `inherit` rule can now name resource-ids as well as words (`node_ids`), because `android:id/button1` is the positive button of every platform dialog whatever its label says, and the default rule names it. `android:id/` is the platform, not an app, so `tests/test_core_knows_no_app.py` still holds. A consequence that the J7 shows: "Disconnect" on SocksTun's own VPN dialog is now denied by `j7.sockstun`, which names the word in the question, before `j7.sockstun-screens`, which names the screen. Both deny it, and the earlier rule in file order reports. The commit table has an `[[affirmative]]` table with one row for each of the 28 affirmatives, planted in the four placements a user reads under a question that commits another effect, and a test fails when an affirmative is added without a row.
- **The axis is read from the children that show, and a sideways swipe avoids the rows of a list inside the collection.** `hit.runs_across` and `hit.runs_down` read the bounds of the target's own non-empty children, and three shapes got through. One attached card is no pair, so a card list that attaches only the card in view read as a list that runs down, and an up or down scroll of recents went out as the swipe that dismisses an app. A footer below side-by-side cards made `runs_down` true, so the cards read as a grid. A sideways swipe on a pager started at the pager's middle height, on a row of the list that is its page. The logic is now `act/axis.py`, and `act.ready` and `hit.swipe_across` both read it. A collection runs across when it is a pager or a `HorizontalScrollView`, when its parent is a pager and it shows no item below another, when a child is clipped to an empty strip at its left or right edge level with a child that shows (the next card, kept attached off screen), when two children that show sit side by side, or when its one child that shows has space on both sides, spans at most 90 % of the width and fills at least 75 % of the height (one card of a row). A grid needs two rows that each hold two items, so a lone footer or page indicator below the items is no row. A sideways swipe picks a height at which it crosses no row of a scrolling view that runs down inside the collection: the middle when that is clear, else the middle of the nearest band between rows. When the rows leave no band, the scroll is `NOT_ACTIONABLE` with reason `wrong_axis` and the message says to tap the tab or button, and `act.ready` raises it, so it is not retried like the other planning refusals.

  I changed one clause of the decision. The clause "its parent is a pager" read alone refuses an up or down scroll of every list that is the page of a pager, such as a call log in the Phone app's tab pager, which is the most common use of a pager. It needed one more condition: the list shows no item below another. `swipeable_nav_view_pager_inner_recycler_view` on the J7's Instagram feed shows one page and runs across, and a call log shows rows and does not. `tests/test_axis.py` pins both.

  Known limit: a sideways collection that attaches one child that fills it, and shows no other sign, passes as a list that runs down. The one page of a vertical feed of videos looks the same in the dump, so a card that spans more than 90 % of the width reads the same way. A sideways scroll of it is refused with the message that says to scroll up or down. A grid that shows one row and a part of a second, with one item in it, is not a grid for the same reason, and an up or down scroll of it is refused.
- **A scrolling view the dump calls invisible takes the touch too.** `hit.scrolls_over` required `Flag.VISIBLE`, while `receiver_in` lets a clickable view take a touch whatever the dump says, because a view at alpha 0 is not visible to the user and still takes touches. `ScrollView.onTouchEvent` and `RecyclerView.onTouchEvent` keep ACTION_DOWN at any alpha as well, so the list of a sheet that is fading in, drawn over Save, ate the tap while the plan aimed at Save and the report said that Save received it. The harm ran in the harmless direction, a swallowed tap reported as delivered, and the visible case already had the same severity. `scrolls_over` no longer reads visibility. The half of `test_a_scrollable_view_drawn_under_the_target_or_not_visible_does_not_take_its_touch` that pinned the opposite is replaced by a test whose name gives the reason, and the half about a view drawn under the target stays. No fixture has an invisible node with non-empty bounds, so no fixture tap changes. The Android half is framework source, not a phone run, as for the visible case.
