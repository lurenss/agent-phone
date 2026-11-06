# Device operations

`agent-phone launch`, `stop`, `open-url` and `rotate` change what the device shows, `clipboard get` and `clipboard set` read and replace the clipboard, and `screenshot` saves the screen as evidence. Every one that changes the device is an input: it needs a current snapshot and it spends every ref taken before it.

## Sub-features

- `launch-app` starts an app's launcher screen.
- `stop-app` force-stops an app.
- `open-intent` opens a Settings page with `intent:#Intent;action=...;end`.
- `rotate-restore` locks the rotation, then hands it back as it was.
- `clipboard-roundtrip` saves the clipboard, replaces it, reads it back and restores it.
- `screenshot-file` saves a JPEG under the state root, readable only by the user.

## How to get to it (user POV)

- Run `agent-phone launch <package>`, `agent-phone stop <package>`, `agent-phone open-url <uri>`, `agent-phone rotate portrait|landscape|auto`, `agent-phone clipboard get`, `agent-phone clipboard set <text>` and `agent-phone screenshot`.
- In Python, call `launch`, `stop`, `open_uri`, `rotate`, `clipboard`, `set_clipboard` and `screenshot` on the driver.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line.
- The phone shows the home screen. Settings' main page shows a line named Settings, so from there the launch's `--wait-for 'name=Settings'` already holds and is refused.
- Your task allows launching and stopping `com.android.settings`, opening a Settings page by intent, changing the rotation and restoring it, and replacing the clipboard and restoring it. Stop and launch no other package.
- Read the rotation first: `evidence.py run "$RUN" rotation-before -- adb -s "$SERIAL" shell 'settings get system accelerometer_rotation; settings get system user_rotation'`.

Steps:

- **Launch.** After `agent-phone snapshot`, run `evidence.py run "$RUN" launch --input -- agent-phone launch com.android.settings --wait-for 'name=Settings'`. Exit 0, and `focus`, the `dumpsys window | grep mCurrentFocus` read, names `com.android.settings`.
- **Intent.** After a snapshot, run `evidence.py run "$RUN" display --input -- agent-phone open-url 'intent:#Intent;action=android.settings.DISPLAY_SETTINGS;end' --wait-for 'name=Brightness'`. `delivery` is `delivered_verified`.
- **Stop.** After a snapshot, run `evidence.py run "$RUN" stop --input -- agent-phone stop com.android.settings`. Exit 0, and the `focus` read no longer names Settings.
- **Rotate.** After a snapshot, run `rotate landscape` with `--input`. A `snapshot --settle` has landscape bounds, wider than tall. Restore what `rotation-before` said: `rotate portrait` then `rotate auto` when it said `1` and `0`. `rotation-after`, the same read, equals `rotation-before`.
- **Clipboard.** Run `evidence.py run "$RUN" clip-before -- agent-phone clipboard get` and keep `data.value`. After a snapshot, `clipboard set 'agent-phone check'` with `--input`, then `clip-check`, a `clipboard get`, says `agent-phone check`. After another snapshot, set the saved value back, and `clip-after` equals `clip-before`.
- **Screenshot.** Run `evidence.py run "$RUN" shot -- agent-phone screenshot`. `data.value` is a path under `~/.agent-phone/devices/<serial>/screenshots/`, the file is a JPEG, and its mode is `600`.

## Gotchas

- `launch` uses `monkey` with one event, which only starts the launcher activity.
- An intent may name only an action and a package. Anything else, such as a component or extras, is `INVALID_ARGS` and is never sent.
- `rotate portrait` and `rotate landscape` turn auto-rotation off. Restore it with `rotate auto` when it was on.
- A clipboard that held no text reads as `null`. Restoring it with `clipboard set ''` leaves an empty text, which is not the same. Say so in the report.
- A screenshot shows everything on screen. It stays under the state root and never goes into git.
