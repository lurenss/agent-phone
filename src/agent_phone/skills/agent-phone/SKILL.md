---
name: agent-phone
description: >
  Read and drive an Android phone through its accessibility tree, over adb, with the agent-phone
  CLI. Use when an AI agent must see an Android screen or act on it: snapshot the active window as
  compact lines with refs, tap, type into a field, scroll, press back or home, launch an app, wait
  for a screen condition, or find elements. Every input passes a commit gate, so a tap that would
  post, send, delete or pay needs the user's grant. This is the short guide for the usual loop;
  the reference guide holds the rest. Triggers on "android", "phone screen", "adb", "accessibility
  tree", "snapshot the phone", "tap on the phone", "agent-phone".
---

# agent-phone

agent-phone is a CLI that reads an Android phone's screen through the accessibility tree, over adb, and sends input to it. It is a tool, not an agent: the loop of look, act and look again runs in you. Each command prints one JSON object on one line and exits. A policy engine refuses any input that would post, send, delete, pay or change the phone's state, unless you grant that effect.

This short guide covers the usual loop. `agent-phone skills get reference` prints the full guide, and a command run with `--help`, such as `agent-phone click --help`, lists its flags.

## The loop

```bash
agent-phone snapshot --settle --lean            # 1. look: the screen as lines, each with a ref
agent-phone click @q7m2k:e7 --settle --lean     # 2. act on a ref, and get back the screen the input ends on
agent-phone click @v9mme:e3 --settle --lean     # 3. act again, on a ref from that screen
```

1. Look first, with `agent-phone snapshot --settle --lean`. An input sent before any look fails with `OBSERVE_FIRST`.
2. Send each input with `--settle`. Its result holds `data.after`: the screen once it stopped changing, with fresh refs. That is your next look. Take no snapshot after it.
3. Take the ref for your next input from the newest screen you have. Every input spends all refs taken before it, so an older ref fails with `STALE_REF`.
4. Put `--lean` on every command. It prints the short form of the same result, which is all the loop needs.

The inputs and the reads you need most:

```bash
agent-phone click @q7m2k:e7 --settle --lean                 # tap; --long holds the touch
agent-phone set-text @r2c8w:e3 'display' --settle --lean    # replace a field's text, with no tap first and no keyboard
agent-phone scroll down @r2c8w:e5 --settle --lean           # swipe a list once; down shows what is below
agent-phone scroll down 'id=recycler_view' --until 'name=About phone' --lean   # swipe until that line shows
agent-phone press back --settle --lean                      # also home, recents and enter
agent-phone launch com.android.settings --settle --lean     # open an app
agent-phone wait --for 'name=Uploaded' --timeout-ms 30000 --lean   # wait for something slow that comes by itself
agent-phone find --name Wi-Fi --lean                        # the matching lines only, each with a ref
```

## Send two steps in one line when you know both

A turn of yours costs more time than a command. When you can name the next target before you see the next screen, because your task names it or the screen you have shows where it leads, chain the two commands with `&&`:

```bash
agent-phone launch com.android.settings --settle --lean && agent-phone click 'name=Search settings' --settle --lean
agent-phone scroll down 'id=recycler_view' --until 'name=About phone' --lean && agent-phone click 'name=About phone' --settle --lean
agent-phone press back --settle --lean && agent-phone press back --settle --lean
```

- The second command cannot use a ref, because the first one spends every ref. Name its target by a query that matches one element.
- The chain stops at the first command that fails, and each command prints its own result.
- A query that matches nothing waits `--timeout-ms` before it fails. Chain only what you are sure of. When you cannot say what the screen will show, send one input and read `after`.

## Read the output

```json
{"ok":true,"delivery":"delivered_unverified","data":{"after":{"id":"v9mme","app":"com.android.settings","settled":"settled",
  "tree":[
   "@v9mme:e1 button \"Navigate up\"",
   "@v9mme:e2 list #recycler_view (2 rows)",
   "  @v9mme:e3 button \"Dark theme\" \"Will never turn on automatically\"",
   "    @v9mme:e4 switch \"Dark theme\" checked"]}}}
```

- A `snapshot` and a `wait` print the object under `after` as their `data`.
- A tree line holds the indent, the ref, the role, the name, the detail (a second quoted text, such as a row's summary), `value="…"` for typed text, `#<resource-id>`, the states (`checked`, `focused`, `disabled`, `selected`) and `(N rows)`. A line with no ref is text you cannot act on. A switch or a checkbox that is on shows `checked`, so you need no other call to read it.
- A ref is `@<snapshot id>:e<N>`. Pass it as printed.
- `settled` is `settled` when every read for 800 ms printed the same lines. `unsettled` means the screen still changed when the time ran out: look again with `agent-phone snapshot --settle --lean` before you trust it.
- The lean form leaves out a key that holds its usual value, so a missing key means that value. `dialog: true` shows only when a dialog is the window, and then the page behind it has no lines until it closes. `keyboard: true` shows only when the keyboard is up. `set-text` needs no keyboard. `permission_mode` shows only when it is not `ask`, and `gate` only when the input committed something.
- `interruptions` shows when a pop-up you did not ask for is up, such as a permission prompt, each with `dismiss`, the ref of its safe way out. When `needs_human` is true, stop and ask your user.
- On an error, `ok` is false and `error` holds `code`, `message` and sometimes `hint`. Branch on `error.code`. The exit code is 0 for ok, 1 for an error and 2 for arguments that do not parse.
- Without `--lean` a command prints the full form: every key, each line's bounds, what was sent and where, and the gate's verdict. The reference describes it.

## Name the target

- A TARGET that starts with `@` is a ref. It names the element you saw, so prefer it after a look.
- Anything else is a query: `name=Display`, `name*=Bright` (a part), `name^=Create` (a prefix), `role=button name=OK`, `id=recycler_view`, `text=…`, `value=…`. It must match exactly one element on the live screen. Two matches are `AMBIGUOUS_TARGET`, and none is `NOT_FOUND` after the timeout.
- A row and its switch are two elements. Tap the one whose line carries the ref you mean. `NOT_ACTIONABLE` on a switch means its row takes the tap.
- What you need may be below the fold. `scroll` with `--until QUERY` swipes the list until a line that matches shows, up to 10 swipes or the end of the list, and `after` is that screen. Name the list by a query, such as the `#<resource-id>` its line prints (`id=recycler_view`), or leave the target out when one list scrolls. A ref cannot name it, because the first swipe spends it. `NOT_FOUND` means the line never showed, and `after` is where the list stopped.

## Say what you expect only when you know it

- `--settle` needs no guess, and it proves nothing: `delivery` stays `delivered_unverified`. Read `after` to see what the input did.
- `--wait-for QUERY` waits until a matching line shows after the input, and `--wait-for-gone QUERY` until it goes. Then `delivery` is `delivered_verified`. Use one when you know a line that the input will add, or with `--settle` beside it when you want both. The condition must be false before the input, or the input is refused with `INVALID_ARGS`. A condition that never shows costs the whole `--timeout-ms` (5000 by default) and ends in `TIMEOUT`, so do not guess one.
- `set-text` reads the field back by itself, and is `delivered_verified` when the field holds the text.
- Add `--after diff` to an input that changes part of a long screen. `after` then prints `added` and `gone` lines in place of `tree`.
- Never sleep. Use `--settle`, or the `wait` command with `--for`, `--gone`, `--app` or `--settled`.

## Grant only the commit your user asked for

```bash
agent-phone click @m9q4t:e21                    # COMMIT_REFUSED: details.effects lists "schedule"
agent-phone click @m9q4t:e21 --commit schedule  # sent, because the user asked to schedule it
```

- A tap that would publish, schedule, send, delete, purchase, follow or block, change the system, give a consent or confirm such a thing fails with `COMMIT_REFUSED`, and nothing is sent. `--commit` with the effect's name grants one effect for one input. Grant it only when your user asked for exactly that.
- `DENIED` comes from a rule of the device's profile. No flag opens it. `press back` and `press home` are never refused, so you can always leave a screen.
- The permission mode is `ask` or `dangerously-skip`. Your user chooses it when launching you. Never set `AGENT_PHONE_PERMISSION_MODE` yourself. In `dangerously-skip` nothing asks before a commit goes out, so act on one only when your user asked for exactly that.

## When a command fails

Every error carries `delivery` and `retry`. `retry` is `safe` only when nothing reached the phone. After any other `delivery`, look at the screen before you send anything again.

| Code | What to do |
| --- | --- |
| `OBSERVE_FIRST`, `STALE_REF`, `SNAPSHOT_NOT_FOUND` | Look again with `agent-phone snapshot --settle` and use its refs. |
| `AMBIGUOUS_TARGET`, `NOT_FOUND` | Narrow or correct the query, or use a ref. |
| `NOT_ACTIONABLE`, `OCCLUDED`, `UNSTABLE` | The element cannot take this input, something covers it, or it keeps moving. Look again. |
| `INTERRUPTED` | A pop-up is in the way. Click its `dismiss` ref when your task allows. |
| `TIMEOUT` | The input went out and its `--wait-for` did not show. `data.after` is the screen: read it. |
| `COMMIT_REFUSED`, `DENIED` | See the gate above. Do not retry with a grant your user did not give. |
| `DEVICE_AMBIGUOUS`, `NO_DEVICE` | Pass `-d <serial>`. `agent-phone devices` lists the phones. |
| `DEVICE_BUSY`, `SERVER_UNAVAILABLE` | Another process or tool holds the phone. Run the command again, or `agent-phone server stop` first. |

## More in the reference

`agent-phone skills get reference` covers what this guide leaves out: `--skeleton` and `--root` for long screens, `--surface` and `--window` for dialogs, the keyboard and the notification shade, `get` and `is`, `batch` and `flow` for several steps in one call, `open-url`, `stop`, `rotate`, the clipboard and screenshots, every refusal of the gate, and the server on the phone.
