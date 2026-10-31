# Concepts

The words agent-phone's code, docs and tests use, each with the type that owns it. Read it before `docs/design/core-types.md`, which explains why the types have their shape. Some entries describe behavior that later units of `docs/plan.md` build, such as resolving refs, input, the ledger and the policy engine's verdicts. Those entries describe the types in `core/` as the design doc lays them out.

## Reading the screen

### Screen

One read of every window on the device (`Screen`, `core/screen.py`). Its nodes sit in one flat list in pre-order, so a node's subtree is the slice from its id to its `end`. A backend builds nested `WindowSpec` trees and `Screen.build` indexes them.

### Window

One window in the read (`Window`): an app, the status bar, the keyboard, a dialog or the notification shade. It has a kind (`WindowKind`), an `active` flag for the window with input focus, and a `layer` when the backend knows the stacking order. The uiautomator2 backend cannot read layers or focus. It reports as active the first window of its dump that is not a strip or the keyboard (`A2-7`, `A2-8`).

### Node

One element of the accessibility tree (`Node`). Its `Attrs` hold what the backend says: class, package, resource-id, text, content-desc, hint, bounds and flags such as clickable or visible. Absent evidence is an empty string or None, never a guess.

### Role

What an element is for, from a closed list (`Role`, `core/role.py`). `role_of` reads flags before class, because Compose and web content arrive as plain `android.view.View`. A clickable view is a `button`, an editable one is a `field`.

### Strip

A system window along one edge of the display: as wide as the display along its top or bottom, or as tall as it down a side, and no more than 8% thick the other way (`is_strip`, `adapters/uiautomator2/parse.py`). The status bar and the navigation bar are strips. A strip is never the active window. A server that has seen no screen change since it started lists the status bar before the app, and skipping strips finds the app anyway (`A2-8`).

### Touch consumer

A node that Android hands a tap to instead of its parent: clickable, long-clickable or checkable (`consumes_touch`).

### Actionable

A node that gets a ref in a snapshot (`is_actionable`): visible, and a touch consumer, scrollable, a field or a slider. A disabled node is still actionable, so an agent can name it while it waits for it to become enabled.

### Label surface

Every label string an element owns, each with the field and the node it came from (`labels.Surface`, `surface_of`). It is the element's own fields plus those of every descendant that is not inside a nested touch consumer. The snapshot name, the fingerprint and the policy engine all read it. *Avoid:* "surface" alone, which means the snapshot surface.

### Name, detail and value

What a snapshot line says about an element (`shown_values`). The name is its first naming label and the detail is the rest. A touch consumer takes them from its label surface, so a Button with empty text is named by the text inside it. Every other node, collections included, uses only its own fields. The value is a field's or a slider's own text. It is never a name, and a secret field never prints it.

### Match

A line of a compact view that satisfies a `Query` (`core/query.py`). `find` lists every match with the ref it has in the snapshot it records, and `get` and `is` read one property of a ref on the live screen. A query matches the display name, any word the element shows, the text typed in a field, its role and its resource-id. A secret field has no value a query can read.

### Stable name

The part of the name that identifies an element (`stable_name`). It leaves out values that change as the user types or drags.

### Wrapper

A nameless touch consumer whose only consumer descendant contains its center (`is_wrapper`). A tap on the wrapper reaches that descendant, so the wrapper gets no line and no ref. The system UI wraps every quick-settings tile this way.

### Collection and row

A list, pager or scroll view (`COLLECTIONS`). A row is one child of a collection. Rows tell apart elements that share a resource-id.

## Snapshots

### Snapshot surface

The window a snapshot describes, and what it notes about the rest (`snapshot.surface.Surface`, `select_surface`): whether a keyboard is up, whether the window is a dialog that does not cover the display, and one entry for every other window. It is the active window unless the caller names another one, with a `Pick` (`dialog`, `keyboard`, `shade` or `all`), a window id from `others`, or a drill-down root. A surface that is not on screen is `NO_SURFACE`.

### View and line

Which nodes a snapshot shows and what each line says (`View`, `Line`, `core/snapshot/view.py`). A line holds no node id, so it outlives the screen it came from.

### Mode

How much a view shows (`Mode`). `compact` shows every actionable element and every text that no actionable element owns. `skeleton` hides what is inside collections and counts it, except that it looks through pages. `full` prints every node.

### Page

A pager or list that holds one row (`is_page`). It selects nothing, so the skeleton looks through it and folds the first collection that has several rows. The Instagram feed is a pager over a list over the feed list, and without this rule the skeleton hid the whole feed (`A4-1`). A scroll view is never a page, because it holds one child by construction. Budget fitting still folds a page as its last step.

### Scope

What a read looks at (`Scope`, `core/snapshot/scope.py`): a `Pick`, or a window id, or a drill-down root ref. At most one of the three is set. `look` reads the screen for a scope, once or until it settles, and finds the root ref again on that read. `snapshot` and `find` share it.

### Snapshot

One observation of one window on one device boot, at one ledger epoch (`Snapshot`). The same frozen value is printed, stored and read back. It carries the lines the agent saw and the fingerprints its refs resolve with.

### Snapshot id

Five lower-case Crockford base32 characters, unique across every device in the store. The id alone names the device that took the snapshot.

### Budget

The 8 KB limit on a snapshot's printed tree (`A4-1`, `core/snapshot/budget.py`). `fit` removes detail in a fixed order until the tree fits. `folded` on a line counts the lines hidden under it, and `truncated` on the snapshot counts every line fitting removed.

### Settle state

Whether the screen had stopped changing when it was read (`SettleState`). `settled` means two reads in a row printed the same compact lines of the surface that was asked for. The uiautomator2 dump does not wait for animations (`A2-5`), so a plain snapshot is `unchecked`.

## Refs and identity

### Ref

A handle on one element, valid for one snapshot (`RefToken`), written `@k3x9q:e12`. The number counts actionable elements in tree order over the whole window, so an element keeps its number in compact, skeleton and drill-down views of the same screen. A ref without its snapshot id is `INVALID_ARGS`.

### Device identity

The adb serial plus the boot id (`DeviceIdentity`, `core/device.py`). A ref used on another device is `WRONG_DEVICE`. A ref used on the same phone after a reboot is `STALE_REF` with reason `rebooted`.

### Fingerprint

What a ref stores to find its element again (`Fingerprint`, `core/refs/fingerprint.py`). Its `Key` holds package, window kind, role, class, resource-id, stable name and row key, and is compared whole. Bounds and the child path are hints, never identity.

### Row key

The first four stable labels of the row that holds an element (`row_key`). Two "Like" buttons in two rows of a feed share their name and resource-id, and their row keys tell them apart.

### Twin

Elements on one screen whose keys are equal (`Twin`). A twin ref also stores its ordinal and the bounds of the whole set, and it resolves only while that set has not moved.

### Snapshot store

Snapshots on disk, one immutable JSON file each, under `devices/<serial>/snapshots/` in `~/.agent-phone/` (`SnapshotStore`). Each device keeps its newest 64.

## Input and safety

### Policy

The rules that decide what an input commits (`Policy`, `core/policy/rules.py`). Rules are data in TOML files: the package's `default.toml`, a device profile, and the files a caller passes. There are five rule kinds: `commit`, `exempt`, `ignore`, `inherit` and `deny`. `parse_policy` validates a file and `merge` applies the layers in order.

### Effect

What an input does that cannot be taken back (`Effect`): `publish`, `schedule`, `send`, `delete`, `purchase`, `social`, `system`, `confirm` or `unlabeled`. `--commit` grants effects, not words.

### Phrase

Consecutive words that a commit or deny rule looks for in one label (`Phrase`). A leading `^` anchors it to the label's first word, so `^post` matches "Post" and not "More actions for this post".

### Device profile

Owner data for one phone (`DeviceProfile`), such as `examples/devices/j7.toml`: the packages it protects and its own policy tables. No policy file can disable a profile's deny rules.

### Verdict and grant

What the policy engine says about one input (`Verdict`: `Clear`, `Commits` or `Denied`), and what the caller allowed (`Grant`). A grant opens only the effects it names.

### Ledger, epoch and permit

One input counter per device (`Ledger`, `core/act/ledger.py`). Every input spends a `Permit`, which advances the epoch, and a snapshot from an earlier epoch cannot be used for input. A blind retry is therefore refused until the agent looks again.

### Outcome and disposition

What a command produced (`Outcome`, `core/outcome.py`): `Refused`, `Acted` or `Read`. The outcome type decides the `delivery` disposition, and `retry` follows from it. `not_delivered` is the only safe retry. `docs/json-output.md` lists the values.

## Devices and the server

### Device facts

What a process reads from the phone once, in one shell call (`DeviceInfo`, `core/device.py`): model, API level, ABI, display size, density, locale, default keyboard and the boot id that completes the device identity. An override size or density wins over the physical one. A fact the phone does not report is `TRANSPORT`, never a default.

### State root

The folder for everything agent-phone keeps between commands: `AGENT_PHONE_HOME`, or `~/.agent-phone`. Each device has its own `devices/<serial>/` folder in it, with its snapshots, its ledger and its lock. Two state roots are two sets of locks, so processes that share a device must share a root.

### Device lock

The claim on one device (`DeviceLock`, `core/refs/store.py`). It is an advisory `flock` on `devices/<serial>/lock`, held for one command or for one Driver session. A second process waits up to `AGENT_PHONE_LOCK_WAIT_S` seconds (10 by default) and then gets `DEVICE_BUSY`. The kernel drops the lock when its holder dies, so a crash leaves nothing to clean up.

### Server, watchdog and idle limit

The server is the uiautomator2 process on the phone that answers screen reads (`Server`, `adapters/uiautomator2/server.py`). A command starts it detached when its health check fails. A watchdog shell on the phone kills it when the last-use file is older than the idle limit, 15 minutes by default (`AGENT_PHONE_IDLE_S`). `agent-phone server stop` ends both, which frees the device's one UiAutomation client for another tool.

## Relationships

A backend turns one dump into a `Screen`. `select_surface` picks the window to describe. `build_view` walks it with the label surface and the role rules and produces lines, and `fit` keeps those lines within the budget. `fingerprints` keys every node so that each printed ref can be found again. The `Snapshot` holds the lines, the fingerprints and the device identity, and the store writes it to disk. A later command reads the snapshot back by the id in its ref, checks the device and the ledger epoch, and finds the element on a new `Screen` by its key. The policy engine reads the same label surface that named the element, so it judges the words the agent saw.
