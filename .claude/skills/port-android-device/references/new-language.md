# Adding a language to the policy

agent-phone's gate reads the words on what an input lands on. A device whose language has no words in
`src/agent_phone/policy/default.toml` gets `LOCALE_UNSUPPORTED` for every labeled input, because the gate cannot
tell a Send from a Settings tile. Adding a language means adding its words to each rule, with tests, and having
another model and the owner check them. The words decide what counts as a commit, so they are safety data, not
copy.

## What to translate

For each rule, translate the concept, not the English word. Use the words that apps in that language actually
put on their buttons. If you are unsure, an app's own string resources and the platform's translations are the
evidence (Settings, the Play Store, the system dialogs on the device). Keep a word in its button form: the
imperative or the infinitive, whichever that language's apps use.

| Rule | Effect | Concepts |
| --- | --- | --- |
| `default.publish` | publish | share, post (as the first word of a label), publish, upload, go live, repost |
| `default.schedule` | schedule | schedule, plan for later |
| `default.send` | send | send, reply, comment, call, video call |
| `default.delete` | delete | delete, remove, discard, erase, clear all, clear data, clear storage, uninstall |
| `default.purchase` | purchase | buy, pay, purchase, subscribe (paid), donate, boost, promote, place order |
| `default.social` | social | follow, unfollow, block, report, join, subscribe or sign up (free), take part |
| `default.system` | system | airplane mode, mobile data, VPN, force stop, disable, factory reset, reset, power off, restart, USB debugging, developer options |
| `default.consent` | consent | authorize, accept, agree, allow, consent, grant access |
| `default.confirm` | confirm | confirm, submit |
| `default.consent-declined` (exempt) | none | the decline forms that contain a consent word, such as "don't allow", "do not accept" |
| `default.affirmative` (inherit) | the dialog's | ok, yes, done, continue, accept, agree, allow, apply, got it, turn off, turn on, disable, enable, stop, disconnect, remove |

Also look at what the language does that English and Italian do not:
- Compound words (German "Abonnieren" vs "abonniert"). A phrase matches whole words, so a compound needs its own
  entry.
- Gendered or polite forms that buttons use (French "Envoyer", Spanish "Enviar").
- A word that is a commit in one sense and harmless in another. The English "post" is anchored with `^` for this
  reason.

## Steps

1. Write strict-xfail tests first: a few real labels in that language, the way `tests/test_gate_words_from_the_thor.py`
   tests the Thor's labels, each with the effects it must give.
2. Add the words to each rule in `default.toml`, the language code to `languages`, and a `[[case]]` row per new
   phrase to `tests/policy/commit_table.toml` (`tests/test_commit_table.py` fails when a phrase has no row). Add
   `[[affirmative]]` rows for new affirmatives.
3. Run `uv run pytest`. `tests/test_denials_hold_against_any_consumer_rule.py` builds every one-rule consumer layer
   from the denied dialogs and must still hold, in both permission modes.
4. Have another model review the words: a pstack `interrogate` pass, or at least one fresh reviewer that gets the
   language, the concepts table and the diff, and is asked for missing commit words, false positives and decline
   forms. Fix what it finds.
5. Show the owner the word list and the review, and merge only on their yes.
6. Rerun the survey and the sweep on the device. A labeled input that was `LOCALE_UNSUPPORTED` before must now be
   judged.
