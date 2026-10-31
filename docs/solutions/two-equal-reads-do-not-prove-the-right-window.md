---
title: Two equal reads do not prove the right window
date: 2026-11-01
module: adapters/uiautomator2/parse.py
problem_type: logic_error
tags: [settle, active-window, uiautomator2, cold-server, probes]
---

# Two equal reads do not prove the right window

## What broke

After `adb shell am start -a android.settings.WIFI_SETTINGS`, `agent-phone snapshot --settle` described the status bar and printed `settled`, in 4 of 10 runs with a cold server. The Wi-Fi window was in the dump, second, with its title (`A2-8`). The parser took the first window of the dump as the active one. A server that started after the screen last changed knows no active window. It lists windows by layer, the status bar first, and it keeps doing so until something changes.

## Why the checks missed it

Every fixture and every earlier probe read a server that had seen the screen change, where the active window comes first (`A2-7`). The first freshness runs used a server that was already up, and passed 10 of 10. Only a run with the server stopped first, which is the first call of every session, showed it. The settle rule itself was right about what it checks: two reads in a row agreed. They agreed on the wrong window.

## Rules

- `--settle` proves that a surface stopped changing. Choosing the surface is a separate job, so test both. A test for `Settled` needs a screen where the surface is wrong and stable.
- A probe that checks freshness must run with the server cold as well as warm. A cold server is the normal first call, not an edge.
- The dump has no focus attribute. Whatever the parser infers about the active window needs a live check in each server state, and a row in `FINDINGS.md` that says which states were observed.
