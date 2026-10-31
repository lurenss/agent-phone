# Concepts

The words agent-phone's code, docs and tests use, each with the type that owns it. Read it before `docs/design/core-types.md`, which explains why the types have their shape. Some entries describe behavior that later units of `docs/plan.md` build, such as resolving refs, input, the ledger and the policy engine's verdicts. Those entries describe the types in `core/` as the design doc lays them out.

## Reading the screen

### Screen

One read of every window on the device (`Screen`, `core/screen.py`). Its nodes sit in one flat list in pre-order, so a node's subtree is the slice from its id to its `end`. A backend builds nested `WindowSpec` trees and `Screen.build` indexes them.

### Window

One window in the read (`Window`): an app, the status bar, the keyboard, a dialog or the notification shade. It has a kind (`WindowKind`), an `active` flag for the window with input focus, and a `layer` when the backend knows the stacking order. The uiautomator2 backend reports the first window of its dump as active and cannot read layers.

### Node

One element of the accessibility tree (`Node`). Its `Attrs` hold what the backend says: class, package, resource-id, text, content-desc, hint, bounds and flags such as clickable or visible. Absent evidence is an empty string or None, never a guess.

### Role

What an element is for, from a closed list (`Role`, `core/role.py`). `role_of` reads flags before class, because Compose and web content arrive as plain `android.view.View`. A clickable view is a `button`, an editable one is a `field`.

### Touch consumer

A node that Android hands a tap to instead of its parent: clickable, long-clickable or checkable (`consumes_touch`).

### Actionable

A node that gets a ref in a snapshot (`is_actionable`): visible, and a touch consumer, scrollable, a field or a slider. A disabled node is still actionable, so an agent can name it while it waits for it to become enabled.

### Label surface

Every label string an element owns, each with the field and the node it came from (`labels.Surface`, `surface_of`). It is the element's own fields plus those of every descendant that is not inside a nested touch consumer. The snapshot name, the fingerprint and the policy engine all read it. *Avoid:* "surface" alone, which means the snapshot surface.

### Name, detail and value

What a snapshot line says about an element (`shown_values`). The name is its first naming label and the detail is the rest. A touch consumer takes them from its label surface, so a Button with empty text is named by the text inside it. Every other node, collections included, uses only its own fields. The value is a field's or a slider's own text. It is never a name, and a secret field never prints it.

### Stable name

The part of the name that identifies an element (`stable_name`). It leaves out values that change as the user types or drags.

### Wrapper

A nameless touch consumer whose only consumer descendant contains its center (`is_wrapper`). A tap on the wrapper reaches that descendant, so the wrapper gets no line and no ref. The system UI wraps every quick-settings tile this way.

### Collection and row

A list, pager or scroll view (`COLLECTIONS`). A row is one child of a collection. Rows tell apart elements that share a resource-id.

## Snapshots

### Snapshot surface

The window a snapshot describes, and what it notes about the rest (`snapshot.surface.Surface`, `select_surface`): whether a keyboard is up, whether the window is a dialog that does not cover the display, and one entry for every other window. It is the active window unless the caller names another one or a drill-down root.

### View and line

Which nodes a snapshot shows and what each line says (`View`, `Line`, `core/snapshot/view.py`). A line holds no node id, so it outlives the screen it came from.

### Mode

How much a view shows (`Mode`). `compact` shows every actionable element and every text that no actionable element owns. `skeleton` hides what is inside collections and counts it. `full` prints every node.

### Snapshot

One observation of one window on one device boot, at one ledger epoch (`Snapshot`). The same frozen value is printed, stored and read back. It carries the lines the agent saw and the fingerprints its refs resolve with.

### Snapshot id

Five lower-case Crockford base32 characters, unique across every device in the store. The id alone names the device that took the snapshot.

### Budget

The 8 KB limit on a snapshot's printed tree (`A4-1`, `core/snapshot/budget.py`). `fit` removes detail in a fixed order until the tree fits. `folded` on a line counts the lines hidden under it, and `truncated` on the snapshot counts every line fitting removed.

### Settle state

Whether the screen had stopped changing when it was read (`SettleState`). The uiautomator2 dump does not wait for animations (`A2-5`).

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

## Relationships

A backend turns one dump into a `Screen`. `select_surface` picks the window to describe. `build_view` walks it with the label surface and the role rules and produces lines, and `fit` keeps those lines within the budget. `fingerprints` keys every node so that each printed ref can be found again. The `Snapshot` holds the lines, the fingerprints and the device identity, and the store writes it to disk. A later command reads the snapshot back by the id in its ref, checks the device and the ledger epoch, and finds the element on a new `Screen` by its key. The policy engine reads the same label surface that named the element, so it judges the words the agent saw.
