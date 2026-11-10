# JSON output

Every agent-phone command prints one JSON object, the envelope, on stdout and exits. This page is the contract for that object. `core/envelope.py` builds it from the command's `Outcome` (`core/outcome.py`), and the snapshot payload comes from `Snapshot` (`core/snapshot/snapshot.py`). `tests/test_docs.py` checks every value table below against its enum and the examples below against the code.

The envelope is UTF-8 JSON with no escaping of non-ASCII characters and no spaces between tokens. The example below is wrapped for reading.

## Envelope

| Key | Type | Present | Meaning |
| --- | --- | --- | --- |
| `v` | int | always | Contract version, `1`. |
| `ok` | bool | always | `true` when the command did what it was asked. |
| `command` | string | always | The command name, such as `snapshot` or `click`. |
| `permission_mode` | string or null | always | The [permission mode](#permission-modes) the process ran in. Null only when `AGENT_PHONE_PERMISSION_MODE` named a mode that does not exist, so none was in force. |
| `device` | string or null | always | The adb serial the command ran against, or null when no device was chosen. |
| `delivery` | string | input commands and every error | Whether input reached the device. See [Delivery](#delivery). |
| `retry` | string | with `delivery` | `safe` when `delivery` is `not_delivered`, otherwise `unsafe`. |
| `data` | object | success, and an input that went out | The command's result. A snapshot is described in [Snapshot payload](#snapshot-payload). |
| `error` | object | failure | `code`, `message`, `hint` and `details`. |

The outcome type decides which keys appear, and no command writes `delivery` or `retry` itself:

- A read that succeeds (`Read`) has `ok: true` and `data`. It has no `delivery` and no `retry`.
- A command refused before any input left the computer (`Refused`) has `ok: false`, `error`, `delivery: not_delivered` and `retry: safe`.
- An input that was handed to the backend (`Acted`) has `data` with the action report and the observation after it, a `delivery` from its `SentState`, and `retry: unsafe`. If the input went out but the command still failed, `ok` is `false` and `error` is present as well.
- A batch has its own rule for `delivery` and `retry`, written under [Batch payload](#batch-payload). Its `retry` is the one value that is not always derived from its `delivery`.
- An exception that no command caught has `code: INTERNAL`. Its `delivery` is `delivery_uncertain` when this process spent an input permit that it did not refund, otherwise `not_delivered`.

The exit code is 0 when `ok` is true, 1 for an error envelope, and 2 when the arguments do not parse. The envelope is printed in all three cases.

### Permission modes

The mode is a setting of the process, read once from the environment variable `AGENT_PHONE_PERMISSION_MODE`. The person who launches the agent sets it. An agent never does, and no policy file, device profile, command flag or batch step can.

| Mode | What a commit needs |
| --- | --- |
| `ask` | The caller's `--commit` for every effect it names. This is the default, and it is the mode when the variable is unset or empty. |
| `dangerously-skip` | Nothing. A commit goes out with no `--commit`, and the [gate](#input-payload) lists the effects the mode let through as `skipped`. |

The mode lifts that one condition. A deny rule, a protected package, `LOCALE_UNSUPPORTED` and every other refusal are the same in both modes, and a `--commit` that an agent passes in `dangerously-skip` is still accepted and changes nothing. Any other value of the variable is `INVALID_ARGS` before a device is opened, and its envelope has `"permission_mode": null` and an empty `command`:

```json
{"v":1,"ok":false,"command":"","permission_mode":null,"device":null,"delivery":"not_delivered","retry":"safe",
 "error":{"code":"INVALID_ARGS","message":"AGENT_PHONE_PERMISSION_MODE is 'skip'. It must be `ask` or `dangerously-skip`, or unset for `ask`.","hint":null,"details":{}}}
```

### Error object

| Key | Type | Meaning |
| --- | --- | --- |
| `code` | string | One of the [error codes](#error-codes). |
| `message` | string | One or two sentences for the agent, naming what failed and what to use instead. |
| `hint` | string or null | A recovery step for codes whose recovery the message does not make obvious, otherwise null. |
| `details` | object | Machine-readable facts for the code, such as `reason` for `STALE_REF`, `source`, `table` and `field` for `POLICY_INVALID`, or `after`, a [snapshot](#snapshot-payload), for the `TIMEOUT` of `wait`. |

## Delivery

| Value | Retry | Meaning |
| --- | --- | --- |
| `not_delivered` | safe | No input left the computer, or the backend proved that nothing reached the device. Running the same command again is safe. |
| `delivery_uncertain` | unsafe | Input may have reached the device. Look at the screen before you act again. |
| `delivered_unverified` | unsafe | Input reached the device and nothing checked its effect. |
| `delivered_verified` | unsafe | Input reached the device, and every `--wait-for` and `--wait-for-gone` of the input did not hold before it and held after it. A `set-text` with no wait is also `delivered_verified` when the field reads back the text it sent, or, on a field that reads `lossy`, that text with each character above U+FFFF as `..`. That read-back does not check what the field held before. |

`not_delivered` is the only value after which the same command can succeed again, because every input spends the refs taken before it.

## Error codes

| Code | Meaning |
| --- | --- |
| `INVALID_ARGS` | The arguments do not parse. A target that is neither a ref nor a query, such as `e12` or `Display`, is one case. A step of a batch or of a [flow](#flow-file) that does not parse, names its own device, or is not a command that uses the phone is another, and so is a flow file that breaks one of its rules, and a batch file that is not a JSON array of non-empty arrays of strings, or a batch with no file on a terminal. A link for `open-url` that holds a line break or any other control character, written out or percent-encoded, is another. So is a value of `AGENT_PHONE_PERMISSION_MODE` that is neither `ask` nor `dangerously-skip`, which stops the process before a device is opened. So is a `--wait-for` or `--wait-for-gone` that already holds on the read the input is planned on: it would hold whether or not the input worked, so it cannot prove anything, and the input is not sent. |
| `POLICY_INVALID` | A policy file, or the order its layers merge in, is invalid. `details` names the `source`, the `table` and the `field`, or the `rule`. A file that disables a deny rule of the device profile, or of a file the profile names, is one case, and a file whose top-level `languages` names a language the built-in policy does not cover is another. |
| `NO_DEVICE` | No device is connected and ready, or the requested one is not. |
| `DEVICE_AMBIGUOUS` | Several devices are ready and neither `-d` nor a ref names one. |
| `WRONG_DEVICE` | The ref belongs to another device, or `-d` contradicts the device the ref names. |
| `DEVICE_BUSY` | Another process drives this device (`A3-4`). |
| `SERVER_UNAVAILABLE` | The on-device server did not answer its health check in time. |
| `NOT_SUPPORTED` | The backend cannot perform this input. |
| `SNAPSHOT_NOT_FOUND` | No stored snapshot has that id. It was never taken here, it is older than the newest 64 of its device, or it was written in a form this version cannot read. |
| `STALE_REF` | The ref cannot be trusted. `details.reason` is `spent` (input was sent after its snapshot), `rebooted` (the snapshot is from an earlier boot) or `gone` (its element is no longer on screen). |
| `OBSERVE_FIRST` | Input was sent after the device's latest snapshot, so a query or an input without a target needs a new snapshot first. |
| `AMBIGUOUS_TARGET` | More than one live element matches, and nothing was sent. `details.matches` is their number, for a query and for a ref that now matches several elements. Narrow the query, or take a ref from `find`. |
| `NOT_FOUND` | No element matches the query, the snapshot has no ref with that number, nothing on screen scrolls, or no app handles the link or intent. |
| `NO_SURFACE` | The window asked for is not on screen. No window has input focus (the screen is off), or `--surface` finds none, or `--window` is not an id of this read. The message lists the windows that are. A wait reads again after an empty dump, so it reports `NO_SURFACE` only at its deadline, and only when none of its reads showed a screen. A `snapshot` without `--settle` reads once and reports it at once. |
| `NOT_ACTIONABLE` | The element cannot take this input. `details.reason` is `hidden` or `disabled` when it stayed so until the deadline, and `no_tap`, `not_a_field`, `not_scrollable`, `no_area` or `wrong_axis` (a sideways scroll of a list that runs down, a sideways scroll of a pager whose page is a list that covers its whole height, or an up or down scroll of a collection that runs across) when it never can. |
| `UNSTABLE` | The element moved between two reads. |
| `OCCLUDED` | No point of the element would reach it: another window covers it, another element takes the touch there, such as a list that scrolls and is drawn above it, two elements overlap in an unknown order, or its window has no input focus. |
| `COMMIT_REFUSED` | The input would commit an effect that `--commit` did not grant, in `ask` mode. `details` lists the `effects`, the `granted` effects and the `evidence`. `dangerously-skip` never raises it. |
| `DENIED` | A deny rule forbids the input whatever the caller grants, and in either permission mode. `details` names the `rule`, its `source` and the `evidence`. A device profile's protected package is denied this way. A deny rule reads a tap, a set-text, a scroll and Enter, and never back, home or recents. |
| `LOCALE_UNSUPPORTED` | The device language has no policy rules, so input that commit rules read, a tap or Enter, cannot be judged. |
| `TIMEOUT` | A wait reached its deadline. For `wait`, nothing was sent, `delivery` is `not_delivered`, and `details.after` is the snapshot of the last screen it read, or null when that screen had no window to describe. For `--wait-for` on an input, the input went out, `delivery` says how far, and `data.after` is that snapshot. A wait that read a screen and then only empty dumps is a `TIMEOUT` with that screen. |
| `TRANSPORT` | adb or the server failed, or the device returned output that does not parse. |
| `ACTION_FAILED` | The input went out, and reading the screen back contradicts what was asked, such as a field that does not hold the text `set-text` sent. |
| `INTERNAL` | A defect in agent-phone. |

## Devices payload

`agent-phone devices` lists every device adb knows, in adb's order, as `{"devices": [...]}`. It reads facts from each ready device in one shell call and starts nothing on it. The envelope's `device` is null.

| Key | Type | Present | Meaning |
| --- | --- | --- | --- |
| `serial` | string | always | The adb serial. Pass it to `-d`. |
| `model` | string | always | The device's own model name when its facts were read, otherwise the name adb lists, with `_` for spaces. |
| `ready` | bool | always | `true` when adb lists the device as `device`. An unauthorized or offline device is `false` and has no facts. |
| `api` | int | with facts | The Android API level. |
| `abi` | string | with facts | The primary CPU ABI. |
| `display` | array | with facts | `[width, height]` in pixels, in the device's natural orientation. A size override wins over the physical size. |
| `density` | int | with facts | Dots per inch. An override wins over the physical density. |
| `locale` | string | with facts | The user's language tag, such as `en-US`. |
| `ime` | string or null | with facts | The package of the default keyboard, or null when none is set. |
| `boot_id` | string | with facts | The kernel's boot id. It changes at every reboot, and a ref from an earlier boot is `STALE_REF`. |
| `problem` | string | when facts failed | Why a ready device has no facts. |
| `profile` | string or null | always | The `name` of the device profile in `<state root>/profiles/` whose `serial` is this device's, or null when none is. |

```json
{"v":1,"ok":true,"command":"devices","permission_mode":"ask","device":null,"data":{"devices":[
 {"serial":"0a1b2c3d4e5f6a7b","model":"SM-J730F","ready":true,"api":28,"abi":"armeabi-v7a","display":[1080,1920],
  "density":420,"locale":"en-US","ime":"com.sec.android.inputmethod","boot_id":"8d3f6c1e-0b5a-4c2e-9f1d-2a7b3c4d5e6f",
  "profile":null},
 {"serial":"R58M1234567","model":"","ready":false,"profile":null}]}}
```

## Server payload

`agent-phone server start`, `stop` and `status` each print the server's status after the command, as the `data` object. `start` and `stop` can run again with no harm. The server holds the device's one UiAutomation client (`A3-4`), so `stop` also makes the device free for any other tool.

| Key | Type | Meaning |
| --- | --- | --- |
| `running` | bool | The uiautomator2 server process is alive on the phone. |
| `watchdog` | bool | The watchdog that stops an idle server is alive. |
| `idle_limit_s` | int or null | The idle limit the running watchdog was started with, in seconds. The default is 900. `AGENT_PHONE_IDLE_S` sets it for the next start. |
| `idle_for_s` | int or null | Seconds since a command last used the server. Null when no server runs. |

## Skills payload

`agent-phone skills list` and `agent-phone skills get [name]` print the usage guides for agents that ship inside the package, under `agent_phone/skills/`. They read no device, and the envelope's `device` is null.

### Skills list

`list` prints `{"skills": [...]}`, one object per guide.

| Key | Type | Meaning |
| --- | --- | --- |
| `name` | string | The guide's name. Pass it, or its alias, to `skills get`. |
| `alias` | string | A short name for the same guide, such as `phone`. |
| `summary` | string | What the guide covers. |

### Skills get

`get` prints one guide. With no name it prints `agent-phone`.

| Key | Type | Meaning |
| --- | --- | --- |
| `name` | string | The guide's name, also when an alias asked for it. |
| `content` | string | The guide's `SKILL.md`, as Markdown with its YAML front matter. |

## Find payload

`agent-phone find` searches the lines a compact snapshot prints. It lists every match, up to `--limit`, and records them as a snapshot of their own, which owns their refs. `--count` records nothing and prints only `count`.

| Key | Type | Present | Meaning |
| --- | --- | --- | --- |
| `count` | int | always | Every match on the surface, including those the list leaves out. |
| `id` | string | without `--count` | The snapshot the find recorded. A match's ref is `@<id>:e<N>`, with the number it has in a snapshot of the whole window. |
| `app` | string | without `--count` | The package of the window that was searched. |
| `window` | string | without `--count` | That window's kind. See [Window kinds](#window-kinds). |
| `truncated` | int | without `--count` | The matches that `--limit` or the 8 KB budget left out of `matches`. |
| `matches` | array of strings | without `--count` | The matching lines in tree order, each as [a tree line](#tree-lines) at depth 0. A match with no ref is text with no action target. |

```json
{"v":1,"ok":true,"command":"find","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","data":{
 "count":1,"id":"p4n8c","app":"com.android.settings","window":"application","truncated":0,
 "matches":["@p4n8c:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" focused [0,179,1920,394]"]}}
```

## Get and is payload

`agent-phone get <ref>` reads one property of the element a ref names, and `agent-phone is <ref>` checks one boolean. Both read the live screen, after the ref is resolved strictly (see `STALE_REF` and `AMBIGUOUS_TARGET`). They record no snapshot and send no input, so no ref changes.

| Key | Type | Meaning |
| --- | --- | --- |
| `ref` | string | The ref that was asked about. |
| `property` | string | The property that was read. |
| `value` | string, bool, array or null | The answer. `null` means the element has no such property, such as the value of a button. |

```json
{"v":1,"ok":true,"command":"get","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","data":{
 "ref":"@p4n8c:e4","property":"bounds","value":[0,179,1920,394]}}
```

### Get properties

| Property | Value |
| --- | --- |
| `text` | What a person reads: the typed text of a field or slider when it has some, otherwise the name and then the detail, joined with `, `. Never a secret field's text. |
| `value` | The text a field or slider holds, `""` when it is empty, and `null` for every other element and for a secret field. |
| `bounds` | `[left, top, right, bottom]` in pixels of the current rotation. |
| `states` | The element's states, from [States](#states), in that table's order. |

### Is properties

| Property | Value |
| --- | --- |
| `visible` | `true` when the element is visible to the user. |
| `enabled` | `true` when the element is enabled. |
| `checked` | `true` when the element is checked. It is `false` for an element that cannot be checked. |
| `focused` | `true` when the element has input focus. |
| `selected` | `true` when the element is selected. |

## Wait payload

`agent-phone wait [--for QUERY]... [--gone QUERY]... [--app PACKAGE] [--settled] [--timeout-ms N]` reads the screen until every condition holds on one read. `--for` and `--gone` take the query that `--wait-for` and `--wait-for-gone` take, `--app` holds when the window that has focus belongs to that package, and `--settled` holds when every read for 800 ms has printed the same lines, and a read that prints other lines, or an empty read, starts that window again. At least one condition is required, or the command is `INVALID_ARGS` and reads nothing. The default timeout is 10,000 ms.

`wait` sends no input, so it is a read: it never has a permit, and running it again is safe.

- When the conditions hold, the result is `ok: true` with no `delivery` and no `retry`, like every read. `data` is the [snapshot payload](#snapshot-payload) of the read they held on, recorded at the current epoch, so its refs serve the next command and it is the observation that the next input needs. `settled` is `settled` when `--settled` was asked and `unchecked` otherwise.
- When the deadline comes first, the result is an error with `code` `TIMEOUT`, `delivery` `not_delivered` and `retry` `safe`. `error.details.after` is the snapshot of the last screen it read, recorded the same way, so the agent sees what the screen showed instead. Its `settled` is `unsettled` when `--settled` was asked.
- When no read of the wait showed a screen, the result is an error with `code` `NO_SURFACE`, with the same `delivery` and `retry`, and no `details.after`. It comes at the deadline and not on the first read, so a screen that is off takes the whole timeout to report it.

```json
{"v":1,"ok":false,"command":"wait","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"not_delivered","retry":"safe",
 "error":{"code":"TIMEOUT","message":"present name=\"Brightness\" did not hold within 200 ms.","hint":null,
  "details":{"after":{
   "id":"q7m2k","app":"com.android.settings","window":"application","mode":"compact","settled":"unchecked",
   "keyboard":false,"dialog":false,"others":[],"toasts":[],"truncated":0,
   "tree":[
    "text \"Settings\" [63,33,277,114]",
    "@q7m2k:e1 button \"Search\" [1648,0,1775,147]",
    "@q7m2k:e2 button \"Samsung account profile\" [1775,0,1920,147]",
    "@q7m2k:e3 list #dashboard_container (4 rows) [0,179,1920,1080]",
    "  @q7m2k:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" focused [0,179,1920,394]",
    "  @q7m2k:e5 button \"Sounds and vibration\" \"Sound mode, Ringtone, Volume\" [0,436,1920,653]",
    "  @q7m2k:e6 button \"Notifications\" \"Block, Allow, Do not disturb\" [0,653,1920,868]",
    "  @q7m2k:e7 button \"Display\" \"Brightness, Blue light filter, Home scre…\" [0,910,1920,1080]"]}}}}
```

Every condition has to hold on the same read. `--for` holds when a line of the active window matches, and `--gone` holds when the window prints lines, none matches and the window is not a dialog, so `--gone` for something that never showed holds at once on a full-screen window. A dialog hides what lies under it (`A2-7`), so `--gone` never holds on a read whose window is a dialog (`dialog` is true in its snapshot), even when the target was on the page under it. A read with no active window, or with no line, such as the blank frame between two screens, holds neither. A read with no window on the default display, such as the empty dump between two screens, holds no condition, and that includes `--gone`, because an empty dump is no evidence that anything left the screen. The wait reads again until its deadline, and then ends `TIMEOUT` with the last screen it read, or `NO_SURFACE` when none of its reads showed one. The same holds for `--wait-for` on an input and for `snapshot --settle`. Any other failed read, such as `TRANSPORT`, ends the command at once with its own error.

## Input payload

`click`, `set-text`, `scroll`, `press`, `launch`, `stop`, `open-url`, `rotate` and `clipboard set` send input. An input that went out has `delivery` and `retry` from how far it got, and this `data` object. An input refused before it went out is an error envelope with `delivery` `not_delivered`, and has no `data`. An input that went out and then failed, such as a `--wait-for` that timed out, has `data` and `error` both.

| Key | Type | Meaning |
| --- | --- | --- |
| `input` | object | What was sent. `kind` is one of the [input kinds](#input-kinds), with its own keys. Typed text and clipboard text are never echoed. |
| `target` | object or null | For an input on an element: its `ref` (or null for a query), `role`, `name`, and `at`, the point a tap landed on, or null. Null for an input with no element. |
| `gate` | object | The policy verdict the input was sent under: `{"verdict": "clear", "reason": …}` with a [clear reason](#clear-reasons), or `{"verdict": "commits", "effects": […], "granted": […], "skipped": […]}`. `effects` are the [effects](#effects) the input commits. `granted` is the part of them that the caller's `--commit` named, and `skipped` is the rest, which `dangerously-skip` let through with no grant. `skipped` is always empty in `ask`, and `effects` is `granted` and `skipped` together. |
| `verified_by` | string or null | What proved the effect, such as `present name="Brightness"` or `the field holds the text`. |
| `after` | object or null | The snapshot the wait ended on, with fresh refs, as in [Snapshot payload](#snapshot-payload). Null when nothing was waited for. |

```json
{"v":1,"ok":true,"command":"click","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"delivered_unverified","retry":"unsafe",
 "data":{"input":{"kind":"tap","at":[960,995]},
  "target":{"ref":"@q7m2k:e7","role":"button","name":"Display","at":[960,995]},
  "gate":{"verdict":"clear","reason":"no_commit_words"},"verified_by":null,"after":null}}
```

A refused commit lists what the input would do, what was granted, and the labels that said so:

```json
{"v":1,"ok":false,"command":"click","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"not_delivered","retry":"safe",
 "error":{"code":"COMMIT_REFUSED",
  "message":"This input would schedule ('Schedule reel'). It is sent only with --commit schedule. Grant it only when your user asked for this commit.",
  "hint":"Grant the listed effect with --commit only when your user asked for it.",
  "details":{"effects":["schedule"],"granted":[],"evidence":[{"rule":"default.schedule","source":"receiver","label":"Schedule reel"}]}}}
```

The same tap under `dangerously-skip` goes out with no grant, and the gate says which effects the mode let through:

```json
{"v":1,"ok":true,"command":"click","permission_mode":"dangerously-skip","device":"0a1b2c3d4e5f6a7b","delivery":"delivered_unverified","retry":"unsafe",
 "data":{"input":{"kind":"tap","at":[540,1750]},
  "target":{"ref":"@m9q4t:e1","role":"button","name":"Schedule reel","at":[540,1750]},
  "gate":{"verdict":"commits","effects":["schedule"],"granted":[],"skipped":["schedule"]},"verified_by":null,"after":null}}
```

### Input kinds

| Kind | Keys | Input |
| --- | --- | --- |
| `tap` | `at` | A touch at a point (`click`). |
| `long_press` | `at`, `ms` | A touch held for `ms` (`click --long`). |
| `activate` | none | The accessibility click of a backend that has one. The uiautomator2 backend has none (`A2-11`). |
| `swipe` | `from`, `to` | A swipe across a list (`scroll`). |
| `set_text` | `secret` | A field's text replaced through the accessibility action (`set-text`). |
| `key` | `key` | A key: `back`, `home`, `recents` or `enter` (`press`). |
| `launch` | `package` | An app's launcher screen started. |
| `stop` | `package` | An app force-stopped. |
| `open_uri` | `uri`, `package` | A link or an intent opened (`open-url`). |
| `rotate` | `orientation` | The rotation locked to `portrait` or `landscape`, or handed to the sensor with `auto`. |
| `power` | `power` | The screen turned `on` or `off`. No command sends it yet. |
| `set_clipboard` | none | The clipboard replaced (`clipboard set`). |

### Clear reasons

| Reason | Meaning |
| --- | --- |
| `no_receiver` | Nothing that takes a touch is at the point, or, for Enter, no view has focus. |
| `no_commit_words` | No commit rule matched the words of the element or, for a button that does not say what it does, such as OK or Confirm, its dialog. |
| `exempt` | An exempt rule removed the only words that matched. |
| `not_labeled_input` | Commit rules do not read this input: a set-text, a scroll, back, home, recents, or an input that lands on no element, and no rule for keys or links matched it. |

### Effects

| Effect | What the input does |
| --- | --- |
| `publish` | Makes content visible to others. |
| `schedule` | Queues a post or a message for later. |
| `send` | Delivers a message, or starts a call. |
| `delete` | Destroys data. |
| `purchase` | Spends money. |
| `social` | Changes who the account is connected to, visibly. |
| `system` | Changes device state that can cut off the device or the agent. |
| `consent` | Gives a permission, a consent or an authorization that the user owns. |
| `confirm` | Confirms an action whose effect the label does not say. |
| `unlabeled` | Lands on an element with no words, so nothing says what it does. |

## Batch payload

`agent-phone batch [FILE]` runs the steps of a JSON array in one process, under one device lock. A step is an array of the arguments of one command without `agent-phone`, such as `["click", "name=Display", "--wait-for", "name*=Brightness"]`. The CLI's own parser reads each step. `-d` is given once, on the batch. A step may name no device, may not be `batch`, and must be a command that reads or drives the phone, so `server`, `devices` and `skills` are not steps. `--commit` and `--policy` go inside the step they serve, and a grant or a file in one step does not reach another. The steps run in order and stop at the first step whose result is not ok.

An agent that must not send an input twice cannot rely on a ref after another input, because every input spends the refs taken before it. A later step finds its target by a query, after a `--wait-for` or a `wait` that gave it a current observation. A step with no observation to stand on is refused as `OBSERVE_FIRST`, as the example shows.

| Key | Type | Meaning |
| --- | --- | --- |
| `steps` | array of envelopes | One envelope for each step that ran, in order. Each is exactly what that command alone prints. |
| `stopped_at` | int or null | The index, from 0, of the first step that is not ok, or null when every step is ok. Steps after it did not run. |
| `trace` | string | The path of the [trace](#batch-trace) file. |

The envelope's own keys follow the steps. `permission_mode` is the batch process's, and every step ran under it, so each step's envelope and each step line of the trace carry the same value.

- When every step is ok, `ok` is true. A batch that sent no input, such as one of reads, has no `delivery` and no `retry`, like a read. A batch that sent input has the weakest `delivery` among its inputs, in the order `delivery_uncertain`, `delivered_unverified`, `delivered_verified`, and `retry: unsafe`.
- When a step fails, `ok` is false, and `error` has that step's `code`, `message` and `hint`, with `details` `{"step": i}`, the index of the step. The step's own `details`, such as the snapshot a `wait` timed out on, stand once, in its envelope in `steps`, because an agent reads this output into its context. `delivery` is that step's `delivery`. `retry` is `unsafe` when any earlier step sent an input, because running the batch again would send that input again. Otherwise it is that step's `retry`. So `delivery` can be `not_delivered` with `retry` `unsafe`: the failed step sent nothing, and an earlier one did.
- The exit code is the failed step's exit code, and 0 when every step is ok.
- A failure before the first step runs, such as a step that does not parse, `NO_DEVICE`, `DEVICE_BUSY` or `POLICY_INVALID`, is an ordinary error envelope with `command` `batch`, `delivery` `not_delivered`, `retry` `safe` and no `data`. Nothing ran, and no trace was written.
- A step that raises is the failed step. Its envelope is the `INTERNAL` envelope of an uncaught exception, with `delivery_uncertain` only when that step spent an input permit that it did not refund. The steps before it stay in `steps` and in the trace.

```json
{"v":1,"ok":false,"command":"batch","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"not_delivered","retry":"unsafe",
 "data":{"steps":[
  {"v":1,"ok":true,"command":"launch","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"delivered_unverified","retry":"unsafe",
   "data":{"input":{"kind":"launch","package":"com.android.settings"},"target":null,
    "gate":{"verdict":"clear","reason":"not_labeled_input"},"verified_by":null,"after":null}},
  {"v":1,"ok":false,"command":"click","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"not_delivered","retry":"safe",
   "error":{"code":"OBSERVE_FIRST","message":"Input was sent since the latest snapshot, e8j9h. Take a new one and look first.",
    "hint":"Input was sent since the last snapshot. Take one and look before acting.","details":{}}}],
  "stopped_at":1,"trace":"/home/agent/.agent-phone/traces/0a1b2c3d4e5f6a7b/20261101T091500.123456Z-batch.jsonl"},
 "error":{"code":"OBSERVE_FIRST","message":"Input was sent since the latest snapshot, e8j9h. Take a new one and look first.",
  "hint":"Input was sent since the last snapshot. Take one and look before acting.","details":{"step":1}}}
```

The launch had no `--wait-for`, so it left no observation for the click. The click is refused with nothing sent, and the batch's `retry` is `unsafe` because the launch went out.

### Batch trace

Each batch writes one JSONL file, `<state root>/traces/<serial>/<UTC timestamp>-batch.jsonl`, in a folder of mode 0700, and the file has mode 0600. A line is written as its step ends, so a crash leaves the steps before it. There is one line for each step that ran, then a last line. A line is read from the step's envelope, so the two agree. It holds no `after` snapshot and no tree, which the step's envelope in the batch result has.

#### Trace step line

| Key | Type | Meaning |
| --- | --- | --- |
| `line` | string | `step`. |
| `i` | int | The step's index, from 0. |
| `argv` | array of strings | The step's arguments. The text that `set-text` or `clipboard set` typed is replaced by `<N chars>` wherever it stands, also inside a longer word such as the query `value=hunter2`. Command words and flag names stay. |
| `permission_mode` | string | The step's `permission_mode`, the permission mode of the batch's process. |
| `started_utc` | string | When the step started, in UTC with milliseconds. |
| `ms` | int | How long the step took. |
| `ok` | bool | The step's `ok`. |
| `delivery` | string or null | The step's `delivery`, null for a read that succeeded. |
| `retry` | string or null | The step's `retry`, null when it has no `delivery`. |
| `error` | string or null | The step's error code. |
| `input` | string or null | The kind of the input that went out, from the [input kinds](#input-kinds), or null. |
| `target` | object or null | For `click`, `set-text` and `scroll` with a target: the `ref` and the `query` it was asked for, one of them null, and the `role` and `name` it resolved to, null when the input did not get that far. |
| `gate` | object or null | The verdict the input was sent under, as in the [input payload](#input-payload), or null. |

#### Trace end line

| Key | Type | Meaning |
| --- | --- | --- |
| `line` | string | `end`. |
| `stopped_at` | int or null | The same as the batch's `data.stopped_at`. |
| `ms` | int | The steps' total time, from the start of the first to the end of the last. |

```jsonl
{"line":"step","i":0,"argv":["launch","com.android.settings"],"permission_mode":"ask","started_utc":"2026-11-01T09:15:00.211Z","ms":412,"ok":true,"delivery":"delivered_unverified","retry":"unsafe","error":null,"input":"launch","target":null,"gate":{"verdict":"clear","reason":"not_labeled_input"}}
{"line":"step","i":1,"argv":["click","name=Nowhere","--timeout-ms","100"],"permission_mode":"ask","started_utc":"2026-11-01T09:15:00.624Z","ms":3,"ok":false,"delivery":"not_delivered","retry":"safe","error":"OBSERVE_FIRST","input":null,"target":{"ref":null,"query":"name=\"Nowhere\"","role":null,"name":null},"gate":null}
{"line":"end","stopped_at":1,"ms":416}
```

## Flow payload

`agent-phone flow run FILE [--param NAME=VALUE]... [--commit EFFECT]... [--dry-run]` replays a job that was written once as a [flow file](#flow-file). It runs the file's steps in one process, under one device lock, as a batch does, and it prints one envelope whatever the number of steps. The steps' own envelopes are not printed, so a replay costs an agent one call and one small object.

| Key | Type | Meaning |
| --- | --- | --- |
| `flow` | string | The flow's `name`. |
| `steps` | int | How many steps the file has. |
| `ran` | int | How many steps ran and were ok. |
| `stopped_at` | int or null | The index of the step the run stopped at, from 0, or null when every step ran. |
| `dry_run` | bool | Whether `--dry-run` was given. |
| `commit` | array of strings or null | In a dry run that stopped before a commit, the [effects](#effects) the step at `stopped_at` would commit. Null otherwise. |
| `trace` | string | The path of the device's [trace](#command-trace) of the day, which has a begin and an end line for every call the run made. |

- `delivery` and `retry` follow the [batch's](#batch-payload) rule over every call the run made. When a step fails, `delivery` is that step's, and `retry` is `unsafe` when an earlier step sent input.
- The run stops at the first step whose `expect` does not show, and at the first step that is not ok. `ok` is then false, and `error` is that call's own `code`, `message`, `hint` and `details`, such as the snapshot a wait timed out on. `details` also has `step`, the step's index, and `during`: `expect` for the step's expectation, `look` for the snapshot taken for it, `run` for the step itself.
- A dry run that stops before a commit is ok: `stopped_at` names the step, `commit` its effects, and nothing of that step was sent. The steps before it ran and sent their input. When the step's own `--commit` does not name those effects, a real run would refuse the step, so the dry run fails on it with `COMMIT_REFUSED`. `permission_mode` is `ask` in every dry run, because a dry run judges each step as `ask` does.
- A failure before the first step, such as a file that is not a flow, a step that does not parse, a parameter that is missing, or a flow whose `grants` the caller's `--commit` does not cover (`COMMIT_REFUSED`), is an ordinary error envelope with `command` `flow run`, `delivery` `not_delivered`, `retry` `safe` and no `data`. No device was opened. A step's `--policy` file that does not parse is `POLICY_INVALID` after the device is opened and before the first step, with nothing sent, as in a batch.

```json
{"v":1,"ok":true,"command":"flow run","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","delivery":"delivered_unverified","retry":"unsafe",
 "data":{"flow":"settings-search","steps":2,"ran":2,"stopped_at":null,"dry_run":false,"commit":null,
  "trace":"/home/agent/.agent-phone/traces/0a1b2c3d4e5f6a7b/2026-11-10.jsonl"}}
```

The launch had no `--wait-for`, so it proved nothing, and the run's `delivery` is the weakest of its inputs.

### Flow file

```toml
[flow]
name = "settings-search"
app = "com.android.settings"
grants = []
params = ["query"]

[[step]]
run = ["launch", "com.android.settings"]

[[step]]
expect = ["name=Search settings"]
run = ["set-text", "name=Search settings", "{query}"]
```

| Key | Type | Meaning |
| --- | --- | --- |
| `flow.name` | string | The flow's name. Required. |
| `flow.app` | string | The package the flow is for. It is for the reader: nothing checks it. |
| `flow.grants` | array of strings | The [effects](#effects) the flow may commit. Default none. |
| `flow.params` | array of strings | The names of the flow's parameters. Default none. |
| `step.run` | array of strings | The arguments of one command, as a [batch](#batch-payload) step has them. Required. |
| `step.expect` | array of strings | Queries that must all show before the step acts. Default none. |

- The CLI's own parser reads each `run`, so a step means what the same words mean on a command line, and the same gate judges it. A step must be a command that reads or drives the phone, and it may name no device.
- A target is a query, such as `name=Display`. A step that names a ref or a point is refused, because a ref belongs to one snapshot. So are `get`, `is` and `--root`, which take a ref.
- `{name}` in a word of `run` or `expect` stands for the parameter `name`. `--param name=value` must give every parameter of `params` once, and no other. A `{name}` that `params` does not list is refused, so a misspelt name is never typed as it stands. A parameter fills a value and never adds a flag: a value that starts with `-` is refused, unless its word stands after a `"--"` word in `run`, where the parser reads every word as text.
- `grants` is a cap. A step whose `--commit` names an effect outside it is refused. The flow runs only when the caller's `--commit` names every effect in `grants`, except in a dry run and in `dangerously-skip`. The caller's grant reaches no step: a step is judged under its own `--commit`, so an input that commits an effect its step did not grant is `COMMIT_REFUSED`, as in a batch.
- `--dry-run` runs every step with no grant, judged as `ask` judges. The steps that commit nothing run and send their input. The gate refuses the first step that would commit, and the run stops there.
- `expect` is waited for as `wait --for` waits, and the read it holds on is the observation the step needs. A step with no `expect` gets one snapshot first when the step before it left no observation, so a flow may start with `launch`.
- The file's rules above are checked before a device is opened, and a file that breaks one is `INVALID_ARGS`. So is an unknown key in the file.
- Text that a parameter typed is written to no trace line: a begin line of a flow has the words of the file, with `{name}` in them, and the keys `flow` and `step` after `started_utc`. Typed text can still show where the screen shows it. A snapshot prints what a field holds unless it is a password field, so the `details.after` of a later step that fails can show it, as a snapshot after `set-text` does. A parameter inside a query names something on the screen: the end line holds the query and the name it resolved to, and an error message can quote the query. So put a secret only where it is typed, and only into a password field.

### Flow record

`agent-phone flow record TRACE --out FILE` writes the draft of a flow file from a device's [trace](#command-trace) of one day, so a job an agent did by hand can be replayed. It reads that one file and opens no device, so `device` is null. A draft never replaces a file that exists, and it has mode 0600, because it holds names from the screen.

| Key | Type | Meaning |
| --- | --- | --- |
| `out` | string | The path of the draft. |
| `steps` | int | How many steps the draft has. |
| `params` | array of strings | The parameters the draft declares, one for each command that typed text: `text`, `text2` and so on. |
| `refs` | array of ints | The steps that still name a ref, because the element had no name. The draft does not load until each is named by a query. |
| `skipped` | array of ints | The `seq` of each command that was ok and is not in the draft, because its traced words do not parse. A trace hides typed text wherever it stands, so a text of one or two characters can change another word of its line. |

- Each command in the trace that sent input or waited, and was ok, is a step, with the words that were typed. `snapshot`, `find`, `get`, `is`, `clipboard get` and `screenshot`, a command that failed, a command with no end line, and the lines of a flow's own run are left out.
- A target that was named by ref becomes a query on the role and the name the ref resolved to, such as `role=button name="Display"`.
- Typed text is `<N chars>` in a trace, and becomes `{text}` in the step. So no draft holds text that was typed, and `flow run` asks for it with `--param`.
- The effects that the commands granted with `--commit` become the draft's `grants`. A commit that `dangerously-skip` let through had no `--commit`, so the draft declares no grant for it. Its dry run then fails at that step with `COMMIT_REFUSED`, which names the `--commit` to add.
- A file that is not such a trace, a trace with nothing to replay, and an `--out` that exists are `INVALID_ARGS`.

```json
{"v":1,"ok":true,"command":"flow record","permission_mode":"ask","device":null,
 "data":{"out":"settings-search.toml","steps":2,"params":["text"],"refs":[],"skipped":[]}}
```

A draft is a start. It has no `expect`, and a query on a role and a name can match two elements on another day. Read it, and try it with `--dry-run`.

## Command trace

Every command that reads or drives the phone, run by itself, appends two lines to `<state root>/traces/<serial>/<UTC date>.jsonl`: a begin line before it runs and an end line after it. The file has mode 0600 in a folder of mode 0700, like a batch's trace. A begin line with no end line is a command that died on the way. The end line is read from the command's envelope, so the two agree. `devices`, `skills` and `server` write no line, and a batch writes its own file. [`flow record`](#flow-record) drafts a flow from these lines.

#### Command begin line

| Key | Type | Meaning |
| --- | --- | --- |
| `line` | string | `begin`. |
| `seq` | int | The command's number in the file, from 0. Its end line has the same number. |
| `command` | string | The command's name, as in its envelope. |
| `argv` | array of strings | The command's arguments from the command word on, without the flag that named the device. Typed text is replaced by `<N chars>`, as in a [batch's step line](#trace-step-line). Every other word is written as given, so a link given to `open-url` is in the file. |
| `started_utc` | string | When the command started, in UTC with milliseconds. |

#### Command end line

| Key | Type | Meaning |
| --- | --- | --- |
| `line` | string | `end`. |
| `seq` | int | The `seq` of the command's begin line. |
| `permission_mode` | string | The command's `permission_mode`. |
| `ms` | int | How long the command took. |
| `ok` | bool | The command's `ok`. |
| `delivery` | string or null | The command's `delivery`, null for a read that succeeded. |
| `retry` | string or null | The command's `retry`, null when it has no `delivery`. |
| `error` | string or null | The command's error code. |
| `input` | string or null | The kind of the input that went out, from the [input kinds](#input-kinds), or null. |
| `target` | object or null | As in a [batch's step line](#trace-step-line). |
| `gate` | object or null | The verdict the input was sent under, as in the [input payload](#input-payload), or null. |

```jsonl
{"line":"begin","seq":0,"command":"snapshot","argv":["snapshot"],"started_utc":"2026-11-10T09:15:00.211Z"}
{"line":"end","seq":0,"permission_mode":"ask","ms":212,"ok":true,"delivery":null,"retry":null,"error":null,"input":null,"target":null,"gate":null}
{"line":"begin","seq":1,"command":"set-text","argv":["set-text","name=Search settings","<7 chars>"],"started_utc":"2026-11-10T09:15:03.870Z"}
{"line":"end","seq":1,"permission_mode":"ask","ms":655,"ok":true,"delivery":"delivered_verified","retry":"unsafe","error":null,"input":"set_text","target":{"ref":null,"query":"name=\"Search settings\"","role":"field","name":"Search settings"},"gate":{"verdict":"clear","reason":"not_labeled_input"}}
```

## Device reads

`clipboard get` prints `{"value": <text or null>}`, null when the clipboard holds no text. `screenshot` saves a JPEG under the state root, in `devices/<serial>/screenshots/`, readable only by the user, and prints `{"value": <path>}`. Neither sends input, so no ref changes.

## Snapshot payload

`snapshot`, `wait` and the `after` of an input all carry the same object.

| Key | Type | Meaning |
| --- | --- | --- |
| `id` | string | The snapshot id: five characters from `0123456789abcdefghjkmnpqrstvwxyz`. |
| `app` | string | The package of the window the snapshot describes. |
| `window` | string | That window's kind. See [Window kinds](#window-kinds). |
| `mode` | string | `compact`, `skeleton` or `full`. Budget fitting can turn `compact` into `skeleton`. |
| `settled` | string | See [Settle states](#settle-states). |
| `keyboard` | bool | `true` when a keyboard window is on screen. |
| `dialog` | bool | `true` when the described window does not fill the display. A window fills it when none of its edges is inset from the display's edge by more than 8% of the display's width (left and right) or height (top and bottom). A full-screen app lying between the status bar and the navigation bar, or a pixel short of the display, fills it, and a dialog whose margins are all under 8% reads as `false`. |
| `others` | array | Every other window, in dump order, as `{"id", "app", "window", "bounds", "nodes"}`. `bounds` is `[left, top, right, bottom]`, and `nodes` is the window's node count. |
| `toasts` | array of strings | Toast texts the backend saw. |
| `truncated` | int | The number of lines that budget fitting removed. |
| `tree` | array of strings | One string per line, described below. |

### Example

The Settings home fixture (`tests/fixtures/dumps/settings-home.xml`), in landscape:

```json
{"v":1,"ok":true,"command":"snapshot","permission_mode":"ask","device":"0a1b2c3d4e5f6a7b","data":{
 "id":"q7m2k","app":"com.android.settings","window":"application","mode":"compact","settled":"unchecked",
 "keyboard":false,"dialog":false,"others":[],"toasts":[],"truncated":0,
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

### Tree lines

A line holds these parts in this order, separated by one space. Only the role is always present.

1. Two spaces of indent per level. A line is indented one level under the line it belongs to.
2. The ref, `@<snapshot id>:e<N>`, on elements an agent can act on. `N` counts these elements in tree order over the whole window, so an element keeps its number in a skeleton and in a drill-down.
3. The role. See [Roles](#roles).
4. The name, in JSON string quotes.
5. The detail: the element's other labels, joined with `, ` and cut to 40 characters plus `…`.
6. `value="…"`: the text of a field or a slider. It is never printed for a secret field.
7. `#<id>`: the entry name of the resource-id, only when the name is empty.
8. States. See [States](#states).
9. `(N rows)`, or `(1 row)`, on a collection: the rows that hold at least one line.
10. `(+N)`: lines hidden under this collection by the skeleton or by budget fitting.
11. Bounds, `[left,top,right,bottom]`, in pixels of the current rotation.

The `tree` array, encoded, stays within 7,680 bytes: the 8 KB budget (`A4-1`) minus 512 bytes for the rest of the envelope. When it does not fit, fitting tries each step in order and stops at the first that fits. It drops the details, then the bounds of lines without a ref, then the rows after the first k of each collection (k halves each time), then everything inside collections. As a last resort it drops lines from the end. A collection that lost rows keeps its ref and shows `(+N)`, so the agent can drill into it with `snapshot --root`.

The tree of `--surface all` also has a line at depth 0 that opens each window: `group "<package>" "<window kind>"`, then `focused` for the active window, then the window's bounds. The windows come in dump order, which is the order of their ids, so a window's place in the tree is the id that `--window` takes. The window's own lines follow, indented one level, and the ref numbers run on across windows.

### Roles

| Role | Element |
| --- | --- |
| `button` | Anything that takes a tap and is not one of the roles below, including clickable images, texts and plain views. |
| `field` | An editable text field. |
| `checkbox` | A checkable element that is not a switch or a radio button. |
| `switch` | An on and off switch. |
| `radio` | A radio button. |
| `tab` | A tab. No class maps to it yet, so the uiautomator2 backend does not report it. |
| `slider` | A seek bar. |
| `dropdown` | A spinner. |
| `list` | A recycler, list or grid view. |
| `pager` | A view pager. |
| `scroll` | A scroll view, or any scrollable plain view. |
| `web` | A web view. |
| `image` | An image that takes no tap. |
| `text` | A text that takes no tap. |
| `progress` | A progress bar. |
| `group` | Any other view. |

### States

| State | Meaning |
| --- | --- |
| `disabled` | The element is not enabled. It still has a ref. |
| `checked` | The element is checked or on. |
| `selected` | The element is selected. |
| `focused` | The element has input focus. |
| `secret` | A password field. Its value is never printed. |
| `offscreen` | The element is not visible to the user. Only `full` mode prints such lines. |
| `lossy` | The line's text holds `..`, which may stand for a character the backend could not read. Each character above U+FFFF, such as an emoji, shows as `..`. A literal `..` is marked too, because the read cannot tell the two apart. A query matches the text as the line shows it. |

### Window kinds

| Kind | Window |
| --- | --- |
| `application` | An app's window. |
| `input_method` | The keyboard: the window of the device's default input method. |
| `system` | Android's own UI: the status bar, the notification shade, system dialogs. |
| `overlay` | A window drawn over other apps. |
| `unknown` | A window whose kind the backend cannot read. |

### Settle states

| State | Meaning |
| --- | --- |
| `settled` | Every read for 800 ms gave the same lines. |
| `unsettled` | The settle deadline passed first, and this is the last screen read. A deadline under 800 ms always ends here. |
| `unchecked` | One read, with no settle asked (`A2-5`). |
