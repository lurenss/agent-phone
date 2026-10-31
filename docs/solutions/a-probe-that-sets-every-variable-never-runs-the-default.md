---
title: A probe that sets every variable never runs the default
date: 2026-11-01
module: cli/settings.py
problem_type: runtime_error
tags: [settings, slots, dataclass, probes, defaults]
---

# A probe that sets every variable never runs the default

## What broke

`agent-phone snapshot` failed for every user who had not set `AGENT_PHONE_HOME`, with `INTERNAL: 'member_descriptor' object has no attribute 'mkdir'`. `Settings.from_environment` fell back to `Settings.state_root` when the variable was unset. `Settings` is a `slots=True` dataclass, and on such a class the attribute `Settings.state_root` is the slot's descriptor, not the field's default value.

## Why the checks missed it

The unit 2 live probe set `AGENT_PHONE_HOME` to a fresh temp folder on every run, so the default path never ran on the phone. The unit tests built `Settings` directly with a `tmp_path`, so they never called `from_environment({})`. Both checks were right about what they ran, and neither ran what a user runs.

## Rules

- Read a dataclass default from a module constant, never from the class. On a slots dataclass the class attribute is a descriptor.
- A probe or test that sets an environment variable covers the set case only. Keep one test that runs the unset case (`tests/test_settings.py`).
- When you verify a CLI on a device, run it once from a plain shell with none of the probe's variables set.
