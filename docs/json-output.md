# JSON output

Every agent-phone command prints one JSON object, the envelope, on stdout and exits. This page is the contract for that object. `core/envelope.py` builds it from the command's `Outcome` (`core/outcome.py`), and the snapshot payload comes from `Snapshot` (`core/snapshot/snapshot.py`). `tests/test_docs.py` checks every value table below against its enum and the examples below against the code.

The envelope is UTF-8 JSON with no escaping of non-ASCII characters and no spaces between tokens. The example below is wrapped for reading.

## Envelope

| Key | Type | Present | Meaning |
| --- | --- | --- | --- |
| `v` | int | always | Contract version, `1`. |
| `ok` | bool | always | `true` when the command did what it was asked. |
| `command` | string | always | The command name, such as `snapshot` or `click`. |
| `device` | string or null | always | The adb serial the command ran against, or null when no device was chosen. |
| `delivery` | string | input commands and every error | Whether input reached the device. See [Delivery](#delivery). |
| `retry` | string | with `delivery` | `safe` when `delivery` is `not_delivered`, otherwise `unsafe`. |
| `data` | object | success, and an input that went out | The command's result. A snapshot is described in [Snapshot payload](#snapshot-payload). |
| `error` | object | failure | `code`, `message`, `hint` and `details`. |

The outcome type decides which keys appear, and no command writes `delivery` or `retry` itself:

- A read that succeeds (`Read`) has `ok: true` and `data`. It has no `delivery` and no `retry`.
- A command refused before any input left the computer (`Refused`) has `ok: false`, `error`, `delivery: not_delivered` and `retry: safe`.
- An input that was handed to the backend (`Acted`) has `data` with the action report and the observation after it, a `delivery` from its `SentState`, and `retry: unsafe`. If the input went out but the command still failed, `ok` is `false` and `error` is present as well.
- An exception that no command caught has `code: INTERNAL`. Its `delivery` is `delivery_uncertain` when this process spent an input permit that it did not refund, otherwise `not_delivered`.

The exit code is 0 when `ok` is true, 1 for an error envelope, and 2 when the arguments do not parse. The envelope is printed in all three cases.

### Error object

| Key | Type | Meaning |
| --- | --- | --- |
| `code` | string | One of the [error codes](#error-codes). |
| `message` | string | One or two sentences for the agent, naming what failed and what to use instead. |
| `hint` | string or null | A recovery step for codes whose recovery the message does not make obvious, otherwise null. |
| `details` | object | Machine-readable facts for the code, such as `reason` for `STALE_REF` or `source`, `table` and `field` for `POLICY_INVALID`. |

## Delivery

| Value | Retry | Meaning |
| --- | --- | --- |
| `not_delivered` | safe | No input left the computer, or the backend proved that nothing reached the device. Running the same command again is safe. |
| `delivery_uncertain` | unsafe | Input may have reached the device. Look at the screen before you act again. |
| `delivered_unverified` | unsafe | Input reached the device and nothing checked its effect. |
| `delivered_verified` | unsafe | Input reached the device and a wait predicate saw its effect. |

`not_delivered` is the only value after which the same command can succeed again, because every input spends the refs taken before it.

## Error codes

| Code | Meaning |
| --- | --- |
| `INVALID_ARGS` | The arguments do not parse. A ref without its snapshot id, such as `e12`, is one case. |
| `POLICY_INVALID` | A policy file, or the order its layers merge in, is invalid. `details` names the `source`, the `table` and the `field`, or the `rule`. |
| `NO_DEVICE` | No device is connected and ready, or the requested one is not. |
| `DEVICE_AMBIGUOUS` | Several devices are ready and neither `-d` nor a ref names one. |
| `WRONG_DEVICE` | The ref belongs to another device, or `-d` contradicts the device the ref names. |
| `DEVICE_BUSY` | Another process drives this device (`A3-4`). |
| `SERVER_UNAVAILABLE` | The on-device server did not answer its health check in time. |
| `NOT_SUPPORTED` | The backend cannot perform this input. |
| `SNAPSHOT_NOT_FOUND` | No stored snapshot has that id. It was never taken here, it is older than the newest 64 of its device, or it was written in a form this version cannot read. |
| `STALE_REF` | The ref cannot be trusted. `details.reason` is `spent` (input was sent after its snapshot), `rebooted` (the snapshot is from an earlier boot) or `gone` (its element is no longer on screen). |
| `OBSERVE_FIRST` | Input was sent after the device's latest snapshot, so a query or an input without a target needs a new snapshot first. |
| `AMBIGUOUS_TARGET` | More than one live element matches. `details.candidates` lists their refs when the target was a query. A ref that now matches several elements lists `details.matches`, their number. |
| `NOT_FOUND` | No element matches the query, or the snapshot has no ref with that number. |
| `NO_SURFACE` | The window asked for is not on screen. No window has input focus (the screen is off), or `--surface` finds none, or `--window` is not an id of this read. The message lists the windows that are. |
| `NOT_ACTIONABLE` | The element cannot take this input, for example because it is disabled. |
| `UNSTABLE` | The element moved between two reads. |
| `OCCLUDED` | Another window covers the point the input would land on. |
| `COMMIT_REFUSED` | The input would commit an effect that `--commit` did not grant. `details` lists the `effects`, the `granted` effects and the `evidence`. |
| `DENIED` | A deny rule forbids the input whatever the caller grants. `details` names the `rule` and its `source`. |
| `LOCALE_UNSUPPORTED` | The device language has no policy rules, so labeled input cannot be judged. |
| `TIMEOUT` | A wait reached its deadline. |
| `TRANSPORT` | adb or the server failed, or the device returned output that does not parse. |
| `ACTION_FAILED` | The input went out, and reading the screen back contradicts what was asked. |
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
| `profile` | string or null | always | The device profile that applies. It is null until profile files load. |

```json
{"v":1,"ok":true,"command":"devices","device":null,"data":{"devices":[
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
{"v":1,"ok":true,"command":"find","device":"0a1b2c3d4e5f6a7b","data":{
 "count":1,"id":"p4n8c","app":"com.android.settings","window":"application","truncated":0,
 "matches":["@p4n8c:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" focused [0,179,1920,394]"]}}
```

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
| `dialog` | bool | `true` when the described window does not cover the display. |
| `others` | array | Every other window, in dump order, as `{"id", "app", "window", "bounds", "nodes"}`. `bounds` is `[left, top, right, bottom]`, and `nodes` is the window's node count. |
| `toasts` | array of strings | Toast texts the backend saw. |
| `truncated` | int | The number of lines that budget fitting removed. |
| `tree` | array of strings | One string per line, described below. |

### Example

The Settings home fixture (`tests/fixtures/dumps/settings-home.xml`), in landscape:

```json
{"v":1,"ok":true,"command":"snapshot","device":"0a1b2c3d4e5f6a7b","data":{
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

With `--surface all`, a line at depth 0 opens each window: `group "<package>" "<window kind>"`, then `focused` for the active window and the window's bounds. The window's own lines follow, indented one level, and the ref numbers run on across windows.

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
| `settled` | Two reads in a row gave the same lines. |
| `unsettled` | The settle deadline passed first, and this is the last read. |
| `unchecked` | One read, with no settle asked (`A2-5`). |
