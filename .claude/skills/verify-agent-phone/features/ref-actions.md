# Taps, text, scrolls and keys

`agent-phone click`, `set-text` and `scroll` act on a ref from the newest snapshot, and `press` sends a key. Each finds its element again, waits out a disabled or moving one, plans a point where the touch reaches exactly that element, asks the policy engine, and sends the input once. Every input spends every ref taken before it, so a repeated input fails until the agent looks again.

## Sub-features

- `click-tile` taps a Settings tile and `--wait-for` proves the new page opened, with `delivery` `delivered_verified` and fresh refs in `after`.
- `click-back` taps the back navigation of a sub-page.
- `ref-spent` refuses a ref taken before an input with `STALE_REF` and `details.reason` `spent`, and sends nothing.
- `set-text-search` replaces the text of the Settings search field and reads it back, with no keyboard and no tap.
- `scroll-list` swipes a Settings list down and back up inside its bounds.
- `press-keys` sends back, home and recents.
- `observe-first` refuses a key with no snapshot since the last input with `OBSERVE_FIRST`.

## How to get to it (user POV)

- Run `agent-phone click <ref>`, `agent-phone set-text <ref> <text>`, `agent-phone scroll <direction> [<ref>]` and `agent-phone press <key>`, with `--wait-for`, `--wait-for-gone` and `--timeout-ms`.
- In Python, call `click`, `set_text`, `scroll` and `press` on the driver that `open_phone()` yields.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and `devices` reports `locale` `en-US`.
- Your task allows taps on the Settings home tiles named below, on the back navigation of their pages and on the Settings search, text into the Settings search field, scrolls of Settings lists, and the keys back, home and recents. Never tap a switch, a toggle, `Connections` or anything network related.
- Settings home shows. Open it with `evidence.py run "$RUN" launch --input -- agent-phone launch com.android.settings` after a snapshot, then `evidence.py run "$RUN" home -- agent-phone snapshot --settle`. `app` is `com.android.settings`.

Steps:

- **Tap a tile.** Take the ref of `button "Display"` from the `home` record. Run `evidence.py run "$RUN" display --input -- agent-phone click <ref> --wait-for 'name=Brightness'`. Exit 0, `delivery` `delivered_verified`, `data.gate.verdict` `clear`, and `data.after.tree` has `Brightness`.
- **Spent ref.** Run `evidence.py run "$RUN" spent --input -- agent-phone click <the same ref>`. Exit 1, `STALE_REF`, `details.reason` `spent`, `delivery` `not_delivered`. Then `evidence.py run "$RUN" still -- agent-phone snapshot --settle` still shows the Display page, and `evidence.py run "$RUN" focus -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'` names the same activity as before.
- **Back.** Take the ref of `button "Navigate up"` from the `still` record. Run `evidence.py run "$RUN" up --input -- agent-phone click <ref> --wait-for 'name=Display'`. `data.after` is Settings home.
- **Scroll.** Take the ref of `list #dashboard_container` from a new `snapshot --settle`. Run `evidence.py run "$RUN" down --input -- agent-phone scroll down <ref>`, `snapshot --settle`, then `evidence.py run "$RUN" up-again --input -- agent-phone scroll up <new ref>`. `data.input.from` and `data.input.to` lie inside the list's bounds, and the second snapshot shows tiles the first did not.
- **Search.** Take the ref of `button "Search"` and run `evidence.py run "$RUN" search --input -- agent-phone click <ref>`, then `snapshot --settle`. Go on only when `app` is still `com.android.settings` and a `field` line shows. Run `evidence.py run "$RUN" type --input -- agent-phone set-text <field ref> display`. `delivery` is `delivered_verified`, `data.input` is `{"kind": "set_text", "secret": false}`, and a `get <field ref> --property value` on a new snapshot says `display`.
- **Keys.** After a `snapshot`, run `evidence.py run "$RUN" back --input -- agent-phone press back`. Then `evidence.py run "$RUN" observe --input -- agent-phone press back` fails with `OBSERVE_FIRST`. After another snapshot, `press recents` and, after one more, `press home` leave the home screen showing.

## Gotchas

- The first read after a tap shows the screen before it (`A2-10`). Use `--wait-for`, or `snapshot --settle`, before you take the next ref.
- A click on a ref from a snapshot that was not settled reads the screen twice, to see the element at the same place both times. A ref from `snapshot --settle` needs one read.
- `set-text` sends no touch (`A2-12`). It fails with `STALE_REF` when no field on the device has the bounds the snapshot showed, which is the safe side.
- The `Connections` tile is `DENIED` on the J7, because its summary names airplane mode and the J7 profile denies that.
- `press enter` commits `send`. It is not part of this journey.
