---
name: agent-phone
description: >
  Read and drive an Android phone through its accessibility tree, over adb, with the agent-phone
  CLI. Use when an AI agent must see an Android screen or act on it: list the connected devices,
  snapshot the active window as compact lines with refs, outline a long screen and drill into one
  list, find elements, read one property of an element, wait for a screen condition, tap, type into
  a field, scroll, press back or home, launch or stop an app, open a link or a Settings page, rotate
  the screen, read or set the clipboard, save a screenshot, or run several steps in one batch. Every input passes a commit gate, so a tap that would post, send,
  delete or pay needs the user's grant. Triggers on "android", "phone screen", "adb", "accessibility
  tree", "snapshot the phone", "tap on the phone", "agent-phone".
---

# agent-phone

agent-phone is a CLI that reads an Android phone's screen through the accessibility tree, over adb. It is a tool, not an agent. The loop of observe, act and observe again runs in you. Each command prints one JSON object on one line and exits.

agent-phone reads the screen and sends input. Every input names what it acts on by a ref from a snapshot you just took, and a policy engine refuses any input that would post, send, delete, pay or change the phone's state unless you grant that effect.

## Start here

1. Run `agent-phone devices`. Use a row with `"ready": true`. A row with `"ready": false` is a phone that is offline or has not accepted USB debugging.
2. Run `agent-phone snapshot --settle`. The first command of a session starts a server on the phone, which takes 2 to 3 s on a Samsung J7. Later commands take about 300 ms.
3. For the flags of a command, run it with `--help`, for example `agent-phone find --help`. This guide does not list every flag.

## Read the output

```json
{"v":1,"ok":true,"command":"snapshot","device":"emulator-5554","data":{
 "id":"q7m2k","app":"com.android.settings","window":"application","mode":"compact","settled":"settled",
 "keyboard":false,"dialog":false,"others":[],"toasts":[],"truncated":0,
 "tree":[
  "text \"Settings\" [63,33,277,114]",
  "@q7m2k:e1 button \"Search\" [1648,0,1775,147]",
  "@q7m2k:e3 list #dashboard_container (4 rows) [0,179,1920,1080]",
  "  @q7m2k:e4 button \"Connections\" \"Wi-Fi, Bluetooth, Data usage, Airplane m…\" focused [0,179,1920,394]"]}}
```

- On an error, `ok` is false and `error` holds `code`, `message`, `hint` and `details`. Branch on `error.code`, because the message wording can change.
- The exit code is 0 on success, 1 on an error and 2 when the arguments do not parse.
- A tree line holds, in this order, the indent, the ref, the role, the name, the detail, `value="…"`, `#<resource-id>`, the states, `(N rows)`, `(+N)` and the bounds `[left,top,right,bottom]`. Only the role is always there.
- A line with no ref is text that has nothing to act on.
- `keyboard` and `dialog` say that an overlay is up. `others` lists every other window with its `id`.

## Use refs

- A ref is `@<snapshot id>:e<N>`, such as `@q7m2k:e4`. Pass it as printed. A ref without its snapshot id, such as `e4`, is `INVALID_ARGS`.
- Each `snapshot` and each `find` records a new snapshot with a new id. A ref names the snapshot that made it, and through it the device, so a command that gets a ref needs no `-d`.
- `N` counts the elements you can act on, in tree order, over the whole window. One element keeps its `N` in the compact view, the skeleton and a `--root` drill-down of the same screen, each under its own snapshot id.
- `get` and `is` find the ref's element again on the live screen before they read it. It must be there exactly once.
- `STALE_REF` means the ref cannot be trusted. `details.reason` is `gone` when its element left the screen and `rebooted` when the phone restarted after the snapshot. Take a new snapshot and use its refs.
- `SNAPSHOT_NOT_FOUND` means the id was never recorded here, or it is older than the newest 64 snapshots of its device. Take a new snapshot.
- `AMBIGUOUS_TARGET` means several live elements match the ref. Narrow the target with `find` or drill in with `--root`.

## Outline a long screen, then drill in

```bash
agent-phone snapshot --skeleton           # a collection prints as one line: (12 rows) (+40)
agent-phone snapshot --root @k3x9q:e3     # that collection only, with the same ref numbers
```

- Start with `--skeleton` on a feed, a long list or a screen you do not know. It folds the rows of each collection into one line, with `(N rows)` and `(+N)` for the lines it hides.
- Drill into the collection you need with `--root` and its ref, then use the refs of the drill-down.
- A snapshot stays under 8 KB. When a compact view does not fit, agent-phone drops detail first and can fall back to a skeleton. `mode` says which you got, and `truncated` counts the lines it removed. A line that shows `(+N)` lost lines, and `--root` on its ref shows them.
- `--full` prints every node, including nodes with no words and nodes off screen. Use it only when the compact view lacks something you expected.

## Settle after the screen changes

A plain snapshot reads the screen once, and its `settled` is `unchecked`. Right after the screen changes, that one read can show the screen from before the change. On a Samsung J7, the first read after `adb shell am start` showed the old app in 10 of 10 tries.

- After anything changes the screen, run `agent-phone snapshot --settle`. It reads until two reads in a row print the same lines.
- `settled` means two reads agreed. `unsettled` means `--timeout-ms` passed first (3000 by default), and you got the last read. Settle again before you trust it.
- `find` reads once and takes no `--settle`. Run `agent-phone snapshot --settle` first, then `find`.

## Wait for the screen instead of sleeping

```bash
agent-phone wait --for 'name=Brightness'                         # until a line with that name shows
agent-phone wait --gone 'name=Brightness' --app com.android.settings --settled
agent-phone wait --for 'role=field name=Search' --timeout-ms 20000
```

- `wait` reads the screen until every condition holds on one read, then prints that read as a snapshot, the same object `snapshot` prints. Use it wherever you would sleep and then snapshot again.
- `--for QUERY` waits until a line that matches shows. `--gone QUERY` waits until no line matches. `--app PACKAGE` waits until the window that has focus belongs to that app. `--settled` waits until two reads in a row print the same lines. Each of `--for` and `--gone` may repeat. A query is the one `--wait-for` takes.
- Give at least one condition, or the call is `INVALID_ARGS` and nothing is read. With several, they must hold on the same read. Two conditions that hold on different reads never hold together.
- `--timeout-ms` is 10000 by default. On a timeout `ok` is false, `error.code` is `TIMEOUT`, `delivery` is `not_delivered` and `retry` is `safe`. `error.details.after` is a snapshot of the last read, so you see what the screen showed instead.
- The snapshot is recorded like any other. Its refs work for your next command, and it is the observation that the next input needs after an input: no `OBSERVE_FIRST`.
- `wait` sends nothing. It spends no refs, has no `delivery` when it succeeds, and is safe to run again.
- `--gone` holds at once for something that was never there, so wait for it to show with `--for` first. A read that shows no line, such as the blank frame between two screens, holds neither `--for` nor `--gone`.

Choose between `wait` and `--wait-for`:

- Put `--wait-for` or `--wait-for-gone` on the input when the wait is the proof that the input worked. It is one call, and `delivery` becomes `delivered_verified` when the effect appeared after the input.
- Use `wait` when no input is involved or `--wait-for` cannot say it. That covers a page that loads by itself, a dialog that closes on its own, `--app` and `--settled`, several conditions on one read, an input you sent without `--wait-for`, and a longer wait after a `--wait-for` timed out. `--wait-for` does not take `--app` or `--settled`.

## Pick the window

By default a snapshot describes the active window. That is the first window that is not the status bar, the navigation bar or the keyboard.

| Flag | Window |
| --- | --- |
| `--surface dialog` | A window that does not cover the display, such as a permission dialog |
| `--surface keyboard` | The keyboard |
| `--surface shade` | The notification shade |
| `--surface all` | Every window, each opened by a line `group "<package>" "<window kind>"` |
| `--window N` | The window that `others` lists under the id `N` |

- When `dialog` or `keyboard` is true, read that surface before the window behind it.
- A dialog over an app hides the app. The app has no lines until the dialog closes.
- `NO_SURFACE` means the window you asked for is not on screen, or the screen is off. The message lists the windows that are.
- `find` takes the same `--surface`, `--window` and `--root` flags.

## Find what you know

```bash
agent-phone find --name Wi-Fi --role button       # every match, each with its ref
agent-phone find --text bluetooth --surface dialog
agent-phone find --role button --count            # only how many, and nothing recorded
agent-phone get @p4n8c:e4 --property bounds       # one property of the element, read live
agent-phone is @p4n8c:e4 --property enabled       # one boolean of the element, read live
```

- Use `find` when you know the role, the name, a word it shows, the typed value or the resource-id. It prints a few lines where a snapshot prints the whole window.
- `--name`, `--text` and `--value` match part of the words and ignore case. `--exact` matches the whole of them.
- `find` lists up to 20 matches (`--limit`), and `count` is every match. A `count` of 0 is a success, not an error. Check `count` before you rely on one match.
- The refs in `matches` belong to the snapshot that `find` records, whose id is `data.id`.
- `get` reads `text`, `value`, `bounds` or `states`. `is` checks `visible`, `enabled`, `checked`, `focused` or `selected`. Neither records a snapshot.

## Act on a ref or a query

```bash
agent-phone snapshot --settle                                  # look first, and take the ref
agent-phone click @q7m2k:e7 --wait-for 'name=Brightness'      # tap, then wait for the effect
agent-phone click 'name=Display' --wait-for 'name*=Brightness'  # the same tap, found by a query
agent-phone set-text @r2c8w:e3 'display'                       # replace a field's text
agent-phone scroll down @r2c8w:e5                              # swipe the list; down shows what is below
agent-phone press back                                         # also home, recents and enter
```

- `click`, `set-text` and `scroll` take a TARGET. One that starts with `@` is a ref. Anything else is a query, written as `--wait-for` takes it: `name=Display`, `name*=Bright`, `role=button name=OK`, `id=dashboard_container`. A bare word such as `Display` is neither, and it is `INVALID_ARGS`.
- A query is found again on the live screen, and it must match exactly one element. Two matches are `AMBIGUOUS_TARGET`, `details.matches` counts them, and nothing is sent. No match is waited for up to `--timeout-ms`, then `NOT_FOUND`. A ref is the safer target when you have just looked, because it names the element you saw. Use a query when you cannot have looked yet, as in a batch.
- An input needs the newest snapshot of its device, whether it names a ref or a query. `press` and every other input without a target need that snapshot too. An input with no current observation fails with `OBSERVE_FIRST`. A `snapshot`, a `find` that lists matches, or a `wait` taken after the last input is that observation, and so is the `after` of an input that had a `--wait-for`.
- Before it sends anything, agent-phone finds the ref's element again, checks that it is visible, enabled and at the same place on two reads, and plans a point where the touch reaches exactly that element. A disabled or moving element is waited for up to `--timeout-ms` (5000 by default).
- `NOT_ACTIONABLE` means the element cannot take this input, such as a tap on a plain text, text into a button, or a tap on a switch that its row handles. Tap the row instead. `scroll left` and `scroll right` work only on a collection that runs across, such as a pager, a horizontal scroll view, items that sit side by side, or one card of a row with its neighbor cut off at the edge, because a sideways swipe on a row can call or dismiss. The mirror holds: `scroll up` and `scroll down` on a collection that runs across, such as the recents screen, are `NOT_ACTIONABLE` with `details.reason` `wrong_axis`, because an up or down swipe on a card can dismiss the app. Scroll left or right there. A grid, which has at least two rows of at least two items, scrolls up and down, and a lone item below side-by-side items, such as a footer, does not make a grid. A sideways swipe on a pager whose page is a list keeps to a height between the rows of that list. When the rows cover the whole height, it is refused with the same reason, because it would start on a row: tap the tab or button that switches the page instead. A collection that shows one child that fills it, and nothing else that says it runs across, reads as a list that runs down, so a sideways scroll of it is refused. `UNSTABLE` means it kept moving. `OCCLUDED` means another window, such as the keyboard, or another element covers it. A list that scrolls and is drawn over the element counts, even when the screen shows it as invisible, such as a sheet that is fading in, because a scrolling view keeps the tap at any alpha.
- `click --long` holds the touch. `set-text` replaces the whole text through the accessibility action, with no keyboard and no tap, and reads the field back.
- `--wait-for QUERY` waits until a match shows after the input, and `--wait-for-gone QUERY` until it goes. A query is `name=…`, `text=…`, `value=…`, `role=…` or `id=…`, and `^=` or `*=` match a prefix or a part. The result's `after` is a snapshot of the screen the wait ended on, with fresh refs for your next input.
- `delivery` is `delivered_verified` when the wait saw its effect appear, and `delivered_unverified` otherwise. Read the screen before you trust an unverified input.

## Grant only the commit your user asked for

```bash
agent-phone click @m9q4t:e21                    # COMMIT_REFUSED: details.effects lists "schedule"
agent-phone click @m9q4t:e21 --commit schedule  # sent, because the user asked to schedule it
```

- The engine reads every word of the element the touch lands on, its children's words and its resource-id included. A tap that would publish, schedule, send, delete, purchase, follow or block, change the system, confirm, or hit an element with no words fails with `COMMIT_REFUSED`, and nothing is sent.
- A button that does not say what it does is judged by its question as well as by its own words. "OK", "Yes", "Continue", "Confirm", "Submit", the verbs that take their object from the question ("Turn off", "Turn on", "Disable", "Enable", "Stop", "Disconnect", "Remove") and the positive button of a platform dialog, whatever its label, take the effects of the dialog around them and keep their own: "OK" under "Delete this post?" needs `--commit delete`, and "Confirm" under "Uninstall SafeTunnel?" on a phone that protects SafeTunnel is `DENIED`. A button that names its effect, such as "Send", is judged by its own words alone.
- `--commit` grants one effect for one input, such as `--commit schedule`. Grant only the effect your user asked for. A grant for `publish` does not open a `schedule` tap.
- `press enter` commits `send`. Android hands Enter to the view that has focus, so it also commits what a tap on that view would: Enter on a focused "Delete" button needs `--commit delete` too. `open-url` with a `tel:` or `sms:` link commits `send` as well.
- `DENIED` comes from a rule of the device's profile or a policy file. No flag opens it. A device profile can protect a package, and then `stop` of that package is `DENIED`. A rule that names words reads a button's question as well as the button: on a phone that denies the network, "OK" under "Turn off Wi-Fi?" is `DENIED`, and "Cancel" under it is not. A rule can also name a screen, and then a tap, `set-text`, `scroll` and `press enter` on that screen are `DENIED`. `set-text` and `scroll` commit nothing, so only a deny rule can refuse them. `press back`, `press home` and `press recents` are never refused by a rule, so you can always leave a screen.
- `--policy FILE` adds a policy file of your own, such as one that exempts a label you know only navigates. Your file can weaken a commit and never a denial: it cannot disable a deny rule of the device's profile, and it cannot hide the words that a denial reads.
- `LOCALE_UNSUPPORTED` means the phone's language has no rules, so agent-phone does not judge what it cannot read. A `--policy` file cannot add a language: the built-in vocabulary must cover one before any screen in it can be judged, and a file that declares another is `POLICY_INVALID`.

## Drive the device

```bash
agent-phone launch com.android.settings
agent-phone stop com.android.settings
agent-phone open-url 'intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end'
agent-phone open-url https://example.com --package com.android.chrome
agent-phone rotate landscape        # portrait and landscape lock it; auto hands it back to the sensor
agent-phone clipboard get
agent-phone clipboard set 'text to paste'
agent-phone screenshot              # data.value is the path of the image under the state folder
```

- `launch`, `stop`, `open-url`, `rotate` and `clipboard set` are inputs, so they spend every ref like a tap does.
- `open-url` opens a link with the VIEW action. An intent is written as `intent:#Intent;action=<action>;end`, with `package=<package>;` before `end` when one app must open it. Nothing else an intent can carry is accepted. A link that holds a line break or any other control character, written out or percent-encoded (`%0A`), is `INVALID_ARGS`, and nothing is sent.
- `clipboard get` and `screenshot` only read. A screenshot is evidence for a person and takes about a second, so leave it out of the loop.

## Send several steps in one call

```bash
agent-phone batch steps.json          # the steps in a file; with no file, or -, it reads stdin
cat steps.json | agent-phone batch
```

```json
[
  ["launch", "com.android.settings", "--wait-for", "name=Display"],
  ["click", "name=Display", "--wait-for", "name*=Brightness"],
  ["press", "back", "--wait-for", "name=Display"]
]
```

- Each step is the arguments of one command, as you would type them on the command line, without the program name. The same parser reads them, so a step means what the same words mean on a command line. A step that does not parse is `INVALID_ARGS`, and no step runs.
- A batch fits when you know the steps, and each later step finds its target by a query or after a `wait`. Every input spends the refs taken before it, so two steps with refs from one snapshot fail: the second is `STALE_REF`. Give each input a `--wait-for`, or follow it with a `wait` step, so the next step has an observation. Otherwise run one command at a time and look between them.
- Give `-d` once, on the batch. A step that names its own device is `INVALID_ARGS`. A step is a command that reads or drives the phone. It may not be `batch`, `server`, `devices` or `skills`.
- Give `--commit` and `--policy` inside the step they serve. A grant or a file in one step does not reach the next. `--commit` on the batch itself is `INVALID_ARGS`.
- The steps run in order, in one process, under one device lock. The batch stops at the first step that is not ok, and later steps do not run.
- The result is one envelope with `command` `batch`. `data.steps` holds each step's own envelope, as that command alone would print it. `data.stopped_at` is the index of the failed step, or null. `data.trace` is the path of a trace file.
- When a step fails, the batch's `error` and `delivery` are that step's. Its `retry` is `unsafe` when any earlier step sent input, because running the batch again would send that input again. Read the screen, then plan the rest as new steps.
- The trace is a JSONL file, readable only by you, with one line for each step that ran and a last line for the end. A step line has its index, its arguments, `started_utc`, `ms`, `ok`, `delivery`, `retry`, the error code, and for an input its kind, its target and its gate verdict. The text of `set-text` and `clipboard set` shows as `<N chars>`. It holds no snapshot.
- A Python caller does not need `batch`: a `Driver` from `open_phone()` already runs one step after another in one process.

## Retry only what did not reach the phone

Every error carries `delivery` and `retry`.

- `retry` is `safe` only when `delivery` is `not_delivered`. Nothing reached the phone, and you can run the same command again.
- Any other `delivery` means input may have reached the phone. Read the screen before you do anything else.
- Every input spends every ref taken before it. Running the same input again fails with `STALE_REF` and `details.reason` `spent` until you take a new snapshot, so a blind retry cannot repeat a tap. `not_delivered` is the one case after which the same command can work again.
- `delivery_uncertain` means the request went out and no answer came back. The tap may have landed.
- A batch that stops after an input went out has `retry` `unsafe`, even when its failed step sent nothing. Look at the screen before you run any step of it again.
- `DEVICE_BUSY` means another process drives the phone. Nothing was sent. Run the command again when that process is done.
- `SERVER_UNAVAILABLE` means the server on the phone did not answer, often because another tool holds the phone's one accessibility connection. Run `agent-phone server stop`, then the command again.

## Choose the device

- With one ready device, every command uses it. With several, pass `-d <serial>`, before or after the command, or pass a ref, which names its device. With neither, the command fails with `DEVICE_AMBIGUOUS`.
- `WRONG_DEVICE` means `-d` names another device than the ref does.
- `NO_DEVICE` means no device is ready. Run `agent-phone devices` to see why.
- A `devices` row also carries facts read from the phone, such as `api`, `display`, `density`, `locale` and `boot_id`.

## Mind the server on the phone

agent-phone reads the screen through a uiautomator2 server on the phone. The first command that needs the server starts it, and the server stops itself after 15 idle minutes, even with the cable out.

```bash
agent-phone server status     # running, watchdog, idle_limit_s and idle_for_s
agent-phone server start      # start it now, or confirm that it runs
agent-phone server stop       # stop it and free the phone for other tools
```

- Android allows one accessibility automation client per phone. While the server runs, `uiautomator dump`, uiautomator2 scripts and similar tools fail on that phone. Run `agent-phone server stop` when you finish, or before you hand the phone to another tool.
- `server stop` stops any uiautomator2 server on the phone, also one that another tool started.
- One process drives a phone at a time. A second command waits up to 10 s, then fails with `DEVICE_BUSY`. The lock lives in the state folder, `~/.agent-phone` by default, so processes that share a phone must share `AGENT_PHONE_HOME`.
- The state folder keeps every snapshot, which is what the screen showed. Treat it as private.
- `AGENT_PHONE_IDLE_S` sets the idle limit in seconds, `AGENT_PHONE_LOCK_WAIT_S` the lock wait, and `ADB` the adb binary.

## Print this guide

```bash
agent-phone skills list
agent-phone skills get phone      # this guide, in data.content
```

## Avoid these mistakes

1. **A plain snapshot right after a change.** It can show the screen from before the change. Use `--settle`, or `wait` for what you expect.
2. **A compact or full snapshot of a long feed.** Take `--skeleton`, then `--root` on the list you need, or use `find`.
3. **Tapping printed bounds with `adb shell input tap`.** Nothing checks that the element is still there, and a wrong tap can post, send or delete. Use `click` with a ref.
4. **Fixed sleeps.** The screen does not change on a timer. Use `wait` for the condition you expect, or `snapshot --settle` when you expect any change.
5. **Branching on `message`.** Branch on `error.code` and `retry`.
6. **Leaving the server up when you hand the phone over.** Run `agent-phone server stop`.
7. **Two state folders for one phone.** Each has its own lock, so two processes can drive the phone at once.
8. **A `--commit` your user did not ask for.** The gate exists because a wrong commit cannot be undone. Grant the one effect the user asked for, for the one input that does it.
9. **Retrying an input whose `delivery` is not `not_delivered`.** Take a snapshot and look first.
10. **A batch whose later steps use refs.** Each input spends the refs before it. Name later targets by query, and give each input a `--wait-for` or a `wait` step after it.
