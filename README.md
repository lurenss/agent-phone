<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/media/logo-dark.svg">
    <img src="docs/media/logo-light.svg" alt="agent-phone logo: a phone drawn as two brackets around one tap target" width="96">
  </picture>
</p>

# agent-phone

https://github.com/user-attachments/assets/53370492-cd75-47dc-a98f-ae2e49a225b4

*A 2-minute intro: what agent-phone does, why, and how it was tested (made 1 November 2026).*

agent-phone lets an AI agent see and operate an Android phone through its accessibility tree, over adb. It applies the design of [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop) to a phone: a snapshot returns compact JSON with a ref for every element the agent can act on, the agent acts on a ref, and it snapshots again to check. The loop stays in the agent.

It is in development. It is built for any app on any Android phone. App knowledge lives in policy data and examples, never in core. `docs/plan.md` lists the units and the check each one must pass.

## Why it is built this way

Measured on a Samsung J7 (Android 9), reading the screen with `adb shell uiautomator dump` takes about 2.4 seconds and fails while a screen animates. The same read through a uiautomator2 server that stays running takes about 160 ms. Sending a key takes 902 ms through `adb shell input` and 34 ms through the server. The rows behind these numbers are in `probes/android/FINDINGS.md`.

## Use

```bash
agent-phone devices                      # every device, with its facts
agent-phone snapshot                     # the active window as compact lines with refs
agent-phone snapshot --skeleton          # the outline: collections fold their rows into a count
agent-phone snapshot --root @k3x9q:e3    # one subtree, as a new snapshot, with the same ref numbers
agent-phone snapshot --settle            # read until the reads agree for 800 ms, and say whether they did
agent-phone snapshot --surface dialog    # a dialog, the keyboard, the shade, or every window
agent-phone find --name Wi-Fi --role button   # every match, with its ref
agent-phone get @k3x9q:e4 --property bounds   # one property of a ref, read live
agent-phone is @k3x9q:e4 --property enabled   # one boolean of a ref, read live
agent-phone server stop                  # free the phone for another tool, such as an old uiautomator dump
agent-phone skills get phone             # the usage guide for agents, as Markdown in data.content
agent-phone click @k3x9q:e4 --wait-for 'name*=Brightness'   # tap a ref and verify the tap by its effect
agent-phone set-text @k3x9q:e2 display   # write a field, then read it back
agent-phone scroll down @k3x9q:e3        # swipe a list along the way it runs
agent-phone press back                   # back, home, recents or enter
agent-phone launch com.android.settings  # also stop, open-url, rotate, clipboard get|set, screenshot
agent-phone wait --for name=Brightness   # read until a condition holds, with no sleep
agent-phone click @k3x9q:e9 --commit send   # a commit action is sent only with the effect granted
agent-phone click name=Display           # a target is a ref or a query that must match one element
agent-phone batch steps.json             # several steps in one call, with one trace of what each did
```

Each command prints one JSON object, described in `docs/json-output.md`. `-d <serial>` picks a device when several are ready, and a ref names its own device. The server on the phone starts when a command needs it and stops after 15 idle minutes. Every input goes through one pipeline. The ref must come from a snapshot taken after the last input, its element is found again on a fresh read, and the policy engine judges what the touch lands on. An input that would post, send, delete, pay, give a consent or change the system is refused unless the caller grants that effect with `--commit`, and a deny rule or a package the device profile protects refuses it whatever the grant. That is the `ask` permission mode. The person who launches the agent can set `AGENT_PHONE_PERMISSION_MODE=dangerously-skip`, and a commit then goes out with no grant while every denial still holds. The agent never sets it, and every result names the mode in `permission_mode`. Each result says whether the input was delivered, and a retry is safe only after `not_delivered`. `AGENT_PHONE_HOME`, `AGENT_PHONE_IDLE_S`, `AGENT_PHONE_LOCK_WAIT_S` and `ADB` configure the state folder, the idle limit, how long a command waits for another process to let go of the device, and the adb binary. `AGENT_PHONE_PERMISSION_MODE` is `ask` or `dangerously-skip`.

Right after something changes the screen, such as `adb shell am start`, take the next snapshot with `--settle`. A plain snapshot reads once and can show the middle of a transition (`A2-5`).

## Develop

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check .
```

`AGENTS.md` has the architecture rules, the coding standards and the phone safety rules.

## License

Apache-2.0. See `LICENSE`.
