# Several steps in one call

`agent-phone batch` runs a JSON array of steps in one process, under one device lock, and prints one envelope with each step's own envelope in `data.steps`. It stops at the first step that is not ok. It also writes one JSONL trace, so the agent can read afterwards what each step did and whether its input went out. A step finds its target by a query, because every input spends the refs taken before it.

## Sub-features

- `batch-three` runs launch, a tap by query and back in one call, each verified by its `--wait-for`.
- `batch-trace` writes one private JSONL file with a line for each step and an end line.
- `batch-query` taps the Display tile by `name=Display`, where its ref would have been spent.
- `batch-stop` stops at the first step that is not ok, runs nothing after it, and says `retry` `safe` when nothing went out.
- `batch-timing` costs less than the same steps as separate calls.
- `batch-parse` refuses a step that does not parse, names a device, or is not a command on the phone, before the phone is opened.

## How to get to it (user POV)

- Run `agent-phone batch FILE`, or pipe the steps into `agent-phone batch`. A step is an array of the arguments of one command without `agent-phone`. `-d` goes on the batch, and `--commit` and `--policy` inside the step they serve.
- A `TARGET` of `click`, `set-text` and `scroll` is a ref (it starts with `@`) or a query such as `name=Display`.
- There is no Python entry point. A `Driver` from `open_phone()` already runs steps one after another in one process.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and `devices` reports `locale` `en-US`. The titles below are English.
- Your task allows exactly these inputs: the steps `launch com.android.settings`, `click name=Display` and `press back` as one batch, run at most twice, then `press home`, then one batch of `wait --app com.android.settings --timeout-ms 100` and `press back` that must stop at its first step. No scroll, no text, no other tap. Every other command below is a read.
- The phone shows the home screen. Take `ledger.json` from `~/.agent-phone/devices/$SERIAL/` before and after a batch, to see whether an input was spent.
- If Settings opens scrolled so that the Display tile is not on screen, stop and report. Do not scroll to find it.

Steps:

- **Look first.** Run `evidence.py run "$RUN" look -- agent-phone snapshot`. It is the observation that the first launch needs.
- **Write the steps.** Save the three steps as `$RUN/three-steps.json`:

  ```json
  [
    ["launch", "com.android.settings", "--wait-for", "name=Display"],
    ["click", "name=Display", "--wait-for", "name*=Brightness"],
    ["press", "back", "--wait-for-gone", "name*=Brightness"]
  ]
  ```

  `evidence.py` reads this file and refuses a batch whose steps name a protected package, or one with no file.
- **Run it.** Run `evidence.py run "$RUN" batch --input -- agent-phone batch "$RUN/three-steps.json"`. Exit 0, `command` is `batch`, `data.stopped_at` is `null`, `data.steps` has three envelopes whose `delivery` is `delivered_verified`, and the batch's own `delivery` is `delivered_verified` with `retry` `unsafe`. The second step's `data.target.ref` is `null` and its `name` is `Display`.
- **Read the trace.** Open the file that `data.trace` names. It has three step lines and an end line with `stopped_at` `null`. Step 1's line has `input` `tap`, a `target` with the query `name="Display"`, and a `gate`. No line holds a tree. Check its mode with `stat`: the file is 600 and its folder 700.
- **Check the screen.** Run `evidence.py run "$RUN" settings-after -- agent-phone wait --for 'name=Display'`, and `evidence.py run "$RUN" focus -- adb -s "$SERIAL" shell 'dumpsys window | grep mCurrentFocus'`, which names a Settings activity.
- **Home.** Run `evidence.py run "$RUN" home --input -- agent-phone press home`, then `evidence.py run "$RUN" home-look -- agent-phone snapshot` and the focus check, which names the launcher.
- **Timing.** The `ms` of the `batch` record is the cost of the three steps as one call. To compare, run the same three steps as three calls, each `evidence.py run "$RUN" <label> --input -- agent-phone <step>` with a `snapshot` before the first, and add their `ms`. Both runs are inputs, so count them against your task's limit. Both start with the server running.
- **A batch that stops before it sends.** On the home screen, with a `snapshot` taken first, save `[["wait", "--app", "com.android.settings", "--timeout-ms", "100"], ["press", "back"]]` as `$RUN/stop-steps.json` and run `evidence.py run "$RUN" stop --input -- agent-phone batch "$RUN/stop-steps.json"`. Exit 1, `error.code` `TIMEOUT`, `data.stopped_at` `0`, `delivery` `not_delivered`, `retry` `safe`, and one envelope in `data.steps`. Its trace has one step line and an end line with `stopped_at` `0`. `ledger.json` has the same epoch as before it.
- **The refusals.** A step that does not parse never reaches the phone. Run `evidence.py run "$RUN" bad -- agent-phone batch "$RUN/bad-steps.json"` with `[["press", "back"], ["click", "Display"]]`: exit 2, `error.code` `INVALID_ARGS`, and the message names `steps[1]`. This is a read in effect, but `evidence.py` still wants `--input`, so add it only when your task allows it, and otherwise skip this step and say so.
- **Proof of the inputs.** Run `evidence.py list "$RUN"`. A batch is one input in the list. Write its steps, from the steps files, into `decisions.tsv`.

## Gotchas

- A step with no `--wait-for` leaves no observation, so a later step that needs one is refused as `OBSERVE_FIRST`. The result is still a valid envelope, but it stops there. Give each input a `--wait-for`, or follow it with a `wait` step.
- A batch's `retry` is `unsafe` when an earlier step sent, even if the failed step is `not_delivered` and safe on its own. Never run a stopped batch again without a look.
- Two refs from one snapshot cannot both be used. The second is `STALE_REF`. Use a query for every step after the first input.
- The record's `ms` includes the process start and, on a cold server, the server start. Compare warm runs, and compare calls that ran back to back.
- `evidence.py list` shows one line for a batch. The steps live in the steps file, so keep it in the run folder. Name it `<something>-steps.json`: a record is `<label>.json`, so a steps file named like a label makes `evidence.py run` refuse the label.
- The trace holds each step's arguments and the screen's words in its target. It is private. Never commit it or paste it whole.
