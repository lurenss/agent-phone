# Find, get and is

`agent-phone find` lists the lines of a compact view that match a query, each with its ref, and records them as a snapshot of their own. `agent-phone get` reads one property of a ref on the live screen, and `agent-phone is` checks one boolean. Both find the ref's element again first and refuse when they cannot trust it.

## Sub-features

- `find-name` matches the printed name, as a part or whole with `--exact`, ignoring case.
- `find-role-count` counts the matches of a role and records nothing with `--count`.
- `find-limit` lists at most `--limit` matches, and `count` and `truncated` still say how many there are.
- `find-text-id` matches any word an element shows with `--text`, and its resource-id with `--id`.
- `find-root` searches only the subtree under a ref.
- `find-none` answers a query with no match with `count` 0 and `ok` `true`.
- `get-props` reads `text`, `value`, `bounds` and `states` live.
- `is-props` checks `visible`, `enabled`, `checked`, `focused` and `selected` live.
- `ref-bare` refuses a ref without its snapshot id with `INVALID_ARGS`.
- `ref-unknown` refuses a ref from an unknown snapshot with `SNAPSHOT_NOT_FOUND`.
- `ref-gone` refuses a ref whose element left the screen with `STALE_REF` and `details.reason` `gone`.

## How to get to it (user POV)

- Run `agent-phone find` with `--role`, `--name`, `--text`, `--value` or `--id`, and with `--exact`, `--limit`, `--count`, `--surface`, `--window` or `--root`.
- Run `agent-phone get <ref> --property <name>` and `agent-phone is <ref> --property <name>`.
- In Python, call `find`, `count`, `get` and `is_` on the driver that `open_phone()` yields.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and `devices` reports `locale` `en-US`.
- Your task allows `adb shell am start -a android.settings.SETTINGS` and `adb shell am start -a android.settings.WIFI_SETTINGS`.
- Stock Settings home shows. Open it with `evidence.py run "$RUN" open-settings --input -- adb -s "$SERIAL" shell am start -a android.settings.SETTINGS`, then `evidence.py run "$RUN" settled -- agent-phone snapshot --settle` shows `app` `com.android.settings`.

Steps:

- **Name.** Run `evidence.py run "$RUN" find-name -- agent-phone find --name connections --exact`. `count` is 1 and the one match starts with a ref and `button "Connections"`. Keep that ref as `$TILE`.
- **Bounds.** Run `evidence.py run "$RUN" get-bounds -- agent-phone get "$TILE" --property bounds`. `value` equals the bounds at the end of the match line.
- **Text.** Run `evidence.py run "$RUN" get-text -- agent-phone get "$TILE"`. `value` starts with `Connections`.
- **Booleans.** Run `agent-phone is "$TILE"`, then the same with `--property enabled` and with `--property checked`, each through `evidence.py run`. The values are `true`, `true` and `false`.
- **Count.** Run `evidence.py run "$RUN" count -- agent-phone find --role button --count`. `data` holds only `count`, and it is above 1.
- **Limit.** Run `evidence.py run "$RUN" limit -- agent-phone find --role button --limit 2`. `matches` has 2 lines and `truncated` is `count` minus 2.
- **Root.** Take the ref of the `list` line from `agent-phone snapshot --skeleton`. Run `evidence.py run "$RUN" find-root -- agent-phone find --role button --root <list ref> --count`. `count` is above 0 and at most the `count` step's.
- **None.** Run `evidence.py run "$RUN" none -- agent-phone find --name "no such element on this screen" --count`. `ok` is `true` and `count` is 0.
- **Bare ref.** Run `evidence.py run "$RUN" bare -- agent-phone get e4`. Exit code 2 and `INVALID_ARGS`.
- **Unknown snapshot.** Run `evidence.py run "$RUN" unknown -- agent-phone get @zzzzz:e1`. Exit code 1 and `SNAPSHOT_NOT_FOUND`.
- **Gone.** Run `evidence.py run "$RUN" open-wifi --input -- adb -s "$SERIAL" shell am start -a android.settings.WIFI_SETTINGS` and `evidence.py run "$RUN" wifi -- agent-phone snapshot --settle`, then `evidence.py run "$RUN" gone -- agent-phone get "$TILE"`. Exit code 1, `STALE_REF`, `details.reason` `gone`, `delivery` `not_delivered`.

## Gotchas

- `find` reads the screen once and has no `--settle`. Settle with `snapshot --settle` after a screen change, then find.
- A match is a line of the compact view. A button whose words sit in a child matches once, as the button.
- `--text` also matches the detail, the words after the name, so it finds more than `--name`.
- `--id` takes the full resource-id or the part after the slash.
- The refs in `matches` belong to the snapshot `find` records, whose id is `data.id`. `--count` records nothing, so it prints no refs.
- `get` and `is` need the element exactly once. Two live twins fail with `AMBIGUOUS_TARGET` and `details.matches`.
- A secret field has no `value`, and no query can read its text.
