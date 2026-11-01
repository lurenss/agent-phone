# Devices and device selection

`agent-phone devices` lists every device adb knows, with the facts read from each ready one. Every other command that drives a phone picks it from `-d`, from the ref it was given, or as the only ready device, and refuses before it sends anything when that choice fails.

## Sub-features

- `devices-list` lists every adb device, ready or not, and reads facts from each ready one.
- `devices-facts` reports the same API level, boot id, display size and density as the phone's own reads.
- `select-default` uses the only ready device when nothing names one.
- `select-flag` accepts `-d` before the command and after it.
- `select-missing` refuses a `-d` serial that is not connected with `NO_DEVICE`.
- `select-ref` takes the device from a ref, and refuses a `-d` that contradicts the ref with `WRONG_DEVICE`.
- `select-ambiguous` refuses with `DEVICE_AMBIGUOUS` when several devices are ready and nothing names one.

## How to get to it (user POV)

- Run `agent-phone devices`.
- Pass `-d <serial>` before or after a command that drives a phone.
- Pass a ref to `get`, to `is`, or to `--root`.
- In Python, call `open_phone(serial)` from `agent_phone.cli.driver`.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and exactly one device is ready, `$SERIAL`.
- No device with the serial `emulator-5554` is connected.
- The journey reads the screen that is showing and sends no input.

Steps:

- **List.** Run `evidence.py run "$RUN" devices -- agent-phone devices`. Exit code 0, `device` is `null`, and the row for `$SERIAL` has `ready` `true` with `model`, `api`, `abi`, `display`, `density`, `locale`, `ime` and `boot_id`.
- **Facts.** Run `evidence.py run "$RUN" facts-adb -- adb -s "$SERIAL" shell 'getprop ro.build.version.sdk; cat /proc/sys/kernel/random/boot_id; wm size; wm density'`. The API level and the boot id equal the `devices` row. `display` equals the override size when `wm size` prints one, else the physical size, and `density` follows the same rule.
- **Default.** Run `evidence.py run "$RUN" default -- agent-phone snapshot --skeleton`. `ok` is `true` and `device` is `$SERIAL`.
- **Flag before and after.** Run `evidence.py run "$RUN" flag-before -- agent-phone -d "$SERIAL" snapshot --skeleton` and `evidence.py run "$RUN" flag-after -- agent-phone snapshot --skeleton -d "$SERIAL"`. Both succeed with `device` `$SERIAL`.
- **Missing serial.** Run `evidence.py run "$RUN" missing -- agent-phone -d emulator-5554 snapshot`. Exit code 1, `NO_DEVICE`, `delivery` `not_delivered`, `retry` `safe`, and `details.connected` lists `$SERIAL`.
- **Ref names its device.** Run `evidence.py run "$RUN" a-ref -- agent-phone find --role button --limit 1` and take the ref that starts `matches[0]`. Run `evidence.py run "$RUN" ref-device -- agent-phone is <ref>`. It succeeds with `device` `$SERIAL` and no `-d`.
- **Contradicting flag.** Run `evidence.py run "$RUN" wrong-device -- agent-phone is <ref> -d emulator-5554`. Exit code 1, `WRONG_DEVICE`, `details.requested` is `emulator-5554` and `details.ref_device` is `$SERIAL`.
- **Several devices.** Only with a second ready device. Run `evidence.py run "$RUN" ambiguous -- agent-phone snapshot`. Exit code 1 and `DEVICE_AMBIGUOUS`, and the message names both serials.

## Gotchas

- A phone that has not accepted USB debugging is listed with `ready` `false` and no facts. Accepting the prompt is a step for the phone's owner.
- `profile` is `null` until profile files load (`docs/plan.md` unit 4). Do not assert a profile name.
- `display` is in the natural orientation, so it does not change when the phone rotates.
- `select-ambiguous` needs a second ready device, such as an emulator or the AYN Thor. With one phone, report it as skipped. `tests/test_select_device.py` covers it on fakes only.
- A ref recorded under another state root is `SNAPSHOT_NOT_FOUND`, not `WRONG_DEVICE`, because the snapshot that names the device is not in this root.
- `-d` with a ref is checked before anything is read, so `wrong-device` needs no second phone.
