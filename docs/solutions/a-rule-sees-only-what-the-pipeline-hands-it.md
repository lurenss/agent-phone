---
title: A rule sees only what the pipeline hands it
date: 2026-11-01
module: core/policy/engine.py
problem_type: logic_error
tags: [policy, deny-rules, act, hit-plan, consumer-files, review]
---

# A rule sees only what the pipeline hands it

## What broke

The J7's profile says that a screen showing SocksTun is a screen where "nothing on it is tapped". Unit 4 enforced that for a tap. Two reviewers then sent every other input at the same rule, and three separate gaps showed the same fault. In each one the engine was correct about what it was given, and the pipeline gave it too little.

- **No screen for most inputs.** `act()` built a `Site` for a tap and for nothing else. On SocksTun's own screen a tap was `DENIED`, while a set-text, a scroll and Enter went out. Enter was judged by its key alone, so `--commit send` also pressed a focused "Delete" button whose effect nobody granted.
- **Words that belonged to nobody.** The hit plan hands a touch to a clickable node (`takes_touch`). Label ownership stopped at any node that consumes a touch, which also counts a checkable node. A clickable row with a checkable, non-clickable child received the tap, and the child's "Delete all" or "Mobile data" was judged for nobody.
- **A consumer file that trimmed the evidence.** A denial that names effects checks the effects the engine found. A consumer's `disable`, `exempt` or `ignore` changed what the engine found on three paths: a neutral OK that takes its dialog's words, a key rule and a link-scheme rule. A one-line consumer file let the OK of "uninstall SafeTunnel?" through with no `--commit`.

## Why the checks missed it

Every earlier check planted its evidence on one path. The commit table planted each commit phrase in six places, all on a tap. The fix for withdrawn commit rules (`f526ec0`) closed the receiver's words and tested the receiver's words. Each fix was right for its path, and its test could not see a sibling path, because the test was built from the path it fixed.

## Rules

- Hand every input that lands on something the same evidence: the element's surface and the screen around it (`act/site.py`). Name each input that gets less, here back, home and recents, in the design doc with its reason.
- Name every kind of input in `reads.reads_of`, which has no default. A kind that was forgotten would read nothing and pass every deny rule, so the function ends in `assert_never`, and a test lists one input of each kind.
- Use one predicate for who receives a touch. The hit plan and the gate's label ownership both read `takes_touch`. A second predicate lets words land on nobody.
- Consumer layers may weaken a commit and never a denial. A denial reads `Policy.strict`, which keeps every commit and inherit rule that any layer loaded, and the exempt and ignore rules of trusted layers only. The same function, `effects_of`, runs on the rules in force and on `strict`, so no path gets a reading of its own.
- Test every path into the engine. `tests/test_input_sites.py` plants a deny rule's words on the element and on the screen around it, then sends a tap, a set-text, a scroll and Enter down each. A new kind of input joins that table in the same change.
- When a review finds a bypass, search for its siblings before you fix the instance. List the inputs, the rule kinds and the layers, and plant the words on each pair.
