# AGENTS.md

Guidance for AI coding agents working in this repository.

agent-phone is a tool that AI agents call, not an agent. It is a Python CLI that reads an Android phone's accessibility tree over adb and returns JSON with refs for the elements an agent can act on. The observe, act and verify loop lives in the calling agent. agent-phone embeds no LLM and has no interactive prompt. Its design follows [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop), and its layout mirrors that repo's.

## Commands

```bash
uv sync                         # install the package and the dev tools
uv run pytest                   # every test, including the architecture and no-sleep gates
uv run ruff check               # lint
uv run ruff format --check .    # formatting
uv run agent-phone devices      # the CLI; `snapshot`, `find`, `get`, `is` and `server start|stop|status` are the other commands
probes/android/server_lifetime.sh                         # re-run a platform probe against the phone
uv run python -I probes/android/unit2_probe.py <check>    # facts, watchdog, bench, idle, concurrent, stop, foreign
uv run python -I probes/android/unit3_probe.py <check>    # windows, freshness, bench, commands (reading the screen)
uv run python -I probes/android/compare_backends.py <label>   # compare the old dump with the server dump
```

Probes touch the real phone. Read the phone safety rules below before you run one.

## Where the truth lives

- **Shipped behavior** is the code and its tests. A doc that contradicts the code is a defect. Fix it in the same change.
- **Platform evidence** is `probes/android/FINDINGS.md`. A row id such as `A2-1` is the citation form for a measurement. Code and docs may cite row ids.
- **The build plan** is `docs/plan.md`. When the plan contradicts the code, the code says what shipped. Correct the plan in place and cite the row or the source line that disproved it.
- **The decision trail** is `decisions.tsv`, one row per decision, append-only. Its format belongs to pstack's `show-me-your-work` skill.

## Architecture

```
src/agent_phone/core/       platform-neutral domain types and command logic, one folder per concept
src/agent_phone/adapters/   backends; each one translates one automation stack into core types
src/agent_phone/cli/        argument parsing and the Driver; the only place an adapter is wired to core
src/agent_phone/policy/     the built-in policy rules, shipped as package data
examples/                   consumers built on the public API, with their own policy files
skills/                     agent-facing usage docs, shipped in the package
probes/android/             phone measurements, their captures, and FINDINGS.md
docs/                       the plan, the JSON contract, and lessons from past bugs
tests/                      behavior tests and redacted golden fixtures
```

**Dependency direction.** Core never imports an adapter, the CLI, `uiautomator2`, `adbutils` or `subprocess`. Adapters never import the CLI. `tests/test_architecture.py` enforces both rules and plants violations first, so a rule that stops detecting fails the suite.

**Boundaries.** An adapter parses everything it reads from the phone into core types before returning. Core never sees XML, a uiautomator2 object or an adb string. Core trusts the types it receives and does not validate them again.

**Commands.** A command lives in `core/commands/<name>.py`, named after the command. The CLI dispatches with one `match` over the parsed command. There is no command registry.

**Design.** `docs/design/core-types.md` explains the types and the reasons behind them. Read it before you change a type in `core/`.

**Backends.** The adapter interface is the `Phone` protocol in `core/phone.py`. A second backend, such as a custom `app_process` server, is a new folder under `adapters/` and changes no command.

## Coding standards

- **No fixed sleeps.** `time.sleep` is banned by ruff's `TID251` everywhere except `core/wait/` and `probes/`. Wait on a screen condition instead. `tests/test_no_sleep_rule.py` proves the rule catches every import form.
- **400 lines at most per source file.** Split by responsibility. `tests/test_architecture.py` enforces it.
- **Domain types are frozen dataclasses. Closed vocabularies are enums.** A role, an error code and a delivery state each come from one enum, never from loose strings.
- **One concept per module.** Name a module after the concept it owns, not after the step it runs in.
- **Comments explain a non-obvious why.** The code says what. Delete a comment that restates the code.
- **Errors carry a code and a delivery disposition.** Nothing raises a bare exception across the CLI boundary. `main()` turns every error into the JSON envelope and an exit code.

## Device safety

agent-phone drives real phones with real accounts. A wrong tap can post, send or delete, and that cannot be undone.

**Core knows no app.** App names, labels and package lists never appear in `core/`. They live in policy files, device profiles, fixtures and `examples/`. A rule that only makes sense for one app is data, not code.

The framework enforces these on every device:

- Never send a commit action without the caller's explicit `--commit`. The policy engine decides what counts as a commit action from its rules. Tests never pass `--commit`.
- Never stop a package that the device profile marks as protected.
- Install nothing on the device. The only footprint is `/data/local/tmp/u2.jar` (`A3-1`) and the empty file `/data/local/tmp/ap-lastuse` that the idle watchdog reads (`A3-8`). `agent-phone server stop` removes the second.
- Only one process drives a device at a time (`A3-4`).
- Raw dumps contain private screen content. Keep them in `probes/android/raw/`, which git ignores. Commit only fixtures that pass `tests/test_fixtures_are_redacted.py`.

The development phone, Lorenzo's Samsung J7, adds these:

- SocksTun (`hev.sockstun`) is protected. Never stop it or change VPN settings. With always-on lockdown VPN, a dead tunnel takes the phone offline.
- It runs live Instagram and Business Suite accounts. Write every app a run opened on it, and every input it sent, to `decisions.tsv`.

## Commits

- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`. Write `type: imperative summary` in lowercase, and say why in the body.
- One unit of `docs/plan.md` per commit, or one coherent step inside a unit. Every commit passes `uv run pytest`, `uv run ruff check` and `uv run ruff format --check .`.
- Order commits so the history reads as an argument: the measurement before the design, the failing test before the fix.
