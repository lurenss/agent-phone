# Server lifetime and the device lock

agent-phone reads the screen through a uiautomator2 server on the phone. A command starts the server when it is down, a watchdog on the phone stops it after the idle limit, and `agent-phone server stop` frees the phone for another tool. One lock per device lets one process drive the phone at a time.

## Sub-features

- `server-start` starts the server detached with its watchdog, and confirms a server that already runs.
- `server-status` reports `running`, `watchdog`, `idle_limit_s` and `idle_for_s`, and does not count as use.
- `server-stop` leaves no server process, no watchdog and no `ap-lastuse` file, and a second stop also exits 0.
- `server-autostart` starts a stopped server from the first command that needs it.
- `server-idle` stops the server by itself after `AGENT_PHONE_IDLE_S` seconds without use.
- `server-frees-phone` lets another UiAutomation tool, such as `uiautomator dump`, run after a stop.
- `lock-busy` refuses a second process with `DEVICE_BUSY` and names the holder's pid.
- `lock-wait` makes a second process wait for the holder, up to `AGENT_PHONE_LOCK_WAIT_S` seconds.
- `lock-crash` frees the lock when the holder dies, with nothing to clean up.

## How to get to it (user POV)

- Run `agent-phone server start`, `agent-phone server status` and `agent-phone server stop`.
- Run any command that reads the screen, such as `agent-phone snapshot`, which starts the server.
- Set `AGENT_PHONE_IDLE_S` before a start, and `AGENT_PHONE_LOCK_WAIT_S` for a command that may wait.
- In Python, `open_phone()` holds the lock until its block ends.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and its server line says `stopped`, or `running` with a watchdog and idle.
- The journey reads the screen that is showing and sends no input.

Steps:

- **Stop.** Run `evidence.py run "$RUN" stop -- agent-phone server stop`. `data.running` and `data.watchdog` are `false`.
- **Second view of the stop.** Run `evidence.py run "$RUN" stop-adb -- adb -s "$SERIAL" shell "pgrep -f 'uia2[.]Main'; pgrep -f 'ap-watchdo[g]'; ls /data/local/tmp/ap-lastuse"`. Neither `pgrep` prints a pid, and `ls` reports no such file in `stderr` or `stdout`.
- **Stop again.** Run `evidence.py run "$RUN" stop-again -- agent-phone server stop`. Exit code 0.
- **Frees the phone.** Run `evidence.py run "$RUN" old-dump -- adb -s "$SERIAL" shell uiautomator dump /dev/null`. Its output says `UI hierchary dumped to`, which is Android's own spelling.
- **Autostart.** Run `evidence.py run "$RUN" autostart -- agent-phone snapshot`. `ok` is `true`, and the record's `ms` is about 2 to 3 s on the J7.
- **Status.** Run `evidence.py run "$RUN" status-1 -- agent-phone server status`, wait 5 s, and run `status-2` the same way. Both say `running` and `watchdog` `true` with `idle_limit_s` 900, and `idle_for_s` grew.
- **Idle stop.** Run `evidence.py run "$RUN" stop-for-idle -- agent-phone server stop`, then `evidence.py run "$RUN" start-idle --env AGENT_PHONE_IDLE_S=8 -- agent-phone server start`. `data.idle_limit_s` is 8. Poll `agent-phone server status` through `evidence.py run`, with labels `idle-1`, `idle-2` and so on, every 2 s for at most 30 s. A record shows `running` `false` within about 10 s of the start.
- **Hold the lock.** Run `uv run python -I .claude/skills/verify-agent-phone/scripts/hold_lock.py > "$RUN/holder.txt" &`. Poll `"$RUN/holder.txt"` until it has the line `held <serial> <pid>`, for at most 20 s.
- **Busy.** Run `evidence.py run "$RUN" busy --env AGENT_PHONE_LOCK_WAIT_S=0 -- agent-phone snapshot`. Exit code 1, `DEVICE_BUSY`, `delivery` `not_delivered`, `retry` `safe`, and the message names the holder's pid.
- **Crash frees it.** Run `kill <pid>` with the pid from `holder.txt`. Then `evidence.py run "$RUN" after-holder -- agent-phone snapshot` succeeds.
- **Wait.** Start the holder again and wait for its line. Start `evidence.py run "$RUN" waited -- agent-phone snapshot` in the background, wait 2 s, and `kill` the holder. The `waited` record has `ok` `true` and `ms` above 2000.

## Gotchas

- `server stop` kills any uiautomator2 server on the phone, also one that another tool started. Doctor's `stop server` line is the guard. Never run this journey past it.
- A server that another tool started has no watchdog until `agent-phone server start` runs.
- `server status` does not count as use (`A3-17`), so polling it does not keep the server alive.
- The idle stop has a few seconds of slack. File times have 1 s resolution, and a client touches the last-use file at most every limit/4 s (`A3-14`).
- `hold_lock.py` opens the phone, so it starts the server when none runs.
- The lock lives under the state root. A process with another `AGENT_PHONE_HOME` takes another lock and drives the phone at the same time.
- On the phone, write every `pgrep` pattern with a bracket, as `uia2[.]Main`. A plain pattern matches the shell that runs it (`A3-9`).
- `uiautomator dump` takes about 2 s and fails while the server runs (`A3-12`). Stop the server first.
